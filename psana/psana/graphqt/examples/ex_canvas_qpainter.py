#!/usr/bin/env python

"""Example: draw free-hand lines with ``QPainter`` on a ``QLabel`` pixmap, with a row of color buttons.

The ``QApplication`` and ``MainWindow`` are created and shown at import time (there is no
``__main__`` guard). ``Canvas`` is defined twice with identical bodies; the second definition is the one used.
"""
import sys
from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtCore import Qt

COLORS = [
# 17 undertones https://lospec.com/palette-list/17undertones
'#000000', '#141923', '#414168', '#3a7fa7', '#35e3e3', '#8fd970', '#5ebb49',
'#458352', '#dcd37b', '#fffee5', '#ffd035', '#cc9245', '#a15c3e', '#a42f3b',
'#f45b7a', '#c24998', '#81588d', '#bcb0c2', '#ffffff',
]

class QPaletteButton(QtWidgets.QPushButton):

    """24x24 ``QPushButton`` whose background is set to ``color``; the color string is kept in ``self.color``."""
    def __init__(self, color):
        super().__init__()
        self.setFixedSize(QtCore.QSize(24,24))
        self.color = color
        self.setStyleSheet("background-color: %s;" % color)

class Canvas(QtWidgets.QLabel):

    """``QLabel`` showing a white 600x300 pixmap on which mouse drags draw lines (first definition; shadowed by the second)."""
    def __init__(self):
        super().__init__()
        pixmap = QtGui.QPixmap(600, 300)
        pixmap.fill(Qt.white)
        self.setPixmap(pixmap)

        self.last_x, self.last_y = None, None
        self.pen_color = QtGui.QColor('#000000')

    def set_pen_color(self, c):
        """Set ``self.pen_color`` to ``QColor(c)``."""
        self.pen_color = QtGui.QColor(c)

    def mouseMoveEvent(self, e):
        """Draw a 4-pixel line in ``pen_color`` from the last mouse position to the current one on the pixmap.

        On the first move after a release only the position is stored and nothing is drawn.
        """
        if self.last_x is None: # First event.
            self.last_x = e.x()
            self.last_y = e.y()
            return # Ignore the first time.

        painter = QtGui.QPainter(self.pixmap())
        p = painter.pen()
        p.setWidth(4)
        p.setColor(self.pen_color)
        painter.setPen(p)
        painter.drawLine(self.last_x, self.last_y, e.x(), e.y())
        painter.end()
        self.update()

        # Update the origin for next time.
        self.last_x = e.x()
        self.last_y = e.y()

    def mouseReleaseEvent(self, e):
        """Reset the stored last mouse position to None so the next drag starts a new line."""
        self.last_x = None
        self.last_y = None

class Canvas(QtWidgets.QLabel):

    """``QLabel`` showing a white 600x300 pixmap on which mouse drags draw lines (this definition replaces the first one)."""
    def __init__(self):
        super().__init__()
        pixmap = QtGui.QPixmap(600, 300)
        pixmap.fill(Qt.white)
        self.setPixmap(pixmap)

        self.last_x, self.last_y = None, None
        self.pen_color = QtGui.QColor('#000000')

    def set_pen_color(self, c):
        """Set ``self.pen_color`` to ``QColor(c)``."""
        self.pen_color = QtGui.QColor(c)

    def mouseMoveEvent(self, e):
        """Draw a 4-pixel line in ``pen_color`` from the last mouse position to the current one on the pixmap.

        On the first move after a release only the position is stored and nothing is drawn.
        """
        if self.last_x is None: # First event.
            self.last_x = e.x()
            self.last_y = e.y()
            return # Ignore the first time.

        painter = QtGui.QPainter(self.pixmap())
        p = painter.pen()
        p.setWidth(4)
        p.setColor(self.pen_color)
        painter.setPen(p)
        painter.drawLine(self.last_x, self.last_y, e.x(), e.y())
        painter.end()
        self.update()

        # Update the origin for next time.
        self.last_x = e.x()
        self.last_y = e.y()

    def mouseReleaseEvent(self, e):
        """Reset the stored last mouse position to None so the next drag starts a new line."""
        self.last_x = None
        self.last_y = None

class MainWindow(QtWidgets.QMainWindow):

    """``QMainWindow`` whose central widget holds a ``Canvas`` above a row of palette buttons."""
    def __init__(self):
        super().__init__()

        self.canvas = Canvas()

        w = QtWidgets.QWidget()
        l = QtWidgets.QVBoxLayout()
        w.setLayout(l)
        l.addWidget(self.canvas)

        palette = QtWidgets.QHBoxLayout()
        self.add_palette_buttons(palette)
        l.addLayout(palette)

        self.setCentralWidget(w)


    def add_palette_buttons(self, layout):
        """Add one ``QPaletteButton`` per entry of ``COLORS`` to ``layout``; pressing a button sets the canvas pen color."""
        for c in COLORS:
            b = QPaletteButton(c)
            b.pressed.connect(lambda c=c: self.canvas.set_pen_color(c))
            layout.addWidget(b)

app = QtWidgets.QApplication(sys.argv)
window = MainWindow()
window.show()
app.exec_()

# EOF
