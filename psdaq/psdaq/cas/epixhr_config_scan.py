"""Scan of one EpixHR expert parameter chosen with -P, validated against the configdb entry 'epixhr_0'."""
from psdaq.cas.config_scan_base import ConfigScanBase
from psdaq.configdb.get_config import cdb
import json
import os
import sys

def listParams(d,name):
    """Return dotted names of all leaf keys under dict `d`, prefixed by `name`.

    Keys containing 'PacketRegisters' are skipped; of the 'Hr10kTAsic*' keys only
    'Hr10kTAsic0' is descended, under the name 'Hr10kTAsic'.
    """
    result = []
    name = '' if name is None else name+'.'
    for k,v in d.items():
        if 'PacketRegisters' in k:
            pass
        elif 'Hr10kTAsic' in k:
            if k=='Hr10kTAsic0':
                result.extend(listParams(v,f'{name}Hr10kTAsic'))
            else:
                pass
        elif isinstance(v,dict):
            result.extend(listParams(v,f'{name}{k}'))
        else:
            result.extend([f'{name}{k}'])
    return result
            
def main():

    # default command line arguments
    """Look up the EpixHR expert parameters in the configdb, then run a --linear scan of parameter -P.

    The configdb hutch is args.hutch for tmo/rix/asc/ued, else 'tst'. If -P is missing or
    not valid, the parameter list is printed and it returns; an 'Hr10kTAsic' parameter
    is written to all four ASICs. Without --linear it raises RuntimeError.

    Notes
    -----
    The `steps` generator uses `np`, which this module does not import (NameError).
    """
    defargs = {'--events'  :1000,
               '--hutch'   :'rix',
               '--detname' :'epixhr_0',
               '--scantype':'scan',
               '--record'  :1}

    aargs = [('-P',{'default':None,'help':'parameter to scan (omit to get full list'}),
             ('--linear',{'type':float,'nargs':3,'help':'linear scan over range [0]:[1] in steps of [2]'})]
    scan = ConfigScanBase(userargs=aargs,defargs=defargs)
             
    args = scan.args

    #  Validate scan parameter
    #  Lookup the configuration in the database
    prod  = True
    if args.hutch not in ('tmo','rix','asc','ued'):
        hutch = 'tst'
    else:
        hutch = args.hutch
             
    del sys.argv[1:]
    dbargs = cdb.createArgs().args
    dbargs.inst = hutch
    dbargs.prod = False
    dbargs.name = 'epixhr'
    dbargs.segm = 0
    dbargs.user = os.environ['USER']
    create = False
    db = 'configdb' # if dbargs.prod else 'devconfigdb'
    mycdb = cdb.configdb(f'https://pswww.slac.stanford.edu/ws-auth/{db}/ws/', dbargs.inst, create,
                         root='configDB', user=dbargs.user, password=dbargs.password)
    top = mycdb.get_configuration(dbargs.alias, dbargs.name+'_%d'%dbargs.segm)

    d = top['expert']['EpixHR']
    l = listParams(d,None)

    keys = None
    if args.P is not None and args.P in l:
        if 'Hr10kTAsic' in args.P:
            keys = [f'{args.detname}:expert.EpixHR.Hr10kTAsic{i}.{args.P[11:]}' for i in range(4)]
        elif 'PacketRegisters' in args.P:
            pass
        else:
            keys = [f'{args.detname}:expert.EpixHR.{args.P}']
        if keys is None:
            print('Invalid parameter {args.P}')

    usage = keys is None

    if usage:
        print('Valid parameters are:')
        for i in l:
            print(i)
        return

    if args.linear:
        print(f'linear: {args.linear}')
        def steps():
            metad = {'detname':args.detname, 'scantype':args.scantype}
            d = {}
            for value in np.arange(*args.linear):
                for k in keys:
                    d[k] = int(value)
                yield (d, value, json.dumps(metad))

    else:
        raise RuntimeError('Must specify scan type (--linear,)')

    scan.run(keys,steps)

if __name__ == '__main__':
    main()
