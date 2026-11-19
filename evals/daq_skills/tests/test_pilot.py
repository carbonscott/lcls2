"""Tests for family C in run.py (root views of real MFX logs), cold-start scoring in score.py, evidence.py on
family C, and pilot.py end to end.  No model calls: the agent, the extractor and the judge are scripted.

    python3 -m unittest discover -s tests -v
"""
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import evidence   # noqa: E402
import pilot      # noqa: E402
import real_mfx   # noqa: E402
import run        # noqa: E402
import score      # noqa: E402
import tree       # noqa: E402
from test_v3 import Fixture   # noqa: E402

EVAL = os.path.dirname(HERE)
REAL = json.load(open(os.path.join(EVAL, 'cases_real.json')))


def put(root, rel, lines, mtime_local):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    t = tree.epoch(datetime.datetime.strptime(mtime_local, '%Y-%m-%d %H:%M:%S'))
    os.utime(p, (t, t))
    return p


class RealWorld(object):
    """A tiny prepared root of 'real' MFX logs and a family-C case table for it."""

    def make_real(self, tmp):
        self.real_root = os.path.join(tmp, 'real-root')
        old, cur = 'home/m/mfxopr/2026/09', 'home/m/mfxopr/daq/logs/2026/09'
        ctl = '16_15:05:23_drp-srcf-cmp014:control.log'
        put(self.real_root, os.path.join(old, ctl), [
            '# HOST: drp-srcf-cmp014',
            '2026-09-16 15:05:30,100 mfx-control[11]: <I> rollcall done for the partition of today',
            '2026-09-16 15:06:44,200 mfx-control[11]: <E> timing_1 did not respond to alloc',
            '2026-09-16 15:06:59,300 mfx-control[11]: <E> alloc failed to change state'], '2026-09-16 15:07:00')
        put(self.real_root, os.path.join(old, '16_15:05:23_drp-srcf-cmp014:timing_1.log'), [
            '2026-09-16 15:06:40,000 mfx-drp[12]: <E> Illegal XPM Remote link id 0xdeadbeef from the remote link'],
            '2026-09-16 15:07:00')
        put(self.real_root, os.path.join(old, '15_14:37:58_drp-srcf-cmp014:control.log'), [
            '2026-09-15 14:38:01,000 mfx-control[21]: <I> state running enter callbacks finished for this one'], '2026-09-15 15:02:30')
        put(self.real_root, os.path.join(cur, '17_09:29:03_drp-srcf-cmp014:control.log'), [
            '2026-09-17 09:29:05,000 mfx-control[31]: <I> the first launch in the new tree, before now'], '2026-09-17 09:31:00')
        put(self.real_root, os.path.join(cur, '17_11:00:00_drp-srcf-cmp014:control.log'), [
            '2026-09-17 11:00:05,000 mfx-control[41]: <I> a launch after the case was asked, must not exist'], '2026-09-17 11:05:00')
        put(self.real_root, 'home/m/mfxopr/daq/logs/2026/10/01_08:00:00_drp-srcf-cmp014:control.log', ['later'], '2026-10-01 08:10:00')
        put(self.real_root, 'home/m/mfxopr/daq/scripts/mfx.py', ['# edited later'], '2026-11-16 02:07:19')
        put(self.real_root, 'home/m/mfxopr/daq/scripts/qadc_pvlist.txt', ['MFX:QADC'], '2026-08-27 15:34:00')
        spec = dict((k, v) for k, v in REAL.items() if k != 'cases')
        launch = {'id': 'previous/2026/09/16_15:05:23', 'start': '2026-09-16T15:05:23', 'end': '2026-09-16T15:06:59',
                  'files': [{'name': ctl, 'sha256': 'x'}, {'name': '16_15:05:23_drp-srcf-cmp014:timing_1.log', 'sha256': 'x'}],
                  'key': {'component': {'component': 'timing_1', 'stage': 'alloc', 'kind': 'no_response',
                                        'mechanism': 'xpm-remote-link-id', 'first_time': '2026-09-16T15:06:44'}}}
        ok = {'id': 'previous/2026/09/15_14:37:58', 'start': '2026-09-15T14:37:58', 'end': '2026-09-15T15:02:30',
              'files': [{'name': '15_14:37:58_drp-srcf-cmp014:control.log', 'sha256': 'x'}], 'key': {'component': 'healthy'}}
        spec['cases'] = [
            {'id': 'real-t-fault', 'kind': 'fault', 'today': '2026-09-17', 'phrase': 'yesterday afternoon', 'cause_scope': 'component+stage',
             'target': launch['id'], 'keyed_launches': [launch['id']], 'launches': [launch],
             'operator': {'when': 'Around three in the afternoon.', 'symptom': 'It would not allocate.', 'what next': 'We restarted it.',
                          'detectors': 'The usual MFX set.'}},
            {'id': 'real-t-ok', 'kind': 'healthy', 'today': '2026-09-18', 'phrase': 'Tuesday afternoon', 'target': ok['id'],
             'keyed_launches': [ok['id']], 'launches': [ok], 'operator': {'when': 'Tuesday afternoon.'}}]
        self.real_spec = spec
        self.cases_real = os.path.join(tmp, 'cases_real.json')
        with open(self.cases_real, 'w') as f:
            json.dump(spec, f)


