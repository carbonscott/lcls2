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
passes.  A record is valid only if its sha is this checkout's HEAD, it was made with no
tracked file modified (only the commit's own code counts), it names the run (run_id), and
every file it lists exists and is non-empty; an .xtc2 file must also be a whole chain of
xtc2 datagrams that starts with a Configure (xtc2_problem).  Any other record is rejected,
and the row's line says why.

Output: every row on its own line, then 'N rows, R run, S stand-in, K N/A, U unproven, X
claimed without valid evidence', where R and S count only rows with valid evidence at HEAD,
then what the status file claims, then PASS (exit 0) if U == 0 and X == 0, else FAIL
(exit 1) and the failing rows.
"""

import argparse
import ast
import contextlib
import datetime
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
# xtc2 datagram header (xtcdata/xtc/Dgram.hh, Xtc.hh): TimeStamp (8 B), env (4 B), then the
# root Xtc: src (4 B), damage (2 B), contains (2 B, TypeId), extent (4 B, counts the Xtc header)
DGRAM = struct.Struct('<QI IHHI')
TRANSITION_SIZE = 12                    # TimeStamp + env: the bytes before the root Xtc
XTC_SIZE = 12
CONFIGURE, L1ACCEPT, UNUSED_11 = 2, 12, 11       # xtcdata/xtc/TransitionId.hh


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


def record_evidence(rows, kind, files, run_id=None, counts=None, started=None, ended=None,
                    job_id=None, host=None, repo=None, evidence=None):
    """Write one evidence record, for a run that passed its own checks, saying it proved
    `rows` at this checkout's HEAD; return its path.  `files` are the run's outputs (xtc2
    file, logs) and must exist when coverage reads the record."""
    repo = repo or find_repo()
    rows = [rows] if isinstance(rows, str) else list(rows)
    sha = head(repo)
    record = {'sha': sha, 'dirty': dirty(repo), 'rows': sorted(set(rows)), 'kind': kind,
              'run_id': run_id, 'job_id': job_id or os.environ.get('SLURM_JOB_ID'),
              'host': host or socket.gethostname(), 'files': [os.path.abspath(f) for f in files],
              'started': started, 'ended': ended or now(), 'counts': counts or {}}
    d = evidence_dir(evidence, repo)
    os.makedirs(d, exist_ok=True)
    rid = f'{time.strftime("%Y%m%dT%H%M%S")}-{re.sub(r"[^A-Za-z0-9_.-]", "_", kind)}-{sha[:9]}-{os.getpid()}'
    path = os.path.join(d, rid + '.json')
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


def xtc2_problem(path):
    """Why `path` is not an xtc2 file, or None: it must be a chain of whole datagrams, the
    first a Configure, each a known transition whose root Xtc is a Parent, the last ending
    exactly at the end of the file (as psana2's reader walks it)."""
    size = os.path.getsize(path)
    off = n = 0
    with open(path, 'rb') as f:
        while off < size:
            f.seek(off)
            hdr = f.read(DGRAM.size)
            if len(hdr) < DGRAM.size:
                return f'datagram {n} at byte {off}: header cut off at the end of the file'
            _, env, _, _, contains, extent = DGRAM.unpack(hdr)
            service = (env >> 24) & 0xf
            if n == 0 and service != CONFIGURE:
                return f'first datagram is transition {service}, not a Configure'
            if service > L1ACCEPT or service == UNUSED_11:
                return f'datagram {n} at byte {off}: no transition has id {service}'
            if contains & 0xfff != 0:
                return f'datagram {n} at byte {off}: root Xtc is TypeId {contains & 0xfff}, not Parent'
            if extent < XTC_SIZE or off + TRANSITION_SIZE + extent > size:
                return f'datagram {n} at byte {off}: extent {extent} does not fit the file ({size} B)'
            off += TRANSITION_SIZE + extent
            n += 1
    return None if n else 'no datagrams'


def file_problem(path):
    """Why one evidence file does not count, or None."""
    path = str(path)
    if not os.path.isfile(path):
        return 'missing'
    if os.path.getsize(path) == 0:
        return 'empty'
    if path.endswith('.xtc2'):
        p = xtc2_problem(path)
        if p:
            return f'not an xtc2 file ({p})'
    return None


def record_problem(rec, sha):
    """Why a record does not prove its rows at `sha`, or None if it does."""
    if rec['sha'] != sha:
        return f'recorded at {str(rec["sha"])[:9]}, not at HEAD {sha[:9]}'
    if rec.get('dirty') is not False:
        return ('recorded with tracked files modified' if rec.get('dirty') else
                'does not say the tree was clean') + ', so not by the commit\'s own code'
    if not str(rec.get('run_id') or '').strip():
        return 'names no run (run_id)'
    files = rec['files']
    if not isinstance(files, list) or not files:
        return 'lists no files'
    bad = [(f, p) for f, p in ((f, file_problem(f)) for f in files) if p]
    if bad:
        kinds = sorted({p.split(' ')[0] for f, p in bad})
        return f'{len(bad)} of {len(files)} files {"/".join(kinds)}, e.g. {bad[0][0]}: {bad[0][1]}'
    return None


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

    out = []
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
                p = record_problem(rec, sha)
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
