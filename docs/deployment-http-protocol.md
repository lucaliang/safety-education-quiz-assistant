# 直接 HTTP 协议部署

该方案使用 Python `requests`，按照参考 HAR 的业务顺序执行登录、取题、提交、保存完整题目、查分和下载证书。页面静态资源只有在指定 `--fetch-page-assets` 时才按 HAR 分阶段补充请求。

## 输入与限制

- 交互提示输入身份证号、密码和答题时长。
- 密码为空时默认使用身份证号后 6 位。
- 时长为空默认 299 秒；支持秒、分、小时单位，例如 `90秒`、`5分钟`。
- 最大时长为 2700 秒（45 分钟），超过上限在发起网络请求前拒绝。
- 登录成功后若 `studentModel.isPassed == 1`，立即停止，不允许继续考试。
- 题目答案只读取服务器返回的 `correctAnswer`。

## 请求顺序

基础流程的每个 API 请求都先发送对应 `OPTIONS` 预检，再发送实际请求：

1. `GET https://gdse.guet.edu.cn/config.json?r=<random>`（除非 `--base-url` 或 `--skip-config`）。
2. `OPTIONS` + `POST /login/stu`，检查 `token` 和 `studentModel`。
3. `OPTIONS` + `GET /common/uuid`。
4. `OPTIONS` + `GET /templateQuestion/questions/exam`，读取 `templateId`、题目和 `correctAnswer`。
5. 计算 `answerTime`、`endTime = answerTime + min`，等待系统时间超过 `endTime`。
6. `OPTIONS` + `POST /examinationRecord/questions/submit`。
7. `OPTIONS` + `POST /examinationRecord/questions/mongo`，先发送 `questions`，再发送 `templateId`、`min`、`answerTime`、`endTime`、`recordId`。
8. `OPTIONS` + `GET /examinationRecord/getById?id=<recordId>`。
9. 成绩为 100 且 `isPass == 1` 时，`OPTIONS` + `GET /examinationRecord/getCertificate` 下载 PDF。

提交体属性顺序为 `templateId`、`min`、`answerTime`、`endTime`、`recordId`、`questions`，使用 HAR 中的本地时间格式；mongo 体属性顺序为 `questions`、`templateId`、`min`、`answerTime`、`endTime`、`recordId`，其中时间使用带毫秒的 UTC ISO-8601 格式。

## HAR 与页面资源

默认不写 HAR。`--har <path>` 会写入未脱敏的 HAR，包含密码、Bearer token、答案和证书响应，只能保存在本机。`--fetch-page-assets` 可以单独启用，会在上述业务节点之间插入参考 HAR 中记录的静态资源 GET 请求；它不改变业务请求顺序。

证书默认保存到系统 `Downloads` 目录：优先采用服务器 `Content-Disposition` 提供的文件名，否则使用 `安全教育学习考试证书.pdf`。不传 `--certificate` 时，最终结果会报告实际保存路径。

如需只验证登录和取题而不提交，可增加 `--dry-run`。

## 提交失败后的恢复边界

如果日志显示：

```text
submit 成功
mongo 保存失败
stage: saving_full_questions
```

不要重新运行完整考试。重新运行会重新获取考试记录编号并再次 submit，可能产生重复考试记录。当前版本没有把完整 mongo 请求体在 submit 前保存下来，因此无法仅凭结果 JSON 安全重试原记录的 mongo 请求；重新获取题目也不能保证与原记录一致。

后续恢复功能应满足：

1. 在 submit 前原子保存完整 mongo payload；
2. payload 固定绑定 `recordId`、`templateId` 和时间字段；
3. 提供只执行 `OPTIONS` + `POST /examinationRecord/questions/mongo` 的重试入口；
4. 重试前校验账号、记录编号和 payload 的一致性。
