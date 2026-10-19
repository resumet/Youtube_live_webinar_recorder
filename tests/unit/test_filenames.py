from datetime import UTC, datetime

import pytest

from youtube_live_recorder.utils.filenames import (
    recording_name,
    reservation_marker,
    reserve_output,
    safe_stem,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CON", "_CON"),
        ("AUX.txt", "_AUX.txt"),
        ("LPT¹", "_LPT¹"),
        ("../강의:제목?.mp4", "_강의_제목_"),
        ("  .  ", "방송"),
        ("사용자 이름.mp4", "사용자 이름"),
    ],
)
def test_windows_filename_sanitization(raw, expected):
    assert safe_stem(raw) == expected


def test_utf16_path_length_and_seoul_actual_start_date():
    assert len(safe_stem("😀" * 100).encode("utf-16-le")) // 2 <= 140
    date = datetime(2026, 10, 18, 15, 30, tzinfo=UTC)
    assert recording_name("방송", date) == "2026-10-19_방송.mp4"
    assert recording_name("방송", date, "직접 입력", replay=True) == "직접 입력_다시보기.mp4"


def test_reservation_preserves_existing_files_and_other_reservations(tmp_path):
    existing = tmp_path / "방송.mp4"
    existing.write_bytes(b"original")
    first = reserve_output(tmp_path, "방송.mp4")
    second = reserve_output(tmp_path, "방송.mp4")
    assert first.name == "방송 (2).mp4" and second.name == "방송 (3).mp4"
    assert existing.read_bytes() == b"original"
    assert not first.exists() and reservation_marker(first).exists()
