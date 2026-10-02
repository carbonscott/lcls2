"""Build, validate and write typed JSON configuration dictionaries (`cdict`), and read or update values in them.

The long comment at the top of this file describes the dictionary format and the public API.
"""
import numpy as np
import numbers
import re

#
# The goal here is to assist the writing of JSON files from python.  The 
# assumption here is that we pass in a dictionary, the keys being the names,
# and the values being one of the following:
#     - A length two tuple, representing a scalar: ("TYPESTRING", VALUE)
#     - A dictionary, representing a hierarchical name space.
#     - A numpy array.
#     - A list of dictionaries.
#
# Names with ":RO" appended are "readonly" and are not displayed/modified
# by the graphical configuration editor. They are either set by the python
# script which creates the object (e.g. the alg/version field) or by the
# drp (e.g. the serialnumber/detid field).
#
# Furthermore, the dictionary must contain a few additional keys with specific
# value types:
#     - "detType" maps to a str.
#     - "detName" maps to a str.
#     - "detId" maps to a str.
#     - "doc" is optional, but if present maps to a str.
#     - "alg" is optional, but if present maps to a dictionary.  The keys of 
#       this dictionary are:
#         - "alg" which maps to a str.
#         - "doc" which is optional, but if present maps to a str.
#         - "version" which maps to a list of three integers.
#
# This file has several external APIs:
#      validate_typed_json(d, edef={}) checks if the above rules are followed
#      for dictionary d, with a dictionary of enum definitions edef and returns
#      True/False.
#
#      write_typed_json(filename_or_fd, d) writes the dictionary d as JSON 
#      to the given filename (or file descriptor).
#
#      class cdict is a helper class for building typed JSON dictionaries.
#          cdict(old_cdict) - The constructor optionally takes an old cdict to clone.
#          set(name, value, type="INT32", override=False, append=False)
#                           - This routine is the heart of the class.  It 
#                             traverses the name hierarchy to set a new value.
#                             The value maybe a numeric value, a list of numeric
#                             values, a numpy array, a clist, or a list of 
#                             clists.  For numeric values or lists of numeric 
#                             values, type indicates the desired type of a new
#                             attribute.  For a clist or list of clists, append
#                             indicates if the target should be overwritten or
#                             the new clists appended to an existing list.  In
#                             general, once a name is typed, setting a new value
#                             will not change the type unless the override flag
#                             is True.  There is no return value.  set raises
#                             exceptions in cas of problems.  The contents of
#                             a clist are copied, but any ndarrays are not.  
#                             (Therefore, modifying a clist after assigning it
#                             to a name does not change the assigned value, but
#                             modifying the contents of an ndarray does.)
#
#          setInfo(detType=None, detName=None, detSegm=None, detId=None, doc=None)
#                           - Sets the additional information for a top-level
#                             clist.
#          setAlg(alg, version=[0,0,0], doc="")
#                           - Set the algorithm information.
#          writeFile(filename)
#                           - Write the typed JSON to a file.
#
# The following routines work on typed JSON dictionaries, or a dictionary
# that maps strings to typed JSON dictionaries, such as those returned from
# configdb.
#      getValue(dict, name)
#          - Given a dictionary, retrieve the value of the fully-dotted name.
#      getType(dict, name)
#          - Given a dictionary, retrieve the type of the fully-dotted name.
#            This will be either:
#                - A string representing a basic type.
#                - A dictionary representing an enum type.
#                - A list, the first element of which is one of the two above
#                  elements and the remainder of which is integer array
#                  dimensions.
#      updateValue(dict, name, string_value)
#          - Given a dictionary, set the element specified by name to the
#            value in string_value.  Array values will be space-separated.
#            This routine returns an integer:
#                0 if successful.
#                1 if the path does not exist.
#                2 if the type conversion failed
#                3 if typed JSON dictionary is somehow malformed.

typerange = {
    "UINT8"   : (0, 2**8 - 1), 
    "UINT16"  : (0, 2**16 - 1),
    "UINT32"  : (0, 2**32 - 1),
    "UINT64"  : (0, 2**64 - 1),
    "INT8"    : (-2**7, 2**7 - 1), 
    "INT16"   : (-2**15, 2**15 - 1), 
    "INT32"   : (-2**31, 2**31 - 1), 
    "INT64"   : (-2**63, 2**63 - 1), 
    "FLOAT"   : None,
    "DOUBLE"  : None,
    "CHARSTR" : None,
}

typedict = {
    "UINT8"   : "uint8", 
    "UINT16"  : "uint16", 
    "UINT32"  : "uint32", 
    "UINT64"  : "uint64", 
    "INT8"    : "int8", 
    "INT16"   : "int16", 
    "INT32"   : "int32", 
    "INT64"   : "int64", 
    "FLOAT"   : "float32", 
    "DOUBLE"  : "float64",
    "CHARSTR" : "str",
}

