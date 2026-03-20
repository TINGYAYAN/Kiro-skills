"""构建 LLM system prompt 和 few-shot 示例。"""
import os
import re
import random
from pathlib import Path

EXAMPLES_DIR = Path(__file__).parent / "examples"
# 项目根目录（test拨号/），向上两级
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 不扫描的目录
_SKIP_DIRS = {".git", ".cursor", ".trae", "_tools", "node_modules", "__pycache__", "插件"}
# 不扫描的文件扩展名
_SKIP_EXTS = {".js", ".vue", ".md", ".json", ".yml", ".yaml", ".txt",
              ".png", ".jpg", ".zip", ".jar", ".DS_Store", ".py",
              ".html", ".css", ".ts", ".java", ".xml"}

# APL 代码特征词（满足任意一条即认为是 APL 文件）
_APL_SIGNATURES = ["Fx.object.", "FQLAttribute", "QueryTemplate", "context.data",
                   "UIEvent", "syncArg", "log.error", "log.info", "Fx.global.",
                   "UpdateAttribute", "CreateAttribute", "SelectAttribute"]

RULES = """
你是纷享销客 PaaS 平台的全栈开发人员，负责用类 Groovy 语言（APL）编写自定义函数。
参考开发文档：https://www.fxiaoke.com/mob/guide/apl_nc/dist/pages/func-apl/api/ObjectDataAPI/

### ⚠️ 重要：语法限制
纷享平台的 Groovy 编译器对某些语法支持不完整，**必须遵守以下规则**：
1. **禁止使用 Elvis 运算符 `?:`**（会导致编译错误 "expecting ':'"）
2. **禁止使用三元运算符 `? :`**（包括 `a ? b : c`，平台常报 "expecting ':', found 'if'"）
3. **条件分支一律用 if-else 块**，不要用 `def x = cond ? if(a){...} : b` 或任何 `?:` 形式
4. 空值处理用 if 语句：`if (!x) x = ""`
5. **禁止使用 `?["key"]` 安全下标访问**（会导致 "expecting ',', found '@'" 编译错误）
6. Map 的安全属性访问必须用 `?._id`（点属性）或 `?.get("key")`（方法调用）

错误示例：
```
// ❌ 错误 - Elvis/三元会报 "expecting ':'" 或 "expecting ':', found 'if'"
String name = (data["name"] as String) ?: ""
def x = cond ? if (a) { valA } : valB   // if 不能放在 ?: 内

// ❌ 错误 - ?["key"] 在 APL 中不支持，会报 "expecting ',', found '@'"
String id = result?["_id"] as String
Map dataMap = result?["data"] as Map
```

正确示例：
```
// ✅ 正确 - 用 if 语句处理空值，用 ?._id 或 ?.get() 安全访问属性
String name = context.data.name as String
if (!name) name = ""

// ✅ 正确 - 从 create/update/copyByRule 返回的 Map 中取 ID
String id = result?._id as String
if (!id) {
    id = (result?.get("data") as Map)?._id as String
}
```

### 平台限制与规范
- 文件后缀 .apl，类 Groovy 语法，有纷享封装限制
- **日期计算**：禁止使用 `java.util.Date` 和 `Calendar`（平台用 `com.fxiaoke.functions.time.Date` 不兼容）。用 Long 时间戳：`long oneMonthAgo = System.currentTimeMillis() - (30L * 24 * 60 * 60 * 1000)`，QueryOperator.GTE/LTE 传 Long
- 上下文通过 `context` 获取，数据通过 `context.data.字段API名` 取值（点属性访问，不用下标）
- 所有 API 调用返回三元组：`def (Boolean error, ResultType result, String errorMessage) = Fx.xxx()`
- 出错时 `log.error(...)` 后直接 `return`，不嵌套过多 if-else
- 流程函数：直接操作对象，无返回值
- UI函数：必须返回 `UIEvent`，通过 `UIEvent.build(context) { ... }` 构建
- 同步前/后函数：通过 `syncArg["data"]` 取入参，可 return Map

### ⚠️ 严禁使用的废弃 API（会导致保存失败）
以下写法已被平台标记为废弃，扫描时报红色错误，**绝对不能使用**：
```
// ❌ 禁止 - 2参数 create（已废弃）
Fx.object.create("objectApi", ["field": value])

// ❌ 禁止 - 3参数 create with CreateAttribute（签名不匹配，编译报错）
Fx.object.create("objectApi", ["field": value], CreateAttribute.builder().build())

// ❌ 禁止 - 3参数 update（已废弃）
Fx.object.update("objectApi", id, ["field": value])
```

### ✅ 正确 API 写法（必须严格按照以下签名）
```
// 查询（必须传入 SelectAttribute）
def (Boolean err, QueryResult r, String msg) = Fx.object.find(
    "objectApi",
    FQLAttribute.builder()
        .columns(["_id", "field"])
        .queryTemplate(QueryTemplate.AND(["field": QueryOperator.EQ(value)]))
        .build(),
    SelectAttribute.builder().build()
)

// 按 ID 查询
def res = Fx.object.findById("objectApi", id,
    FQLAttribute.builder().columns(["_id", "field"]).build(),
    SelectAttribute.builder().build())
Map data = res?.data as Map

// ✅ 正确 update - 4个参数，第4个必须是 UpdateAttribute
def (Boolean updateErr, Map updateResult, String updateMsg) = Fx.object.update(
    "objectApi", id, ["field": value] as Map<String, Object>,
    UpdateAttribute.builder().triggerWorkflow(true).build()
)

// ✅ 正确 create - 4个参数，第3个是空 Map [:]，第4个是 CreateAttribute
def (Boolean createErr, Map createResult, String createMsg) = Fx.object.create(
    "objectApi", ["field": value] as Map<String, Object>,
    [:],
    CreateAttribute.builder().triggerWorkflow(false).build()
)

// 添加团队成员
def attr = TeamMemberAttribute.createEmployMember(
    [userId], TeamMemberEnum.Role.NORMAL_STAFF, TeamMemberEnum.Permission.READONLY
)
Fx.object.addTeamMember("objectApi", objectId, attr)

// copyByRule（对象转换映射规则）
// ⚠️ copyByRule 的返回结构与普通 create 不同，必须打印原始结果用于调试
def (Boolean copyErr, Map copyResult, String copyMsg) = Fx.object.copyByRule(
    "srcObjectApi", srcId, "mapRuleApi", masterDataMap, detailDataMap
)
if (copyErr) { log.error("[业务] copyByRule 失败: " + copyMsg); return }
// 必须打印原始结构，让运行日志告诉我们实际返回了什么，再据此提取 ID
log.info("[业务][诊断] copyByRule result: " + copyResult?.toString())
// copyByRule 可能的 ID 路径（按诊断日志确认后选一条）：
// ✅ 用 ?._id 和 ?.get() - 绝对不能用 ?["_id"]（APL 不支持安全下标）
String newId = copyResult?._id as String
if (!newId) {
    newId = (copyResult?.get("data") as Map)?._id as String
}
if (!newId) {
    newId = copyResult?.get("newId") as String
}
if (!newId) { log.error("[业务] 终止: 未获取到新记录ID，请查看上方[诊断]日志确认实际结构"); return }
log.info("[业务] 新记录ID: " + newId)

// 全局变量
def (Boolean err, String val, String msg) = Fx.global.findByApiName("varApiName")
```

### 代码风格
- 变量用驼峰命名
- 类型转换统一用 `as String`、`as List`、`as Map`
- 空值检查：`if (xxx != null && xxx.size() > 0)`
- **避免使用 Elvis 运算符 `?:`**，纷享平台的 Groovy 编译器对复杂表达式支持不好，用 if 语句代替
- 三元组中的返回值必须使用真实变量名（如 `updateResult`、`createResult`），
  **不要用 `_`**（平台会报 "variable '_' is not used" warning）

### 必须：分段注释与业务日志（便于根据运行日志排查测试）
生成的代码**必须**包含以下两类内容，便于部署后根据「运行日志」排查业务问题；
**调试时结合日志分析**：若没获取到数据先看入参与逻辑是否正确，不要仅以无报错就认为成功。

1. **分段注释**：按逻辑步骤在代码前加一行注释，格式为：
   \`// ----- 1. 步骤简述 -----\`
   例如：\`// ----- 1. 取当前记录数据 -----\`、\`// ----- 2. 按条件查询 xxx -----\`、\`// ----- 3. 回写/更新 -----\`

2. **关键业务日志**：
   - **入参**：在取完 context 数据并做空值检查前，打一条 \`log.info("入参: key1=" + val1 + ", key2=" + val2)\`（只输出关键字段，敏感信息可脱敏）。
   - **提前终止**：每次 \`return\` 前若是业务校验失败，用 \`log.error("终止: 原因")\`。
   - **关键分支**：查询前 \`log.info("按 xxx 查询: " + 条件)\`；查到/未查到、新建前/新建成功、更新前 各打一条 \`log.info("[业务] 步骤结果简述")\`。
   - **API 原始结果**：所有 API 调用成功后（create / copyByRule 等），在提取 ID 之前必须先打 \`log.info("[业务][诊断] result: " + result?.toString())\`，让日志告诉我们实际返回的数据结构，再据此提取所需字段。这样一旦取不到 ID，看日志就能立刻知道真实的结构是什么。
   - **失败**：API 调用失败时 \`log.error("[业务] 操作失败: " + msg)\`。
   - **完成**：最后成功时 \`log.info("[业务] 完成: 结果简述")\`。

示例片段：
\`\`\`
// ----- 1. 取当前记录数据 -----
String id = context.data["_id"] as String
log.info("入参: id=" + (id ?: "空"))
if (!id) { log.info("终止: ID为空"); return }

// ----- 2. 按条件查询 -----
log.info("按xxx查询: " + id)
def (Boolean err, QueryResult r, String msg) = Fx.object.find(...)
if (err) { log.error("查询失败: " + msg); return }
log.info("查到N条 / 未查到，将新建...")
// ...
log.info("完成success: 已关联/已更新")
\`\`\`

### ⚠️ 禁止编造字段 API 名
- 字段名必须来自给定的对象字段列表，**禁止用中文或占位描述作为 API 名**（如 `["近一个月回款字段API名": value]` 会导致运行时错误）
- 若需求中的字段在列表中未找到，用占位符如 `TODO_REPLACE_NEAR_MONTH_RECEIPT` 并注释 `// 待确认：近一个月回款 字段 API 名需在平台对象管理中查看后替换`

### ⚠️ 未使用变量会导致保存失败（扫描 warning 阻断保存）
平台会检查每个在三元组中声明的变量是否被使用。**每次 API 调用后必须**：
1. `if (err) { log.error("操作失败：" + msg); return }` — 确保 `msg` 被引用
2. 如果 result Map 不需要用，也必须出现在代码中，例如：
   `if (!err) { log.info("操作成功") }`  ← 至少写一行 else/success 分支
   或者直接从 result 取 id：`String newId = result?._id as String`

**正确的错误处理模板**（每个 find/create/update 调用都必须完整套用）：
```
// find
def (Boolean findErr, QueryResult findResult, String findMsg) = Fx.object.find(...)
if (findErr) { log.error("查询失败：" + findMsg); return }  // findMsg 被使用

// create
def (Boolean createErr, Map createResult, String createMsg) = Fx.object.create(...)
if (createErr) { log.error("创建失败：" + createMsg); return }
String newId = createResult?._id as String  // createResult 被使用

// update
def (Boolean updateErr, Map updateResult, String updateMsg) = Fx.object.update(...)
if (updateErr) { log.error("更新失败：" + updateMsg) }  // updateMsg 被使用
else { log.info("更新成功") }  // 确保 updateResult 无需用时逻辑仍完整
```
""".strip()

