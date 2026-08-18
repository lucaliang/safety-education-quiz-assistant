import argparse
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from take_online_exam_http import (  # noqa: E402
    build_mongo_questions,
    build_mongo_payload,
    build_submit_payload,
    certificate_filename_from_headers,
    default_certificate_path,
    fetch_api_base_url,
    fetch_page_assets,
    fetch_page_phase,
    HAR_PAGE_PHASES,
    HARRecorder,
    GUETExamClient,
    LoginError,
    MAX_DURATION_SECONDS,
    _interactive_inputs,
    validate_exam_result,
    send_request_with_retry,
    wait_until,
    USER_AGENTS,
    choose_user_agent,
    extract_answer_ids,
    parse_api_response,
    run_exam,
)


class FakeResponse:
    def __init__(self, payload=None, *, content=b"", status_code=200, headers=None):
        self._payload = payload
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class ProtocolClientTests(unittest.TestCase):
    def test_get_request_retries_transient_http_failure_with_timeout(self):
        session = Mock()
        session.request.side_effect = [
            FakeResponse({}, status_code=503),
            FakeResponse({"ok": True}, status_code=200),
        ]

        response = send_request_with_retry(
            session,
            "GET",
            "https://seapi.guet.edu.cn/common/uuid",
            {},
            timeout=(1, 2),
            sleep_fn=lambda _: None,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.request.call_count, 2)
        self.assertEqual(session.request.call_args_list[0].kwargs["timeout"], (1, 2))

    def test_post_request_is_not_retried_after_transient_http_failure(self):
        session = Mock()
        session.request.return_value = FakeResponse({}, status_code=503)

        response = send_request_with_retry(
            session,
            "POST",
            "https://seapi.guet.edu.cn/examinationRecord/questions/submit",
            {},
            timeout=(1, 2),
            sleep_fn=lambda _: None,
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(session.request.call_count, 1)

    def test_exam_result_validation_rejects_missing_or_invalid_fields(self):
        with self.assertRaisesRegex(RuntimeError, "score"):
            validate_exam_result({"isPass": 1})
        with self.assertRaisesRegex(RuntimeError, "isPass"):
            validate_exam_result({"score": 100})

    def test_login_failure_raises_login_error_with_user_facing_message(self):
        session = Mock()
        session.request.side_effect = [FakeResponse({}), FakeResponse({"code": 401, "msg": "账号或密码错误"})]
        client = GUETExamClient(session, "https://seapi.guet.edu.cn")

        with self.assertRaisesRegex(LoginError, "登录失败"):
            client.login("student", "password")

    def test_har_page_phase_preserves_declared_order_and_duplicates(self):
        session = Mock()
        session.request.return_value = FakeResponse(b"asset", headers={"content-type": "image/png"})

        fetched = fetch_page_phase(session, "before_config")

        expected = [
            path if path.startswith(("https://", "http://")) else "https://gdse.guet.edu.cn" + path
            for path in HAR_PAGE_PHASES["before_config"]
        ]
        self.assertEqual(fetched, expected)
        self.assertEqual([call.args[1] for call in session.request.call_args_list], expected)
    def test_user_agent_pool_contains_linux_and_windows_chrome(self):
        self.assertGreaterEqual(len(USER_AGENTS), 3)
        self.assertTrue(any("Windows NT" in value for value in USER_AGENTS))
        self.assertTrue(any("X11; Linux" in value for value in USER_AGENTS))
        self.assertTrue(all(choose_user_agent() in USER_AGENTS for _ in range(20)))

    def test_certificate_filename_uses_server_name_and_sanitizes_path(self):
        self.assertEqual(
            certificate_filename_from_headers({"Content-Disposition": "attachment; filename*=UTF-8''%E8%AF%81%E4%B9%A6.pdf"}),
            "证书.pdf",
        )
        self.assertEqual(
            certificate_filename_from_headers({"content-disposition": "attachment; filename=../../certificate"}),
            "certificate.pdf",
        )

    def test_default_certificate_path_uses_download_directory(self):
        with patch("take_online_exam_http.default_download_directory", return_value=Path("/tmp/Downloads")):
            self.assertEqual(default_certificate_path("certificate.pdf"), Path("/tmp/Downloads/certificate.pdf"))

    def test_run_exam_stops_after_login_when_student_already_passed(self):
        session = Mock()
        responses = {
            ("OPTIONS", "/login/stu"): FakeResponse({}),
            ("POST", "/login/stu"): FakeResponse({
                "code": 200,
                "token": "secret-token",
                "studentModel": {"isPassed": 1},
            }),
        }
        calls = []

        def request(method, url, **kwargs):
            path = url.removeprefix("https://seapi.guet.edu.cn")
            calls.append((method, path))
            return responses[(method, path)]

        session.request.side_effect = request

        with self.assertRaisesRegex(RuntimeError, "already passed"):
            run_exam(
                session,
                username="student",
                password="password",
                base_url="https://seapi.guet.edu.cn",
            )

        self.assertEqual(calls, [("OPTIONS", "/login/stu"), ("POST", "/login/stu")])

    def test_interactive_inputs_use_default_password_and_convert_duration(self):
        args = argparse.Namespace(credentials_stdin=False, duration_seconds=None)
        with patch("take_online_exam_http.input", side_effect=["123456789012345678", "5分钟"]), patch(
            "take_online_exam_http.getpass.getpass", return_value=""
        ):
            username, password, duration = _interactive_inputs(args)

        self.assertEqual(username, "123456789012345678")
        self.assertEqual(password, "345678")
        self.assertEqual(duration, 300)

    def test_interactive_inputs_reject_duration_above_maximum(self):
        args = argparse.Namespace(credentials_stdin=False, duration_seconds=None)
        with patch("take_online_exam_http.input", side_effect=["student", "46分钟"]), patch(
            "take_online_exam_http.getpass.getpass", return_value="secret"
        ), self.assertRaisesRegex(ValueError, str(MAX_DURATION_SECONDS)):
            _interactive_inputs(args)

    def test_run_exam_rejects_duration_before_network_request(self):
        session = Mock()
        with self.assertRaisesRegex(ValueError, str(MAX_DURATION_SECONDS)):
            run_exam(
                session,
                username="student",
                password="password",
                base_url="https://seapi.guet.edu.cn",
                duration_seconds=MAX_DURATION_SECONDS + 1,
            )
        session.request.assert_not_called()

    def test_fetch_page_assets_fetches_same_origin_discovered_assets_without_options(self):
        session = Mock()
        responses = {
            "https://gdse.guet.edu.cn/": FakeResponse(
                content=b'<script src="/assets/app.js"></script><link href="/assets/app.css">',
                headers={"content-type": "text/html"},
            ),
            "https://gdse.guet.edu.cn/assets/app.js": FakeResponse(
                content=b'import "./chunk.js";',
                headers={"content-type": "application/javascript"},
            ),
            "https://gdse.guet.edu.cn/assets/app.css": FakeResponse(
                content=b'body { color: red; }',
                headers={"content-type": "text/css"},
            ),
            "https://gdse.guet.edu.cn/assets/chunk.js": FakeResponse(
                content=b"console.log('chunk');",
                headers={"content-type": "application/javascript"},
            ),
        }

        def request(method, url, **kwargs):
            self.assertEqual(method, "GET")
            return responses[url]

        session.request.side_effect = request

        fetched = fetch_page_assets(session, har=None)

        self.assertEqual(fetched, [
            "https://gdse.guet.edu.cn/",
            "https://gdse.guet.edu.cn/assets/app.js",
            "https://gdse.guet.edu.cn/assets/app.css",
            "https://gdse.guet.edu.cn/assets/chunk.js",
        ])

    def test_fetch_api_base_url_reads_config_with_cache_buster(self):
        session = Mock()
        response = FakeResponse({"api": "https://seapi.guet.edu.cn"})
        session.request.return_value = response

        result = fetch_api_base_url(session, cache_buster="0.123", har=None)

        self.assertEqual(result, "https://seapi.guet.edu.cn")
        method, url = session.request.call_args.args[:2]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://gdse.guet.edu.cn/config.json?r=0.123")

    def test_fetch_api_base_url_rejects_invalid_api_address(self):
        session = Mock()
        session.request.return_value = FakeResponse({"api": "http://untrusted.example"})

        with self.assertRaisesRegex(RuntimeError, "invalid api"):
            fetch_api_base_url(session, cache_buster="0.123", har=None)

    def test_extract_answer_ids_uses_server_correct_answer_sequence(self):
        question = {
            "id": "question-1",
            "type": "1",
            "correctAnswer": ["B", "D"],
            "options": [
                {"id": "id-a", "seq": "A", "text": "A", "isTrue": 0},
                {"id": "id-b", "seq": "B", "text": "B", "isTrue": 1},
                {"id": "id-c", "seq": "C", "text": "C", "isTrue": 0},
                {"id": "id-d", "seq": "D", "text": "D", "isTrue": 1},
            ],
        }

        self.assertEqual(extract_answer_ids(question), ["id-b", "id-d"])

    def test_extract_answer_ids_falls_back_to_is_true_when_correct_answer_is_empty(self):
        question = {
            "correctAnswer": [],
            "options": [
                {"id": "id-a", "seq": "A", "isTrue": 0},
                {"id": "id-b", "seq": "B", "isTrue": 1},
            ],
        }

        self.assertEqual(extract_answer_ids(question), ["id-b"])

    def test_submit_payload_uses_comma_joined_option_ids(self):
        questions = [{"id": "q1", "classification": "fireSafety", "answer_ids": ["a", "b"]}]
        payload = build_submit_payload(
            questions,
            record_id="record-1",
            template_id="template-1",
            answer_time="2026-08-19 12:00:00",
            end_time="2026-08-19 12:05:00",
            duration_seconds=299,
        )

        self.assertEqual(payload["recordId"], "record-1")
        self.assertEqual(payload["templateId"], "template-1")
        self.assertEqual(payload["min"], 299)
        self.assertEqual(list(payload), ["templateId", "min", "answerTime", "endTime", "recordId", "questions"])
        self.assertEqual(payload["questions"], [{
            "id": "q1",
            "userAnswer": "a,b",
            "correctAnswers": "a,b",
            "classification": "fireSafety",
        }])

    def test_mongo_questions_preserve_server_question_and_mark_selected_options(self):
        source = {
            "id": "q1",
            "title": "Question",
            "options": [
                {"id": "a", "seq": "A", "isTrue": 0},
                {"id": "b", "seq": "B", "isTrue": 1},
            ],
            "correctAnswer": ["B"],
            "classification": "fireSafety",
        }

        result = build_mongo_questions([(source, ["b"])])

        self.assertFalse(result[0]["options"][0]["active"])
        self.assertTrue(result[0]["options"][1]["active"])
        self.assertEqual(result[0]["userAnswer"], "b")

    def test_mongo_payload_uses_har_property_order(self):
        payload = build_mongo_payload(
            [{"id": "q1", "userAnswer": "b"}],
            template_id="template-1",
            duration_seconds=299,
            answer_time="2026-08-19 12:00:00",
            end_time="2026-08-19 12:04:59",
            record_id="record-1",
        )

        self.assertEqual(list(payload), ["questions", "templateId", "min", "answerTime", "endTime", "recordId"])

    def test_wait_until_sleeps_until_end_time(self):
        current = iter([
            datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 19, 12, 0, 10, tzinfo=timezone.utc),
        ])
        sleeps = []

        wait_until(
            datetime(2026, 8, 19, 12, 0, 10, tzinfo=timezone.utc),
            now_fn=lambda: next(current),
            sleep_fn=sleeps.append,
        )

        self.assertEqual(sleeps, [10.0])

    def test_parse_api_response_rejects_business_error(self):
        with self.assertRaisesRegex(RuntimeError, "login failed"):
            parse_api_response({"code": 401, "msg": "login failed"}, "/login/stu")

    def test_run_exam_calls_protocol_endpoints_in_order_and_downloads_pdf(self):
        question = {
            "id": "q1",
            "title": "Question",
            "type": "0",
            "classification": "fireSafety",
            "correctAnswer": ["A"],
            "options": [{"id": "a", "seq": "A", "isTrue": 1}],
        }
        responses = {
            ("OPTIONS", "/login/stu"): FakeResponse({}, headers={"access-control-allow-origin": "https://gdse.guet.edu.cn"}),
            ("POST", "/login/stu"): FakeResponse({
                "code": 200,
                "token": "secret-token",
                "studentModel": {"isPassed": 0},
            }),
            ("OPTIONS", "/common/uuid"): FakeResponse({}),
            ("GET", "/common/uuid"): FakeResponse({"code": 200, "data": "record-1"}),
            ("OPTIONS", "/templateQuestion/questions/exam"): FakeResponse({}),
            ("GET", "/templateQuestion/questions/exam"): FakeResponse({
                "code": 200,
                "data": {"templateId": "template-1", "questions": [question]},
            }),
            ("OPTIONS", "/examinationRecord/questions/submit"): FakeResponse({}),
            ("POST", "/examinationRecord/questions/submit"): FakeResponse({
                "code": 200,
                "data": {"ok": True, "id": "record-1"},
            }),
            ("OPTIONS", "/examinationRecord/questions/mongo"): FakeResponse({}),
            ("POST", "/examinationRecord/questions/mongo"): FakeResponse({
                "code": 200,
                "data": True,
            }),
            ("OPTIONS", "/examinationRecord/getById?id=record-1"): FakeResponse({}),
            ("GET", "/examinationRecord/getById?id=record-1"): FakeResponse({
                "code": 200,
                "data": {"score": 100, "isPass": 1},
            }),
            ("OPTIONS", "/examinationRecord/getCertificate"): FakeResponse({}),
            ("GET", "/examinationRecord/getCertificate"): FakeResponse(
                content=b"%PDF-1.7", headers={"content-type": "application/pdf"}
            ),
        }

        session = Mock()
        calls = []

        def request(method, url, **kwargs):
            path = url.removeprefix("https://seapi.guet.edu.cn")
            calls.append((method, path, kwargs))
            return responses[(method, path)]

        session.request.side_effect = request
        with TemporaryDirectory() as directory:
            har_path = Path(directory) / "exam.har"
            messages = []
            result = run_exam(
                session,
                username="student",
                password="password",
                remember_account=True,
                now=datetime(2026, 8, 19, 4, 0, tzinfo=timezone.utc),
                output_path=None,
                certificate_path=Path(directory) / "certificate.pdf",
                har_path=har_path,
                base_url="https://seapi.guet.edu.cn",
                duration_seconds=0,
                progress_callback=messages.append,
            )
            har = json.loads(har_path.read_text())

        self.assertEqual(
            [(method, path) for method, path, _ in calls],
            [
                ("OPTIONS", "/login/stu"),
                ("POST", "/login/stu"),
                ("OPTIONS", "/common/uuid"),
                ("GET", "/common/uuid"),
                ("OPTIONS", "/templateQuestion/questions/exam"),
                ("GET", "/templateQuestion/questions/exam"),
                ("OPTIONS", "/examinationRecord/questions/submit"),
                ("POST", "/examinationRecord/questions/submit"),
                ("OPTIONS", "/examinationRecord/questions/mongo"),
                ("POST", "/examinationRecord/questions/mongo"),
                ("OPTIONS", "/examinationRecord/getById?id=record-1"),
                ("GET", "/examinationRecord/getById?id=record-1"),
                ("OPTIONS", "/examinationRecord/getCertificate"),
                ("GET", "/examinationRecord/getCertificate"),
            ],
        )
        self.assertEqual(result["score"], 100)
        self.assertEqual(messages, [
            "正在登录……",
            "登录成功",
            "登录成功，当前账号尚未通过考试，继续后续操作",
            "正在获取考试记录编号……",
            "正在获取考试题目和服务器答案……",
            "已获取 1 道题目",
            "答题开始时间：2026-08-19 12:00:00",
            "答题结束时间：2026-08-19 12:00:00（时长 0 秒）",
            "答题时间已结束，开始提交答案……",
            "正在保存完整题目数据……",
            "正在查询成绩……",
            "成绩达到 100 分，正在下载证书……",
            "证书下载完成",
        ])
        self.assertTrue(result["certificate"])
        self.assertEqual(calls[1][2]["json"], {"username": "student", "password": "password"})
        self.assertEqual(calls[3][2]["headers"]["Authorization"], "Bearer secret-token")
        self.assertIn("Chrome/149.0.0.0", calls[3][2]["headers"]["User-Agent"])
        self.assertEqual(calls[-1][2]["headers"]["Authorization"], "Bearer secret-token")
        mongo_payload = calls[9][2]["json"]
        self.assertEqual(mongo_payload["answerTime"], "2026-08-19T04:00:00.000Z")
        self.assertEqual(mongo_payload["endTime"], "2026-08-19T04:00:00.000Z")
        self.assertEqual(calls[0][2]["headers"]["Access-Control-Request-Method"], "POST")
        self.assertIn("content-type", calls[0][2]["headers"]["Access-Control-Request-Headers"])
        self.assertEqual(len(har["log"]["entries"]), len(calls))
        login_entry = har["log"]["entries"][1]
        self.assertIn("password", login_entry["request"]["postData"]["text"])
        self.assertIn("secret-token", json.dumps(har))

    def test_har_recorder_writes_har_1_2_document(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "capture.har"
            recorder = HARRecorder(path)
            recorder.record(
                method="OPTIONS",
                url="https://seapi.guet.edu.cn/login/stu",
                request_headers={"Origin": "https://gdse.guet.edu.cn"},
                request_body=None,
                response=FakeResponse({}, headers={"content-type": "application/json"}),
                started_at="2026-08-19T00:00:00.000Z",
                elapsed_ms=1.0,
            )
            document = json.loads(path.read_text())

        self.assertEqual(document["log"]["version"], "1.2")
        self.assertEqual(document["log"]["entries"][0]["request"]["method"], "OPTIONS")


if __name__ == "__main__":
    unittest.main()