nptypedict = {
    np.dtype("uint8")  : ("UINT8",  False),
    np.dtype("uint16") : ("UINT16", False),
    np.dtype("uint32") : ("UINT32", False),
    np.dtype("uint64") : ("UINT64", False),
    np.dtype("int8")   : ("INT8",   False),
    np.dtype("int16")  : ("INT16",  False),
    np.dtype("int32")  : ("INT32",  False),
    np.dtype("int64")  : ("INT64",  False),
    np.dtype("float32"): ("FLOAT",  True),
    np.dtype("float64"): ("DOUBLE", True)
}

def namify(l):
    """Join the path elements of `l` with '.', converting non-str elements with ``str``."""
    s = ""
    for v in l:
        if isinstance(v, str):
            if s == "":
                s = v
            else:
                s = s + "." + v
        else:
            s = s + "." + str(v)
    return s

def splitname(name):
    """Split dotted `name` into a list, turning components that start with a digit into ints; return None if such a component is not an integer."""
    n = name.split(".")
    r = []
    for nn in n:
        if nn[0].isdigit():
            try:
                r.append(int(nn))
            except:
                return None
        else:
            r.append(nn)
    return r

def pythonizeName(name):
    """Rewrite dotted `name` with integer components appended as '_<n>' (e.g. 'b.0.c' becomes 'b_0.c')."""
    n = splitname(name)
    r = n[0]
    for i in n[1:]:
        if isinstance(i, int):
            r += "_" + str(i)
        else:
            r += "." + i
    return r

#
# Return None for a valid dictionary and an error string otherwise.
#
def validate_typed_json(d, edef={}, top=[], headers=True):
    """Return None if `d` follows the typed JSON rules, else an error string.

    At the top level (empty `top`) with `headers`, 'detType:RO', 'detName:RO' and 'detId:RO' must be
    strings and 'doc:RO'/'alg:RO' well formed; values must be dicts, lists of dicts, numpy arrays or
    (type, value) tuples whose type is in `typerange` or `edef`, with integer values in range.
    """
    if not isinstance(d, dict):
        return "Not a dictionary"
    k = list(d.keys())
    if len(top) == 0:
        for f in ["detType:RO", "detName:RO", "detId:RO"]:
            if headers and (not f in k or not isinstance(d[f], str)):
                return "No valid " + f
            if f in k:
                k.remove(f)
        if "doc:RO" in k:
            if headers and not isinstance(d["doc:RO"], str):
                return "No valid doc"
            k.remove("doc:RO")
        if "alg:RO" in k:
            if headers:
                a = d["alg:RO"]
                if not isinstance(a, dict):
                    return "alg is not a dictionary"
                ak = a.keys()
                if not "alg:RO" in ak or not isinstance(a["alg:RO"], str):
                    return "alg has no valid alg"
                if "doc:RO" in ak and not isinstance(a["doc:RO"], str):
                    return "alg has no valid doc"
                if not "version:RO" in ak or not isinstance(a["version:RO"], list) or len(a["version:RO"]) != 3:
                    return "alg has no valid version"
                # Do we want to check if the three elements are integers?!?
            k.remove("alg:RO")
    for n in k:
        v = d[n]
        if isinstance(v, dict):
            r = validate_typed_json(v, edef, top + [n])
            if r is not None:
                return r
        elif isinstance(v, list):
            for (nn, dd) in enumerate(v):
                if not isinstance(dd, dict):
                    return namify(top + [n, nn]) + " is not a dict"
                r = validate_typed_json(dd, edef, top + [str(nn)])
                if r is not None:
                    return r
        elif isinstance(v, tuple):
            if len(v) != 2:
                return namify(top + [n]) + " should have len 2"
            if v[0] in edef.keys() and (isinstance(v[1], numbers.Number) or isinstance(v[1], np.ndarray)):
                return None
            if not v[0] in typerange.keys() and not v[0] in edef.keys():
                return namify(top + [n]) + " has invalid type " + str(v[0])
            vv = typerange[v[0]]
            if vv is None:
                if v[0] != "CHARSTR" and not isinstance(v[1], numbers.Number):
                    return namify(top + [n]) + " value is not a number"
            else:
                if not isinstance(v[1], int):
                    return namify(top + [n]) + n + " value is not an int"
                if v[1] < vv[0] or v[1] > vv[1]:
                    return namify(top + [n]) + n + " is out of range"
        elif isinstance(v, np.ndarray):
            pass
        else:
            return namify(top + [n]) + " is invalid"
        return None

