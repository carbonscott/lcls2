"""`Config` class for selecting, adding, renaming and printing entries of a DAQ process-config list (entries keyed by 'id')."""
import copy, os
import socket

LOCALHOST = socket.gethostname()


class Config:
    """Allows users to modify main-config list"""

    def __init__(self, main_config):
        # Turns main config list into a dictionary for ez lookup
        self.main_config = {}
        for _config in main_config:
            config = copy.deepcopy(_config)
            # Make sure host is a required key (detault to LOCALHOST)
            if "host" not in config:
                config["host"] = LOCALHOST
            # Remove the id key and use it as the main key for main_config
            cid = config["id"]
            self.main_config[cid] = config
        self.select_config = {}

    def select(self, items):
        """Select only configs with given config ids or add
        new one if given a list of dictionary.

        items example:
        ids: ['timing_0', 'teb0', 'control'] or
        configs: [{ host: ...}, { host: ...}, ...]
        """
        for item in items:
            if isinstance(item, dict):
                config = copy.deepcopy(item)
                cid = config["id"]
                self.select_config[cid] = config
            else:
                cid = item
                if cid in self.main_config:
                    self.select_config[cid] = copy.deepcopy(self.main_config[cid])
                else:
                    print(f"Warning: no {cid} found in main_config")

    def add(self, config):
        """Add `config` to the selected configs under its 'id', setting 'host' to the local host name if missing.

        Raises
        ------
        ValueError
            If `config` is not a dict.
        """
        if not isinstance(config, (dict,)):
            msg = 'Error: only accept config as a dictionary (e.g. {"id": "daq", ...})'
            raise ValueError(msg)
        cid = config["id"]
        if "host" not in config:
            config["host"] = LOCALHOST
        self.select_config[cid] = config

    def rename(self, *args):
        """Rename selected configs; each positional argument is a (current id, new id) pair.

        An id not yet selected is first selected from the main config; a warning is printed if
        it is still not found.
        """
        for arg in args:
            current_cid, new_cid = arg
            if current_cid not in self.select_config:
                self.select([current_cid])
            if current_cid in self.select_config:
                self.select_config[new_cid] = self.select_config.pop(current_cid)
            else:
                print(f"Warning: no {current_cid} found in select_config")

    def extend(self, configs):
        """Add all items in the given configs list"""
        for config in configs:
            self.add(config)

    def show(self, full=False):
        """Print a table of id, host and command for the selected configs (commands abbreviated unless `full`)."""
        print("%20s %18s %80s" % ("UniqueID", "Host", "Command+Args"))
        for cid, config_detail in self.select_config.items():
            host = config_detail["host"]
            cmd = config_detail["cmd"][:65] + "..." + config_detail["cmd"][-12:]
            if full:
                cmd = config_detail["cmd"]
            print("%20s %18s %80s" % (cid, host, cmd))
