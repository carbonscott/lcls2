"""Configuration database client that talks to MongoDB directly with pymongo (`configdb` class).

Per the header comment, MongoDB transactions were replaced by ``session = None`` blocks, so the
`session` arguments are passed through but no transaction is used.
"""
from pymongo import *
from .typed_json import cdict
import datetime
import time, re, sys

# Note: This was originally written with mongodb transactions in mind, 
# which is why we are passing "session" all over the place.  However,
# these are really only used in three places:
#     add_alias: When we need to get a new key and then insert a new
#                record with this key.
#     modify_device: When we save a bunch of configurations, then
#                get a new key and insert a new record with this key.
#     transfer_config: After retrieving the desired configuration, we
#                get a new key and insert a new record with this key.
# Now in modify_device, it is annoying but harmless to save configurations
# and then have other saves or the insert potentially fail, leaving a
# bunch of unused configurations in the database, but we can live with this.
# 
# In these three functions, I have changed:
#     with self.client.start_session() as session:
#         with session.start_transaction():
# to:
#     if True:
#             session = None
# (Yes, the indenting is ugly, but just in case we ever decide to go back.)
#
# get_key changes to do the counter magic as well.

class configdb(object):
    """MongoDB-backed configuration database for one current hutch.

    Connects to 'mongodb://<server>', uses database `root` and its 'device_configurations'
    collection, and calls `set_hutch`; with `create`, the 'device_configurations' and 'counters'
    collections are created (errors ignored).

    Raises
    ------
    Exception
        If `root` is left at its default 'NONE'.
    """
    client = None
    cdb = None
    cfg_coll = None

    # Parameters:
    #     server - The MongoDB string: "user:password@host:port" or 
    #              "host:port" if no authentication.
    #     h      - The current hutch name.
    #     root   - The root database name, usually "configDB"
    #     drop   - If True, the root database will be dropped.
    #     create - If True, try to create the database and collections
    #              for the hutch, device configurations, and counters.
    def __init__(self, server, h=None, create=False, root="NONE"):
        if root == "NONE":
            raise Exception("configdb: Must specify root!")
        if self.client == None:
            self.client = MongoClient("mongodb://" + server)
            self.cdb = self.client.get_database(root)
            self.cfg_coll = self.cdb.device_configurations
            if create:
                try:
                    self.cdb.create_collection("device_configurations")
                except:
                    pass
                try:
                    self.cdb.create_collection("counters")
                except:
                    pass
            self.set_hutch(h, create=create)

    # Change to the specified hutch, creating it if necessary.
    def set_hutch(self, h, create=False):
        """Make `h` the current hutch (its collection, or None if `h` is None).

        With `create` and a hutch name, also create the hutch collection and a 'counters' document
        ``{'hutch': h, 'seq': -1}`` if missing; errors there are ignored.
        """
        self.hutch = h
        if h is None:
            self.hutch_coll = None
        else:
            self.hutch_coll = self.cdb[h]
        if create and h is not None:
            try:
                self.cdb.create_collection(h)
            except:
                pass
            try:
                if not self.cdb.counters.find_one({'hutch': h}):
                    self.cdb.counters.insert_one({'hutch': h, 'seq': -1})
            except:
                pass

    # Return the highest key for the specified alias, or highest + 1 for all
    # aliases in the hutch if not specified.
    def get_key(self, alias=None, hutch=None, session=None):
        """Return the highest 'key' stored for `alias`, or, if `alias` is not a string, increment the hutch's 'seq' counter and return the new value.

        Any failure is re-raised as NameError (building that message raises TypeError if `alias` or
        `hutch` is None).
        """
        if hutch is None:
            hutch = self.hutch
        try:
            if isinstance(alias, str) or (sys.version_info.major == 2 and
                                          isinstance(alias, unicode)):
                d = self.cdb[hutch].find({'alias' : alias}, session=session).sort('key', DESCENDING).limit(1)[0]
                return d['key']
            else:
                d = self.cdb.counters.find_one_and_update({'hutch': hutch},
                                                          {'$inc': {'seq': 1}},
                                                          session=session,
                                                          return_document=ReturnDocument.AFTER)
                return d['seq']
        except:
            raise NameError('Failed to get key for alias/hutch:'+alias+' '+hutch)

    # Return the current entry (with the highest key) for the specified alias.
    def get_current(self, alias, hutch=None, session=None):
        """Return the document with the highest 'key' for `alias` in the hutch collection.

        Any failure is re-raised as NameError (building that message raises TypeError if `hutch` is None).
        """
        if hutch is None:
            hc = self.hutch_coll
        else:
            hc = self.cdb[hutch]
        try:
            return hc.find({"alias": alias}, session=session).sort('key', DESCENDING).limit(1)[0]
        except:
            raise NameError('Failed to get current key for alias/hutch:'+alias+' '+hutch)


    # Create a new alias in the hutch, if it doesn't already exist.
    def add_alias(self, alias):
        """If the current hutch has no document for `alias`, insert one with a new key from `get_key`, the UTC date and an empty device list."""
        if True:
                session = None
                if self.hutch_coll.find_one({'alias': alias},
                                            session=session) is None:
                    kn = self.get_key(session=session)
                    self.hutch_coll.insert_one({
                        "date": datetime.datetime.utcnow(),
                        "alias": alias, "key": kn,
                        "devices": []}, session=session)

    # Create a new device_configuration if it doesn't already exist!
    def add_device_config(self, cfg, session=None):
        # Validate name?
        """If collection `cfg` is empty, create it and insert ``{'config': {}}`` into it and ``{'collection': cfg}`` into 'device_configurations'; otherwise do nothing."""
        if self.cdb[cfg].count_documents({}) != 0:
            return
        try:
            self.cdb.create_collection(cfg)
        except:
            pass
        self.cdb[cfg].insert_one({'config': {}}, session=session)
        self.cfg_coll.insert_one({'collection': cfg}, session=session)

    # Save a device configuration and return an object ID.  Try to find it if 
    # it already exists! Value should be a typed json dictionary.
    def save_device_config(self, cfg, value, session=None):
        """Return the '_id' of the document in collection `cfg` whose 'config' equals `value`, inserting it first if not found.

        Raises
        ------
        NameError
            If collection `cfg` has no documents.
        """
        if self.cdb[cfg].count_documents({}, session=session) == 0:
            raise NameError("save_device_config: No documents found for %s." % cfg)
        try:
            d = self.cdb[cfg].find_one({'config': value}, session=session)
            return d['_id']
        except:
            pass

        r = self.cdb[cfg].insert_one({'config': value}, session=session)
        return r.inserted_id


    # Modify the current configuration for a specific device, adding it if
    # necessary.  name is the device and value is a json dictionary for the 
    # configuration.  Return the new configuration key if successful and 
    # raise an error if we fail.
    def modify_device(self, alias, value, hutch=None):
        """Store `value` as the configuration of its 'detName:RO' device in a new alias document and return the new key.

        Copies the current document for `alias`, replaces the device's entry (collection 'detType:RO'),
        assigns a new key and UTC date, and inserts it.

        Raises
        ------
        TypeError
            If `value` (after ``typed_json()`` for a `cdict`) is not a dict.
        ValueError
            If 'detType:RO' is missing or the stored config would not change.
        NameError
            If `get_current` fails.
        """
        device = value.get('detName:RO')
        if hutch is None:
            hc = self.hutch_coll
        else:
            hc = self.cdb[hutch]
        c = self.get_current(alias, hutch)
        if c is None:
            raise NameError("modify_device: %s is not a configuration name!"
                            % alias)
        if isinstance(value, cdict):
            value = value.typed_json()
        if not isinstance(value, dict):
            raise TypeError("modify_device: value is not a dictionary!")
        if not "detType:RO" in value.keys():
            raise ValueError("modify_device: value has no detType set!")
        if True:
                session = None
                collection = value["detType:RO"]
                cfg = {'_id': self.save_device_config(collection, 
                                                      value, session),
                       'collection': collection}
                del c['_id']
                for l in c['devices']:
                    if l['device'] == device:
                        if l['configs'] == [cfg]:
                            raise ValueError("modify_device error: No config values changed.")
                        c['devices'].remove(l)
                        break
                kn = self.get_key(session=session, hutch=hutch)
                c['key'] = kn
                c['devices'].append({'device': device, 'configs': [cfg]})
                c['devices'].sort(key=lambda x: x['device'])
                c['date'] = datetime.datetime.utcnow()
                hc.insert_one(c, session=session)
        return kn
    
    # Retrieve the configuration of the device with the specified key or alias.
    # This returns a dictionary where the keys are the collection names and the 
    # values are typed JSON objects representing the device configuration(s).
    def get_configuration(self, key_or_alias, device, hutch=None):
        """Return the stored 'config' dict of `device` in the alias document with the given key (or the highest key of the given alias).

        Raises
        ------
        ValueError
            If `device` is not in that document.
        """
        if hutch is None:
            hc = self.hutch_coll
        else:
            hc = self.cdb[hutch]
        if isinstance(key_or_alias, str) or (sys.version_info.major == 2 and
                                             isinstance(key_or_alias, unicode)):
            key = self.get_key(key_or_alias, hutch)
        else:
            key = key_or_alias
        #try:
        if True:
            c = hc.find_one({"key": key})
            cfg = None
            for l in c["devices"]:
                if l['device'] == device:
                    cfg = l['configs']
                    break
            if cfg is None:
                raise ValueError("get_configuration: No device %s!" % device)
            cname = cfg[0]['collection']
            r = self.cdb[cname].find_one({"_id" : cfg[0]['_id']})
            return r['config']
        #except:
        #    return None

    # Return a list of all hutches.
    def get_hutches(self):
        """Return the 'hutch' field of every document in 'counters'."""
        return [v['hutch'] for v in self.cdb.counters.find()]

    # Return a list of all aliases in the hutch.
    def get_aliases(self, hutch=None):
        """Return the distinct 'alias' values of the hutch collection."""
        if hutch is None:
            hc = self.hutch_coll
        else:
            hc = self.cdb[hutch]
        return [v['_id'] for  v in hc.aggregate([{"$group": 
                                                  {"_id" : "$alias"}}])] 

    # Return a list of all device configurations.
    def get_device_configs(self):
        """Return the 'collection' field of every document in 'device_configurations'."""
        return [v['collection'] for v in self.cfg_coll.find()]

    # Return a list of all devices in an alias/hutch.
    def get_devices(self, key_or_alias, hutch=None):
        """Return the device names in the alias document with the given key (or the highest key of the given alias)."""
        if hutch is None:
            hc = self.hutch_coll
        else:
            hc = self.cdb[hutch]
        if isinstance(key_or_alias, str) or (sys.version_info.major == 2 and
                                             isinstance(key_or_alias, unicode)):
            key = self.get_key(key_or_alias, hutch)
        else:
            key = key_or_alias
        c = hc.find_one({"key": key})
        return [l['device'] for l in c["devices"]]

    # Print all of the configurations for the hutch.
    def print_configs(self, hutch=None):
        """Print every document of the hutch collection."""
        if hutch is None:
            hc = self.hutch_coll
        else:
            hc = self.cdb[hutch]
        for v in hc.find():
            print(v)

    # Print all of the device configurations, or all of the configurations 
    # for a specified device.
    def print_device_configs(self, name="device_configurations"):
        """Print every document of collection `name` (default 'device_configurations')."""
        for v in self.cdb[name].find():
            print(v)

    # Given a {"_id": ID, "collection": collection}, return a new one
    # changing the saved detName:RO to newname.
    def modify_name_in_config(self, cfg, newname, session=None):
        """Load the config referenced by ``{'_id', 'collection'}`` `cfg`, set its 'detName:RO' to `newname`, save it with `save_device_config`, and return the new reference dict."""
        cname = cfg['collection']
        r = self.cdb[cname].find_one({"_id": cfg['_id']},
                                     session=session)
        r['config']['detName:RO'] = newname
        return {'_id': self.save_device_config(cname, r['config'], session=session), 
                'collection': cname}

    # Transfer a configuration from another hutch to the current hutch,
    # returning the new key.
    def transfer_config(self, oldhutch, oldalias, olddevice, newalias,
                        newdevice):
        """Copy the configuration of `olddevice` at the highest key of `oldalias` in `oldhutch` to `newdevice` under `newalias` in the current hutch, and return the new key.

        If `newdevice` already exists there with a different collection, ValueError is raised; if it
        exists with the same collection, the comparison uses the undefined name `cfgs` and raises
        NameError. The name in the copied config is changed when the device names differ.
        """
        k = self.get_key(oldalias, oldhutch)
        pipeline = [
            {"$unwind": "$devices"},
            {"$match": {'key': k, 'devices.device': olddevice}}
        ]
        cfg = next(self.cdb[oldhutch].aggregate(pipeline))['devices']['configs']
        cnew = self.get_current(newalias)
        if True:
                session = None
                kn = self.get_key(session=session)
                cnew['key'] = kn
                del cnew['_id']
                for l in cnew['devices']:
                    if l['device'] == newdevice:
                        if l['configs'][0]['collection'] != cfg[0]['collection']:
                            raise ValueError("transfer_config: Different collections!")
                        if l['configs'] == cfgs:
                            raise ValueError("transfer_config: No change!")
                        cnew['devices'].remove(l)
                        break
                # cfg points to the old name, so change it if necessary.
                if olddevice != newdevice:
                    cfg = [self.modify_name_in_config(cfg[0], newdevice, session=session)]
                cnew['devices'].append({'device': newdevice, 'configs': cfg})
                cnew['devices'].sort(key=lambda x: x['device'])
                cnew['date'] = datetime.datetime.utcnow()
                self.hutch_coll.insert_one(cnew, session=session)
        return kn

    # Get the history of the device configuration for the variables 
    # in plist.  The variables are dot-separated names with the first
    # component being the the device configuration name.
    def get_history(self, alias, device, plist, hutch=None):
        """Return, for every alias document containing `device` (in key order), a dict with 'date', 'key' and the value of each dotted name in `plist` from that device's config."""
        if hutch is None:
            hc = self.hutch_coll
        else:
            hc = self.cdb[hutch]
        pipeline = [
            {"$unwind": "$devices"},
            {"$match": {'alias': alias, 'devices.device': device}},
            {"$sort":  {'key': ASCENDING}}
        ]
        l = []
        for c in list(hc.aggregate(pipeline)):
            d = {'date': c['date'], 'key': c['key']}
            cfg = c['devices']['configs'][0]
            r = self.cdb[cfg['collection']].find_one({"_id" : cfg["_id"]})
            cl = cdict(r['config'])
            for p in plist:
                d[p] = cl.get(p)
            l.append(d)
        return l

    """
    # Untested, but might be useful.
    def rename_hutch(self, hutch, newname):
        all = self.get_hutches()
        if hutch not in all:
            raise ValueError("rename_hutch: %s is not a hutch!" % hutch)
        if newname in all:
            raise ValueError("rename_hutch: %s is already a hutch!" % newname)
        d = self.cdb.counters.find_one_and_update({'hutch': hutch},
                                                  {'$set': {'hutch': newname}},
                                                  session=session,
                                                  return_document=ReturnDocument.AFTER)
        self.cdb[hutch].rename(newname)
        if self.hutch == hutch:
            self.hutch = newname
            self.hutch_coll = self.cdb[newname]
        
    # Untested, but might be useful.
    def rename_alias(self, alias, newname, hutch=None):
        all = self.get_aliases(hutch)
        if hutch not in all:
            raise ValueError("rename_alias: %s is not a hutch!" % alias)
        if newname in all:
            raise ValueError("rename_alias: %s is already a hutch!" % newname)
        if hutch is None:
            hc = self.hutch_coll
        else:
            hc = self.cdb[hutch]
        for l in hc.find({"alias": alias}):
            d = hc.find_one_and_update({'alias': alias, 'key': l['key']},
                                       {'$set': {'alias': newname}},
                                       session=session,
                                       return_document=ReturnDocument.AFTER)
    """

    # cfg is a dict of the form: {'collection': cname, '_id': id}.
    # If no one is using this entry, delete it.  Leaving this blank,
    # because it seems like an excessive amount of effort.
    def remove_orphan(self, cfg):
        """Does nothing (stub); the comment says it was meant to delete unused config entries."""
        pass

    def modify_device_name(self, device, newname, alias, hutch=None):
        """Rename `device` to `newname` (or remove it if `newname` is None) in every document of `alias`, updating the stored config's 'detName:RO' when renaming.

        Raises
        ------
        ValueError
            If no document of `alias` contains `device`.
        """
        if hutch is None:
            hc = self.hutch_coll
        else:
            hc = self.cdb[hutch]
        if True:
                session = None
                cs = []
                for c in hc.find({"alias": alias}):
                    found = False
                    for l in c['devices']:
                        if l['device'] == device:
                            found = True
                            break
                    if not found:
                        continue
                    # l points to our device.
                    # Now, we need to fix up c['devices'].
                    oldcfg = l['configs'][0]
                    if newname is None:
                        # Removing, just take it out!
                        c['devices'].remove(l)
                    else:
                        # Renaming.
                        l['device'] = newname
                        l['configs'] = [self.modify_name_in_config(oldcfg, newname, session=session)]
                    cs.append(oldcfg)
                    d = hc.find_one_and_update({"alias": alias, "key": c['key']},
                                               {'$set': {'devices': c['devices']}},
                                               session=session,
                                               return_document=ReturnDocument.AFTER)
                if len(cs) == 0:
                    raise ValueError("%s_device: cannot find device %s in hutch %s, alias %s"
                                     % ("remove" if newname is None else "rename",
                                        device, self.hutch if hutch is None else hutch, alias))
                for c in cs:
                    self.remove_orphan(c)

    def rename_device(self, device, newname, alias, hutch=None):
        """Return ``modify_device_name(device, newname, alias, hutch)``."""
        return self.modify_device_name(device, newname, alias, hutch)

    def remove_device(self, device, alias, hutch=None):
        """Return ``modify_device_name(device, None, alias, hutch)``, which removes `device` from every document of `alias` that lists it."""
        return self.modify_device_name(device, None, alias, hutch)
            