def write_json_dict(f, d, edef, tdict, top=[], indent="    ", **hw):
    """Write the entries of `d` as JSON text to file `f` and record their types in `tdict`.

    If ``hw['headers']`` is False the header keys ('detType:RO', ..., 'alg:RO') are left out. Values
    are written according to their kind (str, dict, list, (type, value) tuple, numpy array, enum int).
    """
    prefix = indent
    k = list(d.keys())
    try:
        if not hw['headers']:
            for ff in ["detType:RO", "detName:RO", "detId:RO", "doc:RO", "alg:RO"]:
                try: 
                    k.remove(ff)
                except:
                    pass
    except:
        pass
    for n in k:
        v = d[n]
        if isinstance(v, str):
            f.write('%s"%s": "%s"' % (prefix, n, v))
        elif isinstance(v, dict):
            if n == "alg:RO":
                try:
                    doc = v["doc:RO"]
                except:
                    doc = ""
                vinfo = v["version:RO"]
                f.write('%s"alg:RO": {"alg:RO": "%s", "doc:RO": "%s", "version:RO": [%d, %d, %d] }' %
                        (prefix, v["alg:RO"], v["doc:RO"], vinfo[0], vinfo[1], vinfo[2]))
            else:
                f.write('%s"%s": {\n' % (prefix, n))
                tdict0 = {}
                write_json_dict(f, v, edef, tdict0, top + [n], indent + "    ")
                f.write('\n%s}' % indent)
                tdict[n] = tdict0
        elif isinstance(v, list):
            if isinstance(v[0], dict):
                f.write('%s"%s": [\n' % (prefix, n))
                tdict0 = {}
                for (nn, dd) in enumerate(v):
                    if nn != 0:
                        f.write(',\n')
                    f.write('%s    {\n' % indent)
                    write_json_dict(f, dd, edef, tdict0, top + [n, nn], indent + "        ")
                    f.write('\n%s    }' % indent)
                f.write('\n%s]' % indent)
                tdict[n] = tdict0
            else:
                # We must be writing type information
                f.write('%s"%s": ["%s"' % (prefix, n, v[0]))
                for nn in range(1, len(v)):
                    f.write(', %d' % v[nn])
                f.write(']')
        elif isinstance(v, tuple):
            if v[0] in edef.keys():
                if isinstance(v[1], numbers.Number):
                    f.write('%s"%s": %d' % (prefix, n, v[1]))
                    tdict[n] = v[0]
                elif isinstance(v[1], np.ndarray):
                    f.write('%s"%s": [' % (prefix, n))
                    start = ""
                    for vv in v[1].ravel():
                        f.write('%s%d' % (start, vv))
                        start = ", "
                    f.write(']')
                    tdict[n] = list((v[0],) + v[1].shape)
            else:
                vv = typerange[v[0]]
                if vv is None:
                    if v[0] == "CHARSTR":
                        f.write('%s"%s": "%s"' % (prefix, n, v[1]))
                    else:
                        f.write('%s"%s": %g' % (prefix, n, v[1]))
                else:
                    f.write('%s"%s": %d' % (prefix, n, v[1]))
                tdict[n] = v[0]
        elif isinstance(v, np.ndarray):
            typ = nptypedict[v.dtype]
            f.write('%s"%s": [' % (prefix, n))
            start = ""
            for vv in v.ravel():
                if typ[1]:
                    f.write('%s%g' % (start, vv))
                else:
                    f.write('%s%d' % (start, vv))
                start = ", "
            f.write(']')
            tdict[n] = list((typ[0],) + v.shape)
        else: # Must be an enum!
            f.write('%s"%s": %d' % (prefix, n, v))
        prefix = ",\n" + indent

def write_typed_json(filename_or_fd, d, edef, headers=True):
    """Validate `d` and write it, followed by its ':types:' section (enums, header types and value types), as JSON to a file name or open file.

    Returns
    -------
    bool
        False if validation failed (the error is printed), else True. A file opened by name is not
        explicitly closed.
    """
    r = validate_typed_json(d, edef, [], headers)
    if r is not None:
        print(r)
        return False
    if isinstance(filename_or_fd, str):
        f = open(filename_or_fd, "w")
    else:
        f = filename_or_fd
    f.write('{\n')
    tdict = {}
    write_json_dict(f, d, edef, tdict, headers=headers)
    f.write(',\n    ":types:": {\n')
    if edef != {}:
        f.write('        ":enum:": {\n')
        write_json_dict(f, edef, {}, {}, [], "            ")
        f.write('\n        },\n')
    f.write('        "detType:RO": "CHARSTR",\n')
    f.write('        "detName:RO": "CHARSTR",\n')
    f.write('        "detId:RO": "CHARSTR",\n')
    f.write('        "doc:RO": "CHARSTR",\n')
    f.write('        "alg:RO": {\n')
    f.write('            "alg:RO": "CHARSTR",\n')
    f.write('            "doc:RO": "CHARSTR",\n')
    f.write('            "version:RO": ["INT32", 3]\n')
    f.write('        },\n')
    write_json_dict(f, tdict, {}, {}, [], "        ")
    f.write('\n    }\n}\n')
    return True

