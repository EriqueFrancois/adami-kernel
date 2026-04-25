import logging

logger = logging.getLogger("FitnessEvaluator")


class FitnessEvaluator:
    def calculate_from_memory(self, history: list) -> float:
        if not history:
            return 2.0  # 初始鼓励分

        score = 0.0
        for exp in history:
            decision = exp.get("decision", {})
            action = decision.get("action")

            # 模拟资源消耗惩罚 (未来可对接真实 Token 消耗)
            # 如果动作是反复 THINK 或查网络，通常消耗较大
            cost_penalty = 0.2 if action in ["THINK", "WEB_SEARCH"] else 0.05

            if action == "TASK_COMPLETE":
                score += 1.0 - cost_penalty
            elif action in ["WRITE_FILE", "EXECUTE_COMMAND"]:
                # 工具执行成功给予部分分数，但扣除执行成本
                score += 0.5 - cost_penalty
            else:
                # 无效或高耗能动作，微弱扣分
                score -= cost_penalty

        # 归一化并放大到 5.0 分制
        raw_score = (score / len(history)) * 5.0

        # 严格限制在 1.5 到 5.0 之间，1.5为防止死锁的生命底线
        final_score = max(min(raw_score, 5.0), 1.5)
        return round(final_score, 2)
