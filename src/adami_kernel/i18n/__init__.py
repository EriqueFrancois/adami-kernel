"""AdamI i18n (Module 6).

Public API is intentionally small:
- ``Translator`` loads JSON catalogs with fallback.
- ``t`` is a module-level helper bound to the default translator.

步骤 6 翻译模块请使用 ``adami_kernel.i18n.translate``（不在此包 ``__init__`` 中导入，
避免 ``config`` 初始化与 ``i18n.locale_utils`` 的循环依赖）。
"""

from adami_kernel.i18n.catalog import Translator, default_translator, set_default_translator, t

__all__ = ["Translator", "default_translator", "set_default_translator", "t"]
