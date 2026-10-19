from youtube_live_recorder.utils.time import from_iso, seoul_time


def local_time(value: str | None) -> str:
    if not value:
        return "미정"
    return seoul_time(from_iso(value)).strftime("%Y-%m-%d %H:%M")


def duration(seconds: float | None) -> str:
    total = max(0, int(seconds or 0))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def size_label(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:,.1f} {unit}"
        value /= 1024
    return "0 B"
