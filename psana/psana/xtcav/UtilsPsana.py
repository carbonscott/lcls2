
"""Helpers that read XTCAV-related values through psana run and event objects: detector lookups for calibration and ROI values, calibration constants, ROI metrics and shot-to-shot parameters."""
import logging
logger = logging.getLogger(__name__)

import numpy as np
#import psana
import time
from psana.xtcav.Utils import ROIMetrics, GlobalCalibration, ShotToShotParameters
import psana.xtcav.Constants as cons

from psana.xtcav.Simulators import\
  SimulatorDetector
#  SimulatorEBeam,\
#  SimulatorGasDetector,\
#  SimulatorEventId,\
#  SimulatorEnvironment

# def get_attribute(o, aname):
#     """ wrapper for getattr bwith message to the logger.
#     """
#     oat = getattr(o, aname, None)
#     if oat is None : 
#         logger.warning('Object %s does not contain attribute %s' % (str(o), attrname))
#         return None
#     #logger.debug('XXX get_attribute dir(oat) for %s: %s' % (aname,str(dir(oat))))
#     return oat



def get_pv_value(evt, atr, name, default):
    """Return ``atr(evt)``, or ``default`` with a warning if ``atr`` is None.

    The warning formats ``default`` with %d, so a non-numeric default (such as None) raises TypeError on that path.
    """
    if atr is None :
        logger.warning('PV "%s" is set to default value %d' % (name, default))
        return default
    else : 
        return atr(evt)


def getCameraSaturationValue(xtcavcalibpars, evt):

    """Return 4095 if an analysis-version value is found for ``evt``, otherwise 16383.

    The lookup uses the key 'analysiver' of ``xtcavcalibpars``; any exception (including KeyError, since ``get_calibration_parameters`` stores 'analysisver') is caught and 16383 is returned.
    """
    try:
        analysis_version = get_pv_value(evt, xtcavcalibpars["analysiver"], xtcavcalibpars["analysisver_name"], None) #SimulatorDetector(cons.ANALYSIS_VERSION)
        if analysis_version(evt) is not None:
            return (1<<12)-1
    except:
        pass

    return (1<<14)-1
    

def get_calibconst(det, ctype='xtcav_pedestals', detname='xtcav', expname='amox23616', run_number=131):
    """Return ``det.calibconst.get(ctype)``; if that is None, fetch the constants with ``MDBWebUtils.calib_constants(detname, exp=expname, ctype=ctype, run=run_number)``.

    Logs a warning and calls ``sys.exit`` if both give None.
    """
    resp = det.calibconst.get(ctype)
    if resp is None : # try direct access
        logger.warning('ACCESS TO CALIB CONSTANTS "%s"' % ctype\
                       + ' VIA "%s" DETECTOR INTERFACE DOES NOT WORK, USE DIRECT ACESS' % detname)
        from psana.pscalib.calib.MDBWebUtils import calib_constants
        resp = calib_constants(detname, exp=expname, ctype=ctype, run=run_number)
    if resp is None :
        logger.warning('CAN NOT ACCESS CALIB CONSTANTS "%s" FOR DETECTOR "%s"' % (ctype, detname))
        import sys
        sys.exit('EXIT - PROBLEM NEEDS TO BE FIXED...')
    #dark_data, dark_meta = resp
    return resp


def getGlobalXTCAVCalibration(xtcavcalibpars, evt):
    """
    Obtain the global XTCAV calibration form the epicsStore
    Arguments:
      xtcavcalibpars, evt
    Output:
      globalCalibration: struct with the parameters
      ok: if all the data was retrieved correctly
    """
    def getCalibrationValue(par, parname, evt):
        val = par(evt)
        if val is None or abs(val) < 1e-100 :
            logger.warning('XTCAV variable/s %s is/are not found in the xtc event' % parname)
            return None
        return val
        
    global_calibration = GlobalCalibration(
        umperpix    =getCalibrationValue(xtcavcalibpars["umperpix"], xtcavcalibpars["umperpix_name"], evt),
        strstrength =getCalibrationValue(xtcavcalibpars["strstrength"], xtcavcalibpars["strstrength_name"], evt), 
        rfampcalib  =getCalibrationValue(xtcavcalibpars["rfampcalib"], xtcavcalibpars["rfampcalib_name"], evt),
        rfphasecalib=getCalibrationValue(xtcavcalibpars["rfphasecalib"], xtcavcalibpars["rfphasecalib_name"], evt), 
        dumpe       =getCalibrationValue(xtcavcalibpars["dumpe"], xtcavcalibpars["dumpe_name"], evt),
        dumpdisp    =getCalibrationValue(xtcavcalibpars["dumpdisp"], xtcavcalibpars["dumpdisp_name"], evt)
    )

    #self check
    for k,v in global_calibration._asdict().items():
        if not v:
            logger.warning('No XTCAV Calibration for epics variable %s' % k)
            return None

    return global_calibration
                          

