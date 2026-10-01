#!/usr/bin/env python

"""
:py:class:`test_UtilsEventLoop` - test of detector/UtilsEventLoop.py
====================================================================

command: testman/test_UtilsEventLoop.py

@date 2025-10-08
@author Mikhail Dubrovin
"""
from psana.detector.UtilsEventLoop import *
import psana.detector.UtilsCalib as uc

SCRNAME = sys.argv[0].rsplit('/')[-1]


class EventLoopTest(EventLoop):
    """`EventLoop` subclass that tests the event loop with dark processing (`UtilsCalib.DarkProc`).

    Each step's constants are saved to the calibration repository in `end_step`.
    """
    msgelt='ELT:'

    def __init__(self, parser):
        EventLoop.__init__(self, parser)

    def init_event_loop(self):
        """Log and print the start and reset the loop state.

        Sets `dpo` and `status` to None and `dic_consts_tot` and `kwa_depl` to empty dicts.
        """
        message(msg=self.msgelt, metname=sys._getframe().f_code.co_name, logmethod=logger.info)
        print('init_event_loop - dskwargs: %s detname: %s' % (str(self.dskwargs), self.detname))
        #kwa['init_event_loop'] = 'OK'
        self.dpo = None
        self.status = None
        self.dic_consts_tot = {} # {<gain_mode>:{<ctype>:nda3d_shape:(4, 192, 384)}}
        self.kwa_depl = {}

    def begin_run(self):
        """Log the method name and print the experiment name and run number."""
        message(msg=self.msgelt, metname=sys._getframe().f_code.co_name, logmethod=logger.info)
        print('begin_run expname: %s runnum: %s' % (self.expname, str(self.runnum)))

    def end_run(self):
        """Log the method name; does nothing else."""
        message(msg=self.msgelt, metname=sys._getframe().f_code.co_name, logmethod=logger.info)

    def begin_step(self):
        """Print the step number and metadata and create the `DarkProc` if it does not exist yet.

        The `DarkProc` gets the parameters with `rms_hi` and `int_hi` set to the detector's data bit mask
        minus 10, plus the run number, experiment and timestamps.
        """
        message(msg=self.msgelt, metname=sys._getframe().f_code.co_name, logmethod=logger.info)
        print('begin_step istep/nevtot: %d/%s' % (self.istep, str(self.metadic)))

        dpo = self.dpo
        if dpo is None:
            odet = self.odet
            kwa = self.kwa
            kwa['rms_hi'] = odet.raw._data_bit_mask - 10
            kwa['int_hi'] = odet.raw._data_bit_mask - 10

            dpo = self.dpo = uc.DarkProc(**kwa)
            dpo.runnum = self.runnum
            dpo.exp = self.expname
            dpo.ts_run, dpo.ts_now = self.ts_run, self.ts_now #uc.tstamps_run_and_now(env, fmt=uc.TSTAMP_FOR

    def end_step(self):
        """Finish dark processing for the step and save the constants to the repository.

        Gets the pedestals, RMS, status, max and min arrays from the `DarkProc`, works out the gain mode
        from the step metadata, builds the deployment metadata with `UtilsCalib.add_metadata_kwargs`,
        calls `save_constants_in_repository` and stores the constants in `dic_consts_tot`. Only a local
        name is deleted, so `self.dpo` is kept and reused by later steps.
        """
        message(msg=self.msgelt, metname=sys._getframe().f_code.co_name, logmethod=logger.info)
        if True:
                odet = self.odet
                dpo = self.dpo
                dpo.summary()
                ctypes = ('pedestals', 'pixel_rms', 'pixel_status', 'pixel_max', 'pixel_min') # 'status_extra'
                arr_av1, arr_rms, arr_sta = dpo.constants_av1_rms_sta()
                arr_max, arr_min = dpo.constants_max_min()
                consts = arr_av1, arr_rms, arr_sta, arr_max, arr_min
                logger.info('evaluated constants: \n  %s\n  %s\n  %s\n  %s\n  %s' % (
                            au.info_ndarr(arr_av1, 'arr_av1', first=0, last=5),\
                            au.info_ndarr(arr_rms, 'arr_rms', first=0, last=5),\
                            au.info_ndarr(arr_sta, 'arr_sta', first=0, last=5),\
                            au.info_ndarr(arr_max, 'arr_max', first=0, last=5),\
                            au.info_ndarr(arr_min, 'arr_min', first=0, last=5)))
                dic_consts = dict(zip(ctypes, consts))
                gainmode = gain_mode(odet, self.metadic, self.istep) # nsteptot)\
                kwa_depl = self.kwa_depl
                kwa_depl = uc.add_metadata_kwargs(self.orun, odet, **self.kwa)
                kwa_depl['gainmode'] = gainmode
                kwa_depl['repoman'] = self.repoman
                longname = kwa_depl['longname'] # odet.raw._uniqueid
                #if shortname is None:
                shortname = uc.detector_name_short(longname)
                print('detector long  name: %s' % longname)
                print('detector short name: %s' % shortname)
                kwa_depl['shortname'] = shortname
                segind = self.kwa_depl.get('segind', None)
                kwa_depl['segind'] = 0 if segind is None else segind

                #kwa_depl['segment_ids'] = odet.raw._segment_ids()

                logger.info('kwa_depl:\n%s' % info_dict(kwa_depl, fmt='  %12s: %s', sep='\n'))
                #sys.exit('TEST EXIT')

                save_constants_in_repository(dic_consts, **kwa_depl)
                self.dic_consts_tot[gainmode] = dic_consts
                del(dpo)
                dpo=None

                logger.info('==== End of step %1d ====' % self.istep)

    def proc_event(self, msgmaxnum=5):
        """Pass the current event's raw data to `DarkProc.event` and store its return value in `status`.

        Returns at once for events with index above `msgmaxnum`, so only events 0 to `msgmaxnum` reach
        `DarkProc.event`; those log a warning ("STOP WARNINGS" at `msgmaxnum`). The event loop stops
        when `status` is 2.
        """
        if   self.ievt  > msgmaxnum: return
        elif self.ievt == msgmaxnum:
            message(msg='STOP WARNINGS', metname='', logmethod=logger.warning)
        else:
            message(msg=self.msgelt, metname=sys._getframe().f_code.co_name, logmethod=logger.warning)

        #print('proc_event ievt/nevtot: %d/%d' % (self.ievt, self.nevtot))
        self.status = self.dpo.event(self.odet.raw.raw(self.evt), self.ievt)

    def summary(self):
        """Log the gain modes with constants and the detector's gain modes, and fill `kwa_depl` with metadata.

        The call that would deploy constants is commented out, so nothing is saved.
        """
        message(msg=self.msgelt, metname=sys._getframe().f_code.co_name, logmethod=logger.info)
        gainmodes = [k for k in self.dic_consts_tot.keys()]
        logger.info('constants'\
                   +'\n  created  for gain modes: %s' % str(gainmodes)\
                   +'\n  expected for gain modes: %s' % str(self.odet.raw._gain_modes))

        ctypes = ('pedestals', 'pixel_rms', 'pixel_status', 'pixel_max', 'pixel_min')
        gmodes = self.odet.raw._gain_modes #  or gainmodes
        kwa_depl = self.kwa_depl
        kwa_depl['shape_as_daq'] = None if self.odet.raw is None else self.odet.raw._shape_as_daq()
        kwa_depl['exp']          = self.expname
        kwa_depl['det']          = self.detname
        kwa_depl['run_orig']     = self.runnum

        #deploy_constants(ctypes, gmodes, **kwa_depl)