FAKE_AGENT = r'''
import json, os, subprocess, sys
prompt = sys.stdin.read()
root = os.environ.get("DAQ_EVAL_SDF", "/sdf")
def say(ev): print(json.dumps(ev)); sys.stdout.flush()
def tool(i, name, inp, out):
    say({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t%d" % i, "name": name, "input": inp}]}})
    say({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t%d" % i, "content": out}]}})
sh = lambda c: subprocess.run(c, shell=True, stdout=subprocess.PIPE, universal_newlines=True).stdout
ans = sh("ask-operator 'When was that?'").strip()
tool(1, "Bash", {"command": "ask-operator 'When was that?'"}, ans)
if "yesterday afternoon" in prompt:          # family C fault case
    tool(2, "Bash", {"command": "ls"}, sh("ls %s/home/m/mfxopr/2026/09" % root))
    tool(3, "Bash", {"command": "grep -h Illegal *timing_1.log"}, sh("grep -h Illegal %s/home/m/mfxopr/2026/09/*timing_1.log" % root))
    rec = {"verdict_kind": "fault", "launches": [{"time": "15:05:23", "date": "2026-09-16", "tz": "local", "status": "failed"}],
           "problems": [{"role": "cause", "launch_time": "15:05:23", "tz": "local", "component": "timing_1", "stage": "alloc",
                         "mechanism": "Illegal XPM Remote link id"}],
           "concluded_launch": {"time": "15:05:23", "date": "2026-09-16", "tz": "local"}, "basis": "cause"}
elif "Tuesday afternoon" in prompt:          # family C healthy case
    rec = {"verdict_kind": "no-fault", "launches": [{"time": "14:37:58", "date": "2026-09-15", "tz": "local", "status": "ok"}], "problems": [],
           "concluded_launch": {"time": "14:37:58", "date": "2026-09-15", "tz": "local"}, "basis": "reviewed"}
else:                                        # family B case c1 (tt_0, Verify error, 2026-11-17 12:12:52)
    tool(2, "Bash", {"command": "grep -h Verify *tt_0.log"}, sh("grep -h Verify %s/home/m/mfxopr/daq/logs/2026/11/*tt_0.log" % root))
    rec = {"verdict_kind": "fault", "launches": [{"time": "12:12:52", "date": "2026-11-17", "tz": "local", "status": "failed"}],
           "problems": [{"role": "cause", "launch_time": "12:12:52", "tz": "local", "component": "tt_0", "stage": "configure",
                         "mechanism": "Verify error for block Top.TriggerDelay"}],
           "concluded_launch": {"time": "12:12:52", "date": "2026-11-17", "tz": "local"}, "basis": "cause"}
say({"type": "result", "result": "Report (operator: %s)\nRECORD: %s\n" % (ans, json.dumps(rec)), "total_cost_usd": 0.02,
     "num_turns": 3, "usage": {"output_tokens": 9}, "modelUsage": {"claude-haiku-x": {}}})
'''
FAKE_EXTRACT = r'''
import json, sys
prompt = sys.stdin.read()
report = prompt.split('REPORT:\n<<<\n', 1)[1].rsplit('\n>>>', 1)[0]
rec = report.split('RECORD: ', 1)[1].strip() if 'RECORD: ' in report else '{"verdict_kind": "unsure"}'
print(json.dumps({"result": rec, "total_cost_usd": 0.01, "modelUsage": {"fake-extractor": {}}}))
'''
FAKE_JUDGE = r'''
import json, re, sys
prompt = sys.stdin.read()
open(sys.argv[1], 'a').write('j')
items = [{"item": int(n), "verdict": "accepted" if "Verify error" in st else "other", "matched": "A1", "reason": "fake"}
         for n, st in re.findall(r'ITEM (\d+)\nSTATEMENT:\n<<<\n(.*?)\n>>>', prompt, re.S)]
print(json.dumps({"result": json.dumps({"items": items}), "total_cost_usd": 0.002, "modelUsage": {"fake-judge": {}}}))
'''


