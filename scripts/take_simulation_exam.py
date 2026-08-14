#!/usr/bin/env python3
"""Answer the GUET safety simulation exam from collected local quiz banks."""
import json, os, re, subprocess, sys, unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = Path(os.environ.get("EXAM_OUT", DATA / "simulation-exam-20260813.json"))
SESSION = "safety-education"
SOURCES = [
    DATA / "anti-fraud-security.sample.json",
    DATA / "fire-safety.sample.json",
    DATA / "national-security.sample.json",
    DATA / "traffic-safety.sample.json",
]

def cli(*args):
    p = subprocess.run(["opencli", "browser", SESSION, *args], text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout

def last_json(text):
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            v, _ = dec.raw_decode(text[m.start():])
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            pass
    raise RuntimeError(f"No JSON: {text[-500:]}")

def norm(s):
    s = unicodedata.normalize("NFKC", s or "").replace("査", "查").replace("**", "")
    s = re.sub(r"^\s*(?:单选题|多选题)\s+", "", s)
    s = re.sub(r"^\s*\d+\s*[、,，.．:：)）]\s*", "", s)
    s = re.sub(r"^\s*[A-Z]\s*[、,，.．:：)）]\s*", "", s)
    return re.sub(r"\s+", " ", s).strip().rstrip("？?")

def read_page():
    return last_json(cli("eval", """(()=>{
      const root=document.querySelector('#app'); const t=root?.innerText||'';
      const title=[...document.querySelectorAll('.item-title')].map(x=>x.innerText.trim()).find(Boolean)||'';
      const options=[...document.querySelectorAll('.topic-item')].map(x=>x.innerText.trim());
      const n=t.match(/(\\d+)\\/100题/);
      return {number:n?.[1]||'',title,options,text:t};
    })()"""))

def records():
    result=[]
    for p in SOURCES:
        d=json.loads(p.read_text())
        for r in d.get('items',[]):
            r=dict(r); r['_source']=p.name; result.append(r)
    return result

def match(local, page):
    q=norm(page['title']); opts=sorted(norm(x) for x in page['options'])
    hits=[r for r in local if norm(r.get('question',''))==q and sorted(norm(o) for o in r.get('options',[]))==opts]
    if len(hits)==1: return hits[0]
    if hits:
        keys={tuple(sorted(norm(x) for x in (r.get('answer') if isinstance(r.get('answer'),list) else [r.get('answer')]))) for r in hits}
        if len(keys)==1: return hits[0]
    return None

def answer_options(record, page):
    ans=record.get('answer'); ans=ans if isinstance(ans,list) else [ans]
    want=Counter(norm(x) for x in ans if x)
    got=[]
    for i, option in enumerate(page['options']):
        key=norm(option)
        if want[key]: got.append(i); want[key]-=1
    if any(want.values()): raise RuntimeError('answer text does not map to page options')
    return got

def infer(page):
    # Conservative fallback for unmatched questions. Uses direct safety rules
    # only when the correct option is unambiguous; otherwise selects option A
    # and flags the record for later review.
    text=norm(page['title'])
    options=page['options']
    positive=[]
    for i,o in enumerate(options):
        v=norm(o)
        if any(k in v for k in ('报警','远离','停止','遵守','正确','安全','低姿','切断电源','戴头盔','不闯红灯')):
            positive.append(i)
    if positive: return positive, 'rule_based_candidate'
    return [0], 'fallback_first_option_needs_review'

def save(log): OUT.write_text(json.dumps(log,ensure_ascii=False,indent=2)+'\n')

def main():
    local=records()
    if OUT.exists():
        log=json.loads(OUT.read_text())
        # A prior buggy run could record the same displayed question repeatedly.
        # Keep the first submitted selection for each number and resume safely.
        unique={}
        for item in log.get('items',[]):
            unique.setdefault(item['display_number'], item)
        log['items']=[unique[n] for n in sorted(unique)]
        log['status']='in_progress'
    else:
        log={'exam':os.environ.get('EXAM_KIND','simulation'),'started_at':datetime.now(timezone.utc).isoformat(),'sources':[p.name for p in SOURCES],'items':[],'status':'in_progress'}
    save(log)
    page=read_page()
    if not page['number']: raise RuntimeError(f'Exam not active: {page["text"][:400]}')
    while True:
        page=read_page(); rec=match(local,page)
        if rec:
            indices=answer_options(rec,page); origin='local_bank'; source=rec['_source']
        else:
            indices,origin=infer(page); source=None
        for i in indices: cli('click','.topic-item','--nth',str(i))
        item={'display_number':int(page['number']),'question':norm(page['title']),'options':page['options'],'selected_options':[page['options'][i] for i in indices],'origin':origin,'source':source}
        log['items']=[x for x in log['items'] if x['display_number'] != item['display_number']]
        log['items'].append(item)
        log['items'].sort(key=lambda x:x['display_number'])
        save(log)
        print(json.dumps({'number':page['number'],'origin':origin,'question':norm(page['title'])},ensure_ascii=False),flush=True)
        if page['number']=='100':
            break
        cli('click','--role','button','--name','下一题'); cli('wait','time','0.6')
        advanced=read_page()
        if advanced['number'] == page['number']:
            raise RuntimeError(f"question did not advance from {page['number']}")
    log['status']='ready_to_submit'; save(log)
    print(json.dumps({'status':'ready_to_submit','items':len(log['items'])},ensure_ascii=False))

if __name__=='__main__':
    try: main()
    except Exception as e:
        print('STOPPED:',e,file=sys.stderr); sys.exit(2)
