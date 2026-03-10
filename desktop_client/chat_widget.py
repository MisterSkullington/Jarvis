"""
chat_widget.py — Holographic chat panel with scrollable history, text input,
and send button, styled to match the JARVIS HUD aesthetic.
"""
from __future__ import annotations

import math
import time
from typing import Optional

import httpx

from PySide6.QtCore import QPointF, QTimer, Qt, Signal, QThread, QObject
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from desktop_client.styles import (
    CYAN, CYAN_HEX, LABEL, LABEL_HEX, WHITE_HEX, BG_HEX, BG_INPUT,
    BORDER_HEX, CYAN_120,
    c, hex_poly, font_chat, font_chat_small, font_label, font_title,
)

# ---------------------------------------------------------------------------
# Colour shorthand (local, matching HUD)
# ---------------------------------------------------------------------------

_BG      = QColor(0,   8,  20, 238)
_SCAN    = QColor(0,   0,   0,  18)
_RULE    = QColor(0, 180, 255,  38)


# ---------------------------------------------------------------------------
# Worker thread for NLU HTTP calls
# ---------------------------------------------------------------------------

class _NluWorker(QObject):
    """Calls NLU /chat in a background thread so the GUI stays responsive."""
    finished = Signal(str)   # response text
    error    = Signal(str)   # error message

    def __init__(self, url: str, text: str, session_id: str):
        super().__init__()
        self._url = url
        self._text = text
        self._sid = session_id

    def run(self) -> None:
        try:
            r = httpx.post(
                self._url,
                json={"text": self._text, "session_id": self._sid},
                timeout=60,
            )
            r.raise_for_status()
            data = r.json()
            self.finished.emit(data.get("response", "(no response)"))
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Single chat message widget
# ---------------------------------------------------------------------------

class _MessageBubble(QFrame):
    """A single message in the chat history — holographic styling."""

    def __init__(self, role: str, text: str, parent=None):
        super().__init__(parent)

        is_user = role.lower() in ("you", "user")
        obj_name = "MessageBubbleUser" if is_user else "MessageBubbleJarvis"
        self.setObjectName(obj_name)

        role_label = "YOU" if is_user else "JARVIS"
        role_colour = LABEL_HEX if is_user else CYAN_HEX
        text_colour = WHITE_HEX if is_user else CYAN_HEX
        border_col = "#004488" if is_user else CYAN_HEX
        bg_alpha = 140 if is_user else 180
        ts = time.strftime("%H:%M")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(2)

        # Header row: timestamp + role
        header = QHBoxLayout()
        header.setSpacing(8)

        time_lbl = QLabel(ts)
        time_lbl.setObjectName("ChatTime")
        time_lbl.setStyleSheet(f"background: transparent; color: {LABEL_HEX};")
        header.addWidget(time_lbl)

        role_lbl = QLabel(role_label)
        role_lbl.setObjectName("ChatRole")
        role_lbl.setStyleSheet(f"background: transparent; color: {role_colour};")
        header.addWidget(role_lbl)
        header.addStretch()
        layout.addLayout(header)

        # Message text
        text_lbl = QLabel(text)
        text_lbl.setObjectName("ChatText")
        text_lbl.setStyleSheet(f"background: transparent; color: {text_colour};")
        text_lbl.setWordWrap(True)
        text_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(text_lbl)

        # Holographic bubble style
        self.setStyleSheet(f"""
            QFrame#{obj_name} {{
                background-color: rgba(0, 12, 30, {bg_alpha});
                border-left: 2px solid {border_col};
                border-bottom: 1px solid rgba(0, 180, 255, 25);
                margin: 2px 8px;
                border-radius: 2px;
            }}
        """)


# ---------------------------------------------------------------------------
# Chat widget (right panel) — holographic
# ---------------------------------------------------------------------------

