"""daq_sim coverage: is every part of the DAQ proven to run with no hardware, at this commit?

    python -m psdaq.sim.coverage [--repo DIR] [--status FILE] [--evidence DIR] [-v] [--json]
    daq_sim coverage             (the same options)

Rows are enumerated from the source of the checkout the tool runs in, never from a list:
  det:drp:<type>, det:drp_gpu:<type>  one per register_type("<type>") call in
                                      psdaq/drp/PGPDetectorApp.cc, psdaq/drpGpu/PGPDetectorApp.cc
  prog:<program>                      one per distinct program a procmgr config in
                                      psdaq/psdaq/cnf starts (see config_programs)

coverage_status.json (next to this file) gives each row a status:
  RUN       it ran in a hardware-free run
  STAND-IN  a simulated program ('stand_in') serving the same 'interface' ran in its place
  N/A       a hardware diagnostic or firmware tool with no role in a run ('reason', one line)
A row with no entry is UNPROVEN.  An entry for a row the enumeration does not find is an error.

Every RUN and STAND-IN row needs an evidence record: a JSON file in the evidence dir
($DAQ_SIM_EVIDENCE, else <repo>/.daq_sim/evidence), written by record_evidence() when a run
passes.  A record counts only if its sha is this checkout's HEAD, it was made with no
tracked file modified (only the commit's own code counts), it names the run (run_id), and
every file it lists exists, is non-empty and still holds the bytes the record hashed when it
was written (sha256 of the first 'bytes' bytes: a log may have grown since, an .xtc2 file
not); an .xtc2 file must also be a whole chain of xtc2 datagrams that starts with a
Configure (xtc2_content).  Then the record proves a row only if its files' content says so,
as the coverage tool reads them (xtc2_content, read_log):
  det:<drp>:<type>   a listed .xtc2 file whose Configure has a <type> detector (its detType
                     or detName), with >= 1000 L1Accepts that hold that detector's data, and
                     whose BeginRun runinfo is the record's run_id; and a listed log whose
                     '# CMDLINE:' runs <drp> with -D <type> and names that run
  prog:<program>     a listed log whose '# CMDLINE:' runs <program> (for a STAND-IN row, its
                     stand_in) and names the run, or, for a program whose log never names a
                     run, that log and a witness of the run (below)
A log names the run if it holds the path of a listed .xtc2 file of the run, that path relative
to the record's data_dir (control_gui logs control's fileReport, '/<instr>/<expt>/xtc/<file>',
which counts only when it resolves under data_dir to that very file), or that file's BeginRun
time (sec.nsec, as the TEB and simxpm log it).

A witness is a listed JSON log a check of the cycle wrote, {"witness": <kind>, "run_id",
"xtc2": [the run's files], ...}; it counts only with the record's run_id and one of the run's
listed .xtc2 files.  Rows that need one:
  prog:ami-*         always (AMI's logs never name a run): an 'ami_check' witness that PASSed,
                     with 'matches' [[timestamp, seq, pixel], ...], at least one, every timestamp
                     an L1Accept of the run's file; and 'served_by' [{pid, cmdline, ancestors}], the
                     processes that held AMI's ports during the check, one of them or of their
                     ancestors the row's program with the pid its log gives (procServ's 'The PID
                     of new child ... is: N', or daq_sim's '# PID: N')
  prog:<GUI or monitor>, STAND-IN prog:<PV server>
                     when its (or its stand-in's) log does not name the run: a 'gui_witness'
                     witness whose 'programs' (GUIs run offscreen against the run's partition,
                     psdaq.sim.gui_witness) or 'servers' (stand-ins whose PVs a client read) entry
                     for the program PASSed, ran within the run's L1Accepts ('start' and 'end',
                     EPICS-epoch seconds, between the file's first and last L1Accept) and read at
                     least one value under the witness's 'partition' prefix that changed (2 or
                     more distinct numbers); for procstat ('kind': 'procmgr'), its table instead
                     lists every process whose procmgr log ('# ID:') names the run, RUNNING; a
                     'servers' entry reads under its own 'prefix' (the stand-in's PVs) and must
                     give the row program's 'interfaces' entry: 'defined' (PV names its source
                     defines, > 0) and 'missing' (those the stand-in does not serve) empty; a
                     'programs' entry with 'stand_in' (R4, a GUI on a device stand-in: hsdpva on
                     simhsd, tprca on simtpr, dtica on simdti) instead shows, in one read
                     (gui_witness keeps a read per widget), 2 or more distinct values after the
                     widget's first text (which may be the text it was built with) of a PV under
                     a prefix the stand-in serves (the -P of the stand-in's own log, which the
                     record must list); for a TPR program ('kind': 'tpr', R8: tprtrig and
                     tpr_trigger on a simulated TPR card, tpr::Client with PSDAQ_SIM_TPR), 2 or
                     more reads of the card's registers within the run, each showing what the
                     program's own command line programs (tpr_expected; tpr_trigger's channel on
                     the partition's readout group), of the card its own log says it mapped; for
                     a BLD server on such a card ('kind': 'bld': lclsBldServer, its card's frames
                     from psdaq.sim.tprframes), that and BLD_MIN_PACKETS or more packets received
                     on the group and port its command line sends to (bld_expected), every one
                     timed within the run's L1Accepts, at the rate and with the words its source
                     sends for its -b type, from the pid its log gives (bld_problem); for a
                     program of the HPS BLD chain ('kind': 'hps', R9: hpsBldServer, its crate the
                     stand-in psdaq.sim.simhps, and hpsBldCopy), HPS_MIN_PACKETS or more packets on
                     the group and port bldcas serves for its output service (the command line of
                     a bldcas log in the record), every one sent from a socket of the process whose
                     pid its own log gives, each event's 'valid' word the FIELDMASK hpsBldServer
                     served; hpsBldServer's events at the pulse IDs simxpm gives their times, timed
                     within the run's L1Accepts, its packets' ID that mask, and every PV of its
                     source (PVCtrls) served, PAYLOAD's type ID the mask; hpsBldCopy's events
                     carrying the times of hpsBldServer's events, as its Client gives them
                     (hps_problem); for wave8pvs ('kind': 'pvs', R6b: in a site conda env of its own,
                     its board simulated in process), every PV its own log lists under its --base
                     served, its PVA server's port held by the pid its log gives, a simulated
                     device (--dev sim://), and one PV read back 2 or more distinct numbers, each
                     after the first one its board logged written to the PV's register
                     (pvs_problem)
Any other record is rejected for the row, and the row's line says why.

Output: every row on its own line, then 'N rows, R run, S stand-in, K N/A, U unproven, X
claimed without valid evidence', where R and S count only rows with valid evidence at HEAD,
then what the status file claims, then PASS (exit 0) if U == 0 and X == 0, else FAIL
(exit 1) and the failing rows.
"""

import argparse
import ast
import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import shlex
import socket
import struct
import subprocess
import sys
import time

DET_SOURCES = (('drp', 'psdaq/drp/PGPDetectorApp.cc'),
               ('drp_gpu', 'psdaq/drpGpu/PGPDetectorApp.cc'))
CNF_DIR = 'psdaq/psdaq/cnf'
# procmgr (.cnf) and daqmgr (.py) configs; the other files there (.txt .csv .json .db .sh) are data
CONFIG_SUFFIXES = ('.cnf', '.py')
STATUS_FILE = 'psdaq/psdaq/sim/coverage_status.json'
EVIDENCE_SUBDIR = os.path.join('.daq_sim', 'evidence')

STATUSES = ('RUN', 'STAND-IN', 'N/A')
REQUIRED = {'RUN': (), 'STAND-IN': ('interface', 'stand_in'), 'N/A': ('reason',)}
OPTIONAL = ('note',)
RECORD_KEYS = ('sha', 'rows', 'kind', 'files')       # an evidence record must have these
MIN_L1ACCEPTS = 1000                    # L1Accepts with the row's detector data a det row needs
# xtc2 datagram header (xtcdata/xtc/Dgram.hh, Xtc.hh): TimeStamp (8 B: nanoseconds, seconds),
# env (4 B), then the root Xtc: src (4 B), damage (2 B), contains (2 B, TypeId), extent (4 B,
# counts the Xtc header)
DGRAM = struct.Struct('<QI IHHI')
TRANSITION_SIZE = 12                    # TimeStamp + env: the bytes before the root Xtc
XTC = struct.Struct('<IHHI')
XTC_SIZE = XTC.size
CONFIGURE, BEGINRUN, L1ACCEPT, UNUSED_11 = 2, 4, 12, 11      # xtcdata/xtc/TransitionId.hh
PARENT, SHAPESDATA, SHAPES, DATA, NAMES = range(5)           # xtcdata/xtc/TypeId.hh
SRC_VALUE = 0x0fffffff                  # Src.hh: the NamesId, without the level bits
# xtcdata/xtc/ShapesData.hh: a Names Xtc holds a NameInfo (numArrays, detType, detName, detId,
# Alg (name, version), segment) and then one Name (Alg, name, type, rank) per item; a Shapes Xtc
# one uint32[MaxRank] per array item, in item order
NAMEINFO = struct.Struct('<I256s256s256s256sII')
NAME = struct.Struct('<256sI256sII')
SHAPE = struct.Struct('<5I')
CHARSTR = 10
# Name::DataType -> (element size, struct code for a scalar) (xtcdata/xtc/src/ShapesData.cc)
ELEMENT = [(1, 'B'), (2, 'H'), (4, 'I'), (8, 'Q'), (1, 'b'), (2, 'h'), (4, 'i'), (8, 'q'),
           (4, 'f'), (8, 'd'), (1, None), (4, 'i'), (4, 'i'), (2, 'e')]
READ_WHOLE = 1 << 20                    # a datagram up to this size is read in one call
HASH_CHUNK = 1 << 23


class CoverageError(Exception):
    pass


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


# --- the checkout -------------------------------------------------------------------------

def git(repo, *args):
    return subprocess.run(['git', '-C', repo] + list(args), capture_output=True, text=True,
                          check=True, timeout=120).stdout.strip()


def find_repo(path=None):
    """The checkout to check: `path`, else the one holding this file (also when it runs from
    <repo>/install), else the one holding the current directory."""
    starts = [path] if path else [os.path.dirname(os.path.abspath(__file__)), os.getcwd()]
    for start in starts:
        try:
            top = git(start, 'rev-parse', '--show-toplevel')
        except (subprocess.SubprocessError, OSError):
            continue
        if os.path.exists(os.path.join(top, DET_SOURCES[0][1])):
            return top
    raise CoverageError(f'no lcls2 git checkout at {" or ".join(starts)}')


def head(repo):
    return git(repo, 'rev-parse', 'HEAD')


def dirty(repo):
    """True if tracked files differ from HEAD."""
    return bool(git(repo, 'status', '--porcelain', '--untracked-files=no'))


