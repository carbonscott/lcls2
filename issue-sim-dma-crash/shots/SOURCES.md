# Sources of the screenshots

- `01-code-clamp-and-pebble-size.png` (1300x1243): rendered from `../evidence/code-excerpt.txt` (lines 1-4, 6-35, 37-47) by `lib/render.py`, caption "sim-main 6f0a24daebc2: MemPoolSim clamps an oversized payload to fill the 64 KiB DMA buffer, and the DRP's pebble buffer is the same 64 KiB"; highlights `^ +37 `, `^ +910 `, `^ +99[3-7] `, `^ +155 `, `^ +11[0-2] `; callouts 4. Unedited text of the capture.
- `02-trigger-64k-payload-drp-aborts.png` (1400x631): rendered from `../evidence/run-dma-16384.log` (lines 1-5, 9-9, 29-29, 48-54) by `lib/render.py`, caption "daq_sim up --length 16384 (64 KiB events, fakecam, 120 Hz): the DRP clamps the payload and aborts with signal 6 at the first L1Accept"; highlights `does not fit sim_dma_size`, `Insufficient space`, `killed by signal 6`, `dmaSize 65536`, `pebble buffer size 65536 B`, `--length 16384`; callouts 4. Unedited text of the capture.
- `03-symptom-running-61s-empty-file.png` (1400x774): rendered from `../evidence/run-dma-16384.log` (lines 1-4, 29-47) by `lib/render.py`, caption "Symptom: control reports running for 61 s with the DRP dead, Disable then fails, and the run's xtc2 file is empty (0 B)"; highlights `setState running`, `NumL0Acc = 1010@@yellow`, `did not respond to disable`, `disable failed`, `FAIL`, `\(0 B\)`; callouts 4. Unedited text of the capture.
- `04-control-16300-words-pass.png` (1400x662): rendered from `../evidence/run-dma-16300.log` (lines 1-5, 29-30, 44-51, 53-56) by `lib/render.py`, caption "Control run, same build: a 16300-word payload (63.7 KiB) fits, and the cycle PASSes with every count equal"; highlights `cycle PASS@@green`, `equal .*True@@green`, `16300 payload words@@green`, `dmaSize 65536`; callouts 2. Unedited text of the capture.
- `05-fix-dma-sized-from-length-pass.png` (1400x687): rendered from `../evidence/run-dma-16384-fix.log` (lines 1-5, 29-30, 44-51, 53-56) by `lib/render.py`, caption "With the fix (default sim_dma_size sized from sim_length), the same 64 KiB payload gets 128 KiB buffers and the cycle PASSes"; highlights `cycle PASS@@green`, `equal .*True@@green`, `dmaSize 131072@@green`, `pebble buffer size 131072@@green`, `16384 payload words@@green`; callouts 3. Unedited text of the capture.

The captures were written on S3DF by `evidence/daqrun.sh` (sha1 prefix in each log's `# commit:` line), one Slurm
step each on sdfrome044 (job 47203689), and copied here unchanged:

| Capture here | Written on S3DF as |
|---|---|
| `evidence/run-dma-16384.log` | `/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-issues/agents/h3/runs/dma-16384/run.log` |
| `evidence/run-dma-16300.log` | `.../agents/h3/runs/dma-16300/run.log` |
| `evidence/run-dma-16384-fix.log` | `.../agents/h3/runs/dma-16384-fix/run.log` (build `agents/h3/lcls2-fix`, commit `2b4586066`) |
| `evidence/code-excerpt.txt` | `.../agents/h3/runs/gh/dma-code-excerpt.txt` (`evidence/excerpt.sh` on sdfiana025) |
