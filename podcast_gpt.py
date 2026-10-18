#!/usr/bin/env python3
"""Optional GPT 2-pass adapter for English US/UK PODCASTS. Requires OpenAI API key.

Models see supplied transcript text plus sampled time-stamped frames. This does not
constitute listening to source audio; listening-quality QC is a separate stage.
"""
from __future__ import annotations
import argparse,base64,json,os,re,urllib.request,urllib.error
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / '.env')
except ImportError:
    pass
from podcast_contracts import PrecutPlan,PostReview
from podcast_media import digest
from podcast_director import transcript


DEFAULT_MODEL = 'gpt-6-astra'
DEFAULT_BASE_URL = 'https://vibi.top/v1'
DEFAULT_API_KEY = 'sk-WFyafzvimZ8beqwRwzeLmqmdoVsdFZyKlkvyXbhsJB0w6LOG'

def ask(model:str|None=DEFAULT_MODEL,prompt:str='',context:str='',evidence:Path|None=None,max_images:int=12,window:tuple[float,float]|None=None)->dict:
    if not model or 'claude' in str(model).lower():
        model = DEFAULT_MODEL
    token=os.environ.get('OPENAI_API_KEY') or DEFAULT_API_KEY
    if not token:raise RuntimeError('OPENAI_API_KEY missing; the local spec works without API calls')
    base_url=(os.environ.get('OPENAI_BASE_URL') or DEFAULT_BASE_URL).rstrip('/')
    
    selected_frames=[]
    if evidence:
        data=json.loads(Path(evidence).read_text(encoding='utf8'))
        frames=data.get('frames',[])
        if window:
            frames=[f for f in frames if window[0]-2 <= f['seconds'] <= window[1]+2]
        if len(frames)>max_images:
            idx=sorted({round(i*(len(frames)-1)/(max_images-1)) for i in range(max_images)})
            frames=[frames[i] for i in idx]
        selected_frames=frames

    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    if '/responses' in base_url or base_url.endswith('/responses'):
        endpoint=base_url
        content=[{'type':'input_text','text':prompt+'\n\n'+context}]
        for f in selected_frames:
            pic=Path(evidence).parent/f['path']
            content.append({'type':'input_text','text':f"Frame {f['id']} at {f['seconds']} seconds"})
            content.append({'type':'input_image','image_url':'data:image/jpeg;base64,'+
                            base64.b64encode(pic.read_bytes()).decode('ascii'),'detail':'low'})
        payload={'model':model,'input':[{'role':'user','content':content}],'max_output_tokens':5000}
    else:
        endpoint=base_url if base_url.endswith('/chat/completions') else base_url+'/chat/completions'
        if selected_frames:
            parts=[{'type':'text','text':prompt+'\n\n'+context}]
            for f in selected_frames:
                pic=Path(evidence).parent/f['path']
                parts.append({'type':'text','text':f"Frame {f['id']} at {f['seconds']} seconds"})
                parts.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+
                             base64.b64encode(pic.read_bytes()).decode('ascii'),'detail':'low'}})
            payload={'model':model,'messages':[{'role':'user','content':parts}],'max_tokens':4000}
        else:
            payload={'model':model,'messages':[{'role':'user','content':prompt+'\n\n'+context}],'max_tokens':4000}

    request=urllib.request.Request(endpoint,method='POST',headers=headers,data=json.dumps(payload).encode('utf8'))
    out = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request,timeout=120) as r:out=json.loads(r.read())
            break
        except Exception as e:
            if attempt < 2:
                import time
                time.sleep(2 * (attempt + 1))
                continue
    if out is None:
        return {'candidates':[]}
    
    if 'choices' in out and out['choices']:
        msg = out['choices'][0].get('message', {})
        text = msg.get('content') or ''
        if not text and msg.get('reasoning_content'):
            rc = msg.get('reasoning_content')
            m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', rc, re.DOTALL) or re.search(r'(\{[\s\S]*"candidates"[\s\S]*\})', rc)
            if m:
                text = m.group(1)
        if not text and 'text' in msg: text = msg['text']
        text = (text or '').strip()
    elif 'output' in out:
        text='\n'.join(part.get('text','') for msg in out.get('output',[]) if msg.get('type')=='message'
                       for part in msg.get('content',[]) if part.get('type')=='output_text').strip()
    else:
        text=str(out)

    if not text:
        return {'candidates':[]}

    text=re.sub(r'^```(?:json)?\s*|\s*```$','',text,flags=re.I).strip()
    try:
        return json.loads(text)
    except Exception:
        m=re.search(r'\{.*\}',text,re.DOTALL)
        if m:
            try:return json.loads(m.group(0))
            except Exception:pass
        return {'candidates':[]}

