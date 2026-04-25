"""
小条（3）PARA / move_brain_note / L2 README + 小条（4）MAINTAIN / WRITING 验收用例。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.cortex.decision_processor import DecisionProcessor
from adami_kernel.cortex.intent_router import IntentSystemToken, SemanticIntentRouter
from adami_kernel.hippocampus.second_brain import SecondBrainManager

# ----- 小条（3）-----


def test_move_brain_note_projects_and_frontmatter():
    d = Path(tempfile.mkdtemp(prefix="t3_mv_"))
    (d / "Inbox").mkdir(parents=True)
    (d / "Projects").mkdir(parents=True)
    src = d / "Inbox" / "n.md"
    src.write_text("---\npara: inbox\n---\n\nx", encoding="utf-8")
    sb = SecondBrainManager(str(d))
    out = sb.move_brain_note(src, "projects", "n.md")
    assert out.parent.name == "Projects"
    assert "para: projects" in out.read_text(encoding="utf-8")
    assert not (d / "Inbox" / "n.md").exists()


def test_move_brain_note_rejects_outside_brain():
    d = Path(tempfile.mkdtemp(prefix="t3_safe_"))
    sb = SecondBrainManager(str(d))
    with pytest.raises(ValueError, match="不在 brain 根目录"):
        sb.move_brain_note("/etc/passwd", "inbox")


def test_move_brain_note_rejects_bad_para():
    d = Path(tempfile.mkdtemp(prefix="t3_para_"))
    (d / "Inbox").mkdir(parents=True)
    f = d / "Inbox" / "a.md"
    f.write_text("---\npara: inbox\n---\n\n", encoding="utf-8")
    sb = SecondBrainManager(str(d))
    with pytest.raises(ValueError, match="para"):
        sb.move_brain_note(f, "evil_dir")


def test_sync_para_readme_matches_md_after_move():
    d = Path(tempfile.mkdtemp(prefix="t3_l2_"))
    for name in SecondBrainManager.PARA_MEMBER_DIRS:
        (d / name).mkdir(parents=True)
    (d / "Inbox" / "a.md").write_text("x", encoding="utf-8")
    sb = SecondBrainManager(str(d))
    src = d / "Inbox" / "a.md"
    sb.move_brain_note(src, "projects", "a.md")
    sb.sync_para_readme_members()
    inbox_readme = (d / "Inbox" / "README.md").read_text(encoding="utf-8")
    proj_readme = (d / "Projects" / "README.md").read_text(encoding="utf-8")
    assert inbox_readme.count("`a.md`") == 0
    assert "`a.md`" in proj_readme


# ----- 小条（4）-----


@pytest.mark.asyncio
async def test_intent_maintain_and_writing_tokens():
    router = MagicMock()
    router.call_llm = AsyncMock(return_value="noop")

    r = SemanticIntentRouter(router)
    cases_maintain = ["/maintain", "维护", "全库诊断"]
    for t in cases_maintain:
        tag, data = await r.route_task(t)
        assert tag == "SYSTEM_ACTION"
        assert data == IntentSystemToken.MAINTAIN.value

    cases_writing = ["/writing", "写作", "/writing 周报", "写作：摘要"]
    for t in cases_writing:
        tag, data = await r.route_task(t)
        assert tag == "SYSTEM_ACTION"
        assert data == IntentSystemToken.WRITING.value


@pytest.mark.asyncio
async def test_maintain_action_report_readable():
    d = Path(tempfile.mkdtemp(prefix="t4_m_"))
    for name in SecondBrainManager.PARA_MEMBER_DIRS:
        (d / name).mkdir(parents=True)
        (d / name / "README.md").write_text(f"# {name}\n> ok\n\n## 成员清单\nx\n", encoding="utf-8")
    (d / "Inbox" / "one.md").write_text("n", encoding="utf-8")
    wm = d / "System" / "working-memory"
    wm.mkdir(parents=True)
    (wm / "candidates.md").write_text("a\nb\n\n", encoding="utf-8")

    replies: list[str] = []

    async def capture_reply(cid, text, platform="telegram"):
        replies.append(text)

    sb = SecondBrainManager(str(d))
    k = MagicMock()
    k.second_brain = sb
    k.session_locks = {}
    k.telegram_nerve = None
    k.discord_nerve = None
    k._send_reply = AsyncMock(side_effect=capture_reply)

    proc = DecisionProcessor(k)
    await proc._handle_maintain_action("cli", "cli")

    assert len(replies) == 1
    body = replies[0]
    assert "诊断" in body or "PARA" in body
    assert "Inbox" in body
    assert "candidates" in body
    assert "只读" in body or "未执行修复" in body


@pytest.mark.asyncio
async def test_writing_action_loads_writing_glob_and_calls_llm():
    d = Path(tempfile.mkdtemp(prefix="t4_w_"))
    (d / "Resources").mkdir(parents=True)
    spec = d / "Resources" / "memo_writing_spec.md"
    spec.write_text(
        "## 一、背景\n（须填写）\n\n## 二、结论\n（须填写）\n",
        encoding="utf-8",
    )

    captured_prompt: list[str] = []

    async def llm(prompt, **kwargs):
        captured_prompt.append(prompt)
        return "## 一、背景\n自动化测试填充。\n\n## 二、结论\n通过。\n"

    replies: list[str] = []

    async def capture_reply(cid, text, platform="telegram"):
        replies.append(text)

    sb = SecondBrainManager(str(d))
    k = MagicMock()
    k.second_brain = sb
    k.router = MagicMock()
    k.router.call_llm = AsyncMock(side_effect=llm)
    k.session_locks = {}
    k.telegram_nerve = None
    k.discord_nerve = None
    k._send_reply = AsyncMock(side_effect=capture_reply)

    proc = DecisionProcessor(k)
    await proc._handle_writing_action("/writing 按规范写示例", "1", "cli")

    assert len(captured_prompt) == 1
    assert "memo_writing_spec.md" in captured_prompt[0]
    assert "二、结论" in captured_prompt[0]
    assert len(replies) == 1
    assert "writing_glob" in replies[0]
    assert "一、背景" in replies[0]


@pytest.mark.asyncio
async def test_writing_fallback_first_md_without_writing_in_name():
    d = Path(tempfile.mkdtemp(prefix="t4_wb_"))
    (d / "Resources").mkdir(parents=True)
    (d / "Resources" / "plain_ref.md").write_text("# 参考\n仅一段。\n", encoding="utf-8")

    async def llm(prompt, **kwargs):
        return "OK"

    replies: list[str] = []

    async def capture_reply(cid, text, platform="telegram"):
        replies.append(text)

    sb = SecondBrainManager(str(d))
    k = MagicMock()
    k.second_brain = sb
    k.router = MagicMock()
    k.router.call_llm = AsyncMock(side_effect=llm)
    k.session_locks = {}
    k.telegram_nerve = None
    k.discord_nerve = None
    k._send_reply = AsyncMock(side_effect=capture_reply)

    proc = DecisionProcessor(k)
    await proc._handle_writing_action("/writing", "1", "cli")

    assert "fallback_first_md" in replies[0]
    assert "plain_ref.md" in replies[0]
