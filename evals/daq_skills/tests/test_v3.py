"""Tests for the v3 additions: tree.py (family-B roots), run.py --mode m1 and the controls, ask-operator,
evidence.py.  No model calls: the agent is a scripted program.

    python3 -m unittest discover -s tests -v
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import evidence  # noqa: E402
import harvest   # noqa: E402
import run       # noqa: E402
import tree      # noqa: E402

EVAL = os.path.dirname(HERE)
T0 = '2026-11-09 12:12:52'


def epoch_of(local):
    return tree.epoch(datetime.datetime.strptime(local, '%Y-%m-%d %H:%M:%S'))


def write_pool(work, name, prefix, host, procs, ym='2026/11', day='2026-11-09'):
    """A harvested pool of one launch: procs {process: [lines]}; each line's time is its mtime basis."""
    pdir = os.path.join(work, 'pools', harvest.pool_id(name))
    logs = os.path.join(pdir, 'logs', ym)
    os.makedirs(logs, exist_ok=True)
    files = []
    hhmmss = prefix[3:]
    for proc, lines in sorted(procs.items()):
        f = '%s_%s:%s.log' % (prefix, host, proc)
        open(os.path.join(logs, f), 'w').write('\n'.join(lines) + '\n')
        t = epoch_of('%s %s' % (day, hhmmss)) + 60
        os.utime(os.path.join(logs, f), (t, t))
        files.append(f)
    s = {'prefix': prefix, 'host': host, 'ym': ym, 'start': '%s %s' % (day, hhmmss), 'files': files, 'planted': [],
         'first': '%s %s' % (day, hhmmss), 'last': '%s %s' % (day, hhmmss), 'zst': False}
    json.dump({'leaks': [], 'compress_before': None, 'sessions': [s]}, open(os.path.join(pdir, 'pool.json'), 'w'))
    return s


def control_lines(day, hhmm, pid, extra):
    return ['# ID:      control', '# HOST:    sdfmilan%s' % pid, '# CMDLINE: control -P tst -r /sdf/data/lcls/ds/tst/tstx00001/scratch/a.json',
            '@@@ Restarting child "%s/%s_%s:00_sdfmilan%s:control.log"' % (day[:7].replace('-', '/'), day[8:], hhmm, pid),
            '%s %s:01,001 tst-control[%s]: <I> logging initialized for launch %s' % (day, hhmm, pid, pid),
            '%s %s:02,002 tst-control[%s]: <D> headers: {\'Date\': \'Mon, 09 Nov 2026 20:13:00 GMT\'} for %s' % (day, hhmm, pid, pid),
            'tst-drp[%s]: <I> received key = configure @ Mon Nov  9 %s:03 2026 (launch %s)' % (pid, hhmm, pid)] + extra


