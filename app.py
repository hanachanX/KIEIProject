# -*- coding: utf-8 -*-
"""棋慧（KIEI）— 将棋検討ツール（盤面で駒を動かすと、エンジンが候補手を出し、LLMが局面を解説する）"""
import json
import os
import queue
from datetime import datetime
import sys
import threading
import time
import traceback

from PyQt6.QtCore import QBuffer, QTimer, QByteArray, QIODevice, QPointF, QObject, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPolygonF, QShortcut
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow,
                             QMenu, QMessageBox, QPlainTextEdit, QPushButton as NativePushButton, QSpinBox, QSplitter, QTabWidget, QTextBrowser, QTextEdit,
                             QToolTip, QStyle, QStyleOptionButton, QStylePainter, QVBoxLayout, QWidget)
import shogi

import core
try:
    import senkei
except Exception:
    senkei = None
try:
    import book as bookmod
except Exception:
    bookmod = None
try:
    import tsume_mode
except Exception:
    tsume_mode = None
try:
    import tsume_verify                      # 無駄合を除いた検証（棋慧エンジン）
except Exception:
    tsume_verify = None

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

_FONTS = {}


def kiei_fonts():
    """同梱フォント（SIL OFL）を読み込む。戻り値は筆文字 Yuji Syuku（看板と駒の字だけに使う）。
    見つからなければ代わりに明朝体の名前を返す"""
    if not _FONTS:
        from PyQt6.QtGui import QFontDatabase
        brush = "Yu Mincho"
        try:
            fid = QFontDatabase.addApplicationFont(os.path.join(HERE, "fonts", "YujiSyuku-Regular.ttf"))
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if fams:
                brush = fams[0]
        except Exception:
            pass
        _FONTS["brush"] = brush
    return _FONTS["brush"]
FONT_FAMILIES = ["Yu Gothic UI", "Meiryo UI", "Meiryo", "MS Gothic", "Noto Sans CJK JP"]