def pv_and_name_from_list(run, names):
    """Return ``(run.Detector(name), name)`` for the first name in ``names`` that gives a detector.

    Names whose lookup raises are logged as warnings; if none works the result is ``(None, <last name>)``.
    """
    atr = None
    for name in names:
        try:
            atr = run.Detector(name)
        except:
            logger.warning('No available detector class with %s' % (name))
            atr = None            
        if atr is not None : break
    return atr, name

def get_calibration_parameters(run):
    """Look up detectors for the calibration names in ``psana.xtcav.Constants`` (um per pixel, streak strength, RF amplitude and phase calibration, dump energy and dispersion, analysis version) with ``pv_and_name_from_list``.

    Returns
    -------
    dict
        Keys 'umperpix', 'strstrength', 'rfampcalib', 'rfphasecalib', 'dumpe', 'dumpdisp', 'analysisver' with the detector objects (or None) and the same keys with suffix '_name' holding the names used.
    """
    umperpix, umperpix_name  = pv_and_name_from_list(run, cons.UM_PER_PIX_names)
    strstrength, strstrength_name = pv_and_name_from_list(run, cons.STR_STRENGTH_names) 
    rfampcalib, rfampcalib_name = pv_and_name_from_list(run, cons.RF_AMP_CALIB_names) 
    rfphasecalib, rfphasecalib_name = pv_and_name_from_list(run, cons.RF_PHASE_CALIB_names) 
    dumpe, dumpe_name = pv_and_name_from_list(run, cons.DUMP_E_names)
    dumpdisp , dumpdisp_name = pv_and_name_from_list(run, cons.DUMP_DISP_names)
    analysisver, analysisver_name = pv_and_name_from_list(run, cons.ANALYSIS_VERSION)
    

    return {
        "umperpix": umperpix,
        "umperpix_name": umperpix_name,
        "strstrength": strstrength,
        "strstrength_name": strstrength_name,
        "rfampcalib": rfampcalib,
        "rfampcalib_name": rfampcalib_name, 
        "rfphasecalib": rfphasecalib,
        "rfphasecalib_name": rfphasecalib_name,
        "dumpe": dumpe,
        "dumpe_name": dumpe_name,
        "dumpdisp": dumpdisp,
        "dumpdisp_name": dumpdisp_name,
        "analysisver": analysisver,
        "analysisver_name": analysisver_name,
    }


def get_roi_parameters(run):
    """Look up detectors for the ROI size and start names in ``psana.xtcav.Constants`` with ``pv_and_name_from_list``.

    Returns
    -------
    dict
        Keys 'roiXN', 'roiYN', 'roiX0', 'roiY0' with the detector objects (or None) and 'nameXN', 'nameYN', 'nameX0', 'nameY0' with the names used.
    """
    roiXN, nameXN = pv_and_name_from_list(run, cons.ROI_SIZE_X_names)
    roiYN, nameYN = pv_and_name_from_list(run, cons.ROI_SIZE_Y_names)
    roiX0, nameX0 = pv_and_name_from_list(run, cons.ROI_START_X_names)
    roiY0, nameY0 = pv_and_name_from_list(run, cons.ROI_START_Y_names)
    return {
        "roiXN": roiXN,
        "nameXN": nameXN,
        "roiYN": roiYN,
        "nameYN": nameYN, 
        "roiX0": roiX0,
        "nameX0": nameX0,
        "roiY0": roiY0,
        "nameY0": nameY0,
    }


