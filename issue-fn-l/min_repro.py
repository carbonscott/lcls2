import os, tempfile
from psana import DataSource

src = "/sdf/data/lcls/ds/prj/public01/xtc/tmoacr019-r0004-s000-c000.xtc2"
d = os.path.join(tempfile.mkdtemp(), "d" * 150)
os.makedirs(d)
path = os.path.join(d, os.path.basename(src))
os.symlink(src, path)
print(len(path), "chars, exists:", os.path.exists(path))
ds = DataSource(files=path)
