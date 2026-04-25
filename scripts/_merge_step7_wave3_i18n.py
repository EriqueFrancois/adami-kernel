#!/usr/bin/env python3
"""Merge wave-3 i18n keys into locales/en and locales/zh-Hans common.json."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EN = REPO / "src/adami_kernel/i18n/locales/en/common.json"
ZH = REPO / "src/adami_kernel/i18n/locales/zh-Hans/common.json"

EN_PATCH: dict[str, str] = {
    "lc.persona.default": "You are AdamI, a highly autonomous evolving intelligent system.",
    "lc.cli.unknown_skill": "unknown skill",
    "lc.skill_created.weather_detail": "{city} weather {condition}, temperature {temperature}",
    "lc.skill_created.pass_with_tests": "✅ Skill **{skill_name}** created and tests passed!\nTest result: {test_result}",
    "lc.skill_created.pass_data_only": "✅ Skill **{skill_name}** created and tests passed!\nTest result: {test_result}",
    "lc.skill_created.pass_message": "✅ Skill **{skill_name}** created and tests passed!\nTest result: {test_result}",
    "lc.skill_created.pass_short": "✅ Skill **{skill_name}** created and tests passed!",
    "lc.skill_created.approved_only": "✅ Skill **{skill_name}** passed review!",
    "lc.skill_created.failed": "❌ Skill creation failed: {detail}",
    "lc.console.cli_reply": "[bold cyan]AdamI CLI reply:[/bold cyan] ",
    "lc.console.fallback_telegram": "[bold yellow]Fallback reply (telegram):[/bold yellow] ",
    "lc.console.fallback_discord": "[bold yellow]Fallback reply (discord):[/bold yellow] ",
    "lc.console.default_reply": "[bold cyan]Default reply:[/bold cyan] ",
    "lc.system_action.ok": "✅ System command executed",
    "lc.shutdown.line": "\n[bold red]AdamI shut down normally.[/bold red]",
    "wf.field.node_id": "Unique node ID",
    "wf.field.node_type": "Node type",
    "wf.field.node_config": "Node configuration (e.g. LLM prompt, tool name, condition expression)",
    "wf.field.node_timeout": "Per-node execution timeout in seconds (circuit breaker)",
    "wf.field.node_max_retries": "Max retries for this node",
    "wf.field.node_description": "Human-readable node description",
    "wf.field.workflow_id": "Unique workflow ID",
    "wf.field.chat_id": "Multi-tenant isolation key (same as the rest of the system)",
    "wf.field.status": "Current workflow status",
    "wf.field.current_node_id": "Currently executing node ID",
    "wf.field.nodes": "Node registry",
    "wf.field.edges": "Directed edge routing table (from_node_id -> [to_node_id, ...])",
    "wf.field.context": (
        "Shared workspace (blackboard; all nodes read/write). "
        "Module 4 controlled keys: current_phase (str), long_task_stages (list of StageArtifact dicts); "
        "use adami_kernel.orchestrator.long_task_schema to read/write and avoid polluting large objects."
    ),
    "wf.field.history": (
        "Execution history (idempotent audit). Module 4: includes structured phase events with "
        "event_type=phase_transition; see long_task_phase_gate.extract_phase_sequence_from_history."
    ),
    "wf.field.error_retry_counts": "Per-node failure retry counts",
    "wf.field.global_step_count": "Global step counter to prevent infinite loops",
    "wf.field.max_steps": "Global max steps cap",
    "wf.field.version": "State version (optimistic locking)",
    "wf.field.parent_workflow_id": "Parent workflow ID (nested workflows)",
    "wf.field.metadata": (
        "Extra metadata (custom tags). Module 4: long_task_tracking_enabled (bool) enables per-workflow phase tracking; "
        "long_task_schema_version (int) is written by long_task_schema.maybe_initialize_long_task_context."
    ),
    "wf.field.created_at": "Created at",
    "wf.field.last_updated": "Last updated at",
    "wf.create.start_description": "Workflow entry",
    "wfe.error.deerflow_node_disabled": (
        "Workflow contains DELEGATE_DEERFLOW node {node_id} but ADAMI_DEERFLOW_ENABLED is off; "
        "see docs/deer_flow_bridge_security.md."
    ),
    "wfe.error.deerflow_requires_flag": (
        "DELEGATE_DEERFLOW requires ADAMI_DEERFLOW_ENABLED=true; do not register this node type when disabled "
        "(see docs/deer_flow_bridge_security.md)."
    ),
    "wfe.error.max_steps": "Workflow exceeded max_steps={max_steps}",
    "wfe.msg.simple_node_passed": "{node_type} passed",
    "wfe.error.router_missing": "toolbox.router is not injected; cannot execute LLM node",
    "wfe.error.evolution_missing": "evolution_engine is not injected; cannot execute SKILL_CALL",
    "wfe.error.skill_build_failed": "Skill build failed: {detail}",
    "wfe.msg.skill_built_from_workflow": "Skill {skill_name} was built from the workflow",
    "wfe.error.skill_missing": "Skill {skill_name} does not exist",
    "wfe.error.invalid_condition": "Invalid condition: {condition_template}",
    "wfe.error.condition_no_next": "Condition node has no successor",
    "wfe.msg.node_done": "Node {node_id} finished",
    "wfe.error.node_failed": "Node {node_id} failed: {detail}",
    "wfe.error.workflow_cancelled": "Workflow cancelled workflow_id={workflow_id}",
    "sb.readme.heading_members": "## Members",
    "sb.readme.heading_duty": "## Responsibilities",
    "sb.seed.profile": "# Scenario preferences\n> User communication and execution preferences. Written by AI observation after user approval.\n\n",
    "sb.seed.operating_rules": "# Operating rules\n> System execution agreements confirmed by the user.\n\n",
    "sb.seed.candidates": (
        "# Preference candidate pool\n> New preferences observed by AI are written here silently; confirm via /digest.\n"
        "## Pending confirmation\n"
    ),
    "sb.seed.pending_approvals": (
        "# Approval queue\n> B/C change proposals are written here and must include rationale, risks, and rollback.\n"
        "## Pending approval\n"
    ),
    "sb.snippet.none": "(none)",
    "sb.search.truncation_suffix": "\n\n… (SecondBrain truncated)\n",
    "sb.err.para_invalid": "para must be one of {allowed}, got: {got!r}",
    "sb.err.path_unresolvable": "Cannot resolve path ({label}): {path}",
    "sb.err.path_escape": "{label} is not under the brain root: {path}",
    "sb.label.src_path": "source path",
    "sb.label.dest_dir": "destination directory",
    "sb.label.dest_file": "destination file",
    "sb.err.src_not_file": "Source path is not a file: {path}",
    "sb.err.dest_filename_invalid": "Invalid destination filename: {name!r}",
    "sb.readme.no_md_members": "- (no `.md` members yet)",
    "sb.readme.footer_auto": "\n## Members\n(maintained automatically)\n",
    "sb.readme.dir_default": "Directory description",
    "sb.tpl.telos": """# Identity framework (TELOS)
