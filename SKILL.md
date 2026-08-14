---
name: safety-education-quiz-assistant
description: Use when an authorized GUET user asks to collect safety-education questions, answer a safety question, or complete the GUET safety-education online or simulation exam through a compatible Agent, OpenCLI, and local quiz banks.
---

# Safety Education Quiz Assistant

Use the bundled scripts for browser automation from any Agent host that can load
this skill and run local shell commands, such as Codex CLI, Claude Code, or
another compatible Agent. The scripts do not require a specific Agent vendor's
CLI. Do not place identity numbers, passwords, cookies, or tokens in Markdown,
JSON, shell history, or Git.

## Automated Online Exam

1. Run `python3 scripts/take_online_exam.py preflight`. Report every failed dependency and provide its installation instruction; install only when the user authorizes it. The preflight checks the local runtime and OpenCLI, not the Agent vendor.
2. Ask the user for the identity number, password, and whether to remember the account. State that an empty password prompt uses the last six identity-number digits. Pass neither credential as a command-line argument.
3. Run `python3 scripts/take_online_exam.py take --login [--remember-account]`.
4. The script opens the platform, enters the login page through “打开安全大门”, navigates to 考试 → 在线考试, and answers with complete option-text matches from all four local banks.
5. For an unmatched question, read the saved `unmatched_question` in `data/exam-runs/`, reason from authoritative safety knowledge, then resume the same record with `--record <path> --unmatched-answer '<JSON complete-option-text array>' --unmatched-evidence '<basis>'`. Never use a random fallback when 100% is required.
6. Treat only a reported score of 100 as passed. The script then downloads the certificate and records the download result and expected Chrome download directory. Report failures clearly.

## Data and Runtime Files

- Main banks: `data/*-security.sample.json` and `data/traffic-safety.sample.json`.
- Exam records: `data/exam-runs/online-exam-*.json`; records contain answers and results but never credentials.
- Browser workflow detail: `docs/使用教程.md`.

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
