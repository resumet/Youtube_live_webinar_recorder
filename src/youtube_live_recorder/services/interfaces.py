from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Event
from typing import Protocol

from youtube_live_recorder.data.models import Quality
from youtube_live_recorder.utils.errors import ErrorCode


class LiveState(StrEnum):
    UPCOMING = "is_upcoming"
    LIVE = "is_live"
    POST_LIVE = "post_live"
    WAS_LIVE = "was_live"
    NOT_LIVE = "not_live"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BroadcastMetadata:
    video_id: str
    title: str
    channel_name: str
    thumbnail_url: str
    state: LiveState
    scheduled_start_at: str | None = None
    actual_start_at: str | None = None


@dataclass(frozen=True)
class MediaInspection:
    path: Path
    valid: bool
    duration_seconds: float
    size_bytes: int
    video_codec: str = ""
    audio_codec: str = ""
    height: int = 0
    reason: str = ""


class MetadataProvider(Protocol):
    def fetch(self, url: str) -> BroadcastMetadata: ...


class MediaVerifier(Protocol):
    def inspect(self, path: Path) -> MediaInspection: ...


@dataclass(frozen=True)
class CaptureRequest:
    url: str
    quality: Quality
    work_directory: Path
    from_start: bool
    on_quality: Callable[[int], None] | None = None


@dataclass(frozen=True)
class CaptureResult:
    return_code: int
    files: tuple[Path, ...]
    stopped_by_user: bool
    from_start_attempted: bool
    error_code: ErrorCode | None = None
    forced: bool = False


class CaptureBackend(Protocol):
    def capture(self, request: CaptureRequest, stop: Event) -> CaptureResult: ...
