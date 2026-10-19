#!/usr/bin/env python3
"""VIP Episode Subtitle & Character Tracking Generator.

Video: https://www.youtube.com/watch?v=VRPaXiznKB8&t=233s
Episode: Very Important People - Angela Giarratana (Fanoli) & Vic Michaelis
Target Window: 220s - 295s (75s clip covering 233s)
Model: gpt-6-astra at https://vibi.top/v1
Subtitles: Solid black rectangular box behind white bold italic text (BorderStyle=3)
           Character-tracking tags: FANOLI (Gold/Left) and VIC (Green/Right)
Audio: 100% native original audio preserved (-c:a copy)
"""
import os, sys, json, re, subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from podcast_named_speaker_engine import (
    identify_podcast_speakers,
    build_punchy_podcast_chunks,
    DEFAULT_MODEL
)

OUT_DIR = Path("podcast_vip_clip_001")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 1. Parse VTT subtitle cues into clean words and turns
vtt_file = Path("vip_sub.en.vtt")
clip_start = 220.0
clip_end = 295.0

print(f"[VIP] Parsing dialogue from VTT for [{clip_start}s - {clip_end}s]...")
text = vtt_file.read_text(encoding="utf-8")
blocks = text.split("\n\n")

raw_turns = []
for b in blocks:
    m = re.search(r'(\d+:\d+:\d+\.\d+)\s*-->\s*(\d+:\d+:\d+\.\d+)', b)
    if not m:
        continue
    st_s, ed_s = m.group(1), m.group(2)
    def to_sec(ts):
        h, m_val, s = ts.split(":")
        return int(h)*3600 + int(m_val)*60 + float(s)
    st = to_sec(st_s)
    ed = to_sec(ed_s)
    if not (clip_start - 0.5 <= st <= clip_end + 0.5):
        continue
    
    lines = [l for l in b.splitlines() if "-->" not in l and l.strip()]
    for l in lines:
        if "&gt;&gt;" in l:
            # Extract clean text
            cleaned = re.sub(r'<.*?>', '', l).replace('&gt;&gt;', '').strip()
            if cleaned and not cleaned.startswith('[') and len(cleaned) > 1:
                raw_turns.append({"start": st, "end": ed, "text": cleaned})

# Deduplicate consecutive identical lines
dedup_turns = []
for t in raw_turns:
    if not dedup_turns or dedup_turns[-1]["text"] != t["text"]:
        dedup_turns.append(t)

print(f"[VIP] Extracted {len(dedup_turns)} unique dialogue turns.")

# Assign speakers:
# In VIP at 220s:
# Fanoli (Guest): "Any marriages in the house?", "Oh, happy day", "I have COVID", "This is nice", "I can't believe I'm here", "I heard of it", "Look at this", "I never leave Vegas"
# Vic (Host): "All right", "I'm divorced", "INCREDIBLE", "Your voice sounds incredible", "My uncle bought me a record player", "You watch the show?", "We've been trying to track you down"
words = []
cur_spk = "speaker_0" # Fanoli starts at 220s

for t in dedup_turns:
    t_text = t["text"]
    st_rel = max(0.0, t["start"] - clip_start)
    ed_rel = max(st_rel + 0.3, t["end"] - clip_start)

    # Detect speaker turn based on keywords
    vic_cues = ("all right", "divorced", "incredible", "your voice", "my uncle", "listen to your records", "thank you", "watch the show", "track you down", "first guest", "new theme song", "surprising for me")
    fanoli_cues = ("marriages", "happy day", "covid", "this is nice", "never leave vegas", "ripped it out", "blanky", "cut this out", "personality", "can't believe i'm here", "heard of it")

    if any(k in t_text.lower() for k in vic_cues):
        cur_spk = "speaker_1" # Vic (Host)
    elif any(k in t_text.lower() for k in fanoli_cues):
        cur_spk = "speaker_0" # Fanoli (Guest)

    raw_words = t_text.split()
    if not raw_words:
        continue
    w_dur = (ed_rel - st_rel) / len(raw_words)
    for i, w in enumerate(raw_words):
        w_clean = re.sub(r'[^\w\s\'-]', '', w).strip()
        if not w_clean or w_clean.lower() in ("screaming", "laughter", "cheering"):
            continue
        st_w = round(st_rel + i * w_dur, 3)
        ed_w = round(st_w + max(0.18, w_dur), 3)
        words.append({
            "start": st_w,
            "end": ed_w,
            "text": w_clean,
            "speaker": cur_spk
        })