class Fixture(object):
    """A tiny world: one keyed fault launch, three decoy launches, a case table, a catalog."""

    def make(self):
        self.tmp = tempfile.mkdtemp(prefix='daqeval3-')
        self.work = os.path.join(self.tmp, 'work')
        write_pool(self.work, 'one', '09_12:12:52', 'sdfmilan001',
                   {'control': control_lines('2026-11-09', '12:12', '101', ['2026-11-09 12:14:02,000 tst-control[101]: <E> tt_0 did not respond to configure',
                                                                          "2026-11-09 12:14:03,000 tst-control[101]: <D> {'proc_info': {'alias': 'tt_0', 'host': 'sdfmilan001', 'pid': 7}}",
                                                                          "2026-11-09 12:14:04,000 tst-control[101]: <D> {'gen': 2, 'hostname': 'sdfmilan001', 'run_num': 1}"]),
                    'tt_0': ['# HOST: sdfmilan001', '# CMDLINE: drp -P tst -D tt', '2026-11-09 12:13:30,000 tst-drp[102]: rogue.GeneralError: Verify error for block Top.TriggerDelay'],
                    'teb0': ['# HOST: sdfmilan001', '# CMDLINE: teb -P tst', '2026-11-09 12:13:00,500 tst-teb[103]: <I> teb configured for the launch']})
        for i, (name, pre) in enumerate([('d1', '09_09:00:10'), ('d2', '09_18:30:20'), ('d3', '09_13:00:30')]):
            write_pool(self.work, name, pre, 'sdfada%03d' % (i + 2),
                       {'control': control_lines('2026-11-09', pre[3:8], str(200 + i), ['2026-11-09 %s:30,000 tst-control[%d]: <E> decoy %s failed' % (pre[3:8], 200 + i, name)])})
        self.cat = {'version': 2, 'logs_path': '/sdf/home/t/tstopr/daq/logs', 'context': 'Logs are under /sdf/home/t/tstopr/daq/logs.',
                    'pools': {n: {'sessions': []} for n in ('one', 'd1', 'd2', 'd3')},
                    'cases': [{'id': 'c1', 'tier': 1, 'set': 'core', 'pool': 'one', 'question': 'On 2026-11-09 around 12:13 the DAQ would not configure. Why?',
                               'key_source': 'planted', 'key': {'fault': {'component': ['tt_0'], 'transition': ['configure'], 'mechanism': ['Verify error'],
                                                                          'summary': 'tt_0 failed configure: Verify error.'}, 'sessions': ['09_12:12:52']}}]}
        self.catalog = os.path.join(self.tmp, 'catalog.json')
        json.dump(self.cat, open(self.catalog, 'w'))
        self.table = json.load(open(os.path.join(EVAL, 'cases_v3.json')))
        self.table['cases'] = [{'id': 'c1', 'families': ['A', 'B'], 'pool': 'one', 'healthy': False, 'keyed_launches': ['09_12:12:52'],
                                'crib': 'tt_0 failed configure: Verify error.', 'starve_component': 'tt_0',
                                'starve_files': ['09_12:12:52_sdfmilan001:tt_0.log'],
                                'm1': {'date': '2026-11-17', 'now': '2026-11-18 09:40', 'vague': 'Tuesday around lunch',
                                       'widest': ['2026-11-17 11:00', '2026-11-17 14:00'], 'question': 'On Tuesday around lunch the DAQ would not configure. Why?',
                                       'answers': {'when': 'Tuesday the 17th, around 12:15.', 'hutch': 'MFX.'}}}]
        self.calendar = [('2026-09-10', 1, '18:00', '23:00', 'mfx'), ('2026-11-17', 1, '00:00', '10:00', 'mfx'),
                         ('2026-11-17', 1, '12:00', '13:30', 'tmo')]
        self.roots = os.path.join(self.work, 'roots')
        self.manifest, self.failed = tree.build(self.work, self.table['cases'], self.cat, self.roots, quiet=True,
                                                calendar=self.calendar, configs=[('mfx.py', 'one')])
        for c in self.table['cases']:
            c['m1'].update((k, self.manifest['cases'][c['id']][k]) for k in ('keyed_stamp', 'keyed_dir', 'keyed_files', 'starve_files', 'pointer'))
        self.cases_v3 = os.path.join(self.tmp, 'cases_v3.json')
        json.dump(self.table, open(self.cases_v3, 'w'))


