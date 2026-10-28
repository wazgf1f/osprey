"""Visual editor for click plans.

Run with:

    osprey gui
    osprey gui my-plan.json

The editor writes the same plan.json that "osprey play" understands, so a
plan can be built visually and then run from the command line or scheduled.
"""

from __future__ import annotations

import ctypes
import datetime
import logging
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

import numpy as np

from .capture.gdi import GdiGrabber
from .core.engine import Engine, EngineConfig
from .core.plan import Plan, Step
from .core.sequence import SequenceTask
from .errors import ConfigError
from .vision.io import save_image
from . import __version__
from .win32util import enable_dpi_awareness

logger = logging.getLogger("osprey.gui")

ACTION_LABELS = {"click": "点击", "move": "移动", "wait": "等待", "press": "按键"}
LABEL_ACTIONS = {value: key for key, value in ACTION_LABELS.items()}
MISSING_LABELS = {"stop": "找不到就停止", "skip": "找不到就跳过"}

FONT = "Microsoft YaHei UI"
MONO = "Consolas"
PALETTE = {
    "bg": "#F3F6FB",
    "card": "#FFFFFF",
    "ink": "#14213D",
    "muted": "#6B7A90",
    "accent": "#2563EB",
    "accent_dark": "#1D4ED8",
    "ok": "#16A34A",
    "run": "#2563EB",
    "err": "#DC2626",
    "header": "#0E1B33",
    "header_sub": "#9FB0CC",
}


def _window_geometry(screen_w: int, screen_h: int) -> tuple:
    """Choose a window that always fits, even on 800x600 or 1024x600 screens."""
    screen_w = max(320, int(screen_w))
    screen_h = max(240, int(screen_h))
    width = min(screen_w, max(720, min(1320, screen_w - 80)))
    height = min(screen_h, max(560, min(880, screen_h - 120)))
    return width, height


def _as_float(var: tk.StringVar, label: str) -> float:
    try:
        return float(var.get().strip())
    except ValueError as exc:
        raise ConfigError("%s 必须是数字" % label) from exc


def _as_int(var: tk.StringVar, label: str) -> int:
    try:
        return int(var.get().strip())
    except ValueError as exc:
        raise ConfigError("%s 必须是整数" % label) from exc


def _as_scales(var: tk.StringVar) -> List[float]:
    text = var.get().strip() or "1.0"
    try:
        values = [float(part) for part in text.replace("，", ",").split(",") if part.strip()]
    except ValueError as exc:
        raise ConfigError("缩放必须是逗号分隔的数字，例如 1.0,1.25,1.5") from exc
    if not values or any(value <= 0 for value in values):
        raise ConfigError("缩放必须是正数")
    return values


class _LogHandler(logging.Handler):
    def __init__(self, callback) -> None:
        super().__init__()
        self.callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.callback(record.levelname, self.format(record))
        except Exception:
            pass


