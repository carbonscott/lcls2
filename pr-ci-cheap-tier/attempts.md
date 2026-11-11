# ci/cheap-tier attempt log (worker CI, sim-daq-hardening)

1. b41d66424 https://github.com/carbonscott/lcls2/actions/runs/42987776214 conclusion=failure, 08:31:56Z-08:42:28Z (10m32s; build ~6 min after conda)
   - unit: 16 files collected; `test_sim_configdb_seed_store.py F`, then pytest vanished in `test_sim_features.py ........` with `##[error]Process completed with exit code 1.` and no summary
     (cause read from code: test_two_node_plan calls daq_sim.main(['up','--hosts','nodeA,nodeB']) -> ensure_env os.execvp('bash', ...) replaces pytest when SIM_ENV_SOURCED is unset, daq_sim.py:350-359, test_sim_features.py:246)
   - daq: `PREFLIGHT PASS` on runnervm7aw5e; blocking: `daq_sim: up FAILED: procmgr start exited 1 (logs/procmgr.log)` with procmgr.log `SUBMODULEDIR not defined in environment` (ProcMgr.py:964-967)
2. 585648cbb https://github.com/carbonscott/lcls2/actions/runs/42989331376 conclusion=failure, 08:43:47Z-08:55:57Z (12m10s)
   - unit: 16 files, 422 collected, ran to the end; 10 F (seed_store, hsd store, rogue_dev x5, sls x1, xpmdet_types x1 ...), all `Exception: Library path /home/runner/work/lcls2/lcls2/install/no-submodules/... does not exist or is not readable` (my fake SUBMODULEDIR: the tests skip when it is unset, not when it is wrong)
   - daq: PREFLIGHT PASS, config DB seeded, procServ children started (control.log shows control running), blocking: `daq_sim: up FAILED: not RUNNING after start: ['control', 'teb0', 'fakecam_0']` with status `NOCONNECT` for all three (procmgr telnets procServ's control port at gethostname(), ProcMgr.py:600-604; Ubuntu procServ takes control connections from localhost only)
3. 929dc5e36 https://github.com/carbonscott/lcls2/actions/runs/42991273542 conclusion=failure, 08:58:32Z-09:10:19Z (11m47s)
   - unit: `4 failed, 412 passed, 6 skipped in 135.38s`; the 4 failures each `KeyError: 'SUBMODULEDIR'` in a subprocess with no skip guard (seed_store, hsd store, rogue_dev proc text, sls seed); 5 siblings already skip `needs $SUBMODULEDIR (the DAQ env)`
   - daq: control RUNNING (hostname on loopback fixed NOCONNECT); blocking: `daq_sim: up FAILED: not RUNNING after start: ['teb0', 'fakecam_0']`, teb/drp logs `<C> Inadequate MEMLOCK limit: got 8388608, require -1` / `<C> Resource limit(s) error`, exit status 1
   - upload: `The path for one of the files in artifact is not valid: /pmlogs/2026/11/11_09:09:20_runnervm7aw5e:control.log. Contains the following character:  Colon :`
4. 0adbb1fad https://github.com/carbonscott/lcls2/actions/runs/42993195471 conclusion=failure, 09:12:19Z-09:22:20Z (10m01s)
   - unit: GREEN `412 passed, 10 skipped in 125.11s (0:02:05)`
   - daq: control and teb0 RUNNING, MEMLOCK unlimited; blocking: `daq_sim: up FAILED: not RUNNING after start: ['fakecam_0']`, drp log `Exception: Library path /home/runner/work/_temp/daq_sim_ci/no-submodules/l2si-drp/firmware/submodules/axi-pcie-core/python does not exist or is not readable` / `<C> **** python error`, killed by signal 6 (fakecam's drp runs xpmdet_config -> enable_l2si_drp at startup)
5. 23d4a9ac1 https://github.com/carbonscott/lcls2/actions/runs/42994900405 conclusion=failure, 09:24:24Z-09:31:34Z (7m10s)
   - unit: green (412 passed, 10 skipped)
   - daq: blocking: `fatal: could not read Username for 'https://github.com': No such device or address` / `fetch of slaclab/l2si-drp 759fe14ec33ccc04a0bba4eb36d71928ac0e49a7 failed`
     slaclab/l2si-drp is private (`gh api repos/slaclab/l2si-drp` -> {"private":true,"visibility":"internal"}; anonymous https://github.com/slaclab/l2si-drp -> 404; axi-pcie-core, l2si-core, lcls-timing-core, lcls2-pgp-fw-lib, surf -> 200).
     The only public copy, conda lcls-ii/l2si-drp 5.2.1 (2024-12-11), lacks _DevC1100/_TimingFrameRx/_TimingPhyMonitor and its _Root.Root passes `tdet=tdet` (undefined name), so DrpTDetRoot cannot be built from it: not usable.
6. b80648843 https://github.com/carbonscott/lcls2/actions/runs/42996358002 conclusion=success, 09:34:46Z-09:41:44Z (6m58s; job 09:34:49Z-09:41:43Z)
   - unit: `sim test files collected: 16`, `collected 422 items`, `412 passed, 10 skipped in 103.18s (0:01:43)`
   - daq: NOT RUN (step skipped): `##[warning]fakecam's drp imports l2si_drp from slaclab/l2si-drp, a private repository; set the repository secret L2SI_DRP_TOKEN (read access to it) to run it` (no such secret exists on carbonscott/lcls2)

## Iteration 2 (worker CI2): unit only (user decision 10:50Z: no token for slaclab/l2si-drp; the fakecam DAQ run is the S3DF command `daq_sim matrix -w <WD> --only types --types fakecam`, `--break corrupt` exit 1)
7. 74c94bfb8 https://github.com/carbonscott/lcls2/actions/runs/43028861910 conclusion=failure, 13:24:36Z-13:30:58Z (6m22s)
   - unit-only job (DAQ step, token step, l2si-drp fetch, procServ step and DAQ_SIM_RCFILE removed; 4 skips moved up front)
   - `sim test files collected: 16 (glob psdaq/psdaq/tests/test_sim*.py at 74c94bf)` then `psdaq/psdaq/sim/sim_env.sh: line 86: PROCMGR_EXPORT: unbound variable` (I had dropped the PROCMGR_EXPORT export from ci_cheap_tier.sh; sim_env.sh extends it under set -u)
8. af3696039 https://github.com/carbonscott/lcls2/actions/runs/43029880142 conclusion=success, 13:31:24Z-13:40:46Z (9m22s; job 13:31:28Z-13:40:46Z)
   - `sim test files collected: 16 (glob psdaq/psdaq/tests/test_sim*.py at af36960)`, `collected 422 items`
   - `================= 412 passed, 10 skipped in 125.12s (0:02:05) ==================`
   - skips: SKIPPED [1] psdaq/psdaq/tests/test_sim_configdb_seed_store.py:30: needs $SUBMODULEDIR (the DAQ env)
            SKIPPED [1] psdaq/psdaq/tests/test_sim_hsd.py:92: needs $SUBMODULEDIR (the DAQ env)
            SKIPPED [1] psdaq/psdaq/tests/test_sim_programs.py:125: could not import 'ami': No module named 'ami'
            SKIPPED [1] psdaq/psdaq/tests/test_sim_rogue_dev.py:201: needs $SUBMODULEDIR (the DAQ env)
            SKIPPED [1] psdaq/psdaq/tests/test_sim_rogue_dev.py:291: needs $SUBMODULEDIR (the DAQ env)
            SKIPPED [1] psdaq/psdaq/tests/test_sim_rogue_dev.py:303: needs $SUBMODULEDIR (the DAQ env)
            SKIPPED [1] psdaq/psdaq/tests/test_sim_rogue_dev.py:491: needs $SUBMODULEDIR (the DAQ env)
            SKIPPED [1] psdaq/psdaq/tests/test_sim_rogue_dev.py:505: needs $SUBMODULEDIR (the DAQ env)
            SKIPPED [1] psdaq/psdaq/tests/test_sim_sls.py:267: needs $SUBMODULEDIR (the DAQ env)
            SKIPPED [1] psdaq/psdaq/tests/test_sim_xpmdet_types.py:63: needs $SUBMODULEDIR (the DAQ env)
9. ci-break/unit-1 d7325d70c (from af3696039; test_sim_framer.py:66 `==` flipped to `!=`) https://github.com/carbonscott/lcls2/actions/runs/43031426914 conclusion=failure, 13:41:36Z-13:51:30Z
   - `E       assert 5 != (5 & 255)` / `psdaq/psdaq/tests/test_sim_framer.py:66: AssertionError`
   - `FAILED psdaq/psdaq/tests/test_sim_framer.py::test_epix100_frame_layout - assert 5 != (5 & 255)`
   - `============ 1 failed, 411 passed, 10 skipped in 131.94s (0:02:11) =============`
10. ci-break/payload-1 ba402090c (from af3696039; workflow sets PSDAQ_SIM_CORRUPT_SEQ=9 for the unit step: drp_sim_frame inverts one payload byte of L1Accept 9, MemPoolSim::corrupt) https://github.com/carbonscott/lcls2/actions/runs/43031434875 conclusion=failure, 13:41:39Z-13:50:44Z
   - `FAILED psdaq/psdaq/tests/test_sim_framer.py::test_tb_event_timing_message_layout - assert [41368, 60994...7, 41229, ...] == [41368, 60994...7, 41229, ...]` / `At index 6 diff: 44102 != 44217` (0xac46 vs 0xacb9: low byte 0x46 = ~0xb9, one byte inverted)
   - `FAILED psdaq/psdaq/tests/test_sim_framer.py::test_ts_timing_message_layout - AssertionError: mpsPowerClass` / `At index 7 diff: 248 != 7` (0xf8 = ~0x07)
   - `FAILED psdaq/psdaq/tests/test_sim_framer.py::test_wave8_frame_layout - assert False` (diff shows word 57956 vs 58011 = 0xe264 vs 0xe29b, low byte inverted)
   - `FAILED psdaq/psdaq/tests/test_sim_framer.py::test_epixhr2x2_frame_layout - assert False`
   - `============ 4 failed, 408 passed, 10 skipped in 123.81s (0:02:03) =============`
   - same 4 failures reproduced first on sdfiana025 with builds/96ba26676 (`PSDAQ_SIM_CORRUPT_SEQ=9 python -m pytest psdaq/psdaq/tests/test_sim_framer.py`: `4 failed, 22 passed in 8.09s`)
11. aa6b0e428 (merge of origin/sim-main d4e2217e0, sync PR #48, into ci/cheap-tier; no conflicts) https://github.com/carbonscott/lcls2/actions/runs/43031519426 conclusion=success, 13:42:13Z-13:52:40Z (10m27s; job 13:42:16Z-13:52:39Z)
   - `sim test files collected: 16 (glob psdaq/psdaq/tests/test_sim*.py at aa6b0e4)`, `collected 422 items`
   - `================= 412 passed, 10 skipped in 136.08s (0:02:16) ==================`, the same 10 skip lines as run 8
