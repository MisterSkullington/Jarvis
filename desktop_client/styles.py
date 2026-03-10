"""
styles.py — Shared colour palette, fonts, and QSS for the Jarvis desktop app.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QFont, QPolygonF


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

BG          = QColor(0,   8,  20, 238)
CYAN        = QColor(0, 212, 255)
CYAN_60     = QColor(0, 212, 255,  60)
CYAN_120    = QColor(0, 212, 255, 120)
BLUE        = QColor(0, 136, 255)
BLUE_40     = QColor(0, 136, 255,  40)
GRID        = QColor(0, 180, 255,  16)
GRID_HI     = QColor(0, 200, 255,  35)
WHITE       = QColor(200, 235, 255)
WHITE_80    = QColor(200, 235, 255,  80)
RED         = QColor(255,  60,  60)
ORANGE      = QColor(255, 160,   0)
SCAN        = QColor(  0,   0,   0,  28)
RULE        = QColor(  0, 180, 255,  38)
LABEL       = QColor(  0, 180, 255, 120)

# Hex colour strings for use in QSS
CYAN_HEX    = "#00d4ff"
BG_HEX      = "#000814"
BG_LIGHT    = "#001428"
BG_INPUT    = "#001030"
BORDER_HEX  = "#003060"
WHITE_HEX   = "#c8ebff"
LABEL_HEX   = "#00b4ff"
RED_HEX     = "#ff3c3c"
ORANGE_HEX  = "#ffa000"


def c(base: QColor, alpha: int) -> QColor:
    """Return a copy of *base* with the given alpha."""
    colour = QColor(base)
    colour.setAlpha(alpha)
    return colour


def hex_poly(cx: float, cy: float, r: float, angle_offset: float = 0.0) -> QPolygonF:
    """Return a QPolygonF for a regular hexagon centred at (*cx*, *cy*)."""
    pts = []
    for i in range(6):
        a = math.radians(60 * i + angle_offset)
        pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
    return QPolygonF(pts)


# ---------------------------------------------------------------------------
# Font factories
# ---------------------------------------------------------------------------

def font_title() -> QFont:
    f = QFont("Courier New", 11, QFont.Bold)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 5)
    return f

def font_mono() -> QFont:
    return QFont("Courier New", 9)

def font_label() -> QFont:
    return QFont("Courier New", 7)

def font_btn() -> QFont:
    f = QFont("Courier New", 8, QFont.Bold)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
    return f

def font_chat() -> QFont:
    return QFont("Courier New", 10)

def font_chat_small() -> QFont:
    return QFont("Courier New", 8)


# ---------------------------------------------------------------------------
# QSS stylesheet for standard widgets
# ---------------------------------------------------------------------------

APP_QSS = f"""
QWidget#MainWindow {{
    background-color: {BG_HEX};
}}

QScrollArea {{
    background-color: transparent;
    border: none;
}}

QScrollBar:vertical {{
    background: {BG_HEX};
    width: 8px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_HEX};
    min-height: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {CYAN_HEX};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

QLineEdit#ChatInput {{
    background-color: {BG_INPUT};
    color: {WHITE_HEX};
    border: 1px solid {BORDER_HEX};
    border-radius: 4px;
    padding: 8px 12px;
    font-family: "Courier New";
    font-size: 10pt;
    selection-background-color: {CYAN_HEX};
    selection-color: {BG_HEX};
}}
QLineEdit#ChatInput:focus {{
    border-color: {CYAN_HEX};
}}

QPushButton#SendBtn {{
    background-color: {BG_INPUT};
    color: {CYAN_HEX};
    border: 1px solid {BORDER_HEX};
    border-radius: 4px;
    padding: 8px 16px;
    font-family: "Courier New";
    font-size: 9pt;
    font-weight: bold;
    letter-spacing: 2px;
}}
QPushButton#SendBtn:hover {{
    border-color: {CYAN_HEX};
    background-color: #001a3a;
}}
QPushButton#SendBtn:pressed {{
    background-color: #002244;
}}

QPushButton#GearBtn {{
    background-color: transparent;
    color: {LABEL_HEX};
    border: 1px solid {BORDER_HEX};
    border-radius: 4px;
    padding: 8px;
    font-size: 14pt;
}}
QPushButton#GearBtn:hover {{
    border-color: {CYAN_HEX};
    color: {CYAN_HEX};
}}

QLabel#StatusBar {{
    color: {LABEL_HEX};
    font-family: "Courier New";
    font-size: 7pt;
    padding: 4px 12px;
}}

QLabel#ChatRole {{
    font-family: "Courier New";
    font-size: 8pt;
    font-weight: bold;
}}

QLabel#ChatText {{
    font-family: "Courier New";
    font-size: 10pt;
    color: {WHITE_HEX};
}}

QLabel#ChatTime {{
    font-family: "Courier New";
    font-size: 7pt;
    color: {LABEL_HEX};
}}

QDialog {{
    background-color: {BG_HEX};
    color: {WHITE_HEX};
}}

QGroupBox {{
    color: {CYAN_HEX};
    border: 1px solid {BORDER_HEX};
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 16px;
    font-family: "Courier New";
    font-size: 8pt;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}

QLabel {{
    color: {WHITE_HEX};
    font-family: "Courier New";
    font-size: 9pt;
}}

QLineEdit {{
    background-color: {BG_INPUT};
    color: {WHITE_HEX};
    border: 1px solid {BORDER_HEX};
    border-radius: 3px;
    padding: 4px 8px;
    font-family: "Courier New";
    font-size: 9pt;
}}
QLineEdit:focus {{
    border-color: {CYAN_HEX};
}}

QSpinBox, QDoubleSpinBox {{
    background-color: {BG_INPUT};
    color: {WHITE_HEX};
    border: 1px solid {BORDER_HEX};
    border-radius: 3px;
    padding: 4px 8px;
    font-family: "Courier New";
    font-size: 9pt;
}}

QCheckBox {{
    color: {WHITE_HEX};
    font-family: "Courier New";
    font-size: 9pt;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER_HEX};
    border-radius: 3px;
    background-color: {BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background-color: {CYAN_HEX};
    border-color: {CYAN_HEX};
}}

QComboBox {{
    background-color: {BG_INPUT};
    color: {WHITE_HEX};
    border: 1px solid {BORDER_HEX};
    border-radius: 3px;
    padding: 4px 8px;
    font-family: "Courier New";
    font-size: 9pt;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_HEX};
    color: {WHITE_HEX};
    selection-background-color: {BORDER_HEX};
}}

QTextEdit {{
    background-color: {BG_INPUT};
    color: {WHITE_HEX};
    border: 1px solid {BORDER_HEX};
    border-radius: 3px;
    padding: 4px 8px;
    font-family: "Courier New";
    font-size: 9pt;
}}

QPushButton {{
    background-color: {BG_INPUT};
    color: {CYAN_HEX};
    border: 1px solid {BORDER_HEX};
    border-radius: 4px;
    padding: 6px 16px;
    font-family: "Courier New";
    font-size: 9pt;
}}
QPushButton:hover {{
    border-color: {CYAN_HEX};
}}
"""
