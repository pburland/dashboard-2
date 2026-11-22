import pytest


@pytest.fixture(autouse=True)
def _no_cached_zones():
    """Tested zones are cached in memory; start every test without them."""
    from app.periodization import zones
    zones._CURRENT.clear()
    yield
    zones._CURRENT.clear()
