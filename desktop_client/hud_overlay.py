#!/usr/bin/env python3
"""
hud_overlay.py — JARVIS HUD Overlay
====================================
Iron Man-style holographic HUD for the Jarvis voice assistant.

Features
--------
- Animated arc-reactor with three concentric rotating rings
- Hexagonal grid background with shimmer effect
- CRT scanline overlay
- Waveform voice-input visualiser
- Transcript display (YOU / JARVIS)
- Service-status matrix with glow indicators
- Holographic hexagonal LISTEN button
- DND toggle with sliding pill
- Corner-bracket HUD decorations
- Boot-in fade animation

Public API
----------
    hud.set_transcript(you: str, response: str)
    hud.set_listening(active: bool)
    hud.set_service_status({"NLU": True, "STT": False, ...})
    hud.set_dnd(enabled: bool)

Signals
-------
    hud.listen_requested   – user clicked LISTEN
    hud.dnd_toggled(bool)  – user toggled DND
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation,
    QRectF, QSettings, Qt, QTimer, Signal, Slot,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath,
    QPen, QPolygonF, QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

_BG          = QColor(0,   8,  20, 238)
_CYAN        = QColor(0, 212, 255)
_CYAN_60     = QColor(0, 212, 255,  60)
_CYAN_120    = QColor(0, 212, 255, 120)
_BLUE        = QColor(0, 136, 255)
_BLUE_40     = QColor(0, 136, 255,  40)
_GRID        = QColor(0, 180, 255,  16)
_GRID_HI     = QColor(0, 200, 255,  35)
_WHITE       = QColor(200, 235, 255)
_WHITE_80    = QColor(200, 235, 255,  80)
_RED         = QColor(255,  60,  60)
_ORANGE      = QColor(255, 160,   0)
_SCAN        = QColor(  0,   0,   0,  28)
_RULE        = QColor(  0, 180, 255,  38)
_LABEL       = QColor(  0, 180, 255, 120)


def _c(base: QColor, alpha: int) -> QColor:
    c = QColor(base)
    c.setAlpha(alpha)
    return c


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _hex_poly(cx: float, cy: float, r: float, angle_offset: float = 0.0) -> QPolygonF:
    pts = []
    for i in range(6):
        a = math.radians(60 * i + angle_offset)
        pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
    return QPolygonF(pts)


def _pt_in_hex(px: float, py: float, cx: float, cy: float, r: float) -> bool:
    dx, dy = abs(px - cx), abs(py - cy)
    return (
        dx <= r * math.sqrt(3) / 2
        and dy <= r
        and dx * 0.5 + dy * math.sqrt(3) / 4 <= r * math.sqrt(3) / 2
    )


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class JarvisHUD(QWidget):
    """Frameless, translucent JARVIS HUD overlay."""

    listen_requested = Signal()
    dnd_toggled      = Signal(bool)

    # ── Animatable Qt Properties ──────────────────────────────────────────

    def _get_ring(self):  return self._ring_angle
    def _set_ring(self, v): self._ring_angle = v; self.update()
    ring_angle = Property(float, _get_ring, _set_ring)

    def _get_boot(self):  return self._boot_alpha
    def _set_boot(self, v): self._boot_alpha = v; self.update()
    boot_alpha = Property(float, _get_boot, _set_boot)

    # ── Init ──────────────────────────────────────────────────────────────

    _SETTINGS_KEY = "JarvisHUD"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._embedded = parent is not None

        if not self._embedded:
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool,
            )
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_NoSystemBackground)
            self.setMinimumSize(400, 520)
            self.resize(520, 680)
        else:
            self.setFixedWidth(520)
            self.setMinimumHeight(520)

        # ── State ─────────────────────────────────────────────────────────
        self._ring_angle:       float = 0.0
        self._boot_alpha:       float = 0.0
        self._tick_t:           float = 0.0
        self._listening:        bool  = False
        self._dnd:              bool  = False
        self._transcript_you:   str   = ""
        self._transcript_jarvis: str  = ""
        self._services: Dict[str, bool] = {
            "NLU": True, "ORCH": True, "STT": True, "TTS": True, "SCHED": True,
        }
        self._waveform: List[float] = [0.0] * 26
        self._drag_origin: Optional[QPointF] = None

        # Restore window position/size (standalone only)
        if not self._embedded:
            self._restore_geometry()

        # ── Fonts ─────────────────────────────────────────────────────────
        self._f_title = QFont("Courier New", 11, QFont.Bold)
        self._f_title.setLetterSpacing(QFont.AbsoluteSpacing, 5)
        self._f_mono  = QFont("Courier New", 9)
        self._f_label = QFont("Courier New", 7)
        self._f_btn   = QFont("Courier New", 8, QFont.Bold)
        self._f_btn.setLetterSpacing(QFont.AbsoluteSpacing, 2)

        # ── Ring spin animation (continuous) ──────────────────────────────
        self._ring_anim = QPropertyAnimation(self, b"ring_angle")
        self._ring_anim.setStartValue(0.0)
        self._ring_anim.setEndValue(360.0)
        self._ring_anim.setDuration(9000)
        self._ring_anim.setLoopCount(-1)
        self._ring_anim.start()

        # ── Boot-in fade ──────────────────────────────────────────────────
        self._boot_anim = QPropertyAnimation(self, b"boot_alpha")
        self._boot_anim.setStartValue(0.0)
        self._boot_anim.setEndValue(1.0)
        self._boot_anim.setDuration(900)
        self._boot_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._boot_anim.start()

        # ── Render tick (30 fps) ──────────────────────────────────────────
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(33)

    # ── Public slots ──────────────────────────────────────────────────────

    @Slot(str, str)
    def set_transcript(self, you: str, response: str) -> None:
        self._transcript_you    = you
        self._transcript_jarvis = response
        self.update()

    @Slot(bool)
    def set_listening(self, active: bool) -> None:
        self._listening = active

    @Slot(dict)
    def set_service_status(self, statuses: Dict[str, bool]) -> None:
        self._services.update(statuses)
        self.update()

    @Slot(bool)
    def set_dnd(self, enabled: bool) -> None:
        self._dnd = enabled
        self.update()

    # ── Tick ──────────────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        self._tick_t += 0.045
        n = len(self._waveform)
        if self._listening:
            for i in range(n):
                self._waveform[i] += (random.uniform(0.1, 1.0) - self._waveform[i]) * 0.45
        else:
            for i in range(n):
                self._waveform[i] *= 0.82
        self.update()

    # ── Mouse ─────────────────────────────────────────────────────────────

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        px, py = ev.position().x(), ev.position().y()
        w, h   = self.width(), self.height()

        # Close × (standalone only)
        if not self._embedded and px > w - 34 and py < 34:
            self.hide()
            return

        # LISTEN hex button
        lx, ly = w * 0.28, h * 0.875
        if _pt_in_hex(px, py, lx, ly, 46):
            self.listen_requested.emit()
            return

        # DND toggle track
        dx, dy = w * 0.72, h * 0.875
        if abs(px - dx) < 32 and abs(py - dy) < 14:
            self._dnd = not self._dnd
            self.dnd_toggled.emit(self._dnd)
            self.update()
            return

        # Drag (standalone only)
        if not self._embedded:
            self._drag_origin = ev.globalPosition() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if not self._embedded and self._drag_origin and ev.buttons() & Qt.LeftButton:
            self.move((ev.globalPosition() - self._drag_origin).toPoint())

    def mouseReleaseEvent(self, ev):
        if self._drag_origin is not None:
            self._drag_origin = None
            if not self._embedded:
                self._save_geometry()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if not self._embedded:
            self._save_geometry()

    def closeEvent(self, ev):
        if not self._embedded:
            self._save_geometry()
        super().closeEvent(ev)

    # ── Geometry persistence ──────────────────────────────────────────────

    def _save_geometry(self) -> None:
        s = QSettings("Jarvis", self._SETTINGS_KEY)
        s.setValue("geometry", self.saveGeometry())

    def _restore_geometry(self) -> None:
        s = QSettings("Jarvis", self._SETTINGS_KEY)
        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    # ── Paint ─────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.setOpacity(self._boot_alpha)

        w, h = float(self.width()), float(self.height())

        self._draw_bg(p, w, h)
        self._draw_hex_grid(p, w, h)
        self._draw_scanlines(p, w, h)
        self._draw_border(p, w, h)
        self._draw_corners(p, w, h)
        self._draw_title(p, w, h)
        self._draw_arc_reactor(p, w, h)
        self._draw_waveform(p, w, h)
        self._draw_transcript(p, w, h)
        self._draw_services(p, w, h)
        self._draw_listen_btn(p, w, h)
        self._draw_dnd(p, w, h)
        if not self._embedded:
            self._draw_close(p, w, h)

        p.end()

    # ── Draw layers ───────────────────────────────────────────────────────

    def _draw_bg(self, p: QPainter, w: float, h: float) -> None:
        p.setPen(Qt.NoPen)
        p.fillRect(0, 0, int(w), int(h), _BG)
        # Soft radial vignette
        rg = QRadialGradient(w / 2, h / 2, max(w, h) * 0.72)
        rg.setColorAt(0, QColor(0, 55, 110, 22))
        rg.setColorAt(1, QColor(0,  0,   0, 55))
        p.fillRect(0, 0, int(w), int(h), rg)

    def _draw_hex_grid(self, p: QPainter, w: float, h: float) -> None:
        size = 30.0
        cols = int(w / (size * 1.5)) + 3
        rows = int(h / (size * math.sqrt(3))) + 3
        p.save()
        for row in range(-1, rows):
            for col in range(-1, cols):
                cx = col * size * 1.5
                cy = row * size * math.sqrt(3) + (col % 2) * size * math.sqrt(3) / 2
                shimmer = 0.5 + 0.5 * math.sin(self._tick_t + col * 0.38 + row * 0.55)
                alpha = int(6 + shimmer * 14)
                p.setPen(QPen(QColor(0, 190, 255, alpha), 0.7))
                p.setBrush(Qt.NoBrush)
                p.drawPolygon(_hex_poly(cx, cy, size * 0.86, 30))
        p.restore()

    def _draw_scanlines(self, p: QPainter, w: float, h: float) -> None:
        p.save()
        p.setPen(QPen(_SCAN, 1))
        y = 0
        while y < h:
            p.drawLine(0, y, int(w), y)
            y += 3
        p.restore()

    def _draw_border(self, p: QPainter, w: float, h: float) -> None:
        p.save()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 180, 255, 38), 1))
        p.drawRect(QRectF(1, 1, w - 2, h - 2))
        p.setPen(QPen(QColor(0, 180, 255, 16), 1))
        p.drawRect(QRectF(6, 6, w - 12, h - 12))
        p.restore()

    def _draw_corners(self, p: QPainter, w: float, h: float) -> None:
        arm, pad = 26.0, 2.0
        p.save()
        p.setPen(QPen(_CYAN, 1.8, Qt.SolidLine, Qt.SquareCap))
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
        # Small corner diamonds
        p.setPen(Qt.NoPen)
        p.setBrush(_c(_CYAN, 100))
        diam = 3.5
        for corner_x, corner_y in [(pad, pad), (w - pad, pad), (pad, h - pad), (w - pad, h - pad)]:
            pts2 = QPolygonF([
                QPointF(corner_x,        corner_y - diam),
                QPointF(corner_x + diam, corner_y),
                QPointF(corner_x,        corner_y + diam),
                QPointF(corner_x - diam, corner_y),
            ])
            p.drawPolygon(pts2)
        p.restore()

    def _draw_title(self, p: QPainter, w: float, h: float) -> None:
        p.save()
        # Title
        p.setFont(self._f_title)
        p.setPen(QPen(_CYAN))
        title = "J . A . R . V . I . S"
        fm = QFontMetrics(self._f_title)
        p.drawText(int((w - fm.horizontalAdvance(title)) / 2), 36, title)
        # Subtitle
        p.setFont(self._f_label)
        p.setPen(QPen(_LABEL))
        sub = "JUST A RATHER VERY INTELLIGENT SYSTEM  ·  ONLINE"
        fm2 = QFontMetrics(self._f_label)
        p.drawText(int((w - fm2.horizontalAdvance(sub)) / 2), 53, sub)
        # Rule
        p.setPen(QPen(_RULE, 1))
        p.drawLine(20, 60, int(w) - 20, 60)
        # Side tick marks on rule
        for xpos in [20, int(w) - 20]:
            p.drawLine(xpos, 57, xpos, 63)
        p.restore()

    def _draw_arc_reactor(self, p: QPainter, w: float, h: float) -> None:
        cx, cy = w / 2, h * 0.312
        t = self._tick_t
        p.save()

        # ── Outermost halo glow ───────────────────────────────────────────
        for r_halo, alpha_halo, width_halo in [(96, 8, 22), (96, 20, 6), (96, 55, 1.5)]:
            p.setPen(QPen(QColor(0, 212, 255, alpha_halo), width_halo))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r_halo, r_halo)

        # ── Ring 1: slow clockwise spin with dashed pattern ───────────────
        p.save()
        p.translate(cx, cy)
        p.rotate(self._ring_angle)
        pen1 = QPen(_CYAN, 1.5, Qt.CustomDashLine)
        pen1.setDashPattern([7, 3, 1, 3])
        p.setPen(pen1)
        p.drawEllipse(QPointF(0, 0), 88, 88)
        # Tick marks
        p.setPen(QPen(_CYAN, 2))
        for i in range(24):
            a = math.radians(i * 15)
            r_in = 82 if i % 6 == 0 else (84 if i % 3 == 0 else 85.5)
            p.drawLine(
                QPointF(r_in * math.cos(a), r_in * math.sin(a)),
                QPointF(88  * math.cos(a), 88  * math.sin(a)),
            )
        p.restore()

        # ── Ring 2: counter-spin, dotted ──────────────────────────────────
        p.save()
        p.translate(cx, cy)
        p.rotate(-self._ring_angle * 1.65)
        pen2 = QPen(QColor(0, 168, 255, 130), 1.1, Qt.DotLine)
        pen2.setDashPattern([2, 4])
        p.setPen(pen2)
        p.drawEllipse(QPointF(0, 0), 72, 72)
        p.restore()

        # ── Ring 3: slow counter, 6 arc segments ─────────────────────────
        p.save()
        p.translate(cx, cy)
        p.rotate(-self._ring_angle * 0.45)
        arc_pen = QPen(QColor(0, 130, 255, 200), 2.8, Qt.SolidLine, Qt.FlatCap)
        p.setPen(arc_pen)
        p.setBrush(Qt.NoBrush)
        for i in range(6):
            p.drawArc(QRectF(-54, -54, 108, 108), int(i * 60 * 16 + 10 * 16), int(35 * 16))
        p.restore()

        # ── Pulsing core fill ─────────────────────────────────────────────
        pulse = 0.5 + 0.5 * math.sin(t * 1.9)
        rg = QRadialGradient(cx, cy, 44)
        rg.setColorAt(0,   QColor(0, 212, 255, int(170 * pulse + 50)))
        rg.setColorAt(0.5, QColor(0, 136, 255, int( 80 * pulse)))
        rg.setColorAt(1,   QColor(0,   0,   0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(rg)
        p.drawEllipse(QPointF(cx, cy), 44, 44)

        # ── Core disc ─────────────────────────────────────────────────────
        p.setPen(QPen(_CYAN, 1.5))
        p.setBrush(QBrush(QColor(0, 22, 55, 210)))
        p.drawEllipse(QPointF(cx, cy), 24, 24)

        # ── Inner hex ─────────────────────────────────────────────────────
        p.setPen(QPen(_c(_CYAN, 160), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(_hex_poly(cx, cy, 15, 30))

        # ── Centre dot ────────────────────────────────────────────────────
        p.setPen(Qt.NoPen)
        p.setBrush(_CYAN)
        p.drawEllipse(QPointF(cx, cy), 3, 3)

        # ── Status label below reactor ────────────────────────────────────
        p.setFont(self._f_label)
        status_col = _ORANGE if self._dnd else _CYAN
        status_text = "◌  DO NOT DISTURB" if self._dnd else "●  ACTIVE  //  NOMINAL"
        fm = QFontMetrics(self._f_label)
        p.setPen(QPen(status_col))
        p.drawText(int(cx - fm.horizontalAdvance(status_text) / 2), int(cy + 112), status_text)

        p.restore()

    def _draw_waveform(self, p: QPainter, w: float, h: float) -> None:
        n      = len(self._waveform)
        bar_w  = 6.5
        gap    = 2.8
        total  = n * (bar_w + gap) - gap
        x0     = (w - total) / 2
        y0     = h * 0.545
        alpha  = 200 if self._listening else 55

        p.save()

        # Label
        label = "▶  VOICE INPUT  ◀" if self._listening else "—  STANDBY  —"
        p.setFont(self._f_label)
        fm = QFontMetrics(self._f_label)
        lbl_col = _CYAN if self._listening else _LABEL
        p.setPen(QPen(lbl_col))
        p.drawText(int((w - fm.horizontalAdvance(label)) / 2), int(y0 - 12), label)

        # Bars
        for i, amp in enumerate(self._waveform):
            bar_h = max(2.5, amp * 38.0)
            x = x0 + i * (bar_w + gap)
            # Glow halo
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 212, 255, int(alpha * amp * 0.35)))
            p.drawRect(QRectF(x - 1.5, y0 - bar_h / 2 - 1.5, bar_w + 3, bar_h + 3))
            # Bar body
            bar_col = QColor(0, 212, 255, int(alpha * (0.25 + amp * 0.75)))
            p.setBrush(bar_col)
            p.drawRect(QRectF(x, y0 - bar_h / 2, bar_w, bar_h))

        # Baseline
        p.setPen(QPen(QColor(0, 180, 255, 36), 1))
        p.drawLine(QPointF(x0, y0), QPointF(x0 + total, y0))

        p.restore()

    def _draw_transcript(self, p: QPainter, w: float, h: float) -> None:
        x0, x1 = 26.0, w - 26.0
        y0 = h * 0.612
        avail_w = int(x1 - x0)

        p.save()
        # Top rule
        p.setPen(QPen(_RULE, 1))
        p.drawLine(QPointF(x0, y0 - 5), QPointF(x1, y0 - 5))

        fm_lbl = QFontMetrics(self._f_label)
        fm_mono = QFontMetrics(self._f_mono)
        line_h = fm_mono.height() + 2

        def _draw_block(label: str, text: str, y: float, lc: QColor, tc: QColor, max_lines: int = 3) -> float:
            """Draw label + word-wrapped text. Returns y after the block."""
            p.setFont(self._f_label)
            p.setPen(QPen(lc))
            p.drawText(int(x0), int(y), label)
            lw = fm_lbl.horizontalAdvance(label) + 5
            p.setFont(self._f_mono)
            p.setPen(QPen(tc))
            # Word-wrap text into lines
            words = text.split()
            lines: List[str] = []
            cur = ""
            text_w = int(avail_w - lw)
            for word in words:
                test = f"{cur} {word}".strip()
                if fm_mono.horizontalAdvance(test) > text_w and cur:
                    lines.append(cur)
                    cur = word
                else:
                    cur = test
            if cur:
                lines.append(cur)
            if not lines:
                lines = [text]
            # Limit lines and add ellipsis
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                lines[-1] = fm_mono.elidedText(lines[-1] + "…", Qt.ElideRight, text_w)
            # Draw first line beside label, subsequent lines indented
            for i, line in enumerate(lines):
                p.drawText(int(x0 + lw), int(y + i * line_h), line)
            return y + len(lines) * line_h

        y_after = _draw_block(
            "YOU:    ",
            self._transcript_you or "(awaiting input…)",
            y0 + 15,
            _LABEL,
            _WHITE if self._transcript_you else _WHITE_80,
        )
        _draw_block(
            "JARVIS: ",
            self._transcript_jarvis or "(no response yet)",
            y_after + 6,
            _CYAN,
            _CYAN if self._transcript_jarvis else _CYAN_120,
            max_lines=4,
        )

        # Bottom rule
        p.setPen(QPen(_RULE, 1))
        p.drawLine(QPointF(x0, y0 + 80), QPointF(x1, y0 + 80))
        p.restore()

    def _draw_services(self, p: QPainter, w: float, h: float) -> None:
        y_label = h * 0.76
        names   = list(self._services.keys())
        slot_w  = (w - 48) / len(names)

        p.save()
        p.setFont(self._f_label)
        p.setPen(QPen(_LABEL))
        p.drawText(26, int(y_label - 14), "SERVICE MATRIX")

        for i, name in enumerate(names):
            online = self._services[name]
            cx = 24 + slot_w * i + slot_w / 2
            cy = y_label + 6
            dot_col = _CYAN if online else _RED
            r_dot   = 5.5

            # Glow halo
            p.setPen(Qt.NoPen)
            p.setBrush(_c(dot_col, 38))
            p.drawEllipse(QPointF(cx, cy), r_dot + 4, r_dot + 4)

            # Dot
            p.setBrush(dot_col)
            p.setPen(QPen(dot_col.lighter(140), 0.8))
            p.drawEllipse(QPointF(cx, cy), r_dot, r_dot)

            # Name label
            fm = QFontMetrics(self._f_label)
            tw = fm.horizontalAdvance(name)
            lbl_col = _c(_CYAN, 130) if online else _RED
            p.setPen(QPen(lbl_col))
            p.drawText(int(cx - tw / 2), int(cy + 20), name)

        p.restore()

    def _draw_listen_btn(self, p: QPainter, w: float, h: float) -> None:
        cx, cy = w * 0.28, h * 0.875
        r_hex  = 46.0
        t      = self._tick_t

        p.save()

        # Outer pulse glow
        pulse = (0.5 + 0.5 * math.sin(t * 3.5)) if self._listening else 0.18
        p.setPen(Qt.NoPen)
        p.setBrush(_c(_CYAN, int(pulse * 52 + 8)))
        p.drawPolygon(_hex_poly(cx, cy, r_hex + 7, 0))

        # Hex fill
        p.setBrush(QBrush(QColor(0, 18, 46, 195)))
        p.setPen(QPen(_CYAN, 1.6))
        p.drawPolygon(_hex_poly(cx, cy, r_hex, 0))

        # Inner hex accent
        p.setPen(QPen(_c(_CYAN, 55), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(_hex_poly(cx, cy, r_hex * 0.62, 0))

        # Label
        p.setFont(self._f_btn)
        fm = QFontMetrics(self._f_btn)
        label = "◈  LISTEN"
        tw = fm.horizontalAdvance(label)
        p.setPen(QPen(_CYAN))
        p.drawText(int(cx - tw / 2), int(cy + fm.ascent() / 2 - 1), label)

        p.restore()

    def _draw_dnd(self, p: QPainter, w: float, h: float) -> None:
        cx, cy = w * 0.72, h * 0.875
        track_w, track_h = 58.0, 20.0
        tx = cx - track_w / 2
        ty = cy - track_h / 2

        p.save()

        # Section label
        p.setFont(self._f_label)
        fm = QFontMetrics(self._f_label)
        lbl = "DO NOT DISTURB"
        p.setPen(QPen(_LABEL))
        p.drawText(int(cx - fm.horizontalAdvance(lbl) / 2), int(ty - 8), lbl)

        # Track
        track_fill = _c(_ORANGE, 55) if self._dnd else QColor(0, 50, 90, 100)
        p.setBrush(track_fill)
        border_col = _ORANGE if self._dnd else _c(_CYAN, 80)
        p.setPen(QPen(border_col, 1.2))
        p.drawRoundedRect(QRectF(tx, ty, track_w, track_h), track_h / 2, track_h / 2)

        # Thumb
        margin  = 2.5
        thumb_d = track_h - margin * 2
        thumb_x = tx + track_w - thumb_d - margin if self._dnd else tx + margin
        thumb_col = _ORANGE if self._dnd else _c(_CYAN, 180)
        p.setPen(Qt.NoPen)
        p.setBrush(thumb_col)
        p.drawEllipse(QRectF(thumb_x, ty + margin, thumb_d, thumb_d))

        # State text
        state = "ON" if self._dnd else "OFF"
        state_col = _ORANGE if self._dnd else _c(_CYAN, 100)
        p.setPen(QPen(state_col))
        p.drawText(int(cx - fm.horizontalAdvance(state) / 2), int(ty + track_h + 14), state)

        p.restore()

    def _draw_close(self, p: QPainter, w: float, h: float) -> None:
        p.save()
        p.setPen(QPen(_c(_CYAN, 80), 1.5))
        cx, cy, arm = w - 20, 20.0, 7.0
        p.drawLine(QPointF(cx - arm, cy - arm), QPointF(cx + arm, cy + arm))
        p.drawLine(QPointF(cx + arm, cy - arm), QPointF(cx - arm, cy + arm))
        p.restore()


# ---------------------------------------------------------------------------
# Standalone demo
# ---------------------------------------------------------------------------

def main() -> None:  # pragma: no cover
    app = QApplication(sys.argv)
    hud = JarvisHUD()
    hud.set_transcript(
        "what's the weather in London",
        "Currently 17°C, Sir. Partly cloudy with a 20% chance of rain this afternoon.",
    )
    hud.set_service_status({"NLU": True, "ORCH": True, "STT": True, "TTS": True, "SCHED": False})
    hud.show()
    QTimer.singleShot(2200, lambda: hud.set_listening(True))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
