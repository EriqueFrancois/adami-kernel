"""Idle-gated Agent Lightning training (runs ``run_training_job`` after user quiet period).

Shares ``train_job_lock`` with :mod:`adami_kernel.training.schedule` so wall-clock and idle
jobs never overlap.
"""

from __future__ import annotations

import asyncio
import logging
import time

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.observability.activity_clock import seconds_since_user_activity
from adami_kernel.training.schedule import run_training_job_sync_blocking, train_job_lock

logger = logging.getLogger("AdamI-IdleTrain")

_last_idle_train_monotonic = 0.0


async def _idle_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _tridle_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


async def idle_training_loop() -> None:
    """Poll ``seconds_since_user_activity``; when above threshold, run one training job."""
    global _last_idle_train_monotonic
    logger.info(
        boot_t(
            "boot.log.lifecycle_idle_train",
            sec=int(settings.ADAMI_IDLE_TRAIN_AFTER_SEC),
            poll=int(settings.ADAMI_IDLE_TRAIN_POLL_SEC),
        )
    )
    poll = max(5.0, float(settings.ADAMI_IDLE_TRAIN_POLL_SEC))
    need = max(60.0, float(settings.ADAMI_IDLE_TRAIN_AFTER_SEC))
    cooldown = max(0.0, float(settings.ADAMI_IDLE_TRAIN_COOLDOWN_SEC))

    while True:
        try:
            await _idle_sleep(poll)
            if not bool(getattr(settings, "ADAMI_IDLE_TRAIN_ENABLED", True)):
                continue
            if seconds_since_user_activity() < need:
                continue
            now_m = time.monotonic()
            if cooldown > 0.0 and (now_m - _last_idle_train_monotonic) < cooldown:
                continue
            logger.info(_tridle_t("tridle.log.trigger", sec=int(seconds_since_user_activity())))
            code = 1
            async with train_job_lock:
                try:
                    code = await asyncio.to_thread(run_training_job_sync_blocking)
                except Exception:
                    logger.exception(_tridle_t("tridle.exc.round"))
                    _last_idle_train_monotonic = time.monotonic()
                    continue
            _last_idle_train_monotonic = time.monotonic()
            if code == 0:
                logger.info(_tridle_t("tridle.log.round_ok"))
            elif code == 3:
                logger.warning(_tridle_t("tridle.warn.skip_no_episodes", code=code))
            elif code == 2:
                logger.warning(_tridle_t("tridle.warn.no_agentlightning", code=code))
            else:
                logger.error(_tridle_t("tridle.err.bad_exit", code=code))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(_tridle_t("tridle.exc.poll"))
