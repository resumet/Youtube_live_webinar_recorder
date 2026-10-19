import logging
from dataclasses import dataclass
from pathlib import Path

from youtube_live_recorder.config import Settings
from youtube_live_recorder.data.db import Database
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.utils.logging import configure_logging
from youtube_live_recorder.utils.paths import AppPaths


@dataclass(frozen=True)
class ApplicationContext:
    paths: AppPaths
    database: Database
    repository: Repository
    settings: Settings
    logger: logging.Logger


def bootstrap(data_dir: Path | None = None) -> ApplicationContext:
    paths = AppPaths.discover(data_dir)
    paths.ensure()
    logger = configure_logging(paths.logs)
    database = Database(paths.database)
    database.initialize()
    repository = Repository(database)
    settings = Settings.load(repository)
    logger.info("프로그램 초기화 완료")
    return ApplicationContext(paths, database, repository, settings, logger)
