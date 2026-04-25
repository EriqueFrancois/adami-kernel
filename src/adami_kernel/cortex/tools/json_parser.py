# src/adami_kernel/cortex/tools/json_parser.py
import json
import re
from typing import Any, Dict, Optional, Tuple

# ====================== 【本次核心修复】可选 json-repair 兜底 ======================
try:
    from json_repair import repair_json

    JSON_REPAIR_AVAILABLE = True
except ImportError:
    JSON_REPAIR_AVAILABLE = False
# =================================================================================


def extract_json_from_llm_output(raw: str) -> Optional[Dict[str, Any]]:
    """【工业级强化版】从 LLM 输出中提取第一个完整有效的 JSON 对象
    优先级（从高到低）：
    1. 直接 json.loads
    2. ```json 代码块
    3. 贪婪提取最大的 {} 对象
    4. json-repair 最终兜底
    """
    if not raw or not isinstance(raw, str):
        return None

    # 预清洗
    text = raw.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"^```(?:json|JSON)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()

    # 1. 直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. 提取 ```json 代码块
    match = re.search(r"```(?:json|JSON)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        block = match.group(1).strip()
        try:
            return json.loads(block)
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. 贪婪提取最大的 {} 对象
    matches = re.findall(r"(\{[\s\S]*\})", text)
    if matches:
        for candidate in sorted(matches, key=len, reverse=True):
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, TypeError):
                continue

    # 4. json-repair 兜底
    if JSON_REPAIR_AVAILABLE:
        try:
            repaired = repair_json(text)
            if repaired:
                return json.loads(repaired) if isinstance(repaired, str) else repaired
        except Exception:
            pass

    return None


def extract_json_and_python_code(raw: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """同时提取 action JSON 与 Python 代码块（CREATE_NEW_SKILL）。
    先在 ```python 之前的区域解析 JSON，减少代码中花括号干扰。
    """
    if not raw or not isinstance(raw, str):
        return None, None

    text = raw.strip()

    code = None
    code_match = re.search(r"```(?:python|Python)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if code_match:
        code = code_match.group(1).strip()
    else:
        code_match = re.search(r"(async def execute|def execute).*?(?=\Z|```)", text, re.DOTALL)
        if code_match:
            code = code_match.group(0).strip()

    json_region = text
    fence = re.search(r"```(?:python|Python)", text, re.IGNORECASE)
    if fence:
        json_region = text[: fence.start()]

    action = extract_json_from_llm_output(json_region)
    if not action:
        action = extract_json_from_llm_output(text)

    return action, code


# --- END OF FILE src/adami_kernel/cortex/tools/json_parser.py ---
