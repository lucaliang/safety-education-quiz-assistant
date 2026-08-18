# 浏览器/OpenCLI 环境

本目录只描述浏览器辅助部署，不用于直接 HTTP 方案。

要求：Python 3.10+、Node.js 20+、可运行的 `opencli`、Chrome 及已连接的 OpenCLI 浏览器扩展/会话，以及本 skill `data/` 下的本地题库。

检查环境：

```bash
python3 scripts/take_online_exam.py preflight
```

运行状态、未匹配题目和答案记录位于 `data/exam-runs/`；不要把账号、密码、Cookie 或 token 写入题库和文档。
