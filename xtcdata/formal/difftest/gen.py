#!/usr/bin/env python3
"""Case generator for the XTC2 differential test.

    gen.py --seed 1 --n 60000 [--ops iterate,fileiter,...] > cases.txt

Each line is one case in the format difftest/oracle.cc and lean/DiffMain.lean
read.  Values are biased to the edges of the C++ integer widths and masks.
Enum arguments stay inside the range of their C++ enumeration.  Ops whose
whole input space is smaller than --n are listed in full instead.
"""
import argparse
import random
import struct

E32 = [0, 1, 2, 3, 4, 5, 7, 8, 11, 12, 13, 15, 16, 23, 24, 25, 0xff, 0x100, 0xfff, 0x1000,
       0xffff, 0x10000, 0xffffff, 0x1000000, (1 << 28) - 1, 1 << 28, (1 << 31) - 1, 1 << 31,
       (1 << 31) + 11, (1 << 31) + 12, (1 << 31) + 13, (1 << 32) - 25, (1 << 32) - 24,
       (1 << 32) - 13, (1 << 32) - 12, (1 << 32) - 1]
NS = 1000000000
E64 = E32 + [1 << 32, (1 << 32) + 1, NS - 1, NS, NS + 1, (1 << 32) * NS - 1, (1 << 32) * NS,
             (1 << 32) * NS + 1, (1 << 63) - 1, 1 << 63, (1 << 64) - 12, (1 << 64) - 1]


def rnd(r, bits, edges):
    k = r.random()
    mask = (1 << bits) - 1
    if k < 0.30:
        return r.choice(edges) & mask
    if k < 0.45:
        return (r.choice(edges) + r.randint(-2, 2)) & mask
    if k < 0.60:
        return r.randrange(0, 64)
    if k < 0.70:
        return 1 << r.randrange(bits)
    return r.getrandbits(bits)


def r16(r): return rnd(r, 16, E32)
def r32(r): return rnd(r, 32, E32)
def r64(r): return rnd(r, 64, E64)


NAMES = ["Parent", "ShapesData", "Shapes", "Data", "Names"]
ALPHA = "PSDNarentShapesDataNames_v0123456789+-x"


def typeid_str(r):
    k = r.random()
    if k < 0.08:
        s = r.choice(NAMES) + "_v" + r.choice(["~s1", "~t1", "~n+1", "~s~s12", "~s1~s", "-~s1", "~s", "1~s", "~s-7"])
    elif k < 0.35:
        s = r.choice(NAMES) + "_v" + str(r.choice([0, 1, 2, 3, 9, 15, 16, 255, 65535, 65536, 10**25]))
    elif k < 0.6:
        s = r.choice(NAMES + ["names", "Name", "", "Parent_", "Data_v1"]) + \
            r.choice(["_v", "_V", "_", "v", "__v", "_vv", "_v_v"]) + \
            r.choice(["", "1", "+1", "-1", "12x", "x12", "+", "-", "++1", "1_", "0x10", "1.0"])
    else:
        s = "".join(r.choice(ALPHA) for _ in range(r.randrange(1, 14)))
    return s if s else "_"


def xtc(src, dmg, contains, extent):
    return struct.pack("<IHHI", src & 0xffffffff, dmg & 0xffff, contains & 0xffff, extent & 0xffffffff)


def tree(r, depth, exts):
    """A well-formed Xtc and the positions of its extent fields.  `exts` is the
    maximum nesting depth (None = 4)."""
    dmg = 0 if r.random() < 0.85 else r16(r)
    ver = r.choice([0, 0, 0, 1, 2, 15]) << 12
    deep = exts is not None and exts > 4
    parent = depth < (exts or 4) and r.random() < (0.9 if depth == 0 else 0.85 if deep else 0.4)
    if parent:
        kids = [tree(r, depth + 1, exts) for _ in range(r.randrange(1, 3) if deep else r.randrange(0, 5))]
        body = b"".join(k[0] for k in kids)
        contains = ver
    else:
        kids = []
        body = bytes(r.getrandbits(8) for _ in range(r.choice([0, 0, 1, 2, 4, 8, 12, 13, 16, 24])))
        contains = ver | r.choice([1, 2, 3, 4, 4, 5, 0x7ff, 0xfff])
    data = xtc(r.getrandbits(32), dmg, contains, 12 + len(body)) + body
    # extent offsets relative to this node
    offs = [8]
    pos = 12
    for k in kids:
        offs += [pos + o for o in k[1]]
        pos += len(k[0])
    return data, offs


EXT_EDGES = [0, 1, 11, 12, 13, 16, 24, 28, 1 << 31, (1 << 31) + 12, (1 << 32) - 12, (1 << 32) - 4,
             (1 << 32) - 1]


def mutate(r, data, offs):
    data = bytearray(data)
    k = r.random()
    offs = [o for o in offs if o + 4 <= len(data)]
    if k < 0.45 and offs:
        o = r.choice(offs)
        old = struct.unpack_from("<I", data, o)[0]
        new = r.choice(EXT_EDGES + [old + d for d in (-13, -12, -4, -1, 1, 4, 12, 13, 24)])
        struct.pack_into("<I", data, o, new & 0xffffffff)
    elif k < 0.60:
        del data[r.randrange(0, len(data) + 1):]
    elif k < 0.75:
        data += bytes(r.getrandbits(8) for _ in range(r.randrange(1, 30)))
    elif k < 0.90 and data:
        data[r.randrange(len(data))] = r.getrandbits(8)
    else:
        data += bytes(r.randrange(1, 30))
    return bytes(data)


