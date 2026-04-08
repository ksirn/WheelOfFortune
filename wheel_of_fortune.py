"""
Колесо Фортуны — PyQt6
Запуск: python fortune_wheel.py
Зависимости: pip install PyQt6 discord.py python-dotenv
"""

import asyncio
import json
import math
import random
import time
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath,
                          QPen, QRadialGradient)
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout,
                              QLabel, QLineEdit, QListWidget, QListWidgetItem,
                              QMainWindow, QPushButton, QScrollArea,
                              QSizePolicy, QSlider, QVBoxLayout, QWidget,
                              QProgressBar)

DATA_FILE = Path("fortune_wheel_save.json")
EPSILON = 1e-9
MAX_HISTORY = 250

PALETTE = {
    "dark": {
        "bg":           "#0d1117",
        "surface":      "#161b22",
        "surface2":     "#21262d",
        "border":       "#30363d",
        "text":         "#e6edf3",
        "muted":        "#8b949e",
        "accent":       "#58a6ff",
        "accent2":      "#f78166",
        "success":      "#3fb950",
        "warning":      "#d29922",
        "spin_end":     "#388bfd",
        "outline":      "#0d1117",
        "center_bg":    "#161b22",
        "arrow":        "#f78166",
    },
    "light": {
        "bg":           "#f6f8fa",
        "surface":      "#ffffff",
        "surface2":     "#f0f3f6",
        "border":       "#d0d7de",
        "text":         "#1f2328",
        "muted":        "#656d76",
        "accent":       "#0969da",
        "accent2":      "#cf222e",
        "success":      "#1a7f37",
        "warning":      "#9a6700",
        "spin_end":     "#218bff",
        "outline":      "#f6f8fa",
        "center_bg":    "#ffffff",
        "arrow":        "#cf222e",
    },
}

SECTOR_COLORS_DARK = [
    "#1a3a6e", "#5c2d7a", "#14523e", "#6b2424",
    "#3d3d10", "#14405e", "#52300e", "#243d14",
    "#30145e", "#143058", "#524014", "#14522e",
    "#2a1a5e", "#5e1a3a", "#1a5e52", "#5e3a14",
]
SECTOR_COLORS_LIGHT = [
    "#4a8fd4", "#a050c0", "#30a060", "#d84040",
    "#c09018", "#1898c0", "#c06828", "#68a018",
    "#6838c0", "#1868c0", "#c0a030", "#18c068",
    "#5030c0", "#c0305a", "#18c0a8", "#c05818",
]


@dataclass
class Lot:
    id: int
    name: str
    points: float
    eliminated: bool = False


def lot_color(lot_id: int, dark: bool) -> QColor:
    p = SECTOR_COLORS_DARK if dark else SECTOR_COLORS_LIGHT
    return QColor(p[lot_id % len(p)])


# ── Wheel ─────────────────────────────────────────────────────────────────────