def getXTCAVImageROI(xtcavroipars, evt):
    """Return a ``ROIMetrics`` built from the ROI sizes and start positions read for ``evt`` (constants from ``psana.xtcav.Constants`` when a detector is missing).

    The pixel coordinates are ``x0 + arange(xN)`` and ``y0 + arange(yN)``. Returns None if any value is None or all four are 0.
    """
    #logger.debug('ZZZZ getXTCAVImageROI dir(ovals):\n%s' % str(dir(ovals)))

    xN = get_pv_value(evt, xtcavroipars["roiXN"], xtcavroipars["nameXN"], cons.ROI_SIZE_X)  # Size of the image in X
    yN = get_pv_value(evt, xtcavroipars["roiYN"], xtcavroipars["nameYN"], cons.ROI_SIZE_Y)  # Size of the image in Y
    x0 = get_pv_value(evt, xtcavroipars["roiX0"], xtcavroipars["nameX0"], cons.ROI_START_X) # Position of the first pixel in x
    y0 = get_pv_value(evt, xtcavroipars["roiY0"], xtcavroipars["nameY0"], cons.ROI_START_Y) # Position of the first pixel in y

    if None in (xN, yN, x0, y0) : return None
    if all(v==0 for v in (xN, yN, x0, y0)) : return None

    x = x0+np.arange(0, xN) 
    y = y0+np.arange(0, yN) 

    return ROIMetrics(xN, x0, yN, y0, x, y) 

    #    try:
    #    except KeyError:
    #        continue        
    #logger.warning('No XTCAV ROI info 2')
    #return None


def getShotToShotParameters(evt, ebeam, gasdetector) :
    
    #TODO: Is this correct?
    
    # sec, nsec      = valseid.time(evt)
    # unixtime       = int((sec<<32)|nsec)
    """Return a ``ShotToShotParameters`` for ``evt`` built from ``ebeam.raw`` and ``gasdetector.raw`` values.

    Uses ebeam charge, XTCAV RF amplitude and phase, dump charge multiplied by ``Constants.E_CHARGE``, ``1e-3 * gasdetector.raw.energy(evt)`` as x-ray energy, and ``evt.timestamp`` as unixtime.
    """
    timestamp        = evt.timestamp
    # fiducial       = valseid.fiducials(evt)
    ebeamcharge      = ebeam.raw.ebeamCharge(evt)
    xtcavrfamp       = ebeam.raw.ebeamXTCAVAmpl(evt)
    xtcavrfphase     = ebeam.raw.ebeamXTCAVPhase(evt)
    
    
    # TODO: TJ multiplied this value by E_CHARGE, Mikhail did not
    dumpecharge      = ebeam.raw.ebeamDumpCharge(evt)*cons.E_CHARGE #In C 

    energydetector   = gasdetector.raw.energy(evt)

    return ShotToShotParameters(\
        ebeamcharge  = ebeamcharge,\
        xtcavrfphase = xtcavrfphase,\
        xtcavrfamp   = xtcavrfamp,\
        dumpecharge  = dumpecharge,\
        xrayenergy   = 1e-3*energydetector,\
        unixtime     = timestamp)
    #return ShotToShotParameters(unixtime = unixtime, fiducial = fiducial, valid = 0)
        


#def divideImageTasks(first_image, last_image, rank, size):
#    """
#    DEPRICATED
#    Split image numbers among cores based on number of cores and core ID
#    The run will be segmented into chunks of 4 shots, with each core alternatingly assigned to each.
#    e.g. Core 1 | Core 2 | Core 3 | Core 1 | Core 2 | Core 3 | ....
#    """
#    num_shots = last_image - first_image
#    if num_shots <= 0:
#        return np.empty()
#    tiling = np.arange(rank*4, rank*4+4,1) #  returns [0, 1, 2, 3] if e.g. rank == 0 and size == 4:
#    comb1 = np.tile(tiling, np.ceil(num_shots/(4.*size)).astype(int))  # returns [0, 1, 2, 3, 0, 1, 2, 3, ...]        
#    comb2 = np.repeat(np.arange(0, np.ceil(num_shots/(4.*size)), 1), 4) # returns [0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, ...]
#            #  list of shot numbers assigned to this core
#    main = comb2*4*size + comb1  + first_image # returns [  0.   1.   2.   3.  16.  17.  18.  19.  32.  33. ... ]
#    main = np.delete(main, np.where(main>=last_image) )  # remove element if greater or equal to maximum number of shots in run
#    return main.astype(int)

