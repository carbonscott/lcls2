# min_gc.py: dtica's statistics rows lose their PV monitors to Python's garbage collector (no PV server needed)
import gc
from PyQt5 import QtWidgets
from psdaq.cas import pvedit

app = QtWidgets.QApplication([])
table = pvedit.PvIntTable('Upstream Link Stats', 'TEST:DTI:3:', ['UsWrFifoD', 'UsRdFifoD'], ['FifoWr', 'FifoRd'], 7)
count = lambda cls: sum(isinstance(o, cls) for o in gc.get_objects())
print('PvIntRow monitors before gc.collect():', count(pvedit.PvIntRow))
gc.collect()
print('PvIntRow monitors after  gc.collect():', count(pvedit.PvIntRow), '(the table still shows', len(table.findChildren(QtWidgets.QLabel)), 'labels)')
