# sim_env.sh -- isolation env for the hardware-free lcls2 DAQ (psdaq/psdaq/sim).
# SOURCE this (do not execute) in every DAQ process env, AFTER setup_env_daq.sh,
# because setup_env_daq.sh sources auth.sh which exports production credentials.
#   source ./setup_env_daq.sh && source psdaq/psdaq/sim/sim_env.sh
# Every setting below exists to keep EPICS (CA + PVA), HTTP and credentials on the
# local node. ZMQ is not env-controlled: see the note at the bottom.

# --- 0. Optional: keep tool caches on a fast, local-enough filesystem ----------
# On S3DF, caches under /sdf/data can hang during filesystem incidents. Set
# SIM_CACHE_ROOT (e.g. a /sdf/scratch path) to move XDG and uv caches there.
if [[ -n "${SIM_CACHE_ROOT:-}" ]]; then
  export XDG_CACHE_HOME=$SIM_CACHE_ROOT/xdg UV_CACHE_DIR=$SIM_CACHE_ROOT/uv
fi

# --- 1. Production credentials: drop them -----------------------------------
# setup_env_daq.sh -> /sdf/group/lcls/ds/ana/sw/conda2/auth.sh exports these.
# control.py uses CONFIGDB_AUTH as the default --password for the run DB/eLog
# (control.py:2620) and configdb clients use it for ws-auth. Unset => any call
# that slips through to a production service is unauthenticated and is refused.
# procmgr's start() refuses to run when CONFIGDB_AUTH is undefined
# (ProcMgr.py:957-960), so define it EMPTY rather than unset it.
unset BOS_AUTH CALIBDB_AUTH
export CONFIGDB_AUTH=

# --- 2. EPICS PV Access (pvAccessCPP 7.1.6 in C++, pvxs 1.2 under p4p) ------------
# Client side: never build a search list from the node's interfaces/broadcasts.
export EPICS_PVA_AUTO_ADDR_LIST=NO
# Client side: search only the loopback address.
export EPICS_PVA_ADDR_LIST=127.0.0.1
# No TCP name servers (pvxs/pvAccess may use this to bypass UDP search).
export EPICS_PVA_NAME_SERVERS=
# Non-default ports (defaults 5075/5076): even a stray packet that leaves the
# node cannot be answered by a production PVA server listening on 5075/5076,
# and a production client cannot find our sim PVs.
export EPICS_PVA_SERVER_PORT=15075
export EPICS_PVA_BROADCAST_PORT=15076
# Server side (PVAS_*): bind only loopback, beacon only to loopback.
export EPICS_PVAS_INTF_ADDR_LIST=127.0.0.1
export EPICS_PVAS_BEACON_ADDR_LIST=127.0.0.1
export EPICS_PVAS_AUTO_BEACON_ADDR_LIST=NO
export EPICS_PVAS_SERVER_PORT=15075
export EPICS_PVAS_BROADCAST_PORT=15076

# --- 3. EPICS Channel Access (libca 4.14 / pyepics 3.5.7) -----------------------
export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST=127.0.0.1
export EPICS_CA_NAME_SERVERS=
# Non-default ports (defaults 5064/5065), same reasoning as PVA.
export EPICS_CA_SERVER_PORT=15064
export EPICS_CA_REPEATER_PORT=15065
# CA server side (pcas / rsrv / pyepics-based servers).
export EPICS_CAS_INTF_ADDR_LIST=127.0.0.1
export EPICS_CAS_BEACON_ADDR_LIST=127.0.0.1
export EPICS_CAS_AUTO_BEACON_ADDR_LIST=NO
export EPICS_CAS_SERVER_PORT=15064

# --- 4. HTTP(S): fail closed through a dead proxy -------------------------------
# Port 9 on loopback is 'discard'; nothing listens there, so every proxied
# request gets ECONNREFUSED. requests, urllib and curl honour these (curl only
# reads the lowercase http_proxy, so set both cases). NO_PROXY lets requests to
# the campaign-local stand-ins on this node go direct.
_sim_host=$(hostname)
export HTTP_PROXY=http://127.0.0.1:9
export HTTPS_PROXY=http://127.0.0.1:9
export ALL_PROXY=http://127.0.0.1:9
export http_proxy=$HTTP_PROXY https_proxy=$HTTPS_PROXY all_proxy=$ALL_PROXY
export NO_PROXY=localhost,127.0.0.1,${_sim_host},${_sim_host%%.*}
export no_proxy=$NO_PROXY
unset _sim_host

# --- 5. procmgr-launched children ----------------------------------------------
# For host=localhost entries ProcMgr.start() runs condaProcServ via
# Popen(shell=True) with no env= argument (ProcMgr.py ~1153), so the child
# inherits THIS environment; condaProcServ only resets PATH, LD_LIBRARY_PATH and
# PYTHONPATH. PROCMGR_EXPORT is only used for remote hosts (setenv over telnet)
# and for the '# NAME:value' header of each procmgr log file. Its parser splits
# on ',' then '=' and keeps only the first value field (ProcMgr.py:988-995), so a
# comma-bearing value such as NO_PROXY must NOT go into it. We append the
# comma-free isolation vars so they show up in every log header as evidence.
for _v in EPICS_PVA_AUTO_ADDR_LIST EPICS_PVA_ADDR_LIST EPICS_PVA_SERVER_PORT EPICS_PVA_BROADCAST_PORT \
          EPICS_PVAS_INTF_ADDR_LIST EPICS_PVAS_BEACON_ADDR_LIST EPICS_PVAS_AUTO_BEACON_ADDR_LIST \
          EPICS_PVAS_SERVER_PORT EPICS_PVAS_BROADCAST_PORT \
          EPICS_CA_AUTO_ADDR_LIST EPICS_CA_ADDR_LIST EPICS_CA_SERVER_PORT EPICS_CA_REPEATER_PORT \
          EPICS_CAS_INTF_ADDR_LIST EPICS_CAS_BEACON_ADDR_LIST EPICS_CAS_AUTO_BEACON_ADDR_LIST EPICS_CAS_SERVER_PORT \
          HTTP_PROXY HTTPS_PROXY http_proxy https_proxy; do
  case ",$PROCMGR_EXPORT," in *",$_v="*) ;; *) export PROCMGR_EXPORT="${PROCMGR_EXPORT:+$PROCMGR_EXPORT,}$_v=${!_v}";; esac
done
unset _v

# --- 6. libfabric: pin the TCP provider ---------------------------------------
# Collection.cc getNicIp prefers InfiniBand then Ethernet; the default provider
# choice may pick verbs. tcp works on loopback with no memlock needs.
export FI_PROVIDER=tcp
case ",$PROCMGR_EXPORT," in *",FI_PROVIDER="*) ;; *) export PROCMGR_EXPORT="$PROCMGR_EXPORT,FI_PROVIDER=tcp";; esac

export SIM_ENV_SOURCED=1

# NOTE (not env-controllable): control.py binds its ZMQ sockets on tcp://*:<port>
# (control.py:724-728) and MetricExporter binds Prometheus on 0.0.0.0:92xx
# (MetricExporter.cc:37). They LISTEN on all interfaces; isolation of ZMQ relies
# on every peer being started on this node with host=localhost addresses.
