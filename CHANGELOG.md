# Changelog

All notable changes to this project will be documented in this file.
See [docs/CHANGELOG_GUIDE.md](docs/CHANGELOG_GUIDE.md) for how to add entries.

## [Unreleased]

### Added

- Added the config DB editor (select, tree and text editors, long-value popup, save with confirm) and the rest of the PyQt control GUI's user-facing controls (partition-table columns and segment collapse, state box that ignores arrow keys and the wheel, mnemonics) to the web GUI, with a parity check that enumerates the PyQt controls from source and passes only when every row is mapped to a web element with a passing, tagged headless-browser test or is not applicable with a reason an offscreen PyQt walk confirms; `daq_sim e2e --edit-seed` (a config edit in the web editor read back at the next Configure) and `--break truncate-xtc2`; the web GUI also offers the User/Expert tabs of `CGWMainTabs`/`CGWMainTabUser`, modules the live PyQt GUI no longer imports. [#27](https://github.com/carbonscott/lcls2/pull/27)
- Added a web control GUI for the DAQ beside the PyQt one (`daq_webgui`, `psdaq/psdaq/webgui`): a loopback-only stdlib HTTP + server-sent-events server on `DaqControl` and a vanilla-JS page with the main window's controls and an events counter fed by the timing source; `daq_sim up --webgui`; `daq_sim e2e`, a one-command headless-browser test that takes the hardware-free DAQ to Running and back through the web GUI and checks that the page count, the TEB written count and psana2's count agree; and a parity enumerator and checker over `psdaq/psdaq/control_gui`. [#26](https://github.com/carbonscott/lcls2/pull/26)
- Added a hardware-free DAQ on one node: `simxpm`, a simulated XPM that serves the PVs control.py writes and sends ordered timing frames; a `sim://` DMA backend for the CPU DRP (`MemPoolSim`, `drp -d sim://host:port`) with a fakecam payload checkable per event; `daq_sim up/cycle/status/down` to run control (normal mode), the TEB and a simulated DRP under procmgr; `xtc2_check` for psana2 read-back; and `psdaq/psdaq/sim/RUNBOOK.md`. [#25](https://github.com/carbonscott/lcls2/pull/25)
- Added `psdaq.sim` local stand-ins for running the DAQ with no hardware on one node: a config DB server with `mongoconfigdb` semantics backed by a JSON file, a seed for the `tmoteb` trigger and a `fakecam` sim detector, a run DB/eLog stub, and an isolation env (`sim_env.sh`) with a fail-closed `preflight.sh`. [#24](https://github.com/carbonscott/lcls2/pull/24)
- Added ePixUHR calibration and a CALIB mode for taking darks to the GPU DRP, with the Reader/Reducer performance work that runs five GPU DRPs on one node at 33 kHz, and per-stage metrics. @rclaus2 [#269](https://github.com/slac-lcls/lcls2/pull/269)

### Changed

- Changed the TEB, MEB and DRP to detect a reused or overwritten RDMA buffer slot when it happens and report the source, slot and pulse IDs; `-k eb_slot_check=0` turns this off. @rclaus2 [#289](https://github.com/slac-lcls/lcls2/pull/289)
- Changed control's BeginRun phase 1 timeout from 6 s to 12 s, since fetching calibration constants can take several seconds. @rclaus2 [#269](https://github.com/slac-lcls/lcls2/pull/269)
- Changed the DAQ and psana tests to run on every push to a PR. @mavaylon1 [#267](https://github.com/slac-lcls/lcls2/pull/267)

### Deprecated

### Removed

### Fixed

- Fixed psana SMD callbacks restarting their step and event counters at chunk boundaries, which could skip selected steps or repeat event-selection windows in serial and MPI processing. @monarin [#287](https://github.com/slac-lcls/lcls2/pull/287)
- Fixed parallel psana hanging silently when the MPI layout leaves an EventBuilder with no BigData ranks. `Communicators` now rejects such layouts up front with the numbers spelled out. @amandashack [#249](https://github.com/slac-lcls/lcls2/pull/249)
- Fixed a multi-lane DRP stalling silently when one lane stops delivering, as in #273. The reader now logs, once, which lanes arrived and which are missing for the stuck event, and counts it in the `drp_num_lane_stalls` metric. A partial event left by the stall no longer survives a Reset or an evtCounter restart, where it used to combine with the next event into a duplicate transition and abort the DRP; such events are counted in `drp_num_stale_events`. @rclaus2 [#282](https://github.com/slac-lcls/lcls2/pull/282)
- Fixed `XtcMonitorServer` and `ShmemClient` not saying why `mq_open` failed. They now name the exceeded system limit (e.g. `fs.mqueue.msg_max`) or other cause and how to fix it, and errors no longer appear ahead of earlier output in logs. @rclaus2 [#276](https://github.com/slac-lcls/lcls2/pull/276)
