#!/usr/bin/env python3
"""Run the GUET online safety exam using the local verified quiz banks.

Credentials are prompted interactively and are never written to disk, stdout,
or command arguments.  The script stops safely for an unmatched question so
the calling agent can reason about it and resume with an explicit answer.
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RUNS_DIR = DATA_DIR / "exam-runs"
PLATFORM_URL = "https://gdse.guet.edu.cn/#/"
BANKS = (
    "anti-fraud-security.sample.json",
    "fire-safety.sample.json",
    "national-security.sample.json",
    "traffic-safety.sample.json",
)


def parse_json(text: str) -> dict[str, Any] | list[Any]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
            if isinstance(value, (dict, list)):
                return value
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"Expected JSON from OpenCLI: {text[-500:]}")


def normalize(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").replace("査", "查").replace("**", "")
    value = re.sub(r"^\s*(?:单选题|多选题)\s+", "", value)
    value = re.sub(r"^\s*\d+\s*[、,，.．:：)）]\s*", "", value)
    value = re.sub(r"^\s*[A-Z]\s*[、,，.．:：)）]\s*", "", value)
    return re.sub(r"\s+", " ", value).strip().rstrip("？?")


class Browser:
    def __init__(self, session: str):
        self.session = session

    def run(self, *args: str) -> str:
        process = subprocess.run(
            ["opencli", "browser", self.session, *args], text=True, capture_output=True
        )
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or process.stdout.strip())
        return process.stdout

    def try_run(self, *args: str) -> bool:
        try:
            self.run(*args)
            return True
        except RuntimeError:
            return False

    def open(self, url: str) -> None:
        self.run("open", url)
        self.run("wait", "time", "1")

    def eval(self, javascript: str) -> Any:
        return parse_json(self.run("eval", javascript))

    def click_button(self, label: str) -> None:
        if self.try_run("click", "--role", "button", "--name", label):
            return
        # Vant's login button is rendered as “登 录”, with presentation
        # whitespace that does not always match its semantic name.
        if label == "登录" and self.try_run("click", "button", "--nth", "0"):
            return
        raise RuntimeError(f"Could not click button: {label}")

    def click_css(self, selector: str, nth: int) -> None:
        self.run("click", selector, "--nth", str(nth))

    def fill_css(self, selector: str, nth: int, value: str) -> None:
        self.run("fill", selector, value, "--nth", str(nth))

    def state(self) -> str:
        return self.run("state")


def preflight(session: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "python": sys.version.split()[0],
        "node": shutil.which("node"),
        "opencli": shutil.which("opencli"),
        "codex": shutil.which("codex"),
        "banks": {},
        "errors": [],
    }
    if sys.version_info < (3, 10):
        report["errors"].append("Python 3.10 or newer is required.")
    if not report["node"]:
        report["errors"].append("Node.js is missing. Install Node.js 20+.")
    if not report["opencli"]:
        report["errors"].append("OpenCLI is missing. Install/configure OpenCLI and its Chrome extension.")
    if not report["codex"]:
        report["errors"].append("Codex CLI was not found in PATH; run this Skill from a Codex agent environment.")
    records = 0
    for filename in BANKS:
        path = DATA_DIR / filename
        try:
            data = json.loads(path.read_text())
            items = data.get("items", [])
            valid = isinstance(items, list) and bool(items) and all(
                item.get("question") and item.get("options") and item.get("answer")
                for item in items
            )
            report["banks"][filename] = {"records": len(items), "valid": valid}
            records += len(items)
            if not valid:
                report["errors"].append(f"Invalid or incomplete quiz bank: {filename}")
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            report["banks"][filename] = {"error": str(exc)}
            report["errors"].append(f"Missing or unreadable quiz bank: {filename}")
    report["bank_records"] = records
    if report["opencli"]:
        doctor = subprocess.run(["opencli", "doctor"], text=True, capture_output=True)
        report["opencli_doctor"] = doctor.stdout.strip()
        if doctor.returncode or "Everything looks good!" not in doctor.stdout:
            report["errors"].append("OpenCLI doctor did not confirm a connected Chrome extension.")
    return report


def load_records() -> list[dict[str, Any]]:
    result = []
    for filename in BANKS:
        for item in json.loads((DATA_DIR / filename).read_text()).get("items", []):
            record = dict(item)
            record["_source"] = filename
            result.append(record)
    return result


def read_view(browser: Browser) -> dict[str, Any]:
    return browser.eval(
        """(()=>{
          const root=document.querySelector('#app'); const text=root?.innerText||'';
          const title=[...document.querySelectorAll('.item-title')].map(e=>e.innerText.trim()).find(Boolean)||'';
          const options=[...document.querySelectorAll('.topic-item')].map(e=>e.innerText.trim());
          const number=text.match(/(\\d+)\\/100题/);
          const inputs=[...document.querySelectorAll('input')].map((e,i)=>({i,type:e.type,name:e.name,placeholder:e.placeholder,checked:e.checked}));
          return {url:location.href,text,title,options,number:number?.[1]||'',inputs};
        })()"""
    )


def click_visible_text(browser: Browser, text: str) -> None:
    """Resolve a visible leaf by text, then click its current OpenCLI ref."""
    entries = parse_json(browser.run("find", "--text", text, "--limit", "10"))
    for entry in entries.get("entries", []):
        if entry.get("visible") and entry.get("text", "").strip() == text:
            browser.run("click", str(entry["ref"]))
            return
    raise RuntimeError(f"Could not find visible control text: {text}")


def click_link_containing(browser: Browser, text: str) -> bool:
    """Click a visible link by stable displayed text without hard-coding its route."""
    entries = parse_json(browser.run("find", "--css", "a", "--limit", "20"))
    for entry in entries.get("entries", []):
        if entry.get("visible") and text in entry.get("text", ""):
            browser.run("click", str(entry["ref"]))
            return True
    return False


def download_directory() -> str:
    process = subprocess.run(["xdg-user-dir", "DOWNLOAD"], text=True, capture_output=True)
    if process.returncode == 0 and process.stdout.strip():
        return process.stdout.strip()
    return str(Path.home() / "Downloads")


def login(browser: Browser, remember_account: bool, credentials_stdin: bool = False) -> None:
    browser.open(PLATFORM_URL)
    view = read_view(browser)
    if "打开安全大门" in view["text"]:
        click_visible_text(browser, "打开安全大门")
        browser.run("wait", "time", "1")
    view = read_view(browser)
    if "登录" not in view["text"]:
        raise RuntimeError("The platform did not reach the login view.")
    inputs = view["inputs"]
    password = next((item for item in inputs if item["type"] == "password"), None)
    identities = [item for item in inputs if item["type"] not in {"password", "checkbox", "hidden"}]
    if not password or not identities:
        raise RuntimeError("Could not identify the ID-number and password fields.")
    if credentials_stdin:
        id_number = sys.stdin.readline().strip()
        secret = sys.stdin.readline().strip()
    else:
        id_number = input("身份证号: ").strip()
        secret = getpass.getpass("密码（默认身份证后6位）: ")
    if not id_number:
        raise RuntimeError("An identity number is required for login.")
    if not secret:
        secret = id_number[-6:]
    browser.fill_css("input", identities[0]["i"], id_number)
    browser.fill_css("input", password["i"], secret)
    checkbox = next((item for item in inputs if item["type"] == "checkbox"), None)
    if checkbox:
        action = "check" if remember_account else "uncheck"
        browser.run(action, "input", "--nth", str(checkbox["i"]))
    browser.click_button("登录")
    browser.run("wait", "time", "2")
    after = read_view(browser)
    if "登录" in after["text"] or "身份证" in after["text"]:
        raise RuntimeError("Login did not complete. Check the credentials or platform response.")


def find_record(records: list[dict[str, Any]], page: dict[str, Any]) -> dict[str, Any] | None:
    question = normalize(page["title"])
    options = sorted(normalize(option) for option in page["options"])
    hits = [
        item
        for item in records
        if normalize(item.get("question")) == question
        and sorted(normalize(option) for option in item.get("options", [])) == options
    ]
    if len(hits) == 1:
        return hits[0]
    if hits:
        answer_keys = {
            tuple(sorted(normalize(value) for value in (item["answer"] if isinstance(item["answer"], list) else [item["answer"]])))
            for item in hits
        }
        if len(answer_keys) == 1:
            return hits[0]
    return None


def answer_indices(record: dict[str, Any], page: dict[str, Any]) -> list[int]:
    answer = record["answer"] if isinstance(record["answer"], list) else [record["answer"]]
    required = Counter(normalize(value) for value in answer)
    indices = []
    for index, option in enumerate(page["options"]):
        key = normalize(option)
        if required[key]:
            indices.append(index)
            required[key] -= 1
    if any(required.values()):
        raise RuntimeError("Stored answer cannot be mapped to the current option texts.")
    return indices


def run_path(run_id: str | None) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    return RUNS_DIR / f"online-exam-{stamp}.json"


def save(path: Path, record: dict[str, Any]) -> None:
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")


def enter_online_exam(browser: Browser) -> None:
    """Use visible UI navigation; state snapshots prevent silent route drift."""
    view = read_view(browser)
    if "考试" not in view["text"]:
        raise RuntimeError("Expected the safety-education home page after login.")
    browser.run("click", "--role", "tab", "--name", "考试")
    browser.run("wait", "time", "1")
    view = read_view(browser)
    if "在线考试" not in view["text"]:
        raise RuntimeError("Could not find the 在线考试 entry after opening the 考试 tab.")
    click_visible_text(browser, "在线考试")
    browser.run("wait", "time", "1")
    view = read_view(browser)
    if "开始考试" not in view["text"]:
        raise RuntimeError("Online exam start page did not load.")
    browser.click_button("开始考试")
    browser.run("wait", "time", "1")
    if not read_view(browser)["number"]:
        raise RuntimeError("Online exam did not enter the question view.")


def submit_and_download(browser: Browser, record: dict[str, Any], output: Path) -> None:
    browser.click_button("交卷")
    browser.run("wait", "time", "1")
    view = read_view(browser)
    score_match = re.search(r"本次成绩\s*分\s*(\d+)|本次成绩\D*(\d+)", view["text"])
    score = int(next(group for group in score_match.groups() if group)) if score_match else None
    record["result"] = {"score": score, "result_page_text": view["text"]}
    record["status"] = "passed" if score == 100 else "failed_or_unreadable"
    save(output, record)
    if score != 100:
        raise RuntimeError(f"Online exam was not passed with 100%; reported score: {score}")
    # Some platform versions expose a direct result-page download, while others
    # expose the certificate only after opening the submitted-exam detail page.
    for label in ("下载证书", "下载", "安全教育学习考试证书", "查看我的证书"):
        if label in view["text"] and browser.try_run("click", "--role", "button", "--name", label):
            # “查看我的证书” opens the certificate page rather than downloading.
            if label == "查看我的证书":
                browser.run("wait", "time", "1")
                view = read_view(browser)
                if "保存到手机" not in view["text"]:
                    continue
                browser.click_button("保存到手机")
            download = parse_json(browser.run("wait", "download", "证书", "--timeout", "15000"))
            record["certificate_download"] = download
            record["certificate_directory"] = download_directory()
            save(output, record)
            return
    if click_link_containing(browser, "查看考试详情"):
        browser.run("wait", "time", "1")
        view = read_view(browser)
        for label in ("下载证书", "下载", "安全教育学习考试证书", "保存到手机"):
            if label in view["text"] and browser.try_run("click", "--role", "button", "--name", label):
                download = parse_json(browser.run("wait", "download", "证书", "--timeout", "15000"))
                record["certificate_download"] = download
                record["certificate_directory"] = download_directory()
                save(output, record)
                return
    record["certificate_download"] = {"status": "not_found_on_result_page"}
    save(output, record)
    raise RuntimeError("Exam passed, but no certificate download control was found on the result page.")


def take_exam(args: argparse.Namespace) -> None:
    report = preflight(args.session)
    if report["errors"]:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise RuntimeError("Preflight failed; fix the reported environment issues before continuing.")
    browser = Browser(args.session)
    if args.login:
        login(browser, args.remember_account, args.credentials_stdin)
    else:
        view = read_view(browser)
        if "登录" in view["text"] or not view["url"].startswith("https://gdse.guet.edu.cn/"):
            raise RuntimeError("No authenticated safety-education page. Re-run with --login.")
    enter_online_exam(browser)
    output = Path(args.record) if args.record else run_path(args.run_id)
    if output.exists():
        record = json.loads(output.read_text())
        record["status"] = "in_progress"
    else:
        record = {
            "exam": "online_exam",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "sources": list(BANKS),
            "status": "in_progress",
            "items": [],
        }
    save(output, record)
    local = load_records()
    while True:
        page = read_view(browser)
        if not page["number"] or not page["title"] or not page["options"]:
            raise RuntimeError("Question view is incomplete.")
        matched = find_record(local, page)
        override = args.unmatched_answer if args.unmatched_answer else None
        if not matched and not override:
            unmatched = {
                "display_number": int(page["number"]),
                "question": normalize(page["title"]),
                "options": page["options"],
                "reason": "no_exact_local_match",
            }
            record["unmatched_question"] = unmatched
            record["status"] = "paused_for_agent_reasoning"
            save(output, record)
            print(json.dumps(unmatched, ensure_ascii=False, indent=2))
            raise RuntimeError("Unmatched question recorded. Resume with --record, --unmatched-answer, and --unmatched-evidence after reasoning.")
        if matched:
            indices = answer_indices(matched, page)
            origin = "local_bank"
            source = matched["_source"]
            evidence = None
        else:
            temporary = {"answer": json.loads(override)}
            indices = answer_indices(temporary, page)
            origin = "agent_reasoned_unmatched"
            source = None
            evidence = args.unmatched_evidence
        for index in indices:
            browser.click_css(".topic-item", index)
        item = {
            "display_number": int(page["number"]),
            "question": normalize(page["title"]),
            "selected_options": [page["options"][index] for index in indices],
            "origin": origin,
            "source": source,
        }
        if evidence:
            item["evidence"] = evidence
        record["items"].append(item)
        save(output, record)
        if page["number"] == "100":
            break
        browser.click_button("下一题")
        browser.run("wait", "time", "0.5")
        if read_view(browser)["number"] == page["number"]:
            raise RuntimeError(f"Question did not advance from {page['number']}.")
    record["status"] = "ready_to_submit"
    save(output, record)
    submit_and_download(browser, record, output)
    print(json.dumps({"status": record["status"], "record": str(output)}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "take"))
    parser.add_argument("--session", default="safety-education")
    parser.add_argument("--login", action="store_true", help="Prompt for credentials and log in first.")
    parser.add_argument("--remember-account", action="store_true")
    parser.add_argument(
        "--credentials-stdin",
        action="store_true",
        help="Read the identity number and password from two stdin lines without echoing them.",
    )
    parser.add_argument("--run-id", help="Non-secret identifier for the output record.")
    parser.add_argument("--record", help="Resume an existing non-secret exam record.")
    parser.add_argument(
        "--unmatched-answer",
        help="JSON array of complete option texts for only the current unmatched question.",
    )
    parser.add_argument(
        "--unmatched-evidence",
        help="Short basis for the agent-reasoned unmatched answer; stored in the exam record.",
    )
    args = parser.parse_args()
    if args.command == "preflight":
        report = preflight(args.session)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if not report["errors"] else 2)
    take_exam(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        sys.exit(2)
