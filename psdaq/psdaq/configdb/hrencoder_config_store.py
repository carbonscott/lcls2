"""Script: write a default 'hrencoder' configuration to the config database (see `write_to_daq_config_db`)."""
from psdaq.configdb.typed_json import cdict
import psdaq.configdb.configdb as cdb
import sys
import argparse
import IPython
import pyrogue as pr

def lookupValue(d,name):
    """Return the value at dotted path `name` in nested dict `d`, with bools converted to 1/0, or None if a path component is missing.

    If a dict is reached when `name` has no more components, IndexError is raised.
    """
    key = name.split('.',1)
    if key[0] in d:
        v = d[key[0]]
        if isinstance(v,dict):
            return lookupValue(v,key[1])
        elif isinstance(v,bool):
            return 1 if v else 0
        else:
            return v
    else:
        return None

class mcdict(cdict):
    """`cdict` that can take values from a YAML file.

    Parameters
    ----------
    fn : str, optional
        YAML file loaded with ``pyrogue.yamlToData``; if not given the YAML dict is empty.
    """
    def __init__(self, fn=None):
        super().__init__(self)

        self._yamld = {}
        if fn:
            print('Loading yaml...')
            self._yamld = pr.yamlToData(fName=fn)

    #  intercept the set call to replace value with yaml definition
    def init(self, prefix, name, value, type="INT32", override=False, append=False):
        """Set the read-only entry '<prefix>:RO.<name>:RO', using the YAML value at `name` instead of `value` when that value is truthy."""
        v = lookupValue(self._yamld,name)
        if v:
            print('Replace {:}[{:}] with [{:}]'.format(name,value,v))
            value = v
        self.set(prefix+':RO.'+name+':RO', value, type, override, append)

def write_to_daq_config_db(args):
    """Create the alias and the 'hrencoder' device config if needed and write a default hrencoder configuration under ``args.alias``.

    The database is 'configdb' if ``args.prod`` else 'devconfigdb' at pswww.slac.stanford.edu;
    the values set (help text, 'user.delay_ns', 'expert.PauseThreshold', 'expert.TriggerDelay')
    are in the code. `args` comes from ``configdb.createArgs``.
    """
    create: bool = True
    dbname: str = 'configDB'

    db: str  = 'configdb' if args.prod else 'devconfigdb'
    url: str  = f'https://pswww.slac.stanford.edu/ws-auth/{db}/ws/'

    mycdb = cdb.configdb(url, args.inst, create,
                         root=dbname, user=args.user, password=args.password)
    mycdb.add_alias(args.alias)
    mycdb.add_device_config('hrencoder')

    top: mcdict = mcdict(args.yaml)
    top.setInfo('hrencoder', args.name, args.segm, args.id, 'No comment')
    top.setAlg('config', [0,1,0])

    help_str: str = (
        '-- user --\n'
        '  - delay_ns : Nanosecond delay to the encoder trigger signal. Adjust '
                       'for timing in the encoder.'
    )
    top.set('help:RO', help_str, 'CHARSTR')

    # Additional delay - cannot be negative if I understand correctly
    top.set('user.delay_ns', 105765, 'UINT32')

    top.set('expert.PauseThreshold', 16, 'UINT8')
    top.set('expert.TriggerDelay', 42, 'UINT32') # 185.7 MHz clocks

    mycdb.add_alias(args.alias)
    mycdb.modify_device(args.alias, top)


if __name__ == "__main__":
    args = cdb.createArgs().args
    write_to_daq_config_db(args)