def c1_keys():
    """keys_v3-shaped keys for the Fixture's case c1."""
    return {'version': 3, 'tz_offset_hours': -8, 'pools': {}, 'cases': {'c1': {
        'id': 'c1', 'kind': 'fault', 'pool': 'one', 'launch_keyed': False, 'known_issues': [],
        'launches': [{'prefix': '09_12:12:52', 'start': '2026-11-09 12:12:52', 'first': '2026-11-09 12:12:52', 'last': '2026-11-09 12:14:04',
                      'files': ['09_12:12:52_sdfmilan001:control.log']}],
        'component': {'name': 'tt_0', 'aliases': ['tt_0', 'timetool'], 'not': ['teb0', 'control']},
        'stage': {'name': 'configure', 'aliases': ['configure', 'configuration']},
        'mechanism': {'summary': 'Verify error', 'accepted': ['tt_0 Verify error for block Top.TriggerDelay'], 'near_miss': ['did not respond']}}}}


class World(Fixture, RealWorld):
    def make_all(self):
        Fixture.make(self)
        self.make_real(self.tmp)
        self.keys = os.path.join(self.tmp, 'keys.json')
        json.dump(c1_keys(), open(self.keys, 'w'))
        for name, body in (('agent.py', FAKE_AGENT), ('x.py', FAKE_EXTRACT), ('j.py', FAKE_JUDGE)):
            open(os.path.join(self.tmp, name), 'w').write(body)
        self.agent = '%s %s' % (sys.executable, os.path.join(self.tmp, 'agent.py'))
        self.judged = os.path.join(self.tmp, 'judged')
        self.xcmd = '%s %s' % (sys.executable, os.path.join(self.tmp, 'x.py'))
        self.jcmd = '%s %s %s' % (sys.executable, os.path.join(self.tmp, 'j.py'), self.judged)
        self.views = os.path.join(self.tmp, 'views')
        self.out = os.path.join(self.tmp, 'results')