# --- detector rows ------------------------------------------------------------------------

REGISTER = re.compile(r'\bregister_type\s*(?:<[^>]*>)?\s*\(\s*"([^"]+)"')
CPP_TOKENS = re.compile(r'"(?:\\.|[^"\\\n])*"|//[^\n]*|/\*.*?\*/', re.S)


def strip_cpp_comments(text):
    """Blank out // and /* */ comments (not inside strings), keeping line numbers."""
    def blank(m):
        s = m.group(0)
        return s if s.startswith('"') else re.sub(r'[^\n]', ' ', s)
    return CPP_TOKENS.sub(blank, text)


def detector_rows(repo):
    """{row id: where}, one row per register_type("<type>") call, in source order."""
    rows = {}
    for exe, rel in DET_SOURCES:
        with open(os.path.join(repo, rel)) as f:
            text = strip_cpp_comments(f.read())
        for m in REGISTER.finditer(text):
            line = text.count('\n', 0, m.start()) + 1
            rows.setdefault(f'det:{exe}:{m.group(1)}', f'registered at {rel}:{line}')
    return rows


# --- program rows: from a command string to the program it runs ---------------------------

ENV_ASSIGN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
PYTHON = re.compile(r'^python[0-9.]*$')
# Wrappers that run the command after them: {name: (options that take a separate value,
# positional words before the command)}.  Long options written --opt=value need no entry.
WRAPPERS = {
    'env':       ({'-u', '--unset', '-C', '--chdir'}, 0),
    'nice':      ({'-n', '--adjustment'}, 0),
    'nohup':     (set(), 0),
    'exec':      (set(), 0),
    'time':      (set(), 0),
    'stdbuf':    ({'-i', '-o', '-e'}, 0),
    'taskset':   (set(), 1),                     # [-c] <mask or cpu list>
    'chrt':      (set(), 1),                     # [-f|-r|...] <priority>
    'numactl':   ({'-C', '-N', '-m', '-i', '-p', '-P', '--physcpubind', '--cpunodebind',
                   '--membind', '--interleave', '--preferred'}, 0),
    'timeout':   ({'-k', '-s', '--kill-after', '--signal'}, 1),          # <duration>
    'procServ':  ({'-c', '-e', '-I', '-i', '-k', '-L', '-l', '-n', '-P', '-p', '-x'}, 1),  # <port>
    'launch_py': (set(), 0),                     # psdaq/psdaq/scripts/launch_py <script.py>
}
PYTHON_OPTS_WITH_VALUE = {'-W', '-X'}


def program_name(path):
    """The alias rule: a program is named by the file it runs, as a basename without a .py
    suffix, so '/reg/.../procstat.py' is procstat and 'launch_py .../partca.py' is partca."""
    name = os.path.basename(path)
    return name[:-3] if name.endswith('.py') else name


def resolve(cmd):
    """(program, its arguments) for a command string, or (None, []) if it names none.
    Skips VAR=value words and wrappers; 'python [-m] x' and 'bash -c "..."' run what they name."""
    try:
        words = shlex.split(cmd)
    except ValueError:
        words = cmd.split()
    i = 0
    while i < len(words):
        w, base = words[i], os.path.basename(words[i])
        if ENV_ASSIGN.match(w):
            i += 1
        elif base in WRAPPERS:
            takes_value, positional = WRAPPERS[base]
            i += 1
            while i < len(words) and words[i].startswith('-'):
                if base == 'procServ' and words[i] in ('-P', '--port'):
                    positional = 0                # the port came as an option
                i += 2 if words[i] in takes_value else 1
            i += positional
        elif base in ('bash', 'sh') and i + 2 < len(words) and words[i + 1] == '-c':
            return resolve(words[i + 2])
        elif PYTHON.match(base):
            i += 1
            while i < len(words) and words[i].startswith('-') and words[i] != '-m':
                i += 2 if words[i] in PYTHON_OPTS_WITH_VALUE else 1
            if i + 1 < len(words) and words[i] == '-m':
                return words[i + 1].split('.')[-1], words[i + 2:]
            if i < len(words):
                return program_name(words[i]), words[i + 1:]
            return None, []
        else:
            return program_name(w), words[i + 1:]
    return None, []


def detector_types(args):
    """The types a drp command line asks for with -D (comma-separated)."""
    out = []
    for k, a in enumerate(args):
        if a == '-D' and k + 1 < len(args):
            out += args[k + 1].split(',')
        elif a.startswith('-D') and len(a) > 2:
            out += a[2:].split(',')
    return [t for t in out if t]


# --- program rows: loading the configs ---------------------------------------------------

def procmgr_names(path, platform, testreldir, configdir):
    """The names procmgr defines before it execs a config (ProcMgr.py deduce_platform2 and
    ProcMgr.__init__).  CONDA_PREFIX is required there; a stand-in value is used if unset."""
    return {'platform': platform, 'procmgr_config': None, 'TESTRELDIR': testreldir,
            'CONDA_PREFIX': os.environ.get('CONDA_PREFIX', '/conda_prefix'), 'CONFIGDIR': configdir,
            'id': 'id', 'cmd': 'cmd', 'flags': 'flags', 'port': 'port', 'host': 'host',
            '__file__': path, 'rtprio': 'rtprio', 'env': 'env', 'evr': 'evr', 'conda': 'conda',
            'procmgr_macro': {}}


def exec_config(path, src):
    """Run a config as procmgr does: once with platform None to read the platform it sets
    (deduce_platform2), then with that platform (ProcMgr.__init__).  A config that sets none
    needs procmgr -p; 0 is used.  Returns the namespace; raises if the config does not load."""
    code = compile(src, path, 'exec')
    with contextlib.redirect_stdout(io.StringIO()):
        ns = procmgr_names(path, None, '', '')
        try:
            exec(code, {}, ns)
        except Exception:
            pass                              # procmgr then needs -p, as below
        p = ns.get('platform')
        platform = int(p) if isinstance(p, str) and p.isdigit() else 0
        ns = procmgr_names(path, repr(platform), None, os.path.dirname(os.path.abspath(path)))
        exec(code, {}, ns)
    return ns


def cmd_values(tree):
    """(line, expression) for the value of every 'cmd' key of a dict literal in a config."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Name) and k.id == 'cmd') or \
                   (isinstance(k, ast.Constant) and k.value == 'cmd'):
                    yield node.lineno, v


def known_prefix(expr, ns):
    """(text, complete): the start of the string an expression builds, as far as it is known
    from literals and string variables of the config's namespace."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value, True
    if isinstance(expr, ast.Name) and isinstance(ns.get(expr.id), str):
        return ns[expr.id], True
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        text, complete = known_prefix(expr.left, ns)
        if complete:
            more, complete = known_prefix(expr.right, ns)
            text += more
        return text, complete
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Mod):    # 'fmt %d' % x
        return known_prefix(expr.left, ns)[0], False
    if isinstance(expr, ast.JoinedStr):                                 # f'...'
        text = ''
        for part in expr.values:
            more, complete = known_prefix(part.value if isinstance(part, ast.FormattedValue) else part, ns)
            text += more
            if not complete:
                return text, False
        return text, True
    return '', False


def static_cmd(expr, ns):
    """The command of a cmd entry the exec pass may not have reached (a branch not taken):
    its value in the config's namespace, else its known prefix cut to whole words."""
    try:
        value = eval(compile(ast.Expression(expr), '<cmd>', 'eval'), {}, dict(ns))
        if isinstance(value, str):
            return value
    except Exception:
        pass
    text, complete = known_prefix(expr, ns)
    if not complete and text and not text[-1].isspace():
        text = ' '.join(text.split()[:-1])    # its last word may be cut off
    return text


def config_programs(path):
    """What one config starts: ({program: [detector types]} from the exec pass,
    {program: [lines]} for cmd entries only the AST pass finds, [problems])."""
    with open(path) as f:
        src = f.read()
    started, static, problems = {}, {}, []
    try:
        ns = exec_config(path, src)
    except Exception as e:
        return started, static, [f'{os.path.basename(path)} does not load as procmgr loads it: '
                                 f'{type(e).__name__}: {e}']
    config = ns.get('procmgr_config')
    if not isinstance(config, list):
        return started, static, [f'{os.path.basename(path)}: procmgr_config is not a list']
    cmds = set()
    for entry in config:
        if isinstance(entry, dict) and isinstance(entry.get('cmd'), str):
            cmds.add(entry['cmd'])
            name, args = resolve(entry['cmd'])
            if name is None:
                problems.append(f'{os.path.basename(path)}: no program in cmd {entry["cmd"]!r}')
                continue
            types = started.setdefault(name, [])
            types += [t for t in detector_types(args) if t not in types]
    for line, expr in cmd_values(ast.parse(src, path)):
        cmd = static_cmd(expr, ns)
        if cmd in cmds:
            continue
        name = resolve(cmd)[0] if cmd else None
        if name is None:
            problems.append(f'{os.path.basename(path)}:{line}: cannot tell the program of cmd '
                            f'{ast.unparse(expr)[:120]}')
        elif name not in started:
            static.setdefault(name, []).append(line)
    return started, static, problems


def config_files(repo):
    d = os.path.join(repo, CNF_DIR)
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.endswith(CONFIG_SUFFIXES) and os.path.isfile(os.path.join(d, f))]


def program_rows(repo):
    """({row id: where}, [problems]), one row per distinct program, sorted by name."""
    found, problems = {}, []
    for path in config_files(repo):
        cnf = os.path.basename(path)
        started, static, probs = config_programs(path)
        problems += probs
        for name in started:
            found.setdefault(name, {'started': [], 'static': []})['started'].append(cnf)
        for name, lines in static.items():
            found.setdefault(name, {'started': [], 'static': []})['static'] += \
                [f'{cnf}:{n}' for n in lines]
    rows = {}
    for name in sorted(found, key=str.lower):
        f = found[name]
        if f['started']:
            where = f'started by {len(f["started"])} config(s): {" ".join(f["started"][:6])}' + \
                    (' ...' if len(f['started']) > 6 else '')
        else:
            where = f'only in a branch not taken: {" ".join(f["static"][:6])}'
        rows[f'prog:{name}'] = where
    return rows, problems


def config_rows(path):
    """The rows one config's run covers: prog:<program> for every program it starts and
    det:<drp>:<type> for every -D type of a drp/drp_gpu; used by runners for their evidence."""
    started, _, problems = config_programs(path)
    if problems:
        raise CoverageError('; '.join(problems))
    rows = [f'prog:{name}' for name in started]
    for name, types in started.items():
        if name in ('drp', 'drp_gpu'):
            rows += [f'det:{name}:{t}' for t in types]
    return rows


