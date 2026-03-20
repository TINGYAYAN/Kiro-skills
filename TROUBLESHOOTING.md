# 已知问题与解决方案

> 按问题类型分类，遇到新问题时追加到对应章节末尾。

---

## 〇、流水线整体不工作（优先排查）

### 现象：生成步骤无反应 / 报错 model_not_found / 超时

**根因**：LLM 配置的模型不可用（代理无此模型、网络不通等）。

**解决**：
1. 检查 `config.local.yml` 的 `llm` 配置，当前可用配置示例：
   ```yaml
   llm:
     provider: openai
     base_url: http://1.95.142.151:3000/v1
     api_key: sk-xxx
     model: claude-sonnet-4-5-20250929
     timeout: 120
   ```
2. 若代理不可达，改用 `provider: manual`：会生成 prompt 文件，你复制到 claude.ai 生成代码后粘贴到 `manual_code.txt`。
3. 若有 Anthropic 直连 Key，可改用 `provider: anthropic` + `model: claude-3-5-sonnet-20241022`。

### 现象：批量生成提示「没有待执行的记录」

**根因**：多维表格中无满足条件的行（描述已填、函数名为空、状态为待执行）。

**解决**：新增一行，填「描述」和「绑定对象」，**函数名留空**，再发「批量生成」。

### 现象：字段缓存不完整或生成代码未使用抓取的字段

**根因**：抓取时表格未完全滚动、describe API 未命中，或 LLM 未严格按字段列表生成。

**解决**：
1. **强制刷新缓存**：`python -m fetcher.fetch_fields --object-api DeliveryOrderObj --object-label 提货单 --project 硅基流动 --force`
2. **手动补充缺失字段**：在 `.fields_cache/项目/` 下新建 `对象API_supplement.yml`，例如：
   ```yaml
   add_fields:
     - api: life_status
       label: 生命状态
   ```
3. 生成器已强化「必须使用字段列表中的 API 名」，若需求中的字段在列表中不存在会加 `// 待确认` 注释。

### 现象：req.yml 不完整导致输出路径奇怪

**根因**：缺少 `code_name`、`output_dir`、`output_file` 时，会用需求首句前 30 字作文件名。

**解决**：在 req.yml 中补全，例如：
```yaml
code_name: 【工作流】租户关联客户
output_dir: 万泰
output_file: 【工作流】租户关联客户
```

---

## 一、浏览器自动化（Playwright）

### 1. `Page.wait_for_selector: Timeout exceeded` —— 等待"保存草稿"超时

**现象**
```
Page.wait_for_selector: Timeout 20000ms exceeded.
waiting for locator(':text-is("保存草稿")')
```
或「代码编辑器超时 - 页面加载太慢，保存按钮一直没出现」。

**根因**
点击"下一步"后，平台弹出"选择模板"对话框，模板弹窗加载较慢时未能点击"使用空模板"，或编辑器加载慢导致「保存草稿」迟迟不出现。

**解决**
已调整：等待「使用空模板」20 秒（含重试）；等待「保存草稿」40 秒（新建）或 35 秒（编辑）。若仍超时，可检查网络或纷享平台稳定性。

---

### 2. 按钮点击无效 —— Shadow DOM 封装

**现象**
`document.querySelectorAll('button, .el-button')` 返回空数组，
或 `locator.is_visible()` 返回 False，但截图上按钮明显可见。

**根因**
纷享销客按钮渲染在 Shadow DOM 内，标准 JS DOM 查询无法穿透；
Playwright 的 `locator.is_visible()` 在某些情况下也无法处理 Shadow DOM。

**解决**
改用 Playwright 文本选择器 `:text-is("按钮文字")`，再用 `bounding_box()` 获取坐标，
最后用 `page.mouse.click(x, y)` 坐标点击。这套方案能穿透 Shadow DOM：
```python
btn = frame.locator(':text-is("保存")').last
bbox = btn.bounding_box(timeout=5000)
if bbox:
    page.mouse.click(bbox['x'] + bbox['width']/2, bbox['y'] + bbox['height']/2)
```