class Views(unittest.TestCase, RealWorld):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='daqevalC-')
        self.make_real(self.tmp)
        self.case = self.real_spec['cases'][0]
        self.dest = os.path.join(self.tmp, 'views')
        self.root, self.rec = real_mfx.build_view(self.real_root, self.case, real_mfx.case_now(self.real_spec, self.case), self.dest)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def files(self):
        return sorted(os.path.relpath(os.path.join(d, f), self.root) for d, _s, fs in os.walk(self.root) for f in fs)

    def test_view_holds_only_what_existed_at_now(self):
        self.assertEqual(real_mfx.case_now(self.real_spec, self.case), '2026-09-17 10:00')
        self.assertEqual(self.files(), ['home/m/mfxopr/2026/09/15_14:37:58_drp-srcf-cmp014:control.log',
                                        'home/m/mfxopr/2026/09/16_15:05:23_drp-srcf-cmp014:control.log',
                                        'home/m/mfxopr/2026/09/16_15:05:23_drp-srcf-cmp014:timing_1.log',
                                        'home/m/mfxopr/daq/logs/2026/09/17_09:29:03_drp-srcf-cmp014:control.log',
                                        'home/m/mfxopr/daq/scripts/qadc_pvlist.txt'])
        self.assertFalse(os.path.exists(os.path.join(self.root, 'home/m/mfxopr/daq/logs/2026/10')))   # no empty future month
        self.assertEqual((self.rec['kept'], self.rec['dropped'], self.rec['newest_launch_stamp']), (5, 3, '2026-09-17 09:29:03'))

    def test_view_is_hard_links_with_its_record_outside_the_mounted_root(self):
        rel = 'home/m/mfxopr/2026/09/16_15:05:23_drp-srcf-cmp014:timing_1.log'
        self.assertTrue(os.path.samefile(os.path.join(self.root, rel), os.path.join(self.real_root, rel)))
        self.assertEqual(sorted(os.listdir(os.path.join(self.dest, self.case['id']))), ['root', 'view.json'])
        self.assertLessEqual(os.stat(os.path.join(self.root, 'home')).st_mtime,
                             tree.epoch(datetime.datetime(2026, 9, 17, 10, 0)))       # folders never look newer than now

    def test_view_is_reused_and_a_different_now_is_refused(self):
        again, rec = real_mfx.build_view(self.real_root, self.case, '2026-09-17 10:00', self.dest)
        self.assertEqual((again, rec), (self.root, self.rec))
        with self.assertRaises(SystemExit):
            real_mfx.build_view(self.real_root, self.case, '2026-09-18 10:00', self.dest)

    def test_pointer_and_today(self):
        self.assertEqual(real_mfx.pointer(self.case), 'The DAQ logs are in /sdf/home/m/mfxopr/2026/09, and the launch in question '
                                                      'ran on 2026-09-16 between 15:05 and 15:07.')
        self.assertEqual(real_mfx.today_long('2026-09-17'), 'Thursday, September 17, 2026')

    def test_bundled_cases_have_scope_rules_and_now(self):
        self.assertEqual(REAL['now_time'], '10:00')
        for c in REAL['cases']:
            self.assertEqual(c.get('cause_scope'), 'component+stage' if c['kind'] == 'fault' else None, c['id'])
            self.assertTrue(set(c['operator']) <= set(r['id'] for r in REAL['operator_rules']), c['id'])
            w0, w1 = real_mfx.widest_window(c['today'], c['phrase'])
            self.assertLessEqual(w1, datetime.datetime.strptime(real_mfx.case_now(REAL, c), '%Y-%m-%d %H:%M'), c['id'])


class OperatorAnswers(unittest.TestCase):
    """Families B and C: the operator never names the keyed component (or a word of its name) or lists detectors."""

    def words(self, comp):
        return set(w for w in re.split(r'[_\d]+', comp.lower()) if len(w) > 2) | {comp.lower()}

    def test_answers_are_stage_level_at_most(self):
        keys = score.load_keys(os.path.join(EVAL, 'keys_v3.json'))
        v3 = json.load(open(os.path.join(EVAL, 'cases_v3.json')))
        answers = [(c['id'], c['m1']['answers'], keys['cases'][c['id']].get('component', {}).get('aliases', [])) for c in v3['cases']]
        for c in REAL['cases']:
            comp = real_mfx.target_launch(c)['key']['component']
            answers.append((c['id'], c['operator'], sorted(self.words(comp['component'])) if isinstance(comp, dict) else []))
        detectors = ('jungfrau', 'epix', 'alvium', 'camera', 'qadc', 'timing', 'bld', 'epics', 'wave8', 'pvcam', 'fakecam', 'drp')
        for cid, table, banned in answers:
            text = ' '.join(table.values()).lower()
            for w in list(banned) + list(detectors):
                self.assertIsNone(re.search(r'(?<![a-z])%s' % re.escape(w.lower()), text), (cid, w, text))


