from youtube_live_recorder.data.models import BroadcastStatus, SessionStatus


def _values(items) -> str:
    return ",".join(f"'{item.value}'" for item in items)


MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        f"""CREATE TABLE broadcasts (
            id TEXT PRIMARY KEY,
            video_id TEXT NOT NULL,
            original_url TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            channel_name TEXT NOT NULL DEFAULT '',
            thumbnail_url TEXT NOT NULL DEFAULT '',
            scheduled_start_at TEXT,
            actual_start_at TEXT,
            registered_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ({_values(BroadcastStatus)})),
            preferred_quality TEXT NOT NULL CHECK(preferred_quality IN ('720p','1080p','best')),
            custom_filename TEXT NOT NULL DEFAULT '',
            last_polled_at TEXT,
            next_check_at TEXT,
            last_error_code TEXT,
            poll_failures INTEGER NOT NULL DEFAULT 0 CHECK(poll_failures >= 0),
            permission_confirmed INTEGER NOT NULL CHECK(permission_confirmed = 1),
            updated_at TEXT NOT NULL
        )""",
        """CREATE UNIQUE INDEX unique_active_video ON broadcasts(video_id)
           WHERE status NOT IN ('COMPLETED','CANCELLED','REPLAY_EXPIRED')""",
        "CREATE INDEX broadcast_due ON broadcasts(status, next_check_at, registered_at)",
        f"""CREATE TABLE recording_sessions (
            id TEXT PRIMARY KEY,
            broadcast_id TEXT NOT NULL REFERENCES broadcasts(id),
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL CHECK(status IN ({_values(SessionStatus)})),
            mode TEXT NOT NULL CHECK(mode IN ('LIVE','REPLAY')),
            selected_quality TEXT NOT NULL CHECK(selected_quality IN ('720p','1080p','best')),
            actual_quality TEXT,
            output_path TEXT,
            duration_seconds REAL CHECK(duration_seconds >= 0),
            size_bytes INTEGER NOT NULL DEFAULT 0 CHECK(size_bytes >= 0),
            ffprobe_ok INTEGER NOT NULL DEFAULT 0 CHECK(ffprobe_ok IN (0,1)),
            failure_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(status != 'COMPLETE' OR
                (ffprobe_ok = 1 AND output_path IS NOT NULL AND
                 duration_seconds IS NOT NULL AND duration_seconds > 0 AND size_bytes > 0))
        )""",
        """CREATE UNIQUE INDEX single_active_session ON recording_sessions((1))
           WHERE status IN ('CREATED','RUNNING','RECONNECTING','FINALIZING','VERIFYING')""",
        """CREATE TABLE recording_segments (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES recording_sessions(id),
            segment_index INTEGER NOT NULL CHECK(segment_index >= 0),
            temporary_path TEXT NOT NULL,
            final_path TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL CHECK(status IN
                ('WRITING','RECOVERING','COMPLETE','PARTIAL','FAILED')),
            bytes_written INTEGER NOT NULL DEFAULT 0 CHECK(bytes_written >= 0),
            UNIQUE(session_id, segment_index)
        )""",
        """CREATE TABLE replay_jobs (
            id TEXT PRIMARY KEY,
            broadcast_id TEXT NOT NULL UNIQUE REFERENCES broadcasts(id),
            status TEXT NOT NULL CHECK(status IN ('WAITING','DOWNLOADING','COMPLETE','EXPIRED')),
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            deadline_at TEXT,
            next_check_at TEXT NOT NULL,
            last_attempt_at TEXT,
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
            output_path TEXT,
            error_code TEXT
        )""",
        """CREATE TABLE app_settings (
            key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE app_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TEXT NOT NULL,
            severity TEXT NOT NULL,
            category TEXT NOT NULL,
            broadcast_id TEXT REFERENCES broadcasts(id),
            session_id TEXT REFERENCES recording_sessions(id),
            error_code TEXT,
            message TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}'
        )""",
    ),
    2: (
        "ALTER TABLE broadcasts ADD COLUMN first_detected_at TEXT",
        "ALTER TABLE broadcasts ADD COLUMN live_state TEXT NOT NULL DEFAULT 'unknown'",
        "ALTER TABLE recording_sessions ADD COLUMN work_directory TEXT",
        "ALTER TABLE recording_sessions ADD COLUMN coverage_note TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE recording_sessions ADD COLUMN from_start_attempted INTEGER NOT NULL DEFAULT 0",
    ),
    3: (
        "ALTER TABLE recording_sessions ADD COLUMN recovery_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE recording_segments ADD COLUMN duration_seconds REAL",
        "ALTER TABLE recording_segments ADD COLUMN height INTEGER",
        "ALTER TABLE recording_segments ADD COLUMN failure_reason TEXT",
    ),
}

SCHEMA_VERSION = max(MIGRATIONS)