class StepDialog(tk.Toplevel):
    """Modal editor for one plan step."""

    def __init__(self, master: tk.Misc, step: Step) -> None:
        super().__init__(master)
        self.title("编辑步骤")
        self.resizable(False, False)
        self.transient(master)
        self.value: Optional[Step] = None

        self.action = tk.StringVar(value=step.action)
        self.template = tk.StringVar(value=step.template)
        self.key = tk.StringVar(value=step.key)
        self.seconds = tk.StringVar(value=("%.2f" % step.seconds) if step.seconds else "1.00")
        self.wait = tk.StringVar(value=("%.2f" % step.wait) if step.wait else "0.00")
        self.timeout = tk.StringVar(value="" if step.timeout is None else "%.2f" % step.timeout)
        self.threshold = tk.StringVar(value="" if step.threshold is None else "%.2f" % step.threshold)
        self.missing = tk.StringVar(
            value="" if step.on_missing is None else MISSING_LABELS.get(step.on_missing, "使用计划默认")
        )

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="动作").grid(row=0, column=0, sticky="w", pady=4)
        combo = ttk.Combobox(frame, values=list(ACTION_LABELS.values()), state="readonly",
                             textvariable=self._action_label())
        combo.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)
        combo.bind("<<ComboboxSelected>>", lambda _event: self._sync())

        ttk.Label(frame, text="模板").grid(row=1, column=0, sticky="w", pady=4)
        self.template_entry = ttk.Entry(frame, textvariable=self.template, width=42)
        self.template_entry.grid(row=1, column=1, sticky="ew", pady=4)
        self.browse_button = ttk.Button(frame, text="浏览…", command=self._browse)
        self.browse_button.grid(row=1, column=2, padx=(6, 0), pady=4)

        ttk.Label(frame, text="按键").grid(row=2, column=0, sticky="w", pady=4)
        self.key_entry = ttk.Entry(frame, textvariable=self.key, width=18)
        self.key_entry.grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="等待秒数").grid(row=3, column=0, sticky="w", pady=4)
        self.seconds_entry = ttk.Entry(frame, textvariable=self.seconds, width=10)
        self.seconds_entry.grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="动作后等待").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.wait, width=10).grid(row=4, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="超时（秒）").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.timeout, width=10).grid(row=5, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="阈值").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.threshold, width=10).grid(row=6, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="找不到时").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Combobox(frame, values=["使用计划默认", "找不到就停止", "找不到就跳过"],
                     state="readonly", textvariable=self.missing, width=16).grid(
            row=7, column=1, sticky="w", pady=4)

        buttons = ttk.Frame(frame)
        buttons.grid(row=8, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="取消", command=self._cancel).pack(side="right")
        ttk.Button(buttons, text="确定", command=self._ok).pack(side="right", padx=(0, 6))

        frame.columnconfigure(1, weight=1)
        self._sync()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        self.wait_visibility()
        self.grab_set()
        self.focus_force()

    def _action_label(self) -> tk.StringVar:
        # Combobox shows Chinese labels; keep a separate var for display.
        if not hasattr(self, "_label_var"):
            self._label_var = tk.StringVar(value=ACTION_LABELS.get(self.action.get(), "点击"))
        return self._label_var

    def _selected_action(self) -> str:
        return LABEL_ACTIONS.get(self._label_var.get(), "click")

    def _sync(self) -> None:
        action = self._selected_action()
        state = "normal" if action in ("click", "move") else "disabled"
        self.template_entry.configure(state=state)
        self.browse_button.configure(state=state)
        self.key_entry.configure(state="normal" if action == "press" else "disabled")
        self.seconds_entry.configure(state="normal" if action == "wait" else "disabled")

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="选择模板图片",
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")],
        )
        if path:
            self.template.set(path)

    def _ok(self) -> None:
        action = self._selected_action()
        try:
            step = Step(
                action=action,
                template=self.template.get().strip(),
                key=self.key.get().strip(),
                seconds=_as_float(self.seconds, "等待秒数") if action == "wait" else 0.0,
                wait=_as_float(self.wait, "动作后等待"),
                threshold=_as_float(self.threshold, "阈值") if self.threshold.get().strip() else None,
                timeout=_as_float(self.timeout, "超时") if self.timeout.get().strip() else None,
                on_missing={"找不到就停止": "stop", "找不到就跳过": "skip"}.get(self.missing.get()),
            )
            step.validate(0)
        except ConfigError as exc:
            messagebox.showerror("步骤有误", str(exc), parent=self)
            return
        self.value = step
        self.destroy()

    def _cancel(self) -> None:
        self.value = None
        self.destroy()