class RunC(unittest.TestCase, World):
    def setUp(self):
        self.make_all()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_(self, arm, case, control=None, extra=()):
        args = ['--catalog', self.catalog, '--cases-v3', self.cases_v3, '--cases-real', self.cases_real, '--work', self.work,
                '--arm', arm, '--out', self.out, '--no-sandbox', '--agent-cmd', self.agent, '--mode', 'm1', '--skills', 'none',
                '--real-root', self.real_root, '--views', self.views, '--case', case] + list(extra)
        if control:
            args += ['--control', control]
        return run.main(args)

    def one(self, arm):
        (name,) = os.listdir(os.path.join(self.out, arm))
        return os.path.join(self.out, arm, name)

    def test_family_c_prompt_operator_and_meta(self):
        self.assertEqual(self.run_('C.none', 'real-t-fault'), 0)
        d = self.one('C.none')
        prompt = open(os.path.join(d, 'prompt.txt')).read()
        self.assertIn('It is now Thursday 2026-09-17, 10:00 (US Pacific time', prompt)
        self.assertIn('Today is Thursday, September 17, 2026. The MFX operators asked us to look at their DAQ yesterday afternoon.', prompt)
        for leak in ('/sdf', 'mfxopr', '15:05', '2026-09-16', 'timing'):
            self.assertNotIn(leak, prompt)
        (q,) = [json.loads(l) for l in open(os.path.join(d, 'operator.jsonl'))]
        self.assertEqual((q['rule'], q['answer']), ('when', 'Around three in the afternoon.'))
        meta = json.load(open(os.path.join(d, 'meta.json')))
        self.assertEqual((meta['family'], meta['mode'], meta['now'], meta['keyed_stamp'], meta['keyed_dir']),
                         ('C', 'm1', '2026-09-17 10:00', '16_15:05:23', '/sdf/home/m/mfxopr/2026/09'))
        self.assertEqual(meta['logs_src'], os.path.join(self.views, 'real-t-fault', 'root'))

    def test_family_c_operator_rules_and_default(self):
        row = run.real_case_row(type('A', (), {'real': self.real_spec})(), self.real_spec['cases'][0])
        self.assertEqual(run.operator_answer(self.real_spec, row, 'What did you do after that?')[1], 'what next')
        self.assertEqual(run.operator_answer(self.real_spec, row, 'Which detectors were in the partition?')[1], 'detectors')
        self.assertEqual(run.operator_answer(self.real_spec, row, 'What error message did you see?')[1], 'symptom')
        self.assertEqual(run.operator_answer(self.real_spec, row, 'Where are the logs?'), (self.real_spec['operator_default'], None))

    def test_family_c_pointer_names_the_old_root_and_the_window(self):
        self.run_('C.pointer', 'real-t-fault', 'pointer')
        prompt = open(os.path.join(self.one('C.pointer'), 'prompt.txt')).read()
        self.assertTrue(prompt.endswith('The DAQ logs are in %s/home/m/mfxopr/2026/09, and the launch in question ran on 2026-09-16 '
                                        'between 15:05 and 15:07.' % os.path.join(self.views, 'real-t-fault', 'root')), prompt[-200:])

    def test_family_c_refuses_starved_and_m0(self):
        with self.assertRaises(SystemExit):
            self.run_('x', 'real-t-fault', 'starved')
        with self.assertRaises(SystemExit):
            run.main(['--catalog', self.catalog, '--work', self.work, '--arm', 'x', '--out', self.out, '--skills', 'none',
                      '--case', 'real-t-fault', '--dry-run'])

    def test_evidence_uses_the_target_launch_files(self):
        self.run_('C.none', 'real-t-fault')
        r = evidence.evaluate(self.one('C.none'), {}, {}, self.work, dict((c['id'], c) for c in self.real_spec['cases']))
        self.assertEqual((r['family'], r['calls'], r['censored'], r['first']['index']), ('C', 2, False, 3))


