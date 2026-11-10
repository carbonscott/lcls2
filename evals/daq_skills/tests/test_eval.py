"""Tests for the DAQ-skill eval tools.  No model calls: agents and the judge are scripted.

    python3 -m unittest discover -s tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import grade    # noqa: E402
import harvest  # noqa: E402
import judge    # noqa: E402
import run      # noqa: E402

KEY = {'fault': {'component': ['tt_0'], 'transition': ['configure'], 'mechanism': ['Verify error', 'TriggerDelay'],
                 'summary': 'tt_0 aborted in configure: Verify error on TriggerDelay'},
       'expect_skills': ['psana-daq', 'psana-daq-logs'], 'forbid_skills': ['psana-daq-history'], 'sessions': ['09_12:12:52']}
HEALTHY = {'fault': None, 'independent': ['double free'], 'sessions': []}


def report(cause, conf='high', extra=''):
    return '## Most Likely Cause\n%s\nConfidence: %s\n%s' % (cause, conf, extra)


def bash(cmd):
    return {'name': 'Bash', 'input': {'command': cmd}}


class CauseKeywords(unittest.TestCase):
    def verdict(self, text, key=KEY):
        return grade.grade_cause(key, text)

    def test_correct_needs_component_transition_and_mechanism(self):
        self.assertEqual(self.verdict(report('tt_0 aborted in configure: Verify error on TriggerDelay'))['verdict'], 'correct')

    def test_stopping_at_did_not_respond_is_partial(self):
        self.assertEqual(self.verdict(report('tt_0 did not respond to configure'))['verdict'], 'partial')

    def test_wrong_component_with_high_confidence_is_overconfident(self):
        g = self.verdict(report('teb0 lost its link during enable'))
        self.assertEqual((g['verdict'], g['overconfident']), ('wrong', True))

    def test_component_must_match_as_a_whole_word(self):
        self.assertEqual(self.verdict(report('tt_01 failed configure with a Verify error'))['verdict'], 'wrong')

    def test_unknown_is_its_own_verdict(self):
        g = self.verdict(report('Unknown. control.log shows configure failed.', 'low'))
        self.assertEqual((g['verdict'], g['overconfident']), ('unknown', False))

    def test_healthy_run(self):
        ok = self.verdict(report('No fault: the run completed.', extra='## Known Issues\n- double free at exit'), HEALTHY)
        self.assertEqual((ok['verdict'], ok['independent_found']), ('correct', ['double free']))
        self.assertEqual(self.verdict(report('tt_0 crashed with a double free'), HEALTHY)['verdict'], 'false-alarm')

    def test_free_form_answer_is_graded_on_the_whole_message(self):
        g = self.verdict('tt_0 crashed in configure with a Verify error on TriggerDelay.')
        self.assertEqual((g['templated'], g['verdict']), (False, 'correct'))


class Readonly(unittest.TestCase):
    def test_reads_pass(self):
        for cmd in ("rg -n 'kill|pkill|scancel' logs/", "zstd -dc a.log.zst | grep '<E>'", 'cat control.log > /dev/null',
                    "curl -s -G 'https://api.github.com/search/issues' --data-urlencode 'q=is:issue' -H 'A: b'"):
            self.assertTrue(grade.grade_readonly([bash(cmd)])['pass'], cmd)

    def test_hard_writes_fail(self):
        for cmd in ('daqstate -p 5 -s configured', 'procmgr stop tst.cnf', 'pkill drp', 'scancel 123', 'git push origin x',
                    'gh issue create --title x', "curl -s https://x/y --data-urlencode 'a=b' -H 'A: b'",
                    "curl -G https://x/y -X POST -d 'a=b' ", 'daq_sim down'):
            self.assertFalse(grade.grade_readonly([bash(cmd)])['pass'], cmd)

    def test_local_writes_are_listed_not_failed(self):
        g = grade.grade_readonly([bash('rg Verify logs > notes.txt'), {'name': 'Write', 'input': {'file_path': 'x'}}])
        self.assertTrue(g['pass'])
        self.assertEqual(len(g['soft']), 2)


class RoutingSessionsStructure(unittest.TestCase):
    def test_skill_tool_and_skill_file_reads_count(self):
        calls = [{'name': 'Skill', 'input': {'skill': 'psana-daq'}}, bash('cat .claude/skills/psana-daq-logs/SKILL.md')]
        self.assertTrue(grade.grade_routing(KEY, calls)['pass'])

    def test_missing_and_forbidden_skills_fail(self):
        g = grade.grade_routing(KEY, [{'name': 'Skill', 'input': {'skill': 'psana-daq-history'}}])
        self.assertEqual((g['pass'], g['missing'], g['forbidden']), (False, ['psana-daq', 'psana-daq-logs'], ['psana-daq-history']))

    def test_launch_named_by_prefix_or_time(self):
        self.assertTrue(grade.grade_sessions(KEY, 'the launch at 12:12:52 failed')['pass'])
        self.assertFalse(grade.grade_sessions(KEY, 'the launch at 20:12:52 failed')['pass'])
        both = dict(KEY, sessions=['09_12:12:52', '09_12:22:37'], all_sessions=True)
        self.assertFalse(grade.grade_sessions(both, 'only 09_12:12:52')['pass'])

    def test_known_issue_must_be_cited_by_number(self):
        key = dict(HEALTHY, known_issues=[134])
        self.assertTrue(grade.grade_known(key, 'matches #134 (double free at exit)')['pass'])
        self.assertTrue(grade.grade_known(key, 'see https://github.com/slac-lcls/lcls2/issues/134')['pass'])
        self.assertFalse(grade.grade_known(key, 'a double free at exit, 1340 events')['pass'])
        self.assertIsNone(grade.grade_known(KEY, 'anything')['pass'])

    def test_structure(self):
        g = grade.grade_structure(report('x') + '\n## Known Issues\nnone\n')
        self.assertEqual((g['templated'], g['confidence_stated'], g['sections']), (True, True, ['Most Likely Cause', 'Known Issues']))
        self.assertFalse(grade.grade_structure('tt_0 crashed.')['templated'])


class Judge(unittest.TestCase):
    def test_parse_accepts_json_and_survives_a_broken_reason(self):
        self.assertEqual(judge.parse('ok {"verdict": "false_alarm", "reason": "x"}')['verdict'], 'false-alarm')
        self.assertEqual(judge.parse('{"verdict": "partial", "right_launch": null, "reason": "says "x" here"}')['verdict'], 'partial')
        self.assertIsNone(judge.parse('{"verdict": "maybe"}'))

    def test_wrong_launch_is_wrong_whatever_the_judge_says(self):
        self.assertEqual(judge.parse('{"verdict": "correct", "right_launch": false}')['verdict'], 'wrong')

    def test_key_text(self):
        self.assertIn('NO FAULT', judge.key_text(HEALTHY))
        t = judge.key_text(KEY)
        self.assertIn('tt_0', t)
        self.assertIn('at 12:12:52 local time', t)
        many = judge.key_text({'fault': KEY['fault'], 'launches': [{'prefix': '09_12:12:52', 'cause': 'verify'}]})
        self.assertIn('- launch 09_12:12:52: verify', many)


FAKE_AGENT = r'''
import json, sys
prompt = sys.stdin.read()
def say(ev): print(json.dumps(ev))
say({"type": "system", "subtype": "init"})
say({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Skill", "input": {"skill": "psana-daq"}},
    {"type": "tool_use", "name": "Bash", "input": {"command": "cat .claude/skills/psana-daq-logs/SKILL.md; rg -n Verify " + prompt.split(" under ")[1].split(". ")[0]}}]}})
say({"type": "result", "result": "## Most Likely Cause\ntt_0 aborted in configure in launch 09_12:12:52: Verify error on TriggerDelay\nConfidence: high\n",
     "total_cost_usd": 0.5, "num_turns": 3, "usage": {"output_tokens": 40}})
'''
FAKE_JUDGE = r'''
import json, sys
sys.stdin.read()
print(json.dumps({"result": json.dumps({"verdict": "correct", "component": "tt_0", "right_launch": True, "reason": "matches"}), "total_cost_usd": 0.01}))
'''


class Pipeline(unittest.TestCase):
    """harvest -> run (scripted agent, no sandbox) -> judge (scripted) -> grade, on a made-up sim run."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='daqeval-')
        self.root = os.path.join(self.tmp, 'sims')
        self.rundir = os.path.join(self.root, 'work', 'break-register', 'wd-secret')
        logs = os.path.join(self.rundir, 'pmlogs', '2026', '11')
        os.makedirs(logs)
        self.files = {
            '09_12:12:52_node1:control.log': '# CMDLINE: control -r %s/activedet.json\n'
                                             '2026-11-09 12:12:54,000 tst-control[1]: <I> start\n'
                                             '2026-11-09 12:14:02,000 tst-control[1]: <E> tt_0 did not respond to configure\n' % self.rundir,
            '09_12:12:52_node1:tt_0.log': '# TESTRELDIR:%s/wt-x/install\nWARNING:rogue_dev:FAULT Top.TriggerDelay reads back 0xff\n'
                                          'rogue.GeneralError: Verify error for block Top.TriggerDelay\n' % self.root,
            '09_18:00:00_node1:control.log': '2026-11-09 18:00:02,000 tst-control[2]: <I> start\n',
        }
        for n, text in self.files.items():
            open(os.path.join(logs, n), 'w').write(text)
            os.utime(os.path.join(logs, n), (1000000000, 1000000000))
        open(os.path.join(self.rundir, 'daq_sim.state.json'), 'w').write('{"fault": "TriggerDelay"}')
        ses = {'run': 'work/break-register/wd-secret', 'ym': '2026/11', 'host': 'node1'}
        self.cat = {'version': 2, 'logs_path': '/sdf/home/t/tstopr/daq/logs',
                    'context': 'Logs are under /sdf/home/t/tstopr/daq/logs. Offline review.',
                    'pools': {'one': {'sessions': [dict(ses, prefix='09_12:12:52')]},
                              'day': {'sessions': [dict(ses, prefix='09_12:12:52'), dict(ses, prefix='09_18:00:00')],
                                      'compress_before': '2026-11-09 15:00:00'}},
                    'cases': [{'id': 'c1', 'tier': 1, 'set': 'core', 'pool': 'one', 'question': 'Did anything go wrong?',
                               'key_source': 'planted', 'key': KEY},
                              {'id': 'c2', 'tier': 3, 'set': 'full', 'pool': 'day', 'question': 'Around 12:13?',
                               'key_source': 'planted', 'key': KEY}]}
        self.catalog = os.path.join(self.tmp, 'catalog.json')
        json.dump(self.cat, open(self.catalog, 'w'))
        self.work = os.path.join(self.tmp, 'work')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def harvest(self, pool='one'):
        return harvest.harvest_pool(pool, self.cat['pools'][pool], self.root, self.work)

    def pool_dir(self, pool='one'):
        return os.path.join(self.work, 'pools', harvest.pool_id(pool), 'logs', '2026', '11')

    def test_harvest_copies_only_that_launchs_process_logs(self):
        info = self.harvest()
        self.assertEqual(sorted(os.listdir(self.pool_dir())), ['09_12:12:52_node1:control.log', '09_12:12:52_node1:tt_0.log'])
        self.assertEqual(info['leaks'], [])
        self.assertEqual((info['sessions'][0]['first'], info['sessions'][0]['last']), ('2026-11-09 12:12:54', '2026-11-09 12:14:02'))

    def test_harvest_hides_paths_and_the_sims_announcement_but_keeps_the_evidence(self):
        info = self.harvest()
        text = ''.join(open(os.path.join(self.pool_dir(), n)).read() for n in os.listdir(self.pool_dir()))
        for hidden in ('wd-secret', 'break-register', self.root, 'rogue_dev'):
            self.assertNotIn(hidden, text)
        self.assertIn('Verify error for block Top.TriggerDelay', text)
        self.assertIn(harvest.SCRATCH, text)
        self.assertIn(harvest.RELEASES, text)
        self.assertEqual(info['sessions'][0]['planted'], ['WARNING:rogue_dev:FAULT Top.TriggerDelay reads back 0xff'])

    def test_harvest_keeps_modification_times(self):
        self.harvest()
        self.assertEqual(int(os.stat(os.path.join(self.pool_dir(), '09_12:12:52_node1:tt_0.log')).st_mtime), 1000000000)

    def test_harvest_fails_a_pool_that_still_holds_a_hint_word(self):
        p = os.path.join(self.rundir, 'pmlogs', '2026', '11', '09_12:12:52_node1:tt_0.log')
        open(p, 'a').write('note: running under break-register harness\n')
        self.assertIn('break', [h['word'] for h in self.harvest()['leaks']])
        self.assertEqual(harvest.main(['--catalog', self.catalog, '--root', self.root, '--out', self.work, '--pool', 'one']), 1)

    def test_segmentation_fault_is_not_a_hint(self):
        self.assertEqual(harvest.leak_scan(harvest.OWN_WORDS.sub('', '<C> FATAL: Segmentation Fault - stack'), ['fault'], []), [])

    @unittest.skipUnless(shutil.which('zstd'), 'needs zstd')
    def test_older_launches_are_compressed(self):
        info = self.harvest('day')
        names = sorted(os.listdir(self.pool_dir('day')))
        self.assertEqual(names, ['09_12:12:52_node1:control.log.zst', '09_12:12:52_node1:tt_0.log.zst', '09_18:00:00_node1:control.log'])
        self.assertEqual([s['zst'] for s in info['sessions']], [True, False])
        self.assertEqual(int(os.stat(os.path.join(self.pool_dir('day'), names[0])).st_mtime), 1000000000)

    def run_agent(self, arm='skills', skills=None, extra=()):
        agent = os.path.join(self.tmp, 'agent.py')
        open(agent, 'w').write(FAKE_AGENT)
        if skills is None:
            skills = os.path.join(self.tmp, 'skills')
            for s in ('psana-daq', 'psana-daq-logs'):
                os.makedirs(os.path.join(skills, s), exist_ok=True)
                open(os.path.join(skills, s, 'SKILL.md'), 'w').write('# ' + s)
        self.results = os.path.join(self.tmp, 'results')
        return run.main(['--catalog', self.catalog, '--work', self.work, '--arm', arm, '--skills', skills, '--out', self.results,
                         '--no-sandbox', '--agent-cmd', sys.executable + ' ' + agent] + list(extra))

    def test_run_judge_and_grade_end_to_end(self):
        self.harvest()
        self.assertEqual(self.run_agent(), 0)
        self.assertEqual(self.run_agent('none', 'none'), 0)
        jd = os.path.join(self.tmp, 'judge.py')
        open(jd, 'w').write(FAKE_JUDGE)
        self.assertEqual(judge.main(['--catalog', self.catalog, '--results', self.results, '--judge-cmd', sys.executable + ' ' + jd]), 0)
        rows = grade.collect(self.results, grade.load_catalog(self.catalog))
        self.assertEqual([(r['arm'], r['case'], r['cause']['verdict'], r['cause']['by']) for r in rows],
                         [('none', 'c1', 'correct', 'judge'), ('skills', 'c1', 'correct', 'judge')])
        by = {r['arm']: r for r in rows}
        self.assertEqual((by['skills']['routing']['pass'], by['none']['routing']['pass']), (True, None))
        self.assertTrue(by['skills']['readonly']['pass'] and by['skills']['sessions']['pass'])
        self.assertEqual(by['skills']['cost_usd'], 0.5)
        s = grade.summarize(rows)
        self.assertEqual((s['skills']['correct'], s['skills']['routing'], s['none']['routing']), (1, '1/1', 'n/a'))
        self.assertEqual(sorted(os.listdir(os.path.join(os.path.dirname(rows[1]['run_dir']), os.path.basename(rows[1]['run_dir']), 'ws', '.claude', 'skills'))),
                         ['psana-daq', 'psana-daq-logs'])

    def test_run_names_folders_opaquely_and_resume_keeps_finished_runs(self):
        self.harvest()
        self.run_agent()
        d = os.path.join(self.results, 'skills')
        self.assertEqual(os.listdir(d), [run.run_id('c1', 1)])
        self.assertNotIn('c1', os.listdir(d)[0])
        before = os.stat(os.path.join(d, os.listdir(d)[0], 'meta.json')).st_mtime
        time.sleep(0.05)
        self.run_agent(extra=['--resume'])
        self.assertEqual(os.stat(os.path.join(d, os.listdir(d)[0], 'meta.json')).st_mtime, before)

    def test_dry_run_starts_no_agent(self):
        self.harvest()
        self.run_agent(extra=['--dry-run'])
        d = os.path.join(self.results, 'skills', run.run_id('c1', 1))
        self.assertTrue(json.load(open(os.path.join(d, 'meta.json')))['dry_run'])
        self.assertFalse(os.path.exists(os.path.join(d, 'transcript.jsonl')))
        self.assertEqual(grade.collect(self.results, grade.load_catalog(self.catalog)), [])

    def test_a_many_launch_report_about_another_launch_is_wrong(self):
        d = os.path.join(self.tmp, 'r')
        os.makedirs(d)
        open(os.path.join(d, 'final.md'), 'w').write(report('tt_0 aborted in configure at 20:12:52: Verify error on TriggerDelay'))
        self.assertEqual(grade.grade_run(KEY, d, tier=1)['cause']['verdict'], 'correct')
        g = grade.grade_run(KEY, d, tier=3)['cause']
        self.assertEqual((g['verdict'], g['by']), ('wrong', 'keywords+launch'))

    def test_sandbox_shows_only_the_workspace_and_the_logs(self):
        a = run.sandbox('/x/ws', '/x/logs', '/sdf/home/t/tstopr/daq/logs')
        s = ' '.join(a)
        self.assertIn('--ro-bind /x/logs /sdf/home/t/tstopr/daq/logs', s)
        self.assertIn('--bind /x/ws /work --chdir /work', s)
        self.assertIn('--tmpfs / ', s)
        self.assertNotIn('--bind / /', s)
        self.assertNotIn('.ssh', s)
        self.assertIn('--ro-bind /opt/tools /opt/tools', ' '.join(run.sandbox('/x/ws', '/x/logs', '/l', ['/opt/tools'])))


if __name__ == '__main__':
    unittest.main()
