# 流程与代码优化建议

> 基于整体流程和代码审查整理的改进点，按优先级排序。

---

## 一、Bug 修复

### 1. batch_runner 中 `_run_pipeline` 使用 subprocess 但未导入

`_run_pipeline` 调用了 `subprocess.run`，但文件顶部没有 `import subprocess`。

**现状**：`_run_pipeline` 为死代码（当前批量流程用 `run_batch_inprocess` 直接调用 generate + deploy），但若将来复用会报错。

**建议**：删除 `_run_pipeline`，或补充 `import subprocess` 以备后用。

---

### 2. 生成器输出文件无 .apl 后缀

`generate()` 写入路径为 `output_dir / output_file`，未加 `.apl`，例如 `【流程】租户关联客户`。

**影响**：编辑器、IDE 无法按 APL 语法高亮，部分工具可能无法识别。

**建议**：输出时统一加 `.apl` 后缀，例如 `out_path = ... / f"{output_file}.apl"`。

---

## 二、流程优化

### 3. ~~pipeline --step deploy/all 时生成阶段无字段上下文~~ ✅ 已实现

deploy/all 时预拉取字段，一次生成即可。

### 4. ~~批量模式下字段抓取与部署使用两套浏览器~~ ✅ 已实现

`fetch_fields_for_req` 支持 `page` 参数，批量模式传入当前 page 复用同一浏览器。

---

### 5. feishu_batch.sh 路径写死

```bash
TOOLS_DIR="/Users/yanye/code/test拨号/_tools"
```

**建议**：改为基于脚本位置解析，例如：
```bash
TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
```

---

## 三、代码质量

### 6. 配置校验缺失

启动时未校验 `fxiaoke.username`、`llm.api_key` 等必填项，错误往往在后续步骤才暴露。

**建议**：在 `load_config` 或 pipeline 入口做基础校验，缺失时给出明确提示。

---

### 7. 重复的 req 加载

`pipeline.main()` 中 `req` 被加载一次，`step_generate` 和 `step_deploy` 内部可能再次读取 `args.req`。

**建议**：统一由 main 加载 req，以参数形式传入各 step，避免重复 IO 和解析。

---

### 8. ~~deployer 体积过大~~ ✅ 部分完成

- 已拆分 `deploy_login.py`：登录、Session 管理、导航
- Session 按项目分文件：`session_硅基流动.json`，文件内带 `_project`、`_comment` 标注所属项目
- `deploy_editor.py`：编辑器操作与错误修复

---

## 四、功能增强（OVERVIEW 已描述但实现不完整）

### 9. ~~运行后分析日志并自动修复~~ ✅ 已实现（含自愈式测试）

- **有报错**：编译错误 → **规则修复**（?["key"]、反引号、for 循环等）→ 若无则 **LLM 修复** → 重跑验证 → 重复直到通过
- **无报错**：选数据源运行，分析业务日志
  - **不符合业务需求** 且 **逻辑问题** → LLM 修复 → 重试（最多 3 次）
  - **数据问题**（入参为空、查不到数据等）→ 不改代码，仅提示

---

### 10. 报错分类与记忆闭环 ✅

OVERVIEW 提到：「记录报错并分类，并优化提示词」。

**已实现**（`deployer/memory_store.py` + `deploy.py` 集成）：

- **分类**：`classify_error()` 按关键词将错误归类（未使用变量、Elvis 运算符、API 签名、安全下标、FQL 分页等）
- **记忆**：编译通过后，将成功修复链写入 `deployer/memory/fix_memory.json`，含 error_snippet、fix_snippet、count
- **检索**：`query_similar_fixes()` 按类型 + 片段相似度检索历史，`build_memory_prompt_context()` 生成注入 prompt 的上下文
- **闭环**：`_call_llm_fix` 在调用 LLM 前注入「历史类似修复」，修复成功后写入 memory，下次同类错误可直接参考
- **自愈式**：每次修复后自动重跑验证；同错误多次时提示 LLM 换策略；提取报错行号注入上下文

---

## 五、可快速落地的改动

| 优先级 | 改动 | 工作量 |
|--------|------|--------|
| 高 | 生成器输出加 .apl 后缀 | 小 |
| 高 | feishu_batch.sh 路径改为脚本相对路径 | 小 |
| 中 | 删除或修复 batch_runner 中 _run_pipeline | 小 |
| 中 | pipeline deploy/all 时预拉取字段 | 中 |
| 低 | deployer 模块拆分 | 大 |
