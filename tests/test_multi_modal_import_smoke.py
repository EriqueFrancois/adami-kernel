"""multi_modal must import without HuggingFace transformers installed."""

from __future__ import annotations


def test_multi_modal_module_imports() -> None:
    import adami_kernel.cortex.multi_modal as mm

    assert hasattr(mm, "TRANSFORMERS_AVAILABLE")
    assert hasattr(mm, "MultiModalInput")
