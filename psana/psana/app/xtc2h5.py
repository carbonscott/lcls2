# TODO: fix StaleFlags and epicsinfo exceptions, and perhaps eventcodes list

"""Script `xtc2h5.py <exp> <run>`: write the values of all detector and epics accessors of each event to HDF5 with smalldata.

The output file is hard-coded under /cds/data/psdm/xpp/xpptut15/scratch/cpo/. The code runs at
import time and sets PS_SRV_NODES=1.
"""
from psana import DataSource
import numpy as np
import sys
import os

exp=sys.argv[1]
runnum=int(sys.argv[2])
hutch=exp[:3]

os.environ['PS_SRV_NODES']='1'

ds = DataSource(exp=exp,run=runnum)
#outfile='/cds/data/psdm/'+hutch+'/exp/hdf5/run'+str(runnum)+'.h5'
outfile='/cds/data/psdm/xpp/xpptut15/scratch/cpo/run'+str(runnum)+'.h5'
smd = ds.smalldata(filename=outfile, batch_size=5)

def fill_dict(mydict, obj, evt, name, epics):
    """Store in `mydict[name]` a nested dict of the values of the public callables of `obj`.

    Callables are called with `evt`, or with no argument when `epics` is True; None values are
    skipped, list values become numpy arrays, `calibconst` is skipped, and non-callable attributes
    are descended into.
    """
    mydict[name]={}
    localdict = mydict[name]
    for attrstr in dir(obj):
        if attrstr[0]=='_' or attrstr=='calibconst': continue
        attr = getattr(obj,attrstr)
        if callable(attr):
            if epics:
                val = attr()
            else:
                val = attr(evt)
            if val is not None:
                if type(val) is list: # for eventcodes
                    localdict[attrstr] = np.array(val)
                else:
                    localdict[attrstr] = val
        else:
            fill_dict(localdict,attr,evt,attrstr,epics)

for myrun in ds.runs():
    detnames = myrun.detinfo.keys()
    detnames = list(set([name for name,_ in detnames if name!='epicsinfo'])) # remove duplicates
    epicsnames = myrun.epicsinfo.keys()
    epicsnames = [name for name,_ in epicsnames]
    dets = [(name,myrun.Detector(name)) for name in detnames]
    epicsdets = [(name,myrun.Detector(name)) for name in epicsnames if name!='StaleFlags']

    for nevt,evt in enumerate(myrun.events()):
        mydict = {}
        for name,det in dets:
            fill_dict(mydict, det, evt, name, False)
        mydict['epics'] = {}
        for name,det in epicsdets:
            fill_dict(mydict['epics'], det, evt, name, True)
        smd.event(evt, mydict)

smd.done()
