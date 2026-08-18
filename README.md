# 安全教育答题助手

本 skill 支持两套相互独立的考试部署。使用时先在对话中选择部署方案；没有明确选择时，助手必须先询问。

| 方案 | 依赖 | 答题数据来源 |
|---|---|---|
| 浏览器辅助 | Chrome、OpenCLI、本地题库 | 本地已核验题库 |
| HTTP 协议 | Python、`requests` | 服务器返回的 `correctAnswer` |

HTTP 方案快速运行：

```bash
python3 scripts/take_online_exam_http.py --fetch-page-assets \
  --output ./exam-result.json
```

程序会提示身份证号、密码和答题时长。密码直接回车时使用身份证号后 6 位；时长默认 299 秒，可输入 `120秒`、`5分钟` 等，最长 45 分钟。执行过程中会打印登录、题目、等待、提交、保存、成绩和证书阶段。

默认不生成 HAR；证书会保存到系统 `Downloads` 目录，并在结果中报告实际路径。只有需要本地协议调试时才增加 `--har`，因为该文件未脱敏。

登录成功后先检查 `studentModel.isPassed`：值为 `1` 时立即停止，不会继续考试。HTTP 方案只使用服务器返回的正确答案，不读取本地题库。

本仓库不包含账号密码、Cookie、考试运行记录、个人证书或未脱敏 HAR。请只在已获授权的环境中使用。

详细内容：

- [HTTP 协议部署教程](docs/deployment-http-protocol.md)
- [浏览器/OpenCLI 部署教程](docs/deployment-browser-opencli.md)
- [HTTP 环境配置](environments/http-protocol/README.md)
- [浏览器环境配置](environments/browser-opencli/README.md)
- [Skill 入口规则](SKILL.md)
