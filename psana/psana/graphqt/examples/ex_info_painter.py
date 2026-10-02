#!/usr/bin/env python

"""Example: show a QGraphicsView with marked scene and origin rects and print the shape, type, rect, position and bounding rect of a QGraphicsRectItem.

The Qt application and event loop run at import time.
"""
import sys
from PyQt5.QtWidgets import QApplication, QGraphicsScene, QGraphicsView, QGraphicsRectItem
from PyQt5.QtCore import Qt, QPoint, QSize, QRectF
from PyQt5.QtGui import QColor, QPen, QBrush, QPolygonF, QPixmap, QImage

app = QApplication(sys.argv)

rs = QRectF(0, 0, 100, 100)
ro = QRectF(-1, -1, 5, 5)
s = QGraphicsScene(rs)
v = QGraphicsView(s)
v.setGeometry(20, 20, 600, 600)

print('screenGeometry():', app.desktop().screenGeometry())
print('scene rect=', s.sceneRect())

v.fitInView(rs, Qt.KeepAspectRatio) # Qt.IgnoreAspectRatio Qt.KeepAspectRatioByExpanding

s.addRect(rs, pen=QPen(Qt.black, 0, Qt.SolidLine), brush=QBrush(Qt.yellow))
s.addRect(ro, pen=QPen(Qt.black, 0, Qt.SolidLine), brush=QBrush(Qt.red))

r = QRectF(5, 5, 10, 10)
item = QGraphicsRectItem(r)
#item.show()

print('XXXX QGraphicsRectItem')
#print('XXXX', dir(item))
print('XXXX shape:', item.shape())
print('XXXX type:', item.type())
print('XXXX rect:', item.rect())
print('XXXX pos:', item.pos())
print('XXXX boundingRect:', item.boundingRect())

v.setWindowTitle('My window')
v.setContentsMargins(0,0,0,0)
v.show()
app.exec_()

del app

# EOF
