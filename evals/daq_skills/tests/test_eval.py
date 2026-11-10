"""Tests for the DAQ-skill eval tools: graders on hand-written reports and transcripts,
harvest on a synthetic run folder, and the whole harvest -> run -> grade path with a
fake agent (no model calls).

Run: python3 -m unittest discover -s evals/daq_skills/tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import grade    # noqa: E402
import harvest  # noqa: E402
import run      # noqa: E402

KEY = {'fault': {'component': ['tt_0'], 'transition': ['configure'],
                 'mechanism': ['Verify error', 'verify', 'TriggerDelay'], 'summary': 's'},
       'expect_skills': ['psana-daq', 'psana-daq-control', 'psana-daq-logs'],
       'forbid_skills': ['psana-daq-history']}
NULL_KEY = {'fault': None, 'expect_skills': ['psana-daq'], 'independent': ['double free']}


def report(cause, conf='high', evidence='- control.log line — verified-against-real-logs',
           independent='none'):
    return ('## New Crashes\nnone\n\n## Most Likely Cause\n%s\nConfidence: %s\nEvidence:\n  %s\n\n'
            '## Also Possible\nnone\n\n## Independent Issues\n%s\n\n## Known Issues\nnone\n\n'
            '## Raw Findings\n- Session: 09_12:12:52\n' % (cause, conf, evidence, independent))


class CauseTests(unittest.TestCase):
    def test_correct_needs_component_transition_and_mechanism(self):
        r = report('tt_0 DRP aborted during configure phase 1',
                   evidence='- tt_0.log: Verify error for block ...TriggerDelay Got 0xff Exp 0x17 — verified-against-real-logs')
        self.assertEqual(grade.grade_cause(KEY, r)['verdict'], 'correct')

    def test_stopping_at_did_not_respond_is_partial(self):
        r = report('tt_0 did not respond to configure', conf='medium')
        self.assertEqual(grade.grade_cause(KEY, r)['verdict'], 'partial')

    def test_wrong_component_high_confidence_is_overconfident(self):
        g = grade.grade_cause(KEY, report('teb0 failed to configure: verify error'))
        self.assertEqual(g['verdict'], 'wrong')
        self.assertTrue(g['overconfident'])

    def test_component_name_must_match_whole_word(self):
        g = grade.grade_cause(KEY, report('tt_00 failed configure verify'))
        self.assertEqual(g['verdict'], 'wrong')

    def test_unknown(self):
        g = grade.grade_cause(KEY, report('Unknown — the evidence does not isolate a cause', conf='low'))
        self.assertEqual(g['verdict'], 'unknown')
        self.assertFalse(g['overconfident'])

    def test_healthy_run(self):
        ok = grade.grade_cause(NULL_KEY, report('No fault found: the run completed normally',
                                                independent='1. tt_0 double free at exit'))
        self.assertEqual(ok['verdict'], 'correct')
        self.assertEqual(ok['independent_found'], ['double free'])
        bad = grade.grade_cause(NULL_KEY, report('tt_0 failed to configure'))
        self.assertEqual(bad['verdict'], 'false-alarm')
        self.assertTrue(bad['overconfident'])

    def test_free_form_answer(self):
        text = 'Configure failed because tt_0 hit a register verify error on TriggerDelay and aborted.'
        g = grade.grade_cause(KEY, text)
        self.assertFalse(g['templated'])
        self.assertEqual(g['verdict'], 'correct')

    def test_cause_section_only(self):
        # A mechanism word in another section does not count for the cause
        r = report('tt_0 did not respond to configure', independent='1. verify error on hsd_0')
        self.assertEqual(grade.grade_cause(KEY, r)['verdict'], 'partial')


def bash(cmd):
    return {'name': 'Bash', 'input': {'command': cmd}}


class ReadonlyTests(unittest.TestCase):
    def test_reads_pass(self):
        calls = [bash("zstdcat logs/2026/11/x.log.zst | rg -n '<E>|kill'"), bash('rg -c pkill logs'),
                 bash('ls logs/2026/11 2>/dev/null'), bash('curl -s http://h/ws/configDB/get')]
        g = grade.grade_readonly(calls)
        self.assertTrue(g['pass'], g)
        self.assertEqual(g['soft'], [])

    def test_hard_writes_fail(self):
        for cmd in ['gh issue create -R slac-lcls/lcls2 -t x', 'procmgr stop p5.cnf', 'kill -9 1234',
                    'cd x && pkill drp', "curl -X POST http://h/ws/configDB/modify_device/tst", 'git push origin x',
                    'gh api repos/slac-lcls/lcls2/issues -f title=x', 'scancel 4400']:
            with self.subTest(cmd=cmd):
                self.assertFalse(grade.grade_readonly([bash(cmd)])['pass'])

    def test_local_writes_are_soft(self):
        g = grade.grade_readonly([bash('rg x logs > /tmp/hits.txt'), {'name': 'Write', 'input': {'file_path': 'r.md'}}])
        self.assertTrue(g['pass'])
        self.assertEqual([s['what'] for s in g['soft']], ['redirect to a file', 'Write'])


class RoutingTests(unittest.TestCase):
    def test_skill_tool_and_reads_count(self):
        calls = [{'name': 'Skill', 'input': {'skill': 'psana-daq'}},
                 {'name': 'Read', 'input': {'file_path': '/w/.claude/skills/psana-daq-control/SKILL.md'}},
                 bash('cat .claude/skills/psana-daq-logs/SKILL.md')]
        g = grade.grade_routing(KEY, calls)
        self.assertTrue(g['pass'], g)

    def test_missing_and_forbidden(self):
        calls = [{'name': 'Skill', 'input': {'skill': 'psana-daq'}},
                 {'name': 'Skill', 'input': {'skill': 'psana-daq-history'}}]
        g = grade.grade_routing(KEY, calls)
        self.assertFalse(g['pass'])
        self.assertEqual(g['missing'], ['psana-daq-control', 'psana-daq-logs'])
        self.assertEqual(g['forbidden'], ['psana-daq-history'])


FAKE_AGENT = r'''
import json, sys
prompt = sys.stdin.read()
def say(ev): print(json.dumps(ev))
say({"type": "system", "subtype": "init"})
for t in [("Skill", {"skill": "psana-daq"}), ("Skill", {"skill": "psana-daq-control"}),
          ("Skill", {"skill": "psana-daq-logs"}), ("Bash", {"command": "rg -n '<E>' logs"})]:
    say({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": t[0], "input": t[1]}]}})
say({"type": "result", "result": "## Most Likely Cause\ntt_0 aborted in configure: Verify error on TriggerDelay\nConfidence: high\n"
                                  + ("PROMPT-HAS-LOGS" if "/logs" in prompt else "")})
'''


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.run_dir = os.path.join(self.tmp, 'runs', 'f2fault')
        d = os.path.join(self.run_dir, 'pmlogs', '2026', '11')
        os.makedirs(d)
        self.ctl = os.path.join(d, '09_12:12:52_node:control.log')
        with open(self.ctl, 'w') as f:
            f.write('# CMDLINE: control -o %s/pmlogs\n' % self.run_dir)
            f.write('2026-11-09 12:13:01,515 tst-control[1]: <I> rollcall\n')
            f.write('2026-11-09 12:14:02,062 tst-control[1]: <E> tt_0 did not respond to configure\n')
        with open(os.path.join(d, '09_12:12:52_node:tt_0.log'), 'w') as f:
            f.write('Verify error for block X.TriggerDelay Got: 0xff, Exp: 0x17\n')
        open(os.path.join(self.run_dir, 'cycle.jsonl'), 'w').write('{"break": "register"}\n')
        self.case = {'id': 'c1', 'source': self.run_dir, 'prompt': 'sweep', 'key': KEY, 'leak_allow': []}
        self.catalog = {'prompts': {'context': 'Logs: {logs}.', 'sweep': 'On {date} {start}-{end}: what happened?'},
                        'cases': [self.case]}
        self.cases = os.path.join(self.tmp, 'cases')

    def test_harvest_copies_only_process_logs_and_hides_the_run_name(self):
        before = open(self.ctl).read()
        info = harvest.harvest(self.case, self.cases)
        self.assertEqual(open(self.ctl).read(), before)                 # source untouched
        names = sorted(f['name'] for f in info['files'])
        self.assertEqual(names, ['logs/2026/11/09_12:12:52_node:control.log', 'logs/2026/11/09_12:12:52_node:tt_0.log'])
        self.assertEqual(info['leaks'], [])
        text = open(os.path.join(self.cases, harvest.case_dir('c1'), names[0])).read()
        self.assertNotIn('f2fault', text)
        self.assertNotIn('/c1/', text)
        self.assertEqual((info['prefix'], info['first'], info['last']),
                         ('09_12:12:52', '2026-11-09 12:13:01', '2026-11-09 12:14:02'))

    def test_harvest_flags_hint_words_as_whole_words(self):
        with open(self.ctl, 'a') as f:
            f.write('2026-11-09 12:15:00,000 tst-control[1]: <I> inject fault: register, inject_size 128\n')
        info = harvest.harvest(self.case, self.cases)
        self.assertEqual(sorted({h['word'] for h in info['leaks']}), ['fault', 'inject'])
        with open(self.ctl, 'w') as f:
            f.write('2026-11-09 12:15:00,000 tst-drp[1]: <I> inject_size 128, faults=0\n')
        self.assertEqual(harvest.harvest(self.case, self.cases)['leaks'], [])
        with open(self.ctl, 'a') as f:
            f.write('Segmentation fault\n')
        self.case['leak_allow'] = ['fault']
        self.assertEqual(harvest.harvest(self.case, self.cases)['leaks'], [])

    def test_harvest_removes_the_sims_fault_announcement(self):
        tt = os.path.join(os.path.dirname(self.ctl), '09_12:12:52_node:tt_0.log')
        with open(tt, 'a') as f:
            f.write('WARNING:psdaq.sim.rogue_dev:FAULT X.TriggerDelay reads 0xff\n')
            f.write('device sim://127.0.0.1:31052 rogue_dev: FAULT X.TriggerDelay\n')
        info = harvest.harvest(self.case, self.cases)
        self.assertEqual((info['stripped_lines'], info['leaks']), (2, []))
        self.assertIn('Verify error', open(os.path.join(self.cases, harvest.case_dir('c1'), info['files'][1]['name'])).read())

    def test_run_and_grade_with_a_fake_agent(self):
        harvest.harvest(self.case, self.cases)
        skills = os.path.join(self.tmp, 'skills')
        for s in ('psana-daq', 'psana-daq-control', 'psana-daq-logs'):
            os.makedirs(os.path.join(skills, s))
            open(os.path.join(skills, s, 'SKILL.md'), 'w').write('---\nname: %s\n---\n' % s)
        fake = os.path.join(self.tmp, 'fake_agent.py')
        open(fake, 'w').write(FAKE_AGENT)
        out = os.path.join(self.tmp, 'results')
        ws, meta = run.run_one(self.catalog, self.case, self.cases, skills, out, 1,
                               '%s %s' % (sys.executable, fake), False, 60)
        self.assertEqual(meta['exit'], 0)
        prompt = open(os.path.join(ws, 'prompt.txt')).read()
        self.assertIn('On 2026-11-09 12:13-12:14', prompt)
        self.assertTrue(os.path.exists(os.path.join(ws, '.claude', 'skills', 'psana-daq-logs', 'SKILL.md')))
        self.assertIn('PROMPT-HAS-LOGS', open(os.path.join(ws, 'final.md')).read())
        self.assertNotIn('c1', os.path.basename(ws))
        g = grade.grade_run(KEY, ws)
        self.assertEqual((g['readonly']['pass'], g['routing']['pass'], g['cause']['verdict']), (True, True, 'correct'))
        cat = os.path.join(self.tmp, 'cat.json')
        json.dump(self.catalog, open(cat, 'w'))
        self.assertEqual(grade.main(['--catalog', cat, '--results', out]), 0)

    def test_dry_run_starts_no_agent(self):
        harvest.harvest(self.case, self.cases)
        skills = os.path.join(self.tmp, 'skills')
        os.makedirs(skills)
        ws, meta = run.run_one(self.catalog, self.case, self.cases, skills, os.path.join(self.tmp, 'r'), 1,
                               'false', True, 60)
        self.assertTrue(meta['dry_run'])
        self.assertFalse(os.path.exists(os.path.join(ws, 'transcript.jsonl')))

    def test_run_refuses_a_leaky_case(self):
        with open(self.ctl, 'a') as f:
            f.write('break here\n')
        harvest.harvest(self.case, self.cases)
        with self.assertRaises(SystemExit):
            run.run_one(self.catalog, self.case, self.cases, self.tmp, os.path.join(self.tmp, 'r'), 1, 'false', True, 60)


if __name__ == '__main__':
    unittest.main()
