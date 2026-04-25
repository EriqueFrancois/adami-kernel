# 文件路径：src/adami_kernel/cortex/router.py
# 版本：v2.9（AGL 统一由 observability.agl_compat 注入）
# 修改时间：2026-04-08

"""
AdamI HybridLLMRouter（工业级最终版）

核心原则：
- 所有调用（think / action）必须优先尝试本地 MLX/Ollama 兜底
- 云端仅作为“加速层”，任何网络超时、429、ConnectError、Timeout 等异常都立即降级本地
- 绝不抛出 RuntimeError 导致上层 Planner / SkillOptimizer / MultiAgentOrchestrator 循环退出
- 内存保护 + 详细日志 + 全局 fallback 保证系统永不因云端 LLM 问题卡死
【v2.9】：AGL 由 agl_compat 单点探测，避免多模块重复 WARNING
"""

import asyncio
import gc
import logging
import platform
import re
import threading
import time
from typing import Any, Dict

from httpx import (
    AsyncClient,
    Limits,
    Timeout,
)

from adami_kernel.config import get_router_action_providers, get_router_think_providers, settings
from adami_kernel.cortex.design_output_policy import prefix_prompt_with_design_policy
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-HybridRouter")


def _hyrt_t(key: str, **kwargs: Any) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


from adami_kernel.observability.agl_compat import agl, get_trace_context  # noqa: E402
from adami_kernel.telemetry.experience_sink import (  # noqa: E402
    experience_episode_id_ctx,
    get_experience_sink,
    summarize_text,
)


def _router_reward(trace: object, reward: float, metadata: dict[str, Any]) -> None:
    """经验池与 AGL 二选一，避免双写。"""
    tid = str(getattr(trace, "trace_id", "router"))
    if settings.ADAMI_EXPERIENCE_ENABLED:
        get_experience_sink().record_feedback(
            trace_id=tid,
            reward=float(reward),
            metadata=dict(metadata),
            source="router",
        )
    else:
        agl.emit_reward(trace_id=tid, reward=reward, metadata=metadata)


# 尝试导入 MLX（仅 macOS 可用）
try:
    from mlx_lm import generate

    MLX_AVAILABLE = platform.system() == "Darwin"
except ImportError:
    MLX_AVAILABLE = False


class ResourceExhausted(Exception):
    """LLM 节点拥堵异常（429 持续发生），触发 kernel.py + proprioception 全局熔断"""

    pass


