# -*- coding: utf-8 -*-
"""Wave-24: skill_composer, decision_processor, engineer, multi_agent_orchestrator, skill_factory logger strings."""

from __future__ import annotations


def build_wave24_blobs() -> tuple[dict[str, str], dict[str, str]]:
    en: dict[str, str] = {}
    zh: dict[str, str] = {}

    pairs: list[tuple[str, str, str]] = [
        # --- skill_composer (skcp) ---
        (
            "skcp.log.otel_noop",
            "[SkillComposer] OTEL not ready; using noop span",
            "[SkillComposer] OTEL observability 未就绪，使用 noop span",
        ),
        ("skcp.log.otel_span", "[OTEL noop] span started: {name}", "[OTEL noop] span started: {name}"),
        (
            "skcp.warn.router_import",
            "[SkillComposer] SkillRouter lazy import failed: {e}",
            "[SkillComposer] SkillRouter 延迟导入失败: {e}",
        ),
        (
            "skcp.warn.no_action_json",
            "[SkillComposer] cannot extract action JSON; using fallback parse",
            "[SkillComposer] 无法提取 action JSON，使用备用解析",
        ),
        (
            "skcp.warn.py_no_json",
            "[SkillComposer] extracted Python but no JSON; synthesizing CREATE_NEW_SKILL action",
            "[SkillComposer] 已提取 Python 代码但无 JSON，使用合成 CREATE_NEW_SKILL action",
        ),
        (
            "skcp.log.extract_ok",
            "[SkillComposer] CREATE_NEW_SKILL payload extracted | action={action} | code_length={code_length}",
            "[SkillComposer] 成功提取 CREATE_NEW_SKILL payload | action={action} | code_length={code_length}",
        ),
        (
            "skcp.warn.action_only_json",
            "[SkillComposer] only action JSON extracted; code block empty",
            "[SkillComposer] 仅提取到 action JSON，代码块为空",
        ),
        (
            "skcp.err.extract_fail",
            "[SkillComposer] cannot extract CREATE_NEW_SKILL payload at all",
            "[SkillComposer] 完全无法提取 CREATE_NEW_SKILL payload",
        ),
        (
            "skcp.debug.cond_han",
            "condition expression contains Han characters: {expr}",
            "条件表达式包含中文字符: {expr}",
        ),
        (
            "skcp.debug.cond_punct",
            "condition expression contains natural-language punctuation: {expr}",
            "条件表达式包含自然语言标点: {expr}",
        ),
        (
            "skcp.debug.cond_syntax",
            "condition expression syntax error: {expr}",
            "条件表达式语法错误: {expr}",
        ),
        (
            "skcp.log.cond_repair",
            "[SkillComposer] repaired condition: {old} -> {new}",
            "[SkillComposer] 修复条件表达式: {old} -> {new}",
        ),
        (
            "skcp.warn.cond_repair_fail",
            "[SkillComposer] cannot repair condition: {condition}",
            "[SkillComposer] 无法修复条件表达式: {condition}",
        ),
        (
            "skcp.warn.cond_no_successors",
            "[SkillComposer] CONDITION node {node_id} has no successors; adding empty branches",
            "[SkillComposer] 条件节点 {node_id} 没有任何后继，将添加空分支",
        ),
        (
            "skcp.log.cond_fill_branches",
            "[SkillComposer] filled branches for {node_id}: true_next={nxt}, false_next={nxt}",
            "[SkillComposer] 为条件节点 {node_id} 补充分支: true_next={nxt}, false_next={nxt}",
        ),
        (
            "skcp.log.fallback_workflow",
            "[SkillComposer] using fallback single-node workflow",
            "[SkillComposer] 使用 fallback 单节点工作流",
        ),
        (
            "skcp.warn.fallback_call_spec",
            "[SkillComposer] fallback get_call_spec error: {err}",
            "[SkillComposer] fallback get_call_spec 异常: {err}",
        ),
        (
            "skcp.err.fallback_workflow",
            "[SkillComposer] fallback workflow creation failed: {e}",
            "[SkillComposer] fallback workflow 创建失败: {e}",
        ),
        (
            "skcp.log.unified_create",
            "[SkillComposer][UnifiedIntent] CREATE_NEW_SKILL intent detected → dedicated extract path",
            "[SkillComposer][UnifiedIntent] 检测到 CREATE_NEW_SKILL 意图 → 进入专用提取流程",
        ),
        (
            "skcp.err.create_extract_fail",
            "[SkillComposer] CREATE_NEW_SKILL extract failed; returning fallback",
            "[SkillComposer] CREATE_NEW_SKILL 提取失败，返回 fallback",
        ),
        (
            "skcp.log.create_dag_ok",
            "[SkillComposer] CREATE_NEW_SKILL DAG generated (code block OK)",
            "[SkillComposer] CREATE_NEW_SKILL 专用 DAG 已生成（代码块提取成功）",
        ),
        ("skcp.err.llm", "LLM call failed: {e}", "LLM 调用失败: {e}"),
        ("skcp.err.json_decode", "JSON parse failed: {e}", "JSON 解析失败: {e}"),
        (
            "skcp.err.no_json_in_response",
            "cannot extract JSON from LLM response",
            "无法从 LLM 响应中提取 JSON",
        ),
        ("skcp.err.json_unknown", "unknown JSON parse error: {e}", "未知 JSON 解析错误: {e}"),
        (
            "skcp.err.not_json_object",
            "LLM response is not a JSON object, got {typ}",
            "LLM 返回的不是 JSON 对象，而是 {typ}",
        ),
        (
            "skcp.err.no_nodes_field",
            "workflow definition missing or invalid nodes field",
            "工作流定义缺少 nodes 字段或类型错误",
        ),
        (
            "skcp.warn.no_edges_field",
            "workflow definition missing edges; using empty edges",
            "工作流定义缺少 edges 字段，将使用空边",
        ),
        (
            "skcp.warn.node_bad_condition",
            "node {node_id} has invalid condition: {condition}",
            "节点 {node_id} 的条件表达式无效: {condition}",
        ),
        (
            "skcp.warn.invalid_conditions_retry",
            "{count} invalid condition(s); retrying workflow generation (attempt {attempt}/{max_retries})",
            "检测到 {count} 个无效条件表达式，尝试重新生成工作流 (尝试 {attempt}/{max_retries})",
        ),
        (
            "skcp.err.conditions_abort",
            "conditions still invalid after retries; aborting workflow generation",
            "重试后条件表达式仍无效，放弃生成工作流",
        ),
        ("skcp.warn.node_not_dict", "node definition is not a dict; skip", "节点定义不是字典，跳过"),
        (
            "skcp.warn.node_missing_fields",
            "node definition missing required fields; skip",
            "节点定义缺少必要字段，跳过",
        ),
        (
            "skcp.warn.unknown_node_type",
            "[SkillComposer] unknown node_type={raw_type!r}; mapping to LLM_CALL",
            "[SkillComposer] 未知 node_type={raw_type!r}，降级映射为 LLM_CALL",
        ),
        (
            "skcp.err.no_valid_nodes",
            "workflow has no valid nodes",
            "工作流未包含任何有效节点",
        ),
        (
            "skcp.log.workflow_generated",
            "SkillComposer generated workflow with {n} node(s)",
            "SkillComposer 成功生成工作流，包含 {n} 个节点",
        ),
        # --- decision_processor (dcpu) ---
        (
            "dcpu.log.skill_router_ok",
            "[DecisionProcessor] SkillRouter lazy-imported",
            "[DecisionProcessor] SkillRouter 已延迟导入",
        ),
        (
            "dcpu.warn.skill_router_fail",
            "[DecisionProcessor] SkillRouter lazy import failed: {e}",
            "[DecisionProcessor] SkillRouter 延迟导入失败: {e}",
        ),
        (
            "dcpu.warn.ui_thought",
            "[UI_ANIMATION] failed to update thought UI: {e}",
            "[UI_ANIMATION] 更新思考动画失败: {e}",
        ),
        (
            "dcpu.warn.report_push",
            "[ReportStudio] failed to push report body (ignored): {e}",
            "[ReportStudio] 推送简报正文失败（忽略）: {e}",
        ),
        (
            "dcpu.log.stop_audit",
            "[DecisionProcessor] stop_audit appended {name}",
            "[DecisionProcessor] stop_audit 追加 {name}",
        ),
        (
            "dcpu.warn.stop_audit",
            "[DecisionProcessor] stop_audit write failed (ignored): {e}",
            "[DecisionProcessor] stop_audit 写入失败（忽略）: {e}",
        ),
        (
            "dcpu.log.session_export",
            "[DecisionProcessor] session_export {name}",
            "[DecisionProcessor] session_export {name}",
        ),
        (
            "dcpu.warn.session_export",
            "[DecisionProcessor] session_export failed (ignored): {e}",
            "[DecisionProcessor] session_export 失败（忽略）: {e}",
        ),
        (
            "dcpu.log.unified_skill_intent",
            "[DecisionProcessor][UnifiedIntent] skill-creation intent detected → Planner path",
            "[DecisionProcessor][UnifiedIntent] 检测到技能创建意图，直接转 Planner 创建流程",
        ),
        (
            "dcpu.warn.planner_none",
            "[DecisionProcessor] Planner returned None; using empty dict fallback",
            "[DecisionProcessor] Planner 返回 None，使用空字典兜底",
        ),
        (
            "dcpu.log.plan_ok",
            "[DecisionProcessor] skill creation plan validated: {skill_name}",
            "[DecisionProcessor] 技能创建计划验证通过: {skill_name}",
        ),
        (
            "dcpu.warn.plan_pydantic",
            "[DecisionProcessor] Pydantic validation failed; template fallback: {ve}",
            "[DecisionProcessor] Pydantic 验证失败，回退到模板: {ve}",
        ),
        (
            "dcpu.debug.cli_after_skill",
            "[DecisionProcessor] CLI prompt restored after skill creation",
            "[DecisionProcessor] 技能创建后 CLI 提示符已强制恢复",
        ),
        (
            "dcpu.warn.cli_print",
            "[DecisionProcessor] failed to print CLI prompt: {e}",
            "[DecisionProcessor] 强制打印 CLI 提示符失败: {e}",
        ),
        (
            "dcpu.err.planner_skill",
            "[DecisionProcessor][UnifiedIntent] Planner skill creation failed: {e}",
            "[DecisionProcessor][UnifiedIntent] Planner 创建技能失败: {e}",
        ),
        (
            "dcpu.debug.cli_planner_finally",
            "[DecisionProcessor] CLI prompt restored (_create_skill_via_planner finally)",
            "[DecisionProcessor] CLI 提示符已强制恢复（_create_skill_via_planner finally）",
        ),
        (
            "dcpu.log.episodic_recalled",
            "[DecisionProcessor] recalled past errors → {snippet}...",
            "[DecisionProcessor] 已唤醒历史教训 → {snippet}...",
        ),
        (
            "dcpu.debug.cli_release",
            "[DecisionProcessor] CLI prompt restored (release_session_lock)",
            "[DecisionProcessor] CLI 提示符已强制恢复（release_session_lock）",
        ),
        (
            "dcpu.warn.cli_print_release",
            "[DecisionProcessor] CLI prompt print failed: {e}",
            "[DecisionProcessor] 打印 CLI 提示符失败: {e}",
        ),
        (
            "dcpu.debug.cli_bg_silent",
            "[DecisionProcessor] background service mode; CLI prompt fully silent",
            "[DecisionProcessor] 后台服务模式，Erique@AdamI> 提示符已完全静默",
        ),
        (
            "dcpu.log.maintain_done",
            "[DecisionProcessor] MAINTAIN diagnostics done | root={root} inbox_md={inbox_md}",
            "[DecisionProcessor] MAINTAIN 诊断完成 | root={root} inbox_md={inbox_md}",
        ),
        (
            "dcpu.warn.writing_list",
            "[WRITING] list Resources failed: {e}",
            "[WRITING] 列出 Resources 失败: {e}",
        ),
        (
            "dcpu.warn.writing_skip",
            "[WRITING] skip {path}: {e}",
            "[WRITING] 跳过 {path}: {e}",
        ),
        (
            "dcpu.log.writing_mode",
            "[WRITING] Resources mode={mode} files={files} ~{chars} chars",
            "[WRITING] Resources 模式={mode} 文件={files} 约{chars} 字",
        ),
        (
            "dcpu.err.writing_llm",
            "[WRITING] LLM call failed: {e}",
            "[WRITING] LLM 调用失败: {e}",
        ),
        (
            "dcpu.err.task_note_write",
            "[DecisionProcessor] TASK_NOTE tasks.md write failed: {e}",
            "[DecisionProcessor] TASK_NOTE 写入 tasks.md 失败: {e}",
        ),
        (
            "dcpu.log.task_note_ok",
            "[DecisionProcessor] TASK_NOTE appended | path={path} | date={date} | preview={preview}",
            "[DecisionProcessor] TASK_NOTE 已追加待办 | path={path} | 📅 {date} | preview={preview}",
        ),
        (
            "dcpu.warn.intake_para",
            "[Intake] PARA move failed (kept Inbox): {e}",
            "[Intake] PARA 归位失败（保留 Inbox）: {e}",
        ),
        (
            "dcpu.warn.intake_readme",
            "[Intake] failed to refresh PARA README member list: {e}",
            "[Intake] 刷新 PARA README 成员清单失败: {e}",
        ),
        (
            "dcpu.log.intake_ok",
            "[Intake] archive done → {path} (domain={domain} para={para})",
            "[Intake] 归档完成 → {path} (domain={domain} para={para})",
        ),
        ("dcpu.err.intake", "[Intake] archive failed: {e}", "[Intake] 归档失败: {e}"),
        (
            "dcpu.log.force_opt_ok",
            "[DecisionProcessor] FORCE_OPTIMIZE done → {skill_name}",
            "[DecisionProcessor] FORCE_OPTIMIZE 执行完成 → {skill_name}",
        ),
        (
            "dcpu.err.force_opt",
            "[DecisionProcessor] FORCE_OPTIMIZE error: {e}",
            "[DecisionProcessor] FORCE_OPTIMIZE 执行异常: {e}",
        ),
        # --- engineer (eng) ---
        (
            "eng.warn.dream_sandbox_missing",
            "[Engineer] dream_sandbox not found",
            "[Engineer] dream_sandbox 未找到",
        ),
        (
            "eng.warn.evolution_no_create",
            "[Engineer] EvolutionEngine missing create_new_skill",
            "[Engineer] EvolutionEngine 缺少 create_new_skill 方法",
        ),
        (
            "eng.warn.evolution_no_get",
            "[Engineer] EvolutionEngine missing get_skill (reuse check)",
            "[Engineer] EvolutionEngine 缺少 get_skill 方法（复用验证需要）",
        ),
        ("eng.log.ready", "[Engineer] ready", "[Engineer] ready"),
        ("eng.warn.init_exc", "[Engineer] init warning: {e}", "[Engineer] 初始化异常: {e}"),
        (
            "eng.log.degrade_report",
            "[Engineer][GracefulDegradeMonitor] report → attempts={total} tier1_rate={rate1}% degrade_rate={rate2}%",
            "[Engineer][GracefulDegradeMonitor] 降级成功率报告 → 总尝试:{total} | Tier1成功率:{rate1}% | 降级率:{rate2}%",
        ),
        (
            "eng.log.skillrouter_name",
            "[Engineer] SkillRouter normalized skill name: {name}",
            "[Engineer] SkillRouter 提供规范化技能名: {name}",
        ),
        (
            "eng.log.finalguard_applied",
            "[Engineer][FinalGuard] forced Phase 9 hardened wrapper on {skill_name}",
            "[Engineer][FinalGuard] 已对 {skill_name} **强制应用 Phase 9 铁壁兜底包装**（强制 result + 双重返回）",
        ),
        (
            "eng.debug.finalguard_preview",
            "[Engineer][FinalGuard] wrapper head:\n{preview}",
            "[Engineer][FinalGuard] 最终 wrapper 前50行:\n{preview}",
        ),
        (
            "eng.warn.microretry_no_router",
            "[Engineer][MicroRetry] router not injected; cannot micro-repair",
            "[Engineer][MicroRetry] router 未注入，无法进行微重试修复",
        ),
        (
            "eng.log.microretry_done",
            "[Engineer][MicroRetry] repair round {n} done (Phase 9)",
            "[Engineer][MicroRetry] 第 {n} 次微重试修复完成（Phase 9）",
        ),
        (
            "eng.warn.microretry_llm",
            "[Engineer][MicroRetry] repair LLM call failed: {e}",
            "[Engineer][MicroRetry] 修复 LLM 调用失败: {e}",
        ),
        (
            "eng.log.return_result",
            "[Engineer] returning: workflow_id={wid} skill_name={sn} target={tgt}",
            "[Engineer] 准备返回结果: workflow_id={wid} skill_name={sn} target={tgt}",
        ),
        (
            "eng.log.use_original_task",
            "[Engineer] using original task description: {snippet}...",
            "[Engineer] 使用原始任务描述: {snippet}...",
        ),
        (
            "eng.log.task_start",
            "[Engineer] starting engineering task: {snippet}...",
            "[Engineer] 开始工程任务: {snippet}...",
        ),
        (
            "eng.log.unified_intent_name",
            "[Engineer][UnifiedIntent] skill creation intent; normalized: {name}",
            "[Engineer][UnifiedIntent] 检测到技能创建意图，SkillRouter 规范化名称: {name}",
        ),
        (
            "eng.warn.unified_intent_fallback_name",
            "[Engineer][UnifiedIntent] SkillRouter could not normalize name; fallback generator",
            "[Engineer][UnifiedIntent] SkillRouter 未能提取规范化名称，回退生成",
        ),
        (
            "eng.log.weather_probe",
            "[Engineer] generic weather skill '{name}'; probing availability...",
            "[Engineer] 检测到通用天气技能 '{name}'，开始可用性验证...",
        ),
        (
            "eng.log.weather_ok",
            "[Engineer] skill '{name}' availability OK; reusing",
            "[Engineer] 技能 '{name}' 可用性验证通过，直接复用",
        ),
        (
            "eng.warn.weather_bad_status",
            "[Engineer] skill '{name}' run failed or status != success; invalid",
            "[Engineer] 技能 '{name}' 执行失败或 status != success，视为无效",
        ),
        (
            "eng.warn.weather_timeout",
            "[Engineer] skill '{name}' timed out (3s); invalid",
            "[Engineer] 技能 '{name}' 执行超时（3秒），视为无效",
        ),
        (
            "eng.warn.weather_exc",
            "[Engineer] skill '{name}' run error: {e}; invalid",
            "[Engineer] 技能 '{name}' 执行异常: {e}，视为无效",
        ),
        (
            "eng.warn.weather_invalid_continue",
            "[Engineer] skill '{name}' invalid; continuing creation flow",
            "[Engineer] 技能 '{name}' 无效，继续走创建流程",
        ),
        (
            "eng.log.weather_mark_optimize",
            "[Engineer] marked skill '{name}' pending optimization (SkillCleaner)",
            "[Engineer] 已标记技能 '{name}' 为待优化（供 SkillCleaner 处理）",
        ),
        ("eng.log.skill_name", "[Engineer] generated skill name: {name}", "[Engineer] 生成的技能名: {name}"),
        (
            "eng.warn.skillmanager_missing",
            "[Engineer][BugFix] SkillManager not injected; direct create (not recommended)",
            "[Engineer][BugFix] SkillManager 未注入，回退到直接创建（不推荐）",
        ),
        (
            "eng.log.microretry_round",
            "[Engineer][MicroRetry] round {n} start (Phase 9)",
            "[Engineer][MicroRetry] 第 {n} 次微重试开始（Phase 9）",
        ),
        (
            "eng.log.microretry_fixable",
            "[Engineer][MicroRetry] fixable error detected; starting LLM micro-fix",
            "[Engineer][MicroRetry] 检测到可修复错误，启动 LLM 微修复",
        ),
        (
            "eng.warn.microretry_no_change",
            "[Engineer][MicroRetry] code unchanged after fix; aborting this retry",
            "[Engineer][MicroRetry] 修复后代码无变化，放弃本次重试",
        ),
        (
            "eng.warn.microretry_unfixable",
            "[Engineer][MicroRetry] unfixable error; exiting micro-retry loop",
            "[Engineer][MicroRetry] 不可修复错误，退出微重试循环",
        ),
        (
            "eng.log.microretry_qc_ok",
            "[Engineer][MicroRetry] QC passed; round {n} succeeded",
            "[Engineer][MicroRetry] 质检通过，第 {n} 次微重试成功",
        ),
        (
            "eng.log.microretry_skip_runtime",
            "[Engineer][MicroRetry] QC passed; skipping fast runtime check (final QC covers)",
            "[Engineer][MicroRetry] 质检通过，跳过快速运行时验证（由最终质检兜底）",
        ),
        (
            "eng.log.finalguard_after_retry",
            "[Engineer][FinalGuard] micro-retry ended; Phase 9 wrapper applied to {name}",
            "[Engineer][FinalGuard] 微重试结束，已对 {name} 强制应用 Phase 9 铁壁兜底包装",
        ),
        (
            "eng.log.finalguard_no_extra",
            "[Engineer][FinalGuard] micro-retry OK; {name} passed SkillBuilder; no extra Phase 9 wrap",
            "[Engineer][FinalGuard] 微重试成功，{name} 已通过 SkillBuilder 完整验证，无需额外 Phase 9 包装",
        ),
        (
            "eng.warn.reject",
            "[Engineer][Reject] skill creation failed: {detail}",
            "[Engineer][Reject] 技能创建失败: {detail}",
        ),
        (
            "eng.warn.qc_fail",
            "[Engineer][BugFix] skill QC failed: {feedback}",
            "[Engineer][BugFix] 技能质检失败: {feedback}",
        ),
        (
            "eng.log.rename_try",
            "[Engineer][BugFix] trying corrected skill name: {name}",
            "[Engineer][BugFix] 尝试修正技能名: {name}",
        ),
        (
            "eng.log.register_renamed_ok",
            "[Engineer][BugFix] register OK after rename; name={name}",
            "[Engineer][BugFix] 技能注册成功（修正后），技能名: {name}",
        ),
        (
            "eng.log.register_ok",
            "[Engineer][BugFix] register OK; name={name}",
            "[Engineer][BugFix] 技能注册成功，技能名: {name}",
        ),
        (
            "eng.err.task_fail",
            "[Engineer] engineering task failed: {e}",
            "[Engineer] 工程任务失败: {e}",
        ),
        # --- multi_agent (orch.magent.log / warn / err) ---
        (
            "orch.magent.log.checkpoint_saved",
            "[MultiAgentOrchestrator][Checkpoint] Researcher checkpoint saved (workflow_id={wid})",
            "[MultiAgentOrchestrator][Checkpoint] Researcher checkpoint 已强制保存（workflow_id={wid}）",
        ),
        (
            "orch.magent.warn.checkpoint_fail",
            "[MultiAgentOrchestrator][Checkpoint] save failed: {e} (non-fatal)",
            "[MultiAgentOrchestrator][Checkpoint] 保存 Researcher checkpoint 失败: {e}（不影响主流程）",
        ),
        (
            "orch.magent.warn.circuit_fingerprint",
            "[MultiAgentOrchestrator][CircuitBreaker] workflow {wid} error fingerprint '{fp}' seen {count} times",
            "[MultiAgentOrchestrator][CircuitBreaker] 工作流 {wid} 错误指纹 '{fp}' 连续出现 {count} 次",
        ),
        (
            "orch.magent.err.listen",
            "[MultiAgentOrchestrator] message listener error: {e}",
            "[MultiAgentOrchestrator] 消息监听异常: {e}",
        ),
        (
            "orch.magent.log.recv",
            "[Orchestrator] message: source={src} target={tgt} workflow_id={wid} type={mtype}",
            "[Orchestrator] 收到消息: source={src} target={tgt} workflow_id={wid} message_type={mtype}",
        ),
        (
            "orch.magent.debug.recv_short",
            "[MultiAgentOrchestrator] {src} → {tgt} {mtype} | workflow={wid}",
            "[MultiAgentOrchestrator] 收到 {src} → {tgt} {mtype} | workflow={wid}",
        ),
        (
            "orch.magent.log.future_lookup",
            "[Orchestrator] future key={fkey} exists={exists}",
            "[Orchestrator] 查找 future key={fkey}, exists={exists}",
        ),
        ("orch.magent.log.future_set", "[MultiAgentOrchestrator] Future set: {fkey}", "[MultiAgentOrchestrator] Future 已设置: {fkey}"),
        (
            "orch.magent.debug.future_missing",
            "[MultiAgentOrchestrator] no Future for {fkey}; ignoring",
            "[MultiAgentOrchestrator] 未找到对应的 Future: {fkey}，忽略消息",
        ),
        (
            "orch.magent.log.event_published",
            "[MultiAgentOrchestrator] published {src} → {tgt} (trace_id={tid})",
            "[MultiAgentOrchestrator] 已发布 {src} → {tgt} 事件（trace_id={tid}）",
        ),
        (
            "orch.magent.warn.agent_missing",
            "[MultiAgentOrchestrator] target agent {tgt} not registered; have {keys}",
            "[MultiAgentOrchestrator] 目标代理 {tgt} 未注册！当前已注册代理: {keys}",
        ),
        (
            "orch.magent.err.handle_msg",
            "[MultiAgentOrchestrator] message handling failed: {e}",
            "[MultiAgentOrchestrator] 消息处理失败: {e}",
        ),
        (
            "orch.magent.log.generic_workflow",
            "[MultiAgentOrchestrator] generic workflow started → {wid}",
            "[MultiAgentOrchestrator] 通用工作流已启动 → {wid}",
        ),
        (
            "orch.magent.err.node_missing",
            "node {nid} missing; workflow FAILED",
            "节点 {nid} 不存在，工作流终止",
        ),
        (
            "orch.magent.err.workflow_exec",
            "[MultiAgentOrchestrator] workflow execution error: {e}",
            "[MultiAgentOrchestrator] 工作流执行异常: {e}",
        ),
        (
            "orch.magent.debug.run_node",
            "[MultiAgentOrchestrator] executing node {nid} ({ntype})",
            "[MultiAgentOrchestrator] 执行节点 {nid} ({ntype})",
        ),
        (
            "orch.magent.log.cond_ok",
            "[Workflow] condition OK: {path}({left}) {op} {right} -> {result}",
            "[Workflow] 条件安全评估成功: {path}({left}) {op} {right} -> {result}",
        ),
        (
            "orch.magent.err.cond_eval",
            "[Workflow] condition eval failed: {tpl} error: {e}",
            "[Workflow] 条件表达式安全求值失败: {tpl}, Error: {e}",
        ),
        (
            "orch.magent.warn.cond_fallback",
            "[Workflow] branch mismatch; using default successor: {target}",
            "[Workflow] 条件节点分支匹配失败，降级使用默认后继: {target}",
        ),
        (
            "orch.magent.err.node_exec",
            "node {nid} execution failed: {e}",
            "节点 {nid} 执行失败: {e}",
        ),
        (
            "orch.magent.log.start_multi",
            "[MultiAgentOrchestrator] starting multi-agent workflow",
            "[MultiAgentOrchestrator] 开始启动多代理工作流",
        ),
        (
            "orch.magent.log.started",
            "[MultiAgentOrchestrator] multi-agent workflow started → workflow_id={wid}",
            "[MultiAgentOrchestrator] 多代理工作流已启动 → workflow_id={wid}",
        ),
        (
            "orch.magent.err.start_fail",
            "[MultiAgentOrchestrator] failed to start multi-agent workflow: {e}",
            "[MultiAgentOrchestrator] 启动多代理工作流失败: {e}",
        ),
        (
            "orch.magent.log.skillrouter_none",
            "[MultiAgentOrchestrator][UnifiedIntent] SkillRouter returned None → creation flow",
            "[MultiAgentOrchestrator][UnifiedIntent] SkillRouter 返回 None → 进入技能创建流程",
        ),
        (
            "orch.magent.warn.skillrouter_stale",
            "[MultiAgentOrchestrator][BugFix] SkillRouter skill {name} missing; forcing creation",
            "[MultiAgentOrchestrator][BugFix] SkillRouter 返回的技能 {name} 实际不存在，强制走创建流程",
        ),
        (
            "orch.magent.log.skill_lookup_ok",
            "[MultiAgentOrchestrator] skill resolved: {name} args={args}",
            "[MultiAgentOrchestrator] 技能查找成功: {name} args={args}",
        ),
        (
            "orch.magent.err.skill_lookup",
            "[MultiAgentOrchestrator] skill lookup failed: {e}",
            "[MultiAgentOrchestrator] 技能查找失败: {e}",
        ),
        ("orch.magent.debug.future_create", "[MultiAgentOrchestrator] created Future: {fkey}", "[MultiAgentOrchestrator] 创建 Future: {fkey}"),
        (
            "orch.magent.debug.engineer_ctx",
            "[MultiAgentOrchestrator] Engineer original_task: {snippet}...",
            "[MultiAgentOrchestrator] 为 Engineer 注入原始任务: {snippet}...",
        ),
        (
            "orch.magent.log.executor_payload",
            "[MultiAgentOrchestrator] Executor skill={name} args={args}",
            "[MultiAgentOrchestrator] Executor 收到技能: {name}, 参数 {args}",
        ),
        (
            "orch.magent.debug.role_ctx",
            "[MultiAgentOrchestrator] injected context for {role}: {keys}",
            "[MultiAgentOrchestrator] 为 {role} 注入上下文结果: {keys}",
        ),
        (
            "orch.magent.log.task_sent",
            "[MultiAgentOrchestrator] task dispatched → {role}, waiting...",
            "[MultiAgentOrchestrator] 任务已分发 → {role}，等待响应...",
        ),
        (
            "orch.magent.warn.executor_missing_skill",
            "[MultiAgentOrchestrator][BugFix] Executor: skill missing; fallback to creation",
            "[MultiAgentOrchestrator][BugFix] Executor 检测到技能不存在，fallback 到创建流程",
        ),
        ("orch.magent.debug.future_clear", "[MultiAgentOrchestrator] cleared Future: {fkey}", "[MultiAgentOrchestrator] 清理 Future: {fkey}"),
        (
            "orch.magent.log.skill_fastpath",
            "[MultiAgentOrchestrator] skill hit; skipping Researcher/Engineer, running {name}",
            "[MultiAgentOrchestrator] 技能查找命中，跳过 Researcher/Engineer，直接执行 {name}",
        ),
        (
            "orch.magent.log.full_pipeline",
            "[MultiAgentOrchestrator] no existing skill; starting full multi-agent creation",
            "[MultiAgentOrchestrator] 未找到现有技能，启动完整多代理创建流程",
        ),
        (
            "orch.magent.log.timeout_set",
            "[MultiAgentOrchestrator][Timeout] task {role} wait threshold {sec}s",
            "[MultiAgentOrchestrator][Timeout] 任务 {role} 等待阈值设置为 {sec} 秒",
        ),
        (
            "orch.magent.log.timeout_ctx_ok",
            "[MultiAgentOrchestrator] task {role} timed out but result already in context; OK",
            "[MultiAgentOrchestrator] 任务 {role} 超时但结果已存在于 context，视为成功",
        ),
        (
            "orch.magent.warn.timeout_retry",
            "[MultiAgentOrchestrator] task {role} timed out with no result; retry",
            "[MultiAgentOrchestrator] 任务 {role} 超时且无结果，重试",
        ),
        (
            "orch.magent.warn.hitl_none",
            "[MultiAgentOrchestrator][NoneProtection] hitl_handler is None; skip trigger_paused, PAUSED",
            "[MultiAgentOrchestrator][NoneProtection] hitl_handler 为 None，跳过 trigger_paused，直接降级为 PAUSED",
        ),
        (
            "orch.magent.log.timeout_future_done",
            "[MultiAgentOrchestrator] future completed before timeout (key={fkey}); continuing",
            "[MultiAgentOrchestrator] 超时前 future 已完成（key={fkey}），忽略超时并继续正常流程",
        ),
        (
            "orch.magent.warn.timeout_future_err",
            "[MultiAgentOrchestrator] completed future raised: {e}; treating as timeout",
            "[MultiAgentOrchestrator] 已完成 future 获取结果异常: {e}，仍按超时处理",
        ),
        (
            "orch.magent.warn.timeout_threshold",
            "[MultiAgentOrchestrator][Timeout] task {role} exceeded {sec}s; retrying",
            "[MultiAgentOrchestrator][Timeout] 任务 {role} 超时（阈值 {sec}秒），尝试重试",
        ),
        (
            "orch.magent.warn.hitl_none_short",
            "[MultiAgentOrchestrator][NoneProtection] hitl_handler is None; skip trigger_paused",
            "[MultiAgentOrchestrator][NoneProtection] hitl_handler 为 None，跳过 trigger_paused",
        ),
        (
            "orch.magent.log.workflow_done",
            "[MultiAgentOrchestrator] workflow completed → {wid}",
            "[MultiAgentOrchestrator] 工作流完成 → {wid}",
        ),
        (
            "orch.magent.err.orchestrate",
            "[MultiAgentOrchestrator] orchestration error: {e}",
            "[MultiAgentOrchestrator] 编排异常: {e}",
        ),
        (
            "orch.magent.warn.circuit_pause",
            "[MultiAgentOrchestrator][CircuitBreaker] workflow {wid} same error 3x → PAUSED",
            "[MultiAgentOrchestrator][CircuitBreaker] 工作流 {wid} 连续 3 次相同错误，触发熔断 → PAUSED",
        ),
        (
            "orch.magent.warn.register_none",
            "[MultiAgentOrchestrator] register failed: {role} instance is None",
            "[MultiAgentOrchestrator] 注册失败：{role} 实例为空",
        ),
        (
            "orch.magent.debug.workflow_paused",
            "[MultiAgentOrchestrator] workflow paused → {wid}",
            "[MultiAgentOrchestrator] 工作流已暂停 → {wid}",
        ),
        (
            "orch.magent.debug.workflow_resumed",
            "[MultiAgentOrchestrator] workflow resumed → {wid}",
            "[MultiAgentOrchestrator] 工作流已恢复 → {wid}",
        ),
        (
            "orch.magent.debug.shutdown",
            "[MultiAgentOrchestrator] multi-agent orchestrator shut down",
            "[MultiAgentOrchestrator] 多代理编排器已关闭",
        ),
        # --- skill_factory (sfac.log) ---
        (
            "sfac.log.template_use",
            "[SkillFactory][TemplateBackend] using template for {name}",
            "[SkillFactory][TemplateBackend] 使用模板生成 {name}",
        ),
        (
            "sfac.log.anthropic_try",
            "[SkillFactory][AnthropicBackend] loading from Anthropic Skills: {name}",
            "[SkillFactory][AnthropicBackend] 尝试从 Anthropic Skills 加载: {name}",
        ),
        (
            "sfac.log.anthropic_ok",
            "[SkillFactory][AnthropicBackend] loaded Anthropic skill: {name}",
            "[SkillFactory][AnthropicBackend] 成功加载 Anthropic 技能: {name}",
        ),
        (
            "sfac.log.anthropic_fuzzy",
            "[SkillFactory][AnthropicBackend] fuzzy-matched Anthropic skill: {name}",
            "[SkillFactory][AnthropicBackend] 模糊匹配 Anthropic 技能: {name}",
        ),
        (
            "sfac.warn.anthropic_miss",
            "[SkillFactory][AnthropicBackend] no Anthropic match; falling through tiers",
            "[SkillFactory][AnthropicBackend] 未找到匹配的 Anthropic 技能，回退后续 Tier",
        ),
        (
            "sfac.log.llm_tier2",
            "[SkillFactory][LLMBackend][Tier2] generating via LLM: {name}",
            "[SkillFactory][LLMBackend][Tier2] 调用 LLM 生成 {name}",
        ),
        (
            "sfac.log.github_tier1_start",
            "[SkillFactory][GitHubBackend][Tier1] searching GitHub for: {name}",
            "[SkillFactory][GitHubBackend][Tier1] 开始搜索 GitHub 高星实现: {name}",
        ),
        (
            "sfac.warn.github_tier1_miss",
            "[SkillFactory][GitHubBackend][Tier1] no qualified code; fallback Tier2",
            "[SkillFactory][GitHubBackend][Tier1] 未找到合格高星代码，回退 Tier2",
        ),
        (
            "sfac.log.github_tier1_done",
            "[SkillFactory][GitHubBackend][Tier1] washed code ready → {name}",
            "[SkillFactory][GitHubBackend][Tier1] 高星代码洗髓完成 → {name}",
        ),
        (
            "sfac.log.naming_infer",
            "[SkillFactory][Naming] inferred skill name → {name}",
            "[SkillFactory][Naming] 从描述智能提取技能名称 → {name}",
        ),
        (
            "sfac.warn.naming_fallback",
            "[SkillFactory][Naming] could not infer; fallback → {name}",
            "[SkillFactory][Naming] 无法提取有效名称，使用兜底 → {name}",
        ),
        (
            "sfac.log.gen_start",
            "[SkillFactory] generating code; normalized name: {name}",
            "[SkillFactory] 开始生成代码，规范化后技能名称: {name}",
        ),
        (
            "sfac.log.github_timeout",
            "[SkillFactory][GracefulDegrade] default GitHub search timed out (1.5s); degrading",
            "[SkillFactory][GracefulDegrade] 默认 GitHub 搜索超时（1.5s），立即平滑降级",
        ),
        ("sfac.warn.github_exc", "[SkillFactory] GitHubBackend error: {e}", "[SkillFactory] GitHubBackend 异常: {e}"),
        (
            "sfac.log.tier_anthropic",
            "[SkillFactory] template empty; Tier1 Anthropic Skills",
            "[SkillFactory] Template 为空，进入 Tier 1 Anthropic Skills",
        ),
        (
            "sfac.log.tier_github",
            "[SkillFactory] Anthropic miss; Tier1 GitHub search",
            "[SkillFactory] Anthropic 未命中，进入 Tier 1 GitHub 高星搜索",
        ),
        (
            "sfac.log.github_tier1_timeout",
            "[SkillFactory][GracefulDegrade] Tier1 GitHub timed out (1.0s); Tier2 LLM",
            "[SkillFactory][GracefulDegrade] Tier 1 GitHub 搜索超时（1.0s），立即降级到 Tier 2 LLM 生成",
        ),
        (
            "sfac.warn.github_tier1_exc",
            "[SkillFactory][GracefulDegrade] Tier1 GitHub error (caught): {e}",
            "[SkillFactory][GracefulDegrade] Tier 1 GitHub 异常（已安全捕获）: {e}",
        ),
        (
            "sfac.log.tier2_llm",
            "[SkillFactory] Tier1 GitHub miss; Tier2 LLM",
            "[SkillFactory] Tier 1 GitHub 未命中，进入 Tier 2 LLM 生成",
        ),
        (
            "sfac.log.tier3",
            "[SkillFactory] Tier2 LLM failed; Tier3 history fallback",
            "[SkillFactory] Tier 2 LLM 也失败，进入 Tier 3 历史成功案例回退",
        ),
        (
            "sfac.log.tier3_from_history",
            "[SkillFactory][Tier3] code from history → {name}",
            "[SkillFactory][Tier3] 从历史成功技能提取代码 → {name}",
        ),
        (
            "sfac.err.all_tiers_fail",
            "[SkillFactory] all tiers failed; returning empty string",
            "[SkillFactory] 所有 Tier 均失败，返回空字符串",
        ),
        (
            "sfac.log.tdd_start",
            "[SkillFactory][TDD Post-Validate] async TDD for {name}",
            "[SkillFactory][TDD Post-Validate] 开始为 {name} 异步生成 TDD 用例",
        ),
        (
            "sfac.log.tdd_done",
            "[SkillFactory][TDD Post-Validate] {name} TDD async generation done",
            "[SkillFactory][TDD Post-Validate] {name} TDD 测试用例异步生成完成",
        ),
        (
            "sfac.warn.tdd_exc",
            "[SkillFactory][TDD Post-Validate] {name} background TDD error: {e}",
            "[SkillFactory][TDD Post-Validate] {name} 后台 TDD 生成异常: {e}",
        ),
        (
            "sfac.log.evo_trigger",
            "[SkillFactory][ActiveEvolution] triggering evolution for {name}",
            "[SkillFactory][ActiveEvolution] 主动触发 {name} 进化",
        ),
        (
            "sfac.warn.evo_no_optimizer",
            "[SkillFactory][ActiveEvolution] SkillOptimizer not injected",
            "[SkillFactory][ActiveEvolution] SkillOptimizer 未注入，无法主动优化",
        ),
        (
            "sfac.log.evo_scan",
            "[SkillFactory][ActiveEvolution] proactive evolution scan started",
            "[SkillFactory][ActiveEvolution] 主动进化扫描启动",
        ),
        (
            "sfac.warn.tier3_hist",
            "[SkillFactory][Tier3] history extraction error: {e}",
            "[SkillFactory][Tier3] 历史案例提取异常: {e}",
        ),
    ]

    for key, en_s, zh_s in pairs:
        en[key] = en_s
        zh[key] = zh_s

    return en, zh


_W24_EN0, _W24_ZH0 = build_wave24_blobs()
WAVE24_KEYS: tuple[str, ...] = tuple(sorted(_W24_EN0))
assert _W24_EN0.keys() == _W24_ZH0.keys(), "wave24 EN/ZH key sets must match"
