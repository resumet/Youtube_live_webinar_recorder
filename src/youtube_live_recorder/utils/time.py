from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("시간대가 없는 시각은 저장할 수 없습니다.")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def from_iso(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("저장된 시각에 시간대 정보가 없습니다.")
    return result.astimezone(UTC)


def seoul_time(value: datetime) -> datetime:
    return from_iso(to_iso(value)).astimezone(ZoneInfo("Asia/Seoul"))
