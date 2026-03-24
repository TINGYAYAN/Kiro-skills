# 函数需求提交约定（技术细节）

**需求信息模板见 [REQ_TEMPLATE.md](REQ_TEMPLATE.md)**：用户需发什么、已做/新项目逻辑、复制填空模板。

本文档为技术补充：config 项说明、推断规则。每次完成函数需求时，未提供的信息由 AI 自行分析推断。

---

## 一、登录 / 环境（如有变更需告知）

| 项 | 说明 | 示例 |
|----|------|------|
| **代理登录** | 登录方式已改为代理登录，需配置 `agent_login_employee_id`。若在新环境/新项目，需告知员工 ID；首次需手动登录一次生成 session | `agent_login_employee_id: "1001"` |
| **项目名** | 多项目时用于 sharedev 拉取、session 分文件 | `project_name: "硅基流动"` |
| **ShareDev 证书** | 字段/函数拉取优先用证书 API（准确），未配置则用浏览器抓取（不准确）。请在 cert.conf 或 config 中配置 domain 和 cert | 见 cert.conf.example、sharedev_pull/README.md |
| **代理登录 URL** | 切换环境时，可提供一次性 token URL。部署时设置 `FX_BOOTSTRAP_TOKEN_URL` 或 config `bootstrap_token_url`，会优先用其登录。生成方式：`python -m deployer.agent_login_test`（需先有 session）| `https://www.fxiaoke.com/FHH/EM0HXUL/SSO/Login?token=xxx` |
| **Bootstrap 脚本** | 有 token URL 时，可先运行 `python -m deployer.bootstrap_token_login "token_url"` 保存 cookies，再运行 pipeline | 见 deployer/bootstrap_token_login.py |
| **数据源偏好** | 部署时选择的数据源。`datasource_prefer` 按名称匹配（如「其他数据源」），`datasource_index` 为 0-based 索引 | `datasource_prefer: "其他数据源"` 或 `datasource_index: 1` |

---

## 二、函数需求（必填）

| 项 | 必填 | 说明 | 示例 |
|----|------|------|------|
| **requirement** | ✓ | 需求描述，越具体越好 | 新建租户时，根据组织机构代码查找客户，若存在则关联，否则新建客户并关联 |
| **object_label** | 流程/按钮等有绑定对象时 | 绑定对象中文名 | 租户、客户、销售线索 |
| **object_api** | 可选 | 对象 API 名，已知则填 | `tenant__c`、`AccountObj` |
| **function_type** | ✓（建议） | 函数类型，明确可显著提高准确度 | 见下表 |

### 函数类型（function_type）可选值

| 类型 | 说明 |
|------|------|
| 流程函数 / flow | 工作流/流程触发，绑定对象，`context.data` 取当前记录 |
| 按钮 / button | 对象列表或详情的按钮点击触发 |
| 自定义控制器 / controller | 无绑定对象，`call_controller` 调用，return Map 作为接口响应 |
| 计划任务 / scheduled_task | 定时任务，无绑定对象 |
| UI函数 / ui | UI 事件（如字段变更、加载） |
| 范围规则 / range_rule | 数据范围过滤 |
| 同步前/后函数 | 集成流同步前后钩子 |
| 校验函数 / validation | 数据校验 |
| 自增编号 / auto_number | 自增编号规则 |
| 导入 / import | 导入相关 |

---

## 三、req.yml 模板示例

```yaml
requirement: |
  创建计划任务函数。查询银行流水对象日期距当前日期 1 个月内的全部数据，
  汇总打款金额，将汇总金额更新到客户对象上的近一个季度回款字段上。
object_label: 银行流水
object_api: payment_record__c
function_type: scheduled_task   # 或 计划任务

# 若涉及多对象，可补充字段 API 名
# 银行流水：date__c, transfer_amount__c, store_name__c
# 客户：quarterly_repayment__c
```

---

## 四、未提供时的推断规则

- **function_type**：从需求关键词推断，如含「计划任务」「定时」→ 计划任务；含「按钮」「点击」→ 按钮；含「接口」「控制器」「call_controller」→ 自定义控制器；含「范围」「过滤」→ 范围规则；默认 → 流程函数
- **object_label**：从需求中对象名推断
- **object_api**：优先查 `.fields_cache`、`sharedev_pull`，或通过 OBJECT_LABEL_TO_API 映射
