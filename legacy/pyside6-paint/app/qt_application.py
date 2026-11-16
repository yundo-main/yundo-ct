"""PySide6 기반 그림판 UI."""

from pathlib import Path

from PIL import Image

from app.help_dialog import show_help
from array import array

from PySide6.QtCore import QByteArray, QDir, QPoint, QRect, QSettings, QSize, Qt, QTimer
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QImage, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QRadioButton,
    QColorDialog,
    QLabel,
    QMainWindow,
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFileSystemModel,
    QMessageBox,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QFrame,
    QPushButton,
    QSlider,
    QSpinBox,
    QTextEdit,
    QToolBar,
    QToolTip,
    QTreeView,
    QScrollArea,
    QWidget,
)


# 칠판(캔버스 바탕) 색상 선택지: (이름, 값). 값은 #rrggbb 또는 "transparent"
BOARD_COLORS = [
    ("흰색", "#ffffff"),
    ("검정", "#111111"),
    ("칠판 초록", "#2d4a3e"),
    ("남색", "#1f2a44"),
    ("회색", "#808080"),
    ("투명", "transparent"),
]


def _luminance(color: QColor) -> float:
    """WCAG 상대 휘도(0=검정, 1=흰색)."""
    def channel(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())


def _contrast_ratio(a: QColor, b: QColor) -> float:
    """두 색의 명암비(1~21). 3 미만이면 글씨/선이 칠판에서 잘 안 보인다."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


THEME_LIGHT = {
    "win": "#c6d1e2", "panel_bg": "#dceaf5", "panel_border": "#c1d3e2",
    "title_bg": "#c2dced", "title_fg": "#1f4665", "title_border": "#9ebbd2",
    "bar_bg": "#d8e8f7", "bar_border": "#9db8d3", "bar_sel": "#b9d7f0", "text": "#243b53", "label": "#36566f",
    "btn_bg": "#eaf3fb", "btn_fg": "#334155", "btn_border": "#b4c9da", "btn_hover": "#c9e4f8", "btn_hover_b": "#5b9bd5",
    "btn_press": "#b8d9f2", "btn_press_b": "#4b8fbe",
    "tool_chk": "#b4d8f1", "tool_chk_b": "#2563a6", "tool_chk_fg": "#173a56", "sec_chk": "#8fc1e5", "sec_chk_fg": "#123b63",
    "input_bg": "#ffffff", "input_border": "#cbd5e1", "status_bg": "#f8fafc", "status_fg": "#475569", "sep": "#a9bfd2",
    "ruler_bg": "#e8eef5", "ruler_fg": "#7c91a6", "base": "#ffffff", "window": "#eef3f8",
}
THEME_DARK = {
    "win": "#0f1624", "panel_bg": "#1b2638", "panel_border": "#2a3a52",
    "title_bg": "#243349", "title_fg": "#cfe3f6", "title_border": "#3a4d69",
    "bar_bg": "#16202f", "bar_border": "#2a3a52", "bar_sel": "#2c4466", "text": "#dbe7f3", "label": "#a9bdd1",
    "btn_bg": "#223048", "btn_fg": "#dbe7f3", "btn_border": "#3a4d69", "btn_hover": "#2d4263", "btn_hover_b": "#5b9bd5",
    "btn_press": "#30496f", "btn_press_b": "#6db3e6",
    "tool_chk": "#2f5381", "tool_chk_b": "#6db3e6", "tool_chk_fg": "#ffffff", "sec_chk": "#3a6a9c", "sec_chk_fg": "#ffffff",
    "input_bg": "#111a28", "input_border": "#3a4d69", "status_bg": "#16202f", "status_fg": "#a9bdd1", "sep": "#3a4d69",
    "ruler_bg": "#16202f", "ruler_fg": "#8aa0b8", "base": "#111a28", "window": "#1b2638",
}
THEME_NAMES = [("system", "시스템 설정에 맞춤"), ("light", "밝게"), ("dark", "어둡게")]


def main_qss(t: dict) -> str:
    return f"""
        QMainWindow {{ background: {t['win']}; }}
        QWidget {{ font-family: Arial; font-size: 10px; }}
        QToolTip {{ background: #243b53; color: #ffffff; border: 1px solid #8fb3d1; padding: 4px 6px; }}
        QMenuBar {{ background: {t['bar_bg']}; color: {t['text']}; border-bottom: 1px solid {t['bar_border']}; padding: 2px 6px; }}
        QMenuBar::item {{ padding: 5px 12px; }}
        QMenuBar::item:selected {{ background: {t['bar_sel']}; }}
        QToolBar {{ background: {t['bar_bg']}; border: 0; border-bottom: 1px solid {t['bar_border']}; spacing: 2px; padding: 4px 6px 6px 6px; }}
        QToolBar::handle {{ width: 0px; height: 0px; }}
        QToolBar QLabel {{ color: {t['label']}; font-size: 10px; font-weight: 600; }}
        QToolBar QComboBox, QToolBar QSpinBox {{ font-size: 11px; }}
        QPushButton {{ background: {t['btn_bg']}; color: {t['btn_fg']}; border: 1px solid {t['btn_border']}; border-radius: 3px; padding: 2px; }}
        QPushButton:hover {{ background: {t['btn_hover']}; border-color: {t['btn_hover_b']}; }}
        QPushButton:pressed, QPushButton:checked {{ background: {t['btn_press']}; border-color: {t['btn_press_b']}; }}
        QPushButton[toolButton="true"] {{ font-size: 18px; font-weight: 600; padding: 0px; border-radius: 4px; }}
        QPushButton[toolButton="true"]:checked {{ background: {t['tool_chk']}; border: 2px solid {t['tool_chk_b']}; color: {t['tool_chk_fg']}; }}
        QPushButton[sectionButton="true"]:checked {{ background: {t['sec_chk']}; border: 1px solid {t['tool_chk_b']}; color: {t['sec_chk_fg']}; }}
        QPushButton[sectionButton="true"] {{ font-size: 10px; font-weight: 600; padding: 0px; }}
        QComboBox, QSpinBox {{ background: {t['input_bg']}; color: {t['btn_fg']}; border: 1px solid {t['input_border']}; border-radius: 5px; padding: 1px 4px; min-height: 20px; max-height: 20px; }}
        QSpinBox::up-button, QSpinBox::down-button {{ width: 20px; }}
        QStatusBar {{ background: {t['status_bg']}; color: {t['status_fg']}; border-top: 1px solid {t['input_border']}; }}
    """


def panel_qss(t: dict) -> str:
    return f"#panel {{ background: {t['panel_bg']}; border: 1px solid {t['panel_border']}; border-radius: 3px; }}"


def title_qss(t: dict) -> str:
    return (f"background: {t['title_bg']}; color: {t['title_fg']}; font-size: 13px; font-weight: 700; "
            f"padding: 1px 0; border-bottom: 1px solid {t['title_border']}; border-radius: 2px;")


def toolbar_qss(t: dict) -> str:
    return (f"QToolBar {{ background: {t['bar_bg']}; border: 0; border-right: 1px solid {t['bar_border']}; "
            "spacing: 2px; padding: 4px; margin: 0px; }")


def make_palette(t: dict) -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t["window"]))
    pal.setColor(QPalette.WindowText, QColor(t["text"]))
    pal.setColor(QPalette.Base, QColor(t["base"]))
    pal.setColor(QPalette.AlternateBase, QColor(t["panel_bg"]))
    pal.setColor(QPalette.Text, QColor(t["text"]))
    pal.setColor(QPalette.Button, QColor(t["btn_bg"]))
    pal.setColor(QPalette.ButtonText, QColor(t["btn_fg"]))
    pal.setColor(QPalette.ToolTipBase, QColor("#243b53"))
    pal.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    pal.setColor(QPalette.Highlight, QColor("#2563a6"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.PlaceholderText, QColor(t["label"]))
    return pal


# 도구 아이콘: 24x24 선(stroke) 아이콘. 글자 기호(✎ ◒ ▩ …)는 글꼴마다 모양이 달라 어색해서 직접 그린다.
TOOL_ICONS = {
    "연필": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "브러시": '<path d="M18.4 2.6a2 2 0 0 1 3 3L12 15l-3-3z"/><path d="M9 12c-3 0-4 2-4 4s-1 3-3 4c4 1 9 0 9-5"/>',
    "지우개": '<path d="M20 20H8.5L3.8 15.3a2 2 0 0 1 0-2.8l8.5-8.5a2 2 0 0 1 2.8 0l5 5a2 2 0 0 1 0 2.8L12 20"/><path d="M7 11l6 6"/>',
    "텍스트": '<path d="M4 7V5h16v2"/><path d="M9 19h6"/><path d="M12 5v14"/>',
    "직선": '<path d="M5 19L19 5"/>',
    "사각형": '<rect x="4" y="5" width="16" height="14" rx="1.5"/>',
    "타원": '<ellipse cx="12" cy="12" rx="9" ry="6.5"/>',
    "색 채우기": '<path d="M19 11l-8-8-8.6 8.6a2 2 0 0 0 0 2.8l5.2 5.2c.8.8 2 .8 2.8 0z"/><path d="M5 2l5 5"/><path d="M2 13h15"/><path d="M22 20a2 2 0 1 1-4 0c0-1.6 1.7-2.4 2-4 .3 1.6 2 2.4 2 4z"/>',
    "색 선택": '<path d="M14.5 5.5l4 4"/><path d="M13 7l-9 9v4h4l9-9"/><path d="M16 4l1.5-1.5a2.1 2.1 0 0 1 3 3L19 7"/>',
    "선택": '<rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="3 3"/>',
    "영역 삭제": '<rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="3 3"/><path d="M9 9l6 6M15 9l-6 6"/>',
    "선택 영역 삭제": '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/><path d="M10 10v6M14 10v6"/>',
}


def svg_icon(name: str, normal: str, checked: str, size: int = 22) -> QIcon:
    """TOOL_ICONS의 선 아이콘을 지정한 색으로 그려 QIcon으로 만든다(선택됐을 때는 checked 색)."""
    icon = QIcon()
    for color, state in ((normal, QIcon.Off), (checked, QIcon.On)):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
               f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{TOOL_ICONS[name]}</svg>')
        ratio = 2
        pixmap = QPixmap(size * ratio, size * ratio)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(ratio)
        icon.addPixmap(pixmap, QIcon.Normal, state)
    return icon


class RulerWidget(QWidget):
    def __init__(self, orientation: Qt.Orientation, parent=None) -> None:
        super().__init__(parent)
        self.orientation = orientation
        self.unit = "px"
        self.zoom = 1.0
        self.offset = 0
        self.bg, self.fg = "#e8eef5", "#7c91a6"
        if orientation == Qt.Horizontal:
            self.setFixedHeight(18)
        else:
            self.setFixedWidth(24)

    def set_colors(self, bg: str, fg: str) -> None:
        self.bg, self.fg = bg, fg
        self.update()

    def set_measurement(self, unit: str, zoom: float, offset: int) -> None:
        self.unit = unit
        self.zoom = zoom
        self.offset = offset
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.bg))
        painter.setPen(QPen(QColor(self.fg), 1))
        base_pixels = {"px": 1.0, "cm": 37.795, "mm": 3.7795}[self.unit]
        unit_step = {"px": 10.0, "cm": 0.1, "mm": 1.0}[self.unit]
        minor_step = base_pixels * unit_step * self.zoom
        if minor_step < 2:
            unit_step *= 2
            minor_step = base_pixels * unit_step * self.zoom
        start = -self.offset % minor_step
        count = int((self.width() if self.orientation == Qt.Horizontal else self.height()) / minor_step) + 2
        for index in range(count):
            position = start + index * minor_step
            logical_unit = (position + self.offset) / (base_pixels * self.zoom)
            major = index % 10 == 0
            tick = 10 if major else 5
            if self.orientation == Qt.Horizontal:
                painter.drawLine(round(position), self.height(), round(position), self.height() - tick)
                if major:
                    painter.drawText(round(position) + 2, 11, self._format_value(logical_unit))
            else:
                painter.drawLine(self.width(), round(position), self.width() - tick, round(position))
                if major:
                    painter.save()
                    painter.translate(9, round(position) - 2)
                    painter.rotate(-90)
                    painter.drawText(0, 0, self._format_value(logical_unit))
                    painter.restore()

    def _format_value(self, value: float) -> str:
        if self.unit == "px":
            return str(round(value))
        return f"{value:.1f}".rstrip("0").rstrip(".")


class PaletteButton(QPushButton):
    def __init__(self, color: str, foreground_callback, background_callback, parent=None) -> None:
        super().__init__(parent)
        self.color = color
        self.foreground_callback = foreground_callback
        self.background_callback = background_callback

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            self.background_callback(self.color)
            event.accept()
            return
        self.foreground_callback(self.color)
        super().mousePressEvent(event)


class HoverToolButton(QPushButton):
    """화면 가장자리에서도 잘리지 않도록 툴팁 위치를 조정하는 버튼."""

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        text = self.toolTip()
        if not text:
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        below = self.mapToGlobal(QPoint(0, self.height() + 4))
        above = self.mapToGlobal(QPoint(0, -8))
        position = below
        if below.y() + 42 > available.bottom():
            position = above
        if position.x() + 220 > available.right():
            position.setX(max(available.left() + 6, self.mapToGlobal(QPoint(-220, 0)).x()))
        QToolTip.showText(position, text, self)

    def leaveEvent(self, event) -> None:
        QToolTip.hideText()
        super().leaveEvent(event)


class InlineTextEdit(QTextEdit):
    def __init__(self, commit_callback, cancel_callback, parent=None) -> None:
        super().__init__(parent)
        self.commit_callback = commit_callback
        self.cancel_callback = cancel_callback
        self.focus_lost_callback = None
        self.setPlaceholderText("글씨를 입력하세요 (Ctrl+Enter 확정 · Esc 취소)")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.cancel_callback()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.commit_callback()
            return
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and not self.toPlainText():
            self.cancel_callback()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        # 다른 곳을 눌러 입력이 끝나면 글씨를 확정한다(바로 처리하지 않고 포커스가 옮겨간 뒤에 판단)
        if self.focus_lost_callback is not None:
            QTimer.singleShot(0, self.focus_lost_callback)


class PaintCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(800, 600)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.tool = "연필"
        self.color = QColor("black")
        self.background_color = QColor("white")  # 배경색 스와치(지우개가 쓰는 색)
        self.board_color = QColor("white")       # 칠판(캔버스 바탕) 색
        self.background_mode = "solid"           # "solid"(칠판색으로 채움) | "transparent"
        self.last_point: QPoint | None = None
        self.start_point: QPoint | None = None
        self.preview_image: QImage | None = None
        self.text_editor: InlineTextEdit | None = None
        self.text_font_family = "Arial"
        self.text_font_size = 24
        self.text_aux_widget: QWidget | None = None  # 글꼴 패널: 여기를 눌러도 입력을 끝내지 않는다
        self.on_hint = None
        self.zoom = 1.0
        self.grid_visible = False
        self.fill_shapes = False
        self.grid_size = 20
        self.eraser_width = 20
        self.stroke_widths = {
            "연필": 2,
            "브러시": 8,
            "직선": 2,
            "사각형": 2,
            "타원": 2,
        }
        self.selection_start: QPoint | None = None
        self.selection_rect: QRect | None = None
        self.moving_selection = False
        self.move_anchor: QPoint | None = None
        self.move_source: QImage | None = None
        self.move_original_rect: QRect | None = None
        self.modified = False
        self.undo_stack: list[QImage] = []
        self.redo_stack: list[QImage] = []
        self.on_change = None
        self.image = QImage(800, 600, QImage.Format_ARGB32)
        self.image.fill(Qt.white)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#c6d1e2"))
        if self.background_mode == "transparent":
            tile = 12
            for y in range(0, self.height(), tile):
                for x in range(0, self.width(), tile):
                    color = "#ffffff" if (x // tile + y // tile) % 2 == 0 else "#d9e0e8"
                    painter.fillRect(x, y, tile, tile, QColor(color))
        painter.scale(self.zoom, self.zoom)
        painter.drawImage(0, 0, self.image)
        if self.grid_visible:
            painter.setPen(QPen(QColor("#d7dee8"), 1))
            for x in range(0, self.image.width() + 1, self.grid_size):
                painter.drawLine(x, 0, x, self.image.height())
            for y in range(0, self.image.height() + 1, self.grid_size):
                painter.drawLine(0, y, self.image.width(), y)
        if self.selection_rect is not None:
            painter.setPen(QPen(QColor("#0066ff"), 2, Qt.DashLine))
            painter.drawRect(self.selection_rect)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.RightButton and self.tool == "색 선택":
            point = self._image_point(event.position().toPoint())
            self.background_color = self.image.pixelColor(point)
            self._notify()
            return
        if event.button() == Qt.LeftButton:
            self.commit_text()
            self.setFocus()
            self.last_point = self._image_point(event.position().toPoint())
            self.start_point = self.last_point
            self.preview_image = self.image.copy()
            if self.tool == "색 채우기":
                if self._flood_fill(self.last_point, self.color):
                    self._push_undo(self.preview_image)
                    self.modified = True
                self.last_point = None
                self.start_point = None
                self.preview_image = None
                self.update()
                return
            if self.tool == "색 선택":
                self.color = self.image.pixelColor(self.last_point)
                self.last_point = None
                self.start_point = None
                self.preview_image = None
                self._notify()
                return
            if (
                self.tool == "선택"
                and self.selection_rect is not None
                and self.selection_rect.width() > 1
                and self.selection_rect.height() > 1
                and self.selection_rect.contains(self.last_point)
            ):
                self.moving_selection = True
                self.move_anchor = QPoint(
                    self.last_point.x() - self.selection_rect.left(),
                    self.last_point.y() - self.selection_rect.top(),
                )
                self.move_source = self.image.copy()
                self.move_original_rect = QRect(self.selection_rect)
                return
            if self.tool in {"선택", "영역 삭제"}:
                self.selection_start = self.start_point
                self.selection_rect = QRect(self.start_point, self.start_point)
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.LeftButton) and self.tool == "선택":
            point = self._image_point(event.position().toPoint())
            if self.selection_rect is not None and self.selection_rect.contains(point):
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.CrossCursor)
        if self.moving_selection and self.tool == "선택" and event.buttons() & Qt.LeftButton:
            current = self._image_point(event.position().toPoint())
            source_rect = self.move_original_rect
            if self.move_source is not None and source_rect is not None and self.move_anchor is not None:
                new_left = current.x() - self.move_anchor.x()
                new_top = current.y() - self.move_anchor.y()
                new_left = max(0, min(self.image.width() - source_rect.width(), new_left))
                new_top = max(0, min(self.image.height() - source_rect.height(), new_top))
                self.image = self.move_source.copy()
                painter = QPainter(self.image)
                self._clear_rect(painter, source_rect)
                painter.drawImage(QPoint(new_left, new_top), self.move_source, source_rect)
                painter.end()
                self.selection_rect = QRect(new_left, new_top, source_rect.width(), source_rect.height())
                self.last_point = current
                self.update()
            return
        if self.tool in {"선택", "영역 삭제"} and self.start_point is not None and event.buttons() & Qt.LeftButton:
            current = self._image_point(event.position().toPoint())
            self.selection_rect = self._rect_from_points(self.start_point, current)
            self.last_point = current
            self.update()
            return
        if self.last_point is not None and event.buttons() & Qt.LeftButton:
            current = self._image_point(event.position().toPoint())
            if self.tool in {"연필", "브러시", "지우개"}:
                painter = QPainter(self.image)
                color = self.background_color if self.tool == "지우개" else self.color
                width = self.eraser_width if self.tool == "지우개" else self.stroke_widths.get(self.tool, 2)
                if self.tool == "지우개" and self.background_mode == "transparent":
                    painter.setCompositionMode(QPainter.CompositionMode_Clear)
                painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.drawLine(self.last_point, current)
            elif self.tool in {"직선", "사각형", "타원"}:
                self.image = self.preview_image.copy()
                painter = QPainter(self.image)
                painter.setPen(QPen(self.color, self.stroke_widths.get(self.tool, 2)))
                painter.setBrush(self.color if self.fill_shapes else Qt.NoBrush)
                if self.tool == "직선":
                    painter.drawLine(self.start_point, current)
                elif self.tool == "사각형":
                    painter.drawRect(self.start_point.x(), self.start_point.y(), current.x() - self.start_point.x(), current.y() - self.start_point.y())
                else:
                    painter.drawEllipse(self.start_point.x(), self.start_point.y(), current.x() - self.start_point.x(), current.y() - self.start_point.y())
            elif self.tool == "텍스트":
                self.image = self.preview_image.copy()
                painter = QPainter(self.image)
                painter.setPen(QPen(self.color, 1, Qt.DashLine))
                painter.drawRect(self._rect_from_points(self.start_point, current))
            elif self.tool == "선택":
                self.selection_rect = self._rect_from_points(self.selection_start, current)
            elif self.tool == "영역 삭제":
                self.image = self.preview_image.copy()
                self.selection_rect = self._rect_from_points(self.selection_start, current)
                painter = QPainter(self.image)
                painter.setPen(QPen(Qt.red, 1, Qt.DashLine))
                painter.drawRect(self.selection_rect)
            self.last_point = current
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self.moving_selection:
                if self.selection_rect != self.move_original_rect:
                    self._push_undo(self.move_source)
                    self.modified = True
                self.moving_selection = False
                self.move_anchor = None
                self.move_source = None
                self.move_original_rect = None
                self.last_point = None
                self.start_point = None
                self.preview_image = None
                self.update()
                return
            if self.tool == "선택" and self.selection_start is not None:
                self.selection_rect = self._rect_from_points(self.selection_start, self._image_point(event.position().toPoint()))
            if self.tool == "영역 삭제" and self.selection_start is not None:
                rect = self._rect_from_points(self.selection_start, self._image_point(event.position().toPoint()))
                painter = QPainter(self.image)
                self._clear_rect(painter, rect)
                painter.end()
                self._push_undo(self.preview_image)
                self.selection_rect = None
                self.modified = True
            if self.tool == "텍스트" and self.start_point is not None:
                rect = self._rect_from_points(self.start_point, self._image_point(event.position().toPoint()))
                self.image = self.preview_image.copy()
                self._begin_text_edit(rect)
            if self.tool in {"연필", "브러시", "지우개", "직선", "사각형", "타원"} and self.start_point is not None:
                self._push_undo(self.preview_image)
                self.modified = True
            self.last_point = None
            self.start_point = None
            self.preview_image = None
            if self.tool == "선택" and self.selection_rect is not None and self.selection_rect.width() > 1 and self.selection_rect.height() > 1:
                self.setCursor(Qt.SizeAllCursor)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selection_rect is not None:
            self.delete_selection()
            return
        super().keyPressEvent(event)

    def delete_selection(self) -> None:
        if self.text_editor is not None:
            self._cancel_text()
            return
        if self.selection_rect is None:
            return
        self._push_undo()
        painter = QPainter(self.image)
        self._clear_rect(painter, self.selection_rect)
        painter.end()
        self.selection_rect = None
        self.modified = True
        self.update()

    def _push_undo(self, state: QImage | None = None) -> None:
        """현재 상태(또는 지정한 상태)를 실행 취소 스택에 저장한다."""
        self.undo_stack.append(state.copy() if state is not None else self.image.copy())
        if len(self.undo_stack) > 25:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def undo(self) -> None:
        if not self.undo_stack:
            return
        self.redo_stack.append(self.image.copy())
        self.image = self.undo_stack.pop()
        self._after_history_change()

    def redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append(self.image.copy())
        self.image = self.redo_stack.pop()
        self._after_history_change()

    def _after_history_change(self) -> None:
        self.selection_rect = None
        self.moving_selection = False
        self.modified = True
        self.set_zoom(round(self.zoom * 100))
        self._notify()

    def _flood_fill(self, start: QPoint, fill: QColor) -> bool:
        width, height = self.image.width(), self.image.height()
        if not (0 <= start.x() < width and 0 <= start.y() < height):
            return False
        target = self.image.pixelColor(start)
        if target.rgba() == fill.rgba():
            return False
        target_bytes = bytes((target.blue(), target.green(), target.red(), target.alpha()))
        fill_bytes = bytes((fill.blue(), fill.green(), fill.red(), fill.alpha()))
        data = bytearray(self.image.constBits().tobytes())
        row_bytes = width * 4
        stack = [(start.x(), start.y())]
        while stack:
            x, y = stack.pop()
            row = y * row_bytes
            left, right = x, x
            while left > 0 and data[row + (left - 1) * 4 : row + left * 4] == target_bytes:
                left -= 1
            while right + 1 < width and data[row + (right + 1) * 4 : row + (right + 2) * 4] == target_bytes:
                right += 1
            for px in range(left, right + 1):
                data[row + px * 4 : row + px * 4 + 4] = fill_bytes
            for ny in (y - 1, y + 1):
                if not 0 <= ny < height:
                    continue
                nrow = ny * row_bytes
                px = left
                while px <= right:
                    if data[nrow + px * 4 : nrow + px * 4 + 4] == target_bytes:
                        stack.append((px, ny))
                        while px <= right and data[nrow + px * 4 : nrow + px * 4 + 4] == target_bytes:
                            px += 1
                    else:
                        px += 1
        self.image = QImage(bytes(data), width, height, row_bytes, QImage.Format_ARGB32).copy()
        return True

    def _rect_from_points(self, first: QPoint, second: QPoint) -> QRect:
        return QRect(first, second).normalized()

    def _image_point(self, point: QPoint) -> QPoint:
        x = max(0, min(self.image.width() - 1, round(point.x() / self.zoom)))
        y = max(0, min(self.image.height() - 1, round(point.y() / self.zoom)))
        return QPoint(x, y)

    def set_zoom(self, value: int) -> None:
        self.zoom = max(0.25, value / 100.0)
        self.setFixedSize(
            max(1, round(self.image.width() * self.zoom)),
            max(1, round(self.image.height() * self.zoom)),
        )
        self.update()

    def set_grid_visible(self, visible: bool) -> None:
        self.grid_visible = visible
        self.update()

    def _clear_color(self):
        return self.board_color if self.background_mode == "solid" else Qt.transparent

    def _clear_rect(self, painter: QPainter, rect: QRect) -> None:
        if self.background_mode == "transparent":
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        else:
            painter.fillRect(rect, self.board_color)

    def _replace_pixels(self, old: int, new: int) -> None:
        """색이 정확히 old(0xAARRGGBB)인 픽셀을 모두 new로 바꾼다."""
        img = self.image.convertToFormat(QImage.Format_ARGB32)
        width, height = img.width(), img.height()
        pixels = array("I")
        pixels.frombytes(bytes(img.constBits()))
        if pixels.itemsize != 4:
            return
        pixels = array("I", [new if value == old else value for value in pixels])
        self.image = QImage(pixels.tobytes(), width, height, width * 4, QImage.Format_ARGB32).copy()

    def set_background_mode(self, mode: str, color: QColor | None = None) -> None:
        """칠판 바탕을 바꾼다. 기존 그림은 유지하고 칠판색 픽셀만 새 색으로 바뀐다(실행 취소 가능)."""
        new_color = QColor(color) if color is not None else self.board_color
        if mode == self.background_mode and (mode == "transparent" or new_color == self.board_color):
            self.update()
            return
        self._push_undo()
        if mode == "transparent":
            if self.background_mode == "solid":
                self._replace_pixels(self.board_color.rgba(), 0)  # 칠판색 → 투명
        elif self.background_mode == "transparent":
            under = QImage(self.image.size(), QImage.Format_ARGB32)  # 투명한 곳에 칠판색을 깐다
            under.fill(new_color)
            painter = QPainter(under)
            painter.drawImage(0, 0, self.image)
            painter.end()
            self.image = under
        else:
            self._replace_pixels(self.board_color.rgba(), new_color.rgba())
        if mode == "solid":
            self.board_color = new_color
        self.background_mode = mode
        self.modified = True
        self.update()

    def _begin_text_edit(self, rect: QRect) -> None:
        if self.text_editor is not None:
            self._commit_text()
        if rect.width() < 10 or rect.height() < 10:  # 클릭만 한 경우: 글자 크기에 맞는 기본 상자(두 줄 높이)
            line_px = self.text_font_size * 96 / 72
            rect = QRect(rect.topLeft(), QPoint(rect.left() + max(260, round(line_px * 9)), rect.top() + round(line_px * 2.6)))
        self.text_editor = InlineTextEdit(self._commit_text, self._cancel_text, self)
        self.text_editor.focus_lost_callback = self._text_focus_lost
        self.text_editor.setGeometry(
            round(rect.left() * self.zoom),
            round(rect.top() * self.zoom),
            max(10, round(rect.width() * self.zoom)),
            max(10, round(rect.height() * self.zoom)),
        )
        self._apply_editor_font()
        self.text_editor.show()
        self.text_editor.setFocus()
        if self.on_hint is not None:
            self.on_hint("글씨 입력 중 — Ctrl+Enter 또는 다른 곳 클릭: 확정, Esc: 취소")

    def _editor_background(self) -> QColor:
        """입력 상자 배경: 칠판색과 같게 해서 글씨가 확정된 뒤와 같은 모습으로 보이게 한다."""
        if self.background_mode == "solid":
            return self.board_color
        return QColor("#ffffff") if _contrast_ratio(self.color, QColor("#ffffff")) >= 3 else QColor("#2b2b2b")

    def _apply_editor_font(self) -> None:
        """입력 상자의 글꼴·색·배경을 상자 자체 스타일로 지정한다.
        앱 전체 스타일시트가 setFont를 덮어쓰므로 스타일시트에 넣어야 하고, 크기는 확정할 때(96dpi 이미지)와
        같아지도록 pt를 96/72 배한 픽셀로 쓴다. 확대/축소에도 맞춘다."""
        if self.text_editor is None:
            return
        px = max(1.0, self.text_font_size * 96 / 72 * self.zoom)
        bg = self._editor_background()
        self.text_editor.setStyleSheet(
            f'background: rgba({bg.red()},{bg.green()},{bg.blue()},235); color: {self.color.name()}; '
            f'border: 1px dashed #888; font-family: "{self.text_font_family}"; font-size: {px:.1f}px;'
        )

    def _text_focus_lost(self) -> None:
        """입력 상자에서 포커스가 나간 뒤: 글꼴 패널로 간 것이거나 창 전환이면 계속 입력 중으로 둔다."""
        if self.text_editor is None:
            return
        focused = QApplication.focusWidget()
        if focused is None or focused is self.text_editor:
            return
        if self.text_aux_widget is not None and (
            focused is self.text_aux_widget or self.text_aux_widget.isAncestorOf(focused)
        ):
            return
        self._commit_text()

    def commit_text(self) -> None:
        """입력 중인 글씨가 있으면 캔버스에 확정한다(도구 전환·저장·새로 만들기 전에 호출)."""
        if self.text_editor is not None:
            self._commit_text()

    def _commit_text(self) -> None:
        if self.text_editor is None:
            return
        text = self.text_editor.toPlainText()
        editor_rect = self.text_editor.geometry()
        rect = QRect(
            round(editor_rect.left() / self.zoom),
            round(editor_rect.top() / self.zoom),
            max(1, round(editor_rect.width() / self.zoom)),
            max(1, round(editor_rect.height() / self.zoom)),
        )
        if text:
            self._push_undo()
            painter = QPainter(self.image)
            painter.setPen(self.color)
            painter.setFont(QFont(self.text_font_family, self.text_font_size))
            painter.drawText(rect, Qt.TextWordWrap, text)
            self.modified = True
        self.text_editor.deleteLater()
        self.text_editor = None
        self.update()

    def _cancel_text(self) -> None:
        if self.text_editor is not None:
            self.text_editor.deleteLater()
            self.text_editor = None
            self.image = self.preview_image.copy() if self.preview_image is not None else self.image
            self.update()

    def set_text_font(self, family: str, size: int) -> None:
        self.text_font_family = family
        self.text_font_size = size
        if self.text_editor is not None:
            self._apply_editor_font()
            self.text_editor.setFocus()  # 글꼴을 바꾼 뒤 바로 이어서 타이핑할 수 있게


class QtPaintApplication(QMainWindow):
    def __init__(self) -> None:
        self._init_ui()
        saved = QSettings("yundo-ct", "paint").value("theme", "system")
        self._set_theme(saved if saved in {n for n, _ in THEME_NAMES} else "system", save=False)

    def _style(self, widget, fn) -> None:
        """스타일을 지금 테마로 적용하고, 테마를 바꿀 때 다시 적용되도록 등록한다."""
        self._themed.append((widget, fn))
        widget.setStyleSheet(fn(self.theme_colors))

    def _resolve_theme(self, pref: str) -> str:
        if pref in ("light", "dark"):
            return pref
        scheme = QApplication.styleHints().colorScheme() if hasattr(QApplication.styleHints(), "colorScheme") else None
        return "dark" if scheme == Qt.ColorScheme.Dark else "light"

    def _set_theme(self, pref: str, save: bool = True) -> None:
        self.theme_pref = pref
        self.theme_name = self._resolve_theme(pref)
        self.theme_colors = THEME_DARK if self.theme_name == "dark" else THEME_LIGHT
        t = self.theme_colors
        app = QApplication.instance()
        if not hasattr(app, "_base_style"):
            app._base_style = app.style().objectName()
        app.setStyle("Fusion" if self.theme_name == "dark" else app._base_style)  # 어두운 팔레트는 Fusion에서 가장 안정적이다
        self.setPalette(make_palette(t))
        self.setStyleSheet(main_qss(t))
        for widget, fn in self._themed:
            widget.setStyleSheet(fn(t))
        for name, button in self._tool_icon_buttons.items():
            button.setIcon(svg_icon(name, t["btn_fg"], t["tool_chk_fg"]))
        self.horizontal_ruler.set_colors(t["ruler_bg"], t["ruler_fg"])
        self.vertical_ruler.set_colors(t["ruler_bg"], t["ruler_fg"])
        if hasattr(self, "theme_actions"):
            self.theme_actions[pref].setChecked(True)
        if save:
            QSettings("yundo-ct", "paint").setValue("theme", pref)

    def _init_ui(self) -> None:
        super().__init__()
        self.theme_colors = THEME_LIGHT
        self.setWindowTitle("Untitled - Paint")
        icon_path = Path(__file__).resolve().parent.parent / "assets" / "paint_icon.svg"
        self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1120, 820)
        self._tool_icon_buttons = {}
        self._themed = []  # (위젯, 스타일 만드는 함수): 테마를 바꿀 때 다시 적용한다
        self.theme_pref = "system"
        self.canvas = PaintCanvas()
        self.canvas.on_change = self._on_canvas_changed
        self.canvas.on_hint = lambda message: self.statusBar().showMessage(message)
        self.current_file: Path | None = None
        self.canvas_area = QScrollArea()
        self.canvas_area.setWidget(self.canvas)
        self.canvas_area.setWidgetResizable(False)
        self.canvas_area.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._style(self.canvas_area, lambda t: f"QScrollArea {{ border: 0; background: {t['win']}; }}")
        self.horizontal_ruler = RulerWidget(Qt.Horizontal)
        self.vertical_ruler = RulerWidget(Qt.Vertical)
        canvas_container = QWidget()
        canvas_layout = QGridLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)
        canvas_layout.addWidget(QLabel(), 0, 0)
        canvas_layout.addWidget(self.horizontal_ruler, 0, 1)
        canvas_layout.addWidget(self.vertical_ruler, 1, 0)
        canvas_layout.addWidget(self.canvas_area, 1, 1)
        self.setCentralWidget(canvas_container)
        self.canvas_area.horizontalScrollBar().valueChanged.connect(self._update_rulers)
        self.canvas_area.verticalScrollBar().valueChanged.connect(self._update_rulers)
        self.statusBar().showMessage("준비")
        background_status_label = QLabel("칠판")
        self.statusBar().addPermanentWidget(background_status_label, 0)
        background_box = QComboBox()
        background_box.setFixedWidth(104)
        for name, value in BOARD_COLORS:
            background_box.addItem(name, value)
        background_box.setToolTip("칠판 색상")
        background_box.currentIndexChanged.connect(lambda index: self._set_board(background_box.itemData(index)))
        self.background_box = background_box
        self.statusBar().addPermanentWidget(background_box, 0)
        background_status_label.show()
        background_box.show()
        self.canvas_size_label = QLabel()
        self.zoom_label = QLabel("100%")
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(25, 400)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(110)
        self.zoom_slider.valueChanged.connect(self._zoom_changed)
        credit_label = QLabel("Produced by yundo")
        credit_label.setStyleSheet("color: #7c91a6; padding-right: 10px;")
        self.statusBar().addPermanentWidget(credit_label)
        self.statusBar().addPermanentWidget(self.canvas_size_label)
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.statusBar().addPermanentWidget(self.zoom_slider)
        self.statusBar().clearMessage()
        self._build_menu()
        self._build_toolbar()
        self._build_file_browser()
        self._update_canvas_info()
        self._update_rulers()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("파일")
        for text, shortcut, handler in (
            ("새로 만들기", "Ctrl+N", self._new_image),
            ("열기...", "Ctrl+O", self._open_image),
            ("저장", "Ctrl+S", self._save_image),
            ("다른 이름으로 저장...", "Ctrl+Shift+S", self._save_image_as),
        ):
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(handler)
            file_menu.addAction(action)
        file_menu.addSeparator()
        quit_action = QAction("종료", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        edit_menu = self.menuBar().addMenu("편집")
        undo_action = QAction("실행 취소", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self.canvas.undo)
        edit_menu.addAction(undo_action)
        redo_action = QAction("다시 실행", self)
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(self.canvas.redo)
        edit_menu.addAction(redo_action)
        edit_menu.addSeparator()
        delete_action = QAction("선택 영역/텍스트 박스 삭제", self)
        delete_action.setShortcuts([Qt.Key_Delete, Qt.Key_Backspace])
        delete_action.setShortcutContext(Qt.WindowShortcut)
        delete_action.triggered.connect(self.canvas.delete_selection)
        edit_menu.addAction(delete_action)
        view_menu = self.menuBar().addMenu("보기")
        self.view_menu = view_menu
        self.grid_action = QAction("격자 표시", self)
        self.grid_action.setCheckable(True)
        self.grid_action.setShortcut("Ctrl+G")
        self.grid_action.toggled.connect(self._toggle_grid)
        view_menu.addAction(self.grid_action)
        view_menu.addSeparator()
        self.ruler_action = QAction("눈금 표시", self)
        self.ruler_action.setCheckable(True)
        self.ruler_action.setChecked(True)
        self.ruler_action.toggled.connect(self._toggle_rulers)
        view_menu.addAction(self.ruler_action)
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("화면 테마")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        self.theme_actions = {}
        for name, label in THEME_NAMES:
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, n=name: self._set_theme(n))
            theme_group.addAction(action)
            theme_menu.addAction(action)
            self.theme_actions[name] = action
        view_menu.addSeparator()
        board_menu = view_menu.addMenu("칠판 색상")
        board_group = QActionGroup(self)
        board_group.setExclusive(True)
        self.board_actions = {}
        for name, value in BOARD_COLORS:
            action = QAction(name, self)
            action.setCheckable(True)
            action.setChecked(value == "#ffffff")
            board_group.addAction(action)
            board_menu.addAction(action)
            action.toggled.connect(lambda checked, v=value: checked and self._set_board(v))
            self.board_actions[value] = action
        image_menu = self.menuBar().addMenu("이미지")
        canvas_size_action = QAction("캔버스 크기...", self)
        canvas_size_action.triggered.connect(self._resize_canvas)
        image_menu.addAction(canvas_size_action)
        help_menu = self.menuBar().addMenu("도움말")
        for text, shortcut, tab in (
            ("사용법", "F1", 0),
            ("단축키 목록", None, 1),
            ("정보", None, 2),
        ):
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(lambda checked=False, t=tab: show_help(self, t))
            help_menu.addAction(action)

    def _build_file_browser(self) -> None:
        self.file_browser_dock = QDockWidget("파일 브라우저", self)
        self.file_browser_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        self.file_browser_dock.setMinimumWidth(240)
        self.file_browser_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.file_model = QFileSystemModel(self)
        self.file_model.setRootPath(str(Path.cwd()))
        self.file_model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
        self.file_tree = QTreeView()
        self.file_tree.setModel(self.file_model)
        self.file_tree.setRootIndex(self.file_model.index(str(Path.cwd())))
        self.file_tree.setColumnWidth(0, 180)
        self.file_tree.doubleClicked.connect(self._open_file_from_browser)
        self.file_browser_dock.setWidget(self.file_tree)
        self.addDockWidget(Qt.RightDockWidgetArea, self.file_browser_dock)
        self.file_browser_dock.hide()
        self.file_browser_action = QAction("파일 브라우저", self)
        self.file_browser_action.setCheckable(True)
        self.file_browser_action.setShortcut("Ctrl+B")
        self.file_browser_action.toggled.connect(self.file_browser_dock.setVisible)
        self.file_browser_dock.visibilityChanged.connect(self.file_browser_action.setChecked)
        self.file_toggle_button.toggled.connect(self.file_browser_action.setChecked)
        self.file_browser_action.toggled.connect(self.file_toggle_button.setChecked)

        self.toolbox_action = QAction("도구상자", self)
        self.toolbox_action.setCheckable(True)
        self.toolbox_action.setChecked(True)
        self.toolbox_action.setShortcut("Ctrl+Shift+T")
        self.toolbox_action.toggled.connect(self.toolbox_toolbar.setVisible)
        self.toolbox_toolbar.visibilityChanged.connect(self.toolbox_action.setChecked)
        self.toolbox_toggle_button.toggled.connect(self.toolbox_action.setChecked)
        self.toolbox_action.toggled.connect(self.toolbox_toggle_button.setChecked)

        self.view_menu.addSeparator()
        self.view_menu.addAction(self.toolbox_action)
        self.view_menu.addAction(self.file_browser_action)

    def _open_file_from_browser(self, index) -> None:
        path = self.file_model.filePath(index)
        if Path(path).is_dir() or not self._confirm_discard():
            return
        self._load_image_file(path)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("도구")
        toolbar.setOrientation(Qt.Vertical)
        toolbar.setContentsMargins(0, 0, 0, 0)
        self._style(toolbar, toolbar_qss)
        toolbar.setFixedWidth(300)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setAllowedAreas(Qt.LeftToolBarArea | Qt.RightToolBarArea)
        # 도구상자는 고정 배치이므로 툴바 자체의 '핸들 드래그' 안내는 표시하지 않는다.
        toolbar.setToolTip("")
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        self.toolbox_toolbar = toolbar
        tools = (
            ("", "연필"), ("", "브러시"), ("", "지우개"), ("", "텍스트"), ("", "직선"),
            ("", "사각형"), ("", "타원"), ("", "색 채우기"), ("", "색 선택"), ("", "선택"),
            ("", "영역 삭제"), ("", "선택 영역 삭제"),
        )
        tool_panel = QWidget()
        tool_panel.setObjectName("panel")
        tool_panel.setFixedWidth(292)
        tool_panel.setFixedHeight(241)
        self._style(tool_panel, panel_qss)
        tool_layout = QGridLayout(tool_panel)
        tool_layout.setContentsMargins(8, 3, 8, 3)
        tool_layout.setHorizontalSpacing(6)
        tool_layout.setVerticalSpacing(3)
        tool_title = QLabel("도구 · 도형")
        tool_title.setAlignment(Qt.AlignCenter)
        tool_title.setFixedHeight(22)
        self._style(tool_title, title_qss)
        tool_layout.addWidget(tool_title, 0, 0, 1, 2)
        self.tool_title = tool_title
        tool_buttons = {}
        tool_shortcuts = {
            "연필": "P", "브러시": "B", "지우개": "E", "직선": "L", "사각형": "R",
            "타원": "O", "선택": "S", "영역 삭제": "D", "텍스트": "T",
            "색 채우기": "F", "색 선택": "I",
        }
        for index, (icon, name) in enumerate(tools):
            button = HoverToolButton(icon)
            button.setIconSize(QSize(22, 22))
            self._tool_icon_buttons[name] = button
            shortcut = tool_shortcuts.get(name)
            button.setToolTip(f"{name} 도구" + (f" ({shortcut})" if shortcut else ""))
            button.setFixedSize(58, 32)
            button.setCheckable(name != "선택 영역 삭제")
            button.setProperty("toolButton", True)
            button.setFocusPolicy(Qt.StrongFocus)
            if name == "선택 영역 삭제":
                button.setToolTip("선택 영역 삭제 실행")
                button.clicked.connect(self.canvas.delete_selection)
            else:
                button.clicked.connect(lambda checked=False, value=name: self._select_tool(value))
                if shortcut:
                    tool_action = QAction(name, self)
                    tool_action.setShortcut(shortcut)
                    tool_action.setShortcutContext(Qt.WindowShortcut)
                    tool_action.triggered.connect(lambda checked=False, value=name: self._select_tool(value))
                    self.addAction(tool_action)
            tool_layout.addWidget(button, 1 + index // 2, index % 2)
            tool_buttons[name] = button
            if index == 0:
                button.setChecked(True)
        self.tool_buttons = tool_buttons
        toolbar.addWidget(tool_panel)
        view_panel = QWidget()
        view_panel.setObjectName("panel")
        view_panel.setFixedSize(292, 125)
        self._style(view_panel, panel_qss)
        view_layout = QGridLayout(view_panel)
        view_layout.setContentsMargins(8, 3, 8, 3)
        view_layout.setSpacing(2)
        view_title = QLabel("보기")
        view_title.setAlignment(Qt.AlignCenter)
        view_title.setFixedHeight(22)
        self._style(view_title, title_qss)
        view_layout.addWidget(view_title, 0, 0, 1, 2)
        grid_button = HoverToolButton("격자")
        grid_button.setFixedSize(130, 32)
        grid_button.setProperty("sectionButton", True)
        grid_button.setCheckable(True)
        grid_button.setFocusPolicy(Qt.StrongFocus)
        grid_button.setToolTip("격자 표시/숨기기 (Ctrl+G)")
        grid_button.toggled.connect(self.grid_action.setChecked)
        self.grid_button = grid_button
        view_layout.addWidget(grid_button, 1, 0)
        ruler_button = HoverToolButton("눈금")
        ruler_button.setFixedSize(130, 32)
        ruler_button.setProperty("sectionButton", True)
        ruler_button.setCheckable(True)
        ruler_button.setChecked(True)
        ruler_button.setFocusPolicy(Qt.StrongFocus)
        ruler_button.setToolTip("눈금 표시/숨기기")
        ruler_button.toggled.connect(self.ruler_action.setChecked)
        self.ruler_button = ruler_button
        view_layout.addWidget(ruler_button, 1, 1)
        unit_label = QLabel("단위")
        unit_label.setFixedWidth(90)
        unit_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        view_layout.addWidget(unit_label, 2, 0)
        unit_box = QComboBox()
        unit_box.setFixedWidth(130)
        unit_box.addItem("px", "px")
        unit_box.addItem("cm", "cm")
        unit_box.addItem("mm", "mm")
        unit_box.setToolTip("눈금 단위")
        unit_box.currentIndexChanged.connect(lambda index: self._unit_changed(unit_box.itemData(index)))
        self.unit_box = unit_box
        view_layout.addWidget(unit_box, 2, 1)
        file_toggle_button = HoverToolButton("파일")
        file_toggle_button.setFixedSize(260, 28)
        file_toggle_button.setProperty("sectionButton", True)
        file_toggle_button.setCheckable(True)
        file_toggle_button.setFocusPolicy(Qt.StrongFocus)
        file_toggle_button.setToolTip("오른쪽 파일 브라우저 표시/숨기기")
        self.file_toggle_button = file_toggle_button
        view_layout.addWidget(file_toggle_button, 3, 0, 1, 2)

        # 도구상자를 숨겨도 다시 켤 수 있도록 토글은 고정된 상태 표시줄에 둔다.
        toolbox_toggle_button = HoverToolButton("도구")
        toolbox_toggle_button.setFixedSize(70, 22)
        toolbox_toggle_button.setCheckable(True)
        toolbox_toggle_button.setChecked(True)
        toolbox_toggle_button.setFocusPolicy(Qt.StrongFocus)
        toolbox_toggle_button.setToolTip("왼쪽 도구상자 표시/숨기기")
        toolbox_toggle_button.toggled.connect(self.toolbox_toolbar.setVisible)
        self.toolbox_toggle_button = toolbox_toggle_button
        self.statusBar().addPermanentWidget(toolbox_toggle_button, 0)
        toolbar.addWidget(view_panel)
        board_panel = QWidget()
        board_panel.setObjectName("panel")
        board_panel.setFixedWidth(292)
        self._style(board_panel, panel_qss)
        board_layout = QGridLayout(board_panel)
        board_layout.setContentsMargins(8, 3, 8, 6)
        board_layout.setHorizontalSpacing(6)
        board_layout.setVerticalSpacing(2)
        board_title = QLabel("칠판 색상")
        board_title.setAlignment(Qt.AlignCenter)
        board_title.setFixedHeight(22)
        self._style(board_title, title_qss)
        board_layout.addWidget(board_title, 0, 0, 1, 2)
        self.board_group = QButtonGroup(self)
        self.board_group.setExclusive(True)
        self.board_radios = {}
        for index, (name, value) in enumerate(BOARD_COLORS):
            radio = QRadioButton(name)
            swatch = QPixmap(16, 16)
            if value == "transparent":
                swatch.fill(QColor("#ffffff"))
                painter = QPainter(swatch)
                painter.fillRect(0, 0, 8, 8, QColor("#d9e0e8"))
                painter.fillRect(8, 8, 8, 8, QColor("#d9e0e8"))
                painter.end()
            else:
                swatch.fill(QColor(value))
            radio.setIcon(QIcon(swatch))
            radio.setChecked(value == "#ffffff")
            radio.setFocusPolicy(Qt.StrongFocus)
            radio.setToolTip(f"칠판 바탕을 {name}으로 바꿉니다 (그린 그림은 유지됩니다)")
            radio.toggled.connect(lambda checked, v=value: checked and self._set_board(v))
            self.board_group.addButton(radio)
            self.board_radios[value] = radio
            board_layout.addWidget(radio, 1 + index // 2, index % 2)
        self.board_panel = board_panel
        toolbar.addWidget(board_panel)
        palette_widget = QWidget()
        palette_widget.setObjectName("panel")
        palette_widget.setFixedWidth(292)
        palette_widget.setFixedHeight(214)
        self.palette_widget = palette_widget
        self._style(palette_widget, panel_qss)
        palette_layout = QGridLayout(palette_widget)
        palette_layout.setContentsMargins(8, 3, 8, 3)
        palette_layout.setSpacing(4)
        palette_title = QLabel("색상")
        palette_title.setAlignment(Qt.AlignCenter)
        palette_title.setFixedHeight(22)
        self._style(palette_title, title_qss)
        palette_layout.addWidget(palette_title, 0, 0, 1, 2)
        color_chip_area = QWidget()
        color_chip_area.setFixedSize(76, 50)
        color_chip_layout = QGridLayout(color_chip_area)
        color_chip_layout.setContentsMargins(0, 0, 0, 0)
        foreground_button = QPushButton()
        foreground_button.setFixedSize(50, 34)
        foreground_button.setToolTip("전경색 선택: 클릭하면 색상 대화상자 열기")
        foreground_button.clicked.connect(self._choose_color)
        self.foreground_button = foreground_button
        background_button = QPushButton()
        background_button.setFixedSize(50, 34)
        background_button.setToolTip("배경색 선택: 클릭하면 색상 대화상자 열기")
        background_button.clicked.connect(self._choose_background_color)
        self.background_button = background_button
        color_chip_layout.addWidget(foreground_button, 0, 0, Qt.AlignLeft | Qt.AlignTop)
        color_chip_layout.addWidget(background_button, 0, 0, Qt.AlignRight | Qt.AlignBottom)
        palette_layout.addWidget(color_chip_area, 1, 0, Qt.AlignCenter)
        color_actions = QWidget()
        color_actions.setFixedSize(132, 22)
        color_actions_layout = QGridLayout(color_actions)
        color_actions_layout.setContentsMargins(0, 0, 0, 0)
        color_actions_layout.setSpacing(3)
        swap_button = QPushButton("⇄")
        swap_button.setFixedSize(42, 22)
        swap_button.setToolTip("전경색과 배경색 맞바꾸기")
        swap_button.clicked.connect(self._swap_colors)
        reset_colors_button = QPushButton("기본")
        reset_colors_button.setFixedSize(42, 22)
        reset_colors_button.setToolTip("전경색 검정, 배경색 흰색으로 초기화")
        reset_colors_button.clicked.connect(self._reset_colors)
        color_actions_layout.addWidget(swap_button, 0, 0)
        color_actions_layout.addWidget(reset_colors_button, 0, 1)
        custom_button = QPushButton("+")
        custom_button.setFixedSize(42, 22)
        custom_button.setStyleSheet("font-size: 16px;")
        custom_button.setToolTip("사용자 지정 색상")
        custom_button.clicked.connect(self._choose_color)
        color_actions_layout.addWidget(custom_button, 0, 2)
        palette_layout.addWidget(color_actions, 1, 1, Qt.AlignCenter)
        palette_separator = QFrame()
        palette_separator.setFrameShape(QFrame.HLine)
        palette_separator.setFrameShadow(QFrame.Sunken)
        self._style(palette_separator, lambda t: f"color: {t['sep']};")
        palette_layout.addWidget(palette_separator, 2, 0, 1, 2)
        color_grid = QWidget()
        color_grid_layout = QGridLayout(color_grid)
        color_grid_layout.setContentsMargins(0, 0, 0, 0)
        color_grid_layout.setSpacing(2)
        self.palette_buttons = []
        palette_colors = ("#000000", "#ffffff", "#ff0000", "#ff8800", "#ffff00", "#00aa00", "#00aaff", "#0000ff", "#aa00aa", "#808080")
        self.standard_palette_colors = set(palette_colors)
        for index, color in enumerate(palette_colors):
            button = PaletteButton(color, self._set_color, self._set_background_color)
            button.setFixedSize(135, 22)
            button.setProperty("paletteColor", color)
            qcolor = QColor(color)
            button.setToolTip(f"RGB({qcolor.red()}, {qcolor.green()}, {qcolor.blue()})  {color}")
            color_grid_layout.addWidget(button, index // 2, index % 2)
            self.palette_buttons.append(button)
        palette_layout.addWidget(color_grid, 3, 0, 1, 2, Qt.AlignCenter)
        recent_grid = QWidget()
        recent_layout = QGridLayout(recent_grid)
        recent_layout.setContentsMargins(0, 0, 0, 0)
        recent_layout.setSpacing(2)
        self.recent_buttons = []
        for index in range(4):
            recent_button = QPushButton()
            recent_button.setFixedSize(135, 18)
            recent_button.setVisible(False)
            recent_button.clicked.connect(
                lambda checked=False, button=recent_button: self._set_color(button.property("recentColor"))
            )
            recent_layout.addWidget(recent_button, index // 2, index % 2)
            self.recent_buttons.append(recent_button)
        palette_layout.addWidget(recent_grid, 4, 0, 1, 2, Qt.AlignCenter)
        recent_grid.setVisible(False)
        self.recent_grid = recent_grid
        self._update_color_indicators()
        toolbar.addWidget(palette_widget)
        text_panel = QWidget()
        text_panel.setObjectName("panel")
        text_panel.setFixedWidth(292)
        text_panel.setFixedHeight(88)
        self._style(text_panel, panel_qss)
        text_layout = QGridLayout(text_panel)
        text_layout.setContentsMargins(8, 3, 8, 3)
        text_layout.setHorizontalSpacing(6)
        text_layout.setVerticalSpacing(2)
        text_title = QLabel("텍스트")
        text_title.setAlignment(Qt.AlignCenter)
        text_title.setFixedHeight(22)
        self._style(text_title, title_qss)
        text_layout.addWidget(text_title, 0, 0, 1, 2)
        font_label = QLabel("글꼴")
        font_label.setFixedWidth(90)
        text_layout.addWidget(font_label, 1, 0)
        font_box = QFontComboBox()
        font_box.setFixedWidth(160)
        font_box.setCurrentFont(QFont(self.canvas.text_font_family))
        font_box.currentFontChanged.connect(lambda font: self._font_changed(font.family()))
        text_layout.addWidget(font_box, 1, 1)
        size_label = QLabel("크기")
        size_label.setFixedWidth(90)
        text_layout.addWidget(size_label, 2, 0)
        size_box = QSpinBox()
        size_box.setFixedWidth(160)
        size_box.setRange(8, 72)
        size_box.setValue(24)
        size_box.setSuffix(" pt")
        size_box.valueChanged.connect(self._size_changed)
        text_layout.addWidget(size_box, 2, 1)
        self.text_panel = text_panel
        self.canvas.text_aux_widget = text_panel
        text_panel.hide()
        self.text_action = toolbar.addWidget(text_panel)
        eraser_panel = QWidget()
        eraser_panel.setObjectName("panel")
        eraser_panel.setFixedWidth(292)
        eraser_panel.setFixedHeight(116)
        self._style(eraser_panel, panel_qss)
        eraser_layout = QGridLayout(eraser_panel)
        eraser_layout.setContentsMargins(8, 3, 8, 3)
        eraser_title = QLabel("도구 옵션")
        eraser_title.setAlignment(Qt.AlignCenter)
        eraser_title.setFixedHeight(22)
        self._style(eraser_title, title_qss)
        eraser_layout.addWidget(eraser_title, 0, 0, 1, 2)
        option_label = QLabel("굵기")
        option_label.setFixedWidth(90)
        eraser_layout.addWidget(option_label, 1, 0)
        option_size_box = QSpinBox()
        option_size_box.setFixedWidth(160)
        option_size_box.setRange(1, 100)
        option_size_box.setValue(self.canvas.stroke_widths["연필"])
        option_size_box.setSuffix(" px")
        option_size_box.setToolTip("현재 도구의 굵기")
        option_size_box.valueChanged.connect(self._option_size_changed)
        eraser_layout.addWidget(option_size_box, 1, 1)
        fill_checkbox = QCheckBox("도형 채우기")
        fill_checkbox.setChecked(False)
        fill_checkbox.setVisible(False)
        fill_checkbox.toggled.connect(self._fill_shapes_changed)
        eraser_layout.addWidget(fill_checkbox, 2, 0, 1, 2)
        self.option_panel = eraser_panel
        self.option_title = eraser_title
        self.option_label = option_label
        self.option_size_box = option_size_box
        self.fill_checkbox = fill_checkbox
        self.option_action = toolbar.addWidget(eraser_panel)
        self._select_tool("연필")


    def _select_tool(self, tool: str) -> None:
        self.canvas.commit_text()
        self.canvas.tool = tool
        for name, button in getattr(self, "tool_buttons", {}).items():
            button.setChecked(name == tool)
        if hasattr(self, "tool_title"):
            self.tool_title.setText(f"도구 · {tool}")
        if hasattr(self, "text_panel"):
            self.text_panel.setVisible(tool == "텍스트")
            self.text_action.setVisible(tool == "텍스트")
        if hasattr(self, "option_title"):
            is_eraser = tool == "지우개"
            shows_option = tool in {"연필", "브러시", "지우개", "직선", "사각형", "타원"}
            shows_fill = tool in {"사각형", "타원"}
            self.option_title.setText("지우개" if is_eraser else "도구 옵션")
            self.option_label.setText("지우개 크기" if is_eraser else "굵기")
            self.option_panel.setVisible(shows_option)
            self.option_action.setVisible(shows_option)
            self.fill_checkbox.setVisible(shows_fill)
            self.option_size_box.blockSignals(True)
            self.option_size_box.setValue(
                self.canvas.eraser_width if is_eraser else self.canvas.stroke_widths.get(tool, 2)
            )
            self.option_size_box.blockSignals(False)
        self.canvas.setCursor(
            Qt.CrossCursor if tool in {"선택", "영역 삭제", "색 채우기", "색 선택"} else Qt.ArrowCursor
        )
        self.statusBar().showMessage(f"현재 도구: {tool}")

    def _toggle_grid(self, visible: bool) -> None:
        self.canvas.set_grid_visible(visible)
        if hasattr(self, "grid_button") and self.grid_button.isChecked() != visible:
            self.grid_button.setChecked(visible)
        self.statusBar().showMessage("격자 표시" if visible else "격자 숨김")

    def _update_rulers(self) -> None:
        unit = self.unit_box.currentData() if hasattr(self, "unit_box") else "px"
        zoom = self.canvas.zoom
        self.horizontal_ruler.set_measurement(unit, zoom, self.canvas_area.horizontalScrollBar().value())
        self.vertical_ruler.set_measurement(unit, zoom, self.canvas_area.verticalScrollBar().value())

    def _unit_changed(self, unit: str) -> None:
        self._update_rulers()
        self.statusBar().showMessage(f"눈금 단위: {unit}")

    def _set_board(self, value: str) -> None:
        """칠판 색상 변경의 단일 진입점: 라디오 버튼, 메뉴, 상태바 선택이 모두 여기를 거친다."""
        if getattr(self, "_board_busy", False):  # 표시를 맞추느라 되돌아온 신호는 무시
            return
        self.canvas.commit_text()
        if value == "transparent":
            self.canvas.set_background_mode("transparent")
        else:
            color = QColor(value)
            self.canvas.set_background_mode("solid", color)
            self.canvas.background_color = QColor(color)  # 지우개가 칠판색으로 지우도록 배경색 스와치도 맞춘다
            if _contrast_ratio(self.canvas.color, color) < 3:  # 칠판에서 잘 안 보이는 펜 색은 대비되는 색으로
                self.canvas.color = QColor("#ffffff" if _luminance(color) < 0.18 else "#000000")
            self._update_color_indicators()
        self._sync_board_controls(value)
        name = next((n for n, v in BOARD_COLORS if v == value), value)
        self.statusBar().showMessage(f"칠판 색상: {name}")

    def _sync_board_controls(self, value: str) -> None:
        """라디오·메뉴·상태바 선택 표시를 현재 칠판 색상에 맞춘다.
        신호를 막으면 메뉴의 '하나만 선택' 동작도 같이 멈추므로, 대신 재진입 플래그로 되돌아오는 신호를 무시한다."""
        self._board_busy = True
        try:
            if value in getattr(self, "board_radios", {}):
                self.board_radios[value].setChecked(True)
            if value in getattr(self, "board_actions", {}):
                self.board_actions[value].setChecked(True)
            if hasattr(self, "background_box"):
                index = self.background_box.findData(value)
                if index >= 0 and self.background_box.currentIndex() != index:
                    self.background_box.setCurrentIndex(index)
        finally:
            self._board_busy = False

    def _toggle_rulers(self, visible: bool) -> None:
        self.horizontal_ruler.setVisible(visible)
        self.vertical_ruler.setVisible(visible)
        if hasattr(self, "ruler_button") and self.ruler_button.isChecked() != visible:
            self.ruler_button.setChecked(visible)
        self.statusBar().showMessage("눈금 표시" if visible else "눈금 숨김")

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(self.canvas.color, self, "색상 선택")
        if color.isValid():
            self.canvas.color = color
            self._record_recent_color(color.name())
            self._update_color_indicators()
            self.statusBar().showMessage(f"색상: {color.name()}")

    def _set_color(self, color: str) -> None:
        self.canvas.color = QColor(color)
        if color not in getattr(self, "standard_palette_colors", set()):
            self._record_recent_color(color)
        self._update_color_indicators()
        self.statusBar().showMessage(f"색상: {color}")

    def _record_recent_color(self, color: str) -> None:
        if not color:
            return
        recent = getattr(self, "recent_colors", [])
        normalized = QColor(color).name()
        recent = [value for value in recent if value != normalized]
        self.recent_colors = [normalized, *recent][:4]
        if hasattr(self, "recent_grid"):
            self.recent_grid.setVisible(True)
        if hasattr(self, "palette_widget"):
            self.palette_widget.setFixedHeight(256)
        for index, button in enumerate(getattr(self, "recent_buttons", [])):
            if index < len(self.recent_colors):
                value = self.recent_colors[index]
                button.setProperty("recentColor", value)
                button.setStyleSheet(f"background-color: {value}; border: 1px solid #64748b; border-radius: 3px;")
                button.setToolTip(f"최근 색상 {value}")
                button.setVisible(True)
            else:
                button.setVisible(False)

    def _choose_background_color(self) -> None:
        color = QColorDialog.getColor(self.canvas.background_color, self, "배경색 선택")
        if color.isValid():
            self._set_background_color(color.name())

    def _set_background_color(self, color: str) -> None:
        self.canvas.background_color = QColor(color)
        self._update_color_indicators()
        self.statusBar().showMessage(f"배경색: {color}")

    def _swap_colors(self) -> None:
        self.canvas.color, self.canvas.background_color = (
            self.canvas.background_color,
            self.canvas.color,
        )
        self._update_color_indicators()
        self.statusBar().showMessage("전경색과 배경색을 맞바꿈")

    def _reset_colors(self) -> None:
        self.canvas.color = QColor("#000000")
        self.canvas.background_color = QColor("#ffffff")
        self._update_color_indicators()
        self.statusBar().showMessage("색상을 기본값으로 초기화")

    def _update_color_indicators(self) -> None:
        if hasattr(self, "foreground_button"):
            self.foreground_button.setStyleSheet(
                f"background-color: {self.canvas.color.name()}; border: 2px solid #3b82b6; border-radius: 4px;"
            )
        if hasattr(self, "background_button"):
            self.background_button.setStyleSheet(
                f"background-color: {self.canvas.background_color.name()}; border: 1px solid #64748b; border-radius: 4px;"
            )
        for button in getattr(self, "palette_buttons", []):
            color = button.property("paletteColor")
            selected = color in {self.canvas.color.name(), self.canvas.background_color.name()}
            border = "2px solid #3b82b6" if selected else "1px solid #64748b"
            button.setStyleSheet(
                f"background-color: {color}; border: {border}; border-radius: 3px;"
            )

    def _font_changed(self, family: str) -> None:
        self.canvas.set_text_font(family, self.canvas.text_font_size)

    def _size_changed(self, size: int) -> None:
        self.canvas.set_text_font(self.canvas.text_font_family, size)

    def _option_size_changed(self, size: int) -> None:
        if self.canvas.tool == "지우개":
            self.canvas.eraser_width = size
        elif self.canvas.tool in self.canvas.stroke_widths:
            self.canvas.stroke_widths[self.canvas.tool] = size
        self.statusBar().showMessage(f"크기: {size}px")

    def _fill_shapes_changed(self, filled: bool) -> None:
        self.canvas.fill_shapes = filled
        self.statusBar().showMessage("도형 채우기" if filled else "도형 외곽선만")

    def _eraser_size_changed(self, size: int) -> None:
        self.canvas.eraser_width = size
        self.statusBar().showMessage(f"지우개 크기: {size}px")

    def _on_canvas_changed(self) -> None:
        self._update_canvas_info()
        self._update_color_indicators()

    def _update_canvas_info(self) -> None:
        self.canvas_size_label.setText(
            f"캔버스 {self.canvas.image.width()} × {self.canvas.image.height()} px"
        )

    def _zoom_changed(self, value: int) -> None:
        self.canvas.set_zoom(value)
        self.zoom_label.setText(f"{value}%")
        self._update_rulers()

    def _resize_canvas(self) -> None:
        current_width = self.canvas.image.width()
        current_height = self.canvas.image.height()
        dialog = QDialog(self)
        dialog.setWindowTitle("캔버스 크기")
        form, width_box, height_box = self._size_preset_form(dialog, current_width, current_height)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        width = width_box.value()
        height = height_box.value()

        new_image = QImage(width, height, QImage.Format_ARGB32)
        new_image.fill(self.canvas._clear_color())
        painter = QPainter(new_image)
        painter.drawImage(0, 0, self.canvas.image)
        painter.end()
        self.canvas._push_undo()
        self.canvas.image = new_image
        self.canvas.modified = True
        self.canvas.set_zoom(self.zoom_slider.value())
        self.canvas.update()
        self._update_canvas_info()
        self.statusBar().showMessage(f"캔버스 크기: {width} × {height}px")

    def _update_title(self) -> None:
        name = self.current_file.name if self.current_file else "Untitled"
        self.setWindowTitle(f"{name} - Paint")

    def _confirm_discard(self) -> bool:
        """저장되지 않은 변경 내용이 있으면 저장 여부를 묻는다. 계속 진행 가능하면 True."""
        self.canvas.commit_text()
        if not self.canvas.modified:
            return True
        choice = QMessageBox.warning(
            self,
            "저장되지 않은 변경 내용",
            "변경 내용을 저장하시겠습니까?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if choice == QMessageBox.Cancel:
            return False
        if choice == QMessageBox.Save:
            return self._save_image()
        return True

    def _size_preset_form(self, dialog: QDialog, width: int, height: int):
        form = QFormLayout(dialog)
        preset_box = QComboBox()
        preset_box.addItems([
            "사용자 지정",
            "PowerPoint 16:9 (1280 × 720)",
            "PowerPoint 16:9 (1920 × 1080)",
            "PowerPoint 16:9 (1600 × 900)",
        ])
        width_box = QSpinBox()
        width_box.setRange(1, 10000)
        width_box.setValue(width)
        width_box.setSuffix(" px")
        height_box = QSpinBox()
        height_box.setRange(1, 10000)
        height_box.setValue(height)
        height_box.setSuffix(" px")
        def apply_preset(index: int) -> None:
            presets = {1: (1280, 720), 2: (1920, 1080), 3: (1600, 900)}
            if index in presets:
                w, h = presets[index]
                width_box.setValue(w)
                height_box.setValue(h)

        preset_box.currentIndexChanged.connect(apply_preset)
        form.addRow("프리셋:", preset_box)
        form.addRow("가로:", width_box)
        form.addRow("세로:", height_box)
        return form, width_box, height_box

    def _new_image(self) -> None:
        if not self._confirm_discard():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("새 이미지")
        form, width_box, height_box = self._size_preset_form(
            dialog, self.canvas.image.width(), self.canvas.image.height()
        )
        background_box = QComboBox()
        for name, value in BOARD_COLORS:
            background_box.addItem(name, value)
        form.addRow("칠판 색상:", background_box)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        width, height = width_box.value(), height_box.value()
        background = background_box.currentData()
        new_image = QImage(width, height, QImage.Format_ARGB32)
        new_image.fill(Qt.transparent if background == "transparent" else QColor(background))
        self.canvas.image = new_image
        self.canvas.background_mode = "transparent" if background == "transparent" else "solid"
        if background != "transparent":
            self.canvas.board_color = QColor(background)
            self.canvas.background_color = QColor(background)
        self.canvas.selection_rect = None
        self.canvas.modified = False
        self.canvas.undo_stack.clear()
        self.canvas.redo_stack.clear()
        self.current_file = None
        self.canvas.set_zoom(self.zoom_slider.value())
        self._sync_board_controls(background)
        self._update_title()
        self._update_canvas_info()
        self.statusBar().showMessage(f"새 이미지: {width} × {height}px")

    def _open_image(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "이미지 열기",
            "",
            "이미지 파일 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;모든 파일 (*)",
        )
        if path:
            self._load_image_file(path)

    def _load_image_file(self, path: str) -> None:
        try:
            pil_image = Image.open(path)
            pil_image.load()
        except OSError:
            QMessageBox.critical(self, "열기 실패", f"이미지를 열 수 없습니다:\n{path}")
            return
        rgba = pil_image.convert("RGBA")
        qimage = QImage(rgba.tobytes(), rgba.width, rgba.height, QImage.Format_RGBA8888)
        self.canvas.image = qimage.copy().convertToFormat(QImage.Format_ARGB32)
        self.canvas.selection_rect = None
        self.canvas.modified = False
        self.canvas.undo_stack.clear()
        self.canvas.redo_stack.clear()
        self.current_file = Path(path)
        self.canvas.set_zoom(self.zoom_slider.value())
        self._update_title()
        self._update_canvas_info()
        self.statusBar().showMessage(f"열기: {Path(path).name}")

    def _save_image(self) -> bool:
        self.canvas.commit_text()
        if self.current_file is None:
            return self._save_image_as()
        return self._write_image(self.current_file)

    def _save_image_as(self) -> bool:
        self.canvas.commit_text()
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "다른 이름으로 저장",
            str(self.current_file) if self.current_file else "",
            "PNG 이미지 (*.png);;JPEG 이미지 (*.jpg *.jpeg);;BMP 이미지 (*.bmp);;모든 파일 (*)",
        )
        if not path:
            return False
        target = Path(path)
        if not target.suffix:
            extension = ".jpg" if "JPEG" in selected_filter else ".bmp" if "BMP" in selected_filter else ".png"
            target = target.with_suffix(extension)
        return self._write_image(target)

    def _write_image(self, path: Path) -> bool:
        rgba = self.canvas.image.convertToFormat(QImage.Format_RGBA8888)
        pil_image = Image.frombytes("RGBA", (rgba.width(), rgba.height()), rgba.constBits().tobytes())
        if path.suffix.lower() in {".jpg", ".jpeg", ".bmp"}:
            background = Image.new("RGBA", pil_image.size, (255, 255, 255, 255))
            pil_image = Image.alpha_composite(background, pil_image).convert("RGB")
        try:
            pil_image.save(path)
        except OSError as error:
            QMessageBox.critical(self, "저장 실패", f"저장할 수 없습니다:\n{error}")
            return False
        self.current_file = path
        self.canvas.modified = False
        self._update_title()
        self.statusBar().showMessage(f"저장: {path.name}")
        return True

    def closeEvent(self, event) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()


def run() -> None:
    app = QApplication.instance() or QApplication([])
    icon_path = Path(__file__).resolve().parent.parent / "assets" / "paint_icon.svg"
    app.setWindowIcon(QIcon(str(icon_path)))
    window = QtPaintApplication()
    window.show()
    window.raise_()
    window.activateWindow()
    app.exec()