def stand_in_rows(programs, repo=None, status_path=None):
    """The STAND-IN rows whose stand-in is one of `programs` (e.g. 'simxpm' -> prog:pyxpm)."""
    repo = repo or find_repo()
    with open(status_path or os.path.join(repo, STATUS_FILE)) as f:
        data = json.load(f)
    return [rid for rid, e in data.items() if isinstance(e, dict) and
            e.get('status') == 'STAND-IN' and e.get('stand_in') in set(programs)]


def enumerate_rows(repo):
    """({row id: where}, [problems]): detector rows, then program rows."""
    rows = detector_rows(repo)
    prog, problems = program_rows(repo)
    rows.update(prog)
    return rows, problems


# --- status file --------------------------------------------------------------------------

def load_status(path, rows):
    """({row id: entry}, [problems]); every problem fails the check."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return {}, [f'status file {path}: {e}']
    if not isinstance(data, dict):
        return {}, [f'status file {path}: not a JSON object keyed by row id']
    status, problems = {}, []
    for rid, e in data.items():
        if rid not in rows:
            problems.append(f'{rid}: in the status file, but the enumeration does not find it')
            continue
        if not isinstance(e, dict) or e.get('status') not in STATUSES:
            problems.append(f'{rid}: status must be one of {", ".join(STATUSES)}')
            continue
        need = REQUIRED[e['status']]
        missing = [k for k in need if not str(e.get(k) or '').strip()]
        extra = sorted(set(e) - {'status'} - set(need) - set(OPTIONAL))
        if missing:
            problems.append(f'{rid}: {e["status"]} needs {", ".join(missing)}')
        elif extra:
            problems.append(f'{rid}: unknown field(s) {", ".join(extra)}')
        elif '\n' in e.get('reason', ''):
            problems.append(f'{rid}: the N/A reason must be one line')
        else:
            status[rid] = e
    return status, problems


# --- evidence -----------------------------------------------------------------------------

def evidence_dir(path=None, repo=None):
    return path or os.environ.get('DAQ_SIM_EVIDENCE') or os.path.join(repo or find_repo(), EVIDENCE_SUBDIR)


def content_hash(path, size):
    """sha256 (hex) of the first `size` bytes of a file."""
    h, left = hashlib.sha256(), size
    with open(path, 'rb') as f:
        while left > 0:
            block = f.read(min(HASH_CHUNK, left))
            if not block:
                break
            h.update(block)
            left -= len(block)
    return h.hexdigest()


def record_evidence(rows, kind, files, run_id=None, counts=None, started=None, ended=None,
                    job_id=None, host=None, repo=None, evidence=None, cache=None, data_dir=None):
    """Write one evidence record, for a run that passed its own checks, saying it proved
    `rows` at this checkout's HEAD; return its path.  `files` are the run's outputs (xtc2
    files, logs); the record keeps each one's size and sha256 as they are now ('content'), so
    coverage can tell they are still the files the run left, and reads its rows' proof in them.
    `data_dir` is the run's data dir (the drp's -o), against which a log's relative xtc2 path
    resolves.  `cache` (a dict) keeps the hashes for a record_verdicts call on the same files."""
    repo = repo or find_repo()
    rows = [rows] if isinstance(rows, str) else list(rows)
    files = [os.path.abspath(f) for f in files]
    content = {}
    for f in files:
        if os.path.isfile(f):
            size = os.path.getsize(f)
            content[f] = {'bytes': size, 'sha256': _cached(cache, ('sha256', f, size),
                                                           lambda f=f, size=size: content_hash(f, size))}
    sha = head(repo)
    record = {'sha': sha, 'dirty': dirty(repo), 'rows': sorted(set(rows)), 'kind': kind,
              'run_id': run_id, 'job_id': job_id or os.environ.get('SLURM_JOB_ID'),
              'host': host or socket.gethostname(), 'files': files, 'content': content,
              'started': started, 'ended': ended or now(), 'counts': counts or {},
              'data_dir': os.path.abspath(data_dir) if data_dir else None}
    d = evidence_dir(evidence, repo)
    os.makedirs(d, exist_ok=True)
    rid = f'{time.strftime("%Y%m%dT%H%M%S")}-{re.sub(r"[^A-Za-z0-9_.-]", "_", kind)}-{sha[:9]}-{os.getpid()}'
    path, k = os.path.join(d, rid + '.json'), 1
    while os.path.exists(path):         # another record of this process in the same second
        k += 1
        path = os.path.join(d, f'{rid}-{k}.json')
    with open(path + '.tmp', 'w') as f:
        json.dump(record, f, indent=1, sort_keys=True)
    os.replace(path + '.tmp', path)
    return path


def load_evidence(d):
    """[(record id, record or None, problem)] for every *.json in the evidence dir, by id."""
    out = []
    names = sorted(os.listdir(d)) if os.path.isdir(d) else []
    for name in names:
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(d, name)) as f:
                rec = json.load(f)
        except (OSError, ValueError) as e:
            out.append((name[:-5], None, f'unreadable: {e}'))
            continue
        missing = [k for k in RECORD_KEYS if k not in rec] if isinstance(rec, dict) else RECORD_KEYS
        if missing or not isinstance(rec.get('rows'), list):
            out.append((name[:-5], None, f'not a record (missing {", ".join(missing) or "rows list"})'))
            continue
        out.append((name[:-5], rec, None))
    return out


# --- reading an xtc2 file -----------------------------------------------------------------

def _cstr(b):
    return b.split(b'\0', 1)[0].decode('ascii', 'replace')


def _xtcs(read, start, end, where, depth=0):
    """(offset, NamesId/src, type id, extent) of each Xtc in a Parent's payload [start, end),
    through nested Parents; read(offset, size) gives the bytes.  Raises ValueError if an Xtc
    does not fit in its parent."""
    off = start
    while off < end:
        hdr = read(off, XTC_SIZE)
        if len(hdr) < XTC_SIZE or off + XTC_SIZE > end:
            raise ValueError(f'{where}: Xtc header at byte {off} cut off')
        src, _, contains, extent = XTC.unpack(hdr)
        if extent < XTC_SIZE or off + extent > end:
            raise ValueError(f'{where}: Xtc at byte {off} has extent {extent}, beyond its parent')
        if contains & 0xfff == PARENT and depth < 8:
            yield from _xtcs(read, off + XTC_SIZE, off + extent, where, depth + 1)
        else:
            yield off, src & SRC_VALUE, contains & 0xfff, extent
        off += extent


def _names(buf, where):
    """(detType, detName, segment, alg), [(item, type, rank)] of a Names Xtc (its bytes)."""
    if len(buf) < XTC_SIZE + NAMEINFO.size:
        raise ValueError(f'{where}: Names Xtc of {len(buf)} B is shorter than a NameInfo')
    _, dettype, detname, _, alg, _, segment = NAMEINFO.unpack_from(buf, XTC_SIZE)
    body = buf[XTC_SIZE + NAMEINFO.size:]
    body = body[:len(body) // NAME.size * NAME.size]
    items = [(_cstr(name), typ, rank) for _, _, name, typ, rank in NAME.iter_unpack(body)]
    return (_cstr(dettype), _cstr(detname), segment, _cstr(alg)), items


def _values(read, off, extent, items, where):
    """{item: value} for the scalar and string items of the ShapesData Xtc at off (arrays of
    numbers are skipped), laid out as xtcdata's DescData lays them out."""
    shapes = data = None
    for o, _, typ, ext in _xtcs(read, off + XTC_SIZE, off + extent, where):
        if typ == SHAPES:
            shapes = read(o + XTC_SIZE, ext - XTC_SIZE)
        elif typ == DATA:
            data = read(o + XTC_SIZE, ext - XTC_SIZE)
    if data is None:
        raise ValueError(f'{where}: ShapesData at byte {off} holds no Data')
    out, pos, k = {}, 0, 0
    for name, typ, rank in items:
        if typ >= len(ELEMENT):
            raise ValueError(f'{where}: item {name} has unknown type {typ}')
        size, code = ELEMENT[typ]
        if rank:
            if shapes is None or len(shapes) < SHAPE.size * (k + 1):
                raise ValueError(f'{where}: no shape for item {name}')
            for dim in SHAPE.unpack_from(shapes, SHAPE.size * k)[:rank]:
                size *= dim
            k += 1
        raw = data[pos:pos + size]
        if len(raw) < size:
            raise ValueError(f'{where}: Data ends before item {name}')
        if typ == CHARSTR:
            out[name] = _cstr(raw)
        elif not rank:
            out[name] = struct.unpack('<' + code, raw)[0]
        pos += size
    return out


def xtc2_content(path):
    """Read an xtc2 file as psana2's reader walks it; returns (problem, content).

    problem says why it is not an xtc2 file, or is None: it must be a chain of whole datagrams,
    the first a Configure, each a known transition whose root Xtc is a Parent, the last ending
    exactly at the end of the file, and the Xtcs of the Configure, the BeginRun and every
    L1Accept must fit in their parents.  content (as far as the walk got):
      types      the detType and detName of every Names in the Configure
      run        '<experiment>/r<run number, 4 digits>' from the first BeginRun's runinfo
                 (as DrpBase::runInfoData writes it), or None
      beginrun   that BeginRun's time, 'sec.nsec' with 9 digits of ns, or None
      l1accepts  the number of L1Accepts
      l1_with    {detType or detName: L1Accepts holding a ShapesData of that detector}
      l1_stamps  the set of the L1Accepts' timestamps (sec << 32 | nsec, as psana2's
                 evt.timestamp), and l1_first, l1_last the smallest and largest, or None"""
    size = os.path.getsize(path)
    c = {'types': set(), 'run': None, 'beginrun': None, 'l1accepts': 0, 'l1_with': {},
         'l1_stamps': set(), 'l1_first': None, 'l1_last': None}
    dets, items = {}, {}                 # NamesId -> (detType, detName, segment, alg), its items
    off = n = 0
    with open(path, 'rb') as f:
        def read_file(p, k):
            f.seek(p)
            return f.read(k)
        try:
            while off < size:
                hdr = read_file(off, DGRAM.size)
                if len(hdr) < DGRAM.size:
                    return f'datagram {n} at byte {off}: header cut off at the end of the file', c
                stamp, env, _, _, contains, extent = DGRAM.unpack(hdr)
                service = (env >> 24) & 0xf
                if n == 0 and service != CONFIGURE:
                    return f'first datagram is transition {service}, not a Configure', c
                if service > L1ACCEPT or service == UNUSED_11:
                    return f'datagram {n} at byte {off}: no transition has id {service}', c
                if contains & 0xfff != PARENT:
                    return f'datagram {n} at byte {off}: root Xtc is TypeId {contains & 0xfff}, not Parent', c
                if extent < XTC_SIZE or off + TRANSITION_SIZE + extent > size:
                    return f'datagram {n} at byte {off}: extent {extent} does not fit the file ({size} B)', c
                where = f'datagram {n} at byte {off}'
                start, end = off + DGRAM.size, off + TRANSITION_SIZE + extent
                if service in (CONFIGURE, BEGINRUN, L1ACCEPT):
                    if service != L1ACCEPT or end - start <= READ_WHOLE:
                        buf = read_file(start, end - start)
                        read = lambda p, k, buf=buf, base=start: buf[p - base:p - base + k]
                    else:
                        read = read_file
                    xtcs = _xtcs(read, start, end, where)
                    if service == CONFIGURE:
                        for o, src, typ, ext in xtcs:
                            if typ == NAMES:
                                dets[src], items[src] = _names(read(o, ext), where)
                                c['types'].update(dets[src][:2])
                    elif service == BEGINRUN and c['beginrun'] is None:
                        c['beginrun'] = f'{stamp >> 32}.{stamp & 0xffffffff:09d}'
                        for o, src, typ, ext in xtcs:
                            detname, alg = dets.get(src, ('', '', 0, ''))[1::2]
                            if typ == SHAPESDATA and detname == alg == 'runinfo':
                                v = _values(read, o, ext, items[src], where)
                                if isinstance(v.get('expt'), str) and isinstance(v.get('runnum'), int):
                                    c['run'] = f'{v["expt"]}/r{v["runnum"]:04d}'
                    else:
                        c['l1accepts'] += 1
                        c['l1_stamps'].add(stamp)
                        c['l1_first'] = stamp if c['l1_first'] is None else min(c['l1_first'], stamp)
                        c['l1_last'] = stamp if c['l1_last'] is None else max(c['l1_last'], stamp)
                        held = set()
                        for o, src, typ, ext in xtcs:
                            if typ == SHAPESDATA and src in dets:
                                held.update(dets[src][:2])
                        for t in held:
                            c['l1_with'][t] = c['l1_with'].get(t, 0) + 1
                off = end
                n += 1
        except ValueError as e:
            return str(e), c
    return (None if n else 'no datagrams'), c