#
# Let's try to make creating valid dictionaries easier.  This heart
# of this class is the method:
#     set(name, value, type="INT32", override=False, append=False)
# Once the type of a name is set, changing it is only possible if
# override is True.
#
# name here is an expanded name (with ".") that will be unpacked to
# build the hierarchy.  Multiple possibilities for value are supported:
#     - A numeric value or numpy array will just create/overwrite the 
#       value.
#     - A list of numeric values will be converted to a numpy array
#       of the specified type and stored.
#     - A cdict will splice in the hierarchy at the specified location.
#     - A list of cdicts will add the list of dictionaries.
#
class cdict(object):
    """Builder for typed JSON dicts: values are kept as (type, value) tuples, numpy arrays or nested dicts/lists, plus enum definitions.

    Parameters
    ----------
    old : cdict or dict, optional
        A `cdict` to copy (shallow), a typed JSON dict with ':types:', or a plain dict whose
        types are inferred.
    """
    def __init__(self, old=None):
        self.dict = {}
        self.enumdef = {}
        if isinstance(old, cdict):
            self.dict.update(old.dict)
            self.enumdef.update(old.enumdef)
        elif isinstance(old, dict):
            if ":types:" in old.keys():
                cp = {}
                cp.update(old)
                jt = cp[':types:']
                if ":enum:" in jt.keys():
                    self.enumdef = jt[":enum:"]
                    del jt[":enum:"]
                del cp[':types:']
                self.init_from_json(cp, jt)
            else:
                self.init_from_dict(old)

    def init_from_dict(self, old, base=None):
        """Add the values of plain dict/list `old` under dotted prefix `base`, inferring types: str 'CHARSTR', float 'DOUBLE', bool 'UINT8', anything else 'INT32'.

        For each dict visited, missing header keys are set in the top-level dict ('' or an empty
        'alg:RO' entry).
        """
        if isinstance(old, dict):
            for k in old.keys():
                if base is None:
                    n = k
                else:
                    n = base + "." + k
                self.init_from_dict(old[k], n)
            for k in ["detType:RO", "detName:RO", "detId:RO", "doc:RO", "alg:RO"]:
                if not k in old.keys():
                    if k != "alg:RO":
                        self.dict[k] = ""
                    else:
                        self.dict[k] = { "alg:RO": "", "doc:RO": "", "version:RO": [0, 0, 0]}
        elif isinstance(old, list):
            for (k, v) in enumerate(old):
                n = base + "." + str(k)
                self.init_from_dict(v, n)
        elif isinstance(old, str):
            self.set(base, old, type="CHARSTR")
        elif isinstance(old, float):
            self.set(base, old, type="DOUBLE")
        elif isinstance(old, bool):
            self.set(base, old, type="UINT8")
        else:
            self.set(base, old, type="INT32")

    def init_from_json(self, old, jt, base=None):
        """Add the values of typed JSON `old` with types `jt` under dotted prefix `base`.

        Header strings and a complete 'alg:RO' entry are copied as is, numeric lists become numpy arrays
        of the listed type and shape, and scalars are set with their type.
        """
        if isinstance(old, dict):
            for k in old.keys():
                if k in ["detType:RO", "detName:RO", "detId:RO", "doc:RO"]:
                    self.dict[k] = str(old[k])
                    continue
                if k == "alg:RO":
                    alg = old['alg:RO']
                    if isinstance(alg, dict) and set([k for k in alg.keys()]) == set(["alg:RO", "doc:RO", "version:RO"]):
                        self.dict['alg:RO'] = alg
                    continue
                v = old[k]
                t = jt[k]
                if base is None:
                    n = k
                else:
                    n = base + "." + k
                if isinstance(v, dict) or (isinstance(v, list) and not self.checknumlist(v)):
                    self.init_from_json(v, t, n)
                elif isinstance(v, list) or isinstance(v, np.ndarray):
                    if isinstance(v, list):
                        # set v to an np.array of the appropriate type!
                        v = np.array(v, dtype=typedict[t[0]]).reshape(t[1:])
                        pass
                    self.set(n, v)
                else:
                    # Scalar!
                    self.set(n, v, t)
        elif isinstance(old, list):
            for (k, v) in enumerate(old):
                n = base + "." + str(k)
                self.init_from_json(v, jt, n)

    def typed_json(self):
        """Return the stored data as a typed JSON dict with a ':types:' entry (including ':enum:' if enums are defined)."""
        (d, t) = self.create_json(self.dict, True)
        if self.enumdef != {}:
            t[":enum:"] = {}
            t[":enum:"].update(self.enumdef)
        d[':types:'] = t
        return d

    # Add all of t2 to t1.  We'd use update, but we want to merge all 
    # the way down...
    def merge_dict(self, t1, t2):
        """Recursively add the keys of `t2` that are missing from `t1`; existing entries of `t1` are never replaced."""
        for k in t2.keys():
            if k in t1.keys():
                if isinstance(t1[k], dict):
                    if isinstance(t2[k], dict):
                        self.merge_dict(t1[k], t2[k])
                    # else WTF?
                # else check if types agree?!?
            else:
                t1[k] = t2[k]

    def create_json(self, input, top=False):
        """Convert stored data `input` into a ``(values, types)`` pair for typed JSON.

        Dicts and lists are converted recursively (list types are merged), numpy arrays become flat
        lists with type ``[TYPE, *shape]``, and (type, value) tuples are split; with `top`, header keys
        get 'CHARSTR' types.

        Raises
        ------
        ValueError
            For any other kind of value.
        """
        if isinstance(input, dict):
            d = {}
            t = {}
            for k in input.keys():
                if top and (k in ["detType:RO", "detName:RO", "detId:RO", "doc:RO", "alg:RO"]):
                    d[k] = input[k]
                    if k == 'alg:RO':
                        t[k] = {'alg:RO' : 'CHARSTR', 'doc:RO': 'CHARSTR', 'version:RO': ['INT32', 3]}
                    else:
                        t[k] = "CHARSTR"
                    continue
                (d2, t2) = self.create_json(input[k])
                d[k] = d2
                t[k] = t2
        elif isinstance(input, list):
            d = []
            t = {}
            for (k, v) in enumerate(input):
                (d2, t2) = self.create_json(v)
                d.append(d2)
                self.merge_dict(t, t2)
        elif isinstance(input, np.ndarray):
            typ = nptypedict[input.dtype]
            if typ[1]:
                d = [float(x) for x in input.ravel()]
            else:
                d = [int(x) for x in input.ravel()]
            t = list((typ[0],)+ input.shape)
        elif isinstance(input, tuple):
            d = input[1]
            t = input[0]
        else:
            raise ValueError('Type %s not supported with value %s' % (type(input),input))
        return (d, t)

    def get(self, name, withtype=False):
        """Return the entry at dotted `name`, or None if the name is empty, invalid or missing.

        (type, value) tuples are returned as the value only, unless `withtype` is True.
        """
        if len(name) == 0:
            return None
        n = splitname(name)
        if n is None:
            return None
        d = self.dict
        while len(n) != 0:
            if isinstance(d, list):
                try:
                    d = d[int(n[0])]
                    n = n[1:]
                except:
                    return None
            elif isinstance(d, dict):
                try:
                    d = d[n[0]]
                    n = n[1:]
                except:
                    return None
        if isinstance(d, tuple) and not withtype:
            return d[1]
        else:
            return d

    def getenumdict(self, name, reverse=False):
        """Return the enum mapping (label to value, or value to label if `reverse`) of the enum-typed entry `name`, or None if it is missing or not an enum."""
        r = self.get(name, True)
        if isinstance(r, tuple):
            if r[0] in typerange.keys():
                return None
            try:
                if reverse:
                    return {v: k for k, v in self.enumdef[r[0]].items()}
                else:
                    return self.enumdef[r[0]]
            except:
                return None
        else:
            return None

    def getenum(self, name):
        """Return the enum label of entry `name` (or its value if no label matches); basic-typed entries return their value and other entries are returned as is."""
        r = self.get(name, True)
        if isinstance(r, tuple):
            if r[0] in typerange.keys():
                return r[1]
            try:
                return next(key for key, value in self.enumdef[r[0]].items() if value == r[1])
            except:
                return r[1]
        else:
            return r

    def checknumlist(self, l):
        """Return True if list `l` (possibly nested) contains only numbers."""
        for v in l:
            if isinstance(v, list):
                if not self.checknumlist(v):
                    return False
            elif not isinstance(v, numbers.Number):
                return False
        return True

    def define_enum(self, name, value):
        # Validate the value dictionary?!?
        """Store enum `name` with label-to-value dict `value` (not validated) and return True."""
        self.enumdef[name] = value
        return True

    def set(self, name, value, type="INT32", override=False, append=False):
        """Store `value` at dotted `name`, creating intermediate dicts and lists as needed.

        Numbers become (`type`, value) tuples (enum values are checked with ``assert``), strings need
        `type` 'CHARSTR', numeric lists become numpy arrays of `type`, and a `cdict` or list of cdicts is
        copied in (appended to an existing list with `append`). Without `override`, an existing scalar keeps
        its stored type, and changing an array's dtype/shape or a container's kind raises ValueError.

        Raises
        ------
        ValueError
            For an empty or unsplittable name, or a disallowed change without `override`.
        TypeError
            For an invalid `type` or value kind (the parameter `type` shadows the built-in, so the two
            branches that call ``type(...)`` raise TypeError about a str not being callable instead).
        """
        if len(name) == 0:
            raise ValueError("set: received name with length 0")
        n = splitname(name)
        if n is None:
            raise ValueError("set: error splitting name %s" % name)
        d = self.dict
        # Check the type of value!
        if isinstance(value, numbers.Number):
            if not type in typedict.keys() and not type in self.enumdef.keys():
                raise TypeError('set: Invalid type: %s' % (type))
            if type in self.enumdef.keys():
                # check to see that the value is in the enum
                assert value in self.enumdef[type].values()
            value = (type, value)
            issimple = True
        elif isinstance(value, str):
            if type != "CHARSTR":
                raise TypeError('set: Invalid type: %s' % (type))
            issimple = True
        elif isinstance(value, np.ndarray):
            issimple = True
        elif isinstance(value, cdict):
            issimple = False
        elif isinstance(value, list):
            if self.checknumlist(value):
                if type in self.enumdef.keys():
                    value = np.array(value, dtype='int32')
                else:
                    value = np.array(value, dtype=typedict[type])
                issimple = True
            else:
                # Must be a list of cdicts!
                for v in value:
                    if not isinstance(v, cdict):
                        raise TypeError("set: expected type cdict")
                issimple = False
        else:
            raise TypeError("set: unknown type %s" % type(value))
        for i in range(len(n)):
            if isinstance(n[i], int):
                if d is None:
                    p[n[i-1]] = []
                    d = p[n[i-1]]
                if not isinstance(d, list):
                    if override:
                        p[n[i-1]] = []
                        d = p[n[i-1]]
                    else:
                        raise ValueError("set: override set to false")
                while len(d) < n[i]+1:
                    d.append({})
                p = d
                d = d[n[i]]
            else:
                if d is None:
                    p[n[i-1]] = {}
                    d = p[n[i-1]]
                if not isinstance(d, dict):
                    if override:
                        p[n[i-1]] = {}
                        d = p[n[i-1]]
                    else:
                        raise ValueError("set: override set to false")
                try:
                    p = d
                    d = d[n[i]]
                except:
                    if i+1 == len(n):
                        if not issimple and append:
                            p[n[i]] = []
                        else:
                            p[n[i]] = None
                    elif isinstance(n[i+1], int):
                        p[n[i]] = []
                    else:
                        p[n[i]] = {}
                    d = p[n[i]]
        # d is current value, if any. p is the last enclosing structure.
        if issimple:
            # A number or a numpy array
            if isinstance(value, np.ndarray):
                if not override and d is not None:
                    if not isinstance(d, np.ndarray):
                        raise ValueError("set: trying to change type (from array to %s)" % type(d))
                    if value.dtype != d.dtype or value.shape != d.shape:
                        raise ValueError(f"set: trying to change array dtype/shape [{value.dtype},{d.dtype}] [{value.shape},{d.shape}]")
                if type in self.enumdef.keys():
                    value = (type, value)
            elif isinstance(value, str):
                value = ("CHARSTR", value)
            else:
                if not override and d is not None:
                    if d[0] != "DOUBLE" and d[0] != "FLOAT":
                        value = (d[0], int(value[1]))
                    else:
                        value = (d[0], value[1])
            p[n[-1]] = value
            return
        else:
            # A cdict or a list of cdicts
            if isinstance(value, cdict):
                if not override and d is not None and not (isinstance(d, dict) or 
                                                           (isinstance(d, list) and append)):
                    raise ValueError("set: expected dict or list type")
                vnew = {}
                vnew.update(value.dict)
                if isinstance(d, list):
                    d.append(vnew)
                else:
                    p[n[-1]] = vnew
            else:
                if not override and d is not None and not isinstance(d, list):
                    raise ValueError("set: expected list type")
                if not append:
                    p[n[-1]] = []
                for v in value:
                    vnew = {}
                    vnew.update(v)
                    p[n[-1]].append(vnew)
            return

    def setAlg(self, alg, version=[0,0,0], doc=""):
        """Set the 'alg:RO' entry to `alg`, `doc` and `version`; if `version` is not a 3-element list or `alg`/`doc` are not strings, print a message and change nothing."""
        if not isinstance(version, list) or len(version) != 3:
            print("version should be a length 3 list!\n")
            return
        if not isinstance(alg, str):
            print("alg should be a string!")
            return
        if not isinstance(doc, str):
            print("doc should be a string!")
            return
        self.dict["alg:RO"] = {
            "alg:RO": alg,
            "doc:RO": doc,
            "version:RO": version
        }

    def setString(self, name, value):
        """Set top-level entry `name` to `value` if it is a str; print a message for other non-None values; ignore None."""
        if value is not None:
            if not isinstance(value, str):
                print("%s must be a str!" % name)
            else:
                self.dict[name] = value

    def setInfo(self, detType=None, detName=None, detSegm=None, detId=None, doc=None):
        """Set the header strings 'detType:RO', 'detName:RO' ('<detName>_<detSegm>' if `detSegm` is given), 'detId:RO' and 'doc:RO'; None arguments are skipped."""
        self.setString("detType:RO", detType)
        self.setString("detName:RO", detName if detSegm is None else detName+'_%d'%detSegm)
        self.setString("detId:RO", detId)
        self.setString("doc:RO", doc)

    def writeFile(self, file, headers=True):
        """Return ``write_typed_json(file, self.dict, self.enumdef, headers)``."""
        return write_typed_json(file, self.dict, self.enumdef, headers)


