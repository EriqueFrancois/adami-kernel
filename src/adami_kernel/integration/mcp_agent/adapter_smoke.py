"""Smoke CLI: ``MCPApp.run()`` → ``Agent`` → ``attach_llm`` → ``generate_str`` (one turn).

Requires ``poetry install -E mcp-agent``, valid ``ADAMI_MCP_SERVERS_JSON`` (Docker specs),
and (for ``--llm-mode openai``) provider API keys per mcp-agent Settings.

Usage::

    adami-mcp-agent-smoke
    adami-mcp-agent-smoke "Call the echo tool with message hello"
    adami-mcp-agent-smoke --llm-mode router_hybrid "Say hi in one sentence"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import cast


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(_async_main()))


async def _async_main() -> int:
    parser = argparse.ArgumentParser(description="mcp-agent adapter smoke (one generate_str turn)")
    parser.add_argument(
        "prompt",
        nargs="?",
        default=(
            "List the MCP tools you can use, then invoke any simple echo or ping tool once "
            "with a short test string. Summarize what happened."
        ),
    )
    parser.add_argument(
        "--llm-mode",
        choices=["openai", "router_hybrid"],
        default="openai",
        help="openai: full tool loop via OpenAIAugmentedLLM; router_hybrid: text fallback when no tools",
    )
    args = parser.parse_args()

    try:
        from adami_kernel.integration.mcp_agent.adapter import (
            LLMMode,
            run_single_turn_with_agent_llm,
        )
    except ImportError as e:
        print(f"SKIP: adapter import failed ({e})", file=sys.stderr)
        return 0

    prompt: str = args.prompt
    llm_mode = cast(LLMMode, args.llm_mode)
    try:
        if args.llm_mode == "router_hybrid":
            from adami_kernel.cortex.router import HybridLLMRouter

            out = await run_single_turn_with_agent_llm(
                prompt,
                llm_mode=llm_mode,
                router=HybridLLMRouter(),
            )
        else:
            out = await run_single_turn_with_agent_llm(prompt, llm_mode=llm_mode)
    except RuntimeError as e:
        if "mcp-agent not installed" in str(e) or "No MCP servers" in str(e):
            print(f"SKIP: {e}", file=sys.stderr)
            return 0
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(out)
    return 0


if __name__ == "__main__":
    main()
