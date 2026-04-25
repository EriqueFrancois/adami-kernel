import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

from adami_kernel.config import settings
from adami_kernel.i18n import t

logger = logging.getLogger("AdamI-WebSocket")


def _webws_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class WebSocketHandler:
    """Phase 2 实时事件流 - 带心跳 + 稳定连接"""

    @staticmethod
    async def handle(websocket: WebSocket, web_manager):
        await websocket.accept()
        web_manager.active_connections.add(websocket)
        logger.info(_webws_t("webws.log.connected", n=len(web_manager.active_connections)))

        try:
            # 心跳任务（每 30 秒 ping 一次）
            async def heartbeat():
                while True:
                    await asyncio.sleep(30)
                    try:
                        await websocket.send_json({"type": "ping"})
                    except:
                        break

            asyncio.create_task(heartbeat())

            while True:
                await asyncio.sleep(1)  # 保持连接
        except WebSocketDisconnect:
            web_manager.active_connections.remove(websocket)
            logger.info(_webws_t("webws.log.disconnected"))
        except Exception as e:
            logger.error(_webws_t("webws.err.exc", e=e))