class Tree(unittest.TestCase, Fixture):
    @classmethod
    def setUpClass(cls):
        Fixture.make(cls)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_keyed_launch_is_rehoused_at_the_mfx_path_on_its_new_day(self):
        m = self.manifest['cases']['c1']
        self.assertEqual((m['keyed_dir'], m['keyed_stamp']), ('/sdf/home/m/mfxopr/daq/logs/2026/11', '17_12:12:52'))
        self.assertEqual(m['keyed_files'], ['17_12:12:52_drp-srcf-cmp014:control.log', '17_12:12:52_drp-srcf-cmp014:teb0.log',
                                            '17_12:12:52_drp-srcf-cmp033:tt_0.log'])
        self.assertEqual(self.failed, [])
        self.assertTrue(m['check']['pass'])
        self.assertEqual(m['check']['in_window'], ['home/m/mfxopr/daq/logs/2026/11/17_12:12:52'])
        self.assertEqual(m['check']['other_hutch_in_window'], 1)        # the second hutch's launch is a trap, not a failure

    def test_text_is_rewritten_hutch_and_dates_but_nothing_else(self):
        p = os.path.join(self.roots, 'm1', 'c1', 'home/m/mfxopr/daq/logs/2026/11/17_12:12:52_drp-srcf-cmp014:control.log')
        text = open(p).read()
        self.assertNotIn('tst', text)
        self.assertIn('2026-11-17 12:12:01,001 mfx-control[101]', text)
        self.assertIn('/sdf/data/lcls/ds/mfx/mfxx00001/', text)
        self.assertIn('2026/11/17_12:12:00_drp-srcf-cmp014:control.log', text)
        self.assertIn('# HOST:    drp-srcf-cmp014', text)
        self.assertIn("'alias': 'tt_0', 'host': 'drp-srcf-cmp033'", text)     # a node name takes its process's host
        self.assertIn("'hostname': 'drp-srcf-cmp033'", text)                 # a file report: the launch's detector DRP
        self.assertEqual(tree.node_names(text), [])
        self.assertIn('Tue, 17 Nov 2026 20:13:00 GMT', text)
        self.assertIn('@ Tue Nov 17 12:12:03 2026', text)
        self.assertEqual(len(text.splitlines()), len(open(os.path.join(self.work, 'pools', harvest.pool_id('one'), 'logs/2026/11/09_12:12:52_sdfmilan001:control.log')).read().splitlines()))
        self.assertEqual(self.manifest['stale_local_dates'], 0)
        self.assertEqual(self.manifest['cases']['c1']['leftovers'], {})
        self.assertEqual((self.manifest['cases']['c1']['node_leftovers'], self.manifest['shared_node_leftovers']), (0, 0))

    def test_modification_time_moves_with_the_day(self):
        p = os.path.join(self.roots, 'm1', 'c1', 'home/m/mfxopr/daq/logs/2026/11/17_12:12:52_drp-srcf-cmp014:control.log')
        self.assertEqual(tree.local_of_epoch(os.stat(p).st_mtime), datetime.datetime(2026, 11, 17, 12, 13, 52))

    def test_launches_before_the_cutover_go_to_the_old_root(self):
        old = [l for l in self.manifest['launches'] if l['start'].startswith('2026-09-10')]
        self.assertEqual([l['dir'] for l in old], ['home/m/mfxopr/2026/09'])
        self.assertTrue(os.path.isdir(os.path.join(self.roots, 'm1', 'c1', 'home/m/mfxopr/2026/09')))

    def test_partition_configs_sit_in_daq_scripts(self):
        p = os.path.join(self.roots, 'm1', 'c1', tree.SCRIPTS, 'mfx.py')
        text = open(p).read()
        self.assertIn("id: 'control'", text)
        self.assertIn('control -P mfx', text)
        self.assertTrue(os.path.exists(p + '~'))

    def test_starved_roots_lack_exactly_the_root_cause_files(self):
        d = os.path.join(self.roots, 'm1-starved', 'c1', 'home/m/mfxopr/daq/logs/2026/11')
        self.assertEqual(sorted(f for f in os.listdir(d) if f.startswith('17_12')),
                         ['17_12:12:52_drp-srcf-cmp014:control.log', '17_12:12:52_drp-srcf-cmp014:teb0.log'])
        m0 = os.path.join(self.roots, 'm0-starved', 'c1', 'logs', '2026', '11')
        self.assertEqual(sorted(os.listdir(m0)), ['09_12:12:52_sdfmilan001:control.log', '09_12:12:52_sdfmilan001:teb0.log'])
        self.assertTrue(self.manifest['cases']['c1']['starved_absent'])

    def test_case_tree_holds_nothing_after_now(self):
        for l in self.manifest['launches']:
            exists = os.path.exists(os.path.join(self.roots, 'm1', 'c1', l['dir'], l['files'][0]))
            self.assertEqual(exists, l['end'] < '2026-11-18 09:40', l)

    def test_check_fails_when_another_launch_is_inside_the_window(self):
        root = os.path.join(self.tmp, 'bad')
        shutil.copytree(os.path.join(self.roots, 'm1', 'c1'), root)
        d = os.path.join(root, 'home/m/mfxopr/daq/logs/2026/11')
        shutil.copy2(os.path.join(d, '17_12:12:52_drp-srcf-cmp014:teb0.log'), os.path.join(d, '17_13:20:00_drp-srcf-cmp014:teb0.log'))
        mine = [l for l in self.manifest['launches'] if l['case'] == 'c1'][0]
        chk = tree.check_root(root, mine, *tree.window(self.table['cases'][0]))
        self.assertFalse(chk['pass'])
        self.assertIn('home/m/mfxopr/daq/logs/2026/11/17_13:20:00', chk['in_window'])

    def test_build_is_deterministic(self):
        out2 = os.path.join(self.tmp, 'roots2')
        m2, _ = tree.build(self.work, self.table['cases'], self.cat, out2, quiet=True, calendar=self.calendar, configs=[('mfx.py', 'one')])
        self.assertEqual(m2['launches'], self.manifest['launches'])
        for l in m2['launches']:
            for f in l['files']:
                a, b = (os.path.join(r, 'shared', l['dir'], f) for r in (self.roots, out2))
                self.assertEqual((open(a, 'rb').read(), int(os.stat(a).st_mtime)), (open(b, 'rb').read(), int(os.stat(b).st_mtime)))

    def test_dst_and_utc_shift(self):
        # 2026-11-09 21:36 PST is 05:36Z on the 10th; moved to 2026-09-16 (PDT) it is 04:36Z on the 17th
        out = tree.shift_text('"begin_time": "2026-11-10T05:36:29.949485+00:00" at 2026-11-09 21:36:29', -54, 'mfx')
        self.assertEqual(out, '"begin_time": "2026-09-17T04:36:29.949485+00:00" at 2026-09-16 21:36:29')
        self.assertEqual(tree.shift_text('Mon Nov  9 09:03:08 2026 getstate _bootstrap Ctst-teb tstopr', 8, 'mfx'),
                         'Tue Nov 17 09:03:08 2026 getstate _bootstrap Cmfx-teb mfxopr')


