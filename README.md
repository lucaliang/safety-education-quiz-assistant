# Safety Education Quiz Assistant

用于桂林电子科技大学安全教育平台的 Codex Skill：检查运行环境、通过 OpenCLI 驱动已授权的 Chrome、根据本地题库完成模拟考试或在线考试，并下载考试证书。

> 仅供已获授权的学生个人学习使用。请遵守学校平台规则、课程要求和适用法律；不要使用本项目规避身份验证、伪造考试结果或商业化分发题库。

## 功能

- 环境预检：Python、Node.js、Codex CLI、OpenCLI、Chrome Browser Bridge 和题库文件。
- 安全登录：运行时询问身份证号和密码，不将凭据写入 JSON、日志或命令行参数。
- 题库匹配：按题干和完整选项文本匹配，不依赖随机题号或 A/B/C/D 的显示位置。
- 考试自动化：支持模拟考试和在线考试；在线考试只有得分 100 才视为通过。
- 证书下载：通过后自动下载“安全教育培训证书” PDF。

## 快速开始

1. 安装 Codex CLI、Node.js 20+、Python 3.10+ 和 [OpenCLI](https://github.com/jackwener/OpenCLI)。
2. 在 Chrome 安装并连接 OpenCLI Browser Bridge，然后确认：

   ```bash
   opencli doctor
   ```

3. 进入本目录，检查环境和题库：

   ```bash
   python3 scripts/take_online_exam.py preflight
   ```

4. 在 Codex 中调用 `$safety-education-quiz-assistant`，或按 Skill 指引执行在线考试。脚本会在运行时安全地询问账号信息。

详见 [使用教程](docs/使用教程.md)。

## 题库状态

| 专题 | 记录数 | 平台验证 |
| --- | ---: | ---: |
| 反诈安全 | 99 | 99 |
| 消防安全 | 97 | 97 |
| 国家安全 | 100 | 100 |
| 交通安全 | 100 | 100 |

记录数小于 100 的专题已经按“题干 + 无序完整选项”去重；学习页面的显示题号可能随机复用，不能仅凭编号判断题目缺失。

## 发布内容

本仓库不含账号密码、Cookie、考试运行记录、个人证书、题库清理备份或个人身份信息。详见 [NOTICE.md](NOTICE.md)。

## License

代码以 [MIT License](LICENSE) 发布。题库内容及平台相关材料受其来源和平台条款约束，见 [NOTICE.md](NOTICE.md)。
