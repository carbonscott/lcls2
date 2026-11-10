"""oldcode.py REV MODULE TESTFILE KEYWORD: run the test(s) KEYWORD of TESTFILE with psdaq.sim.MODULE's code taken from
commit REV (git show, exec'd into the installed module), to show the new test fails on the old code."""
import importlib, subprocess, sys
rev, mod, testfile, kw = sys.argv[1:5]
m = importlib.import_module(f'psdaq.sim.{mod}')
src = subprocess.check_output(['git', 'show', f'{rev}:psdaq/psdaq/sim/{mod}.py'], text=True)
exec(compile(src, m.__file__, 'exec'), m.__dict__)
print(f'psdaq.sim.{mod} now runs the code of {rev}')
import pytest
sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', testfile, '-k', kw]))
