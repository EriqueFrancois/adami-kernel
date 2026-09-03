import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, Union

from adami_kernel.config import settings
from adami_kernel.hippocampus.second_brain_ingest import SecondBrainIngestError, write_note
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t


def _sb_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


logger = logging.getLogger("AdamI-SecondBrain")


# 仓库内「外挂大脑」复刻指南全文（与包内 SecondBrain.md 同构），供 L1 教义注入读取
_SECOND_BRAIN_DOCTRINE_PATH = Path(__file__).resolve().parent.parent / "SecondBrain.md"

# `retrieve_brain_snippets` 仅扫 PARA 下这三个顶层目录中的成员 `.md`（与步骤 17 一致）
_RETRIEVE_SNIPPET_SUBDIRS = ("Inbox", "Projects", "Resources")

# `search_similar_skill`：回传正文上限（SkillFactory Tier3 兜底）
_SIMILAR_SKILL_MAX_CHARS = 32_000
# 打分阶段最多读入的字符数（超大文件只读前缀）
_SIMILAR_SKILL_SCAN_SAMPLE_CHARS = 80_000
# 超过此字节的文件仍以截断样本参与打分，不再全文读入内存
_SIMILAR_SKILL_MAX_FILE_BYTES = 3_000_000


def _iter_resources_py_and_md(resources_root: Path) -> Iterator[Path]:
    """`Resources` 下递归 `*.py` / `*.md`，排除 `__pycache__`、隐藏文件等。"""
    if not resources_root.is_dir():
        return
    for p in resources_root.rglob("*"):
        if not p.is_file():
            continue
        if "__pycache__" in p.parts or ".git" in p.parts:
            continue
        if p.name.startswith("."):
            continue
        suf = p.suffix.lower()
        if suf not in (".py", ".md"):
            continue
        yield p


def _description_overlap_tokens(description: str) -> List[str]:
    """从任务描述抽取关键词：分词 + 连续中英文字符段，去重保序。"""
    d = (description or "").strip()
    if not d:
        return []
    seen: set[str] = set()
    out: List[str] = []
    for t in _topic_tokens(d):
        k = t.strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    for w in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{2,}", d):
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _keyword_overlap_score(tokens: List[str], rel_posix: str, text_sample: str) -> int:
    hay = f"{rel_posix}\n{text_sample}".lower()
    score = 0
    for tok in tokens:
        tl = tok.lower()
        if len(tl) < 2 and all(ord(c) < 128 for c in tl):
            continue
        c = hay.count(tl)
        if c:
            score += c * 2 + min(len(tl), 12)
    return score


def _parse_md_summary_and_first_heading(text: str) -> Tuple[str, str]:
    """从笔记中取出 YAML frontmatter 的 `summary` 与正文首条 Markdown 标题（`#`）。"""
    summary = ""
    body = text
    if text.startswith("---"):
        close = text.find("\n---", 4)
        if close != -1:
            fm = text[4:close]
            body = text[close + 4 :].lstrip("\n")
            for raw_ln in fm.split("\n"):
                ln = raw_ln.strip()
                if ln.lower().startswith("summary:"):
                    val = raw_ln.split(":", 1)[1].strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
                        val = val[1:-1]
                    summary = val
                    break
    title = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            break
    if not title:
        for line in body.splitlines():
            s = line.strip()
            if s and not s.startswith("---"):
                title = s[:200]
                break
    return summary, title


def _topic_tokens(topic: str) -> List[str]:
    parts = [p.strip() for p in re.split(r"[\s,，、;；]+", topic) if p.strip()]
    return parts if parts else [topic.strip()]


_NOTE_DATE_IN_NAME = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")


def _frontmatter_source(text: str) -> str:
    if not (text or "").startswith("---"):
        return ""
    close = text.find("\n---", 4)
    if close == -1:
        return ""
    fm = text[4:close]
    for raw_ln in fm.split("\n"):
        ln = raw_ln.strip()
        if ln.lower().startswith("source:"):
            val = raw_ln.split(":", 1)[1].strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
                val = val[1:-1]
            return val.strip()
    return ""


def _is_generated_report_note(rel: str, raw: str, title: str) -> bool:
    """Studio-written briefs must not be re-injected as 'news' for a new briefing."""
    name = Path(rel).name.lower()
    if name.startswith("report-"):
        return True
    src = _frontmatter_source(raw).lower().replace("-", "_")
    if src == "report_studio":
        return True
    tl = (title or "").strip().lower()
    return tl.startswith("report:") or tl.startswith("report：")