---

### 3. 备注弹窗无法填写 —— 代码编辑器隐藏 textarea 排在最前

**现象**
```
[调试] 未能填写备注，直接点确定
[警告] 必填属性不可为空
```
备注字段为空，"确定"无效，弹窗不关闭。

**根因**
`frame.locator('textarea').first` 拿到的是代码编辑器的**无尺寸隐藏 textarea**
（ACE/CodeMirror/Monaco 会放一个 accessibility textarea），其 `bounding_box()` 返回 None。

**解决**
迭代所有 textarea，找 `bounding_box.height > 20` 的那个：
```python
for idx in range(min(count, 10)):
    ta = frame.locator('textarea').nth(idx)
    bbox = ta.bounding_box(timeout=500)
    if bbox and bbox['height'] > 20:
        page.mouse.click(cx, cy)
        page.keyboard.type(remark)
        break
```

---

### 4. 搜索框误触左侧导航栏

**现象**
进入函数管理页后，函数名被输入到左侧**导航栏搜索框**而非右侧函数列表搜索框。

**根因**
选择器 `input[placeholder*="搜索"]` 匹配了左侧 placeholder="搜索" 的导航搜索框，
DOM 顺序排在函数列表 "搜索代码名称" 之前，优先命中。

**解决**
`selectors.py` 中收窄选择器：
```python
FUNC_SEARCH_INPUT = 'input[placeholder*="搜索代码名称"]'
```

---

### 5. 更新函数时"找不到编辑入口"——编辑按钮需要 hover 才显示

**现象**
```
[部署器] 更新失败：找不到函数「xxx」的编辑入口
```
日志显示函数"存在"，但 `update_function` 报找不到编辑入口，随即回退新建。

**根因**
纷享销客函数列表的「编辑」按钮是 hover 行后才出现的。
代码直接 `edit.is_visible()` 而没有先 hover，自然拿不到可见元素。

**解决**
先用 `row.bounding_box()` + `page.mouse.move()` hover 到行中心，等 0.5s 触发按钮显示，
再用 `edit.bounding_box()` + `page.mouse.click()` 坐标点击（穿透 Shadow DOM）。
降级方案：`edit.click(force=True)`。

**附：函数 API 名兜底**
同时保存系统生成的函数 API 名（如 `Proc_BXYcW__c`）到 `.meta.yml`，后续按 API 名搜索更可靠。
`update_function` 仍失败时自动回退到 `create_function`（重新导航后新建）。

---

### 6. "请选择模板或使用空模板进行创建" 提示反复出现

**现象**
新建函数点"下一步"后，编辑器虽然打开了，但页面顶部总是出现红色 toast：
> 请选择模板或使用空模板进行创建

**根因**
`empty_tmpl.click()` 未能穿透 Shadow DOM，按钮被"找到"但点击事件未实际触发，
平台判断用户未选择模板，因此弹出该 toast。

**解决**
与其他 Shadow DOM 按钮相同，改用 `bounding_box()` + `page.mouse.click()` 坐标点击：
```python
bbox = empty_tmpl.bounding_box(timeout=5000)
if bbox:
    page.mouse.click(bbox['x'] + bbox['width']/2, bbox['y'] + bbox['height']/2)
else:
    empty_tmpl.click(force=True)
```

---

### 6.1 运行脚本「执行两次」/ 多次

**现象**
保存草稿后，看到「运行脚本」被点击了两次或多次，或日志显示对多个数据源依次执行。

**根因**
1. **编译修复流程**：第一次 run 检测到编译错误 → LLM 修复代码 → 再次 run 验证。这是预期行为。
2. **业务校验**：编译通过后，会对前 3 个数据源依次 run，分析业务日志是否满足需求。若第一个数据源 run 后判定为数据问题，会尝试下一个数据源。

**说明**
以上均为正常流程，非重复执行。若需减少等待，可后续通过配置限制业务校验只跑第一个数据源。

---

### 6.2 两次运行都失败（编译错误 / 业务未完成）

