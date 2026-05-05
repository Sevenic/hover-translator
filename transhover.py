import re
import time
import threading
import tkinter as tk
import ctypes
import sys
import platform
from pynput import mouse
import pyperclip
from deep_translator import GoogleTranslator

# 系统托盘
import pystray
from PIL import Image, ImageDraw

# ---------- 用户配置 ----------
FONT_FAMILY = "微软雅黑"
FONT_SIZE = 18                    # 加大两号
FONT_WEIGHT = "normal"
BG_COLOR = "#FFFFE0"
FG_COLOR = "#000000"
ALPHA = 0.85
DISPLAY_DURATION = 3.0
MAX_TEXT_LENGTH = 500
CACHE_SIZE = 200                 # 缓存最近翻译条数
# --------------------------------

class FloatingTranslator:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.popup = None
        self.after_id = None
        self.mouse_listener = None
        self.tray_icon = None

        self.last_text = ""                  # 去重用的上次原文
        self.translation_cache = {}           # 翻译缓存

        # DPI 感知
        if sys.platform == 'win32':
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

    def start(self):
        self.mouse_listener = mouse.Listener(on_click=self.on_click)
        self.mouse_listener.daemon = True
        self.mouse_listener.start()

        threading.Thread(target=self._run_tray, daemon=True).start()
        self.root.mainloop()

    def on_click(self, x, y, button, pressed):
        if button == mouse.Button.left and not pressed:
            self.handle_selection(x, y)

    # ---------- 无侵入复制（不干扰剪贴板）----------
    def _copy_selected_text(self):
        """模拟 Ctrl+C 获取选中文本，不备份不还原，不破坏图片剪贴板"""
        if platform.system() == "Windows":
            self._win32_ctrl_c()
        else:
            self._cross_platform_ctrl_c()

        time.sleep(0.1)
        try:
            text = pyperclip.paste()
            return text.strip() if isinstance(text, str) else ""
        except Exception:
            return ""

    def _win32_ctrl_c(self):
        VK_CONTROL = 0x11
        VK_C = 0x43
        KEYEVENTF_KEYUP = 0x0002

        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_C, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

        # 释放左右 Ctrl（防键盘状态残留）
        VK_LCONTROL = 0xA2
        VK_RCONTROL = 0xA3
        ctypes.windll.user32.keybd_event(VK_LCONTROL, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(VK_RCONTROL, 0, KEYEVENTF_KEYUP, 0)

    def _cross_platform_ctrl_c(self):
        from pynput.keyboard import Controller, Key
        kb = Controller()
        kb.press(Key.ctrl)
        kb.press('c')
        kb.release('c')
        kb.release(Key.ctrl)

    # ---------- 核心逻辑 ----------
    def handle_selection(self, x, y):
        text = self._copy_selected_text()
        # 空文本、过长文本不翻译
        if not text or len(text) > MAX_TEXT_LENGTH:
            return
        # 去重：与上次完全相同则忽略
        if text == self.last_text:
            return
        self.last_text = text
        threading.Thread(target=self.translate_and_show, args=(x, y, text), daemon=True).start()

    def contains_chinese(self, text: str) -> bool:
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    def translate_and_show(self, x, y, text):
        # 先查缓存
        cache_key = text.strip()
        if cache_key in self.translation_cache:
            translated = self.translation_cache[cache_key]
        else:
            target_lang = 'en' if self.contains_chinese(text) else 'zh-CN'
            try:
                translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
            except Exception as e:
                print(f"翻译失败: {e}")
                return
            # 写入缓存，保持大小
            if len(self.translation_cache) >= CACHE_SIZE:
                # 简单的 FIFO 清理
                first_key = next(iter(self.translation_cache))
                del self.translation_cache[first_key]
            self.translation_cache[cache_key] = translated

        if translated:
            self.root.after(0, self.show_popup, x, y, translated)

    def show_popup(self, x, y, text):
        self.destroy_popup()

        self.popup = tk.Toplevel(self.root)
        self.popup.overrideredirect(True)
        self.popup.attributes('-topmost', True)
        self.popup.attributes('-alpha', ALPHA)

        font = (FONT_FAMILY, FONT_SIZE, FONT_WEIGHT)
        label = tk.Label(
            self.popup, text=text, font=font,
            bg=BG_COLOR, fg=FG_COLOR,
            padx=8, pady=4, wraplength=400, justify='left'
        )
        label.pack()

        self.popup.update_idletasks()
        win_w = self.popup.winfo_width()
        win_h = self.popup.winfo_height()
        pos_x = x + 10
        pos_y = y - win_h - 20

        screen_w = self.popup.winfo_screenwidth()
        screen_h = self.popup.winfo_screenheight()
        if pos_x + win_w > screen_w:
            pos_x = screen_w - win_w - 5
        if pos_y < 0:
            pos_y = y + 20
        if pos_y + win_h > screen_h:
            pos_y = screen_h - win_h - 5

        self.popup.geometry(f"+{pos_x}+{pos_y}")
        self.after_id = self.popup.after(int(DISPLAY_DURATION * 1000), self.destroy_popup)

    def destroy_popup(self):
        if self.after_id:
            try:
                self.popup.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None
        if self.popup:
            try:
                self.popup.destroy()
            except Exception:
                pass
            self.popup = None

    # ---------- 系统托盘 ----------
    def _create_image(self):
        width, height = 16, 16
        image = Image.new('RGB', (width, height), color='#4A90D9')
        draw = ImageDraw.Draw(image)
        draw.text((3, 1), "T", fill="white")
        return image

    def _run_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("退出", self.quit_app)
        )
        self.tray_icon = pystray.Icon(
            "HoverTranslator",
            self._create_image(),
            "划词翻译 (运行中)",
            menu
        )
        self.tray_icon.run()

    def quit_app(self, icon=None, item=None):
        if self.mouse_listener and self.mouse_listener.running:
            self.mouse_listener.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.destroy_popup()
        self.root.quit()
        self.root.destroy()
        sys.exit(0)


if __name__ == "__main__":
    app = FloatingTranslator()
    app.start()
