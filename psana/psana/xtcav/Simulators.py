
"""Simulators of currently non-available LCLS2 data.

   from psana.xtcav.Simulators import SimulatorEBeam, SimulatorGasDetector
   from psana.xtcav.Simulators import SimulatorEventId, SimulatorEnvironment
"""
#----------
import logging
logger = logging.getLogger(__name__)

class Simulator :
    """Base stand-in object for data that is not available; the constructor prints a message and stores ``detname``."""
    def __init__(self, detname) :
        print('Simulator of %s missing data in LCLS2' % detname)
        self.detname = detname

    def get(self, evt=None) :
        """Return ``self``; ``evt`` is ignored."""
        return self

#----------
# for LasingOffReference.py
#----------
import psana.xtcav.Constants as cons

class SimulatorEBeam(Simulator) :
    """Stand-in for 'EBeam' data whose methods return fixed values from ``psana.xtcav.Constants``."""
    def __init__(self) :
        Simulator.__init__(self, 'EBeam')
    def ebeamCharge(self) :
        """Return ``Constants.E_BEAM_CHARGE``."""
        return cons.E_BEAM_CHARGE # 5
    def ebeamDumpCharge(self) :
        """Return ``Constants.DUMP_E_CHARGE``."""
        return cons.DUMP_E_CHARGE # 175E-12 #IN C
    def ebeamXTCAVAmpl(self) :
        """Return ``Constants.XTCAV_RFAMP``."""
        return cons.XTCAV_RFAMP   # 20
    def ebeamXTCAVPhase(self) :
        """Return ``Constants.XTCAV_RFPHASE``."""
        return cons.XTCAV_RFPHASE # 90


class SimulatorGasDetector(Simulator) :
    """Stand-in for 'GasDetector' data whose methods return fixed numbers."""
    def __init__(self) :
        Simulator.__init__(self, 'GasDetector')
    def f_11_ENRC(self) :
        """Return the constant 6011."""
        return 6011
    def f_12_ENRC(self) :
        """Return the constant 6012."""
        return 6012


class SimulatorEventId(Simulator) :
    """Stand-in for 'EventId' data with counters for time and fiducials, starting from the current time in seconds."""
    def __init__(self) :
        from time import time
        Simulator.__init__(self, 'EventId')
        self.count_time_sec = int(time())
        self.count_time_nsec = 0
        self.count_fiducials = 0

    def time(self) :
        """Increment both time counters by 1 and return ``[count_time_sec, count_time_nsec]``."""
        self.count_time_sec += 1
        self.count_time_nsec += 1
        return [self.count_time_sec, self.count_time_nsec]

    def fiducials(self) :
        """Increment the fiducials counter by 1 and return it."""
        self.count_fiducials += 1
        return self.count_fiducials


class SimulatorEnvironment(Simulator) :
    """Stand-in for 'Environment' data."""
    def __init__(self) :
        Simulator.__init__(self, 'Environment')

    def calibDir() :
        """Return './calib'.

        The method has no ``self`` parameter, so calling it on an instance raises TypeError.
        """
        return './calib'


class SimulatorDetector(Simulator) :
    """Callable stand-in for a detector named ``name``.

    Calling the object prints the name and returns the ROI size/start constants from ``psana.xtcav.Constants`` for the matching ROI names, the argument ``v`` (default 1e-100) for the scale and calibration names, and None otherwise.
    """
    def __init__(self, name) :
        Simulator.__init__(self, 'Detector')
        self.name = name

    def __call__(self, evt=None, v=1e-100) :
        print('    __call__("%s")' % self.name)
        if   self.name in cons.ROI_SIZE_X_names     : return cons.ROI_SIZE_X
        elif self.name in cons.ROI_SIZE_Y_names     : return cons.ROI_SIZE_Y
        elif self.name in cons.ROI_START_X_names    : return cons.ROI_START_X
        elif self.name in cons.ROI_START_Y_names    : return cons.ROI_START_Y
        elif self.name in cons.UM_PER_PIX_names     : return v
        elif self.name in cons.STR_STRENGTH_names   : return v
        elif self.name in cons.RF_AMP_CALIB_names   : return v
        elif self.name in cons.RF_PHASE_CALIB_names : return v
        elif self.name in cons.DUMP_E_names         : return v
        elif self.name in cons.DUMP_DISP_names      : return v
        elif self.name == cons.ANALYSIS_VERSION     : return None
        else : return None

#----------

if __name__ == "__main__" :
    o0 = Simulator('Superclass for')
    o1 = SimulatorEBeam()
    o2 = SimulatorGasDetector()
    o3 = SimulatorEventId()
    o4 = SimulatorEnvironment()
    o5 = SimulatorDetector(Simulator); print(o5())

#----------
