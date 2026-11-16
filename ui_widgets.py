"""棋慧の共通ボタン。"""
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import QPushButton as NativePushButton, QStyleOptionButton, QStylePainter, QStyle

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

