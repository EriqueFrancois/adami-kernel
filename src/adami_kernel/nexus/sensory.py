import asyncio
import json
import logging

from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.nexus.event import AdamiEvent, EventPriority

logger = logging.getLogger("AdamI-Sensory")


class SensoryNervousSystem:
    """
    感官神经系统：负责接收外部物理脉冲并转化为高优先级内核事件。
    它像皮肤或耳朵一样监听特定的物理端口，并将刺激信号转化为 URGENT 级别的事件。
    """

    def __init__(self, publish_func, port=9999):
        self.publish = publish_func
        self.port = port
        self.server = None

    async def start_listening(self):
        """
        启动异步 TCP 监听服务，等待外部脉冲刺激。
        """
        self.server = await asyncio.start_server(self._handle_pulse, "127.0.0.1", self.port)
        logger.info(boot_t("boot.log.sensory_listen_started", port=self.port))
        async with self.server:
            await self.server.serve_forever()

    async def _handle_pulse(self, reader, writer):
        """
        处理传入的感官脉冲信号，并将其发布到事件总线。
        """
        data = await reader.read(1024)
        addr = writer.get_extra_info("peername")
        try:
            pulse_data = data.decode().strip()
            if not pulse_data:
                return

            pulse = json.loads(pulse_data)
            logger.info(
                boot_t(
                    "boot.log.sensory_pulse_received",
                    addr=str(addr),
                    pulse=json.dumps(pulse, ensure_ascii=False),
                )
            )

            # 使用在 Canvas 中补全后的 URGENT 优先级发布事件
            # 这将确保该事件在调度队列中被最优先处理
            event = AdamiEvent(
                trace_id=f"sensory_{asyncio.get_event_loop().time()}",
                source_module="sensory.webhook",
                target_topic="system.events",
                priority=EventPriority.URGENT,
                payload={
                    "task": boot_t("cjk_gate.sensory_pulse_task_prefix")
                    + json.dumps(pulse, ensure_ascii=False),
                    "raw_pulse": pulse,
                },
            )
            await self.publish(event)
        except Exception as e:
            logger.error(boot_t("boot.log.sensory_pulse_error", detail=str(e)))
        finally:
            writer.close()
            await writer.wait_closed()
