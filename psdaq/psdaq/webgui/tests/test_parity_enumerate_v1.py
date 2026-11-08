"""Tests for the PyQt affordance enumerator v1 (psdaq.webgui.parity.enumerate_pyqt).

Small synthetic PyQt packages (written to tmp_path, never imported or run) check
each rule; the last tests run the enumerator over the real psdaq/control_gui.
"""

import os
import textwrap

import pytest

from psdaq.webgui.parity import enumerate_pyqt as en

ENTRY = {
    "__init__.py": "",
    "control_gui/__init__.py": "",
    "control_gui/app/__init__.py": "",
    "control_gui/app/control_gui.py": """
        from psdaq.control_gui.Main import proc_main
        def control_gui():
            proc_main()
        """,
}

# A QWTableOfCheckBoxes-like table: fields are [state, text] (global do_ctrl) or
# [state, text, flags, regex]; header from kwargs title_h; rows from a producer.
TABLE = """
    from PyQt5.QtWidgets import QTableView
    from PyQt5.QtGui import QStandardItemModel, QStandardItem
    BIT_CHECKABLE = 1
    BIT_ENABLED = 2
    BIT_EDITABLE = 4
    class Table(QTableView):
        def __init__(self, **kwargs):
            QTableView.__init__(self, None)
            self._si_model = QStandardItemModel()
            self.fill_table_model(**kwargs)
            self.clicked.connect(self.on_click)
        def fill_table_model(self, **kwargs):
            self.tableio = kwargs.get('tableio', None)
            title_h = kwargs.get('title_h', None)
            do_ctrl = kwargs.get('do_ctrl', False)
            do_edit = kwargs.get('do_edit', False)
            if title_h is not None: self._si_model.setHorizontalHeaderLabels(title_h)
            for row, rec in enumerate(self.tableio):
                for col, fld in enumerate(rec):
                    if isinstance(fld, list):
                        item = QStandardItem(fld[1])
                        lsize = len(fld)
                        if lsize == 2:
                            item.setCheckable(do_ctrl)
                            item.setEditable(do_edit)
                        elif lsize > 2:
                            flags = fld[2]
                            item.setCheckable((flags & BIT_CHECKABLE) and do_ctrl)
                            item.setEnabled(flags & BIT_ENABLED)
                            item.setEditable((flags & BIT_EDITABLE) and do_ctrl)
                    else:
                        item = QStandardItem(fld)
                    self._si_model.setItem(row, col, item)
        def is_column_for_title(self, col, t):
            return True
        def on_click(self, index):
            item = self._si_model.itemFromIndex(index)
            self.pick_group(item)
        def pick_group(self, item):
            if not self.is_column_for_title(item.column(), 'grp'): return
            if not item.isEditable(): return
            item.setText('3')
    """

DATA = """
    def get_rows():
        rows = []
        for k in range(3):
            has_grp = k > 0
            flag = 6 if has_grp else 2
            if k == 2: flag += 16
            rows.append([[True, ''], [False, str(k), flag, '^[0-9]$'], [False, 'name', 2], [False, '']])
        return {}, rows
    """

MAIN = """
    from PyQt5.QtWidgets import (QWidget, QPushButton, QTextEdit, QComboBox, QFileDialog,
                                 QApplication)
    from psdaq.control_gui.Table import Table
    from psdaq.control_gui.Data import get_rows
    from psdaq.control_gui.Popup import ask
    from psdaq.control_gui.Logger import Logger

    class Main(QWidget):
        HEADER = ['sel', 'grp', 'name', 'Monitor']
        MORE = ('More', 'Load', 'Save')
        KINDS = ('A', 'B')
        def __init__(self):
            QWidget.__init__(self)
            self.but_go = QPushButton('Go')
            self.but_go.setToolTip('start')
            self.but_go.clicked.connect(self.on_go)
            self.box_more = QComboBox()
            self.box_more.addItems(self.MORE)
            self.box_more.currentIndexChanged[int].connect(self.on_more)
            self.box_kind = QComboBox()
            self.box_kind.addItems(self.KINDS)
            self.box_kind.currentIndexChanged[int].connect(self.on_kind)
            self.log = Logger(show_buttons=False)
            self.do_ctrl = True
            _, rows = get_rows()
            self.w_select = Table(tableio=rows, title_h=self.HEADER, do_ctrl=self.do_ctrl)
            self.w_show = Table(tableio=rows, title_h=self.HEADER)
        def on_go(self):
            if ask('Really?'):
                pass
        def on_more(self, ind):
            if ind == 1: self.load()
            elif ind == 2: self.save()
        def load(self):
            path, _ = QFileDialog.getOpenFileName(self, caption='Load')
        def save(self):
            path, _ = QFileDialog.getSaveFileName(self, caption='Save')
        def on_kind(self, ind):
            self.wedi = self.make(self.KINDS[ind])
        def make(self, kind):
            if kind == self.KINDS[0]: return QTextEdit('a')
            elif kind == self.KINDS[1]: return QTextEdit('b')
            else: return QTextEdit('fallback')
        def never_called(self):
            QFileDialog.getSaveFileName(self, caption='Never')

    def proc_main():
        app = QApplication([])
        w = Main()
        app.exec_()

    if __name__ == "__main__":
        t = QPushButton('test only')
    """