class Hosts(unittest.TestCase):
    """The sim's S3DF node names become real MFX hosts, per process, in names and text."""

    def test_roles_put_control_on_the_collect_host_and_detectors_on_drp_nodes(self):
        self.assertEqual([tree.host_for(p) for p in ('control', 'teb0', 'pvcam_0', 'control_gui', 'ami-client', 'ami-node_0', 'meb0')],
                         ['drp-srcf-cmp014', 'drp-srcf-cmp014', 'drp-srcf-cmp014', 'mfx-daq', 'mfx-daq', 'drp-srcf-mon006', 'drp-srcf-mon006'])
        self.assertEqual(tree.host_for('jungfrau_0'), 'drp-srcf-cmp033')          # where MFX runs it
        for p in ('fakecam_0', 'tt_0', 'wave8_0', 'cspad_0', 'some_new_det_0'):
            self.assertIn(tree.host_for(p), tree.HOSTS['mfx']['drps'])
            self.assertEqual(tree.host_for(p), tree.host_for(p))                     # deterministic
        self.assertEqual(tree.host_for('control', 'tmo'), 'drp-srcf-mon001')

    def test_rename_keeps_stamp_process_and_suffix(self):
        self.assertEqual(tree.rename('09_21:12:48_sdfada013:jungfrau_0.log.zst', '09_21:12:48', '17_21:12:48'),
                         '17_21:12:48_drp-srcf-cmp033:jungfrau_0.log.zst')
        self.assertEqual(tree.rename('09_21:12:48_sdfmilan082:control.log', '09_21:12:48', '01_21:12:48'),
                         '01_21:12:48_drp-srcf-cmp014:control.log')

    def test_each_node_name_takes_the_host_of_its_process(self):
        text = '\n'.join([
            '# HOST:    sdfmilan082',
            '@@@ Restarting child "2026/11/09_15:14:29_sdfmilan082:teb0.log"',
            "{'alias': 'meb0', 'device': '', 'host': 'sdfmilan082', 'pid': 1}, {'alias': 'fakecam_0', 'host': 'sdfmilan082'}",
            "{'gen': 2, 'hostname': 'sdfmilan082', 'run_num': 1}",
            "[[False, 'drp/123/sdfmilan082', 5], [False, 'fakecam_0', 5]]",
            'no context sdfmilan082 here; a path hash /daq/sdfdefd/prom stays'])
        out = tree.rehost(text, 'control', ['control', 'teb0', 'fakecam_0', 'meb0'])
        self.assertEqual(out.splitlines(), [
            '# HOST:    drp-srcf-cmp014',
            '@@@ Restarting child "2026/11/09_15:14:29_drp-srcf-cmp014:teb0.log"',
            "{'alias': 'meb0', 'device': '', 'host': 'drp-srcf-mon006', 'pid': 1}, {'alias': 'fakecam_0', 'host': '%s'}" % tree.host_for('fakecam_0'),
            "{'gen': 2, 'hostname': '%s', 'run_num': 1}" % tree.host_for('fakecam_0'),
            "[[False, 'drp/123/%s', 5], [False, 'fakecam_0', 5]]" % tree.host_for('fakecam_0'),
            'no context drp-srcf-cmp014 here; a path hash /daq/sdfdefd/prom stays'])
        self.assertEqual(tree.node_names(out), [])
        self.assertEqual(tree.node_names('sdfiana025 sdfrome001.slac.stanford.edu x_sdfada013:y sdfdefd'),
                         ['sdfiana025', 'sdfrome001.slac.stanford.edu', 'sdfada013'])

    @unittest.skipUnless(os.environ.get('HUTCH_RESOURCES'), 'set HUTCH_RESOURCES to the hutch-resources skill folder')
    def test_hosts_are_the_maps_mfx_hosts(self):
        m = json.load(open(os.path.join(os.environ['HUTCH_RESOURCES'], 'resources', 'mfx-resources.json')))
        nodes = m['code']['daq_nodes']['verified_active_assignments_2026_09_20']
        h = tree.HOSTS['mfx']
        for host in [h['collect'], h['gui'], h['monitor']] + h['drps']:
            self.assertIn(host, nodes)
        self.assertIn('control', ' '.join(nodes[h['collect']]))
        for proc, host in h['fixed'].items():
            self.assertTrue(any(x.startswith(proc) for x in nodes[host]), proc)


