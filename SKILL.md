---
name: safety-education-quiz-assistant
description: Use when a GUET user asks to collect safety-education questions, answer a safety question, or complete a GUET safety-education exam. Ask which deployment to use when the user has not selected browser/OpenCLI with local banks or direct HTTP protocol mode.
---

# Safety Education Quiz Assistant

This skill has two deliberately separate exam deployments. At the beginning of
an exam task, ask the user to choose one unless the request already names it:

1. Browser-assisted deployment: AI agent + Chrome + OpenCLI + local quiz banks.
2. Direct HTTP deployment: Python `requests` + the server-provided `correctAnswer`.

Do not silently switch deployments. Do not place identity numbers, passwords,
cookies, or tokens in Markdown, JSON, shell history, or Git. The direct HTTP
client's optional HAR is the only intentional exception, and it is explicitly
unredacted for local protocol debugging.

## Automated Online Exam

1. Run `python3 scripts/take_online_exam.py preflight`. Report every failed dependency and provide its installation instruction; install only when the user authorizes it.
2. Ask the user for the identity number, password, and whether to remember the account. State that an empty password prompt uses the last six identity-number digits. Pass neither credential as a command-line argument.
3. Run `python3 scripts/take_online_exam.py take --login [--remember-account]`.
4. The script opens the platform, enters the login page through “打开安全大门”, navigates to 考试 → 在线考试, and answers with complete option-text matches from all four local banks.
5. For an unmatched question, read the saved `unmatched_question` in `data/exam-runs/`, reason from authoritative safety knowledge, then resume the same record with `--record <path> --unmatched-answer '<JSON complete-option-text array>' --unmatched-evidence '<basis>'`. Never use a random fallback when 100% is required.
6. Treat only a reported score of 100 as passed. The script then downloads the certificate and records the download result and expected Chrome download directory. Report failures clearly.

### Direct HTTP protocol client

Use `python3 scripts/take_online_exam_http.py` only when the user explicitly
requests protocol-level automation and has authorized submitting the exam.
The client prompts for identity number, password, and duration unless
`--credentials-stdin` is used; stdin mode reads username/password and, when no
`--duration-seconds` is supplied, a third duration line. Do
not pass passwords as command-line arguments. It receives the server's
`correctAnswer` and uses it to map option sequences to option UUIDs, then
submits the UUID values in the same format observed in the HAR. `--dry-run`
logs in and fetches the server-supplied questions without submitting.

By default it first requests `https://gdse.guet.edu.cn/config.json?r=<random>`
and uses the returned HTTPS `api` value. Use `--base-url` to override that
lookup, or `--skip-config` to use the default API URL without requesting the
configuration file.

After login, inspect the top-level `studentModel.isPassed` value. If it equals
`1`, stop immediately and do not request an exam UUID, questions, submission,
result, or certificate. The account has already passed and must not start
another exam through this workflow.

The command-line client prompts for identity number, password, and duration.
An empty password uses the last six identity-number digits. The default
duration is 299 seconds; accepted inputs may use seconds, minutes, or hours,
and the maximum is 2700 seconds (45 minutes). Values above the maximum are
rejected before network requests. Progress messages identify login, question
loading, timing, submission, persistence, result, and certificate stages.

The command-line client reports `登录成功` after a valid token and
`studentModel` are received. It then reports whether the account has already
passed or will continue because it has not passed. Login failures, non-200
business responses, and missing tokens are reported as explicit login errors.

The default exam duration is 299 seconds. `answerTime` is set after the exam
questions are loaded, `endTime` is calculated as `answerTime + min`, and the
client waits until `endTime` before submitting. Override the duration with
`--duration-seconds <seconds>` when testing or when the platform specifies a
different duration. The submit and mongo payloads preserve the property order
observed in the HAR for easier manual comparison.

The `--remember-account` flag records the user's preference in the non-secret
run result only. The platform implements that checkbox in browser localStorage,
not in `/login/stu`; this client never persists usernames, passwords, cookies,
or tokens.

Pass `--har <path>` to record an unredacted HAR 1.2 capture. The capture
includes request bodies, passwords, bearer tokens, question answers, and the
PDF response, and it also contains explicit `OPTIONS` CORS preflight entries.
Use this only for local debugging and never commit or share the resulting
file.

If `--certificate` is omitted, the HTTP client saves the PDF in the system
Downloads directory. It uses the server-provided `Content-Disposition`
filename when available, otherwise `安全教育学习考试证书.pdf`, and reports the
actual saved path in the final result.

