import os
from dataclasses import dataclass
from pathlib import Path

from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.limits import DEFAULT_CONCURRENT_RECORDINGS, validate_recording_limit
from youtube_live_recorder.utils.paths import default_save_folder

POLL_SECONDS = 60
REPLAY_POLL_SECONDS = 30 * 60
REPLAY_WINDOW_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class Settings:
    save_folder: Path
    min_free_bytes: int = 1024 * 1024 * 1024
    max_reconnect_attempts: int = 6
    metadata_timeout_seconds: int = 45
    update_manifest_url: str = ""
    max_concurrent_recordings: int = DEFAULT_CONCURRENT_RECORDINGS

    def __post_init__(self):
        validate_recording_limit(self.max_concurrent_recordings)

    @classmethod
    def load(cls, repository: Repository) -> "Settings":
        saved = repository.get_setting("save_folder")
        if not isinstance(saved, str) or not saved or not Path(saved).is_absolute():
            saved = str(default_save_folder())
            repository.set_setting("save_folder", saved)
        manifest = os.environ.get(
            "YLR_UPDATE_MANIFEST_URL", repository.get_setting("update_manifest_url", "")
        )
        if not isinstance(manifest, str) or (manifest and not manifest.startswith("https://")):
            manifest = ""
        limit = repository.get_setting("max_concurrent_recordings")
        try:
            validate_recording_limit(limit)
        except ValueError:
            limit = DEFAULT_CONCURRENT_RECORDINGS
            repository.set_setting("max_concurrent_recordings", limit)
        return cls(
            save_folder=Path(saved), update_manifest_url=manifest, max_concurrent_recordings=limit
        )