########################################################################
#
# The rest of this file is helper functions for typed JSON dictionaries.
#
########################################################################

# A little helper function to pull out type information from a typed
# JSON dictionary.  The second argument is either a fully dotted ('b.0.c')
# or python-style ('b0.c') name.
#
# This returns:
#    A simple type string.
#    An enum type dictionary.
#    A list, the first element of which is a simple type string or enum
#    type dictionary, and the remaining items are the dimensions of the array.
#
def getType(typed_json, name):
    """Return the type of dotted `name` in a typed JSON dict (or a dict of them): a basic type string, an enum dict, or a list of that plus array dimensions.

    Returns None if the path does not exist.

    Raises
    ------
    TypeError
        If `typed_json` is not a dict, no ':types:' entry is found, or the stored type is invalid.
    """
    if not isinstance(typed_json, dict):
        raise TypeError("getType: First argument should be a typed JSON dictionary!")
    try:
        t = typed_json[':types:']
        try:
            e = t[':enum:']
        except:
            e = {}
    except:
        t = None
    v = typed_json
    n = splitname(name)
    for i in n:
        try:
            v = v[i]
            if t is None:
                if ':types:' not in v.keys():
                    raise TypeError("getType: First argument should be a typed JSON dictionary!")
                t = v[':types:']
                try:
                    e = t[':enum:']
                except:
                    e = {}
            elif not isinstance(i, numbers.Number):
                t = t[i]
        except TypeError:
            raise
        except:
            return None
    if isinstance(t, list):
        if t[0] in typerange.keys():
            return t
        if t[0] in e.keys():
            t = list(t) # Make a copy!
            t[0] = e[t[0]]
            return t
        raise TypeError("getType: Invalid array type %s" % t[0])
    else:
        if t in typerange.keys():
            return t
        if t in e.keys():
            return e[t]
        raise TypeError("getType: Invalid type %s" % t)