FAKE_M1 = r'''
import json, os, subprocess, sys
prompt = sys.stdin.read()
root = os.environ.get("DAQ_EVAL_SDF", "/sdf")
def say(ev): print(json.dumps(ev)); sys.stdout.flush()
ans = subprocess.run(["ask-operator", "When exactly was that?"], stdout=subprocess.PIPE, universal_newlines=True).stdout.strip()
listing = subprocess.run("ls %s/home/m/mfxopr/daq/logs/2026/11" % root, shell=True, stdout=subprocess.PIPE, universal_newlines=True).stdout
out = subprocess.run("grep -h Verify %s/home/m/mfxopr/daq/logs/2026/11/*tt_0.log" % root, shell=True, stdout=subprocess.PIPE, universal_newlines=True).stdout
say({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ask-operator 'When exactly was that?'"}}]}})
say({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": ans}]}})
say({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "ls"}}]}})
say({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": listing}]}})
say({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "grep -h Verify *tt_0.log"}}]}})
say({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t3", "content": out}]}})
say({"type": "result", "result": "## Most Likely Cause\ntt_0 Verify error in configure (operator: %s)\n%s" % (ans, prompt), "total_cost_usd": 0.25, "num_turns": 4,
     "usage": {"output_tokens": 9}, "modelUsage": {"claude-haiku-x": {}}})
'''


