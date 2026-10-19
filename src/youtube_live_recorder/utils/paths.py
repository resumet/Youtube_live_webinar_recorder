import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "YouTubeLiveRecorder"


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @classmethod
    def discover(cls, override: Path | None = None) -> "AppPaths":
        if override is not None:
            return cls(override.expanduser().resolve())
        explicit = os.environ.get("YLR_DATA_DIR")
        if explicit:
            return cls(Path(explicit).expanduser().resolve())
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
        return cls(base / APP_NAME)

    @property
    def database(self) -> Path:
        return self.root / "data" / "app.db"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)


def default_save_folder() -> Path:
    from youtube_live_recorder.utils.known_folders import videos_folder

    return videos_folder() / APP_NAME
