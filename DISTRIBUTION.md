# _tools 分发与复用指南

## 一、分享前必做：删除敏感文件

**直接发给别人前，务必删除或不要包含以下文件：**

| 文件/目录 | 原因 |
|-----------|------|
| `config.local.yml` | 含纷享账号密码、飞书 app_secret、LLM API Key、OpenAPI 凭证 |
| `deployer/session*.json` | 登录 session，会泄露你的登录态 |
| `deployer/session_cookies.json` | 同上 |
| `deployer/screenshots/` | 可能含业务截图 |
| `batch.log`、`batch_new.log`、`pipeline.log`、`pipeline_new.log` | 可能含业务日志 |
| `.fields_cache/` | 可选，可保留作为模板，但含你项目的字段结构 |

**推荐：** 用 git 管理，`config.local.yml` 已在 `.gitignore` 中，分享时只推送不含敏感文件的版本。

---

## 二、OpenClaw / FxClaw 相关说明

`_tools` 里包含 **FxClaw agent 的 prompt 配置**：`IDENTITY.md`、`INTRO.md`、`SOUL.md`、`AGENTS.md`、`CLAUDE.md` 等。这些是 agent 的行为定义，**可以分享**。

**OpenClaw 本身**（飞书连接、LLM 配置）在 **每个人的 ~/.openclaw/openclaw.json**，不在 `_tools` 里。所以：
- 发给别人的 `_tools` 里：只有 agent 的「身份」和「行为规则」
- 别人需要自己安装 OpenClaw、配置飞书、配置 LLM API Key

---

## 三、别人拿到后如何复用

### 1. 安装依赖

```bash
cd _tools
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置 config.local.yml

```bash
cp config.yml config.local.yml
# 编辑 config.local.yml，填入：
# - fxiaoke: 纷享账号、密码、base_url
# - openapi: 开放平台 app_id、app_secret、corp_id
# - llm: API Key、base_url（若用代理）、model
# - feishu: 可选，飞书记录用
```

### 3. 准备需求并运行

```bash
# 编辑 req.yml 或新建需求文件
python pipeline.py --req req.yml --step generate   # 仅生成
python pipeline.py --req req.yml --step deploy    # 生成 + 部署
```

### 4. 若要用 OpenClaw + 飞书 对话式生成

1. 安装 OpenClaw：`npm install -g openclaw`
2. 安装飞书插件：`openclaw plugins install @openclaw/feishu`
3. 配置 `~/.openclaw/openclaw.json`：填写飞书、LLM API
4. 把 `_tools` 作为 OpenClaw 的 workspace，agent 会读取其中的 IDENTITY.md、SOUL.md 等
5. 启动：`openclaw gateway start`

---

## 四、目录结构（可分享）

```
_tools/
├── config.yml               # 配置模板（不含敏感信息）✓
├── config.local.yml         # 本地配置（不要分享）✗
├── pipeline.py
├── generator/
├── deployer/
├── tester/
├── IDENTITY.md              # FxClaw 身份 ✓
├── INTRO.md                 # 出场介绍 ✓
├── SOUL.md                  # 行为准则 ✓
├── AGENTS.md
├── CLAUDE.md
├── USER.md
├── README.md
└── ...
```

---

## 五、快速检查清单

分享前执行：

```bash
# 确认 config.local.yml 不在待分享内容里
ls -la config.local.yml

# 若用 git，确认 .gitignore 生效
git status
```
