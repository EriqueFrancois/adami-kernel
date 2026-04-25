# -*- coding: utf-8 -*-
"""Wave-22 Step7 strings merged into locales/*/common.json."""

from __future__ import annotations

import json
from typing import Any


def build_wave22_blobs() -> tuple[dict[str, str], dict[str, str]]:
    en: dict[str, str] = {}
    zh: dict[str, str] = {}

    # --- skill_template_repository (stpl) ---
    en["stpl.match.weather_keywords_json"] = json.dumps(
        ["天气", "weather", "温度", "预报"], ensure_ascii=False
    )
    zh["stpl.match.weather_keywords_json"] = en["stpl.match.weather_keywords_json"]
    en["stpl.match.price_keywords_json"] = json.dumps(
        ["价格", "price", "多少钱", "报价", "数字货币", "crypto", "比特币", "以太坊", "索拉纳"],
        ensure_ascii=False,
    )
    zh["stpl.match.price_keywords_json"] = en["stpl.match.price_keywords_json"]
    en["stpl.log.match_weather"] = "[SkillTemplateRepository] matched weather template"
    zh["stpl.log.match_weather"] = "[SkillTemplateRepository] 匹配天气模板"
    en["stpl.log.match_price"] = "[SkillTemplateRepository] matched price template"
    zh["stpl.log.match_price"] = "[SkillTemplateRepository] 匹配价格模板"
    en["stpl.weather.err_no_city"] = "Please provide a city name."
    zh["stpl.weather.err_no_city"] = "请提供城市名"
    en["stpl.weather.err_congest"] = (
        "Weather source (wttr.in) is busy (HTTP {status_code}). Please try again later."
    )
    zh["stpl.weather.err_congest"] = (
        "天气数据源(wttr.in)当前拥堵（状态码 {status_code}），请稍后再试。"
    )
    en["stpl.weather.err_connect_timeout"] = (
        "Weather request timed out (ConnectTimeout). wttr.in can be unstable; "
        "try a global proxy or retry later."
    )
    zh["stpl.weather.err_connect_timeout"] = (
        "请求天气服务器超时（ConnectTimeout）。wttr.in 在国内访问不稳定，请开启全局代理或稍后重试。"
    )
    en["stpl.weather.err_net"] = "Network error: {exc_name}"
    zh["stpl.weather.err_net"] = "网络请求异常: {exc_name}"
    en["stpl.price.success"] = "💰 {coin} current price: ${amount} USD"
    zh["stpl.price.success"] = "💰 {coin} 当前价格: ${amount} USD"
    en["stpl.price.err_fetch"] = "Could not fetch price for {coin_id} (HTTP {status_code})."
    zh["stpl.price.err_fetch"] = "无法获取 {coin_id} 价格（API 返回状态 {status_code}）"
    en["stpl.price.err_timeout"] = "Request timed out. Check your network."
    zh["stpl.price.err_timeout"] = "请求服务器超时，请检查网络环境。"
    en["stpl.price.err_net"] = "Network error: {err}"
    zh["stpl.price.err_net"] = "网络请求异常: {err}"

    # --- skill_optimizer (sopt) ---
    _sopt_reason_en = {
        "sopt.reason.instinct_skip": "Instinct skill; optimization skipped",
        "sopt.reason.invalid_name": "Invalid skill name",
        "sopt.reason.no_errors": "No historical errors",
        "sopt.reason.gen_failed": "Code generation failed",
        "sopt.reason.tdd_failed": "TDD validation did not pass",
        "sopt.reason.not_better": "New version not significantly better than old",
        "sopt.reason.register_failed": "Registration failed",
    }
    _sopt_reason_zh = {
        "sopt.reason.instinct_skip": "本能技能，跳过优化",
        "sopt.reason.invalid_name": "非法技能名",
        "sopt.reason.no_errors": "无历史错误",
        "sopt.reason.gen_failed": "代码生成失败",
        "sopt.reason.tdd_failed": "TDD 验证未通过",
        "sopt.reason.not_better": "新版本未显著优于旧版本",
        "sopt.reason.register_failed": "注册失败",
    }
    en.update(_sopt_reason_en)
    zh.update(_sopt_reason_zh)
    en["sopt.prompt.optimize_wrap"] = (
        "Skill name: {skill_name}\nHistorical errors:\n{errors}\n\n"
        "Generate an improved version that fixes the issues above. "
        "Use async def execute, return a dict with status and data/error."
    )
    zh["sopt.prompt.optimize_wrap"] = (
        "技能名称：{skill_name}\n历史错误记录：\n{errors}\n\n"
        "请生成修复上述问题的改进版本代码。确保代码符合技能规范（async def execute），"
        "返回 dict，包含 status 和 data/error。"
    )
    en["sopt.desc.register_fmt"] = "Optimized {new_version}; fixes: {errors_preview}"
    zh["sopt.desc.register_fmt"] = "优化版本 {new_version}，修复历史错误：{errors_preview}"
    en["sopt.log.selftest_missing"] = (
        "[SkillOptimizer] SelfTestRunner not injected; using placeholder (TDD real run skipped)"
    )
    zh["sopt.log.selftest_missing"] = (
        "[SkillOptimizer] SelfTestRunner 未注入，将使用占位逻辑（TDD 将跳过真实执行）"
    )
    en["sopt.log.instinct_skip"] = "[SkillOptimizer][Instinct] skip instinct {skill_name} (solidified)"
    zh["sopt.log.instinct_skip"] = "[SkillOptimizer][Instinct] 跳过本能技能 {skill_name}（已固化，无需优化）"
    en["sopt.log.bad_name"] = "[SkillOptimizer] invalid skill name '{skill_name}', skip"
    zh["sopt.log.bad_name"] = "[SkillOptimizer] 技能名 '{skill_name}' 不合法，跳过优化"
    en["sopt.log.start"] = "[SkillOptimizer][UnifiedIntent] optimizing {skill_name}"
    zh["sopt.log.start"] = "[SkillOptimizer][UnifiedIntent] 开始优化技能: {skill_name}"
    en["sopt.log.no_errors"] = "[SkillOptimizer][UnifiedIntent] {skill_name} has no errors, skip"
    zh["sopt.log.no_errors"] = "[SkillOptimizer][UnifiedIntent] 技能 {skill_name} 无历史错误，无需优化"
    en["sopt.log.gen_retry"] = "[SkillOptimizer][UnifiedIntent] code gen failed attempt {attempt}, retry..."
    zh["sopt.log.gen_retry"] = "[SkillOptimizer][UnifiedIntent] 第 {attempt} 次代码生成失败，重试..."
    en["sopt.log.gen_fail"] = "[SkillOptimizer][UnifiedIntent] code gen failed: {skill_name}"
    zh["sopt.log.gen_fail"] = "[SkillOptimizer][UnifiedIntent] 生成新版本代码失败: {skill_name}"
    en["sopt.log.tdd_gen"] = "[SkillOptimizer][TDD Generate] generating TDD for {skill_name}"
    zh["sopt.log.tdd_gen"] = "[SkillOptimizer][TDD Generate] 开始为 {skill_name} 生成 TDD 测试用例"
    en["sopt.log.tdd_reject"] = "[SkillOptimizer][TDD Verify] {skill_name} TDD failed, reject"
    zh["sopt.log.tdd_reject"] = "[SkillOptimizer][TDD Verify] {skill_name} TDD 验证失败，拒绝替换"
    en["sopt.log.tdd_ok"] = "[SkillOptimizer][TDD Verify] {skill_name} TDD passed"
    zh["sopt.log.tdd_ok"] = "[SkillOptimizer][TDD Verify] {skill_name} TDD 验证通过"
    en["sopt.log.score_cmp"] = (
        "[SkillOptimizer][Decision] new score {new_score:.1f} | old score {old_score:.1f}"
    )
    zh["sopt.log.score_cmp"] = (
        "[SkillOptimizer][Decision] 新版本得分 {new_score:.1f} | 旧版本得分 {old_score:.1f}"
    )
    en["sopt.log.keep_old"] = (
        "[SkillOptimizer][Decision] new not better (<= +5); keep old, mark protected"
    )
    zh["sopt.log.keep_old"] = (
        "[SkillOptimizer][Decision] 新版本未显著优于旧版本（≤ +5分），保留旧版本并标记 protected"
    )
    en["sopt.log.replace"] = "[SkillOptimizer][Decision] new significantly better → replace"
    zh["sopt.log.replace"] = "[SkillOptimizer][Decision] 新版本显著优于旧版本 → 执行替换"
    en["sopt.log.reg_retry"] = "[SkillOptimizer][UnifiedIntent] register attempt {attempt} failed, retry..."
    zh["sopt.log.reg_retry"] = "[SkillOptimizer][UnifiedIntent] 第 {attempt} 次注册失败，重试..."
    en["sopt.log.reg_fail"] = "[SkillOptimizer][UnifiedIntent] register failed: {feedback}"
    zh["sopt.log.reg_fail"] = "[SkillOptimizer][UnifiedIntent] 新版本注册失败: {feedback}"
    en["sopt.log.done"] = "[SkillOptimizer][UnifiedIntent] {skill_name} optimized, {new_version} registered"
    zh["sopt.log.done"] = "[SkillOptimizer][UnifiedIntent] 技能 {skill_name} 优化成功，新版本 {new_version} 已注册"
    en["sopt.log.missing_file"] = "[SkillOptimizer] skill file {skill_name}.py missing, cannot diff"
    zh["sopt.log.missing_file"] = "[SkillOptimizer] 技能文件 {skill_name}.py 不存在，无法进行新旧对比"
    en["sopt.log.read_old_fail"] = "[SkillOptimizer] read old code failed: {err}"
    zh["sopt.log.read_old_fail"] = "[SkillOptimizer] 读取旧代码失败: {err}"
    en["sopt.log.protected"] = "[SkillOptimizer][Protected] {skill_name} marked protected"
    zh["sopt.log.protected"] = "[SkillOptimizer][Protected] 技能 {skill_name} 已标记为 protected（保守策略）"
    en["sopt.log.tdd_runner_none"] = "[SkillOptimizer][TDD] SelfTestRunner not injected, placeholder"
    zh["sopt.log.tdd_runner_none"] = "[SkillOptimizer][TDD] SelfTestRunner 未注入，使用占位逻辑"
    en["sopt.log.tdd_saved"] = "[SkillOptimizer][TDD Real Execute] saved {path}, running pytest"
    zh["sopt.log.tdd_saved"] = "[SkillOptimizer][TDD Real Execute] 已保存测试文件 {path}，开始真实 pytest 执行"
    en["sopt.log.tdd_result"] = "[SkillOptimizer][TDD Real Execute] {skill_name} done: {result}"
    zh["sopt.log.tdd_result"] = "[SkillOptimizer][TDD Real Execute] {skill_name} 测试执行完成，结果: {result}"
    en["sopt.log.tdd_exec_fail"] = "[SkillOptimizer][TDD Real Execute] run failed: {err}"
    zh["sopt.log.tdd_exec_fail"] = "[SkillOptimizer][TDD Real Execute] 执行测试失败: {err}"
    en["sopt.log.tier1"] = "[SkillOptimizer][Tier1] SkillFactory for {skill_name} (GitHub + wash)"
    zh["sopt.log.tier1"] = "[SkillOptimizer][Tier1] 使用 SkillFactory 生成 {skill_name}（GitHub 高星 + 洗髓优先）"
    en["sopt.log.empty_code"] = "[SkillOptimizer] SkillFactory returned empty code"
    zh["sopt.log.empty_code"] = "[SkillOptimizer] SkillFactory 返回空代码"
    en["sopt.log.no_builder"] = "[SkillOptimizer] evolution_engine has no skill_builder"
    zh["sopt.log.no_builder"] = "[SkillOptimizer] evolution_engine 没有 skill_builder，无法构建技能"
    en["sopt.log.build_fail"] = "[SkillOptimizer] build failed: {detail}"
    zh["sopt.log.build_fail"] = "[SkillOptimizer] 构建失败: {detail}"
    en["sopt.log.gen_exc"] = "[SkillOptimizer][UnifiedIntent] code gen exception: {err}"
    zh["sopt.log.gen_exc"] = "[SkillOptimizer][UnifiedIntent] 代码生成异常: {err}"
    en["sopt.log.deprecated"] = "[SkillOptimizer][UnifiedIntent] {skill_name} marked deprecated"
    zh["sopt.log.deprecated"] = "[SkillOptimizer][UnifiedIntent] 技能 {skill_name} 已标记为 deprecated"
    en["sopt.log.deprecate_fail"] = "[SkillOptimizer][UnifiedIntent] mark deprecated failed: {err}"
    zh["sopt.log.deprecate_fail"] = "[SkillOptimizer][UnifiedIntent] 标记 deprecated 失败: {err}"
    en["sopt.tdd.passed"] = "passed"
    zh["sopt.tdd.passed"] = "通过"
    en["sopt.tdd.failed"] = "failed"
    zh["sopt.tdd.failed"] = "失败"

    # --- run_trainer (rtrn) ---
    en["rtrn.stderr.agl_missing"] = (
        "agentlightning is not installed; run: poetry install -E training\nImportError: {err}\n"
    )
    zh["rtrn.stderr.agl_missing"] = (
        "agentlightning 未安装；请执行: poetry install -E training\nImportError: {err}\n"
    )
    en["rtrn.cli.description"] = "AdamI × Agent Lightning training CLI"
    zh["rtrn.cli.description"] = "AdamI × Agent Lightning 训练 CLI"
    en["rtrn.cli.help.experience_dir"] = (
        "ExperienceAggregator root (recursive episodes.jsonl); prefill for Baseline"
    )
    zh["rtrn.cli.help.experience_dir"] = (
        "ExperienceAggregator 根目录（递归查找 episodes.jsonl）；供 Baseline 预填队列"
    )
    en["rtrn.cli.help.output_dir"] = "Output directory for manifest + templates"
    zh["rtrn.cli.help.output_dir"] = "manifest + 模板输出目录"
    en["rtrn.cli.help.limit"] = "Max episodes to load"
    zh["rtrn.cli.help.limit"] = "最多加载的 episode 条数"
    en["rtrn.cli.help.mode"] = "Trainer.fit or Trainer.dev"
    zh["rtrn.cli.help.mode"] = "Trainer.fit 或 Trainer.dev"
    en["rtrn.cli.help.execution_strategy"] = (
        "Default client_server (multi-process); use shared_memory for single-process / pytest"
    )
    zh["rtrn.cli.help.execution_strategy"] = (
        "默认 client_server（多进程）；单进程验收或 pytest 可用 shared_memory"
    )
    en["rtrn.cli.help.tracer"] = (
        "dummy: no backend tracing for local runs; default agentops matches Agent Lightning tutorials"
    )
    zh["rtrn.cli.help.tracer"] = (
        "dummy：无后端追踪，适合本地验收；默认 agentops 与 Agent Lightning 教程一致"
    )
    en["rtrn.cli.help.rsync_dest"] = "If set, run rsync -a output-dir/ to this target after training"
    zh["rtrn.cli.help.rsync_dest"] = "若设置，则在结束后执行 rsync -a output-dir/ 到该目标"
    en["rtrn.cli.help.dry_run"] = "Validate JSONL and write PolicyManifest only (no Trainer, no agentlightning)"
    zh["rtrn.cli.help.dry_run"] = "仅校验 JSONL 并写出 PolicyManifest（不启动 Trainer，不依赖 agentlightning）"

    # --- skill_washer (swsh) ---
    en["swsh.log.validation_fail"] = "[SkillWasher] post-wash validation failed: {detail}"
    zh["swsh.log.validation_fail"] = "[SkillWasher] 洗髓后验证失败: {detail}"
    en["swsh.log.done"] = "[SkillWasher] {skill_name} washed (dangerous calls removed, async+retry injected)"
    zh["swsh.log.done"] = "[SkillWasher] 技能 {skill_name} 洗髓完成（危险调用已移除，async + 重试已注入）"
    en["swsh.log.replaced_call"] = "[SkillWasher] dangerous call replaced: {call_str}"
    zh["swsh.log.replaced_call"] = "[SkillWasher] 检测到危险调用，已替换: {call_str}"
    en["swsh.runtime.danger_removed"] = "Dangerous call removed by SkillWasher"
    zh["swsh.runtime.danger_removed"] = "危险调用已被洗髓引擎移除"
    en["swsh.fallback.replace_kw"] = "# [WASHED] dangerous call {kw} removed"
    zh["swsh.fallback.replace_kw"] = "# [WASHED] 危险调用 {kw} 已被移除"
    en["swsh.ast_fallback"] = "[SkillWasher] AST wash failed, string fallback: {err}"
    zh["swsh.ast_fallback"] = "[SkillWasher] AST 清洗失败，回退字符串替换: {err}"
    en["swsh.min.doc_main"] = "Standard entry after wash"
    zh["swsh.min.doc_main"] = "洗髓后标准技能入口"
    en["swsh.min.comment.full_file"] = (
        "# [FULL SKILL FILE] minimal safe fallback after wash failure; ready to run."
    )
    zh["swsh.min.comment.full_file"] = "# 【完整技能文件标记】此模板为洗髓失败时的最小安全兜底，已包含完整 execute 函数"
    en["swsh.min.comment.no_rewrap"] = "# Receivers may use this file as-is without re-wrapping."
    zh["swsh.min.comment.no_rewrap"] = "# 任何接收方均可直接作为完整技能使用，无需再次包装。"
    en["swsh.min.doc_fallback"] = "Minimal safe fallback template after wash failure"
    zh["swsh.min.doc_fallback"] = "洗髓失败安全兜底模板"
    en["swsh.min.log_exec"] = "minimal fallback template execute {skill_name}"
    zh["swsh.min.log_exec"] = "使用洗髓兜底模板执行 {skill_name}"
    en["swsh.min.return_msg"] = "Skill loaded safely (wash fallback)"
    zh["swsh.min.return_msg"] = "技能已安全加载（洗髓兜底）"
    en["swsh.min.log_exc_prefix"] = "fallback template exception: "
    zh["swsh.min.log_exc_prefix"] = "兜底模板执行异常: "

    # --- tools_manager (tlsm) ---
    en["tlsm.err.no_router"] = "Error: Router not injected; cannot summarize"
    zh["tlsm.err.no_router"] = "Error: Router 未注入，无法进行总结"
    en["tlsm.prompt.analyze_raw"] = (
        "You are a professional document analyst. Summarize the following content in clear structured prose "
        "(do not create skills; do not return JSON actions):\n"
        "1. Purpose and document type\n"
        "2. Key facts (names, dates, amounts, clauses)\n"
        "3. Goals and practical recommendations\n\n"
        "Source:\n{raw_excerpt}"
    )
    zh["tlsm.prompt.analyze_raw"] = (
        "你是一位专业文档分析师。请直接用自然流畅的中文对以下文件内容进行**结构化总结**"
        "（不要创建任何技能，不要返回JSON动作）：\n"
        "1. 文件用途和类型\n"
        "2. 关键信息提炼（人名、日期、金额、条款、重点内容）\n"
        "3. 核心目的和实用建议\n\n"
        "原始内容：\n{raw_excerpt}"
    )
    en["tlsm.voice.default_fail"] = "Voice recognition failed"
    zh["tlsm.voice.default_fail"] = "语音识别失败"
    en["tlsm.voice.exc"] = "Voice-to-text failed: {detail}"
    zh["tlsm.voice.exc"] = "语音转文本失败: {detail}"
    en["tlsm.image.default_fail"] = "Image analysis failed"
    zh["tlsm.image.default_fail"] = "图像分析失败"
    en["tlsm.image.exc"] = (
        "Image analysis failed: {detail}\nDescribe the image in words and I will help analyze."
    )
    zh["tlsm.image.exc"] = (
        "图像分析失败: {detail}\n请直接描述图片内容，我来帮你分析。"
    )
    en["tlsm.file.default_fail"] = "File parsing failed"
    zh["tlsm.file.default_fail"] = "文件解析失败"
    en["tlsm.file.exc"] = (
        "File parsing failed: {detail}\nPaste the text from the file and I will extract key information."
    )
    zh["tlsm.file.exc"] = (
        "文件解析失败: {detail}\n请复制文件中的文字给我，我来帮你提取关键信息。"
    )

    # --- agent_models Field descriptions (agmd) ---
    _agmd_en: dict[str, str] = {
        "agmd.field.trace_id": "Globally unique trace id for idempotency and log correlation",
        "agmd.field.source_agent": "Sender agent role",
        "agmd.field.target_agent": "Receiver agent role",
        "agmd.field.message_type": "Message type: task, result, feedback, pause, resume, error",
        "agmd.field.payload": "Task payload (Researcher summary, Engineer code, etc.)",
        "agmd.field.workflow_id": "Linked WorkflowState id",
        "agmd.field.chat_id": "Multi-tenant isolation key (required)",
        "agmd.field.timestamp": "Message creation time (UTC)",
        "agmd.field.version": "Protocol version for future upgrades",
    }
    _agmd_zh: dict[str, str] = {
        "agmd.field.trace_id": "全局唯一追踪ID，用于幂等与日志关联",
        "agmd.field.source_agent": "发送方代理角色",
        "agmd.field.target_agent": "接收方代理角色",
        "agmd.field.message_type": "消息类型：任务下发、结果返回、审计反馈、暂停/恢复、错误",
        "agmd.field.payload": "具体任务数据（Researcher 输出 summary、Engineer 输出 code 等）",
        "agmd.field.workflow_id": "关联的 WorkflowState ID",
        "agmd.field.chat_id": "多用户并发隔离键（必须携带）",
        "agmd.field.timestamp": "消息创建时间（UTC）",
        "agmd.field.version": "消息协议版本，便于未来升级",
    }
    en.update(_agmd_en)
    zh.update(_agmd_zh)

    # --- episodic_memory (epis) ---
    en["epis.log.chroma_missing"] = "[EpisodicMemory] chromadb missing; long-term memory inactive. pip install chromadb"
    zh["epis.log.chroma_missing"] = (
        "⚠️ [EpisodicMemory] 缺少 chromadb 库，长期记忆无法激活。请执行 pip install chromadb"
    )
    en["epis.log.init_fail"] = "[EpisodicMemory] vector DB init failed: {err}"
    zh["epis.log.init_fail"] = "❌ [EpisodicMemory] 向量数据库初始化失败: {err}"
    en["epis.doc.save"] = (
        "Task: {task}\nAttempted action: {action}\nBad code or args:\n{bad_code}\nSystem error:\n{error_msg}\n"
        "Conclusion: blocked path; change approach or fix the code."
    )
    zh["epis.doc.save"] = (
        "任务目标: {task}\n尝试动作: {action}\n错误代码或参数:\n{bad_code}\n系统报错:\n{error_msg}\n"
        "反思结论: 此路不通，必须更换实现方式或修正代码错误。"
    )
    en["epis.query.recall"] = "Task: {current_task} Action: {current_action}"
    zh["epis.query.recall"] = "任务目标: {current_task} 尝试动作: {current_action}"
    en["epis.recall.header"] = (
        "【Subconscious error recall (learn from history; do not repeat mistakes)】:\n"
    )
    zh["epis.recall.header"] = "【🧠 潜意识错题本回忆 (请务必吸取以下历史教训，绝不重蹈覆辙)】：\n"
    en["epis.recall.item"] = "--- Lesson {idx} ---\n{doc}\n"
    zh["epis.recall.item"] = "--- 历史教训 {idx} ---\n{doc}\n"
    en["epis.log.saved"] = "[EpisodicMemory] saved error lesson (action={action})"
    zh["epis.log.saved"] = "💾 [EpisodicMemory] 一条惨痛的教训已写入错题本 (Action: {action})"
    en["epis.log.save_fail"] = "[EpisodicMemory] save to logbook failed: {err}"
    zh["epis.log.save_fail"] = "写入错题本失败: {err}"
    en["epis.log.recall_ok"] = "[EpisodicMemory] recalled {n} related memories"
    zh["epis.log.recall_ok"] = "✨ [EpisodicMemory] 成功唤醒 {n} 条相关的历史记忆！"
    en["epis.log.recall_fail"] = "[EpisodicMemory] recall failed: {err}"
    zh["epis.log.recall_fail"] = "回忆错题本失败: {err}"

    # --- skill_tdd_generator (stdd) ---
    en["stdd.log.start"] = "[SkillTDDGenerator][Background] generating TDD for {skill_name} (async)"
    zh["stdd.log.start"] = "[SkillTDDGenerator][Background] 开始为 {skill_name} 生成 TDD 测试用例（异步任务）"
    en["stdd.prompt.body"] = (
        "You are a strict TDD engineer. Generate a complete runnable pytest file for this AdamI skill.\n\n"
        "Skill: {skill_name}\nDescription: {description}\nCode:\n{code}\n\n"
        "Requirements:\n"
        "1. pytest + asyncio (async def test_)\n"
        "2. At least 6 tests (happy path, edge, error, mock external APIs)\n"
        "3. Mock httpx/requests with pytest-mock or unittest.mock\n"
        "4. Use fixtures for mocks\n"
        "5. Filename style test_{{skill_lower}}.py (return code only)\n"
        "6. End with if __name__ == '__main__': pytest.main()\n"
        "7. Output Python code only, no prose\n\n"
        "Return only the test file content."
    )
    zh["stdd.prompt.body"] = (
        "你是一个严格的 TDD 测试工程师。\n请为以下 AdamI 技能生成完整、可直接运行的 pytest 测试用例。\n\n"
        "技能名称：{skill_name}\n技能描述：{description}\n技能代码：\n{code}\n\n"
        "要求：\n"
        "1. 使用 pytest + asyncio（async def test_）\n"
        "2. 必须包含至少 6 个测试用例（正常、边界、异常、Mock API）\n"
        "3. 对所有外部 API 调用（httpx、requests 等）使用 pytest-mock 或 unittest.mock\n"
        "4. 使用 pytest fixtures 管理 Mock\n"
        "5. 测试文件必须以 test_{{skill_lower}}.py 风格命名（但只返回代码内容）\n"
        "6. 最后必须包含 if __name__ == \"__main__\": pytest.main()\n"
        "7. 输出仅返回完整 Python 代码，不要任何解释\n\n"
        "请严格输出可直接保存运行的测试文件内容。"
    )
    en["stdd.log.too_short"] = "[SkillTDDGenerator][Background] output too short; minimal template → {skill_name}"
    zh["stdd.log.too_short"] = (
        "[SkillTDDGenerator][Background] 生成的测试用例过短或为空，使用最小安全模板 → {skill_name}"
    )
    en["stdd.log.ok"] = "[SkillTDDGenerator][Background] generated TDD for {skill_name} ({n} chars)"
    zh["stdd.log.ok"] = "[SkillTDDGenerator][Background] 已成功生成 {skill_name} 的 TDD 测试用例（长度 {n} 字符）"
    en["stdd.log.fail"] = "[SkillTDDGenerator][Background] generate failed: {err} → minimal template"
    zh["stdd.log.fail"] = "[SkillTDDGenerator][Background] 生成测试用例失败: {err} → 使用最小安全模板"
    en["stdd.min.doc_execute"] = "Original skill code (fallback)"
    zh["stdd.min.doc_execute"] = "原始技能代码（兜底）"
    en["stdd.min.doc_basic"] = "Basic functionality test"
    zh["stdd.min.doc_basic"] = "基本功能测试"
    en["stdd.min.doc_error"] = "Error handling test"
    zh["stdd.min.doc_error"] = "异常处理测试"

    # --- circadian_nerve (circ) ---
    en["circ.last30.task"] = (
        "【last30days {digest_kind}】{date} topic: {topic}\n"
        "You MUST call native skill LAST30DAYS_DIGEST to write SecondBrain (do not replace with web search).\n"
        "Call with these args, then TASK_COMPLETE immediately:\n"
        '- action: "LAST30DAYS_DIGEST"\n'
        '- args: {args_json}\n'
    )
    zh["circ.last30.task"] = (
        "【last30days {digest_kind}】{date} 主题：{topic}\n"
        "你必须调用原生技能 LAST30DAYS_DIGEST 写入 SecondBrain（不要做网页搜索替代）。\n"
        "严格按以下参数调用，并在返回后立刻执行 TASK_COMPLETE 结束：\n"
        '- action: "LAST30DAYS_DIGEST"\n'
        "- args: {args_json}\n"
    )
    en["circ.morning.prefix.test"] = "[Self-test]"
    zh["circ.morning.prefix.test"] = "【测试自检】"
    en["circ.morning.prefix.daily"] = "[Daily standup]"
    zh["circ.morning.prefix.daily"] = "【每日晨会】"
    en["circ.morning.console"] = "\n[bold magenta]🌅 {prefix} starting...[/bold magenta]"
    zh["circ.morning.console"] = "\n[bold magenta]🌅 {prefix} 触发中...[/bold magenta]"
    en["circ.morning.task"] = (
        "{prefix} digest {date}\n"
        "[Rules] Act as a senior analyst and produce one aggregated morning brief in three steps:\n"
        "1. Gather: major global news (skip obituaries and trivia).\n"
        "2. Market: use WEB_SEARCH or a legal skill for latest BTC price.\n"
        "3. Send: do NOT spam. After all inputs, write one long analytical brief and send Telegram once.\n"
        "After a successful send, immediately TASK_COMPLETE."
    )
    zh["circ.morning.task"] = (
        "{prefix} 日报任务 - {date}\n"
        "【最高原则】：你必须作为一名高级分析师，通过以下三步完成一份‘聚合’早报：\n"
        "1. 搜集信息：搜索全球重大新闻（过滤掉讣告或琐事）。\n"
        "2. 获取行情：使用 WEB_SEARCH 或其他合法技能获取 BTC 最新价格。\n"
        "3. 🚨 聚合发送：禁止分散发消息。你必须在获取完所有素材后，编写一篇包含分析评论的长文早报，一次性发送 Telegram 汇报成果。\n"
        "汇报发送成功后，必须立即执行 TASK_COMPLETE 结束思考流！"
    )
    en["circ.publish.fail_console"] = "[bold red]❌ trigger failed: {err}[/bold red]"
    zh["circ.publish.fail_console"] = "[bold red]❌ 触发失败: {err}[/bold red]"
    en["circ.gc.dir_fail"] = "[CircadianNerve] GC clean {dir_path} failed: {err}"
    zh["circ.gc.dir_fail"] = "[CircadianNerve] GC 清理 {dir_path} 失败: {err}"
    en["circ.gc.done"] = "[CircadianNerve] deep GC freed {n} files"
    zh["circ.gc.done"] = "🧹 [CircadianNerve] 深度垃圾回收完成，共清理 {n} 个冗余残骸。"
    en["circ.gc.nothing"] = "[CircadianNerve] deep GC done, nothing to remove"
    zh["circ.gc.nothing"] = "[CircadianNerve] 深度垃圾回收完成，无需清理"
    en["circ.tick.error"] = "[CircadianNerve] circadian loop error: {err}"
    zh["circ.tick.error"] = "[CircadianNerve] 生物钟内部异常: {err}"

    # --- dream_sandbox (drsb) ---
    en["drsb.log.docker_attempt"] = "[DreamSandbox][DockerDebug] connect attempt {attempt}/5 failed: {err}"
    zh["drsb.log.docker_attempt"] = "[DreamSandbox][DockerDebug] 第 {attempt}/5 次连接失败: {err}"
    en["drsb.log.docker_desktop"] = "[DreamSandbox][DockerDebug] Docker Desktop not ready → trying open -a Docker"
    zh["drsb.log.docker_desktop"] = "[DreamSandbox][DockerDebug] macOS Docker Desktop 未就绪 → 尝试自动启动"
    en["drsb.log.docker_giveup"] = "[DreamSandbox][BugFix] Docker failed 5 times → fallback mode without container"
    zh["drsb.log.docker_giveup"] = "[DreamSandbox][BugFix] Docker 连续 5 次初始化失败 → 启用无容器 Fallback 模式"
    en["drsb.log.fallback_enter"] = "[DreamSandbox][BugFix] Docker unavailable → host fallback mode"
    zh["drsb.log.fallback_enter"] = "[DreamSandbox][BugFix] Docker 不可用 → 进入无容器 Fallback 模式"
    en["drsb.log.net_precheck"] = "[DreamSandbox][NetworkPrecheck] container network precheck failed"
    zh["drsb.log.net_precheck"] = "[DreamSandbox][NetworkPrecheck] 容器网络连通性预检失败"
    en["drsb.err.cmd_timeout"] = "Command timed out ({timeout}s)"
    zh["drsb.err.cmd_timeout"] = "命令执行超时（{timeout}秒）"
    en["drsb.log.container_rm_fail"] = "[DreamSandbox] container remove failed: {err}"
    zh["drsb.log.container_rm_fail"] = "[DreamSandbox] 容器移除失败: {err}"
    en["drsb.log.net_error"] = "[DreamSandbox][NetworkError] sandbox network issue (bridge + dummy keys): {err}"
    zh["drsb.log.net_error"] = "[DreamSandbox][NetworkError] 沙箱网络异常（bridge 隔离 + Dummy Key 已生效）: {err}"
    en["drsb.err.net_user"] = "Sandbox network request failed (bridge + dummy keys): {err}"
    zh["drsb.err.net_user"] = "沙箱网络请求失败（bridge 隔离 + Dummy Key 已注入）：{err}"
    en["drsb.suggest.docker"] = "1. Ensure Docker Desktop is running"
    zh["drsb.suggest.docker"] = "1. 确认 Docker Desktop 已开启并运行"
    en["drsb.suggest.net"] = "2. Check host network (VPN/proxy may interfere)"
    zh["drsb.suggest.net"] = "2. 检查宿主机网络是否正常（VPN/代理可能干扰）"
    en["drsb.suggest.localhost"] = "3. Container cannot reach host-local services (127.0.0.1)"
    zh["drsb.suggest.localhost"] = "3. 容器已无法访问宿主机本地服务（127.0.0.1）"
    en["drsb.log.cmd_exc"] = "[DreamSandbox][DockerDebug] sandbox command exception: {err}"
    zh["drsb.log.cmd_exc"] = "[DreamSandbox][DockerDebug] 沙箱命令执行异常: {err}"
    en["drsb.err.fallback_python_only"] = "Fallback mode allows python commands only"
    zh["drsb.err.fallback_python_only"] = "Fallback 模式仅允许 python 命令"
    en["drsb.err.fallback_timeout"] = "Fallback execution timed out"
    zh["drsb.err.fallback_timeout"] = "Fallback 执行超时"
    en["drsb.log.fallback_exc"] = "[DreamSandbox][FallbackDebug] fallback exception: {err}"
    zh["drsb.log.fallback_exc"] = "[DreamSandbox][FallbackDebug] Fallback 执行异常: {err}"
    en["drsb.log.cleanup"] = "[DreamSandbox] sandbox resources cleaned"
    zh["drsb.log.cleanup"] = "[DreamSandbox] 沙箱资源已清理"

    return en, zh


_W22_EN0, _W22_ZH0 = build_wave22_blobs()
WAVE22_KEYS: tuple[str, ...] = tuple(sorted(_W22_EN0))
assert _W22_EN0.keys() == _W22_ZH0.keys(), "wave22 EN/ZH key sets must match"
