"""그리기 엔진의 최소 동작 검증."""

import unittest
from types import SimpleNamespace

from app.application import PaintApplication


class DrawingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = PaintApplication()
        self.app.root.update_idletasks()

    def tearDown(self) -> None:
        self.app.root.destroy()

    def test_pencil_creates_canvas_items(self) -> None:
        self.app._start_drawing(SimpleNamespace(x=20, y=20))
        self.app._draw_preview(SimpleNamespace(x=80, y=80))
        self.app._finish_drawing(SimpleNamespace(x=80, y=80))

        self.assertGreater(
            len(self.app.canvas.find_all()),
            0,
            "연필 입력 후 Canvas 객체가 생성되어야 합니다.",
        )

    def test_shape_preview_creates_rectangle(self) -> None:
        self.app.selected_tool.set("사각형")
        self.app._start_drawing(SimpleNamespace(x=20, y=20))
        self.app._draw_preview(SimpleNamespace(x=120, y=80))

        self.assertEqual(len(self.app.canvas.find_all()), 1)
        self.assertEqual(self.app.canvas.type(self.app.canvas.find_all()[0]), "rectangle")

if __name__ == "__main__":
    unittest.main()
