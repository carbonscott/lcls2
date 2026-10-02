"""Script: read an epixhr configuration from the config database and write parts of its 'expert.EpixHR' section to YAML files.

Files are named '/tmp/epixhr<part>.yml' (e.g. '/tmp/epixhrMMCM.yml'); the file names are
stored as attributes of a dummy object and printed.
"""
from psdaq.configdb.typed_json import cdict
import psdaq.configdb.configdb as cdb
import pyrogue as pr
import numpy as np
import sys
import IPython
import argparse

def intToBool(d,types,key):
    """Convert ``d[key]`` in place to bool where `types` marks it 'boolEnum', recursing into nested dicts.

    Zero becomes False and any other value True.
    """
    if isinstance(d[key],dict):
        for k,value in d[key].items():
            intToBool(d[key],types[key],k)
    elif types[key]=='boolEnum':
        d[key] = False if d[key]==0 else True

def dictToYaml(d,types,keys,dev,path,name):
    """Write the entries `keys` of `d` as YAML under ``{'ePixHr10kT': {'EpixHR': ...}}`` to the file '<path><name>.yml' and set ``dev.filename<name>`` to that path.

    'boolEnum' values are converted to bool with `intToBool`; nested dicts are shared with `d`,
    so they are converted in `d` as well.
    """
    v = {}
    for key in keys:
        v[key] = d[key]
        intToBool(v,types,key)

    nd = {'ePixHr10kT':{'EpixHR':v}}
    yaml = pr.dataToYaml(nd)
    fn = path+name+'.yml'
    f = open(fn,'w')
    f.write(yaml)
    f.close()
    setattr(dev,'filename'+name,fn)

class EpixHR(object):
    """Empty attribute holder used as the target of `dictToYaml`."""
    def __init__(self):
        pass

class test(object):
    """Holder with one attribute `EpixHR` (an `EpixHR` instance)."""
    def __init__(self):
        self.EpixHR = EpixHR()

if __name__ == "__main__":

    create = False
    dbname = 'configDB'     #this is the name of the database running on the server.  Only client care about this name.

    args = cdb.createArgs().args

    db = 'configdb' if args.prod else 'devconfigdb'
    mycdb = cdb.configdb(f'https://pswww.slac.stanford.edu/ws-auth/{db}/ws/', args.inst, create,
                         root=dbname, user=args.user, password=args.password)
    top = mycdb.get_configuration(args.alias, args.name+'_%d'%args.segm)

    epixHR      = top           ['expert']['EpixHR']
    epixHRTypes = top[':types:']['expert']['EpixHR']
    path = '/tmp/epixhr'
    cbase = test()

    dictToYaml(epixHR,epixHRTypes,['MMCMRegisters'  ],cbase.EpixHR,path,'MMCM')
    dictToYaml(epixHR,epixHRTypes,['PowerSupply'    ],cbase.EpixHR,path,'PowerSupply')
    dictToYaml(epixHR,epixHRTypes,['RegisterControl'],cbase.EpixHR,path,'RegisterControl')
    for i in range(4):
        dictToYaml(epixHR,epixHRTypes,['Hr10kTAsic{}'.format(i)],cbase.EpixHR,path,'ASIC{}'.format(i))
    dictToYaml(epixHR,epixHRTypes,['PacketRegisters{}'.format(i) for i in range(4)],cbase.EpixHR,path,'PacketReg')
    dictToYaml(epixHR,epixHRTypes,['TriggerRegisters'],cbase.EpixHR,path,'TriggerReg')

    print(vars(cbase.EpixHR))
