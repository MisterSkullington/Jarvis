"""
main_window.py — Main Jarvis desktop application window.

Assembles the HUD panel (left) and chat panel (right) inside a custom
frameless window with a sci-fi title bar and status bar.
"""
from __future__ import annotations

import math
from typing import Dict

from PySide6.QtCore import QPoint, QSettings, QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from desktop_client.styles import (
    APP_QSS, BG, BG_HEX, BORDER_HEX, CYAN, CYAN_HEX, LABEL, LABEL_HEX,
    WHITE_HEX, c, font_label, font_title,
)
from desktop_client.hud_overlay import JarvisHUD
from desktop_client.chat_widget import ChatWidget

_SETTINGS_KEY = "JarvisMainWindow"
_TITLE_BAR_H = 38
_STATUS_BAR_H = 26


# ---------------------------------------------------------------------------
# Custom title bar — draggable, sci-fi styled
# ---------------------------------------------------------------------------

class _TitleBar(QWidget):
    """Custom-painted title bar with drag, minimize, maximize, close."""

    close_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_TITLE_BAR_H)
        self._drag_origin: QPoint | None = None
        self._btn_hovered: str | None = None
        self.setMouseTracking(True)

    # ── Hit-test helpers ───────────────────────────────────────────────

    def _btn_rects(self):
        """Return (close, max, min) rects as (x, y, w, h) tuples."""
        w = self.width()
        bw, bh = 36, _TITLE_BAR_H
        return {
            "close":    (w - bw, 0, bw, bh),
            "maximize": (w - bw * 2, 0, bw, bh),
            "minimize": (w - bw * 3, 0, bw, bh),
        }

    def _hit_btn(self, x: int, y: int) -> str | None:
        for name, (bx, by, bw, bh) in self._btn_rects().items():
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return name
        return None

    # ── Paint ──────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, QColor(0, 8, 20, 245))

        # Bottom border
        p.setPen(QPen(QColor(0, 180, 255, 40), 1))
        p.drawLine(0, h - 1, w, h - 1)

        # Title text
        f = font_title()
        f.setPointSize(9)
        p.setFont(f)
        p.setPen(QPen(CYAN))
        title = "J.A.R.V.I.S"
        fm = QFontMetrics(f)
        p.drawText(14, (h + fm.ascent()) // 2 - 2, title)

        # Window control buttons
        btn_font = QFont("Courier New", 11)
        p.setFont(btn_font)
        for name, (bx, _, bw, bh) in self._btn_rects().items():
            hovered = self._btn_hovered == name
            if name == "close":
                col = QColor(255, 60, 60) if hovered else QColor(200, 235, 255, 120)
                symbol = "\u00d7"  # multiplication sign (x)
            elif name == "maximize":
                col = CYAN if hovered else QColor(200, 235, 255, 120)
                symbol = "\u25a1"  # square
            else:  # minimize
                col = CYAN if hovered else QColor(200, 235, 255, 120)
                symbol = "\u2013"  # en-dash
            p.setPen(QPen(col))
            fm2 = QFontMetrics(btn_font)
            tx = bx + (bw - fm2.horizontalAdvance(symbol)) // 2
            ty = (bh + fm2.ascent()) // 2 - 2
            p.drawText(tx, ty, symbol)

        p.end()

    # ── Mouse events ───────────────────────────────────────────────────

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        btn = self._hit_btn(int(ev.position().x()), int(ev.position().y()))
        if btn:
            if btn == "close":
                self.close_requested.emit()
            elif btn == "maximize":
                self.maximize_requested.emit()
            elif btn == "minimize":
                self.minimize_requested.emit()
        else:
            self._drag_origin = ev.globalPosition().toPoint() - self.window().frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        # Button hover tracking
        btn = self._hit_btn(int(ev.position().x()), int(ev.position().y()))
        if btn != self._btn_hovered:
            self._btn_hovered = btn
            self.update()

        # Window drag
        if self._drag_origin is not None and ev.buttons() & Qt.LeftButton:
            self.window().move(ev.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, _):
        self._drag_origin = None

    def mouseDoubleClickEvent(self, ev):
        if not self._hit_btn(int(ev.position().x()), int(ev.position().y())):
            self.maximize_requested.emit()

    def leaveEvent(self, _):
        if self._btn_hovered:
            self._btn_hovered = None
            self.update()


# ---------------------------------------------------------------------------
# Status bar
# ---------------------------------------------------------------------------

class _StatusBar(QWidget):
    """Bottom status bar showing service count, memory, and version."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_STATUS_BAR_H)
        self._service_count = 0
        self._total_services = 0
        self._memory_status = "disabled"

    def set_service_info(self, online: int, total: int) -> None:
        self._service_count = online
        self._total_services = total
        self.update()

    def set_memory_status(self, status: str) -> None:
        self._memory_status = status
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, QColor(0, 8, 20, 245))

        # Top border
        p.setPen(QPen(QColor(0, 180, 255, 40), 1))
        p.drawLine(0, 0, w, 0)

        f = font_label()
        p.setFont(f)
        fm = QFontMetrics(f)

        # Left: service count
        dot_col = CYAN if self._service_count > 0 else QColor(255, 60, 60)
        p.setPen(QPen(dot_col))
        svc_text = f"\u25cf {self._service_count}/{self._total_services} services online"
        p.drawText(14, (h + fm.ascent()) // 2 - 2, svc_text)

        # Centre: memory status
        p.setPen(QPen(LABEL))
        mem_text = f"Memory: {self._memory_status}"
        p.drawText((w - fm.horizontalAdvance(mem_text)) // 2, (h + fm.ascent()) // 2 - 2, mem_text)

        # Right: version
        p.setPen(QPen(LABEL))
        ver = "v0.1.0"
        p.drawText(w - fm.horizontalAdvance(ver) - 14, (h + fm.ascent()) // 2 - 2, ver)

        p.end()


# ---------------------------------------------------------------------------
# Holographic separator between HUD and chat
# ---------------------------------------------------------------------------

class _HoloSeparator(QWidget):
    """2 px vertical separator with a bell-curve cyan glow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(2)

    def paintEvent(self, _):
        p = QPainter(self)
        h = self.height()
        for y in range(h):
            t = y / max(h, 1)
            alpha = int(60 * math.sin(t * math.pi))
            p.setPen(QPen(QColor(0, 212, 255, alpha), 2))
            p.drawPoint(0, y)
        p.end()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class JarvisMainWindow(QWidget):
    """
    Frameless main window: custom title bar + HUD panel (left) + chat (right)
    + status bar.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MainWindow")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet(APP_QSS)
        self.setMinimumSize(960, 640)

        self._service_statuses: Dict[str, bool] = {}

        self._build_ui()
        self._restore_geometry()

    @property
    def hud_panel(self) -> JarvisHUD:
        return self._hud

    @property
    def chat_panel(self) -> ChatWidget:
        return self._chat

    @property
    def status_bar(self) -> _StatusBar:
        return self._status_bar

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Title bar ────────────────────────────────────────────────────
        self._title_bar = _TitleBar(self)
        self._title_bar.close_requested.connect(self.close)
        self._title_bar.minimize_requested.connect(self.showMinimized)
        self._title_bar.maximize_requested.connect(self._toggle_maximize)
        root.addWidget(self._title_bar)

        # ── Body: HUD (left) + Chat (right) ──────────────────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._hud = JarvisHUD(self)
        body.addWidget(self._hud)

        # Holographic separator
        sep = _HoloSeparator()
        body.addWidget(sep)

        self._chat = ChatWidget(parent=self)
        body.addWidget(self._chat, 1)  # stretch factor

        root.addLayout(body, 1)

        # ── Status bar ───────────────────────────────────────────────────
        self._status_bar = _StatusBar(self)
        root.addWidget(self._status_bar)

    # ── Public API ─────────────────────────────────────────────────────

    @Slot(dict)
    def update_service_status(self, statuses: Dict[str, bool]) -> None:
        """Update HUD dots and status bar service count."""
        self._service_statuses.update(statuses)
        self._hud.set_service_status(statuses)

        online = sum(1 for v in self._service_statuses.values() if v)
        total = len(self._service_statuses)
        self._status_bar.set_service_info(online, total)

    # ── Geometry persistence ───────────────────────────────────────────

    def _restore_geometry(self) -> None:
        s = QSettings("Jarvis", "DesktopApp")
        geo = s.value(f"{_SETTINGS_KEY}/geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1200, 760)
            # Centre on screen
            screen = QApplication.primaryScreen()
            if screen:
                sg = screen.availableGeometry()
                self.move(
                    (sg.width() - self.width()) // 2,
                    (sg.height() - self.height()) // 2,
                )

    def _save_geometry(self) -> None:
        s = QSettings("Jarvis", "DesktopApp")
        s.setValue(f"{_SETTINGS_KEY}/geometry", self.saveGeometry())

    def closeEvent(self, ev):
        self._save_geometry()
        super().closeEvent(ev)

    # ── Window control helpers ─────────────────────────────────────────

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ── Paint: outer border ────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Fill background
        p.fillRect(0, 0, w, h, BG)

        # Outer border
        p.setPen(QPen(QColor(0, 180, 255, 50), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(0, 0, w - 1, h - 1)

        p.end()
