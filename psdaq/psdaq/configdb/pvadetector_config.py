"""Configure-phase helper for PV-based detectors: reads and writes EPICS PVs listed in the configuration."""
import json

import epics

from psdaq.configdb.get_config import get_config


def pvadetector_config(connect_str,cfgtype,detname,detsegm):
    #  Read the configdb
    """Read the configuration with `get_config`, then read the 'read_only' PVs and write the 'write' PVs it lists, and return it as JSON.

    Each entry has 'pvname', 'ca' and 'value': 'ca' == 1 uses ``epics.caget``/``epics.caput``,
    otherwise ``epics.PV(...).get``/``put``. Read values, and the read-back after a successful put,
    replace 'value' (the nested dicts are shared with the original config).

    Returns
    -------
    str or None
        The JSON text, or None if `get_config` raised (the error is printed).
    """
    try:
        cfg = get_config(connect_str,cfgtype,detname,detsegm)
    except Exception as err:
        print(err)
        return None
    modifiedCfg = cfg.copy()
    # NOTE: Probably don't need casing on channel access. epics.PV.get/put falls
    # back as needed. Will leave for now in case use cases arise.
    for key in cfg:
        if key == "read_only":
            # Read-only processing: replace read_only.desc.value with pvget/caget value
            for pvDesc in cfg[key]:
                if cfg[key][pvDesc]["ca"] == 1:
                    modifiedCfg[key][pvDesc]["value"] = epics.caget(cfg[key][pvDesc]["pvname"])
                else:
                    modifiedCfg[key][pvDesc]["value"] = epics.PV(cfg[key][pvDesc]["pvname"]).get()
        elif key == "write":
            # Write processing: put write.desc.value to the corresponding pv
            for pvDesc in cfg[key]:
                if cfg[key][pvDesc]["ca"] == 1:
                    ret = epics.caput(cfg[key][pvDesc]["pvname"], cfg[key][pvDesc]["value"])
                    # Store actual value IOC uses afterwards
                    if ret:
                        modifiedCfg[key][pvDesc]["value"] = epics.caget(cfg[key][pvDesc]["pvname"])
                else:
                    ret = epics.PV(cfg[key][pvDesc]["pvname"]).put(cfg[key][pvDesc]["value"])
                    # Store actual value IOC uses afterwards
                    if ret:
                        modifiedCfg[key][pvDesc]["value"] = epics.PV(cfg[key][pvDesc]["pvname"]).get()
    return json.dumps(modifiedCfg)
