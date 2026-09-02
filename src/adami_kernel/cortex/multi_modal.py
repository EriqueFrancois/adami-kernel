# --- START OF FILE multi_modal.py ---

import asyncio
import base64
import logging
import os
import warnings
from typing import Any, Dict

import aiohttp

# ====================== 统一配置中心 ======================
from adami_kernel.config import markitdown_effective_enabled, settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

# ==========================================================


def _mm_t(key: str, **kwargs: Any) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


# === 彻底静音所有 HF Warning（transformers 为可选依赖）===
warnings.filterwarnings("ignore")

logger = logging.getLogger("AdamI-MultiModal")
parse_logger = logging.getLogger("AdamI-DocumentParse")

TORCH_AVAILABLE = False
try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    # Optional dependency: vision path is disabled without torch; avoid WARNING spam in default installs.
    logger.debug(boot_t("boot.log.multimodal_torch_missing"))

TRANSFORMERS_AVAILABLE = False
if TORCH_AVAILABLE:
    try:
        from transformers import logging as hf_logging

        hf_logging.set_verbosity_error()
        TRANSFORMERS_AVAILABLE = True
    except ImportError:
        logger.debug(boot_t("boot.log.multimodal_transformers_missing"))


class MultiModalInput:
    """
    AdamI 多模态输入统一处理器（工业级线程安全版）
    【修复 1】：将 HuggingFace 视觉推理与 Unstructured 文档解析丢入 ThreadPool，消除事件循环阻塞 (系统假死)。
    【修复 2】：引入 torch.no_grad()，大幅降低推理时的内存/显存开销。
    【修复 3】：为本地解析增加严格的超时熔断机制。
    """

    def __init__(self, router, toolbox):
        self.router = router
        self.toolbox = toolbox
        self.memory = None

        self.whisper_available = False
        self.vision_available = False
        self.unstructured_available = False

        self.blip_processor = None
        self.blip_model = None
        self._blip_loaded = False

        # ====================== 语音核心配置 ======================
        self.openai_api_key = getattr(settings, "OPENAI_API_KEY", None)
        if self.openai_api_key:
            self.whisper_available = True
            logger.info(boot_t("boot.log.multimodal_whisper_ready"))
        else:
            logger.warning(boot_t("boot.log.multimodal_whisper_no_key"))
        # ============================================================

        try:
            self.unstructured_available = True
        except ImportError:
            pass

        self.vision_available = True

    async def _lazy_load_blip(self):
        if self._blip_loaded:
            return True
        try:
            await asyncio.to_thread(self._load_blip_sync)
            self._blip_loaded = True
            logger.info(boot_t("boot.log.multimodal_blip_ok"))
            return True
        except Exception as e:
            logger.error(_mm_t("mmmd.err.blip_load", e=str(e)))
            self.vision_available = False
            return False

    def _load_blip_sync(self):
        """同步加载模型（已放入后台线程）"""
        if not TRANSFORMERS_AVAILABLE or not TORCH_AVAILABLE:
            raise RuntimeError("transformers/torch not available for BLIP")
        from transformers import BlipForConditionalGeneration, BlipProcessor

        self.blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        self.blip_model = BlipForConditionalGeneration.from_pretrained(
            "Salesforce/blip-image-captioning-base"
        )

        # 针对 macOS 的加速适配 (MPS 或 CPU)
        if torch.backends.mps.is_available():
            device = torch.device("mps")
            device_name = "Apple Silicon (MPS)"
        elif torch.cuda.is_available():
            device = torch.device("cuda")
            device_name = torch.cuda.get_device_name(0)
        else:
            device = torch.device("cpu")
            device_name = "CPU"

        self.blip_model = self.blip_model.to(device)
        self.blip_model.eval()
        logger.info(_mm_t("mmmd.log.blip_moved", dev=device_name))

    async def process_input(self, media_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """主路由口"""
        filename = payload.get("file_name", "").lower()

        # 强化语音路由：根据扩展名强制修正类型
        if media_type == "voice" or filename.endswith((".ogg", ".mp3", ".wav", ".m4a", ".opus")):
            logger.info(_mm_t("mmmd.log.audio_file", name=filename or "unknown"))
            return await self._process_voice(payload)

        elif media_type == "photo":
            return await self._process_image(payload)

        elif media_type == "document":
            return await self._process_file(payload)

        else:
            return {
                "type": "text",
                "content": payload.get("task", ""),
                "task": payload.get("task", ""),
            }

    async def _process_voice(self, payload: Dict) -> Dict:
        """Whisper API 调用（网络 I/O 已经是 async 的，无需扔进 ThreadPool）"""
        if not self.whisper_available or not self.openai_api_key:
            return {
                "type": "text",
                "content": _mm_t("mmodal.voice.no_api_key"),
                "task": "",
            }

        file_path = payload.get("file_path")
        if not file_path or not os.path.exists(file_path):
            return {"type": "text", "content": _mm_t("mmodal.voice.bad_path"), "task": ""}

        try:
            timeout = aiohttp.ClientTimeout(total=45)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 修复文件描述符泄露：使用 with open 安全读取
                with open(file_path, "rb") as audio_file:
                    form = aiohttp.FormData()
                    form.add_field(
                        "file",
                        audio_file,
                        filename=os.path.basename(file_path),
                        content_type="audio/ogg",
                    )
                    form.add_field("model", "whisper-1")

                    headers = {"Authorization": f"Bearer {self.openai_api_key}"}
                    async with session.post(
                        "https://api.openai.com/v1/audio/transcriptions", data=form, headers=headers
                    ) as resp:
                        resp.raise_for_status()
                        data = await resp.json()
                        transcribed_text = data.get("text", _mm_t("mmodal.voice.no_text"))

            if self.memory:
                await self.memory.store_experience(
                    "multi_modal",
                    "voice_raw",
                    {"text": transcribed_text, "timestamp": asyncio.get_event_loop().time()},
                )

            logger.info(_mm_t("mmmd.log.asr_ok", n=len(transcribed_text)))
            return {
                "type": "text",
                "content": transcribed_text,
                "task": _mm_t("mmodal.voice.task_prefix", snippet=transcribed_text[:200]),
            }

        except asyncio.TimeoutError:
            logger.error(_mm_t("mmmd.err.asr_timeout"))
            return {"type": "text", "content": _mm_t("mmodal.voice.timeout"), "task": ""}
        except Exception as e:
            logger.error(_mm_t("mmmd.err.asr_fail", e=e))
            return {
                "type": "text",
                "content": _mm_t("mmodal.voice.failed", detail=str(e)),
                "task": "",
            }

    async def _process_image(self, payload: Dict) -> Dict:
        """视觉分析（计算密集型，必须使用 ThreadPool + 超时熔断）"""
        if not await self._lazy_load_blip():
            return {
                "type": "raw_multi_modal",
                "raw_content": _mm_t("mmodal.image.model_down"),
                "media_type": "image",
                "task": _mm_t("mmodal.image.task_caption"),
            }

        base64_img = payload.get("image_base64")
        if not base64_img:
            return {
                "type": "raw_multi_modal",
                "raw_content": _mm_t("mmodal.image.no_data"),
                "media_type": "image",
                "task": "",
            }

        # 定义阻塞的计算密集型任务
        def _run_blip_inference():
            import io

            from PIL import Image

            img_data = base64.b64decode(base64_img)
            image = Image.open(io.BytesIO(img_data)).convert("RGB")

            # 使用 torch.no_grad() 大幅节省前向传播内存
            with torch.no_grad():
                inputs = self.blip_processor(image, return_tensors="pt").to(self.blip_model.device)
                out = self.blip_model.generate(**inputs, max_new_tokens=50)
                return self.blip_processor.decode(out[0], skip_special_tokens=True)

        try:
            # 放入后台线程执行，并限定 20 秒超时
            raw_caption = await asyncio.wait_for(
                asyncio.to_thread(_run_blip_inference), timeout=20.0
            )

            if self.memory:
                await self.memory.store_experience(
                    "multi_modal",
                    "image_raw",
                    {"caption": raw_caption, "timestamp": asyncio.get_event_loop().time()},
                )

            logger.info(_mm_t("mmmd.log.vision", snippet=raw_caption[:50]))
            return {
                "type": "raw_multi_modal",
                "raw_content": raw_caption,
                "media_type": "image",
                "task": _mm_t("mmodal.image.task_analyze"),
            }

        except asyncio.TimeoutError:
            logger.error(_mm_t("mmmd.err.vision_timeout"))
            return {
                "type": "raw_multi_modal",
                "raw_content": _mm_t("mmodal.image.timeout_body"),
                "media_type": "image",
                "task": "",
            }
        except Exception as e:
            logger.error(_mm_t("mmmd.err.vision_fail", e=e))
            return {
                "type": "raw_multi_modal",
                "raw_content": _mm_t("mmodal.image.extract_failed", detail=str(e)),
                "media_type": "image",
                "task": "",
            }

    async def _process_file(self, payload: Dict) -> Dict:
        """Document path: whitelisted types try MarkItDown (Markdown) first, then unstructured."""
        file_path = payload.get("file_path")
        if not file_path or not os.path.exists(file_path):
            return {
                "type": "raw_multi_modal",
                "raw_content": _mm_t("mmodal.file.bad_path"),
                "media_type": "file",
                "task": "",
            }

        fname = os.path.basename(file_path)
        from adami_kernel.cortex.document_markdown import normalized_allowed_extension

        try_markdown = normalized_allowed_extension(fname) is not None
        prior_markitdown = "na"
        doc_timeout = float(settings.ADAMI_DOCUMENT_MARKDOWN_TIMEOUT_SEC)

        if try_markdown:
            from adami_kernel.cortex.document_markdown import (
                DocumentMarkdownFailureReason,
                DocumentMarkdownSuccess,
                convert_document_path_to_markdown,
            )

            use_markitdown = markitdown_effective_enabled()
            if not use_markitdown:
                prior_markitdown = "skipped"
                skip_reason = (
                    "config_false"
                    if settings.ADAMI_MARKITDOWN_ENABLED is False
                    else "auto_no_markitdown_package"
                )
                parse_logger.info(
                    "[doc.parse] route=markitdown_skipped reason=%s path=%s",
                    skip_reason,
                    file_path,
                )
                if settings.ADAMI_MARKITDOWN_ENABLED is False:
                    logger.info(_mm_t("mmmd.log.markitdown_disabled"))
                else:
                    logger.info(_mm_t("mmmd.log.markitdown_unavailable"))
            else:
                md_res = await convert_document_path_to_markdown(file_path, timeout_s=doc_timeout)
                if isinstance(md_res, DocumentMarkdownSuccess):
                    raw_md = md_res.markdown
                    if self.memory:
                        await self.memory.store_experience(
                            "multi_modal",
                            "file_raw",
                            {
                                "text": raw_md[:3000],
                                "filename": payload.get("file_name", ""),
                                "timestamp": asyncio.get_event_loop().time(),
                            },
                        )
                    logger.info(
                        _mm_t(
                            "mmmd.log.file_markdown",
                            n=len(raw_md),
                            trunc="1" if md_res.meta.truncated else "0",
                        )
                    )
                    return {
                        "type": "raw_multi_modal",
                        "raw_content": raw_md,
                        "media_type": "file",
                        "task": _mm_t("mmodal.file.task_analyze"),
                    }
                prior_markitdown = "failed"
                if md_res.reason == DocumentMarkdownFailureReason.NOT_INSTALLED:
                    logger.info(_mm_t("mmmd.log.markitdown_unavailable"))
                else:
                    parse_logger.info(
                        "[doc.parse] route=fallback_to_unstructured reason=markitdown_%s path=%s",
                        md_res.reason.value,
                        file_path,
                    )
                    logger.warning(
                        _mm_t(
                            "mmmd.warn.markitdown_fallback",
                            reason=md_res.reason.value,
                            detail=(md_res.detail or "")[:200],
                        )
                    )

        if not self.unstructured_available:
            import sys

            parse_logger.info(
                "[doc.parse] route=extract_none reason=no_unstructured prior_markitdown=%s path=%s",
                prior_markitdown,
                file_path,
            )
            return {
                "type": "text",
                "content": _mm_t("mmodal.file.missing_unstructured", exe=sys.executable),
                "task": "",
            }

        def _run_partition() -> str:
            from unstructured.partition.auto import partition

            elements = partition(filename=file_path)
            return "\n".join([str(el) for el in elements])

        try:
            raw_text = await asyncio.wait_for(
                asyncio.to_thread(_run_partition),
                timeout=doc_timeout,
            )

            if self.memory:
                await self.memory.store_experience(
                    "multi_modal",
                    "file_raw",
                    {
                        "text": raw_text[:3000],
                        "filename": payload.get("file_name", ""),
                        "timestamp": asyncio.get_event_loop().time(),
                    },
                )

            logger.info(_mm_t("mmmd.log.file_extract", n=len(raw_text)))
            parse_logger.info(
                "[doc.parse] route=unstructured_ok chars=%s prior_markitdown=%s path=%s",
                len(raw_text),
                prior_markitdown,
                file_path,
            )

            return {
                "type": "raw_multi_modal",
                "raw_content": raw_text,
                "media_type": "file",
                "task": _mm_t("mmodal.file.task_analyze"),
            }

        except asyncio.TimeoutError:
            parse_logger.warning(
                "[doc.parse] route=unstructured_fail reason=timeout prior_markitdown=%s path=%s",
                prior_markitdown,
                file_path,
            )
            logger.error(_mm_t("mmmd.err.file_timeout", path=file_path))
            return {
                "type": "raw_multi_modal",
                "raw_content": _mm_t("mmodal.file.timeout_body"),
                "media_type": "file",
                "task": "",
            }
        except Exception as e:
            parse_logger.warning(
                "[doc.parse] route=unstructured_fail reason=exception prior_markitdown=%s path=%s detail=%s",
                prior_markitdown,
                file_path,
                str(e)[:200],
            )
            logger.error(_mm_t("mmmd.err.file_crash", e=e))
            return {
                "type": "raw_multi_modal",
                "raw_content": _mm_t("mmodal.file.extract_failed", detail=str(e)),
                "media_type": "file",
                "task": "",
            }

    async def cleanup_temp(self, file_path: str):
        """兼容老版本保留的接口，清理工作主要已移交至 Nerve 层"""
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
        except Exception:
            pass


# --- END OF FILE multi_modal.py ---
