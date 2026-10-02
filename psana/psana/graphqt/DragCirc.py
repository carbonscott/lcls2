
"""
Class :py:class:`DragCirc` - for draggable circle
===================================================

Created on 2016-10-09 by Mikhail Dubrovin
"""

from psana.graphqt.DragPoint import *


class DragCirc(DragBase):

    """Stub draggable-circle class derived from ``DragBase``.

    The constructor calls ``DragBase.__init__(self, view, points)`` with names that are not defined in
    this module, so instantiation raises NameError.
    """
    def __init__(self):
        DragBase.__init__(self, view, points)


if __name__ == "__main__":
    print('Self test is not implemented...\nuse > python FWViewImageShapes.py')

# EOF
