import logging
from datetime import UTC, datetime

import pytest

from youtube_live_recorder.utils.logging import SafeFormatter, configure_logging, redact
from youtube_live_recorder.utils.time import from_iso, seoul_time, to_iso


def test_utc_storage_and_seoul_date_boundary():
    instant = datetime(2026, 10, 18, 15, 30, tzinfo=UTC)
    assert from_iso(to_iso(instant)) == instant
    assert seoul_time(instant).date().isoformat() == "2026-10-19"


def test_rejects_ambiguous_timestamp():
    with pytest.raises(ValueError):
        to_iso(datetime(2026, 10, 19))
    with pytest.raises(ValueError):
        from_iso("2026-10-19T12:00:00")


def test_redaction_in_traceback():
    try:
        raise ValueError("https://example.test/media?sig=private token=secret")
    except ValueError:
        import sys

        record = logging.LogRecord("test", logging.ERROR, "", 0, "실패", (), sys.exc_info())
    formatted = SafeFormatter("%(message)s").format(record)
    assert "private" not in formatted and "secret" not in formatted


@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Bearer secret-token",
        "Cookie: first=secret-one; second=secret-two",
        "token=secret-value",
    ],
)
def test_header_values_are_fully_redacted(text):
    assert "secret" not in redact(text)


def test_logger_reinitialization_does_not_duplicate_handlers(tmp_path):
    first = configure_logging(tmp_path)
    second = configure_logging(tmp_path)
    assert first is second
    assert len(second.handlers) == 1
    second.info("한글 로그")
    second.handlers[0].flush()
    assert (tmp_path / "app.log").read_text(encoding="utf-8").count("한글 로그") == 1
    for handler in second.handlers[:]:
        second.removeHandler(handler)
        handler.close()
