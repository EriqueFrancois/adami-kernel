"""
Document parsing — Steps 0–2 acceptance (baseline doc + optional MarkItDown + bridge).

Step 0: baseline is documented; README and cortex README point to it; no new runtime
contract asserted here (see docs/document_parsing_baseline_step0.md).

Step 1: README + baseline doc describe optional Poetry extra; i18n keys for UI hints;
pyproject contract is covered by tests/test_markitdown_pyproject_extra.py.

Step 2: canonical async bridge module exists; README + baseline doc + i18n reference it;
runtime behavior is covered by tests/test_document_markdown.py (requires markitdown extra).

Step 3: `multi_modal._process_file` wiring documented; i18n + README; behavior in
tests/test_multi_modal_document_path_step3.py (subset skipped without unstructured).

Step 4: intake reuses multimodal document path when `file_path` present; i18n + README;
`tests/test_intake_archive_step4.py` covers `_intake_archive_body_from_payload`.

Step 5: skills docs align to kernel document→Markdown SSOT; i18n `doc.pipeline.step5`;
MarkItDown CLI / pip examples only under explicit dev-only blocks in skills.

Step 6: document parse ops toggles in `config.py`, logger `AdamI-DocumentParse`, i18n `doc.pipeline.step6`;
`tests/test_document_parse_step6_config.py`.

Step 7: `tests/test_markitdown_bridge.py` + CI job `markitdown-bridge`; i18n `doc.pipeline.step7`.

Step 8: README optional-capabilities migration section; no root CHANGELOG; i18n `doc.pipeline.step8`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


# --- Step 0 ---


def test_step0_baseline_doc_exists() -> None:
    p = _root() / "docs" / "document_parsing_baseline_step0.md"
    assert p.is_file(), "Step 0 baseline doc must exist"


@pytest.mark.parametrize(
    "needle",
    [
        "## English",
        "## 中文",
        "`MultiModalInput._process_file`",
        "unstructured",
        "DecisionProcessor",
        "INTAKE",
        "Step 1 (dependencies)",
        "poetry install -E markitdown",
        "## Step 3",
        "MarkItDown-first",
        "Step 4 (intake",
        "_intake_archive_body_from_payload",
    ],
)
def test_step0_baseline_doc_contains_contract_anchors(needle: str) -> None:
    text = (_root() / "docs" / "document_parsing_baseline_step0.md").read_text(encoding="utf-8")
    assert needle in text, f"baseline doc should mention {needle!r}"


def test_step0_readme_links_baseline_doc_twice() -> None:
    readme = (_root() / "README.md").read_text(encoding="utf-8")
    frag = "docs/document_parsing_baseline_step0.md"
    assert readme.count(frag) >= 2, "README should link baseline doc (Quickstart + ops bullet)"


def test_step0_cortex_readme_points_at_baseline_doc() -> None:
    text = (_root() / "src" / "adami_kernel" / "cortex" / "README.md").read_text(encoding="utf-8")
    assert "document_parsing_baseline_step0.md" in text


# --- Step 1 ---


def test_step1_readme_optional_markitdown_quickstart() -> None:
    readme = (_root() / "README.md").read_text(encoding="utf-8")
    assert "poetry install -E markitdown" in readme
    assert "doc.pipeline.step1" in readme
    assert "Default `poetry install`" in readme or "does **not** install MarkItDown" in readme


@pytest.mark.parametrize(
    "locale",
    ["en", "zh-Hans"],
)
def test_step1_i18n_doc_pipeline_step1_present(locale: str) -> None:
    p = _root() / "src" / "adami_kernel" / "i18n" / "locales" / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "doc.pipeline.step0" in data
    assert "doc.pipeline.step1" in data
    assert len(str(data["doc.pipeline.step1"]).strip()) > 20


def test_step1_change_log_mentions_lock_and_i18n() -> None:
    text = (_root() / "docs" / "document_parsing_baseline_step0.md").read_text(encoding="utf-8")
    assert "poetry.lock" in text
    assert "doc.pipeline.step1" in text


# --- Step 2 ---


def test_step2_document_markdown_module_exists() -> None:
    p = _root() / "src" / "adami_kernel" / "cortex" / "document_markdown.py"
    assert p.is_file()


def test_step2_readme_mentions_document_markdown_api() -> None:
    readme = (_root() / "README.md").read_text(encoding="utf-8")
    assert "document_markdown.py" in readme
    assert "doc.pipeline.step2" in readme


def test_step2_baseline_doc_mentions_step2_bridge() -> None:
    text = (_root() / "docs" / "document_parsing_baseline_step0.md").read_text(encoding="utf-8")
    for needle in ("Step 2", "document_markdown.py", "enable_plugins=False"):
        assert needle in text, needle


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
def test_step2_i18n_doc_pipeline_step2_present(locale: str) -> None:
    p = _root() / "src" / "adami_kernel" / "i18n" / "locales" / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "doc.pipeline.step2" in data
    assert len(str(data["doc.pipeline.step2"]).strip()) > 20


def test_step2_change_log_records_step2() -> None:
    text = (_root() / "docs" / "document_parsing_baseline_step0.md").read_text(encoding="utf-8")
    assert "**Step 2**:" in text or "Step 2" in text
    assert "doc.pipeline.step2" in text


def test_step2_cortex_readme_lists_document_markdown() -> None:
    text = (_root() / "src" / "adami_kernel" / "cortex" / "README.md").read_text(encoding="utf-8")
    assert "document_markdown.py" in text
    assert "enable_plugins=False" in text


def test_step2_public_module_importable_without_markitdown_runtime() -> None:
    """Import bridge module without triggering MarkItDown install (lazy import inside workers)."""
    from adami_kernel.cortex import document_markdown as dm

    assert hasattr(dm, "convert_document_path_to_markdown")
    assert hasattr(dm, "convert_document_stream_to_markdown")
    assert hasattr(dm, "DocumentMarkdownFailureReason")
    assert hasattr(dm, "DEFAULT_MARKDOWN_CHAR_BUDGET")
    assert dm.DEFAULT_MARKDOWN_CHAR_BUDGET == 4000


def test_step2_pyproject_dev_reportlab_for_pdf_fixtures() -> None:
    raw = (_root() / "pyproject.toml").read_text(encoding="utf-8")
    assert "reportlab" in raw
    assert "[tool.poetry.group.dev.dependencies]" in raw


# --- Step 3 ---


def test_step3_readme_mentions_multimodal_wiring() -> None:
    readme = (_root() / "README.md").read_text(encoding="utf-8")
    assert "Step 3" in readme or "step3" in readme.lower()
    assert "doc.pipeline.step3" in readme


def test_step3_i18n_doc_pipeline_step3_present() -> None:
    for locale in ("en", "zh-Hans"):
        p = _root() / "src" / "adami_kernel" / "i18n" / "locales" / locale / "common.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "doc.pipeline.step3" in data
        assert "mmmd.log.markitdown_unavailable" in data
        assert "mmmd.log.file_markdown" in data
        assert "mmmd.warn.markitdown_fallback" in data
        assert "mmodal.file.missing_unstructured" in data
        assert "markitdown" in str(data["mmodal.file.missing_unstructured"]).lower()


def test_step3_multi_modal_imports_document_markdown_bridge() -> None:
    text = (_root() / "src" / "adami_kernel" / "cortex" / "multi_modal.py").read_text(
        encoding="utf-8"
    )
    for needle in (
        "convert_document_path_to_markdown",
        "normalized_allowed_extension",
        "DocumentMarkdownFailureReason.NOT_INSTALLED",
        "mmmd.log.file_markdown",
    ):
        assert needle in text, needle


def test_step3_integration_test_module_exists() -> None:
    assert (_root() / "tests" / "test_multi_modal_document_path_step3.py").is_file()


def test_step3_change_log_lists_multi_modal_tests() -> None:
    text = (_root() / "docs" / "document_parsing_baseline_step0.md").read_text(encoding="utf-8")
    assert "test_multi_modal_document_path_step3.py" in text
    assert "mmmd.warn.markitdown_fallback" in text


# --- Step 4 ---


def test_step4_readme_mentions_intake_markdown() -> None:
    readme = (_root() / "README.md").read_text(encoding="utf-8")
    assert "doc.pipeline.step4" in readme
    assert "file_path" in readme


def test_step4_i18n_keys_present() -> None:
    for locale in ("en", "zh-Hans"):
        p = _root() / "src" / "adami_kernel" / "i18n" / "locales" / locale / "common.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "doc.pipeline.step4" in data
        assert "dcpu.log.intake_markdown" in data
        assert "dcpu.warn.intake_doc_extract" in data


def test_step4_decision_processor_defines_intake_helper() -> None:
    text = (_root() / "src" / "adami_kernel" / "cortex" / "decision_processor.py").read_text(
        encoding="utf-8"
    )
    text_sup = (
        _root() / "src" / "adami_kernel" / "cortex" / "decision_processor_support.py"
    ).read_text(encoding="utf-8")
    assert "_intake_archive_body_from_payload" in text
    assert "async def _intake_archive_body_from_payload" in text_sup
    assert "INTAKE_AUTO" in text and 'data in ("INTAKE", "INTAKE_AUTO")' in text


def test_step4_intake_unit_tests_exist() -> None:
    assert (_root() / "tests" / "test_intake_archive_step4.py").is_file()


def test_step4_change_log_lists_intake_test_module() -> None:
    text = (_root() / "docs" / "document_parsing_baseline_step0.md").read_text(encoding="utf-8")
    assert "test_intake_archive_step4.py" in text
    assert "doc.pipeline.step4" in text


def test_step4_process_routes_intake_before_multimodal_detection() -> None:
    text = (_root() / "src" / "adami_kernel" / "cortex" / "decision_processor.py").read_text(
        encoding="utf-8"
    )
    i_intake = text.find('tag == "SYSTEM_ACTION" and data in ("INTAKE", "INTAKE_AUTO")')
    i_mm = text.find("_detect_multimodal_intent")
    assert 0 < i_intake < i_mm, "INTAKE must be dispatched before multimodal branch"


def test_step4_handle_intake_sets_yaml_markdown_hints() -> None:
    text = (_root() / "src" / "adami_kernel" / "cortex" / "decision_processor.py").read_text(
        encoding="utf-8"
    )
    assert "body_format: markdown" in text
    assert "source_file:" in text


def test_step4_cortex_readme_mentions_intake_multimodal_reuse() -> None:
    text = (_root() / "src" / "adami_kernel" / "cortex" / "README.md").read_text(encoding="utf-8")
    assert "process_input" in text and "document" in text
    assert "doc.pipeline.step4" in text


# --- Step 5 ---


def test_step5_readme_mentions_skills_ssot() -> None:
    readme = (_root() / "README.md").read_text(encoding="utf-8")
    assert "doc.pipeline.step5" in readme
    assert "skills/" in readme
    assert "convert_document_path_to_markdown" in readme


def test_step5_i18n_keys_present() -> None:
    for locale in ("en", "zh-Hans"):
        p = _root() / "src" / "adami_kernel" / "i18n" / "locales" / locale / "common.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "doc.pipeline.step5" in data
        assert len(str(data["doc.pipeline.step5"]).strip()) > 20


def test_step5_baseline_doc_lists_step5() -> None:
    text = (_root() / "docs" / "document_parsing_baseline_step0.md").read_text(encoding="utf-8")
    assert "## Step 5" in text
    assert "doc.pipeline.step5" in text
    assert "skills/skills/pptx" in text


def test_step5_cortex_readme_mentions_skills_ssot() -> None:
    text = (_root() / "src" / "adami_kernel" / "cortex" / "README.md").read_text(encoding="utf-8")
    assert "doc.pipeline.step5" in text
    assert "document_markdown" in text


def test_step5_skills_markitdown_cli_only_in_pptx_dev_block() -> None:
    """MarkItDown CLI under skills/ is dev-only (pptx SKILL), not production guidance."""
    skills_root = _root() / "skills"
    cli_hits: list[str] = []
    for path in skills_root.rglob("*"):
        if not path.is_file() or path.suffix not in {".md", ".txt"}:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "python -m markitdown" in body:
            cli_hits.append(str(path.relative_to(_root())))
    assert cli_hits == ["skills/skills/pptx/SKILL.md"], cli_hits
    skill_md = (_root() / "skills" / "skills" / "pptx" / "SKILL.md").read_text(encoding="utf-8")
    dev_i = skill_md.find("## Dev-only: MarkItDown CLI")
    assert dev_i >= 0
    assert skill_md.find("python -m markitdown") > dev_i


def test_step5_skills_pip_markitdown_only_in_pptx_dev_block() -> None:
    skills_root = _root() / "skills"
    pip_hits: list[str] = []
    pat = re.compile(r"pip\s+install.*markitdown", re.IGNORECASE)
    for path in skills_root.rglob("*"):
        if not path.is_file() or path.suffix not in {".md", ".txt"}:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if pat.search(body):
            pip_hits.append(str(path.relative_to(_root())))
    assert pip_hits == ["skills/skills/pptx/SKILL.md"], pip_hits
    skill_md = (_root() / "skills" / "skills" / "pptx" / "SKILL.md").read_text(encoding="utf-8")
    dev_i = skill_md.find("## Dev-only: MarkItDown CLI")
    assert dev_i >= 0
    assert pat.search(skill_md, pos=dev_i) is not None


# --- Step 6 ---


def test_step6_readme_mentions_ops_toggles() -> None:
    readme = (_root() / "README.md").read_text(encoding="utf-8")
    assert "doc.pipeline.step6" in readme
    assert "ADAMI_MARKITDOWN_ENABLED" in readme
    assert "AdamI-DocumentParse" in readme


def test_step6_i18n_keys_present() -> None:
    for locale in ("en", "zh-Hans"):
        p = _root() / "src" / "adami_kernel" / "i18n" / "locales" / locale / "common.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "doc.pipeline.step6" in data
        assert "mmmd.log.markitdown_disabled" in data
        assert len(str(data["doc.pipeline.step6"]).strip()) > 20


def test_step6_baseline_doc_lists_step6() -> None:
    text = (_root() / "docs" / "document_parsing_baseline_step0.md").read_text(encoding="utf-8")
    assert "## Step 6" in text
    assert "ADAMI_DOCUMENT_MARKDOWN_MAX_INPUT_BYTES" in text
    assert "test_document_parse_step6_config.py" in text


def test_step6_config_py_declares_settings_fields() -> None:
    text = (_root() / "src" / "adami_kernel" / "config.py").read_text(encoding="utf-8")
    assert "ADAMI_MARKITDOWN_ENABLED" in text
    assert "ADAMI_DOCUMENT_MARKDOWN_TIMEOUT_SEC" in text
    assert "def markitdown_effective_enabled" in text


def test_step6_cortex_readme_mentions_document_parse_ops() -> None:
    text = (_root() / "src" / "adami_kernel" / "cortex" / "README.md").read_text(encoding="utf-8")
    assert "doc.pipeline.step6" in text
    assert "AdamI-DocumentParse" in text


def test_step6_document_markdown_uses_document_parse_logger() -> None:
    text = (_root() / "src" / "adami_kernel" / "cortex" / "document_markdown.py").read_text(
        encoding="utf-8"
    )
    assert 'getLogger("AdamI-DocumentParse")' in text
    assert "[doc.parse] route=" in text


# --- Step 7 ---


def test_step7_bridge_test_module_exists() -> None:
    assert (_root() / "tests" / "test_markitdown_bridge.py").is_file()


def test_step7_readme_mentions_bridge_ci() -> None:
    readme = (_root() / "README.md").read_text(encoding="utf-8")
    assert "doc.pipeline.step7" in readme
    assert "test_markitdown_bridge.py" in readme
    assert "markitdown-bridge" in readme


def test_step7_ci_workflow_declares_markitdown_bridge_job() -> None:
    wf = (_root() / ".github" / "workflows" / "kernel-ci.yml").read_text(encoding="utf-8")
    assert "markitdown-bridge:" in wf
    assert "tests/test_markitdown_bridge.py" in wf
    root_ci = (_root() / "ci.yml").read_text(encoding="utf-8")
    assert "markitdown-bridge:" in root_ci


def test_step7_i18n_keys_present() -> None:
    for locale in ("en", "zh-Hans"):
        p = _root() / "src" / "adami_kernel" / "i18n" / "locales" / locale / "common.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "doc.pipeline.step7" in data
        assert len(str(data["doc.pipeline.step7"]).strip()) > 20


def test_step7_baseline_doc_lists_step7() -> None:
    text = (_root() / "docs" / "document_parsing_baseline_step0.md").read_text(encoding="utf-8")
    assert "## Step 7" in text
    assert "test_markitdown_bridge.py" in text
    assert "markitdown-bridge" in text


def test_step7_pyproject_registers_marker() -> None:
    text = (_root() / "pyproject.toml").read_text(encoding="utf-8")
    assert "markitdown_bridge" in text


# --- Step 8 ---


def test_step8_readme_has_optional_capabilities_section() -> None:
    readme = (_root() / "README.md").read_text(encoding="utf-8")
    assert "doc.pipeline.step8" in readme
    assert "Optional capabilities — document pipeline" in readme
    assert "ADAMI_MARKITDOWN_ENABLED=False" in readme
    assert "poetry install -E markitdown" in readme


def test_step8_no_changelog_file_convention_documented() -> None:
    assert not (_root() / "CHANGELOG.md").is_file()
    assert not (_root() / "CHANGELOG").is_file()
    readme = (_root() / "README.md").read_text(encoding="utf-8")
    assert "CHANGELOG" in readme and "no root" in readme.lower()


def test_step8_i18n_keys_present() -> None:
    for locale in ("en", "zh-Hans"):
        p = _root() / "src" / "adami_kernel" / "i18n" / "locales" / locale / "common.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "doc.pipeline.step8" in data
        assert len(str(data["doc.pipeline.step8"]).strip()) > 30


def test_step8_baseline_doc_lists_step8() -> None:
    text = (_root() / "docs" / "document_parsing_baseline_step0.md").read_text(encoding="utf-8")
    assert "## Step 8" in text
    assert "Optional capabilities" in text
    assert "doc.pipeline.step8" in text


def test_step8_cortex_readme_mentions_release_migration() -> None:
    text = (_root() / "src" / "adami_kernel" / "cortex" / "README.md").read_text(encoding="utf-8")
    assert "doc.pipeline.step8" in text
    assert "CHANGELOG" in text
