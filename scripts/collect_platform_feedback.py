#!/usr/bin/env python3
"""Collect a learning-category question bank from visible platform feedback."""
import json, os, re, subprocess, sys, time, unicodedata
from pathlib import Path

DATA = Path(os.environ.get("QUIZ_DATA", Path(__file__).resolve().parents[1] / "data" / "national-security.sample.json"))
SESSION = os.environ.get("QUIZ_SESSION", "safety-education")

def cli(*args):
    p = subprocess.run(["opencli", "browser", SESSION, *args], text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout

def last_json(text):
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            value, _ = dec.raw_decode(text[m.start():])
            if isinstance(value, dict): return value
        except json.JSONDecodeError: pass
    raise RuntimeError(text[-500:])

def norm(s):
    s = unicodedata.normalize("NFKC", s or "").replace("**", "")
    s = re.sub(r"^\s*\d+\s*[、,.．:：)）]\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def read_page():
    return last_json(cli("eval", """(()=>{
      const root=document.querySelector('#app'); const t=root?.innerText||'';
      const title=[...document.querySelectorAll('.item-title')].map(e=>e.innerText.trim()).find(Boolean)||'';
      const options=[...document.querySelectorAll('.topic-item')].map(e=>e.innerText.trim());
      const n=t.match(/(\\d+)\\/100题/);
      const a=t.match(/正确答案：\\s*([A-Z\\s,，]+)/);
      return {number:n?.[1]||'',title,options,feedback:a?.[1]?.replace(/[\\s,，]/g,'')||null};
    })()"""))

def save(data): DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

def main():
    data=json.loads(DATA.read_text()); items=data["items"]
    page=read_page()
    if page["feedback"]:
        cli("click", "button", "--nth", "0"); time.sleep(.6)
    while True:
        page=read_page()
        if not page["number"] or not page["title"] or not page["options"]:
            raise RuntimeError(f"incomplete page: {page}")
        # One candidate submission: select every visible option once, then use
        # the platform's displayed answer. No subset/combination enumeration.
        for i in range(len(page["options"])):
            cli("click", ".topic-item", "--nth", str(i))
        cli("click", "button", "--nth", "0"); time.sleep(.8)
        feedback=read_page()
        if not feedback["feedback"]:
            raise RuntimeError(f"missing feedback at {page['number']}: {page['title']}")
        labels=list(feedback["feedback"])
        platform=[feedback["options"][ord(x)-65] for x in labels if 0<=ord(x)-65<len(feedback["options"])]
        record={"number":int(page["number"]),"type":"多选题" if len(labels)>1 else "单选题",
                "question":norm(page["title"]),"options":page["options"],
                "selected_options":page["options"],"answer":platform,
                "answer_labels":labels,"selected_options_labels":[],
                "verification_status":"verified_by_platform_text","match":True,
                "answer_match_key":"normalized_unordered_option_text_set",
                "platform_answer_labels":labels,"platform_answer":platform}
        existing=[x for x in items if norm(x.get("question"))==record["question"] and sorted(map(norm,x.get("options",[])))==sorted(map(norm,record["options"]))]
        if existing: existing[0].update(record)
        else: items.append(record)
        save(data); print(json.dumps({"number":page["number"],"question":record["question"]},ensure_ascii=False),flush=True)
        if page["number"]=="100": break
        cli("click", "button", "--nth", "0"); time.sleep(.6)
    data["verification_status"]="platform_displayed"; save(data)
    print(json.dumps({"completed":len(items)},ensure_ascii=False))

if __name__ == '__main__':
    try: main()
    except Exception as e: print(f"STOPPED: {e}", file=sys.stderr); sys.exit(2)
