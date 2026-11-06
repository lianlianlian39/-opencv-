import ctypes
import json
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
import numpy as np
import win32api
import win32con
import win32gui
import win32ui

APP_DIR = (os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
           else os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(APP_DIR, 'window_image_clicker.json')


def capture_client(hwnd):
    """Capture a window's client area using PrintWindow; some GPU surfaces may be blank."""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None
    window_dc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(window_dc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, width, height)
    mem.SelectObject(bmp)
    ok = ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2)
    if not ok:
        ok = ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 0)
    result = None
    if ok:
        info = bmp.GetInfo()
        raw = bmp.GetBitmapBits(True)
        img = np.frombuffer(raw, dtype=np.uint8).reshape((info['bmHeight'], info['bmWidth'], 4))
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        client_origin = win32gui.ClientToScreen(hwnd, (0, 0))
        x, y = client_origin[0] - left, client_origin[1] - top
        cw, ch = win32gui.GetClientRect(hwnd)[2:]
        result = img[y:y + ch, x:x + cw].copy()
    win32gui.DeleteObject(bmp.GetHandle())
    mem.DeleteDC()
    src.DeleteDC()
    win32gui.ReleaseDC(hwnd, window_dc)
    return result


def click_background(hwnd, x, y):
    packed = win32api.MAKELONG(int(x), int(y))
    win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, packed)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, packed)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, packed)


