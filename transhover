import re
import time
import threading
import tkinter as tk
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
        self.hide_timer = None
        # 键盘控制器用于发送 Ctrl+C
        self.keyboard_ctrl = keyboard.Controller()

    def start(self):
        """启动鼠标监听"""
        listener = mouse.Listener(on_click=self.on_click)
        listener.daemon = True
        listener.start()
        # Tkinter 主循环需在主线程运行
        self.root = tk.Tk()
        self.root.withdraw()  # 隐藏主窗口
        self.root.after(100, self.check_threads)  # 保持事件循环
        self.root.mainloop()

    def check_threads(self):
        """保持 Tk 事件循环运行"""
        self.root.after(100, self.check_threads)

    def on_click(self, x, y, button, pressed):
        """鼠标点击事件：左键释放时触发翻译"""
        if button == mouse.Button.left and not pressed:
            # 延迟一点确保选中动作完成
            threading.Thread(target=self.handle_selection, args=(x, y), daemon=True).start()

    def handle_selection(self, x, y):
        """获取选中文本，翻译并显示"""
        # 备份当前剪贴板
        old_clip = None
        try:
            old_clip = pyperclip.paste()
        except Exception:
            pass

        # 模拟 Ctrl+C 复制选中文字
        try:
            self.keyboard_ctrl.press(keyboard.Key.ctrl)
            self.keyboard_ctrl.press('c')
            time.sleep(0.1)                  # 等待复制完成
            self.keyboard_ctrl.release('c')
            self.keyboard_ctrl.release(keyboard.Key.ctrl)
            time.sleep(0.1)
        except Exception:
            self.restore_clipboard(old_clip)
            return

        # 获取当前剪贴板内容
        try:
            text = pyperclip.paste()
        except Exception:
            text = ""

        # 还原剪贴板
        self.restore_clipboard(old_clip)

        # 空文本或过长文本不处理（可自行调整长度限制）
        if not text or len(text) > 500:
            return

        # 判断语言并翻译
        if self.contains_chinese(text):
            target_lang = 'en'       # 中文 -> 英文
        else:
            target_lang = 'zh-CN'    # 英文 -> 中文

        translated = self.translate(text, target_lang)
        if not translated:
            return

        # 在光标上方显示翻译
        self.show_popup(x, y, translated)

    def contains_chinese(self, text: str) -> bool:
        """检测文本是否包含中文汉字"""
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    def translate(self, text: str, target: str) -> str:
        """调用 Google 翻译"""
        try:
            result = GoogleTranslator(source='auto', target=target).translate(text)
            return result
        except Exception as e:
            print(f"翻译失败: {e}")
            return None

    def restore_clipboard(self, content):
        """安全还原剪贴板"""
        if content is not None:
            try:
                pyperclip.copy(content)
            except Exception:
                pass

    def show_popup(self, x, y, text):
        """在指定坐标上方显示悬浮翻译窗口"""
        # 先销毁之前的窗口
        self.destroy_popup()

        self.popup = tk.Toplevel(self.root)
        self.popup.overrideredirect(True)          # 无边框
        self.popup.attributes('-topmost', True)    # 始终置顶
        self.popup.attributes('-alpha', ALPHA)

        # 标签
        label = tk.Label(
            self.popup,
            text=text,
            font=FONT,
            bg=BG_COLOR,
            fg=FG_COLOR,
            padx=8,
            pady=4,
            wraplength=400,          # 自动换行
            justify='left'
        )
        label.pack()

        # 定位：光标上方偏移
        self.popup.update_idletasks()
        win_w = self.popup.winfo_width()
        win_h = self.popup.winfo_height()
        pos_x = x + 10
        pos_y = y - win_h - 20
        # 防止超出屏幕左上角
        if pos_y < 0:
            pos_y = y + 20
        if pos_x + win_w > self.popup.winfo_screenwidth():
            pos_x = self.popup.winfo_screenwidth() - win_w - 5
        self.popup.geometry(f"+{pos_x}+{pos_y}")

        # 设置自动消失定时器
        self.hide_timer = threading.Timer(DISPLAY_DURATION, self.destroy_popup)
        self.hide_timer.daemon = True
        self.hide_timer.start()

    def destroy_popup(self):
        """安全销毁悬浮窗口"""
        if self.hide_timer:
            self.hide_timer.cancel()
            self.hide_timer = None
        if self.popup:
            try:
                self.popup.destroy()
            except Exception:
                pass
            self.popup = None

if __name__ == "__main__":
    translator = FloatingTranslator()
    translator.start()
