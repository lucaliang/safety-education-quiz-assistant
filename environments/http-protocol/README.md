# HTTP 协议环境

本目录只描述直接 HTTP 部署，不需要 Chrome、OpenCLI 或本地题库。

要求：Python 3.10+、`requests`，以及可访问 `gdse.guet.edu.cn` 和由 `config.json` 返回的 HTTPS API 地址。

检查依赖：

```bash
python3 -c "import requests; print(requests.__version__)"
```

运行入口：

```bash
python3 scripts/take_online_exam_http.py
```

账号和密码只在内存中使用。若启用 `--har`，生成文件会包含未脱敏凭据和 token，必须保存在本机并排除在 Git 之外。
