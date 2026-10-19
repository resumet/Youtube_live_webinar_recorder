import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_HEADER = re.compile(r"\b(cookie|authorization)\s*:\s*[^\r\n]+", re.IGNORECASE)
_SECRET = re.compile(
    r"\b(cookie|authorization|token|signature|sig|key|password)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    # 서명 URL이나 일부 공개 영상 ID를 진단 로그에 남기지 않는다.
    text = _HEADER.sub(r"\1: [숨김]", text)
    return _SECRET.sub(r"\1=[숨김]", _URL.sub("[URL 숨김]", text))


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # 예외 traceback까지 생성한 뒤 마스킹한다.
        return redact(super().format(record))


def configure_logging(folder: Path) -> logging.Logger:
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("youtube_live_recorder")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(
        folder / "app.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(SafeFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    return logger
