#!/usr/bin/env python3
"""Explicit opt-in OpusClip POST with time-range credit optimization.

Supports:
1. Batch jobs file via `--jobs` (standard workflow).
2. Direct URL with targeted time-range via `--video-url` and `--time-range` / `--start-sec` & `--end-sec`
   to restrict OpusClip processing to 1-3 minutes (consuming only 1-3 credits instead of 60+ credits for full video).
"""
from __future__ import annotations
import argparse, json, os, urllib.request, urllib.error
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / '.env')
except ImportError:
    pass

from opus_range_manager import (
    build_targeted_opus_payload,
    submit_targeted_opus_project,
    estimate_credits,
    parse_time_range
)

def submit(jobs: Path, output: Path, execute=False, max_projects=8):
    data = json.loads(jobs.read_text(encoding='utf8'))
    if data.get('schema_version') not in ('podcast-v1', 'podcast-v1.1'):
        raise ValueError('Unsupported jobs schema')
    if not execute:
        return {'status': 'DRY_RUN', 'jobs': len(data['jobs']), 'budget_limit_projects': max_projects}
    if len(data['jobs']) > max_projects:
        raise ValueError('OPUS_PROJECT_BUDGET_EXCEEDED: review list; increase --max-projects explicitly')
    token = os.environ.get('OPUSCLIP_API_KEY')
    if not token:
        raise ValueError('OPUSCLIP_API_KEY missing')
    if output.exists():
        raise FileExistsError('Refuse accidental resubmission of existing results')
    results = []
    for job in data['jobs']:
        req = urllib.request.Request(
            'https://api.opus.pro/api/clip-projects',
            method='POST',
            headers={
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
            },
            data=json.dumps(job['request']).encode('utf8')
        )
        try:
            with urllib.request.urlopen(req, timeout=75) as r:
                payload = json.loads(r.read())
            results.append({
                'group_id': job.get('group_id'),
                'candidate_ids': job.get('candidate_ids', [job.get('candidate_id')]),
                'status': 'SUBMITTED',
                'result': payload
            })
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf8', errors='ignore')
            results.append({
                'group_id': job.get('group_id'),
                'candidate_ids': job.get('candidate_ids', [job.get('candidate_id')]),
                'status': 'ERROR',
                'http_code': e.code,
                'error_body': err_body
            })
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'schema_version': data['schema_version'], 'results': results}, indent=2), encoding='utf8')
    return {'status': 'SUBMISSIONS_ATTEMPTED', 'results': len(results)}

def main():
    p = argparse.ArgumentParser(description="Submit OpusClip clip projects with optional range & credit optimization.")
    p.add_argument('--jobs', type=Path, help="Path to pre-planned jobs JSON file")
    p.add_argument('--output', type=Path, help="Output JSON path to save submission results")
    p.add_argument('--execute', action='store_true', help="Actually submit to OpusClip API (otherwise dry run)")
    p.add_argument('--max-projects', type=int, default=8, help="Budget safeguard for batch submissions")
    
    # Direct targeted URL submission options
    p.add_argument('--video-url', type=str, help="Direct video URL (YouTube, MP4, etc.)")
    p.add_argument('--time-range', type=str, help="Time range e.g. '18:44-19:55' or '1124-1195'")
    p.add_argument('--start-sec', type=float, help="Start time in seconds")
    p.add_argument('--end-sec', type=float, help="End time in seconds")
    p.add_argument('--prompt', type=str, default="", help="Custom prompt describing desired clip content")
    p.add_argument('--split-layout', action='store_true', default=True, help="Enable vertical split layout for multi-person podcasts")

    a = p.parse_args()

    if a.jobs:
        if not a.output:
            raise ValueError("--output is required when using --jobs")
        print(json.dumps(submit(a.jobs, a.output, a.execute, a.max_projects), indent=2))
    elif a.video_url:
        range_arg = a.time_range
        if not range_arg and a.start_sec is not None and a.end_sec is not None:
            range_arg = (a.start_sec, a.end_sec)
        
        res = submit_targeted_opus_project(
            video_url=a.video_url,
            time_range=range_arg,
            custom_prompt=a.prompt,
            enable_split_layout=a.split_layout,
            execute=a.execute
        )
        if a.output:
            a.output.parent.mkdir(parents=True, exist_ok=True)
            a.output.write_text(json.dumps(res, indent=2), encoding="utf-8")
            print(f"Result written to {a.output}")
        print(json.dumps(res, indent=2))
    else:
        p.print_help()
        raise ValueError("Must provide either --jobs or --video-url")

if __name__ == '__main__':
    main()
