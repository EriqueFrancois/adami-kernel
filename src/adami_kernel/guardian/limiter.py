import asyncio
import logging
import time

logger = logging.getLogger("GuardianLimiter")


class TokenBucketLimiter:
    """
    支持动态速率调节的令牌桶限流器。
    用于接收 F(c) 适应度反馈，表现越好，系统给予的并发配额越高。
    """

    def __init__(self, capacity: int = 10, fill_rate: float = 2.0):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.fill_rate = fill_rate  # 每秒恢复的令牌数
        self.last_fill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, amount: int = 1) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_fill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
            self.last_fill = now

            if self.tokens >= amount:
                self.tokens -= amount
                return True
            return False

    async def update_rate_from_fitness(self, fc_score: float) -> None:
        """基于 F(c) 动态调整令牌恢复速率与桶容量"""
        async with self._lock:
            # 基础速率 1.0，根据 F(c) 上下浮动
            new_rate = max(0.5, min(10.0, 1.0 + (fc_score * 0.5)))
            new_capacity = int(max(5, min(50, 10 + (fc_score * 2))))

            logger.info(
                f"[GuardianLimiter] Adjusting limits based on F(c)={fc_score:.2f} -> Rate: {new_rate:.2f}/s, Capacity: {new_capacity}"
            )
            self.fill_rate = new_rate
            self.capacity = new_capacity
