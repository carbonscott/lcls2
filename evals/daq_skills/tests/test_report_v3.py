"""Tests for report_v3.py: the privacy filter for family C text, and the page built from a small fixture of pilot and
M0 folders.  No model calls.

    python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import report_v3   # noqa: E402
import verdict     # noqa: E402

PRIVATE = [
    'see /home/jdoe/notes.txt for the setup',
    'the script in /cds/home/j/jdoe/daq/mfx.py was edited',
    'copied from /sdf/home/j/jdoe/scratch/',
    'old copy at /reg/neh/home4/jdoe/x.log',
    'run by /cds/home/opr/jdoe/bin/start',
    'mail jane.doe@slac.stanford.edu about it',
    'ssh jdoe@drp-srcf-cmp014 was used',
    'the helper in ~jdoe/bin',
    'procmgr: user=jdoe started control',
    'Username: jdoe',
    'owner jdoe of the partition config',
    'Thanks Jane Smith for the logs',
    'Dr. Smith restarted the DAQ',
    'asked Jane Smith about the restart',
]
PUBLIC = [
    'logs in /sdf/home/m/mfxopr/daq/logs/2026/11/04_16:52:14_drp-srcf-cmp014:control.log',
    'the old root /sdf/home/m/mfxopr/2026/09/ before the cutover',
    'the account /cds/home/opr/mfxopr/ owns the scripts',
    'ssh mfxopr@drp-srcf-cmp014 runs the launch',
    'procmgr: user mfxopr',
    '17:08:07 teb0: Configure is missing src 2 (qadc_0), the EPICS PV never connected',
    'mebuser0 and meb0_first on drp-srcf-mon005 shut down at 17:08:34',
    'Control Reports the first failure from qadc_0',
]


class PrivacyFilter(unittest.TestCase):
    def test_private_lines_are_dropped(self):
        for line in PRIVATE:
            self.assertTrue(report_v3.private_line(line), line)

    def test_public_lines_are_kept(self):
        for line in PUBLIC:
            self.assertFalse(report_v3.private_line(line), line)

    def test_safe_text_drops_lines_and_caps_at_200(self):
        text = '\n'.join(PRIVATE + PUBLIC * 3)
        out = report_v3.safe_text(text)
        self.assertLessEqual(len(out), 200)
        for bad in ('jdoe', 'Jane', 'Smith', '@slac'):
            self.assertNotIn(bad, out)
        self.assertTrue(out.startswith('logs in /sdf/home/m/mfxopr/daq/logs/2026/11/'))
        self.assertTrue(out.endswith('...'))

    def test_family_c_quote_is_short_and_filtered(self):
        report = ('## Yes, something went wrong\n\nThe operator jdoe@slac.stanford.edu restarted it.\n'
                  'The first failure was qadc_0 in running; see /home/jdoe/a.txt\n' + 'qadc_0 aborted on its first event. ' * 20)
        q = report_v3.conclusion_quote(report, 'C')
        self.assertLessEqual(len(q), report_v3.QUOTE_MAX_C)
        self.assertNotIn('jdoe', q)
        self.assertTrue(q.startswith('Yes, something went wrong qadc_0 aborted'))
        b = report_v3.conclusion_quote(report, 'B')       # sim reports: length cap only
        self.assertLessEqual(len(b), report_v3.QUOTE_MAX)
        self.assertIn('jdoe', b)

    def test_run_text_filters_only_family_c(self):
        self.assertEqual(report_v3.run_text({'family': 'C'}, 'said jdoe@host restarted'), '')
        self.assertEqual(report_v3.run_text({'family': 'B'}, 'said qadc_0'), 'said qadc_0')

    def test_clip(self):
        self.assertEqual(report_v3.clip('a  b\n c', 10), 'a b c')
        out = report_v3.clip('word ' * 100, 50)
        self.assertLessEqual(len(out), 50)
        self.assertTrue(out.endswith('word...'))


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        if isinstance(obj, str):
            f.write(obj)
        else:
            json.dump(obj, f)


def vrow(rid, family, case, arm, repeat, healthy=False, cause=None, outcome=None, located=None, calls=None, model='default'):
    return {'run_id': rid, 'family': family, 'case': case, 'arm': arm, 'mode': 'm1', 'model': model, 'repeat': repeat,
            'healthy': healthy, 'cause_pass': cause, 'healthy_outcome': outcome, 'located': located, 'calls': calls,
            'calls_no_guidance': calls, 'cost_usd': 1.5, 'seconds': 100.0, 'exit': 0, 'error': None, 'scorer_usd': 0.05}


C_REPORT = ('Yes, something went wrong. The first failure was qadc_0 in running.\n'
            'Ask jane.doe@slac.stanford.edu, who ran it from /home/jdoe/bin.\n\n'
            'Thanks Jane Smith for the logs.\n' + 'The buffer was too small for the second array. ' * 12)


class Page(unittest.TestCase):
    """A pilot folder (families B and C, arms none and pointer, 2 repeats) and an M0 folder, then the page."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, 'pilot-x')
        rows, scored = [], []
        spec = [('B', 'gpu-hang-cfg', False), ('C', 'real-qadc-run', False), ('C', 'real-month-edge', True)]
        for fam, case, healthy in spec:
            for arm in ('none', 'pointer'):
                for rep in (1, 2):
                    rid = '%s.%s.default/r%s%d' % (fam, arm, case[-4:].replace('-', ''), rep)
                    ok = arm == 'pointer'
                    r = vrow(rid, fam, case, arm, rep, healthy=healthy, cause=None if healthy else ok,
                             outcome=('clean' if ok else 'false-alarm') if healthy else None, located=ok,
                             calls=(3 if ok else 9 + rep))
                    rows.append(r)
                    facts = {'located': ok, 'verdict_kind': 'fault', 'component_said': 'qadc_0' if ok or fam != 'C' else 'jdoe@host',
                             'stage_said': 'running', 'component': ok, 'stage': True,
                             'conclusion': {'launch': {'time': '17:08:07', 'date': '2026-11-04', 'tz': 'local'}, 'basis': 'cause'}}
                    if healthy:
                        facts = {'located': ok, 'causes_given': [{'component': 'epix100_0_0', 'stage': 'enable'}]}
                    scored.append({'id': rid, 'facts': facts, 'mechanism': {'votes': ['near-miss'] * 3, 'verdict': 'near-miss'} if fam == 'B' else {'verdict': 'not scored'},
                                   'outcome': {'kind': 'healthy', 'outcome': r['healthy_outcome']} if healthy else {'kind': 'fault', 'cause': ok}})
                    d = os.path.join(self.out, rid)
                    write(os.path.join(d, 'meta.json'), {'model': 'claude-test-1', 'started': '2026-11-20T01:0%d:00Z' % rep,
                                                         'operator_questions': 0 if ok else 2, 'exit': 0})
                    write(os.path.join(d, 'evidence.json'), {'calls': r['calls'], 'censored': not ok})
                    write(os.path.join(d, 'final.md'), C_REPORT if fam == 'C' else 'The DAQ failed. ' * 40)
        write(os.path.join(self.out, 'rows.json'), rows)
        write(os.path.join(self.out, 'scored.json'), {'rows': scored, 'meta': {'models': ['claude-scorer-1'], 'votes': 3,
                                                                              'model_flag': 'sonnet', 'keys_sha256': 'ab' * 32}})
        write(os.path.join(self.out, 'usage.json'), {'runs': len(rows), 'agent_usd': 18.0, 'scorer_usd': 0.6, 'total_usd': 18.6,
                                                     'scorer_fresh_usd_this_call': 0.6})
        write(os.path.join(self.out, 'B.none.default', 'rlost', 'meta.json'), {'exit': 0})     # a run not in rows.json
        self.rows = rows
        # M0: one case, none passes twice, crib passes twice, starved fails twice; the fixed key flips one none run
        self.m0 = os.path.join(self.tmp, 'm0-x')
        for name, flip in (('scored.json', False), ('scored-keyfix.json', True)):
            srows = []
            for arm, ok in (('m0-none', True), ('m0-crib', True), ('m0-starved', False)):
                for rep in (1, 2):
                    passed = ok and not (arm == 'm0-none' and rep == 2 and not flip)
                    srows.append({'id': '%s/rm0%d' % (arm, rep), 'arm': arm, 'case': 'gpu-hang-cfg', 'repeat': rep, 'mode': 'm0',
                                  'control': {'m0-crib': 'crib', 'm0-starved': 'starved'}.get(arm), 'family': 'A', 'model_flag': 'haiku',
                                  'kind': 'fault', 'located': True, 'agent_cost_usd': 0.02, 'seconds': 30.0,
                                  'outcome': {'kind': 'fault', 'cause': passed}, 'facts': {'located': True}, 'mechanism': {}})
                    write(os.path.join(self.m0, arm, 'rm0%d' % rep, 'meta.json'), {'model': 'claude-haiku-test', 'started': '2026-11-19T10:00:00Z'})
            write(os.path.join(self.m0, name), {'rows': srows, 'meta': {'scorer_cost_usd': 0.3, 'fresh_cost_usd_this_run': 0.1,
                                                                        'keys_sha256': ('cd' if flip else 'ef') * 32}})
        self.preds = os.path.join(self.tmp, 'predictions.json')
        write(self.preds, {'definitions': {'families': {'A anchor': 'x', 'B sim-tree': 'y', 'C real-MFX': 'z'},
                                           'arms': {'none': 'no guidance installed'}, 'scores': {'Usage': 'API-equivalent USD'}},
                           'predictions': [{'id': 'P1-scorer-agreement', 'outcome': '37/40 = 92.5% agree: PASS. Caveat: more.'},
                                           {'id': 'P1b-scorer-power', 'outcome': 'traps: 28/32: PASS.'},
                                           {'id': 'P6-verdict-rules', 'rule': 'SUPPORTED if share(map) >= 0.5.'},
                                           {'id': 'P3m-controls-M1-pooled', 'rule': 'pooled pointer >= pooled none + 12.5 points.'}]})

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def build(self, *extra):
        page = os.path.join(self.tmp, 'page.html')
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            rc = report_v3.main(['--pilot', self.out, '--m0', self.m0, '--predictions', self.preds, '--commit', 'abc123def456',
                                 '--out', page] + list(extra))
        self.assertEqual(rc, 0)
        with open(page) as f:
            return f.read(), err.getvalue()

    def test_sections_in_order_and_skeleton_rules(self):
        html, _ = self.build()
        self.assertTrue(html.startswith('<title>DAQ Eval v3 Results</title>'))
        self.assertNotRegex(html, r'<(html|head|body)[\s>]')
        self.assertIn('<meta name="claude:viewport-fit-sides" content="cover">', html)
        pos = [html.find('id="%s"' % s) for s, _ in report_v3.SECTIONS]
        self.assertTrue(all(p > 0 for p in pos), pos)
        self.assertEqual(pos, sorted(pos))

    def test_run_ids_numbers_and_verdict(self):
        html, err = self.build()
        for r in self.rows:
            self.assertIn(r['run_id'], html)
        self.assertIn('abc123def456', html)
        self.assertIn('<code>pilot-x</code> (12 runs, pilot) run at commit <code>abc123def456</code>; run folders: '
                      '<code>B.none.default</code> (2), <code>B.pointer.default</code> (2), <code>C.none.default</code> (4)', html)
        self.assertIn('<code>m0-x</code> (6 runs, M0 controls) run at commit <code>not given</code>', html)
        # family C: pointer located 4/4, none 0/4 (healthy runs too), in the verdict's table and the findings
        self.assertIn('<td><b>pointer</b></td><td class="n">4/4 (100.0%)</td>', html)
        self.assertIn('it located the launch in 4/4 (100.0%) runs with the pointer and 0/4 (0.0%) with none', html)
        # P2 from the M0 folder: none 1/2 as run, 2/2 with the fixed key; the flipped run is flagged
        self.assertIn('m0-none/rm02</span> (changed since the keys as run scoring)', html)
        self.assertIn('1/2 (50.0%)', html)
        # the same verdict as verdict.py on these rows
        v = report_v3.run_verdict(self.rows, 'default')
        self.assertEqual(v['P4_B']['pairs'], 2)
        self.assertIn(v['P6_overall'][0], html)
        self.assertIn('rlost', err)                       # the run folder missing from rows.json is reported
        self.assertIn('B.none.default/rlost', html)

    def test_m0_commit_verdict_note_controls_and_amendments(self):
        with open(self.preds) as f:
            p = json.load(f)
        p['amendments'] = [{'when': '2026-11-19T15:45Z', 'what': ['Located is read on the launch the report concludes about.']}]
        write(self.preds, p)
        html, _ = self.build('--m0-commit', '0d628f9', '--verdict-note', 'Review pending.', '--amendment-written', '2026-11-20T00:50Z')
        self.assertIn('(6 runs, M0 controls) run at commit <code>0d628f9</code>', html)
        self.assertEqual(html.count('<p class="vnote">Review pending.</p>'), 2)      # findings and the verdict section
        # beside each positive control: how many runs would flip it (2 here: pointer 2/2 against none 0/2)
        self.assertIn('Controls, printed beside the verdict as P3 asks: P3, M1, family B: positive PASS (2 runs from flipping), negative', html)
        self.assertIn('P3 controls (family B alone): pointer 2/2 (100.0%) against none 0/2 (0.0%)', html)
        self.assertIn('<b>Amendment (2026-11-19T15:45Z)</b>: Located is read on the launch the report concludes about.', html)
        self.assertIn('<b>Amendment time</b>: The predictions file labels the amendment 2026-11-19T15:45Z; it was written at about '
                      '2026-11-20T00:50Z, before the first counted run started (2026-11-20T01:01:00Z).', html)
        self.assertIn('Descriptive only, not a verdict', html)
        # the P6 rules on the guidance-free count (no skills or map arm here: both shares 0, so REFUTED)
        self.assertIn('and the P6 rules on that count read REFUTED in family B', html)
        self.assertIn('<h2>Runs that failed or were not located (', html)

    def test_corrections_and_trust(self):
        html, _ = self.build()
        self.assertIn('None recorded. This page shows the scores as first computed.', html)
        self.assertIn('id="trust"', html)
        self.assertIn('P3, family B: positive control PASS, ', html)
        first = report_v3.run_verdict(self.rows, 'default')
        first['P3_controls_M1_default']['positive_pass'] = False
        path = os.path.join(self.tmp, 'first.json')
        write(path, first)
        alt = os.path.join(self.tmp, 'alt.json')
        write(alt, [{'run_id': r['run_id'], 'alt': (r['calls'] or 0) + 1} for r in self.rows])
        html, _ = self.build('--first-verdict', path, '--first-m0', os.path.join(self.m0, 'scored.json'),
                             '--calls-variant', 'one more call=%s:alt' % alt, '--p3m-written', '2026-11-20T00:30:00Z',
                             '--trust-note', 'A note.')
        self.assertIn('<td>positive control</td><td class="n">FAIL</td><td class="n">PASS</td><td><span class="m part">changed</span>', html)
        self.assertIn('<td>positive: none</td><td class="n">1/2 (50.0%)</td><td class="n">2/2 (100.0%)</td>', html)   # P2: the key fix
        self.assertIn('one more call: with calls to evidence from that count, verdict.py reads family B', html)
        self.assertIn('P3m was written at 2026-11-20T00:30:00Z, 31 minutes before the first counted run started (2026-11-20T01:01:00Z)', html)
        self.assertIn('<li>A note.</li>', html)

    def test_three_m0_scorings_and_scoring_commit(self):
        with open(os.path.join(self.m0, 'scored-keyfix.json')) as f:
            doc = json.load(f)
        doc['rows'][-1]['outcome']['cause'] = True                   # one starved run passes: a third, different scoring
        write(os.path.join(self.m0, 'scored-sc.json'), doc)
        args = ('--m0-scoring', 'keys as run=scored.json', '--m0-scoring', 'fixed key=scored-keyfix.json',
                '--m0-scoring', 'corrected scorer=scored-sc.json', '--scoring-commit', 'feed123')
        html, _ = self.build(*args)
        self.assertIn('<th class="n">Score, keys as run</th><th class="n">Score, fixed key</th><th class="n">Score, corrected scorer</th>', html)
        self.assertIn('run at commit <code>abc123def456</code>, scored at <code>feed123</code>', html)
        self.assertIn('Family A at M0 (the P2 control runs, corrected scorer)', html)
        self.assertIn('P2, M0 Haiku, corrected scorer: positive', html)

    def test_identical_m0_scorings_share_a_column(self):
        shutil.copy(os.path.join(self.m0, 'scored-keyfix.json'), os.path.join(self.m0, 'scored-sc.json'))
        html, _ = self.build('--m0-scoring', 'keys as run=scored.json', '--m0-scoring', 'fixed key=scored-keyfix.json',
                             '--m0-scoring', 'corrected scorer=scored-sc.json',
                             '--m0-scoring-note', 'fixed key=This scoring uses a key fixed after the results.')
        self.assertIn('<th class="n">Score, keys as run</th><th class="n">Score, fixed key (and corrected scorer, identical)</th>'
                      '<th>Runs, marked by the current scoring</th>', html)
        self.assertIn('Family A at M0 (the P2 control runs, fixed key (and corrected scorer, identical))', html)
        self.assertIn('P2, M0 Haiku, fixed key (and corrected scorer, identical): positive', html)
        # the findings give each P2 line its gap and margin, and the note of the fixed key
        self.assertIn('P2 controls, M0 Haiku, fixed key (and corrected scorer, identical): crib 2/2 (100.0%) against none 2/2 '
                      '(100.0%), +0.0 points (needs +20), positive control fails', html)
        self.assertEqual(html.count('This scoring uses a key fixed after the results.'), 2)     # findings and the P2 block
        # usage still counts every file: two re-scores
        self.assertIn('$0.30 + $0.10 re-score (fixed key) + $0.10 re-score (corrected scorer)', html)
        self.assertIn('Corrected scorer: <code>scored-sc.json</code>', html)

    def test_positive_control_notes(self):
        d = {'verdict': {'P3_controls_M1_default': {'pointer': [15, 16, 93.75], 'none': [13, 16, 81.25], 'positive_pass': True,
                                                    'positive_margin_needed': 12.5}},
             'first_verdict': {'P3_controls_M1_default': {'pointer': [14, 16, 87.5], 'none': [13, 16, 81.25], 'positive_pass': False}},
             'p2': []}
        self.assertEqual(report_v3.pos_beside(d, 'P3'),
                         ' (exactly at the +12.5 margin; FAIL (14/16 vs 13/16) as first scored; one run from flipping)')
        d['verdict']['P3_controls_M1_default'].update(pointer=[16, 16, 100.0])
        d['first_verdict']['P3_controls_M1_default']['positive_pass'] = True
        self.assertEqual(report_v3.pos_beside(d, 'P3'), ' (2 runs from flipping)')

    def healthy_records(self):
        """real-month-edge (keyed launch 30_06:20:41, 06:20:41 to 18:02:21): none r1 blames a 16:28:47 launch it dates
        2026-10-29 (inside the keyed launch by its time alone: a false alarm); pointer r1 blames 21:34:00, after the keyed
        launch, so its failure is placed elsewhere (and it is not located).  A first scoring had pointer r1 as a false alarm."""
        with open(os.path.join(self.out, 'scored.json')) as f:
            doc = json.load(f)
        rec = lambda t, day: {'verdict_kind': 'fault', 'problems': [{'role': 'cause', 'launch_time': t, 'tz': 'local',
                                                                     'component': 'meb0_first', 'stage': 'running', 'mechanism': 'x'}],
                              'launches': [{'time': t, 'date': day, 'tz': 'local', 'status': 'failed'}]}
        for row in doc['rows']:
            if row['id'] == 'C.none.default/redge1':
                row['record'] = rec('16:28:47', '2026-10-29')
                row['facts']['verdict_kind'] = 'fault'
            if row['id'] == 'C.pointer.default/redge1':
                row['record'] = rec('21:34:00', '2026-10-30')
                row['facts']['verdict_kind'] = 'fault'
                row['outcome']['outcome'] = 'benign-defect-noted'
        write(os.path.join(self.out, 'scored.json'), doc)
        first = [dict(r) for r in self.rows]
        for r in self.rows:
            if r['run_id'] == 'C.pointer.default/redge1':
                r['healthy_outcome'], r['located'] = 'benign-defect-noted', False     # concluded about the launch it blames
        write(os.path.join(self.out, 'rows.json'), self.rows)
        for r in first:
            if r['run_id'] == 'C.pointer.default/redge1':
                r['healthy_outcome'] = 'false-alarm'
        fp = os.path.join(self.tmp, 'first-x')
        write(os.path.join(fp, 'rows.json'), first)
        write(os.path.join(fp, 'usage.json'), {'scorer_usd': 0.5, 'scorer_fresh_usd_this_call': 0.5})
        return fp

    def test_failure_placed_elsewhere_day_used_and_sc1(self):
        fp = self.healthy_records()
        html, err = self.build('--first-pilot', fp)
        self.assertNotIn('differs from scored.json', err)      # the placement recomputed from the records agrees with the scorer
        self.assertIn('title="C.pointer.default/redge1">failure placed elsewhere, not located</span>', html)
        self.assertIn('<td class="n">1 / 0 / 1 / 0</td>', html)            # C pointer: clean / benign / placed elsewhere / false alarm
        self.assertIn('<td class="n">0 / 0 / 0 / 2</td>', html)            # C none: two false alarms
        self.assertIn('Healthy cases: 2 of 4 runs gave a fault verdict. 1 of them place every cause in another launch than the '
                      'keyed one, so they are not false alarms (failure placed elsewhere: C pointer: 1); 2 are false alarms '
                      '(C none: 2)', html)
        self.assertIn('outcome: <span class="ok">benign-defect-noted (a failure placed in another launch)</span>', html)
        self.assertIn('1 of the 2 false alarms (C.none.default/redge1; case real-month-edge) give the day of the failure they '
                      'blame (Thu 2026-10-29, launch 29_16:28:47), but the scorer places a cause by its time alone on the case&#x27;s '
                      'day (the extraction records a time, not a day), so it lands inside the keyed launch 30_06:20:41 (06:20:41 to '
                      '18:02:21) and they stay false alarms. With the day used, 1 of the 4 healthy runs would be a false alarm '
                      '(C.none.default/redge2, which gives no cause).', html)
        self.assertIn('Of the 2 healthy runs that gave a fault verdict, 1 place every cause in another launch than the keyed one '
                      'and are not false alarms; 1 of them blame a time outside the case&#x27;s window (real-month-edge). On the '
                      'control arms the change moved healthy runs by none +0 and pointer +1 in family C, which works for the '
                      'positive controls.', html)

    def test_first_scoring_usage_and_sources(self):
        fp = self.healthy_records()
        html, _ = self.build('--first-pilot', fp, '--m0-commit', '0d628f9', '--scoring-commit', 'feed123',
                             '--scoring-note', 'abc999 changes only a docstring')
        self.assertIn('$0.50 first scoring (first-x) + $0.60 re-score (pilot-x)', html)
        self.assertIn('<td class="n">$19.10</td>', html)                    # 18.00 agent + 0.50 + 0.60
        self.assertIn('come to $0.60 (usage.json scorer_usd)', html)
        tmp = os.path.basename(self.tmp)
        self.assertIn('Run of record: the corrected scoring, <code>%s/pilot-x</code> (pilot) and <code>%s/m0-x</code> (M0, '
                      '<code>scored-keyfix.json</code>); first scoring: <code>%s/first-x</code>. Commits: agent runs '
                      '<code>abc123def456</code>, M0 runs <code>0d628f9</code>, scoring <code>feed123</code> (abc999 changes only '
                      'a docstring).' % (tmp, tmp, tmp), html)

    def test_flips(self):
        rule = report_v3.pos_rule(12.5)
        self.assertEqual(report_v3.flips(14, 16, 13, 16, rule), 1)       # 87.5 vs 81.25: one more pointer pass reaches +12.5
        self.assertEqual(report_v3.flips(28, 30, 23, 30, rule), 2)
        self.assertEqual(report_v3.flips(3, 12, 9, 12, report_v3.neg_rule(25)), 4)

    def test_rounding_is_half_up(self):
        self.assertEqual(report_v3.frac(13, 16), '13/16 (81.3%)')
        self.assertEqual(report_v3.num(6.25), '6.3')
        self.assertEqual(report_v3.num(-50.0, '%+.1f'), '-50.0')
        self.assertEqual(report_v3.num(6.25, '%+.1f'), '+6.3')
        self.assertEqual(report_v3.num(0.0, '%+.1f'), '+0.0')
        self.assertEqual(report_v3.num(4.5625, '%.2f'), '4.56')
        self.assertEqual(report_v3.usd(147.947), '$147.95')
        self.assertEqual(report_v3.usd(0.8325, '$%.3f'), '$0.833')
        self.assertEqual(report_v3.pc(81.25), '81.3%')
        self.assertEqual(report_v3.num(1.0, '%.3g'), '1')

    def test_no_private_text_and_short_family_c_quotes(self):
        html, _ = self.build()
        for bad in ('jdoe', 'jane.doe', 'Jane Smith', '@slac'):
            self.assertNotIn(bad, html)
        quotes = re.findall(r'<div class="quote">(.*?)</div>', html)
        self.assertTrue(quotes)
        c_quotes = [q for q in quotes if 'qadc_0' in q or 'buffer' in q]
        self.assertTrue(c_quotes)
        for q in c_quotes:
            self.assertLessEqual(len(report_v3.html.unescape(q)), report_v3.QUOTE_MAX_C)
        for q in quotes:
            self.assertLessEqual(len(report_v3.html.unescape(q)), report_v3.QUOTE_MAX)

    def test_a_different_verdict_file_is_flagged(self):
        v = report_v3.run_verdict(self.rows, 'default')
        v['P4_B']['G_calls_p'] = 0.5
        path = os.path.join(self.tmp, 'verdict.json')
        write(path, v)
        html, err = self.build('--verdict', path)
        self.assertIn('P4_B differs between the given verdict file and verdict.py', err)
        self.assertIn('P4_B differs', html)
        v = report_v3.run_verdict(self.rows, 'default')
        write(path, v)
        html, err = self.build('--verdict', path)
        self.assertNotIn('differs', err)

    def test_p2_uses_verdict_margins(self):
        rows = report_v3.load_m0(self.m0)['runs']                # the last scoring: the fixed key
        c = verdict.controls(rows, 'A', 'm0', 'haiku', 'crib', 20.0)
        self.assertEqual(c['none'][:2], [2, 2])
        self.assertEqual(c['starved'][:2], [0, 2])


if __name__ == '__main__':
    unittest.main()
