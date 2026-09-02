"""Report Studio CLI subcommands invoked from ``DecisionProcessor``."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from adami_kernel.config import settings
from adami_kernel.cortex.decision_processor_support import _dcpu_t
from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.locale_utils import normalize_locale
from adami_kernel.i18n.request_locale import get_request_locale

if TYPE_CHECKING:
    from adami_kernel.cortex.decision_processor import DecisionProcessor

logger = logging.getLogger("AdamI-DecisionProcessor")


async def run_report_action(
    dp: DecisionProcessor,
    task_text: str,
    chat_id: str,
    platform: str,
) -> None:
    """
    /report list
    /report show <daily|weekly|monthly>
    /report set <daily|weekly|monthly> <json>
    /report run <daily|weekly|monthly>
    """
    from adami_kernel.peripheral.report_studio.report_store import ReportConfigStore

    raw = (task_text or "").strip()
    raw = re.sub(r"^(/report|/reports|报告|报表)\s*", "", raw, flags=re.IGNORECASE).strip()
    store = ReportConfigStore(getattr(dp.kernel, "second_brain", None))

    if not raw or raw.lower() in ("help", "-h", "--help"):
        msg = i18n_t("report.help.body")
        await dp.kernel._send_reply(chat_id, msg, platform)
        return

    parts = raw.split(maxsplit=2)
    cmd = parts[0].lower()

    if cmd == "list":
        items = store.list_configs()
        lines = [i18n_t("dp.report.list_title"), ""]
        for it in items:
            try:
                cfg = store.load(it["report_type"])  # type: ignore[arg-type]
                sch = cfg.schedule
                lines.append(
                    f"- **{cfg.report_type}** enabled={cfg.enabled} "
                    f"tz=`{sch.timezone}` time=`{sch.publish_time_hhmm}` "
                    f"weekday={sch.weekday} dom={sch.day_of_month}"
                )
            except Exception:
                lines.append(f"- **{it['report_type']}** `{it['path']}`")
        await dp.kernel._send_reply(chat_id, "\n".join(lines), platform)
        return

    if cmd == "show":
        if len(parts) < 2:
            await dp.kernel._send_reply(chat_id, i18n_t("dp.report.usage_show"), platform)
            return
        rtype = parts[1].lower()
        if rtype not in ("daily", "weekly", "monthly"):
            await dp.kernel._send_reply(chat_id, i18n_t("dp.report.err_bad_type"), platform)
            return
        cfg = store.load(rtype)  # type: ignore[arg-type]
        await dp.kernel._send_reply(
            chat_id,
            "```json\n" + cfg.model_dump_json(indent=2, ensure_ascii=False) + "\n```",
            platform,
        )
        return

    if cmd == "set":
        if len(parts) < 3:
            await dp.kernel._send_reply(
                chat_id,
                i18n_t("dp.report.usage_set"),
                platform,
            )
            return
        rtype = parts[1].lower()
        if rtype not in ("daily", "weekly", "monthly"):
            await dp.kernel._send_reply(chat_id, i18n_t("dp.report.err_bad_type"), platform)
            return
        try:
            updates = json.loads(parts[2])
            if not isinstance(updates, dict):
                raise ValueError("JSON must be an object")
        except Exception as e:
            await dp.kernel._send_reply(
                chat_id, i18n_t("dp.report.json_parse_failed", detail=str(e)), platform
            )
            return
        cfg = store.patch(rtype, updates)  # type: ignore[arg-type]
        await dp.kernel._send_reply(
            chat_id,
            i18n_t(
                "dp.report.updated",
                rtype=cfg.report_type,
                tz=cfg.schedule.timezone,
                time=cfg.schedule.publish_time_hhmm,
            ),
            platform,
        )
        return

    if cmd == "run":
        if len(parts) < 2:
            await dp.kernel._send_reply(chat_id, i18n_t("dp.report.usage_run"), platform)
            return
        rtype = parts[1].lower()
        if rtype not in ("daily", "weekly", "monthly"):
            await dp.kernel._send_reply(chat_id, i18n_t("dp.report.err_bad_type"), platform)
            return
        cfg = store.load(rtype)  # type: ignore[arg-type]
        if not cfg.enabled:
            await dp.kernel._send_reply(
                chat_id, i18n_t("dp.report.disabled", rtype=rtype), platform
            )
            return

        async def _emit_sim(payload: dict) -> None:
            if not bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                return
            bus = getattr(dp.kernel, "bus", None)
            if bus is None:
                return
            try:
                from adami_kernel.nexus.event import AdamiEvent, EventPriority

                await bus.publish(
                    AdamiEvent(
                        trace_id=str(getattr(getattr(dp.kernel, "active_sessions", {}).get(chat_id, {}), "get", lambda _k, _d=None: _d)("trace_id", "") or "")
                        or f"sim_{rtype}",
                        source_module="peripheral.report_studio",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload=payload,
                    )
                )
            except Exception:
                return

        await _emit_sim({"event_type": "REPORT_START", "rtype": rtype})

        from adami_kernel.peripheral.report_studio.report_generator import (
            generate_fixed_blocks_report,
        )
        from adami_kernel.peripheral.report_studio.report_port_format import (
            plain_report_text_for_im_channels,
        )

        now = datetime.now(timezone.utc)
        if rtype == "daily":
            start = now - timedelta(hours=24)
        elif rtype == "weekly":
            start = now - timedelta(days=7)
        else:
            start = now - timedelta(days=30)

        sb = getattr(dp.kernel, "second_brain", None)
        web = getattr(getattr(dp.kernel, "toolbox", None), "web", None)
        loc_report = normalize_locale(get_request_locale() or settings.effective_report_locale())
        _ddgs_region = {"en": "us-en", "zh-Hans": "zh-cn", "zh": "zh-cn"}.get(loc_report, "us-en")
        if web is not None:
            _tl = {"daily": "d", "weekly": "w", "monthly": "m"}[rtype]

            async def _report_search(q: str, top_n: int):
                return await web.search(q, max_results=top_n, timelimit=_tl, region=_ddgs_region)

            _search_fn = _report_search
        else:
            _search_fn = None

        _translate_llm = None
        if getattr(dp.kernel, "router", None):

            async def _report_translate_llm(prompt: str) -> str:
                return await dp.kernel.router.call_llm(
                    prompt,
                    brain_type="action",
                    temperature=0.15,
                    apply_design_output_policy=True,
                )

            _translate_llm = _report_translate_llm

        rep = await generate_fixed_blocks_report(
            report_type=rtype,  # type: ignore[arg-type]
            title=None,
            timezone_name=cfg.schedule.timezone,
            period_start=start,
            period_end=now,
            top_n_system=int(cfg.sections.system_updates_top_n),
            top_n_news=int(cfg.sections.world_news_top_n),
            top_n_ai=int(cfg.sections.ai_progress_top_n),
            top_n_market=int(cfg.sections.market_moves_top_n),
            second_brain=sb,
            search_fn=_search_fn,
            locale=loc_report,
            translate_call_llm=_translate_llm,
        )

        note_title = f"{cfg.note_prefix}: {rtype} ({now.strftime('%Y-%m-%d')})"
        body_md = rep.rendered.body_md
        write_to = cfg.write_to
        mgr = sb if sb is not None else SecondBrainManager()
        if write_to == "Resources":
            p = mgr.write_resource_note(
                note_title,
                body_md,
                tags=["report", rtype],
                source="report_studio",
                dedupe_key=f"report:{rtype}:{now.strftime('%Y-%m-%d')}",
                filename_prefix=cfg.note_prefix,
            )
        else:
            p = mgr.write_inbox_note(
                note_title,
                body_md,
                tags=["report", rtype],
                source="report_studio",
                dedupe_key=f"report:{rtype}:{now.strftime('%Y-%m-%d')}",
                filename_prefix=cfg.note_prefix,
            )
        await _emit_sim({"event_type": "REPORT_DONE", "rtype": rtype, "note_path": str(p)})
        try:
            text = plain_report_text_for_im_channels((body_md or "").strip())
            if text:
                if platform == "discord":
                    max_len = 1800
                elif platform == "telegram":
                    max_len = 3800
                else:
                    max_len = 12000

                def _chunks(s: str, n: int) -> list[str]:
                    s2 = s.strip()
                    if len(s2) <= n:
                        return [s2]
                    out: list[str] = []
                    buf: list[str] = []
                    cur = 0
                    for para in s2.split("\n\n"):
                        piece = (para.strip() + "\n\n") if para.strip() else "\n\n"
                        if cur + len(piece) > n and buf:
                            out.append("".join(buf).rstrip())
                            buf = [piece]
                            cur = len(piece)
                        else:
                            buf.append(piece)
                            cur += len(piece)
                    if buf:
                        out.append("".join(buf).rstrip())
                    final: list[str] = []
                    for c in out:
                        if len(c) <= n:
                            final.append(c)
                        else:
                            for i in range(0, len(c), n):
                                final.append(c[i : i + n])
                    return final

                header = i18n_t("dp.report.push_header", rtype=rtype.title())
                await dp.kernel._send_reply(chat_id, header, platform)
                for part in _chunks(text, max_len):
                    await dp.kernel._send_reply(chat_id, part, platform)
        except Exception as e:
            logger.warning(_dcpu_t("dcpu.warn.report_push", e=e))

        final_msg = i18n_t("dp.report.generated_path", path=str(p))
        await dp.kernel._send_reply(chat_id, final_msg, platform)
        await _emit_sim({"event_type": "REPLY", "text": final_msg, "rtype": rtype})
        return

    await dp.kernel._send_reply(chat_id, i18n_t("dp.report.unknown_subcmd", cmd=cmd), platform)
