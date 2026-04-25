# -*- coding: utf-8 -*-
"""Wave-23 Step7: final CJK migration batch."""

from __future__ import annotations

import json
from typing import Any


def build_wave23_blobs() -> tuple[dict[str, str], dict[str, str]]:
    en: dict[str, str] = {}
    zh: dict[str, str] = {}

    # --- code_quality_scorer (cqsc) ---
    en["cqsc.log.score_done"] = "[CodeQualityScorer] {skill_name} scored → total {total:.1f}/100"
    zh["cqsc.log.score_done"] = "[CodeQualityScorer] {skill_name} 评分完成 → 总分 {total:.1f}/100"
    en["cqsc.rec.rule_done"] = "Rule engine scoring complete"
    zh["cqsc.rec.rule_done"] = "规则引擎评分完成"
    en["cqsc.log.rule_err"] = "[CodeQualityScorer] rule scoring error: {err}"
    zh["cqsc.log.rule_err"] = "[CodeQualityScorer] 规则评分异常: {err}"
    en["cqsc.rec.rule_fail"] = "Rule scoring failed"
    zh["cqsc.rec.rule_fail"] = "规则评分失败"
    en["cqsc.prompt.review"] = (
        "You are a rigorous code auditor. Compare two versions of skill {skill_name} and return "
        "structured scores 0–100.\n\n【Old version】\n{old_snippet}\n\n【New version】\n{new_snippet}\n\n"
        "Output JSON only (no prose):\n{{\n"
        '  "functionality": 0-100,\n  "robustness": 0-100,\n  "code_quality": 0-100,\n'
        '  "performance": 0-100,\n  "security": 0-100,\n'
        '  "recommendation": "one-line verdict on whether to replace"\n}}'
    )
    zh["cqsc.prompt.review"] = (
        "你是一位严谨的代码审计专家。\n对比以下两个版本的 {skill_name} 技能代码，给出 0-100 分的结构化评分。\n\n"
        "【旧版本代码】\n{old_snippet}\n\n【新版本代码】\n{new_snippet}\n\n"
        "请严格按以下 JSON 输出（只输出 JSON，不要其他文字）：\n{{\n"
        '  "functionality": 0-100,\n  "robustness": 0-100,\n  "code_quality": 0-100,\n'
        '  "performance": 0-100,\n  "security": 0-100,\n'
        '  "recommendation": "一句话总结是否值得替换"\n}}'
    )
    en["cqsc.rec.llm_done"] = "LLM review complete"
    zh["cqsc.rec.llm_done"] = "LLM 审查完成"
    en["cqsc.log.llm_fallback"] = "[CodeQualityScorer] LLM review failed, rule fallback: {err}"
    zh["cqsc.log.llm_fallback"] = "[CodeQualityScorer] LLM 审查失败，使用规则兜底: {err}"

    # --- scan_regex_issues (scan) ---
    en["scan.print.start"] = "🔍 V5.1 scan starting...\n"
    zh["scan.print.start"] = "🔍 V5.1 最终扫描开始...\n"
    en["scan.print.done"] = (
        "🎉 V5.1 scan done. Checked {total} files; **no regex escape issues found**!\n"
        "   kernel.py / sub_agent.py / swarm_intelligence.py OK ✅\n"
    )
    zh["scan.print.done"] = (
        "🎉 V5.1 扫描完成！共检查 {total} 个文件，**无任何真正正则转义错误**！\n"
        "   kernel.py / sub_agent.py / swarm_intelligence.py 已完全正常 ✅\n"
    )
    en["scan.print.list_title"] = "📋 Checked files ({n}):\n"
    zh["scan.print.list_title"] = "📋 所有被检查的文件列表（共{n}个）：\n"
    en["scan.print.list_footer"] = "\n✅ All {n} files scanned."
    zh["scan.print.list_footer"] = "\n✅ 共 {n} 个文件已全部扫描完毕！"

    # --- executor (exec) ---
    en["exec.err.not_task"] = "message is not a task"
    zh["exec.err.not_task"] = "非 task 消息"
    en["exec.log.direct_call"] = "[Executor] direct skill={skill_name} args={args}"
    zh["exec.log.direct_call"] = "[Executor] 收到直接调用的技能: {skill_name}，参数 {args}"
    en["exec.log.no_user_task"] = "[Executor] cannot route without original user task"
    zh["exec.log.no_user_task"] = "[Executor] 无法获取原始用户任务，无法进行路由"
    en["exec.err.no_user_task"] = "missing original user task; cannot determine action"
    zh["exec.err.no_user_task"] = "缺少原始用户任务，无法确定要执行的操作"
    en["exec.log.user_task"] = "[Executor] original task (truncated): {snippet}"
    zh["exec.log.user_task"] = "[Executor] 原始用户任务: {snippet}"
    en["exec.log.router_match"] = "[Executor] SkillRouter matched skill={skill_name} args={args}"
    zh["exec.log.router_match"] = "[Executor] SkillRouter 匹配到技能 {skill_name}，参数 {args}"
    en["exec.log.router_none"] = "[Executor] SkillRouter matched no skill"
    zh["exec.log.router_none"] = "[Executor] SkillRouter 未匹配到任何技能"
    en["exec.err.no_skill"] = "no runnable skill found; create a new skill"
    zh["exec.err.no_skill"] = "未找到可用的技能，需要创建新技能"
    en["exec.log.no_router_name"] = "[Executor] SkillRouter missing and no skill name in payload"
    zh["exec.log.no_router_name"] = "[Executor] SkillRouter 未注入且未找到技能名称"
    en["exec.err.no_skill_name"] = "skill name not found"
    zh["exec.err.no_skill_name"] = "未找到技能名称"
    en["exec.log.fallback_call"] = "[Executor] fallback direct skill={skill_name} args={args}"
    zh["exec.log.fallback_call"] = "[Executor] 回退模式：直接调用技能 {skill_name}，参数 {args}"
    en["exec.log.skill_not_loaded"] = "[Executor] skill {skill_name} not loaded"
    zh["exec.log.skill_not_loaded"] = "[Executor] 技能 {skill_name} 未加载"
    en["exec.detail.not_loaded"] = "skill not loaded"
    zh["exec.detail.not_loaded"] = "技能未加载"
    en["exec.err.skill_missing"] = "skill {skill_name} does not exist"
    zh["exec.err.skill_missing"] = "技能 {skill_name} 不存在"
    en["exec.log.invoke"] = "[Executor] invoking skill={skill_name} args={safe_args}"
    zh["exec.log.invoke"] = "[Executor] 准备调用技能 {skill_name}，参数 {safe_args}"
    en["exec.log.done"] = "skill {skill_name} finished: {result}"
    zh["exec.log.done"] = "技能 {skill_name} 执行完成，结果: {result}"
    en["exec.log.invoke_fail"] = "[Executor][BugFix] skill {skill_name} failed: {error_msg}"
    zh["exec.log.invoke_fail"] = "[Executor][BugFix] 技能 {skill_name} 调用失败: {error_msg}"

    # --- skill_manager (skmg) ---
    en["skmg.warn.no_vector"] = (
        "⚠️ [SkillManager] VectorStore not injected; new skills won't appear in semantic routing "
        "(rebuild index after restart)"
    )
    zh["skmg.warn.no_vector"] = (
        "⚠️ [SkillManager] VectorStore 未注入，新技能将无法被语义路由检索（需重启后重建索引）"
    )
    en["skmg.log.anthropic_tpl"] = "[SkillManager][Anthropic] official skill; registering via prompt_template: {skill_name}"
    zh["skmg.log.anthropic_tpl"] = "[SkillManager][Anthropic] 检测到官方技能，使用 prompt_template 注册: {skill_name}"
    en["skmg.log.anthropic_attr"] = "[SkillManager][Anthropic] import_single_skill unavailable; using default"
    zh["skmg.log.anthropic_attr"] = "[SkillManager][Anthropic] import_single_skill 方法暂不可用，使用默认兜底"
    en["skmg.log.anthropic_fail"] = "[SkillManager][Anthropic] failed to load official skill: {err}"
    zh["skmg.log.anthropic_fail"] = "[SkillManager][Anthropic] 获取官方技能失败: {err}"
    en["skmg.log.exists_active"] = "[SkillManager] {skill_name} already ACTIVE; skip duplicate register"
    zh["skmg.log.exists_active"] = "[SkillManager] 技能 {skill_name} 已存在且为 ACTIVE，跳过重复注册"
    en["skmg.log.lifecycle_recreate"] = (
        "[SkillManager] {skill_name} lifecycle recreated (old status: {old_status})"
    )
    zh["skmg.log.lifecycle_recreate"] = (
        "[SkillManager] 技能 {skill_name} 已存在，将重新创建生命周期（旧状态: {old_status}）"
    )
    en["skmg.lifecycle.code_gen_done"] = "code generation finished"
    zh["skmg.lifecycle.code_gen_done"] = "代码生成完成"
    en["skmg.log.inspect_fail"] = "[SkillManager][BugFix] {skill_name} inspection failed: {feedback}"
    zh["skmg.log.inspect_fail"] = "[SkillManager][BugFix] 技能 {skill_name} 质检未通过: {feedback}"
    en["skmg.lifecycle.inspection_ok"] = "inspection passed"
    zh["skmg.lifecycle.inspection_ok"] = "质检通过"
    en["skmg.log.reg_evolution_fail"] = "[SkillManager] register {skill_name} to EvolutionEngine failed: {err}"
    zh["skmg.log.reg_evolution_fail"] = "[SkillManager] 注册技能 {skill_name} 到 EvolutionEngine 失败: {err}"
    en["skmg.lifecycle.loaded"] = "dynamic load complete"
    zh["skmg.lifecycle.loaded"] = "动态加载完成"
    en["skmg.log.anthropic_protected"] = "[SkillManager][Protected] Anthropic official {skill_name} marked protected"
    zh["skmg.log.anthropic_protected"] = (
        "[SkillManager][Protected] Anthropic 官方技能 {skill_name} 已自动标记为 protected"
    )
    en["skmg.log.instinct_add"] = "[SkillManager][Instinct] {skill_name} added to instinct set"
    zh["skmg.log.instinct_add"] = "[SkillManager][Instinct] 技能 {skill_name} 已加入本能集合"
    en["skmg.log.register_ok"] = "✅ [SkillManager] {skill_name} inspected and registered"
    zh["skmg.log.register_ok"] = "✅ [SkillManager] 技能 {skill_name} 质检通过并成功注册"
    en["skmg.log.vs_sync_retry"] = "[SkillManager] VectorStore sync attempt {attempt}/3 failed: {err}"
    zh["skmg.log.vs_sync_retry"] = "[SkillManager] VectorStore 同步尝试 {attempt}/3 失败: {err}"
    en["skmg.log.vs_sync_fail"] = "[SkillManager] {skill_name} VectorStore sync failed: {err}"
    zh["skmg.log.vs_sync_fail"] = "[SkillManager] 技能 {skill_name} 同步到 VectorStore 失败: {err}"
    en["skmg.lifecycle.active"] = "registered and activated"
    zh["skmg.lifecycle.active"] = "注册并激活完成"
    en["skmg.log.scoring_paused"] = (
        "[SkillManager][UnifiedIntent][Note] scoring paused; recording iteration only: {skill_name} success={success}"
    )
    zh["skmg.log.scoring_paused"] = (
        "[SkillManager][UnifiedIntent][Note] 评分系统已暂停，仅记录版本迭代: {skill_name} success={success}"
    )
    en["skmg.log.protected"] = "[SkillManager][Protected] {skill_name} is protected"
    zh["skmg.log.protected"] = "[SkillManager][Protected] 技能 {skill_name} 已标记为 protected"
    en["skmg.log.instinct_auto"] = "[SkillManager][Instinct] {skill_name} auto-added to instinct set"
    zh["skmg.log.instinct_auto"] = "[SkillManager][Instinct] 技能 {skill_name} 已自动加入本能集合"
    en["skmg.lifecycle.deprecated_failures"] = "consecutive execution failures"
    zh["skmg.lifecycle.deprecated_failures"] = "连续执行失败"
    en["skmg.log.deprecated"] = "[SkillManager] {skill_name} marked DEPRECATED (repeated failures)"
    zh["skmg.log.deprecated"] = "[SkillManager] 技能 {skill_name} 已标记为 DEPRECATED（连续失败）"
    en["skmg.log.anthropic_mem"] = "[SkillManager][Anthropic] import_single_skill unavailable; memory lookup"
    zh["skmg.log.anthropic_mem"] = "[SkillManager][Anthropic] import_single_skill 方法暂不可用，继续内存检索"
    en["skmg.log.parse_meta_fail"] = "[SkillManager] metadata parse failed: {err}"
    zh["skmg.log.parse_meta_fail"] = "[SkillManager] 解析元数据失败: {err}"
    en["skmg.log.cleanup_req"] = "[SkillManager] cleanup requested (delegated to SkillCleaner)"
    zh["skmg.log.cleanup_req"] = "[SkillManager] 触发技能库清理请求（已委托给 SkillCleaner 定时任务）"
    en["skmg.cleanup.reason"] = "scoring paused; cleanup checks idle/invalid files only"
    zh["skmg.cleanup.reason"] = "评分系统暂停，清理仅执行闲置/非法文件检查"

    # --- long_task_schema Field descriptions (ltsc) ---
    _lt_en = {
        "ltsc.field.artifact_type": "Artifact type, e.g. research_summary, patch_bundle, test_report",
        "ltsc.field.uri_ref": "Out-of-band ref (path, s3://, adami://); do not stuff full text into summary",
        "ltsc.field.summary": "Short summary for UI/audit; full text via uri_or_payload_ref",
        "ltsc.field.created_at": "UTC timestamp",
        "ltsc.field.producer": "Agent/component id that produced this artifact",
        "ltsc.field.content_hash": "Optional fingerprint (e.g. sha256 hex) of body or external blob",
    }
    _lt_zh = {
        "ltsc.field.artifact_type": "产物类型，如 research_summary、patch_bundle、test_report",
        "ltsc.field.uri_ref": "大对象外置引用：文件路径、s3://、adami:// 等；勿把全文塞进 summary",
        "ltsc.field.summary": "短摘要，供 UI/审计；全文走 uri_or_payload_ref",
        "ltsc.field.created_at": "UTC 时间",
        "ltsc.field.producer": "写入该产物的 Agent / 组件标识",
        "ltsc.field.content_hash": "可选：正文或外置对象的校验指纹（如 sha256 hex）",
    }
    en.update(_lt_en)
    zh.update(_lt_zh)

    # --- sim schema (sim) ---
    en["sim.field.phase"] = "Long-task phase (e.g. phase_gate to_phase); redundant with payload for replay stats"
    zh["sim.field.phase"] = "长任务目标阶段（如 phase_gate 的 to_phase）；与 payload 内字段冗余便于回放聚合"
    en["sim.field.checkpoint_seq"] = "LayeredMemory checkpoint sequence when write succeeded"
    zh["sim.field.checkpoint_seq"] = "本事件关联的 LayeredMemory 阶段 checkpoint 序号（若当次写库成功）"

    # --- proprioception (prop) ---
    en["prop.log.sniff_fail"] = "[Proprioception] host vitals check failed: {err}"
    zh["prop.log.sniff_fail"] = "[Proprioception] 嗅探失败: {err}"
    en["prop.log.starve_on"] = "🩸 [Proprioception] API rate limit — entering global throttle..."
    zh["prop.log.starve_on"] = "🩸 [Proprioception] 硅基供血不足 (Rate Limit)！系统进入全局节流模式..."
    en["prop.log.starve_cool"] = "🩸 [Proprioception] 60s cooldown done; resuming monitor..."
    zh["prop.log.starve_cool"] = "🩸 [Proprioception] 60秒冷却结束，继续监控..."
    en["prop.log.starve_off"] = "🩸 [Proprioception] API supply restored; throttle lifted"
    zh["prop.log.starve_off"] = "🩸 [Proprioception] API 供血恢复，节流模式已解除"
    en["prop.pain.ram"] = "Host RAM critically high ({pct:.1f}%) — possible leak or huge file loop."
    zh["prop.pain.ram"] = "宿主物理内存极度枯竭 (已达 {pct:.1f}%)！当前可能陷入了大型文件死循环或内存泄漏。"
    en["prop.pain.cpu"] = "Host CPU critically high ({pct:.1f}%) — compute may be out of control."
    zh["prop.pain.cpu"] = "宿主物理 CPU 严重过载 (已达 {pct:.1f}%)！算力引擎可能已失控。"
    en["prop.log.pain"] = "💥 [PHYSICAL PAIN] reflex fired: {pain_type}"
    zh["prop.log.pain"] = "💥 [PHYSICAL PAIN] 触发全身痛觉反射: {pain_type}"
    en["prop.event.task"] = (
        "【Physical pain alert】: {detail}. Stop exploratory work immediately; consider DELETE_SKILL to "
        "unload heavy resident skills, or TASK_COMPLETE to end the chain, then sleep silently ≥60s."
    )
    zh["prop.event.task"] = (
        "【物理剧痛警告】: {detail}。请立刻停止当前一切探索性任务，考虑调用 DELETE_SKILL 卸载不必要的内存驻留技能，"
        "或直接调用 TASK_COMPLETE 终止运行链条，并静默休眠至少 60 秒！"
    )

    # --- recommender (reco) ---
    en["reco.log.active"] = "🧠 [SkillRecommender] MetaCortex recommender active"
    zh["reco.log.active"] = "🧠 [SkillRecommender] MetaCortex 智能推荐引擎已激活"
    en["reco.reason.row"] = "MetaCortex direction: {target} | high-star repo, recently active"
    zh["reco.reason.row"] = "MetaCortex 推荐方向：{target} | 高星仓库，近期活跃"
    en["reco.desc.none"] = "(no description)"
    zh["reco.desc.none"] = "暂无描述"
    en["reco.log.count"] = "🎯 generated {n} recommendations"
    zh["reco.log.count"] = "🎯 生成 {n} 条智能推荐"
    en["reco.summary.persona"] = (
        "Currently {dynamic} dynamic skills + {instincts} instincts. "
        "Consider adding AI agents, web automation, and blockchain tooling."
    )
    zh["reco.summary.persona"] = (
        "当前拥有 {dynamic} 个动态技能 + {instincts} 个固化本能。需要补充 AI 代理、网络自动化、区块链工具等领域能力。"
    )

    # --- skill_builder (skbd) ---
    en["skbd.log.instinct_skip"] = "[SkillBuilder][Instinct] skip rebuild for instinct {skill_name}"
    zh["skbd.log.instinct_skip"] = "[SkillBuilder][Instinct] 跳过本能技能 {skill_name} 的重新构建（已固化）"
    en["skbd.log.instinct_missing"] = "[SkillBuilder][Instinct] instinct {skill_name} file missing; forcing build"
    zh["skbd.log.instinct_missing"] = "[SkillBuilder][Instinct] 本能技能 {skill_name} 文件丢失，强制构建一次"
    en["skbd.log.complete_detected"] = "[SkillBuilder] complete skill detected; skip template wrap: {skill_name}"
    zh["skbd.log.complete_detected"] = "[SkillBuilder] 检测到完整技能代码，跳过标准模板包装: {skill_name}"
    en["skbd.log.validate_exc"] = "[SkillBuilder] validation exception: {err}"
    zh["skbd.log.validate_exc"] = "[SkillBuilder] 验证异常: {err}"
    en["skbd.log.step1_ok"] = "[SkillBuilder][Step1] inspection OK → v1.0 (VALIDATED); returning success"
    zh["skbd.log.step1_ok"] = "[SkillBuilder][Step1] 质检通过 → 标记为 v1.0 (VALIDATED)，立即返回用户成功"
    en["skbd.log.bg_sched"] = "[SkillBuilder][Background] queued TDD for {skill_name} (file: {file_path})"
    zh["skbd.log.bg_sched"] = "[SkillBuilder][Background] 推入后台 TDD 任务 → {skill_name} (文件: {file_path})"
    en["skbd.log.bg_ok"] = "[SkillBuilder][Background] TDD & SelfTest scheduled (async)"
    zh["skbd.log.bg_ok"] = "[SkillBuilder][Background] TDD & SelfTest 已成功调度至后台（异步执行）"
    en["skbd.log.bg_err"] = "[SkillBuilder][Background] background TDD task error: {err}"
    zh["skbd.log.bg_err"] = "[SkillBuilder][Background] 后台 TDD 任务异常: {err}"
    en["skbd.log.micro_ok"] = "[SkillBuilder][MicroRetry] snapshot written: {path}"
    zh["skbd.log.micro_ok"] = "[SkillBuilder][MicroRetry] 微重试结果已直接写入临时工作区: {path}"
    en["skbd.log.micro_warn"] = "[SkillBuilder][MicroRetry] temp workspace write failed (non-fatal): {err}"
    zh["skbd.log.micro_warn"] = "[SkillBuilder][MicroRetry] 临时工作区写入失败（不中断主流程）: {err}"
    en["skbd.sec.msg"] = "dangerous operation detected: {kw}"
    zh["skbd.sec.msg"] = "检测到危险操作: {kw}"
    en["skbd.sec.suggest"] = "remove dangerous code"
    zh["skbd.sec.suggest"] = "请移除危险代码"
    en["skbd.tpl.comment_httpx"] = "# httpx added for network templates (weather/price)"
    zh["skbd.tpl.comment_httpx"] = "# ← 自动添加，确保 weather / price 等模板可直接运行"
    en["skbd.tpl.log_err"] = "Skill {skill_name} execute error: {{e}}"
    zh["skbd.tpl.log_err"] = "技能 {skill_name} 执行异常: {{e}}"
    en["skbd.log.write_fail"] = "[SkillBuilder] write file failed: {err}"
    zh["skbd.log.write_fail"] = "[SkillBuilder] 写入文件失败: {err}"

    # --- mcp contracts LLM fragment (mcpf) ---
    en["mcpf.header"] = "【🛠️ Registered tools (JSON Schema)】"
    zh["mcpf.header"] = "【🛠️ 已注册工具（JSON Schema 格式）】"
    en["mcpf.block"] = "Tool: {tool_id}\nDescription: {description}\nSchema:\n{schema_str}\n"
    zh["mcpf.block"] = "工具: {tool_id}\n描述: {description}\nSchema:\n{schema_str}\n"
    en["mcpf.footer"] = "The LLM must follow each tool Schema exactly for arguments."
    zh["mcpf.footer"] = "\nLLM 必须严格按照 Schema 输出参数！"
    en["mcpf.truncated"] = "\n... (truncated: too many tools)"
    zh["mcpf.truncated"] = "\n...（工具过多，已自动截断）"

    # --- web_tool (webt) ---
    en["webt.err.backend_title"] = "Search backend unavailable"
    zh["webt.err.backend_title"] = "搜索后端不可用"
    en["webt.err.backend_body"] = "Install ddgs or duckduckgo_search; degraded (SEARCH_BACKEND=unavailable)."
    zh["webt.err.backend_body"] = "请安装 ddgs 或 duckduckgo_search；当前环境已降级（SEARCH_BACKEND=unavailable）。"
    en["webt.err.fail_title"] = "Search failed"
    zh["webt.err.fail_title"] = "搜索失败"
    en["webt.err.fail_body"] = "Error: {detail} (backend: {backend})"
    zh["webt.err.fail_body"] = "错误: {detail} (后端: {backend})"

    # --- hybrid router (hyrt) ---
    en["hyrt.trace.mlx_unload"] = "MLX model unload (proactive)"
    zh["hyrt.trace.mlx_unload"] = "MLX 模型主动释放"
    en["hyrt.log.mlx_freed"] = "[HybridRouter] MLX unload: {released} object(s), {duration_ms}ms"
    zh["hyrt.log.mlx_freed"] = "[HybridRouter] MLX 模型已主动释放（{released} 对象回收），耗时 {duration_ms}ms"
    en["hyrt.log.ollama_ok"] = "[Ollama] OK | reply_len={n}"
    zh["hyrt.log.ollama_ok"] = "[Ollama] 调用成功 | 回复长度={n}"
    en["hyrt.log.ollama_fail"] = "[Ollama] call failed: {err}"
    zh["hyrt.log.ollama_fail"] = "[Ollama] 调用失败: {err}"
    en["hyrt.err.local_action"] = "Local action brain unavailable (MLX and Ollama both failed)"
    zh["hyrt.err.local_action"] = "本地行动脑不可用（MLX 和 Ollama 均失败）"
    en["hyrt.log.cloud_fail"] = "[{name}] cloud error ({exc}) → switching to local fallback"
    zh["hyrt.log.cloud_fail"] = "[{name}] 云端异常 ({exc}) → 立即切换本地兜底"
    en["hyrt.log.cloud_dead"] = "[HybridRouter] cloud {brain} brain down → forcing local MLX/Ollama"
    zh["hyrt.log.cloud_dead"] = "[HybridRouter] 云端 {brain} 脑失效 → 强制本地 MLX/Ollama 兜底"
    en["hyrt.log.local_fail"] = "[HybridRouter] local fallback also failed: {err}"
    zh["hyrt.log.local_fail"] = "[HybridRouter] 本地兜底也失败: {err}"
    en["hyrt.err.all_down"] = "All cloud and local LLM providers failed"
    zh["hyrt.err.all_down"] = "云端 + 本地全部 LLM 提供商失效"
    en["hyrt.trace.close"] = "HybridRouter graceful shutdown"
    zh["hyrt.trace.close"] = "HybridRouter 优雅关闭"
    en["hyrt.log.close_warn"] = "[HybridRouter] HTTP client close warning: {err}"
    zh["hyrt.log.close_warn"] = "[HybridRouter] 关闭 HTTP 客户端时出现警告: {err}"
    en["hyrt.log.close_ok"] = "[HybridRouter] HTTP client closed cleanly"
    zh["hyrt.log.close_ok"] = "[HybridRouter] HTTP 客户端已优雅关闭"
    en["hyrt.log.http_pool"] = "[HybridRouter] HTTP pool (re)initialized (timeout {timeout:.1f}s)"
    zh["hyrt.log.http_pool"] = "[HybridRouter] HTTP 连接池已(重新)初始化（超时 {timeout:.1f}s）"

    # --- vector_store (vs) ---
    bad_zh = ["需要提供技能的实现代码", "架构设计方案", "等待工作流完成"]
    en["vs.bad_markers_json"] = json.dumps(bad_zh, ensure_ascii=False)
    zh["vs.bad_markers_json"] = json.dumps(bad_zh, ensure_ascii=False)
    en["vs.log.already_init"] = "[VectorStore] already initialized, skip"
    zh["vs.log.already_init"] = "[VectorStore] 已初始化，跳过重复初始化"
    en["vs.log.fallback_search"] = "[VectorStore] [FALLBACK] text search: {query}"
    zh["vs.log.fallback_search"] = "[VectorStore] [FALLBACK] 执行文本搜索：{query}"
    en["vs.log.init_fail"] = "[VectorStore] init failed: {err}"
    zh["vs.log.init_fail"] = "[VectorStore] 初始化失败: {err}"
    en["vs.log.cleanup_fail"] = "[VectorStore][Cleanup] bad-skill cleanup failed: {err}"
    zh["vs.log.cleanup_fail"] = "[VectorStore][Cleanup] 清理坏技能失败: {err}"
    en["vs.warn.not_init_rebuild"] = "[VectorStore] not initialized; skip rebuild"
    zh["vs.warn.not_init_rebuild"] = "[VectorStore] 未初始化，无法重建索引"
    en["vs.log.no_meta"] = "[VectorStore] no skill metadata; skip rebuild"
    zh["vs.log.no_meta"] = "[VectorStore] 没有找到技能元数据，跳过索引重建"
    en["vs.log.clear_fail"] = "[VectorStore] collection clear failed: {err}"
    zh["vs.log.clear_fail"] = "[VectorStore] 清空集合失败: {err}"
    en["vs.log.rebuild_fallback"] = "[VectorStore] [FALLBACK] index rebuilt, {n} skill vectors"
    zh["vs.log.rebuild_fallback"] = "[VectorStore] [FALLBACK] 索引重建完成, 共 {n} 个技能向量"
    en["vs.log.upsert_fail"] = "[VectorStore] batch upsert failed: {err}"
    zh["vs.log.upsert_fail"] = "[VectorStore] 批量 upsert 失败: {err}"
    en["vs.warn.not_init_search"] = "[VectorStore] not initialized; empty results"
    zh["vs.warn.not_init_search"] = "[VectorStore] 未初始化，返回空列表"
    en["vs.log.empty_get_fail"] = "[VectorStore] empty-query get() failed: {err}"
    zh["vs.log.empty_get_fail"] = "[VectorStore] 空查询 get() 失败: {err}"
    en["vs.log.search_fail"] = "[VectorStore] search failed: {err}"
    zh["vs.log.search_fail"] = "[VectorStore] 搜索失败: {err}"
    en["vs.warn.add_not_init"] = "[VectorStore] add_skill while not initialized; retrying init for {skill_name}..."
    zh["vs.warn.add_not_init"] = "[VectorStore] 技能 {skill_name} 添加时 store 未初始化，尝试初始化..."
    en["vs.warn.add_init_fail"] = "[VectorStore] init failed; cannot add {skill_name}"
    zh["vs.warn.add_init_fail"] = "[VectorStore] 初始化失败，无法添加技能 {skill_name}"
    en["vs.log.add_fallback"] = "[VectorStore] [FALLBACK] upserted vector: {skill_name}"
    zh["vs.log.add_fallback"] = "[VectorStore] [FALLBACK] 已添加/更新技能向量: {skill_name}"
    en["vs.log.add_ok"] = "[VectorStore] upserted vector: {skill_name}"
    zh["vs.log.add_ok"] = "[VectorStore] 已添加/更新技能向量: {skill_name}"
    en["vs.log.add_fail"] = "[VectorStore] add skill vector failed: {err}"
    zh["vs.log.add_fail"] = "[VectorStore] 添加技能向量失败: {err}"
    en["vs.log.remove_fail"] = "[VectorStore] delete skill vector failed: {err}"
    zh["vs.log.remove_fail"] = "[VectorStore] 删除技能向量失败: {err}"
    en["vs.log.chroma_close"] = "[VectorStore] ChromaDB client closed cleanly"
    zh["vs.log.chroma_close"] = "[VectorStore] ChromaDB 客户端已优雅关闭"
    en["vs.err.chroma_unavailable"] = "[VectorStore] ChromaDB unavailable; vector store disabled"
    zh["vs.err.chroma_unavailable"] = "[VectorStore] ChromaDB 不可用，无法初始化向量存储"

    # --- report_providers heuristic (rpt) ---
    # Catalog strings pass through str.format(); JSON braces must be doubled.
    repair = json.loads('"\u4fee\u590d"')
    abnormal = json.loads('"\u5f02\u5e38"')
    en_json = json.dumps({"repair": "repair", "abnormal": "abnormal"}, ensure_ascii=False)
    zh_json = json.dumps({"repair": repair, "abnormal": abnormal}, ensure_ascii=False)
    en["rpt.kernel_signals_json"] = en_json.replace("{", "{{").replace("}", "}}")
    zh["rpt.kernel_signals_json"] = zh_json.replace("{", "{{").replace("}", "}}")

    return en, zh


_W23_EN0, _W23_ZH0 = build_wave23_blobs()
WAVE23_KEYS: tuple[str, ...] = tuple(sorted(_W23_EN0))
assert _W23_EN0.keys() == _W23_ZH0.keys(), "wave23 EN/ZH key sets must match"