class ColdKeys(unittest.TestCase, World):
    def setUp(self):
        self.make_all()
        self.book = score.KeyBook(c1_keys(), self.table, self.real_spec)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_family_b_key_moves_the_launch_to_the_m1_day(self):
        k = self.book.key('c1', 'm1')
        self.assertEqual(k['launches'][0]['prefix'], '17_12:12:52')
        self.assertEqual((k['launches'][0]['start'], k['launches'][0]['last']), ('2026-11-17 12:12:52', '2026-11-17 12:14:04'))
        self.assertEqual(k['launches'][0]['files'], self.table['cases'][0]['m1']['keyed_files'])
        self.assertEqual((k['cold'], k['launch_keyed'], k['tz_offset_hours']), ('B', False, -8))
        self.assertEqual(self.book.key('c1', 'm0')['launches'][0]['prefix'], '09_12:12:52')     # m0 keeps the catalog key

    def test_family_c_key_from_the_case_table(self):
        k = self.book.key('real-t-fault', 'm1')
        self.assertEqual((k['kind'], k['cause_scope'], k['component']['aliases'], k['stage']['name'], k['tz_offset_hours']),
                         ('fault', 'component+stage', ['timing_1', 'timing'], 'alloc', -7))
        self.assertIsNone(k['mechanism'])
        self.assertEqual(self.book.key('real-t-ok', 'm1')['kind'], 'healthy')
        self.assertEqual(score.KeyBook(score.load_keys(os.path.join(EVAL, 'keys_v3.json'))).key('x', 'm1'), None)

    def caller(self):
        xc, jc = score.Caller('fake', self.xcmd.split()), score.Caller('fake', self.jcmd.split())

        class Both:
            def call(self, prompt, kind, tag='', name=None):
                return (xc if kind in ('extract', 'conclude') else jc).call(prompt, kind, tag, name)
        return Both()

    def rep(self, rec):
        return 'A report.\nRECORD: %s\n' % json.dumps(rec)

    def test_family_c_cause_is_located_component_and_stage_without_a_judge(self):
        k = self.book.key('real-t-fault', 'm1')
        good = {'verdict_kind': 'fault', 'launches': [{'time': '15:05:23', 'tz': 'local'}],
                'problems': [{'role': 'cause', 'component': 'timing_1 DRP', 'stage': 'alloc transition', 'mechanism': 'link id'}],
                'concluded_launch': {'time': '15:05:23', 'tz': 'local'}, 'basis': 'cause'}
        r = score.score_report(k, c1_keys(), self.rep(good), self.caller())
        self.assertEqual((r['facts']['located'], r['outcome']['cause'], r['mechanism']['verdict'], r['calls']['judge']),
                         (True, True, 'not scored', []))
        self.assertEqual(len(r['calls']['conclude']), 1)
        self.assertFalse(os.path.exists(self.judged))
        utc = dict(good, concluded_launch={'time': '22:05:23', 'tz': 'UTC', 'date': '2026-09-16'})      # PDT: 15:05:23 local
        self.assertTrue(score.score_report(k, c1_keys(), self.rep(utc), self.caller())['facts']['located'])
        elsewhere = dict(good, launches=[{'time': '13:58:21', 'tz': 'local'}], concluded_launch={'time': '13:58:21', 'tz': 'local'})
        r = score.score_report(k, c1_keys(), self.rep(elsewhere), self.caller())
        self.assertEqual((r['facts']['located'], r['outcome']['cause']), (False, False))
        blame_control = dict(good, problems=[dict(good['problems'][0], component='control')])
        self.assertFalse(score.score_report(k, c1_keys(), self.rep(blame_control), self.caller())['outcome']['cause'])

    def test_family_b_cause_needs_located_and_an_accepted_mechanism(self):
        k = self.book.key('c1', 'm1')
        rec = {'verdict_kind': 'fault', 'launches': [], 'problems': [{'role': 'cause', 'component': 'tt_0', 'stage': 'configure',
                                                                       'mechanism': 'Verify error for block Top.TriggerDelay'}]}
        here = dict(rec, concluded_launch={'time': '17_12:12:52', 'tz': 'unstated'}, basis='cause')
        r = score.score_report(k, c1_keys(), self.rep(here) + ' launch 17_12:12:52', self.caller())
        self.assertEqual((r['facts']['located'], r['outcome']['cause']), (True, True))
        r = score.score_report(k, c1_keys(), self.rep(rec), self.caller())          # right cause, launch never named
        self.assertEqual((r['facts']['located'], r['outcome']['cause']), (False, False))
        there = dict(rec, concluded_launch={'time': '17_13:20:00', 'tz': 'unstated'}, basis='cause')
        r = score.score_report(k, c1_keys(), self.rep(there) + ' launch 17_13:20:00', self.caller())   # another launch of that day
        self.assertEqual((r['facts']['located'], r['outcome']['cause']), (False, False))

    def test_located_is_the_launch_the_report_concludes_about_not_one_it_lists(self):
        k = self.book.key('c1', 'm1')
        cause = [{'role': 'cause', 'launch_time': '13:20:00', 'tz': 'local', 'component': 'tt_0', 'stage': 'configure',
                  'mechanism': 'Verify error for block Top.TriggerDelay'}]
        listed = {'verdict_kind': 'fault', 'problems': cause, 'concluded_launch': {'time': '13:20:00', 'tz': 'local'}, 'basis': 'cause',
                  'launches': [{'time': '12:12:52', 'tz': 'local', 'status': 'unclear'}, {'time': '13:20:00', 'tz': 'local', 'status': 'failed'}]}
        text = self.rep(listed) + ' Sessions examined: 17_12:12:52, 17_13:20:00.  The failure was in 17_13:20:00.'
        r = score.score_report(k, c1_keys(), text, self.caller())
        self.assertEqual((r['facts']['located'], r['facts']['keyed_named_anywhere'], r['facts']['concluded_launch'], r['outcome']['cause']),
                         (False, True, None, False))
        mine = dict(listed, concluded_launch={'time': '12:13:30', 'date': '2026-11-17', 'tz': 'local'})       # a time inside the launch
        r = score.score_report(k, c1_keys(), self.rep(mine), self.caller())
        self.assertEqual((r['facts']['located'], r['facts']['concluded_launch']), (True, '17_12:12:52'))
        r = score.score_report(k, c1_keys(), self.rep(dict(listed, concluded_launch=None, basis='none')), self.caller())
        self.assertEqual((r['facts']['located'], r.get('error')), (False, None))

    def test_family_c_healthy_is_three_way(self):
        k = self.book.key('real-t-ok', 'm1')
        clean = {'verdict_kind': 'no-fault', 'launches': [{'time': '14:37:58'}], 'problems': [],
                 'concluded_launch': {'time': '14:37:58'}, 'basis': 'reviewed'}
        r = score.score_report(k, c1_keys(), self.rep(clean), self.caller())
        self.assertEqual((r['outcome']['outcome'], r['facts']['located']), ('clean', True))
        other = dict(clean, launches=[{'time': '14:37:58'}, {'time': '12:39:26'}], concluded_launch={'time': '12:39:26'})
        r = score.score_report(k, c1_keys(), self.rep(other), self.caller())    # reviewed another session; this one only listed
        self.assertEqual((r['outcome']['outcome'], r['facts']['located'], r['facts']['keyed_named_anywhere']), ('clean', False, True))
        alarm = {'verdict_kind': 'fault', 'launches': [], 'problems': [{'role': 'cause', 'component': 'x', 'stage': '', 'mechanism': 'y'}]}
        self.assertEqual(score.score_report(k, c1_keys(), self.rep(alarm), self.caller())['outcome']['outcome'], 'false-alarm')


