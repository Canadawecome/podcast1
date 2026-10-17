#!/usr/bin/env python3
"""Opus source transcript fetch + strictly time-coded paragraph/word normalization.

Project transcript timestamps refer to the project's SOURCE (possibly a billed range),
not automatically to Opus's re-ordered exported clip. Never treat this output as
clip word timings; exported MP4 needs independent clip-aligned ASR/timing.
"""
from __future__ import annotations
import argparse,json,os,urllib.parse,urllib.request
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / '.env')
except ImportError:
    pass

ENDPOINT='https://api.opus.pro/api/transcripts'

def normalized(data:dict):
    wrappers=data.get('data')
    if not isinstance(wrappers,list) or not wrappers or wrappers[0] is None:
        raise ValueError('OPUS_TRANSCRIPT_PENDING_OR_MISSING')
    paragraphs=wrappers[0]
    if not isinstance(paragraphs,list):raise ValueError('UNEXPECTED_TRANSCRIPT_SCHEMA')
    result=[]
    for p in paragraphs:
        if not isinstance(p,dict):raise ValueError('INVALID_TRANSCRIPT_PARAGRAPH')
        if not isinstance(p.get('words'),list):raise ValueError('NO_ALIGNED_WORDS')
        for w in p['words']:
            if not isinstance(w,dict) or not all(k in w for k in ('start','end','word')):
                raise ValueError('BAD_WORD_TIMING')
            st,ed=float(w['start']),float(w['end'])
            if st<0 or ed<st:raise ValueError('BAD_WORD_INTERVAL')
            if ed<=st:ed=st+0.05
            result.append({'start':st,'end':ed,'text':str(w['word']),
                           'speaker':p.get('speaker') or 'unknown'})
    result.sort(key=lambda x:x['start'])
    if not result:raise ValueError('NO_TRANSCRIPT_WORDS')
    return {'timebase':'OPUS_PROJECT_SOURCE_TIMELINE_NOT_EXPORTED_CLIP',
            'words':result,'paragraph_count':len(paragraphs),'speaker_labels_are_unverified':True}

def fetch(project_id:str,execute=False):
    url=ENDPOINT+'?'+urllib.parse.urlencode({'q':'findByProjectId','projectId':project_id})
    if not execute:return {'status':'DRY_RUN','url':url}
    key=os.getenv('OPUSCLIP_API_KEY')
    if not key:raise ValueError('OPUSCLIP_API_KEY missing')
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+key,'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req,timeout=60) as resp:data=json.loads(resp.read())
    return normalized(data)

def main():
    p=argparse.ArgumentParser();p.add_argument('--project-id');p.add_argument('--response-json',type=Path)
    p.add_argument('--execute',action='store_true');p.add_argument('--out',type=Path,required=True)
    x=p.parse_args()
    if not x.project_id and not x.response_json:raise ValueError('Supply project id or JSON response')
    result=normalized(json.loads(x.response_json.read_text())) if x.response_json else fetch(x.project_id,x.execute)
    x.out.parent.mkdir(parents=True,exist_ok=True);x.out.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({'status':'WRITTEN','out':str(x.out)},indent=2))
if __name__=='__main__':main()
