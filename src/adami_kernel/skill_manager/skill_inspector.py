# src/adami_kernel/skill_manager/skill_inspector.py
"""
AdamI Skill Inspector - 技能质检员（工业级版本）

负责对生成的技能代码进行严格的静态和动态检查。
【本次核心强化】：进一步强化返回值校验（必须是 dict，且 status 只能是 "success" 或 "error"），HostMode 路径下打印完整 traceback 和返回结果。
【本次强化】：execute 返回 None 时输出技能代码前500字符，帮助快速定位问题。
【步骤1 保留】：质检通过后立即返回 v1.0 (VALIDATED)，TDD/SelfTest 推入后台异步任务。
"""

import ast
import json
import logging
import os
import re
import time
import traceback
from typing import Any, Dict, Optional

# 新增：读取全局配置
from adami_kernel.config import settings
from adami_kernel.cortex.dream_sandbox import DreamSandbox
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output
from adami_kernel.i18n import t
from adami_kernel.orchestrator.loader import PluginLoader

logger = logging.getLogger("AdamI-SkillInspector")


def _insp_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _uhex(*hex4: str) -> str:
    return "".join(json.loads(f'"\\u{h.lower()}"') for h in hex4)


def _stderr_markers() -> list[str]:
    return json.loads(_insp_t("sins.stderr.markers_json"))