class RunV3(unittest.TestCase, Fixture):
    def setUp(self):
        Fixture.make(self)
        self.agent = os.path.join(self.tmp, 'agent.py')
        open(self.agent, 'w').write(FAKE_M1)
        self.out = os.path.join(self.tmp, 'results')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_(self, arm, mode, control=None, skills=('none',), extra=()):
        args = ['--catalog', self.catalog, '--cases-v3', self.cases_v3, '--work', self.work, '--arm', arm, '--out', self.out,
                '--no-sandbox', '--agent-cmd', sys.executable + ' ' + self.agent, '--mode', mode] + list(extra)
        for s in skills:
            args += ['--skills', s]
        if control:
            args += ['--control', control]
        return run.main(args)

    def one(self, arm):
        (name,) = os.listdir(os.path.join(self.out, arm))
        return os.path.join(self.out, arm, name)

    def test_m1_prompt_has_hutch_vague_time_and_today_but_no_path_or_window(self):
        self.assertEqual(self.run_('m1-none', 'm1'), 0)
        d = self.one('m1-none')
        prompt = open(os.path.join(d, 'prompt.txt')).read()
        self.assertIn('MFX hutch', prompt)
        self.assertIn('Wednesday 2026-11-18, 09:40', prompt)
        self.assertIn('On Tuesday around lunch', prompt)
        self.assertIn('ask-operator', prompt)
        for leak in ('/sdf', 'tstopr', 'mfxopr', '12:12', '2026-11-17', 'logs'):
            self.assertNotIn(leak, prompt)
        meta = json.load(open(os.path.join(d, 'meta.json')))
        self.assertEqual((meta['mode'], meta['control'], meta['total_cost_usd'], meta['model'], meta['turns']), ('m1', None, 0.25, 'claude-haiku-x', 4))
        self.assertTrue(meta['logs_src'].endswith(os.path.join('roots', 'm1', 'c1')))

    def test_ask_operator_answers_from_the_table_and_logs_each_question(self):
        self.run_('m1-none', 'm1')
        d = self.one('m1-none')
        (q,) = [json.loads(l) for l in open(os.path.join(d, 'operator.jsonl'))]
        self.assertEqual((q['question'], q['rule'], q['answer']), ('When exactly was that?', 'when', 'Tuesday the 17th, around 12:15.'))
        self.assertIn('operator: Tuesday the 17th', open(os.path.join(d, 'final.md')).read())
        self.assertEqual(json.load(open(os.path.join(d, 'meta.json')))['operator_questions'], 1)

    def test_operator_default_answer(self):
        c = self.table['cases'][0]
        self.assertEqual(run.operator_answer(self.table, c, 'Where are the logs kept?'), ("I don't know more than what I told you.", None))
        self.assertEqual(run.operator_answer(self.table, c, 'Which hutch?')[1], 'hutch')
        self.assertEqual(run.operator_answer(self.table, c, 'What error did you see?'), ("I don't know more than what I told you.", None))

    def test_pointer_adds_the_path_and_window(self):
        self.run_('m1-pointer', 'm1', 'pointer')
        prompt = open(os.path.join(self.one('m1-pointer'), 'prompt.txt')).read()
        self.assertTrue(prompt.endswith('The DAQ logs are in %s/home/m/mfxopr/daq/logs/2026/11, and the launch in question ran on 2026-11-17 '
                                        'between 12:12 and 12:14.' % os.path.join(self.roots, 'm1', 'c1')), prompt[-200:])

    def test_crib_puts_the_mechanism_first_at_m0(self):
        self.run_('crib', 'm0', 'crib', extra=['--dry-run'])
        prompt = open(os.path.join(self.one('crib'), 'prompt.txt')).read()
        self.assertTrue(prompt.startswith('A DAQ expert who has already read these logs says: tt_0 failed configure: Verify error.'))
        self.assertIn('around 12:13', prompt)

    def test_starved_m0_mounts_the_starved_pool(self):
        self.run_('starved', 'm0', 'starved', extra=['--dry-run'])
        meta = json.load(open(os.path.join(self.one('starved'), 'meta.json')))
        self.assertEqual(sorted(os.listdir(os.path.join(meta['logs_src'], '2026', '11'))),
                         ['09_12:12:52_sdfmilan001:control.log', '09_12:12:52_sdfmilan001:teb0.log'])
        self.assertIn(meta['logs_src'], open(os.path.join(self.one('starved'), 'prompt.txt')).read())

    def test_starved_m1_and_evidence_never_found_is_censored(self):
        self.assertEqual(self.run_('m1-starved', 'm1', 'starved'), 0)
        d = self.one('m1-starved')
        r = evidence.evaluate(d, {c['id']: c for c in self.cat['cases']}, {c['id']: c for c in self.table['cases']}, self.work)
        self.assertEqual((r['calls'], r['censored'], r['total']), (4, True, 3))

    def test_evidence_counts_calls_before_the_grep_that_showed_a_keyed_line(self):
        self.run_('m1-none', 'm1')
        r = evidence.evaluate(self.one('m1-none'), {c['id']: c for c in self.cat['cases']}, {c['id']: c for c in self.table['cases']}, self.work)
        self.assertEqual((r['calls'], r['censored'], r['first']['index']), (2, False, 3))

    def test_two_skill_sets_install_side_by_side(self):
        a, b = os.path.join(self.tmp, 'skA'), os.path.join(self.tmp, 'skB')
        for root, s in ((a, 'psana-daq'), (b, 'hutch-resources')):
            os.makedirs(os.path.join(root, s))
            open(os.path.join(root, s, 'SKILL.md'), 'w').write('# ' + s)
        self.run_('m1-both', 'm1', skills=(a, b), extra=['--dry-run'])
        d = self.one('m1-both')
        self.assertEqual(sorted(os.listdir(os.path.join(d, 'ws', '.claude', 'skills'))), ['hutch-resources', 'psana-daq'])
        self.assertEqual(json.load(open(os.path.join(d, 'meta.json')))['skills'], '%s,%s' % (a, b))

    def test_controls_need_their_mode_and_run_ids_differ_by_mode(self):
        with self.assertRaises(SystemExit):
            self.run_('x', 'm0', 'pointer', extra=['--dry-run'])
        with self.assertRaises(SystemExit):
            self.run_('x', 'm1', 'crib', extra=['--dry-run'])
        self.assertNotEqual(run.run_id('c1', 1), run.run_id('c1', 1, 'm1|'))
        self.assertEqual(run.run_id('c1', 1), run.run_id('c1', 1, ''))

    def test_sandbox_mounts_the_root_at_sdf_with_the_operator(self):
        a = ' '.join(run.sandbox('/x/ws', '/x/root', '/sdf', extra=['--ro-bind', '/t/bin', '/run/operator/bin']))
        self.assertIn('--ro-bind /x/root /sdf --ro-bind /t/bin /run/operator/bin --bind /x/ws /work', a)
        self.assertNotIn('--dir / ', a)