FUNCTION_TYPE_HINTS = {
    "流程函数": "绑定到对象的工作流/流程节点，通过 context.data 获取当前记录数据，无需 return。",
    "UI函数": "绑定到页面事件（新建/编辑时触发），必须 return UIEvent。",
    "同步前函数": "在数据同步到 ERP 前执行，通过 syncArg[\"data\"] 取数据，可 return Map 修改同步数据。",
    "同步后函数": "在数据从 ERP 同步回来后执行，通过 syncArg[\"data\"] 取数据。",
    "自定义控制器": "无绑定对象，通过 data/syncArg 取入参，return Map 作为接口响应，供前端 call_controller 调用。",
    "范围规则": (
        "绑定到关联字段的范围规则，控制关联字段可选择的记录范围。"
        "通过 context.data 获取当前表单数据（含未保存的字段值），"
        "return 一个包含 searchCondition 的 Map（QueryTemplate 格式）来过滤可选记录；"
        "若无需过滤则 return [:]（显示全部）。"
        "不得调用 Fx.object.create/update，只做条件判断和 return。"
    ),
    "按钮": "绑定到对象列表/详情的按钮，点击触发，通过 context 获取当前记录。",
    "按钮函数": "同按钮。",
    "计划任务": "定时触发，无 context.data，需自行查询数据。",
    "校验函数": "在保存前校验，return 校验结果（通过/不通过及提示）。",
    "自增编号": "生成自增编号规则，return 编号字符串。",
    "导入": "数据导入时处理每条记录。",
    "关联对象范围规则": "同范围规则，用于关联对象字段。",
    "强制通知": "触发通知规则。",
    "促销": "促销业务相关函数。",
    "金蝶云星空": "金蝶云星空集成相关。",
    "数据集成": "数据集成/同步相关。",
}


