# -*- coding: utf-8 -*-
"""Wave-21 Step7 strings merged into locales/*/common.json."""

from __future__ import annotations

import json
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data"


def _catalog_json_object_literal(dumped: str) -> str:
    """Double only the outermost ``{``/``}`` so ``str.format`` on catalog entries leaves valid JSON."""
    s = dumped.strip()
    if len(s) >= 2 and s[0] == "{" and s[-1] == "}":
        return "{{" + s[1:-1] + "}}"
    return s


def _tail(locale: str) -> str:
    name = "cprm_tail_zh.txt" if locale == "zh-Hans" else "cprm_tail_en.txt"
    return (_DATA / name).read_text(encoding="utf-8")


def build_wave21_blobs() -> tuple[dict[str, str], dict[str, str]]:
    en: dict[str, str] = {}
    zh: dict[str, str] = {}

    en["cprm.tail.static_manual"] = _tail("en")
    zh["cprm.tail.static_manual"] = _tail("zh-Hans")

    # --- consolidation (hcon) ---
    _hcon_zh = {
        "hcon.console.passive_trigger": "[dim blue]💤 [REM Sleep] 被动触发：code_ops 积累超阈值，开始记忆压缩...[/dim blue]",
        "hcon.console.chat_pref": "[dim blue]💤 [REM Sleep] 聊天偏好观察触发（已积累5条聊天）...[/dim blue]",
        "hcon.console.delta": "\n[dim blue]💤 [REM Sleep] 脑电波进入 Delta 频段，潜意识开始进行记忆压缩与高维抽象...[/dim blue]",
        "hcon.console.no_response": "[yellow]⚠️ REM Sleep 未获得回应[/yellow]",
        "hcon.console.insights_ok": "[bold purple]🌌 [REM Sleep] 潜意识成功提取新高维智慧法则：[/bold purple]",
        "hcon.console.prune": "[dim blue]🧹 [REM Sleep] 突触修剪：已清理旧流水账...[/dim blue]",
        "hcon.console.prompt_shell": "[bold green]Erique@AdamI>[/bold green] ",
        "hcon.console.rem_error": "[red]⚠️ REM Sleep 异常，已安全回退[/red]",
        "hcon.console.pref_scan": "[dim blue]💤 [REM Sleep] 正在扫描日间对话，嗅探用户深层偏好与习惯...[/dim blue]",
        "hcon.prompt.dream": (
            "你现在是 AdamI 的潜意识梦境编织者。\n"
            "以下是最近的底层执行流水账（情景记忆）：\n"
            "{history_json}\n\n"
            "【任务】：从这些流水账中抽象出 1~3 条高维经验法则。\n"
            "示例：'斐波那契递归会导致栈溢出，未来必须优先使用迭代法'。\n"
            "只保留纯智慧法则，不要任何 Trace ID、时间、JSON。\n"
            "【输出契约】：先思考，然后输出 [ACTION: STORE_INSIGHT] 后面紧跟纯文本法则，每条一行。\n"
            "不要输出 JSON！不要加 ``` 块！"
        ),
        "hcon.prompt.preference": (
            "你是一个细心的行为观察家。\n"
            "分析以下最近的用户与 AI 交互记录：\n"
            "{history_json}\n\n"
            "【任务】：\n"
            "你是否观察到了用户有什么明显的沟通习惯、格式偏好、情绪雷区或隐含的指令？\n"
            "（例如：'用户不喜欢长段落，偏好分点列表'，'用户遇到代码报错时希望直接给完整代码而不是解释'）\n"
            "【输出格式】：严格 JSON。\n"
            "如果没有发现新偏好，返回空列表。\n"
            "{{\n"
            '  "candidates": ["观察到的偏好1", "观察到的偏好2"]\n'
            "}}"
        ),
        "hcon.console.pref_found": "[bold green]👀 [静默观察] 发现 {count} 条新偏好，已悄悄记入 candidates 候选池[/bold green]",
    }
    _hcon_en = {
        "hcon.console.passive_trigger": "[dim blue]💤 [REM Sleep] Passive trigger: code_ops threshold reached, compressing memory...[/dim blue]",
        "hcon.console.chat_pref": "[dim blue]💤 [REM Sleep] Chat preference scan (5 messages accumulated)...[/dim blue]",
        "hcon.console.delta": "\n[dim blue]💤 [REM Sleep] Delta-band consolidation and abstraction...[/dim blue]",
        "hcon.console.no_response": "[yellow]⚠️ REM Sleep: empty LLM response[/yellow]",
        "hcon.console.insights_ok": "[bold purple]🌌 [REM Sleep] distilled high-level rules:[/bold purple]",
        "hcon.console.prune": "[dim blue]🧹 [REM Sleep] pruned old code_ops...[/dim blue]",
        "hcon.console.prompt_shell": "[bold green]Erique@AdamI>[/bold green] ",
        "hcon.console.rem_error": "[red]⚠️ REM Sleep error; safe fallback[/red]",
        "hcon.console.pref_scan": "[dim blue]💤 [REM Sleep] scanning dialogue for preferences...[/dim blue]",
        "hcon.prompt.dream": (
            "You are AdamI's subconscious dream weaver.\n"
            "Recent low-level execution log (episodic):\n"
            "{history_json}\n\n"
            "Task: distill 1–3 high-level rules.\n"
            "Example: 'Fibonacci recursion risks stack overflow; prefer iteration.'\n"
            "Pure wisdom only—no trace IDs, timestamps, or raw JSON.\n"
            "Contract: think, then emit [ACTION: STORE_INSIGHT] followed by one rule per line.\n"
            "Do NOT output JSON or fenced code blocks."
        ),
        "hcon.prompt.preference": (
            "You are a careful behavioral observer.\n"
            "Recent user/AI interactions:\n"
            "{history_json}\n\n"
            "Task:\n"
            "Did you notice habits, format preferences, emotional triggers, or implicit instructions?\n"
            "(e.g. 'user dislikes long paragraphs', 'on errors user wants full code not prose')\n"
            "Output: strict JSON. If nothing new, return an empty list.\n"
            "{{\n"
            '  "candidates": ["preference observation 1", "preference observation 2"]\n'
            "}}"
        ),
        "hcon.console.pref_found": "[bold green]👀 [Silent observe] {count} preference(s) appended to candidates[/bold green]",
    }

    en.update(_hcon_en)
    zh.update(_hcon_zh)

    # --- skill factory (sfac) ---
    _map = {
        "那美克星人": "NAMEKIAN",
        "那美克星": "NAMEKIAN",
        "查询": "QUERY",
        "数量": "COUNT",
        "人数": "COUNT",
        "天气": "WEATHER",
        "价格": "PRICE",
        "加密货币": "CRYPTO",
        "比特币": "BTC",
        "以太坊": "ETH",
    }
    _map_json = _catalog_json_object_literal(json.dumps(_map, ensure_ascii=False))
    _stop = json.dumps(["一个", "的", "技能", "创建"], ensure_ascii=False)
    en["sfac.name.unknown_lit"] = "未知技能"
    zh["sfac.name.unknown_lit"] = "未知技能"
    en["sfac.name.map_json"] = _map_json
    zh["sfac.name.map_json"] = _map_json
    en["sfac.name.stopwords_json"] = _stop
    zh["sfac.name.stopwords_json"] = _stop

    # --- cortex prompt fragments (cprm) ---
    _cprm_zh = {
        "cprm.mem.empty": "无历史记忆。",
        "cprm.mem.header": "【历史反馈回顾】\n",
        "cprm.block.current_env": "【当前任务/环境反馈】\n{event_str}\n\n",
        "cprm.fmt.persona_head": "【核心人格】\n{persona_text}\n\n",
        "cprm.skill.force_banner": (
            "\n\n⚠️ 🔴 【最高系统警报】：你现在的唯一使命是写代码！你当前没有其他任何工具可以使用！"
            "不要去调用健康检查，不要调用任何无关 API！如果你准备好了，立即输出 action: CREATE_NEW_SKILL。"
            "如果思路不清，输出 action: THINK！\n"
        ),
        "cprm.strip.line_keywords_json": json.dumps(
            ["【🛠️ 已注册工具", "工具:", "Schema:", "动态技能", "本能"],
            ensure_ascii=False,
        ),
    }
    _cprm_en = {
        "cprm.mem.empty": "No prior memories.",
        "cprm.mem.header": "【Historical feedback】\n",
        "cprm.block.current_env": "【Current task / environment】\n{event_str}\n\n",
        "cprm.fmt.persona_head": "【Core persona】\n{persona_text}\n\n",
        "cprm.skill.force_banner": (
            "\n\n⚠️ 🔴 【SYSTEM ALERT】: Your only mission is to write code. No other tools are available. "
            "Do not run health checks or unrelated APIs. When ready, emit action: CREATE_NEW_SKILL. "
            "If unclear, emit action: THINK!\n"
        ),
        "cprm.strip.line_keywords_json": json.dumps(
            ["【🛠️ Registered tools", "Tools:", "Schema:", "Dynamic skill", "Instinct"],
            ensure_ascii=False,
        ),
    }
    en.update(_cprm_en)
    zh.update(_cprm_zh)

    # --- evolution (cevo) ---
    _cevo = {
        "cevo.last_used_unknown": "未知",
        "cevo.desc.missing": "无描述",
        "cevo.err.empty_code": "代码生成失败（原始代码为空）",
        "cevo.err.build_fmt": "技能构建失败: {detail}",
        "cevo.msg.hatch_ok": "🎉 技能 {skill_name} 孵化成功！",
        "cevo.err.market": "市场安装暂未迁移",
        "cevo.schema.param": "必须提取的参数: {name}",
        "cevo.schema.args": "技能参数",
        "cevo.tool.dynamic": "动态技能: {skill_name}",
        "cevo.persona.instincts": "【🧠 核心本能（永久固化）】：{names}",
        "cevo.persona.skills": "【🌱 动态技能（训练中）】：{names}",
        "cevo.log.move_missing_src": "固化失败：源文件 {src} 不存在",
    }
    _cevo_en = {
        "cevo.last_used_unknown": "unknown",
        "cevo.desc.missing": "(no description)",
        "cevo.err.empty_code": "Code generation failed (empty raw code)",
        "cevo.err.build_fmt": "Skill build failed: {detail}",
        "cevo.msg.hatch_ok": "🎉 Skill {skill_name} hatched successfully!",
        "cevo.err.market": "Market install not migrated yet",
        "cevo.schema.param": "Parameter to extract: {name}",
        "cevo.schema.args": "Skill arguments",
        "cevo.tool.dynamic": "Dynamic skill: {skill_name}",
        "cevo.persona.instincts": "【🧠 Core instincts (solidified)】: {names}",
        "cevo.persona.skills": "【🌱 Dynamic skills (training)】: {names}",
        "cevo.log.move_missing_src": "Solidify failed: source file {src} missing",
    }
    zh.update(_cevo)
    en.update(_cevo_en)

    # --- skill inspector (sins) ---
    _markers = json.dumps(
        [
            "网络请求异常",
            "ConnectionError",
            "Timeout",
            "requests.exceptions",
            "httpx.ConnectError",
        ],
        ensure_ascii=False,
    )
    _markers_en = json.dumps(
        [
            "Network request error",
            "网络请求异常",
            "ConnectionError",
            "Timeout",
            "requests.exceptions",
            "httpx.ConnectError",
        ],
        ensure_ascii=False,
    )
    en["sins.stderr.markers_json"] = _markers_en
    zh["sins.stderr.markers_json"] = _markers
    en["sins.mock.city"] = "Beijing"
    zh["sins.mock.city"] = "北京"
    en["sins.prompt.mock_args"] = (
        "You are a test engineer. Given the skill description and code, emit a JSON dict of "
        "reasonable test kwargs for a dry run.\n"
        "Description:\n{description}\n"
        "Code snippet:\n{code_snippet}\n"
        "Parameter names: {args_names}\n"
        "Return only a JSON object mapping names to values. No prose."
    )
    zh["sins.prompt.mock_args"] = (
        "你是一个测试工程师。请根据以下技能描述和代码，生成一组合理的测试参数（字典形式），用于模拟调用该技能。\n"
        "技能描述：{description}\n"
        "代码片段：\n{code_snippet}\n"
        "可用的参数名：{args_names}\n"
        "请返回一个 JSON 对象，键为参数名，值为合适的测试值（例如城市名、数字、字符串等）。\n"
        "只返回 JSON 对象，不要其他文字。"
    )

    # --- skill metadata field descriptions (smeta) ---
    _smeta_zh = {
        "smeta.field.version": "版本号，如 v1.0, v1.1",
        "smeta.field.code": "该版本的完整代码",
        "smeta.field.score_ver": "该版本的综合评分（0-100）",
        "smeta.field.reason": "版本变更原因或评分说明",
        "smeta.field.created_ver": "版本创建时间",
        "smeta.field.skill_name": "技能名称（大写字母数字下划线）",
        "smeta.field.status": "状态：active（活跃）、needs_optimization（需优化）、deprecated（已废弃）",
        "smeta.field.current_version": "当前使用的版本号",
        "smeta.field.score_meta": "当前版本的综合评分（0-100）",
        "smeta.field.metrics": "运行指标，用于动态评分",
        "smeta.field.versions": "版本字典，key为版本号，value为SkillVersion对象",
        "smeta.field.created_meta": "技能首次入库时间",
        "smeta.field.updated_meta": "最后一次元数据更新时间",
    }
    _smeta_en = {
        "smeta.field.version": "Version label, e.g. v1.0, v1.1",
        "smeta.field.code": "Full source code for this version",
        "smeta.field.score_ver": "Aggregate score for this version (0–100)",
        "smeta.field.reason": "Change reason or scoring note",
        "smeta.field.created_ver": "Version creation time",
        "smeta.field.skill_name": "Skill name (uppercase letters, digits, underscore)",
        "smeta.field.status": "Status: active, needs_optimization, or deprecated",
        "smeta.field.current_version": "Currently selected version id",
        "smeta.field.score_meta": "Current aggregate score (0–100)",
        "smeta.field.metrics": "Runtime metrics for dynamic scoring",
        "smeta.field.versions": "Map of version id → SkillVersion",
        "smeta.field.created_meta": "First registration time",
        "smeta.field.updated_meta": "Last metadata update time",
    }
    for k, v in _smeta_zh.items():
        zh[k] = v
    for k, v in _smeta_en.items():
        en[k] = v

    # --- sub_agent (csub) ---
    _csub_zh = {
        "csub.console.spawn": "[dim cyan]🧬 子人格 [{task_id}] 激活 (独立分配至 {brain} 脑)...[/dim cyan]",
        "csub.console.done": "[dim green]✅ 子人格 [{task_id}] 任务回归。[/dim green]",
        "csub.console.orchestrate": "\n[bold magenta]🕸️ [Orchestrator] 分配 {n} 个原子任务 (双脑独立并行分流)[/bold magenta]",
        "csub.console.fused": "[bold magenta]🕸️ [Orchestrator] 双轨记忆融合完毕。[/bold magenta]\n",
        "csub.prompt.system": (
            "你是 AdamI 子人格。任务：{task_desc}\n"
            "可用技能库：{skills}\n"
            "你必须输出包含有效 JSON 的文本，格式示范：\n"
            '{{"action": "CALL_SKILL", "skill_name": "...", "args": {{...}}}}\n'
            '或 {{"action": "COMPLETE", "result": "..."}}'
        ),
        "csub.err.brain_dead": "[Task {task_id}] 脑回路断裂",
        "csub.err.lost": "[Task {task_id}] 步骤耗尽或逻辑迷失。",
    }
    _csub_en = {
        "csub.console.spawn": "[dim cyan]🧬 Sub-persona [{task_id}] active (routed to {brain} brain)...[/dim cyan]",
        "csub.console.done": "[dim green]✅ Sub-persona [{task_id}] completed.[/dim green]",
        "csub.console.orchestrate": "\n[bold magenta]🕸️ [Orchestrator] {n} atomic tasks (dual-brain parallel)[/bold magenta]",
        "csub.console.fused": "[bold magenta]🕸️ [Orchestrator] dual-track fusion done.[/bold magenta]\n",
        "csub.prompt.system": (
            "You are an AdamI sub-persona. Task: {task_desc}\n"
            "Available skills: {skills}\n"
            "You must output valid JSON in the reply. Example shapes:\n"
            '{{"action": "CALL_SKILL", "skill_name": "...", "args": {{...}}}}\n'
            'or {{"action": "COMPLETE", "result": "..."}}'
        ),
        "csub.err.brain_dead": "[Task {task_id}] brain disconnect (empty model output)",
        "csub.err.lost": "[Task {task_id}] out of steps or lost logic.",
    }
    zh.update(_csub_zh)
    en.update(_csub_en)

    return en, zh


_W21_EN0, _W21_ZH0 = build_wave21_blobs()
WAVE21_KEYS: tuple[str, ...] = tuple(sorted(_W21_EN0))
assert _W21_EN0.keys() == _W21_ZH0.keys(), "wave21 EN/ZH key sets must match"