class ChatWidget(QWidget):
    """Scrollable chat history with holographic background matching the HUD."""

    message_sent = Signal(str)       # emitted when user types and sends
    settings_requested = Signal()    # emitted when gear icon clicked

    # Header height reserved for custom painting
    _HEADER_H = 50

    def __init__(self, nlu_base_url: str = "http://127.0.0.1:8001", parent=None):
        super().__init__(parent)
        self._nlu_url = f"{nlu_base_url}/chat"
        self._session_id = f"desktop-{int(time.time())}"
        self._worker: Optional[_NluWorker] = None
        self._thread: Optional[QThread] = None

        # Animation tick for subtle hex-grid shimmer
        self._tick_t: float = 0.0

        self._build_ui()

        # 15 fps shimmer timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(66)

    def _on_tick(self) -> None:
        self._tick_t += 0.04
        self.update()

    # ── Build UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, self._HEADER_H, 0, 0)
        root.setSpacing(0)

        # ── Chat history scroll area ──────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll.viewport().setStyleSheet("background: transparent;")

        self._history_container = QWidget()
        self._history_container.setStyleSheet("background-color: transparent;")
        self._history_layout = QVBoxLayout(self._history_container)
        self._history_layout.setContentsMargins(0, 8, 0, 8)
        self._history_layout.setSpacing(0)
        self._history_layout.addStretch()  # pushes messages to bottom

        self._scroll.setWidget(self._history_container)
        root.addWidget(self._scroll, 1)

        # ── Rule line above input ─────────────────────────────────────────
        input_sep = QWidget()
        input_sep.setFixedHeight(1)
        input_sep.setStyleSheet("background-color: rgba(0, 180, 255, 38);")
        root.addWidget(input_sep)

        # ── Input row ─────────────────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setContentsMargins(8, 8, 8, 8)
        input_row.setSpacing(6)

        self._input = QLineEdit()
        self._input.setObjectName("ChatInput")
        self._input.setPlaceholderText("Type a message...")
        self._input.setFont(font_chat())
        self._input.returnPressed.connect(self._on_send)
        input_row.addWidget(self._input, 1)

        self._send_btn = QPushButton("SEND")
        self._send_btn.setObjectName("SendBtn")
        self._send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self._send_btn)

        self._gear_btn = QPushButton("\u2699")
        self._gear_btn.setObjectName("GearBtn")
        self._gear_btn.setToolTip("Settings")
        self._gear_btn.clicked.connect(self.settings_requested.emit)
        input_row.addWidget(self._gear_btn)

        root.addLayout(input_row)

    # ── Custom paint — holographic background ─────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        w, h = float(self.width()), float(self.height())

        # Background fill
        p.fillRect(0, 0, int(w), int(h), _BG)

        # Hex grid (lighter/sparser than HUD)
        self._draw_hex_grid(p, w, h)

        # CRT scanlines
        self._draw_scanlines(p, w, h)

        # Corner brackets
        self._draw_corners(p, w, h)

        # "COMMUNICATIONS LOG" header
        self._draw_header(p, w)

        p.end()

    def _draw_hex_grid(self, p: QPainter, w: float, h: float) -> None:
        size = 34.0
        cols = int(w / (size * 1.5)) + 3
        rows = int(h / (size * math.sqrt(3))) + 3
        sqrt3 = math.sqrt(3)
        t = self._tick_t
        p.save()
        p.setBrush(Qt.NoBrush)
        for row in range(-1, rows):
            for col in range(-1, cols):
                cx = col * size * 1.5
                cy = row * size * sqrt3 + (col % 2) * size * sqrt3 / 2
                shimmer = 0.5 + 0.5 * math.sin(t + col * 0.4 + row * 0.6)
                alpha = int(4 + shimmer * 8)
                p.setPen(QPen(QColor(0, 190, 255, alpha), 0.5))
                p.drawPolygon(hex_poly(cx, cy, size * 0.86, 30))
        p.restore()

    def _draw_scanlines(self, p: QPainter, w: float, h: float) -> None:
        p.save()
        p.setPen(QPen(_SCAN, 1))
        y = 0
        while y < h:
            p.drawLine(0, y, int(w), y)
            y += 3
        p.restore()

    def _draw_corners(self, p: QPainter, w: float, h: float) -> None:
        arm, pad = 22.0, 2.0
        p.save()
        p.setPen(QPen(CYAN, 1.4, Qt.SolidLine, Qt.SquareCap))
        brackets = [
            [(pad, pad + arm), (pad, pad), (pad + arm, pad)],
            [(w - pad - arm, pad), (w - pad, pad), (w - pad, pad + arm)],
            [(pad, h - pad - arm), (pad, h - pad), (pad + arm, h - pad)],
            [(w - pad - arm, h - pad), (w - pad, h - pad), (w - pad, h - pad - arm)],
        ]
        for pts in brackets:
            path = QPainterPath()
            path.moveTo(pts[0][0], pts[0][1])
            path.lineTo(pts[1][0], pts[1][1])
            path.lineTo(pts[2][0], pts[2][1])
            p.drawPath(path)
        # Corner diamonds
        p.setPen(Qt.NoPen)
        p.setBrush(c(CYAN, 80))
        diam = 3.0
        for cx, cy in [(pad, pad), (w - pad, pad), (pad, h - pad), (w - pad, h - pad)]:
            diamond = QPolygonF([
                QPointF(cx, cy - diam),
                QPointF(cx + diam, cy),
                QPointF(cx, cy + diam),
                QPointF(cx - diam, cy),
            ])
            p.drawPolygon(diamond)
        p.restore()

    def _draw_header(self, p: QPainter, w: float) -> None:
        p.save()
        # Title
        f = font_title()
        f.setPointSize(9)
        p.setFont(f)
        p.setPen(QPen(CYAN))
        title = "COMMUNICATIONS LOG"
        fm = QFontMetrics(f)
        p.drawText(int((w - fm.horizontalAdvance(title)) / 2), 30, title)
        # Subtitle
        fl = font_label()
        p.setFont(fl)
        p.setPen(QPen(LABEL))
        sub = "ENCRYPTED CHANNEL  \u00b7  ACTIVE"
        fm2 = QFontMetrics(fl)
        p.drawText(int((w - fm2.horizontalAdvance(sub)) / 2), 44, sub)
        # Rule line
        p.setPen(QPen(_RULE, 1))
        p.drawLine(16, self._HEADER_H - 2, int(w) - 16, self._HEADER_H - 2)
        # Tick marks on rule
        for xpos in [16, int(w) - 16]:
            p.drawLine(xpos, self._HEADER_H - 5, xpos, self._HEADER_H + 1)
        p.restore()

    # ── Public API ────────────────────────────────────────────────────────

    def add_message(self, role: str, text: str) -> None:
        """Add a message to the chat history. Called for both typed and voice messages."""
        bubble = _MessageBubble(role, text)
        # Insert before the stretch at the end
        count = self._history_layout.count()
        self._history_layout.insertWidget(count - 1, bubble)
        # Auto-scroll to bottom
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum() + 100
        )

    def set_nlu_url(self, base_url: str) -> None:
        self._nlu_url = f"{base_url}/chat"

    # ── Internal ──────────────────────────────────────────────────────────

    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.add_message("user", text)
        self.message_sent.emit(text)
        self._call_nlu(text)

    def _call_nlu(self, text: str) -> None:
        """Fire NLU /chat in a background thread."""
        if self._thread is not None:
            try:
                if self._thread.isRunning():
                    return  # skip if already in-flight
            except RuntimeError:
                # C++ object already deleted — safe to replace
                pass
            self._thread = None
            self._worker = None

        self._thread = QThread()
        self._worker = _NluWorker(self._nlu_url, text, self._session_id)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_nlu_response)
        self._worker.error.connect(self._on_nlu_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        # Clear references when done so next call's guard works correctly
        self._thread.finished.connect(self._cleanup_thread)

        self._send_btn.setEnabled(False)
        self._thread.start()

    def _cleanup_thread(self) -> None:
        """Null out thread/worker references after the thread finishes."""
        self._thread = None
        self._worker = None

    def _on_nlu_response(self, response: str) -> None:
        self.add_message("jarvis", response)
        self._send_btn.setEnabled(True)

    def _on_nlu_error(self, err: str) -> None:
        self.add_message("jarvis", f"[Error: {err}]")
        self._send_btn.setEnabled(True)