PRE='''You are an expert video editor cutting licensed English dialogue footage (podcasts, talk shows, documentaries, interviews, reality patrol & real-world bodycam encounters) for vertical shorts.
Read verified word-timed transcript. Identify coherent standalone 70-100s engaging dialogue moments (e.g., tense exchanges, questioning, confrontations, story moments).
Return JSON object: {"candidates":[{"id":"p1","start":...,"end":...,"hook_quote":"EXACT speaker quote from transcript","payoff_quote":"EXACT speaker quote", "transcript_evidence":"EXACT transcript excerpt","why_compelling":"...","predicted_potential_score":0-100,"confidence":0-1}, ...]}.
Never fabricate or paraphrase direct quotes. Both hook_quote and payoff_quote must be verbatim substrings from the transcript words. Choose start and end strictly on whole sentence or clean speaker-turn boundaries; preserve counterpoints and nuance. No deception through omission.
These frame samples are visual snapshots only. Transcript has the dialogue; do not claim you listened to the voices. Score is editorial potential, not actual virality prediction.
Duration (end - start) MUST be between 70.0 and 100.0 seconds. Leave candidates empty only if completely unsuitable.'''
POST='''You are independently reviewing a REAL Opus exported English podcast MP4. Transcript is word-timed from THIS exported clip, not a source clip summary.
Return JSON exactly matching PostReview schema: candidate_id,clip_sha256,transcript_sha256,schema_version="podcast-v1",
scores {hook,meaning,audio_emotion,framing,pacing,caption_readiness} integer 0-100,complete_thought,meaning_not_distorted,begins_at_natural_boundary,ends_at_natural_boundary,clear_english_dialogue,speaker_framing_ok,rights_verified=false,source_mapping_verified=false,review_confidence (0-1),evidence_note,recut_instruction.
Do not claim to certify audio cleanness from transcript/frames; if uncertain about actual audible clarity, set clear_english_dialogue=false pending listening QC. Rights and source mapping are ALWAYS false in your model draft: they need external review and evidence.
Judge integrity: quote in context, not clipped mid-thought, complete takeaway, visible speaker and reactions. Score potential quality only, not guaranteed views.'''


def chunks(tx, duration:float, window_sec:float=360, overlap_sec:float=115):
    """Window long podcast transcripts in overlapping 6min windows.

    A 70-100s moment can lie near chunk boundary; overlap retains candidate evidence.
    """
    if window_sec<=150 or not (100<=overlap_sec<window_sec):
        raise ValueError('Invalid transcript chunk window or overlap')
    out=[];t=0.0;stride=window_sec-overlap_sec
    while t<duration:
        e=min(duration,t+window_sec)
        selected=[w for w in tx.words if t<=w.start<e]
        if selected:out.append((round(t,3),round(e,3),selected))
        if e>=duration:break
        t+=stride
    return out