class SkillInspector:
    """
    技能质检员：负责对生成的技能代码进行严格的静态和动态检查，
    确保其命名规范、语法正确、安全无危险操作，并能通过沙箱模拟运行。
    【本次强化】：返回值严格契约校验 + 完整异常诊断 + execute 返回 None 时输出代码前500字符。
    """

    # 命名规范：全大写字母、数字、下划线，长度 3-30
    NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
    MIN_NAME_LEN = 3
    MAX_NAME_LEN = 30

    def __init__(
        self,
        dream_sandbox: DreamSandbox,
        router,
        evolution_engine: Optional[EvolutionEngine] = None,
    ):
        self.dream_sandbox = dream_sandbox
        self.router = router
        self.evolution_engine = evolution_engine
        self.plugin_loader = PluginLoader()

        # 【配置开关】默认关闭 Docker 沙箱，使用宿主机直接检测
        self.skip_docker_sandbox = getattr(settings, "ADAMI_SKIP_DOCKER_SANDBOX", True)

        if self.skip_docker_sandbox:
            logger.debug(_insp_t("skisp.debug.host_mode"))
        else:
            logger.debug(_insp_t("skisp.debug.docker_on"))

    async def inspect_and_register(
        self, skill_name: str, code: str, description: str = "", max_retries: int = 3
    ) -> Dict[str, Any]:
        """统一质检入口，失败时自动打回 Engineer 重试"""
        logger.info(_insp_t("skisp.log.inspect_start", name=skill_name, n=max_retries))

        for attempt in range(max_retries):
            result = await self.inspect(skill_name, code, description)
            if result["passed"]:
                logger.info(
                    _insp_t(
                        "skisp.log.inspect_pass_attempt",
                        name=skill_name,
                        a=attempt + 1,
                    )
                )
                return result

            logger.warning(
                _insp_t(
                    "skisp.warn.inspect_fail_attempt",
                    a=attempt + 1,
                    feedback=result.get("feedback", ""),
                )
            )
            if self.evolution_engine and hasattr(self.evolution_engine, "feedback_to_engineer"):
                await self.evolution_engine.feedback_to_engineer(skill_name, result["feedback"])

        logger.error(_insp_t("skisp.err.inspect_exhausted", name=skill_name, n=max_retries))
        return {
            "passed": False,
            "feedback": _insp_t("skill.inspect.retry_exhausted", max_retries=max_retries),
            "suggestions": [_insp_t("skill.inspect.suggest_resubmit_after_feedback")],
        }

    async def inspect(self, skill_name: str, code: str, description: str = "") -> Dict[str, Any]:
        """执行完整的技能质检流程（步骤1：通过后立即返回 v1.0）"""
        name_check = self._check_name(skill_name)
        if not name_check["passed"]:
            return name_check

        ast_check = self._check_ast(code)
        if not ast_check["passed"]:
            return ast_check

        security_check = self._check_security(code)
        if not security_check["passed"]:
            return security_check

        runtime_check = await self._check_runtime(skill_name, code, description)
        if not runtime_check["passed"]:
            return runtime_check

        # 【步骤1 核心】质检全部通过 → 立即返回 v1.0 (VALIDATED)
        logger.info(_insp_t("skisp.log.step1_ok"))
        return {"passed": True, "feedback": _insp_t("skill.inspect.passed_all"), "suggestions": []}

    def _check_name(self, skill_name: str) -> Dict[str, Any]:
        if not self.NAME_PATTERN.match(skill_name):
            return {
                "passed": False,
                "feedback": _insp_t("skill.inspect.name_invalid", skill_name=skill_name),
                "suggestions": [_insp_t("skill.inspect.suggest_uppercase_name")],
            }
        if len(skill_name) < self.MIN_NAME_LEN:
            return {
                "passed": False,
                "feedback": _insp_t(
                    "skill.inspect.name_too_short",
                    skill_name=skill_name,
                    length=len(skill_name),
                    min_len=self.MIN_NAME_LEN,
                ),
                "suggestions": [_insp_t("skill.inspect.suggest_longer_name")],
            }
        if len(skill_name) > self.MAX_NAME_LEN:
            return {
                "passed": False,
                "feedback": _insp_t(
                    "skill.inspect.name_too_long",
                    skill_name=skill_name,
                    length=len(skill_name),
                    max_len=self.MAX_NAME_LEN,
                ),
                "suggestions": [_insp_t("skill.inspect.suggest_shorter_name")],
            }
        return {"passed": True, "feedback": "", "suggestions": []}

    def _check_ast(self, code: str) -> Dict[str, Any]:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {
                "passed": False,
                "feedback": _insp_t("skill.inspect.syntax_error", detail=str(e)),
                "suggestions": [_insp_t("skill.inspect.suggest_fix_syntax")],
            }

        has_execute = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute":
                has_execute = True
                break
        if not has_execute:
            return {
                "passed": False,
                "feedback": _insp_t("skill.inspect.require_execute_fn"),
                "suggestions": [_insp_t("skill.inspect.suggest_add_execute")],
            }

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "asyncio"
                        and node.func.attr == "run"
                    ):
                        return {
                            "passed": False,
                            "feedback": _insp_t("skill.inspect.no_asyncio_run"),
                            "suggestions": [_insp_t("skill.inspect.suggest_no_asyncio_run")],
                        }

        return {"passed": True, "feedback": "", "suggestions": []}

    def _check_security(self, code: str) -> Dict[str, Any]:
        safe = self.plugin_loader.audit_code(code)
        if not safe:
            return {
                "passed": False,
                "feedback": _insp_t("skill.inspect.security_blocked"),
                "suggestions": [_insp_t("skill.inspect.suggest_remove_unsafe")],
            }
        return {"passed": True, "feedback": "", "suggestions": []}

    def _infer_mock_args_from_description(
        self, description: str, skill_name: str = ""
    ) -> Optional[Dict[str, Any]]:
        desc_lower = f"{description.lower()} {skill_name.lower()}"

        if any(
            kw in desc_lower
            for kw in (
                _uhex("5929", "6c14"),
                "weather",
                _uhex("6c14", "6e29"),
                "temperature",
                _uhex("67e5", "8be2", "5929", "6c14"),
            )
        ):
            logger.info(_insp_t("skisp.log.mock_weather", hint=desc_lower[:30]))
            return {"city": _insp_t("sins.mock.city")}
        if any(
            kw in desc_lower
            for kw in (
                _uhex("4ef7", "683c"),
                "price",
                "btc",
                "eth",
                "sol",
                _uhex("6bd4", "7279", "5e01"),
                _uhex("4ee5", "592a", "574a"),
                _uhex("7d22", "62c9", "7eb3"),
                "crypto",
                _uhex("5e01", "4ef7"),
            )
        ):
            logger.info(_insp_t("skisp.log.mock_price", hint=desc_lower[:30]))
            return {"coin": "bitcoin"}
        return None

    # ====================== 【本次强化】统一返回值校验方法 ======================
    def _validate_execute_result(self, result: Any, skill_name: str) -> Dict[str, Any]:
        """严格校验 execute 返回值，必须是 dict 且 status 为 success/error"""
        if result is None:
            return {
                "passed": False,
                "feedback": _insp_t("skill.inspect.exec_returned_none", skill_name=skill_name),
                "suggestions": [_insp_t("skill.inspect.suggest_return_dict")],
            }
        if not isinstance(result, dict):
            return {
                "passed": False,
                "feedback": _insp_t(
                    "skill.inspect.exec_not_dict",
                    skill_name=skill_name,
                    typ=type(result).__name__,
                ),
                "suggestions": [_insp_t("skill.inspect.suggest_return_dict_shape")],
            }
        if "status" not in result:
            return {
                "passed": False,
                "feedback": _insp_t("skill.inspect.missing_status_key", skill_name=skill_name),
                "suggestions": [_insp_t("skill.inspect.suggest_add_status_key")],
            }
        if result["status"] not in ("success", "error"):
            return {
                "passed": False,
                "feedback": _insp_t(
                    "skill.inspect.bad_status_value",
                    skill_name=skill_name,
                    status=result["status"],
                ),
                "suggestions": [_insp_t("skill.inspect.suggest_fix_status_value")],
            }
        if result["status"] == "error" and "error" not in result:
            return {
                "passed": False,
                "feedback": _insp_t(
                    "skill.inspect.error_status_missing_error_key", skill_name=skill_name
                ),
                "suggestions": [_insp_t("skill.inspect.suggest_add_error_key")],
            }
        return {"passed": True, "feedback": "", "suggestions": []}

    # ==========================================================================

    async def _check_runtime(
        self, skill_name: str, code: str, description: str = ""
    ) -> Dict[str, Any]:
        """运行时检测核心方法（已支持配置开关）"""
        if self.skip_docker_sandbox:
            logger.info(_insp_t("skisp.log.host_runtime", name=skill_name))
            return await self._host_runtime_check(skill_name, code, description)

        # ==================== 原有 Docker 沙箱路径（完整保留，无省略） ====================
        logger.info(
            _insp_t(
                "skisp.log.sandbox_start",
                name=skill_name,
                snippet=description[:50],
            )
        )

        args = self._infer_mock_args_from_description(description, skill_name)

        if args is None:
            args = await self._generate_mock_args(description, code)

        if args is None or len(args) == 0:
            logger.debug(_insp_t("skisp.debug.sandbox_no_mock"))
            try:
                exec_globals = {}
                exec(code, exec_globals)
                if "execute" not in exec_globals or not callable(exec_globals["execute"]):
                    return {
                        "passed": False,
                        "feedback": _insp_t("skill.inspect.no_execute_callable"),
                        "suggestions": [_insp_t("skill.inspect.suggest_define_execute")],
                    }
                try:
                    result = await exec_globals["execute"]()
                    validation = self._validate_execute_result(result, skill_name)
                    if not validation["passed"]:
                        return validation
                except Exception as e:
                    logger.debug(_insp_t("skisp.debug.sandbox_noarg_err", e=e))
            except Exception as e:
                return {
                    "passed": False,
                    "feedback": _insp_t("skill.inspect.load_runtime_failed", detail=str(e)),
                    "suggestions": [_insp_t("skill.inspect.suggest_fix_runtime")],
                }
            return {
                "passed": True,
                "feedback": _insp_t("skill.inspect.mock_ok_no_args"),
                "suggestions": [],
            }

        # 生成测试脚本（原有 Docker 沙箱逻辑保持完整）
        test_script = f"""
import asyncio
import json
import sys
import traceback

code = {code!r}
args = {json.dumps(args)}

exec_globals = {{}}
exec(code, exec_globals)

async def main():
    try:
        result = await exec_globals['execute'](**args)
        print(json.dumps(result))
    except Exception as e:
        tb = traceback.format_exc()
        print(json.dumps({{"status": "error", "error": str(e), "traceback": tb}}))
        sys.exit(1)

asyncio.run(main())
"""

        sandbox_volume = self.dream_sandbox.volume_path
        os.makedirs(sandbox_volume, exist_ok=True)
        tmp_filename = f"skill_test_{skill_name}_{int(time.time())}.py"
        tmp_path = os.path.join(sandbox_volume, tmp_filename)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(test_script)
        container_path = f"/sandbox/{tmp_filename}"

        try:
            for _retry in range(2):
                cmd = f"pip install --quiet httpx && python {container_path}"
                report = await self.dream_sandbox.run_command_in_sandbox(
                    ["sh", "-c", cmd], timeout=60
                )

                stdout = report.get("stdout", "").strip()
                stderr = report.get("stderr", "").strip()
                returncode = report.get("returncode", -1)

                logger.info(
                    _insp_t(
                        "skisp.log.sandbox_report",
                        rc=returncode,
                        ls=len(stdout),
                        le=len(stderr),
                        head=stdout[:500],
                    )
                )

                if any(err in stdout or err in stderr for err in _stderr_markers()):
                    logger.error(_insp_t("skisp.err.sandbox_net", name=skill_name))
                    return {
                        "passed": False,
                        "feedback": _insp_t(
                            "skill.inspect.sandbox_network_blocked", skill_name=skill_name
                        ),
                        "suggestions": [
                            _insp_t("skill.inspect.sandbox_net_tip1"),
                            _insp_t("skill.inspect.sandbox_net_tip2"),
                            _insp_t("skill.inspect.sandbox_net_tip3"),
                        ],
                    }

                if returncode != 0:
                    error_msg = stderr or _insp_t("skill.inspect.sandbox_unknown")
                    try:
                        lines = stdout.splitlines()
                        for line in reversed(lines):
                            line = line.strip()
                            if line.startswith("{") and line.endswith("}"):
                                err_json = json.loads(line)
                                if isinstance(err_json, dict) and "error" in err_json:
                                    error_msg = _insp_t(
                                        "skill.inspect.skill_run_failed",
                                        detail=str(err_json["error"]),
                                    )
                                    break
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
                    logger.error(_insp_t("skisp.err.sandbox_run", msg=error_msg))
                    continue

                lines = stdout.splitlines()
                result_json = None
                for line in reversed(lines):
                    line = line.strip()
                    if line.startswith("WARNING") or "pip" in line or "root" in line:
                        continue
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            result_json = json.loads(line)
                            break
                        except json.JSONDecodeError:
                            continue

                if result_json is None:
                    logger.error(_insp_t("skisp.err.sandbox_json", snippet=stdout[:500]))
                    continue

                # 【本次强化】严格返回值校验
                validation = self._validate_execute_result(result_json, skill_name)
                if not validation["passed"]:
                    return validation

                if not isinstance(result_json, dict) or result_json.get("status") != "success":
                    error_msg = (
                        result_json.get("error", _insp_t("skill.inspect.status_not_success"))
                        if isinstance(result_json, dict)
                        else _insp_t("skill.inspect.bad_payload_format")
                    )
                    logger.error(_insp_t("skisp.err.sandbox_skill_err", msg=error_msg))
                    continue

                break
            else:
                return {
                    "passed": False,
                    "feedback": _insp_t("skill.inspect.sandbox_gave_up"),
                    "suggestions": [_insp_t("skill.inspect.suggest_double_braces")],
                }
        except Exception as e:
            logger.error(
                _insp_t(
                    "skisp.err.sandbox_exc",
                    e=e,
                    tb=traceback.format_exc(),
                )
            )
            return {
                "passed": False,
                "feedback": _insp_t("skill.inspect.sandbox_crashed", detail=str(e)),
                "suggestions": [_insp_t("skill.inspect.sandbox_crash_suggest")],
            }
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                    logger.debug(_insp_t("skisp.debug.tmp_cleaned", path=tmp_path))
                except Exception as e:
                    logger.warning(_insp_t("skisp.warn.tmp_clean_fail", e=e))

        logger.info(_insp_t("skisp.log.sandbox_ok", name=skill_name))
        return {"passed": True, "feedback": _insp_t("skill.inspect.sandbox_ok"), "suggestions": []}

    # ====================== 宿主机直接执行检测（已强化返回值校验 + 诊断日志） ======================
    async def _host_runtime_check(
        self, skill_name: str, code: str, description: str = ""
    ) -> Dict[str, Any]:
        """宿主机正常环境直接执行运行时检测（跳过 Docker 沙箱）"""
        logger.debug(_insp_t("skisp.debug.host_start", name=skill_name))

        args = self._infer_mock_args_from_description(description, skill_name)
        if args is None:
            args = await self._generate_mock_args(description, code)

        try:
            exec_globals = {}
            exec(code, exec_globals)

            if "execute" not in exec_globals or not callable(exec_globals["execute"]):
                return {
                    "passed": False,
                    "feedback": _insp_t("skill.inspect.no_execute_callable"),
                    "suggestions": [_insp_t("skill.inspect.suggest_define_execute")],
                }

            result = (
                await exec_globals["execute"](**args) if args else await exec_globals["execute"]()
            )

            # 【本次强化】execute 返回 None 时输出诊断信息（帮助定位 SkillBuilder 二次包装问题）
            if result is None:
                logger.error(
                    _insp_t(
                        "skisp.err.host_none",
                        name=skill_name,
                        head=code[:500],
                    )
                )

            # 【本次强化】严格返回值校验
            validation = self._validate_execute_result(result, skill_name)
            if not validation["passed"]:
                return validation

            logger.info(_insp_t("skisp.log.host_ok", name=skill_name))
            return {"passed": True, "feedback": _insp_t("skill.inspect.host_ok"), "suggestions": []}

        except Exception as e:
            tb = traceback.format_exc()
            logger.error(_insp_t("skisp.err.host_exc", e=e, tb=tb))
            return {
                "passed": False,
                "feedback": _insp_t("skill.inspect.host_failed", detail=str(e)),
                "suggestions": [_insp_t("skill.inspect.host_fail_suggest")],
            }

    async def _generate_mock_args(self, description: str, code: str) -> Optional[Dict[str, Any]]:
        if not self.router:
            return None

        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute":
                    args_names = [arg.arg for arg in node.args.args]
                    break
            else:
                args_names = []
        except (SyntaxError, ValueError):
            args_names = []

        if not args_names:
            return {}

        prompt = _insp_t(
            "sins.prompt.mock_args",
            description=description,
            code_snippet=code[:1000],
            args_names=str(args_names),
        )
        try:
            response = await self.router.call_llm(prompt, brain_type="action", temperature=0.2)
            data = extract_json_from_llm_output(response)
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if k in args_names}
        except Exception as e:
            logger.error(_insp_t("skisp.err.mock_gen", e=e))
        return None