**现象**
第一次 run 失败 → LLM 修复 → 第二次 run 仍失败；或对多个数据源 run 都显示业务未完成。

**可能根因与排查**

| 根因 | 表现 | 排查与解决 |
|------|------|------------|
| **执行结果未就绪** | 点击运行后 3 秒就读结果，平台执行慢时读到空/旧日志 | 看截图 `run_fix0.png` 等，若日志区为空或仍是上一次内容，说明等待不足。可把 `_do_one_run` 里 `time.sleep(3)` 改为 5–8 秒 |
| **无数据源** | 新建函数时可能无数据源，不选直接 run 会失败或超时 | 日志有「数据源下拉无选项」→ 平台可能要求必选数据源。需在纷享销客中为该函数配置至少一个数据源 |
| **LLM 修复无效** | 第一次编译错误，LLM 返回的代码仍有同类问题 | 看 `reports/fix_xxx.md` 里的 diff，确认修复是否合理。可检查 `config.local.yml` 的 LLM 配置、或手动改代码后重试 |
| **LLM 未返回** | 日志有「LLM 未返回修复结果，终止修复」 | LLM 调用失败（网络、模型不可用、超时）。检查 `config.local.yml` 的 `llm` 配置 |
| **业务数据问题** | 编译通过，但业务日志显示「入参为空」「查不到数据」 | 判定为数据问题时不改代码。需选有真实数据的数据源，或调整需求/数据源配置 |

**建议**
1. 用 `PWDEBUG=1` 运行，观察每次 run 后页面实际显示内容
2. 查看 `deployer/screenshots/` 下 `run_fix0.png`、`run_fix1.png` 等，确认错误弹窗/日志内容
3. 若为执行慢，可临时把 `deploy.py` 中 `_do_one_run` 的 `time.sleep(3)` 改为 `time.sleep(6)`

---

### 7. 登录页选择器失效 —— 未找到登录输入框 / 输入框被锁定 (readonly)

**现象**
```
未找到登录输入框，已截图保存...
Page.wait_for_selector: Timeout exceeded
```
或「登录页 UI 问题 - 输入框被锁定 (readonly)，无法填入账号」。

**根因**
1. 纷享销客登录页 UI 升级，placeholder、tab 文案、DOM 结构变化，原有选择器失效。
2. 页面加载时输入框短暂处于 readonly 状态，Playwright 的 fill 无法填入。
3. 若先出现「服务器连接超时」，则可能是 `base_url` 或网络问题，需先确保浏览器能打开登录页。

**解决**
- 已自动处理：登录前会移除输入框的 readonly/disabled 属性，并增加等待时间。
- 若仍失败，可尝试：清除 session 后重试（删除 `deployer/session_*.json`），或手动登录后手动部署。

**解决步骤**

1. **确认登录页能打开**：检查 `config.local.yml` 的 `fxiaoke.base_url`、`login_path`。
   - 若连接超时，尝试更换 `login_path`：`/XV/UI/login` 或 `/XV/User/Login` 或 `/pc-login/build/login_gray.html`（视租户而定）

2. **用 Playwright Inspector 获取新选择器**：
   ```bash
   cd /Users/yanye/code/test拨号/_tools
   PWDEBUG=1 python3 deployer/deploy.py --file 某函数.apl --func-name "某函数名"
   ```
   浏览器会打开并停在登录页，同时启动 Inspector。在 Inspector 中：
   - 点击「账号」输入框 → 复制其选择器（如 `input[placeholder="请输入手机号"]`）
   - 将新选择器追加到 `deployer/selectors.py` 的 `LOGIN_USERNAME_ALT` 列表

3. **手动部署**：若短期内无法更新选择器，可手动完成部署：
   - 登录纷享销客 → 进入 APL 函数管理 → 新建函数 → 粘贴生成的 `.apl` 代码 → 保存

---

### 7.1 登录成功但无法进入函数列表 / 新建函数页面

**现象**
登录成功，但一直停在某页，未出现「新建APL函数」；或提示「导航到函数列表失败」。

