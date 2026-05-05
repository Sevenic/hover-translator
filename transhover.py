import re
import time
import threading
import tkinter as tk
import ctypes
import sys
import platform
import csv
import os
from pynput import mouse
import pyperclip
from deep_translator import GoogleTranslator

# 系统托盘
import pystray
from PIL import Image, ImageDraw

# ---------- 用户配置 ----------
FONT_FAMILY = "微软雅黑"
FONT_SIZE = 18
FONT_WEIGHT = "normal"
BG_COLOR = "#FFFFE0"
FG_COLOR = "#000000"
ALPHA = 0.85
DISPLAY_DURATION = 3.0
MAX_TEXT_LENGTH = 500
CACHE_SIZE = 500                    # 在线翻译缓存条数
LOCAL_DICT_FILE = "local_dict.csv"  # 本地词典文件（可选）
# --------------------------------

class FloatingTranslator:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.popup = None
        self.after_id = None
        self.mouse_listener = None
        self.tray_icon = None
        self.last_text = ""
        self.translation_cache = {}
        self.local_dict = self._load_local_dict()   # 加载本地词典

        if sys.platform == 'win32':
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

    def _load_local_dict(self):
        """加载本地词典 CSV，格式：英文,中文"""
        dict_path = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(__file__), LOCAL_DICT_FILE)
        local = {}
        if os.path.exists(dict_path):
            try:
                with open(dict_path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 2:
                            key = row[0].strip().lower()
                            if key and key not in local:
                                local[key] = row[1].strip()
            except Exception as e:
                print(f"加载本地词典失败: {e}")
        return local

    def start(self):
        self.mouse_listener = mouse.Listener(on_click=self.on_click)
        self.mouse_listener.daemon = True
        self.mouse_listener.start()
        threading.Thread(target=self._run_tray, daemon=True).start()
        self.root.mainloop()

    def on_click(self, x, y, button, pressed):
        if button == mouse.Button.left and not pressed:
            self.handle_selection(x, y)

    # ---------- 无侵入复制 ----------
    def _copy_selected_text(self):
        if platform.system() == "Windows":
            self._win32_ctrl_c()
        else:
            self._cross_platform_ctrl_c()
        time.sleep(0.05)          # 缩短等待，提升响应
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
        if not text or len(text) > MAX_TEXT_LENGTH:
            return
        if text == self.last_text:
            return
        self.last_text = text
        # 立即在后台翻译
        threading.Thread(target=self.translate_and_show, args=(x, y, text), daemon=True).start()

    def contains_chinese(self, text: str) -> bool:
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    def translate_and_show(self, x, y, text):
        # 1. 先查在线缓存
        cache_key = text.strip()
        if cache_key in self.translation_cache:
            translated = self.translation_cache[cache_key]
        else:
            # 2. 尝试本地词典 (仅纯英文单词，无空格且长度<50)
            if not self.contains_chinese(text) and ' ' not in text and len(text) < 50:
                local_result = self.local_dict.get(text.lower().strip('.,!?;:\'"'))
                if local_result:
                    translated = local_result
                else:
                    translated = self._online_translate(text)
            else:
                translated = self._online_translate(text)

            # 写入缓存
            if translated:
                if len(self.translation_cache) >= CACHE_SIZE:
                    first_key = next(iter(self.translation_cache))
                    del self.translation_cache[first_key]
                self.translation_cache[cache_key] = translated

        if translated:
            self.root.after(0, self.show_popup, x, y, translated)

    def _online_translate(self, text):
        """在线翻译（Google，可替换为其他源）"""
        try:
            target = 'en' if self.contains_chinese(text) else 'zh-CN'
            translator = GoogleTranslator(source='auto', target=target)
            # 设置超时，避免长时间卡死
            # 注意：deep-translator 内部使用 requests，可通过 session 传递 timeout
            import requests
            session = requests.Session()
            session.request = lambda *args, **kwargs: requests.Session.request(session, *args, **kwargs)  # 包装
            # 简单粗暴：直接设置全局默认超时（不影响外部）
            old_timeout = requests.models.DEFAULT_TIMEOUT
            requests.models.DEFAULT_TIMEOUT = 5
            result = translator.translate(text)
            requests.models.DEFAULT_TIMEOUT = old_timeout
            return result
        except Exception as e:
            print(f"在线翻译失败: {e}")
            return None

    def show_popup(self, x, y, text):
        self.destroy_popup()

        self.popup = tk.Toplevel(self.root)
        self.popup.overrideredirect(True)
        self.popup.attributes('-topmost', True)
        self.popup.attributes('-alpha', ALPHA)

        # 使用 Text 组件，允许选择和复制
        font = (FONT_FAMILY, FONT_SIZE, FONT_WEIGHT)
        text_widget = tk.Text(
            self.popup,
            font=font,
            bg=BG_COLOR,
            fg=FG_COLOR,
            padx=8,
            pady=4,
            wrap=tk.WORD,
            width=len(text) + 4 if len(text) < 40 else 40,  # 粗略宽度
            height=2 if len(text) < 50 else 3,
            borderwidth=0,
            highlightthickness=0,
            relief='flat',
            state=tk.NORMAL
        )
        text_widget.insert(tk.END, text)
        text_widget.configure(state=tk.DISABLED)   # 只读
        text_widget.pack()

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
