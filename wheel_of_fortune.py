import json
import math
import random
import shutil
import time
import tkinter as tk
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple


DATA_FILE = Path("fortune_wheel_save.json")
EPSILON = 1e-9

THEMES = {
    "light": {
        "root_bg": "#edf2f7",
        "header_bg": "#e2e8f0",
        "panel_bg": "#f8fafc",
        "card_bg": "#ffffff",
        "border": "#d0d7e2",
        "text": "#0f172a",
        "muted": "#64748b",
        "entry_bg": "#ffffff",
        "entry_fg": "#0f172a",
        "list_bg": "#ffffff",
        "list_fg": "#0f172a",
        "list_select_bg": "#dbeafe",
        "list_select_fg": "#1e3a8a",
        "canvas_bg": "#ffffff",
        "stats_bg": "#f8fafc",
        "stats_fg": "#0f172a",
        "wheel_text": "#0f172a",
        "wheel_hint": "#475569",
        "wheel_outline": "#f8fafc",
        "center_fill": "#eef2ff",
        "center_outline": "#cbd5e1",
        "arrow_fill": "#ef4444",
        "arrow_outline": "#7f1d1d",
        "primary": "#4f46e5",
        "primary_hover": "#4338ca",
        "accent": "#f43f5e",
        "accent_hover": "#e11d48",
        "success": "#059669",
        "pill_bg": "#e2e8f0",
    },
    "dark": {
        "root_bg": "#020617",
        "header_bg": "#0b1220",
        "panel_bg": "#0f172a",
        "card_bg": "#111827",
        "border": "#243245",
        "text": "#e2e8f0",
        "muted": "#94a3b8",
        "entry_bg": "#1e293b",
        "entry_fg": "#e2e8f0",
        "list_bg": "#0f172a",
        "list_fg": "#e2e8f0",
        "list_select_bg": "#1d4ed8",
        "list_select_fg": "#f8fafc",
        "canvas_bg": "#020617",
        "stats_bg": "#0b1220",
        "stats_fg": "#e2e8f0",
        "wheel_text": "#e2e8f0",
        "wheel_hint": "#94a3b8",
        "wheel_outline": "#0b1220",
        "center_fill": "#111827",
        "center_outline": "#334155",
        "arrow_fill": "#fb7185",
        "arrow_outline": "#881337",
        "primary": "#2563eb",
        "primary_hover": "#1d4ed8",
        "accent": "#f43f5e",
        "accent_hover": "#e11d48",
        "success": "#10b981",
        "pill_bg": "#1e293b",
    },
}


@dataclass
class Lot:
    id: int
    name: str
    points: float
    eliminated: bool = False


class FortuneWheelApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Колесо Фортуны")
        self.root.geometry("1520x920")
        self.root.minsize(1280, 760)

        self.lots: List[Lot] = []
        self.history: List[str] = []
        self.next_lot_id = 1

        self.elimination_mode = tk.BooleanVar(value=False)
        self.dark_mode = tk.BooleanVar(value=True)
        self.spin_time = tk.DoubleVar(value=5.0)

        self.spinning = False
        self.current_angle = 0.0
        self.target_angle: Optional[float] = None
        self.spin_start_angle = 0.0
        self.spin_start_ts = 0.0
        self.spin_duration_ms = 5000
        self.spin_result_id: Optional[int] = None

        self.color_cache: Dict[str, Dict[int, str]] = {"light": {}, "dark": {}}
        self.current_theme_name = "dark"
        self.current_theme = THEMES[self.current_theme_name]
        self.card_frames: List[ttk.Frame] = []

        self._build_ui()
        self._load_data()
        self._refresh_all(redraw=True)

        self.canvas.bind("<Configure>", lambda _e: self.draw_wheel())

    # -------------------------- Persistence --------------------------
    def _load_data(self) -> None:
        if not DATA_FILE.exists():
            return
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            messagebox.showwarning("Ошибка", "Не удалось прочитать файл сохранения. Использую пустые данные.")
            return

        self.history = data.get("history", [])
        self.next_lot_id = max(int(data.get("next_lot_id", 1)), 1)
        self.dark_mode.set(bool(data.get("dark_mode", True)))

        loaded: List[Lot] = []
        for item in data.get("lots", []):
            try:
                lot = Lot(
                    id=int(item["id"]),
                    name=str(item["name"]).strip(),
                    points=float(item["points"]),
                    eliminated=bool(item.get("eliminated", False)),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if lot.name and lot.points > 0:
                loaded.append(lot)

        self.lots = loaded
        if self.lots:
            self.next_lot_id = max(self.next_lot_id, max(x.id for x in self.lots) + 1)

    def _save_data(self, show_message: bool = False) -> None:
        payload = {
            "next_lot_id": self.next_lot_id,
            "dark_mode": self.dark_mode.get(),
            "lots": [asdict(lot) for lot in self.lots],
            "history": self.history,
        }
        try:
            DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            messagebox.showerror("Ошибка", "Не удалось сохранить файл данных.")
            return
        if show_message:
            messagebox.showinfo("Сохранено", "Данные сохранены.")

    # -------------------------- Math & probability --------------------------
    def active_lots(self) -> List[Lot]:
        return [lot for lot in self.lots if not lot.eliminated]

    def _weights_for_mode(self, lots: List[Lot]) -> List[float]:
        if self.elimination_mode.get():
            return [1.0 / max(lot.points, EPSILON) for lot in lots]
        return [max(lot.points, EPSILON) for lot in lots]

    def _weighted_probabilities(self, lots: List[Lot]) -> List[float]:
        weights = self._weights_for_mode(lots)
        total = sum(weights)
        if total <= EPSILON:
            return [0.0 for _ in lots]
        return [w / total for w in weights]

    def _choose_lot_and_target_angle(self, lots: List[Lot]) -> Tuple[Lot, float]:
        probs = self._weighted_probabilities(lots)
        chosen = random.choices(lots, weights=probs, k=1)[0]

        sector_start = 0.0
        for lot, p in zip(lots, probs):
            extent = p * 360.0
            if lot.id == chosen.id:
                center = sector_start + extent / 2.0
                pointer_angle = 90.0
                landing = (pointer_angle - center) % 360.0
                return chosen, landing
            sector_start += extent

        return chosen, random.random() * 360.0


    def _lot_at_pointer(self, lots: List[Lot], wheel_angle: float) -> Optional[Lot]:
        if not lots:
            return None

        probs = self._weighted_probabilities(lots)
        pointer_angle = 90.0
        relative_angle = (pointer_angle - (wheel_angle % 360.0)) % 360.0

        cumulative = 0.0
        for lot, p in zip(lots, probs):
            extent = p * 360.0
            if cumulative <= relative_angle < cumulative + extent:
                return lot
            cumulative += extent

        return lots[-1]

    # -------------------------- UI construction --------------------------
    def _build_ui(self) -> None:
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.root_container = ttk.Frame(self.root)
        self.root_container.pack(fill=tk.BOTH, expand=True)

        self.header = ttk.Frame(self.root_container, padding=(18, 14))
        self.header.pack(fill=tk.X)

        self.title_label = ttk.Label(self.header, text="🎯 WHEEL OF FORTUNE", font=("Segoe UI", 18, "bold"))
        self.title_label.pack(side=tk.LEFT)

        self.subtitle_label = ttk.Label(self.header, text="взвешенные шансы · режим выбывания · история")
        self.subtitle_label.pack(side=tk.LEFT, padx=(14, 0))

        self.pointer_status_label = ttk.Label(self.header, text="Под стрелкой: —", font=("Segoe UI", 10, "bold"))
        self.pointer_status_label.pack(side=tk.LEFT, padx=(18, 0))

        self.header_badges = ttk.Frame(self.header)
        self.header_badges.pack(side=tk.RIGHT)
        self.badge_mode = ttk.Label(self.header_badges, style="Pill.TLabel", text="Режим: обычный")
        self.badge_mode.pack(side=tk.LEFT, padx=4)
        self.badge_active = ttk.Label(self.header_badges, style="Pill.TLabel", text="Активных: 0")
        self.badge_active.pack(side=tk.LEFT, padx=4)
        self.badge_points = ttk.Label(self.header_badges, style="Pill.TLabel", text="Баллы: 0")
        self.badge_points.pack(side=tk.LEFT, padx=4)

        self.content = ttk.Frame(self.root_container, padding=(14, 14, 14, 0))
        self.content.pack(fill=tk.BOTH, expand=True)

        self.left_panel = ttk.Frame(self.content, padding=14)
        self.left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))

        self.center_panel = ttk.Frame(self.content, padding=12)
        self.center_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.right_panel = ttk.Frame(self.content, padding=14)
        self.right_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()

        self.bottom = ttk.Frame(self.root_container, padding=(14, 10, 14, 16))
        self.bottom.pack(fill=tk.X)
        self.spin_btn = ttk.Button(self.bottom, text="КРУТИТЬ КОЛЕСО", style="Spin.TButton", command=self.spin_wheel)
        self.spin_btn.pack(fill=tk.X)

    def _build_left_panel(self) -> None:
        ttk.Label(self.left_panel, text="Лоты", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 8))

        add_card = ttk.Frame(self.left_panel, padding=10, style="Card.TFrame")
        self.card_frames.append(add_card)
        add_card.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(add_card, text="Название лота").grid(row=0, column=0, sticky="w")
        self.entry_name = ttk.Entry(add_card, width=26)
        self.entry_name.grid(row=1, column=0, padx=(0, 10), pady=(4, 0))

        ttk.Label(add_card, text="Баллы").grid(row=0, column=1, sticky="w")
        self.entry_points = ttk.Entry(add_card, width=10)
        self.entry_points.grid(row=1, column=1, pady=(4, 0))

        ttk.Button(add_card, text="Добавить", command=self.add_lot, style="Primary.TButton").grid(row=1, column=2, padx=(10, 0))
        ttk.Button(add_card, text="Обновить", command=self.update_selected_lot).grid(row=1, column=3, padx=(8, 0))
        ttk.Button(add_card, text="Очистить поля", command=self.clear_lot_inputs).grid(row=1, column=4, padx=(8, 0))

        self.lots_listbox = tk.Listbox(self.left_panel, width=46, height=22, font=("Consolas", 10), selectmode=tk.SINGLE)
        self.lots_listbox.pack(fill=tk.BOTH, expand=True)
        self.lots_listbox.bind("<Double-Button-1>", self._on_lot_select)

        row = ttk.Frame(self.left_panel, style="Card.TFrame", padding=6)
        self.card_frames.append(row)
        row.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(row, text="Удалить", command=self.remove_selected_lot).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(row, text="Сохранить", command=lambda: self._save_data(show_message=True)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(row, text="Сбросить выбывших", command=self.reset_eliminated).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

    def _build_center_panel(self) -> None:
        wheel_card = ttk.Frame(self.center_panel, padding=8, style="Card.TFrame")
        self.card_frames.append(wheel_card)
        wheel_card.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(wheel_card, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

    def _build_right_panel(self) -> None:
        settings_card = ttk.Frame(self.right_panel, padding=12, style="Card.TFrame")
        self.card_frames.append(settings_card)
        settings_card.pack(fill=tk.X)

        ttk.Label(settings_card, text="Настройки", font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Checkbutton(settings_card, text="Режим на выбывание", variable=self.elimination_mode, command=self.on_mode_changed).pack(anchor="w")
        ttk.Checkbutton(settings_card, text="Темная тема", variable=self.dark_mode, command=self.toggle_theme).pack(anchor="w", pady=(4, 10))

        time_row = ttk.Frame(settings_card)
        time_row.pack(fill=tk.X)
        ttk.Label(time_row, text="Время вращения").pack(side=tk.LEFT)
        self.lbl_time = ttk.Label(time_row, text="5.0 сек")
        self.lbl_time.pack(side=tk.RIGHT)

        ttk.Scale(settings_card, from_=1.0, to=12.0, variable=self.spin_time, command=self._on_spin_time_change).pack(fill=tk.X, pady=(6, 0))

        result_card = ttk.Frame(self.right_panel, padding=12, style="Card.TFrame")
        self.card_frames.append(result_card)
        result_card.pack(fill=tk.X, pady=(12, 0))

        ttk.Label(result_card, text="Результат", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.lbl_result = ttk.Label(result_card, text="Готово к запуску", font=("Segoe UI", 12, "bold"))
        self.lbl_result.pack(anchor="w", pady=(6, 0))

        chances_card = ttk.Frame(self.right_panel, padding=12, style="Card.TFrame")
        self.card_frames.append(chances_card)
        chances_card.pack(fill=tk.X, pady=(12, 0))

        ttk.Label(chances_card, text="Шансы выпадения", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.stats = tk.Text(chances_card, width=37, height=11, font=("Consolas", 10), state=tk.DISABLED, relief="flat", bd=0)
        self.stats.pack(fill=tk.X, pady=(6, 0))

        history_card = ttk.Frame(self.right_panel, padding=12, style="Card.TFrame")
        self.card_frames.append(history_card)
        history_card.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        ttk.Label(history_card, text="История", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.history_list = tk.Listbox(history_card, width=37, height=13, font=("Segoe UI", 10))
        self.history_list.pack(fill=tk.BOTH, expand=True, pady=(6, 8))
        ttk.Button(history_card, text="Очистить историю", command=self.clear_history).pack(fill=tk.X)

    # -------------------------- Theme --------------------------
    def toggle_theme(self) -> None:
        self.current_theme_name = "dark" if self.dark_mode.get() else "light"
        self._save_data()
        self._refresh_all(redraw=True)

    def _apply_theme(self) -> None:
        self.current_theme_name = "dark" if self.dark_mode.get() else "light"
        t = THEMES[self.current_theme_name]
        self.current_theme = t

        self.root.configure(bg=t["root_bg"])

        self.style.configure("TFrame", background=t["panel_bg"], borderwidth=0)
        self.style.configure("TLabel", background=t["panel_bg"], foreground=t["text"])
        self.style.configure("TCheckbutton", background=t["panel_bg"], foreground=t["text"])
        self.style.map("TCheckbutton", background=[("active", t["panel_bg"])], foreground=[("active", t["text"])])

        self.style.configure("TEntry", fieldbackground=t["entry_bg"], foreground=t["entry_fg"], insertcolor=t["entry_fg"])
        self.style.configure("TButton", background=t["card_bg"], foreground=t["text"], bordercolor=t["border"], lightcolor=t["border"], darkcolor=t["border"])
        self.style.map("TButton", background=[("active", t["header_bg"])])
        self.style.configure("Primary.TButton", background=t["primary"], foreground="#ffffff")
        self.style.map("Primary.TButton", background=[("active", t["primary_hover"])])
        self.style.configure("Spin.TButton", font=("Segoe UI", 13, "bold"), background=t["accent"], foreground="#ffffff", padding=12)
        self.style.map("Spin.TButton", background=[("active", t["accent_hover"])])
        self.style.configure("Card.TFrame", background=t["card_bg"], bordercolor=t["border"], relief="solid", borderwidth=1)
        self.style.configure("Pill.TLabel", background=t["pill_bg"], foreground=t["text"], padding=(10, 5), font=("Segoe UI", 9, "bold"))

        self.header.configure(style="Header.TFrame")
        self.style.configure("Header.TFrame", background=t["header_bg"])

        self.title_label.configure(background=t["header_bg"], foreground=t["text"])
        self.subtitle_label.configure(background=t["header_bg"], foreground=t["muted"])
        self.pointer_status_label.configure(background=t["header_bg"], foreground=t["success"])
        self.header_badges.configure(style="Header.TFrame")

        for frame in [self.left_panel, self.center_panel, self.right_panel, self.bottom, self.content, self.root_container]:
            frame.configure(style="Panel.TFrame")
        self.style.configure("Panel.TFrame", background=t["panel_bg"])
        for frame in self.card_frames:
            frame.configure(style="Card.TFrame")

        self.canvas.configure(bg=t["canvas_bg"])

        self.lots_listbox.configure(
            bg=t["list_bg"],
            fg=t["list_fg"],
            selectbackground=t["list_select_bg"],
            selectforeground=t["list_select_fg"],
            highlightthickness=1,
            highlightbackground=t["border"],
            relief="flat",
        )
        self.history_list.configure(
            bg=t["list_bg"],
            fg=t["list_fg"],
            selectbackground=t["list_select_bg"],
            selectforeground=t["list_select_fg"],
            highlightthickness=1,
            highlightbackground=t["border"],
            relief="flat",
        )
        self.stats.configure(
            bg=t["stats_bg"],
            fg=t["stats_fg"],
            insertbackground=t["stats_fg"],
            highlightthickness=1,
            highlightbackground=t["border"],
        )

    # -------------------------- Refresh --------------------------
    def _on_spin_time_change(self, value: str) -> None:
        self.lbl_time.config(text=f"{float(value):.1f} сек")

    def on_mode_changed(self) -> None:
        self._refresh_all(redraw=True)

    def _refresh_all(self, redraw: bool = False) -> None:
        self._apply_theme()
        self._refresh_lots_listbox()
        self._refresh_stats()
        self._refresh_history()
        self._refresh_header_badges()
        self._update_pointer_status()
        if redraw:
            self.draw_wheel()

    def _update_pointer_status(self) -> None:
        lots = self.active_lots()
        if not lots:
            self.pointer_status_label.config(text="Под стрелкой: —")
            return

        lot = self._lot_at_pointer(lots, self.current_angle)
        if lot is None:
            self.pointer_status_label.config(text="Под стрелкой: —")
            return

        self.pointer_status_label.config(text=f"Под стрелкой: {lot.name} ({lot.points:g})")

    def _refresh_header_badges(self) -> None:
        mode = "выбывание" if self.elimination_mode.get() else "обычный"
        active = self.active_lots()
        total_points = sum(lot.points for lot in active)
        self.badge_mode.config(text=f"Режим: {mode}")
        self.badge_active.config(text=f"Активных: {len(active)}")
        self.badge_points.config(text=f"Баллы: {total_points:.1f}")

    def _refresh_lots_listbox(self) -> None:
        self.lots_listbox.delete(0, tk.END)
        t = self.current_theme
        for lot in self.lots:
            marker = "(выбыл)" if lot.eliminated else ""
            text = f"{lot.name:<28} {lot.points:>8.2f}  {marker}"
            self.lots_listbox.insert(tk.END, text)
            idx = self.lots_listbox.size() - 1
            color = t["muted"] if lot.eliminated else self._color_for_lot(lot.id)
            self.lots_listbox.itemconfig(idx, fg=color)

    def _refresh_stats(self) -> None:
        lots = self.active_lots()
        probs = self._weighted_probabilities(lots)

        self.stats.config(state=tk.NORMAL)
        self.stats.delete("1.0", tk.END)

        if not lots:
            self.stats.insert(tk.END, "Нет активных лотов")
        else:
            mode = "Режим: выбывание (обратная вероятность)" if self.elimination_mode.get() else "Режим: обычный (по баллам)"
            self.stats.insert(tk.END, mode + "\n\n")
            for lot, p in zip(lots, probs):
                self.stats.insert(tk.END, f"{lot.name:<24} {p * 100:6.2f}%\n")

        self.stats.config(state=tk.DISABLED)

    def _refresh_history(self) -> None:
        self.history_list.delete(0, tk.END)
        for row in reversed(self.history[-250:]):
            self.history_list.insert(tk.END, row)

    # -------------------------- Colors and wheel draw --------------------------
    def _color_for_lot(self, lot_id: int) -> str:
        cache = self.color_cache[self.current_theme_name]
        if lot_id in cache:
            return cache[lot_id]

        hue = (lot_id * 0.61803398875) % 1.0
        if self.current_theme_name == "dark":
            saturation = 0.45
            lightness = 0.33
        else:
            saturation = 0.72
            lightness = 0.55

        r, g, b = self._hsl_to_rgb(hue, saturation, lightness)
        color = f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
        cache[lot_id] = color
        return color

    @staticmethod
    def _hsl_to_rgb(h: float, s: float, l: float) -> Tuple[float, float, float]:
        def hue_to_rgb(p: float, q: float, t: float) -> float:
            if t < 0:
                t += 1
            if t > 1:
                t -= 1
            if t < 1 / 6:
                return p + (q - p) * 6 * t
            if t < 1 / 2:
                return q
            if t < 2 / 3:
                return p + (q - p) * (2 / 3 - t) * 6
            return p

        if s == 0:
            return l, l, l

        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        return hue_to_rgb(p, q, h + 1 / 3), hue_to_rgb(p, q, h), hue_to_rgb(p, q, h - 1 / 3)

    def draw_wheel(self) -> None:
        self.canvas.delete("all")
        t = self.current_theme

        lots = self.active_lots()
        if not lots:
            self._update_pointer_status()
            self.canvas.create_text(30, 30, anchor="nw", text="Добавьте хотя бы один лот", fill=t["wheel_hint"], font=("Segoe UI", 14, "bold"))
            return

        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 180 or h < 180:
            return

        cx, cy = w // 2, h // 2
        radius = max(min(cx, cy) - 60, 40)

        probs = self._weighted_probabilities(lots)
        angle = self.current_angle % 360

        for lot, p in zip(lots, probs):
            extent = p * 360.0
            self.canvas.create_arc(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                start=angle,
                extent=extent,
                fill=self._color_for_lot(lot.id),
                outline=t["wheel_outline"],
                width=2,
                style=tk.PIESLICE,
            )

            mid = math.radians(angle + extent / 2)
            tx = cx + math.cos(mid) * radius * 0.62
            ty = cy - math.sin(mid) * radius * 0.62
            self.canvas.create_text(tx, ty, text=lot.name[:14], fill=t["wheel_text"], font=("Segoe UI", 10, "bold"))
            angle += extent

        center_radius = 38
        self.canvas.create_oval(
            cx - center_radius,
            cy - center_radius,
            cx + center_radius,
            cy + center_radius,
            fill=t["center_fill"],
            outline=t["center_outline"],
            width=3,
        )

        tip_y = cy - radius - 8
        self.canvas.create_polygon(
            cx - 18,
            tip_y - 28,
            cx + 18,
            tip_y - 28,
            cx,
            tip_y,
            fill=t["arrow_fill"],
            outline=t["arrow_outline"],
            width=3,
        )

        self._update_pointer_status()


    def clear_lot_inputs(self, keep_selection: bool = False) -> None:
        self.entry_name.delete(0, tk.END)
        self.entry_points.delete(0, tk.END)
        if not keep_selection:
            self.lots_listbox.selection_clear(0, tk.END)
        self.entry_name.focus_set()

    def _on_lot_select(self, _event=None) -> None:
        selection = self.lots_listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        if idx < 0 or idx >= len(self.lots):
            return

        lot = self.lots[idx]
        self.entry_name.delete(0, tk.END)
        self.entry_name.insert(0, lot.name)
        self.entry_points.delete(0, tk.END)
        self.entry_points.insert(0, f"{lot.points:g}")

    def update_selected_lot(self) -> None:
        selection = self.lots_listbox.curselection()
        if not selection:
            messagebox.showwarning("Ошибка", "Сначала выберите лот в списке.")
            return

        idx = selection[0]
        if idx < 0 or idx >= len(self.lots):
            return

        name = self.entry_name.get().strip()
        points_raw = self.entry_points.get().strip().replace(",", ".")

        if not name:
            messagebox.showwarning("Ошибка", "Введите название лота.")
            return

        try:
            points = float(points_raw)
        except ValueError:
            messagebox.showwarning("Ошибка", "Баллы должны быть числом.")
            return

        if points <= 0:
            messagebox.showwarning("Ошибка", "Баллы должны быть больше 0.")
            return

        self.lots[idx].name = name
        self.lots[idx].points = points

        self._save_data()
        self._refresh_all(redraw=True)
        self.lots_listbox.selection_set(idx)
        self.lots_listbox.activate(idx)
        self.clear_lot_inputs(keep_selection=True)

    # -------------------------- User actions --------------------------
    def add_lot(self) -> None:
        name = self.entry_name.get().strip()
        points_raw = self.entry_points.get().strip().replace(",", ".")

        if not name:
            messagebox.showwarning("Ошибка", "Введите название лота.")
            return

        try:
            points = float(points_raw)
        except ValueError:
            messagebox.showwarning("Ошибка", "Баллы должны быть числом.")
            return

        if points <= 0:
            messagebox.showwarning("Ошибка", "Баллы должны быть больше 0.")
            return

        self.lots.append(Lot(id=self.next_lot_id, name=name, points=points))
        self.next_lot_id += 1

        self.entry_name.delete(0, tk.END)
        self.entry_points.delete(0, tk.END)

        self._save_data()
        self._refresh_all(redraw=True)

    def remove_selected_lot(self) -> None:
        selection = self.lots_listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        if idx < 0 or idx >= len(self.lots):
            return

        del self.lots[idx]
        self._save_data()
        self._refresh_all(redraw=True)

    def reset_eliminated(self) -> None:
        for lot in self.lots:
            lot.eliminated = False
        self.lbl_result.config(text="Выбывшие восстановлены")
        self._save_data()
        self._refresh_all(redraw=True)

    def clear_history(self) -> None:
        self.history.clear()
        self._save_data()
        self._refresh_history()

    def spin_wheel(self) -> None:
        if self.spinning:
            return

        lots = self.active_lots()
        if not lots:
            messagebox.showwarning("Ошибка", "Нет активных лотов для прокрутки.")
            return

        if self.elimination_mode.get() and len(lots) == 1:
            self.lbl_result.config(text=f"Финальный победитель: {lots[0].name}")
            return

        chosen, landing = self._choose_lot_and_target_angle(lots)
        extra_turns = random.uniform(5.0, 8.0) * 360.0

        start = self.current_angle % 360
        target = start + extra_turns + ((landing - start) % 360)

        self.spin_result_id = chosen.id
        self.spin_start_angle = self.current_angle
        self.target_angle = target
        self.spin_duration_ms = int(self.spin_time.get() * 1000)
        self.spin_start_ts = time.time()
        self.spinning = True
        self.lbl_result.config(text="Крутим...")

        self._animate_spin()

    def _animate_spin(self) -> None:
        if not self.spinning or self.target_angle is None:
            return

        elapsed_ms = (time.time() - self.spin_start_ts) * 1000
        progress = min(elapsed_ms / max(self.spin_duration_ms, 1), 1.0)

        eased = 1.0 - (1.0 - progress) ** 3
        self.current_angle = self.spin_start_angle + (self.target_angle - self.spin_start_angle) * eased
        self.draw_wheel()

        if progress < 1.0:
            self.root.after(16, self._animate_spin)
            return

        self.current_angle = self.target_angle % 360
        self.spinning = False

        lots_now = self.active_lots()
        chosen = self._lot_at_pointer(lots_now, self.current_angle)
        if chosen is None and self.spin_result_id is not None:
            chosen = next((x for x in self.lots if x.id == self.spin_result_id), None)
        if chosen is None:
            return

        if self.elimination_mode.get():
            chosen.eliminated = True
            self.lbl_result.config(text=f"Выбыл: {chosen.name}")
            self.history.append(f"Выбыл: {chosen.name}")

            remaining = self.active_lots()
            if len(remaining) == 1:
                winner = remaining[0]
                self.lbl_result.config(text=f"Победитель: {winner.name}")
                self.history.append(f"Победитель: {winner.name}")
                messagebox.showinfo("Финал", f"Победитель: {winner.name}")
        else:
            self.lbl_result.config(text=f"Победитель: {chosen.name}")
            self.history.append(f"Победитель: {chosen.name}")

        self._save_data()
        self._refresh_all(redraw=True)


def main() -> None:
    root = tk.Tk()
    app = FortuneWheelApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()