class WheelWidget(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lots: List[Lot] = []
        self.probs: List[float] = []
        self.angle: float = 0.0
        self.dark_mode = True
        self.spinning = False
        self.hover_center = False
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(400, 400)

    def set_lots(self, lots, probs):
        self.lots = list(lots)
        self.probs = list(probs)
        self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        p = PALETTE["dark" if self.dark_mode else "light"]
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        radius = min(cx, cy) - 16

        painter.fillRect(0, 0, w, h, QColor(p["bg"]))

        if not self.lots:
            painter.setPen(QColor(p["muted"]))
            painter.setFont(QFont("Segoe UI", 14))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Добавьте лоты →")
            return

        # ── Sectors ──
        start = self.angle
        for lot, prob in zip(self.lots, self.probs):
            span = prob * 360.0
            color = lot_color(lot.id, self.dark_mode)
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(p["outline"]), 1.5))
            rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            painter.drawPie(rect, int(start * 16), int(span * 16))
            start += span

        # ── Labels — always readable, never upside-down ──
        # Qt drawPie: angle=0 → 3 o'clock, grows counter-clockwise (screen coords)
        # math.cos/sin: angle=0 → right, positive = counter-clockwise
        # They match, so mid_rad can be used directly for position.
        # For rotation: Qt rotate() is clockwise. Text reads left→right when
        # rotated to point outward. "Outward" direction = mid_deg degrees CCW from east.
        # To avoid upside-down text, flip sectors whose outward direction points left
        # (i.e. mid angle is between 90° and 270° in standard math coords).

        start = self.angle
        for lot, prob in zip(self.lots, self.probs):
            span = prob * 360.0
            start += span
            if span < 3.0:
                continue

            mid_deg = (start - span / 2) % 360   # midpoint in Qt/math degrees (CCW from east)
            mid_rad = math.radians(mid_deg)

            # Text center at 62% of radius
            tr = radius * 0.62
            tx = cx + math.cos(mid_rad) * tr
            ty = cy - math.sin(mid_rad) * tr     # screen y is inverted

            # Rotation: align text along the radius
            # Qt rotate is CW, so to point text outward at mid_deg (CCW), use -mid_deg
            # Flip if the outward direction points into left half (90 < mid_deg < 270)
            # so text never appears upside-down
            rot = -mid_deg
            if 90 < mid_deg < 270:
                rot += 180

            # Font size: larger, based on sector size, clamp 8–13
            font_size = max(8, min(13, int(span * 0.65)))
            font = QFont("Segoe UI", font_size, QFont.Weight.Bold)

            # Available width: arc at 90% radius
            arc_len_px = radius * 0.90 * math.radians(span) * 0.93
            char_w = font_size * 0.56
            max_chars = int(arc_len_px / char_w)

            if max_chars < 4:
                continue

            if len(lot.name) <= max_chars:
                label = lot.name
            elif max_chars >= 6:
                label = lot.name[:max_chars - 1] + "…"
            else:
                continue

            painter.save()
            painter.translate(tx, ty)
            painter.rotate(rot)
            painter.setFont(font)

            text_rect = QRectF(-90, -10, 180, 20)
            painter.setPen(QColor(0, 0, 0, 110))
            painter.drawText(text_rect.translated(0, 1), Qt.AlignmentFlag.AlignCenter, label)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)
            painter.restore()

        # ── Outer ring ──
        painter.setPen(QPen(QColor(p["border"]), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        # ── Center circle ──
        cr = 48
        is_hover = self.hover_center and not self.spinning

        glow = QColor(p["accent"])
        glow.setAlpha(80 if is_hover else 30)
        grad = QRadialGradient(cx, cy, cr + 22)
        grad.setColorAt(0, glow)
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), cr + 22, cr + 22)

        fill = QColor(p["accent"] if is_hover else p["center_bg"])
        painter.setBrush(QBrush(fill))
        bc = QColor(p["accent"])
        bc.setAlpha(220)
        painter.setPen(QPen(bc, 2.5))
        painter.drawEllipse(QPointF(cx, cy), cr, cr)

        painter.setPen(QColor("#ffffff" if (is_hover or self.dark_mode) else p["text"]))
        painter.setFont(QFont("Segoe UI", 22 if not self.spinning else 11))
        painter.drawText(
            QRectF(cx - cr, cy - cr, cr * 2, cr * 2),
            Qt.AlignmentFlag.AlignCenter,
            "..." if self.spinning else "▶"
        )

        # ── Arrow ──
        ax, ay = cx, cy - radius - 4
        sz = 18
        path = QPainterPath()
        path.moveTo(ax, ay)
        path.lineTo(ax - sz * 0.55, ay - sz)
        path.lineTo(ax + sz * 0.55, ay - sz)
        path.closeSubpath()
        painter.setBrush(QBrush(QColor(p["arrow"])))
        painter.setPen(QPen(QColor(p["bg"]), 2))
        painter.drawPath(path)

    def mouseMoveEvent(self, e):
        cx, cy = self.width() / 2, self.height() / 2
        dist = math.hypot(e.position().x() - cx, e.position().y() - cy)
        was = self.hover_center
        self.hover_center = dist <= 48
        if self.hover_center != was:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.hover_center else Qt.CursorShape.ArrowCursor)
            self.update()

    def mousePressEvent(self, e):
        cx, cy = self.width() / 2, self.height() / 2
        if math.hypot(e.position().x() - cx, e.position().y() - cy) <= 48 and not self.spinning:
            self.clicked.emit()

    def leaveEvent(self, _):
        self.hover_center = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()


# ── Lot Card ──────────────────────────────────────────────────────────────────