## Mission
- M0: Act as the user's digital twin and strategic advisor; amplify their intellectual output and never block execution.

## Goals
- G0: Build and maintain a minimally structured, maximally intelligent second brain.

## Beliefs
- B0: Weak structure, strong intelligence. Delegate as much judgment as possible to you (AI), not rigid code rules.
- B1: The user is the approver; you are the executor and proposer.

## Narrative
- N0: I am building a second-brain system with my owner on the AdamI architecture.
""",
    "sb.tpl.context": """# Recent context (CONTEXT)
- Current focus: refactoring and integration of the AdamI codebase.
- Recent pain points: multi-agent messaging and API rate limits.
""",
    "sb.readme.inbox": "Inbox for uncategorized items. When archiving, analyze content and move to the target path.",
    "sb.readme.projects": "Projects with clear goals and deadlines. Example: AdamI 2.0 refactor.",
    "sb.readme.areas": "Ongoing responsibility areas without an end date. Example: technical learning, health.",
    "sb.readme.resources": "Reusable references: snippets, methodologies, notes.",
    "sb.readme.archives": "Archive for completed or deprecated content to retain.",
    "sc.compose.no_skills": "(no skills available)",
    "sc.node.desc.invoke_skill": "Invoke skill {skill_name}",
    "sc.node.prompt.handle_task": "Please handle the following task: {task_description}",
    "sc.node.desc.llm": "LLM processing",
    "sc.node.desc.llm_final": "LLM processing (final fallback)",
    "sc.prompt.create_new_skill": """You are executing CREATE_NEW_SKILL.
