#!/usr/bin/env python3
"""Complete the GUET safety exam through the captured HTTP protocol.

Credentials and bearer tokens are kept in memory only.  The platform's
"remember account" checkbox is a browser-local preference; it is not part of
the /login/stu request, so this client accepts the flag for compatibility but
does not persist credentials.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests

from parse_duration import parse_duration


DEFAULT_BASE_URL = "https://seapi.guet.edu.cn"
DEFAULT_FRONTEND_URL = "https://gdse.guet.edu.cn"
DEFAULT_ORIGIN = "https://gdse.guet.edu.cn"
DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
USER_AGENTS = (
    DEFAULT_USER_AGENT,
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
)
LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_DURATION_SECONDS = 299
MAX_DURATION_SECONDS = 2700
DEFAULT_TIMEOUT = (10.0, 30.0)
DEFAULT_MAX_RETRIES = 2
DEFAULT_CERTIFICATE_FILENAME = "安全教育学习考试证书.pdf"
RETRYABLE_METHODS = frozenset({"GET", "OPTIONS"})
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class LoginError(RuntimeError):
    """Raised when login did not produce a valid authenticated session."""


class AlreadyPassedError(RuntimeError):
    """Raised when the account is not allowed to start another exam."""


def send_request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    headers: dict[str, Any],
    *,
    timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep_fn: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> requests.Response:
    method = method.upper()
    retryable = method in RETRYABLE_METHODS
    for attempt in range(max_retries + 1):
        try:
            response = session.request(method, url, headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException:
            if not retryable or attempt >= max_retries:
                raise
            sleep_fn(min(0.5 * (2**attempt), 2.0))
            continue
        if response.status_code not in RETRYABLE_STATUS_CODES or not retryable or attempt >= max_retries:
            return response
        sleep_fn(min(0.5 * (2**attempt), 2.0))
    raise RuntimeError("request retry loop ended unexpectedly")


def atomic_write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb" if isinstance(data, bytes) else "w",
            encoding=None if isinstance(data, bytes) else "utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()

# Ordered static-resource phases extracted from gdse.guet.edu.cn_fullExam.har.
# The filenames are build artifacts and may need refreshing when the site ships
# a new frontend bundle.
HAR_PAGE_PHASES = {
    "before_config": (
        "/",
        "/assets/index-cmv_doNd.js",
        "/assets/index-yTgWwMRE.css",
        "https://at.alicdn.com/t/c/font_2553510_ciljc7axaw7.woff?t=1705587463221",
        "https://at.alicdn.com/t/c/font_2553510_ciljc7axaw7.woff?t=1705587463221",
        "/assets/index-uOBIjdRA.js",
        "/assets/login-D4T0OWFg.js",
        "/assets/auth-Bmj95k51.js",
        "/assets/index-CqsUUKG_.css",
        "/assets/index-BS17_dpn.css",
        "/assets/index-uusY9sXB.css",
        "/assets/index-D-WWo20N.css",
        "/assets/index-P-ExufR1.css",
        "/assets/index-CnAqlfC8.css",
    ),
    "after_config": (
        "/assets/logo-Cq5-Wrwr.png",
        "/assets/yidao1-7F80neo_.png",
        "/assets/yingdaoye-BNik5KTY.png",
        "/assets/denglubeij-DNAV6Fbu.png",
    ),
    "after_login": (
        "/assets/main-C7U0X32Z.js",
        "/assets/main-BFldImpd.css",
        "/assets/study_column-CUZZljZi.png",
        "/assets/examination_column-P_HPU0q_.png",
        "/assets/banner_01-9UCpt-dC.png",
        "/assets/banner_02-C_tCqmlI.png",
        "/assets/banner_03-GVGjgNa6.png",
        "/assets/banner_04-D6fyy8Y9.png",
        "/assets/index-C6fpMTrY.js",
        "/assets/index-cDp-4GZF.css",
        "/assets/rule_icon_04-C0YRvanl.png",
        "/assets/examination_banner-c1mOOB7Q.png",
        "/assets/exam-dlssSzZx.js",
        "/assets/sampleSize-BsbUvIdx.js",
        "/assets/sampleSize-3bhOYCmo.css",
        "/assets/index-Db9Z8-sK.css",
        "/assets/task-DEC9SZ5B.js",
        "/assets/moment-C5S46NFB.js",
        "/assets/exam-aX6eoG51.css",
        "/assets/index-B1-9YQtc.css",
        "/assets/index-Cp8xXw2H.css",
    ),
    "before_result": (
        "/assets/result-De1URIId.js",
        "/assets/result-D5tTfyFG.css",
    ),
    "after_result": (
        "/assets/submission_successful-P3Q_n6Bl.png",
        "/assets/certificate-BsU7klwv.js",
        "/assets/certificate-DuU9-Msy.css",
        "/assets/zhang02-Bjd_tynN.png",
        "/assets/zhang03-DNuA1RvS.png",
        "/assets/zhang01-DQZljLmJ.png",
        "/assets/certificate_template-B6lD9kBH.png",
    ),
}


def choose_user_agent() -> str:
    return random.choice(USER_AGENTS)


def default_download_directory() -> Path:
    try:
        process = subprocess.run(
            ["xdg-user-dir", "DOWNLOAD"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        process = None
    if process and process.returncode == 0 and process.stdout.strip():
        return Path(process.stdout.strip()).expanduser()
    return Path.home() / "Downloads"


def certificate_filename_from_headers(headers: dict[str, Any]) -> str:
    disposition = next(
        (str(value) for key, value in headers.items() if str(key).lower() == "content-disposition"),
        "",
    )
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.IGNORECASE)
    plain = re.search(r"filename\s*=\s*[\"']?([^;\"']+)", disposition, re.IGNORECASE)
    value = unquote((encoded or plain).group(1).strip()) if encoded or plain else DEFAULT_CERTIFICATE_FILENAME
    value = Path(value).name.strip()
    if not value:
        value = DEFAULT_CERTIFICATE_FILENAME
    if not value.lower().endswith(".pdf"):
        value += ".pdf"
    return value


def default_certificate_path(filename: str = DEFAULT_CERTIFICATE_FILENAME) -> Path:
    return default_download_directory() / certificate_filename_from_headers({"content-disposition": f"filename={filename}"})


def wait_until(
    end_time: datetime,
    *,
    now_fn: Callable[[], datetime] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    clock = now_fn or (lambda: datetime.now(end_time.tzinfo))
    while True:
        remaining = (end_time - clock()).total_seconds()
        if remaining <= 0:
            return
        sleep_fn(remaining)


def _har_headers(headers: dict[str, Any]) -> list[dict[str, str]]:
    return [{"name": str(name), "value": str(value)} for name, value in headers.items()]


def _har_body(value: Any) -> tuple[str | None, int]:
    if value is None:
        return None, 0
    if isinstance(value, (bytes, bytearray)):
        encoded = base64.b64encode(value).decode("ascii")
        return encoded, len(value)
    if isinstance(value, str):
        return value, len(value.encode("utf-8"))
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text, len(text.encode("utf-8"))


class HARRecorder:
    def __init__(self, path: Path):
        self.path = path
        self.document: dict[str, Any] = {
            "log": {
                "version": "1.2",
                "creator": {"name": "safety-education-quiz-assistant", "version": "1.0"},
                "entries": [],
            }
        }

    def record(
        self,
        *,
        method: str,
        url: str,
        request_headers: dict[str, Any],
        request_body: Any,
        response: requests.Response,
        started_at: str,
        elapsed_ms: float,
    ) -> None:
        request_text, request_size = _har_body(request_body)
        response_content = response.content or b""
        content_type = response.headers.get("content-type", "application/octet-stream")
        is_binary = not content_type.startswith(("application/json", "text/", "application/javascript", "text/css"))
        if is_binary:
            response_text = base64.b64encode(response_content).decode("ascii")
        else:
            response_text = response_content.decode("utf-8", errors="replace")
        request_object: dict[str, Any] = {
            "method": method,
            "url": url,
            "httpVersion": "HTTP/1.1",
            "headers": _har_headers(request_headers),
            "queryString": [],
            "cookies": [],
            "headersSize": -1,
            "bodySize": request_size,
        }
        if request_text is not None:
            request_object["postData"] = {
                "mimeType": request_headers.get("Content-Type", "application/json;charset=UTF-8"),
                "text": request_text,
            }
        entry: dict[str, Any] = {
            "startedDateTime": started_at,
            "time": elapsed_ms,
            "request": request_object,
            "response": {
                "status": response.status_code,
                "statusText": "",
                "httpVersion": "HTTP/1.1",
                "headers": _har_headers(dict(response.headers)),
                "cookies": [],
                "content": {
                    "size": len(response_content),
                    "mimeType": content_type,
                    "text": response_text,
                    **({"encoding": "base64"} if is_binary else {}),
                },
                "redirectURL": "",
                "headersSize": -1,
                "bodySize": len(response_content),
            },
            "cache": {},
            "timings": {"send": 0, "wait": elapsed_ms, "receive": 0},
        }
        self.document["log"]["entries"].append(entry)
        atomic_write(self.path, json.dumps(self.document, ensure_ascii=False, indent=2) + "\n")


def fetch_api_base_url(
    session: requests.Session,
    *,
    frontend_url: str = DEFAULT_FRONTEND_URL,
    cache_buster: str | None = None,
    har: HARRecorder | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> str:
    value = cache_buster if cache_buster is not None else str(random.random())
    url = f"{frontend_url.rstrip('/')}/config.json?r={value}"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": DEFAULT_FRONTEND_URL,
        "Referer": f"{DEFAULT_FRONTEND_URL}/",
        "User-Agent": user_agent,
    }
    started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    started = time.perf_counter()
    response = send_request_with_retry(session, "GET", url, headers)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if har:
        har.record(
            method="GET",
            url=url,
            request_headers=headers,
            request_body=None,
            response=response,
            started_at=started_at,
            elapsed_ms=elapsed_ms,
        )
    response.raise_for_status()
    payload = response.json()
    api = payload.get("api") if isinstance(payload, dict) else None
    parsed = urlparse(api) if isinstance(api, str) else None
    if not parsed or parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("config.json: invalid api address")
    return api.rstrip("/")


def fetch_page_assets(
    session: requests.Session,
    *,
    frontend_url: str = DEFAULT_FRONTEND_URL,
    har: HARRecorder | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[str]:
    """Fetch the page and same-origin static assets discoverable in text resources."""
    origin = frontend_url.rstrip("/")
    queue = [origin + "/"]
    visited: set[str] = set()
    fetched: list[str] = []
    asset_pattern = re.compile(
        r"(?:[\"'])([^\"']+\.(?:js|css|png|jpe?g|gif|svg|woff2?|ttf)(?:\?[^\"']*)?)[\"']",
        re.IGNORECASE,
    )
    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != urlparse(origin).netloc:
            continue
        visited.add(url)
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Origin": DEFAULT_FRONTEND_URL,
            "Referer": f"{DEFAULT_FRONTEND_URL}/",
            "User-Agent": user_agent,
        }
        started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        started = time.perf_counter()
        response = send_request_with_retry(session, "GET", url, headers)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if har:
            har.record(
                method="GET",
                url=url,
                request_headers=headers,
                request_body=None,
                response=response,
                started_at=started_at,
                elapsed_ms=elapsed_ms,
            )
        response.raise_for_status()
        fetched.append(url)
        content_type = response.headers.get("content-type", "").lower()
        if not any(kind in content_type for kind in ("html", "javascript", "css")):
            continue
        text = response.content.decode("utf-8", errors="ignore")
        for reference in asset_pattern.findall(text):
            candidate = urljoin(url, reference)
            candidate_parts = urlparse(candidate)
            if candidate_parts.netloc == urlparse(origin).netloc and candidate_parts.path.startswith("/assets/"):
                if candidate not in visited and candidate not in queue:
                    queue.append(candidate)
    return fetched


def fetch_page_phase(
    session: requests.Session,
    phase: str,
    *,
    frontend_url: str = DEFAULT_FRONTEND_URL,
    har: HARRecorder | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[str]:
    """Fetch the exact ordered static-resource phase captured in the HAR."""
    try:
        paths = HAR_PAGE_PHASES[phase]
    except KeyError as exc:
        raise ValueError(f"Unknown HAR page phase: {phase}") from exc
    origin = frontend_url.rstrip("/")
    fetched = []
    for path in paths:
        url = path if path.startswith(("https://", "http://")) else origin + path
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Origin": DEFAULT_FRONTEND_URL,
            "Referer": f"{DEFAULT_FRONTEND_URL}/",
            "User-Agent": user_agent,
        }
        started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        started = time.perf_counter()
        response = send_request_with_retry(session, "GET", url, headers)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if har:
            har.record(
                method="GET",
                url=url,
                request_headers=headers,
                request_body=None,
                response=response,
                started_at=started_at,
                elapsed_ms=elapsed_ms,
            )
        response.raise_for_status()
        fetched.append(url)
    return fetched


def parse_api_response(payload: Any, endpoint: str) -> Any:
    if not isinstance(payload, dict):
        raise RuntimeError(f"{endpoint}: expected a JSON object")
    if payload.get("code") != 200:
        message = payload.get("msg") or f"business code {payload.get('code')!r}"
        raise RuntimeError(f"{endpoint}: {message}")
    return payload.get("data")


def validate_exam_result(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise RuntimeError("/examinationRecord/getById: result data is not an object")
    if not isinstance(data.get("score"), (int, float)) or isinstance(data.get("score"), bool):
        raise RuntimeError("/examinationRecord/getById: result score is missing or invalid")
    if data.get("isPass") not in (0, 1, "0", "1"):
        raise RuntimeError("/examinationRecord/getById: result isPass is missing or invalid")
    return data


def _answer_sequence(question: dict[str, Any]) -> list[Any]:
    answer = question.get("correctAnswer")
    if isinstance(answer, list) and answer:
        return answer
    return [option.get("seq") for option in question.get("options", []) if option.get("isTrue") == 1]


def extract_answer_ids(question: dict[str, Any]) -> list[str]:
    options = question.get("options") or []
    by_seq = {str(option.get("seq")): str(option["id"]) for option in options if option.get("id") is not None}
    by_id = {str(option["id"]): str(option["id"]) for option in options if option.get("id") is not None}
    result = []
    for answer in _answer_sequence(question):
        key = str(answer)
        option_id = by_id.get(key) or by_seq.get(key)
        if option_id is None:
            raise RuntimeError(f"Question {question.get('id', '<unknown>')}: cannot map correct answer {answer!r}")
        result.append(option_id)
    if not result:
        raise RuntimeError(f"Question {question.get('id', '<unknown>')}: server returned no correct answer")
    return result


def _answer_text(answer_ids: list[str]) -> str:
    return ",".join(answer_ids)


def build_submit_payload(
    questions: list[dict[str, Any]],
    *,
    record_id: str,
    template_id: str,
    answer_time: str,
    end_time: str,
    duration_seconds: int,
) -> dict[str, Any]:
    return {
        "templateId": template_id,
        "min": duration_seconds,
        "answerTime": answer_time,
        "endTime": end_time,
        "recordId": record_id,
        "questions": [
            {
                "id": question["id"],
                "userAnswer": _answer_text(question["answer_ids"]),
                "correctAnswers": _answer_text(question["answer_ids"]),
                "classification": question.get("classification"),
            }
            for question in questions
        ],
    }


def build_mongo_questions(question_pairs: list[tuple[dict[str, Any], list[str]]]) -> list[dict[str, Any]]:
    result = []
    for source, answer_ids in question_pairs:
        question = deepcopy(source)
        selected = set(answer_ids)
        for option in question.get("options", []):
            option["active"] = str(option.get("id")) in selected
        question["userAnswer"] = _answer_text(answer_ids)
        result.append(question)
    return result


def build_mongo_payload(
    questions: list[dict[str, Any]],
    *,
    template_id: str,
    duration_seconds: int,
    answer_time: str,
    end_time: str,
    record_id: str,
) -> dict[str, Any]:
    return {
        "questions": questions,
        "templateId": template_id,
        "min": duration_seconds,
        "answerTime": answer_time,
        "endTime": end_time,
        "recordId": record_id,
    }


class GUETExamClient:
    def __init__(
        self,
        session: requests.Session,
        base_url: str = DEFAULT_BASE_URL,
        har: HARRecorder | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    ):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.har = har
        self.user_agent = user_agent
        self.timeout = timeout
        self.token: str | None = None
        self.certificate_filename: str | None = None

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("Accept", "application/json, text/plain, */*")
        headers.setdefault("Origin", DEFAULT_ORIGIN)
        headers.setdefault("Referer", f"{DEFAULT_ORIGIN}/")
        headers.setdefault("User-Agent", self.user_agent)
        if "json" in kwargs:
            headers.setdefault("Content-Type", "application/json;charset=UTF-8")
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = self.base_url + path
        self._preflight(method, url, headers)
        started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        started = time.perf_counter()
        response = send_request_with_retry(
            self.session,
            method,
            url,
            headers,
            timeout=self.timeout,
            **kwargs,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if self.har:
            self.har.record(
                method=method,
                url=url,
                request_headers=headers,
                request_body=kwargs.get("json"),
                response=response,
                started_at=started_at,
                elapsed_ms=elapsed_ms,
            )
        response.raise_for_status()
        return response

    def _preflight(self, method: str, url: str, actual_headers: dict[str, Any]) -> None:
        requested = [name.lower() for name in ("content-type", "authorization") if name.title() in actual_headers or name in {key.lower() for key in actual_headers}]
        headers = {
            "Accept": "*/*",
            "Origin": DEFAULT_ORIGIN,
            "Referer": f"{DEFAULT_ORIGIN}/",
            "User-Agent": self.user_agent,
            "Access-Control-Request-Method": method,
        }
        if requested:
            headers["Access-Control-Request-Headers"] = ", ".join(requested)
        started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        started = time.perf_counter()
        response = send_request_with_retry(
            self.session,
            "OPTIONS",
            url,
            headers,
            timeout=self.timeout,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if self.har:
            self.har.record(
                method="OPTIONS",
                url=url,
                request_headers=headers,
                request_body=None,
                response=response,
                started_at=started_at,
                elapsed_ms=elapsed_ms,
            )
        response.raise_for_status()

    def login(self, username: str, password: str) -> dict[str, Any]:
        try:
            response = self.request("POST", "/login/stu", json={"username": username, "password": password})
            payload = response.json()
            parse_api_response(payload, "/login/stu")
        except Exception as exc:
            raise LoginError(f"登录失败：{exc}") from exc
        if not isinstance(payload, dict) or not payload.get("token"):
            raise LoginError("登录失败：服务器响应中没有有效 token")
        self.token = payload["token"]
        student_model = payload.get("studentModel")
        if not isinstance(student_model, dict):
            raise LoginError("登录失败：服务器响应中没有有效 studentModel")
        if student_model.get("isPassed") not in (0, 1, "0", "1"):
            raise LoginError("登录失败：studentModel.isPassed 缺失或无效")
        return student_model

    def fetch_exam(self) -> tuple[str, list[dict[str, Any]]]:
        response = self.request("GET", "/templateQuestion/questions/exam")
        data = parse_api_response(response.json(), "/templateQuestion/questions/exam")
        if (
            not isinstance(data, dict)
            or not data.get("templateId")
            or not isinstance(data.get("questions"), list)
            or not data["questions"]
            or not all(isinstance(question, dict) for question in data["questions"])
        ):
            raise RuntimeError("/templateQuestion/questions/exam: invalid exam payload")
        return str(data["templateId"]), data["questions"]

    def submit(self, payload: dict[str, Any]) -> str:
        response = self.request("POST", "/examinationRecord/questions/submit", json=payload)
        data = parse_api_response(response.json(), "/examinationRecord/questions/submit")
        if not isinstance(data, dict) or not data.get("ok"):
            raise RuntimeError("/examinationRecord/questions/submit: submission was not accepted")
        return str(data.get("id") or payload["recordId"])

    def save_mongo(self, payload: dict[str, Any]) -> None:
        response = self.request("POST", "/examinationRecord/questions/mongo", json=payload)
        if parse_api_response(response.json(), "/examinationRecord/questions/mongo") is not True:
            raise RuntimeError("/examinationRecord/questions/mongo: server did not confirm persistence")

    def result(self, record_id: str) -> dict[str, Any]:
        response = self.request("GET", f"/examinationRecord/getById?id={record_id}")
        data = parse_api_response(response.json(), "/examinationRecord/getById")
        return validate_exam_result(data)

    def certificate(self) -> bytes:
        response = self.request("GET", "/examinationRecord/getCertificate", headers={"Accept": "application/pdf"})
        content_type = response.headers.get("content-type", "").lower()
        if "application/pdf" not in content_type and not response.content.startswith(b"%PDF"):
            raise RuntimeError("/examinationRecord/getCertificate: response is not a PDF")
        self.certificate_filename = certificate_filename_from_headers(dict(response.headers))
        return response.content


def _local_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_ZONE)
    return value.astimezone(LOCAL_ZONE)


def _mongo_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def run_exam(
    session: requests.Session,
    *,
    username: str,
    password: str,
    remember_account: bool = False,
    now: datetime | None = None,
    output_path: Path | None = None,
    certificate_path: Path | None = None,
    har_path: Path | None = None,
    dry_run: bool = False,
    base_url: str | None = None,
    skip_config: bool = False,
    fetch_assets: bool = False,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    duration_seconds = parse_duration(str(duration_seconds), max_seconds=MAX_DURATION_SECONDS)
    har = HARRecorder(har_path) if har_path else None
    user_agent = choose_user_agent()
    notify = progress_callback or (lambda _: None)
    if fetch_assets:
        notify("正在按 HAR 顺序加载页面资源……")
        fetch_page_phase(session, "before_config", har=har, user_agent=user_agent)
    api_base_url = base_url or DEFAULT_BASE_URL
    if not skip_config and base_url is None:
        notify("正在读取服务器配置……")
        api_base_url = fetch_api_base_url(session, har=har, user_agent=user_agent)
    if fetch_assets:
        fetch_page_phase(session, "after_config", har=har, user_agent=user_agent)
    client = GUETExamClient(session, api_base_url, har, user_agent)
    notify("正在登录……")
    student_model = client.login(username, password)
    notify("登录成功")
    if str(student_model.get("isPassed")) == "1":
        notify("当前账号已经通过考试，不允许继续考试")
        raise AlreadyPassedError("The student has already passed the safety exam; starting another exam is not allowed")
    notify("登录成功，当前账号尚未通过考试，继续后续操作")
    if fetch_assets:
        fetch_page_phase(session, "after_login", har=har, user_agent=user_agent)
    notify("正在获取考试记录编号……")
    uuid_response = client.request("GET", "/common/uuid")
    record_id = parse_api_response(uuid_response.json(), "/common/uuid")
    if not isinstance(record_id, str) or not record_id:
        raise RuntimeError("/common/uuid: invalid UUID")
    notify("正在获取考试题目和服务器答案……")
    template_id, source_questions = client.fetch_exam()
    notify(f"已获取 {len(source_questions)} 道题目")
    started = _local_time(now or datetime.now(timezone.utc))
    questions = []
    question_pairs = []
    for source in source_questions:
        answer_ids = extract_answer_ids(source)
        question = dict(source)
        question["answer_ids"] = answer_ids
        questions.append(question)
        question_pairs.append((source, answer_ids))
    ended = started + timedelta(seconds=duration_seconds)
    answer_time = started.strftime("%Y-%m-%d %H:%M:%S")
    end_time = ended.strftime("%Y-%m-%d %H:%M:%S")
    payload = build_submit_payload(
        questions,
        record_id=record_id,
        template_id=template_id,
        answer_time=answer_time,
        end_time=end_time,
        duration_seconds=duration_seconds,
    )
    result: dict[str, Any] = {
        "exam": "online_exam_http",
        "started_at": started.isoformat(),
        "remember_account_requested": remember_account,
        "question_count": len(questions),
        "record_id": record_id,
        "template_id": template_id,
        "api_base_url": api_base_url,
        "user_agent": user_agent,
        "login_status": "success",
        "is_passed_before_exam": student_model.get("isPassed", 0),
        "status": "ready_to_submit",
        "stage": "ready_to_submit",
    }

    def checkpoint(stage: str) -> None:
        result["stage"] = stage
        if output_path:
            atomic_write(output_path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")

    if dry_run:
        result["status"] = "dry_run"
        checkpoint("dry_run")
        return result
    checkpoint("waiting_for_end_time")
    notify(f"答题开始时间：{answer_time}")
    notify(f"答题结束时间：{end_time}（时长 {duration_seconds} 秒）")
    if duration_seconds > 0:
        notify("等待答题时间结束……")
        wait_until(ended)
    notify("答题时间已结束，开始提交答案……")
    checkpoint("submitting")
    submitted_record_id = client.submit(payload)
    mongo_payload = build_mongo_payload(
        build_mongo_questions(question_pairs),
        template_id=template_id,
        duration_seconds=duration_seconds,
        answer_time=_mongo_time(started),
        end_time=_mongo_time(ended),
        record_id=submitted_record_id,
    )
    notify("正在保存完整题目数据……")
    checkpoint("saving_full_questions")
    client.save_mongo(mongo_payload)
    if fetch_assets:
        fetch_page_phase(session, "before_result", har=har, user_agent=user_agent)
    notify("正在查询成绩……")
    result_data = client.result(submitted_record_id)
    result.update({
        "record_id": submitted_record_id,
        "score": result_data.get("score"),
        "is_pass": result_data.get("isPass"),
        "right_count": result_data.get("rightNum"),
        "wrong_count": result_data.get("wrongNum"),
        "unanswered_count": result_data.get("noAnswerNum"),
    })
    checkpoint("result_received")
    if result.get("score") != 100 or str(result.get("is_pass")) != "1":
        result["status"] = "failed_or_not_passed"
        checkpoint("failed_result")
        notify(f"考试未通过，成绩：{result.get('score')}")
        raise RuntimeError(f"Exam was not passed with 100%; score={result.get('score')!r}")
    if fetch_assets:
        fetch_page_phase(session, "after_result", har=har, user_agent=user_agent)
        if not skip_config and base_url is None:
            api_base_url = fetch_api_base_url(session, har=har, user_agent=user_agent)
            client.base_url = api_base_url
    notify("成绩达到 100 分，正在下载证书……")
    checkpoint("downloading_certificate")
    pdf = client.certificate()
    certificate_path = certificate_path or default_certificate_path(client.certificate_filename or DEFAULT_CERTIFICATE_FILENAME)
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(certificate_path, pdf)
    result["certificate_path"] = str(certificate_path)
    result["certificate"] = True
    result["status"] = "passed"
    result["stage"] = "completed"
    notify("证书下载完成")
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(output_path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def _interactive_inputs(args: argparse.Namespace) -> tuple[str, str, int]:
    if args.credentials_stdin:
        username = sys.stdin.readline().rstrip("\n")
        password = sys.stdin.readline().rstrip("\n")
        duration_input = None if args.duration_seconds is not None else sys.stdin.readline().rstrip("\n")
    else:
        username = input("账号/身份证号: ").strip()
        password = getpass.getpass("密码（直接回车使用身份证号后6位）: ").strip()
        duration_input = None
        if args.duration_seconds is None:
            duration_input = input("答题时长（默认299秒，最长45分钟）: ")
    if not username or not password:
        if not password and username:
            password = username[-6:]
        if not username or not password:
            raise RuntimeError("账号不能为空，且无法生成默认密码")
    duration = parse_duration(
        str(args.duration_seconds) if args.duration_seconds is not None else duration_input,
        max_seconds=MAX_DURATION_SECONDS,
    )
    return username, password, duration


def main() -> None:
    parser = argparse.ArgumentParser(description="Complete the GUET safety exam through HTTP requests.")
    parser.add_argument("--credentials-stdin", action="store_true", help="Read username, password, and (when needed) duration from stdin lines.")
    parser.add_argument("--remember-account", action="store_true", help="Record the preference only; never persist credentials.")
    parser.add_argument("--dry-run", action="store_true", help="Login and fetch server answers without submitting.")
    parser.add_argument("--base-url", help="Override the API base URL and skip config.json.")
    parser.add_argument("--skip-config", action="store_true", help="Skip config.json and use the default API URL.")
    parser.add_argument("--fetch-page-assets", action="store_true", help="Fetch same-origin HTML/JS/CSS/image/font assets into the HAR.")
    parser.add_argument("--duration-seconds", type=int, help="Exam duration in seconds; default 299, maximum 2700.")
    parser.add_argument("--output", type=Path, help="Write a non-secret result record.")
    parser.add_argument("--certificate", type=Path, help="Path for the downloaded PDF certificate.")
    parser.add_argument("--har", type=Path, help="Write an unredacted HAR 1.2 capture, including credentials and token.")
    args = parser.parse_args()
    username, password, duration_seconds = _interactive_inputs(args)
    result = run_exam(
        requests.Session(),
        username=username,
        password=password,
        remember_account=args.remember_account,
        output_path=args.output,
        certificate_path=args.certificate,
        har_path=args.har,
        dry_run=args.dry_run,
        base_url=args.base_url,
        skip_config=args.skip_config,
        fetch_assets=args.fetch_page_assets,
        duration_seconds=duration_seconds,
        progress_callback=print,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except AlreadyPassedError as exc:
        print(f"提示：{exc}")
        raise SystemExit(0)
    except LoginError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        raise SystemExit(1)
