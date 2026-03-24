# 需求信息模板

本文档说明 AI 需要用户提供什么信息，以及 AI 的自动尝试逻辑。

---

## 一、AI 行为逻辑

### 已做过项目（有缓存可复用）

**判定条件**：存在以下任一即可视为「已做过」：
- `deployer/session_{项目名}.json` 或 `session_cookies.json`（登录 session）
- `cert.conf` 或 config 中配置了 ShareDev 证书
- `sharedev_pull/{项目}/` 下有 objects.json、functions.json

**AI 行为**：优先使用缓存的 session 和开发者证书自动尝试登录、拉取字段/函数、部署。**仅当失败时**再向用户索要对应信息。

### 未做过项目（新项目）

**判定条件**：项目名在本地无 session、无该项目的 cert 配置、无 sharedev_pull 数据。

**AI 行为**：直接要求用户按下方模板提供环境配置信息，拿到后再执行。

---

## 二、新项目必备信息（一次性提供）

请按下面模板填写，发给我：

```yaml
# === 新项目环境配置（复制后填空） ===

# 项目名称（必填，用于 session 分文件、sharedev 按项目拉取）
project_name: "_______"

# 纷享销客 base_url（通常为 https://www.fxiaoke.com，测试租户可能不同）
base_url: "https://www.fxiaoke.com"

# 开发者证书（必填，用于准确拉取字段/函数。从租户后台「开发者证书」申请后粘贴）
sharedev_certificate: "粘贴你的开发者证书全文"

# 代理登录 URL（必填，部署/拉取前用其登录。格式如 https://www.fxiaoke.com/FHH/xxx/SSO/Login?token=xxx）
# 生成方式：租户后台获取，或已有 session 时运行 python -m deployer.agent_login_test
bootstrap_token_url: "https://www.fxiaoke.com/FHH/xxx/SSO/Login?token=_______"

# 可选：数据源偏好（部署时选哪个数据源，不填则用第一个）
# datasource_prefer: "其他数据源"
# datasource_index: 1
```

**说明**（索要时让用户知道要什么、哪里找、用来做什么）：
- **项目名称**：用于 session 分文件、sharedev 按项目拉取
- **开发者证书**：租户后台 → 系统设置 → 开发者证书，申请后复制全文。用途：准确拉取对象字段和函数
- **代理登录 URL**：用于首次登录。格式 `https://www.fxiaoke.com/.../SSO/Login?token=xxx`，租户后台获取或 `python -m deployer.agent_login_test` 生成

---

## 三、函数需求信息（每次提需求时发）

### 必填

| 项 | 说明 | 示例 |
|----|------|------|
| **requirement** | 需求描述，越具体越好 | 新建租户时，根据组织机构代码查找客户，若存在则关联，否则新建客户并关联 |
| **function_type** | 函数类型（见下表） | flow / button / scheduled_task / controller |
| **object_label** | 绑定对象中文名（流程/按钮等有绑定时必填） | 租户、客户、提货单 |

### 可选（已知则填，提高准确度）

| 项 | 说明 | 示例 |
|----|------|------|
| object_api | 对象 API 名 | tenant__c、AccountObj |
| 相关对象 | 涉及多对象时，补充对象及其字段 | 银行流水：date__c, amount__c；客户：quarterly_repayment__c |
| 字段 API 名 | 需求中涉及的字段，由 AI 从 lookup_fields_for_req.py 查得后写入草稿 | 日期→date__c、打款金额→transfer_amount__c、近一个季度回款→quarterly_repayment__c |
| namespace | 命名空间（默认流程） | 流程、按钮 |
| datasource_prefer | 运行数据源 | "其他数据源" |

### function_type 可选值

| 值 | 说明 |
|----|------|
| flow | 流程函数，工作流触发 |
| button | 按钮函数，列表/详情按钮点击 |
| controller | 自定义控制器，接口调用 |
| scheduled_task | 计划任务，定时执行 |
| ui | UI 函数，字段变更/加载 |
| validation | 校验函数 |
| range_rule | 范围规则 |

### 函数需求模板（复制填空）

```yaml
# === 函数需求（复制后填空） ===

requirement: |
  请在此处详细描述需求，包括：
  - 触发时机（如：新建租户时、点击按钮时、每天定时）
  - 业务逻辑步骤
  - 涉及的对象和字段
  - 预期的结果

function_type: flow   # flow | button | controller | scheduled_task | ui | validation | range_rule

object_label: "_______"   # 绑定对象中文名，如：租户、客户、提货单

# 可选
object_api: "_______"     # 若已知，如 tenant__c
namespace: "流程"         # 流程 | 按钮 等
```

---

## 四、失败后需补发的信息

当 AI 用缓存自动尝试**失败**时，会根据报错向你索要：

| 场景 | 需要你补发 |
|------|------------|
| 登录失败 / session 过期 | 代理登录 URL（带 token 的免密登录地址） |
| ShareDev 拉取失败 / 证书无效 | 开发者证书全文（确保 domain、cert 正确） |
| 字段不准确 / 对象未找到 | object_api、object_label，或确认对象名 |
| 部署时数据源错误 | datasource_prefer 或 datasource_index |

---

## 五、快速检查：我是不是「已做过」项目？

在项目 `_tools` 目录下检查：

```
_tools/
├── deployer/session_硅基流动.json    # 有 → 该项目的 session 已缓存
├── cert.conf                          # 有且 [sharedev] 或 [sharedev.项目] 填了 domain/cert → 证书已配置
└── sharedev_pull/
    └── 硅基流动/
        ├── objects.json               # 有 → 对象元数据已拉取
        └── functions.json             # 有 → 函数列表已拉取
```

若以上都有，AI 会先自动尝试，失败再找你。

---

## 六、AI 对接流程（用户说「想生成 XX 项目的函数需求」时）

1. **模糊查询**：查 `session_*.json`、`sharedev_pull/*/`、`cert.conf`、`config` 中是否含 XX 或相似项目名。
2. **有匹配**：列出项目信息（项目名、是否有 session、是否有 cert、是否有 sharedev 数据），请用户确认：「是否用这个项目？」
3. **无匹配**：直接向用户索要：
   - project_name
   - sharedev_certificate
   - bootstrap_token_url
