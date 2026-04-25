# src/adami_kernel/self_test/self_test_runner.py
# --- START OF FILE self_test_runner.py ---

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List

from adami_kernel.cortex.dream_sandbox import DreamSandbox
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.web.observability import observability

logger = logging.getLogger("AdamI-SelfTestRunner")


class SelfTestRunner:
    """
    AdamI SelfTest Runner（工业级 pytest 沙箱执行器）
    核心功能：在 DreamSandbox 中安全执行 pytest，支持单个测试文件动态执行。
    【本次 5.2 核心增强】：新增 run_test_file 方法，供 SkillOptimizer 真实 TDD 执行使用
    """

    def __init__(self):
        self.test_dir = os.path.abspath("tests")
        self.sandbox = None
        self.sandbox_tests = None
        self.force_reload = False
        logger.info(boot_t("boot.log.self_test_runner_init"))

    async def initialize(self, force_reload: bool = False):
        """
        确保 tests/ 目录已复制到 sandbox_volume，并初始化 DreamSandbox
        """
        self.force_reload = force_reload
        self.sandbox = DreamSandbox()
        await self.sandbox.initialize()

        self.sandbox_tests = os.path.join(self.sandbox.volume_path, "tests")

        if self.force_reload or not os.path.exists(self.sandbox_tests):
            if os.path.exists(self.sandbox_tests):
                shutil.rmtree(self.sandbox_tests)
            shutil.copytree(self.test_dir, self.sandbox_tests, dirs_exist_ok=True)
            logger.info(
                boot_t(
                    "boot.log.selftest_tests_synced_to_sandbox",
                    force_reload=self.force_reload,
                    path=self.sandbox_tests,
                )
            )
        else:
            logger.debug(
                boot_t("boot.log.selftest_tests_already_in_sandbox", path=self.sandbox_tests)
            )

        if not os.path.exists(self.test_dir):
            logger.warning(boot_t("boot.log.selftest_host_tests_missing", path=self.test_dir))
        else:
            logger.info(boot_t("boot.log.self_test_runner_tests_ready", path=self.test_dir))

    # ====================== 【5.2 新增】单个测试文件真实执行 ======================
    async def run_test_file(self, test_file_path: str) -> bool:
        """
        执行单个动态生成的测试文件（供 SkillOptimizer 调用）
        返回 True 表示全部通过
        """
        if not os.path.exists(test_file_path):
            logger.error(boot_t("boot.log.selftest_real_file_missing", path=test_file_path))
            return False

        # 复制到沙箱
        sandbox_test_path = os.path.join(self.sandbox_tests, os.path.basename(test_file_path))
        shutil.copy2(test_file_path, sandbox_test_path)

        logger.info(boot_t("boot.log.selftest_real_execute_start", path=sandbox_test_path))

        try:
            # 使用相对路径在沙箱内执行
            relative_path = f"/sandbox/tests/{os.path.basename(test_file_path)}"
            cmd = [
                "pytest",
                "-q",
                "--tb=no",
                "--asyncio-mode=auto",
                "--json-report",
                "--json-report-file=/dev/stdout",
                relative_path,
            ]

            sandbox_report = await self.sandbox.run_command_in_sandbox(
                cmd, timeout=60, use_pytest_image=True
            )

            # 解析结果
            try:
                json_report = json.loads(sandbox_report.get("stdout", "{}"))
                summary = json_report.get("summary", {})
                passed = summary.get("passed", 0)
                total = summary.get("total", 0)
                passed_rate = passed / total if total > 0 else 0.0
                result = passed_rate == 1.0
            except Exception:
                # Fallback：文本解析
                output = sandbox_report.get("stdout", "") + sandbox_report.get("stderr", "")
                result = "PASSED" in output and "FAILED" not in output and "ERROR" not in output

            logger.info(
                boot_t(
                    "boot.log.selftest_real_execute_done_pass"
                    if result
                    else "boot.log.selftest_real_execute_done_fail"
                )
            )
            return result

        except asyncio.TimeoutError:
            logger.error(boot_t("boot.log.selftest_real_timeout"))
            return False
        except Exception as e:
            logger.error(boot_t("boot.log.selftest_real_exception", detail=str(e)), exc_info=True)
            return False

    # =======================================================================

    async def run_pytest(self, test_files: List[str], timeout: int = 60) -> Dict[str, Any]:
        """
        在 DreamSandbox 中安全执行 pytest（原有方法，保持不变）
        """
        async with observability.start_span(
            span_name="selftest.runner.execute",
            attributes={"test_files": test_files, "timeout": timeout},
        ):
            report = {
                "status": "running",
                "pass_rate": 0.0,
                "total_tests": 0,
                "passed": 0,
                "failed": 0,
                "duration": 0.0,
                "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "raw_output": "",
            }

            relative_paths = [os.path.join("/sandbox/tests", f) for f in test_files]

            cmd = [
                "pytest",
                "-q",
                "--tb=no",
                "--asyncio-mode=auto",
                "--json-report",
                "--json-report-file=/dev/stdout",
                *relative_paths,
            ]

            try:
                sandbox_report = await self.sandbox.run_command_in_sandbox(
                    cmd, timeout=timeout, use_pytest_image=True
                )

                report["duration"] = sandbox_report.get("execution_time", 0.0)
                report["raw_output"] = sandbox_report.get("stdout", "") + sandbox_report.get(
                    "stderr", ""
                )

                try:
                    json_report = json.loads(sandbox_report.get("stdout", "{}"))
                    summary = json_report.get("summary", {})
                    report["total_tests"] = summary.get("total", 0)
                    report["passed"] = summary.get("passed", 0)
                    report["failed"] = summary.get("failed", 0)
                except:
                    output = report["raw_output"]
                    passed = output.count("PASSED") + output.count("passed")
                    failed = output.count("FAILED") + output.count("failed")
                    total = passed + failed or 1
                    report["total_tests"] = total
                    report["passed"] = passed
                    report["failed"] = failed

                report["pass_rate"] = (
                    round(report["passed"] / report["total_tests"], 4)
                    if report["total_tests"] > 0
                    else 0.0
                )
                report["status"] = "success" if report["failed"] == 0 else "failed"

                logger.info(
                    boot_t(
                        "boot.log.selftest_pytest_done",
                        pass_rate=f"{report['pass_rate']:.2%}",
                        passed=report["passed"],
                        total=report["total_tests"],
                    )
                )

                return report

            except asyncio.TimeoutError:
                logger.error(boot_t("boot.log.selftest_pytest_timeout"))
                report["status"] = "timeout"
                report["error"] = boot_t("cjk_gate.selftest_timeout_detail", seconds=timeout)
                return report
            except Exception as e:
                logger.error(
                    boot_t("boot.log.selftest_pytest_exception", detail=str(e)), exc_info=True
                )
                report["status"] = "error"
                report["error"] = str(e)
                return report

    async def shutdown(self):
        logger.info(boot_t("boot.log.selftest_shutdown_graceful"))


# --- END OF FILE self_test_runner.py ---
