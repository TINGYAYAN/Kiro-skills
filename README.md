# APL 自动化流水线

根据业务需求自动生成 APL 函数代码，通过 **Playwright 浏览器自动化** 部署到纷享销客，并用 OpenAPI 驱动自动化测试。

> 📋 **能力总览**：技能清单、技术架构、报错机制、数据闭环、提效场景、与对话式生成的差异、Playwright 核心作用 → 见 [OVERVIEW.md](OVERVIEW.md)

## 他人电脑 / 协作怎么用（避免用你的配置）

- **不要**把 `config.local.yml`、`.env`、session 截图等提交到 Git：它们已在 `_tools/.gitignore` 里忽略。
- **可以**提交的是 **`config.yml`**（模板，用占位符）、代码、`req.yml`、流水线脚本等。
- 同事克隆仓库后在本机执行：
  1. `cd _tools && pip install -r requirements.txt`（部署还要 `playwright install chromium`）
  2. `cp config.yml config.local.yml`，**只改自己的** `config.local.yml`：纷享 `base_url` / 账号 / `project_name`、OpenAPI、LLM Key、`function_path` 等。
  3. 敏感信息也可用环境变量（见下文「配置」），同样不要写进聊天或提交仓库。
- 每人租户不同：`fxiaoke.project_name`、`base_url`、`function_path`、OpenAPI 都要换成**对方环境**的；字段缓存目录是 `.fields_cache/<project_name>/`，互不冲突。

## 快速开始

### 1. 安装依赖

```bash
cd _tools
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置

复制并填写配置文件：

```bash
cp config.yml config.local.yml
# 编辑 config.local.yml，填入纷享账号、OpenAPI 凭证、LLM API Key
# 配置 fxiaoke.project_name（如「硅基流动」）后，字段缓存将按项目分目录存放，便于多项目复用
# 配置 rag.enabled: true 启用 RAG 语义检索（需 OPENAI_API_KEY，用于 embedding）
```

也可通过环境变量设置敏感信息：

```bash
export ANTHROPIC_API_KEY=sk-ant-xxx   # 或 OPENAI_API_KEY
export FX_USERNAME=your_account
export FX_PASSWORD=your_password
```

### 可选：ShareDev 证书认证（免密码拉取对象/函数）

若有纷享**开发者证书**，可免账号密码拉取租户对象列表和 APL 函数代码。任选一种配置：

1. **cert.conf**：项目根目录创建，内容：
   ```ini
   [sharedev]
   domain = https://www.fxiaoke.com
   cert = 你的开发者证书内容
   ```
2. **config.local.yml**：在 `fxiaoke` 下添加 `sharedev_domain`、`sharedev_certificate`

拉取命令：
```bash
python -m fetcher.sharedev_client --objects          # 对象列表
python -m fetcher.sharedev_client --functions       # 函数列表
python -m fetcher.sharedev_client --describe AccountObj  # 对象字段描述
```

### 代理登录（推荐，避免 Playwright 自动填表）

**不再使用 Playwright 自动填账号密码**，改为每次调用 GetAdminAgentLoginToken 获取带 token 的登录 URL，跳转后完成登录，更稳定。

```yaml
# config.local.yml
fxiaoke:
  agent_login_employee_id: "1001"  # 要代理登录的员工 ID（必填）
  project_name: "硅基流动"        # 用于 session 文件分项目存储
```

**流程**：
1. 首次需有一次有效 session（见下方「手动登录」）→ 保存 cookies 到 `session_{project}.json`
2. 后续部署 → 用 session 文件中的 cookies 调用 GetAdminAgentLoginToken → 拿到 token URL → Playwright 跳转 → 自动登录
3. Session 过期时 → 手动登录一次 → 保存新 cookies → 后续再次走代理登录

**手动登录（首次或 session 过期时）**：打开登录页后，在浏览器中手动输入账号密码、验证码等，程序检测到登录成功后自动继续。不依赖 Playwright 选择器，更稳定。

### 3. 准备需求文件

创建 `req.yml`（参考下方格式）。**提交约定**见 [REQ_CONVENTION.md](REQ_CONVENTION.md)：建议明确提供 `function_type`、`object_label`，未提供时由 AI 推断。

```yaml
requirement: |
  根据当前记录的<客户名称>字段，到【客户】对象查找匹配的客户，
  找到则将客户ID写入<关联客户>字段，并更新<状态>为"已匹配"；
  未找到则更新<状态>为"未找到"。
object_api: your_object__c
object_label: 你的对象名
function_type: 流程函数          # 支持：流程函数|UI函数|自定义控制器|计划任务|按钮|范围规则|同步前函数|同步后函数|校验函数|自增编号|导入|关联对象范围规则|强制通知|促销|金蝶云星空|数据集成。英文别名：flow, range_rule, button, ui, controller 等
namespace: 流程                  # 可选，不填则根据 function_type 自动推断。可选值：流程、UI事件、自定义控制器、计划任务、按钮、校验函数等
code_name: 【流程】根据名称关联客户   # 格式：【命名空间】+ 简短概括
output_dir: 你的客户目录         # 相对于 test拨号/ 目录
output_file: 根据名称关联客户    # 不含扩展名
```

### 4. 运行

```bash
# 仅生成代码（生成后在对应目录查看）
python pipeline.py --req req.yml --step generate

# 生成 + 自动部署到纷享（新建函数：不搜索，直接新建）
python pipeline.py --req req.yml --step deploy

# 需求变更/修改：按 API 名搜索后编辑，在现有函数基础上修改（需提供 func_api_name）
python pipeline.py --req req.yml --step deploy --update --func-api-name Proc_XXX__c
# 或在 req.yml 中写 func_api_name: Proc_XXX__c 后：python pipeline.py --req req.yml --step deploy --update

