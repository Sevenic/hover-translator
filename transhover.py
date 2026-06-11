import re
import time
import threading
import tkinter as tk
import ctypes
import sys
import platform
import csv
import os
import traceback
import atexit
from pynput import mouse
import pyperclip
from deep_translator import GoogleTranslator

# 系统托盘
import pystray
from PIL import Image, ImageDraw

# ---------- UI与用户配置 (已美化) ----------
FONT_FAMILY = "Microsoft YaHei UI" # 更现代的系统字体
FONT_SIZE = 16                     # 调整为16，比18精致，比12清晰
FONT_WEIGHT = "normal"
BG_COLOR = "#FFFFFF"               # 纯白背景
FG_COLOR = "#2C3E50"               # 深灰蓝字体，比纯黑更护眼
BORDER_COLOR = "#E0E4E8"           # 极浅的边框色，模拟精致感
ALPHA = 0.95                       # 稍微提高不透明度，提升文字清晰度
DISPLAY_DURATION = 3.0
LEAVE_DURATION = 1.5
MAX_TEXT_LENGTH = 500
CACHE_SIZE = 500
LOCAL_DICT_FILE = "local_dict.csv"
LOG_FILE = "translator.txt"
LOG_LEVEL = 1                      # 0: 关闭, 1: 仅错误/关键, 2: 全部

# --------------------------------
INVALID_TEXTS = {"undefined", "null", "none", "true", "false", "nan", "infinity", "-infinity"}

def log(msg, level=2):
    if LOG_LEVEL >= level:
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%H:%M:%S')} - {msg}\n")
        except:
            pass

