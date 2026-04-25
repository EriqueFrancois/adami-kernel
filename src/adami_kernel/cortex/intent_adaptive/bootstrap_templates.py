# src/adami_kernel/cortex/intent_adaptive/bootstrap_templates.py
"""Register built-in Step 6 preset handlers on a ``TemplateRegistry`` (kernel bootstrap).

Only **production** retrieval templates are registered here (``retrieval.weather``,
``retrieval.crypto``). Some planning docs mentioned a throwaway ``retrieval_echo`` demo
handler; it was **never** shipped in this tree—do not add an unmarked demo handler to
bootstrap without an explicit product decision. If a dev-only demo is ever needed, tag the
module with ``# dev-only demo handler`` at the top and keep it **out** of this function
unless the team opts in.
"""

from __future__ import annotations

from adami_kernel.cortex.intent_adaptive.models import IntentType
from adami_kernel.cortex.intent_adaptive.template_registry import TemplateRegistry
from adami_kernel.cortex.intent_adaptive.templates.retrieval_crypto import (
    RetrievalCryptoTemplateHandler,
)
from adami_kernel.cortex.intent_adaptive.templates.retrieval_weather import (
    RetrievalWeatherTemplateHandler,
)


def register_builtin_intent_templates(registry: TemplateRegistry) -> None:
    """Wire thin retrieval templates (weather + crypto). Safe to call once at init."""
    registry.register(IntentType.RETRIEVAL_WEATHER, RetrievalWeatherTemplateHandler())
    registry.register(IntentType.RETRIEVAL_CRYPTO, RetrievalCryptoTemplateHandler())