**根因**
1. `function_path` 与当前租户不匹配（不同租户/环境路径可能不同）
2. 函数列表在 iframe 内，主页面选择器找不到
3. SPA 渲染慢，等待超时

**解决**
1. **确认 function_path**：手动登录纷享销客，进入「函数管理」或「APL 函数」，复制地址栏路径（如 `/XV/UI/manage#crmmanage/=/module-myfunction`），填入 `config.local.yml`：
   ```yaml
   fxiaoke:
     function_path: "/XV/UI/manage#crmmanage/=/module-myfunction"  # 按实际路径修改
   ```
2. **清除 session 重试**：删除 `deployer/session_*.json` 后重新运行
3. **有头模式排查**：去掉 `--headless`，观察登录后跳转到哪一页
4. **手动部署**：若自动化仍失败，可手动完成：登录 → 函数管理 → 新建 → 粘贴生成的 `.apl` 代码

---

### 8. 数据源选择失败 —— 未找到数据源选择框 / 下拉无选项

**现象**
```
[部署器] 未找到数据源选择框，将不选数据源运行
[部署器] 数据源下拉无选项或加载超时
```

**根因**
纷享 APL 编辑器「运行脚本」旁的数据源下拉结构可能变化，或 el-select 类名/层级不同。

**解决**
1. 用 `PWDEBUG=1` 打开 Inspector，进入函数编辑页、点「运行脚本」旁的数据源下拉，查看其 DOM 结构。
2. 若找到数据源触发器（input 或 .el-input__inner）的选择器，追加到 `deployer/deploy.py` 的 `_get_datasource_input` 策略列表。
3. 若无数据源（对象无实例数据），会直接运行一次，属正常；要验证业务请手动选一条有数据的数据源再运行。

---

## 二、APL 代码生成质量

### 6. 废弃 API 导致保存失败

**现象**（扫描日志）
```
Fx.object.create接口已过期
Fx.object.update接口已过期
```

**根因**
LLM 生成了 2 参数 `create` 或 3 参数 `update`，平台已废弃这些签名。

**正确签名**
```groovy
// create：4 个参数，第 3 个是空 Map [:]
def (Boolean err, Map result, String msg) = Fx.object.create(
    "objectApi", ["field": value] as Map<String, Object>, [:],
    CreateAttribute.builder().triggerWorkflow(false).build()
)

// update：4 个参数，第 4 个是 UpdateAttribute
def (Boolean err, Map result, String msg) = Fx.object.update(
    "objectApi", id, ["field": value] as Map<String, Object>,
    UpdateAttribute.builder().triggerWorkflow(false).build()
)

// find：必须传 SelectAttribute 作为第 3 个参数
def (Boolean err, QueryResult r, String msg) = Fx.object.find(
    "objectApi",
    FQLAttribute.builder().columns(["_id"]).queryTemplate(...).build(),
    SelectAttribute.builder().build()
)
```

**已在 prompt.py 和 `_call_llm_fix` 的 system prompt 中加入强制规则。**

---

### 7. 未使用变量 warning 阻断保存

**现象**（扫描日志）
```
line21: The variable '[qMsg]' is not used
line54: The variable '[uResult]' is not used
```

**根因**
平台对三元组解构中声明但未引用的变量报 warning，且 warning 也会阻断"保存"操作。

**解决规则**
- find 的 msg 变量：必须写 `if (err) { log.error("..." + msg); return }`
- create 的 result Map：必须取 `String newId = result?["_id"] as String`
- update 的 result Map：加 `else { log.info("更新成功") }` 使变量隐式使用
- **禁止用 `_` 作为占位变量**（平台同样报 warning）

---

### 8. `FQLAttribute.limit()` 不存在

**现象**
```
[Static type checking] Cannot find matching method FQLAttribute#limit(int)
```

**根因**
LLM 误用了 `.limit(n)` 方法，该方法不在 `FQLAttribute` 上。

**解决**
分页通过 `SelectAttribute` 处理，`FQLAttribute` 只负责查询条件和列名：
```groovy
SelectAttribute.builder().pageSize(50).pageNum(1).build()
```