def xtc2_problem(path):
    """Why `path` is not an xtc2 file, or None (see xtc2_content)."""
    return xtc2_content(path)[0]


# --- what a record proves -----------------------------------------------------------------

CMDLINE = re.compile(r'^# CMDLINE:[ \t]*(.*?)[ \t]*$', re.M)


def log_program(text):
    """(program, its arguments) of a log's first '# CMDLINE:' line (procmgr writes one at the
    top of each process's log, daq_sim one for each service it starts), or (None, [])."""
    m = CMDLINE.search(text)
    return resolve(m.group(1)) if m else (None, [])


def names_file(text, path):
    """True if text holds path, or another spelling of it that resolves to the same file (a
    work dir given once through a symlinked dir and once not)."""
    if path in text:
        return True
    real = os.path.realpath(path)
    return any(os.path.realpath(m.group(0)) == real for m in
               re.finditer(r'[^\s\'"]*' + re.escape(os.path.basename(path)), text))


def names_relative(text, path, data_dir):
    """True if text holds `path` relative to data_dir ('/tst/tstx00001/xtc/<file>', as control's
    fileReport gives it), i.e. a spelling that, joined to data_dir, resolves to the same file,
    and path lies under data_dir."""
    if not data_dir:
        return False
    root, real = os.path.realpath(data_dir), os.path.realpath(path)
    if not real.startswith(root + os.sep):
        return False
    for m in re.finditer(r'[^\s\'"\\]*' + re.escape(os.path.basename(path)), text):
        if os.path.realpath(os.path.join(root, m.group(0).lstrip(os.sep))) == real:
            return True
    return False


# --- witnesses: what a check of the cycle saw, for a program whose own log never names a run

WITNESSES = ('ami_check', 'gui_witness')
AMI_PROGRAMS = ('ami-client', 'ami-global', 'ami-manager', 'ami-node', 'ami-worker')
EPICS_EPOCH = 631152000                 # 1990-01-01 in Unix seconds: timing timestamps count from it
CHILD_PID = re.compile(r'^(?:@@@ The PID of new child .* is:|# PID:)[ \t]*(\d+)[ \t\r]*$', re.M)    # procServ ends lines \r\n


def witness(text):
    """The witness a log holds ({'witness': kind, ...}), or None if it is not one."""
    try:
        w = json.loads(text)
    except ValueError:
        return None
    return w if isinstance(w, dict) and w.get('witness') in WITNESSES else None


def stamp_seconds(stamp):
    """A timing timestamp (sec << 32 | nsec) as EPICS-epoch seconds."""
    return (stamp >> 32) + (stamp & 0xffffffff) * 1e-9


def log_pid(text):
    """The pid of a log's program: the last 'The PID of new child ... is: N' line of a procmgr log
    (procServ writes it), or the '# PID: N' line daq_sim writes under a log's '# CMDLINE:'; None if
    it has neither."""
    pids = CHILD_PID.findall(text)
    return int(pids[-1]) if pids else None


def _witness_run(w, run_id, mine):
    """Why a witness is not of the record's run, or None; it must give the run_id and name one of
    the run's listed xtc2 files."""
    if w.get('run_id') != run_id:
        return f'names run {w.get("run_id")}, the record says {run_id}'
    real = {os.path.realpath(f) for f in mine}
    if not any(isinstance(f, str) and os.path.realpath(f) in real for f in w.get('xtc2') or []):
        return f'names no listed xtc2 file of run {run_id}'
    return None


def ami_witness_problem(prog, w, run_id, mine, runs, logs):
    """Why an ami_check witness does not prove prog:<prog> (an AMI program), or None (module doc)."""
    p = _witness_run(w, run_id, mine)
    if p:
        return p
    if w.get('pass') is not True:
        return f'says the check failed: {str(w.get("problems"))[:160]}'
    matches = w.get('matches')
    if not isinstance(matches, list) or not matches:
        return 'lists no per-event match of AMI with psana2 (matches)'
    stamps = set().union(*(runs[f]['l1_stamps'] for f in mine))
    for m in matches:
        if not (isinstance(m, list) and len(m) == 3 and all(isinstance(x, int) for x in m)):
            return f'match {str(m)[:60]} is not [timestamp, seq, pixel]'
        if m[0] not in stamps:
            return f'match timestamp {m[0]:#x} is no L1Accept of the run\'s files'
    served = [s for s in w.get('served_by') or [] if isinstance(s, dict)]
    procs = [p for s in served for p in [s] + [a for a in s.get('ancestors') or [] if isinstance(a, dict)]]
    pids = {p.get('pid') for p in procs if isinstance(p.get('cmdline'), str) and resolve(p['cmdline'])[0] == prog}
    if not pids:
        return (f'its served_by lists no {prog} process (it lists '
                f'{", ".join(sorted({str(resolve(str(p.get("cmdline")))[0]) for p in procs})) or "none"})')
    given = [log_pid(text) for text in logs]
    if not any(given):
        return f'its log of {prog} gives no pid (procServ\'s "The PID of new child ... is: N", or "# PID: N")'
    if not any(pid in pids for pid in given):
        return (f'its log of {prog} gives pid {", ".join(str(p) for p in given if p)}, not one of the '
                f'{prog} processes that served the check ({", ".join(str(p) for p in sorted(pids))})')
    return None


LOG_ID = re.compile(r'^# ID:[ \t]*(\S+)', re.M)        # procmgr heads each process's log with its id


def pv_prefixes(args):
    """The PV prefixes a stand-in's command line serves: the words after its -P, up to the next option."""
    out = []
    for k, a in enumerate(args):
        if a == '-P':
            for b in args[k + 1:]:
                if b.startswith('-'):
                    break
                out.append(b)
    return out


def live_witness_problem(prog, w, run_id, mine, runs, section, run_ids=(), row_prog=None, logs=()):
    """Why a gui_witness does not show prog read live values of the run (its 'programs' or, for a
    stand-in, 'servers' entry), or None (module doc).  run_ids: the procmgr ids of the record's
    logs that name the run, which a 'procmgr' entry (procstat's table) must show RUNNING.  A
    'servers' entry (a stand-in's PVs, read by a client of the cycle) reads under its own
    'prefix' and must hold the row program's interface: {'interfaces': {row_prog: {'defined': n,
    'missing': [...]}}}, the PV names the program's source defines, every one served.  A 'programs'
    entry with 'stand_in' (R4: a GUI on a device stand-in's PVs) must read a PV under a prefix the
    stand-in serves by the command line of its log in the record (logs: [((program, args), text)])."""
    p = _witness_run(w, run_id, mine)
    if p:
        return p
    e = (w.get(section) or {}).get(prog)
    if not isinstance(e, dict):
        return f'has no {section} entry for {prog}'
    if e.get('pass') is not True:
        return f'says {prog} failed: {str(e.get("problems"))[:160]}'
    first = [runs[f]['l1_first'] for f in mine if runs[f]['l1_first'] is not None]
    last = [runs[f]['l1_last'] for f in mine if runs[f]['l1_last'] is not None]
    start, end = e.get('start'), e.get('end')
    if not (first and isinstance(start, (int, float)) and isinstance(end, (int, float))):
        return f'gives no start and end of {prog}\'s reads, or the run has no L1Accept'
    lo, hi = stamp_seconds(min(first)), stamp_seconds(max(last))
    if not lo <= start <= end <= hi:
        return (f'{prog} read from {start:.3f} to {end:.3f}, not within the run\'s L1Accepts '
                f'({lo:.3f} to {hi:.3f}, EPICS-epoch seconds)')
    if e.get('kind') == 'slurm':                            # R5: a GUI that shows Slurm job states (daqstat)
        ok, why = slurm_matched(e, lo, hi)
        if len(ok) < 2:
            return (f'shows {prog} refreshed {len(ok)} time(s) during the run with what an independent squeue read '
                    f'gave (2 or more needed)' + (f': {why}' if why else ''))
        missing = sorted(set(run_ids) - {r[0] for f in ok for r in f['rows']})
        if missing:
            return f'shows {prog} listed no job of {", ".join(missing)} (processes whose logs name the run)'
        return None
    if e.get('kind') == 'tpr':                              # R8: a TPR program on a simulated TPR card
        return tpr_problem(prog, e, logs, w.get('partition'), lo, hi)
    if e.get('kind') == 'bld':                              # R8 + its packets: a BLD server on a simulated TPR card
        return tpr_problem(prog, e, logs, w.get('partition'), lo, hi) or bld_problem(prog, e, logs, lo, hi)
    if e.get('kind') == 'hps':                              # R9: the HPS BLD chain, hpsBldServer's crate a stand-in
        return hps_problem(prog, e, logs, lo, hi, w)
    if e.get('kind') == 'pvs':                              # R6b: wave8pvs in a site env, its board simulated
        return pvs_problem(prog, e, logs)
    if e.get('kind') == 'procmgr':
        if not run_ids:
            return 'the record lists no procmgr log (# ID:) that names the run, for its table to show'
        running = {str(r.get('name'))[len('procmgr:'):] for r in e.get('reads') or [] if isinstance(r, dict)
                   and str(r.get('name', '')).startswith('procmgr:') and isinstance(r.get('values'), list)
                   and r['values'][-1:] == ['RUNNING']}
        missing = sorted(set(run_ids) - running)
        if missing:
            return (f'shows {prog} did not list {", ".join(missing)} RUNNING (processes whose logs name the run)')
        return None
    if section == 'programs' and 'stand_in' in e:         # R4: a GUI on a device stand-in's PVs
        si = e.get('stand_in')
        if not (isinstance(si, str) and si):
            return f'its {prog} entry names no stand-in'
        ran = [args for (name, args), _ in logs if name == si]
        if not ran:
            return (f'its {prog} entry reads the PVs of {si}, but the record lists no log of {si} '
                    f'(a log whose "# CMDLINE:" runs {si})')
        served = sorted({p for args in ran for p in pv_prefixes(args)})
        if not served:
            return f'its log of {si} gives no PV prefix (-P) for {prog} to read under'
        live = [r for r in e.get('reads') or [] if isinstance(r, dict) and isinstance(r.get('values'), list)
                and any(str(r.get('name', '')).startswith(p + ':') for p in served) and len(changed_texts(r['values'])) >= 2]
        if not live:
            return (f'shows {prog} read no live value of a PV {si} serves (under {", ".join(served)}; '
                    f'2 or more distinct values in one read after its first text)')
        return None
    prefix = w.get('partition')
    if section == 'servers':
        prefix = e.get('prefix')
        itf = (e.get('interfaces') or {}).get(row_prog)
        if not isinstance(itf, dict):
            return f'its {prog} entry shows no interface of {row_prog} (PV names its source defines vs served)'
        if not (isinstance(itf.get('defined'), int) and itf['defined'] > 0):
            return f'its {prog} entry gives no PV name {row_prog}\'s source defines'
        if itf.get('missing') != []:
            missing = itf.get('missing') if isinstance(itf.get('missing'), list) else ['?']
            return (f'{prog} does not serve {len(missing)} of the {itf["defined"]} PVs {row_prog} defines, '
                    f'e.g. {", ".join(map(str, missing[:3]))}')
    if not (isinstance(prefix, str) and prefix):
        return 'gives no partition prefix' if section != 'servers' else f'its {prog} entry gives no prefix'
    if section == 'servers' and prog == row_prog:          # R3b: the program serves its PVs itself
        served = sorted({p for (name, args), _ in logs if name == prog for p in pv_prefixes(args)})
        if not any(prefix == p or prefix.startswith(p + ':') for p in served):
            return (f'its {prog} entry reads under {prefix}, which no listed log of {prog} serves '
                    f'(its -P: {", ".join(served) or "none"})')
    live = [r for r in e.get('reads') or [] if isinstance(r, dict) and str(r.get('name', '')).startswith(prefix)
            and isinstance(r.get('values'), list) and len(numbers(r['values'])) >= 2]
    if not live:
        return f'shows {prog} read no live value under {prefix} (2 or more distinct numbers of one name)'
    return None


