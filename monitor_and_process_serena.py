import os, sys, json, time, urllib.request, urllib.parse, subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
token = os.environ.get('OPUSCLIP_API_KEY')
if not token:
    raise ValueError("Missing OPUSCLIP_API_KEY")

from opus_export_manager import get_clips, download
from podcast_named_speaker_engine import (
    identify_podcast_speakers,
    build_punchy_podcast_chunks,
    generate_podcast_ass,
    DEFAULT_MODEL
)

PID = "P3101716rPEk"
OUT_DIR = Path("podcast_serena_clip_001")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def check_stage(pid):
    req = urllib.request.Request(
        f'https://api.opus.pro/api/clip-projects/{pid}',
        headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'Mozilla/5.0'}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        payload = data.get('data', data)
        return payload.get('stage'), payload.get('progress')

print(f"Monitoring OpusClip project {PID} for Serena Kerrigan & Valeria Lipovetsky podcast...")
start_time = time.time()
while time.time() - start_time < 900:
    try:
        stage, progress = check_stage(PID)
        print(f"[{time.strftime('%X')}] Project {PID}: stage={stage}, progress={progress}", flush=True)
        if stage in ('COMPLETE', 'COMPLETED'):
            break
        elif stage in ('FAILED', 'ERROR'):
            raise RuntimeError(f"OpusClip project failed with stage: {stage}")
    except Exception as e:
        print(f"Poll notice: {e}", flush=True)
    time.sleep(15)

print("\nFetching exportable clips from OpusClip...")
clips_list = get_clips(PID, execute=True)
if not clips_list:
    raise RuntimeError("No exportable clips found")

print(f"Discovered {len(clips_list)} exportable clips from OpusClip.")
# Select best clip (preferably 60-90s)
selected_clip = None
for c in clips_list:
    dur = c.get('duration_provider_sec', 0)
    if 50.0 <= dur <= 100.0:
        selected_clip = c
        break
if not selected_clip:
    selected_clip = clips_list[0]

clip_id = selected_clip['id']
print(f"Selected clip {clip_id} (Duration: {selected_clip.get('duration_provider_sec')}s)")
(OUT_DIR / "clip_meta.json").write_text(json.dumps(selected_clip, indent=2), encoding="utf-8")

# Download clip video
clip_file = OUT_DIR / "clip.mp4"
if not clip_file.exists() or clip_file.stat().st_size < 1000:
    print(f"Downloading clip video to {clip_file}...")
    download(selected_clip, clip_file, execute=True)
    print("Download completed!")
else:
    print(f"Clip video already present at {clip_file} ({clip_file.stat().st_size / (1024*1024):.2f} MB)")

# Fetch word-aligned transcript from Opus source timeline and slice for this clip
import opus_transcript_manager
print(f"Fetching source-level transcript for project {PID}...")
tx_res = opus_transcript_manager.fetch(PID, execute=True)

# Determine clip source time range
clip_range = selected_clip.get('ranges_sec', [[0, selected_clip.get('duration_provider_sec', 60)]])[0]
clip_start, clip_end = clip_range[0], clip_range[1]
print(f"Slicing transcript for clip window: {clip_start:.2f}s - {clip_end:.2f}s...")

raw_clip_words = [
    w for w in tx_res.get('words', [])
    if clip_start <= w['start'] <= clip_end
]

# Normalize words relative to clip start
words = []
for w in raw_clip_words:
    st = max(0.0, w['start'] - clip_start)
    ed = max(st + 0.1, w['end'] - clip_start)
    text = w.get('text', '')
    spk = w.get('speaker', 'speaker_0')
    words.append({'start': round(st, 3), 'end': round(ed, 3), 'text': text, 'speaker': spk})

(OUT_DIR / "clip_transcript.json").write_text(json.dumps({"words": words}, indent=2), encoding="utf-8")
print(f"Saved {len(words)} aligned words to {OUT_DIR / 'clip_transcript.json'}")

# Run AI Speaker Name Identification with gpt-6-astra
meta_context = "Podcast: The Real Reason You Keep Attracting the Wrong Men. Host: Valeria Lipovetsky. Guest: Serena Kerrigan (SFK, confidence & dating coach)."
print(f"Running speaker identification with {DEFAULT_MODEL}...")
speakers = identify_podcast_speakers(words, metadata_context=meta_context, model=DEFAULT_MODEL)
(OUT_DIR / "speakers.json").write_text(json.dumps(speakers, indent=2), encoding="utf-8")
print("Identified Speakers:")
for k, v in speakers.items():
    print(f"  {k} -> {v.get('full_name')} (Tag: {v.get('display_tag')}, Role: {v.get('role')})")

# Build punchy chunks
events = build_punchy_podcast_chunks(words, speakers)
(OUT_DIR / "podcast_events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
print(f"Created {len(events)} punchy dialogue events.")

# Generate ASS with solid black box and speaker tracking
# ACTIVE_SPEAKER layout places subtitles at lower-third safe zone (y=1420)
ass_path = OUT_DIR / "captions_podcast_named.ass"
generate_podcast_ass(events, layout_mode="ACTIVE_SPEAKER", out_path=ass_path)
print(f"Generated ASS: {ass_path}")

# Render final video with FFmpeg (-c:a copy preserves 100% native audio)
out_file = OUT_DIR / "final_podcast_named_captions.mp4"
ass_escaped = str(ass_path).replace('\\', '/').replace(':', '\\:')
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

print(f"Rendering final podcast video with FFmpeg...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    raise RuntimeError(f"FFmpeg failed: {res.stderr}")

print(f"SUCCESS! Output saved: {out_file} ({out_file.stat().st_size / (1024*1024):.2f} MB)")