Pass `--fetch-page-assets` to additionally fetch the ordered static-resource
phases extracted from the reference HAR: initial page
resources, post-config login-page images, post-login/home and exam resources,
result-page resources, and certificate-page resources. These asset requests
are recorded as ordinary `GET` requests and do not affect the exam workflow.
The hashed asset names are tied to the captured frontend build and should be
refreshed if the site publishes a new build.

If a run reaches `stage: saving_full_questions`, `submit` has already been
sent but the mongo persistence request failed. Do not restart the full exam:
that would create another record and submit again. The current client does not
persist the complete mongo payload before submit, so it cannot safely retry
mongo for that historical run. A future recovery implementation should save
the exact payload atomically before submit and expose a record-bound mongo-only
retry command.

At startup the HTTP client randomly selects one Chrome `User-Agent` from its
Linux, Windows, and macOS pool, then reuses that value for every request in
the run so the capture remains internally consistent.

The protocol client uses bounded timeouts and retries only `GET`/`OPTIONS`
requests for transient failures. It never automatically retries an exam
submission `POST`. Run records include a `stage` checkpoint and are written
atomically so an interruption can be diagnosed without a partially written
JSON file.

Read `docs/deployment-http-protocol.md` for the complete HTTP request order and
`docs/deployment-browser-opencli.md` for the browser workflow. Their runtime
environment notes are separate under `environments/`.

## Data and Runtime Files

- Main banks: `data/*-security.sample.json` and `data/traffic-safety.sample.json`.
- Exam records: `data/exam-runs/online-exam-*.json`; records contain answers and results but never credentials.
- Browser workflow detail: `quiz-bank-collection-workflow.md`.

## Core workflow

1. Identify the question type: single-choice, multiple-choice, true-false, fill-in-the-blank, or scenario-based.
2. Restate the question briefly and normalize the answer options without changing their meaning.
3. Identify the relevant safety principle, rule, hazard, or emergency response.
4. Evaluate each option against that principle and reject unsafe distractors explicitly.
5. Give the answer first, followed by a concise explanation.
6. If the question depends on a school policy, local regulation, date, or missing image, state the limitation and request the authoritative source or clearer content.

## Output format

Use this format unless the user asks for another format:

```text
题型：
答案：
解析：
关键安全原则：
不确定性：无 / 说明具体缺失信息
```

For multiple-choice questions, state all selected options and explain why each is correct. Do not assume that a quiz's expected answer is legally or technically correct when it conflicts with an authoritative safety source.

## Answer-data matching

- Store the complete option text as the primary answer value; retain `answer_labels` only as auxiliary positional metadata.
- For multiple-choice records, store complete texts in `answer` and `selected_options`, with `answer_labels` and `selected_options_labels` retained for traceability.
- Normalize every option before matching: apply Unicode NFKC, map a small approved set of common look-alike Chinese characters caused by OCR/input variants (for example `査` → `查`), trim whitespace, normalize equivalent presentation punctuation, and remove only a leading option label such as `A、`, `B.`, `C．`, or `D:`. Preserve the remaining wording and meaning; do not use broad fuzzy matching.
- Treat options as an ordered list for display but as an unordered set for identity and answer comparison. Sort normalized option-text keys deterministically before comparing them.
- Do not assume four options. Accept any non-empty option count, including three-option questions; preserve the observed count in the record.
- Match answers by normalized option-text set, not by their displayed order: trim whitespace and presentation punctuation, remove the leading label, preserve wording, and compare the resulting full-text set.
- Never treat matching `A/B/C/D` labels alone as sufficient verification, because question order may be randomized.
- Keep `verification_status: needs_review` when the full option text, question, or feedback is incomplete.

Canonical matching model:

```text
question_key = normalize(question) + "|" + sort(normalize(option_text) for option in options)
answer_key = sort(normalize(option_text) for option in correct_options)
```

The original `options` order and label fields remain available for traceability and display; only the canonical keys ignore order.

## Safety boundaries

- Treat safety questions as educational guidance, not a substitute for emergency services, professional training, or site-specific procedures.
- For an active emergency, prioritize immediate evacuation, isolation of hazards, contacting qualified personnel, and local emergency services over completing the quiz.
- Never invent laws, school rules, emergency numbers, or technical limits.
- Distinguish general safety principles from GUET-specific rules; consult verified references when a question asks about university policy.