def _note_recency_ts(path: Path, rel: str) -> float:
    m = _NOTE_DATE_IN_NAME.search(Path(rel).name)
    if m:
        try:
            dt = datetime(
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3)),
                tzinfo=timezone.utc,
            )
            return dt.timestamp()
        except ValueError:
            pass
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return 0.0


def _recency_score_boost(recency_ts: float, *, now_ts: Optional[float] = None) -> int:
    now = float(now_ts if now_ts is not None else time.time())
    if recency_ts <= 0:
        return 0
    age_days = max(0.0, (now - recency_ts) / 86400.0)
    if age_days <= 3:
        return 6
    if age_days <= 14:
        return 3
    if age_days <= 45:
        return 1
    return 0


def _snippet_match_score(tokens: List[str], summary: str, title: str, rel_path: str) -> int:
    """关键词在 summary / 标题 / 路径中的命中加权（全小写比较，中文原样）。"""
    summary_l = summary.lower()
    title_l = title.lower()
    path_l = rel_path.lower()
    score = 0
    for tok in tokens:
        tl = tok.lower()
        if not tl:
            continue
        if tl in summary_l:
            score += 3
        if tl in title_l:
            score += 2
        if tl in path_l:
            score += 1
    return score


class SecondBrainManager:
    """第二大脑物理文件管理器（PARA架构 + 身份注入）

    职责：
    1. Bootstrap 播种：自动创建 PARA 目录结构及初始身份文件
    2. 身份上下文聚合：供 PromptBuilder 实时注入 L1 提示词
    3. 只读加载包内 SecondBrain.md：供上层注入完整教义（read_second_brain_doctrine）
    4. 文件安全操作：确保目录和核心文件始终存在
    5. L2 成员清单：`sync_para_readme_members()` 按目录内 `*.md` 刷新 README「## 成员清单」
    6. intake 归位：`move_brain_note()` 在 brain 根内移动笔记并更新 frontmatter（路径越界拒绝）
    7. 启动快照：`brain_health_summary()` 供 BootManager 等设备一条健康摘要日志
    8. 主动检索：`retrieve_brain_snippets()` 在 Inbox/Projects/Resources 顶层笔记中按关键词拼接入库片段（无向量）
    9. Tier3 技能兜底：`search_similar_skill()` 在 Resources 下递归扫描 `.py`/`.md`， overlap 打分回传全文或截断（供 SkillFactory）
    10. 未来扩展点：候选池写入等
    """

    def __init__(self, root_dir: Optional[str] = None) -> None:
        self.root = Path(
            root_dir if root_dir is not None else settings.path_second_brain_root
        ).resolve()
        self.dirs: List[str] = [
            "Inbox",
            "Projects",
            "Areas",
            "Resources",
            "Archives",
            "Identity",
            "System/working-memory",
        ]
        self._members_heading = boot_t("sb.readme.heading_members")
        self._duty_heading = boot_t("sb.readme.heading_duty")
        logger.debug(_sb_t("sbrn.debug.init_root", root=str(self.root)))

    async def initialize(self) -> None:
        """Bootstrap 播种原则：检查并初始化目录与说明文件"""
        try:
            # 1. 创建所有必要目录
            for d in self.dirs:
                dir_path = self.root / d
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.debug(_sb_t("sbrn.debug.dir_ok", path=str(dir_path)))

            # 2. 播种核心身份文件 (L1 级提示词)
            self._ensure_file(
                "Identity/TELOS.md",
                self._tpl_telos(),
            )
            self._ensure_file(
                "Identity/CONTEXT.md",
                self._tpl_context(),
            )
            self._ensure_file(
                "Identity/PROFILE.md",
                _sb_t("sb.seed.profile"),
            )
            self._ensure_file(
                "System/working-memory/OPERATING_RULES.md",
                _sb_t("sb.seed.operating_rules"),
            )
            self._ensure_file(
                "System/working-memory/candidates.md",
                _sb_t("sb.seed.candidates"),
            )
            self._ensure_file(
                "System/working-memory/tasks.md",
                boot_t("dp.tasks_md.template"),
            )
            self._ensure_file(
                "System/working-memory/locale.json",
                '{\n  "locale": ""\n}\n',
            )
            self._ensure_file(
                "System/pending_approvals.md",
                _sb_t("sb.seed.pending_approvals"),
            )

            # 3. 播种 L2 目录说明文件
            for d in ["Inbox", "Projects", "Areas", "Resources", "Archives"]:
                self._ensure_file(
                    f"{d}/README.md",
                    self._tpl_readme(d),
                )

            logger.info(boot_t("boot.log.second_brain_para", root=self.root))

        except Exception as e:
            logger.error(_sb_t("sbrn.err.init", e=e), exc_info=True)
            raise

    def _ensure_file(self, rel_path: str, default_content: str) -> None:
        """安全创建文件（若已存在则跳过）"""
        full_path = self.root / rel_path
        try:
            if not full_path.exists():
                full_path.parent.mkdir(parents=True, exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(default_content)
                logger.debug(_sb_t("sbrn.debug.seed", path=str(full_path)))
            else:
                logger.debug(_sb_t("sbrn.debug.exists", path=str(full_path)))
        except Exception as e:
            logger.error(_sb_t("sbrn.err.file_create", path=str(full_path), e=e), exc_info=True)
            raise

    def read_identity_context(self) -> str:
        """聚合读取所有身份上下文，注入给 PromptBuilder

        返回格式严格符合 SecondBrain.md <IDENTITY_AND_RULES> 规范
        """
        context = ["<IDENTITY_AND_RULES>"]
        files_to_inject = [
            "Identity/TELOS.md",
            "Identity/CONTEXT.md",
            "Identity/PROFILE.md",
            "System/working-memory/OPERATING_RULES.md",
        ]

        for f in files_to_inject:
            path = self.root / f
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8").strip()
                    if content:
                        context.append(f"--- {f} ---\n{content}")
                except Exception as e:
                    logger.warning(_sb_t("sbrn.warn.id_read", path=str(path), e=e))
            else:
                logger.warning(_sb_t("sbrn.warn.id_missing", path=str(path)))

        context.append("</IDENTITY_AND_RULES>")
        return "\n\n".join(context)

    def read_second_brain_doctrine(self) -> str:
        """只读加载仓库内 `adami_kernel/SecondBrain.md`（外挂大脑复刻指南全文）。

        供 PromptBuilder 等上层按需注入 L1 教义；本方法不修改磁盘、不依赖 `.adami_data/brain`。
        失败时返回空串并打 warning，避免阻断主流程。
        """
        path = _SECOND_BRAIN_DOCTRINE_PATH
        if not path.is_file():
            logger.warning(_sb_t("sbrn.warn.doctrine_missing", path=str(path)))
            return ""
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                logger.warning(_sb_t("sbrn.warn.doctrine_empty", path=str(path)))
                return ""
            return text
        except OSError as e:
            logger.warning(_sb_t("sbrn.warn.doctrine_read", path=str(path), e=e))
            return ""

    def retrieve_brain_snippets(self, topic: str, max_files: int) -> str:
        """在 Inbox、Projects、Resources 顶层目录扫描成员 `*.md`（不含 README），按 `topic` 关键词匹配 frontmatter `summary` 与正文首条 `#` 标题（及路径），取分数最高的前 K 条拼成片段文本。

        纯字符串规则、无向量；无任何命中时返回空串。
        """
        topic_clean = (topic or "").strip()
        if not topic_clean:
            return ""
        k = max(1, min(int(max_files), 50))
        tokens = _topic_tokens(topic_clean)
        scored: List[Tuple[int, float, str, str, str]] = []
        now_ts = time.time()

        for sub in _RETRIEVE_SNIPPET_SUBDIRS:
            d = self.root / sub
            if not d.is_dir():
                continue
            try:
                candidates = sorted(
                    p
                    for p in d.iterdir()
                    if p.is_file() and p.suffix.lower() == ".md" and p.name != "README.md"
                )
            except OSError as e:
                logger.debug(_sb_t("sbrn.debug.retrieve_list", dir=str(d), e=e))
                continue
            for p in candidates:
                try:
                    raw = p.read_text(encoding="utf-8")
                except OSError as e:
                    logger.debug(_sb_t("sbrn.debug.retrieve_read", path=str(p), e=e))
                    continue
                summary, title = _parse_md_summary_and_first_heading(raw)
                rel = f"{sub}/{p.name}"
                if _is_generated_report_note(rel, raw, title):
                    continue
                recency_ts = _note_recency_ts(p, rel)
                sc = _snippet_match_score(tokens, summary, title, rel)
                sc += _recency_score_boost(recency_ts, now_ts=now_ts)
                if sc > 0:
                    scored.append((sc, recency_ts, rel, summary, title))

        if not scored:
            return ""

        scored.sort(key=lambda x: (-x[0], -x[1]))
        picked = scored[:k]
        blocks: List[str] = []
        for sc, _recency_ts, rel, summary, title in picked:
            blocks.append(
                f"### `{rel}` (match={sc})\n"
                f"- **summary**: {summary or _sb_t('sb.snippet.none')}\n"
                f"- **title**: {title or _sb_t('sb.snippet.none')}\n"
            )
        out = "\n".join(blocks).strip()
        logger.debug(
            _sb_t(
                "sbrn.debug.retrieve_hits",
                topic=repr(topic_clean),
                k=k,
                hits=len(picked),
            )
        )
        return out

    # ====================== 模块五：外部世界信号写入入口（安全落盘） ======================
    def write_inbox_note(
        self,
        title: str,
        body_md: str,
        *,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        dedupe_key: Optional[str] = None,
        dedupe_ttl_sec: float = 3600.0,
        dedupe_strategy: str = "overwrite",
        filename_prefix: str = "note",
    ) -> Path:
        """
        安全写入 SecondBrain Inbox 笔记。
        返回最终落盘的绝对路径；若写入失败抛出 ValueError（包装 ingest 错误）。
        """
        try:
            return write_note(
                brain_root=self.root,
                write_to="Inbox",
                title=title,
                body_md=body_md,
                tags=tags or [],
                source=source,
                dedupe_key=dedupe_key,
                dedupe_ttl_sec=dedupe_ttl_sec,
                dedupe_strategy=dedupe_strategy,  # type: ignore[arg-type]
                filename_prefix=filename_prefix,
            )
        except SecondBrainIngestError as e:
            raise ValueError(str(e)) from e

    def write_resource_note(
        self,
        title: str,
        body_md: str,
        *,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        dedupe_key: Optional[str] = None,
        dedupe_ttl_sec: float = 3600.0,
        dedupe_strategy: str = "overwrite",
        filename_prefix: str = "note",
    ) -> Path:
        """安全写入 SecondBrain Resources 笔记。"""
        try:
            return write_note(
                brain_root=self.root,
                write_to="Resources",
                title=title,
                body_md=body_md,
                tags=tags or [],
                source=source,
                dedupe_key=dedupe_key,
                dedupe_ttl_sec=dedupe_ttl_sec,
                dedupe_strategy=dedupe_strategy,  # type: ignore[arg-type]
                filename_prefix=filename_prefix,
            )
        except SecondBrainIngestError as e:
            raise ValueError(str(e)) from e

    def _search_similar_skill_sync(self, description: str) -> Optional[str]:
        """同步体：扫描 `Resources/**/*.py` 与 `**/*.md`，按关键词 overlap 取最高分文件。"""
        desc = (description or "").strip()
        if not desc:
            return None
        res_dir = self.root / "Resources"
        if not res_dir.is_dir():
            return None
        tokens = _description_overlap_tokens(desc)
        if not tokens:
            return None
        root = self.root.resolve()
        scored: List[Tuple[int, Path]] = []

        for path in _iter_resources_py_and_md(res_dir):
            try:
                resolved = path.resolve()
                rel = resolved.relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            try:
                st = resolved.stat()
            except OSError:
                continue

            sample: str
            try:
                if st.st_size > _SIMILAR_SKILL_MAX_FILE_BYTES:
                    with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
                        sample = fh.read(_SIMILAR_SKILL_SCAN_SAMPLE_CHARS)
                else:
                    sample = resolved.read_text(encoding="utf-8", errors="replace")
                    if len(sample) > _SIMILAR_SKILL_SCAN_SAMPLE_CHARS:
                        sample = sample[:_SIMILAR_SKILL_SCAN_SAMPLE_CHARS]
            except OSError:
                continue

            sc = _keyword_overlap_score(tokens, rel, sample)
            if sc > 0:
                scored.append((sc, resolved))

        if not scored:
            logger.debug(_sb_t("sbrn.debug.search_miss", snippet=repr(desc[:120])))
            return None

        scored.sort(key=lambda x: (-x[0], x[1].as_posix()))
        best_score, best_path = scored[0]
        try:
            full = best_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning(_sb_t("sbrn.warn.search_read_best", e=e))
            return None
        try:
            rel_best = best_path.resolve().relative_to(root).as_posix()
        except ValueError:
            rel_best = best_path.name

        header = f"# Tier3 brain fallback: `{rel_best}` (overlap_score={best_score})\n\n"
        max_c = _SIMILAR_SKILL_MAX_CHARS
        if len(full) <= max_c:
            body = full
        else:
            body = full[: max_c - 24] + _sb_t("sb.search.truncation_suffix")
        out = header + body
        logger.info(
            _sb_t(
                "sbrn.log.search_hit",
                path=rel_best,
                score=best_score,
                olen=len(out),
            )
        )
        return out

    async def search_similar_skill(self, description: str) -> Optional[str]:
        """在 `Resources` 下递归匹配 `.py`/`.md`：描述关键词与路径+正文 overlap 打分，返回最高分文件全文或截断（≤32k 字级别）。

        与 `SkillFactory._get_from_history` 中 `await self.second_brain.search_similar_skill(description)` 签名一致。
        """
        return await asyncio.to_thread(self._search_similar_skill_sync, description)

    #: intake 归位：`para` 小写键 → PARA 顶层文件夹名
    PARA_KEY_TO_SUBDIR: Dict[str, str] = {
        "inbox": "Inbox",
        "projects": "Projects",
        "areas": "Areas",
        "resources": "Resources",
        "archives": "Archives",
    }

    def _normalize_para_key_for_move(self, para: str) -> str:
        s = str(para).strip().lower().replace("\\", "/").rstrip("/")
        s = s.split("/")[-1] if s else ""
        aliases = {
            "project": "projects",
            "area": "areas",
            "resource": "resources",
            "archive": "archives",
        }
        s = aliases.get(s, s)
        if s not in self.PARA_KEY_TO_SUBDIR:
            logger.warning(_sb_t("sbrn.warn.move_bad_para", para=repr(para)))
            raise ValueError(
                _sb_t(
                    "sb.err.para_invalid",
                    allowed=sorted(self.PARA_KEY_TO_SUBDIR),
                    got=para,
                )
            )
        return s

    def _resolved_path_under_root(self, path: Path, *, label: str) -> Path:
        root = self.root.resolve()
        try:
            p = Path(path).expanduser()
            if not p.is_absolute():
                p = (root / p).resolve()
            else:
                p = p.resolve()
        except OSError as e:
            logger.warning(_sb_t("sbrn.warn.move_resolve", label=label, path=str(path), e=e))
            raise ValueError(_sb_t("sb.err.path_unresolvable", label=label, path=path)) from e
        try:
            p.relative_to(root)
        except ValueError:
            logger.warning(_sb_t("sbrn.warn.move_escape", label=label, p=str(p), root=str(root)))
            raise ValueError(_sb_t("sb.err.path_escape", label=label, path=str(p))) from None
        return p

    @staticmethod
    def _frontmatter_set_para(markdown: str, para_key: str) -> str:
        if not markdown.startswith("---\n"):
            return markdown
        close = markdown.find("\n---\n", 4)
        if close == -1:
            return markdown
        before = markdown[:close]
        after = markdown[close:]
        lines = before.split("\n")
        new_lines: List[str] = []
        replaced = False
        for line in lines:
            if line.strip().lower().startswith("para:"):
                new_lines.append(f"para: {para_key}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced and new_lines and new_lines[0] == "---":
            new_lines.insert(1, f"para: {para_key}")
        elif not replaced:
            new_lines = ["---", f"para: {para_key}"] + new_lines
        return "\n".join(new_lines) + after

    def move_brain_note(
        self,
        src: Union[str, Path],
        para: str,
        dest_filename: Optional[str] = None,
    ) -> Path:
        """将 `self.root` 内的笔记移至 PARA 子目录，并更新 frontmatter 的 `para` 字段。

        源与目标均经 ``resolve()`` 后校验必须位于 `self.root` 之下，禁止 ``..`` 或绝对路径逃逸。

        Args:
            src: 源文件（须在 brain 根内）
            para: ``inbox`` / ``projects`` / ``areas`` / ``resources`` / ``archives``（大小写不敏感）
            dest_filename: 可选目标**仅文件名**；缺省则沿用源文件名

        Returns:
            最终文件的绝对路径

        Raises:
            ValueError: 参数非法、路径越界、源不是文件
            OSError: 读写失败
        """
        para_key = self._normalize_para_key_for_move(para)
        src_p = self._resolved_path_under_root(src, label=_sb_t("sb.label.src_path"))
        if not src_p.is_file():
            logger.warning(_sb_t("sbrn.warn.move_not_file", path=str(src_p)))
            raise ValueError(_sb_t("sb.err.src_not_file", path=str(src_p)))

        subdir = self.PARA_KEY_TO_SUBDIR[para_key]
        dest_dir = self._resolved_path_under_root(
            self.root / subdir, label=_sb_t("sb.label.dest_dir")
        )
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(_sb_t("sbrn.warn.move_mkdir", dest=str(dest_dir), e=e))
            raise

        name = dest_filename if dest_filename is not None else src_p.name
        name = os.path.basename(str(name).replace("\\", "/"))
        if not name or name in (".", "..") or "/" in name:
            logger.warning(_sb_t("sbrn.warn.move_bad_dest_name", name=repr(dest_filename)))
            raise ValueError(_sb_t("sb.err.dest_filename_invalid", name=str(dest_filename)))
        if not name.lower().endswith(".md"):
            name = f"{name}.md"

        dest_path_raw = dest_dir / name
        dest_path = self._resolved_path_under_root(dest_path_raw, label=_sb_t("sb.label.dest_file"))

        if dest_path.exists() and dest_path != src_p:
            stem = dest_path.stem
            k = 2
            while True:
                cand_raw = dest_dir / f"{stem}_{k}.md"
                cand = self._resolved_path_under_root(cand_raw, label=_sb_t("sb.label.dest_file"))
                if not cand.exists():
                    dest_path = cand
                    break
                k += 1

        text = src_p.read_text(encoding="utf-8")
        text = self._frontmatter_set_para(text, para_key)
        dest_path.write_text(text, encoding="utf-8")
        if src_p.resolve() != dest_path.resolve():
            try:
                src_p.unlink()
            except OSError as e:
                logger.warning(
                    _sb_t(
                        "sbrn.warn.move_unlink",
                        dest=str(dest_path),
                        src=str(src_p),
                        e=e,
                    )
                )
                raise
        return dest_path

    #: PARA 顶层目录（与 `initialize` 播种的 README 一致）
    PARA_MEMBER_DIRS = ("Inbox", "Projects", "Areas", "Resources", "Archives")

    def sync_para_readme_members(self) -> Dict[str, List[str]]:
        """扫描 PARA 各顶层目录下 `*.md`（不含 README），刷新各自 README 的「## 成员清单」段。

        - 若存在 ``## 成员清单``：从该段起替换到下一个 ``## `` 标题之前（保留 ``## 职责`` 及后续全文）。
        - 若无成员段但有 ``## 职责``：在其上一段插入成员段。
        - 若两者皆无：在文件末尾追加成员段。
        - 若 README 不存在：按 `_tpl_readme` 生成并写入成员列表。

        供 CLI、intake 归位后等显式调用；本方法不注册定时事件。

        Returns:
            各目录名 -> 该目录扫描到的成员文件名列表（已排序）。
        """
        result: Dict[str, List[str]] = {}
        for rel in self.PARA_MEMBER_DIRS:
            result[rel] = self._sync_readme_members_for_dir(rel)
        ib, pj, ar, rs, ac = (len(result.get(d, [])) for d in self.PARA_MEMBER_DIRS)
        logger.info(_sb_t("sbrn.log.sync_readme", ib=ib, pj=pj, ar=ar, rs=rs, ac=ac))
        return result

    def _list_para_md_members(self, rel_dir: str) -> List[str]:
        d = self.root / rel_dir
        if not d.is_dir():
            return []
        names: List[str] = []
        for p in sorted(d.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() != ".md":
                continue
            if p.name == "README.md":
                continue
            names.append(p.name)
        return names

    def brain_health_summary(self) -> str:
        """只读快照：根下子目录数、各 PARA 顶层笔记 `.md` 数（不含 README）、`candidates.md` 行数。

        供 BootManager 启动 hook 等打一条 `logger.info`；不修改磁盘。
        """
        root = self.root.resolve()
        try:
            dir_count = sum(1 for p in root.iterdir() if p.is_dir())
        except OSError:
            dir_count = -1

        para_counts = "/".join(
            f"{name}:{len(self._list_para_md_members(name))}" for name in self.PARA_MEMBER_DIRS
        )

        cand_path = root / "System" / "working-memory" / "candidates.md"
        cand_lines: int
        if cand_path.is_file():
            try:
                cand_lines = len(cand_path.read_text(encoding="utf-8").splitlines())
            except OSError:
                cand_lines = -1
        else:
            cand_lines = 0

        return (
            f"brain_root={root} subdirs={dir_count} "
            f"PARA_md[{para_counts}] candidates_lines={cand_lines}"
        )

    def _member_bullet_lines(self, filenames: List[str]) -> List[str]:
        if not filenames:
            return [_sb_t("sb.readme.no_md_members")]
        return [f"- `{name}`" for name in filenames]

    def _splice_members_into_readme_lines(
        self, lines: List[str], bullet_lines: List[str]
    ) -> List[str]:
        """Replace or insert ``## 成员清单`` block; keep ``## 职责`` and below untouched when present."""
        members_idx: Optional[int] = None
        duty_idx: Optional[int] = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if members_idx is None and (
                stripped == self._members_heading
                or stripped.startswith(f"{self._members_heading} ")
            ):
                members_idx = i
            if duty_idx is None and (
                stripped == self._duty_heading or stripped.startswith(f"{self._duty_heading} ")
            ):
                duty_idx = i

        block = [self._members_heading] + bullet_lines

        if members_idx is not None:
            end = len(lines)
            for j in range(members_idx + 1, len(lines)):
                if lines[j].startswith("## "):
                    end = j
                    break
            return lines[:members_idx] + block + lines[end:]

        if duty_idx is not None:
            prefix = lines[:duty_idx]
            if prefix and prefix[-1].strip():
                prefix = prefix + [""]
            return prefix + block + [""] + lines[duty_idx:]

        out = list(lines)
        if out and out[-1].strip():
            out.append("")
        return out + block

    def _readme_lines_from_template(self, rel_dir: str, bullet_lines: List[str]) -> List[str]:
        tpl_lines = self._tpl_readme(rel_dir).strip().split("\n")
        cut: Optional[int] = None
        for i, line in enumerate(tpl_lines):
            if line.strip() == self._members_heading:
                cut = i
                break
        heading_block = [self._members_heading] + bullet_lines
        if cut is not None:
            return tpl_lines[:cut] + heading_block
        return tpl_lines + [""] + heading_block

    def _sync_readme_members_for_dir(self, rel_dir: str) -> List[str]:
        members = self._list_para_md_members(rel_dir)
        bullet_lines = self._member_bullet_lines(members)
        readme_path = self.root / rel_dir / "README.md"

        if not readme_path.is_file():
            new_lines = self._readme_lines_from_template(rel_dir, bullet_lines)
        else:
            try:
                text = readme_path.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning(_sb_t("sbrn.warn.readme_read", path=str(readme_path), e=e))
                new_lines = self._readme_lines_from_template(rel_dir, bullet_lines)
            else:
                new_lines = self._splice_members_into_readme_lines(text.splitlines(), bullet_lines)

        try:
            readme_path.parent.mkdir(parents=True, exist_ok=True)
            readme_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except OSError as e:
            logger.error(
                _sb_t("sbrn.err.readme_write", path=str(readme_path), e=e),
                exc_info=True,
            )
            raise

        logger.debug(
            _sb_t("sbrn.debug.readme_refresh", dir=rel_dir, n=len(members)),
        )
        return members

    # ================= Markdown 模板库 =================
    def _tpl_telos(self) -> str:
        return _sb_t("sb.tpl.telos")

    def _tpl_context(self) -> str:
        return _sb_t("sb.tpl.context")

    def _tpl_readme(self, dir_name: str) -> str:
        desc_map = {
            "Inbox": _sb_t("sb.readme.inbox"),
            "Projects": _sb_t("sb.readme.projects"),
            "Areas": _sb_t("sb.readme.areas"),
            "Resources": _sb_t("sb.readme.resources"),
            "Archives": _sb_t("sb.readme.archives"),
        }
        desc = desc_map.get(dir_name, _sb_t("sb.readme.dir_default"))
        return f"# {dir_name}/\n> {desc}\n" + _sb_t("sb.readme.footer_auto")
