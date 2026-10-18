#!/usr/bin/env python3
"""Podcast Named Speaker Engine (v1.2).

Automatically identifies the real names of the Host and Guest(s) using gpt-5.6-sol,
maps dialogue turns to each named person, and renders character-tracking subtitles
with solid black boxes, white bold italic text, and unique neon role tags.
"""
from __future__ import annotations
import os, sys, json, re, urllib.request, subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Add FFmpeg path if available locally
FFMPEG_DIR = r"C:\Users\ADMIN\.gemini\antigravity\scratch\local-video-forge\.venv\Scripts"
if os.path.exists(FFMPEG_DIR) and FFMPEG_DIR not in os.environ.get('PATH', ''):
    os.environ['PATH'] = FFMPEG_DIR + ";" + os.environ['PATH']

from opus_range_manager import (
    parse_time_range,
    parse_time_code,
    estimate_credits,
    build_targeted_opus_payload,
    submit_targeted_opus_project
)

DEFAULT_MODEL = "gpt-6-astra"
DEFAULT_BASE_URL = "https://vibi.top/v1"
DEFAULT_API_KEY = "sk-WFyafzvimZ8beqwRwzeLmqmdoVsdFZyKlkvyXbhsJB0w6LOG"

# Signature vibrant neon colors for podcast speakers in ASS BGR format:
NEON_PALETTE = [
    "&H0000D7FF&",  # Vivid Warm Gold / Amber (Host)
    "&H0033FF33&",  # Bright Neon Green (Guest 1)
    "&H00FFFF00&",  # Electric Cyan (Guest 2 / Co-Host)
    "&H00FF33FF&",  # Neon Magenta / Pink (Guest 3)
    "&H002222FF&",  # Fiery Bright Red
]

def ts_ass(seconds: float) -> str:
    n = int(round(seconds * 100))
    h, n = divmod(n, 360000)
    m, n = divmod(n, 6000)
    s, c = divmod(n, 100)
    return f"{h}:{m:02}:{s:02}.{c:02}"

def identify_podcast_speakers(
    transcript_words: list[dict],
    metadata_context: str = "",
    model: str = DEFAULT_MODEL
) -> dict:
    """Uses gpt-6-astra (or sol) to identify the exact names of Host and Guest(s)."""
    # Fallback to DEFAULT_MODEL if claude or empty
    if not model or "claude" in str(model).lower():
        model = DEFAULT_MODEL

    import itertools
    # Group words into clean dialogue lines with speaker prefix
    dialogue_lines = []
    for spk, grp in itertools.groupby(transcript_words[:350], key=lambda x: x.get("speaker", "speaker_0")):
        spk_words = [
            w.get("text", "").strip() for w in grp 
            if w.get("text", "").strip() and not w.get("text", "").strip().startswith("__")
        ]
        if spk_words:
            dialogue_lines.append(f"{spk}: {' '.join(spk_words)}")
    sample_dialogue = "\n".join(dialogue_lines[:20])

    detected_speakers = sorted(list(set(w.get("speaker", "speaker_0") for w in transcript_words if w.get("speaker"))))
    if not detected_speakers:
        detected_speakers = ["speaker_0", "speaker_1"]

    prompt = f"""You are an elite podcast dialogue producer.
Identify the real names and roles of the speakers in this podcast video.
Context & Metadata:
{metadata_context}

Intro & Sample Dialogue:
{sample_dialogue}

Discovered Speaker IDs: {detected_speakers}

Task:
1. Identify the real full name and short display tag for each speaker based on who is speaking in the dialogue.
   - For example: if speaker_0 says "post-SFK" or "dating coach", that is Serena Kerrigan (full_name="Serena Kerrigan", display_tag="SERENA", role="GUEST").
   - If speaker_1 is the podcast host interviewing, that is Valeria Lipovetsky (full_name="Valeria Lipovetsky", display_tag="VALERIA", role="HOST").
2. Assign the role: "HOST" or "GUEST".
3. Return valid JSON matching this schema:
{{
  "speakers": {{
    "{detected_speakers[0]}": {{
      "full_name": "Full Name",
      "display_tag": "SHORT_UPPERCASE_NAME",
      "role": "HOST"
    }}
  }}
}}
Return valid JSON only, no markdown, no explanation.
"""

    token = os.environ.get("OPENAI_API_KEY") or DEFAULT_API_KEY
    base_url = (os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    if not token:
        # Fallback without API
        return _fallback_speakers(detected_speakers)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a precise podcast speaker identification engine. Return JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 1000
    }

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw_text = data["choices"][0]["message"].get("content", "").strip()
        
        # Robust JSON extraction from LLM response
        result = _extract_json_payload(raw_text)
        
        # Ensure all detected speakers are mapped and assign colors
        speakers_map = result.get("speakers", {})
        for idx, spk in enumerate(detected_speakers):
            if spk not in speakers_map:
                speakers_map[spk] = {
                    "full_name": f"Speaker {idx+1}",
                    "display_tag": "HOST" if idx == 0 else f"GUEST {idx}",
                    "role": "HOST" if idx == 0 else "GUEST"
                }
            speakers_map[spk]["color"] = NEON_PALETTE[idx % len(NEON_PALETTE)]
            speakers_map[spk]["display_tag"] = speakers_map[spk]["display_tag"].upper()

        return speakers_map
    except Exception as e:
        print(f"[Warning] Speaker identification fallback due to: {e}")
        return _fallback_speakers(detected_speakers)