class PlanEditor:
    def __init__(self, plan_path: Optional[str] = None) -> None:
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("Osprey 计划编辑器")
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width, height = _window_geometry(screen_w, screen_h)
        self.root.geometry("%dx%d+%d+%d" % (
            width, height,
            max(0, (screen_w - width) // 2),
            max(0, (screen_h - height) // 3),
        ))
        self.root.minsize(min(1080, width), min(760, height))
        self.root.configure(bg=PALETTE["bg"])
        self._apply_theme()

        self.plan_path: Optional[str] = None
        self.base_dir = os.getcwd()
        self.steps: List[Step] = []
        self._safety = None
        self._input = None
        self._running = False
        self._stop_requested = False
        self._closing = False
        self._log_handler: Optional[_LogHandler] = None

        self._build()
        self._install_logging()

        if plan_path:
            self._open_path(plan_path)
        else:
            self._load_plan(Plan())

    # -- layout ------------------------------------------------------------
    def _apply_theme(self) -> None:
        style = ttk.Style(self.root)
        for theme in ("vista", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure(".", font=(FONT, 10), background=PALETTE["bg"], foreground=PALETTE["ink"])
        style.configure("TButton", padding=(9, 5))
        style.configure("Tool.TButton", padding=(10, 6))
        style.configure("TLabelframe", background=PALETTE["bg"], borderwidth=0)
        style.configure("TLabelframe.Label", background=PALETTE["bg"],
                        foreground=PALETTE["muted"], font=(FONT, 10, "bold"))
        style.configure("Steps.Treeview", rowheight=30, font=(FONT, 10),
                        background=PALETTE["card"], fieldbackground=PALETTE["card"], borderwidth=0)
        style.configure("Treeview.Heading", font=(FONT, 10, "bold"),
                        foreground=PALETTE["muted"], background=PALETTE["bg"])
        style.map("Steps.Treeview",
                  background=[("selected", "#DBEAFE")],
                  foreground=[("selected", PALETTE["ink"])])
        style.configure("TEntry", padding=3)
        style.configure("TCombobox", padding=3)

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=3)
        self.root.rowconfigure(5, weight=1)

        header = tk.Canvas(self.root, bg=PALETTE["header"], height=86,
                           highlightthickness=0, bd=0)
        header.grid(row=0, column=0, sticky="ew")
        header.create_text(20, 10, text="Osprey", anchor="nw", fill="#FFFFFF",
                           font=(FONT, 18, "bold"))
        header.create_text(22, 55, text="屏幕视觉自动化 · 点击顺序与间隔",
                           anchor="nw", fill=PALETTE["header_sub"], font=(FONT, 9))
        version_id = header.create_text(18, 18, text="v" + __version__,
                                        anchor="ne", fill=PALETTE["header_sub"],
                                        font=(FONT, 9))
        header.bind("<Configure>",
                    lambda event: header.coords(version_id, event.width - 18, 18))

        toolbar = ttk.Frame(self.root, padding=(12, 10, 12, 2))
        toolbar.grid(row=1, column=0, sticky="ew")

        primary_row = ttk.Frame(toolbar)
        primary_row.pack(fill="x")
        self._edit_buttons = []
        self.capture_button = tk.Button(
            primary_row, text="＋  框选模板并添加点击", command=self._capture_step,
            bg=PALETTE["accent"], fg="white", activebackground=PALETTE["accent_dark"],
            activeforeground="white", relief="flat", bd=0, padx=14, pady=7,
            cursor="hand2", font=(FONT, 10, "bold"),
        )
        self.capture_button.pack(side="left")
        self._edit_buttons.append(self.capture_button)
        for label, command in (
            ("添加点击", self._add_click),
            ("添加等待", self._add_wait),
            ("添加按键", self._add_press),
        ):
            button = ttk.Button(primary_row, text=label, command=command,
                                style="Tool.TButton")
            button.pack(side="left", padx=(6, 0))
            self._edit_buttons.append(button)

        secondary_row = ttk.Frame(toolbar)
        secondary_row.pack(fill="x", pady=(6, 0))
        ttk.Label(secondary_row, text="调整步骤", foreground=PALETTE["muted"]).pack(
            side="left", padx=(2, 8))
        for label, command in (
            ("上移", lambda: self._move(-1)),
            ("下移", lambda: self._move(1)),
            ("编辑", self._edit_selected),
            ("删除", self._delete_selected),
        ):
            button = ttk.Button(secondary_row, text=label, command=command,
                                style="Tool.TButton")
            button.pack(side="left", padx=(0, 4))
            self._edit_buttons.append(button)

        settings = ttk.LabelFrame(self.root, text="计划设置", padding=10)
        settings.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 0))

        self.name_var = tk.StringVar(value="plan")
        self.threshold_var = tk.StringVar(value="0.86")
        self.timeout_var = tk.StringVar(value="8")
        self.fps_var = tk.StringVar(value="6")
        self.loop_var = tk.StringVar(value="1")
        self.scales_var = tk.StringVar(value="1.0")
        self.missing_var = tk.StringVar(value="找不到就停止")

        rows = (
            (("名称", self.name_var, 16), ("阈值", self.threshold_var, 6),
             ("超时(秒)", self.timeout_var, 6), ("帧率", self.fps_var, 5)),
            (("循环(0=无限)", self.loop_var, 5), ("缩放", self.scales_var, 12)),
        )
        for row_index, fields in enumerate(rows):
            column = 0
            for label, variable, width in fields:
                ttk.Label(settings, text=label).grid(
                    row=row_index, column=column, sticky="w", padx=(0, 4), pady=3)
                ttk.Entry(settings, textvariable=variable, width=width).grid(
                    row=row_index, column=column + 1, sticky="w", padx=(0, 18), pady=3)
                column += 2
        ttk.Label(settings, text="找不到时").grid(
            row=1, column=4, sticky="w", padx=(0, 4), pady=3)
        ttk.Combobox(settings, values=list(MISSING_LABELS.values()), state="readonly",
                     textvariable=self.missing_var, width=14).grid(
                         row=1, column=5, sticky="w", pady=3)

        steps_frame = ttk.LabelFrame(self.root, text="步骤", padding=8)
        steps_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=(8, 6))
        steps_frame.columnconfigure(0, weight=1)
        steps_frame.rowconfigure(0, weight=1)

        columns = ("no", "action", "target", "wait", "timeout")
        self.tree = ttk.Treeview(steps_frame, columns=columns, show="headings",
                                 selectmode="browse", style="Steps.Treeview")
        headings = {"no": "#", "action": "动作", "target": "目标 / 按键",
                    "wait": "之后等待", "timeout": "超时"}
        widths = {"no": 46, "action": 90, "target": 430, "wait": 100, "timeout": 100}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column],
                             anchor="w" if column != "no" else "center")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(steps_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-1>", lambda _event: self._edit_selected())
        self.tree.bind("<Delete>", lambda _event: self._delete_selected())
        self.tree.tag_configure("odd", background="#F7F9FC")
        self.tree.tag_configure("even", background=PALETTE["card"])

        self.empty_hint = tk.Label(
            steps_frame,
            text="还没有步骤\n点左上角「框选模板并添加点击」开始",
            bg=PALETTE["card"], fg=PALETTE["muted"], font=(FONT, 10), justify="center",
        )
        self.empty_hint.place(relx=0.5, rely=0.55, anchor="center")
        self.empty_hint.lift()

        actions = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        actions.grid(row=4, column=0, sticky="ew")
        for label, command, pad in (
            ("打开计划", self._open_dialog, 0),
            ("保存", self._save, 6),
            ("另存为", lambda: self._save(True), 6),
        ):
            button = ttk.Button(actions, text=label, command=command,
                                style="Tool.TButton")
            button.pack(side="left", padx=(pad, 0))
            self._edit_buttons.append(button)
        self.stop_button = ttk.Button(actions, text="■  停止", command=self._stop,
                                      state="disabled", style="Tool.TButton")
        self.stop_button.pack(side="right")
        self.live_button = tk.Button(
            actions, text="▶  真实运行", command=lambda: self._run(True),
            bg=PALETTE["accent"], fg="white", activebackground=PALETTE["accent_dark"],
            activeforeground="white", relief="flat", bd=0, padx=14, pady=6,
            cursor="hand2", font=(FONT, 10, "bold"),
        )
        self.live_button.pack(side="right", padx=(0, 8))
        self.dry_button = ttk.Button(actions, text="▷  试运行",
                                     command=lambda: self._run(False), style="Tool.TButton")
        self.dry_button.pack(side="right", padx=(0, 8))

        log_frame = ttk.LabelFrame(self.root, text="日志", padding=6)
        log_frame.grid(row=5, column=0, sticky="nsew", padx=12, pady=(0, 6))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame, height=6, wrap="word", state="disabled",
            bg="#0B1220", fg="#CBD5E1", insertbackground="#CBD5E1",
            relief="flat", bd=0, padx=8, pady=6, font=(MONO, 9),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.tag_configure("WARNING", foreground="#FBBF24")
        self.log_text.tag_configure("ERROR", foreground="#F87171")
        self.log_text.tag_configure("DEBUG", foreground="#64748B")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "就绪 · 运行日志会显示在这里\n", "DEBUG")
        self.log_text.configure(state="disabled")
        self._log_empty = True

        self.status_var = tk.StringVar(value="就绪")
        statusbar = tk.Frame(self.root, bg=PALETTE["card"], height=30)
        statusbar.grid(row=6, column=0, sticky="ew")
        statusbar.grid_propagate(False)
        self.status_dot = tk.Label(statusbar, text="●", bg=PALETTE["card"],
                                   fg=PALETTE["ok"], font=(FONT, 10))
        self.status_dot.pack(side="left", padx=(12, 4))
        tk.Label(statusbar, textvariable=self.status_var, bg=PALETTE["card"],
                 fg=PALETTE["muted"], font=(FONT, 9)).pack(side="left")
        tk.Label(statusbar, text="F12 急停   Ctrl+S 保存",
                 bg=PALETTE["card"], fg="#9AA8BD", font=(FONT, 8)).pack(side="right", padx=12)

        self.root.bind("<Control-s>", lambda _event: self._save())
        self.root.bind("<Control-o>", lambda _event: self._open_dialog())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _install_logging(self) -> None:
        handler = _LogHandler(
            lambda level, message: self.root.after(0, self._append_log, level, message)
        )
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        logging.getLogger("osprey").addHandler(handler)
        logging.getLogger("osprey").setLevel(logging.INFO)
        self._log_handler = handler

    def _append_log(self, level: str, message: str) -> None:
        if self._closing:
            return
        try:
            if not self.log_text.winfo_exists():
                return
        except tk.TclError:
            return
        self.log_text.configure(state="normal")
        if getattr(self, "_log_empty", False):
            self.log_text.delete("1.0", "end")
            self._log_empty = False
        tag = level if level in ("WARNING", "ERROR", "DEBUG") else None
        if tag:
            self.log_text.insert("end", message + "\n", tag)
        else:
            self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # -- plan state --------------------------------------------------------
    def _load_plan(self, plan: Plan, path: Optional[str] = None) -> None:
        self.plan_path = path
        self.base_dir = plan.base_dir
        self.steps = list(plan.steps)
        self.name_var.set(plan.name)
        self.threshold_var.set("%.2f" % plan.threshold)
        self.timeout_var.set("%.2f" % plan.timeout)
        self.fps_var.set("%.2f" % plan.fps)
        self.loop_var.set(str(plan.loop))
        self.scales_var.set(", ".join("%.2f" % value for value in plan.scales))
        self.missing_var.set(MISSING_LABELS.get(plan.on_missing, "找不到就停止"))
        self._refresh()
        if path:
            self._set_status("已加载 %s" % path)
        else:
            self._set_status("新计划：点左上角「框选模板并添加点击」开始")

    def _collect(self) -> Plan:
        plan = Plan(
            name=self.name_var.get().strip() or "plan",
            steps=list(self.steps),
            threshold=_as_float(self.threshold_var, "阈值"),
            timeout=_as_float(self.timeout_var, "超时"),
            fps=_as_float(self.fps_var, "帧率"),
            loop=_as_int(self.loop_var, "循环"),
            on_missing={"找不到就停止": "stop", "找不到就跳过": "skip"}.get(
                self.missing_var.get(), "stop"),
            scales=_as_scales(self.scales_var),
            base_dir=self.base_dir,
        )
        return plan.validate()

    def _refresh(self, select: Optional[int] = None) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, step in enumerate(self.steps):
            self.tree.insert(
                "", "end", iid=str(index),
                values=(index + 1, ACTION_LABELS.get(step.action, step.action),
                        step.describe_target(),
                        ("%.2f" % step.wait) if step.wait else "",
                        ("%.2f" % step.timeout) if step.timeout is not None else ""),
                tags=("odd" if index % 2 else "even",),
            )
        if self.steps:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.55, anchor="center")
            self.empty_hint.lift()
        if select is not None and 0 <= select < len(self.steps):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))

    def _selected(self) -> Optional[int]:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    # -- editing -----------------------------------------------------------
    def _add_click(self) -> None:
        if self._running:
            return
        path = filedialog.askopenfilename(
            title="选择模板图片",
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.steps.append(Step("click", template=os.path.abspath(path), wait=1.0))
        self._refresh(select=len(self.steps) - 1)

    def _add_wait(self) -> None:
        if self._running:
            return
        self.steps.append(Step("wait", seconds=1.0))
        self._refresh(select=len(self.steps) - 1)

    def _add_press(self) -> None:
        if self._running:
            return
        self.steps.append(Step("press", key="enter", wait=0.5))
        self._refresh(select=len(self.steps) - 1)

    def _edit_selected(self) -> None:
        if self._running:
            return
        index = self._selected()
        if index is None:
            return
        dialog = StepDialog(self.root, self.steps[index])
        self.root.wait_window(dialog)
        if dialog.value is not None:
            self.steps[index] = dialog.value
            self._refresh(select=index)

    def _delete_selected(self) -> None:
        if self._running:
            return
        index = self._selected()
        if index is None:
            return
        del self.steps[index]
        self._refresh(select=min(index, len(self.steps) - 1) if self.steps else None)

    def _move(self, delta: int) -> None:
        if self._running:
            return
        index = self._selected()
        if index is None:
            return
        target = index + delta
        if not 0 <= target < len(self.steps):
            return
        self.steps[index], self.steps[target] = self.steps[target], self.steps[index]
        self._refresh(select=target)

    # -- capture -----------------------------------------------------------
    def _capture_step(self) -> None:
        if self._running:
            return
        path = self._capture_template()
        if not path:
            return
        self.steps.append(Step("click", template=path, wait=1.0))
        self._refresh(select=len(self.steps) - 1)

    def _capture_template(self) -> Optional[str]:
        self.root.withdraw()
        self.root.update_idletasks()
        time.sleep(0.2)
        grabber = None
        try:
            # Capture every monitor so templates on a secondary screen work.
            grabber = GdiGrabber(full_desktop=True)
            frame = grabber.grab()
        except Exception as exc:
            self.root.deiconify()
            messagebox.showerror("截屏失败", str(exc), parent=self.root)
            return None
        finally:
            if grabber is not None:
                grabber.close()

        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        self._place_capture_overlay(overlay, frame)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.30)
        overlay.configure(bg="black")
        canvas = tk.Canvas(overlay, bg="black", cursor="cross", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        state = {"x0": 0, "y0": 0, "rect": None, "done": False}

        def on_press(event):
            state["x0"], state["y0"] = event.x, event.y
            if state["rect"] is not None:
                canvas.delete(state["rect"])
            state["rect"] = canvas.create_rectangle(
                event.x, event.y, event.x, event.y, outline="#00e0ff", width=2)

        def on_drag(event):
            if state["rect"] is not None:
                canvas.coords(state["rect"], state["x0"], state["y0"], event.x, event.y)

        def on_release(event):
            x0, y0 = state["x0"], state["y0"]
            x1, y1 = event.x, event.y
            left, right = sorted((x0, x1))
            top, bottom = sorted((y0, y1))
            state["done"] = True
            if right - left < 8 or bottom - top < 8:
                overlay.destroy()
                return
            path = self._store_template(frame, left, top, right, bottom)
            if path:
                state["path"] = path
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", lambda _event: overlay.destroy())
        overlay.focus_force()

        self.root.wait_window(overlay)
        self.root.deiconify()
        self.root.lift()
        return state.get("path")

    def _place_capture_overlay(self, overlay: tk.Toplevel, frame) -> None:
        """Position the overlay over the virtual desktop.

        Tk reads a negative geometry offset as "distance from the right edge",
        which is wrong for a monitor left of the primary. Those cases are moved
        explicitly with SetWindowPos.
        """
        x, y = frame.origin
        overlay.geometry("%dx%d+0+0" % (frame.width, frame.height))
        overlay.update_idletasks()
        if x >= 0 and y >= 0:
            overlay.geometry("%dx%d+%d+%d" % (frame.width, frame.height, x, y))
            return
        hwnd = overlay.winfo_id()
        root = ctypes.windll.user32.GetAncestor(hwnd, 2) or hwnd
        flags = 0x0010 | 0x0040  # SWP_NOACTIVATE | SWP_SHOWWINDOW
        ctypes.windll.user32.SetWindowPos(
            root, -1, x, y, frame.width, frame.height, flags)
        overlay.update_idletasks()

    def _store_template(self, frame, left: int, top: int, right: int, bottom: int) -> Optional[str]:
        """Crop, save and report a template; None means the write failed."""
        crop = frame.bgra[top:bottom, left:right]
        rgb = np.ascontiguousarray(crop[..., 2::-1])
        assets = os.path.join(self.base_dir, "assets")
        try:
            os.makedirs(assets, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(assets, "click_%s.png" % stamp)
            suffix = 1
            while os.path.exists(path):
                path = os.path.join(assets, "click_%s_%d.png" % (stamp, suffix))
                suffix += 1
            save_image(path, rgb)
        except OSError as exc:
            messagebox.showerror(
                "保存模板失败", "无法写入 %s：%s" % (assets, exc), parent=self.root)
            return None
        return path

    # -- run ---------------------------------------------------------------
    def _run(self, live: bool) -> None:
        if self._running:
            return
        try:
            plan = self._collect()
        except ConfigError as exc:
            messagebox.showerror("计划有误", str(exc), parent=self.root)
            return
        if not plan.steps:
            messagebox.showwarning("没有步骤", "先用“框选模板并添加点击”加一个步骤。", parent=self.root)
            return
        if live and not messagebox.askyesno(
            "真实运行", "会真实移动鼠标并点击。\n建议先试运行确认。\n继续吗？", parent=self.root
        ):
            return

        self._stop_requested = False
        self._running = True
        self._set_running_buttons()
        self._set_status("运行中…" if not live else "真实运行中…", kind="run")
        thread = threading.Thread(target=self._worker, args=(plan, live), daemon=True)
        thread.start()

    def _post(self, callback, *args) -> None:
        """Schedule UI work only while the window still exists."""
        if self._closing:
            return
        try:
            self.root.after(0, callback, *args)
        except tk.TclError:
            pass

    def _worker(self, plan: Plan, live: bool) -> None:
        try:
            engine = Engine(
                SequenceTask(plan),
                config=EngineConfig(fps=plan.fps, dry_run=not live, abort_keys=("f12",)),
                settings={"threshold": plan.threshold, "scales": plan.scales,
                          "all_screens": True},
            )
            stats = engine.run(on_ready=self._on_ready)
            self._post(self._finished, stats)
        except Exception as exc:
            self._post(self._failed, exc)

    def _on_ready(self, ctx) -> None:
        self._safety = ctx.safety
        self._input = ctx.input
        if self._stop_requested:
            ctx.safety.request_stop("stopped before the first tick")

    def _stop(self) -> None:
        self._stop_requested = True
        if self._safety is not None:
            self._safety.request_stop("stopped from the editor")
        self._set_status("正在停止…", kind="run")

    def _finished(self, stats) -> None:
        self._running = False
        self._stop_requested = False
        self._safety = None
        self._input = None
        self._set_running_buttons()
        self._set_status("完成：%d 步，%d 次动作，%s"
                         % (stats.ticks, stats.actions, stats.stop_reason or "结束"))

    def _failed(self, exc: Exception) -> None:
        self._running = False
        self._stop_requested = False
        self._safety = None
        self._input = None
        self._set_running_buttons()
        self._set_status("出错：%s" % exc, kind="err")
        messagebox.showerror("运行失败", str(exc), parent=self.root)

    def _set_running_buttons(self) -> None:
        state = "disabled" if self._running else "normal"
        for button in self._edit_buttons:
            button.configure(state=state)
        self.dry_button.configure(state=state)
        self.live_button.configure(state=state)
        self.stop_button.configure(state="normal" if self._running else "disabled")

    # -- files -------------------------------------------------------------
    def _open_dialog(self) -> None:
        if self._running:
            return
        path = filedialog.askopenfilename(
            title="打开计划", filetypes=[("Osprey 计划", "*.json"), ("所有文件", "*.*")]
        )
        if path:
            self._open_path(path)

    def _open_path(self, path: str) -> None:
        try:
            plan = Plan.load(path)
        except ConfigError as exc:
            messagebox.showerror("无法打开", str(exc), parent=self.root)
            return
        self._load_plan(plan, path=os.path.abspath(path))

    def _save(self, save_as: bool = False) -> None:
        if self._running:
            return
        try:
            plan = self._collect()
        except ConfigError as exc:
            messagebox.showerror("计划有误", str(exc), parent=self.root)
            return
        path = self.plan_path
        if save_as or not path:
            path = filedialog.asksaveasfilename(
                title="保存计划", defaultextension=".json",
                filetypes=[("Osprey 计划", "*.json")],
            )
            if not path:
                return
        try:
            plan.save(path)
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return
        self.plan_path = os.path.abspath(path)
        self.base_dir = os.path.dirname(self.plan_path)
        self._set_status("已保存 %s" % self.plan_path)

    # -- misc --------------------------------------------------------------
    def _set_status(self, text: str, kind: str = "ok") -> None:
        self.status_var.set(text)
        colors = {"ok": PALETTE["ok"], "run": PALETTE["run"],
                  "err": PALETTE["err"], "idle": PALETTE["muted"]}
        self.status_dot.configure(fg=colors.get(kind, PALETTE["ok"]))

    def _on_close(self) -> None:
        if self._running:
            if not messagebox.askyesno("仍在运行", "任务还在运行，停止并退出？", parent=self.root):
                return
            self._stop()
        self._closing = True
        if self._input is not None:
            try:
                self._input.release_all()
            except Exception:
                pass
            self._input = None
        if self._log_handler is not None:
            logging.getLogger("osprey").removeHandler(self._log_handler)
        self.root.destroy()


def _detach_console() -> None:
    """Drop the console a double-clicked exe was given, so only the editor shows.

    When launched from an existing terminal FreeConsole only detaches; the
    terminal itself stays open.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass


def run_gui(plan_path: Optional[str] = None) -> int:
    enable_dpi_awareness()
    _detach_console()
    editor = PlanEditor(plan_path)
    editor.root.lift()
    editor.root.attributes("-topmost", True)
    editor.root.after(600, lambda: editor.root.attributes("-topmost", False))
    editor.root.focus_force()
    editor.root.mainloop()
    return 0
