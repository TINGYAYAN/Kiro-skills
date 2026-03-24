# 拿到工具包后怎么做（完整步骤）

适用：别人收到 **`_tools` 文件夹的压缩包**（或包含 `_tools` 的整个项目压缩包）。  
**不要**把作者的 `config.local.yml`、密码、API Key 打进压缩包；每人自己生成本地配置。

---

## 一、环境要求

| 项 | 说明 |
|----|------|
| 操作系统 | Windows / macOS / Linux 均可 |
| Python | **3.10+**（推荐 3.10～3.12） |
| 网络 | 能访问纷享租户、OpenAPI；生成代码时需能访问所选 LLM（如 Anthropic/OpenAI） |
| 浏览器自动化（可选） | 只有要用 **自动部署到纷享** 时才需要：安装 Playwright Chromium |

终端里检查 Python：

```bash
python3 --version
# 或
python --version
```

---

## 二、解压与进入目录

**情况 A：压缩包里只有 `_tools` 文件夹**

```bash
cd /你解压的位置/_tools
```

**情况 B：压缩包是整个项目（含 `中电长城/`、`硅基流动/` 等目录）**

```bash
cd /你解压的位置/项目根目录/_tools
```

以下命令默认当前目录已是 **`_tools`**。

---

## 三、安装 Python 依赖

```bash
cd _tools
pip3 install -r requirements.txt
```

若 `pip3` 不可用，可试：

```bash
python3 -m pip install -r requirements.txt
```

---

## 四、安装 Playwright 浏览器（仅自动部署需要）

若要用 `pipeline.py` **自动打开浏览器部署到纷享**，执行：

```bash
playwright install chromium
```

若只 **生成代码**（`--step generate`），可跳过本步。

---

## 五、本地配置（每人一份，勿提交仓库）

1. 在 `_tools` 目录下复制模板：

```bash
cp config.yml config.local.yml
```

2. 用编辑器打开 **`config.local.yml`**，至少改这些（按自己租户填写）：

- **`fxiaoke.base_url`**：纷享登录域名，如 `https://xxx.fxiaoke.com`
- **`fxiaoke.username` / `fxiaoke.password`**：登录账号密码（或改用环境变量，见下）
- **`fxiaoke.project_name`**：后台项目名称，影响 `.fields_cache/项目名/` 目录
- **`fxiaoke.function_path`**：函数管理页在浏览器地址栏里的路径（以 README 说明为准）
- **`openapi.*`**：开放平台 `app_id`、`app_secret`、`corp_id` 等（做 OpenAPI 测试时需要）
- **`llm.*`**：生成 APL 用的厂商与 `api_key`（或只用环境变量）

**敏感信息也可用环境变量**（不配在文件里也行），例如：

```bash
export ANTHROPIC_API_KEY="sk-ant-xxx"
# 或
export OPENAI_API_KEY="sk-xxx"

export FX_USERNAME="你的纷享账号"
export FX_PASSWORD="你的纷享密码"
```

（Windows CMD/PowerShell 用 `set` / `$env:...` 自行等价设置。）

> **`config.local.yml` 已在 `.gitignore` 中**，正常不会提交；不要把它发给他人或贴到聊天。

---

## 六、准备需求文件 `req.yml`

在 **`_tools` 目录**（或你指定的路径）新建/修改 `req.yml`，填写对象 API、函数类型、需求描述等。  
格式见同目录 **`README.md`** 里「准备需求文件」一节。

---

## 七、常用命令（在 `_tools` 下执行）

**只生成代码（不写纷享）：**

```bash
cd _tools
python3 pipeline.py --req req.yml --step generate
```

**生成并自动部署（新建函数）：**

```bash
python3 pipeline.py --req req.yml --step deploy
```

**更新已有函数（需知道系统里的函数 API 名）：**

```bash
python3 pipeline.py --req req.yml --step deploy --update --func-api-name Proc_XXX__c
```

**抓取字段缓存（首次或字段变更）：**

```bash
python3 pipeline.py --req req.yml --step fetch
```

**一条龙（含测试时还需准备用例 YAML）：**

```bash
python3 pipeline.py --req req.yml --case tester/cases/某用例.yml --step all
```

若 `python3` 不可用，把上面命令里的 `python3` 改成 `python`。

---

## 八、可选：凭据小工具

若仓库里带有 `set_credentials.py`，可在 `_tools` 下按脚本说明更新 `config.local.yml` 中的账号（不要把密码写进聊天记录）。

---

## 九、出问题先看哪里

- **`README.md`**：快速开始、目录说明、飞书表格记录
- **`TROUBLESHOOTING.md`**：生成超时、部署失败、选择器过期等
- 确认 **`config.local.yml`** 里租户地址、`project_name`、OpenAPI、LLM 是否与当前环境一致

---

## 十、压缩包建议包含 / 不包含

| 建议包含 | 建议不要包含（每人自建） |
|----------|---------------------------|
| `config.yml`（模板） | `config.local.yml` |
| `pipeline.py`、`requirements.txt`、各子目录源码 | `.env` |
| `README.md`、本文件、`TROUBLESHOOTING.md` 等 | `deployer/session*.json`、`deployer/screenshots/` |
| 示例 `req.yml`（可脱敏） | 真实密码、app_secret、LLM Key |

按上表打包，别人解压后从 **第二节 → 第七节** 做一遍即可使用。