Task: {task_description}

Output strictly in this format (no extra text):

{{
  "action": "CREATE_NEW_SKILL",
  "args": {{
    "skill_name": "SKILL_NAME",
    "description": "One-line description"
  }}
}}
```python
# Complete async Python skill code
async def execute(**kwargs) -> dict:
    ...
```
""",
    "sc.node.prompt.research": "Research the task requirements",
    "sc.node.desc.research": "Researcher research",
    "sc.node.prompt.engineer": "Generate skill code",
    "sc.node.desc.engineer": "Engineer code generation",
    "sc.node.desc.executor": "Executor run",
    "sc.node.prompt.critic": "Review the results",
    "sc.node.desc.critic": "Critic review",
    "sc.prompt.compose_workflow": """You are a workflow orchestration expert. Design an executable workflow from the task and available skills.

Task:
{task_description}

Available skills: {skills_block}

Return a JSON object describing workflow nodes and edges. Each node may be a skill call, LLM call, or condition branch.
Node types:
- SKILL_CALL: call an existing skill; specify skill_name and args (args may reference context).
- LLM_CALL: call an LLM; specify prompt (may reference context variables).
- CONDITION: branch on context values. Expressions must be valid Python only; comparisons/logic and $context.xxx references are allowed — no Chinese or natural language in conditions!

Output format:
{{
  "nodes": [
    {{
      "node_id": "node1",
      "node_type": "SKILL_CALL",
      "config": {{
        "skill_name": "NAME",
        "args": {{"param1": "$context.var1"}}
      }},
      "description": "description"
    }},
    {{
      "node_id": "node2",
      "node_type": "CONDITION",
      "config": {{
        "condition": "$context.node1.status == 'success'"
      }},
      "description": "Check whether the previous step succeeded"
    }},
    {{
      "node_id": "node3",
      "node_type": "LLM_CALL",
      "config": {{
        "prompt": "Analyze previous result: $context.node1.data"
      }},
      "description": "Analyze"
    }}
  ],
  "edges": {{
    "node1": ["node2"],
    "node2": ["node3"],
    "node3": []
  }}
}}

Notes:
- CONDITION nodes must include a \"condition\" field with a full Python expression, e.g. $context.node1.status == 'success'.
- Do not emit broken expressions starting with a comparator (e.g. == 'success').
- Do not use Chinese or natural language in conditions.
- The workflow must be a DAG.
- If the task is skill creation, prefer a creation flow that includes ENGINEER-style steps.
""",
    "sc.prompt.compose_retry": """The workflow you generated contained invalid CONDITION expressions (Chinese, natural language, or incomplete). Regenerate so every CONDITION config.condition is a valid Python expression with both operands, e.g. $context.node1.status == 'success'.

Task:
{task_description}
Available skills: {skills_block}

