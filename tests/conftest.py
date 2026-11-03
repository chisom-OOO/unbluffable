"""Shared test setup."""

import pytest

from app import limits


@pytest.fixture(autouse=True)
def fresh_limits():
    """Decision log 42: the limits and the daily cost meter live in memory; every test starts
    from zero, so suites that open many sessions from one test client don't trip them."""
    limits.GUARD.reset()
    yield
    limits.GUARD.reset()
