#!/usr/bin/env python3
"""Differential test: the Lean model (xtcdiff) against the real xtcdata code (oracle).

    run.py --seeds 1 2 3 --n 60000 [--valgrind] [--out DIR]

For each seed: generate cases, run the model on all of them, run the oracle on
every case the model does not class as undefined behaviour (OOB, UNINIT, PTROVF), and
compare line by line.  Exit status 0 only if no case disagrees and every op has
at least --min agreeing cases over all seeds (ops listed in full are exempt).

--valgrind adds two checks of the model's memory claims on the first seed:
  clean: the oracle under valgrind reports 0 errors on the iterate/fileiter
         cases the model calls defined (left out: runs ending "end:err", where
         read() is asked for 2^63 bytes or more and refuses);
  ub:    a sample of the cases the model calls OOB/UNINIT, one valgrind run
         each, on the -O0 build of the oracle (gcc -O1 narrows some reads);
         reports how many valgrind flags.  For iterate, a read within 16 bytes
         of the block (valgrind's red zone) must be flagged.
"""
import argparse
import collections
import concurrent.futures
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EXHAUSTIVE = {"typeid_name", "trname", "levelname", "damage_get"}


TIMEOUT = 1800


def run(cmd, text):
    try:
        p = subprocess.run(cmd, input=text.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        print("TIMEOUT: %s did not finish in %d s" % (os.path.basename(cmd[0]), TIMEOUT), flush=True)
        print("RESULT: FAIL")
        os._exit(3)
    lines = [l for l in p.stdout.decode(errors="replace").split("\n") if l and not l.startswith("***")]
    return p.returncode, lines, p.stderr.decode(errors="replace")


def is_ub(res):
    return res.startswith("OOB") or res in ("UNINIT", "PTROVF")


def vg_one(oracle, case):
    p = subprocess.run(["valgrind", "-q", "--error-exitcode=9", oracle], input=(case + "\n").encode(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p.returncode == 9


def stale(model):
    """Model sources newer than the executable."""
    lean = os.path.realpath(os.path.join(HERE, "..", "lean"))
    if not os.path.realpath(model).startswith(lean + os.sep):
        return []          # a model built elsewhere (mutate.py)
    t = os.path.getmtime(model)
    src = [os.path.join(lean, "DiffMain.lean")] + [os.path.join(lean, "XtcLean", f) for f in ("Basic.lean", "Xtc.lean", "FileIter.lean")]
    return [s for s in src if os.path.exists(s) and os.path.getmtime(s) > t]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--n", type=int, default=60000)
    ap.add_argument("--min", type=int, default=50000)
    ap.add_argument("--ops", default="")
    ap.add_argument("--oracle", default=os.path.join(HERE, "build", "oracle"))
    ap.add_argument("--model", default=os.path.join(HERE, "..", "lean", ".lake", "build", "bin", "xtcdiff"))
    ap.add_argument("--valgrind", action="store_true")
    ap.add_argument("--ub-sample", type=int, default=2000)
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--out", default="")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds allowed for one model or oracle batch")
    a = ap.parse_args()
    global TIMEOUT
    TIMEOUT = a.timeout

    if stale(a.model):
        sys.exit("model executable is older than its sources (run lake build): %s" % stale(a.model))
    agree = collections.Counter()
    ub = collections.Counter()
    kern = collections.Counter()
    disagree = []
    vg = {}
    for seed in a.seeds:
        gen = [sys.executable, os.path.join(HERE, "gen.py"), "--seed", str(seed), "--n", str(a.n)]
        if a.ops:
            gen += ["--ops", a.ops]
        cases = subprocess.run(gen, stdout=subprocess.PIPE, check=True).stdout.decode().split("\n")
        cases = [c for c in cases if c]
        rc, model, err = run([a.model], "\n".join(cases) + "\n")
        if rc != 0 or len(model) != len(cases):
            sys.exit("model failed: rc=%d, %d results for %d cases\n%s" % (rc, len(model), len(cases), err[-2000:]))
        defined = [(c, m) for c, m in zip(cases, model) if not is_ub(m)]
        undefined = [(c, m) for c, m in zip(cases, model) if is_ub(m)]
        for c, m in undefined:
            ub[c.split(" ")[0]] += 1
        rc, oracle, err = run([a.oracle], "\n".join(c for c, _ in defined) + "\n")
        if rc != 0 or len(oracle) != len(defined):
            sys.exit("oracle failed: rc=%d, %d results for %d cases\n%s" % (rc, len(oracle), len(defined), err[-2000:]))
        for (c, m), o in zip(defined, oracle):
            op = c.split(" ")[0]
            if m.endswith(" end:err"):
                kern[op] += 1
            if m == o:
                agree[op] += 1
            else:
                disagree.append({"seed": seed, "case": c, "model": m, "oracle": o})
        print("seed %d: %d cases, %d compared, %d undefined, %d disagree so far"
              % (seed, len(cases), len(defined), len(undefined), len(disagree)), flush=True)

        if a.valgrind and seed == a.seeds[0]:
            mem = [c for c, m in defined if c.split(" ")[0] in ("iterate", "fileiter") and not m.endswith(" end:err")]
            t = time.time()
            p = subprocess.run(["valgrind", "-q", "--error-exitcode=9", a.oracle],
                               input=("\n".join(mem) + "\n").encode(), stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
            vg["clean_cases"] = len(mem)
            vg["clean_exit"] = p.returncode
            vg["clean_stderr_head"] = p.stderr.decode(errors="replace")[:1500]
            print("valgrind clean: %d defined memory cases, exit %d (%.0f s)"
                  % (len(mem), p.returncode, time.time() - t), flush=True)
            flagged = collections.Counter()
            total = collections.Counter()
            near_missed = []
            memub = [(c, m) for c, m in undefined if m != "PTROVF"]
            step = max(1, len(memub) // a.ub_sample)
            sample = memub[::step][:a.ub_sample]
            with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
                o0 = a.oracle + "_O0" if os.path.exists(a.oracle + "_O0") else a.oracle
                hits = list(ex.map(lambda cm: vg_one(o0, cm[0]), sample))
            for (c, m), hit in zip(sample, hits):
                f = c.split(" ")
                kind = f[0] + ":" + m.split(" ")[0]
                total[kind] += 1
                flagged[kind] += hit
                if f[0] == "iterate" and not hit:
                    size = 0 if f[1] == "-" else len(f[1]) // 2
                    if int(m.split(" ")[1]) + 8 < max(size, 1) + 16:
                        near_missed.append(c)
            vg["ub_sample"] = {k: [flagged[k], total[k]] for k in total}
            vg["ub_near_missed"] = near_missed[:5]
            print("valgrind ub sample (flagged/total):", vg["ub_sample"],
                  "near reads not flagged:", len(near_missed), flush=True)

    ops = sorted(set(agree) | set(ub))
    print("\n%-18s %9s %9s %9s" % ("op", "agree", "undefined", "kern"))
    short = []
    for op in ops:
        note = ""
        if op in EXHAUSTIVE:
            note = "  (whole input space)"
        elif agree[op] < a.min:
            note = "  < %d" % a.min
            short.append(op)
        print("%-18s %9d %9d %9d%s" % (op, agree[op], ub[op], kern[op], note))
    print("\ndisagreements: %d" % len(disagree))
    for d in disagree[:10]:
        print("  ", json.dumps(d)[:600])
    ok = not disagree and not short
    if a.valgrind:
        ok = ok and vg.get("clean_exit") == 0 and not vg.get("ub_near_missed")
    summary = {"seeds": a.seeds, "n": a.n, "agree": agree, "undefined": ub, "kern": kern,
               "disagreements": disagree[:50], "n_disagree": len(disagree), "valgrind": vg, "pass": ok}
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "summary.json"), "w") as f:
            json.dump(summary, f, indent=1)
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
