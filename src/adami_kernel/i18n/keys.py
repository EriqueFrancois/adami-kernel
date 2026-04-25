"""Stable i18n keys (avoid string drift across the codebase).

Values are the literal key paths used in JSON catalogs.

波次 0 — 键前缀约定（与 ``docs/i18n_boundary_and_locale_policy.md`` §6 一致）
--------------------------------------------------------------------
- ``report.*`` — Report Studio / ``/report`` 向导与帮助
- ``settings.*`` — CLI / 聊天设置向导
- ``port.*`` — Telegram / Discord / Shell 端口输出（启动、回调、媒体错误等）
- ``errors.*`` — 跨模块用户可见错误
- 迁移中新增：``dp.*``（DecisionProcessor）、``planner.*``（TaskPlanner 用户可见返回）、
  ``orch.*``（编排层 HITL / Human 代理 / 工作流暂停原因等）、
  ``skill.*``（SkillValidator / SkillManager 用户可见反馈）、
  ``skill.builder.*`` / ``skill.inspect.*``（SkillBuilder / SkillInspector 面向提交者的反馈与建议）、
  ``market.*`` / ``market.api.*``（技能市场与 FastAPI 市场路由）、``web.*``（Web 控制台 Dashboard / 删除 / 进化触发）、
  ``nexus.*``（nexus 共享逻辑；与 ``port.*`` 重叠时优先 ``port.*``）

第二方摘要（新闻片段、工具返回长文本等）→ UI 语言：在业务边界调用
``adami_kernel.i18n.external_text.translate_external_summary_for_ui``，内部经
``translate_text_async``、``scenario="external_summary"``；勿把此类文本塞进 JSON 模板键。

新键优先落在已有前缀下；确需新桶时再扩展本节与 policy 文档。
"""


class UI:
    MENU_ENTRY = "ui.menu.entry"


class Report:
    WIZARD_PROMPT_TIMEZONE = "report.wizard.prompt.timezone"


class Errors:
    REPORT_JSON_INVALID = "errors.report.json_invalid"
