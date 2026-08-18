# 浏览器/OpenCLI 部署

该方案使用 AI agent 驱动真实 Chrome，通过 OpenCLI 完成页面操作，并从本地题库匹配完整选项文本。它与 HTTP 协议方案分开维护，不读取服务器 `correctAnswer`，也不复刻 API 请求。

```bash
python3 scripts/take_online_exam.py preflight
python3 scripts/take_online_exam.py take --login
```

运行时按提示输入身份证号、密码和是否记住账号。密码直接回车时使用身份证号后 6 位。未匹配的题目会保存到 `data/exam-runs/` 并停止，需人工确认完整选项后再恢复；不能用随机答案兜底。

模拟考试和题库采集也使用这套浏览器环境，详见 `quiz-bank-collection-workflow.md`。
