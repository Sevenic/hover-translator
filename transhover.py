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

# ---------- 现代 UI 配色方案 ----------
BG_COLOR = "#FFFFFF"               # 纯白卡片背景
FG_COLOR = "#0F172A"               # 现代板岩灰（Slate 900），高端大气
BORDER_COLOR = "#E2E8F0"           # 极浅灰色边框（Slate 200）
ALPHA = 0.96                       # 极高不透明度，确保大文本清晰可读
DISPLAY_DURATION = 5.0             # 面对长文本，初始显示时间延长至 5 秒
LEAVE_DURATION = 1.2
MAX_TEXT_LENGTH = 1500             # 扩大长文本支持
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
        self.after_id = None
        self.mouse_listener = None
        self.tray_icon = None
        self.last_text = ""
        self.translation_cache = {}
        self.local_dict = {}
        
        # 动态用户配置项（可通过右键托盘随时修改）
        self.font_family = "Microsoft YaHei UI"
        self.font_size = 14
        self.target_lang = "zh-CN"  # 默认简体中文，可切换 zh-TW
        
        self.last_click_time = 0
        
        sys.excepthook = self.global_exception_handler
        atexit.register(self.cleanup)

        log("程序启动中...")
        if sys.platform == 'win32':
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
                log("DPI 感知已启用")
            except Exception as e:
                log(f"DPI 设置失败: {e}")
        
        self.local_dict = self._load_local_dict()
        log(f"本地词典加载完成，共 {len(self.local_dict)} 条")

    def global_exception_handler(self, exc_type, exc_value, exc_tb):
        err_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log(f"*** 未捕获异常 ***\n{err_msg}")

    def cleanup(self):
        try: self.destroy_popup()
        except: pass

    def _load_local_dict(self):
        if getattr(sys, 'frozen', False): base_path = sys._MEIPASS
        else: base_path = os.path.dirname(__file__)
        dict_path = os.path.join(base_path, LOCAL_DICT_FILE)
        local = {}
        if not os.path.exists(dict_path): return local
        try:
            with open(dict_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2:
                        key = row[0].strip().lower()
                        if key and key not in local: local[key] = row[1].strip()
        except Exception as e:
            log(f"加载本地词典失败: {traceback.format_exc()}")
        return local

    def start(self):
        try:
            self.mouse_listener = mouse.Listener(on_click=self.on_click)
            self.mouse_listener.daemon = True
            self.mouse_listener.start()
            log("鼠标监听已启动")
            
            threading.Thread(target=self._run_tray, daemon=True).start()
            self.root.mainloop()
        except Exception as e:
            log(f"启动失败: {traceback.format_exc()}")
            sys.exit(1)

    def on_click(self, x, y, button, pressed):
        if button == mouse.Button.left and not pressed:
            now = time.time()
            if now - self.last_click_time < 0.2: return
            self.last_click_time = now
            threading.Thread(target=self._async_handle_selection, args=(x, y), daemon=True).start()

    def _async_handle_selection(self, x, y):
        time.sleep(0.12)  # 给系统充足的时间完成渲染和高亮选中
        try:
            self.handle_selection(x, y)
        except Exception as e:
            log(f"处理选中文本时出错: {traceback.format_exc()}")

    def _copy_selected_text(self):
        try: old_clip = pyperclip.paste()
        except: old_clip = ""
            
        for attempt in range(2):
            if platform.system() == "Windows":
                self._win32_ctrl_c()
            else:
                self._cross_platform_ctrl_c()
            
            time.sleep(0.1) # 等待剪贴板写入
            try: new_clip = pyperclip.paste()
            except: continue
                
            if isinstance(new_clip, str) and new_clip != old_clip and is_valid_text(new_clip):
                return new_clip.strip()
            if attempt == 0: time.sleep(0.05)
        return ""

    def _win32_ctrl_c(self):
        VK_CONTROL, VK_C = 0x11, 0x43
        KEYEVENTF_KEYUP = 0x0002
        # 精准模拟组合键
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_C, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        
        # 强制全套释放所有可能滞粘的控制修饰键，确保绝对不卡死键盘
        ctypes.windll.user32.keybd_event(0xA2, 0, KEYEVENTF_KEYUP, 0) # 左Ctrl
        ctypes.windll.user32.keybd_event(0xA3, 0, KEYEVENTF_KEYUP, 0) # 右Ctrl

    def _cross_platform_ctrl_c(self):
        from pynput.keyboard import Controller, Key
        kb = Controller()
        kb.press(Key.ctrl)
        kb.press('c')
        kb.release('c')
        kb.release(Key.ctrl)

    # ---------- 语境清洗管线（大幅提升准确度）----------
    def _clean_text_for_translation(self, text):
        """智能清洗网页/PDF中断行，还原真实流畅的语境"""
        if self.contains_chinese(text):
            # 中文文本：直接抹除多余的换行符和中间空格
            text = re.sub(r'\s*\n\s*', '', text)
        else:
            # 英文文本：修复 PDF 常见的跨行连字符 (如 text- \n book -> textbook)
            text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
            # 将孤立的单行换行符变为空格，让段落重新拼回完整的长句子
            text = re.sub(r'\s*\n\s*', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()

    def handle_selection(self, x, y):
        raw_text = self._copy_selected_text()
        if not raw_text: return
        
        # 预处理清洗文本
        text = self._clean_text_for_translation(raw_text)
        if text == self.last_text or not text: return
        
        self.last_text = text
        log(f"选中文本: {text}")
        self.translate_and_show(x, y, text)

    def contains_chinese(self, text: str) -> bool:
        # 该正则完美覆盖简体与繁体字库
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    def translate_and_show(self, x, y, text):
        try:
            cache_key = f"{self.target_lang}_{text.strip()}"
            if cache_key in self.translation_cache:
                translated = self.translation_cache[cache_key]
            else:
                if not self.contains_chinese(text) and ' ' not in text and len(text) < 50:
                    clean_word = text.lower().strip('.,!?;:\'"')
                    local_result = self.local_dict.get(clean_word)
                    if local_result: translated = local_result
                    else: translated = self._online_translate(text)
                else:
                    translated = self._online_translate(text)

            if translated:
                if len(self.translation_cache) >= CACHE_SIZE:
                    first_key = next(iter(self.translation_cache))
                    del self.translation_cache[first_key]
                self.translation_cache[cache_key] = translated
                self.root.after(0, self.show_popup, x, y, translated)
        except Exception as e:
            log(f"翻译处理异常: {traceback.format_exc()}")

    def _online_translate(self, text):
        try:
            # 如果原文包含中文（简/繁），则统一翻译为英文；否则翻译为用户指定的中文语种
            target = 'en' if self.contains_chinese(text) else self.target_lang
            result = GoogleTranslator(source='auto', target=target).translate(text)
            return result
        except Exception as e:
            log(f"在线翻译失败: {traceback.format_exc()}")
            return None

    # ---------- 现代感 UI & 大容量自适应渲染 ----------
    def show_popup(self, x, y, text):
        self.destroy_popup()
        
        self.popup = tk.Toplevel(self.root)
        self.popup.overrideredirect(True)
        self.popup.attributes('-topmost', True)
        self.popup.attributes('-alpha', ALPHA)
        
        # 外层柔和边框 Frame
        border_frame = tk.Frame(self.popup, bg=BORDER_COLOR, bd=0)
        border_frame.pack(fill=tk.BOTH, expand=True)
        
        inner_frame = tk.Frame(border_frame, bg=BG_COLOR, bd=0)
        inner_frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # --- 黄金比例自适应算法 ---
        lines = text.split('\n')
        max_line_len = max(len(line) for line in lines) if lines else 0
        
        # 限制横向宽度：既不显得细长，在大篇幅时又能横向展开（最大视宽 75）
        display_width = max(42, min(max_line_len + 6, 75))
        
        # 估算自动折行后的实际行数
        total_lines = 0
        for line in lines:
            total_lines += max(1, (len(line) // (display_width - 4)) + 1)
        # 高度自适应：最高可开辟至 18 行，长段话瞬间一览无余
        display_height = max(2, min(total_lines, 18))

        font = (self.font_family, self.font_size, "normal")
        text_widget = tk.Text(inner_frame, 
                              font=font, 
                              bg=BG_COLOR, 
                              fg=FG_COLOR, 
                              padx=16, pady=12,      # 增大呼吸感留白
                              wrap=tk.WORD, 
                              width=display_width, 
                              height=display_height, 
                              spacing1=3,            # 段前距
                              spacing2=6,            # 行间距（极其重要，大气的关键）
                              borderwidth=0, 
                              highlightthickness=0, 
                              relief='flat')
        
        text_widget.insert(tk.END, text)
        text_widget.configure(state=tk.DISABLED)
        text_widget.pack(fill=tk.BOTH, expand=True)
        
        self.popup.update_idletasks()
        win_w = self.popup.winfo_width()
        win_h = self.popup.winfo_height()
        
        pos_x, pos_y = x + 15, y + 22 
        screen_w = self.popup.winfo_screenwidth()
        screen_h = self.popup.winfo_screenheight()
        
        if pos_x + win_w > screen_w: pos_x = screen_w - win_w - 8
        if pos_y + win_h > screen_h: pos_y = y - win_h - 15
        
        self.popup.geometry(f"+{pos_x}+{pos_y}")

        # 悬停感知事件
        def on_enter(event):
            if self.after_id:
                self.popup.after_cancel(self.after_id)
                self.after_id = None
                
        def on_leave(event):
            if self.after_id: self.popup.after_cancel(self.after_id)
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

    # ---------- 多级右键托盘控制菜单 ----------
    def _create_image(self):
        width, height = 16, 16
        image = Image.new('RGB', (width, height), color='#1E293B')
        draw = ImageDraw.Draw(image)
        draw.text((3, 1), "T", fill="#F8FAFC")
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
                    pystray.MenuItem("大号 (16px)", lambda: set_size(16), checked=lambda item: self.font_size == 16),
                    pystray.MenuItem("超大 (18px)", lambda: set_size(18), checked=lambda item: self.font_size == 18)
                )),
                pystray.MenuItem("界面字体", pystray.Menu(
                    pystray.MenuItem("微软雅黑", lambda: set_font("Microsoft YaHei UI"), checked=lambda item: self.font_family == "Microsoft YaHei UI"),
                    pystray.MenuItem("宋体", lambda: set_font("SimSun"), checked=lambda item: self.font_family == "SimSun"),
                    pystray.MenuItem("Segoe UI (英文推荐)", lambda: set_font("Segoe UI"), checked=lambda item: self.font_family == "Segoe UI")
                )),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出程序", self.quit_app)
            )
            self.tray_icon = pystray.Icon("HoverTranslator", self._create_image(), "优雅划词翻译", menu)
            self.tray_icon.run()
        except Exception as e:
            log(f"托盘启动失败: {traceback.format_exc()}")

    def quit_app(self, icon=None, item=None):
        log("用户退出程序")
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
        msgbox.showerror("启动失败", f"程序异常，请查看 translator.txt\n{str(e)}")
