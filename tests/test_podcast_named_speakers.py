import json, pytest
from pathlib import Path
from podcast_named_speaker_engine import (
    identify_podcast_speakers,
    build_punchy_podcast_chunks,
    get_podcast_layout_anchor,
    generate_podcast_ass,
    _fallback_speakers,
    DEFAULT_MODEL
)

def test_default_model_is_astra():
    assert DEFAULT_MODEL == "gpt-6-astra"

def test_fallback_speakers():
    speakers = _fallback_speakers(["speaker_0", "speaker_1"])
    assert "speaker_0" in speakers
    assert speakers["speaker_0"]["role"] == "HOST"
    assert "speaker_1" in speakers
    assert speakers["speaker_1"]["role"] == "GUEST"

def test_build_punchy_podcast_chunks():
    words = [
        {"start": 0.0, "end": 0.5, "text": "Welcome", "speaker": "speaker_0"},
        {"start": 0.5, "end": 1.0, "text": "everyone", "speaker": "speaker_0"},
        {"start": 1.0, "end": 1.5, "text": "today.", "speaker": "speaker_0"},
        {"start": 1.6, "end": 2.2, "text": "Thanks", "speaker": "speaker_1"},
        {"start": 2.2, "end": 2.8, "text": "Joe.", "speaker": "speaker_1"},
    ]
    speakers = {
        "speaker_0": {"display_tag": "ROGAN", "color": "&H0000D7FF&", "role": "HOST"},
        "speaker_1": {"display_tag": "ELON", "color": "&H0033FF33&", "role": "GUEST"}
    }
    chunks = build_punchy_podcast_chunks(words, speakers)
    assert len(chunks) == 2
    assert chunks[0]["display_tag"] == "ROGAN"
    assert chunks[0]["text"] == "WELCOME EVERYONE TODAY"
    assert chunks[1]["display_tag"] == "ELON"
    assert chunks[1]["text"] == "THANKS JOE"

def test_podcast_layout_anchors():
    # Split stack
    h_x, h_y = get_podcast_layout_anchor("HOST", "speaker_0", "SPLIT_STACK")
    g_x, g_y = get_podcast_layout_anchor("GUEST", "speaker_1", "SPLIT_STACK")
    assert h_y < g_y  # Host is above Guest
    assert h_x == 540 and g_x == 540

    # Wide studio
    h_w_x, h_w_y = get_podcast_layout_anchor("HOST", "speaker_0", "WIDE_STUDIO")
    g_w_x, g_w_y = get_podcast_layout_anchor("GUEST", "speaker_1", "WIDE_STUDIO")
    assert h_w_x < g_w_x  # Host is left of Guest

def test_generate_podcast_ass(tmp_path):
    events = [
        {
            "start": 0.5,
            "end": 2.0,
            "speaker_id": "speaker_0",
            "display_tag": "ROGAN",
            "color": "&H0000D7FF&",
            "role": "HOST",
            "text": "THIS IS INCREDIBLE"
        }
    ]
    ass_file = tmp_path / "test.ass"
    generate_podcast_ass(events, layout_mode="SPLIT_STACK", out_path=ass_file)
    content = ass_file.read_text(encoding="utf-8")
    assert "BorderStyle, Outline, Shadow" in content
    assert "Style: PodcastBox,Arial Black,64" in content
    assert "ROGAN:\\N" in content
    assert "THIS IS INCREDIBLE" in content