def _extract_json_payload(raw_text: str) -> dict:
    if not raw_text:
        raise ValueError("Empty response from LLM")
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r'(\{.*\})', raw_text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    return json.loads(raw_text.strip())

def _fallback_speakers(speaker_ids: list[str]) -> dict:
    res = {}
    for idx, spk in enumerate(speaker_ids):
        res[spk] = {
            "full_name": "Host" if idx == 0 else f"Guest {idx}",
            "display_tag": "HOST" if idx == 0 else f"GUEST",
            "role": "HOST" if idx == 0 else "GUEST",
            "color": NEON_PALETTE[idx % len(NEON_PALETTE)]
        }
    return res

def build_punchy_podcast_chunks(words: list[dict], speaker_map: dict, max_words=3, max_gap=0.35) -> list[dict]:
    # Filter out whisper/opus audio artifacts like '__silence'
    valid_words = []
    for w in words:
        raw_t = w.get("text", "").strip()
        if not raw_t or raw_t.startswith("__") or raw_t.lower() in ("silence", "<silence>"):
            continue
        valid_words.append(w)

    chunks = []
    block = []
    for w in valid_words:
        if block:
            gap = w["start"] - block[-1]["end"]
            speaker_changed = (w.get("speaker") != block[-1].get("speaker"))
            if len(block) >= max_words or gap > max_gap or speaker_changed:
                chunks.append(block)
                block = []
        block.append(w)
        if w.get("text", "").rstrip().endswith((".", "?", "!")):
            chunks.append(block)
            block = []
    if block:
        chunks.append(block)

    events = []
    for idx, c in enumerate(chunks, 1):
        st = c[0]["start"]
        ed = c[-1]["end"]
        if ed <= st:
            ed = round(st + 0.35, 3)
        if ed - st < 0.28:
            ed = round(st + 0.28, 3)

        spk_id = c[0].get("speaker", "speaker_0")
        spk_info = speaker_map.get(spk_id, speaker_map.get("speaker_0", {
            "display_tag": "SPEAKER", "color": "&H0033FF33&", "role": "HOST"
        }))

        clean_words = [re.sub(r'[^\w\s\'-]', '', w.get("text", "")).strip().upper() for w in c]
        clean_words = [w for w in clean_words if w]
        text = " ".join(clean_words)
        if text:
            events.append({
                "id": f"pod_{idx:03d}",
                "start": round(st, 3),
                "end": round(ed, 3),
                "speaker_id": spk_id,
                "display_tag": spk_info.get("display_tag", "SPEAKER"),
                "color": spk_info.get("color", "&H0033FF33&"),
                "role": spk_info.get("role", "HOST"),
                "text": text
            })
    return events

