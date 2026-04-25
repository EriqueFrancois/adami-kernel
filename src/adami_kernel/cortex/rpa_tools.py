import asyncio
import base64
import logging
import os
from io import BytesIO
from typing import Any

from rich.console import Console

from adami_kernel.config import settings
from adami_kernel.i18n import t

logger = logging.getLogger("AdamI-RPA")
console = Console()


def _rpa_t(key: str, **kwargs: Any) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class RPAToolbox:
    """RPA 自动化模块：赋予 AdamI 操作鼠标键盘和原生浏览器的能力"""

    def __init__(self):
        self.browser = None
        self.playwright = None
        self.context = None

    async def browser_action(
        self, url: str = "", action_type: str = "goto", selector: str = "", text: str = ""
    ) -> dict | str:
        from playwright.async_api import async_playwright

        try:
            if not self.playwright:
                self.playwright = await async_playwright().start()
                # 【环境检测】：如果是 AWS EC2 (存在 /home/ubuntu) 则强制使用无头模式
                is_aws = os.path.exists("/home/ubuntu")
                self.browser = await self.playwright.chromium.launch(headless=is_aws)
                self.context = await self.browser.new_context(
                    viewport={"width": 1280, "height": 720}
                )

            page = self.context.pages[0] if self.context.pages else await self.context.new_page()

            if action_type == "goto":
                if not url.startswith("http"):
                    url = "https://" + url
                await page.goto(url)
                await page.wait_for_load_state("networkidle")
                title = await page.title()
                return _rpa_t("rpa.browser.page_opened", title=title, url=url)

            elif action_type == "look_and_click" or action_type == "screenshot":
                # 截图并转为 base64
                screenshot_bytes = await page.screenshot(type="png")
                b64_img = base64.b64encode(screenshot_bytes).decode("utf-8")
                return {
                    "text": _rpa_t("rpa.browser.screenshot_caption"),
                    "image_base64": b64_img,
                    "visual_context": True,
                }

            elif action_type == "click":
                await page.click(selector)
                return _rpa_t("rpa.browser.element_clicked", selector=selector)

            elif action_type == "fill":
                await page.fill(selector, text)
                return _rpa_t("rpa.browser.form_filled", selector=selector, text=text)

            elif action_type == "extract_text":
                if selector:
                    content = await page.locator(selector).inner_text()
                else:
                    content = await page.evaluate("document.body.innerText")
                return _rpa_t("rpa.browser.text_extracted", snippet=content[:1000])

            elif action_type == "close":
                await self.browser.close()
                await self.playwright.stop()
                self.playwright = None
                self.browser = None
                return _rpa_t("rpa.browser.closed")

            else:
                return _rpa_t("rpa.browser.unknown_action", action_type=action_type)
        except Exception as e:
            logger.error(_rpa_t("rpa.err.browser", e=e))
            return _rpa_t("rpa.browser.failed", detail=e)

    async def gui_action(
        self, action_type: str, x: int = 0, y: int = 0, text: str = ""
    ) -> dict | str:
        import pyautogui

        pyautogui.FAILSAFE = True

        try:

            def _do_gui():
                if os.path.exists("/home/ubuntu"):
                    return _rpa_t("rpa.gui.aws_blocked")
                if action_type == "screenshot":
                    from PIL import ImageGrab

                    screen = ImageGrab.grab()
                    buffered = BytesIO()
                    screen = screen.convert("RGB")
                    screen.thumbnail((1280, 720))
                    screen.save(buffered, format="PNG")
                    b64_img = base64.b64encode(buffered.getvalue()).decode("utf-8")
                    return {
                        "text": _rpa_t("rpa.gui.screenshot_caption"),
                        "image_base64": b64_img,
                        "visual_context": True,
                    }
                elif action_type == "click":
                    pyautogui.click(x, y)
                    return _rpa_t("rpa.gui.click_done", x=x, y=y)
                elif action_type == "typewrite":
                    pyautogui.typewrite(text, interval=0.05)
                    return _rpa_t("rpa.gui.typewrite_done", text=text)
                elif action_type == "hotkey":
                    keys = text.split(",")
                    pyautogui.hotkey(*keys)
                    return _rpa_t("rpa.gui.hotkey_done", text=text)
                elif action_type == "position":
                    pos = pyautogui.position()
                    return _rpa_t("rpa.gui.position", pos=pos)
                else:
                    return _rpa_t("rpa.gui.unknown_action", action_type=action_type)

            res = await asyncio.to_thread(_do_gui)
            return res
        except Exception as e:
            return _rpa_t("rpa.gui.failed", detail=e)
