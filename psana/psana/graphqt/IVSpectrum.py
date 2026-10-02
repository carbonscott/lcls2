
"""Class :py:class:`IVSpectrum` is a QWidget with histogram, two axes, and color bar
====================================================================================

Usage ::

    # Run test: python lcls2/psana/psana/graphqt/IVSpectrum.py

    from psana.graphqt.IVSpectrum import IVSpectrum
    w = IVSpectrum()

Created on 2021-06-22 by Mikhail Dubrovin
"""
import logging
logger = logging.getLogger(__name__)

from psana.graphqt.FWViewHist import FWViewHist, test_histogram
from psana.graphqt.FWViewAxis import FWViewAxis
from psana.graphqt.FWViewColorBar import FWViewColorBar
import psana.graphqt.ColorTable as ct
from PyQt5.QtWidgets import QWidget, QGridLayout, QPushButton, QTextEdit
from PyQt5.QtCore import Qt, pyqtSignal, QRectF
from psana.pyalgos.generic.NDArrGenerators import test_image
from psana.graphqt.CMConfigParameters import cp


class IVSpectrum(QWidget):
    """QWidget for Image Viewer"""
    histogram_scene_rect_changed = pyqtSignal('QRectF')

    def __init__(self, **kwargs):

        parent= kwargs.get('parent', None)
        image = kwargs.get('image', test_image())
        ctab  = kwargs.get('ctab', ct.color_table_default())
        nbins = kwargs.get('nbins', 1000)
        amin  = kwargs.get('amin', None)
        amax  = kwargs.get('amax', None)
        frmin = kwargs.get('frmin', 0.001)
        frmax = kwargs.get('frmax', 0.999)
        edgemode = kwargs.get('edgemode', 0)
        signal_fast = kwargs.get('signal_fast', True)

        QWidget.__init__(self, parent)

        cp.ivspectrum = self

        self.rs_old = None
        rs=QRectF(0, 0, 100, 1000)
        self.whis = FWViewHist(self, rs, origin='DR', scale_ctl='V', fgcolor='yellow', bgcolor='dark', orient='V', signal_fast=signal_fast, hbins=None)
        self.whis.set_histogram_from_arr(image, nbins, amin, amax, frmin, frmax, edgemode, update_hblimits=True)

        self.wcbar = FWViewColorBar(self, coltab=ctab, orient='V')

        r = self.whis.sceneRect()
        rscx = QRectF(r.x(), 0, r.width(), 1)
        rscy = QRectF(0, r.y(), 1, r.height())

        self.wax = FWViewAxis(None, rscx, side='U', origin='UR', scale_ctl=True, wwidth=30, wlength=200, signal_fast=signal_fast)
        self.way = FWViewAxis(None, rscy, side='L', origin='DL', scale_ctl=True, wwidth=60, wlength=200, signal_fast=signal_fast)

        self.but_reset = QPushButton('Reset')
        self.edi_info = QTextEdit('Info')

        self.box = QGridLayout()
        self.box.setSpacing(0)
        self.box.setVerticalSpacing(0)
        self.box.setHorizontalSpacing(0)
        self.box.addWidget(self.edi_info,   0,  0,  1, 11)
        self.box.addWidget(self.way,        1, 10,  9,  1)
        self.box.addWidget(self.whis,       1,  0,  9,  9)
        self.box.addWidget(self.wax,       10,  0,  1,  9)
        self.box.addWidget(self.wcbar,      1,  9,  9,  1)
        self.box.addWidget(self.but_reset, 10,  9,  1,  2, alignment=Qt.AlignCenter)
        self.setLayout(self.box)

        self.set_tool_tips()
        self.set_style()

        self.connect_scene_rect_changed()
        self.but_reset.clicked.connect(self.on_but_reset)


    def set_signal_fast(self, is_fast=True):
        """Set the ``signal_fast`` attribute of the histogram view and both axis views to ``is_fast``."""
        self.whis.signal_fast = is_fast
        self.wax.signal_fast = is_fast
        self.way.signal_fast = is_fast


    def connect_scene_rect_changed(self):
        """Connect the scene-rect-changed signals of ``whis``, ``wax`` and ``way`` to their ``on_*_scene_rect_changed`` slots."""
        self.whis.connect_scene_rect_changed(self.on_whis_scene_rect_changed)
        self.wax.connect_scene_rect_changed(self.on_wax_scene_rect_changed)
        self.way.connect_scene_rect_changed(self.on_way_scene_rect_changed)


    def disconnect_scene_rect_changed(self):
        """Disconnect the scene-rect-changed signals of ``whis``, ``wax`` and ``way`` from their ``on_*_scene_rect_changed`` slots."""
        self.whis.disconnect_scene_rect_changed(self.on_whis_scene_rect_changed)
        self.wax.disconnect_scene_rect_changed(self.on_wax_scene_rect_changed)
        self.way.disconnect_scene_rect_changed(self.on_way_scene_rect_changed)


    def on_but_reset(self):
        """Call ``reset_original_size()`` on the histogram view and both axis views."""
        logger.debug('on_but_reset')
        self.whis.reset_original_size()
        self.wax.reset_original_size()
        self.way.reset_original_size()


    def on_whis_scene_rect_changed(self, r):
        #logger.debug('on_whis_scene_rect_changed: %s'%str(r))
        """Set the axis views to the x and y ranges of rect ``r``, update the info box and emit the histogram signal if the rect changed."""
        self.wax.set_view(rs=QRectF(r.x(), 0, r.width(), 1))
        self.way.set_view(rs=QRectF(0, r.y(), 1, r.height()))
        self.update_info()
        self.emit_signal_if_histogram_scene_rect_changed()


    def on_wax_scene_rect_changed(self, r):
        #logger.debug('on_wax_scene_rect_changed: %s'%str(r))
        """Emit the histogram signal if the rect changed, then set the histogram view to the x range of ``r`` (keeping its y range).

        The signal check runs before the view is updated.
        """
        rs = self.whis.scene().sceneRect()
        self.emit_signal_if_histogram_scene_rect_changed()
        self.whis.set_view(rs=QRectF(r.x(), rs.y(), r.width(), rs.height()))


    def on_way_scene_rect_changed(self, r):
        #logger.debug('on_way_scene_rect_changed: %s'%str(r))
        """Set the histogram view to the y range of ``r`` (keeping its x range), update the info box and emit the histogram signal if changed."""
        rs = self.whis.scene().sceneRect()
        self.whis.set_view(rs=QRectF(rs.x(), r.y(), rs.width(), r.height()))
        self.update_info()
        self.emit_signal_if_histogram_scene_rect_changed()


    def emit_signal_if_histogram_scene_rect_changed(self):
        """Checks if scene rect have changed and submits signal with new rect.
        """
        rs = self.whis.scene().sceneRect()
        if rs != self.rs_old:
            self.rs_old = rs
            self.histogram_scene_rect_changed.emit(rs)


    def connect_histogram_scene_rect_changed(self, recip):
        """Connect the ``histogram_scene_rect_changed`` signal to ``recip``."""
        self.histogram_scene_rect_changed.connect(recip)


    def disconnect_histogram_scene_rect_changed(self, recip):
        """Disconnect the ``histogram_scene_rect_changed`` signal from ``recip``."""
        self.histogram_scene_rect_changed.disconnect(recip)


    def update_info(self):
        """Show the visible value range and histogram statistics in the info box.

        Statistics (entries, bin range, mean, rms with errors, skew, kurtosis) are added only if
        ``whis.hbins`` is not None and ``histogram_statistics(vmin, vmax)`` returns a result.
        """
        hb = self.whis.hbins
        r = self.whis.scene().sceneRect()
        vmin, vmax = r.y(), r.y()+r.height()
        s = 'spectrum min: %d max: %d' % (vmin, vmax)
        if hb is not None:
          resp = hb.histogram_statistics(vmin, vmax)
          if resp is not None:
            mean, rms, err_mean, err_rms, neff, skew, kurt, err_err, sum_w, ibeg, iend = resp
            s += '\nentries: %d  nbins: %d [%d:%d]' % (sum_w, iend-ibeg, ibeg, iend)\
              + u'\nmean: %.3f \u00B1 %.3f\nrms: %.3f \u00B1 %.3f' % (mean, err_mean, rms, err_rms)\
              + u'\n\u03B31 skew: %.3f  \u03B32 kurt: %.3f' % (skew, kurt)
        self.edi_info.setText(s)


    def set_tool_tips(self):
        """Set tool tips on the histogram, axes, info box, Reset button and color bar."""
        self.whis.setToolTip('Spectral intensity\ndistribution')
        self.wax.setToolTip('Spectral\nintensity')
        self.way.setToolTip('Spectral\nvalue')
        self.edi_info.setToolTip('Spectral statistics')
        self.but_reset.setToolTip('Reset to default\nspectrum')
        self.wcbar.setToolTip('Color bar for color\nto intensity conversion\nclick on it to select another')


    def set_style(self):
        """Set zero margins, color-bar width 25 and maximum info-box height 80."""
        self.layout().setContentsMargins(0,0,0,0)
        self.wcbar.setFixedWidth(25)
        self.edi_info.setMaximumHeight(80)


    def set_spectrum_from_arr(self, arr, nbins=1000, amin=None, amax=None, frmin=0.001, frmax=0.999, edgemode=0, update_hblimits=True):
        """shotcut"""
        self.whis.set_histogram_from_arr(arr, nbins, amin, amax, frmin, frmax, edgemode, update_hblimits)


    def reset_original_size(self):
        """shortcut to whis.reset_original_size"""
        #logger.debug('reset_original_size')
        self.whis.reset_original_size()


    def closeEvent(self, e):
        """Pass the event to ``QWidget.closeEvent`` and set ``cp.ivspectrum`` to None."""
        logger.debug('closeEvent')
        QWidget.closeEvent(self, e)
        cp.ivspectrum = None


    if __name__ == "__main__":

      def key_usage(self):
        """Return a help string listing keys ESC, R and N (defined only when run as a script)."""
        return 'Keys:'\
               '\n  ESC - exit'\
               '\n  R - reset original size'\
               '\n  N - set new spectrum'\
               '\n'


      def keyPressEvent(self, e):
        """Handle keys: Escape closes, R resets the original size, N sets a spectrum from a new 500x500 test image; others print :meth:`key_usage`.

        Defined only when the module is run as ``__main__``.
        """
        print('keyPressEvent key=%s' % e.key())
        if   e.key() == Qt.Key_Escape:
            print('Close app')
            self.close()

        elif e.key() == Qt.Key_R:
            print('Reset original size')
            self.reset_original_size()

        elif e.key() == Qt.Key_N:
            print('Set new histogram')
            a = test_image(shape=(500,500))
            self.set_spectrum_from_arr(a)

        else:
            print(self.key_usage())


if __name__ == "__main__":
    import os
    import sys
    os.environ['LIBGL_ALWAYS_INDIRECT'] = '1' #export LIBGL_ALWAYS_INDIRECT=1
    from PyQt5.QtWidgets import QApplication

    logging.basicConfig(format='[%(levelname).1s] L%(lineno)04d %(name)s : %(message)s', level=logging.DEBUG)

    app = QApplication(sys.argv)
    w = IVSpectrum()
    w.setGeometry(100, 50, 300, 800)
    w.setWindowTitle('Image with two axes')
    w.show()
    app.exec_()
    del w
    del app

# EOF
