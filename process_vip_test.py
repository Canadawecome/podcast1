#!/usr/bin/env python3
"""VIP Podcast / Interview Test (v1.2).

Video: https://www.youtube.com/watch?v=VRPaXiznKB8&t=233s
Show: Very Important People (Dropout)
Host: Vic Michaelis
Guest: Fanoli (Angela Giarratana)

Runs speech parsing, AI named speaker extraction using gpt-6-astra (vibi.top),
generates solid black box character-tracking subtitles (BorderStyle=3),
and renders with FFmpeg (-c:a copy lossless audio).
"""
import os, sys, json, re, subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from podcast_named_speaker_engine import (
    identify_podcast_speakers,
    build_punchy_podcast_chunks,
    generate_podcast_ass,
    DEFAULT_MODEL
)

OUT_DIR = Path("podcast_vip_clip_001")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 1. Parse VTT subtitle into word-level timestamps relative to 220.0s
vtt_file = Path("vip_sub.en.vtt")
clip_start = 220.0
clip_end = 295.0

print(f"Parsing subtitles for clip window [{clip_start}s - {clip_end}s]...")
text = vtt_file.read_text(encoding="utf-8")

# Extract cues
cues = []
blocks = text.split("\n\n")
for b in blocks:
    m = re.search(r'(\d+:\d+:\d+\.\d+)\s*-->\s*(\d+:\d+:\d+\.\d+)', b)
    if m:
        st_s, ed_s = m.group(1), m.group(2)
        def to_sec(ts):
            h, m_val, s = ts.split(":")
            return int(h)*3600 + int(m_val)*60 + float(s)
        st = to_sec(st_s)
        ed = to_sec(ed_s)
        if st >= clip_start - 1.0 and ed <= clip_end + 1.0:
            lines = [l for l in b.splitlines() if "-->" not in l and l.strip()]
            raw = " ".join(lines)
            clean = re.sub(r'<.*?>', '', raw).replace('&gt;', '').strip()
            if clean:
                cues.append({"start": st, "end": ed, "text": clean})

# Group words into speech turns
words = []
# Split cues into approximate word timings
for c in cues:
    c_st = max(0.0, c["start"] - clip_start)
    c_ed = max(c_st + 0.2, c["end"] - clip_start)
    raw_words = c["text"].split()
    if not raw_words:
        continue
    w_dur = (c_ed - c_st) / len(raw_words)
    for i, w in enumerate(raw_words):
        w_clean = re.sub(r'[\r\n]', '', w).strip()
        if not w_clean or w_clean.lower() in ("screaming", "[screaming]", "[laughter]"):
            continue
        st_w = round(c_st + i * w_dur, 3)
        ed_w = round(st_w + max(0.15, w_dur), 3)
        words.append({"start": st_w, "end": ed_w, "text": w_clean, "speaker": "speaker_unknown"})

# Separate speakers by dialogue turns using alternating patterns or cues
# Notice in VIP: Vic (Host) has shorter reactions/interview questions, Fanoli has lounge singer lines
spk_idx = 0
for i, w in enumerate(words):
    if i > 0 and (words[i]["start"] - words[i-1]["end"] > 0.45 or words[i-1]["text"].endswith((".", "?", "!"))):
        # Heuristic turn alternation
        if any(kw in words[i]["text"].lower() for kw in ("all right", "can i just say", "thank you", "my uncle", "you watch")):
            spk_idx = 1 # Vic
        elif any(kw in words[i]["text"].lower() for kw in ("covid", "marriages", "happy day", "vegas", "blanky")):
            spk_idx = 0 # Fanoli
    words[i]["speaker"] = f"speaker_{spk_idx}"

(OUT_DIR / "words.json").write_text(json.dumps(words, indent=2), encoding="utf-8")
print(f"Extracted {len(words)} aligned words.")

# 2. AI Speaker Identification using gpt-6-astra at vibi.top
context = "Show: Very Important People (VIP). Host: Vic Michaelis (interviewer sitting on right). Guest: Fanoli (Angela Giarratana, legendary lounge singer sitting on left with wig and cape)."
print(f"Running speaker identification with {DEFAULT_MODEL}...")
speakers = identify_podcast_speakers(words, metadata_context=context, model=DEFAULT_MODEL)
(OUT_DIR / "speakers.json").write_text(json.dumps(speakers, indent=2), encoding="utf-8")
print("Identified Speakers:")
for k, v in speakers.items():
    print(f"  {k} -> {v.get('full_name')} (Tag: {v.get('display_tag')}, Role: {v.get('role')})")

# 3. Build punchy chunks
events = build_punchy_podcast_chunks(words, speakers, max_words=3)
(OUT_DIR / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
print(f"Built {len(events)} punchy dialogue events.")

# 4. Generate ASS subtitles
# Video is 1280x720 16:9. We position subtitles at bottom-center safe zone (x=640, y=650)
# with solid black rectangular box and neon speaker tags!
ass_lines = [
    "[Script Info]",
    "ScriptType: v4.00+",
    "PlayResX: 1280",
    "PlayResY: 720",
    "WrapStyle: 2",
    "ScaledBorderAndShadow: yes",
    "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    # BorderStyle=3 produces solid black rectangular box behind white text
    "Style: PodcastBox,Arial Black,40,&H00FFFFFF&,&H00000000,&H00000000,&H00000000,1,1,0,0,100,100,0,0,3,10,0,2,20,20,0,1",
    "",
    "[Events]",
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
]

def ts_ass(seconds: float) -> str:
    n = int(round(seconds * 100))
    h, n = divmod(n, 360000)
    m, n = divmod(n, 6000)
    s, c = divmod(n, 100)
    return f"{h}:{m:02}:{s:02}.{c:02}"

for ev in events:
    st = ev["start"]
    ed = ev["end"]
    role = ev.get("role", "HOST")
    spk_id = ev.get("speaker_id", "speaker_0")
    tag_name = ev.get("display_tag", "SPEAKER")
    tag_color = ev.get("color", "&H0033FF33&")
    body_text = ev["text"]

    # Position: For Fanoli (Guest on left), x=420. For Vic (Host on right), x=860.
    if spk_id == "speaker_0" or role == "GUEST":
        x = 450 # Fanoli side
    else:
        x = 830 # Vic side
    y = 660 # Bottom safe area

    line = (
        f"Dialogue: 0,{ts_ass(st)},{ts_ass(ed)},PodcastBox,,0,0,0,,"
        f"{{\\pos({x},{y})}}"
        f"{{\\fs26\\c{tag_color}}}{tag_name}:\\N"
        f"{{\\fs40\\c&H00FFFFFF&}}{body_text}"
    )
    ass_lines.append(line)

ass_path = OUT_DIR / "vip_captions.ass"
ass_path.write_text("\n".join(ass_lines), encoding="utf-8")
print(f"Generated ASS: {ass_path}")

# 5. Render final video with FFmpeg (-c:a copy preserves original lossless audio)
input_video = Path("vip_clip_720.mp4")
out_video = OUT_DIR / "final_vip_clip.mp4"
ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")
vf = f"ass='{ass_escaped}'"

cmd = [
    'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
    '-i', str(input_video),
    '-map', '0:v:0', '-map', '0:a:0',
    '-vf', vf,
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
    '-c:a', 'copy',
    '-movflags', '+faststart',
    str(out_video)
]

print("Rendering video with FFmpeg (-c:a copy)...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    raise RuntimeError(f"FFmpeg failed: {res.stderr}")

print(f"SUCCESS! Rendered: {out_video} (Size: {out_video.stat().st_size / (1024*1024):.2f} MB)")