class LotCard(QFrame):
    remove_requested = pyqtSignal(int)
    edit_requested = pyqtSignal(int)

    def __init__(self, lot: Lot, prob: float, dark: bool, parent=None):
        super().__init__(parent)
        self.lot_id = lot.id
        p = PALETTE["dark" if dark else "light"]
        color = lot_color(lot.id, dark).name()
        self.setFixedHeight(48)
        self.setStyleSheet(f"""
            QFrame {{
                background: {p['surface2']};
                border: 1px solid {p['border']};
                border-left: 4px solid {color};
                border-radius: 7px;
            }}
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(8)

        name_lbl = QLabel(f"✗ {lot.name}" if lot.eliminated else lot.name)
        name_lbl.setStyleSheet(f"""
            color: {'#6e7681' if lot.eliminated else p['text']};
            font-size: 12px; font-weight: {'400' if lot.eliminated else '600'};
            background: transparent; border: none;
        """)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(name_lbl)

        pts = QLabel(f"{lot.points:g} pts")
        pts.setStyleSheet(f"color: {p['muted']}; font-size: 11px; background: transparent; border: none;")
        lay.addWidget(pts)

        prob_lbl = QLabel(f"{prob * 100:.1f}%")
        prob_lbl.setFixedWidth(40)
        prob_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prob_lbl.setStyleSheet(f"color: {p['accent']}; font-size: 11px; font-weight: 700; background: transparent; border: none;")
        lay.addWidget(prob_lbl)

        for icon, attr, hover_c in [("✎", "edit_requested", p["accent"]), ("✕", "remove_requested", p["accent2"])]:
            btn = QPushButton(icon)
            btn.setFixedSize(24, 24)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; border: none; color: {p['muted']}; font-size: 13px; border-radius: 4px; }}
                QPushButton:hover {{ color: {hover_c}; background: {p['surface']}; }}
            """)
            sig = getattr(self, attr)
            btn.clicked.connect(lambda _, s=sig: s.emit(self.lot_id))
            lay.addWidget(btn)


# ── Edit Dialog ───────────────────────────────────────────────────────────────