#
# Get the value from a typed JSON dictionary.
#
def getValue(typed_json, name):
    """Return the value at dotted `name` in `typed_json`, or None if the path does not exist.

    Raises TypeError (with a message naming getType) if `typed_json` is not a dict.
    """
    if not isinstance(typed_json, dict):
        raise TypeError("getType: First argument should be a typed JSON dictionary!")
    v = typed_json
    n = splitname(name)
    for i in n:
        try:
            v = v[i]
        except:
            return None
    return v

#
# Convert a string, v, to a value of the specified simple type, t.  e is an
# enum dictionary.  Arrays need not apply.
#
def simpleConvert(v, t, e):
    """Convert string `v` to simple type `t` (`e` holds the enums).

    Enum labels map to their value and integer strings must be enum values; 'CHARSTR' is returned
    as is, 'FLOAT'/'DOUBLE' use ``float``, and integer types use ``int`` with a range check.

    Raises
    ------
    TypeError
        For an invalid enum value or type specifier.
    ValueError
        If an integer is out of range (or ``int``/``float`` fails).
    """
    if t in e.keys():
        if v in e[t].keys():
            return e[t][v]
        elif int(v)in e[t].values():
            return int(v)
        else:
            raise TypeError("convertValue: %s is not a valid enum of %s" % (v, t))
    elif t == 'CHARSTR':
        return v
    elif t == 'FLOAT' or t == 'DOUBLE':
        return float(v)
    elif t in typedict.keys():
        v = int(v)
        if v >= typerange[t][0] and v <= typerange[t][1]:
            return v
        else:
            raise ValueError("convertValue: %s is not in range of %s!" % (v, t))
    else:
        raise TypeError("convertValue: %s is not a valid type specifier." % t)

