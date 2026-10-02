"""
Usage::
        from Detector.UtilsLogging import logging, DICT_NAME_TO_LEVEL, STR_LEVEL_NAMES, init_logger
        logger = logging.getLogger(__name__)
        init_logger(loglevel='DEBUG', logfname=None)
"""

import logging
logger = logging.getLogger(__name__)
DICT_NAME_TO_LEVEL = {k:v for k,v in logging._levelNames.iteritems() if isinstance(k, str)}
STR_LEVEL_NAMES = ', '.join(DICT_NAME_TO_LEVEL.keys())

#logging.basicConfig(format='[%(levelname).1s] L%(lineno)04d %(filename)s %(message)s', level=logging.INFO)
#logging.basicConfig(format='[%(levelname).1s] L%(lineno)04d %(message)s', level=logging.INFO)

def init_logger(loglevel='DEBUG', logfname=None):
    """Set the root logger level to ``loglevel`` and add a stdout handler and, if ``logfname`` is given, a file handler, both with the format '[L] Lnnnn message'.

    The module-level ``DICT_NAME_TO_LEVEL`` is built with Python-2 ``logging._levelNames.iteritems()``, so importing this module fails in Python 3 before this function can be called.
    """
    import sys

    int_loglevel = DICT_NAME_TO_LEVEL[loglevel.upper()]

    logger = logging.getLogger()
    logger.setLevel(int_loglevel) # logging.DEBUG
    formatter = logging.Formatter('[%(levelname).1s] L%(lineno)04d %(message)s')

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(int_loglevel)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    if logfname is not None:
        file_handler = logging.FileHandler(logfname) #'log-in-file-test.log'
        file_handler.setLevel(int_loglevel) # logging.DEBUG
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

# EOF
