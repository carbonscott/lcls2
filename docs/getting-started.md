# Getting started

This page collects the build and setup pointers that exist in the repository
(`README.md`, `build_all.sh`, `build_psana.sh`, the `setup_env*.sh` scripts and
the GitHub workflows). It does not replace them: when in doubt, read the script.

## Choose a build

| You want | Script | What it builds | Install location |
|---|---|---|---|
| Analysis only (psana2) | `build_psana.sh` | xtcdata, psalg, psana (no psdaq) | `./install_psana` |
| Full repository (analysis, optionally DAQ) | `build_all.sh` | xtcdata, psalg, psana; psdaq with `-d` | `./install` (or `$TESTRELDIR`) |

Both use the root Meson project (`meson.build`, `meson_options.txt`).

## Analysis-only build (`build_psana.sh`)

From `README.md`: create the locked Conda environment that ships with the
repository, build, and activate the install.

```bash
conda create --prefix ./.conda-psana --file .daq_20250402_r9.txt
conda activate ./.conda-psana
./build_psana.sh --clean -j 8
source ./install_psana/activate.sh
python -c "import psana; import psana.dgram; print(psana.__file__)"
```

Useful options (from `./build_psana.sh --help`):

- `-p, --prefix DIR`: installation prefix (default `<repo>/install_psana`).
- `-t, --build-type TYPE`: `debug`, `debugoptimized` (default), `release`, `minsize` or `plain`.
- `--build-dir DIR`: Meson build directory (default `<repo>/builddir_psana`).
- `--python-only`: refresh installed Python files and entry points from an existing native build, without compiling.
- `--with-cuda`: allow nvcc detection and the CUDA subprojects (off by default).
- `--perlmutter-setup FILE`: after a successful build, write a sourceable runtime setup script (see `README.md` for the shared NERSC Perlmutter procedure).

## Full build (`build_all.sh`)

`build_all.sh` refuses to run unless `ENV_TYPE` is set, which the setup scripts do:

| Script | Sets `ENV_TYPE` | Notes |
|---|---|---|
| `setup_env.sh` | `legacy` | Used in `README.md`. Activates site Conda environments when `/cds/sw/` (PCDS) or `/sdf/group/lcls/` (S3DF) exists; sets `PATH`, `PYTHONPATH` and `TESTRELDIR` to `./install`. |
| `setup_env_ana.sh` | `ana` | S3DF paths under `/sdf/group/lcls/ds/ana/`; activates `ps_20241122`. |
| `setup_env_daq.sh` | `daq` | S3DF paths; activates `daq_20250402_r9`; `build_all.sh` then also builds psdaq. |

```bash
source setup_env.sh
./build_all.sh          # -c compile only, -f force clean, -d build DAQ, -j N jobs
```

`build_all.sh` runs `meson setup`/`meson compile`/`meson install` into
`builddir`, then `uv pip install .` into `$INSTDIR` (and the same for `psdaq/`
when the DAQ build is on). The `-d` flag turns the DAQ build **on**, as the
comment in `.github/workflows/run_psana_tests.yaml` points out.

The setup scripts contain site-specific paths (SLAC S3DF, PCDS). Outside those
sites, use the analysis-only build above.

## Calibration access from outside SLAC

From `README.md`: `LCLS_CALIB_HTTP` is the base URL of the calibration web
service, for example `https://pswww.slac.stanford.edu/ws`. Do not append
`/calib_ws/`; psana adds that path itself. See
[Calibration constants](features/calibration.md).

## Run the tests

```bash
pytest psana/psana/tests/
```

`psana/psana/tests/pytest.ini` deselects tests marked `slow` by default. The
subset of tests that runs in CI is listed in
`.github/workflows/run_psana_tests.yaml`; several other tests need LCLS data
paths or the calibration database. Small xtc2 files used by the tests are in
`psana/psana/tests/test_data/` and `psana/psana/tests/*.xtc2`.

## Wheels

`.github/workflows/release.yml` builds wheels with cibuildwheel on tag pushes
and has a PyPI publish step. psdaq is not part of the wheel (comment in
`pyproject.toml`). Whether a particular version is available on PyPI is not
checked here.

## Build this documentation

Run these from the repository root (the griffe extension paths in
`mkdocs.yml` are relative to it):

```bash
pip install -r docs/requirements.txt     # plus doxygen (e.g. apt-get install doxygen)
doxygen Doxyfile                         # C++ API -> docs/api/cpp/ (git-ignored)
mkdocs build --strict                    # or: mkdocs serve
```

`mkdocs.yml` sets `strict: true`, and the "C++ API" navigation entry points at
`docs/api/cpp/index.html`, so run Doxygen first. The site is published per
version with [mike](https://github.com/jimporter/mike) by
`.github/workflows/build_versioned_mkdocs.yml`.
