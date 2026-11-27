from pathlib import Path

import pytest

from bot.config import ConfigError, load_config
from bot.engine.errors import scrub


def test_load_config_parses_ids_and_paths(tmp_path):
    cfg = load_config({"BOT_TOKEN": "123:abc", "ALLOWED_USER_IDS": "111, 222",
                       "INSTAGRAM_COOKIES": str(tmp_path / "c.txt"), "DOWNLOAD_DIR": str(tmp_path / "dl")})
    assert cfg.allowed_user_ids == frozenset({111, 222})
    assert cfg.download_dir == tmp_path / "dl"
    assert cfg.instagram_cookies == tmp_path / "c.txt"
    assert cfg.bot_token == "123:abc"


@pytest.mark.parametrize("missing", ["BOT_TOKEN", "ALLOWED_USER_IDS"])
def test_load_config_requires(missing):
    env = {"BOT_TOKEN": "123:abc", "ALLOWED_USER_IDS": "1"}
    env.pop(missing)
    with pytest.raises(ConfigError, match=missing):
        load_config(env)


def test_load_config_rejects_blank_values():
    with pytest.raises(ConfigError, match="ALLOWED_USER_IDS"):
        load_config({"BOT_TOKEN": "123:abc", "ALLOWED_USER_IDS": " "})


def test_load_config_rejects_non_numeric_ids():
    with pytest.raises(ConfigError, match="ALLOWED_USER_IDS"):
        load_config({"BOT_TOKEN": "123:abc", "ALLOWED_USER_IDS": "abc"})


def test_defaults():
    cfg = load_config({"BOT_TOKEN": "123:abc", "ALLOWED_USER_IDS": "1"})
    assert cfg.instagram_cookies == Path("cookies/instagram.cookies.txt")
    assert cfg.download_dir == Path("downloads")


def test_token_registered_as_secret():
    load_config({"BOT_TOKEN": "123456:secret-token-value", "ALLOWED_USER_IDS": "1"})
    assert "secret-token-value" not in scrub("x 123456:secret-token-value y")