if __name__ == "__main__":

  def USAGE():
    """Return the usage text of this test, including an example test dataset."""
    import inspect
    return '\n  %s <TNAME>\n' % sys.argv[0].split('/')[-1]\
          +'\n  test dataset: datinfo -k exp=mfxdaq23,run=7,dir=/sdf/data/lcls/drpsrcf/ffb/MFX/mfxdaq23/xtc -d jungfrau'
    #+ '\n'.join([s for s in inspect.getsource(selector).split('\n') if "TNAME in" in s])

  def argument_parser():
    """Return the `ArgumentParser` of this test.

    Options: -o/--dirrepo (default ./work1), -k/--dskwargs (default exp=mfxdaq23,run=7),
    -d/--detname (default jungfrau), -L/--loglevel (default INFO), -s/--subtest, -I/--segind.
    """
    from argparse import ArgumentParser
    d_tname    = '0'
    d_dirrepo  = './work1' # DIR_REPO_JUNGFRAU
    d_dskwargs = 'exp=mfxdaq23,run=7' # dir=/sdf/data/lcls/drpsrcf/ffb/MFX/mfxdaq23/xtc
    d_detname  = 'jungfrau'
    d_loglevel = 'INFO' # 'DEBUG'
    d_subtest  = None
    d_segind   = None
    h_dirrepo  = 'non-default repository of calibration results, default = %s' % d_dirrepo
    h_tname    = 'test name, usually numeric number, default = %s' % d_tname
    h_dskwargs = '(str) dataset kwargs for DataSource(**kwargs), default = %s' % d_dskwargs
    h_detname  = 'detector name, default = %s' % d_detname
    h_subtest  = '(str) subtest name, default = %s' % d_subtest
    h_loglevel = 'logging level, one of %s, default = %s' % (', '.join(tuple(logging._nameToLevel.keys())), d_loglevel)
    h_segind   = 'segment index in det.raw.raw array to process, default = %s' % str(d_segind)
    parser = ArgumentParser(description='%s is a bunch of tests for annual issues' % SCRNAME, usage=USAGE())
    #parser.add_argument('tname',            default=d_tname,    type=str, help=h_tname)
    parser.add_argument('-o', '--dirrepo',  default=d_dirrepo,  type=str, help=h_dirrepo)
    parser.add_argument('-k', '--dskwargs', default=d_dskwargs, type=str, help=h_dskwargs)
    parser.add_argument('-d', '--detname',  default=d_detname,  type=str, help=h_detname)
    parser.add_argument('-L', '--loglevel', default=d_loglevel, type=str, help=h_loglevel)
    parser.add_argument('-s', '--subtest',  default=d_subtest,  type=str, help=h_subtest)
    parser.add_argument('-I', '--segind',   default=d_segind,   type=int, help=h_segind)
    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()
    #tname = args.tname
    print(80*'_')

#    kwa = vars(args)
#    STRLOGLEV = args.loglevel
#    INTLOGLEV = logging._nameToLevel[STRLOGLEV]
#    #logging.basicConfig(format='[%(levelname).1s] L%(lineno)04d %(filename)s: %(message)s', level=INTLOGLEV)
    #print('XXX tname:', tname)

    #evl = EventLoop(parser)
    evl = EventLoopTest(parser)
    evl.open_data_sourse()
    evl.event_loop()

    sys.exit('End of %s' % SCRNAME)

#EOF