class QPushButton(NativePushButton):
    """棋慧専用の切り角ボタン。クリック・メニュー・キー操作はQtに任せる。"""

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        enabled = self.isEnabled()
        pressed = self.isDown()
        hovered = self.underMouse() and enabled
        selected = self.isChecked()
        primary = self.property("role") == "primary"
        stop = self.property("role") == "stop"
        # Existing local styles (e.g. the active tsume mode) retain their colors.
        local_style = bool(self.styleSheet())
        ink = QColor("#3d3931")
        paper = QColor("#faf7ee")
        edge = QColor("#c8bfab")
        accent = QColor("#ac8745")
        if primary:
            paper, ink, edge = QColor("#315643"), QColor("#fff9e9"), QColor("#264536")
            accent = QColor("#d5b46d")
        elif selected:
            paper, ink, edge = QColor("#e2eadf"), QColor("#264734"), QColor("#77917b")
            accent = QColor("#46704e")
        elif stop:
            ink, accent = QColor("#974c40"), QColor("#b97662")
        if local_style:
            paper = option.palette.color(QPalette.ColorRole.Button)
            ink = option.palette.color(QPalette.ColorRole.ButtonText)
            edge = paper.darker(120)
        if not enabled:
            paper, ink, edge, accent = (QColor(c) for c in ("#efede6", "#a5a095", "#ddd8cc", "#d0c9ba"))
        elif pressed:
            paper = paper.darker(110)
            edge = accent
        elif hovered:
            paper = paper.lighter(114) if primary else QColor("#f1ebdb") if not selected and not local_style else paper.lighter(104)
            edge = accent
        if self.isDefault() and enabled:
            edge = accent

        painter = QStylePainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        cut = min(6.0, box.height() / 5)
        path = QPainterPath()
        path.moveTo(box.left() + 3, box.top())
        path.lineTo(box.right() - cut, box.top())
        path.lineTo(box.right(), box.top() + cut)
        path.lineTo(box.right(), box.bottom() - 3)
        path.quadTo(box.right(), box.bottom(), box.right() - 3, box.bottom())
        path.lineTo(box.left() + cut, box.bottom())
        path.lineTo(box.left(), box.bottom() - cut)
        path.lineTo(box.left(), box.top() + 3)
        path.quadTo(box.left(), box.top(), box.left() + 3, box.top())
        path.closeSubpath()
        wash = QLinearGradient(box.topLeft(), box.bottomLeft())
        wash.setColorAt(0, paper.lighter(103) if enabled and not pressed else paper)
        wash.setColorAt(1, paper)
        painter.fillPath(path, wash)
        painter.setPen(QPen(edge, 1.0))
        painter.drawPath(path)
        # A short brass inlay, kept outside the normal label area.
        painter.setPen(QPen(accent, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(box.left() + 5, box.center().y() - 5),
                         QPointF(box.left() + 5, box.center().y() + 5))
        if self.hasFocus() and enabled:
            painter.setPen(QPen(accent, 1.0, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(3, 3, -3, -3), 2, 2)
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
            option.palette.setColor(group, QPalette.ColorRole.ButtonText, ink)
        # Qt draws text, mnemonics, icons and menu arrows, including the disabled state.
        painter.drawControl(QStyle.ControlElement.CE_PushButtonLabel, option)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def sq_of(name):
    return shogi.SQUARE_NAMES.index(name)


def safe(fn, default=False):
    """駒が欠けた局面などで例外が出ても、画面が止まらないようにする。"""
    try:
        return fn()
    except Exception:
        return default


def clipboard_png(max_width=1800):
    """クリップボードの画像をPNGのバイト列で返す（画像が無ければNone）。"""
    img = QApplication.clipboard().image()
    if img.isNull():
        return None
    if img.width() > max_width:
        img = img.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def screen_png(screen, max_width=None):
    """指定した画面(モニター)全体を撮影して、PNGのバイト列で返す。"""
    img = screen.grabWindow(0).toImage()
    if img.isNull():
        return None
    if max_width and img.width() > max_width:
        img = img.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


PIECE_MENU = [("歩", "P"), ("香", "L"), ("桂", "N"), ("銀", "S"), ("金", "G"), ("角", "B"), ("飛", "R"), ("玉", "K"),
              ("と", "+P"), ("杏", "+L"), ("圭", "+N"), ("全", "+S"), ("馬", "+B"), ("龍", "+R")]


# ====================================================================== 盤面
class BoardWidget(QWidget):
    moveMade = pyqtSignal(str)       # 利用者が指した手（USI形式）
    positionEdited = pyqtSignal(str)  # 編集モードで直した局面（SFEN）

    def __init__(self):
        super().__init__()
        self.setMinimumSize(420, 480)
        self.board = shogi.Board()
        self.legal = list(self.board.legal_moves)
        self.last_move = None
        self.preview = None
        self.flipped = False
        self.sel = None          # ("sq", 升) または ("drop", 駒の種類)
        self.targets = {}        # 行き先の升 -> [指し手]
        self.hand_rects = []
        self.edit_mode = False
        self.names = ["先手", "後手"]      # 対局者の名前（棋譜に入っていれば盤の上下の帯に出す）
        self.senkei = ""                  # 戦型（盤の右上に大きく出す）

    def set_position(self, board, last_move=None):
        self.board = board
        self.legal = safe(lambda: list(board.legal_moves), [])
        self.last_move = last_move
        self.preview = None
        self._clear_sel()

    def set_senkei(self, text):
        if text != self.senkei:
            self.senkei = text
            self.update()

    def set_preview(self, usi):
        self.preview = usi
        self.update()

    def _clear_sel(self):
        self.sel = None
        self.targets = {}
        self.update()

    # ---- 座標
    def _geom(self):
        w, h = self.width(), self.height()
        cell = max(20.0, min(w / 10.2, h / 13.45))
        ban = 0.95 * cell                      # 盤の上に戦型を出す帯
        lab = 0.4 * cell                       # 持ち駒の名前（「△後手の持ち駒」）を出す細い帯
        ox, oy = (w - 9 * cell) / 2, (h - 13.45 * cell) / 2
        by = oy + ban + lab + 1.5 * cell
        return {"cell": cell, "bx": ox, "by": by,
                "banner": QRectF(ox, oy, 9 * cell, ban),
                "top_label": QRectF(ox, oy + ban, 9 * cell, lab),
                "top": QRectF(ox, oy + ban + lab, 9 * cell, cell),
                "bottom": QRectF(ox, by + 9.2 * cell, 9 * cell, cell),
                "bottom_label": QRectF(ox, by + 10.2 * cell, 9 * cell, lab)}

    def _rc(self, sq):
        col, row = sq % 9, sq // 9
        return (8 - col, 8 - row) if self.flipped else (col, row)

    def _sq_from_rc(self, col, row):
        return (8 - row) * 9 + (8 - col) if self.flipped else row * 9 + col

    def _center(self, sq, g):
        col, row = self._rc(sq)
        return QPointF(g["bx"] + (col + 0.5) * g["cell"], g["by"] + (row + 0.5) * g["cell"])

    def _pos_to_sq(self, pos):
        g = self._geom()
        col = int((pos.x() - g["bx"]) // g["cell"])
        row = int((pos.y() - g["by"]) // g["cell"])
        if 0 <= col < 9 and 0 <= row < 9 and pos.x() >= g["bx"] and pos.y() >= g["by"]:
            return self._sq_from_rc(col, row)
        return None

    # ---- 描画
    def draw_piece(self, p, cx, cy, size, symbol, color):
        p.save()
        p.translate(cx, cy)
        # 画面の上側にいる側の駒を逆向きにする（盤面を反転したときは先手が上側になる）
        if (color == shogi.WHITE) != self.flipped:
            p.rotate(180)
        s = size
        poly = QPolygonF([QPointF(0, -0.46 * s), QPointF(0.34 * s, -0.28 * s), QPointF(0.42 * s, 0.46 * s),
                          QPointF(-0.42 * s, 0.46 * s), QPointF(-0.34 * s, -0.28 * s)])
        p.setBrush(QColor("#f7e3b5"))
        p.setPen(QPen(QColor("#5b4015"), 1.2))
        p.drawPolygon(poly)
        p.setPen(QColor("#c0182a") if symbol.startswith("+") else QColor("#1c1308"))
        f = QFont(kiei_fonts())                 # 駒の字は筆文字（太字の指定はしない：もともと太い書体）
        f.setPixelSize(max(8, int(0.62 * s)))
        p.setFont(f)
        rect = QRectF(-0.5 * s, -0.40 * s, s, 0.86 * s)
        # 筆文字を少し太く見せるため、同じ字をわずかにずらして重ね書きする
        d = max(0.4, 0.012 * s)
        for dx, dy in ((-d, 0), (d, 0), (0, -d), (0, d)):
            p.drawText(rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, core.BOARD_NAME[symbol])
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, core.BOARD_NAME[symbol])
        p.restore()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = self._geom()
        cell, bx, by = g["cell"], g["bx"], g["by"]
        p.fillRect(self.rect(), QColor("#ece7da"))
        p.fillRect(QRectF(bx, by, 9 * cell, 9 * cell), QColor("#e9c47e"))

        # 升目と目印
        for sq_hl, col in self._highlights():
            c = self._center(sq_hl, g)
            p.fillRect(QRectF(c.x() - cell / 2, c.y() - cell / 2, cell, cell), col)
        p.setPen(QPen(QColor("#3a2a10"), 1.2))
        for i in range(10):
            p.drawLine(QPointF(bx, by + i * cell), QPointF(bx + 9 * cell, by + i * cell))
            p.drawLine(QPointF(bx + i * cell, by), QPointF(bx + i * cell, by + 9 * cell))
        p.setBrush(QColor("#3a2a10"))
        for (cx, cy) in [(3, 3), (6, 3), (3, 6), (6, 6)]:
            p.drawEllipse(QPointF(bx + cx * cell, by + cy * cell), cell * 0.06, cell * 0.06)

        # 筋・段の数字
        f = QFont(self.font())
        f.setPixelSize(max(8, int(cell * 0.28)))
        p.setFont(f)
        p.setPen(QColor("#3a2a10"))
        for i in range(9):
            file_no = (i + 1) if self.flipped else (9 - i)
            rank_no = (9 - i) if self.flipped else (i + 1)
            p.drawText(QRectF(bx + i * cell, by - 0.45 * cell, cell, 0.4 * cell), Qt.AlignmentFlag.AlignCenter,
                       core.FILE_ZEN[file_no])
            p.drawText(QRectF(bx + 9 * cell + 2, by + i * cell, 0.5 * cell, cell), Qt.AlignmentFlag.AlignCenter,
                       core.RANK_KAN[rank_no])

        # 駒
        for sq in range(81):
            pc = self.board.piece_at(sq)
            if pc is not None:
                c = self._center(sq, g)
                self.draw_piece(p, c.x(), c.y(), cell * 0.92, pc.symbol().upper(), pc.color)

        # 行き先の目印
        for to_sq in self.targets:
            c = self._center(to_sq, g)
            if self.board.piece_at(to_sq) is not None:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(220, 40, 40, 200), cell * 0.07))
                p.drawEllipse(c, cell * 0.42, cell * 0.42)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(30, 110, 230, 120))
                p.drawEllipse(c, cell * 0.16, cell * 0.16)

        # 持ち駒
        self.hand_rects = []
        top_color = shogi.BLACK if self.flipped else shogi.WHITE
        for rect, lrect, color in ((g["top"], g["top_label"], top_color), (g["bottom"], g["bottom_label"], 1 - top_color)):
            self._draw_hand(p, rect, color, cell)
            f = QFont(self.font())
            f.setPixelSize(max(8, int(cell * 0.28)))
            p.setFont(f)
            p.setPen(QColor("#3a2a10"))
            nm = (self.names[0] if color == shogi.BLACK else self.names[1]) if len(self.names) >= 2 else ""
            if nm and nm not in ("先手", "後手"):
                f.setPixelSize(max(9, int(cell * 0.34)))
                f.setBold(True)
                p.setFont(f)
                label = ("▲" if color == shogi.BLACK else "△") + nm
            else:
                label = "▲先手の持ち駒" if color == shogi.BLACK else "△後手の持ち駒"
            p.drawText(lrect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)

        # 戦型（盤の右上に大きく）
        if self.senkei:
            self._draw_senkei(p, g)

        # 候補手の矢印
        if self.preview:
            self._draw_preview(p, g)

        # 編集モード：ドラッグ中の駒（元の場所は薄くする）
        d = getattr(self, "_drag", None)
        if self.edit_mode and d and d.get("active") and d["src"] is not None:
            src = d["src"]
            if src[0] == "sq":
                pc = self.board.piece_at(src[1])
                c0 = self._center(src[1], g)
                p.fillRect(QRectF(c0.x() - cell / 2, c0.y() - cell / 2, cell, cell), QColor(255, 255, 255, 150))
                sym, col = pc.symbol().upper(), pc.color
            else:
                sym, col = shogi.Piece(src[2], src[1]).symbol().upper(), src[1]
            self.draw_piece(p, d["pos"].x(), d["pos"].y(), cell * 1.0, sym, col)

        # 編集モードの表示
        if self.edit_mode:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(230, 120, 20, 170), 1, Qt.PenStyle.DashLine))
            p.drawRect(g["top"])
            p.drawRect(g["bottom"])
            p.setPen(QPen(QColor(230, 120, 20), 4))
            p.drawRect(self.rect().adjusted(2, 2, -2, -2))
            f = QFont(self.font())
            f.setPixelSize(max(10, int(cell * 0.26)))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(190, 80, 0))
            p.drawText(QRectF(12, 8, max(70.0, g["top"].x() - 16), cell * 0.9), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       "編集中")
        p.end()

    def _draw_senkei(self, p, g):
        rect = g["banner"]
        f = QFont(self.font())
        f.setFamilies([kiei_fonts(), "Yu Mincho", "MS 明朝", "serif"])   # 看板・駒と同じ筆文字
        f.setBold(False)
        size = max(10, int(rect.height() * 0.62))
        f.setPixelSize(size)
        label = self.senkei
        fm = None
        # 長い場合は収まるまで文字を小さくする
        while True:
            f.setPixelSize(size)
            p.setFont(f)
            fm = p.fontMetrics()
            if fm.horizontalAdvance(label) + 2.2 * size <= rect.width() or size <= 10:
                break
            size -= 1
        wtxt = fm.horizontalAdvance(label)
        pad = 0.5 * size
        w = min(rect.width(), wtxt + 2 * pad + 1.8 * size)
        box = QRectF(rect.right() - w, rect.top() + 2, w, rect.height() - 4)
        grad = QLinearGradient(box.topLeft(), box.bottomRight())
        grad.setColorAt(0.0, QColor("#4a2f14"))
        grad.setColorAt(1.0, QColor("#2a1a0a"))
        p.setPen(QPen(QColor("#c9a24a"), 1.6))
        p.setBrush(grad)
        p.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        # 「戦型」の小さなラベル
        f2 = QFont(f)
        f2.setPixelSize(max(8, int(size * 0.5)))
        p.setFont(f2)
        p.setPen(QColor("#e0c27a"))
        p.drawText(QRectF(box.left() + pad, box.top(), 1.5 * size, box.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "戦型")
        p.setFont(f)
        p.setPen(QColor("#fff1c8"))
        p.drawText(QRectF(box.left() + pad + 1.5 * size, box.top(), wtxt + pad, box.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, label)

    def _highlights(self):
        out = []
        lm = self.last_move
        if lm:
            if lm[1] != "*":
                out.append((sq_of(lm[0:2]), QColor(255, 235, 120, 150)))
            out.append((sq_of(lm[2:4]), QColor(255, 235, 120, 150)))
        if self.sel and self.sel[0] == "sq":
            out.append((self.sel[1], QColor(120, 200, 120, 170)))
        return out

    def _draw_hand(self, p, rect, color, cell):
        x = rect.x() + 0.1 * cell
        for pt, _name in core.HAND_ORDER:
            n = self.board.pieces_in_hand[color].get(pt, 0)
            if not n:
                continue
            sym = shogi.Piece(pt, color).symbol().upper()
            w = cell * 0.95
            r = QRectF(x, rect.y(), w, rect.height())
            if self.sel == ("drop", pt) and color == self.board.turn:
                p.fillRect(r, QColor(120, 200, 120, 170))
            self.draw_piece(p, r.center().x(), r.center().y(), cell * 0.8, sym, color)
            if n > 1:
                f = QFont(self.font())
                f.setPixelSize(max(8, int(cell * 0.3)))
                p.setFont(f)
                p.setPen(QColor("#a01010"))
                p.drawText(QRectF(r.right() - 0.05 * cell, r.bottom() - 0.45 * cell, 0.8 * cell, 0.45 * cell),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"×{n}")
            self.hand_rects.append((r, color, pt))
            x += cell * 1.2

    def _draw_preview(self, p, g):
        usi, cell = self.preview, g["cell"]
        try:
            to_c = self._center(sq_of(usi[2:4]), g)
        except Exception:
            return
        if usi[1] == "*":
            # 駒を打つ手：持ち駒の駒から、打つマスへ矢印を引く
            p.fillRect(QRectF(to_c.x() - cell / 2, to_c.y() - cell / 2, cell, cell), QColor(30, 100, 230, 90))
            pt = core.BASE_PT.get(usi[0])
            for r, color, hpt in self.hand_rects:
                if color == self.board.turn and hpt == pt:
                    p.fillRect(r, QColor(30, 100, 230, 90))
                    self._arrow(p, r.center(), to_c, cell)
                    break
            return
        self._arrow(p, self._center(sq_of(usi[0:2]), g), to_c, cell)

    @staticmethod
    def _arrow(p, fr_c, to_c, cell):
        col = QColor(30, 100, 230, 170)
        p.setPen(QPen(col, cell * 0.12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(fr_c, to_c)
        dx, dy = to_c.x() - fr_c.x(), to_c.y() - fr_c.y()
        L = max(1.0, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / L, dy / L
        head = cell * 0.3
        a = QPointF(to_c.x() - ux * head + uy * head * 0.6, to_c.y() - uy * head - ux * head * 0.6)
        b = QPointF(to_c.x() - ux * head - uy * head * 0.6, to_c.y() - uy * head + ux * head * 0.6)
        p.setBrush(col)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([to_c, a, b]))

    # ---- 操作
    def mousePressEvent(self, e):
        if self.edit_mode:
            if e.button() == Qt.MouseButton.LeftButton:
                self._drag = {"src": self._edit_source(e.position()), "press": e.position(), "pos": e.position(), "active": False}
            elif e.button() == Qt.MouseButton.RightButton:
                self._edit_context(e.position())
            return
        if e.button() == Qt.MouseButton.RightButton:
            self._clear_sel()
            return
        pos = e.position()
        for rect, color, pt in self.hand_rects:
            if rect.contains(pos):
                if color == self.board.turn:
                    self._select_drop(pt)
                return
        sq = self._pos_to_sq(pos)
        if sq is None:
            self._clear_sel()
            return
        if sq in self.targets:
            self._try_move(sq)
            return
        pc = self.board.piece_at(sq)
        if pc is not None and pc.color == self.board.turn:
            self.sel = ("sq", sq)
            self.targets = {}
            for m in self.legal:
                if m.drop_piece_type is None and m.from_square == sq:
                    self.targets.setdefault(m.to_square, []).append(m)
            self.update()
        else:
            self._clear_sel()

    # ---- 編集モード：ドラッグで移動・右クリックで成り／先後入れ替え
    def _edit_source(self, pos):
        """押した場所にある駒（盤の升 or 持ち駒）。無ければ None。"""
        for rect, color, pt in self.hand_rects:
            if rect.contains(pos):
                return ("hand", color, pt)
        sq = self._pos_to_sq(pos)
        if sq is not None and self.board.piece_at(sq) is not None:
            return ("sq", sq)
        return None

    def mouseMoveEvent(self, e):
        d = getattr(self, "_drag", None)
        if self.edit_mode and d and d["src"] is not None:
            d["pos"] = e.position()
            if not d["active"] and (d["pos"] - d["press"]).manhattanLength() > 8:
                d["active"] = True
            if d["active"]:
                self.update()

    def mouseReleaseEvent(self, e):
        d = getattr(self, "_drag", None)
        self._drag = None
        if not (self.edit_mode and d and e.button() == Qt.MouseButton.LeftButton):
            return
        if not d["active"]:
            self._edit_click(d["press"])           # ただのクリック：これまでどおり、駒を選んで置く／持ち駒を直す
            self.update()
            return
        self._edit_drop(d["src"], e.position())
        self.update()

    def _edit_drop(self, src, pos):
        g = self._geom()
        top_color = shogi.BLACK if self.flipped else shogi.WHITE
        cells, hands, turn = core.board_to_model(self.board)
        rev = {v: k for k, v in core.HAND_LETTER.items()}
        target = None                                  # ("sq", 升) / ("hand", 色) / None（盤の外）
        if g["top"].contains(pos) or g["top_label"].contains(pos):
            target = ("hand", top_color)
        elif g["bottom"].contains(pos) or g["bottom_label"].contains(pos):
            target = ("hand", 1 - top_color)
        else:
            sq = self._pos_to_sq(pos)
            if sq is not None:
                target = ("sq", sq)
        # 動かす駒を取り上げる
        if src[0] == "sq":
            sym = cells[src[1]]
            if target == ("sq", src[1]):
                return
            cells[src[1]] = None
        else:
            _k, color, pt = src
            if hands[color].get(pt, 0) <= 0:
                return
            hands[color][pt] -= 1
            if hands[color][pt] <= 0:
                del hands[color][pt]
            sym = core.HAND_LETTER[pt] if color == shogi.BLACK else core.HAND_LETTER[pt].lower()
        # 置く
        if target is not None and target[0] == "sq":
            cells[target[1]] = sym                       # 相手の駒がある升に置くと、その駒は消える
        elif target is not None and target[0] == "hand":
            base = sym.replace("+", "").upper()
            if base in rev:                              # 玉は持ち駒にならないので、そのまま消える
                hands[target[1]][rev[base]] = hands[target[1]].get(rev[base], 0) + 1
        self.positionEdited.emit(core.model_to_sfen(cells, hands, turn))

    def _edit_context(self, pos):
        """右クリック：成り→先後入れ替え→成りをもとに戻す→先後入れ替え、と黙って循環する。
        Shift＋右クリックなら、メニュー（成り／先後入れ替え／取り除く）を出す。"""
        sq = self._pos_to_sq(pos)
        if sq is None or self.board.piece_at(sq) is None:
            return
        cells, hands, turn = core.board_to_model(self.board)
        sym = cells[sq]
        base = sym.replace("+", "").upper()
        if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier):
            # 黙って循環：成り駒 → 先後入れ替え → 成り駒をもとに戻す → 先後入れ替え（もとの駒）
            promoted = sym.startswith("+")
            white = sym.replace("+", "")[0].islower()
            if base in ("P", "L", "N", "S", "B", "R"):
                if not promoted and not white:
                    promoted = True
                elif promoted and not white:
                    white = True
                elif promoted and white:
                    promoted = False
                else:
                    white = False
            else:
                white = not white
            letter = base.lower() if white else base
            cells[sq] = ("+" if promoted else "") + letter
            self.positionEdited.emit(core.model_to_sfen(cells, hands, turn))
            return
        menu = QMenu(self)
        can_promote = base in ("P", "L", "N", "S", "B", "R")
        a_pro = menu.addAction("成り駒をもとに戻す" if sym.startswith("+") else "成り駒にする")
        a_pro.setEnabled(can_promote)
        a_flip = menu.addAction("先手 ⇄ 後手 を入れ替える")
        a_del = menu.addAction("この駒を取り除く")
        act = menu.exec(QCursor.pos())
        if act is None:
            return
        if act is a_pro:
            cells[sq] = sym[1:] if sym.startswith("+") else ("+" + sym)
        elif act is a_flip:
            cells[sq] = sym.swapcase()
        elif act is a_del:
            cells[sq] = None
        self.positionEdited.emit(core.model_to_sfen(cells, hands, turn))

    def _select_drop(self, pt):
        self.sel = ("drop", pt)
        self.targets = {}
        for m in self.legal:
            if m.drop_piece_type == pt:
                self.targets.setdefault(m.to_square, []).append(m)
        self.update()

    # ---- 編集モード
    def _edit_click(self, pos):
        g = self._geom()
        top_color = shogi.BLACK if self.flipped else shogi.WHITE
        if g["top"].contains(pos):
            self._edit_hand(top_color)
        elif g["bottom"].contains(pos):
            self._edit_hand(1 - top_color)
        else:
            sq = self._pos_to_sq(pos)
            if sq is not None:
                self._edit_square(sq)

    def _choose_piece(self):
        """置く駒を選ばせる。先手は大文字・後手は小文字の記号、空にするなら""、取り消しならNone。"""
        menu = QMenu(self)
        chosen = {}
        chosen[menu.addAction("空にする")] = ""
        for title, lower in (("先手の駒を置く", False), ("後手の駒を置く", True)):
            sub = menu.addMenu(title)
            for ja, sym in PIECE_MENU:
                chosen[sub.addAction(ja)] = sym.lower() if lower else sym
        return chosen.get(menu.exec(QCursor.pos()))

    def _edit_square(self, sq):
        sym = self._choose_piece()
        if sym is None:
            return
        cells, hands, turn = core.board_to_model(self.board)
        cells[sq] = sym or None
        self.positionEdited.emit(core.model_to_sfen(cells, hands, turn))

    def _hand_dialog(self, color, cur):
        dlg = QDialog(self)
        dlg.setWindowTitle("先手の持ち駒" if color == shogi.BLACK else "後手の持ち駒")
        form = QFormLayout(dlg)
        boxes = {}
        for pt, name in core.HAND_ORDER:
            sb = QSpinBox()
            sb.setRange(0, 18)
            sb.setValue(int(cur.get(pt, 0)))
            boxes[pt] = sb
            form.addRow(name, sb)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec():
            return {pt: sb.value() for pt, sb in boxes.items() if sb.value()}
        return None

    def _edit_hand(self, color):
        cells, hands, turn = core.board_to_model(self.board)
        new = self._hand_dialog(color, hands[color])
        if new is None:
            return
        hands[color] = new
        self.positionEdited.emit(core.model_to_sfen(cells, hands, turn))

    def _ask_promote(self):
        box = QMessageBox(self)
        box.setWindowTitle("成りますか？")
        yes = box.addButton("成る", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("成らない", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _try_move(self, sq):
        moves = self.targets[sq]
        if len(moves) == 1:
            m = moves[0]
        else:
            promo = next(x for x in moves if x.promotion)
            plain = next(x for x in moves if not x.promotion)
            m = promo if self._ask_promote() else plain
        self._clear_sel()
        self.moveMade.emit(m.usi())


def _default_tsume_engine():
    """アプリと同じフォルダにKomoringHeights（user-normal-g++-avx2.exe）があれば、それを初期値にする。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user-normal-g++-avx2.exe")
    return p if os.path.exists(p) else ""


# ====================================================================== 設定画面
class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.setMinimumWidth(620)
        opts = dict(cfg.get("engine_options", {}))
        form = QFormLayout(self)

        self.engine = QLineEdit(cfg.get("engine_path", ""))
        b1 = QPushButton("参照…")
        b1.clicked.connect(self._pick_engine)
        form.addRow("エンジン（exe）", self._row(self.engine, b1))

        self.tengine = QLineEdit(cfg.get("tsume_engine_path", _default_tsume_engine()))
        self.tengine.setPlaceholderText("詰将棋モードで使う専用エンジン（KomoringHeights の exe）。空欄なら通常のエンジンを使う")
        bt = QPushButton("参照…")
        bt.clicked.connect(self._pick_tsume_engine)
        form.addRow("詰将棋用エンジン（exe）", self._row(self.tengine, bt))
        self.tsec = QSpinBox()
        self.tsec.setRange(1, 600)
        self.tsec.setValue(int(cfg.get("tsume_sec", 5)))
        self.tsec.setToolTip("詰将棋モードで、玉方の応手を決めるときの1局面あたりの制限時間(秒)")
        form.addRow("詰将棋の応手を考える時間(秒)", self.tsec)

        self.threads = QSpinBox()
        self.threads.setRange(1, 256)
        self.threads.setValue(int(opts.pop("Threads", 4)))
        form.addRow("スレッド数", self.threads)
        self.hash = QSpinBox()
        self.hash.setRange(16, 131072)
        self.hash.setValue(int(opts.pop("USI_Hash", 512)))
        form.addRow("ハッシュ(MB)", self.hash)

        self.extra = QPlainTextEdit("\n".join(f"{k}={v}" for k, v in opts.items()))
        self.extra.setPlaceholderText("追加のエンジン設定を1行に1つ「名前=値」で書く（例：FV_SCALE=24）。評価関数(nn.bin)は、エンジンのexeの隣の eval フォルダに置けば自動で読まれます")
        self.extra.setFixedHeight(70)
        form.addRow("追加オプション", self.extra)

        self.sec = QSpinBox()
        self.sec.setRange(1, 600)
        self.sec.setValue(int(cfg.get("movetime_sec", 5)))
        form.addRow("思考時間(秒)", self.sec)
        self.gsec = QDoubleSpinBox()
        self.gsec.setRange(0.1, 120)
        self.gsec.setSingleStep(0.1)
        self.gsec.setDecimals(1)
        self.gsec.setValue(float(cfg.get("game_sec", 1)))
        self.gsec.setToolTip("「全局を解析」で、1手(1局面)あたりに考えさせる秒数")
        form.addRow("全局解析：1手あたり(秒)", self.gsec)
        self.gwork = QSpinBox()
        self.gwork.setRange(1, 8)
        self.gwork.setValue(int(cfg.get("game_workers", 3)))
        self.gwork.setToolTip("同時に動かすエンジンの数。パソコンのコア数より多くしないでください（4コアなら3〜4）")
        form.addRow("全局解析：並列エンジン数", self.gwork)
        self.msec = QSpinBox()
        self.msec.setRange(0, 86400)
        self.msec.setSpecialValueText("無制限")
        self.msec.setValue(int(cfg.get("mate_sec", 60)))
        self.msec.setToolTip("「詰みを探す」の制限時間(秒)。0=無制限（停止ボタンで止める）")
        form.addRow("詰み探索の時間(秒)", self.msec)
        self.mpv = QSpinBox()
        self.mpv.setRange(1, 10)
        self.mpv.setValue(int(cfg.get("multipv", 3)))
        form.addRow("候補手の数", self.mpv)

        self.provider = QComboBox()
        self.provider.addItem("Gemini（Google）", "gemini")
        self.provider.addItem("ChatGPT（OpenAI）", "openai")
        self.provider.addItem("Claude（Anthropic）", "claude")
        self.provider.addItem("Groq（高速・無料枠あり）", "groq")
        self.provider.setCurrentIndex(max(0, self.provider.findData(cfg.get("llm_provider", "gemini"))))
        form.addRow("解説に使うAI", self.provider)
        self.key = QLineEdit(cfg.get("gemini_api_key", ""))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Gemini APIキー", self.key)
        self.model = QLineEdit(cfg.get("gemini_model", "gemini-2.5-flash"))
        form.addRow("Geminiモデル名", self.model)
        self.okey = QLineEdit(cfg.get("openai_api_key", ""))
        self.okey.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("OpenAI APIキー", self.okey)
        self.omodel = QComboBox()
        self.omodel.setEditable(True)            # 一覧に無い名前も直接入力できる
        self.omodel.addItems(core.OPENAI_MODELS)
        self.omodel.setCurrentText(cfg.get("openai_model", "gpt-5.4-mini"))
        self.omodel.setToolTip("gpt-5.4-mini = GPT-5.4 Mini（標準）。一覧に無いモデルは、名前を直接入力してください")
        form.addRow("OpenAIモデル名", self.omodel)
        self.akey = QLineEdit(cfg.get("anthropic_api_key", ""))
        self.akey.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Anthropic APIキー", self.akey)
        self.amodel = QComboBox()
        self.amodel.setEditable(True)
        self.amodel.addItems(core.CLAUDE_MODELS)
        self.amodel.setCurrentText(cfg.get("anthropic_model", "claude-sonnet-5-5"))
        form.addRow("Claudeモデル名", self.amodel)
        self.gkey = QLineEdit(cfg.get("groq_api_key", ""))
        self.gkey.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Groq APIキー", self.gkey)
        self.gmodel = QComboBox()
        self.gmodel.setEditable(True)
        self.gmodel.addItems(core.GROQ_MODELS)
        self.gmodel.setCurrentText(cfg.get("groq_model", "openai/gpt-oss-120b"))
        form.addRow("Groqモデル名", self.gmodel)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    @staticmethod
    def _row(edit, btn):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(edit, 1)
        lay.addWidget(btn)
        return w

    def _pick_engine(self):
        path, _ = QFileDialog.getOpenFileName(self, "エンジンを選ぶ", "", "実行ファイル (*.exe);;すべて (*)")
        if path:
            self.engine.setText(path)

    def _pick_tsume_engine(self):
        path, _ = QFileDialog.getOpenFileName(self, "詰将棋用エンジンを選ぶ", "", "実行ファイル (*.exe);;すべて (*)")
        if path:
            self.tengine.setText(path)

    def apply_to(self, cfg):
        opts = {"Threads": self.threads.value(), "USI_Hash": self.hash.value()}
        for line in self.extra.toPlainText().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip():
                    opts[k.strip()] = v.strip()
        cfg.update({"engine_path": self.engine.text().strip(), "engine_options": opts,
                    "tsume_engine_path": self.tengine.text().strip(), "tsume_sec": self.tsec.value(),
                    "movetime_sec": self.sec.value(), "mate_sec": self.msec.value(), "game_sec": self.gsec.value(), "game_workers": self.gwork.value(), "multipv": self.mpv.value(),
                    "gemini_api_key": self.key.text().strip(), "gemini_model": self.model.text().strip(),
                    "llm_provider": self.provider.currentData(),
                    "openai_api_key": self.okey.text().strip(), "openai_model": self.omodel.currentText().strip(),
                    "anthropic_api_key": self.akey.text().strip(), "anthropic_model": self.amodel.currentText().strip(),
                    "groq_api_key": self.gkey.text().strip(), "groq_model": self.gmodel.currentText().strip()})


# ====================================================================== メイン画面
class Sig(QObject):
    cands = pyqtSignal(int, list, bool)
    senkei = pyqtSignal(int, str)
    senkei_ready = pyqtSignal()
    error = pyqtSignal(int, str)
    gemini = pyqtSignal(int, str)
    gemini_err = pyqtSignal(int, str)
    shot = pyqtSignal(object)
    shot_err = pyqtSignal(str)
    mate = pyqtSignal(object)
    verify = pyqtSignal(object)
    game_prog = pyqtSignal(str, int, object)
    game_done = pyqtSignal(str, bool)
    game_err = pyqtSignal(str)
    review = pyqtSignal(str, str)
    review_err = pyqtSignal(str)
    tsume_judged = pyqtSignal(int, object, str)
    tsume_line = pyqtSignal(int, object)


class EvalGraph(QWidget):
    """一局の評価値グラフ。上＝先手有利、下＝後手有利。クリックでその手数へ移動。"""
    plotClicked = pyqtSignal(int)
    CLIP = 2000

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(130)
        self.setMaximumHeight(170)
        self.setMouseTracking(True)
        self.data = None            # 各手数の記録(dict)またはNone(未解析)のリスト
        self.marks = {}             # 手数 -> {"grade":..}
        self.goods = {}             # 手数 -> {"grade":..}（好手・妙手）
        self.cursor = 0
        self.tipfn = None
        self.min_n = 0              # 観戦中は、手数の目盛りを固定して、右へ伸びていくようにする
        self.msg = "検討しながら指していくと、ここに評価値のグラフが伸びていきます"

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(300, 130)          # 余裕があるときは高さ130（全画面で低い画面のときだけ70まで縮む）

    def set_data(self, data, marks=None, goods=None):
        self.data, self.marks, self.goods = data, (marks or {}), (goods or {})
        self.update()

    def set_cursor(self, ply):
        self.cursor = ply
        self.update()

    def _geom(self):
        m = 8
        return m, m + 4, self.width() - 2 * m, self.height() - 2 * m - 8

    def _x(self, i, n, left, w):
        return left + (w * i / n if n else 0)

    def _y(self, v, top, h):
        v = max(-self.CLIP, min(self.CLIP, v))
        return top + h / 2 - v / self.CLIP * (h / 2)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(250, 250, 250))
        left, top, w, h = self._geom()
        p.setPen(QPen(QColor(200, 200, 200), 1))
        p.drawRect(left, top, w, h)
        for frac in (0.25, 0.75):
            p.drawLine(int(left), int(top + h * frac), int(left + w), int(top + h * frac))
        p.setPen(QPen(QColor(120, 120, 120), 1))
        p.drawLine(int(left), int(top + h / 2), int(left + w), int(top + h / 2))
        f = QFont(); f.setPointSize(8); p.setFont(f)
        p.setPen(QColor(120, 120, 120))
        p.drawText(int(left + 3), int(top + 12), "先手有利")
        p.drawText(int(left + 3), int(top + h - 4), "後手有利")
        d = self.data
        if not d or len(d) < 2:
            p.setPen(QColor(110, 110, 110))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.msg)
            p.end()
            return
        n = max(len(d) - 1, self.min_n)
        pts = [(i, e["v"]) for i, e in enumerate(d) if e is not None]
        zero = top + h / 2
        # 面（上は先手側＝青、下は後手側＝赤）
        for up, col in ((True, QColor(90, 140, 220, 90)), (False, QColor(230, 110, 100, 90))):
            p.save()
            p.setClipRect(QRectF(left, top if up else zero, w, h / 2))
            poly = QPolygonF()
            if pts:
                poly.append(QPointF(self._x(pts[0][0], n, left, w), zero))
                for i, v in pts:
                    poly.append(QPointF(self._x(i, n, left, w), self._y(v, top, h)))
                poly.append(QPointF(self._x(pts[-1][0], n, left, w), zero))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawPolygon(poly)
            p.restore()
        p.setPen(QPen(QColor(40, 60, 120), 1.6))
        for (i0, v0), (i1, v1) in zip(pts, pts[1:]):
            if i1 == i0 + 1:
                p.drawLine(QPointF(self._x(i0, n, left, w), self._y(v0, top, h)),
                           QPointF(self._x(i1, n, left, w), self._y(v1, top, h)))
        cols = {"??": QColor(220, 30, 30), "?": QColor(240, 130, 20), "?!": QColor(220, 190, 0)}
        for i, m in self.marks.items():
            if i < len(d) and d[i] is not None:
                p.setBrush(cols.get(m["grade"], QColor(200, 0, 0)))
                p.setPen(QPen(QColor(60, 60, 60), 1))
                p.drawEllipse(QPointF(self._x(i, n, left, w), self._y(d[i]["v"], top, h)), 4, 4)
        for i, m in self.goods.items():
            if i < len(d) and d[i] is not None:
                big = m["grade"] == "!!"
                p.setBrush(QColor(10, 125, 50) if big else QColor(70, 190, 100))
                p.setPen(QPen(QColor(60, 60, 60), 1))
                p.drawEllipse(QPointF(self._x(i, n, left, w), self._y(d[i]["v"], top, h)), 5 if big else 4, 5 if big else 4)
        if self.min_n:
            p.setPen(QColor(150, 150, 150))
            for k in range(20, n + 1, 20):
                xk = self._x(k, n, left, w)
                p.drawLine(QPointF(xk, top + h - 3), QPointF(xk, top + h))
                if xk < left + w - 34:
                    p.drawText(QPointF(xk + 2, top + h - 4), f"{k}手")
        cx = self._x(min(self.cursor, n), n, left, w)
        p.setPen(QPen(QColor(210, 40, 40), 1.4))
        p.drawLine(QPointF(cx, top), QPointF(cx, top + h))
        p.end()

    def _ply_at(self, x):
        if not self.data or len(self.data) < 2:
            return None
        left, top, w, h = self._geom()
        n = max(len(self.data) - 1, self.min_n)
        return max(0, min(len(self.data) - 1, round((x - left) / w * n))) if w > 0 else None

    def mousePressEvent(self, ev):
        i = self._ply_at(ev.position().x())
        if i is not None:
            self.plotClicked.emit(i)

    def mouseMoveEvent(self, ev):
        i = self._ply_at(ev.position().x())
        if i is not None and self.tipfn:
            QToolTip.showText(ev.globalPosition().toPoint(), self.tipfn(i), self)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("棋慧")
        self.resize(1440, 780)
        self.cfg = core.load_config(CONFIG_PATH)
        self.engine = None
        self.engine_lock = threading.Lock()
        self.tsume_eng = None                  # 詰将棋専用エンジン（KomoringHeights）
        self.tsume_lock = threading.Lock()
        self.tsume_olock = threading.Lock()
        self.tsume_oeng = None
        self.kh_ask_ms = 40                   # 検証中の1回の問い合わせの制限時間(ミリ秒)。普通は数ミリ秒で答えが出る
        self.kh_ask_by = {}
        self.gen = 0
        self.analyzing = False
        self.cands = []
        self.cands_final = False
        self.explain_pending = False
        self.names = ["先手", "後手"]
        self.start_sfen = shogi.STARTING_SFEN
        self.moves = []
        self.cursor = 0
        self.cur_board = shogi.Board()
        self.sig = Sig()
        self.sig.cands.connect(self.on_cands)
        self.sig.senkei.connect(self.on_senkei)
        self.tsume = None
        self.variations = []
        self.main_game = None
        self.tsume_src = ""
        self.tsume_dlg = None
        self.tsume_seq = 0
        self.sig.tsume_judged.connect(self.on_tsume_judged)
        self.sig.tsume_line.connect(self.on_tsume_line)
        self.sig.senkei_ready.connect(self.on_senkei_ready)
        if senkei is not None:
            senkei.READY_CB = lambda: self.sig.senkei_ready.emit()
            try:
                senkei.preload()
            except Exception:
                pass
        self._sk_cache, self._info_base, self._sk_seq = {}, "", 0
        self.kif_senkei = ("", "")
        self.sig.error.connect(self.on_error)
        self.sig.gemini.connect(self.on_gemini)
        self.sig.mate.connect(self.on_mate)
        self.sig.verify.connect(self.on_verify)
        self.sig.game_prog.connect(self.on_game_prog)
        self.sig.game_done.connect(self.on_game_done)
        self.sig.game_err.connect(self.on_game_err)
        self.sig.review.connect(self.on_review)
        self.sig.review_err.connect(self.on_review_err)
        self.game_running = False
        self.game_cancel = threading.Event()
        self.eval_key = None
        self.evals = None
        self.swings = {}
        self.goods = {}
        self.matches = {}           # 手数 -> エンジン候補との一致（1〜3位、0=候補外）
        self.review_md = ""            # 全局の講評（全局の結果タブに残す）
        self.sig.gemini_err.connect(self.on_gemini_err)

        # 左：盤面と操作ボタン
        self.boardw = BoardWidget()
        self.boardw.moveMade.connect(self.on_user_move)
        left = QWidget()
        lv = QVBoxLayout(left)
        self.tsume_banner = QLabel("")
        self.tsume_banner.setStyleSheet("background:#d9480f; color:white; font-weight:bold; font-size:15px; padding:6px 10px; border-radius:4px;")
        self.tsume_banner.hide()
        lv.addWidget(self.tsume_banner)
        lv.addWidget(self.boardw, 1)
        self.graph = EvalGraph()
        self.graph.plotClicked.connect(self.go_to_ply)
        self.graph.tipfn = self.graph_tip
        lv.addWidget(self.graph)
        self.btn_game = QPushButton("全局を解析（評価値グラフ）")
        self.btn_game.setToolTip("読み込んだ棋譜の全局面をエンジンで解析し、評価値のグラフを出します。もう一度押すと中止します")
        self.btn_game.clicked.connect(self.toggle_game_analysis)
        self.game_label = QLabel("")
        self.btn_open_eval = QPushButton("評価グラフを開く…")
        self.btn_open_eval.setToolTip("保存した評価グラフ（解説保存\\評価グラフ フォルダのJSON）を選んで開きます")
        self.btn_open_eval.clicked.connect(self.open_eval_file)
        self.mode_box = QComboBox()
        self.mode_box.addItem("高速", "fast")
        self.mode_box.addItem("詳細", "detail")
        self.mode_box.setToolTip("高速＝候補1つで解析（好手・妙手・エンジン一致は出しません）。\n"
                                 "詳細＝候補3つで解析（好手・妙手・エンジン一致を出します。1手あたりの時間は1.5倍）")
        self.mode_box.setCurrentIndex(1 if self.cfg.get("game_mode") == "detail" else 0)
        self.mode_box.currentIndexChanged.connect(self.on_mode_changed)
        self.btn_review = QPushButton("全局をAIで講評")
        self.btn_review.setToolTip("全局解析の結果（評価値の流れと勝負所）を、設定で選んだAIに渡して、一局の講評を書いてもらいます")
        self.btn_review.clicked.connect(self.review_game)
        self.var_widget = QWidget()
        varrow = QHBoxLayout(self.var_widget)
        varrow.setContentsMargins(0, 0, 0, 0)
        varrow.addWidget(QLabel("変化："))
        self.var_combo = QComboBox()
        self.var_combo.setToolTip("この棋譜にある枝分かれ（変化）の手順です。選ぶと、その手順に切り替わります")
        self.var_combo.currentIndexChanged.connect(self.on_variation)
        varrow.addWidget(self.var_combo, 1)
        lv.addWidget(self.var_widget)
        self.var_widget.hide()
        nav = QHBoxLayout()
        nav.setSpacing(4)
        for text, fn in [("|◀ 最初", self.go_first), ("◀ 戻る", self.go_prev), ("進む ▶", self.go_next),
                         ("最後 ▶|", self.go_last), ("反転", self.flip), ("平手へ", self.reset_board)]:
            b = QPushButton(text)
            b.setToolTip({"反転": "盤面を反転", "平手へ": "平手に戻す", "◀ 戻る": "1手戻る", "進む ▶": "1手進む"}.get(text, ""))
            b.clicked.connect(fn)
            nav.addWidget(b)
        # まとめメニュー：貼り付け・コピー・ファイル（KIFとSFENを選ぶ）
        mb0 = QPushButton("貼り付け")
        mb0.setToolTip("クリップボードの文字を見て、SFEN・棋譜（KIF）のどちらかを自動で判別して読み込みます")
        mb0.clicked.connect(self.paste_auto)
        kifu_btns = [mb0]
        for title, items in [("コピー", [("SFENをコピー", self.copy_sfen), ("KIFをコピー", self.copy_kif)]),
                             ("ファイル", [("KIFを読み込む…", self.open_kif), ("KIFを保存…", self.save_kif)])]:
            mb = QPushButton(title)
            m = QMenu(mb)
            for t, fn in items:
                m.addAction(t, fn)
            mb.setMenu(m)
            kifu_btns.append(mb)
        self.btn_tsume = QPushButton("詰将棋")
        self.btn_tsume.setToolTip("詰将棋の問題一覧を開きます")
        self.btn_tsume.clicked.connect(self.open_tsume)
        self.btn_main = QPushButton("元の手順へ戻る")
        self.btn_main.setToolTip("棋譜の途中から別の手を指して枝分かれしたあと、元の棋譜の手順に戻ります")
        self.btn_main.clicked.connect(self.back_to_main)
        self.btn_main.hide()
        nav.addWidget(self.btn_main)
        lv.addLayout(nav)
        nav2 = QHBoxLayout()
        self.btn_shot = QPushButton("スクショ→局面（クリップボードの画像）")
        self.btn_shot.clicked.connect(lambda: self.import_screenshot())
        self.btn_zumen = QPushButton("図→局面（画像）")
        self.btn_zumen.setToolTip("Webページ・棋書・論文などの盤面の図（画像）から局面を読み取ります。"
                                  "画像をコピーしてからボタンを押すか、画像ファイルを選びます（将棋ソフトの画面は対象外）")
        self.btn_zumen.clicked.connect(self.import_diagram)
        self.btn_zumen_out = QPushButton("局面→図（画像）")
        self.btn_zumen_out.setToolTip("いまの盤の局面を、棋書のような盤面の図（画像）にして、コピーまたは保存します。")
        self.btn_zumen_out.clicked.connect(self.export_diagram)
        self.btn_cap = QPushButton("画面を撮影→局面")
        self.btn_cap.setToolTip("このウィンドウを隠してから画面全体を撮影し、読み取ります（棋桜を全画面にしておく）")
        self.btn_cap.clicked.connect(self.capture_screen)
        self.btn_edit = QPushButton("編集モード")
        self.btn_edit.setCheckable(True)
        self.btn_edit.toggled.connect(self.toggle_edit)
        self.btn_tsumehai = QPushButton("詰将棋配置")
        self.btn_tsumehai.setToolTip("盤上は後手玉(5一)だけにして、残りの駒をすべて玉方(後手)の持ち駒にします（攻方の玉は除く）。そのまま編集モードで、駒を盤に置いて形を作れます")
        self.btn_tsumehai.clicked.connect(self.set_tsume_layout)
        self.btn_tsumehai.setVisible(False)   # 編集モードのときだけ表示
        btn_turn = QPushButton("手番切替")
        btn_turn.clicked.connect(self.toggle_turn)
        self.btn_mate = QPushButton("詰みを探す")
        self.btn_mate.setToolTip("詰将棋用：この局面の詰み手順を探します。詰将棋用エンジンが設定されていればそれを、無ければ通常のエンジンの詰み探索(go mate)を使います。止めるには右の「停止」")
        self.btn_mate.clicked.connect(self.search_mate)
        self.btn_kiei = QPushButton("棋慧で解く")
        self.btn_kiei.setToolTip("Komoringなどの外部エンジンを使わず、棋慧だけでこの詰将棋を解きます（短い手数から順に読むので、15手前後までが目安）。"
                                 "最短の手数・初手・変化まで調べます")
        self.btn_kiei.clicked.connect(self.solve_kiei)
        self.btn_mate_apply = QPushButton("詰み手順を盤へ")
        self.btn_mate_apply.setToolTip("「詰みを探す」で見つかった手順を、棋譜として盤に取り込みます（KIF保存・KIFコピーで残せます）")
        self.btn_mate_apply.setEnabled(False)
        self.btn_mate_apply.clicked.connect(self.apply_mate_line)
        self.btn_mate_check = QPushButton("手順検証")
        self.btn_mate_check.setToolTip("Komoringの手順に出てくる合駒が無駄合でないかを、すばやく確かめます（他の変化は調べません）")
        self.btn_mate_check.setEnabled(False)
        self.btn_mate_check.clicked.connect(lambda: self.verify_mate("line"))
        self.btn_mate_alt = QPushButton("詳細検討")
        self.btn_mate_alt.setToolTip("無駄合を除いたうえで、変化・非限定の手・合駒の扱いを詳しく調べます（時間がかかることがあります）")
        self.btn_mate_alt.setEnabled(False)
        self.btn_mate_alt.clicked.connect(lambda: self.verify_mate("alt"))
        self.btn_mate_apply_v = QPushButton("検証済み手順を盤へ")
        self.btn_mate_apply_v.setToolTip("「詳細検討」で直した（無駄合を除いた）手順を、変化も含めて棋譜として盤に取り込みます")
        self.btn_mate_apply_v.setEnabled(False)
        self.btn_mate_apply_v.clicked.connect(lambda: self.apply_mate_line(True))
        self.kh_ask_n, self.kh_ask_sec = 0, 0.0      # 検証中にKomoringへ聞いた回数と時間
        self.verified_pv = None
        self.verified_game = None            # 詳細検討の変化つき棋譜（分岐棋譜として盤へ送る）
        self.mate_report = None             # 詰み探索・検証の結果（盤を動かしても残す）: (棋譜の開始局面, HTML)
        self.last_mate = None

        # 盤の下の操作は、使う場面ごとのタブにまとめる（常に見えるのは「最初・戻る・進む…」の並びだけ）
        def page(rows):
            w = QWidget()
            g = QGridLayout(w)
            g.setContentsMargins(4, 6, 4, 4)
            g.setSpacing(6)
            for r, items in enumerate(rows):
                for c, it in enumerate(items):
                    if it is not None:
                        g.addWidget(it, r, c)
            g.setColumnStretch(8, 1)
            return w
        self.btn_shot.setText("スクショ→局面")
        self.btn_shot.setToolTip("コピーした画面の画像（スクリーンショット）から、棋桜の局面を読み取ります")
        self.btn_cap.setText("画面を撮影")
        self.tools = QTabWidget()
        self.tools.setDocumentMode(True)
        self.btn_watch = QPushButton("観戦モード")
        self.btn_watch.setCheckable(True)
        self.btn_watch.setToolTip("中継を見ながら、手が進むたびに評価値グラフを伸ばします。\n"
                                  "・中継サイトの「棋譜コピー」(KIF)でコピーするだけで、自動で読み込みます\n"
                                  "・盤で1手ずつ指しても、グラフが伸びます\n"
                                  "観戦用です。自分が対局中の局面の解析には使わないでください")
        self.btn_watch.toggled.connect(self.toggle_watch)
        self.watching = False
        self.orig_line = None               # 棋譜の途中から別の手を指したとき、元の手順を覚えておく
        self.tsume_shown = None             # 答えを盤に出した詰将棋（帯を残すため）
        self.live_evals = {}                # 検討した局面(SFEN)ごとの評価値。グラフが伸びていくのに使う
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._watch_tick)
        self.tools.addTab(page([kifu_btns, [self.btn_game, self.mode_box, self.btn_open_eval, self.btn_review],
                                [self.btn_watch]]), "棋譜・解析")
        self.tools.addTab(page([[self.btn_zumen, self.btn_zumen_out, self.btn_shot, self.btn_cap],
                                [self.btn_edit, btn_turn, self.btn_tsumehai]]), "局面を作る")
        self.tools.addTab(page([[self.btn_tsume, self.btn_mate, self.btn_kiei, self.btn_mate_apply, self.btn_mate_check, self.btn_mate_alt, self.btn_mate_apply_v]]), "詰将棋")
        self.tools.setMaximumHeight(160)
        self.tools.currentChanged.connect(lambda _i: self.update_tsume_banner())
        lv.addWidget(self.tools)
        lv.addWidget(self.game_label)
        self.boardw.positionEdited.connect(self.on_position_edited)
        self.sig.shot.connect(self.on_shot)
        self.sig.shot_err.connect(self.on_shot_err)

        # 右：検討結果と解説
        right = QWidget()
        right.setMinimumWidth(440)
        rv = QVBoxLayout(right)
        self.info = QLabel()
        self.info.setStyleSheet("font-weight:bold; font-size:14px;")
        rv.addWidget(self.info)
        self.book_label = QLabel()
        self.book_label.setWordWrap(True)
        self.book_label.setTextFormat(Qt.TextFormat.RichText)
        self.book_label.setStyleSheet("background:#eef5ff; padding:4px; border:1px solid #c5d8f5;")
        self.book_label.hide()
        self._book = None
        rv.addWidget(self.book_label)

        # 棋譜に付いていたコメント（KIFの「*」の行）。コメントのある手でだけ出る
        self.kif_comments, self.kif_comment_sfen, self.kif_comment_moves = {}, None, []
        self.comment_box = QTextBrowser()
        self.comment_box.setOpenExternalLinks(True)
        self.comment_box.setMaximumHeight(190)
        self.comment_box.setStyleSheet("background:#fffbe8;")
        self.comment_box.hide()
        rv.addWidget(self.comment_box)

        row = QHBoxLayout()
        self.btn_go = QPushButton("検討開始")
        self.btn_go.setProperty("role", "primary")
        self.btn_go.clicked.connect(lambda: self.request_analysis())
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setProperty("role", "stop")
        self.btn_stop.clicked.connect(self.stop_analysis)
        self.auto = QCheckBox("自動で検討")
        self.auto.setChecked(True)
        row.addWidget(self.btn_go)
        row.addWidget(self.btn_stop)
        row.addWidget(self.auto, 1)
        btn_set = QPushButton("設定…")
        btn_set.clicked.connect(self.open_settings)
        row.addWidget(btn_set)
        rv.addLayout(row)

        rv.addWidget(QLabel("エンジンの候補手（クリックで盤面に矢印）"))
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setMaximumHeight(210)
        self.list.currentRowChanged.connect(self.on_pick_cand)
        rv.addWidget(self.list)

        row2 = QHBoxLayout()
        self.btn_explain = QPushButton("解説する")
        self.btn_explain.setProperty("role", "primary")
        self.btn_explain.clicked.connect(self.explain)
        more = QPushButton("その他")
        mm = QMenu(more)
        mm.addAction("文章をコピー", self.copy_prompt)
        mm.addAction("保存した解説を開く…", self.open_saved)
        more.setMenu(mm)
        row2.addWidget(self.btn_explain, 1)
        row2.addWidget(more)
        rv.addLayout(row2)

        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("ここに解説が出ます")
        # 全局の結果（悪手・好手の一覧と講評）は別のタブに置き、局面を動かしても消えないようにする
        self.summary = QTextBrowser()
        self.summary.setOpenLinks(False)
        self.summary.setOpenExternalLinks(False)
        self.summary.anchorClicked.connect(self.on_summary_link)
        self.summary.setPlaceholderText("「全局を解析」をすると、悪手や好手の一覧がここに残ります（手数をクリックするとその局面へ移動）")
        self.tabs = QTabWidget()
        self.tabs.addTab(self.result, "この局面の解説")
        self.tabs.addTab(self.summary, "全局の結果")
        self.update_ai_labels()
        rv.addWidget(self.tabs, 1)
        self.status = QLabel("盤面の駒をクリックして動かせます（右クリックで選択解除）")
        self.status.setWordWrap(True)
        rv.addWidget(self.status)

        # 盤の左：棋譜（指し手の一覧）。クリックでその局面へ
        movepanel = QWidget()
        movepanel.setMinimumWidth(220)
        mv = QVBoxLayout(movepanel)
        mv.setContentsMargins(4, 4, 0, 4)
        self.move_title = QLabel("棋譜")
        self.move_title.setStyleSheet("font-weight:bold;")
        mv.addWidget(self.move_title)
        self.move_list = QListWidget()
        self.move_list.setStyleSheet("QListWidget{font-size:14px;} QListWidget::item{padding:1px 2px;}")
        self.move_list.currentRowChanged.connect(self.on_move_row)
        mv.addWidget(self.move_list, 1)
        self._ml_key = None

        sp = QSplitter()
        sp.addWidget(movepanel)
        sp.addWidget(left)
        sp.addWidget(right)
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 3)
        sp.setStretchFactor(2, 2)
        sp.setSizes([265, 650, 480])
        self.setCentralWidget(self._with_header(sp))

        QShortcut(QKeySequence("Left"), self, self.go_prev)
        QShortcut(QKeySequence("Right"), self, self.go_next)
        self.refresh(analyze=False)

    # ---------------------------------------------------------- 看板（窓の上のロゴ）
    def _with_header(self, body):
        """窓の上部に「棋慧」の看板を置く。書体は同梱の Yuji Syuku（SIL OFL）。無ければ明朝系で代用"""
        from PyQt6.QtGui import QFontDatabase
        from PyQt6.QtWidgets import QHBoxLayout as _H, QVBoxLayout as _V, QWidget as _W
        family = kiei_fonts()
        head = _W()
        head.setObjectName("kieiHead")
        head.setStyleSheet("#kieiHead { background:#2b2118; border-bottom:3px solid #b8892f; }")
        hl = _H(head)
        hl.setContentsMargins(16, 4, 16, 4)
        hl.setSpacing(14)
        logo = QLabel("棋慧")
        lf = QFont(family)
        lf.setPixelSize(38)
        logo.setFont(lf)
        logo.setStyleSheet("color:#f3e3bd;")
        en = QLabel("KIEI")
        ef = QFont(family)
        ef.setPixelSize(18)
        ef.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        en.setFont(ef)
        en.setStyleSheet("color:#b8892f;")
        sub = QLabel("将棋検討ツール　—　詰将棋・解説・棋譜")
        sf = QFont(family)
        sf.setPixelSize(14)
        sub.setFont(sf)
        sub.setStyleSheet("color:#c9b48a;")
        hl.addWidget(logo)
        hl.addWidget(en, 0, Qt.AlignmentFlag.AlignBottom)
        hl.addSpacing(8)
        hl.addWidget(sub, 0, Qt.AlignmentFlag.AlignBottom)
        hl.addStretch(1)
        wrap = _W()
        wl = _V(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        wl.addWidget(head)
        wl.addWidget(body, 1)
        return wrap

    # ---------------------------------------------------------- 局面の管理
    def rebuild_board(self):
        return core.board_from(self.start_sfen, self.moves[:self.cursor])

    def _on_hidden_graph_tab(self):
        """「局面を作る」「詰将棋」のタブでは評価値グラフを出さない。"""
        try:
            return self.tools.tabText(self.tools.currentIndex()) in ("局面を作る", "詰将棋")
        except Exception:
            return False

    def update_tsume_banner(self):
        """詰将棋モードのとき、目立つ帯と色つきのボタンで知らせる。"""
        try:
            t = self.tsume
            if t:
                p = t["prob"]
                self.tsume_banner.setText(f"◆ 詰将棋モード　{p.get('title', '')}　{p['steps']}手詰　先手（攻方）の王手の連続で詰ませてください")
                self.tsume_banner.show()
                self.graph.hide()                     # 詰将棋では評価値グラフを出さない
                self.btn_tsume.setStyleSheet("background:#d9480f; color:white; font-weight:bold;")
            else:
                shown = getattr(self, "tsume_shown", None)
                if shown and shown[1] == self.start_sfen:     # 答え・詰み手順を盤に出している間は、帯を残す
                    p = shown[0]
                    self.tsume_banner.setText(f"◆ 詰将棋　{p.get('title', '')}　{p['steps']}手詰　解答を表示中（▶キーで1手ずつ進められます）")
                    self.tsume_banner.show()
                    self.graph.hide()
                else:
                    self.tsume_banner.hide()
                    self.graph.setVisible(not self._on_hidden_graph_tab())
                self.btn_tsume.setStyleSheet("")
        except Exception:
            pass

    def refresh(self, analyze=True):
        self.update_tsume_banner()
        try:
            ol = self.orig_line
            self.btn_main.setVisible(bool(ol) and ol[0] == self.start_sfen and self.moves != ol[1] and not self.tsume)
        except Exception:
            pass
        self.gen += 1
        if self.tsume:
            analyze = False
        if self.analyzing:
            self.stop_analysis()
        self.analyzing = False
        self.cands, self.cands_final, self.explain_pending = [], False, False
        self.cur_board = self.rebuild_board()
        last = self.moves[self.cursor - 1] if self.cursor > 0 else None
        self.boardw.names = list(self.names)
        shown = [n for n in self.names if n not in ("先手", "後手")]
        self.setWindowTitle("棋慧" + (f"　▲{self.names[0]} 対 △{self.names[1]}" if shown else ""))
        self.boardw.set_position(self.cur_board, last)
        self.list.clear()
        self.result.clear()
        rep_ = getattr(self, "mate_report", None)       # 詰み探索・検証の結果は、盤を動かしても消さない
        if rep_ and rep_[0] == self.start_sfen:
            self.result.setHtml(rep_[1])
        turn = "先手" if self.cur_board.turn == shogi.BLACK else "後手"
        text = f"{self.cursor}手目まで　{turn}の手番"
        if safe(self.cur_board.is_checkmate):
            text += "　詰み"
        elif safe(self.cur_board.is_check):
            text += "　王手"
        hdr = self.kif_header_text()
        if hdr:
            text += "　" + hdr
        if self.tsume:
            text = f"【詰将棋】{self.tsume['prob']['steps']}手詰　{self.cursor}手目まで"
        self._info_base = text
        self.update_senkei()
        self.info.setText(text)
        ki = self.kif_info_here()
        self.info.setToolTip("\n".join(f"{k}：{v}" for k, v in ki) if ki else "")
        self.show_book()
        self.show_kif_comment()
        self.sync_eval_graph()
        self.refresh_move_list()
        if analyze and self.auto.isChecked() and not self.game_running and not safe(self.cur_board.is_checkmate):
            self.request_analysis()

    def kif_header_text(self):
        """読み込んだ棋譜のファイルに書かれていた戦型（KENTOが書いたもの／元の棋譜のもの）。"""
        kento, orig = self.kif_senkei
        if not (kento or orig) or self.start_sfen != self.kif_comment_sfen \
                or self.moves[:10] != self.kif_comment_moves[:10]:
            return ""
        s = f"棋譜の戦型: {kento or orig}"
        if kento and orig and orig != kento:
            s += f"（元の戦型: {orig}）"
        return s

    def senkei_for_save(self):
        """保存する棋譜に書く戦型。30手あたりの局面で判定し、確信が持てなければ空にする。"""
        if senkei is None or self.start_sfen != shogi.STARTING_SFEN or len(self.moves) < 20:
            return ""
        for ply in (34, 30, 38, 26, 42, 22):
            if ply > len(self.moves):
                continue
            try:
                r = senkei.classify(self.start_sfen, self.moves, ply)
            except Exception:
                r = None
            if r:
                return r.replace("（参考）", "")
        return ""

    def update_senkei(self):
        """戦型を盤の右上に出す。判定は裏で行い、画面は止めない"""
        if senkei is None:
            return
        ck = (tuple(self.moves[:self.cursor]), self.cursor, self.start_sfen)
        self._sk_seq += 1                      # 古い判定結果が後から届いても使わないための通し番号（検討の通し番号とは別）
        seq = self._sk_seq
        if ck in self._sk_cache:
            self.boardw.set_senkei(self._sk_cache[ck])
            return
        sfen, mvs, cur = self.start_sfen, list(self.moves[:self.cursor]), self.cursor
        # 同じ対局の前後に動いただけなら、判定が出るまで今のラベルをそのまま見せる（ちらつき防止）
        last = getattr(self, "_sk_last", None)
        same = last is not None and last[0] == sfen and (
            mvs[:len(last[1])] == last[1] or last[1][:len(mvs)] == mvs)
        if not same:
            self.boardw.set_senkei("")
        self._sk_last = (sfen, mvs)

        def work_sk():
            try:
                r = senkei.classify_sticky(sfen, mvs, cur)
            except Exception as e:
                senkei.log("classify error: " + repr(e))
                r = ""
            if r is not None:
                if len(self._sk_cache) > 500:
                    self._sk_cache.clear()
                self._sk_cache[ck] = r
                self.sig.senkei.emit(seq, r)
        threading.Thread(target=work_sk, daemon=True).start()

    def on_senkei_ready(self):
        self._sk_cache.clear()
        self.update_senkei()

    def on_senkei(self, seq, sk):
        if seq == self._sk_seq:
            self.boardw.set_senkei(sk)

    def _load_book(self):
        if self._book == "loading":
            return False
        if self._book is None:
            self._book = "loading"
            threading.Thread(target=self._load_book_bg, daemon=True).start()
            return False
        return self._book

    def _load_book_bg(self):
        book = False
        if True:
            if bookmod is not None:
                here = os.path.dirname(os.path.abspath(__file__))
                for p in (self.cfg.get("book_path"), os.path.join(here, "book.npz"), r"C:\kisen\book.npz"):
                    if p and os.path.isfile(p):
                        try:
                            book = bookmod.Book(p)
                        except Exception:
                            book = False
                        break
        self._book = book

    def show_book(self):
        """人間（将棋倶楽部24の高段者）が、この局面で指した手の割合を表示する"""
        bk = self._load_book()
        if not bk or self.start_sfen != shogi.STARTING_SFEN:
            self.book_label.hide()
            return
        try:
            rows = bk.lookup(self.cur_board)
        except Exception:
            rows = []
        total = sum(r[1] for r in rows)
        if total < 3:
            self.book_label.hide()
            return
        parts = []
        for usi, n, w, l in rows[:6]:
            try:
                name = core.move_ja(self.cur_board, usi)
            except Exception:
                name = usi
            wr = f"　勝率{round(100 * w / (w + l))}%" if (w + l) >= 5 else ""
            parts.append(f"{name}　{round(100 * n / total)}%（{n}局）{wr}")
        rest = total - sum(r[1] for r in rows[:6])
        if rest > 0:
            parts.append(f"その他　{round(100 * rest / total)}%")
        self.book_label.setText(f"<b>人間の定跡</b><br>" + "<br>".join(parts))
        self.book_label.show()

    def on_move_row(self, row):
        if row >= 0 and row != self.cursor and row <= len(self.moves):
            self.go_to_ply(row)

    def refresh_move_list(self):
        """盤の左の棋譜欄を作り直し（必要なときだけ）、今の手の行を選ぶ。"""
        try:
            ev = self.evals if (self.evals and len(self.evals) == len(self.moves) + 1) else None
            sw = self.swings if ev else {}
            gd = self.goods if ev else {}
            cms = self.current_kif_comments() if self.kif_comments else {}
            key = (self.start_sfen, tuple(self.moves), sum(1 for e in (ev or []) if e), len(sw or {}), len(gd or {}), len(self.matches if ev else {}), tuple(sorted(cms)))
            if key != self._ml_key:
                self._ml_key = key
                import re as _re
                from PyQt6.QtGui import QBrush
                from PyQt6.QtWidgets import QListWidgetItem
                n = len(self.moves)
                self.move_list.blockSignals(True)
                self.move_list.clear()
                first = "開始局面" + (" 💬" if 0 in cms else "")
                self.move_list.addItem(first)
                b = shogi.Board(self.start_sfen)
                prev = None
                black_first = (b.turn == shogi.BLACK)
                for i, usi in enumerate(self.moves, 1):
                    txt, prev = core._kif_move(b, usi, prev)
                    txt = _re.sub(r"\(\d\d\)$", "", txt)
                    side = "▲" if b.turn == shogi.BLACK else "△"
                    line = f"{i:>3} {side}{txt}"
                    e = ev[i] if ev else None
                    if e:
                        line += "  " + ("詰" if (e.get("mate") is not None or abs(e["v"]) >= core.MATE_VALUE - 1000)
                                        else f"{e['v']:+d}")
                    s = sw.get(i) if sw else None
                    g = gd.get(i) if gd else None
                    mt = self.matches.get(i) if ev else None
                    if mt is not None:
                        line += " " + {1: "◎", 2: "○", 3: "○", 0: "△"}[mt]
                    if s:
                        line += " " + s["grade"]
                    elif g:
                        line += " " + g["grade"]
                    if i in cms or (i == n and any(k > n for k in cms)):
                        line += " 💬"
                    it = QListWidgetItem(line)
                    if s:
                        col = {"??": "#c01818", "?": "#d0601a", "?!": "#8a6a10"}.get(s["grade"])
                        if col:
                            it.setForeground(QBrush(QColor(col)))
                    elif g:
                        it.setForeground(QBrush(QColor("#0f7a35" if g["grade"] == "!!" else "#2a8f47")))
                    self.move_list.addItem(it)
                    b.push(shogi.Move.from_usi(usi))
                self.move_list.blockSignals(False)
                nm = [x for x in self.names if x not in ("先手", "後手")]
                self.move_title.setText("棋譜　" + (f"{n}手" if n else "（指し手なし）"))
            self.move_list.blockSignals(True)
            self.move_list.setCurrentRow(min(self.cursor, self.move_list.count() - 1))
            self.move_list.blockSignals(False)
            self.move_list.scrollToItem(self.move_list.currentItem(), QListWidget.ScrollHint.PositionAtCenter)
        except Exception:
            pass

    def kif_comment_here(self):
        """今の局面に付いている棋譜コメント（なければ空）。指し手が棋譜と違っていたら空。"""
        try:
            c = self.cursor
            same = (self.kif_comments and self.start_sfen == self.kif_comment_sfen
                    and self.moves[:c] == self.kif_comment_moves[:c])
            if not same:
                return ""
            parts = []
            if c in self.kif_comments:
                parts.append(self.kif_comments[c])
            if c == len(self.kif_comment_moves) and len(self.moves) == c:
                # 「投了」など、指し手の後ろに付いたコメントも最後の局面で一緒に出す
                for k in sorted(self.kif_comments):
                    if k > c:
                        parts.append(self.kif_comments[k])
            return "\n\n".join(parts)
        except Exception:
            return ""

    def set_variations(self, game=None):
        """読み込んだ棋譜の枝分かれ（変化）を、選べるようにする。game=None で消す。"""
        self.variations = list(game.get("variations") or []) if game else []
        self.main_game = (list(game["moves"]), dict(game.get("comments") or {}), game["sfen"]) if game else None
        self.var_combo.blockSignals(True)
        self.var_combo.clear()
        if self.variations:
            self.var_combo.addItem(f"本手順（{len(game['moves'])}手）")
            for v in self.variations:
                self.var_combo.addItem(v["label"])
            self.var_widget.show()
        else:
            self.var_widget.hide()
        self.var_combo.blockSignals(False)

    def on_variation(self, idx):
        if not self.variations or self.main_game is None or idx < 0:
            return
        mm, mc, sfen = self.main_game
        if idx == 0:
            moves, comments, cur = list(mm), dict(mc), min(self.cursor, len(mm))
        else:
            v = self.variations[idx - 1]
            moves, comments, cur = v["prefix"] + v["moves"], dict(v["all_comments"]), v["from"] - 1
        self.start_sfen, self.moves, self.cursor = sfen, moves, cur
        self.kif_comments, self.kif_comment_sfen, self.kif_comment_moves = comments, sfen, list(moves)
        self.refresh()
        self.status.setText(self.var_combo.itemText(idx) + " に切り替えました（分かれ目の局面です。▶で進めてください）" if idx else "本手順に戻しました")

    def kif_info_here(self):
        """読み込んだ棋譜の対局情報（棋戦・日時・場所・持ち時間など）。別の棋譜に変わっていたら空。"""
        info = getattr(self, "kif_info", None)
        if not info or self.start_sfen != self.kif_comment_sfen or self.moves[:10] != self.kif_comment_moves[:10]:
            return []
        return info

    def show_kif_comment(self):
        """今の手に付いている棋譜コメントを出す。指し手が棋譜と違っていたら出さない。"""
        import html as _html
        import re as _re
        text = self.kif_comment_here()
        info = self.kif_info_here() if self.cursor == 0 else []
        if not text.strip() and not info:
            self.comment_box.hide()
            self.comment_box.clear()
            return
        parts = []
        if info:
            rows = "<br>".join(f"{_html.escape(k)}：{_html.escape(v)}" for k, v in info)
            parts.append(f"<b>📋 対局情報</b><br>{rows}")
        if text.strip():
            esc = _html.escape(text).replace("\n", "<br>")
            esc = _re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', esc)
            head = "対局前のコメント" if self.cursor == 0 else f"{self.cursor}手目のコメント"
            parts.append(f"<b>💬 {head}</b><br>{esc}")
        self.comment_box.setHtml("<br><br>".join(parts))
        self.comment_box.show()

    def on_user_move(self, usi):
        if self.tsume:
            self.tsume_user_move(usi)
            return
        if self.cursor < len(self.moves):
            if self.moves[self.cursor] == usi:           # 棋譜と同じ手なら、先へ進めるだけ（後ろを消さない）
                self.cursor += 1
                self.refresh()
                return
            if self.orig_line is None:                   # 棋譜と違う手：元の手順を覚えてから、枝分かれさせる
                self.orig_line = (self.start_sfen, list(self.moves), self.cursor)
        self.moves = self.moves[:self.cursor] + [usi]
        self.cursor += 1
        self.refresh()

    def back_to_main(self):
        """枝分かれする前の手順（元の棋譜）に戻る。分かれ目の局面まで戻して、▶で進められるようにする。"""
        if not self.orig_line:
            return
        sfen, moves, bp = self.orig_line
        self.start_sfen, self.moves, self.cursor = sfen, list(moves), bp
        self.refresh()
        self.status.setText("元の手順に戻しました（分かれ目の局面です。▶で進めてください）")

    def go_to_ply(self, ply):
        self.cursor = max(0, min(len(self.moves), int(ply)))
        self.refresh()

    def go_first(self):
        self.cursor = 0
        self.refresh()

    def go_prev(self):
        if self.tsume:
            self.cursor = max(0, (self.cursor - 1) // 2 * 2)
            self.refresh()
            return
        if self.cursor > 0:
            self.cursor -= 1
            self.refresh()

    def go_next(self):
        if self.tsume:
            self.cursor = min(len(self.moves) // 2 * 2, self.cursor + 2)
            self.refresh()
            return
        if self.cursor < len(self.moves):
            self.cursor += 1
            self.refresh()

    def go_last(self):
        self.cursor = len(self.moves)
        self.refresh()

    def flip(self):
        self.boardw.flipped = not self.boardw.flipped
        self.boardw.update()

    def reset_board(self):
        self.tsume = None
        self.set_variations(None)
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        self.start_sfen, self.moves, self.cursor = shogi.STARTING_SFEN, [], 0
        self.names = ["先手", "後手"]
        self.refresh()

    def paste_sfen(self):
        text, ok = QInputDialog.getText(self, "SFEN貼り付け", "SFENを貼り付けてください：")
        if not ok or not text.strip():
            return
        s = text.strip()
        for prefix in ("position sfen ", "sfen "):
            if s.startswith(prefix):
                s = s[len(prefix):]
        s = s.split(" moves ")[0].strip()
        try:
            shogi.Board(s)
        except Exception:
            QMessageBox.warning(self, "SFENを読めません", "SFENの形式を確認してください。")
            return
        self.tsume = None
        self.set_variations(None)
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        self.start_sfen, self.moves, self.cursor = s, [], 0
        self.refresh()

    def paste_auto(self):
        """クリップボードの文字がSFENか棋譜（KIF）かを自動で判別して読み込む。"""
        text = QApplication.clipboard().text()
        if not text.strip():
            QMessageBox.information(self, "案内", "クリップボードに文字がありません。SFENか棋譜（KIF）をコピーしてから押してください。")
            return
        kind, data = core.detect_clip(text)
        if kind == "sfen":
            self.tsume = None
            self.set_variations(None)
            self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
            self.start_sfen, self.moves = data["sfen"], list(data["moves"])
            self.cursor = len(self.moves)
            self.refresh()
            self.status.setText("SFENとして読み込みました" + (f"（指し手{len(self.moves)}手つき）" if self.moves else "（局面のみ）"))
        elif kind == "kif":
            self._apply_game(data, from_clip=True)
        elif kind == "error":
            QMessageBox.warning(self, "読み込めません", data)
        else:
            QMessageBox.information(self, "貼り付けできません", "SFENでもKIFでもありません。")

    def copy_sfen(self):
        QApplication.clipboard().setText(self.cur_board.sfen())
        self.status.setText("この局面のSFENをコピーしました")

    def open_kif(self):
        path, _ = QFileDialog.getOpenFileName(self, "棋譜を選ぶ", "", "KIF棋譜 (*.kif *.kifu);;すべて (*)")
        if not path:
            return
        self.open_kif_path(path)

    def open_kif_path(self, path):
        """棋譜ファイルを読み込む（メニューからも、.kifのダブルクリックからも使う）。"""
        try:
            game = core.load_kif(path)
            core.board_from(game["sfen"], game["moves"])
        except Exception as e:
            QMessageBox.warning(self, "棋譜を読めません", str(e))
            return
        self._apply_game(game)

    def current_kif_comments(self):
        """読み込んだ棋譜のコメントのうち、今の指し手の並びに合うもの。"""
        if not self.kif_comments or self.start_sfen != self.kif_comment_sfen:
            return {}
        n = 0
        for a, b in zip(self.moves, self.kif_comment_moves):
            if a != b:
                break
            n += 1
        out = {k: v for k, v in self.kif_comments.items() if k <= n}
        if n == len(self.moves) == len(self.kif_comment_moves):
            out.update({k: v for k, v in self.kif_comments.items() if k > n})
        return out

    def save_kif(self):
        """今の棋譜をKIFで保存する。全局解析の結果があれば、各手のコメントに評価値と読み筋（候補1）を入れる。"""
        import re as _re
        from datetime import datetime
        if not self.moves and shogi.Board(self.start_sfen).sfen() == shogi.STARTING_SFEN:
            QMessageBox.information(self, "案内", "保存する棋譜がありません。")
            return
        evals = self.evals if (self.evals and len(self.evals) == len(self.moves) + 1
                               and any(e is not None for e in self.evals)) else None
        base = f"{datetime.now():%Y%m%d}-{self.names[0]}-{self.names[1]}"
        base = _re.sub(r'[\\/:*?"<>|\s]+', "_", base)
        start = os.path.join(self.save_dir(), base + ".kif")
        path, filt = QFileDialog.getSaveFileName(
            self, "KIFで保存", start, "KIF（Shift-JIS・ふつうの棋譜ソフト向け）(*.kif);;KIFU（UTF-8）(*.kifu)")
        if not path:
            return
        utf8 = path.lower().endswith(".kifu") or ("KIFU" in (filt or "") and not path.lower().endswith(".kif"))
        if not _re.search(r"\.kifu?$", path, _re.I):
            path += ".kifu" if utf8 else ".kif"
        try:
            # 戦型：上書き保存では、ファイルに書かれている戦型を変えない。新規保存では判定した戦型を書く。
            sk_kento, sk_orig = "", self.kif_senkei[1]
            if os.path.isfile(path):
                try:
                    old_t = core._read_text(path)
                    m1 = _re.search(r"^戦型\(KENTO\)：(.*)$", old_t, _re.M)
                    m2 = _re.search(r"^戦型：(.*)$", old_t, _re.M)
                    sk_kento = m1.group(1).strip() if m1 else ""
                    sk_orig = m2.group(1).strip() if m2 else sk_orig
                    if not m1:
                        sk_kento = ""          # 古いファイルにはKENTOの戦型が無い：書き足さない
                except Exception:
                    pass
            else:
                sk_kento = self.kif_senkei[0] or self.senkei_for_save()
            vars_save, moves_s, comments_s = None, self.moves, self.current_kif_comments()
            if self.variations and self.main_game and self.start_sfen == self.main_game[2]:
                if self.var_combo.currentIndex() > 0:        # 変化を見ている：本手順＋全部の変化として保存する
                    moves_s, comments_s, evals = self.main_game[0], self.main_game[1], None
                    vars_save = self.variations
                elif self.moves == self.main_game[0]:
                    vars_save = self.variations
            text = core.export_kif(self.start_sfen, moves_s, self.names, comments_s,
                                   evals, self.swings if evals else None, goods=self.goods if evals else None,
                                   variations=vars_save,
                                   senkei_kento=sk_kento, senkei_orig=sk_orig,
                                   info=self.kif_info_here())
            with open(path, "wb") as f:
                f.write(core.kif_bytes(text, utf8))
        except Exception as e:
            QMessageBox.warning(self, "保存できません", str(e))
            return
        what = "評価値と読み筋つき" if evals else "解析結果なし（先に「全局を解析」をすると評価値と読み筋が入ります）"
        self.status.setText(f"KIFを保存しました（{len(self.moves)}手・{what}）：{path}")

    def copy_kif(self):
        """今の局面（指し手があれば手順つき）をKIFの文章にして、クリップボードに入れる。柿木将棋などに貼り付けて使う。"""
        try:
            vars_copy, moves_c, comments_c = None, self.moves, self.current_kif_comments()
            if self.variations and self.main_game and self.start_sfen == self.main_game[2]:
                if self.var_combo.currentIndex() > 0:        # 変化を見ている：本手順＋全部の変化として出す
                    moves_c, comments_c = self.main_game[0], self.main_game[1]
                    vars_copy = self.variations
                elif self.moves == self.main_game[0]:
                    vars_copy = self.variations
            text = core.export_kif(self.start_sfen, moves_c, self.names, comments_c,
                                   None, None, variations=vars_copy, info=self.kif_info_here())
        except Exception as e:
            QMessageBox.warning(self, "コピーできません", str(e))
            return
        QApplication.clipboard().setText(text)
        n = len(self.moves)
        self.status.setText(f"KIFをコピーしました（{n}手）。柿木将棋などに貼り付けてください" if n
                            else "いまの局面（初形）をKIFでコピーしました。柿木将棋などに貼り付けてください")

    def paste_kif(self):
        """クリップボードのKIF（指し手つき、または盤面の図だけ）を読み込む。"""
        text = QApplication.clipboard().text()
        if not text.strip():
            QMessageBox.information(self, "案内", "クリップボードに文字がありません。KIFをコピーしてから押してください。")
            return
        try:
            game = core.load_kif_text(text)
            core.board_from(game["sfen"], game["moves"])
        except Exception as e:
            QMessageBox.warning(self, "棋譜を読めません", str(e))
            return
        self._apply_game(game, from_clip=True)

    def _apply_game(self, game, from_clip=False):
        self.tsume = None
        self.set_variations(game)
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        self.start_sfen, self.moves, self.names = game["sfen"], game["moves"], game["names"]
        self.kif_comments = dict(game.get("comments") or {})
        self.kif_comment_sfen, self.kif_comment_moves = game["sfen"], list(game["moves"])
        self.kif_senkei = (game.get("senkei_kento") or "", game.get("senkei_orig") or "")
        self.kif_info = list(game.get("info") or [])
        self.cursor = 0 if (from_clip and not self.moves) or self._is_problem(game) else len(self.moves)
        self.refresh()
        src = "クリップボード" if from_clip else "棋譜"
        if self.moves:
            extra = f"　コメント{len(self.kif_comments)}か所あり" if self.kif_comments else ""
            self.status.setText(f"{len(self.moves)}手の{src}を読み込みました（◀▶キーで前後に動かせます）{extra}")
        else:
            self.status.setText(f"{src}から局面だけ読み込みました（指し手はありません）")

    @staticmethod
    def _is_problem(game):
        """詰将棋の棋譜（先手玉が無い初形）は、最初の局面を見せる。"""
        try:
            return shogi.Board(game["sfen"]).king_squares[shogi.BLACK] is None
        except Exception:
            return False


    # ---------------------------------------------------------- 詰将棋 解答モード
    def _tsume_state_path(self):
        return os.path.join(HERE, "tsume_state.json")

    def _tsume_state(self):
        if getattr(self, "_tsume_st", None) is None:
            try:
                with open(self._tsume_state_path(), encoding="utf-8") as fh:
                    st = json.load(fh)
            except Exception:
                st = {}
            st.setdefault("solved", {})
            self._tsume_st = st
        return self._tsume_st

    def _tsume_save(self):
        try:
            st = self._tsume_state()
            with open(self._tsume_state_path(), "w", encoding="utf-8") as fh:
                json.dump(st, fh, ensure_ascii=False)
        except Exception:
            pass

    def open_tsume(self):
        if tsume_mode is None:
            QMessageBox.warning(self, "詰将棋", "tsume_mode.py が見つかりません。")
            return
        if self.tsume_dlg is None:
            dbpath = os.path.join(HERE, tsume_mode.DB_NAME)
            first = not os.path.exists(dbpath)
            self.tsume_dlg = tsume_mode.TsumeDialog(self, dbpath, self._tsume_state())
            if first and os.path.isdir(tsume_mode.DEFAULT_FOLDER):
                r = QMessageBox.question(self, "詰将棋データベース",
                                         f"詰将棋のデータベースがまだありません。\n{tsume_mode.DEFAULT_FOLDER}\nの問題を取り込みますか？")
                if r == QMessageBox.StandardButton.Yes:
                    self.tsume_dlg.import_path(tsume_mode.DEFAULT_FOLDER)
        self.tsume_dlg.show()
        self.tsume_dlg.raise_()
        self.tsume_dlg.activateWindow()

    def tsume_start(self, p):
        self.tsume = {"prob": p, "line": p["line"], "busy": False, "hint": 0, "pending": None}
        self.mate_report = None
        self.tsume_seq += 1
        self.set_variations(None)
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        self.start_sfen, self.moves, self.cursor = p["sfen"], [], 0
        self.names = ["先手", "後手"]
        self.kif_comments, self.kif_comment_sfen, self.kif_comment_moves = {}, p["sfen"], []
        self.kif_senkei = ("", "")
        self.boardw.flipped = False
        self.refresh()
        self.result.clear()
        self.status.setText(f"{p['steps']}手詰：先手（攻方）の王手の連続で、後手玉を詰ませてください")

    def tsume_exit(self):
        self.tsume = None
        self.tsume_seq += 1
        self.status.setText("詰将棋モードを終えました")
        self.refresh(analyze=False)

    def tsume_reset(self):
        if not self.tsume:
            return
        self.tsume["busy"] = False
        self.tsume["hint"] = 0
        self.tsume_seq += 1
        self.moves, self.cursor = [], 0
        self.refresh()
        self.status.setText("初形に戻しました")

    def tsume_user_move(self, usi):
        t = self.tsume
        if t["busy"]:
            return
        if self.cur_board.turn != shogi.BLACK:
            self.status.setText("いまは玉方（後手）の番です。「初形に戻す」か「1手戻る」で攻方の番に戻してください")
            return
        t["busy"] = True
        t["hint"] = 0
        self.tsume_seq += 1
        seq = self.tsume_seq
        moves = list(self.moves[:self.cursor])
        p = t["prob"]
        line = t["line"]
        self.status.setText("判定中…")

        def work():
            res = tsume_mode.judge(p["sfen"], moves, usi, p["steps"], line, self._tsume_emate, p.get("tree"),
                                    self._tsume_kh if self._tsume_path() else None)
            self.sig.tsume_judged.emit(seq, res, usi)
        threading.Thread(target=work, daemon=True).start()

    def on_tsume_judged(self, seq, res, usi):
        t = self.tsume
        if not t or seq != self.tsume_seq:
            return
        t["busy"] = False
        if not res["ok"]:
            self.status.setText("× " + res["msg"])
            return
        self.moves = self.moves[:self.cursor] + [usi]
        self.cursor += 1
        self.refresh()
        if res["done"]:
            self._tsume_solved()
            return
        if res.get("fail"):
            self.status.setText(f"× 失敗：{t['prob']['steps']}手以内に詰ませられませんでした。「初形に戻す」でやり直せます")
            return
        if res["reply"]:
            self.status.setText("玉方が応じています…")
            t["busy"] = True
            n = len(self.moves)
            reply = res["reply"]

            def go():
                if self.tsume is t and len(self.moves) == n:
                    t["busy"] = False
                    self.moves.append(reply)
                    self.cursor = len(self.moves)
                    self.refresh()
                    self.status.setText("玉方が応じました。次の一手を指してください")
            QTimer.singleShot(450, go)
        else:
            self.status.setText("玉方の応手を決められませんでした。「初形に戻す」でやり直してください")

    def _tsume_solved(self):
        t = self.tsume
        p = t["prob"]
        st = self._tsume_state()
        st["solved"][p["id"]] = True
        self._tsume_save()
        if self.tsume_dlg:
            self.tsume_dlg.mark_solved(p)
        self.status.setText(f"◎ 正解！　{p['steps']}手詰を解きました。「次の問題」で続けられます")
        try:
            self.result.setPlainText("正解！\n手順：" + core.pv_ja(core.board_from(self.start_sfen, []), self.moves, 40))
        except Exception:
            pass

    def _tsume_path(self):
        p = self.cfg.get("tsume_engine_path", None)
        if p is None:
            p = _default_tsume_engine()
        return p if p and os.path.exists(p) else ""

    def close_tsume_engine(self):
        eng, self.tsume_eng = self.tsume_eng, None
        if eng:
            try:
                eng.stop()
                eng.close()
            except Exception:
                pass
        eng2, self.tsume_oeng = getattr(self, "tsume_oeng", None), None
        if eng2:
            try:
                eng2.stop()
                eng2.close()
            except Exception:
                pass

    def _tsume_kh(self, sfen, ms=None):
        """詰将棋専用エンジン(KomoringHeights)の詰み探索。sfenは攻方番。戻り値 (状態, 手順)。
        状態: mate / nomate / timeout / error。攻方の玉が無い局面は、そのまま渡す（だめなら玉を補って再挑戦）。"""
        ms = int(ms) if ms else int(self.cfg.get("tsume_sec", 5)) * 1000
        path = self._tsume_path()
        if not path:
            return "error", []
        tries = [sfen]
        try:
            alt = core.mate_king_candidates(sfen, 1)[0][0]
            if alt != sfen:
                tries.append(alt)
        except Exception:
            pass
        last = ("error", [])
        t_start = time.time()
        for s in tries:
            for attempt in (0, 1):
                try:
                    with self.tsume_lock:
                        eng = self.tsume_eng
                        dead = eng is None or eng.proc is None or eng.proc.poll() is not None
                        if dead:
                            self.close_tsume_engine()
                            eng = core.UsiEngine(path, {"USI_Hash": 256})
                            eng.start()
                            self.tsume_eng = eng
                        state, pv, _n = eng.mate(s, ms)
                    if state in ("mate", "nomate", "timeout"):
                        self._tsume_log(sfen, state, len(pv or []), time.time() - t_start)
                        return state, pv
                    last = (state, pv)
                    break
                except (OSError, RuntimeError, TimeoutError):
                    self.close_tsume_engine()
                    if attempt == 1:
                        break
        return last

    def _kh_oracle(self, sfen):
        """棋慧の検証から呼ばれる：局面（攻方番）が普通のルールで詰むかを、KomoringHeightsに聞く。
        戻り値 1=詰む / -1=詰まない / 0=分からない。
        検証専用のエンジン（ハッシュ小さめ）を別に起動して使う（「詰みを探す」のエンジンとは別）。"""
        t0 = time.time()
        res, state = 0, "error"
        try:
            path = self._tsume_path()
            if not path:
                return 0
            tries = [sfen]
            try:
                alt = core.mate_king_candidates(sfen, 1)[0][0]
                if alt != sfen:
                    tries.append(alt)
            except Exception:
                pass
            for s in tries:
                with self.tsume_olock:
                    eng = getattr(self, "tsume_oeng", None)
                    if eng is None or eng.proc is None or eng.proc.poll() is not None:
                        eng = core.UsiEngine(path, {"USI_Hash": 16})
                        eng.start()
                        self.tsume_oeng = eng
                    state, _pv, _n = eng.mate(s, self.kh_ask_ms)
                if state in ("mate", "nomate", "timeout"):
                    break
            res = 1 if state == "mate" else (-1 if state == "nomate" else 0)
            return res
        except Exception:
            return 0
        finally:
            dt = time.time() - t0
            self.kh_ask_n += 1
            self.kh_ask_sec += dt
            key = "mate" if res > 0 else ("nomate" if res < 0 else "other")
            c = self.kh_ask_by.setdefault(key, [0, 0.0])
            c[0] += 1
            c[1] += dt

    def _tsume_log(self, sfen, state, n, sec):
        """どの局面で何秒かかったかを kento_tsume_log.txt に記録する（遅いときの原因調べ用）。"""
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "kento_tsume_log.txt"), "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%H:%M:%S}\t{sec:.2f}秒\t{state}\t{n}手\t{sfen}\n")
        except Exception:
            pass

    def _tsume_emate(self, sfen):
        """エンジンの詰み探索（攻方に玉が無いときは補う）。戻り値 (状態, 手順)。"""
        if self._tsume_path():
            st, pv = self._tsume_kh(sfen)
            if st in ("mate", "nomate", "timeout"):
                return st, pv
        try:
            ms = min(int(self.cfg.get("mate_sec", 60)), 15) * 1000 or 15000
            s = core.mate_king_candidates(sfen, 1)[0][0]
            for attempt in (0, 1):
                try:
                    with self.engine_lock:
                        eng = self._get_engine()
                        state, pv, _n = eng.mate(s, ms)
                    return state, pv
                except (OSError, RuntimeError):
                    self.close_engine()              # エンジンが落ちていた：起動し直して1回だけやり直す
                    if attempt == 1:
                        raise
        except Exception:
            self.close_engine()
        return "error", []

    def _tsume_need_line(self, then):
        """正解手順を用意して then() を呼ぶ。無ければソルバーで解く（時間がかかる）。"""
        t = self.tsume
        if t["line"]:
            then()
            return
        p = t["prob"]
        self.status.setText("エンジンで解いています…（少し時間がかかります）")
        t["pending"] = then
        seq = self.tsume_seq

        def work():
            ln = tsume_mode.engine_line(p["sfen"], p["steps"], self._tsume_emate)
            if not ln:
                ln = tsume_mode.solve_line(p["sfen"], p["steps"])
            self.sig.tsume_line.emit(seq, ln)
        threading.Thread(target=work, daemon=True).start()

    def on_tsume_line(self, seq, line):
        t = self.tsume
        if not t or seq != self.tsume_seq:
            return
        if not line:
            self.status.setText("エンジンでも解けませんでした（時間切れか、エンジン未設定）")
            return
        t["line"] = line
        then, t["pending"] = t["pending"], None
        if then:
            then()

    def tsume_hint(self):
        if not self.tsume:
            self.status.setText("先に問題を出題してください")
            return
        self._tsume_need_line(self._tsume_hint2)

    def _tsume_hint2(self):
        t = self.tsume
        line = t["line"]
        cur = list(self.moves[:self.cursor])
        idx = len(cur)
        if idx >= len(line) or cur != line[:idx]:
            self.status.setText("手順から外れています。「初形に戻す」からやり直してください")
            return
        usi = line[idx]
        t["hint"] += 1
        if t["hint"] == 1:
            sq = usi[2:4]
            self.status.setText(f"ヒント：次の手は {sq[0]}{'一二三四五六七八九'[ord(sq[1]) - 97]} に動かします")
        else:
            self.status.setText("ヒント：次の手は " + core.move_ja(self.cur_board, usi))

    def tsume_answer(self):
        if not self.tsume:
            self.status.setText("先に問題を出題してください")
            return
        self._tsume_need_line(self._tsume_answer2)

    def _tsume_answer2(self):
        t = self.tsume
        line = list(t["line"])
        self.tsume = None
        self.tsume_shown = (t["prob"], self.start_sfen)        # 答えを見たあとも、詰将棋の画面だと分かるようにする
        self.tsume_seq += 1
        self.moves, self.cursor = line, 0
        self.refresh(analyze=False)
        try:
            txt = core.pv_ja(core.board_from(self.start_sfen, []), line, 40)
        except Exception:
            txt = " ".join(line)
        self.result.setPlainText("答え：" + txt)
        self.status.setText("答えを盤に出しました（▶キーで1手ずつ進められます）。次の問題は一覧から選んでください")

    # ---------------------------------------------------------- スクショ取り込み・編集
    def capture_screen(self):
        """このウィンドウを隠し、少し待ってから画面全体を撮影して読み取る。"""
        if self.cfg.get("screenshot_mode") == "gemini" and not self.cfg.get("gemini_api_key"):
            QMessageBox.information(self, "案内", "Gemini APIキーが未設定です。「設定…」で入力してください。")
            return
        screens = QApplication.screens()
        idx = self.cfg.get("capture_screen")
        if isinstance(idx, int) and 0 <= idx < len(screens):
            targets = [screens[idx]]
        elif self.cfg.get("screenshot_mode") == "gemini":
            targets = [self.screen() or screens[0]]
        else:
            targets = list(screens)          # 全モニターを撮って、棋桜が写っているものを自動で選ぶ
        delay = int(self.cfg.get("capture_delay_ms", 1500))
        self.showMinimized()

        def shoot():
            pngs = [p for p in (screen_png(s, 1800 if self.cfg.get("screenshot_mode") == "gemini" else None)
                                for s in targets) if p]
            self.showNormal()
            self.activateWindow()
            if not pngs:
                QMessageBox.warning(self, "撮影できません", "画面を撮影できませんでした。")
                return
            self.import_screenshot(pngs)

        QTimer.singleShot(delay, shoot)

    def import_screenshot(self, png=None):
        if self.cfg.get("screenshot_mode") == "gemini" and not self.cfg.get("gemini_api_key"):
            QMessageBox.information(self, "案内", "Gemini APIキーが未設定です。「設定…」で入力してください。")
            return
        if not png:
            png = clipboard_png(1800 if self.cfg.get("screenshot_mode") == "gemini" else 100000)
        pngs = png if isinstance(png, list) else [png]      # 複数のモニターの画像が来たら、読めたものを使う
        if pngs[0] is None:
            QMessageBox.information(
                self, "案内", "クリップボードに画像がありません。\nWindowsなら「Win＋Shift＋S」で盤面の範囲を選ぶと、"
                "画像がコピーされます。そのあと、もう一度このボタンを押してください。")
            return
        self.btn_shot.setEnabled(False)
        self.status.setText("スクショを読み取り中…")
        cfg = dict(self.cfg)

        def work():
            first_err = None
            for p in pngs:
                try:
                    self.sig.shot.emit(core.read_screenshot(p, cfg))
                    return
                except Exception as e:
                    first_err = first_err or str(e)
            self.sig.shot_err.emit(first_err or "読み取れませんでした")

        threading.Thread(target=work, daemon=True).start()

    def export_diagram(self):
        """いま盤にある局面を、棋書のような盤面の図（画像）にして、コピーまたは保存する。"""
        from PyQt6.QtGui import QImage
        board = self.boardw.board
        cell = 64
        mx, my = int(cell * 2.0), int(cell * 1.2)
        W, H = int(9 * cell + 2 * mx), int(9 * cell + 2 * my)
        img = QImage(W, H, QImage.Format.Format_RGB32)
        img.fill(QColor("white"))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = QColor("#111111")
        p.setPen(QPen(ink, 2.0))
        bx, by = mx, my
        for i in range(10):
            lw = 3.0 if i in (0, 9) else 1.4
            p.setPen(QPen(ink, lw))
            p.drawLine(QPointF(bx, by + i * cell), QPointF(bx + 9 * cell, by + i * cell))
            p.drawLine(QPointF(bx + i * cell, by), QPointF(bx + i * cell, by + 9 * cell))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        for (cx, cy) in [(3, 3), (6, 3), (3, 6), (6, 6)]:
            p.drawEllipse(QPointF(bx + cx * cell, by + cy * cell), 3.2, 3.2)
        fam = kiei_fonts()
        # 筋・段の数字
        f = QFont(fam)
        f.setPixelSize(int(cell * 0.30))
        p.setFont(f)
        p.setPen(ink)
        for i in range(9):
            p.drawText(QRectF(bx + i * cell, by - 0.55 * cell, cell, 0.45 * cell), Qt.AlignmentFlag.AlignCenter, core.FILE_ZEN[9 - i])
            p.drawText(QRectF(bx + 9 * cell + 6, by + i * cell, 0.5 * cell, cell), Qt.AlignmentFlag.AlignCenter, core.RANK_KAN[i + 1])

        def glyph(cx, cy, size, text, rot, red=False):
            p.save()
            p.translate(cx, cy)
            if rot:
                p.rotate(180)
            ff = QFont(fam)
            ff.setPixelSize(int(size))
            p.setFont(ff)
            p.setPen(QColor("#111111"))
            rect = QRectF(-size, -size, 2 * size, 2 * size)
            d = max(0.4, 0.012 * size)
            for dx, dy in ((-d, 0), (d, 0), (0, -d), (0, d)):
                p.drawText(rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, text)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            p.restore()

        for sq in range(81):
            pc = board.piece_at(sq)
            if pc is None:
                continue
            col, row = sq % 9, sq // 9              # 左端が9筋、上端が一段目
            glyph(bx + (col + 0.5) * cell, by + (row + 0.52) * cell, cell * 0.68,
                  core.BOARD_NAME[pc.symbol().upper()],
                  pc.color == shogi.WHITE)
        # 持ち駒：盤の左右にたて書き（右が先手・正立、左が後手・逆さ）。2枚以上は駒の下に算用数字
        order = [shogi.ROOK, shogi.BISHOP, shogi.GOLD, shogi.SILVER, shogi.KNIGHT, shogi.LANCE, shogi.PAWN]
        for color, cx0 in ((shogi.BLACK, bx + 9 * cell + 1.25 * cell), (shogi.WHITE, bx - 1.25 * cell)):
            items = []
            for pt in order:
                n = board.pieces_in_hand[color].get(pt, 0)
                if n > 0:
                    items.append((shogi.Piece(pt, shogi.BLACK).symbol().upper(), n))
            if not items:
                continue
            rot = color == shogi.WHITE
            p.save()
            p.translate(cx0, by + 4.5 * cell)
            if rot:
                p.rotate(180)
            y = -4.5 * cell + 0.35 * cell
            for sym, n in items:
                glyph(0, y, cell * 0.5, core.BOARD_NAME[sym], False)
                y += 0.55 * cell
                if n > 1:
                    glyph(0, y - 0.02 * cell, cell * 0.38, str(n), False)
                    y += 0.45 * cell
            p.restore()
        p.end()

        mb = QMessageBox(self)
        mb.setWindowTitle("局面→図（画像）")
        mb.setText("いまの局面を、盤面の図（画像）にします。どうしますか？")
        b_clip = mb.addButton("コピーする", QMessageBox.ButtonRole.AcceptRole)
        b_file = mb.addButton("ファイルに保存", QMessageBox.ButtonRole.ActionRole)
        mb.addButton("やめる", QMessageBox.ButtonRole.RejectRole)
        mb.exec()
        c = mb.clickedButton()
        if c is b_clip:
            QApplication.clipboard().setImage(img)
            self.status.setText("盤面の図をコピーしました。メモ帳や文書・掲示板などに貼り付けられます")
        elif c is b_file:
            path, _ = QFileDialog.getSaveFileName(self, "図を保存", "局面図.png", "PNG画像 (*.png)")
            if path:
                if not path.lower().endswith(".png"):
                    path += ".png"
                if img.save(path):
                    self.status.setText("盤面の図を保存しました：" + path)
                else:
                    QMessageBox.warning(self, "保存できません", "保存に失敗しました。")

    def import_diagram(self):
        """盤面の図（画像）から局面を読み取る。クリップボードに画像があればそれを、無ければ画像ファイルを選ぶ。"""
        from PyQt6.QtGui import QImage
        img = QApplication.clipboard().image()
        if img is not None and not img.isNull():
            mb = QMessageBox(self)
            mb.setWindowTitle("図の読み込み")
            mb.setText("コピーしてある画像があります。どちらを読み取りますか？")
            b_clip = mb.addButton("コピーした画像", QMessageBox.ButtonRole.AcceptRole)
            b_file = mb.addButton("ファイルを選ぶ", QMessageBox.ButtonRole.ActionRole)
            mb.addButton("やめる", QMessageBox.ButtonRole.RejectRole)
            mb.exec()
            c = mb.clickedButton()
            if c is b_file:
                img = None
            elif c is not b_clip:
                return
        if img is None or img.isNull():
            path, _ = QFileDialog.getOpenFileName(self, "盤面の図（画像）を選ぶ", "", "画像 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;すべて (*)")
            if not path:
                return
            img = QImage(path)
            if img.isNull():
                QMessageBox.warning(self, "読み込めません", "画像として開けませんでした。")
                return
        try:
            import numpy as np
            import zumen
            img = img.convertToFormat(QImage.Format.Format_RGB888)
            w, h = img.width(), img.height()
            buf = img.constBits()
            buf.setsize(img.sizeInBytes())
            arr = np.frombuffer(buf, np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
            bgr = arr[:, :, ::-1].copy()
            res = zumen.read_diagram(bgr)
            shogi.Board(res["sfen"])
        except Exception as e:
            QMessageBox.warning(self, "図を読み取れません", str(e))
            return
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        self.start_sfen, self.moves, self.cursor, self.names = res["sfen"], [], 0, ["先手", "後手"]
        self.tsume = None
        self.refresh(analyze=False)
        if res["notes"]:
            QMessageBox.information(self, "読み取り結果の確認", "局面を読み込みました。次の点を確認してください。\n\n・"
                                    + "\n・".join(res["notes"]) + "\n\n間違いがあれば「編集モード」で直せます。")
        self.status.setText("図から局面を読み取りました。駒や持ち駒が合っているか確認してください（手番は先手番にしてあります）")

    def on_shot(self, result):
        self.btn_shot.setEnabled(True)
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        self.start_sfen, self.moves, self.cursor, self.names = result["sfen"], [], 0, ["先手", "後手"]
        self.refresh(analyze=not self.btn_edit.isChecked())
        lines = ["・" + t for _, t in result["messages"]]
        if any(lv in ("error", "warn") for lv, _ in result["messages"]):
            QMessageBox.warning(self, "読み取り結果の確認",
                                "局面を読み込みました。次の点を確認してください。\n\n" + "\n".join(lines)
                                + "\n\n間違いがあれば「編集モード」で直せます。")
        self.status.setText("読み取り完了：" + (lines[-1][1:] if lines else ""))

    def on_shot_err(self, msg):
        self.btn_shot.setEnabled(True)
        self.status.setText("読み取りに失敗：" + msg)
        QMessageBox.warning(self, "スクショを読み取れません", msg)

    def toggle_edit(self, checked):
        self.boardw.edit_mode = checked
        self.btn_tsumehai.setVisible(checked)
        self.boardw.update()
        if checked:
            self.status.setText("編集モード：駒をドラッグして移動（持ち駒の帯にも落とせます）／右クリックで成り→先後入れ替え→…と切り替え（Shift＋右クリックでメニュー）／空きマスや点線の帯をクリックで駒・持ち駒を追加")
        else:
            self.refresh()

    def set_tsume_layout(self):
        """柿木将棋の「詰将棋用配置」：盤上は後手玉(5一)のみ、残りの駒は全部玉方の持ち駒。攻方の玉は無し。"""
        sfen = "4k4/9/9/9/9/9/9/9/9 b 2r2b4g4s4n4l18p 1"
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        self.start_sfen, self.moves, self.cursor, self.names = sfen, [], 0, ["先手", "後手"]
        self.btn_edit.setChecked(True)
        self.refresh(analyze=False)
        self.status.setText("詰将棋配置にしました。持ち駒の駒をドラッグして盤に置き、形を作ってください（攻方の持駒は、先手側の帯をクリックして追加できます）")

    def on_position_edited(self, sfen):
        try:
            shogi.Board(sfen)
        except Exception:
            return
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        self.start_sfen, self.moves, self.cursor, self.names = sfen, [], 0, ["先手", "後手"]
        self.refresh(analyze=not self.btn_edit.isChecked())

    def toggle_turn(self):
        cells, hands, turn = core.board_to_model(self.cur_board)
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        self.start_sfen, self.moves, self.cursor = core.model_to_sfen(cells, hands, 1 - turn), [], 0
        self.refresh(analyze=not self.btn_edit.isChecked())

    # ---------------------------------------------------------- エンジン検討
    def _get_engine(self):
        if self.engine is not None:
            try:
                dead = self.engine.proc is None or self.engine.proc.poll() is not None
            except Exception:
                dead = True
            if dead:                       # エンジンが落ちていたら、捨てて起動し直す
                self.close_engine()
        if self.engine is None:
            path = self.cfg.get("engine_path", "")
            if not path:
                raise RuntimeError("エンジンが登録されていません。右上の「設定…」から登録してください。")
            eng = core.UsiEngine(path, self.cfg.get("engine_options", {}))
            eng.start()
            self.engine = eng
        return self.engine

    def close_engine(self):
        eng, self.engine = self.engine, None
        if eng:
            eng.stop()
            eng.close()

    @staticmethod
    def _no_king(board):
        """玉が片方でも盤上に無い局面（詰将棋の形）。通常のエンジンは、こういう局面を読めず落ちてしまう。"""
        try:
            return board.king_squares[shogi.BLACK] is None or board.king_squares[shogi.WHITE] is None
        except Exception:
            return False

    def request_analysis(self, explain_after=False):
        if self._no_king(self.cur_board):
            self.analyzing = False
            self.cands, self.cands_final = [], False
            self.status.setText("玉が盤上に1枚しかない局面（詰将棋の形）です。通常の検討はできません。「詰将棋」タブの「詰みを探す」を使ってください")
            return
        if safe(self.cur_board.is_checkmate):
            self.status.setText("詰みの局面です")
            return
        if self.analyzing and self.engine:
            self.engine.stop()
        self.gen += 1
        gen = self.gen
        self.analyzing = True
        self.cands_final = False
        self.explain_pending = explain_after
        sfen = self.cur_board.sfen()
        ms, mpv = int(self.cfg["movetime_sec"]) * 1000, int(self.cfg["multipv"])
        self.status.setText("エンジンで検討中…（初回はエンジンの起動に時間がかかります）")

        def work():
            try:
                for attempt in (0, 1):
                    try:
                        with self.engine_lock:
                            if gen != self.gen:
                                return
                            eng = self._get_engine()
                            cands, _ = eng.analyze(sfen, ms, mpv, on_info=lambda c: self.sig.cands.emit(gen, c, False))
                        break
                    except (OSError, RuntimeError):
                        if attempt == 1:
                            raise
                        self.close_engine()          # エンジンが落ちていた：起動し直して1回だけやり直す
                self.sig.cands.emit(gen, cands, True)
            except Exception as e:
                self.sig.error.emit(gen, str(e))

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- 詰み探索（詰将棋）
    def search_mate(self):
        if safe(self.cur_board.is_checkmate):
            self.status.setText("すでに詰みの局面です")
            return
        if self.analyzing and self.engine:
            self.engine.stop()
        self.gen += 1                      # 動いている通常の検討の結果は捨てる
        self.analyzing = False
        sfen = self.cur_board.sfen()
        ms = int(self.cfg.get("mate_sec", 60)) * 1000
        board = shogi.Board(sfen)
        compare = self.moves if (self.cursor == 0 and self.moves and shogi.Board(self.start_sfen).sfen() == sfen) else None
        self.btn_mate.setEnabled(False)
        self.status.setText("詰み探索中…（右の「停止」で中止。初回はエンジンの起動に時間がかかります）")

        def work():
            t0 = time.time()
            try:
                if self._tsume_path():
                    # 詰将棋専用エンジン(KomoringHeights)で探す。攻方の玉が無い局面もそのまま渡せる
                    got = None
                    try:
                        with self.tsume_lock:
                            eng = self.tsume_eng
                            dead = eng is None or eng.proc is None or eng.proc.poll() is not None
                            if dead:
                                self.close_tsume_engine()
                                eng = core.UsiEngine(self._tsume_path(), {"USI_Hash": 512})
                                eng.start()
                                self.tsume_eng = eng
                            state, pv, n = eng.mate(sfen, ms)
                        if state == "mate" and pv and tsume_mode is not None:
                            try:
                                pv = tsume_mode.normalize_pv(sfen, pv, self._tsume_kh)   # 合駒より駒を取る手を優先
                            except Exception:
                                pass
                        if state in ("mate", "nomate", "timeout"):
                            got = [{"king": None, "state": state, "pv": pv, "n": n}]
                    except (OSError, RuntimeError, TimeoutError):
                        self.close_tsume_engine()
                    if got:
                        self.sig.mate.emit({"state": got[0]["state"], "runs": got, "sec": time.time() - t0,
                                            "sfen": sfen, "compare": compare, "engine": "KomoringHeights"})
                        return
                with self.engine_lock:
                    eng = self._get_engine()
                    runs = []
                    for s, kname in core.mate_king_candidates(sfen, 2):
                        state, pv, n = eng.mate(s, ms)
                        runs.append({"king": kname, "state": state, "pv": pv, "n": n})
                        if state != "mate":
                            break
                self.sig.mate.emit({"state": runs[0]["state"], "runs": runs, "sec": time.time() - t0,
                                    "sfen": sfen, "compare": compare})
            except Exception as e:
                self.sig.mate.emit({"state": "error", "msg": str(e), "runs": [], "sec": time.time() - t0})

        threading.Thread(target=work, daemon=True).start()

    def solve_kiei(self):
        """棋慧だけで詰将棋を解く（Komoring不要）。最短の手数と初手を求めてから、「詳細検討」と同じ形で変化まで出す。"""
        if tsume_verify is None:
            QMessageBox.warning(self, "解けません", "検証用の部品(tsume_verify)が読み込めていません。")
            return
        sfen = self.cur_board.sfen()
        self.btn_kiei.setEnabled(False)
        self.btn_mate_apply.setEnabled(False)
        self.btn_mate_check.setEnabled(False)
        self.btn_mate_alt.setEnabled(False)
        self.btn_mate_apply_v.setEnabled(False)
        self.verified_pv = None
        self.verified_game = None
        self.last_mate = (sfen, [])
        self.status.setText("棋慧だけで解いています…（短い手数から順に読みます。最長3分）")
        self.kh_ask_n, self.kh_ask_sec, self.kh_ask_by = 0, 0.0, {}

        def work():
            t0 = time.time()
            try:
                sv = tsume_verify.solve_first(sfen, time_limit=150)
                if sv["state"] != "ok":
                    res = {"state": "timeout" if sv["state"] == "timeout" else ("skip" if sv["state"] in ("skip", "nomate") else "error"),
                           "msg": sv["msg"], "sec": 0.0}
                    pv = []
                else:
                    pv = list(sv["pv"])
                    res = tsume_verify.detail(sfen, pv, time_limit=max(20, 175 - int(time.time() - t0)), fmt=core.move_ja)
                    res["firsts"] = list(sv["firsts"])
                    if sv["pv"]:
                        self.last_mate = (sfen, pv)
            except Exception as e:
                res, pv = {"state": "error", "msg": str(e), "sec": 0.0}, []
            res["sec"] = time.time() - t0
            res["by_kiei"] = True
            res["kind"], res["sfen"], res["pv"] = "alt", sfen, pv
            res["kh_used"], res["kh_asks"], res["kh_sec"], res["kh_by"] = False, 0, 0.0, {}
            self.sig.verify.emit(res)

        threading.Thread(target=work, daemon=True).start()

    def apply_mate_line(self, verified=False):
        """「詰みを探す」で見つかった手順を、棋譜として盤に取り込む（駒を動かしても消えない）。
        verified=True のときは、「詳細検討」で直した手順を取り込む。"""
        if not self.last_mate:
            return
        sfen, pv = self.last_mate
        if verified is True:
            if not self.verified_pv:
                return
            pv = list(self.verified_pv)
        try:
            b = shogi.Board(sfen)
            for u in pv:
                b.push_usi(u)
        except Exception as e:
            QMessageBox.warning(self, "取り込めません", str(e))
            return
        _prob = self.tsume["prob"] if self.tsume else None
        self.tsume = None
        self.tsume_seq += 1
        self.set_variations(None)
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        _vg = self.verified_game if (verified is True and self.verified_game) else None
        self.start_sfen, self.moves, self.cursor = sfen, list(pv), 0
        self.tsume_shown = (_prob, sfen) if _prob else None
        if getattr(self, "mate_report", None):
            self.mate_report = (sfen, self.mate_report[1])      # 取り込んだ手順の局面でも、結果を残す
        self.names = ["先手", "後手"]
        self.kif_comments, self.kif_comment_sfen, self.kif_comment_moves = {}, sfen, []
        self.kif_senkei = ("", "")
        self.refresh(analyze=False)
        _extra = ""
        if _vg and _vg.get("variations"):
            try:
                self.set_variations(_vg)
                _extra = f"変化が{len(_vg['variations'])}つあります（「変化」の選択欄で切り替えられます）。"
            except Exception:
                pass
        self.status.setText(f"詰み手順（{len(pv)}手）を棋譜として盤に取り込みました。{_extra}「進む」で手順を見られます。"
                            "「ファイル」→「KIFを保存」、「コピー」→「KIFをコピー」で残せます")

    def on_mate(self, r):
        self.btn_mate.setEnabled(True)
        st, sec = r["state"], r["sec"]
        if st == "error":
            self.status.setText("エラー：" + r["msg"])
            QMessageBox.warning(self, "エンジンのエラー", r["msg"])
            return
        runs = r["runs"]
        first = runs[0]
        if st == "mate":
            pv = first["pv"]
            self.last_mate = (r["sfen"], list(pv))
            self.btn_mate_apply.setEnabled(True)
            self.verified_pv = None
            self.verified_game = None
            self.btn_mate_apply_v.setEnabled(False)
            self.btn_mate_check.setEnabled(tsume_verify is not None)
            self.btn_mate_alt.setEnabled(tsume_verify is not None)
            b = shogi.Board(r["sfen"])
            n = len(pv)
            text = [f"## 詰みが見つかりました：{n}手詰（{sec:.1f}秒）", ""]
            if first["n"] and first["n"] != n:
                text += [f"（エンジンは詰みまで{first['n']}手と報告。表示できた手順は{n}手分です）", ""]
            if r.get("engine") == "KomoringHeights":
                text += ["詰将棋専用エンジン（KomoringHeights）の手順（最短とは限りません）：", "", (tsume_verify.line_ja(r["sfen"], pv) if tsume_verify is not None else core.pv_ja(b, pv, n)), ""]
            else:
                text += ["エンジンの手順（最短とは限りません）：", "", core.pv_ja(b, pv, n), ""]
            if first["king"]:
                text.append(f"※詰将棋には先手玉がないため、先手玉を{first['king']}に補って探索しました。")
                if len(runs) > 1:
                    s2 = runs[1]
                    if s2["state"] == "mate" and s2["pv"] == pv:
                        text.append(f"玉を{s2['king']}に置き換えて再探索しても、同じ手順でした（玉の影響なし）。")
                    elif s2["state"] == "mate":
                        text.append(f"玉を{s2['king']}に置き換えて再探索すると、{len(s2['pv'])}手詰・手順が異なりました。"
                                    "玉の位置の影響か、別解の可能性があります。")
                    else:
                        text.append(f"玉を{s2['king']}に置き換えた再探索は詰みを確認できませんでした"
                                    "（玉の位置の影響が出ている可能性があります）。")
                text.append("")
            cmp_ = r.get("compare")
            if cmp_:
                if list(cmp_) == list(pv):
                    text.append("**棋譜の手順と完全に一致しました。**")
                else:
                    k = next((i for i, (x, y) in enumerate(zip(cmp_, pv)) if x != y), min(len(cmp_), len(pv)))
                    text.append(f"棋譜は{len(cmp_)}手、エンジンは{n}手。{k + 1}手目から手順が違います"
                                f"（同じ手数の別解・余詰め・エンジンの手順が最短でない、のいずれかです）。")
            text += ["", "※KomoringHeightsの手順は、無駄合を含んでいる可能性があります。「手順検証」「詳細検討」で確かめられます。"]
            self.show_result("\n".join(text))
            self.mate_report = (self.start_sfen, self.result.toHtml())
            self.status.setText(f"{n}手詰を発見（{sec:.1f}秒）　「詰み手順を盤へ」で棋譜にできます")
        elif st == "nomate":
            self.show_result(f"## 詰みはありません（不詰）\n\n{sec:.1f}秒で、この局面は詰まないと判定されました。")
            self.status.setText("不詰と判定")
        elif st == "timeout":
            self.show_result(f"## 詰みを見つけられませんでした\n\n{sec:.0f}秒で中止または時間切れです。"
                                    "設定の「詰み探索の時間」を長くするか、0（無制限）にして試してください。")
            self.status.setText("詰み探索：時間切れ／中止")
        else:
            self.show_result("## 詰みの答えを得られませんでした\n\n"
                                    "エンジンが詰みの情報を返しませんでした。通常の検討（検討開始）も試してください。")
            self.status.setText("詰みの情報が得られませんでした")

    # ---------------------------------------------------------- 全局解析・評価値グラフ
    def sync_eval_graph(self):
        """棋譜が変わったらグラフを入れ替える（保存済みの解析結果があればそれを出す）。カーソルを合わせる。"""
        if getattr(self, "watching", False):
            self.graph.set_cursor(self.cursor)
            return
        key = core.game_key(self.start_sfen, self.moves) if self.moves else None
        if key != self.eval_key:
            if self.game_running:
                self.game_cancel.set()
                self._stop_game_engines()
            self.eval_key = key
            self.evals, self.swings, self.goods, self.matches, self.review_md = None, {}, {}, {}, ""
            self.game_label.setText("")
            if key:
                cache = core.load_eval_cache(self.save_dir(), key, len(self.moves))
                if cache:
                    self.evals = cache["evals"]
                    self._classify()
                    revs = cache.get("reviews") or []
                    if revs and isinstance(revs[-1], dict):
                        self.review_md = revs[-1].get("text", "")
                    self.game_label.setText(f"保存済みの解析結果を表示中（1手{cache.get('movetime_ms', 0) / 1000:g}秒）"
                                            + ("" if self._has_second() else "　（高速モードの結果。好手・妙手・一致を出すには「詳細」で解析し直してください）"))
            self.graph.set_data(self.evals, self.swings, self.goods)
            self.show_game_summary()
            self.refresh_move_list()
        self._live_graph()
        self.graph.set_cursor(self.cursor)

    def _classify(self):
        """評価値の記録から、悪手・疑問手と好手を求める。"""
        self.swings = core.classify_swings(self.start_sfen, self.moves, self.evals)
        self.goods = core.classify_good(self.start_sfen, self.moves, self.evals)
        self.matches = core.classify_match(self.moves, self.evals)

    def _has_second(self):
        return core.has_detail(self.evals)

    def verify_mate(self, kind):
        """「詰みを探す」の結果を、棋慧のエンジンで検証する（kind: line=手順検証 / alt=詳細検討）。"""
        if not self.last_mate or tsume_verify is None:
            return
        sfen, pv = self.last_mate
        self.btn_mate_check.setEnabled(False)
        self.btn_mate_alt.setEnabled(False)
        self.status.setText("棋慧エンジンで検証中…（短い問題なら数秒です）")

        self.kh_ask_n, self.kh_ask_sec, self.kh_ask_by = 0, 0.0, {}

        def work():
            use_kh = False
            try:
                if kind == "line":
                    res = tsume_verify.quick_check(sfen, list(pv), time_limit=120, fmt=core.move_ja)
                else:
                    # まず棋慧だけで解く（短い問題はこれが最速）。30秒で終わらなければKomoringの助けを借りる
                    res = tsume_verify.detail(sfen, list(pv), time_limit=30, fmt=core.move_ja)
                    if res.get("state") == "timeout" and self._tsume_path():
                        try:
                            import tsume_native
                            use_kh = bool(tsume_native.set_oracle(self._kh_oracle))
                        except Exception:
                            use_kh = False
                        if use_kh:
                            res = tsume_verify.detail(sfen, list(pv), time_limit=150, fmt=core.move_ja)
                            res["sec"] = res.get("sec", 0.0) + 30.0
            except Exception as e:
                res = {"state": "error", "msg": str(e), "sec": 0.0}
            res["kind"], res["sfen"], res["pv"] = kind, sfen, list(pv)
            res["kh_used"], res["kh_asks"], res["kh_sec"] = use_kh, self.kh_ask_n, self.kh_ask_sec
            res["kh_by"] = {k: list(v) for k, v in self.kh_ask_by.items()}
            try:
                import tsume_native
                tsume_native.set_oracle(None)
            except Exception:
                pass
            self.sig.verify.emit(res)

        threading.Thread(target=work, daemon=True).start()

    def on_verify(self, r):
        import html as _h
        esc = lambda t: _h.escape(str(t))
        self.btn_kiei.setEnabled(True)
        same = bool(self.last_mate and self.last_mate[0] == r.get("sfen"))
        if same:
            self.btn_mate_check.setEnabled(tsume_verify is not None)
            self.btn_mate_alt.setEnabled(tsume_verify is not None)
        else:
            return                                   # 検証中に別の局面へ移った：古い結果は出さない
        st, sec, kind = r.get("state"), r.get("sec", 0.0), r.get("kind")
        b = shogi.Board(r["sfen"])
        by_kiei = bool(r.get("by_kiei"))
        try:
            kh = tsume_verify.line_ja(r["sfen"], r["pv"]) if r["pv"] else ""
        except Exception:
            kh = ""
        title = "棋慧で解く" if by_kiei else ("手順検証" if kind == "line" else "詳細検討")
        h = [f"<h3>{title}（棋慧エンジン）</h3>"]
        if kh:
            h.append(f"<p>{'棋慧が見つけた手順' if by_kiei else 'KomoringHeightsの手順'}：<br>{esc(kh)}</p>")
        if st in ("skip", "timeout", "error"):
            h.append(f"<p>{esc(r.get('msg') or '検証できませんでした。')}</p>")
        elif kind == "line":
            if st == "pending":
                h.append("<p>無駄合は見つかりませんでしたが、次の合駒は時間内に判定できませんでした（無駄合でないとは言い切れません）：</p>")
                h.append(f"<p>{esc(' '.join(r.get('pending', [])))}</p>")
            elif st == "warn":
                h.append("<p><b><span style='color:#d32f2f'>Komoringの手順は正確でない可能性があります。</span></b></p>")
                h.append(f"<p>無駄合： {esc(' '.join(r['futile']))}</p>")
                if r.get("pending"):
                    h.append(f"<p>※次の合駒は時間内に判定できませんでした： {esc(' '.join(r['pending']))}</p>")
                h.append("<p>正しい手順や手数は「詳細検討」で調べられます（時間がかかることがあります）。</p>")
            else:
                h.append("<p>KomoringHeightsの手順に、無駄合は見つかりませんでした。</p>")
                h.append("<p>※この手順1本の合駒だけを調べています。他の変化や余詰は「詳細検討」で調べられます。</p>")
        else:
            if r.get("kh_futile"):
                h.append(f"<p>KomoringHeightsの手順は無駄合（{esc(' '.join(r['kh_futile']))}）を含んでいます。"
                         f"それを除くと{r['kh_eff']}手の変化で、最長の変化ではありません。</p>")
            h.append(f"<p>この問題の正しい詰み手数（無駄合を除いた最長の変化）： <b>{r['N']}手</b></p>")
            if r.get("msg"):
                h.append(f"<p><span style='color:#d32f2f'>{esc(r['msg'])}</span></p>")
            for ttl, text, notes in r.get("blocks", []):
                h.append(f"<h4>{esc(ttl)}</h4><p><b>{esc(text)}</b></p>")
                for n in notes:
                    h.append(f"<p>※{esc(n)}</p>")
            if by_kiei:
                fs = r.get("firsts") or []
                if len(fs) > 1:
                    try:
                        b0 = shogi.Board(r["sfen"])
                        names = [core.move_ja(b0, u) for u in fs]
                    except Exception:
                        names = list(fs)
                    h.append(f"<p><b>初手に余詰があります：</b> {esc(' '.join(names))}（どれでも{r['N']}手で詰みます）</p>")
                else:
                    h.append("<p>初手に余詰はありません（最短の詰みになる初手は、上の1手だけです）。</p>")
            else:
                h.append("<p>初手はKomoringHeightsの手を前提にしています（初手の余詰は調べていません）。</p>")
        h.append(f"<p>棋慧エンジンの考慮時間：{sec:.1f}秒</p>")
        if r.get("kh_used"):
            by = r.get("kh_by", {})
            names = {"mate": "詰み", "nomate": "不詰", "other": "時間切れ等"}
            det = "、".join(f"{names[k]} {v[0]}回・{v[1]:.1f}秒" for k, v in by.items() if k in names)
            h.append(f"<p>（うち、Komoringへの問い合わせ：{r.get('kh_asks', 0)}回・合計{r.get('kh_sec', 0.0):.1f}秒"
                     + (f"　内訳：{det}" if det else "") + "）</p>")
        else:
            h.append("<p>（棋慧エンジン単独で検証しました）</p>")
        if kind == "alt" and st in ("ok", "warn") and r.get("game") and r["game"].get("moves"):
            self.verified_game = r["game"]
            self.verified_pv = list(r["game"]["moves"])
            self.btn_mate_apply_v.setEnabled(True)
            if by_kiei:
                self.btn_mate_apply.setEnabled(True)
            if r["game"].get("variations"):
                h.append("<p>「検証済み手順を盤へ」を押すと、変化も分岐棋譜として盤に取り込めます（「変化」の選択欄から切り替え）。</p>")
        self.result.setHtml("".join(h))
        self.mate_report = (self.start_sfen, self.result.toHtml())
        self.tabs.setCurrentWidget(self.result)
        self.status.setText(f"{title}：完了（{sec:.1f}秒）")

    def show_result(self, md):
        """この局面の解説の欄に出す（全局の結果は別のタブに残る）。"""
        self.result.setMarkdown(md)
        self.tabs.setCurrentWidget(self.result)

    def on_summary_link(self, url):
        s = url.toString()
        if s.startswith("ply"):
            try:
                self.go_to_ply(int(s[3:]))
            except ValueError:
                pass

    def open_eval_file(self):
        """保存した評価グラフ(JSON)を選んで開く。棋譜ごと読み込み、グラフを表示する。"""
        if self.game_running:
            QMessageBox.information(self, "案内", "解析中です。終わるか中止してから開いてください。")
            return
        path, _ = QFileDialog.getOpenFileName(self, "評価グラフを選ぶ", core.eval_cache_dir(self.save_dir()),
                                              "評価グラフ (*.json);;すべて (*)")
        if not path:
            return
        try:
            data = core.read_eval_file(path)
            core.board_from(data["start_sfen"], data["moves"])
        except Exception as e:
            QMessageBox.warning(self, "開けません", str(e))
            return
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        self.start_sfen, self.moves = data["start_sfen"], list(data["moves"])
        self.names = list(data.get("names") or ["先手", "後手"])
        self.cursor = 0
        self.refresh(analyze=False)                      # この中で、保存場所にあれば自動で読まれる
        key = core.game_key(self.start_sfen, self.moves)
        self.eval_key = key
        self.evals = data["evals"]
        self._classify()
        self.graph.set_data(self.evals, self.swings, self.goods)
        self.refresh_move_list()
        try:                                              # 別の場所のファイルでも、次からは自動で読めるようにする
            core.save_eval_cache(self.save_dir(), key, self.start_sfen, self.moves, self.names,
                                 data.get("movetime_ms", 0), self.evals)
        except Exception:
            pass
        self.game_label.setText(f"{len(self.moves)}手の評価グラフを開きました（1手{data.get('movetime_ms', 0) / 1000:g}秒）")
        self.graph.set_cursor(0)
        revs = data.get("reviews") or []
        self.review_md = ""
        if revs and isinstance(revs[-1], dict):
            r = revs[-1]
            self.review_md = r.get("text", "")
        self.show_game_summary()
        self.tabs.setCurrentWidget(self.summary)

    def review_game(self):
        """全局解析の結果から、AIに一局の講評を書いてもらう。"""
        if self.game_running:
            QMessageBox.information(self, "案内", "解析中です。終わってから押してください。")
            return
        if not self.evals or any(e is None for e in self.evals):
            QMessageBox.information(self, "案内", "先に「全局を解析」を実行するか、「評価グラフを開く…」で結果を開いてください。")
            return
        if core.llm_key_missing(self.cfg):
            QMessageBox.information(self, "案内", f"{core.llm_name(self.cfg)}のAPIキーが未設定です。「設定…」で入力してください。")
            return
        key = self.eval_key
        try:
            prompt = core.build_review_prompt(self.names, self.start_sfen, self.moves, self.evals, self.swings,
                                                comments=self.current_kif_comments(), goods=self.goods)
        except Exception as e:
            QMessageBox.warning(self, "講評の材料を作れません", str(e))
            return
        cfg = dict(self.cfg)
        self.btn_review.setEnabled(False)
        self.status.setText(f"{core.llm_name(cfg)}に講評を頼んでいます…（10〜30秒ほど）")

        def work():
            try:
                self.sig.review.emit(key, core.ask_llm(prompt, cfg))
            except Exception as e:
                self.sig.review_err.emit(str(e))

        threading.Thread(target=work, daemon=True).start()

    def on_review(self, key, text):
        self.btn_review.setEnabled(True)
        if key != self.eval_key:
            return                                   # 頼んでいる間に別の棋譜へ移った
        self.review_md = text
        self.show_game_summary()
        self.tabs.setCurrentWidget(self.summary)
        model = {"openai": self.cfg.get("openai_model"), "claude": self.cfg.get("anthropic_model"),
                 "groq": self.cfg.get("groq_model")}.get(self.cfg.get("llm_provider"), self.cfg.get("gemini_model"))
        try:
            core.append_review(self.save_dir(), key, {"ai": core.llm_name(self.cfg), "model": model,
                                                      "generated_at": datetime.now().isoformat(timespec="seconds"),
                                                      "text": text})
            self.status.setText("講評を表示し、評価グラフのファイルに保存しました")
        except Exception as e:
            self.status.setText("講評を表示しました（保存に失敗：%s）" % e)

    def on_review_err(self, msg):
        self.btn_review.setEnabled(True)
        self.status.setText(f"{core.llm_name(self.cfg)}のエラー：" + msg)
        QMessageBox.warning(self, f"{core.llm_name(self.cfg)}のエラー", msg)

    def graph_tip(self, ply):
        e = self.evals[ply] if self.evals and 0 <= ply < len(self.evals) else None
        lines = [f"{ply}手目まで　評価値 {core.fmt_value(e)}"]
        if ply >= 1 and ply <= len(self.moves):
            try:
                bd = core.board_from(self.start_sfen, self.moves[:ply - 1])
                lines.append("指し手：" + core.move_ja(bd, self.moves[ply - 1]))
                sw = self.swings.get(ply)
                if sw:
                    best = core.move_ja(bd, sw["best"]) if sw["best"] else "?"
                    lines.append(f"{sw['name']}（{sw['loss']}点悪化）　最善は {best}")
                gd = self.goods.get(ply)
                if gd:
                    lines.append(f"{gd['name']}（{core.describe_good(bd, gd)}）")
                mt = self.matches.get(ply)
                if mt is not None and not gd:
                    lines.append({1: "エンジンの最善手と一致", 2: "エンジンの2番目の候補と一致",
                                  3: "エンジンの3番目の候補と一致", 0: "エンジンの3候補の外の手"}[mt])
            except Exception:
                pass
        return "\n".join(lines)

    def toggle_game_analysis(self):
        if self.watching:
            self._watch_off()
        if self.game_running:
            self.game_cancel.set()
            self._stop_game_engines()
            self.game_label.setText("中止しています…")
            return
        if not self.moves:
            QMessageBox.information(self, "案内", "指し手のある棋譜を読み込んでください（KIF読込／KIF貼付）。")
            return
        if self._no_king(shogi.Board(self.start_sfen)):
            QMessageBox.information(self, "案内", "玉が盤上に1枚しかない局面（詰将棋の形）なので、全局解析はできません。")
            return
        key = core.game_key(self.start_sfen, self.moves)
        mode = self.game_mode()
        mpv = core.GAME_MODES[mode]
        ms = self.game_ms(mode)
        self.game_used = (mode, ms)
        cache = core.load_eval_cache(self.save_dir(), key, len(self.moves))
        if cache:
            cmode = "詳細" if core.has_detail(cache.get("evals")) else "高速"
            hint = ("\n\n※今は「詳細」が選ばれていますが、保存済みは「高速」の結果です。好手・妙手・エンジン一致を出すには「いいえ」で解析し直してください。"
                    if mode == "detail" and cmode == "高速" else "")
            r = QMessageBox.question(self, "保存済みの解析があります",
                                     f"この棋譜は解析済みです（{cmode}モード・1手{cache.get('movetime_ms', 0) / 1000:g}秒）。{hint}\n"
                                     "「はい」＝保存済みの結果を使う　／　「いいえ」＝解析し直す",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                     | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return
            if r == QMessageBox.StandardButton.Yes:
                self.eval_key = None
                self.sync_eval_graph()
                self.show_game_summary()
                self.tabs.setCurrentWidget(self.summary)
                return
        if self.analyzing and self.engine:
            self.engine.stop()
        self.gen += 1
        self.analyzing = False
        self.game_running = True
        self.game_cancel.clear()
        self.eval_key = key
        n = len(self.moves)
        self.evals, self.swings, self.goods, self.matches, self.review_md = [None] * (n + 1), {}, {}, {}, ""
        self.summary.clear()
        self.graph.set_data(self.evals, {})
        self.refresh_move_list()
        self.btn_game.setText("解析を中止")
        nw0 = max(1, int(self.cfg.get("game_workers", 3)))
        est = (n + 1) * ms / 1000 / nw0 + 5
        self.game_label.setText(f"解析中… 0/{n + 1}局面（エンジン{nw0}個で並列・約{est:.0f}秒）")
        start_sfen, moves = self.start_sfen, list(self.moves)

        nw = max(1, int(self.cfg.get("game_workers", 3)))
        self.game_engines = []

        def work():
            try:
                path = self.cfg.get("engine_path", "")
                if not path:
                    raise RuntimeError("エンジンが登録されていません。右上の「設定…」から登録してください。")
                b = shogi.Board(start_sfen)
                sfens = [b.sfen()]
                for u in moves:
                    b.push(shogi.Move.from_usi(u))
                    sfens.append(b.sfen())
                todo = queue.Queue()
                for i, s in enumerate(sfens):
                    todo.put((i, s))
                opts = dict(self.cfg.get("engine_options", {}))
                opts["Threads"] = 1                              # 1つのエンジンは1スレッド。エンジンを複数動かして並列にする
                opts["USI_Hash"] = min(int(opts.get("USI_Hash", 256)), 256)
                errors = []

                def worker():
                    try:
                        eng = core.UsiEngine(path, opts)
                        self.game_engines.append(eng)
                        eng.start()
                        while not self.game_cancel.is_set():
                            try:
                                i, s = todo.get_nowait()
                            except queue.Empty:
                                break
                            e = core.eval_position(eng, s, ms, mpv)
                            if self.game_cancel.is_set():
                                break                      # 途中で止めた局面の結果は捨てる（短い思考で歪むため）
                            self.sig.game_prog.emit(key, i, e)
                    except Exception as ex:
                        errors.append(str(ex))
                        self.game_cancel.set()             # 1つでも失敗したら全体を止める
                        self._stop_game_engines()

                ts = [threading.Thread(target=worker, daemon=True) for _ in range(min(nw, len(sfens)))]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join()
                for eng in list(self.game_engines):
                    eng.close()
                self.game_engines = []
                if errors:
                    self.sig.game_err.emit(errors[0])
                else:
                    self.sig.game_done.emit(key, self.game_cancel.is_set())
            except Exception as ex:
                self.sig.game_err.emit(str(ex))

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- 観戦モード（手が進むたびにグラフを伸ばす）
    def toggle_watch(self, on):
        if on:
            if self.game_running:
                QMessageBox.information(self, "案内", "全局解析の途中です。終わってから（または中止してから）観戦モードにしてください。")
                self.btn_watch.blockSignals(True)
                self.btn_watch.setChecked(False)
                self.btn_watch.blockSignals(False)
                return
            if self._no_king(self.cur_board) or self._no_king(shogi.Board(self.start_sfen)):
                QMessageBox.information(self, "案内", "玉が盤上に1枚しかない局面（詰将棋の形）では、観戦モードは使えません。")
                self.btn_watch.blockSignals(True)
                self.btn_watch.setChecked(False)
                self.btn_watch.blockSignals(False)
                return
            if not self.cfg.get("engine_path"):
                QMessageBox.information(self, "案内", "エンジンが登録されていません。右上の「設定…」から登録してください。")
                self.btn_watch.blockSignals(True)
                self.btn_watch.setChecked(False)
                self.btn_watch.blockSignals(False)
                return
            self.watching = True
            self._watch_lock = threading.Lock()
            self._watch_stop = threading.Event()
            self._watch_res, self._watch_err = {}, None
            self._watch_sfens, self.watch_evals, self._watch_key = [], [], None
            self._watch_clip = QApplication.clipboard().text()
            self.graph.min_n = 60
            self.graph.msg = "観戦中：中継の棋譜をコピーするか、盤で指すと、ここに評価値が伸びていきます"
            self._watch_sync()
            threading.Thread(target=self._watch_worker, daemon=True).start()
            self._watch_timer.start(700)
            self.game_label.setText("観戦モード：中継サイトの「棋譜コピー」を押すと、自動で読み込んで解析します")
        else:
            self._watch_off()

    def _watch_off(self):
        self.watching = False
        self._watch_timer.stop()
        try:
            self._watch_stop.set()
        except Exception:
            pass
        self.graph.min_n = 0
        self.graph.msg = "検討しながら指していくと、ここに評価値のグラフが伸びていきます"
        self.evals = None
        self.eval_key = None
        self.game_label.setText("")
        self.btn_watch.blockSignals(True)
        self.btn_watch.setChecked(False)
        self.btn_watch.blockSignals(False)
        self.sync_eval_graph()

    def _watch_sync(self):
        """棋譜（手）が変わったら、解析の記録を作り直す（同じ局面の結果は引き継ぐ）。"""
        key = (self.start_sfen, tuple(self.moves))
        if key == self._watch_key:
            return
        self._watch_key = key
        try:
            b = shogi.Board(self.start_sfen)
            sfens = [b.sfen()]
            for u in self.moves:
                b.push(shogi.Move.from_usi(u))
                sfens.append(b.sfen())
        except Exception:
            return
        with self._watch_lock:
            old_s, old_e = self._watch_sfens, self.watch_evals
            new_e = [old_e[i] if (i < len(old_s) and old_s[i] == s) else None for i, s in enumerate(sfens)]
            self._watch_sfens, self.watch_evals = sfens, new_e
        self.evals = self.watch_evals
        n = len(sfens) - 1
        self.graph.min_n = max(60, (n // 20 + 1) * 20)

    def _watch_tick(self):
        if not self.watching:
            return
        if self._watch_err:
            msg, self._watch_err = self._watch_err, None
            self._watch_off()
            QMessageBox.warning(self, "観戦モードを止めました", msg)
            return
        # 中継サイトの棋譜（KIF）がコピーされたら、自動で読み込む
        try:
            text = QApplication.clipboard().text()
        except Exception:
            text = self._watch_clip
        if text != self._watch_clip:
            self._watch_clip = text
            if text and len(text) > 20:
                kind, data = core.detect_clip(text)
                if kind == "kif" and data.get("moves"):
                    self._apply_game(data, from_clip=True)
        self._watch_sync()
        with self._watch_lock:
            for i, s in enumerate(self._watch_sfens):
                if self.watch_evals[i] is None and s in self._watch_res:
                    self.watch_evals[i] = self._watch_res[s]
            done = sum(1 for e in self.watch_evals if e)
            total = len(self.watch_evals)
        self.graph.set_data(self.watch_evals, {}, {})
        self.graph.set_cursor(self.cursor)
        self.game_label.setText(f"観戦中：{len(self.moves)}手　解析済み {done}/{total}局面")

    def _watch_worker(self):
        eng = None
        try:
            opts = dict(self.cfg.get("engine_options", {}))
            opts["Threads"] = max(1, int(opts.get("Threads", 2)) // 2)
            opts["USI_Hash"] = min(int(opts.get("USI_Hash", 256)), 256)
            eng = core.UsiEngine(self.cfg.get("engine_path", ""), opts)
            eng.start()
            ms = max(self.game_ms("fast"), 1500)
            while not self._watch_stop.is_set():
                with self._watch_lock:
                    todo = [(i, s) for i, s in enumerate(self._watch_sfens) if self.watch_evals[i] is None and s not in self._watch_res]
                if not todo:
                    time.sleep(0.3)
                    continue
                i, s = todo[-1]                  # いちばん新しい局面から先に解析する
                e = core.eval_position(eng, s, ms, 1)
                if self._watch_stop.is_set():
                    break
                with self._watch_lock:
                    self._watch_res[s] = e
        except Exception as ex:
            self._watch_err = f"エンジンの解析でエラーが出ました：{ex}"
        finally:
            if eng is not None:
                try:
                    eng.stop()
                    eng.close()
                except Exception:
                    pass

    # ---------------------------------------------------------- 検討しながら伸びていくグラフ
    def _live_record(self, cands):
        """いま検討している局面の評価値を覚えて、グラフを更新する（詰将棋・全局解析・観戦中は対象外）。"""
        try:
            if self.tsume or self.game_running or getattr(self, "watching", False) or not cands:
                return
            b = self.cur_board
            c = cands[0]
            v, mate = core.eval_for_black(c, b.turn)
            self.live_evals[b.sfen()] = {"v": int(v), "mate": mate, "depth": c.get("depth", 0),
                                         "best": c["pv"][0] if c.get("pv") else "", "pv": list(c.get("pv", [])[:8]), "mpv": 1}
            self._live_graph()
        except Exception:
            pass

    def _live_graph(self):
        """全局解析の結果が無いとき、検討した局面の評価値をつないだグラフを出す。"""
        watching = getattr(self, "watching", False)
        if watching or self.tsume or self.evals is not None:
            if not watching:
                self.graph.min_n = 0
            return
        try:
            b = shogi.Board(self.start_sfen)
            sfens = [b.sfen()]
            for u in self.moves:
                b.push(shogi.Move.from_usi(u))
                sfens.append(b.sfen())
            data = [self.live_evals.get(x) for x in sfens]
            if len(self.moves) == 0 or not any(data):
                self.graph.min_n = 0
                self.graph.set_data(None, {}, {})
                return
            self.graph.min_n = max(40, ((len(sfens) - 1) // 20 + 1) * 20)
            self.graph.set_data(data, {}, {})
        except Exception:
            pass

    def _stop_game_engines(self):
        for eng in list(getattr(self, "game_engines", [])):
            try:
                eng.stop()
            except Exception:
                pass

    def game_mode(self):
        return "detail" if self.cfg.get("game_mode") == "detail" else "fast"

    def on_mode_changed(self, _i=None):
        self.cfg["game_mode"] = self.mode_box.currentData()
        try:
            save_config(self.cfg)
        except Exception:
            pass

    def game_ms(self, mode=None):
        ms = max(100, int(float(self.cfg.get("game_sec", 1)) * 1000))
        if (mode or self.game_mode()) == "detail":
            ms = int(ms * core.DETAIL_TIME_FACTOR)
        return ms

    def on_game_prog(self, key, i, entry):
        if key != self.eval_key or not self.evals or i >= len(self.evals):
            return
        self.evals[i] = entry
        self.graph.set_data(self.evals, {})
        self.refresh_move_list()
        self.game_label.setText(f"解析中… {i + 1}/{len(self.evals)}局面")

    def on_game_done(self, key, cancelled):
        self.game_running = False
        self.btn_game.setText("全局を解析（評価値グラフ）")
        if key != self.eval_key or not self.evals:
            return
        if cancelled:
            self.game_label.setText("中止しました（途中までの結果は保存していません）")
            return
        self._classify()
        self.graph.set_data(self.evals, self.swings, self.goods)
        self.refresh_move_list()
        try:
            core.save_eval_cache(self.save_dir(), key, self.start_sfen, self.moves, self.names,
                                 self.game_used[1] if getattr(self, "game_used", None) else self.game_ms(), self.evals)
            self.game_label.setText("解析完了（結果を保存しました）")
        except Exception as ex:
            self.game_label.setText(f"解析完了（保存に失敗: {ex}）")
        self.show_game_summary()
        self.tabs.setCurrentWidget(self.summary)

    def on_game_err(self, msg):
        self.game_running = False
        self.btn_game.setText("全局を解析（評価値グラフ）")
        self.game_label.setText("エラー：" + msg)
        QMessageBox.warning(self, "全局解析のエラー", msg)

    @staticmethod
    def _adv_text(v):
        """先手から見た評価値を、どちらがどれだけ有利かの言葉にする。"""
        v = int(v)
        if abs(v) < 30:
            return "互角"
        return f"{'先手' if v > 0 else '後手'}が{abs(v)}点有利"

    def show_game_summary(self):
        """悪手・好手の一覧（手数をクリックでその局面へ）と、あれば講評を「全局の結果」タブに出す。
        このタブは、局面を動かしても消えない。"""
        if not self.evals or any(e is None for e in self.evals):
            if not self.game_running:
                self.summary.clear()
            return
        n = len(self.moves)
        lines = [f"## 全局解析の結果（{n}手）", "",
                 "手数をクリックすると、盤がその局面に移ります（この一覧は消えません。「この局面の解説」タブで検討できます）。", ""]
        lines += ["### 悪手・疑問手", ""]
        if not self.swings:
            lines.append("評価値が大きく悪化した手は見つかりませんでした。")
        else:
            lines.append("評価値が大きく悪化した手（悪化の大きい順）：")
            lines.append("")
            for i, s in sorted(self.swings.items(), key=lambda kv: -kv[1]["loss"])[:12]:
                bd = core.board_from(self.start_sfen, self.moves[:i - 1])
                best = core.move_ja(bd, s["best"]) if s["best"] else "?"
                lines.append(f"- [{i}手目 {core.move_ja(bd, s['usi'])}](ply{i})　**{s['name']}**（{s['loss']}点悪化、"
                             f"{self._adv_text(s['before'])}→{self._adv_text(s['after'])}）　最善は {best}")
        lines += ["", "### 好手・妙手", ""]
        if not self._has_second():
            lines.append("この解析は「高速」モード（候補1つ）なので、好手・妙手・エンジン一致は出していません。"
                         "「詳細」を選んで「全局を解析」をやり直すと出せます。")
        else:
            lines.append(f"好手＝エンジンの最善手と同じ手で、次善手より{core.GOOD_GAP}点以上よかった手（ほかの手では難しい局面）。"
                         f"妙手＝エンジンの3候補にはないのに、指した後の評価値がほとんど落ちず（{core.MYOU_MAX_LOSS}点以内）、"
                         f"3番目の候補より{core.MYOU_THIRD_GAP}点以上よかった手（評価値の誤差を含む目安です）。"
                         f"駒を取る手と序盤{core.GOOD_SKIP_PLY}手目までは判定しません。")
            lines.append("")
            if not self.goods:
                lines.append("該当する手は見つかりませんでした。")
            for i, g in sorted(self.goods.items(), key=lambda kv: -kv[1]["gap"])[:12]:
                bd = core.board_from(self.start_sfen, self.moves[:i - 1])
                lines.append(f"- [{i}手目 {core.move_ja(bd, g['usi'])}](ply{i})　**{g['name']}**"
                             f"（{g['mover']}。{core.describe_good(bd, g)}）")
            if self.matches:
                lines += ["", "### エンジンとの一致（3候補のどれかと同じ手）", ""]
                for side, par in (("先手", 1), ("後手", 0)):
                    ms_ = [v for k, v in self.matches.items() if k % 2 == par]
                    if ms_:
                        n1 = sum(1 for v in ms_ if v == 1)
                        n3 = sum(1 for v in ms_ if v > 0)
                        lines.append(f"- {side}：{len(ms_)}手中 最善手と一致 {n1}手、3候補のどれかと一致 {n3}手（{n3 * 100 // len(ms_)}%）")
                lines.append("")
                lines.append("棋譜欄の印：◎最善手と一致　○2・3番目の候補と一致　△3候補の外")
        if self.review_md:
            lines += ["", "---", "", "## AIの講評", "", self.review_md]
        self.summary.setMarkdown("\n".join(lines))

    def stop_analysis(self):
        if self.engine:
            self.engine.stop()
        if self.tsume_eng:
            self.tsume_eng.stop()

    def on_cands(self, gen, cands, final):
        if gen != self.gen:
            return
        self.cands = cands
        row = max(0, self.list.currentRow())
        self.list.blockSignals(True)
        self.list.clear()
        b = self.cur_board
        for i, c in enumerate(cands, 1):
            self.list.addItem(f"{i}.  {core.fmt_eval(c, b.turn)}  （深さ{c['depth']}）\n    {core.pv_ja(b, c['pv'], 10)}")
        if cands:
            self.list.setCurrentRow(min(row, len(cands) - 1))
        self.list.blockSignals(False)
        self.on_pick_cand(self.list.currentRow())
        self._live_record(cands)
        if final:
            self.analyzing = False
            self.cands_final = True
            self.status.setText("検討完了" if cands else "候補手を取得できませんでした")
            if self.explain_pending and cands:
                self.explain_pending = False
                self.start_gemini()

    def on_pick_cand(self, row):
        if 0 <= row < len(self.cands):
            self.boardw.set_preview(self.cands[row]["pv"][0])

    def on_error(self, gen, msg):
        if gen != self.gen:
            return
        self.analyzing = False
        self.explain_pending = False
        self.auto.setChecked(False)
        self.close_engine()               # 次に押したときは、エンジンを起動し直す
        self.status.setText("エラー：" + msg)
        QMessageBox.warning(self, "エンジンのエラー", msg + "\n\n設定を直したら「検討開始」を押してください。")

    # ---------------------------------------------------------- Gemini解説
    def _prompt(self):
        game = {"names": self.names}
        return core.build_position_prompt(game, self.cur_board, self.cursor, self.cands, self.cfg,
                                          comment=self.kif_comment_here() or None)

    def explain(self):
        if core.llm_key_missing(self.cfg):
            QMessageBox.information(self, "案内", f"{core.llm_name(self.cfg)}のAPIキーが未設定です。「設定…」で入力してください。")
            return
        if self.cands_final and self.cands:
            self.start_gemini()
        else:
            self.request_analysis(explain_after=True)

    def start_gemini(self):
        gen = self.gen
        prompt = self._prompt()
        cfg = dict(self.cfg)
        self.btn_explain.setEnabled(False)
        self.status.setText(f"{core.llm_name(cfg)}に問い合わせ中…")

        def work():
            try:
                self.sig.gemini.emit(gen, core.ask_llm(prompt, cfg))
            except Exception as e:
                self.sig.gemini_err.emit(gen, str(e))

        threading.Thread(target=work, daemon=True).start()

    def on_gemini(self, gen, text):
        self.btn_explain.setEnabled(True)
        if gen != self.gen:
            return
        self.show_result(text)
        try:
            path = self.save_explanation(text)
            self.status.setText("解説を表示し、保存しました：" + os.path.basename(path))
        except Exception as e:
            self.status.setText("解説を表示しました（保存に失敗：%s）" % e)

    def on_gemini_err(self, gen, msg):
        self.btn_explain.setEnabled(True)
        self.status.setText(f"{core.llm_name(self.cfg)}のエラー：" + msg)
        if gen == self.gen:
            QMessageBox.warning(self, f"{core.llm_name(self.cfg)}のエラー", msg)

    def copy_prompt(self):
        if not self.cands:
            QMessageBox.information(self, "案内", "先に検討を実行して、候補手を出してください。")
            return
        QApplication.clipboard().setText(self._prompt())
        self.status.setText("LLMに渡す文章をコピーしました（ClaudeなどのチャットにPasteしてください）")

    # ---------------------------------------------------------- 解説の保存と読み込み
    def save_dir(self):
        d = self.cfg.get("save_dir") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "解説保存")
        os.makedirs(d, exist_ok=True)
        return d

    def current_ply(self):
        """この局面の手数。SFENに手数が入っていればそれも足す（スクショ由来の1は「不明」とみなす）。"""
        try:
            base = int(self.start_sfen.split()[3])
        except (IndexError, ValueError):
            base = 1
        return self.cursor + (base - 1 if base > 1 else 0)

    def save_explanation(self, text):
        """解説した局面のSFEN・候補手（読み筋）・解説文を「日付-手数.json」に保存する。"""
        board = self.cur_board
        now = datetime.now()
        ply = self.current_ply()
        sfen = board.sfen()
        stem = now.strftime("%Y%m%d") + "-" + (f"{ply}手" if ply > 0 else now.strftime("%H%M%S"))
        folder = self.save_dir()
        path, n = os.path.join(folder, stem + ".json"), 1
        data = None
        while os.path.exists(path):          # 同じ名前で別の局面なら、番号を付けて別ファイルにする
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
            except Exception:
                old = None
            if old and old.get("sfen") == sfen:
                data = old
                break
            n += 1
            path = os.path.join(folder, f"{stem}_{n}.json")
        if data is None:
            data = {"version": 1, "explanations": []}
        data.update({
            "date": now.strftime("%Y-%m-%d"), "ply": ply, "sfen": sfen,
            "turn": "先手" if board.turn == shogi.BLACK else "後手", "names": list(self.names)})
        if self.cands or "candidates" not in data:     # 候補手が空のときは、すでに保存してある読み筋を消さない
            data["candidates"] = [{
                "rank": i, "eval_text": core.fmt_eval(c, board.turn), "depth": c.get("depth", 0),
                "kind": c["kind"], "cp": c["cp"], "mate_sign": c["mate_sign"], "mate_n": c["mate_n"],
                "pv": list(c["pv"]), "pv_ja": core.pv_ja(board, c["pv"], 10),
            } for i, c in enumerate(self.cands, 1)]
        model = {"openai": self.cfg.get("openai_model"), "claude": self.cfg.get("anthropic_model"),
             "groq": self.cfg.get("groq_model")}.get(
            self.cfg.get("llm_provider"), self.cfg.get("gemini_model"))
        data["explanations"].append({"ai": core.llm_name(self.cfg), "model": model,
                                     "generated_at": now.isoformat(timespec="seconds"), "text": text})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def open_saved(self):
        path, _ = QFileDialog.getOpenFileName(self, "保存した解説を開く", self.save_dir(), "解説ファイル (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            shogi.Board(data["sfen"])
            cands = [{"kind": c["kind"], "cp": c["cp"], "mate_sign": c["mate_sign"], "mate_n": c["mate_n"],
                      "depth": c.get("depth", 0), "pv": list(c["pv"]), "multipv": c.get("rank", 1)}
                     for c in data.get("candidates", [])]
        except Exception as e:
            QMessageBox.warning(self, "読み込めません", f"解説ファイルを読めませんでした。\n{e}")
            return
        self.orig_line = None                      # 別の局面・棋譜に変わったら、戻る先を忘れる
        self.start_sfen, self.moves, self.cursor = data["sfen"], [], 0
        self.names = data.get("names") or ["先手", "後手"]
        self.refresh(analyze=False)
        self.on_cands(self.gen, cands, False)
        self.cands_final = True
        parts = []
        for ex in data.get("explanations", []):
            parts.append(f"## {ex.get('ai', '')}（{ex.get('model', '')}）　{str(ex.get('generated_at', '')).replace('T', ' ')}\n\n{ex.get('text', '')}")
        self.show_result("\n\n---\n\n".join(parts) if parts else "（解説は保存されていません）")
        self.info.setText(f"保存した解説：{data.get('date', '')}　{data.get('ply', '')}手目　{data.get('turn', '')}の手番")
        self.status.setText("読み込みました：" + os.path.basename(path))

    # ---------------------------------------------------------- 設定・終了
    def update_ai_labels(self):
        """選んでいる解説AIの名前を、ボタンと説明欄に出す。"""
        name = core.llm_name(self.cfg)
        self.btn_explain.setText(f"解説する（{name}）")
        self.result.setPlaceholderText(f"ここに{name}の解説が出ます")

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            dlg.apply_to(self.cfg)
            save_config(self.cfg)
            self.update_ai_labels()
            self.gen += 1
            self.close_engine()
            self.close_tsume_engine()
            self.analyzing = False
            self.auto.setChecked(True)
            self.status.setText("設定を保存しました")

    def changeEvent(self, e):
        """最大化・全画面のときだけ、盤とグラフの「縮められる限界」を小さくする（画面の高さに収まらず、
        部品が重なるのを防ぐ）。ウィンドウ表示のときの大きさは変えない。"""
        super().changeEvent(e)
        try:
            from PyQt6.QtCore import QEvent
            if e.type() == QEvent.Type.WindowStateChange:
                compact = self.isMaximized() or self.isFullScreen()
                self.boardw.setMinimumSize(280, 290) if compact else self.boardw.setMinimumSize(420, 480)
                self.graph.setMinimumHeight(70 if compact else 130)
        except Exception:
            pass

    def closeEvent(self, e):
        self.gen += 1
        try:
            if self.watching:
                self._watch_stop.set()
        except Exception:
            pass
        try:
            save_config(self.cfg)
        except OSError:
            pass
        try:
            if getattr(self, "tsume_dlg", None):
                self.tsume_dlg.close()          # 詰将棋の一覧ウインドウも一緒に閉じる
        except Exception:
            pass
        self.close_engine()
        self.close_tsume_engine()
        e.accept()
        QApplication.quit()



APP_QSS = """
/* Preserve original button metrics; custom buttons paint their own surfaces. */
QPushButton {
    background: #faf7ee; color: #3d3931;
    border: 1px solid #c8bfab; border-radius: 5px;
    padding: 5px 12px; min-height: 22px;
}
QPushButton:hover { background: #f1ebdb; border-color: #ac8745; }
QPushButton:pressed { background: #e7dfcb; }
QPushButton:checked { background: #e2eadf; color: #264734; border-color: #77917b; }
QPushButton[role="primary"] { color: #fff9e9; font-weight: bold; }
QPushButton[role="stop"] { color: #974c40; }
QPushButton:focus { border-color: #ac8745; }
QPushButton:disabled { background: #efede6; color: #a5a095; border-color: #ddd8cc; }
QPushButton[role="primary"]:disabled, QPushButton[role="stop"]:disabled { color: #a5a095; }
QDialogButtonBox QPushButton { min-width: 72px; }
"""


def main():
    app = QApplication(sys.argv)
    try:   # アプリ専用のアイコンを、ウインドウとタスクバーに付ける（kento.ico が無くても動く）
        from app_icon import apply_app_icon
        apply_app_icon(app, "kiei.ico", "Muramatsu.KieiShogi", folder=os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    f = app.font()
    f.setFamilies(FONT_FAMILIES)
    f.setPointSize(10)
    app.setFont(f)
    app.setStyleSheet(APP_QSS)
    w = MainWindow()
    w.show()
    # .kif をダブルクリックして起動されたときは、その棋譜を開く
    files = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if files:
        QTimer.singleShot(400, lambda: w.open_kif_path(files[0]))
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        with open(os.path.join(HERE, "error.log"), "w", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        raise