def _is_apl_file(path: Path) -> bool:
    """判断文件是否为 APL 代码（按扩展名或内容特征）。"""
    if path.suffix.lower() in _SKIP_EXTS:
        return False
    if path.suffix.lower() == ".apl":
        return True
    # 无扩展名文件：读前 2KB 判断是否含 APL 特征
    if path.suffix == "":
        try:
            head = path.read_bytes()[:2048].decode("utf-8", errors="ignore")
            return any(sig in head for sig in _APL_SIGNATURES)
        except Exception:
            return False
    return False


def _score_relevance(content: str, filename: str, function_type: str,
                     requirement: str) -> int:
    """给候选示例打相关性分（越高越相关）。"""
    score = 0
    text = (filename + "\n" + content).lower()
    req_lower = requirement.lower()

    # 1. 函数类型匹配
    type_keywords = {
        "流程函数": ["流程", "workflow", "proc_", "新建后", "更新后"],
        "UI函数": ["ui函数", "uievent", "ui_", "页面", "默认值"],
        "同步前函数": ["同步前", "syncarg", "sync_before"],
        "同步后函数": ["同步后", "syncarg", "sync_after"],
        "自定义控制器": ["自定义控制器", "cstmctrl", "call_controller", "控制器", "接口"],
        "范围规则": ["范围规则", "searchcondition", "querytemplat", "关联字段", "介绍人", "范围"],
        "按钮": ["按钮", "button", "点击", "触发"],
        "按钮函数": ["按钮", "button", "点击"],
        "计划任务": ["计划任务", "定时", "cron", "scheduled"],
        "校验函数": ["校验", "validation", "validate"],
        "自增编号": ["自增编号", "auto_number", "编号规则"],
        "导入": ["导入", "import"],
        "关联对象范围规则": ["关联对象范围", "关联范围"],
    }
    for kw in type_keywords.get(function_type, []):
        if kw in text:
            score += 3

    # 2. 必须有正确的新版 API（带 Attribute builder）
    if "UpdateAttribute" in content:
        score += 4
    if "CreateAttribute" in content:
        score += 4
    if "SelectAttribute" in content:
        score += 2

    # 3. 需求关键词命中
    # 提取中文词组和英文词（3字符以上）作为关键词
    keywords = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z_]{3,}', req_lower)
    for kw in keywords:
        if kw in text:
            score += 1

    # 4. 包含同类型 API 操作（create/update/find）
    for api in ["fx.object.find", "fx.object.create", "fx.object.update",
                "fx.object.findbyid", "fx.object.addteammember"]:
        if api in content.lower():
            score += 1

    return score


