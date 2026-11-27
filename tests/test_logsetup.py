import logging

from bot.engine.errors import register_secret
from bot.logsetup import setup_logging


def test_httpx_request_log_hides_token(capsys):
    register_secret("123456789:AAHrealtokenrealtokenrealtoken12")
    setup_logging()
    logging.getLogger("httpx").warning(
        "HTTP Request: POST https://api.telegram.org/bot123456789:AAHrealtokenrealtokenrealtoken12/getUpdates")
    out = capsys.readouterr()
    assert "getUpdates" in out.out + out.err
    assert "AAHreal" not in out.out + out.err


def test_log_args_are_scrubbed(capsys):
    register_secret("hunter2hunter2")
    setup_logging()
    logging.getLogger("bot.x").warning("value %s", "hunter2hunter2")
    out = capsys.readouterr()
    assert "hunter2" not in out.out + out.err
    assert "value ***" in out.out + out.err


def test_httpx_info_suppressed():
    setup_logging()
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


def test_exception_traceback_is_scrubbed(capsys):
    register_secret("tracebacksecret99")
    setup_logging()
    try:
        raise RuntimeError("boom tracebacksecret99")
    except RuntimeError:
        logging.getLogger("bot.x").exception("job failed")
    out = capsys.readouterr()
    assert "RuntimeError" in out.out
    assert "tracebacksecret99" not in out.out
