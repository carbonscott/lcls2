"""MkDocs hook: do not fail the strict build on cross-references inside docstrings.

mkdocs-autorefs treats ``[text][target]`` as a cross-reference. Some existing
docstrings contain this pattern as plain prose, for example
``[32 bits of seconds][32 bits of nanoseconds]`` in ``psana/psana/event.py``.
autorefs then logs "Could not find cross-reference target", which fails
``mkdocs build --strict`` even though nothing is wrong with the docs pages.

This hook lowers those messages to INFO when they come from a Python source
file (the message then contains ``from /path/to/file.py:<line>:``). Broken
cross-references written in the Markdown pages under docs/ still produce a
WARNING and still fail the strict build. Run ``mkdocs build -v`` to see the
lowered messages.
"""

import logging
import re

AUTOREFS_LOGGER = "mkdocs.plugins.mkdocs_autorefs._internal.plugin"
FROM_DOCSTRING = re.compile(r"from \S+\.py:\d+: .*Could not find cross-reference target")


class _DocstringXrefFilter(logging.Filter):
    def filter(self, record):
        if record.levelno == logging.WARNING and FROM_DOCSTRING.search(record.getMessage()):
            record.levelno = logging.INFO
            record.levelname = "INFO"
        return True


def on_config(config, **kwargs):
    logger = logging.getLogger(AUTOREFS_LOGGER)
    if not any(isinstance(f, _DocstringXrefFilter) for f in logger.filters):
        logger.addFilter(_DocstringXrefFilter())
    return config
