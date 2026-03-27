"""
APL 代码生成器

用法：
  python generate.py --req req.yml
  python generate.py --requirement "需求描述" --object-api xxx__c --object-label "对象名" --type 流程函数

req.yml 格式：
  requirement: "业务需求描述"
  object_api: "object_api_name__c"
  object_label: "绑定对象中文名"
  function_type: "流程函数"   # 流程函数|UI函数|按钮|范围规则|自定义控制器|计划任务|同步前/后函数|校验函数|自增编号|导入等，支持英文：flow/range_rule/button/ui/controller
  code_name: "函数代码名称"    # 可选，默认从需求首句提取
  description: "函数描述"      # 可选，默认等于 requirement
  author: "作者名"              # 可选，使用 config.yml 中的 default_author
  output_dir: "客户目录名"      # 可选，相对于项目根目录
  output_file: "文件名"         # 可选，不含扩展名
"""
import argparse
import os
import sys
from datetime import date
from pathlib import Path

import yaml
from jinja2 import Template

sys.path.insert(0, str(Path(__file__).parent.parent))
from generator.prompt import build_system_prompt, build_user_prompt, load_examples
from utils import load_config

HEADER_TEMPLATE = Path(__file__).parent.parent / "templates" / "header.j2"
PROJECT_ROOT = Path(__file__).parent.parent.parent  # test拨号/


def render_header(author: str, code_name: str, description: str,
                  object_label: str, object_api: str) -> str:
    # 多行描述每行加注释前缀，保持 /** */ 格式正确
    desc_lines = description.strip().splitlines()
    formatted_desc = ("\n * ".join(desc_lines))
    tmpl = Template(HEADER_TEMPLATE.read_text(encoding="utf-8"))
    return tmpl.render(
        author=author,
        code_name=code_name,
        description=formatted_desc,
        object_label=object_label,
        object_api=object_api,
        today=date.today().strftime("%Y-%m-%d"),
    )


def call_llm(system: str, user: str, cfg: dict) -> str:
    provider = cfg["llm"]["provider"]

    # ---- 手动模式：写文件交互，避免终端粘贴混乱 ----
    if provider == "manual":
        tools_dir = Path(__file__).parent.parent
        prompt_file = tools_dir / "manual_prompt.txt"
        code_file = tools_dir / "manual_code.txt"

        # 写 prompt 文件
        prompt_content = f"=== System Prompt ===\n\n{system}\n\n=== User Prompt ===\n\n{user}"
        prompt_file.write_text(prompt_content, encoding="utf-8")

        # 清空或创建 code 文件，让用户填入
        code_file.write_text("", encoding="utf-8")

        sep = "=" * 60
        print("\n" + sep)
        print("【手动模式】操作步骤：")
        print(f"\n  1. 用编辑器打开以下文件，复制全部内容：")
        print(f"     {prompt_file}")
        print(f"\n  2. 粘贴到 claude.ai 或 chatgpt.com 发送")
        print(f"\n  3. 将 AI 回复的【纯代码】（不含说明文字）粘贴到以下文件并保存：")
        print(f"     {code_file}")
        print(f"\n  4. 回到本终端，按回车继续")
        print(sep)
        input("\n  → 代码已保存到文件后，按回车继续...")

        code = code_file.read_text(encoding="utf-8").strip()
        if not code:
            raise ValueError(f"manual_code.txt 为空，请将 AI 生成的代码写入该文件后重试")
        return code

    api_key = cfg["llm"].get("api_key") or os.environ.get(
        "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY", ""
    )
    model = cfg["llm"]["model"]
    temperature = float(cfg["llm"].get("temperature", 0.1))
    max_tokens = int(cfg["llm"].get("max_tokens", 4096))

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text.strip()

    elif provider == "openai":
        from openai import OpenAI, NotFoundError
        base_url = cfg["llm"].get("base_url") or None
        timeout = float(cfg["llm"].get("timeout", 120))
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        # 使用流式输出，避免代理合并换行符
        try:
            stream = client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except NotFoundError as e:
            endpoint = (base_url or "https://api.openai.com/v1").rstrip("/")
            raise RuntimeError(
                f"LLM 接口返回 404：base_url={endpoint} model={model}。"
                "通常是代理地址失效、路径不兼容，或该代理不支持当前模型。"
                "请检查 llm.base_url / llm.model，或切换到已验证可用的代理。"
            ) from e
        chunks = []
        for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta.content or ""
                chunks.append(delta)
        content = "".join(chunks)
        return content.strip()

    else:
        raise ValueError(f"不支持的 LLM provider: {provider}（可选: anthropic | openai | manual）")


