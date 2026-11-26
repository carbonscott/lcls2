# Suggested fix, applied at import time for the control run only (loaded only when this folder is on PYTHONPATH).
# DataSourceBase._get_file_info_from_db as at lcls2 fae94d3, with two changes:
#   1. the URL can be overridden (PS_LGBK_FILE_INFO_URL, a format string with {exp} and {runnum});
#   2. requests.get() moves inside the try (with a timeout), so an unreachable logbook falls back to the disk.
import os, sys, importlib.abc, importlib.util

class _Fix(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name != "psana.psexp.ds_base":
            return None
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(name)
        orig = spec.loader.exec_module

        def exec_module(module):
            orig(module)
            import re, requests
            base = module.DataSourceBase
            default = base._file_info_url

            def _file_info_url(self, runnum):
                fmt = os.environ.get("PS_LGBK_FILE_INFO_URL")
                return fmt.format(exp=self.exp, runnum=runnum) if fmt else default(self, runnum)

            def _get_file_info_from_db(self, runnum):
                url = self._file_info_url(runnum)
                try:
                    resp = requests.get(url, timeout=10)
                    resp.raise_for_status()
                    all_xtc_files = resp.json()["value"]
                except Exception as e:
                    self.logger.info(f"Warning: unable to connect to {url}: {e}")
                    all_xtc_files = []
                file_info = {}
                if all_xtc_files:
                    xtc_files = sorted(os.path.basename(f) for f in all_xtc_files if re.search(r"-c000\.", f))
                    if xtc_files:
                        file_info["xtc_files"] = xtc_files
                        file_info["dirname"] = os.path.dirname(all_xtc_files[0])
                return file_info

            base._file_info_url = _file_info_url
            base._get_file_info_from_db = _get_file_info_from_db
            print("fixshim: DataSourceBase._get_file_info_from_db patched (request inside try)", flush=True)
        spec.loader.exec_module = exec_module
        return spec

sys.meta_path.insert(0, _Fix())
