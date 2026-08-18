#!/usr/bin/env python3
"""Reverify the current safety-education learning page one question at a time."""
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from pathlib import Path

DATA = Path(os.environ.get("QUIZ_DATA", Path(__file__).resolve().parents[1] / "data" / "anti-fraud-security.sample.json"))
SESSION = os.environ.get("QUIZ_SESSION", "safety-education")


def cli(*args):
    p = subprocess.run(["opencli", "browser", SESSION, *args], text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout


def last_json(text):
    decoder = json.JSONDecoder()
    for index in (m.start() for m in re.finditer(r"\{", text)):
        try:
            value, end = decoder.raw_decode(text[index:])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"No JSON result: {text[-500:]}")


def norm(value):
    value = unicodedata.normalize("NFKC", value or "").replace("査", "查")
    # The learning page occasionally exposes Markdown emphasis markers in text.
    value = value.replace("**", "")
    value = re.sub(r"^\s*\d+\s*[、,，.．:：)）]\s*", "", value)
    value = re.sub(r"^\s*[A-Da-d]\s*[、,，.．:：)）]\s*", "", value)
    value = re.sub(r"[？?]$", "", value)
    return re.sub(r"\s+", " ", value).strip()


def split_title(title):
    return title.split("\n", 1)[-1]


def read_page():
    return last_json(cli("eval", """(()=>{
      const t=document.querySelector('#app')?.innerText||'';
      const title=[...document.querySelectorAll('.item-title')].map(e=>e.innerText.trim()).find(Boolean)||'';
      const options=[...document.querySelectorAll('.topic-item')].map(e=>e.innerText.trim());
      const m=t.match(/(\\d+)\\/100题/);
      const a=t.match(/正确答案：\\s*([A-Z\\s]+)/);
      return {number:m?.[1]||'',title,options,feedback:a?.[1]?.replace(/\\s/g,'')||null};
    })()"""))


def find_record(items, page):
    q = norm(split_title(page["title"]))
    page_options = sorted(norm(x) for x in page["options"])
    candidates = [x for x in items if norm(x.get("question")) == q]
    candidates = [x for x in candidates if sorted(norm(o) for o in x.get("options", [])) == page_options]
    if len(candidates) == 1:
        return candidates[0]
    # Duplicate source records are safe to collapse only when their answer
    # texts are identical; otherwise the page identity is genuinely ambiguous.
    if candidates:
        answer_keys = {tuple(sorted(norm(x) for x in answer_texts(c))) for c in candidates}
        if len(answer_keys) == 1:
            return candidates[0]
    return None


def answer_texts(record):
    value = record.get("answer")
    return value if isinstance(value, list) else [value]


def main():
    data = json.loads(DATA.read_text())
    items = data["items"]
    completed = 0
    page = read_page()
    # The caller leaves the browser on a feedback view. Advance exactly once.
    if page["feedback"]:
        cli("click", "button", "--nth", "0")
        cli("wait", "time", "0.5")

    while True:
        page = read_page()
        record = find_record(items, page)
        if record is None:
            raise RuntimeError(f"No unique local record for page {page['number']}: {page['title']}")
        wanted_list = [norm(x) for x in answer_texts(record) if x]
        available = Counter(norm(option) for option in page["options"])
        wanted_counts = Counter(wanted_list)
        if not wanted_list or any(available[key] < count for key, count in wanted_counts.items()):
            raise RuntimeError(f"Answer text does not map to page options at {page['number']}: {page['title']}")
        remaining = wanted_counts.copy()
        indices = []
        for index, option in enumerate(page["options"]):
            key = norm(option)
            if remaining[key] > 0:
                indices.append(index)
                remaining[key] -= 1
        for index in indices:
            cli("click", ".topic-item", "--nth", str(index))
        cli("click", "button", "--nth", "0")
        cli("wait", "time", "0.7")
        feedback = read_page()
        if not feedback["feedback"]:
            raise RuntimeError(f"Missing platform feedback at {page['number']}: {page['title']}")
        labels = list(feedback["feedback"])
        platform = sorted(norm(feedback["options"][ord(label)-65]) for label in labels if 0 <= ord(label)-65 < len(feedback["options"]))
        expected = sorted(wanted_list)
        record["verification_status"] = "verified_by_platform_text" if platform == expected else "needs_review"
        record["match"] = platform == expected
        record["verification_note"] = f"Platform feedback {feedback['feedback']} compared using normalized unordered option text."
        record["platform_answer_labels"] = list(feedback["feedback"])
        record["platform_answer"] = [feedback["options"][ord(label)-65] for label in labels if 0 <= ord(label)-65 < len(feedback["options"])]
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        completed += 1
        print(json.dumps({"number": page["number"], "question": split_title(page["title"]), "match": record["match"]}, ensure_ascii=False), flush=True)
        if page["number"] == "100":
            cli("click", "button", "--nth", "0")
            break
        cli("click", "button", "--nth", "0")
        cli("wait", "time", "0.5")
    print(json.dumps({"completed": completed}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        sys.exit(2)
