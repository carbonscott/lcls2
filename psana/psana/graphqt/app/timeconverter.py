#!/usr/bin/env python
"""
Created on 2017-06-14 by Mikhail Dubrovin
Adopted for LCLS2 on 2018-02-15
"""

from psana.graphqt.QWDateTimeSec import QWDateTimeSec, QApplication, sys

def timeconverter():
    """Print a start message, show a ``QWDateTimeSec`` widget in a new ``QApplication`` and exit via ``sys.exit('End of app')`` after the event loop."""
    print('Start convertor date and time <-> sec')
    app = QApplication(sys.argv)
    w = QWDateTimeSec()
    w.setWindowTitle('Date and time <-> sec')
    w.show()
    app.exec_()
    del app
    sys.exit('End of app')

if __name__ == "__main__":
    timeconverter()

# EOF