class Pilot(unittest.TestCase, World):
    def setUp(self):
        self.make_all()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def pilot(self, *extra):
        args = ['--out', self.out, '--work', self.work, '--real-root', self.real_root, '--views', self.views,
                '--catalog', self.catalog, '--cases-v3', self.cases_v3, '--cases-real', self.cases_real, '--keys', self.keys,
                '--agent-cmd', self.agent, '--no-sandbox', '--extract-cmd', self.xcmd, '--judge-cmd', self.jcmd,
                '--cell', 'B/none/haiku/all/2', '--cell', 'B/pointer/haiku', '--cell', 'C/none/haiku/all/1',
                '--cell', 'C/pointer/haiku/real-t-fault'] + list(extra)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = pilot.main(args)
        return rc, buf.getvalue()

    def test_refuses_a_batch_over_the_budget_and_prints_the_estimate(self):
        rc, out = self.pilot('--budget-left', '0.5')
        self.assertEqual(rc, 2)
        self.assertIn('per-run estimate: model haiku    agent $0.100 (table) + scorer $0.060', out)
        self.assertIn('6 to do; projected usage $0.96', out)
        self.assertIn('refusing to start', out)
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self.pilot()[0], 2)                         # no --budget-left: refused too

    def test_batch_runs_scores_and_writes_rows_verdict_reads(self):
        rc, out = self.pilot('--budget-left', '5', '--jobs', '2')
        self.assertEqual(rc, 0, out)
        rows = json.load(open(os.path.join(self.out, 'rows.json')))
        self.assertEqual(len(rows), 6)
        by = dict(((r['family'], r['arm'], r['case'], r['repeat']), r) for r in rows)
        b = by[('B', 'none', 'c1', 2)]
        self.assertEqual((b['mode'], b['model'], b['healthy'], b['cause_pass'], b['located'], b['calls'], b['cost_usd'], b['exit']),
                         ('m1', 'haiku', False, True, True, 1, 0.02, 0))
        c = by[('C', 'none', 'real-t-fault', 1)]
        self.assertEqual((c['cause_pass'], c['located'], c['calls'], c['healthy_outcome']), (True, True, 2, None))
        h = by[('C', 'none', 'real-t-ok', 1)]
        self.assertEqual((h['healthy'], h['healthy_outcome'], h['cause_pass'], h['located']), (True, 'clean', None, True))
        self.assertEqual(sorted(set(r['run_id'].split('/')[0] for r in rows)), ['B.none.haiku', 'B.pointer.haiku', 'C.none.haiku',
                                                                              'C.pointer.haiku'])
        usage = json.load(open(os.path.join(self.out, 'usage.json')))
        self.assertEqual((usage['agent_usd'], usage['runs']), (0.12, 6))
        self.assertAlmostEqual(usage['scorer_usd'], 6 * 0.01 * 2 + 3 * 0.002 * 3)  # extraction and conclusion each; 3 judge votes on 3 B runs
        v = subprocess.run([sys.executable, os.path.join(EVAL, 'verdict.py'), os.path.join(self.out, 'rows.json')],
                           stdout=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(v.returncode, 0)
        self.assertIn('P6_overall', json.loads(v.stdout))
        # resume keeps every run and re-scores from the cache
        rc, out = self.pilot('--budget-left', '0', '--resume')
        self.assertEqual(rc, 0, out)
        self.assertIn('0 to do; projected usage $0.00', out)

    def test_cells_file_and_unknown_case(self):
        cells = os.path.join(self.tmp, 'cells.json')
        json.dump([{'family': 'C', 'arm': 'map', 'model': 'default', 'cases': ['real-t-ok'], 'repeats': 1}], open(cells, 'w'))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = pilot.main(['--out', self.out, '--work', self.work, '--real-root', self.real_root, '--cases-real', self.cases_real,
                             '--cases-v3', self.cases_v3, '--cells', cells, '--map', self.tmp, '--dry-run'])
        self.assertEqual(rc, 0)
        self.assertIn('C.map.default', buf.getvalue())
        self.assertIn('agent $2.000 (table)', buf.getvalue())
        with self.assertRaises(SystemExit):
            pilot.main(['--out', self.out, '--work', self.work, '--cases-v3', self.cases_v3, '--cases-real', self.cases_real,
                        '--cell', 'B/none/haiku/nope', '--dry-run'])
        with self.assertRaises(SystemExit):
            pilot.main(['--out', self.out, '--work', self.work, '--cases-v3', self.cases_v3, '--cases-real', self.cases_real,
                        '--cell', 'C/starved', '--dry-run'])

    def test_run_command_per_arm(self):
        a = type('A', (), dict(work='/w', out='/o', catalog='cat', cases_v3='v3', cases_real='cr', real_root='/r', views='/v',
                               roots=None, resume=True, agent_cmd=None, no_sandbox=False, expose=[], timeout=60,
                               skills='/sk', map='/map'))()
        cell = pilot.normalize({'family': 'C', 'arm': 'both', 'model': 'haiku', 'cases': 'all'}, {'v3': self.table, 'real': self.real_spec})
        cmd = ' '.join(pilot.run_cmd(a, cell, 'real-t-ok', 2))
        for part in ('--arm C.both.haiku', '--mode m1', '--case real-t-ok --first-repeat 2 --repeats 1', '--skills /sk --skills /map',
                     '--model haiku', '--family C', '--real-root /r --views /v', '--resume'):
            self.assertIn(part, cmd)
        cell = pilot.normalize({'family': 'A', 'arm': 'crib', 'model': 'default'}, {'v3': self.table, 'real': self.real_spec})
        cmd = ' '.join(pilot.run_cmd(a, cell, 'c1', 1))
        self.assertIn('--mode m0', cmd)
        self.assertIn('--skills none --control crib', cmd)
        self.assertNotIn('--model', cmd)


if __name__ == '__main__':
    unittest.main()
