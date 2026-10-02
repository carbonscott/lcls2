"""Script: run ``tt_update_weights.main('piranha4', piranha4tt_cdict)`` to update the time-tool weights/calibration of a piranha4 configuration."""
import psdaq.configdb.tt_update_weights as ttuw
from psdaq.configdb.piranha4tt_config_store import piranha4tt_cdict

if __name__ == "__main__":
    ttuw.main('piranha4', piranha4tt_cdict)
