"""Helpers that print the contents of detector configuration objects."""
import numpy

def dumpvars(prefix,c):
    """Print every attribute of `c` as `<prefix>.<name> <value>`, recursing into nested objects.

    ints, floats, strs, lists and numpy arrays are printed as they are; objects with a `value`
    attribute print `val.names[val.value]`; other objects are dumped recursively, and an error
    during that prints "Error dumping <name> <type>".
    """
    for key,val in vars(c).items():
        name = prefix+'.'+key
        if (isinstance(val,int) or
            isinstance(val,float) or
            isinstance(val,str) or
            isinstance(val,list) or
            isinstance(val,numpy.ndarray)):
            print('{:} {:}'.format(name,val))
        elif hasattr(val,'value'):
            print('{:} {:}'.format(name,val.names[val.value]))
        else:
            try:
                dumpvars(name,val)
            except:
                print('Error dumping {:} {:}'.format(name,type(val)))

def dump_seg(seg,cfg):
    """Print a "-- segment <seg> --" header, then dump `cfg.config` with `dumpvars` using the prefix "config"."""
    print('-- segment {:} --'.format(seg))
    dumpvars('config',cfg.config)

def dump_det_config(det,name):
    """Dump the configuration of detector `name` for each segment in each config of `det._configs`.

    Configs that do not contain `name` are reported with a "Skipping config" line that prints the
    config's attribute dict.
    """
    for config in det._configs:
        if not name in config.__dict__:
            print('Skipping config {:}'.format(config.__dict__))
            continue
        scfg = getattr(config,name)
        for seg,segcfg in scfg.items():
            dump_seg(seg,segcfg)