---

## 三、Python 环境兼容性

### 9. `list | None` 类型注解在 Python 3.9 报错

**现象**
```
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

**根因**
`X | Y` 联合类型语法需要 Python 3.10+，当前 macOS 默认安装的是 3.9。

**解决**
在文件顶部加：
```python
from __future__ import annotations
```
这让 3.9 也支持 `list | None` 风格的类型注解。

---

## 四、字段 API 名抓取

### 10. fetch 步骤命名空间未找到导致编辑器不加载

**现象**
```
命名空间 → 公共库: not_found. options=按钮|流程|...
Page.wait_for_selector: Timeout 30000ms exceeded.
```

**根因**
`fetch_fields` 用了硬编码的 "公共库" 作为命名空间，而该系统没有"公共库"，
导致命名空间未选中，表单无法提交"下一步"，编辑器永远不加载。

**解决**
从 `req.yml` 的 `namespace` 字段读取（与部署用同一个值），
若还是找不到则自动选下拉里的第一个可用项。

### 10.1 自定义控制器等命名空间未匹配

**现象**
```
命名空间 → 自定义控制器: not_found. options=按钮|流程|...
```

**根因**
纷享命名空间下拉有分组（如 平台>流程/计划任务/自定义控制器），
过滤或滚动未正确展示「自定义控制器」选项。

**解决**
1. 在 `req.yml` 中显式填写 `function_type: 自定义控制器` 和 `namespace: 自定义控制器`
2. 部署器已支持根据 `function_type` 自动推断 `namespace`，无需重复填写
3. 若仍失败，部署器会清除过滤并滚动下拉重试

---

## 五、DOM 解析

### 11. 字段抓取噪音（标签拼接、重复 `_id`）

**现象**（`.fields_cache/tenant__c.yml` 内容）
```yaml
- api: tenant__c
  label: CRM对象API集成对象API   # 两个 span 拼在一起
- api: _id
  label: 字符串(String)          # 字段类型描述被当成 label
- api: _id
  label: 单行文本                # 重复
```

**根因**
"字段API对照表"面板里每行有多列（字段名、API Name、字段类型、数据类型），
JS 策略 3（全页文本逐行解析）把相邻列的文字拼在了一起，且把类型列也解析成了字段。

**解决方向（待实现）**
优先用策略1（`<tr>/<td>` 表格解析），精确取第 1 列（字段名）和第 2 列（API Name），
跳过第 3、4 列（字段类型、数据类型），可用列 index 或 `th` header 匹配来定位列。

---

## 六、测试与调试

### 12. 无报错不等于业务成功 —— 结合日志分析

**现象**
部署后运行脚本没有编译/运行报错，但业务上数据没关联上、或流程未按预期执行。

**根因**
「运行脚本」只要不抛错就会显示执行完成；若代码里因入参为空、查不到数据等走了 `return` 或 `log.error` 分支，逻辑并未走到真正的「完成」步骤。

**正确调试方式**
1. **看运行日志里的 [业务] 行**：生成的代码已要求带 `[业务]` 前缀的 log，部署后运行在「运行日志」里过滤 `[业务]`：
   - 看到 `[业务] 入参: ...` → 确认当前数据源是否带齐所需字段（如组织机构代码、租户ID）。
   - 看到 `[业务] 终止: xxx为空` → 要么换有数据的数据源，要么检查绑定对象/字段是否与预期一致。
   - 看到 `[业务] 完成: ...` 或 `[业务] 已关联...` → 才表示逻辑走到了成功分支。
2. **部署器已做业务日志分析**：运行结束后会打印 `[部署器] 业务日志分析: xxx`；若为「业务未走到完成分支」，请根据入参与步骤日志检查数据源或逻辑，不要仅以无报错视为成功。
3. **无数据源时**：入参多为空，出现「终止: 组织机构代码为空」等属正常；要验证业务请选择一条有完整数据的数据源再运行，并依据 [业务] 日志判断是否真正完成。