def is_valid_text(text: str) -> bool:
    if not text or len(text) > MAX_TEXT_LENGTH: return False
    if text.lower() in INVALID_TEXTS: return False
    if not re.search(r'[a-zA-Z\u4e00-\u9fff]', text): return False
    return True

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
        self.local_dict = {}
        
        self.last_click_time = 0 # 用于防抖
        
        sys.excepthook = self.global_exception_handler
        atexit.register(self.cleanup)

        log("程序启动中...", level=1)
        if sys.platform == 'win32':
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
                log("DPI 感知已启用", level=1)
            except Exception as e:
                log(f"DPI 设置失败: {e}", level=1)
        
        self.local_dict = self._load_local_dict()
        log(f"本地词典加载完成，共 {len(self.local_dict)} 条", level=1)

    def global_exception_handler(self, exc_type, exc_value, exc_tb):
        err_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log(f"*** 未捕获异常 ***\n{err_msg}", level=1)

    def cleanup(self):
        try:
            self.destroy_popup()
        except:
            pass

    def _load_local_dict(self):
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(__file__)
            
        dict_path = os.path.join(base_path, LOCAL_DICT_FILE)
        local = {}
        if not os.path.exists(dict_path):
            return local
            
        try:
            with open(dict_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2:
                        key = row[0].strip().lower()
                        if key and key not in local:
                            local[key] = row[1].strip()
        except Exception as e:
            log(f"加载本地词典失败: {traceback.format_exc()}", level=1)
        return local

    def start(self):
        try:
            self.mouse_listener = mouse.Listener(on_click=self.on_click)
            self.mouse_listener.daemon = True
            self.mouse_listener.start()
            log("鼠标监听已启动", level=1)
            
            threading.Thread(target=self._run_tray, daemon=True).start()
            self.root.mainloop()
        except Exception as e:
            log(f"启动失败: {traceback.format_exc()}", level=1)
            sys.exit(1)

    # ---------------- 核心性能优化区 ----------------
    def on_click(self, x, y, button, pressed):
        """系统底层鼠标回调：必须做到极速返回，绝不阻塞！"""
        if button == mouse.Button.left and not pressed:
            now = time.time()
            # 防抖：如果距离上次点击释放不足 0.2 秒，直接忽略
            if now - self.last_click_time < 0.2:
                return
            self.last_click_time = now
            
            # 瞬间将任务扔给后台线程，立即释放鼠标系统控制权
            threading.Thread(target=self._async_handle_selection, args=(x, y), daemon=True).start()

    def _async_handle_selection(self, x, y):
        """在完全独立的后台线程中执行等待和复制"""
        time.sleep(0.1) # 留出足够的时间让双击选中高亮生效
        try:
            self.handle_selection(x, y)
        except Exception as e:
            log(f"处理选中文本时出错: {traceback.format_exc()}", level=1)
    # ------------------------------------------------

    def _copy_selected_text(self):
        try:
            old_clip = pyperclip.paste()
        except:
            old_clip = ""
            
        for attempt in range(2):
            if platform.system() == "Windows":
                self._win32_ctrl_c()
            else:
                self._cross_platform_ctrl_c()
            
            time.sleep(0.12)
            try:
                new_clip = pyperclip.paste()
            except:
                continue
                
            if isinstance(new_clip, str) and new_clip != old_clip and is_valid_text(new_clip):
                return new_clip.strip()
            
            if attempt == 0:
                time.sleep(0.08)
        return ""

    def _win32_ctrl_c(self):
        VK_CONTROL, VK_C = 0x11, 0x43
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_C, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    def _cross_platform_ctrl_c(self):
        from pynput.keyboard import Controller, Key
        kb = Controller()
        kb.press(Key.ctrl)
        kb.press('c')
        kb.release('c')
        kb.release(Key.ctrl)

    def handle_selection(self, x, y):
        text = self._copy_selected_text()
        if not text: return
        if text == self.last_text: return
        
        self.last_text = text
        log(f"选中文本: {text}", level=2)
        
        # 获取文本后，直接在当前独立线程请求翻译即可，无需再开新线程
        self.translate_and_show(x, y, text)

    def contains_chinese(self, text: str) -> bool:
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    def translate_and_show(self, x, y, text):
        try:
            cache_key = text.strip()
            if cache_key in self.translation_cache:
                translated = self.translation_cache[cache_key]
                log(f"缓存命中: {cache_key}", level=2)
            else:
                if not self.contains_chinese(text) and ' ' not in text and len(text) < 50:
                    clean_word = text.lower().strip('.,!?;:\'"')
                    local_result = self.local_dict.get(clean_word)
                    if local_result:
                        translated = local_result
                        log(f"本地词典命中", level=2)
                    else:
                        translated = self._online_translate(text)
                else:
                    translated = self._online_translate(text)

            if translated:
                if len(self.translation_cache) >= CACHE_SIZE:
                    first_key = next(iter(self.translation_cache))
                    del self.translation_cache[first_key]
                self.translation_cache[cache_key] = translated
                
                # 回到主线程更新 UI
                self.root.after(0, self.show_popup, x, y, translated)
        except Exception as e:
            log(f"翻译处理异常: {traceback.format_exc()}", level=1)

    def _online_translate(self, text):
        try:
            target = 'en' if self.contains_chinese(text) else 'zh-CN'
            result = GoogleTranslator(source='auto', target=target).translate(text)
            log(f"在线翻译成功", level=2)
            return result
        except Exception as e:
            log(f"在线翻译失败: {traceback.format_exc()}", level=1)
            return None

    # ---------------- UI 美化区 ----------------
    def show_popup(self, x, y, text):
        self.destroy_popup()
        
        self.popup = tk.Toplevel(self.root)
        self.popup.overrideredirect(True)
        self.popup.attributes('-topmost', True)
        self.popup.attributes('-alpha', ALPHA)
        
        # 嵌套 Frame 模拟精美边框效果
        border_frame = tk.Frame(self.popup, bg=BORDER_COLOR, bd=0)
        border_frame.pack(fill=tk.BOTH, expand=True)
        
        inner_frame = tk.Frame(border_frame, bg=BG_COLOR, bd=0)
        inner_frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1) # 留出 1px 的边框

        font = (FONT_FAMILY, FONT_SIZE, FONT_WEIGHT)
        text_widget = tk.Text(inner_frame, 
                              font=font, 
                              bg=BG_COLOR, 
                              fg=FG_COLOR, 
                              padx=12, pady=8,       # 增加内边距，让文字更有呼吸感
                              wrap=tk.WORD, 
                              width=min(len(text) + 6, 50), # 宽度自适应优化
                              height=min(4, max(2, text.count('\n') + 1)), 
                              borderwidth=0, 
                              highlightthickness=0, 
                              relief='flat')
        
        text_widget.insert(tk.END, text)
        text_widget.configure(state=tk.DISABLED)
        text_widget.pack()
        
        self.popup.update_idletasks()
        win_w = self.popup.winfo_width()
        win_h = self.popup.winfo_height()
        
        # 优化显示位置：稍微偏右下一点，避免挡住光标选中的原始文本
        pos_x = x + 15 
        pos_y = y + 20 
        
        screen_w = self.popup.winfo_screenwidth()
        screen_h = self.popup.winfo_screenheight()
        
        # 边界碰撞检测
        if pos_x + win_w > screen_w: pos_x = screen_w - win_w - 5
        if pos_y + win_h > screen_h: pos_y = y - win_h - 15
        
        self.popup.geometry(f"+{pos_x}+{pos_y}")

        # 悬停事件绑定
        def on_enter(event):
            if self.after_id:
                self.popup.after_cancel(self.after_id)
                self.after_id = None
                
        def on_leave(event):
            if self.after_id:
                self.popup.after_cancel(self.after_id)
            self.after_id = self.popup.after(int(LEAVE_DURATION * 1000), self.destroy_popup)

        self.popup.bind("<Enter>", on_enter)
        self.popup.bind("<Leave>", on_leave)
        text_widget.bind("<Enter>", on_enter)
        text_widget.bind("<Leave>", on_leave)

        self.after_id = self.popup.after(int(DISPLAY_DURATION * 1000), self.destroy_popup)

    def destroy_popup(self):
        if self.after_id:
            try: self.popup.after_cancel(self.after_id)
            except: pass
            self.after_id = None
            
        if self.popup:
            try: self.popup.destroy()
            except: pass
            self.popup = None

    # ---------- 系统托盘 ----------
    def _create_image(self):
        width, height = 16, 16
        image = Image.new('RGB', (width, height), color='#4A90D9')
        draw = ImageDraw.Draw(image)
        draw.text((3, 1), "T", fill="white")
        return image

    def _run_tray(self):
        try:
            menu = pystray.Menu(pystray.MenuItem("退出", self.quit_app))
            self.tray_icon = pystray.Icon("HoverTranslator", self._create_image(), "划词翻译 (运行中)", menu)
            self.tray_icon.notify("划词翻译已启动", title="HoverTranslator")
            self.tray_icon.run()
        except Exception as e:
            log(f"托盘启动失败: {traceback.format_exc()}", level=1)

    def quit_app(self, icon=None, item=None):
        log("用户退出程序", level=1)
        if self.mouse_listener and self.mouse_listener.running:
            self.mouse_listener.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.destroy_popup()
        self.root.quit()
        self.root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    try:
        app = FloatingTranslator()
        app.start()
    except Exception as e:
        import tkinter.messagebox as msgbox
        msgbox.showerror("启动失败", f"程序启动失败，请查看 translator.txt\n错误：{str(e)}")