def stream(*pairs):
    """A stream-json transcript from (tool name, input, output) triples."""
    lines = []
    for i, (name, inp, out) in enumerate(pairs):
        lines.append(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 'u%d' % i, 'name': name, 'input': inp}]}}))
        lines.append(json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'u%d' % i,
                                                                            'content': [{'type': 'text', 'text': out}]}]}}))
    return '\n'.join(lines) + '\n'


class Evidence(unittest.TestCase):
    KEYED = ['17_21:12:48_node1:control.log', '17_21:12:48_node1:drp_0.log.zst']
    LINE = '2026-11-17 21:13:20,123 mfx-control[4242]: <E> drp_0 did not respond to configure'
    OTHER = '2026-11-16 08:00:00,000 mfx-control[1]: <I> another launch entirely, nothing to do with it'
    BANNER = '# CONDA_PREFIX:/sdf/group/lcls/ds/ana/sw/conda2/inst/envs/daq_20250402_r9'

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='daqev-')
        self.root = os.path.join(self.tmp, 'root', '2026', '11')
        os.makedirs(self.root)
        open(os.path.join(self.root, self.KEYED[0]), 'w').write('%s\n%s\nshort\n' % (self.BANNER, self.LINE))
        if shutil.which('zstd'):
            subprocess.run(['zstd', '-q', '-o', os.path.join(self.root, self.KEYED[1]), '-'], input=b'2026-11-17 21:13:21,000 mfx-drp[7]: <I> Collector thread started now\n')
        open(os.path.join(self.root, '16_08:00:00_node1:control.log'), 'w').write('%s\n%s\n' % (self.BANNER, self.OTHER))
        self.prints = evidence.fingerprints(os.path.join(self.tmp, 'root'), self.KEYED)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def calls(self, *pairs):
        p = os.path.join(self.tmp, 't.jsonl')
        open(p, 'w').write(stream(*pairs))
        return evidence.calls_to_evidence(p, self.KEYED, self.prints)

    def test_shared_banner_is_not_a_fingerprint(self):
        self.assertNotIn(self.BANNER[:40], self.prints)
        self.assertIn(self.LINE[:40], self.prints)

    def test_guidance_reads_count_and_a_read_of_a_keyed_file_ends_the_count(self):
        r = self.calls(('Skill', {'skill': 'psana-daq'}, 'loaded'), ('Read', {'file_path': '/w/.claude/skills/psana-daq-logs/SKILL.md'}, 'x'),
                       ('Read', {'file_path': '/sdf/home/m/mfxopr/daq/logs/2026/11/' + self.KEYED[0]}, '     1\t' + self.BANNER))
        self.assertEqual((r['calls'], r['censored'], r['first']['why']), (2, False, 'Read of ' + self.KEYED[0]))

    def test_listing_does_not_count_but_a_glob_grep_with_a_keyed_line_does(self):
        r = self.calls(('Bash', {'command': 'ls /sdf/home/m/mfxopr/daq/logs/2026/11'}, '\n'.join(self.KEYED)),
                       ('Glob', {'pattern': '**/*control.log'}, '/sdf/x/' + self.KEYED[0]),
                       ('Bash', {'command': 'grep -l configure */*control.log'}, '2026/11/' + self.KEYED[0]),
                       ('Bash', {'command': 'grep -H "<E>" 2026/11/*control.log'}, '2026/11/16_08:00:00_node1:control.log:' + self.OTHER),
                       ('Bash', {'command': 'grep -Hn "<E>" 2026/11/*control.log'}, '2026/11/%s:2:%s' % (self.KEYED[0], self.LINE)))
        self.assertEqual((r['calls'], r['first']['index']), (4, 5))

    def test_read_output_with_line_numbers_and_grep_n_count(self):
        self.assertEqual(self.calls(('Grep', {'pattern': 'respond'}, '2:' + self.LINE))['calls'], 0)
        self.assertEqual(self.calls(('Read', {'file_path': '/tmp/copy.txt'}, '     2→' + self.LINE))['calls'], 0)

    @unittest.skipUnless(shutil.which('zstd'), 'needs zstd')
    def test_compressed_keyed_file_counts_by_content_and_by_name(self):
        self.assertEqual(self.calls(('Bash', {'command': 'zstd -dc *drp_0.log.zst'}, '2026-11-17 21:13:21,000 mfx-drp[7]: <I> Collector thread started now'))['calls'], 0)
        self.assertEqual(self.calls(('Read', {'file_path': '/sdf/' + self.KEYED[1]}, 'binary'))['calls'], 0)

    def test_never_read_is_censored_at_total_plus_one(self):
        r = self.calls(('Bash', {'command': 'ls'}, 'a'), ('Bash', {'command': 'cat other'}, self.OTHER), ('Bash', {'command': 'ask-operator when'}, 'Tuesday'))
        self.assertEqual((r['calls'], r['censored'], r['total']), (4, True, 3))

    def test_empty_transcript(self):
        r = self.calls()
        self.assertEqual((r['calls'], r['censored'], r['total']), (1, True, 0))


