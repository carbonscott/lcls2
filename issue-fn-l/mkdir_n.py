"""python mkdir_n.py <root> <n>: mirror tmoacr019 r4 into a dir whose bigdata paths are n chars; print the dir."""
import os, sys, glob
XTC = "/sdf/data/lcls/ds/prj/public01/xtc"
root, n = sys.argv[1], int(sys.argv[2])
d = os.path.join(root, "d" * (n - len(root) - 2 - len("tmoacr019-r0004-s000-c000.xtc2")))
os.makedirs(os.path.join(d, "smalldata"), exist_ok=True)
for f in glob.glob(f"{XTC}/tmoacr019-r0004-*") + glob.glob(f"{XTC}/smalldata/tmoacr019-r0004-*"):
    if not os.path.lexists(f.replace(XTC, d)): os.symlink(f, f.replace(XTC, d))
print(d)