TPR_CARD = re.compile(r'Tpr::Client: simulated TPR \(PSDAQ_SIM_TPR\): (\S+) is (\S+)')
# getopt strings of the TPR programs (psdaq/psdaq/app/tprtrig.cc, psdaq/drp/TprTrigger.cc), '?' left out
TPR_GETOPT = {'tprtrig': 'c:d:D:m:w:o:t:r:e:p:zC:L:M:P:h', 'tpr_trigger': 'p:C:u:k:H:c:d:D:w:o:t:K:L:M:P:hv',
              'lclsBldServer': 'a:d:b:e:i:p:r:vh'}
# lclsBldServer's BLD types (psdaq/psdaq/app/lclsBldServer.cc): -b name -> (group offset = bldInfo, typeId, payload
# words); its groups are <-a base, 239.255.25.0 by default> + offset on <-p port, 12148 by default>
BLD_TYPES = {'ebeam': (0, (7 << 16) | 15, 41), 'pcav': (1, 17, 8), 'gmd': (2, (2 << 16) | 64, 12),
             'xgmd': (3, 64, 12)}
BLD_DEFAULT_BASE, BLD_DEFAULT_PORT, BLD_MIN_PACKETS = 0xefff1900, 12148, 10


def _strtoul(text):
    """C's strtoul(text, NULL, 0) for a whole argument (0x hex, leading-0 octal, decimal; quotes procmgr's repr adds
    to -p dropped); None if it is not one."""
    t = str(text).strip().strip('\'"')
    try:
        return int(t, 16) if t.lower().startswith('0x') else int(t, 8) if len(t) > 1 and t.startswith('0') else int(t)
    except ValueError:
        return None


def tpr_expected(prog, args, group=None):
    """R8: what TPR program `prog` (tprtrig, tpr_trigger) with command line `args` writes to its TPR card's registers,
    as its source does through tpr::Client (TprBase::setupChannel and setupTrigger, psdaq/psdaq/tpr/Module.cc):
    ({'channel': i, 'control': c, 'evtSel': s or None}, [{'trigger': i, 'control', 'delay', 'width', 'delayTap'}]),
    tpr_trigger's channel on readout group `group` (control's, at Connect); None for an argv the program refuses."""
    import getopt
    if prog == 'lclsBldServer':         # Client(dev, 1, ...): setup(0, 0, 1), then start(FixedRate(-r) or EventCode(-e))
        b = bld_expected(args)
        if b is None:
            return None
        sel = (1 << 30) | (2 << 11) | (b['evcode'] & 0x3ff) if b['evcode'] is not None else (1 << 30) | b['rate']
        return ({'channel': 1, 'control': 7, 'evtSel': sel & 0xffffffff},
                [{'trigger': 0, 'control': 1 | (1 << 16) | (1 << 31), 'delay': 0, 'width': 1, 'delayTap': 0}])
    try:
        opts, rest = getopt.getopt(list(args), TPR_GETOPT[prog])
    except (getopt.GetoptError, KeyError):
        return None
    if rest:
        return None
    v = {'c': 10, 'o': 0, 'd': 0, 'w': 1, 'D': 0, 'P': 0}
    mode = rate = None
    for o, a in opts:
        o = o[1:]
        if o in v:
            v[o] = _strtoul(a)
        elif prog == 'tprtrig' and o in 'erp':
            if mode is not None:
                return None             # only one rate selection mode
            mode, rate = 'erp'.index(o), _strtoul(a)
    if None in v.values() or (mode is not None and rate is None):
        return None
    if prog == 'tpr_trigger':
        if group is None:
            return None
        mode, rate = 2, group
    m32 = 0xffffffff
    if mode is None:                    # tprtrig without -e/-r/-p: the channel is stopped, never started
        chan = {'channel': v['c'], 'control': 0, 'evtSel': None}
    else:
        sel = ((1 << 30) | (2 << 11) | (rate & 0x3ff), (1 << 30) | rate, (1 << 30) | (3 << 11) | (rate & 0xf))[mode]
        chan = {'channel': v['c'], 'control': 7, 'evtSel': sel & m32}
    trigs = [{'trigger': i, 'control': ((v['c'] & 0xffff) | ((1 << 16) if v['P'] else 0) | (1 << 31)) & m32,
              'delay': v['d'] & m32, 'width': v['w'] & m32, 'delayTap': v['D'] & m32}
             for i in range(32) if v['o'] >> i & 1]
    return chan, trigs


def bld_expected(args):
    """What lclsBldServer with command line `args` sends, as its source does: {'group' (dotted), 'port', 'type',
    'bldInfo', 'typeId', 'words' (payload words), 'rate' (FixedRate index, -r, 5 by default) or 'evcode' (-e)}; None
    for an argv it refuses (no -b of BLD_TYPES or no -i, a bad -a or -p, a word that is no option)."""
    import getopt
    import socket
    try:
        opts, rest = getopt.getopt(list(args), TPR_GETOPT['lclsBldServer'])
    except getopt.GetoptError:
        return None
    if rest:
        return None
    o = {k[1:]: a for k, a in opts}
    if o.get('b') not in BLD_TYPES or 'i' not in o:
        return None
    base, port = BLD_DEFAULT_BASE, BLD_DEFAULT_PORT
    if 'a' in o:
        try:
            base = struct.unpack('>I', socket.inet_aton(o['a'].strip('\'"')))[0]
        except OSError:
            return None
        if not base:
            return None
    if 'p' in o:
        port = _strtoul(o['p'])
        if not port or port > 0xffff:
            return None
    rate = _strtoul(o.get('r', '5'))
    evcode = _strtoul(o['e']) if 'e' in o else None
    if rate is None or ('e' in o and evcode is None):
        return None
    info, type_id, words = BLD_TYPES[o['b']]
    return {'group': socket.inet_ntoa(struct.pack('>I', (base + info) & 0xffffffff)), 'port': port, 'type': o['b'],
            'bldInfo': info, 'typeId': type_id, 'words': words, 'rate': rate, 'evcode': evcode}