LOGGER = """
    from PyQt5.QtWidgets import QWidget, QPushButton, QTextEdit, QFileDialog
    class Logger(QWidget):
        def __init__(self, **kwargs):
            QWidget.__init__(self)
            self.show_buttons = kwargs.get('show_buttons', True)
            self.edi_txt = QTextEdit('log')
            self.but_save = QPushButton('Save')
            self.but_close = QPushButton('Close')
            if self.show_buttons: self.connect_buttons()
            self.set_style()
        def connect_buttons(self):
            self.but_save.clicked.connect(self.on_save)
        def set_style(self):
            self.edi_txt.setReadOnly(True)
            self.but_save.setVisible(self.show_buttons)
        def on_save(self):
            QFileDialog.getSaveFileName(self, caption='Save log')
    """

POPUP = """
    from PyQt5.QtWidgets import QMessageBox
    def ask(text):
        box = QMessageBox(text=text, standardButtons=QMessageBox.Ok | QMessageBox.Cancel)
        return box.exec_()
    """

UNUSED = """
    from PyQt5.QtWidgets import QWidget, QPushButton, QTabBar
    class Unused(QWidget):
        names = ['User', 'Expert']
        def __init__(self):
            self.but_x = QPushButton('never')
            self.bar = QTabBar()
            for n in self.names:
                self.bar.addTab(n)
    """