Output JSON only.
""",
}

ZH_PATCH: dict[str, str] = {
    "lc.persona.default": "你是 AdamI，一个拥有高度自主进化能力的智能生命。",
    "lc.cli.unknown_skill": "未知技能",
    "lc.skill_created.weather_detail": "{city}天气 {condition}，温度 {temperature}",
    "lc.skill_created.pass_with_tests": "✅ 技能 **{skill_name}** 已创建并测试通过！\n测试结果：{test_result}",
    "lc.skill_created.pass_data_only": "✅ 技能 **{skill_name}** 已创建并测试通过！\n测试结果：{test_result}",
    "lc.skill_created.pass_message": "✅ 技能 **{skill_name}** 已创建并测试通过！\n测试结果：{test_result}",
    "lc.skill_created.pass_short": "✅ 技能 **{skill_name}** 已创建并测试通过！",
    "lc.skill_created.approved_only": "✅ 技能 **{skill_name}** 已通过评审！",
    "lc.skill_created.failed": "❌ 技能创建失败：{detail}",
    "lc.console.cli_reply": "[bold cyan]AdamI CLI 回复:[/bold cyan] ",
    "lc.console.fallback_telegram": "[bold yellow]降级回复 (telegram):[/bold yellow] ",
    "lc.console.fallback_discord": "[bold yellow]降级回复 (discord):[/bold yellow] ",
    "lc.console.default_reply": "[bold cyan]默认回复:[/bold cyan] ",
    "lc.system_action.ok": "✅ 系统指令已执行",
    "lc.shutdown.line": "\n[bold red]AdamI 已正常下线。[/bold red]",
    "wf.field.node_id": "节点唯一ID",
    "wf.field.node_type": "节点类型",
    "wf.field.node_config": "节点配置（如 LLM prompt、工具名称、条件表达式等）",
    "wf.field.node_timeout": "单节点执行超时秒数（熔断保护）",
    "wf.field.node_max_retries": "节点级最大重试次数",
    "wf.field.node_description": "节点人类可读描述",
    "wf.field.workflow_id": "工作流唯一ID",
    "wf.field.chat_id": "多用户隔离键（与现有系统完全一致）",
    "wf.field.status": "当前工作流状态",
    "wf.field.current_node_id": "当前正在执行的节点ID",
    "wf.field.nodes": "节点注册表",
    "wf.field.edges": "有向边路由表（from_node_id -> [to_node_id, ...]）",
    "wf.field.context": (
        "共享工作区（黑板模式，所有节点可读写）。"
        "模块四受控键（长任务阶段）：current_phase（str）、long_task_stages（StageArtifact 字典列表）；"
        "请通过 adami_kernel.orchestrator.long_task_schema 读写以避免污染大对象。"
    ),
    "wf.field.history": (
        "执行历史（幂等、审计）。模块四：含 event_type=phase_transition 的结构化阶段事件，"
        "见 long_task_phase_gate.extract_phase_sequence_from_history。"
    ),
    "wf.field.error_retry_counts": "每个节点的失败重试计数",
    "wf.field.global_step_count": "全局步数计数，防止死循环",
    "wf.field.max_steps": "全局最大步数上限",
    "wf.field.version": "状态版本号（用于乐观锁）",
    "wf.field.parent_workflow_id": "父工作流ID（支持嵌套）",
    "wf.field.metadata": (
        "扩展元数据（可存储自定义标签）。模块四：long_task_tracking_enabled（bool）按工作流开启阶段跟踪；"
        "long_task_schema_version（int）由 long_task_schema.maybe_initialize_long_task_context 写入。"
    ),
    "wf.field.created_at": "创建时间",
    "wf.field.last_updated": "最后更新时间",
    "wf.create.start_description": "工作流入口",
    "wfe.error.deerflow_node_disabled": (
        "工作流包含 DELEGATE_DEERFLOW 节点 {node_id} 但未启用 ADAMI_DEERFLOW_ENABLED；"
        "见 docs/deer_flow_bridge_security.md。"
    ),
    "wfe.error.deerflow_requires_flag": (
        "DELEGATE_DEERFLOW 需要 ADAMI_DEERFLOW_ENABLED=true；未启用时请勿在工作流中注册该节点类型（见 docs/deer_flow_bridge_security.md）。"
    ),
    "wfe.error.max_steps": "工作流超过 max_steps={max_steps}",
    "wfe.msg.simple_node_passed": "{node_type} 已越过",
    "wfe.error.router_missing": "toolbox.router 未注入，无法执行 LLM 节点",
    "wfe.error.evolution_missing": "evolution_engine 未注入，无法执行 SKILL_CALL",
    "wfe.error.skill_build_failed": "技能构建失败: {detail}",
    "wfe.msg.skill_built_from_workflow": "技能 {skill_name} 已从工作流构建",
    "wfe.error.skill_missing": "技能 {skill_name} 不存在",
    "wfe.error.invalid_condition": "不合法条件: {condition_template}",
    "wfe.error.condition_no_next": "条件节点缺少后继",
    "wfe.msg.node_done": "节点 {node_id} 执行完成",
    "wfe.error.node_failed": "节点 {node_id} 失败: {detail}",
    "wfe.error.workflow_cancelled": "工作流已取消 workflow_id={workflow_id}",
    "sb.readme.heading_members": "## 成员清单",
    "sb.readme.heading_duty": "## 职责",
    "sb.seed.profile": "# 场景化偏好\n> 记录用户的沟通与执行偏好。由 AI 自动观察并经用户审批后写入。\n\n",
    "sb.seed.operating_rules": "# 操作性规则\n> 经用户确认的系统执行约定。\n\n",
    "sb.seed.candidates": (
        "# 偏好候选池\n> AI 观察到新偏好时静默写入此处，/digest 时确认。\n## 待确认\n"
    ),
    "sb.seed.pending_approvals": (
        "# 审批队列\n> B/C 类变更提案写入此处，须包含依据、风险与回滚方案。\n## 待审批\n"
    ),
    "sb.snippet.none": "（无）",
    "sb.search.truncation_suffix": "\n\n…（SecondBrain 截断）\n",
    "sb.err.para_invalid": "para 必须是 {allowed} 之一，得到: {got!r}",
    "sb.err.path_unresolvable": "无法解析路径 ({label}): {path}",
    "sb.err.path_escape": "{label} 不在 brain 根目录内: {path}",
    "sb.label.src_path": "源路径",
    "sb.label.dest_dir": "目标目录",
    "sb.label.dest_file": "目标文件",
    "sb.err.src_not_file": "源路径不是文件: {path}",
    "sb.err.dest_filename_invalid": "非法目标文件名: {name!r}",
    "sb.readme.no_md_members": "- （暂无 `.md` 成员）",
    "sb.readme.footer_auto": "\n## 成员清单\n（由系统自动维护）\n",
    "sb.readme.dir_default": "目录说明",
    "sb.tpl.telos": """# 身份框架 (TELOS)