def get_podcast_layout_anchor(role: str, speaker_id: str, layout_mode: str = "SPLIT_STACK") -> tuple[int, int]:
    """Returns the (X, Y) coordinate for subtitles following the speaker."""
    if layout_mode == "SPLIT_STACK":
        # Host on top half, Guest on bottom half
        if role == "HOST" or speaker_id == "speaker_0":
            return (540, 840)   # Anchored below top speaker's chest
        else:
            return (540, 1480)  # Anchored below bottom speaker's chest

    elif layout_mode == "WIDE_STUDIO":
        # Host on left, Guest on right
        if role == "HOST" or speaker_id == "speaker_0":
            return (340, 1380)  # Left speaker
        else:
            return (740, 1380)  # Right speaker

    else:
        # ACTIVE_SPEAKER centered safe zone
        return (540, 1420)

def generate_podcast_ass(
    events: list[dict],
    layout_mode: str = "SPLIT_STACK",
    width: int = 1080,
    height: int = 1920,
    out_path: Path = Path("captions_podcast.ass")
) -> Path:
    """Generates ASS subtitles with solid black box and named speaker tracking."""
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # BorderStyle=3 produces solid opaque rectangular black background box behind white text
        "Style: PodcastBox,Arial Black,64,&H00FFFFFF&,&H00000000,&H00000000,&H00000000,1,1,0,0,100,100,0,0,3,13,0,2,20,20,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]

    for ev in events:
        st = ev["start"]
        ed = ev["end"]
        role = ev.get("role", "HOST")
        spk_id = ev.get("speaker_id", "speaker_0")
        tag_name = ev.get("display_tag", "SPEAKER")
        tag_color = ev.get("color", "&H0033FF33&")
        body_text = ev["text"]

        x, y = get_podcast_layout_anchor(role, spk_id, layout_mode)

        # Dialogue event with speaker name tag stacked on top of spoken text
        dialogue = (
            f"Dialogue: 0,{ts_ass(st)},{ts_ass(ed)},PodcastBox,,0,0,0,,"
            f"{{\\pos({x},{y})}}"
            f"{{\\fs38\\c{tag_color}}}{tag_name}:\\N"
            f"{{\\fs64\\c&H00FFFFFF&}}{body_text}"
        )
        lines.append(dialogue)

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path

def render_podcast_clip(
    clip_path: str | Path,
    transcript_words: list[dict],
    metadata_context: str = "",
    layout_mode: str = "SPLIT_STACK",
    out_name: str = "final_podcast_named_captions.mp4"
) -> Path:
    clip_file = Path(clip_path).resolve()
    folder = clip_file.parent

    print(f"[Podcast Engine] Identifying speaker names with {DEFAULT_MODEL}...")
    speakers = identify_podcast_speakers(transcript_words, metadata_context=metadata_context)
    (folder / "podcast_speakers.json").write_text(json.dumps(speakers, indent=2), encoding="utf-8")
    print(f"[Podcast Engine] Identified speakers: {list(speakers.keys())}")
    for k, v in speakers.items():
        print(f"   -> {k}: {v['full_name']} (Display: '{v['display_tag']}:')")

    events = build_punchy_podcast_chunks(transcript_words, speakers)
    (folder / "podcast_events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
    print(f"[Podcast Engine] Built {len(events)} punchy dialogue events.")

    ass_path = folder / "captions_podcast_named.ass"
    generate_podcast_ass(events, layout_mode=layout_mode, out_path=ass_path)
    print(f"[Podcast Engine] Generated ASS subtitle: {ass_path}")

    out_file = folder / out_name
    ass_escaped = str(ass_path).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'").replace(',', '\\,')
    vf = f"ass='{ass_escaped}'"

    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
        '-i', str(clip_file),
        '-map', '0:v:0', '-map', '0:a:0',
        '-vf', vf,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        str(out_file)
    ]

    print(f"[Podcast Engine] Rendering video with FFmpeg (-c:a copy lossless audio)...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg render failed: {res.stderr}")

    print(f"[Podcast Engine] SUCCESS! Saved: {out_file} (Size: {out_file.stat().st_size / (1024*1024):.2f} MB)")
    return out_file

if __name__ == "__main__":
    print("Podcast Named Speaker Engine ready.")