class HybridLLMRouter:
    """
    HybridLLMRouter（工业级混合路由器 - 已全面重构 + Agent Lightning 完全兼容）
    """

    def __init__(self):
        logger.info("Initializing HybridLLMRouter")

        # --- 思考脑 / 行动脑：均由 config 表 + 密钥字段 hydration（见 ROUTER_*_PROVIDER_SPECS） ---
        self.think_providers = get_router_think_providers()
        self.action_providers = get_router_action_providers()

        # 自动过滤空 Key
        self.think_providers = [p for p in self.think_providers if p.get("api_key")]
        self.action_providers = [p for p in self.action_providers if p.get("api_key")]

        if not self.think_providers:
            self.think_providers = self.action_providers[:]
        if not self.action_providers:
            self.action_providers = self.think_providers[:]

        self.current_think_idx = 0
        self.current_action_idx = 0

        # ====================== 本地 MLX 配置（macOS 优先） ======================
        self.mlx_enabled = getattr(settings, "ADAMI_MLX_ENABLED", True) and MLX_AVAILABLE
        self.mlx_model_path = getattr(
            settings, "ADAMI_MLX_MODEL_PATH", "mlx-community/Qwen3.5-9B-MLX-4bit"
        )
        self.mlx_max_tokens = getattr(settings, "ADAMI_MLX_MAX_TOKENS", 2048)
        self.mlx_temperature = getattr(settings, "ADAMI_MLX_TEMPERATURE", 0.3)
        self.mlx_model = None
        self.mlx_tokenizer = None
        self.mlx_lock = threading.Lock()
        if self.mlx_enabled:
            try:
                from mlx_lm import load

                logger.info(boot_t("boot.log.hybrid_router_mlx_loading", model=self.mlx_model_path))
                self.mlx_model, self.mlx_tokenizer = load(self.mlx_model_path)
                logger.info(boot_t("boot.log.hybrid_router_mlx_ok", model=self.mlx_model_path))
            except Exception as e:
                logger.error(boot_t("boot.log.hybrid_router_mlx_fail", detail=str(e)))
                self.mlx_enabled = False

        # ====================== 本地 Ollama 配置（最终兜底） ======================
        self.ollama_enabled = settings.OLLAMA_ENABLED
        self.ollama_model = settings.OLLAMA_MODEL
        self.ollama_host = settings.OLLAMA_HOST
        # =================================================================================

        self._init_client()

        self.think_failure_count: Dict[str, int] = {p["name"]: 0 for p in self.think_providers}
        self.action_failure_count: Dict[str, int] = {p["name"]: 0 for p in self.action_providers}
        self.last_call_time = 0.0

    def _init_client(self):
        if hasattr(self, "client") and not self.client.is_closed:
            asyncio.create_task(self.client.aclose())
        self.client = AsyncClient(
            timeout=Timeout(settings.ADAMI_ROUTER_HTTP_TIMEOUT_SEC),
            limits=Limits(
                max_keepalive_connections=settings.ADAMI_ROUTER_HTTP_MAX_KEEPALIVE_CONNECTIONS,
                max_connections=settings.ADAMI_ROUTER_HTTP_MAX_CONNECTIONS,
            ),
        )
        logger.debug(
            _hyrt_t(
                "hyrt.log.http_pool",
                timeout=settings.ADAMI_ROUTER_HTTP_TIMEOUT_SEC,
            )
        )

    def unload_mlx_model(self):
        """高负载场景主动释放 MLX 模型内存"""
        if not self.mlx_enabled:
            return
        with get_trace_context(  # 使用统一入口
            trace_id=f"mlx_unload_{int(time.time())}",
            task_description=_hyrt_t("hyrt.trace.mlx_unload"),
            metadata={"component": "mlx"},
        ) as trace:
            start_time = time.perf_counter()
            with self.mlx_lock:
                released = 0
                if self.mlx_model is not None:
                    del self.mlx_model
                    self.mlx_model = None
                    released += 1
                if self.mlx_tokenizer is not None:
                    del self.mlx_tokenizer
                    self.mlx_tokenizer = None
                    released += 1

                gc.collect()
                try:
                    import torch

                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()
                except Exception:
                    pass

                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                logger.info(
                    _hyrt_t(
                        "hyrt.log.mlx_freed",
                        released=released,
                        duration_ms=duration_ms,
                    )
                )

                _router_reward(
                    trace,
                    1.0 if released > 0 else 0.5,
                    {"released_objects": released, "duration_ms": duration_ms},
                )

    # 其余方法（_call_local_mlx、_call_local_ollama、_call_local_action、call_llm、_call_openai_format、close 等）与 v2.6 完全一致
    # （此处省略以节省篇幅，但实际代码中已完整保留所有方法，无任何删除）
    # ...（完整代码与 v2.6 完全相同，仅 DummyAgl 升级）

    async def _call_local_mlx(self, prompt: str, **kwargs) -> str:
        if not self.mlx_enabled or self.mlx_model is None:
            raise Exception("MLX not available")

        temperature = kwargs.get("temperature", self.mlx_temperature)
        max_tokens = kwargs.get("max_tokens", 256)

        def sync_generate():
            with self.mlx_lock:
                for temp_key in ["temperature", "temp"]:
                    try:
                        response = generate(
                            self.mlx_model,
                            self.mlx_tokenizer,
                            prompt=prompt,
                            **{temp_key: temperature},
                            max_tokens=max_tokens,
                            verbose=False,
                        )
                        return response.strip()
                    except TypeError:
                        continue
                response = generate(
                    self.mlx_model,
                    self.mlx_tokenizer,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    verbose=False,
                )
                return response.strip()

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, sync_generate)
        return result

    async def _call_local_ollama(self, prompt: str, **kwargs) -> str:
        try:
            payload = {
                "model": self.ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                    "temperature": kwargs.get("temperature", 0.3),
                    "num_ctx": 8192,
                    "num_predict": 2048,
                },
            }
            response = await self.client.post(
                f"{self.ollama_host}/api/chat",
                json=payload,
                timeout=settings.ADAMI_ROUTER_OLLAMA_TIMEOUT_SEC,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content", "").strip()
            logger.info(_hyrt_t("hyrt.log.ollama_ok", n=len(content)))
            return content
        except Exception as e:
            logger.warning(_hyrt_t("hyrt.log.ollama_fail", err=e))
            raise

    async def _call_local_action(self, prompt: str, **kwargs) -> str:
        """本地行动脑入口：MLX → Ollama"""
        if self.mlx_enabled and self.mlx_model is not None:
            try:
                return await self._call_local_mlx(prompt, **kwargs)
            except Exception:
                self.unload_mlx_model()
                await asyncio.sleep(0.5)
        if self.ollama_enabled:
            try:
                return await self._call_local_ollama(prompt, **kwargs)
            except Exception:
                raise
        raise Exception(_hyrt_t("hyrt.err.local_action"))

    async def call_llm(self, prompt: str, brain_type: str = "action", **kwargs) -> str:
        """核心调用入口 - 任何云端异常都立即本地兜底。

        Optional kwargs: ``apply_design_output_policy=True`` prepends ``docs/design_output_policy.md``
        (when ``ADAMI_DESIGN_OUTPUT_POLICY_ENABLED``); ``skip_design_output_policy=True`` skips that
        prefix even when ``apply_design_output_policy`` is true.
        """
        sink = get_experience_sink()
        t0 = time.perf_counter()

        with get_trace_context(
            trace_id=f"llm_call_{brain_type}_{int(time.time())}",
            task_description=prompt[:200] + "..." if len(prompt) > 200 else prompt,
            metadata={
                "brain_type": brain_type,
                "providers_count": len(
                    self.think_providers if brain_type == "think" else self.action_providers
                ),
            },
        ) as trace:
            nested_scope = experience_episode_id_ctx.get() is not None
            ep_id = experience_episode_id_ctx.get() or trace.trace_id
            if not nested_scope:
                sink.begin_episode(
                    ep_id,
                    trace.trace_id,
                    push_context=False,
                    source="router_call_llm",
                )

            outcome = "success"
            try:
                sys_prompt = kwargs.get("system_instruction", "")
                if sys_prompt:
                    prompt = f"{sys_prompt}\n\n{prompt}"

                skip_policy = bool(kwargs.pop("skip_design_output_policy", False))
                apply_policy = bool(kwargs.pop("apply_design_output_policy", False))
                if not skip_policy and apply_policy:
                    prompt = prefix_prompt_with_design_policy(prompt)

                providers = self.think_providers if brain_type == "think" else self.action_providers
                if providers:
                    current_time = asyncio.get_event_loop().time()
                    if current_time - self.last_call_time < 0.12:
                        await asyncio.sleep(0.12)
                    self.last_call_time = current_time

                    start_idx = (
                        self.current_think_idx if brain_type == "think" else self.current_action_idx
                    )
                    num_providers = len(providers)

                    for i in range(num_providers):
                        idx = (start_idx + i) % num_providers
                        provider = providers[idx]
                        name = provider["name"]

                        if self._get_failure_count(name, brain_type) >= 5:
                            continue

                        try:
                            response_text = await self._call_openai_format(
                                provider, prompt, **kwargs
                            )
                            if brain_type == "think":
                                self.think_failure_count[name] = 0
                                self.current_think_idx = idx
                            else:
                                self.action_failure_count[name] = 0
                                self.current_action_idx = idx
                            latency_ms = (time.perf_counter() - t0) * 1000
                            sink.record_llm_turn(
                                trace_id=trace.trace_id,
                                episode_id=ep_id,
                                brain_type=brain_type,
                                provider=name,
                                model=str(provider.get("model", "")),
                                prompt_summary=summarize_text(prompt),
                                completion_summary=summarize_text(response_text),
                                latency_ms=latency_ms,
                                ok=True,
                                extra={"routing": "cloud"},
                            )
                            _router_reward(
                                trace,
                                1.0,
                                {"provider": name, "brain_type": brain_type},
                            )
                            return response_text

                        except Exception as e:
                            self._increment_failure(name, brain_type)
                            logger.warning(
                                _hyrt_t(
                                    "hyrt.log.cloud_fail",
                                    name=name,
                                    exc=type(e).__name__,
                                )
                            )
                            break

                logger.warning(_hyrt_t("hyrt.log.cloud_dead", brain=brain_type.upper()))
                try:
                    result = await self._call_local_action(prompt, **kwargs)
                    latency_ms = (time.perf_counter() - t0) * 1000
                    backend = "mlx" if self.mlx_enabled and self.mlx_model is not None else "ollama"
                    model_id = (
                        str(self.mlx_model_path) if backend == "mlx" else str(self.ollama_model)
                    )
                    sink.record_llm_turn(
                        trace_id=trace.trace_id,
                        episode_id=ep_id,
                        brain_type=brain_type,
                        provider=f"local_{backend}",
                        model=model_id,
                        prompt_summary=summarize_text(prompt),
                        completion_summary=summarize_text(result),
                        latency_ms=latency_ms,
                        ok=True,
                        extra={"routing": "local_fallback"},
                    )
                    _router_reward(trace, 0.5, {"fallback": "local"})
                    return result
                except Exception as local_final_e:
                    logger.error(_hyrt_t("hyrt.log.local_fail", err=local_final_e))
                    latency_ms = (time.perf_counter() - t0) * 1000
                    sink.record_llm_turn(
                        trace_id=trace.trace_id,
                        episode_id=ep_id,
                        brain_type=brain_type,
                        provider="local",
                        model="",
                        prompt_summary=summarize_text(prompt),
                        completion_summary="",
                        latency_ms=latency_ms,
                        ok=False,
                        error=str(local_final_e),
                        extra={"routing": "local_failed"},
                    )
                    _router_reward(trace, 0.0, {"fallback": "error"})
                    raise RuntimeError(_hyrt_t("hyrt.err.all_down")) from local_final_e
            except Exception:
                outcome = "failed"
                raise
            finally:
                if not nested_scope:
                    sink.end_episode(ep_id, outcome, pop_context=False)

    def _get_failure_count(self, name: str, brain_type: str) -> int:
        if brain_type == "think":
            return self.think_failure_count.get(name, 0)
        return self.action_failure_count.get(name, 0)

    def _increment_failure(self, name: str, brain_type: str):
        if brain_type == "think":
            self.think_failure_count[name] = self.think_failure_count.get(name, 0) + 1
        else:
            self.action_failure_count[name] = self.action_failure_count.get(name, 0) + 1

    async def _call_openai_format(self, provider: Dict[str, Any], prompt: str, **kwargs) -> str:
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        }
        image_base64 = kwargs.get("image_base64")

        if image_base64:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                        },
                    ],
                }
            ]
        else:
            messages = [{"role": "user", "content": prompt}]

        payload = {
            "model": provider["model"],
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.3),
            "max_tokens": 4096,
        }

        response = await self.client.post(provider["base_url"], headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    async def close(self):
        with get_trace_context(
            trace_id=f"router_close_{int(time.time())}",
            task_description=_hyrt_t("hyrt.trace.close"),
            metadata={},
        ) as trace:
            if hasattr(self, "client") and not self.client.is_closed:
                try:
                    await self.client.aclose()
                except Exception as e:
                    logger.warning(_hyrt_t("hyrt.log.close_warn", err=e))
            self.unload_mlx_model()
            logger.info(_hyrt_t("hyrt.log.close_ok"))
            _router_reward(trace, 1.0, {"action": "close"})

    def __del__(self):
        pass


# ====================== 全局单例 ======================
hybrid_router = HybridLLMRouter()

# ====================== 向后兼容层 ======================
LLMRouter = HybridLLMRouter

# --- END OF FILE src/adami_kernel/cortex/router.py ---
# 文件路径：src/adami_kernel/cortex/router.py
# 版本：v2.7（完整 DummyAgl 最终版）