def convertValue(v, t, e={}):
    """Convert string `v` to type `t`: a simple type via `simpleConvert`, or for an array type a list from the space-separated items.

    Raises
    ------
    TypeError
        If the item count does not match the array dimensions or `t` is neither str nor list.
    """
    if isinstance(t, str):
        return simpleConvert(v, t, e)
    elif isinstance(t, list):
        vs = v.split(' ')
        l = np.prod(t[1:])
        if len(vs) != l:
            raise TypeError("convertValue: value has %d elements, not %d!" % (len(vs), l))
        return [simpleConvert(vw, t[0], e) for vw in vs]
    else:
        raise TypeError("convertValue: type must be a str or list.")

#
# Store new values into a typed JSON dictionary.  The value here is always
# a string.  If we have an array value, it will be a space-separated list
# of values.
#
# Returns an integer status:
#     =0 - ok
#     =1 - non-existent path
#     =2 - type conversion failed
#     =3 - invalid dictionary
#
def updateValue(typed_json, name, value):
    """Convert string `value` to the type of dotted `name` and store it in `typed_json`.

    Returns
    -------
    int
        0 on success, 1 if the path does not exist, 2 if the conversion failed, 3 if the
        dictionary is invalid.
    """
    if not isinstance(typed_json, dict):
        return 3
    try:
        t = typed_json[':types:']
        try:
            e = t[':enum:']
        except:
            e = {}
    except:
        t = None
    v = typed_json
    n = splitname(name)
    ln = n[-1]
    n = n[:-1]
    for i in n:
        try:
            v = v[i]
            if t is None:
                if ':types:' not in v.keys():
                    return 3
                t = v[':types:']
                try:
                    e = t[':enum:']
                except:
                    e = {}
            elif not isinstance(i, numbers.Number):
                t = t[i]
        except:
            return 1
    # t and v better be dictionaries with an entry ln!
    if (not isinstance(v, dict) or not isinstance(t, dict) or 
        ln not in v.keys() or ln not in t.keys()):
        return 1
    try:
        v[ln] = convertValue(value, t[ln], e)
        return 0
    except:
        return 2