# 完整流水线（生成 + 部署 + 测试）
python pipeline.py --req req.yml --case tester/cases/your_case.yml --step all

# 仅测试已部署的函数
python pipeline.py --case tester/cases/your_case.yml --step test
```

**部署模式说明**：
- **新建函数**（默认）：函数需求时直接新建，不搜索。
- **更新函数**（`--update`）：需求变更/需求修改时，必须提供 `func_api_name`，按 API 名搜索 → 点编辑 → 在现有函数基础上修改。

## skill目录结构

```
_tools/
├── .fields_cache/           # 字段缓存（按项目分目录，如 硅基流动/tenant__c.yml）
├── .rag_index/              # RAG 向量索引（gitignore，首次生成或新增 APL 后自动构建）
├── pipeline.py              # 主入口
├── config.yml               # 配置模板（不含敏感信息）
├── config.local.yml         # 本地配置（gitignore，填入真实凭证）
├── utils.py                 # 公共工具
├── generator/
│   ├── generate.py          # APL 代码生成器
│   ├── prompt.py            # LLM prompt 构建（含 few-shot）
│   └── examples/            # few-shot 示例
├── rag/                     # RAG 语义检索（可复用于生成器等）
│   ├── retriever.py         # 通用向量检索器（ChromaDB）
│   ├── apl_examples.py      # APL 示例检索
│   └── rebuild_index.py     # 重建索引（新增 APL 后执行 python -m rag.rebuild_index）
├── deployer/
│   ├── deploy.py            # Playwright 浏览器部署
│   ├── selectors.py         # 纷享销客页面 CSS 选择器
│   └── screenshots/         # 部署截图（自动生成，gitignore）
├── tester/
│   ├── openapi_client.py    # 纷享 OpenAPI 封装
│   ├── test_runner.py       # 测试执行器
│   ├── cases/               # YAML 格式测试用例
│   │   └── example_申领T2经销商.yml
│   └── reports/             # 测试报告（自动生成，gitignore）
└── templates/
    └── header.j2            # APL 文件头部注释模板
```

## 测试用例格式

```yaml
function: 函数名称
description: 测试描述

setup:            # 测试前创建的数据
  - id: record1
    action: create
    object: some_object__c
    data:
      field1: "value1"

trigger:          # 触发函数执行的操作
  - id: main_record
    action: create
    object: bound_object__c
    data:
      ref_field: "value1"

assertions:       # 验证结果
  - description: 字段应更新为期望值
    object: bound_object__c
    record_ref: "trigger.main_record"
    field: result_field__c
    operator: eq          # eq | not_null | null | contains | not_eq
    expected: expected_value

teardown:         # 清理测试数据（倒序执行）
  - action: delete
    object: bound_object__c
    record_ref: "trigger.main_record"
  - action: delete
    object: some_object__c
    record_ref: "setup.record1"
```

## 飞书记录（可选）

部署成功后，可将函数信息自动追加到飞书表格，便于团队统一查看。

### 方式一：电子表格（推荐，更简单）

1. 在飞书中新建「电子表格」
2. 第一行填写表头：**函数名** | **描述** | **绑定对象** | **系统API名**
3. 从 URL 获取 `spreadsheet_token`：`https://xxx.feishu.cn/sheets/XXXXX` → 其中 `XXXXX` 即为 token
4. 在 `config.local.yml` 的 `feishu` 下填写 `spreadsheet_token`

### 方式二：多维表格

1. 在飞书中创建多维表格，新建数据表。批量生成**建议按模板建表**，不要只保留自由文本一列
2. 推荐表头包含列：**描述**、**绑定对象**、**函数类型**、**项目**、**函数名**、**系统API名**、**状态**、**执行时间**、**执行反馈**、**风险级别**、**人工处理建议**
3. 其中 **函数名**、**系统API名** 需要保持留空，系统据此识别为待执行
4. 从 URL 获取 `app_token` 和 `table_id`：`https://xxx.feishu.cn/base/APP_TOKEN?table=TABLE_ID`
5. 在 `config.local.yml` 的 `feishu` 下填写 `bitable_app_token`、`bitable_table_id`

可直接使用模板文件：

- [bitable_template_blank.csv](/Users/yanye/code/test拨号/_tools/bitable_template_blank.csv)
- [bitable_template_example.csv](/Users/yanye/code/test拨号/_tools/bitable_template_example.csv)

如果你已经有一张固定的模板表，也可以在 `config.local.yml -> feishu.template_table_url` 里配置固定链接。之后生成“批量模板回复文案”时，会优先引用这张表，不再临时创建新模板表。

未配置或配置不完整时，流水线会静默跳过飞书记录步骤。

## 流水线不工作？

优先看 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 开头的「流水线整体不工作」：
- **生成无反应/超时** → 检查 `config.local.yml` 的 LLM 配置（模型、代理、timeout）
- **批量无待执行** → 飞书表格需新增行，至少填描述，且函数名/系统API名留空
- **req.yml 示例** → 见 `req.yml`，建议补全 code_name、output_dir、output_file

## 注意事项

- **部署器 selectors**：纷享销客 UI 升级后，如果部署失败请检查 `deployer/selectors.py` 中的选择器，可通过 `PWDEBUG=1 python deployer/deploy.py ...` 打开 Playwright Inspector 重新录制。
- **测试等待时间**：函数执行需要时间，可在 `config.yml` 的 `tester.trigger_wait_seconds` 调整等待秒数。
- **LLM 生成质量**：生成后建议人工检查字段名是否与实际对象匹配，首次使用时可先 `--step generate` 检查代码再部署。