def iterate(r):
    data, offs = tree(r, 0, r.choice([None] * 9 + [14]))
    if r.random() < 0.03:
        # a root cut inside its header, often marked Corrupted
        data = xtc(r.getrandbits(32), r.choice([0, 8, 8, 0xffff, r.getrandbits(16)]), 0, r.choice([0, 8, 12, 28]))
        data = data[:r.randrange(0, 12)]
        offs = []
    n = r.choice([0, 0, 0, 1, 1, 2, 3])
    for _ in range(n):
        data = mutate(r, data, offs)
    size = len(data)
    k = r.random()
    if k < 0.2:
        end = "none"
    elif k < 0.6:
        end = size
    elif k < 0.8:
        end = max(0, size - r.randrange(1, 14))
    elif k < 0.95:
        end = r.randrange(0, size + 1)
    else:
        end = size + r.randrange(1, 14)
    stop = 0 if r.random() < 0.8 else r.randrange(1, 7)
    return "iterate %s %s %d" % (data.hex() or "-", end, stop)


def fileiter(r):
    out = b""
    offs = []
    for _ in range(r.randrange(0, 5)):
        pay = r.choice([0, 0, 0, 4, 8, 12, 16, 40])
        offs.append(len(out) + 20)
        out += struct.pack("<QI", r.getrandbits(64), r.getrandbits(32)) + \
            xtc(r.getrandbits(32), 0, r.getrandbits(16), 12 + pay) + bytes(r.getrandbits(8) for _ in range(pay))
    out = bytearray(out)
    k = r.random()
    if k < 0.25 and offs:
        struct.pack_into("<I", out, r.choice(offs), r.choice(EXT_EDGES + [20, 36, 52, 1000]))
    elif k < 0.45:
        del out[r.randrange(0, len(out) + 1):]
    elif k < 0.65:
        out += bytes(r.getrandbits(8) for _ in range(r.randrange(1, 30)))
    elif k < 0.75:
        out += bytes(r.randrange(1, 30))
    mx = r.choice([0, 12, 23, 24, 24, 25, 35, 36, 40, 48, 64, 64, 64, 64, 128, 4096, 4096, 4096, 1 << 20])
    return "fileiter %s %d %d" % (bytes(out).hex() or "-", mx, r.randrange(1, 7))


def alloc(r):
    ext = r32(r)
    size = rnd(r, 40, E32)
    if r.random() < 0.15:
        # sizes as produced by alloc(other.sizeofPayload(), end) with a bad extent
        size = r.choice([r64(r), (1 << 64) - r.randrange(1, 40), (1 << 47) - 1, 1 << 47])
    k = r.random()
    if k < 0.25:
        end = "none"
    elif k < 0.8:
        end = max(0, ext + size + r.choice([-13, -12, -1, 0, 0, 0, 1, 12]))
    else:
        end = rnd(r, 41, E32)
    return "alloc %d %d %s" % (ext, size, end)


def ts_cmp(r):
    a = r64(r)
    k = r.random()
    if k < 0.2:
        c = a
    elif k < 0.5:
        c = (a & ~0xffffffff) | r.getrandbits(32)
    elif k < 0.7:
        c = (a & 0xffffffff) | (r.getrandbits(32) << 32)
    else:
        c = r64(r)
    return "ts_cmp %d %d" % (a, c)


RANDOM_OPS = {
    "typeid_ctor": lambda r: "typeid_ctor %d %d" % (r.randrange(8), r32(r)),
    "typeid_str": lambda r: "typeid_str " + typeid_str(r),
    "damage_inc_value": lambda r: "damage_inc_value %d %d" % (r16(r), r.randrange(16)),
    "damage_inc_u16": lambda r: "damage_inc_u16 %d %d" % (r16(r), r16(r)),
    "damage_setuser": lambda r: "damage_setuser %d %d" % (r16(r), r16(r)),
    "src_ctor": lambda r: "src_ctor %d %d" % (r32(r), r.randrange(4)),
    "namesid": lambda r: "namesid %d %d" % (
        r.choice([r.randrange(0x1002), r.randrange(0x1002), r32(r)]),
        r.choice([r.randrange(0x102), r.randrange(0x102), r32(r)])),
    "ts_u64": lambda r: "ts_u64 %d" % r64(r),
    "ts_secnsec": lambda r: "ts_secnsec %d %d" % (r32(r), r32(r)),
    "ts_from_ns": lambda r: "ts_from_ns %d" % r64(r),
    "ts_cmp": ts_cmp,
    "transition": lambda r: "transition %d %d %d" % (r.randrange(4), r.randrange(16), r32(r)),
    "env": lambda r: "env %d" % r32(r),
    "sizeof_payload": lambda r: "sizeof_payload %d" % r32(r),
    "alloc": alloc,
    "iterate": iterate,
    "fileiter": fileiter,
}

# ops whose whole input space is small: listed in full once
EXHAUSTIVE_OPS = {
    "typeid_name": ["typeid_name %d" % t for t in range(8)],
    "trname": ["trname %d" % t for t in range(16)],
    "levelname": ["levelname %d" % t for t in range(4)],
    "damage_get": ["damage_get %d" % d for d in range(1 << 16)],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n", type=int, default=60000)
    ap.add_argument("--ops", default="")
    a = ap.parse_args()
    ops = a.ops.split(",") if a.ops else list(RANDOM_OPS) + list(EXHAUSTIVE_OPS)
    for op in ops:
        if op in EXHAUSTIVE_OPS:
            for line in EXHAUSTIVE_OPS[op]:
                print(line)
            continue
        r = random.Random("%s/%d" % (op, a.seed))
        for _ in range(a.n):
            print(RANDOM_OPS[op](r))


if __name__ == "__main__":
    main()