class EditDialog(QDialog):
    def __init__(self, lot: Lot, dark: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактировать лот")
        self.setFixedSize(300, 150)
        p = PALETTE["dark" if dark else "light"]
        self.setStyleSheet(f"""
            QDialog {{ background: {p['surface']}; }}
            QLabel {{ color: {p['text']}; font-size: 13px; background: transparent; }}
            QLineEdit {{
                background: {p['surface2']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 6px; padding: 5px 9px; font-size: 13px;
            }}
            QPushButton {{
                background: {p['accent']}; color: #fff; border: none;
                border-radius: 6px; padding: 7px 16px; font-size: 13px; font-weight: 700;
            }}
            QPushButton:hover {{ background: {p['spin_end']}; }}
            QPushButton#cancel {{ background: {p['surface2']}; color: {p['text']}; border: 1px solid {p['border']}; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Название"))
        self.name_e = QLineEdit(lot.name)
        r1.addWidget(self.name_e)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Баллы   "))
        self.pts_e = QLineEdit(f"{lot.points:g}")
        r2.addWidget(self.pts_e)
        lay.addLayout(r2)

        btns = QHBoxLayout()
        c = QPushButton("Отмена"); c.setObjectName("cancel"); c.clicked.connect(self.reject)
        o = QPushButton("Сохранить"); o.clicked.connect(self.accept)
        btns.addWidget(c); btns.addWidget(o)
        lay.addLayout(btns)

    def values(self):
        return self.name_e.text().strip(), self.pts_e.text().strip()


# ── Sync signal bridge ────────────────────────────────────────────────────────

class SyncSignals(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)


# ── Main Window ───────────────────────────────────────────────────────────────

class FortuneWheelApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Колесо Фортуны")
        self.resize(1400, 860)
        self.setMinimumSize(1000, 660)

        self.lots: List[Lot] = []
        self.history: List[str] = []
        self.next_lot_id = 1
        self.dark_mode = True
        self.elimination_mode = False
        self.spin_duration_ms = 5000

        self.spinning = False
        self.current_angle = 0.0
        self.target_angle = 0.0
        self.spin_start_angle = 0.0
        self.spin_start_ts = 0.0
        self.spin_result_id: Optional[int] = None
        self._secondary_btns: List[QPushButton] = []

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._animate_step)

        self._sync_signals = SyncSignals()
        self._sync_signals.progress.connect(self._on_sync_progress)
        self._sync_signals.finished.connect(self._on_sync_finished)

        self._build_ui()
        self._load_data()
        self._refresh_all()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_data(self):
        if not DATA_FILE.exists():
            return
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        self.dark_mode = bool(data.get("dark_mode", True))
        self.history = data.get("history", [])[-MAX_HISTORY:]
        self.next_lot_id = max(int(data.get("next_lot_id", 1)), 1)
        for item in data.get("lots", []):
            try:
                lot = Lot(int(item["id"]), str(item["name"]).strip(),
                          float(item["points"]), bool(item.get("eliminated", False)))
                if lot.name and lot.points > 0:
                    self.lots.append(lot)
            except Exception:
                continue
        if self.lots:
            self.next_lot_id = max(self.next_lot_id, max(x.id for x in self.lots) + 1)

    def _save_data(self):
        try:
            DATA_FILE.write_text(
                json.dumps({
                    "next_lot_id": self.next_lot_id,
                    "dark_mode": self.dark_mode,
                    "lots": [asdict(l) for l in self.lots],
                    "history": self.history[-MAX_HISTORY:],
                }, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except OSError:
            pass

    # ── Logic ─────────────────────────────────────────────────────────────────

    def active_lots(self):
        return [l for l in self.lots if not l.eliminated]

    def _probs(self, lots):
        weights = [1.0 / max(l.points, EPSILON) if self.elimination_mode
                   else max(l.points, EPSILON) for l in lots]
        total = sum(weights)
        return [w / total for w in weights] if total > EPSILON else [0.0] * len(lots)

    def _lot_at_pointer(self, lots, angle):
        if not lots:
            return None
        probs = self._probs(lots)
        rel = (90.0 - (angle % 360.0)) % 360.0
        if rel >= 360.0 - EPSILON:
            return lots[-1]
        cum = 0.0
        for lot, p in zip(lots, probs):
            span = p * 360.0
            if cum <= rel < cum + span:
                return lot
            cum += span
        return lots[-1]

    def _choose_target(self, lots):
        probs = self._probs(lots)
        chosen = random.choices(lots, weights=probs, k=1)[0]
        cum = 0.0
        for lot, p in zip(lots, probs):
            span = p * 360.0
            if lot.id == chosen.id:
                return chosen, (90.0 - (cum + span / 2)) % 360.0
            cum += span
        return chosen, random.random() * 360.0

    # ── Spin ──────────────────────────────────────────────────────────────────

    def spin_wheel(self):
        if self.spinning:
            return
        lots = self._wheel_lots if hasattr(self, '_wheel_lots') else []
        if not lots:
            self._set_result("Нет активных лотов", warning=True)
            return
        if self.elimination_mode and len(lots) == 1:
            self._set_result(f"🏆 Победитель: {lots[0].name}", success=True)
            return

        chosen, landing = self._choose_target(lots)
        extra = random.uniform(5, 9) * 360.0
        start = self.current_angle % 360
        self.target_angle = start + extra + ((landing - start) % 360)
        self.spin_start_angle = self.current_angle
        self.spin_start_ts = time.time()
        self.spin_result_id = chosen.id
        self.spinning = True
        self.wheel.spinning = True
        self._set_result("Крутим...", muted=True)
        self._timer.start()

    def _animate_step(self):
        elapsed = (time.time() - self.spin_start_ts) * 1000
        progress = min(elapsed / max(self.spin_duration_ms, 1), 1.0)
        eased = 1.0 - (1.0 - progress) ** 3
        self.current_angle = self.spin_start_angle + (self.target_angle - self.spin_start_angle) * eased
        self.wheel.angle = self.current_angle % 360
        self.wheel.update()
        self._update_pointer_lbl()
        if progress >= 1.0:
            self._timer.stop()
            self.current_angle = self.target_angle % 360
            self.wheel.angle = self.current_angle
            self.wheel.spinning = False
            self.spinning = False
            self._on_spin_done()

    def _on_spin_done(self):
        lots = self._wheel_lots if hasattr(self, '_wheel_lots') else []
        chosen = self._lot_at_pointer(lots, self.current_angle)
        if chosen is None and self.spin_result_id is not None:
            chosen = next((x for x in self.lots if x.id == self.spin_result_id), None)
        if chosen is None:
            return
        if self.elimination_mode:
            chosen.eliminated = True
            self._set_result(f"Выбыл: {chosen.name}")
            self.history.append(f"Выбыл: {chosen.name}")
            remaining = self.active_lots()
            if len(remaining) == 1:
                msg = f"🏆 Победитель: {remaining[0].name}"
                self._set_result(msg, success=True)
                self.history.append(msg)
        else:
            msg = f"🏆 {chosen.name}"
            self._set_result(msg, success=True)
            self.history.append(f"Победитель: {chosen.name}")
        self._save_data()
        self._refresh_all()

    # ── Discord sync ──────────────────────────────────────────────────────────

    def _start_discord_sync(self):
        """Запускает синхронизацию с Discord в фоновом потоке."""
        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("⟳ Подключаюсь...")
        self.sync_progress.setVisible(True)
        self.sync_progress.setRange(0, 0)  # indeterminate

        def run():
            try:
                import discord_sync as ds
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    ds.sync(progress_cb=lambda msg: self._sync_signals.progress.emit(msg))
                )
                loop.close()
                self._sync_signals.finished.emit(result)
            except ImportError:
                self._sync_signals.finished.emit("Ошибка: файл discord_sync.py не найден рядом с программой")
            except Exception as e:
                self._sync_signals.finished.emit(f"Ошибка синхронизации: {e}")

        t = threading.Thread(target=run, daemon=True)
        t.start()

    def _on_sync_progress(self, msg: str):
        self.sync_btn.setText(f"⟳ {msg[:40]}")

    def _on_sync_finished(self, result: str):
        self.sync_progress.setVisible(False)
        self.sync_btn.setEnabled(True)
        self.sync_btn.setText("⟳ Обновить из Discord")
        self._set_result(result, success="Готово" in result)
        # Полностью перезагружаем лоты из файла (Discord полностью заменил их)
        self.lots.clear()
        self.next_lot_id = 1
        self._load_data()
        self._refresh_all()

    # ── UI Build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self.header_w = QWidget()
        self.header_w.setFixedHeight(52)
        hl = QHBoxLayout(self.header_w)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(10)

        self.title_lbl = QLabel("🎯  WHEEL OF FORTUNE")
        self.title_lbl.setStyleSheet("font-size: 16px; font-weight: 800; letter-spacing: 1px;")
        hl.addWidget(self.title_lbl)

        self.pointer_lbl = QLabel("▲ —")
        self.pointer_lbl.setStyleSheet("font-size: 12px; font-weight: 600;")
        hl.addWidget(self.pointer_lbl)

        hl.addStretch()

        self.sync_btn = QPushButton("⟳ Обновить из Discord")
        self.sync_btn.setFixedHeight(32)
        self.sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_btn.clicked.connect(self._start_discord_sync)
        hl.addWidget(self.sync_btn)

        self.theme_btn = QPushButton("☀ Светлая")
        self.theme_btn.setFixedHeight(32)
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self._toggle_theme)
        hl.addWidget(self.theme_btn)

        self.elim_btn = QPushButton("Режим выбывания: ВЫКЛ")
        self.elim_btn.setFixedHeight(32)
        self.elim_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.elim_btn.clicked.connect(self._toggle_elimination)
        hl.addWidget(self.elim_btn)

        root.addWidget(self.header_w)

        # Sync progress bar (скрыт по умолчанию)
        self.sync_progress = QProgressBar()
        self.sync_progress.setFixedHeight(3)
        self.sync_progress.setTextVisible(False)
        self.sync_progress.setVisible(False)
        root.addWidget(self.sync_progress)

        self.sep = QFrame()
        self.sep.setFrameShape(QFrame.Shape.HLine)
        self.sep.setFixedHeight(1)
        root.addWidget(self.sep)

        # Body
        body = QHBoxLayout()
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(14)

        # ── Left: lot list (compact) ──
        left = QVBoxLayout()
        left.setSpacing(6)

        lots_hdr = QHBoxLayout()
        self.lots_count_lbl = QLabel("Лоты")
        self.lots_count_lbl.setStyleSheet("font-size: 13px; font-weight: 700;")
        lots_hdr.addWidget(self.lots_count_lbl)
        lots_hdr.addStretch()
        reset_btn = QPushButton("↺ Сбросить")
        reset_btn.setFixedHeight(26)
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_eliminated)
        self._secondary_btns.append(reset_btn)
        lots_hdr.addWidget(reset_btn)
        left.addLayout(lots_hdr)

        add_row = QHBoxLayout()
        add_row.setSpacing(5)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Название лота...")
        self.name_input.setFixedHeight(34)
        self.name_input.returnPressed.connect(self._add_lot)
        add_row.addWidget(self.name_input, 3)
        self.pts_input = QLineEdit()
        self.pts_input.setPlaceholderText("Баллы")
        self.pts_input.setFixedHeight(34)
        self.pts_input.setFixedWidth(64)
        self.pts_input.returnPressed.connect(self._add_lot)
        add_row.addWidget(self.pts_input)
        self.add_btn = QPushButton("+ Добавить")
        self.add_btn.setFixedHeight(34)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self._add_lot)
        add_row.addWidget(self.add_btn)
        left.addLayout(add_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(4)
        self.cards_layout.setContentsMargins(0, 0, 4, 0)
        self.cards_layout.addStretch()
        scroll.setWidget(self.cards_container)
        left.addWidget(scroll, 1)
        body.addLayout(left, 28)

        # ── Center: wheel (максимум места) ──
        center = QVBoxLayout()
        center.setSpacing(8)
        self.wheel = WheelWidget()
        self.wheel.clicked.connect(self.spin_wheel)
        center.addWidget(self.wheel, 1)

        self.result_lbl = QLabel("Нажмите на центр колеса чтобы крутить")
        self.result_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_lbl.setFixedHeight(28)
        center.addWidget(self.result_lbl)

        slider_row = QHBoxLayout()
        self._slider_lbl = QLabel("Время:")
        self._slider_lbl.setFixedWidth(44)
        slider_row.addWidget(self._slider_lbl)
        self.time_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_slider.setRange(10, 120)
        self.time_slider.setValue(50)
        self.time_slider.setFixedHeight(18)
        self.time_slider.valueChanged.connect(self._on_slider)
        slider_row.addWidget(self.time_slider)
        self.time_val_lbl = QLabel("5.0 сек")
        self.time_val_lbl.setFixedWidth(50)
        slider_row.addWidget(self.time_val_lbl)
        center.addLayout(slider_row)
        body.addLayout(center, 50)

        # ── Right: stats + history (compact) ──
        right = QVBoxLayout()
        right.setSpacing(8)

        stats_lbl = QLabel("Шансы")
        stats_lbl.setStyleSheet("font-size: 13px; font-weight: 700;")
        right.addWidget(stats_lbl)
        self.stats_list = QListWidget()
        self.stats_list.setFixedHeight(200)
        self.stats_list.setSpacing(1)
        self.stats_list.setFrameShape(QFrame.Shape.NoFrame)
        right.addWidget(self.stats_list)

        hist_hdr = QHBoxLayout()
        hist_lbl = QLabel("История")
        hist_lbl.setStyleSheet("font-size: 13px; font-weight: 700;")
        hist_hdr.addWidget(hist_lbl)
        hist_hdr.addStretch()
        clr_btn = QPushButton("Очистить")
        clr_btn.setFixedHeight(24)
        clr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clr_btn.clicked.connect(self._clear_history)
        self._secondary_btns.append(clr_btn)
        hist_hdr.addWidget(clr_btn)
        right.addLayout(hist_hdr)

        self.history_list = QListWidget()
        self.history_list.setFrameShape(QFrame.Shape.NoFrame)
        self.history_list.setSpacing(1)
        right.addWidget(self.history_list, 1)
        body.addLayout(right, 22)

        bw = QWidget()
        bw.setLayout(body)
        root.addWidget(bw, 1)

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self._save_data()
        self._refresh_all()

    def _toggle_elimination(self):
        self.elimination_mode = not self.elimination_mode
        self._refresh_all()

    def _apply_styles(self):
        p = PALETTE["dark" if self.dark_mode else "light"]

        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {p['bg']}; color: {p['text']};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QLineEdit {{
                background: {p['surface2']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 7px;
                padding: 3px 9px; font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {p['accent']}; }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: {p['surface2']}; width: 5px; border-radius: 2px;
            }}
            QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 2px; }}
            QSlider::groove:horizontal {{
                background: {p['surface2']}; height: 3px; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {p['accent']}; width: 13px; height: 13px;
                margin: -5px 0; border-radius: 6px;
            }}
            QSlider::sub-page:horizontal {{ background: {p['accent']}; border-radius: 2px; }}
            QProgressBar {{ background: {p['surface2']}; border: none; }}
            QProgressBar::chunk {{ background: {p['accent']}; }}
        """)

        self.header_w.setStyleSheet(f"background: {p['surface']}; border: none;")
        self.sep.setStyleSheet(f"background: {p['border']};")
        self.title_lbl.setStyleSheet(f"color: {p['text']}; font-size: 16px; font-weight: 800; letter-spacing: 1px; background: transparent;")
        self.pointer_lbl.setStyleSheet(f"color: {p['success']}; font-size: 12px; font-weight: 600; background: transparent;")

        # Sync button
        self.sync_btn.setStyleSheet(f"""
            QPushButton {{
                background: {p['surface2']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 6px;
                padding: 0 11px; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {p['accent']}; color: {p['accent']}; }}
            QPushButton:disabled {{ color: {p['muted']}; }}
        """)

        self.theme_btn.setText("☀ Светлая" if self.dark_mode else "🌙 Тёмная")
        self.theme_btn.setStyleSheet(f"""
            QPushButton {{
                background: {p['surface2']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 6px;
                padding: 0 11px; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {p['accent']}; color: {p['accent']}; }}
        """)

        elim = self.elimination_mode
        elim_bg = "#1a3a1a" if (elim and self.dark_mode) else ("#d0ead0" if elim else p["surface2"])
        self.elim_btn.setText(f"Выбывание: {'ВКЛ ✓' if elim else 'ВЫКЛ'}")
        self.elim_btn.setStyleSheet(f"""
            QPushButton {{
                background: {elim_bg}; color: {p['success'] if elim else p['text']};
                border: 1px solid {p['success'] if elim else p['border']};
                border-radius: 6px; padding: 0 11px; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {p['success']}; }}
        """)

        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background: {p['accent']}; color: #fff;
                border: none; border-radius: 7px; font-size: 12px; font-weight: 700;
            }}
            QPushButton:hover {{ background: {p['spin_end']}; }}
        """)

        for w in [self.name_input, self.pts_input]:
            w.setStyleSheet(f"""
                QLineEdit {{
                    background: {p['surface2']}; color: {p['text']};
                    border: 1px solid {p['border']}; border-radius: 7px;
                    padding: 3px 9px; font-size: 12px;
                }}
                QLineEdit:focus {{ border-color: {p['accent']}; }}
            """)

        sec = f"""
            QPushButton {{
                background: {p['surface2']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 6px;
                padding: 0 9px; font-size: 11px;
            }}
            QPushButton:hover {{ border-color: {p['accent']}; color: {p['accent']}; }}
        """
        for btn in self._secondary_btns:
            btn.setStyleSheet(sec)

        lst = f"""
            QListWidget {{
                background: {p['surface']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 7px;
                padding: 3px; font-size: 11px; outline: none;
            }}
            QListWidget::item {{ padding: 2px 5px; border-radius: 3px; }}
            QListWidget::item:selected {{ background: {p['accent']}; color: #fff; }}
        """
        self.stats_list.setStyleSheet(lst)
        self.history_list.setStyleSheet(lst)

        self.result_lbl.setStyleSheet(f"color: {p['text']}; font-size: 14px; font-weight: 700; background: transparent;")
        self.lots_count_lbl.setStyleSheet(f"color: {p['text']}; font-size: 13px; font-weight: 700; background: transparent;")
        self.time_val_lbl.setStyleSheet(f"color: {p['muted']}; font-size: 11px; background: transparent;")
        self._slider_lbl.setStyleSheet(f"color: {p['muted']}; font-size: 11px; background: transparent;")
        self.cards_container.setStyleSheet("background: transparent;")
        self.wheel.dark_mode = self.dark_mode
        self.wheel.update()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh_all(self):
        self._apply_styles()
        self._refresh_cards()
        self._refresh_stats()
        self._refresh_history()
        self._update_pointer_lbl()
        lots = self.active_lots()
        self.lots_count_lbl.setText(f"Лоты ({len(lots)} активных)")
        probs = self._probs(lots)
        # Перемешиваем один раз — используется и колесом и для определения победителя
        combined = list(zip(lots, probs))
        random.shuffle(combined)
        if combined:
            self._wheel_lots, self._wheel_probs = zip(*combined)
            self._wheel_lots = list(self._wheel_lots)
            self._wheel_probs = list(self._wheel_probs)
        else:
            self._wheel_lots, self._wheel_probs = [], []
        self.wheel.set_lots(self._wheel_lots, self._wheel_probs)

    def _refresh_cards(self):
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        lots = self.active_lots()
        prob_map = {l.id: p for l, p in zip(lots, self._probs(lots))}
        for lot in self.lots:
            card = LotCard(lot, prob_map.get(lot.id, 0.0), self.dark_mode)
            card.remove_requested.connect(self._remove_lot)
            card.edit_requested.connect(self._edit_lot)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

    def _refresh_stats(self):
        self.stats_list.clear()
        lots = self.active_lots()
        for lot, prob in zip(lots, self._probs(lots)):
            bar = "█" * max(1, int(prob * 18))
            item = QListWidgetItem(f"{lot.name[:20]:<20} {prob*100:4.1f}%  {bar}")
            item.setForeground(QColor(lot_color(lot.id, self.dark_mode)))
            self.stats_list.addItem(item)

    def _refresh_history(self):
        self.history_list.clear()
        for row in reversed(self.history):
            self.history_list.addItem(row)

    def _update_pointer_lbl(self):
        lots = self._wheel_lots if hasattr(self, '_wheel_lots') else self.active_lots()
        lot = self._lot_at_pointer(lots, self.current_angle)
        p = PALETTE["dark" if self.dark_mode else "light"]
        if lot:
            self.pointer_lbl.setText(f"▲ {lot.name}  ({lot.points:g} pts)")
        else:
            self.pointer_lbl.setText("▲ —")

    def _on_slider(self, val):
        secs = val / 10
        self.spin_duration_ms = int(secs * 1000)
        self.time_val_lbl.setText(f"{secs:.1f} сек")

    def _set_result(self, text, success=False, warning=False, muted=False):
        p = PALETTE["dark" if self.dark_mode else "light"]
        color = p["success"] if success else (p["warning"] if warning else (p["muted"] if muted else p["text"]))
        self.result_lbl.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: 700; background: transparent;")
        self.result_lbl.setText(text)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _add_lot(self):
        name = self.name_input.text().strip()
        pts_raw = self.pts_input.text().strip().replace(",", ".")
        if not name:
            self.name_input.setFocus(); return
        if any(l.name.lower() == name.lower() for l in self.lots):
            self._set_result(f"«{name}» уже существует", warning=True); return
        try:
            points = float(pts_raw)
            if points <= 0: raise ValueError
        except ValueError:
            self._set_result("Введите корректные баллы", warning=True); return
        self.lots.append(Lot(self.next_lot_id, name, points))
        self.next_lot_id += 1
        self.name_input.clear(); self.pts_input.clear(); self.name_input.setFocus()
        self._save_data(); self._refresh_all()

    def _remove_lot(self, lot_id):
        self.lots = [l for l in self.lots if l.id != lot_id]
        self._save_data(); self._refresh_all()

    def _edit_lot(self, lot_id):
        lot = next((l for l in self.lots if l.id == lot_id), None)
        if not lot: return
        dlg = EditDialog(lot, self.dark_mode, self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        name, pts_raw = dlg.values()
        if not name: return
        if any(l.name.lower() == name.lower() and l.id != lot_id for l in self.lots):
            self._set_result(f"«{name}» уже существует", warning=True); return
        try:
            points = float(pts_raw.replace(",", "."))
            if points <= 0: raise ValueError
        except ValueError:
            self._set_result("Некорректные баллы", warning=True); return
        lot.name = name; lot.points = points
        self._save_data(); self._refresh_all()

    def _reset_eliminated(self):
        for l in self.lots: l.eliminated = False
        self._set_result("Выбывшие восстановлены")
        self._save_data(); self._refresh_all()

    def _clear_history(self):
        self.history.clear(); self._save_data(); self._refresh_history()


# ── Entry ─────────────────────────────────────────────────────────────────────

def main():
    import sys
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = FortuneWheelApp()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()