def _scan_project_apl_files() -> list:
    """扫描整个项目，返回所有 APL 文件路径列表。"""
    results = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        root_path = Path(root)
        # 跳过无关目录
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            fpath = root_path / fname
            if _is_apl_file(fpath):
                results.append(fpath)
    return results


def load_examples(function_type: str, num: int = 6, requirement: str = "") -> list:
    """从整个项目扫描 APL 文件，按相关性排序后返回 TOP-N 示例。"""
    # 先加载 examples/ 目录（保证必有的高质量示例）
    builtin = list(EXAMPLES_DIR.glob("*.apl"))

    # 再扫描全项目
    project_files = _scan_project_apl_files()
    # 去重（examples/ 里的文件也会被扫描到，去掉）
    builtin_names = {f.stem for f in builtin}
    project_files = [f for f in project_files
                     if f not in builtin and f.stem not in builtin_names]

    all_files = builtin + project_files

    # 读取内容并打分
    candidates = []
    for f in all_files:
        try:
            content = f.read_text(encoding="utf-8")
            # 过滤太短（< 100 字符）或太长（> 8000 字符）的文件
            if len(content) < 100 or len(content) > 8000:
                continue
            score = _score_relevance(content, f.stem, function_type, requirement)
            candidates.append((score, f, content))
        except Exception:
            continue

    # 按分数降序，分数相同随机打乱保持多样性
    random.shuffle(candidates)
    candidates.sort(key=lambda x: x[0], reverse=True)

    # 取 TOP-N，但每个目录（客户）最多取 2 个，保证多样性
    seen_dirs: dict = {}
    selected = []
    for score, f, content in candidates:
        dir_key = f.parent.name
        if seen_dirs.get(dir_key, 0) >= 2:
            continue
        seen_dirs[dir_key] = seen_dirs.get(dir_key, 0) + 1
        selected.append({"filename": f.stem, "content": content})
        if len(selected) >= num:
            break

    # 如果数量不足，放宽目录限制补足
    if len(selected) < num:
        existing_names = {e["filename"] for e in selected}
        for score, f, content in candidates:
            if f.stem not in existing_names:
                selected.append({"filename": f.stem, "content": content})
                if len(selected) >= num:
                    break

    return selected


