"""Tests for score.py, the v3 fact-level scorer, and for keys_v3.json.  No model calls: the
extractor and the mechanism judge are scripted.

    python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import make_keys_v3  # noqa: E402
import score         # noqa: E402

KEYS = score.load_keys(os.path.join(os.path.dirname(HERE), 'keys_v3.json'))

# The fake extractor returns the record written in the report after 'RECORD: ', and counts its calls.
FAKE_EXTRACT = r'''
import json, sys
prompt = sys.stdin.read()
report = prompt.split('REPORT:\n<<<\n', 1)[1].rsplit('\n>>>', 1)[0]
if len(sys.argv) > 1:
    open(sys.argv[1], 'a').write('x')
rec = report.split('RECORD: ', 1)[1].strip() if 'RECORD: ' in report else '{"verdict_kind": "unsure"}'
print(json.dumps({"result": rec, "total_cost_usd": 0.01, "modelUsage": {"fake-extractor": {}}}))
'''
# The fake judge: 'Verify error' is accepted, 'did not respond' a near-miss, anything else other.
FAKE_JUDGE = r'''
import json, re, sys
prompt = sys.stdin.read()
if len(sys.argv) > 1:
    open(sys.argv[1], 'a').write('j')
items = []
for n, st in re.findall(r'ITEM (\d+)\nSTATEMENT:\n<<<\n(.*?)\n>>>', prompt, re.S):
    v = 'accepted' if 'Verify error' in st or 'TypeError' in st or 'illegal XtcData' in st or 'hung' in st else (
        'near-miss' if 'did not respond' in st else 'other')
    items.append({"item": int(n), "verdict": v, "matched": "none", "reason": "fake"})
print(json.dumps({"result": json.dumps({"items": items}), "total_cost_usd": 0.002, "modelUsage": {"fake-judge": {}}}))
'''


def rec(verdict='fault', problems=(), launches=(), asks=()):
    return {'verdict_kind': verdict, 'launches': list(launches), 'problems': list(problems), 'asks_operator': list(asks),
            'confidence': None}


def cause(component, stage, mechanism, time=None, tz='unstated', role='cause'):
    return {'role': role, 'launch_time': time, 'tz': tz, 'component': component, 'stage': stage, 'mechanism': mechanism}


def report(record, text='A report.'):
    return '%s\nRECORD: %s\n' % (text, json.dumps(record))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='score-')
        self.count = os.path.join(self.tmp, 'count')
        for name, body in (('x.py', FAKE_EXTRACT), ('j.py', FAKE_JUDGE)):
            with open(os.path.join(self.tmp, name), 'w') as f:
                f.write(body)
        self.xcmd = [sys.executable, os.path.join(self.tmp, 'x.py'), self.count]
        self.jcmd = [sys.executable, os.path.join(self.tmp, 'j.py'), self.count]

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def caller(self, cache=None):
        xc = score.Caller('fake', self.xcmd, cache)
        jc = score.Caller('fake', self.jcmd, cache)
        jc.sem = xc.sem

        class Both:
            def call(self, prompt, kind, tag='', name=None):
                return (xc if kind == 'extract' else jc).call(prompt, kind, tag, name)
        return Both()

    def score(self, case, record, text='A report.', cache=None):
        return score.score_report(KEYS['cases'][case], KEYS, report(record, text), self.caller(cache))

    def calls(self):
        if not os.path.exists(self.count):
            return ''
        with open(self.count) as f:
            return f.read()


class Keys(unittest.TestCase):
    def test_keys_file_is_what_the_builder_writes(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(make_keys_v3.main(['--check']), 0)

    def test_every_scored_case_has_a_key_with_closed_lists(self):
        with open(os.path.join(os.path.dirname(HERE), 'catalog.json')) as f:
            cat = json.load(f)
        want = {c['id'] for c in cat['cases'] if c['set'] in ('core', 'full')}
        self.assertEqual(set(KEYS['cases']), want)
        for cid, k in KEYS['cases'].items():
            if k['kind'] == 'fault':
                self.assertTrue(k['mechanism']['accepted'] and k['mechanism']['near_miss'], cid)
                self.assertTrue(k['component']['aliases'] and k['stage']['aliases'], cid)
            elif k['kind'] == 'multi':
                self.assertTrue(all(f['mechanism']['accepted'] and f['mechanism']['near_miss'] for f in k['failed']))
            else:
                self.assertIn('benign', k, cid)
        self.assertIn('double-free-exit', [b['id'] for b in KEYS['cases']['healthy-tt']['benign']])

    def test_the_extractor_never_sees_the_key_or_the_arm(self):
        k = KEYS['cases']['reg-cfg-tt']
        for prompt in (score.EXTRACT_PROMPT.format(report='REPORT TEXT'), score.CONCLUDE_PROMPT.format(report='REPORT TEXT', now='2026-11-18 09:40')):
            for leak in [k['mechanism']['accepted'][0], k['mechanism']['near_miss'][0], 'TriggerDelay', 'skills', 'reg-cfg-tt',
                         k['question'], 'map', 'pointer', 'keyed']:
                self.assertNotIn(leak, prompt)

    def test_the_conclusion_call_is_told_when_the_operator_asked(self):
        class Cap:
            prompts = []

            def call(self, prompt, kind, tag='', name=None):
                self.prompts.append((kind, prompt, name))
                return {'text': '{"concluded_launch": null, "basis": "none", "quote": ""}', 'cost_usd': 0.0,
                        'model': 'x', 'cached': False, 'error': None}
        cap = Cap()
        score.conclude(cap, 'A report about yesterday.', '2026-11-18 09:40')
        kind, prompt, name = cap.prompts[0]
        self.assertEqual((kind, name), ('conclude', None))          # cached by the whole prompt, so a new 'now' re-asks
        self.assertIn('The operator asked on 2026-11-18 09:40', prompt)

    def test_m0_runs_make_no_conclusion_call(self):
        kinds = []

        class Caller:
            def call(self, prompt, kind, tag='', name=None):
                kinds.append(kind)
                return {'text': '{"verdict_kind": "unsure"}', 'cost_usd': 0, 'model': 'm', 'cached': False, 'error': None}
        r = score.score_report(KEYS['cases']['reg-cfg-tt'], KEYS, 'A report.', Caller())
        self.assertEqual((kinds, 'conclude' in r['calls']), (['extract'], False))


class ScriptedFacts(unittest.TestCase):
    def test_component_aliases_and_wrongly_blamed_components(self):
        kc = KEYS['cases']['ctl-blames-meb']['component']
        for said in ('fakecam_0', '`fakecam_0` (DRP)', 'the DRP fakecam_0', 'drp/fakecam_0'):
            self.assertTrue(score.component_ok(kc, said), said)
        for said in ('meb0', 'meb0 (because fakecam_0 died)', 'teb0', 'fakecam_01', '', 'fakecam_0 + meb0 + teb0'):
            self.assertFalse(score.component_ok(kc, said), said)

    def test_stage_aliases_are_whole_words(self):
        ks = KEYS['cases']['reg-connect-fakecam']['stage']
        self.assertTrue(score.stage_ok(ks, 'Connect transition'))
        self.assertFalse(score.stage_ok(ks, 'disconnect'))
        self.assertTrue(score.stage_ok(KEYS['cases']['reg-cfg-tt']['stage'], 'configure (phase 1)'))
        self.assertTrue(score.stage_ok(KEYS['cases']['startup-crash-tt-q']['stage'], 'startup, before rollcall'))

    def test_times_resolve_to_the_launch_that_holds_them(self):
        k = KEYS['cases']['day-last-good']
        L = score.pool_launches(KEYS, k)
        at = lambda t, tz='local': score.resolve(score.to_local(t, None, tz, '2026-11-09'), L)
        self.assertEqual(at('12:21:27'), '09_12:21:27')          # 70 s apart: each stamp keeps its own launch
        self.assertEqual(at('12:22:37'), '09_12:22:37')
        self.assertEqual(at('12:23:40'), '09_12:22:37')          # an event inside the launch
        self.assertEqual(at('20:22:37', 'UTC'), '09_12:22:37')    # UTC is converted
        self.assertEqual(at('09_12:12:52'), '09_12:12:52')       # a log-file prefix
        self.assertEqual(at('12:23'), '09_12:22:37')
        self.assertIsNone(at('10:30:00'))                         # no launch within 2 minutes

    def test_one_launch_pool_uses_the_two_minute_rule(self):
        k = KEYS['cases']['reg-cfg-tt']
        L = score.pool_launches(KEYS, k)
        self.assertEqual(score.resolve(score.to_local('12:11:00', None, 'local', '2026-11-09'), L), '09_12:12:52')
        self.assertIsNone(score.resolve(score.to_local('12:09:00', None, 'local', '2026-11-09'), L))


class Outcomes(Base):
    def test_fault_cause_needs_component_stage_and_an_accepted_mechanism(self):
        good = cause('tt_0', 'configure', 'tt_0 aborted: Verify error for block ...TriggerDelay')
        r = self.score('reg-cfg-tt', rec(problems=[good]))
        self.assertTrue(r['outcome']['cause'] and r['outcome']['cause_strict'])
        self.assertEqual(r['mechanism']['votes'], ['accepted'] * 3)
        self.assertIsNone(r['facts']['launch'])                   # one launch in the pool: not scored
        for bad, fact in ((cause('teb0', 'configure', 'Verify error'), 'component'),
                          (cause('tt_0', 'enable', 'Verify error'), 'stage')):
            r = self.score('reg-cfg-tt', rec(problems=[bad]))
            self.assertFalse(r['outcome']['cause'])
            self.assertFalse(r['facts'][fact])
        r = self.score('reg-cfg-tt', rec(problems=[cause('tt_0', 'configure', 'tt_0 did not respond to configure')]))
        self.assertEqual((r['mechanism']['verdict'], r['outcome']['cause']), ('near-miss', False))

    def test_no_cause_fails_without_a_judge_call(self):
        r = self.score('reg-cfg-tt', rec('no-fault'))
        self.assertFalse(r['outcome']['cause'])
        self.assertEqual(r['mechanism']['verdict'], 'none')
        self.assertEqual(self.calls(), 'x')

    def test_main_conclusion_is_the_first_cause(self):
        r = self.score('reg-cfg-tt', rec(problems=[cause('teb0', 'configure', 'lost its DRP link'),
                                                   cause('tt_0', 'configure', 'Verify error')]))
        self.assertFalse(r['outcome']['cause'])

    def test_many_launch_pool_needs_the_keyed_launch(self):
        right = cause('tt_0', 'configure', 'Verify error on TriggerDelay', time='20:22:37', tz='UTC')
        r = self.score('day-window-utc', rec(problems=[right]))
        self.assertTrue(r['facts']['launch'] and r['outcome']['cause'] and r['facts']['located'])
        wrong = cause('tt_0', 'configure', 'Verify error on TriggerDelay', time='12:12:52')
        r = self.score('day-window-utc', rec(problems=[wrong]))
        self.assertFalse(r['facts']['launch'] or r['outcome']['cause'])
        # the report's cause for the keyed launch is used even when another launch comes first
        r = self.score('day-window-utc', rec(problems=[wrong, cause('tt_0', 'configure', 'Verify error', time='12:22:37')]))
        self.assertTrue(r['outcome']['cause'])
        self.assertEqual(r['facts']['picked'], 'cause of the keyed launch')

    def test_last_good_needs_both_launches(self):
        c = cause('tt_0', 'configure', 'Verify error', time='12:22:37')
        r = self.score('day-last-good', rec(problems=[c]))
        self.assertFalse(r['outcome']['cause'])
        r = self.score('day-last-good', rec(problems=[c], launches=[{'time': '12:21:27', 'status': 'ok', 'tz': 'local'}]))
        self.assertTrue(r['outcome']['cause'])

    def test_healthy_three_way(self):
        self.assertEqual(self.score('healthy-tt', rec('no-fault'))['outcome']['outcome'], 'clean')
        side = cause('tt_0', 'shutdown', 'free(): double free detected in tcache 2', role='side-issue')
        r = self.score('healthy-tt', rec('no-fault', problems=[side]))
        self.assertEqual(r['outcome']['outcome'], 'benign-defect-noted')
        self.assertIn('double-free-exit', r['facts']['benign_named'])
        # "Yes, one thing went wrong: tt_0 crashed at shutdown; the run was clean"
        said = cause('tt_0', 'shutdown', 'tt_0 crashed with a double free')
        self.assertEqual(self.score('healthy-tt', rec('no-fault', problems=[said]))['outcome']['outcome'], 'benign-defect-noted')
        self.assertEqual(self.score('healthy-tt', rec('fault', problems=[said]))['outcome']['outcome'], 'false-alarm')
        self.assertEqual(self.calls(), 'xxxx')                    # healthy cases never call the judge

    def test_day_count_needs_every_failed_launch_and_no_extra(self):
        fam = {'register': ('configure', 'Verify error'), 'typeerror': ('startup', 'TypeError: unexpected keyword'),
               'badname': ('configure', 'illegal XtcData::Name'), 'hang': ('configure', 'tt_0 hung, no error')}
        allc = [cause('tt_0', fam[f['family']][0], fam[f['family']][1], time=f['prefix'][3:])
                for f in KEYS['cases']['day-count']['failed']]
        r = self.score('day-count', rec(problems=allc))
        self.assertTrue(r['outcome']['cause'] and r['facts']['located'])
        self.assertEqual(r['outcome']['launches_right'], 9)
        self.assertEqual(self.calls().count('j'), 3)              # one judge call per vote for all nine launches
        r = self.score('day-count', rec(problems=allc[:-1]))
        self.assertFalse(r['outcome']['cause'])
        self.assertEqual(r['facts']['failed_found'], 8)
        r = self.score('day-count', rec(problems=allc + [cause('tt_0', 'configure', 'Verify error', time='12:21:27')]))
        self.assertEqual((r['outcome']['cause'], r['facts']['extra_failed']), (False, ['09_12:21:27']))


class Located(Base):
    def test_located_by_file_prefix_by_time_and_not_by_a_neighbour(self):
        self.assertTrue(self.score('healthy-tt', rec('no-fault'), 'See 09_12:21:27_sdfmilan082:tt_0.log')['facts']['located'])
        r = self.score('healthy-tt', rec('no-fault', launches=[{'time': '12:21', 'tz': 'local', 'status': 'ok'}]))
        self.assertTrue(r['facts']['located'])
        self.assertFalse(self.score('healthy-tt', rec('no-fault'), 'Nothing named.')['facts']['located'])
        r = self.score('day-last-good', rec(problems=[cause('tt_0', 'configure', 'Verify error', time='12:24:58')]))
        self.assertFalse(r['facts']['located'])
        self.assertIsNone(self.score('day-healthy-late', rec('no-fault'))['facts']['located'])   # a window: no keyed launch


class Caching(Base):
    def test_rerun_is_free_and_a_changed_report_is_extracted_again(self):
        cache = os.path.join(self.tmp, 'cache')
        r1 = self.score('reg-cfg-tt', rec(problems=[cause('tt_0', 'configure', 'Verify error')]), cache=cache)
        self.assertEqual(self.calls(), 'xjjj')
        r2 = self.score('reg-cfg-tt', rec(problems=[cause('tt_0', 'configure', 'Verify error')]), cache=cache)
        self.assertEqual(self.calls(), 'xjjj')
        self.assertEqual(r1['outcome'], r2['outcome'])
        self.assertTrue(all(c['cached'] for c in r2['calls']['extract'] + r2['calls']['judge']))
        self.assertEqual(score.usage(r2)['fresh_calls'], 0)
        self.assertAlmostEqual(score.usage(r2)['cost_usd'], 0.016)  # cached calls keep their first cost
        name = score.sha(report(rec(problems=[cause('tt_0', 'configure', 'Verify error')])))
        self.assertTrue(os.path.exists(os.path.join(cache, 'extract', name + '.json')))   # by the report's sha256
        self.score('reg-cfg-tt', rec(problems=[cause('tt_0', 'configure', 'Verify error')]), 'Another report.', cache=cache)
        self.assertEqual(self.calls(), 'xjjjx')                   # same statement: the judge votes come from the cache

    def test_the_default_command_saves_no_session_and_the_cache_ignores_the_command(self):
        argv = score.Caller().argv()
        self.assertEqual(argv[:2], ['claude', '-p'])
        self.assertIn('--no-session-persistence', argv)             # no folder per call under ~/.claude/projects
        cache = os.path.join(self.tmp, 'cache')
        prompt = 'REPORT:\n<<<\nA report.\n>>>'
        first = score.Caller('fake', self.xcmd, cache).call(prompt, 'extract')
        again = score.Caller('fake', ['false'], cache).call(prompt, 'extract')     # another command, same model and prompt
        self.assertEqual((first['cached'], again['cached'], again['text']), (False, True, first['text']))
        self.assertEqual(self.calls(), 'x')


class Pipeline(Base):
    def test_main_scores_a_results_folder_and_keeps_quiet_ids_quiet(self):
        res = os.path.join(self.tmp, 'results')
        runs = {('none', 'r1'): ('reg-cfg-tt', rec(problems=[cause('tt_0', 'configure', 'Verify error')]), 'Visible report.'),
                ('skills', 'r2'): ('healthy-tt', rec('fault', problems=[cause('tt_0', 'shutdown', 'double free')]), 'Quiet.'),
                ('skills', 'r3'): ('big-healthy-31', rec('no-fault'), 'Disputed: never scored.')}
        for (arm, run), (case, record, text) in runs.items():
            d = os.path.join(res, arm, run)
            os.makedirs(d)
            score.write_json(os.path.join(d, 'meta.json'), {'case': case, 'arm': arm, 'repeat': 1, 'cost_usd': 1.0})
            score.write_text(os.path.join(d, 'final.md'), report(record, text))
        quiet = os.path.join(self.tmp, 'quiet.json')
        score.write_json(quiet, ['skills/r2'])
        out, summ = os.path.join(self.tmp, 'out.json'), os.path.join(self.tmp, 'summary.txt')
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = score.main(['--results', res, '--out', out, '--summary', summ, '--quiet-ids', quiet,
                             '--extract-cmd', ' '.join(self.xcmd), '--judge-cmd', ' '.join(self.jcmd)])
        self.assertEqual(rc, 0)
        printed = buf.getvalue()
        self.assertIn('none/r1', printed)
        self.assertNotIn('false-alarm', printed.split('\n\n')[0])  # the quiet row's outcome is not printed
        with open(out) as f:
            rows = {r['id']: r for r in json.load(f)['rows']}
        self.assertEqual(sorted(rows), ['none/r1', 'skills/r2'])
        self.assertTrue(rows['none/r1']['outcome']['cause'])
        self.assertEqual(rows['skills/r2']['outcome']['outcome'], 'false-alarm')
        self.assertEqual(rows['none/r1']['usage']['models'], ['fake-extractor', 'fake-judge'])
        with open(summ) as f:
            text = f.read()
        self.assertIn('ALL', text)
        self.assertIn('"scorer_calls": 5', text)
        self.assertIn(' scorer calls ', text.splitlines()[0])        # not 'calls': pilot.py's calls are calls to evidence


if __name__ == '__main__':
    unittest.main()
