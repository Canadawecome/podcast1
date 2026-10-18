"""Tests for OpusClip Time Range & Credit Optimization (v1.2).

Verifies that time range targeting (curationPref.range, timeRanges, videoRange)
correctly restricts cloud processing to targeted segments (consuming 1-3 credits
instead of 60+ credits for full-length videos).
"""
import pytest
from opus_range_manager import (
    parse_time_code,
    parse_time_range,
    estimate_credits,
    build_targeted_opus_payload,
    submit_targeted_opus_project
)

def test_parse_time_code_various_formats():
    assert parse_time_code(120) == 120.0
    assert parse_time_code(1124.5) == 1124.5
    assert parse_time_code("75.5s") == 75.5
    # MM:SS
    assert parse_time_code("18:44") == 18 * 60 + 44.0  # 1124.0
    assert parse_time_code("01:30") == 90.0
    # HH:MM:SS
    assert parse_time_code("01:04:13") == 3600 + 4 * 60 + 13.0  # 3853.0

def test_parse_time_range_formats():
    expected = (1124.0, 1195.0)
    assert parse_time_range("1124-1195") == expected
    assert parse_time_range("1124:1195") == expected
    assert parse_time_range("1124 to 1195") == expected
    assert parse_time_range("1124, 1195") == expected
    assert parse_time_range([1124, 1195]) == expected
    assert parse_time_range((1124.0, 1195.0)) == expected
    assert parse_time_range("18:44-19:55") == (1124.0, 1195.0)

def test_credit_estimation_savings():
    # Full 64m 13s Serena Kerrigan podcast episode (3853.4s)
    full_duration = 3853.4
    full_credits = estimate_credits(full_duration)
    assert full_credits == 65

    # Targeted clip segment (70.67s)
    clip_duration = 70.67
    clip_credits = estimate_credits(clip_duration)
    assert clip_credits == 2

    # Verify credit reduction
    credits_saved = full_credits - clip_credits
    assert credits_saved == 63
    savings_percentage = (credits_saved / full_credits) * 100
    assert savings_percentage > 95.0  # Saves over 95% of credits!

    # 150s segment -> 3 credits
    assert estimate_credits(150.0) == 3

def test_build_targeted_opus_payload():
    url = "https://www.youtube.com/watch?v=WQpoAfnl3p0"
    payload = build_targeted_opus_payload(
        video_url=url,
        time_range="18:44-19:55",
        custom_prompt="Valeria and Serena discussion on dating standards",
        enable_split_layout=True
    )

    assert payload["videoUrl"] == url
    curation = payload["curationPref"]
    assert curation["range"] == {"startSec": 1124.0, "endSec": 1195.0}
    assert curation["timeRanges"] == [[1124.0, 1195.0]]
    assert payload["timeRanges"] == [[1124.0, 1195.0]]
    assert payload["videoRange"] == [1124.0, 1195.0]

    # Render settings
    render = payload["renderPref"]
    assert render["enableSplitLayout"] is True
    assert render["enableCaption"] is False  # Local high-res styling preferred
    assert render["layoutAspectRatio"] == "portrait"

    # Optimization metadata
    opt = payload["_range_optimization"]
    assert opt["start_sec"] == 1124.0
    assert opt["end_sec"] == 1195.0
    assert opt["duration_sec"] == 71.0
    assert opt["estimated_credits"] == 2

def test_invalid_ranges_rejected():
    url = "https://example.com/podcast.mp4"
    # Negative start
    with pytest.raises(ValueError, match="negative"):
        build_targeted_opus_payload(url, time_range=[-10, 50])
    
    # End <= start
    with pytest.raises(ValueError, match="greater than startSec"):
        build_targeted_opus_payload(url, time_range=[100, 50])
    
    # Span too short (< 30s)
    with pytest.raises(ValueError, match="too short"):
        build_targeted_opus_payload(url, time_range=[100, 115])

def test_dry_run_submission():
    url = "https://www.youtube.com/watch?v=WQpoAfnl3p0"
    res = submit_targeted_opus_project(
        video_url=url,
        time_range=(1124.2, 1194.9),
        custom_prompt="Best hook conversation",
        execute=False
    )
    assert res["status"] == "DRY_RUN"
    assert res["estimated_credits"] == 2
    assert "curationPref" in res["payload"]
    assert res["payload"]["curationPref"]["range"]["startSec"] == 1124.2
