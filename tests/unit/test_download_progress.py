import json

import pytest
from yt_dlp import YoutubeDL

from youtube_live_recorder.services.download_progress import (
    PLAN_TEMPLATE,
    PROGRESS_TEMPLATE,
    ProgressTracker,
)


def plan(tracker, formats, duration=10):
    tracker.feed("YLR_PLAN " + json.dumps({"formats": formats, "duration": duration}))


def event(tracker, identifier, downloaded, **extra):
    tracker.feed(
        "YLR_PROGRESS "
        + json.dumps(
            {
                "format_id": identifier,
                "status": "downloading",
                "downloaded": downloaded,
                "speed": 100,
                **extra,
            }
        )
    )


def test_separate_video_audio_are_aggregated_without_premature_completion():
    updates = []
    tracker = ProgressTracker(updates.append, clock=lambda: 100)
    plan(tracker, [{"format_id": "v", "filesize": 800}, {"format_id": "a", "filesize": 200}])
    event(tracker, "v", 400)
    assert (updates[-1].total_bytes, updates[-1].percent, updates[-1].eta_seconds) == (1000, 40, 6)
    event(tracker, "v", 800, status="finished")
    assert updates[-1].percent == 80 and not updates[-1].transfer_finished
    event(tracker, "v", 800, status="finished")
    event(tracker, "a", 100)
    assert updates[-1].downloaded_bytes == 900 and updates[-1].percent == 90
    event(tracker, "a", 200, status="finished")
    assert updates[-1].percent == 100 and updates[-1].transfer_finished


def test_bitrate_estimate_replaced_by_actual_sizes_and_freshness_expires():
    updates = []
    tracker = ProgressTracker(updates.append, clock=lambda: 100)
    plan(tracker, [{"format_id": "v", "tbr": 80}, {"format_id": "a", "filesize_approx": 1000}])
    assert updates[-1].total_bytes == 101000 and updates[-1].estimated
    event(tracker, "v", 500, total=1000)
    assert updates[-1].total_bytes == 2000 and updates[-1].eta_seconds == 15
    assert not updates[-1].is_stale(110) and updates[-1].is_stale(116)
    event(tracker, "v", 1000, status="finished")
    event(tracker, "a", 400, total=500)
    assert updates[-1].total_bytes == 1500 and not updates[-1].estimated


def test_unknown_audio_size_does_not_show_video_percentage_as_whole_download():
    updates = []
    tracker = ProgressTracker(updates.append)
    plan(tracker, [{"format_id": "v", "filesize": 800}, {"format_id": "a"}])
    event(tracker, "v", 400)
    assert updates[-1].total_bytes is None and updates[-1].percent is None
    assert updates[-1].eta_seconds is None
    event(tracker, "a", 50, estimate=100, speed=None)
    assert updates[-1].total_bytes == 900 and updates[-1].percent == 50
    assert updates[-1].eta_seconds is None


def test_late_stdout_plan_keeps_stderr_progress_and_no_premature_100():
    updates = []
    tracker = ProgressTracker(updates.append)
    event(tracker, "v", 1000, status="finished")
    assert updates[-1].percent is None and not updates[-1].transfer_finished
    plan(tracker, [{"format_id": "v", "filesize_approx": 500}, {"format_id": "a", "filesize": 100}])
    assert updates[-1].downloaded_bytes == 1000 and updates[-1].total_bytes == 1100
    assert not updates[-1].transfer_finished


@pytest.mark.parametrize("value", [None, "NA", -10, True, float("nan"), float("inf")])
def test_invalid_numbers_do_not_generate_misleading_estimates(value):
    updates = []
    tracker = ProgressTracker(updates.append)
    plan(tracker, [{"format_id": "v", "filesize": value, "tbr": value}], duration=value)
    event(tracker, "v", value, total=value, speed=value)
    assert updates[-1].downloaded_bytes == 0 and updates[-1].percent is None
    assert updates[-1].eta_seconds is None
    assert tracker.feed("YLR_PROGRESS invalid json")
    assert not tracker.feed("ERROR: disconnected")


def test_underestimated_size_cannot_reach_100_until_transfer_finishes():
    updates = []
    tracker = ProgressTracker(updates.append)
    plan(tracker, [{"format_id": "v", "filesize_approx": 100}])
    event(tracker, "v", 200)
    assert updates[-1].percent == 99.9 and not updates[-1].transfer_finished
    event(tracker, "v", 220, status="finished")
    assert updates[-1].percent == 100 and updates[-1].total_bytes == 220


def test_installed_ytdlp_templates_round_trip_without_urls_or_fragments():
    updates = []
    tracker = ProgressTracker(updates.append)
    info = {
        "format_id": "v+a",
        "duration": 10,
        "requested_formats": [
            {"format_id": "v", "filesize": 800, "url": "SECRET", "fragments": ["SECRET"]},
            {"format_id": "a", "filesize": 200},
        ],
    }
    with YoutubeDL({"quiet": True}) as downloader:
        line = downloader.evaluate_outtmpl(PLAN_TEMPLATE.split(":", 1)[1], info)
        assert "SECRET" not in line
        tracker.feed(line)
        tracker.feed(
            downloader.evaluate_outtmpl(
                PROGRESS_TEMPLATE.split(":", 1)[1],
                {
                    "info": {"format_id": "v"},
                    "progress": {"status": "downloading", "downloaded_bytes": 400, "speed": 100},
                },
            )
        )
    assert updates[-1].percent == 40 and updates[-1].eta_seconds == 6
