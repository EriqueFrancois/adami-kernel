import logging

from rich.console import Console
from rich.table import Table

from adami_kernel.i18n.boot_msg import boot_t

console = Console()
logger = logging.getLogger("AdamI-Diagnostics")


class SystemDiagnostics:
    @staticmethod
    def perform_startup_check(kernel):
        """全面扫描 AdamI 系统的模块挂载状态并生成报告"""
        core_modules = {
            "EventBus": getattr(kernel, "bus", None),
            "UnifiedMemory": getattr(kernel, "memory", None),
            "LLMRouter": getattr(kernel, "router", None),
            "EvolutionEngine": getattr(kernel, "evolution_engine", None),
            "ToolboxManager": getattr(kernel, "toolbox", None),
        }

        cognitive_modules = {
            "SubconsciousRAG": getattr(kernel, "subconscious", None),
            "MetaCortex": getattr(kernel, "meta_cortex", None),
            "WoofishPredictor": getattr(kernel, "woofish", None),
            "EndocrineSystem": getattr(kernel, "endocrine", None),
            "SelfModel": getattr(kernel, "self_model", None),
            "CuriosityQueue": getattr(kernel, "curiosity", None),
            "SubAgentManager": getattr(kernel, "sub_agent_manager", None),
        }

        security_modules = {
            "ImmunitySystem": getattr(kernel, "immunity", None),
        }

        peripheral_modules = {
            "SensoryNerve": getattr(kernel, "sensory", None),
            "TelegramNerve": getattr(kernel, "telegram_nerve", None),
            "Proprioception": getattr(kernel, "proprioception", None),
            "DeadLetterQueue": getattr(kernel, "dlq", None),
        }

        nerves = getattr(kernel, "nerves", [])
        nerve_names = [n.__class__.__name__ for n in nerves]
        if nerve_names:
            nerve_status = boot_t("boot.diag.nerve_online", n=len(nerves))
            nerve_status += f"\n[dim cyan]({', '.join(nerve_names)})[/dim cyan]"
        else:
            nerve_status = boot_t("boot.diag.nerve_zero")

        ee = getattr(kernel, "evolution_engine", None)
        dynamic_skills = getattr(ee, "dynamic_skills", {}) if ee is not None else {}

        table = Table(title=f"[bold cyan]{boot_t('boot.diag.title')}[/bold cyan]", show_lines=True)
        table.add_column(boot_t("boot.diag.col_subsystem"), style="cyan", no_wrap=True)
        table.add_column(boot_t("boot.diag.col_mount"), style="magenta")
        table.add_column(boot_t("boot.diag.col_health"), justify="center", style="bold green")

        active_count = 0
        total_count = 0

        def build_status_str(mod_dict):
            nonlocal active_count, total_count
            mounted = []
            missing = []
            for name, inst in mod_dict.items():
                total_count += 1
                if inst is not None:
                    mounted.append(name.split(" ")[0])
                    active_count += 1
                else:
                    missing.append(name.split(" ")[0])

            status_str = "[green]" + ", ".join(mounted) + "[/green]"
            if missing:
                status_str += (
                    "\n[dim red]"
                    + boot_t("boot.diag.missing_prefix")
                    + ", ".join(missing)
                    + "[/dim red]"
                )

            health = (
                "[bold green]100%[/bold green]"
                if not missing
                else f"[bold yellow]{int(len(mounted) / len(mod_dict) * 100)}%[/bold yellow]"
            )
            return status_str, health

        core_str, core_h = build_status_str(core_modules)
        cog_str, cog_h = build_status_str(cognitive_modules)
        sec_str, sec_h = build_status_str(security_modules)
        peri_str, peri_h = build_status_str(peripheral_modules)

        table.add_row(boot_t("boot.diag.label_core"), core_str, core_h)
        table.add_row(boot_t("boot.diag.label_cognitive"), cog_str, cog_h)
        table.add_row(boot_t("boot.diag.label_security"), sec_str, sec_h)
        table.add_row(boot_t("boot.diag.label_peripheral"), peri_str, peri_h)

        table.add_row(
            boot_t("boot.diag.label_nerves"),
            nerve_status,
            boot_t("boot.diag.nerve_health_badge", n=len(nerves)),
        )
        total_count += 1
        active_count += len(nerves)

        skill_names = list(dynamic_skills.keys())
        total_count += len(skill_names)
        active_count += len(skill_names)

        if skill_names:
            skills_str = "[green]" + ", ".join(skill_names) + "[/green]"
        else:
            skills_str = boot_t("boot.diag.skills_empty_waiting")
        table.add_row(
            boot_t("boot.diag.label_dynamic_skills"),
            skills_str,
            f"[bold green]{len(skill_names)} Nodes[/bold green]",
        )

        console.print(table)
        logger.info(
            boot_t(
                "boot.diag.logger_summary",
                active=active_count,
                total=total_count,
                nerves=len(nerves),
            )
        )

        if active_count >= total_count - 5:
            console.print(
                f"[bold green]{boot_t('boot.diag.selftest_pass_full', active=active_count, total=total_count, nerves=len(nerves))}[/bold green]\n"
            )
        else:
            console.print(
                f"[bold yellow]{boot_t('boot.diag.selftest_partial', active=active_count, total=total_count, nerves=len(nerves))}[/bold yellow]\n"
            )
