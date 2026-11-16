"""PySide6 그림판: 글씨 입력(키보드)과 칠판 색상 동작 검증. 화면 없이(offscreen) 실행된다.

실행: python -m unittest tests.test_paint_qt -v
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QInputMethodEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.qt_application import BOARD_COLORS, QtPaintApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def has_ink(image, rect: QRect, background: QColor) -> bool:
    """rect 안에 바탕색이 아닌 픽셀이 하나라도 있는가."""
    for y in range(rect.top(), rect.bottom()):
        for x in range(rect.left(), rect.right()):
            if image.pixelColor(x, y) != background:
                return True
    return False


class TextTypingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.win = QtPaintApplication()
        self.win.show()
        self.canvas = self.win.canvas
        self.win._select_tool("텍스트")
        self.white = QColor("white")
        self.region = QRect(100, 100, 220, 60)  # 클릭 지점에서 열리는 기본 입력 상자 영역

    def tearDown(self) -> None:
        # 닫을 때 "저장하시겠습니까?" 대화상자가 떠서 테스트가 멈추지 않도록 입력 중인 글씨를 취소하고 변경 표시를 끈다
        if self.canvas.text_editor is not None:
            self.canvas._cancel_text()
        self.canvas.modified = False
        self.win.close()

    def click(self, x: int, y: int) -> None:
        QTest.mouseClick(self.canvas, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))

    def type_text(self, text: str) -> None:
        """영문은 키 입력으로, 한글은 입력기(IME)가 글자를 확정해 보내는 방식으로 흉내 낸다.
        (QTest.keyClicks는 비ASCII 글자를 지원하지 않는다)"""
        editor = self.canvas.text_editor
        for ch in text:
            if ch.isascii():
                QTest.keyClicks(editor, ch)
            else:
                event = QInputMethodEvent()
                event.setCommitString(ch)
                QApplication.sendEvent(editor, event)

    def test_click_opens_box_and_typing_works(self) -> None:
        self.click(100, 100)
        self.assertIsNotNone(self.canvas.text_editor)
        self.type_text("Hello 가나다")
        self.assertEqual(self.canvas.text_editor.toPlainText(), "Hello 가나다")

    def test_ctrl_enter_commits_text_to_canvas(self) -> None:
        self.click(100, 100)
        self.type_text("Hello 가나다")
        QTest.keyClick(self.canvas.text_editor, Qt.Key_Return, Qt.ControlModifier)
        self.assertIsNone(self.canvas.text_editor)
        self.assertTrue(has_ink(self.canvas.image, self.region, self.white), "글씨가 캔버스에 그려져야 한다")

    def test_clicking_elsewhere_commits_text(self) -> None:
        """예전에는 Ctrl+Enter 말고는 확정되지 않아 글씨가 사라졌다."""
        self.click(100, 100)
        self.type_text("확정 테스트")
        self.click(500, 400)  # 다른 곳 클릭
        self.assertTrue(has_ink(self.canvas.image, self.region, self.white), "다른 곳을 눌러도 글씨가 남아야 한다")
        self.assertIsNotNone(self.canvas.text_editor, "새 위치에 새 입력 상자가 열린다")
        self.assertEqual(self.canvas.text_editor.toPlainText(), "")

    def test_switching_tool_commits_text(self) -> None:
        self.click(100, 100)
        self.type_text("도구 전환")
        self.win._select_tool("연필")
        self.assertIsNone(self.canvas.text_editor)
        self.assertTrue(has_ink(self.canvas.image, self.region, self.white))

    def test_escape_cancels_and_undo_restores(self) -> None:
        self.click(100, 100)
        self.type_text("취소할 글씨")
        QTest.keyClick(self.canvas.text_editor, Qt.Key_Escape)
        self.assertIsNone(self.canvas.text_editor)
        self.assertFalse(has_ink(self.canvas.image, self.region, self.white))
        # 확정한 글씨는 실행 취소로 되돌릴 수 있다
        self.click(100, 100)
        self.type_text("되돌리기")
        self.win._select_tool("연필")
        self.assertTrue(has_ink(self.canvas.image, self.region, self.white))
        self.canvas.undo()
        self.assertFalse(has_ink(self.canvas.image, self.region, self.white))

    def test_text_uses_foreground_color(self) -> None:
        self.win._set_color("#ff0000")
        self.click(100, 100)
        self.assertIn("#ff0000", self.canvas.text_editor.styleSheet(), "입력 중 글자색이 선택한 색이어야 한다")
        self.type_text("빨강")
        self.win._select_tool("연필")
        reds = sum(
            1
            for y in range(100, 160)
            for x in range(100, 320)
            if (c := self.canvas.image.pixelColor(x, y)).red() > 200 and c.green() < 80 and c.blue() < 80
        )
        self.assertGreater(reds, 20)

    def test_font_panel_does_not_end_editing(self) -> None:
        self.click(100, 100)
        self.type_text("글꼴 바꾸는 중")
        with mock.patch.object(QApplication, "focusWidget", return_value=self.win.text_panel):
            self.canvas._text_focus_lost()
        self.assertIsNotNone(self.canvas.text_editor, "글꼴 패널을 눌러도 입력이 끝나면 안 된다")
        with mock.patch.object(QApplication, "focusWidget", return_value=self.win.tool_buttons["연필"]):
            self.canvas._text_focus_lost()
        self.assertIsNone(self.canvas.text_editor, "다른 곳으로 포커스가 가면 확정된다")

    def test_editor_matches_board_and_final_size(self) -> None:
        """입력 상자는 칠판색 배경에 글자색이 대비되어야 하고, 글자 크기는 확정 후와 같아야 한다."""
        self.win.board_radios["#2d4a3e"].click()
        self.click(100, 100)
        css = self.canvas.text_editor.styleSheet()
        self.assertIn("rgba(45,74,62", css)  # 칠판색 배경
        self.assertIn("color: #ffffff", css)  # 어두운 칠판이라 흰 글자
        self.assertIn("font-size: 32.0px", css)  # 24pt = 96dpi 기준 32px (확정 후와 같은 크기)
        self.win._size_changed(40)
        self.assertIn("font-size: 53.3px", self.canvas.text_editor.styleSheet())
        self.assertIsNotNone(self.canvas.text_editor, "크기를 바꿔도 입력은 계속된다")

    def test_window_switch_keeps_editing(self) -> None:
        self.click(100, 100)
        self.type_text("창 전환")
        with mock.patch.object(QApplication, "focusWidget", return_value=None):  # 다른 앱으로 이동
            self.canvas._text_focus_lost()
        self.assertIsNotNone(self.canvas.text_editor)


class BoardColorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.win = QtPaintApplication()
        self.win.show()
        self.canvas = self.win.canvas

    def tearDown(self) -> None:
        # 닫을 때 "저장하시겠습니까?" 대화상자가 떠서 테스트가 멈추지 않도록 입력 중인 글씨를 취소하고 변경 표시를 끈다
        if self.canvas.text_editor is not None:
            self.canvas._cancel_text()
        self.canvas.modified = False
        self.win.close()

    def px(self, x: int = 5, y: int = 5) -> QColor:
        return self.canvas.image.pixelColor(x, y)

    def draw_line(self) -> None:
        self.win._select_tool("연필")
        QTest.mousePress(self.canvas, Qt.LeftButton, Qt.NoModifier, QPoint(50, 300))
        for x in range(50, 250, 10):
            QTest.mouseMove(self.canvas, QPoint(x, 300))
        QTest.mouseRelease(self.canvas, Qt.LeftButton, Qt.NoModifier, QPoint(250, 300))

    def test_radio_buttons_exist_for_every_color(self) -> None:
        self.assertEqual(set(self.win.board_radios), {value for _, value in BOARD_COLORS})
        self.assertTrue(self.win.board_radios["#ffffff"].isChecked())

    def test_clicking_radio_changes_board_color(self) -> None:
        self.win.board_radios["#2d4a3e"].click()
        self.assertEqual(self.px().name(), "#2d4a3e")
        self.assertEqual(self.px(799, 599).name(), "#2d4a3e")
        # 라디오는 하나만 선택된다
        self.assertEqual([v for v, r in self.win.board_radios.items() if r.isChecked()], ["#2d4a3e"])

    def test_existing_drawing_is_kept_when_color_changes(self) -> None:
        self.draw_line()
        self.assertEqual(self.px(150, 300).name(), "#000000")
        self.win.board_radios["#1f2a44"].click()
        self.assertEqual(self.px().name(), "#1f2a44")
        self.assertNotEqual(self.px(150, 300).name(), "#1f2a44", "그린 선은 남아 있어야 한다")

    def test_dark_board_makes_pen_visible_and_eraser_matches(self) -> None:
        self.win.board_radios["#111111"].click()
        self.assertEqual(self.canvas.color.name(), "#ffffff", "검은 칠판에서 검은 펜은 안 보이므로 흰색으로 바뀐다")
        self.assertEqual(self.canvas.background_color.name(), "#111111", "지우개가 칠판색으로 지운다")
        self.win.board_radios["#ffffff"].click()
        self.assertEqual(self.canvas.color.name(), "#000000", "다시 밝은 칠판이면 검은 펜으로")

    def test_pen_color_kept_when_already_visible(self) -> None:
        self.win._set_color("#ff0000")
        self.win.board_radios["#111111"].click()
        self.assertEqual(self.canvas.color.name(), "#ff0000")

    def test_transparent_and_back(self) -> None:
        self.draw_line()
        self.win.board_radios["transparent"].click()
        self.assertEqual(self.px().alpha(), 0)
        self.assertGreater(self.px(150, 300).alpha(), 0, "선은 남는다")
        self.win.board_radios["#2d4a3e"].click()
        self.assertEqual(self.px().name(), "#2d4a3e")
        self.assertEqual(self.px().alpha(), 255)

    def test_undo_restores_previous_board(self) -> None:
        self.win.board_radios["#111111"].click()
        self.canvas.undo()
        self.assertEqual(self.px().name(), "#ffffff")

    def test_menu_and_statusbar_stay_in_sync(self) -> None:
        self.win.board_radios["#808080"].click()
        self.assertTrue(self.win.board_actions["#808080"].isChecked())
        self.assertEqual(self.win.background_box.currentData(), "#808080")
        self.win.background_box.setCurrentIndex(self.win.background_box.findData("#111111"))
        self.assertTrue(self.win.board_radios["#111111"].isChecked())
        self.assertEqual(self.px().name(), "#111111")
        self.win.board_actions["#ffffff"].setChecked(True)
        self.assertTrue(self.win.board_radios["#ffffff"].isChecked())
        self.assertEqual(self.px().name(), "#ffffff")

    def test_same_color_does_not_add_undo_step(self) -> None:
        before = len(self.canvas.undo_stack)
        self.win.board_radios["#ffffff"].click()
        self.assertEqual(len(self.canvas.undo_stack), before)


class ThemeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.win = QtPaintApplication()
        self.win.show()

    def tearDown(self) -> None:
        self.win.canvas.modified = False
        self.win.close()

    def test_dark_theme_changes_window_and_panels(self) -> None:
        self.win._set_theme("dark", save=False)
        self.assertEqual(self.win.theme_name, "dark")
        self.assertIn("#0f1624", self.win.styleSheet())
        self.assertIn("#1b2638", self.win.tool_buttons["연필"].parent().styleSheet() + self.win.text_panel.styleSheet())
        self.assertTrue(self.win.theme_actions["dark"].isChecked())
        self.win._set_theme("light", save=False)
        self.assertIn("#c6d1e2", self.win.styleSheet())
        self.assertIn("#dceaf5", self.win.text_panel.styleSheet())

    def test_theme_does_not_touch_board_or_drawing(self) -> None:
        self.win._set_theme("dark", save=False)
        self.assertEqual(self.win.canvas.image.pixelColor(5, 5).name(), "#ffffff")
        self.assertTrue(self.win.board_radios["#ffffff"].isChecked())


if __name__ == "__main__":
    unittest.main()