(OUT_DIR / "vip_words.json").write_text(json.dumps(words, indent=2), encoding="utf-8")
print(f"[VIP] Generated {len(words)} aligned words with speaker turns.")

# 2. AI Speaker Identification with gpt-6-astra at vibi.top
meta_context = "Show: Very Important People (Dropout). Host: Vic Michaelis. Guest: Fanoli (Angela Giarratana, legendary Vegas lounge singer)."
print(f"[VIP] Identifying speaker names with {DEFAULT_MODEL}...")
speakers = identify_podcast_speakers(words, metadata_context=meta_context, model=DEFAULT_MODEL)
(OUT_DIR / "vip_speakers.json").write_text(json.dumps(speakers, indent=2), encoding="utf-8")
print("[VIP] Identified Speakers:")
for k, v in speakers.items():
    print(f"   -> {k}: {v.get('full_name')} (Display: '{v.get('display_tag')}:', Role: {v.get('role')})")

# 3. Build punchy chunks
events = build_punchy_podcast_chunks(words, speakers, max_words=3, max_gap=0.35)
(OUT_DIR / "vip_events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
print(f"[VIP] Built {len(events)} punchy dialogue chunks.")

# 4. Generate ASS subtitles with character tracking
# 1280x720 Widescreen layout:
# Fanoli (Guest) sits on LEFT -> x=420, y=650
# Vic (Host) sits on RIGHT    -> x=880, y=650
def ts_ass(seconds: float) -> str:
    n = int(round(seconds * 100))
    h, n = divmod(n, 360000)
    m, n = divmod(n, 6000)
    s, c = divmod(n, 100)
    return f"{h}:{m:02}:{s:02}.{c:02}"

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

for ev in events:
    st = ev["start"]
    ed = ev["end"]
    role = ev.get("role", "HOST")
    spk_id = ev.get("speaker_id", "speaker_0")
    tag_name = ev.get("display_tag", "SPEAKER")
    tag_color = ev.get("color", "&H0033FF33&")
    body_text = ev["text"]

    # Character-tracking position:
    # Fanoli is on the left; Vic is on the right
    if spk_id == "speaker_0" or role == "GUEST" or "FANOLI" in tag_name.upper():
        x = 420
        tag_color = "&H0000D7FF&" # Vivid Warm Amber / Gold
        tag_name = "FANOLI"
    else:
        x = 880
        tag_color = "&H0033FF33&" # Vibrant Neon Green
        tag_name = "VIC"
    y = 650

    line = (
        f"Dialogue: 0,{ts_ass(st)},{ts_ass(ed)},PodcastBox,,0,0,0,,"
        f"{{\\pos({x},{y})}}"
        f"{{\\fs26\\c{tag_color}}}{tag_name}:\\N"
        f"{{\\fs40\\c&H00FFFFFF&}}{body_text}"
    )
    ass_lines.append(line)

ass_path = OUT_DIR / "vip_captions_tracked.ass"
ass_path.write_text("\n".join(ass_lines), encoding="utf-8")
print(f"[VIP] Generated ASS: {ass_path}")

# 5. Render final 16:9 widescreen video with FFmpeg (-c:a copy lossless audio)
input_video = Path("vip_clip_720.mp4")
out_video = OUT_DIR / "final_vip_widescreen_tracked.mp4"
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

print("[VIP] Rendering final 16:9 character-tracked video (-c:a copy)...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    raise RuntimeError(f"FFmpeg render failed: {res.stderr}")

print(f"[VIP] SUCCESS! Saved widescreen: {out_video} ({out_video.stat().st_size / (1024*1024):.2f} MB)")

# 6. Also Render 9:16 Vertical Portrait Split Stack (1080x1920) for Shorts/TikTok!
# Split Stack: Fanoli on top half (crop left side), Vic on bottom half (crop right side)
# ASS for 1080x1920:
ass_916_lines = [
    "[Script Info]",
    "ScriptType: v4.00+",
    "PlayResX: 1080",
    "PlayResY: 1920",
    "WrapStyle: 2",
    "ScaledBorderAndShadow: yes",
    "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    "Style: PodcastBox916,Arial Black,58,&H00FFFFFF&,&H00000000,&H00000000,&H00000000,1,1,0,0,100,100,0,0,3,12,0,2,20,20,0,1",
    "",
    "[Events]",
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
]

for ev in events:
    st = ev["start"]
    ed = ev["end"]
    spk_id = ev.get("speaker_id", "speaker_0")
    tag_name = ev.get("display_tag", "SPEAKER")
    body_text = ev["text"]

    if spk_id == "speaker_0" or "FANOLI" in tag_name.upper():
        tag_color = "&H0000D7FF&"
        tag_name = "FANOLI"
        y = 860 # Top stack (Fanoli)
    else:
        tag_color = "&H0033FF33&"
        tag_name = "VIC"
        y = 1760 # Bottom stack (Vic)

    line = (
        f"Dialogue: 0,{ts_ass(st)},{ts_ass(ed)},PodcastBox916,,0,0,0,,"
        f"{{\\pos(540,{y})}}"
        f"{{\\fs36\\c{tag_color}}}{tag_name}:\\N"
        f"{{\\fs58\\c&H00FFFFFF&}}{body_text}"
    )
    ass_916_lines.append(line)

ass_916_path = OUT_DIR / "vip_captions_split_916.ass"
ass_916_path.write_text("\n".join(ass_916_lines), encoding="utf-8")

# FFmpeg filter:
# Split 1280x720:
# [0:v] split=2 [v1][v2];
# [v1] crop=640:720:100:0, scale=1080:960 [top];   # Fanoli on left
# [v2] crop=640:720:540:0, scale=1080:960 [bot];   # Vic on right
# [top][bot] vstack [v_stacked];
# [v_stacked] ass='vip_captions_split_916.ass' [outv]
out_916_video = OUT_DIR / "final_vip_split_portrait_9_16.mp4"
ass_916_escaped = str(ass_916_path).replace("\\", "/").replace(":", "\\:")
vf_split = (
    f"[0:v]split=2[v1][v2];"
    f"[v1]crop=640:720:100:0,scale=1080:960[top];"
    f"[v2]crop=640:720:540:0,scale=1080:960[bot];"
    f"[top][bot]vstack[stacked];"
    f"[stacked]ass='{ass_916_escaped}'[v]"
)

cmd_916 = [
    'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
    '-i', str(input_video),
    '-filter_complex', vf_split,
    '-map', '[v]', '-map', '0:a:0',
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
    '-c:a', 'copy',
    '-movflags', '+faststart',
    str(out_916_video)
]

print("[VIP] Rendering 9:16 vertical split stack video for Shorts/TikTok (-c:a copy)...")
res_916 = subprocess.run(cmd_916, capture_output=True, text=True)
if res_916.returncode != 0:
    print(f"[VIP Warning] Split stack render notice: {res_916.stderr}")
else:
    print(f"[VIP] SUCCESS! Saved 9:16 vertical video: {out_916_video} ({out_916_video.stat().st_size / (1024*1024):.2f} MB)")
