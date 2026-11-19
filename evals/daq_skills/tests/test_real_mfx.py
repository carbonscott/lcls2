"""Tests for real_mfx.py on a synthetic MFX-shaped tree.  No S3DF, no model.

    python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import real_mfx as rm  # noqa: E402

HAVE_ZSTD = shutil.which('zstd') is not None
CUR = 'home/m/mfxopr/daq/logs'
PREV = 'home/m/mfxopr'


def control(day, lines, month='2026-09'):
    """control.log text: a header, then (time, level, who, msg) lines."""
    out = ['# ID:      control', '# PLATFORM:0', '']
    for t, lvl, who, msg in lines:
        out.append('%s-%s %s,100 mfx:0-%s[4242]: <%s> %s' % (month, day, t, who, lvl, msg))
    return '\n'.join(out) + '\n'


def states(*names, t='10:00:05'):
    return [(t, 'I', 'core', 'Finished processing state %s enter callbacks.' % s) for s in names]


HEALTHY = states('unallocated', 'allocated', 'connected', 'configured', 'starting', 'paused', 'running') + [
    ('10:00:06', 'W', 'control', "epics_0: Number of PVs that didn't connect: 5 (of 300)"),
    ('11:30:00', 'I', 'control', 'slowupdate transitions DISABLED')]
FAILED = states('unallocated', t='20:00:09') + [
    ('20:00:40', 'E', 'control', 'jungfrau_0 did not respond to alloc'),
    ('20:00:40', 'E', 'control', '1 client did not respond to alloc'),
    ('20:00:40', 'E', 'control', 'alloc failed to change state'),
    ('20:10:00', 'E', 'control', 'timing_1 did not respond to disable phase 2')]
TWO = states('unallocated', t='09:00:09') + [
    ('09:00:40', 'E', 'control', 'jungfrau_0 did not respond to alloc'),
    ('09:00:40', 'E', 'control', 'jungfrau_1 did not respond to alloc')]


def jload(path):
    with open(path) as f:
        return json.load(f)


def jsave(obj, path):
    with open(path, 'w') as f:
        json.dump(obj, f)


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write(text)
    return p


def make_tree(root):
    """previous tree: a healthy launch on 09-16 10:00.  current tree: a failing launch on 09-18 20:00
    with a hand restart of jungfrau_0 at 20:05, a two-component failure on 09-20 09:00, and a healthy
    launch on 09-30 23:50 whose hand restart lands in the next month."""
    write(root, PREV + '/2026/09/16_10:00:00_drp-srcf-cmp014:control.log', control('16', HEALTHY))
    write(root, PREV + '/2026/09/16_10:00:00_drp-srcf-cmp014:teb0.log', 'mfx-teb[1]: <I> ok\n')
    write(root, PREV + '/2026/09/16_10:00:00_drp-srcf-cmp033:jungfrau_0.log',
          'mfx-drp[1]: <C> Inadequate RTPRIO limit: got 0, require 1\n'
          "srun: error: drp-srcf-cmp033: task 0: Aborted (core dumped)\n")
    write(root, CUR + '/2026/09/18_20:00:00_drp-srcf-cmp014:control.log', control('18', FAILED))
    write(root, CUR + '/2026/09/18_20:00:00_drp-srcf-cmp033:jungfrau_0.log',
          '- 20:00:30.000 ERROR: ClientSocket: Cannot connect to Detector:mfx-jungfrau4m-0 on port 2015\n'
          'Traceback (most recent call last):\n  File "x.py", line 1\nRuntimeError: boom\n')
    write(root, CUR + '/2026/09/18_20:00:00_drp-srcf-cmp042:timing_1.log', 'mfx-drp[1]: <I> fine\n')
    write(root, CUR + '/2026/09/18_20:05:00_drp-srcf-cmp033:jungfrau_0.log', 'mfx-drp[1]: <E> again\n')
    write(root, CUR + '/2026/09/20_09:00:00_drp-srcf-cmp014:control.log', control('20', TWO))
    write(root, CUR + '/2026/09/20_09:00:00_drp-srcf-cmp033:jungfrau_0.log', 'mfx-drp[1]: <E> x\n')
    write(root, CUR + '/2026/09/20_09:00:00_drp-srcf-cmp032:jungfrau_1.log', 'mfx-drp[1]: <E> y\n')
    late = [(t.replace('10:', '23:'), l, w, m) for t, l, w, m in HEALTHY[:-1]]
    write(root, CUR + '/2026/09/30_23:50:00_drp-srcf-cmp014:control.log', control('30', late))
    write(root, CUR + '/2026/10/01_00:20:00_drp-srcf-cmp042:timing_1.log', 'mfx-drp[1]: <I> back\n')
    write(root, PREV + '/2026/09/notes.txt', 'not a log\n')


CASES = {'cases': [
    {'id': 'syn-fail', 'today': '2026-09-19', 'phrase': 'yesterday evening', 'target': 'current/2026/09/18_20:00:00',
     'keyed_launches': ['current/2026/09/18_20:00:00']},
    {'id': 'syn-old', 'today': '2026-09-17', 'phrase': 'yesterday morning', 'target': 'previous/2026/09/16_10:00:00',
     'keyed_launches': ['previous/2026/09/16_10:00:00']}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, 'root')
        make_tree(self.root)
        self.cases = os.path.join(self.tmp, 'cases.json')
        jsave(CASES, self.cases)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = rm.main(list(argv))
        return rc, buf.getvalue()

    def inv(self):
        return {i['id']: i for i in rm.inventory(self.root, rm.dt.datetime(2026, 9, 1), rm.dt.datetime(2026, 10, 2))}


class Inventory(Base):
    def test_launches_come_from_both_trees_in_time_order(self):
        self.assertEqual(list(self.inv()), ['previous/2026/09/16_10:00:00', 'current/2026/09/18_20:00:00',
                                            'current/2026/09/20_09:00:00', 'current/2026/09/30_23:50:00'])

    def test_hand_restart_is_attached_to_the_launch_before_it(self):
        inv = self.inv()
        self.assertEqual(inv['current/2026/09/18_20:00:00']['restarts'], ['18_20:05:00_drp-srcf-cmp033:jungfrau_0.log'])
        self.assertEqual(inv['current/2026/09/30_23:50:00']['restarts'], ['../10/01_00:20:00_drp-srcf-cmp042:timing_1.log'])

    def test_end_is_the_last_control_line(self):
        self.assertEqual(self.inv()['current/2026/09/18_20:00:00']['end'], '2026-09-18T20:10:00')

    def test_classes_per_component(self):
        c = self.inv()['current/2026/09/18_20:00:00']['classes']
        self.assertEqual(c['no_response'], {'control': 3})
        self.assertEqual(c['state_failed'], {'control': 1})
        self.assertEqual(c['traceback'], {'jungfrau_0': 1})
        h = self.inv()['previous/2026/09/16_10:00:00']
        self.assertEqual(h['classes'], {'pv_connect': {'control': 1}, 'crash': {'jungfrau_0': 1}})
        self.assertEqual(h['severe'], {})   # RTPRIO <C> lines are not counted

    def test_component_key_needs_one_named_component_with_its_own_error(self):
        k = self.inv()['current/2026/09/18_20:00:00']['key']['component']
        self.assertEqual((k['component'], k['stage'], k['kind'], k['mechanism']),
                         ('jungfrau_0', 'alloc', 'no_response', 'detector-socket-connect'))
        two = self.inv()['current/2026/09/20_09:00:00']['key']
        self.assertEqual((two['component'], two['named']), ('not keyed', ['jungfrau_0', 'jungfrau_1']))

    def test_specific_mechanism_beats_the_traceback_before_it(self):
        p = write(self.root, 'x/t.log', 'Traceback (most recent call last):\n  File "a.py"\n'
                  'RuntimeError: Illegal XPM Remote link id. Try TxPllReset.\nmfx-drp[1]: <C> **** python error\n')
        self.assertEqual(rm.scan_file(p)['mechanism'], 'xpm-remote-link-id')

    def test_healthy_launch(self):
        k = self.inv()['previous/2026/09/16_10:00:00']['key']
        self.assertEqual(k['component'], 'healthy')
        self.assertEqual((k['inventory']['failed'], k['inventory']['n_running']), (False, 1))

    def test_normal_stop_is_not_a_crash(self):
        self.assertIsNone(rm.classify('jungfrau cleaning up on signal: Terminated'))
        self.assertEqual(rm.classify('jungfrau cleaning up on signal: Aborted'), 'crash')
        self.assertEqual(rm.classify('epix100 received signal: Aborted'), 'crash')
        self.assertIsNone(rm.classify('[x] error: *** JOB 1 ON h CANCELLED AT t DUE to SIGNAL Terminated ***'))

    def test_failure_ignores_later_stages_for_the_key(self):
        f = self.inv()['current/2026/09/18_20:00:00']['failure']
        self.assertEqual((f['stage'], f['later_stages']), ('alloc', ['disable']))

    def test_failure_named_only_by_the_event_builder(self):
        f = rm.failure_of([('2026-09-18 20:00:00', "teb0: TEB didn't hear from:"),
                           ('2026-09-18 20:00:00', 'teb0: jungfrau_2'),
                           ('2026-09-18 20:00:01', 'cannot set config alias in state \'running\'')],
                          [('2026-09-18 19:00:00', 'paused'), ('2026-09-18 19:00:01', 'running')])
        self.assertEqual((f['kind'], f['stage'], f['components']), ('eb_missing', 'running', ['jungfrau_2']))
        f = rm.failure_of([('2026-09-18 20:00:00', 'teb0: jungfrau_2')], [('2026-09-18 19:00:00', 'connected')])
        self.assertEqual(f['stage'], 'configure')     # the event builder gave up during configure
        self.assertIsNone(rm.failure_of([('2026-09-18 20:00:00', "cannot set config alias in state 'running'")]))


class Windows(unittest.TestCase):
    def w(self, today, phrase):
        a, b = rm.widest_window(today, phrase)
        return a.strftime('%Y-%m-%d %H:%M'), b.strftime('%Y-%m-%d %H:%M')

    def test_phrases(self):
        self.assertEqual(self.w('2026-11-19', 'yesterday evening'), ('2026-11-18 16:00', '2026-11-19 00:00'))
        self.assertEqual(self.w('2026-11-19', 'Tuesday afternoon'), ('2026-11-17 11:00', '2026-11-17 19:00'))
        self.assertEqual(self.w('2026-11-19', 'Thursday morning'), ('2026-11-12 00:00', '2026-11-12 13:00'))
        self.assertEqual(self.w('2026-11-19', 'last night'), ('2026-11-18 18:00', '2026-11-19 08:00'))
        self.assertEqual(self.w('2026-11-19', 'this morning'), ('2026-11-19 00:00', '2026-11-19 13:00'))
        self.assertEqual(self.w('2026-11-02', 'over the weekend'), ('2026-10-30 18:00', '2026-11-02 08:00'))
        self.assertEqual(self.w('2026-11-02', 'early Sunday morning'), ('2026-11-01 00:00', '2026-11-01 13:00'))
        self.assertEqual(self.w('2026-11-19', 'Monday night'), ('2026-11-16 18:00', '2026-11-17 08:00'))

    def test_unknown_phrase_raises(self):
        with self.assertRaises(ValueError):
            rm.widest_window('2026-11-19', 'a while ago')


class Cli(Base):
    def test_check_unique_and_ambiguous(self):
        rc, out = self.run_cli('check', '--root', self.root, '--cases', self.cases)
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count('UNIQUE'), 2)
        spec = jload(self.cases)
        spec['cases'][0]['phrase'] = 'Friday'          # 09-18 is a Friday; whole day still one launch
        spec['cases'].append({'id': 'syn-amb', 'today': '2026-09-21', 'phrase': 'over the weekend',
                              'target': 'current/2026/09/18_20:00:00',
                              'keyed_launches': ['current/2026/09/18_20:00:00', 'current/2026/09/20_09:00:00']})
        jsave(spec, self.cases)
        rc, out = self.run_cli('check', '--root', self.root, '--cases', self.cases)
        self.assertEqual(rc, 1)
        self.assertIn('current/2026/09/20_09:00:00: not keyed, a second answer beside the target', out)

    def test_keys_update_then_verify_then_detect_change(self):
        self.assertEqual(self.run_cli('keys', '--root', self.root, '--cases', self.cases, '--update')[0], 0)
        spec = jload(self.cases)
        names = [f['name'] for f in spec['cases'][0]['launches'][0]['files']]
        self.assertIn('18_20:05:00_drp-srcf-cmp033:jungfrau_0.log', names)
        rc, out = self.run_cli('keys', '--root', self.root, '--cases', self.cases)
        self.assertEqual(rc, 0, out)
        self.assertIn('jungfrau_0 @ alloc (detector-socket-connect)', out)
        with open(os.path.join(self.root, CUR, '2026/09/18_20:00:00_drp-srcf-cmp042:timing_1.log'), 'a') as f:
            f.write('one more line\n')
        rc, out = self.run_cli('keys', '--root', self.root, '--cases', self.cases)
        self.assertEqual(rc, 1)
        self.assertIn('sha256 differs: 18_20:00:00_drp-srcf-cmp042:timing_1.log', out)

    @unittest.skipUnless(HAVE_ZSTD, 'zstd not installed')
    def test_rotation_to_zst_keeps_keys_and_hashes(self):
        self.run_cli('keys', '--root', self.root, '--cases', self.cases, '--update')
        for name in ('18_20:00:00_drp-srcf-cmp033:jungfrau_0.log', '18_20:00:00_drp-srcf-cmp014:control.log'):
            subprocess.check_call(['zstd', '-q', '--rm', os.path.join(self.root, CUR, '2026/09', name)])
        rc, out = self.run_cli('keys', '--root', self.root, '--cases', self.cases)
        self.assertEqual(rc, 0, out)

    def test_fetch_local_drops_largest_non_case_file_and_verifies(self):
        self.run_cli('keys', '--root', self.root, '--cases', self.cases, '--update')
        write(self.root, CUR + '/2026/09/20_09:00:00_drp-srcf-cmp035:jungfrau_2.log', 'x' * 5000)
        write(self.root, PREV + '/.psdaq/x2_p0.activedet.json', '{}')
        dest = os.path.join(self.tmp, 'copy')
        rc, out = self.run_cli('fetch', '--dest', dest, '--host', '', '--source-root', self.root,
                               '--cases', self.cases, '--max-bytes', '4000')
        self.assertEqual(rc, 0, out)
        self.assertIn('all sha256 match', out)
        man = jload(dest + '.manifest.json')
        self.assertEqual([d['path'] for d in man['dropped']],
                         [CUR + '/2026/09/20_09:00:00_drp-srcf-cmp035:jungfrau_2.log'])
        self.assertTrue(os.path.exists(os.path.join(dest, PREV, '.psdaq/x2_p0.activedet.json')))
        self.assertTrue(os.path.exists(os.path.join(dest, PREV, '2026/09/notes.txt')))
        self.assertEqual(self.run_cli('keys', '--root', dest, '--cases', self.cases)[0], 0)

    def test_plan_keeps_case_files_even_when_largest(self):
        files, dropped, total = rm.plan_fetch([(900, 'a/big.log'), (500, 'a/case.log.zst'), (100, 'a/s.log')],
                                              {'case.log'}, 700)
        self.assertEqual([p for _, p in dropped], ['a/big.log'])
        self.assertEqual((files, total), (['a/case.log.zst', 'a/s.log'], 600))

    def test_candidates_are_alone_in_their_window(self):
        got = rm.candidates(list(self.inv().values()), lag_days=(1,))
        self.assertIn(('current/2026/09/18_20:00:00', '2026-09-19', 'yesterday evening', 1), got)
        self.assertIn(('previous/2026/09/16_10:00:00', '2026-09-17', 'yesterday morning', 1), got)
        self.assertFalse([c for c in got if c[0] == 'current/2026/09/20_09:00:00'])   # not keyed
        # the whole of Friday 09-18 also holds the 20:00 launch only; the weekend adds the unkeyed one
        self.assertIn(('current/2026/09/18_20:00:00', '2026-09-20', 'Friday evening', 1), rm.candidates(
            list(self.inv().values()), lag_days=(2,)))

    def test_compatible_neighbours(self):
        f = {'component': 'jungfrau_0', 'stage': 'alloc'}
        self.assertTrue(rm.compatible(f, 'healthy') and rm.compatible(f, 'idle'))
        self.assertTrue(rm.compatible(f, dict(f, mechanism='x')))
        self.assertFalse(rm.compatible(f, {'component': 'jungfrau_0', 'stage': 'configure'}))
        self.assertFalse(rm.compatible(f, 'not keyed'))

    def test_name_scan_counts_without_values(self):
        write(self.root, CUR + '/2026/09/18_20:00:00_drp-srcf-cmp014:teb0.log',
              'cd /sdf/home/q/qperson/x\n# CMDLINE: control --user mfxopr\nowner=zed1 user: mfxopr\n')
        st = rm.scan_names(self.root)
        self.assertEqual(st['home-path'], {'files': 1, 'lines': 1, 'distinct': 1})
        self.assertEqual(st['user-assign'], {'files': 1, 'lines': 1, 'distinct': 1})
        self.assertEqual(st['cli-user']['lines'], 0)      # the shared operator account is not a person

    def test_months_of_cases_cover_windows_and_launches(self):
        self.assertEqual(rm.months_of_cases(CASES), ['2026/09'])


if __name__ == '__main__':
    unittest.main()