def generate(
    req: dict,
    cfg: dict,
    fields_map: dict = None,
    req_file_path = None,
) -> Path:
    requirement = req["requirement"]
    object_api = req["object_api"]
    object_label = req["object_label"]
    from utils import (
        FUNCTION_TYPE_ALIASES,
        infer_function_type_into_req_if_missing,
        sync_function_type_from_trigger_type,
    )

    sync_function_type_from_trigger_type(req)
    infer_function_type_into_req_if_missing(req)
    function_type = req.get("function_type", "流程函数")
    ft_key = str(function_type).strip().lower()
    function_type = FUNCTION_TYPE_ALIASES.get(ft_key, function_type)
    req["function_type"] = function_type
    if function_type == "计划任务":
        ns0 = (req.get("namespace") or "").strip()
        if ns0 in ("流程", "工作流"):
            req["namespace"] = "计划任务"
    # 仅当用户未显式指定流程时，才根据需求文本推断范围规则（避免覆盖用户明确的流程函数）
    req_text = (requirement or "") if isinstance(requirement, str) else str(requirement or "")
    if "范围规则" in req_text and function_type not in ("流程函数", "流程", "flow"):
        function_type = "范围规则"
        req["function_type"] = "范围规则"
        req["namespace"] = "范围规则"
    author = req.get("author") or cfg["generator"].get("default_author", "纷享实施人员")
    # 代码名称格式：【命名空间】+ 简短概括，如【流程】租户关联客户。若 req 未提供则推断
    code_name = req.get("code_name")
    if not code_name:
        from utils import resolve_namespace, NAMESPACE_TO_CODE_PREFIX, infer_short_code_summary
        namespace = resolve_namespace(req)
        prefix = NAMESPACE_TO_CODE_PREFIX.get(namespace, f"【{namespace}】")
        summary = infer_short_code_summary(requirement, req.get("object_label", ""))
        code_name = f"{prefix}{summary}"
    elif code_name.startswith("【工作流】"):
        # 兼容旧格式，【工作流】→【流程】
        code_name = "【流程】" + code_name[5:]
    # 各函数类型必须有正确前缀，修正错误前缀
    from utils import FUNCTION_TYPE_TO_NAMESPACE, NAMESPACE_TO_CODE_PREFIX
    ns = FUNCTION_TYPE_TO_NAMESPACE.get(function_type, "流程")
    expect_prefix = NAMESPACE_TO_CODE_PREFIX.get(ns, f"【{ns}】")
    if not code_name.startswith(expect_prefix):
        for wrong in ("【流程】", "【按钮】", "【自定义控制器】", "【范围规则】", "【UI事件】", "【计划任务】"):
            if wrong != expect_prefix and code_name.startswith(wrong):
                code_name = expect_prefix + code_name[len(wrong):]
                break
        else:
            if not code_name.startswith("【"):
                code_name = expect_prefix + code_name
    description = req.get("description") or requirement
    output_dir = req.get("output_dir") or cfg["generator"].get("output_dir", ".")
    output_file = req.get("output_file") or code_name

    from fetcher.fetch_fields import _project_from_cfg
    from generator.prompt import infer_project_name_from_req_path

    proj = (req.get("project") or req.get("project_name") or "").strip() or None
    if not proj:
        proj = _project_from_cfg(cfg)
    if not proj and req_file_path:
        proj = infer_project_name_from_req_path(req_file_path)

    num_examples = int(cfg["generator"].get("num_examples", 8))
    rag_enabled = (cfg.get("rag") or {}).get("enabled", False)
    if rag_enabled:
        try:
            from rag.apl_examples import retrieve_apl_examples
            examples = retrieve_apl_examples(
                requirement,
                function_type,
                cfg,
                num=num_examples,
                project_name=proj,
                req_path=req_file_path,
            )
        except Exception as e:
            print(f"[生成器] RAG 检索失败，回退到规则检索: {e}")
            examples = load_examples(
                function_type,
                num_examples,
                requirement=requirement,
                project_name=proj,
                req_path=req_file_path,
            )
    else:
        examples = load_examples(
            function_type,
            num_examples,
            requirement=requirement,
            project_name=proj,
            req_path=req_file_path,
        )

    # 构建字段上下文（若有缓存字段信息）
    fields_context = ""
    if fields_map:
        try:
            from fetcher.fetch_fields import build_fields_context
            max_fields = int((cfg.get("generator") or {}).get("max_fields_in_prompt", 72))
            fields_context = build_fields_context(
                fields_map, req, max_fields_per_object=max_fields
            )
            if fields_context:
                total = sum(len(v) for v in fields_map.values())
                print(f"[生成器] 已加载字段上下文：{len(fields_map)} 个对象，{total} 个字段")
        except Exception as e:
            print(f"[生成器] 字段上下文构建失败（跳过）: {e}")

    print(f"[生成器] 函数类型: {function_type}，绑定对象: {object_api}")
    from collections import Counter

    tier_counts = Counter(ex.get("tier_label", "?") for ex in examples)
    print(f"[生成器] 加载 {len(examples)} 个参考函数，分层: {dict(tier_counts)}")

    system_prompt = build_system_prompt(function_type)
    # 注入历史修复记忆，让生成阶段也能避免已知错误
    try:
        from deployer.memory_store import _load_memory
        mem_data = _load_memory()
        entries = [e for e in mem_data.get("entries", []) if e.get("fix_snippet")]
        if entries:
            lines = ["\n## 历史高频错误（生成时务必避免）\n"]
            for e in sorted(entries, key=lambda x: x.get("count", 1), reverse=True)[:5]:
                lines.append(f"- [{e['type']}] {e.get('fix_rule', '')} (出现{e.get('count',1)}次)")
                if e.get("fix_snippet"):
                    lines.append(f"  正确写法示例：{e['fix_snippet'][:150]}")
            system_prompt = system_prompt.rstrip() + "\n" + "\n".join(lines)
    except Exception:
        pass
    user_prompt = build_user_prompt(requirement, object_api, object_label, function_type,
                                    examples, fields_context=fields_context)

    print(f"[生成器] 调用 {cfg['llm']['provider']} ({cfg['llm']['model']})...")
    code_body = call_llm(system_prompt, user_prompt, cfg)

    # 去除 LLM 可能多余输出的 markdown 代码块标记
    code_body = (code_body or "").strip()
    if code_body.startswith("```"):
        lines = code_body.splitlines()
        inner = lines[1:-1] if (lines and lines[-1].strip() == "```") else lines[1:]
        code_body = "\n".join(inner).strip()
    elif "```" in code_body:
        # LLM 在代码前加了解释文字，提取最后一个 ```...``` 块里的代码
        import re as _re
        blocks = _re.findall(r"```(?:groovy|apl)?\n(.*?)```", code_body, _re.DOTALL)
        if blocks:
            code_body = blocks[-1].strip()

    if not code_body:
        raise ValueError(
            f"LLM 返回空代码。当前模型: {cfg['llm']['model']}\n"
            "可能原因：① 模型开启了 thinking 模式导致 content 为空 "
            "② API Key 无效 ③ 模型名称不正确\n"
            "建议：将 config.local.yml 中的 model 改为 claude-3-5-sonnet-20241022"
        )

    header = render_header(author, code_name, description, object_label, object_api)
    full_code = header + "\n" + code_body

    # 统一加 .apl 后缀，便于 IDE 识别
    base = (output_file if output_file.endswith(".apl") else f"{output_file}.apl")
    out_path = PROJECT_ROOT / output_dir / base
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_code, encoding="utf-8")

    print(f"[生成器] 已输出: {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="APL 代码生成器")
    parser.add_argument("--req", help="需求 YAML 文件路径")
    parser.add_argument("--requirement", help="业务需求描述（直接传入）")
    parser.add_argument("--object-api", dest="object_api", help="绑定对象 API 名")
    parser.add_argument("--object-label", dest="object_label", help="绑定对象中文名")
    parser.add_argument("--type", dest="function_type", default="流程函数",
                        help="函数类型: 流程函数|UI函数|同步前函数|同步后函数")
    parser.add_argument("--author", help="作者名")
    parser.add_argument("--code-name", dest="code_name", help="函数代码名称")
    parser.add_argument("--output-dir", dest="output_dir", help="输出目录（相对于项目根）")
    parser.add_argument("--output-file", dest="output_file", help="输出文件名（不含扩展名）")
    parser.add_argument("--config", default=None, help="config 文件路径")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.req:
        req = yaml.safe_load(Path(args.req).read_text(encoding="utf-8"))
    else:
        if not args.requirement or not args.object_api or not args.object_label:
            parser.error("需提供 --req 文件，或同时提供 --requirement、--object-api、--object-label")
        req = {
            "requirement": args.requirement,
            "object_api": args.object_api,
            "object_label": args.object_label,
            "function_type": args.function_type,
        }
        if args.author:
            req["author"] = args.author
        if args.code_name:
            req["code_name"] = args.code_name
        if args.output_dir:
            req["output_dir"] = args.output_dir
        if args.output_file:
            req["output_file"] = args.output_file

    out_path = generate(
        req,
        cfg,
        fields_map=None,
        req_file_path=args.req if args.req else None,
    )
    print(f"[生成器] 完成 → {out_path}")
    return str(out_path)


if __name__ == "__main__":
    main()
