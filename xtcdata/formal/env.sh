# Source this before building or running the formal model.
#
# Needs elan (https://github.com/leanprover/elan); the toolchain is pinned in
# lean/lean-toolchain.  If `lake` is not on PATH, set ELAN_HOME to the install.
#
# On hosts where Lean's bundled clang cannot start (RHEL 8: it needs
# glibc >= 2.30), the native step uses the system gcc with the toolchain's
# bundled static libraries.
if [ -n "${ELAN_HOME:-}" ] && [ -d "$ELAN_HOME/bin" ]; then
    export PATH="$ELAN_HOME/bin:$PATH"
fi
_ver=$(sed 's/.*://' "$(dirname "${BASH_SOURCE[0]}")/lean/lean-toolchain")
_tc="${ELAN_HOME:-$HOME/.elan}/toolchains/leanprover--lean4---$_ver"
if [ -x "$_tc/bin/clang" ] && ! "$_tc/bin/clang" --version >/dev/null 2>&1; then
    export LEAN_CC=/usr/bin/gcc
    export LIBRARY_PATH="$_tc/lib:$_tc/lib/lean${LIBRARY_PATH:+:$LIBRARY_PATH}"
fi
unset _ver _tc
