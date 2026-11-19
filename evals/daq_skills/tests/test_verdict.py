"""Tests for verdict.py: the pre-registered verdict rules read from a rows table.  No model calls.

    python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import verdict  # noqa: E402

EVAL = os.path.dirname(HERE)


def row(family, arm, case, repeat, mode='m1', model='default', healthy=False, cause=None, outcome=None, located=None, calls=None,
        calls_ng=None):
    return {'run_id': '%s.%s/%s-%d' % (family, arm, case, repeat), 'family': family, 'case': case, 'arm': arm, 'mode': mode,
            'model': model, 'repeat': repeat, 'healthy': healthy, 'cause_pass': cause, 'healthy_outcome': outcome,
            'located': located, 'calls': calls, 'calls_no_guidance': calls if calls_ng is None else calls_ng,
            'cost_usd': 0.1, 'seconds': 10.0}


class Wilcoxon(unittest.TestCase):
    def test_exact_small_samples(self):
        self.assertAlmostEqual(verdict.wilcoxon_greater([1, 2, 3, 4, 5])[0], 1 / 32.0)
        self.assertAlmostEqual(verdict.wilcoxon_greater([-1, 2, 3])[0], 2 / 8.0)
        self.assertEqual(verdict.wilcoxon_greater([0, 0]), (1.0, 0))

    def test_zeros_are_dropped_and_ties_get_mid_ranks(self):
        p, n = verdict.wilcoxon_greater([0, 3, 3, 3])
        self.assertEqual(n, 3)
        self.assertAlmostEqual(p, 1 / 8.0)

    def test_large_samples_use_the_normal_approximation(self):
        p, n = verdict.wilcoxon_greater(list(range(1, 26)))
        self.assertEqual(n, 25)
        self.assertLess(p, 1e-4)
        self.assertGreater(verdict.wilcoxon_greater([-x for x in range(1, 26)])[0], 0.99)

    def test_selftest_runs(self):
        out = subprocess.run([sys.executable, os.path.join(EVAL, 'verdict.py'), '--selftest'], stdout=subprocess.PIPE,
                             universal_newlines=True)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, 'selftest ok'))


class Controls(unittest.TestCase):
    def rows(self, crib_pass, starved_pass):
        rows = []
        for c in ('f1', 'f2'):
            for r in (1, 2):
                rows.append(row('A', 'none', c, r, mode='m0', model='haiku', cause=(r == 1)))
                rows.append(row('A', 'crib', c, r, mode='m0', model='haiku', cause=crib_pass))
                rows.append(row('A', 'starved', c, r, mode='m0', model='haiku', cause=starved_pass))
        rows.append(row('A', 'none', 'h1', 1, mode='m0', model='haiku', healthy=True, outcome='false-alarm'))
        rows.append(row('A', 'crib', 'h1', 1, mode='m0', model='haiku', healthy=True, outcome='clean'))
        return rows

    def test_both_controls_pass(self):
        out = verdict.controls(self.rows(True, False), 'A', 'm0', 'haiku', 'crib', 20.0)
        self.assertEqual(out['none'][:2], [2, 5])                  # the healthy false alarm counts as a miss
        self.assertEqual(out['none_on_starved_pools'][:2], [2, 4])  # the healthy case has no starved run
        self.assertTrue(out['positive_pass'] and out['negative_pass'] and out['detects_difference'])

    def test_controls_fail_when_they_change_nothing(self):
        out = verdict.controls(self.rows(False, True), 'A', 'm0', 'haiku', 'crib', 20.0)
        self.assertFalse(out['positive_pass'] or out['negative_pass'] or out['detects_difference'])

    def test_score_of_a_row(self):
        self.assertTrue(verdict.score({'healthy': True, 'healthy_outcome': 'benign-defect-noted'}))
        self.assertFalse(verdict.score({'healthy': True, 'healthy_outcome': 'false-alarm'}))
        self.assertIsNone(verdict.score({'healthy': True, 'healthy_outcome': None}))
        self.assertTrue(verdict.score({'healthy': False, 'cause_pass': True}))


class PooledControls(unittest.TestCase):
    """P3m: pointer vs none over families B and C pooled (+12.5 points), B starved vs B none on the same fault pools (-25)."""

    def rows(self, b_ptr, c_ptr, starved):
        rows = []
        for r in (1, 2):
            for i in range(6):                                   # family B: 6 fault cases, 2 healthy
                rows.append(row('B', 'none', 'b%d' % i, r, cause=(i < 4)))
                rows.append(row('B', 'pointer', 'b%d' % i, r, cause=(i < b_ptr)))
                rows.append(row('B', 'starved', 'b%d' % i, r, cause=(i < starved)))
            for i in range(2):
                rows.append(row('B', 'none', 'bh%d' % i, r, healthy=True, outcome='clean'))
                rows.append(row('B', 'pointer', 'bh%d' % i, r, healthy=True, outcome='clean'))
            for i in range(3):                                   # family C: 3 fault cases, 4 healthy
                rows.append(row('C', 'none', 'c%d' % i, r, cause=(i < 1)))
                rows.append(row('C', 'pointer', 'c%d' % i, r, cause=(i < c_ptr)))
            for i in range(4):
                rows.append(row('C', 'none', 'ch%d' % i, r, healthy=True, outcome='false-alarm' if i == 0 else 'clean'))
                rows.append(row('C', 'pointer', 'ch%d' % i, r, healthy=True, outcome='benign-defect-noted'))
        rows.append(row('C', 'none', 'c0', 1, model='haiku', cause=False))   # another model: not counted
        return rows

    def test_pooled_positive_and_b_negative(self):
        # none: B 4/6 fault + 2/2 healthy, C 1/3 + 3/4 per repeat -> 20/30 = 66.7%; pointer B 6/6+2/2, C 2/3+4/4 -> 28/30 = 93.3%
        out = verdict.controls_pooled(self.rows(6, 2, 0), ('B', 'C'), 'm1', 'default', 'pointer', 12.5, 'B')
        self.assertEqual((out['none_pooled'][:2], out['pointer_pooled'][:2]), ([20, 30], [28, 30]))
        self.assertEqual((out['none_on_starved_pools'][:2], out['starved'][:2]), ([8, 12], [0, 12]))
        self.assertTrue(out['positive_pass'] and out['negative_pass'] and out['detects_difference'])
        self.assertEqual(out['per_family']['C'], {'none': [8, 14], 'pointer': [12, 14]})

    def test_pooled_positive_fails_under_the_margin_and_negative_fails_when_starving_changes_little(self):
        # pointer B 5/6+2/2, C 1/3+4/4 -> 24/30 = 80% vs 66.7%: +13.3 >= 12.5 passes; 4/6+2/2, 1/3+4/4 -> 22/30: +6.7 fails
        self.assertTrue(verdict.controls_pooled(self.rows(5, 1, 0), ('B', 'C'), 'm1', 'default', 'pointer', 12.5, 'B')['positive_pass'])
        out = verdict.controls_pooled(self.rows(4, 1, 3), ('B', 'C'), 'm1', 'default', 'pointer', 12.5, 'B')
        self.assertFalse(out['positive_pass'] or out['negative_pass'])     # starved 6/12 = 50% vs 66.7%: only -16.7


class Sensitivity(unittest.TestCase):
    def test_calls_without_guidance_are_reported_beside_the_verdict(self):
        rows = []
        for i in range(16):
            c, r = 'c%d' % (i // 2), i % 2 + 1
            rows += [row('B', 'none', c, r, cause=True, calls=20, calls_ng=20), row('B', 'pointer', c, r, cause=True, calls=4, calls_ng=4),
                     row('B', 'map', c, r, cause=True, calls=14, calls_ng=6), row('B', 'skills', c, r, cause=True, calls=22, calls_ng=19)]
        s = verdict.calls_sensitivity(rows, 'B', 'default')
        self.assertEqual((s['column'], s['calls']['map'], s['G_calls'], s['G_calls_real_by_P4_rule']), ('calls_no_guidance', 6, 16, True))
        self.assertEqual((s['shares_on_calls']['map'], s['shares_on_calls']['skills']), (14 / 16.0, 1 / 16.0))
        self.assertAlmostEqual(verdict.family_verdict(rows, 'B', 'default')['shares']['map'], 6 / 16.0)   # the verdict keeps 'calls'


class FamilyVerdict(unittest.TestCase):
    def world(self, family, calls, located=None):
        """calls: {arm: [calls per (case, repeat) pair]} over 8 cases x 2 repeats."""
        rows = []
        for arm, vals in calls.items():
            for i, v in enumerate(vals):
                loc = located[arm][i] if located else True
                rows.append(row(family, arm, 'c%d' % (i // 2), i % 2 + 1, cause=True, located=loc, calls=v))
        return rows

    def test_supported_when_the_map_closes_the_gap_and_skills_do_not(self):
        rows = self.world('B', {'none': [30 + i % 3 for i in range(16)], 'pointer': [5] * 16, 'map': [8] * 16,
                                'skills': [30 + i % 3 for i in range(16)], 'both': [7] * 16})
        v = verdict.family_verdict(rows, 'B', 'default')
        self.assertTrue(v['G_calls_real'])
        self.assertEqual(v['primary'], 'calls')
        self.assertEqual((v['verdict'], v['shares']['skills']), ('SUPPORTED', 0.0))
        self.assertGreater(v['shares']['map'], 0.5)

    def test_refuted_when_skills_do_as_well_as_the_map(self):
        rows = self.world('C', {'none': [30] * 16, 'pointer': [5] * 16, 'map': [10] * 16, 'skills': [9] * 16})
        self.assertEqual(verdict.family_verdict(rows, 'C', 'default')['verdict'], 'REFUTED')

    def test_no_gap_is_no_answer(self):
        rows = self.world('B', {'none': [10] * 16, 'pointer': [10] * 16, 'map': [3] * 16, 'skills': [10] * 16})
        v = verdict.family_verdict(rows, 'B', 'default')
        self.assertEqual((v['G_calls_real'], v['G_loc_real'], v['verdict']), (False, False, 'NO ANSWER'))

    def test_located_is_the_primary_metric_when_calls_show_no_gap(self):
        loc = {'none': [False] * 16, 'pointer': [True] * 16, 'map': [True] * 16, 'skills': [False] * 16}
        rows = self.world('B', {'none': [10] * 16, 'pointer': [10] * 16, 'map': [10] * 16, 'skills': [10] * 16}, loc)
        v = verdict.family_verdict(rows, 'B', 'default')
        self.assertEqual((v['primary'], v['G_loc'], v['verdict']), ('located', 1.0, 'SUPPORTED'))

    def test_overall_combines_the_families(self):
        S, R, N = ({'verdict': x} for x in ('SUPPORTED', 'REFUTED', 'NO ANSWER'))
        self.assertEqual(verdict.overall(S, S)[0], 'SUPPORTED')
        self.assertEqual(verdict.overall(N, R), ('REFUTED', 'from one family (C real-MFX)'))
        self.assertEqual(verdict.overall(S, N), ('SUPPORTED', 'from one family (B sim-tree)'))
        self.assertEqual(verdict.overall(S, R)[0], 'NO ANSWER')


class Main(unittest.TestCase):
    def test_main_reads_a_rows_file_and_prints_every_prediction(self):
        rows = FamilyVerdict().world('B', {'none': [20] * 16, 'pointer': [4] * 16, 'map': [6] * 16, 'skills': [18] * 16})
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(rows, f)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                verdict.main(f.name)
            out = json.loads(buf.getvalue())
        finally:
            os.unlink(f.name)
        self.assertEqual(sorted(out), ['P2_controls_M0_haiku', 'P3_controls_M1_default', 'P3m_controls_M1_pooled', 'P4_B', 'P5_C',
                                       'P6_overall', 'sensitivity_calls_no_guidance'])
        self.assertEqual(out['P5_C']['verdict'], 'NO ANSWER')
        self.assertEqual(out['P6_overall'][0], out['P4_B']['verdict'])


if __name__ == '__main__':
    unittest.main()
