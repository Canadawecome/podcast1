#!/usr/bin/env python3
"""OpusClip Time Range & Credit Optimizer (v1.2).

Allows passing `timeRanges` / `videoRange` / `curationPref.range` to OpusClip API requests.
Instead of processing an entire 1-hour or 2-hour long video (which consumes 60-120+ credits),
restricts processing to an exact segment (e.g. 60-180s), consuming only 1 to 3 credits!
"""
from __future__ import annotations
import math, os, re, json, urllib.request, urllib.error
from pathlib import Path
from typing import Tuple, List, Union, Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

def parse_time_code(val: Union[str, float, int]) -> float:
    """Parses seconds, MM:SS, or HH:MM:SS format into seconds float."""
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower().rstrip("s")
    if ":" in s:
        parts = [float(p) for p in s.split(":")]
        if len(parts) == 2:
            # MM:SS
            return parts[0] * 60.0 + parts[1]
        elif len(parts) == 3:
            # HH:MM:SS
            return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
        else:
            raise ValueError(f"Invalid timestamp format: {val}")
    return float(s)

def parse_time_range(val: Union[str, tuple, list]) -> Tuple[float, float]:
    """Parses various range formats into (start_sec, end_sec).
    
    Accepts:
    - (1124.0, 1195.0) or [1124, 1195]
    - "1124-1195" or "1124:1195" or "1124 to 1195" or "1124, 1195"
    - "18:44-19:55" or "00:18:44 to 00:19:55"
    """
    if isinstance(val, (list, tuple)):
        if len(val) != 2:
            raise ValueError(f"Time range list/tuple must have exactly 2 elements (start, end), got {val}")
        st = parse_time_code(val[0])
        ed = parse_time_code(val[1])
        return (round(st, 3), round(ed, 3))
    
    s = str(val).strip()
    # Check for "to" or "," separator
    if " to " in s:
        p1, p2 = s.split(" to ", 1)
    elif "," in s:
        p1, p2 = s.split(",", 1)
    elif "-" in s and not s.startswith("-"):
        # Could be "18:44-19:55" or "1124-1195"
        p1, p2 = s.split("-", 1)
    elif ":" in s and s.count(":") == 1 and not re.search(r'\d+:\d+:\d+', s):
        # "1124:1195"
        p1, p2 = s.split(":", 1)
    else:
        raise ValueError(f"Could not parse time range from '{val}'. Expected format like '18:44-19:55' or '1124-1195'")
    
    st = parse_time_code(p1)
    ed = parse_time_code(p2)
    return (round(st, 3), round(ed, 3))

def estimate_credits(duration_sec: float) -> int:
    """Calculates OpusClip credits required (1 credit per minute, rounded up)."""
    if duration_sec <= 0:
        return 0
    return max(1, math.ceil(duration_sec / 60.0))

def build_targeted_opus_payload(
    video_url: str,
    time_range: Optional[Union[str, tuple, list]] = None,
    custom_prompt: str = "",
    clip_durations: Optional[List[List[int]]] = None,
    enable_split_layout: bool = True,
    aspect_ratio: str = "portrait"
) -> dict:
    """Constructs an OpusClip project creation payload with strict time-range targeting."""
    if not video_url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid video URL: {video_url}")

    curation_pref = {
        "model": "ClipAnything",
        "clipDurations": clip_durations or [[60, 90]],
        "customPrompt": custom_prompt or "Find the best viral podcast conversation."
    }

    payload = {
        "videoUrl": video_url,
        "curationPref": curation_pref,
        "renderPref": {
            "layoutAspectRatio": aspect_ratio,
            "enableCaption": False,
            "enableEmoji": False,
            "enableBroll": False,
            "quickstartConfig": {
                "enableRemoveFillerWords": False
            },
            "enableSplitLayout": enable_split_layout
        }
    }

    if time_range is not None:
        st, ed = parse_time_range(time_range)
        if st < 0:
            raise ValueError(f"startSec cannot be negative, got {st}")
        if ed <= st:
            raise ValueError(f"endSec ({ed}s) must be greater than startSec ({st}s)")
        span = ed - st
        if span < 30.0:
            raise ValueError(f"Time range span ({span:.1f}s) is too short. OpusClip requires at least 30s-60s for clipping.")

        # Range targeting fields supported by OpusClip API to restrict processing:
        curation_pref["range"] = {
            "startSec": round(st, 2),
            "endSec": round(ed, 2)
        }
        curation_pref["timeRanges"] = [[round(st, 2), round(ed, 2)]]
        payload["timeRanges"] = [[round(st, 2), round(ed, 2)]]
        payload["videoRange"] = [round(st, 2), round(ed, 2)]

        # Attach metadata helper
        payload["_range_optimization"] = {
            "start_sec": st,
            "end_sec": ed,
            "duration_sec": span,
            "estimated_credits": estimate_credits(span),
            "note": f"Restricted to {span:.1f}s window ({span/60.0:.2f} min) -> ~{estimate_credits(span)} credits."
        }

    return payload

def submit_targeted_opus_project(
    video_url: str,
    time_range: Optional[Union[str, tuple, list]] = None,
    custom_prompt: str = "",
    clip_durations: Optional[List[List[int]]] = None,
    enable_split_layout: bool = True,
    execute: bool = False
) -> dict:
    """Submits a time-restricted clip project to OpusClip.
    
    If execute=False (default), performs a dry-run returning the payload and credit estimation.
    """
    payload = build_targeted_opus_payload(
        video_url=video_url,
        time_range=time_range,
        custom_prompt=custom_prompt,
        clip_durations=clip_durations,
        enable_split_layout=enable_split_layout
    )

    opt = payload.get("_range_optimization")
    if opt:
        print(f"[Opus Range Optimizer] Targeted window: {opt['start_sec']}s - {opt['end_sec']}s ({opt['duration_sec']}s)")
        print(f"[Opus Range Optimizer] Estimated credits: ~{opt['estimated_credits']} credit(s)")
    else:
        print(f"[Opus Range Optimizer] Warning: No time_range provided! Full video will be processed (may cost 60-100+ credits).")

    if not execute:
        return {
            "status": "DRY_RUN",
            "payload": payload,
            "estimated_credits": opt["estimated_credits"] if opt else "UNRESTRICTED_FULL_VIDEO"
        }

    token = os.environ.get("OPUSCLIP_API_KEY")
    if not token:
        raise ValueError("OPUSCLIP_API_KEY environment variable missing")

    # Clean out internal metadata before sending to API
    api_payload = {k: v for k, v in payload.items() if not k.startswith("_")}
    if "_range_optimization" in api_payload.get("curationPref", {}):
        api_payload["curationPref"].pop("_range_optimization", None)

    req = urllib.request.Request(
        "https://api.opus.pro/api/clip-projects",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        },
        data=json.dumps(api_payload).encode("utf-8")
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "status": "SUBMITTED",
                "project_id": data.get("id", data.get("data", {}).get("id")),
                "response": data,
                "range_optimization": opt
            }
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpusClip API error (HTTP {e.code}): {err_body}")