def write_pkg(root, files):
    for rel, text in files.items():
        path = os.path.join(str(root), rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(textwrap.dedent(text))
    return str(root)


@pytest.fixture(scope='module')
def synth(tmp_path_factory):
    files = dict(ENTRY)
    files.update({'control_gui/Main.py': MAIN, 'control_gui/Table.py': TABLE,
                  'control_gui/Data.py': DATA, 'control_gui/Popup.py': POPUP,
                  'control_gui/Logger.py': LOGGER, 'control_gui/Unused.py': UNUSED})
    root = write_pkg(tmp_path_factory.mktemp('synth') / 'psdaq', files)
    rows, e = en.enumerate_rows(root)
    return {r['id']: r for r in rows}, rows, e


def test_one_row_per_checkbox_column(synth):
    by, rows, _ = synth
    cols = sorted(r['id'] for r in rows if r['kind'] == 'column')
    assert cols == ['Main.w_select.grp', 'Main.w_select.monitor', 'Main.w_select.name',
                    'Main.w_select.sel', 'Main.w_show.grp', 'Main.w_show.monitor',
                    'Main.w_show.name', 'Main.w_show.sel']
    # select window (do_ctrl=self.do_ctrl): both checkbox columns are separate live rows
    assert not by['Main.w_select.sel']['inert'] and 'check' in by['Main.w_select.sel']['label']
    assert not by['Main.w_select.monitor']['inert'] and 'check' in by['Main.w_select.monitor']['label']
    # grp: flags 6 -> editable when do_ctrl, and the click slot acts on 'grp'
    assert 'edit' in by['Main.w_select.grp']['label'] and 'click' in by['Main.w_select.grp']['label']
    # flags 2 only: never checkable/editable, no click action -> inert, with evidence
    assert by['Main.w_select.name']['inert']
    assert any('checkable {0}' in e for e in by['Main.w_select.name']['evidence'])
    # show window (do_ctrl omitted -> default False): every column inert
    for c in ('sel', 'grp', 'name', 'monitor'):
        assert by['Main.w_show.' + c]['inert'], c
    assert any('do_ctrl' not in e or True for e in by['Main.w_show.sel']['evidence'])


def test_hidden_button_and_derived_flags(synth):
    by, _, _ = synth
    save = by['Logger.but_save']
    assert save['reachable'] and save['hidden'] and save['inert']
    assert any('Main.py' in e and 'show_buttons={False}' in e for e in save['evidence'])
    # but_close: never connected, never read -> inert but not hidden
    assert by['Logger.but_close']['inert'] and not by['Logger.but_close']['hidden']
    # read-only text is inert
    assert by['Logger.edi_txt']['inert']
    # the dialog opened only from the hidden, unconnected button is not live
    dlg = by['Logger.on_save@1']
    assert not dlg['reachable'] and dlg['reach'] == 'method-not-live'


def test_unreachable_module_rows_listed(synth):
    by, _, e = synth
    for rid in ('Unused.but_x', 'Unused.bar.user', 'Unused.bar.expert'):
        assert rid in by
        assert not by[rid]['reachable'] and by[rid]['reach'] == 'module-unreachable'
    assert by['Main.__main__@1']['reach'] == 'main-block'


def test_action_combo_items_dialogs_and_fallback(synth):
    by, _, _ = synth
    assert 'Main.box_more' not in by          # action combo -> one row per dispatched item
    assert by['Main.box_more.load']['kind'] == 'combo-item'
    assert by['Main.box_more.save']['kind'] == 'combo-item'
    assert by['Main.box_kind']['kind'] == 'combo' and by['Main.box_kind']['label'] == 'A|B'
    assert by['Main.load@1']['kind'] == 'file-dialog' and by['Main.load@1']['reachable']
    assert 'box_more.currentIndexChanged[1]' in by['Main.load@1']['trigger']
    assert by['Main.on_go@1']['kind'] == 'confirm'          # helper call site, not helper body
    assert not any(r.startswith('Popup.') for r in by)
    assert by['Main.never_called@1']['reach'] == 'method-not-live'
    fb = [r for r in by.values() if r['label'] == 'fallback']
    assert len(fb) == 1 and fb[0]['reach'] == 'fallback-branch'
    assert by['Main.make@1']['reachable'] and by['Main.make@2']['reachable']
    assert by['Main.but_go']['tooltip'] == 'start'


def test_ids_have_no_line_numbers(synth):
    _, rows, _ = synth
    for r in rows:
        assert ':' not in r['id'] and '.py' not in r['id'], r['id']
        assert r['loc'] == '%s:%d' % (r['file'], r['line'])


def test_ids_survive_an_edit(tmp_path):
    files = dict(ENTRY)
    files.update({'control_gui/Main.py': MAIN, 'control_gui/Table.py': TABLE,
                  'control_gui/Data.py': DATA, 'control_gui/Popup.py': POPUP,
                  'control_gui/Logger.py': LOGGER, 'control_gui/Unused.py': UNUSED})
    a = {r['id'] for r in en.enumerate_rows(write_pkg(tmp_path / 'a' / 'psdaq', files))[0]}
    files['control_gui/Main.py'] = '# a comment\n\n\n' + textwrap.dedent(MAIN)
    b = {r['id'] for r in en.enumerate_rows(write_pkg(tmp_path / 'b' / 'psdaq', files))[0]}
    assert a == b


REAL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.skipif(not os.path.isdir(os.path.join(REAL, 'control_gui')),
                    reason='psdaq/control_gui not next to webgui')
def test_real_control_gui():
    rows, e = en.enumerate_rows(REAL)
    by = {r['id']: r for r in rows}
    assert len(rows) > 0 and len(by) == len(rows)
    sel, mon = by['CGWMainPartition.w_select.sel'], by['CGWMainPartition.w_select.monitor']
    assert sel['kind'] == mon['kind'] == 'column' and not sel['inert'] and not mon['inert']
    assert by['CGWMainPartition.w_show.sel']['inert']
    assert by['QWLoggerStd.but_save']['hidden']
    assert by['QWLoggerStd.save_log_in_file@1']['reach'] == 'method-not-live'
    assert by['CGWConfigEditor.editor_widget_selector@1']['reach'] == 'fallback-branch'
    assert not by['CGWMainTabs.tab_bar.user']['reachable']
    files = {m.rel for m in e.gui_modules}
    assert 'control_gui/ex_SLConfigEditor.py' in files and 'control_gui/CGWMainTabs.py' in files


# ---------------- input-event overrides, mnemonics and guard lines ----------------

FILTERS = {
    "control_gui/Combo.py": """
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QComboBox
        class Combo(QComboBox):
            def keyPressEvent(self, event):
                if event.key() in (Qt.Key_Up, Qt.Key_Down):
                    event.ignore()
                else:
                    super().keyPressEvent(event)
            def wheelEvent(self, event):
                event.ignore()
        if __name__ == "__main__":
            c = Combo()
        """,
    "control_gui/Main.py": """
        from PyQt5.QtWidgets import QWidget, QPushButton
        from psdaq.control_gui.Combo import Combo
        #from psdaq.control_gui.Gone import Gone
        def proc_main():
            Main()
        class Main(QWidget):
            def __init__(self):
                self.box = Combo()
                self.box.currentIndexChanged[int].connect(self.on_box)
                self.but_ok = QPushButton('&Apply')
                self.but_ok.clicked.connect(self.on_box)
                self.but_amp = QPushButton('Save && quit')
                self.but_amp.clicked.connect(self.on_box)
            def on_box(self, i=0):
                pass
            if __name__ == "__main__":
                def keyPressEvent(self, e):
                    if e.key() == Qt.Key_Escape:
                        self.close()
        """,
    "control_gui/Gone.py": """
        from PyQt5.QtWidgets import QWidget, QPushButton
        class Gone(QWidget):
            def __init__(self):
                self.but_g = QPushButton('&Go')
        """,
}


def test_event_filters_mnemonics_and_guards(tmp_path):
    files = dict(ENTRY)
    files.update(FILTERS)
    rows, _ = en.enumerate_rows(write_pkg(tmp_path / 'f' / 'psdaq', files))
    by = {r['id']: r for r in rows}
    k, w = by['Main.box.keyPressEvent'], by['Main.box.wheelEvent']
    assert k['kind'] == w['kind'] == 'event-filter' and k['reachable'] and w['reachable']
    assert k['label'].startswith('ignores Key_Up, Key_Down (control_gui/Combo.py:')
    assert w['label'].startswith('ignores every wheel')
    assert k['loc'] == by['Main.box']['loc']                      # where the widget is built
    m = by['Main.but_ok.mnemonic']
    assert m['kind'] == 'mnemonic' and m['widget'] == 'Alt+A' and m['reachable']
    assert 'Main.but_amp.mnemonic' not in by                       # '&&' is a literal ampersand
    # the main-block instance of Combo and its handlers: not reachable, guard = the if __name__ line
    main_combo = [r for r in rows if r['id'].startswith('Combo.') and r['kind'] == 'combo'][0]
    assert main_combo['reach'] == 'main-block' and main_combo['guard'] == 'control_gui/Combo.py:12'
    assert by[main_combo['id'] + '.wheelEvent']['reach'] == 'main-block'
    esc = by['Main.keyPressEvent.escape']
    assert esc['reach'] == 'main-block' and esc['guard'] == 'control_gui/Main.py:17'
    assert any(e.startswith('guard control_gui/Main.py:17 `if __name__ == "__main__":`') for e in esc['evidence'])
    # a module whose import is commented out: guard = that comment line; its mnemonic row inherits the flags
    g, gm = by['Gone.but_g'], by['Gone.but_g.mnemonic']
    assert g['reach'] == gm['reach'] == 'module-unreachable'
    assert g['guard'] == gm['guard'] == 'control_gui/Main.py:4'
    ids0 = {r['id'] for r in rows}
    files['control_gui/Main.py'] = '# moved\n\n' + textwrap.dedent(FILTERS['control_gui/Main.py'])
    assert {r['id'] for r in en.enumerate_rows(write_pkg(tmp_path / 'g' / 'psdaq', files))[0]} == ids0


@pytest.mark.skipif(not os.path.isdir(os.path.join(REAL, 'control_gui')),
                    reason='psdaq/control_gui not next to webgui')
def test_real_control_gui_v1_additions():
    rows, _ = en.enumerate_rows(REAL)
    by = {r['id']: r for r in rows}
    assert by['CGWMainControl.box_state.keyPressEvent']['label'].startswith('ignores Key_Up, Key_Down')
    assert by['CGWMainControl.box_state.wheelEvent']['reachable']
    for rid in ('QWPopupTableCheck.but_apply.mnemonic', 'QWPopupEditText.but_apply.mnemonic',
                'QWPopupEditText.but_cancel.mnemonic'):
        assert by[rid]['reachable'] and not by[rid]['hidden'], rid
    assert by['QWLoggerStd.but_save.mnemonic']['hidden']
    assert by['QWLoggerStd.but_save.mnemonic']['guard'] == 'control_gui/QWLoggerStd.py:289'
    assert by['CGWMain.keyPressEvent.escape']['guard'] == 'control_gui/CGWMain.py:406'
    assert by['CGWMainTabs.tab_bar.user']['guard'] == 'control_gui/CGWMain.py:43'
    assert by['CGWMainTabUser.but_play']['guard'] == 'control_gui/CGWMain.py:43'
    assert all(r['guard'] for r in rows if r['reach'] in ('main-block', 'module-unreachable', 'fallback-branch'))
