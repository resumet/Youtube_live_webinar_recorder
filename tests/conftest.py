import pytest

from youtube_live_recorder.data.db import Database
from youtube_live_recorder.data.repository import Repository


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / "data" / "app.db")
    db.initialize()
    return db


@pytest.fixture
def repository(database):
    return Repository(database)