def bld_problem(prog, e, logs, lo, hi):
    """Why a 'bld' witness entry does not show BLD server prog send what its command line says while the run ran
    (lo..hi, EPICS-epoch seconds), or None: BLD_MIN_PACKETS or more packets received on the group and port of its
    command line (bld_expected, from the log that names its card), each timed (sec.ns) within the run's L1Accepts and
    after the one before, at the fixed rate it selects (times on that marker, psdaq.sim.tprframes: every
    simxpm.FIXED_RATE_DIV[rate] pulses of 1300/1.4 MHz, and as many as its rate gives over the time received, half at
    least), each pulse ID the one simxpm's timing gives its time, each of the size and with the words its source sends
    for its type, the pid in them the one its log gives."""
    from psdaq.sim.simxpm import FIXED_RATE_DIV, TIMING_BASE_HZ
    mine = [(args, text) for (name, args), text in logs if name == prog and TPR_CARD.search(text)]
    b = bld_expected(mine[0][0]) if mine else None
    if b is None:
        return f'its log of {prog} gives a command line {prog} refuses: {mine[0][0] if mine else None}'
    if (e.get('group'), e.get('port')) != (b['group'], b['port']):
        return (f'received on {e.get("group")}:{e.get("port")}, but its command line sends to '
                f'{b["group"]}:{b["port"]}')
    pk = [p for p in e.get('packets') or [] if isinstance(p, list) and len(p) == 5 and
          all(isinstance(x, (int, float)) for x in p)]
    if len(pk) < BLD_MIN_PACKETS:
        return f'received {len(pk)} packet(s) of {prog} on {b["group"]}:{b["port"]} ({BLD_MIN_PACKETS} or more needed)'
    if b['evcode'] is not None or b['rate'] >= len(FIXED_RATE_DIV):
        return f'its command line selects {"event code " + str(b["evcode"]) if b["evcode"] is not None else "rate " + str(b["rate"])}, which no simulated card delivers'
    div = FIXED_RATE_DIV[b['rate']]
    last = None
    for t, sec, ns, pid, nbytes in pk:
        when = sec + ns * 1e-9
        if not lo <= when <= hi:
            return f'its packet of pulseId {pid:#x} is timed {when:.6f}, not within the run\'s L1Accepts ({lo:.3f} to {hi:.3f})'
        if last is not None and (pid, when) <= last:
            return f'its packet of pulseId {pid:#x} does not come after the one before ({last[0]:#x})'
        if ((sec * 10**9 + ns) * 13 // 14000) % div:     # the LCLS-II pulse of its time (psdaq.sim.tprframes)
            return (f'its packet of pulseId {pid:#x} is timed {sec}.{ns:09d}, not on fixed rate {b["rate"]}\'s marker '
                    f'(every {div} pulses of 1300/1.4 MHz)')
        if pid != ((sec * 14000000) // 13 + (ns * 14) // 13000) & ((1 << 56) - 1):
            return (f'its packet of pulseId {pid:#x} is timed {sec}.{ns:09d}, to which simxpm\'s timing gives '
                    f'another pulse ID')
        if nbytes != 96 + 4 * b['words']:
            return f'its packet of pulseId {pid:#x} has {nbytes} B, not the {96 + 4 * b["words"]} its -b {b["type"]} sends'
        last = (pid, when)
    span = pk[-1][0] - pk[0][0]
    want = int(0.5 * span * TIMING_BASE_HZ / div)
    if len(pk) < want:
        return (f'received {len(pk)} packets in {span:.1f} s, fewer than half the {2 * want} fixed rate {b["rate"]} '
                f'gives')
    pids = [log_pid(text) for _, text in mine]
    body = e.get('body')
    exp = None
    if isinstance(body, list) and len(body) == 11 + b['words']:
        src = body[2] if isinstance(body[2], int) else -1
        exp = [0, 0, src, b['bldInfo'], b['typeId'], 4 * b['words'] + 20,
               0, src, b['bldInfo'], b['typeId'], 4 * b['words'] + 20] + list(range(b['words']))
    if exp is None or body != exp or src >> 24 != 6:
        return f'its packets do not hold the words lclsBldServer sends for -b {b["type"]}: {str(body)[:120]}'
    if e.get('bodies') != len(e.get('packets') or []):
        return f'{len(e.get("packets") or []) - (e.get("bodies") or 0)} of its packets differ from the first after the pulse ID'
    if not any(p is not None and (p & 0xffffff) == (src & 0xffffff) for p in pids):
        return (f'its packets carry pid {src & 0xffffff}, but its log of {prog} gives pid '
                f'{", ".join(str(p) for p in pids if p is not None) or "none"}')
    return None


HPS_MIN_PACKETS = 10
HPS_PVS = ('HPS:FIELDNAMES', 'HPS:FIELDTYPES', 'HPS:FIELDMASK', 'PAYLOAD')     # pyhpsbld.PVCtrls.run, under -n


def _opt(args, flag):
    """The word after `flag` in args, or None."""
    args = list(args)
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None


def hps_registries(logs, name):
    """[(group, port)] the bldcas logs of the record (their command lines) serve for BLD service `name`
    (<prefix>:<service>): -A plus the service's place among its services, --port (11001 by default)."""
    import ipaddress
    prefix, _, service = name.rpartition(':')
    out = []
    for (prog, args), _text in logs:
        if prog != 'bldcas':
            continue
        args, rest, k = list(args), [], 0
        opts = {'-A': '239.255.128.1', '--port': '11001', '-P': None}
        while k < len(args):
            if args[k] in opts and k + 1 < len(args):
                opts[args[k]] = args[k + 1]
                k += 2
            elif args[k].startswith('-'):
                k += 1
            else:
                rest.append(args[k])
                k += 1
        if opts['-P'] == prefix and service in rest:
            try:
                out.append((str(ipaddress.ip_address(opts['-A']) + rest.index(service)), int(opts['--port'])))
            except ValueError:
                pass
    return out


def hps_problem(prog, e, logs, lo, hi, w=None):
    """R9: why an 'hps' witness entry does not show program prog of the HPS BLD chain send what its command line
    says while the run ran (lo..hi, EPICS-epoch seconds), or None (module doc).  w: the witness, whose hpsBldServer
    entry hpsBldCopy's events are checked against."""
    from psdaq.sim.tprframes import stamp_pid
    mine = [(args, text) for (name, args), text in logs if name == prog]
    if not mine:
        return f'lists no log of {prog}'
    args = mine[0][0]
    out = _opt(args, '-n' if prog == 'hpsBldServer' else '-O')
    wants = hps_registries(logs, out) if out else []
    if not wants:
        return f'lists no bldcas log that serves {prog}\'s output service {out}'
    want = (e.get('group'), e.get('port'))
    if want not in wants:
        return (f'received on {want[0]}:{want[1]}, but the bldcas logs of the record serve {out} on '
                f'{", ".join(f"{g}:{p}" for g, p in wants)}')
    pk = [p for p in e.get('packets') or [] if isinstance(p, list) and len(p) == 4 and isinstance(p[3], list)]
    if len(pk) < HPS_MIN_PACKETS:
        return f'received {len(pk)} packet(s) of {prog} on {want[0]}:{want[1]} ({HPS_MIN_PACKETS} or more needed)'
    if not isinstance(e.get('count'), int) or e['count'] < len(pk):
        return f'keeps {len(pk)} packets of {prog} but says it received {e.get("count")}'
    pids = {log_pid(text) for _, text in mine} - {None}
    owners = e.get('owners') if isinstance(e.get('owners'), dict) else {}
    for p in pk:
        held = owners.get(str(p[1]))
        if not (isinstance(held, list) and pids & set(held)):
            return (f'its packets come from port {p[1]}, held by pids {held}, not the pid its log of {prog} gives '
                    f'({", ".join(str(x) for x in sorted(pids)) or "none"})')
    mask = e.get('mask')
    if not isinstance(mask, int) or not mask & 0x7fffffff:
        return f'gives no channel mask of hpsBldServer\'s FIELDMASK ({mask!r})'
    nw = 1 + bin(mask).count('1')
    last = None
    for t, sport, ident, evs in pk:
        if not evs or not all(isinstance(v, list) and len(v) == 3 and isinstance(v[2], list) and len(v[2]) == nw
                              and v[2][0] == mask for v in evs):
            return f'its packet received at {t} holds events whose valid word is not the mask {mask:#x}: {str(evs)[:120]}'
        if prog == 'hpsBldServer':
            pid, ts = evs[0][0], evs[0][1]
            sec, ns = ts >> 32, ts & 0xffffffff
            when = sec + ns * 1e-9
            if not lo <= when <= hi:
                return f'its event of pulseId {pid:#x} is timed {when:.6f}, not within the run\'s L1Accepts ({lo:.3f} to {hi:.3f})'
            if ns >= 10**9 or pid != stamp_pid(sec, ns):
                return f'its event of pulseId {pid:#x} is timed {sec}.{ns:09d}, to which simxpm\'s timing gives another pulse ID'
            if ident != mask:
                return f'its packet of pulseId {pid:#x} has ID {ident:#x}, not the channel mask {mask:#x} of its payload'
            if any(not 0 <= v[0] - pid <= 0xfff for v in evs):
                return f'its packet of pulseId {pid:#x} holds an event more than 4095 pulses after it'
            if last is not None and pid <= last:
                return f'its packet of pulseId {pid:#x} does not come after the one before ({last:#x})'
            last = evs[-1][0]
    if prog == 'hpsBldServer':
        pvs = e.get('pvs') if isinstance(e.get('pvs'), dict) else {}
        missing = [n for n in HPS_PVS if not isinstance(pvs.get(f'{out}:{n}'), str) or pvs[f'{out}:{n}'].startswith('error')]
        if missing:
            return f'does not show {prog} serve {", ".join(missing)} under {out} (the PVs its source defines)'
        if pvs[f'{out}:HPS:FIELDMASK'].split()[-1:] != [str(mask)] or not \
                re.match(r'%da? ' % mask, pvs[f'{out}:PAYLOAD']):
            return (f'its FIELDMASK {pvs[f"{out}:HPS:FIELDMASK"][-20:]!r} or PAYLOAD type ID '
                    f'{pvs[f"{out}:PAYLOAD"][:20]!r} is not the mask {mask} of its packets')
        return None
    svc = (w or {}).get('programs', {}).get('hpsBldServer') if isinstance(w, dict) else None
    firsts = sorted({p[3][0][1] for p in (svc or {}).get('packets') or [] if isinstance(p, list) and len(p) == 4
                     and p[3] and isinstance(p[3][0], list) and isinstance(p[3][0][1], int)})
    if not firsts:
        return f'has no hpsBldServer entry whose events {prog}\'s carry'
    import bisect
    evs = [v for p in pk for v in p[3]]
    hit = 0
    for v in evs:
        k = bisect.bisect_right(firsts, v[0]) - 1
        hit += k >= 0 and v[0] - firsts[k] <= 0xfff
    if 2 * hit < len(evs) or not hit:
        return (f'{len(evs) - hit} of its {len(evs)} events do not carry the time of an event hpsBldServer sent '
                f'(hpsBldCopy publishes its Client\'s pulseId, the time of hpsBldServer\'s event)')
    for v in evs:
        when = (v[0] >> 32) + (v[0] & 0xffffffff) * 1e-9
        if not lo - 1 <= when <= hi + 1:
            return f'its event of {v[0]:#x} carries the time {when:.6f}, not within the run\'s L1Accepts ({lo:.3f} to {hi:.3f})'
    return None


PVS_DUMP = re.compile(r'^(\S+) -> (Top\b\S*)[ \t\r]*$', re.M)     # pyrogue's EpicsPvServer.dump(): '<pv> -> <path>'


def pvs_problem(prog, e, logs):
    """R6b: why a 'pvs' witness entry does not show prog (wave8pvs) serve its board's PVs while the run ran, or None
    (module doc)."""
    mine = [(args, text) for (name, args), text in logs if name == prog]
    if not mine:
        return f'lists no log of {prog}'
    args, text = mine[0]
    dev, base = _opt(args, '--dev') or '/dev/datadev_0', _opt(args, '--base') or 'DAQ:WAVE8'
    if not dev.startswith('sim://'):
        return f'its log of {prog} runs --dev {dev}, not a simulated device (sim://)'
    pvs = dict(PVS_DUMP.findall(text))
    names = [n for n in pvs if n.startswith(base + ':')]
    if not names:
        return f'its log of {prog} lists no PV under its --base {base} (EpicsPvServer.dump())'
    if e.get('names') != len(names) or e.get('served') != len(names) or e.get('nmissing'):
        return (f'shows {prog} serve {e.get("served")} of {e.get("names")} PVs, but its log lists {len(names)} '
                f'(missing {str(e.get("missing"))[:100]})')
    pids = {log_pid(t) for _, t in mine} - {None}
    if not (isinstance(e.get('owners'), list) and pids & set(e['owners'])):
        return (f'its PVA server\'s port is held by pids {e.get("owners")}, not the pid its log of {prog} gives '
                f'({", ".join(str(p) for p in sorted(pids)) or "none"})')
    pv, path = e.get('put'), e.get('path')
    if pv not in pvs or pvs[pv] != path:
        return f'puts {pv}, which its log of {prog} does not list as the register {path}'
    nums = numbers(e.get('values') or [])
    if len(nums) < 2:
        return f'{pv} read back {e.get("values")}, not 2 or more distinct numbers'
    written = set()
    for wr in e.get('writes') or []:
        for r in (wr.get('regs') or []) if isinstance(wr, dict) else []:
            if str(r).startswith(f'{path}='):
                try:
                    written.add(int(str(r).split('=', 1)[1], 0))
                except ValueError:
                    pass
    shown = []
    for v in (e.get('values') or [])[1:]:
        try:
            shown.append(int(float(v)))
        except ValueError:
            continue
    if not shown or not set(shown) <= written:
        return (f'{pv} read back {shown}, but its board logged {path} written to {sorted(written)} '
                f'(a value read back after a put must have reached the simulated board)')
    return None


def tpr_problem(prog, e, logs, partition, lo, hi):
    """R8: why a 'tpr' witness entry does not show TPR program prog's card programmed as its command line says
    while the run ran (lo..hi, EPICS-epoch seconds), or None.  The card is the file the program's own log says
    tpr::Client mapped (TPR_CARD); tpr_trigger's readout group is the partition's (<...>:PART:<group>)."""
    card = e.get('card')
    mine = [(args, text) for (name, args), text in logs if name == prog]
    named = [(args, m.group(1)) for args, text in mine for m in TPR_CARD.finditer(text) if isinstance(card, str)
             and (m.group(2) == card or os.path.realpath(m.group(2)) == os.path.realpath(card))]
    if not named:
        return (f'its {prog} entry reads the card {card}, but no listed log of {prog} says tpr::Client mapped it '
                f'(PSDAQ_SIM_TPR)')
    m = re.search(r':PART:(\d+)$', str(partition or ''))
    group = int(m.group(1)) if m else None
    exp = tpr_expected(prog, named[0][0], group)
    if exp is None:
        return f'its log of {prog} gives a command line {prog} refuses, or no readout group for it: {named[0][0]}'
    chan, trigs = exp
    reads = [r for r in e.get('reads') or [] if isinstance(r, dict) and isinstance(r.get('t'), (int, float))
             and lo <= r['t'] <= hi and isinstance(r.get('channels'), list) and isinstance(r.get('triggers'), list)]
    if len(reads) < 2:
        return f'read {prog}\'s card {len(reads)} time(s) within the run\'s L1Accepts (2 or more needed)'
    for r in reads:
        try:
            c = r['channels'][chan['channel']]
            got = [(k, c.get(k), chan[k]) for k in ('control', 'evtSel') if chan[k] is not None and c.get(k) != chan[k]]
            for t in trigs:
                tr = r['triggers'][t['trigger']]
                got += [(f'trigger{t["trigger"]}.{k}', tr.get(k), t[k]) for k in ('control', 'delay', 'width', 'delayTap')
                        if tr.get(k) != t[k]]
        except (IndexError, AttributeError, TypeError):
            return f'its {prog} entry has a read at {r["t"]:.3f} without the channel or trigger its command line programs'
        if got:
            k, have, want = got[0]
            where = k if k.startswith('trigger') else f'channel{chan["channel"]}.{k}'
            return (f'shows {prog}\'s card at {r["t"]:.3f} with {where} '
                    f'{hex(have) if isinstance(have, int) else have}, not the {hex(want)} its command line programs')
    return None


SLURM_SKEW = 1.5                        # s: R5, a refresh matches the squeue read nearest it if this close


def slurm_matched(e, lo=None, hi=None):
    """R5: (the refreshes of a 'slurm' entry, within [lo, hi] (EPICS-epoch seconds) if given, whose table shows for
    every row the state the squeue read nearest in time (within SLURM_SKEW) gave the job of that process (comment
    <comment_prefix>_<ID>; COMPLETED when squeue lists none, as daqstat shows a job that ended), with one job
    squeue listed at least; why the first other refresh does not count, or None)."""
    prefix = e.get('comment_prefix')
    if not (isinstance(prefix, str) and prefix):
        return [], 'it gives no job comment prefix'
    reads = [r for r in e.get('squeue') or [] if isinstance(r, dict) and isinstance(r.get('t'), (int, float))
             and isinstance(r.get('jobs'), dict)]
    if not reads:
        return [], 'it lists no squeue read'
    ok, why, seen = [], None, set()
    for f in e.get('refreshes') or []:
        if not (isinstance(f, dict) and isinstance(f.get('t'), (int, float)) and isinstance(f.get('rows'), list)):
            continue
        t = f['t']
        if lo is not None and not lo <= t <= hi:
            why = why or f'the refresh at {t:.3f} is not within the run\'s L1Accepts'
            continue
        rows = [r for r in f['rows'] if isinstance(r, list) and len(r) == 2]
        near = min(reads, key=lambda r: abs(r['t'] - t))
        want = {str(i): near['jobs'].get(f'{prefix}_{i}', 'COMPLETED') for i, _ in rows}
        bad = [(i, st) for i, st in rows if st != want[str(i)]]
        if abs(near['t'] - t) > SLURM_SKEW:
            why = why or f'no squeue read within {SLURM_SKEW} s of the refresh at {t:.3f}'
        elif bad:
            why = why or f'the refresh at {t:.3f} shows {bad[0][0]} {bad[0][1]}, squeue said {want[str(bad[0][0])]}'
        elif not any(f'{prefix}_{i}' in near['jobs'] for i, _ in rows):
            why = why or f'the refresh at {t:.3f} shows no job squeue listed'
        elif t not in seen:
            seen.add(t)
            ok.append(f)
    return ok, why


def witness_section(entry, prog, w):
    """The gui_witness section that proves prog: 'servers' for a STAND-IN row (R3), and for a RUN row whose
    program is a PV server of the tree's own (R3b: a 'servers' entry keyed by the program and marked
    "program": true, and no 'programs' entry; it then needs the program's own interface served, under a prefix
    its own log's -P serves); 'programs' otherwise."""
    if entry.get('status') == 'STAND-IN':
        return 'servers'
    e = (w.get('servers') or {}).get(prog)
    own = isinstance(e, dict) and e.get('program') is True and prog not in (w.get('programs') or {})
    return 'servers' if own else 'programs'


def changed_texts(values):
    """R4: the distinct texts holding a digit among a widget's texts after its first one.  The first may be
    the text the widget was built with (tprca's PvEditDbl shows '0' before its PV's value), and a value may
    carry units or be an array (dtica's '928.6154kHz'), so texts, not numbers, are compared."""
    return {str(v).strip() for v in values[1:] if any(c.isdigit() for c in str(v))}


def numbers(values):
    """The distinct numbers among a widget's texts (a placeholder such as '' or '-' is none)."""
    out = set()
    for v in values:
        try:
            x = float(str(v).replace(',', ''))
        except ValueError:
            continue
        if x == x:                      # not NaN
            out.add(x)
    return out


def _cached(cache, key, make):
    if cache is None:
        return make()
    if key not in cache:
        cache[key] = make()
    return cache[key]


def read_log(path, size, cache=None):
    """The first `size` bytes of a log, as text: the bytes its record hashed (what was
    appended after the record was written does not count)."""
    def make():
        with open(path, 'rb') as f:
            return f.read(size).decode('utf-8', 'replace')
    return _cached(cache, ('log', path, size), make)


def file_problem(path, entry=None, cache=None):
    """(kind, why) if one evidence file does not count, else None.  `entry` is the record's
    {'bytes', 'sha256'} for it: the file must still hold those bytes at its start (an xtc2
    file exactly those)."""
    path = str(path)
    if not os.path.isfile(path):
        return 'missing', 'missing'
    size = os.path.getsize(path)
    if size == 0:
        return 'empty', 'empty'
    if not (isinstance(entry, dict) and isinstance(entry.get('bytes'), int)
            and isinstance(entry.get('sha256'), str)):
        return 'unhashed', 'the record holds no content hash of it'
    want = entry['bytes']
    if size < want or (path.endswith('.xtc2') and size != want):
        return 'changed', f'{size} B now, the record hashed {want} B'
    if path.endswith('.xtc2'):
        p = _cached(cache, ('xtc2', path), lambda: xtc2_content(path))[0]
        if p:
            return 'not xtc2', f'not an xtc2 file ({p})'
    if _cached(cache, ('sha256', path, want), lambda: content_hash(path, want)) != entry['sha256']:
        return 'changed', f'its first {want} B are not the bytes the record hashed (sha256 differs)'
    return None


def record_problem(rec, sha, cache=None):
    """Why a record proves nothing at `sha`, or None if its rows still need row_problem."""
    if rec['sha'] != sha:
        return f'recorded at {str(rec["sha"])[:9]}, not at HEAD {sha[:9]}'
    if rec.get('dirty') is not False:
        return ('recorded with tracked files modified' if rec.get('dirty') else
                'does not say the tree was clean') + ', so not by the commit\'s own code'
    if not str(rec.get('run_id') or '').strip():
        return 'names no run (run_id)'
    files = rec['files']
    if not isinstance(files, list) or not files or not all(isinstance(f, str) for f in files):
        return 'lists no files'
    content = rec.get('content')
    if not isinstance(content, dict):
        return 'holds no content hashes of its files (content), so they cannot be tied to the run'
    bad = [(f, p) for f, p in ((f, file_problem(f, content.get(f), cache)) for f in files) if p]
    if bad:
        kinds = '/'.join(sorted({kind for _, (kind, _) in bad}))
        return f'{len(bad)} of {len(files)} files {kinds}, e.g. {bad[0][0]}: {bad[0][1][1]}'
    return None


def row_problem(rid, entry, rec, cache=None):
    """Why a record that passes record_problem does not prove row `rid` (status `entry`), or
    None: the content of its files must show the row ran in the record's run (module doc)."""
    run_id = str(rec['run_id'])
    data_dir = rec.get('data_dir') if isinstance(rec.get('data_dir'), str) else None
    runs = {f: _cached(cache, ('xtc2', f), lambda f=f: xtc2_content(f))[1]
            for f in rec['files'] if f.endswith('.xtc2')}
    named = [(f, rec['content'][f]['bytes']) for f in rec['files'] if not f.endswith('.xtc2')]
    texts = [read_log(f, size, cache) for f, size in named]
    logs = [(log_program(text), text) for text in texts]

    def names_run(text, paths):
        return any(names_file(text, p) or names_relative(text, p, data_dir) or
                   (runs[p]['beginrun'] and runs[p]['beginrun'] in text) for p in paths)

    if rid.startswith('det:'):
        exe, typ = rid.split(':', 2)[1:]
        if not runs:
            return 'lists no xtc2 file'
        has = [f for f, c in runs.items() if typ in c['types']]
        if not has:
            seen = sorted(set().union(*(c['types'] for c in runs.values())) - {'runinfo', 'chunkinfo'})
            return (f'no listed xtc2 file has a detector of type {typ} in its Configure '
                    f'(they have: {", ".join(seen) or "no detector"})')
        why = []
        for f in has:
            c, n = runs[f], runs[f]['l1_with'].get(typ, 0)
            if c['run'] != run_id:
                why.append(f'{f}: its BeginRun is run {c["run"]}, the record says {run_id}' if c['run']
                           else f'{f}: no BeginRun with the run\'s runinfo')
            elif n < MIN_L1ACCEPTS:
                why.append(f'{f}: {n} of its {c["l1accepts"]} L1Accepts hold {typ} data, '
                           f'fewer than {MIN_L1ACCEPTS}')
            elif not any(prog == exe and typ in detector_types(args) and names_run(text, [f])
                         for (prog, args), text in logs):
                why.append(f'no listed log runs {exe} -D {typ} and names the run of {f} '
                           f'(its path or BeginRun time {c["beginrun"]})')
            else:
                return None
        return why[0]
    prog = entry['stand_in'] if entry.get('status') == 'STAND-IN' else rid.split(':', 1)[1]
    mine = [f for f, c in runs.items() if c['run'] == run_id]
    if not mine:
        return (f'lists no xtc2 file of run {run_id} (by its BeginRun runinfo) to tie the log '
                f'of {prog} to')
    ran = [text for (name, _), text in logs if name == prog]
    if not ran:
        return f'lists no log of {prog} (a log whose "# CMDLINE:" runs {prog})'
    witnesses = [w for w in (_cached(cache, ('witness', f, size), lambda t=t: witness(t))
                             for (f, size), t in zip(named, texts)) if w]
    if prog in AMI_PROGRAMS and entry.get('status') != 'STAND-IN':
        kind = 'ami_check'
        why = [ami_witness_problem(prog, w, run_id, mine, runs, ran) for w in witnesses
               if w['witness'] == kind]
    elif any(names_run(text, mine) for text in ran):
        return None
    else:
        kind = 'gui_witness'
        run_ids = {m.group(1) for m in (LOG_ID.search(t) for t in texts if names_run(t, mine)) if m}
        why = [live_witness_problem(prog, w, run_id, mine, runs, witness_section(entry, prog, w), run_ids,
                                    rid.split(':', 1)[1], logs)
               for w in witnesses if w['witness'] == kind]
        if not why:
            return (f'its log of {prog} names neither the run\'s xtc2 file {mine[0]} (nor that path '
                    f'relative to the data dir {data_dir}) nor its BeginRun time '
                    f'{runs[mine[0]]["beginrun"]}, and it lists no {kind} witness')
    if not why:
        return f'lists no {kind} witness (a JSON log {{"witness": "{kind}", ...}}) for {prog}'
    if None in why:
        return None
    return f'its {kind} witness {why[0]}'


def record_verdicts(path, repo=None, status_path=None, cache=None):
    """{row: why the record at `path` does not prove it, or None}, as check() decides at HEAD;
    for a runner to report right after it writes a record."""
    repo = repo or find_repo()
    with open(path) as f:
        rec = json.load(f)
    with open(status_path or os.path.join(repo, STATUS_FILE)) as f:
        status = json.load(f)
    cache = {} if cache is None else cache
    p = record_problem(rec, head(repo), cache)
    return {rid: p or row_problem(rid, status.get(rid) or {'status': 'RUN'}, rec, cache)
            for rid in rec['rows']}


# --- the check ----------------------------------------------------------------------------

def check(repo, status_path=None, evidence_path=None):
    """Everything the report needs, as a dict; 'pass' is the verdict."""
    sha = head(repo)
    status_path = status_path or os.path.join(repo, STATUS_FILE)
    edir = evidence_dir(evidence_path, repo)
    rows, problems = enumerate_rows(repo)
    status, sproblems = load_status(status_path, rows)
    problems += sproblems
    records = load_evidence(edir)
    problems += [f'evidence {rid}: {p}' for rid, rec, p in records if rec is None]
    records = [(rid, rec) for rid, rec, p in records if rec is not None]
    known = set(rows)
    for rid, rec in records:
        unknown = [r for r in rec['rows'] if r not in known]
        if unknown and rec['sha'] == sha:
            problems.append(f'evidence {rid}: names rows the enumeration does not find: {" ".join(unknown)}')

    out, whole, cache = [], {}, {}     # whole: record id -> record_problem; cache: files read
    for rid, where in rows.items():
        entry = status.get(rid)
        row = {'row': rid, 'where': where, 'status': entry['status'] if entry else 'UNPROVEN',
               'ok': False, 'evidence': [], 'rejected': []}
        mine = [(eid, rec) for eid, rec in records if rid in rec['rows']]
        if entry is None:
            row['text'] = 'no status entry' + (f' (evidence exists: {mine[-1][0]})' if mine else '')
        elif entry['status'] == 'N/A':
            row['ok'], row['text'] = True, entry['reason']
        else:
            for eid, rec in mine:
                if eid not in whole:
                    whole[eid] = record_problem(rec, sha, cache)
                p = whole[eid] or row_problem(rid, entry, rec, cache)
                if p:
                    row['rejected'].append((eid, p))
                else:
                    row['evidence'].append(eid)
            row['ok'] = bool(row['evidence'])
            if row['ok']:
                text = f'evidence {row["evidence"][-1]}'
                if dict(mine)[row['evidence'][-1]].get('dirty'):
                    text += ' (run with tracked files modified)'
                if len(row['evidence']) > 1:
                    text += f' (+{len(row["evidence"]) - 1} more)'
                if row['rejected']:
                    text += f'; {len(row["rejected"])} rejected'
            else:
                text = f'NO VALID EVIDENCE at HEAD {sha[:9]}'
                for eid, p in row['rejected'][-3:]:
                    text += f'; rejected {eid}: {p}'
                if len(row['rejected']) > 3:
                    text += f'; and {len(row["rejected"]) - 3} more rejected'
            if entry['status'] == 'STAND-IN':
                text = f'stand-in {entry["stand_in"]} ({entry["interface"]}); {text}'
            row['text'] = text
        out.append(row)

    # R and S count rows whose evidence is valid at HEAD; what the status file says is 'claimed'
    count = {s: sum(r['status'] == s and r['ok'] for r in out) for s in STATUSES}
    count['UNPROVEN'] = sum(r['status'] == 'UNPROVEN' for r in out)
    count['INVALID'] = sum(r['status'] in ('RUN', 'STAND-IN') and not r['ok'] for r in out)
    claimed = {s: sum(r['status'] == s for r in out) for s in STATUSES}
    return {'repo': repo, 'sha': sha, 'dirty': dirty(repo), 'status_file': status_path,
            'evidence_dir': edir, 'records': len(records), 'problems': problems, 'rows': out,
            'count': count, 'claimed': claimed,
            'pass': not problems and all(r['ok'] for r in out)}


def report(res, verbose=False, file=sys.stdout):
    def p(*a):
        print(*a, file=file)
    rows = res['rows']
    ndet = {exe: sum(r['row'].startswith(f'det:{exe}:') for r in rows) for exe, _ in DET_SOURCES}
    nprog = sum(r['row'].startswith('prog:') for r in rows)
    p(f'daq_sim coverage at {res["sha"]} (HEAD of {res["repo"]})'
      f'{", tracked files modified" if res["dirty"] else ""}')
    p('rows from: ' + ', '.join(f'{rel} ({ndet[exe]} types)' for exe, rel in DET_SOURCES) +
      f', {CNF_DIR} ({len(config_files(res["repo"]))} configs, {nprog} programs)')
    p(f'status: {res["status_file"]}')
    p(f'evidence: {res["evidence_dir"]} ({res["records"]} records)')
    for problem in res['problems']:
        p(f'ERROR {problem}')
    p(f'{"row":<30} {"status":<9} evidence / reason')
    for r in rows:
        p(f'{r["row"]:<30} {r["status"]:<9} {r["text"]}')
        if verbose:
            p(f'{"":<30} {"":<9} {r["where"]}')
    c, cl = res['count'], res['claimed']
    p(f'{len(rows)} rows, {c["RUN"]} run, {c["STAND-IN"]} stand-in, {c["N/A"]} N/A, '
      f'{c["UNPROVEN"]} unproven, {c["INVALID"]} claimed without valid evidence')
    p(f'status file claims (not counted above unless proven): {cl["RUN"]} RUN, '
      f'{cl["STAND-IN"]} STAND-IN, {cl["N/A"]} N/A')
    if res['pass']:
        p('PASS')
        return
    bad = [r for r in rows if not r['ok'] and r['status'] != 'UNPROVEN']
    unproven = [r['row'] for r in rows if r['status'] == 'UNPROVEN']
    p(f'FAIL: {len(res["problems"])} error(s), {len(bad)} RUN/STAND-IN row(s) without valid '
      f'evidence, {len(unproven)} unproven row(s)')
    for problem in res['problems']:
        p(f'  error: {problem}')
    for r in bad:
        p(f'  {r["row"]}: {r["status"]} row without valid evidence at HEAD {res["sha"][:9]}')
    for k in range(0, len(unproven), 6):
        p('  unproven: ' + ' '.join(unproven[k:k + 6]))


def add_arguments(parser):
    parser.add_argument('--repo', help='checkout to check (default: the one holding this '
                        'module, else the one holding the current directory)')
    parser.add_argument('--status', help=f'status file (default <repo>/{STATUS_FILE})')
    parser.add_argument('--evidence', help='evidence dir (default $DAQ_SIM_EVIDENCE, else '
                        f'<repo>/{EVIDENCE_SUBDIR})')
    parser.add_argument('-v', '--verbose', action='store_true', help='show where each row comes from')
    parser.add_argument('--json', action='store_true', help='print the result as JSON')


def run(args):
    """The check for parsed arguments (also 'daq_sim coverage'); returns the exit code."""
    try:
        res = check(find_repo(args.repo), args.status, args.evidence)
    except (CoverageError, OSError, subprocess.SubprocessError) as e:
        print(f'coverage: {e}', file=sys.stderr)
        print('FAIL')
        return 1
    if args.json:
        print(json.dumps(res, indent=1))
    else:
        report(res, args.verbose)
    return 0 if res['pass'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m psdaq.sim.coverage',
                                     description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__.split('\n\n', 1)[1])
    add_arguments(parser)
    return run(parser.parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