## 使命 (Mission)
- M0: 作为用户的数字分身与战略参谋，放大用户的智力输出，绝不成为执行的绊脚石。

## 目标 (Goals)
- G0: 建立并维护一个结构极简、智能拉满的第二大脑。

## 核心信念 (Beliefs)
- B0: 弱结构，强智能。把尽可能多的判断交给你（AI），而不是依靠死板的代码规则。
- B1: 用户是审批者，你是执行者与提议者。

## 当前叙事 (Narrative)
- N0: 我正在与主人一起构建基于 AdamI 架构的第二大脑系统。
""",
    "sb.tpl.context": """# 近期状态 (CONTEXT)
- 当前重点：正在进行 AdamI 系统代码的重构与联调。
- 近期痛点：需要解决多代理通信和 API Rate Limit 问题。
""",
    "sb.readme.inbox": "输入收集箱，未分类内容暂存。归档时需分析内容并移入目标路径。",
    "sb.readme.projects": "项目，有明确目标和截止日期。如：AdamI 2.0 重构。",
    "sb.readme.areas": "责任领域，持续维护无终点。如：技术学习、健康管理。",
    "sb.readme.resources": "资源库，可复用的参考资料、代码片段、方法论。",
    "sb.readme.archives": "归档库，已完成或废弃但需要保留的内容。",
    "sc.compose.no_skills": "（无可用技能）",
    "sc.node.desc.invoke_skill": "调用技能 {skill_name}",
    "sc.node.prompt.handle_task": "请处理以下任务：{task_description}",
    "sc.node.desc.llm": "LLM 处理",
    "sc.node.desc.llm_final": "LLM 处理（最终兜底）",
    "sc.prompt.create_new_skill": """你正在执行 CREATE_NEW_SKILL 动作。
