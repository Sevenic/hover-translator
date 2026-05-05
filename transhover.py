import re
import time
import threading
import tkinter as tk
import ctypes
import sys
from pynput import mouse, keyboard
import pyperclip
from deep_translator import GoogleTranslator

# ---------- 配置 ----------
FONT = ("微软雅黑", 12)          # 翻译显示字体
BG_COLOR = "#FFFFE0"           # 浅黄背景色
FG_COLOR = "#000000"           # 文字颜色
ALPHA = 0.85                   # 窗口透明度
DISPLAY_DURATION = 3.0         # 显示秒数
# -----------------------

class FloatingTranslator:
    def __init__(self):
        self.popup = None
        self.after_id = None    # 用于 after 销毁定时器
        self.keyboard_ctrl = keyboard.Controller()
        # 确保 Tk 仅主线程创建
        self.root = tk.Tk()
        self.root.withdraw()

        # 开启 Windows DPI 感知，解决高分屏坐标偏移问题
        if sys.platform == 'win32':
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
            except Exception:
                pass

    def start(self):
        """启动鼠标监听"""
        listener = mouse.Listener(on_click=self.on_click)
        listener.daemon = True
        listener.start()
        self.root.mainloop()

    def on_click(self, x, y, button, pressed):
        """鼠标左键释放时触发"""
        if button == mouse.Button.left and not pressed:
            # 在主线程中尽快处理剪贴板复制与还原，翻译显示放到后台线程
            self.handle_selection(x, y)

    def handle_selection(self, x, y):
        """获取选中文本并立即还原剪贴板，然后异步翻译显示"""
        # ---- 第一步：安全备份当前剪贴板 ----
        try:
            old_clip = pyperclip.paste()
        except Exception:
            old_clip = ""

        # ---- 第二步：模拟 Ctrl+C 复制选中文本 ----
        try:
            self.keyboard_ctrl.press(keyboard.Key.ctrl)
            self.keyboard_ctrl.press('c')
            time.sleep(0.05)               # 等待复制完成
            self.keyboard_ctrl.release('c')
            self.keyboard_ctrl.release(keyboard.Key.ctrl)
            time.sleep(0.05)
        except Exception:
            # 按键失败也要尽量还原剪贴板
            self.safe_restore_clipboard(old_clip)
            return

        # ---- 第三步：立即获取文本 ----
        try:
            text = pyperclip.paste()
        except Exception:
            text = ""

        # ---- 第四步：立即还原剪贴板（最高优先级） ----
        self.safe_restore_clipboard(old_clip)

        # ---- 第五步：过滤无效文本 ----
        if not text or len(text) > 500:
            return

        # ---- 第六步：后台线程进行翻译和显示，完全不阻塞剪贴板 ----
        threading.Thread(target=self.translate_and_show, args=(x, y, text), daemon=True).start()

    def safe_restore_clipboard(self, content):
        """绝对安全的剪贴板还原"""
        try:
            if content is not None:
                pyperclip.copy(content)
            else:
                pyperclip.copy("")
        except Exception:
            pass

    def contains_chinese(self, text: str) -> bool:
        """检测文本是否包含中文汉字"""
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    def translate_and_show(self, x, y, text):
        """后台翻译并调主线程显示弹窗"""
        if self.contains_chinese(text):
            target_lang = 'en'
        else:
            target_lang = 'zh-CN'

        translated = None
        try:
            translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
        except Exception as e:
            print(f"翻译失败: {e}")
            return

        if translated:
            # 调度到主线程显示弹窗
            self.root.after(0, self.show_popup, x, y, translated)

    def show_popup(self, x, y, text):
        """在主线程中安全显示悬浮窗"""
        # 先清理旧弹窗（包括取消旧的 after 定时器）
        self.destroy_popup()

        self.popup = tk.Toplevel(self.root)
        self.popup.overrideredirect(True)
        self.popup.attributes('-topmost', True)
        self.popup.attributes('-alpha', ALPHA)

        label = tk.Label(
            self.popup,
            text=text,
            font=FONT,
            bg=BG_COLOR,
            fg=FG_COLOR,
            padx=8,
            pady=4,
            wraplength=400,
            justify='left'
        )
        label.pack()

        # 窗口定位：光标上方偏移（考虑 DPI 后坐标已准确）
        self.popup.update_idletasks()
        win_w = self.popup.winfo_width()
        win_h = self.popup.winfo_height()

        pos_x = x + 10
        pos_y = y - win_h - 20

        # 屏幕边界保护
        screen_w = self.popup.winfo_screenwidth()
        screen_h = self.popup.winfo_screenheight()
        if pos_x + win_w > screen_w:
            pos_x = screen_w - win_w - 5
        if pos_y < 0:
            pos_y = y + 20
        if pos_y + win_h > screen_h:
            pos_y = screen_h - win_h - 5

        self.popup.geometry(f"+{pos_x}+{pos_y}")

        # 使用 after 设置自动消失（线程安全）
        self.after_id = self.popup.after(int(DISPLAY_DURATION * 1000), self.destroy_popup)

    def destroy_popup(self):
        """安全销毁悬浮窗"""
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


if __name__ == "__main__":
    translator = FloatingTranslator()
    translator.start()
