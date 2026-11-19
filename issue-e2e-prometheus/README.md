# issue-e2e-prometheus

Evidence for the fork's issue "`daq_sim e2e` assertion 6 fails: e2e.py passes a (host, port) tuple to `scrape` as the port".
Everything ran on S3DF node sdfrome046 (roma partition, Slurm job 45757390), inside `unshare -rn` (a private network
namespace: only `lo`), on 2026-11-19 between 00:29:49 and 00:35:35 UTC, in one recorded take.

- `expected.txt`: the expected results, written at 00:20:26Z before the take.
- `recording/`: the take. `typescript` + `timing` (util-linux `script -q -f --timing`, unedited), `session.cast`
  (the same bytes as asciicast v2, with chapter markers; `asciinema play session.cast`), `transcript.txt` (escape codes
  stripped), `e2e-prometheus.gif` (tmux pane snapshots in `frames.jsonl`, rendered with `scripts/render.py` of this
  branch; waits capped at 2.5 s), `steps.json` (every typed command), `rc.sh` (the recorded shell's rc), `chapters.jsonl`,
  `driver.log`.
- `logs/`: full `daq_sim e2e` output per run (`e2e-bef.log` at 5eb773c84b9d, `e2e-a.log` at e601509f9 = 71895fbda^,
  `e2e-b.log` at 71895fbda, `e2e-fix.log` at 5eb773c84b9d + the fix), the read-back pollers' output (`curl-*.log`,
  `pypoll-*.log`) and the exporters' answer after RESET (`bef-reset-*.txt`).
- `shots/`: `<run>-e2e-0N-*.png` are the e2e's own headless-Chromium screenshots of the web GUI;
  `term-*.png` are frames of the recording.
- `scripts/`: the runner (`e2e-at.sh`), the pollers (`curlpoll.sh`, `pypoll.py`), the recorder (`rec.sh`, `drive.py`,
  `rec.tmux.conf`), `cast.py`, `keyframes.py`, and `build.sh` (the build of each checkout, no CUDA).