class App:
    def __init__(self, root):
        self.root = root
        root.title('窗口图像识别点击器')
        root.geometry('900x680')
        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.templates = []
        self.available_windows = []
        self.bound_windows = []
        self.saved_windows = {}
        self.last_click = {}
        self.interval = tk.IntVar(value=500)
        self.threshold = tk.DoubleVar(value=0.88)
        self.click_interval = tk.IntVar(value=1000)
        self.click_interval_text = tk.StringVar(value='1000 毫秒')
        self.random_offset = tk.IntVar(value=0)
        self.delay_min = tk.IntVar(value=0)
        self.delay_max = tk.IntVar(value=0)
        self._build()
        self._load_config()
        self.refresh_windows()
        root.after(150, self._drain_logs)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def _build(self):
        panes = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        left = ttk.Frame(panes, padding=6)
        right = ttk.Frame(panes, padding=6)
        panes.add(left, weight=1)
        panes.add(right, weight=1)
        ttk.Label(left, text='检测到的窗口：按住 Ctrl / Shift 多选').pack(anchor='w')
        available_frame = ttk.Frame(left)
        available_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 6))
        self.window_list = tk.Listbox(available_frame, selectmode=tk.EXTENDED, exportselection=False, height=12)
        available_scroll = ttk.Scrollbar(available_frame, orient=tk.VERTICAL, command=self.window_list.yview)
        self.window_list.configure(yscrollcommand=available_scroll.set)
        self.window_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        available_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        window_buttons = ttk.Frame(left)
        window_buttons.pack(fill=tk.X)
        ttk.Button(window_buttons, text='刷新窗口', command=self.refresh_windows).pack(side=tk.LEFT)
        ttk.Button(window_buttons, text='绑定所选', command=self.bind_selected).pack(side=tk.LEFT, padx=5)
        ttk.Label(left, text='已绑定窗口：').pack(anchor='w', pady=(12, 0))
        bound_frame = ttk.Frame(left)
        bound_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 6))
        self.bound_list = tk.Listbox(bound_frame, selectmode=tk.EXTENDED, exportselection=False, height=8)
        bound_scroll = ttk.Scrollbar(bound_frame, orient=tk.VERTICAL, command=self.bound_list.yview)
        self.bound_list.configure(yscrollcommand=bound_scroll.set)
        self.bound_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bound_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Button(left, text='解绑所选', command=self.unbind_selected).pack(anchor='w')

        ttk.Label(right, text='图片模板').pack(anchor='w')
        self.template_list = tk.Listbox(right, height=12, selectmode=tk.EXTENDED)
        self.template_list.pack(fill=tk.BOTH, expand=True, pady=6)
        row = ttk.Frame(right)
        row.pack(fill=tk.X)
        ttk.Button(row, text='添加图片', command=self.add_images).pack(side=tk.LEFT)
        ttk.Button(row, text='移除选中', command=self.remove_templates).pack(side=tk.LEFT, padx=5)
        threshold_row = ttk.Frame(right)
        threshold_row.pack(fill=tk.X, pady=(12, 0))
        ttk.Label(threshold_row, text='匹配阈值 (0-1)').pack(side=tk.LEFT)
        self.threshold_text = tk.StringVar(value=f'{self.threshold.get():.2f}')
        ttk.Label(threshold_row, textvariable=self.threshold_text, width=5, anchor='e').pack(side=tk.RIGHT)
        self.threshold.trace_add('write', self._update_threshold_text)
        ttk.Scale(right, from_=0.60, to=0.99, variable=self.threshold, orient=tk.HORIZONTAL).pack(fill=tk.X)
        ttk.Label(right, text='轮询间隔（毫秒）').pack(anchor='w', pady=(8, 0))
        ttk.Spinbox(right, from_=100, to=10000, increment=100, textvariable=self.interval, width=10).pack(anchor='w')
        speed_row = ttk.Frame(right)
        speed_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(speed_row, text='点击速度 / 重复间隔').pack(side=tk.LEFT)
        ttk.Label(speed_row, textvariable=self.click_interval_text, width=12, anchor='e').pack(side=tk.RIGHT)
        ttk.Scale(right, from_=100, to=5000, variable=self.click_interval, orient=tk.HORIZONTAL,
                  command=self._update_click_interval).pack(fill=tk.X)
        random_row = ttk.Frame(right)
        random_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(random_row, text='随机偏移范围（像素，±）').pack(side=tk.LEFT)
        ttk.Spinbox(random_row, from_=0, to=300, increment=1, textvariable=self.random_offset, width=8).pack(side=tk.LEFT, padx=6)
        delay_row = ttk.Frame(right)
        delay_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(delay_row, text='点击前随机延迟（毫秒）').pack(side=tk.LEFT)
        ttk.Spinbox(delay_row, from_=0, to=10000, increment=50, textvariable=self.delay_min, width=8).pack(side=tk.LEFT, padx=(6, 3))
        ttk.Label(delay_row, text='至').pack(side=tk.LEFT)
        ttk.Spinbox(delay_row, from_=0, to=10000, increment=50, textvariable=self.delay_max, width=8).pack(side=tk.LEFT, padx=3)
        controls = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        controls.pack(fill=tk.X)
        self.start_button = ttk.Button(controls, text='开始', command=self.start)
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(controls, text='停止', command=self.stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=6)
        ttk.Button(controls, text='保存配置', command=self.save_config).pack(side=tk.LEFT)
        ttk.Label(self.root, text='运行日志').pack(anchor='w', padx=10)
        self.log = tk.Text(self.root, height=7, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=False, padx=10, pady=(0, 10))

    def _update_threshold_text(self, *_):
        self.threshold_text.set(f'{self.threshold.get():.2f}')

    def _update_click_interval(self, value):
        milliseconds = max(100, min(5000, int(round(float(value) / 100) * 100)))
        self.click_interval.set(milliseconds)
        self.click_interval_text.set(f'{milliseconds} 毫秒')

    def refresh_windows(self):
        previous_bound = {hwnd for hwnd, _title in self.bound_windows}
        previous_bound.update(hwnd for hwnd, enabled in self.saved_windows.items() if enabled)
        self.available_windows = []
        self.window_list.delete(0, tk.END)
        for hwnd, title in self.bound_windows:
            if win32gui.IsWindow(hwnd) and hwnd not in previous_bound:
                previous_bound.add(hwnd)
        def visit(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd) or win32gui.GetParent(hwnd):
                return
            title = win32gui.GetWindowText(hwnd).strip()
            if not title or '明日之后' not in title:
                return
            self.available_windows.append((hwnd, title))
        win32gui.EnumWindows(visit, None)
        available_ids = {hwnd for hwnd, _title in self.available_windows}
        self.bound_windows = [(hwnd, title) for hwnd, title in self.bound_windows if hwnd in available_ids]
        for hwnd, title in self.available_windows:
            self.window_list.insert(tk.END, f'{title} | HWND {hwnd:#x}')
            if hwnd in previous_bound and all(bound_hwnd != hwnd for bound_hwnd, _ in self.bound_windows):
                self.bound_windows.append((hwnd, title))
        self._refresh_bound_list()

    def _refresh_bound_list(self):
        self.bound_list.delete(0, tk.END)
        for hwnd, title in self.bound_windows:
            self.bound_list.insert(tk.END, f'{title} | HWND {hwnd:#x}')

    def bind_selected(self):
        for index in self.window_list.curselection():
            item = self.available_windows[index]
            if all(hwnd != item[0] for hwnd, _title in self.bound_windows):
                self.bound_windows.append(item)
        self._refresh_bound_list()

    def unbind_selected(self):
        selected = set(self.bound_list.curselection())
        self.bound_windows = [item for index, item in enumerate(self.bound_windows) if index not in selected]
        self._refresh_bound_list()

    def add_images(self):
        paths = filedialog.askopenfilenames(title='选择要识别的图片', filetypes=[('图片', '*.png *.jpg *.jpeg *.bmp'), ('所有文件', '*.*')])
        for path in paths:
            if not any(t['path'] == path for t in self.templates):
                self.templates.append({'path': path})
                self.template_list.insert(tk.END, os.path.basename(path))

    def remove_templates(self):
        for idx in reversed(self.template_list.curselection()):
            self.template_list.delete(idx)
            del self.templates[idx]

    def selected_windows(self):
        return [(hwnd, title) for hwnd, title in self.bound_windows if win32gui.IsWindow(hwnd)]

    def start(self):
        if not self.selected_windows():
            messagebox.showinfo('提示', '请先刷新并勾选至少一个窗口。')
            return
        if not self.templates:
            messagebox.showinfo('提示', '请先添加至少一张图片模板。')
            return
        try:
            offset = int(self.random_offset.get())
            delay_min = int(self.delay_min.get())
            delay_max = int(self.delay_max.get())
            if offset < 0 or delay_min < 0 or delay_max < delay_min:
                raise ValueError('随机偏移不能为负数，且延迟最大值必须大于或等于最小值。')
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror('参数有误', str(exc))
            return
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._scan_loop, daemon=True)
        self.worker.start()
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self._log('开始轮询。')

    def stop(self):
        self.stop_event.set()
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self._log('已停止。')

    def _scan_loop(self):
        cache = {}
        while not self.stop_event.is_set():
            started = time.monotonic()
            for hwnd, title in self.selected_windows():
                if self.stop_event.is_set():
                    break
                try:
                    frame = capture_client(hwnd)
                    if frame is None or frame.size == 0:
                        continue
                    fh, fw = frame.shape[:2]
                    for item in list(self.templates):
                        path = item['path']
                        if path not in cache:
                            cache[path] = cv2.imread(path, cv2.IMREAD_COLOR)
                        templ = cache[path]
                        if templ is None:
                            continue
                        th, tw = templ.shape[:2]
                        if tw > fw or th > fh:
                            continue
                        scores = cv2.matchTemplate(frame, templ, cv2.TM_CCOEFF_NORMED)
                        _, score, _, loc = cv2.minMaxLoc(scores)
                        key = (hwnd, path)
                        now = time.monotonic()
                        if score >= self.threshold.get() and now - self.last_click.get(key, 0) >= self.click_interval.get() / 1000.0:
                            radius = max(0, int(self.random_offset.get()))
                            offset_x = random.randint(-radius, radius) if radius else 0
                            offset_y = random.randint(-radius, radius) if radius else 0
                            client_h, client_w = frame.shape[:2]
                            click_x = max(0, min(client_w - 1, loc[0] + tw // 2 + offset_x))
                            click_y = max(0, min(client_h - 1, loc[1] + th // 2 + offset_y))
                            min_delay = max(0, int(self.delay_min.get()))
                            max_delay = max(min_delay, int(self.delay_max.get()))
                            delay_ms = random.randint(min_delay, max_delay)
                            if self.stop_event.wait(delay_ms / 1000.0):
                                break
                            click_background(hwnd, click_x, click_y)
                            self.last_click[key] = time.monotonic()
                            self.log_queue.put(f'[{title}] 匹配 {os.path.basename(path)}，相似度 {score:.3f}，偏移({offset_x},{offset_y})，延迟 {delay_ms} 毫秒，已发送后台点击。')
                except Exception as exc:
                    self.log_queue.put(f'[{title}] 处理失败：{exc}')
            delay = max(0.05, self.interval.get() / 1000 - (time.monotonic() - started))
            self.stop_event.wait(delay)

    def _log(self, text):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, time.strftime('%H:%M:%S ') + text + '\n')
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _drain_logs(self):
        while not self.log_queue.empty():
            self._log(self.log_queue.get())
        self.root.after(150, self._drain_logs)

    def save_config(self):
        data = {'templates': self.templates, 'windows': {str(hwnd): True for hwnd, _title in self.bound_windows}, 'interval_ms': self.interval.get(), 'threshold': self.threshold.get(), 'click_interval_ms': self.click_interval.get(), 'random_offset_px': self.random_offset.get(), 'click_delay_min_ms': self.delay_min.get(), 'click_delay_max_ms': self.delay_max.get()}
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._log('配置已保存。')
        except Exception as exc:
            messagebox.showerror('保存失败', str(exc))

    def _load_config(self):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.templates = [t for t in data.get('templates', []) if os.path.isfile(t.get('path', ''))]
            for t in self.templates:
                self.template_list.insert(tk.END, os.path.basename(t['path']))
            self.interval.set(data.get('interval_ms', 500))
            self.threshold.set(data.get('threshold', 0.88))
            self.click_interval.set(data.get('click_interval_ms', 1000))
            self.click_interval_text.set(f'{self.click_interval.get()} 毫秒')
            self.random_offset.set(data.get('random_offset_px', 0))
            self.delay_min.set(data.get('click_delay_min_ms', 0))
            self.delay_max.set(data.get('click_delay_max_ms', 0))
            self.saved_windows = {int(k): v for k, v in data.get('windows', {}).items()}
        except (OSError, ValueError, TypeError):
            self.saved_windows = {}

    def close(self):
        self.stop_event.set()
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()