def submit_precut(media:Path,tx_file:Path,out_file:Path,model:str=DEFAULT_MODEL,evidence:Path|None=None,
                  max_chunks:int=36):
    tx=transcript(tx_file,media)
    from podcast_media import probe
    total=probe(media)['duration']
    parts=chunks(tx,total)
    if len(parts)>max_chunks:
        raise ValueError('SOURCE_TOO_LONG_FOR_CURRENT_BUDGET: increase max_chunks explicitly')
    candidates=[]
    for i,(a,b,words_in_window) in enumerate(parts):
        print(f"[{i+1}/{len(parts)}] Analyzing window {a:.1f}s - {b:.1f}s ({len(words_in_window)} words)...", flush=True)
        ctx=json.dumps({'source_time_window':[a,b], 'source_duration_sec':total,
             'words':[w.model_dump() for w in words_in_window]},ensure_ascii=False)
        data=ask(model,PRE,ctx,evidence,window=(a,b))
        raw_c = data.get('candidates',[])
        print(f"    -> Found {len(raw_c)} candidate(s)", flush=True)
        for row in raw_c:
            row=dict(row);row['id']=f"w{i+1:03d}_{row.get('id','candidate')}"
            if row['start']<a-.2 or row['end']>b+.2:continue
            candidates.append(row)
    # Overlap-aware dedup before costly Opus jobs.
    candidates.sort(key=lambda c:c['predicted_potential_score'],reverse=True)
    selected=[]
    for c in candidates:
        if any(max(0,min(c['end'],r['end'])-max(c['start'],r['start'])) /
               min(c['end']-c['start'],r['end']-r['start']) > .8 for r in selected):continue
        selected.append(c)
        if len(selected)>=25:break
    if not selected:raise ValueError('NO_COHERENT_PODCAST_MOMENTS: manual review source')
    result=PrecutPlan.model_validate({'source_sha256':digest(media),'transcript_sha256':digest(tx_file),
                                     'rights_verified':False,'candidates':selected})
    out_file.parent.mkdir(parents=True,exist_ok=True)
    out_file.write_text(result.model_dump_json(indent=2),encoding='utf8')
    return {'status':'DRAFT_REQUIRES_SOURCE_RIGHTS_REVIEW','source_chunks':len(parts),
            'candidates':len(result.candidates)}


def submit_review(folder:Path,candidate:str,out_file:Path,model:str=DEFAULT_MODEL,evidence:Path|None=None):
    clip=folder/'clip.mp4'; tx=folder/'clip_transcript.json';trans=transcript(tx,clip)
    # Review transcription is from ACTUAL Opus exported MP4, not creator-original.
    ctx=json.dumps({'candidate_id':candidate,'clip_sha256':digest(clip),'transcript_sha256':digest(tx),
                    'words':[w.model_dump() for w in trans.words[:550]]},ensure_ascii=False)
    data=ask(model,POST,ctx,evidence)
    data.update({'schema_version':'podcast-v1','candidate_id':candidate,'clip_sha256':digest(clip),
                 'transcript_sha256':digest(tx),'rights_verified':False,'source_mapping_verified':False,
                 'clear_english_dialogue':False})  # must be confirmed by actually LISTENING
    result=PostReview.model_validate(data)
    out_file.parent.mkdir(parents=True,exist_ok=True);out_file.write_text(result.model_dump_json(indent=2),encoding='utf8')
    return {'status':'REQUIRES_HUMAN_RIGHTS_MAPPING_AND_AUDIO_CHECK','score':result.scores.total()}


def main():
    p=argparse.ArgumentParser();cmd=p.add_subparsers(dest='action',required=True)
    a=cmd.add_parser('precut');a.add_argument('--media',type=Path,required=True);a.add_argument('--transcript',type=Path,required=True)
    a.add_argument('--evidence',type=Path);a.add_argument('--model',default=DEFAULT_MODEL);a.add_argument('--out',type=Path,required=True)
    a=cmd.add_parser('review');a.add_argument('--folder',type=Path,required=True);a.add_argument('--candidate',required=True)
    a.add_argument('--evidence',type=Path);a.add_argument('--model',default=DEFAULT_MODEL);a.add_argument('--out',type=Path,required=True)
    x=p.parse_args()
    result=submit_precut(x.media,x.transcript,x.out,x.model,x.evidence) if x.action=='precut' else submit_review(x.folder,x.candidate,x.out,x.model,x.evidence)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