def copyValues(din,top,k=None):
    """Copy values from an input dictionary to an output one.

    Useful for, e.g., reading register values from a YAML and
    updating a configuration dictionary to resubmit to configdb.

    Performs some type checking and conversion of enum labels to
    corresponding integer values.

    Args:
        din (Dict[str,Any]): Dictionary of new values.

        top (Dict[str, Any]): Top of the object configuration.
            Retrieved by calling cdb.get_configuration. See
            configdb.py for more information.

        k (str): Key to begin transferring from din to top at.
    """
    _copyValues(din, top, top[':types:'], top[':types:'][':enum:'],k)


def _copyValues(din,dout,types,enum_types,k=None):
    """Copy values from an input dictionary to an output one.

    Useful for, e.g., reading register values from a YAML and
    updating a configuration dictionary to resubmit to configdb.

    Performs some type checking and conversion of enum labels to
    corresponding integer values.

    Args:
        din (Dict[str,Any]): Dictionary of new values.

        dout (Dict[str, Any]): Dictionary to copy the values to.
            Should generally be the `top` object retrieved from
            the configdb, though this method is called recursively
            to update nested dictionaries.

        types (Dict[str, str]): Portion of the typed JSON dictionary
            containing the type information. Generally stored under
            `top[':types:']`

        enum_types (Dict[str, int]): Enum label-value configuration.
            This parameter is not updated during recursion. It is
            generally found under `top[':types:'][':enum:']`.

        k (str): Key to begin transferring from din to dout at.
    """
    if enum_types is None:
        raise ValueError('Cannot type check, provide data types!')
    if isinstance(din,dict) and isinstance(dout[k],dict):
        for key,value in din.items():
            if key in dout[k]:
                _copyValues(value,dout[k],types[k],enum_types,key)
            else:
                print(f'skip {key}')
    elif isinstance(din,bool):
        vin = 1 if din else 0
        if dout[k] != vin:
            print(f'Writing {k} = {vin}')
            dout[k] = 1 if din else 0
        else:
            print(f'{k} unchanged')
    else:
        if type(din) is type(dout[k]):
            if dout[k] != din:
                print(f'Writing {k} = {din}')
                dout[k] = din
            else:
                print(f'{k} unchanged')
        elif types[k] in enum_types:
            enum_type = enum_types[types[k]]
            dout[k] = enum_type[din]
            print(
                f'Changing enum {din} of {types[k]} to corresponding value: {dout[k]}'
            )
        else:
            print(
                f'Type mismatch for {k}: expect {type(dout[k])}, yaml has {type(din)} ({din})'
            )
            print(f'{k} unchanged')
