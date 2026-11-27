import pytest

from bot.engine import errors


@pytest.fixture(autouse=True)
def _clear_secrets():
    errors._SECRETS.clear()
    yield
    errors._SECRETS.clear()