_SCOPE_RULE_EXTRA = """
### ⚠️ 范围规则函数专属规范（必须严格遵守）

范围规则函数的唯一职责是**返回过滤条件**，绝对禁止查询数据库或做任何写操作。

**正确写法模板**：
```groovy
// 从当前表单取字段值（context.data 含未保存的字段）
String someField = context.data.field_api_name__c as String
if (!someField) someField = ""

if (someField == "值A") {
    return [
        "searchCondition": QueryTemplate.AND([
            "filter_field__c": QueryOperator.EQ("值A")
        ])
    ]
}

if (someField == "值B") {
    return [
        "searchCondition": QueryTemplate.AND([
            "filter_field__c": QueryOperator.EQ("值B")
        ])
    ]
}

// 获取不到值时显示全部
return [:]
```

**关键要点**：
- 必须 `return ["searchCondition": QueryTemplate.AND([...])]` 返回过滤条件
- 无需过滤时 `return [:]`
- **禁止** `Fx.object.find / create / update`
- **禁止** `log.info / log.error`（范围规则不产生运行日志）
- 代码极简，只做条件判断和 return，不做任何数据库操作

**⚠️ 选项字段（单选/多选）的值**：
需求中提到的任何选项值（如「门店」「用户」等）都是**选项的显示名称**，不是数据库存储值。纷享销客选项字段的存储值可能与显示名称不同（如数字 ID、英文 code 等）。
- **若字段列表已提供「选项」列**（格式：label=value），直接使用其中的 value 作为 QueryOperator.EQ 等参数，无需加待确认注释
- 若字段上下文未提供各选项的存储值，在代码顶部加：`// 待确认：以下选项值需在平台「对象管理-{绑定对象}-字段-{字段名}-选项」中查看真实存储值并替换`，用显示名作占位
"""