class BundledV3(unittest.TestCase):
    """cases_v3.json must agree with the catalog, the bundled pools and what tree.py derives from them."""

    @classmethod
    def setUpClass(cls):
        cls.table = json.load(open(os.path.join(EVAL, 'cases_v3.json')))
        cls.cat = json.load(open(os.path.join(EVAL, 'catalog.json')))
        cls.cases = {c['id']: c for c in cls.cat['cases']}

    def test_anchor_rule_picks_the_listed_cases(self):
        sel = self.table['anchor_selection']
        fault = sorted(sel['fault_ranked'], key=lambda r: (-r[1], r[2], r[0]))
        healthy = sorted(sel['healthy_ranked'], key=lambda r: (r[1], r[0]))
        self.assertEqual([r[0] for r in fault[:6]] + [r[0] for r in healthy[:2]], sel['chosen'])
        self.assertEqual([c['id'] for c in self.table['cases']], sel['chosen'])
        for cid in sel['chosen']:
            self.assertEqual(self.cases[cid]['set'], 'core')

    def test_crib_is_the_keys_own_words(self):
        for c in self.table['cases']:
            fault = self.cases[c['id']]['key'].get('fault')
            if fault:
                self.assertIn(c['crib'], fault['summary'], c['id'])
                self.assertTrue(c['starve_files'], c['id'])
            else:
                self.assertNotIn('starve_files', c)

    def test_windows_are_before_now_and_hold_the_keyed_start(self):
        for c in self.table['cases']:
            w0, w1 = tree.window(c)
            start = datetime.datetime.strptime('%s %s' % (c['m1']['date'], c['m1']['keyed_stamp'][3:]), '%Y-%m-%d %H:%M:%S')
            self.assertTrue(w0 <= start < w1 <= tree.parse(c['m1']['now']), c['id'])
            self.assertEqual(int(c['m1']['keyed_stamp'][:2]), int(c['m1']['date'][8:]), c['id'])

    @unittest.skipUnless(shutil.which('zstd'), 'needs zstd')
    def test_case_table_matches_what_tree_derives_from_the_bundled_pools(self):
        tmp = tempfile.mkdtemp(prefix='daqeval3b-')
        try:
            with tarfile.open(os.path.join(EVAL, 'data', 'pools.tar.gz')) as tar:
                tar.extractall(tmp)
            _pools, placed = tree.placements(tmp, self.table['cases'], self.cat)
            mine = {rec['case']: rec for _ln, rec in placed if rec['case']}
            for c in self.table['cases']:
                d = tree.derived(c, mine[c['id']])
                self.assertEqual(dict((k, c['m1'][k]) for k in d), d, c['id'])
            # the plan keeps every MFX decoy out of every case's widest window
            for _ln, rec in placed:
                if rec['tree'] == 'mfx' and not rec['case']:
                    s, e = (datetime.datetime.strptime(rec[k], '%Y-%m-%d %H:%M:%S') for k in ('start', 'end'))
                    for c in self.table['cases']:
                        self.assertFalse(tree.overlaps(s, e, *tree.window(c)), (rec['dir'], rec['prefix'], c['id']))
            # the starve rule: the component's log and every file holding a mechanism phrase of 6+ characters
            for c in self.table['cases']:
                if c['healthy']:
                    continue
                k = self.cases[c['id']]['key']
                pdir = os.path.join(tmp, 'pools', harvest.pool_id(c['pool']))
                (s,) = [s for s in json.load(open(os.path.join(pdir, 'pool.json')))['sessions'] if s['prefix'] in k['sessions']]
                want = [f for f in s['files'] if ':%s.log' % c['starve_component'] in f or
                        any(len(m) >= 6 and m.lower() in tree.read_log(os.path.join(pdir, 'logs', s['ym'], f)).lower() for m in k['fault']['mechanism'])]
                self.assertEqual(c['starve_files'], want, c['id'])
        finally:
            shutil.rmtree(tmp)


if __name__ == '__main__':
    unittest.main()
