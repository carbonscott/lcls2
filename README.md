# pr-assets

Recordings, screenshots and logs for the proof sections of carbonscott/lcls2 PRs #28-#31
(the hardware-free DAQ and its web GUI). This branch holds no code to merge; the PR
descriptions link here so the evidence stays out of the diffs.

- `prNN/terminal.gif`, `.cast`, `.txt`: a tmux pane on an exe.dev VM, recorded with asciinema,
  that ran `ssh -t sdfiana025 srun --jobid=<job> --pty bash` and typed every command. The GIF
  caps waits at 1 s; `asciinema play terminal.cast` replays at real speed.
- `pr30/`, `pr31/`: `tunnel-terminal.*` (the same VM driving the web GUI through a two-hop
  `ssh -L` tunnel), `browser.gif`/`browser.webm` (headless Chromium on the VM) and screenshots.
- `pr31/parity*.txt`: the full parity check output.
- `scripts/`: the recorder (`recdrive.py`), renderers (`render.py`, `vid2gif.sh`, `transcript.py`),
  the tunnel driver (`tunnel_drive.py`), the node-side helpers (`remote/`) and the typed steps (`steps/`).
