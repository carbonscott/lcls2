"""Read detector configurations from the config database for the DAQ, merging referenced and serial-number configurations and removing ':RO' from key names."""
import psdaq.configdb.configdb as cdb
import json

#import pprint

def get_serno(connect_info, detname):
    """Lookup a serial number for a detector given current DAQ status."""

    for level in ('drp', 'tpr'):
        if level in connect_info['body']:
            for _, item in connect_info['body'][level].items():
                if item.get('proc_info', {}).get('alias') == detname:
                    # We will pass around serial numbers in connect_info
                    # These are truncated hashes of the full serial number to make
                    # it easier to read. They also include the det type
                    # E.g. f"{det_type}_{short_hash}"
                    return item.get('connect_info', {}).get('short_sn_id')

# json2xtc conversion depends on these being present with ':RO'
# (and the :RO does not appear in the xtc names)
leave_alone = ['detName:RO','detType:RO','detId:RO','doc:RO','alg:RO','version:RO']

def remove_read_only(cfg):
    # be careful here: iterating recursively over dictionaries
    # while deleting items can produce strange effects (which we
    # need to do to effectively "rename" the keys without ":RO"). So
    # create a new dict, unfortunately.
    """Return a copy of nested dict `cfg` with ':RO' removed from every key, except the keys in `leave_alone` (e.g. 'detName:RO').

    The module comment says json2xtc needs those keys to keep ':RO'.
    """
    new = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            v = remove_read_only(v)
        if k in leave_alone:
            new[k] = v
        else:
            new[k.replace(':RO', '')] = v
    return new

def update_config(src, dst, verbose=False, pfx=None):
    """Copy values from `src` into `dst` for keys present in both, recursing into dicts, and return `dst`.

    Keys ending in ':RO' and anything under a ':types:' prefix keep the `dst` value; keys only in
    `src` are skipped. With `verbose`, missing keys and changes are printed.
    """
    for k, v in src.items():
        if k not in dst:
            if verbose:
                print(f'key {k} not found in dst dict')
            continue
        if isinstance(v, dict):
            v = update_config(v, dst[k], verbose, k if pfx is None else f'{pfx}.{k}')
        if (pfx is not None and pfx.startswith(':types:')) or k.endswith(':RO'):
            # Keep the value that is in dst
            if verbose and v != dst[k]:
                print('Changed:', f'{k}:' if pfx is None else f'{pfx}.{k}:', f'{v} -> {dst[k]}')
        else:
            # Keep the value that is in src
            if verbose and v != dst[k]:
                print('Changed:', f'{k}:' if pfx is None else f'{pfx}.{k}:', f'{dst[k]} -> {v}')
            dst[k] = v
    return dst

# this interface requires the detector segment
def get_config(connect_json,cfgtype,detname,detsegm):

    """Return the configuration of '<detname>_<detsegm>' for alias `cfgtype`, using the instrument and database named in the connect JSON.

    If the configuration has a true 'use_serial_db' and `get_serno` finds a serial-number id other
    than '-', the configuration '<serno>_<detsegm>' from instrument 'det' is merged into it with
    `update_config`; any error there is printed and ignored.

    Parameters
    ----------
    connect_json : str
        Connect message; body.control.'0'.control_info gives 'instrument' and 'cfg_dbase'
        ('<url>/<db_name>').
    cfgtype : str
        Configuration alias, e.g. 'BEAM'.
    detname : str
        Detector name.
    detsegm : int
        Detector segment.
    """
    connect_info = json.loads(connect_json)
    control_info = connect_info['body']['control']['0']['control_info']
    instrument = control_info['instrument']
    cfg_dbase = control_info['cfg_dbase'].rsplit('/', 1)
    db_url = cfg_dbase[0]
    db_name =cfg_dbase[1]

    cfg = get_config_with_params(db_url, instrument, db_name, cfgtype, detname+'_%d'%detsegm)

    final_cfg = cfg
    if cfg.get('use_serial_db', False):
        serno = get_serno(connect_info, detname)
        # Check for placeholder... brittle if placeholder changes
        if serno and serno != '-':
            sn_detname = f"{serno}_{detsegm}"
            try:
                # Special `det` database has seriial number lookups
                serno_instrument = "det"
                cfg_sn = get_config_with_params(db_url, serno_instrument, db_name, cfgtype, sn_detname)
                final_cfg = update_config(cfg_sn, final_cfg)
            except:
                print("Unable to retrieve serial number config for:", sn_detname)
    return final_cfg

def get_config_with_params(db_url, instrument, db_name, cfgtype, detname):
    """Read the configuration of `detname` for alias `cfgtype`, merge it with its '_cfgTypeRef' configuration if it has one, and return it with ':RO' removed from key names.

    When merging, the requested configuration's values replace the referenced one's for keys
    present in both (`update_config`), and the referenced configuration is used.

    Raises
    ------
    ValueError
        If a configuration is None, '_cfgTypeRef' equals `cfgtype`, or the two configurations'
        'alg:RO'/'version:RO' differ.
    """
    create = False
    mycdb = cdb.configdb(db_url, instrument, create, db_name)
    cfg = mycdb.get_configuration(cfgtype, detname)

    if cfg is None: raise ValueError('Config for instrument/detname %s/%s not found. dbase url: %s, db_name: %s, config_style: %s'%(instrument,detname,db_url,db_name,cfgtype))

    if '_cfgTypeRef' in cfg.keys():

        if cfg['_cfgTypeRef'] == cfgtype:
            raise ValueError('A configuration cannot be self-relative: _cfgTypeRef is %s'%(cfgtype))

        # Replace values (and add k,v) in the referenced config with those of the requested config
        # and return the combined config
        ref = mycdb.get_configuration(cfg['_cfgTypeRef'], detname)
        if ref is None:
            raise ValueError('Reference config for instrument/detname %s/%s not found. dbase url: %s, db_name: %s, config_style: %s'%(instrument,detname,db_url,db_name,cfg['_cfgTypeRef']))
        if cfg['alg:RO']['version:RO'] != ref['alg:RO']['version:RO']: # Require the version numbers to be the same
            raise ValueError('%s and %s configs for instrument/detname %s/%s must have matching alg version numbers: got %s vs %s'%
                             (cfgtype, cfg['_cfgTypeRef'], instrument, detname,
                              cfg['alg:RO']['version:RO'], ref['alg:RO']['version:RO']))
        cfg = update_config(cfg, ref)
        #print('*** final config')
        #pp = pprint.PrettyPrinter()
        #pp.pprint(cfg)
        #print('*** end')

    cfg_no_RO_names = remove_read_only(cfg)

    return cfg_no_RO_names

def get_config_json(*args):
    """Return ``json.dumps(get_config(*args))``."""
    return json.dumps(get_config(*args))

def get_config_json_with_params(*args):
    """Return ``json.dumps(get_config_with_params(*args))``."""
    return json.dumps(get_config_with_params(*args))