def build_system_prompt(function_type: str) -> str:
    type_hint = FUNCTION_TYPE_HINTS.get(function_type, f"按需求实现，遵循平台 API 规范。")
    base = f"{RULES}\n\n### 当前函数类型\n{function_type}：{type_hint}"
    if function_type == "范围规则":
        base += _SCOPE_RULE_EXTRA
    return base


def build_user_prompt(
    requirement: str,
    object_api: str,
    object_label: str,
    function_type: str,
    examples: list,
    fields_context: str = "",
) -> str:
    shots = ""
    for ex in examples:
        content = ex["content"]
        if len(content) > 3000:
            content = content[:3000] + "\n// ... (已截断)"
        shots += f"\n\n--- 示例：{ex['filename']} ---\n```groovy\n{content}\n```"

    if fields_context:
        fields_section = f"\n{fields_context}\n"
        fields_section += (
            "\n**字段匹配规则**：需求中的中文描述（如「生命状态」「审核通过日期」）"
            "应对应上表「字段标签」列，使用对应的「API 名」列值。\n"
        )
    else:
        fields_section = (
            "\n## 对象字段 API 名\n"
            "（未提供真实字段信息，请根据需求和命名惯例合理推断。"
            "自定义字段用 __c 后缀，标准字段如 _id / name 不加后缀）\n"
        )

    if function_type == "范围规则":
        output_requirements = """\
- 只输出纯 APL 代码，不要任何 markdown 代码块标记，不要任何解释文字
- 不要包含文件头部注释（/**...*/），头部会单独生成
- 禁止使用 log.info / log.error（范围规则不产生运行日志）
- 禁止调用 Fx.object.find / create / update 等数据库操作
- 字段 API 名若不确定，用合理推断值直接生成代码，在注释中标注「待确认」
- **选项字段**：若字段列表已提供选项列（label=value），直接使用 value；否则用显示名作占位并加 `// 待确认：...选项...` 注释
- 代码只做条件判断，最终 return ["searchCondition": QueryTemplate.AND([...])] 或 return [:]"""
    else:
        output_requirements = """\
- 只输出纯代码，不要任何 markdown 代码块标记（不要 ```groovy 等）
- 不要包含文件头部注释（/**...*/），头部会单独生成
- **必须**按逻辑步骤加分段注释（// ----- 1. 步骤简述 -----）并在关键节点打 log.info/log.error，且所有日志带 [业务] 前缀，便于根据运行日志排查测试
- 遵循上述规范，变量命名清晰"""

    return f"""请根据以下业务需求生成一个纷享销客 APL 函数。

## 业务需求
{requirement}

## 函数元信息
- 函数类型：{function_type}
- 绑定对象 API 名：{object_api}
- 绑定对象中文名：{object_label}
{fields_section}
## 参考示例（仅作风格参考，不要照搬字段名）{shots}

## 输出要求
{output_requirements}
"""