任务描述：{task_description}

请严格按照以下格式输出（不允许任何多余文字）：

{{
  "action": "CREATE_NEW_SKILL",
  "args": {{
    "skill_name": "技能名称",
    "description": "一句话描述"
  }}
}}
```python
# 这里是完整的、可直接运行的 Python 异步技能代码
async def execute(**kwargs) -> dict:
    ...
```
""",
    "sc.node.prompt.research": "调研任务需求",
    "sc.node.desc.research": "Researcher 调研",
    "sc.node.prompt.engineer": "生成技能代码",
    "sc.node.desc.engineer": "Engineer 生成代码",
    "sc.node.desc.executor": "Executor 执行",
    "sc.node.prompt.critic": "审查结果",
    "sc.node.desc.critic": "Critic 审查",
    "sc.prompt.compose_workflow": """你是一个工作流编排专家。根据以下任务描述和可用技能，设计一个可执行的工作流。

任务描述：{task_description}

可用技能：{skills_block}

你需要输出一个 JSON 对象，描述工作流的节点和边。每个节点可以是一个技能调用、LLM 调用或条件分支。
节点类型：
- SKILL_CALL: 调用一个现有技能，需要指定 skill_name 和参数（参数可以从 context 中获取）。
- LLM_CALL: 调用 LLM 进行推理，需要指定 prompt（可以引用 context 中的变量）。
- CONDITION: 条件判断，根据 context 中的值决定下一步。条件表达式必须使用纯 Python 语法，只允许比较、逻辑运算和 $context.xxx 引用，禁止出现中文或自然语言描述！

输出格式：
{{
  "nodes": [
    {{
      "node_id": "node1",
      "node_type": "SKILL_CALL",
      "config": {{
        "skill_name": "技能名",
        "args": {{"param1": "$context.var1"}}
      }},
      "description": "描述"
    }},
    {{
      "node_id": "node2",
      "node_type": "CONDITION",
      "config": {{
        "condition": "$context.node1.status == 'success'"
      }},
      "description": "判断上一步是否成功"
    }},
    {{
      "node_id": "node3",
      "node_type": "LLM_CALL",
      "config": {{
        "prompt": "分析上一步结果：$context.node1.data"
      }},
      "description": "分析"
    }}
  ],
  "edges": {{
    "node1": ["node2"],
    "node2": ["node3"],
    "node3": []
  }}
}}

注意：
- 条件节点（CONDITION）的 config 中必须包含 "condition" 字段，值为完整的 Python 表达式，例如：$context.node1.status == 'success'。
- 禁止生成以比较运算符开头的残缺表达式（如 `== 'success'`）。
- 禁止使用中文、自然语言作为条件。
- 你可以自由组合，但必须保证工作流是有向无环图。
- 如果任务是“创建技能”，请优先生成包含 ENGINEER 节点的创建专用流程。
""",
    "sc.prompt.compose_retry": """你之前生成的工作流中包含无效的条件表达式（例如使用了中文、自然语言或不完整的表达式）。请重新生成，确保所有条件节点（CONDITION）的 config.condition 字段是合法的 Python 表达式，必须包含左操作数和右操作数，例如：$context.node1.status == 'success'。

任务描述：{task_description}
可用技能：{skills_block}

请只输出正确的 JSON。
""",
}


def _merge(path: Path, patch: dict[str, str]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    overlap = set(data) & set(patch)
    if overlap:
        raise SystemExit(f"Keys already exist in {path.name}: {sorted(overlap)[:20]}")
    data.update(patch)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    _merge(EN, EN_PATCH)
    _merge(ZH, ZH_PATCH)
    print("merged", len(EN_PATCH), "keys into en and zh-Hans")


if __name__ == "__main__":
    main()
