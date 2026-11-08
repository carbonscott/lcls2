#!/bin/bash
# Run the web GUI tests (Playwright UI tests + safety tests) with the campaign's headless-browser venv.
# The server under test runs with the DAQ env's python (sourced from setup_env_daq.sh next to this checkout),
# bound to 127.0.0.1, with dead HTTP(S) proxies. Extra arguments go to pytest, e.g.
#   psdaq/psdaq/webgui/tests/run_webgui_tests.sh -k full_cycle --junitxml=/tmp/webgui.xml
# Environment: WEBGUI_SHOTS (screenshot dir, default ./webgui-shots), WEBGUI_SERVER_ARGS (extra server args),
#              WEBGUI_PYTHON (server interpreter), AGENTIFY_WEBTEST (venv + browsers root).
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/../../../.." && pwd)                  # checkout root (has setup_env_daq.sh)
W=${AGENTIFY_WEBTEST:-/sdf/scratch/users/c/cwang31/agentify-webtest}
export PLAYWRIGHT_BROWSERS_PATH=$W/browsers
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-/sdf/scratch/users/c/cwang31/.cache-agentify}
export HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
export PYTHONDONTWRITEBYTECODE=1
if [ -z "${WEBGUI_PYTHON:-}" ] && [ -f "$REPO/setup_env_daq.sh" ]; then
    WEBGUI_PYTHON=$(bash -c "source '$REPO/setup_env_daq.sh' >/dev/null 2>&1; command -v python")
fi
export WEBGUI_PYTHON=${WEBGUI_PYTHON:-$W/venv/bin/python}
export WEBGUI_SHOTS=${WEBGUI_SHOTS:-$PWD/webgui-shots}
echo "host $(hostname) date $(date -Is) server-python $WEBGUI_PYTHON shots $WEBGUI_SHOTS server-args '${WEBGUI_SERVER_ARGS:-}'"
cd "$HERE"
exec "$W/venv/bin/python" -m pytest -p no:cacheprovider --rootdir "$HERE" --browser chromium "$@" "$HERE"
