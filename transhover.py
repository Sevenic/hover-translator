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
from pynput.keyboard import Controller as KeyboardController, Key as KeyboardKey
import pyperclip
from deep_translator import GoogleTranslator

# 系统托盘
import pystray
from PIL import Image, ImageDraw

# ---------- 学术现代设计语言 ----------
BG_COLOR = "#FFFFFF"
FG_COLOR = "#1D1D1F"
BORDER_COLOR = "#D2D2D7"
SEL_BG_COLOR = "#B3D7FF"
SEL_FG_COLOR = "#000000"
MUTED_FG_COLOR = "#86868B"
ALPHA = 0.98
DISPLAY_DURATION = 5.0
LEAVE_DURATION = 1.0
MAX_TEXT_LENGTH = 3500
CACHE_SIZE = 500
LOCAL_DICT_FILE = "local_dict.csv"
LOG_FILE = "translator.txt"

INVALID_TEXTS = {"undefined", "null", "none", "true", "false", "nan", "infinity", "-infinity"}

def log(msg):
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
        self.text_widget = None
        self.after_id = None
        self.mouse_listener = None
        self.tray_icon = None
        self.last_text = ""
        self.translation_cache = {}
        self.local_dict = {}
        
        self.font_family = "Microsoft YaHei UI"
        self.font_size = 14
        self.target_lang = "zh-CN"
        self.last_click_time = 0
        self.is_pinned = False
        
        sys.excepthook = self.global_exception_handler
        atexit.register(self.cleanup)

        if sys.platform == 'win32':
            try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except: pass
        
        self.local_dict = self._load_local_dict()

    def global_exception_handler(self, exc_type, exc_value, exc_tb):
        err_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log(f"*** 未捕获异常 ***\n{err_msg}")

    def cleanup(self):
        try: self.destroy_popup()
        except: pass

    def _load_local_dict(self):
        """只读加载本地词典，不自动创建文件，避免权限错误"""
        local = {}
        # 优先查找程序所在目录的 local_dict.csv（或 academic_terms.csv）
        dict_path = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(__file__), LOCAL_DICT_FILE)
        # 也可尝试同目录下的 academic_terms.csv
        alt_path = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(__file__), "academic_terms.csv")
        for path in [dict_path, alt_path]:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        reader = csv.reader(f)
                        for row in reader:
                            if len(row) >= 2:
                                local[row[0].strip().lower()] = row[1].strip()
                    log(f"已加载本地词典: {path}, 词条数: {len(local)}")
                    break
                except Exception as e:
                    log(f"加载词典失败: {e}")
        return local

    def start(self):
        try:
            self.mouse_listener = mouse.Listener(on_click=self.on_click)
            self.mouse_listener.daemon = True
            self.mouse_listener.start()
            threading.Thread(target=self._run_tray, daemon=True).start()
            self.root.mainloop()
        except Exception as e:
            log(f"启动失败: {e}")
            sys.exit(1)

    def on_click(self, x, y, button, pressed):
        if button == mouse.Button.left and not pressed:
            now = time.time()
            if now - self.last_click_time < 0.2: return
            self.last_click_time = now
            threading.Thread(target=self._async_handle_selection, args=(x, y), daemon=True).start()

    def _async_handle_selection(self, x, y):
        time.sleep(0.12)
        try: self.handle_selection(x, y)
        except Exception as e: log(f"处理选中文本出错: {e}")

    def _copy_selected_text(self):
        try: old_clip = pyperclip.paste()
        except: old_clip = ""
        for attempt in range(2):
            self._do_ctrl_c()
            time.sleep(0.1)
            try: new_clip = pyperclip.paste()
            except: continue
            if isinstance(new_clip, str) and new_clip != old_clip and is_valid_text(new_clip):
                return new_clip.strip()
            if attempt == 0: time.sleep(0.05)
        return ""

    def _do_ctrl_c(self):
        kb = KeyboardController()
        with kb.pressed(KeyboardKey.ctrl):
            kb.press('c')
            time.sleep(0.01)
            kb.release('c')
        # 确保释放左右 Ctrl
        kb.release(KeyboardKey.ctrl)
        kb.release(KeyboardKey.ctrl_l)
        kb.release(KeyboardKey.ctrl_r)

    def _smart_clean_text(self, text):
        """修复 PDF 碎片化换行，保留段落结构"""
        if self.contains_chinese(text):
            text = re.sub(r'\s*\n\s*', '', text)
        else:
            text = re.sub(r'([a-zA-Z]+)-\s*\n\s*([a-zA-Z]+)', r'\1\2', text)
            text = text.replace('\r\n', '\n')
            text = re.sub(r'(\.|\:|\?|\!)\s*\n', r'\1<PARAGRAPH_BREAK>', text)
            text = re.sub(r'\n{2,}', '<PARAGRAPH_BREAK>', text)
            text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
            text = text.replace('<PARAGRAPH_BREAK>', '\n\n')
        return re.sub(r' {2,}', ' ', text).strip()

    def handle_selection(self, x, y):
        raw_text = self._copy_selected_text()
        if not raw_text: return
        text = self._smart_clean_text(raw_text)
        if text == self.last_text or not text: return
        self.last_text = text
        self.process_translation(x, y, text)

    def contains_chinese(self, text: str) -> bool:
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    def process_translation(self, x, y, text):
        try:
            cache_key = f"{self.target_lang}_{text}"
            if cache_key in self.translation_cache:
                self.root.after(0, self.show_popup, x, y, self.translation_cache[cache_key], False)
                return

            if len(text) > 100:
                self.root.after(0, self.show_popup, x, y, "⏳ 正在翻译长段落，请稍候...", True)

            if not self.contains_chinese(text) and ' ' not in text and len(text) < 50:
                clean_word = text.lower().strip('.,!?;:\'"')
                local_result = self.local_dict.get(clean_word)
                translated = local_result if local_result else self._online_translate(text)
            else:
                translated = self._online_translate(text)

            if translated:
                if len(self.translation_cache) >= CACHE_SIZE:
                    del self.translation_cache[next(iter(self.translation_cache))]
                self.translation_cache[cache_key] = translated
                self.root.after(0, self.update_popup_content, translated)
            else:
                self.root.after(0, self.update_popup_content, "❌ 翻译失败")
        except Exception as e: log(f"翻译处理异常: {e}")

    def _online_translate(self, text):
        try:
            target = 'en' if self.contains_chinese(text) else self.target_lang
            return GoogleTranslator(source='auto', target=target).translate(text)
        except Exception as e:
            log(f"在线翻译失败: {e}")
            return None

    def show_popup(self, x, y, text, is_loading):
        self.destroy_popup()
        self.is_pinned = False
        
        self.popup = tk.Toplevel(self.root)
        self.popup.overrideredirect(True)
        self.popup.attributes('-topmost', True)
        self.popup.attributes('-alpha', ALPHA)
        
        border_frame = tk.Frame(self.popup, bg=BORDER_COLOR, bd=0)
        border_frame.pack(fill=tk.BOTH, expand=True)
        inner_frame = tk.Frame(border_frame, bg=BG_COLOR, bd=0)
        inner_frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        display_width = 65
        font = (self.font_family, self.font_size, "normal")
        curr_fg = MUTED_FG_COLOR if is_loading else FG_COLOR
        
        self.text_widget = tk.Text(inner_frame, 
                              font=font, 
                              bg=BG_COLOR, 
                              fg=curr_fg, 
                              selectbackground=SEL_BG_COLOR,
                              selectforeground=SEL_FG_COLOR,
                              padx=24, pady=20,
                              wrap=tk.WORD, 
                              width=display_width, 
                              height=2,
                              spacing1=8,
                              spacing2=8,
                              borderwidth=0, 
                              highlightthickness=0, 
                              relief='flat')
        self.text_widget.pack(fill=tk.BOTH, expand=True)
        self._insert_and_resize(text)
        
        # 事件绑定
        self.text_widget.bind("<Key>", self._readonly_key_handler)
        self.text_widget.bind("<Control-a>", self._select_all)
        self.text_widget.bind("<Control-A>", self._select_all)
        self.text_widget.bind("<Button-1>", self._pin_popup)
        self.popup.bind("<Escape>", lambda e: self.destroy_popup())
        self.text_widget.bind("<Escape>", lambda e: self.destroy_popup())
        
        self.popup.update_idletasks()
        win_w, win_h = self.popup.winfo_width(), self.popup.winfo_height()
        pos_x, pos_y = x + 15, y + 25
        screen_w, screen_h = self.popup.winfo_screenwidth(), self.popup.winfo_screenheight()
        if pos_x + win_w > screen_w: pos_x = screen_w - win_w - 10
        if pos_y + win_h > screen_h: pos_y = y - win_h - 15
        self.popup.geometry(f"+{pos_x}+{pos_y}")

        def on_enter(event):
            if self.after_id:
                self.popup.after_cancel(self.after_id)
                self.after_id = None
        def on_leave(event):
            if self.is_pinned: return
            if self.after_id: self.popup.after_cancel(self.after_id)
            self.after_id = self.popup.after(int(LEAVE_DURATION * 1000), self.destroy_popup)

        self.popup.bind("<Enter>", on_enter)
        self.popup.bind("<Leave>", on_leave)
        self.text_widget.bind("<Enter>", on_enter)
        self.text_widget.bind("<Leave>", on_leave)

        dur = 10.0 if is_loading else DISPLAY_DURATION
        self.after_id = self.popup.after(int(dur * 1000), self.destroy_popup)

    def update_popup_content(self, translated_text):
        if not self.popup or not self.text_widget: return
        self.text_widget.config(fg=FG_COLOR)
        self._insert_and_resize(translated_text)

    def _insert_and_resize(self, text):
        self.text_widget.config(state=tk.NORMAL)
        self.text_widget.delete("1.0", tk.END)
        self.text_widget.insert(tk.END, text)
        lines = text.split('\n')
        total_lines = 0
        for line in lines:
            total_lines += max(1, (len(line) // (self.text_widget.cget('width') - 2)) + 1)
        display_height = max(2, min(total_lines, 25))
        self.text_widget.config(height=display_height)
        self.text_widget.config(state=tk.DISABLED)

    def _pin_popup(self, event):
        self.is_pinned = True
        self.text_widget.focus_set()
        if self.after_id:
            self.popup.after_cancel(self.after_id)
            self.after_id = None

    def _select_all(self, event):
        self.text_widget.tag_add(tk.SEL, "1.0", tk.END)
        self.text_widget.mark_set(tk.INSERT, "1.0")
        self.text_widget.see(tk.INSERT)
        return 'break'

    def _readonly_key_handler(self, event):
        if event.state & 0x0004 and event.keysym.lower() in ['c', 'a']: return None
        if event.keysym in ['Up', 'Down', 'Left', 'Right', 'Prior', 'Next', 'Home', 'End']: return None
        if event.keysym == 'Escape':
            self.destroy_popup()
            return "break"
        return "break"

    def destroy_popup(self):
        if self.after_id:
            try: self.popup.after_cancel(self.after_id)
            except: pass
            self.after_id = None
        if self.popup:
            try: self.popup.destroy()
            except: pass
            self.popup = None
        self.last_text = ""

    # ---------- 系统托盘 ----------
    def _create_image(self):
        image = Image.new('RGB', (16, 16), color='#1D1D1F') 
        draw = ImageDraw.Draw(image)
        draw.text((3, 1), "T", fill="#FFFFFF")
        return image

    def _run_tray(self):
        try:
            def set_lang(lang): self.target_lang = lang
            def set_font(font): self.font_family = font
            def set_size(size): self.font_size = size

            menu = pystray.Menu(
                pystray.MenuItem("翻译目标", pystray.Menu(
                    pystray.MenuItem("简体中文 (zh-CN)", lambda: set_lang("zh-CN"), checked=lambda item: self.target_lang == "zh-CN"),
                    pystray.MenuItem("繁体中文 (zh-TW)", lambda: set_lang("zh-TW"), checked=lambda item: self.target_lang == "zh-TW")
                )),
                pystray.MenuItem("文本字号", pystray.Menu(
                    pystray.MenuItem("标准 (12px)", lambda: set_size(12), checked=lambda item: self.font_size == 12),
                    pystray.MenuItem("中等 (14px)", lambda: set_size(14), checked=lambda item: self.font_size == 14),
                    pystray.MenuItem("大号 (16px)", lambda: set_size(16), checked=lambda item: self.font_size == 16)
                )),
                pystray.MenuItem("界面字体", pystray.Menu(
                    pystray.MenuItem("系统雅黑", lambda: set_font("Microsoft YaHei UI"), checked=lambda item: self.font_family == "Microsoft YaHei UI"),
                    pystray.MenuItem("Segoe UI", lambda: set_font("Segoe UI"), checked=lambda item: self.font_family == "Segoe UI")
                )),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出程序", self.quit_app)
            )
            self.tray_icon = pystray.Icon("HoverTranslator", self._create_image(), "学术划词器", menu)
            self.tray_icon.run()
        except: pass

    def quit_app(self, icon=None, item=None):
        if self.mouse_listener and self.mouse_listener.running: self.mouse_listener.stop()
        if self.tray_icon: self.tray_icon.stop()
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
        msgbox.showerror("启动失败", str(e))
