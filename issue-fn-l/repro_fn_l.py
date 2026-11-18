"""psana2 truncates xtc2 paths longer than dgrammanager.FN_L (200) characters.

Symlinks a small public run (tmoacr019 r4) at chosen path lengths and reads it.
usage: python repro_fn_l.py [--patch]     (--patch sets FN_L = 4096 first)
"""
import os, sys, glob, tempfile
import psana, psana.dgrammanager as dgm
from psana import DataSource

if "--patch" in sys.argv:
    dgm.FN_L = 4096
XTC = "/sdf/data/lcls/ds/prj/public01/xtc"
EXP, RUN = "tmoacr019", 4
S000 = f"{EXP}-r{RUN:04d}-s000-c000.xtc2"
ROOT = tempfile.mkdtemp(prefix="fnl-")
print(f"psana {os.path.dirname(psana.__file__)}  FN_L={dgm.FN_L}")


def mirror(n):
    """Symlink the run into a dir whose bigdata paths are n characters long."""
    d = os.path.join(ROOT, "d" * (n - len(ROOT) - 2 - len(S000)))
    os.makedirs(os.path.join(d, "smalldata"))
    for f in glob.glob(f"{XTC}/{EXP}-r{RUN:04d}-*") + glob.glob(f"{XTC}/smalldata/{EXP}-r{RUN:04d}-*"):
        os.symlink(f, f.replace(XTC, d))
    return d


def count(**kw):
    try:
        ds = DataSource(**kw)
        return f"OK   {sum(1 for r in ds.runs() for _ in r.events())} events"
    except BaseException as e:  # psana calls sys.exit(1) on FileNotFoundError in serial mode
        msg = f"FAIL {type(e).__name__}: {e}"
        c = e if isinstance(e, OSError) else e.__context__
        if isinstance(c, OSError):
            msg += f"\n{'':32}{'(while handling ' if c is not e else '('}{type(c).__name__}: "
            msg += f"psana opened a {len(c.filename)}-char path ending '...{c.filename[-14:]}')"
        return msg


for d in [XTC] + [mirror(n) for n in (199, 200, 201, 260)]:
    smd = f"{d}/smalldata/{S000.replace('.xtc2', '.smd.xtc2')}"
    print(f"\nbigdata path {len(d + '/' + S000)} chars, smalldata path {len(smd)} chars")
    print(f"  files=<s000 bigdata file>     {count(files=f'{d}/{S000}')}")
    print(f"  exp, run, dir, max_events=20  {count(exp=EXP, run=RUN, dir=d, max_events=20)}")
