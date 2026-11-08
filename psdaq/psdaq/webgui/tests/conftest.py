"""Shared pytest hooks of the web GUI tests."""

import pytest

from parity_rows import ROWS


@pytest.fixture(autouse=True)
def _parity_rows(request, record_property):
    """Record the parity rows parity_rows.ROWS assigns to this test as junit `parity` properties."""
    mod = getattr(request.node, 'module', None)
    name = mod.__name__.rsplit('.', 1)[-1] if mod is not None else ''
    for rid in ROWS.get(name, {}).get(getattr(request.node, 'originalname', request.node.name), []):
        record_property('parity', rid)
