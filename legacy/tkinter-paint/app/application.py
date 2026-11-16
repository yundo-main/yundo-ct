"""그림판의 기본 창과 UI를 구성한다."""

import tkinter as tk
from tkinter import messagebox


class PaintApplication:
    """클래식 그림판의 기본 애플리케이션 창."""

    CANVAS_WIDTH = 800
    CANVAS_HEIGHT = 600

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("제목 없음 - 그림판")
        self.root.geometry("1000x760")
        self.root.minsize(700, 500)
        # macOS에서 터미널 뒤에 창이 생성되는 경우를 방지한다.
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(500, lambda: self.root.attributes("-topmost", False))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.status_text = tk.StringVar(value="준비")
        self.selected_tool = tk.StringVar(value="연필")
        self.active_color = "black"
        self.start_point: tuple[int, int] | None = None
        self.preview_item: int | None = None
        self._build_menu()
        self._build_layout()

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self.root)

        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="새로 만들기", accelerator="Ctrl+N")
        file_menu.add_command(label="열기...", accelerator="Ctrl+O")
        file_menu.add_command(label="저장", accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="종료", command=self._on_close)
        menu_bar.add_cascade(label="파일", menu=file_menu)

        edit_menu = tk.Menu(menu_bar, tearoff=False)
        edit_menu.add_command(label="실행 취소", accelerator="Ctrl+Z")
        edit_menu.add_command(label="다시 실행", accelerator="Ctrl+Y")
        menu_bar.add_cascade(label="편집", menu=edit_menu)

        view_menu = tk.Menu(menu_bar, tearoff=False)
        view_menu.add_command(label="확대")
        view_menu.add_command(label="축소")
        menu_bar.add_cascade(label="보기", menu=view_menu)

        image_menu = tk.Menu(menu_bar, tearoff=False)
        image_menu.add_command(label="캔버스 크기")
        image_menu.add_command(label="이미지 속성")
        menu_bar.add_cascade(label="이미지", menu=image_menu)

        help_menu = tk.Menu(menu_bar, tearoff=False)
        help_menu.add_command(label="그림판 정보", command=self._show_about)
        menu_bar.add_cascade(label="도움말", menu=help_menu)

        self.root.config(menu=menu_bar)

    def _build_layout(self) -> None:
        toolbar = tk.Frame(self.root, bd=1, relief=tk.RAISED, padx=4, pady=4)
        toolbar.pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(toolbar, text="도구", font=("TkDefaultFont", 10, "bold")).pack(
            pady=(0, 6)
        )
        for tool_name in ("연필", "브러시", "지우개", "직선", "사각형", "타원"):
            tk.Radiobutton(
                toolbar,
                text=tool_name,
                variable=self.selected_tool,
                value=tool_name,
                indicatoron=False,
                width=9,
                command=self._update_status,
            ).pack(pady=2)

        content = tk.Frame(self.root, bg="#d0d0d0")
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        canvas_frame = tk.Frame(content, bg="#808080", padx=8, pady=8)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(
            canvas_frame,
            width=self.CANVAS_WIDTH,
            height=self.CANVAS_HEIGHT,
            bg="white",
            highlightthickness=1,
            highlightbackground="#555555",
            takefocus=True,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        palette = tk.Frame(content, bd=1, relief=tk.SUNKEN, padx=6, pady=4)
        palette.pack(fill=tk.X)
        tk.Label(palette, text="색상:").pack(side=tk.LEFT, padx=(0, 6))
        for color in ("black", "white", "red", "orange", "yellow", "green", "cyan", "blue", "purple"):
            tk.Button(
                palette,
                bg=color,
                activebackground=color,
                width=2,
                height=1,
                relief=tk.RAISED,
                command=lambda selected=color: self._select_color(selected),
            ).pack(side=tk.LEFT, padx=1)

        status = tk.Label(
            self.root,
            textvariable=self.status_text,
            anchor=tk.W,
            bd=1,
            relief=tk.SUNKEN,
            padx=6,
        )
        status.pack(side=tk.BOTTOM, fill=tk.X)

        # Canvas 자체에 직접 연결하면 도구 버튼과 캔버스 입력이 서로 간섭하지 않는다.
        self.canvas.bind("<Motion>", self._show_coordinates)
        self.canvas.bind("<ButtonPress-1>", self._start_drawing)
        self.canvas.bind("<B1-Motion>", self._draw_preview)
        self.canvas.bind("<ButtonRelease-1>", self._finish_drawing)

    def _select_color(self, color: str) -> None:
        self.active_color = color
        self.status_text.set(f"선택한 색상: {color}")

    def _update_status(self) -> None:
        self.status_text.set(f"현재 도구: {self.selected_tool.get()}")

    def _show_coordinates(self, event: tk.Event) -> None:
        self.status_text.set(
            f"도구: {self.selected_tool.get()}   위치: ({event.x}, {event.y})"
        )

    def _start_drawing(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        self.start_point = (event.x, event.y)
        self.preview_item = None
        if self.selected_tool.get() in {"연필", "브러시", "지우개"}:
            self._draw_freehand(event)

    def _draw_freehand(self, event: tk.Event) -> None:
        if self.start_point is None:
            self.start_point = (event.x, event.y)
        color = "white" if self.selected_tool.get() == "지우개" else self.active_color
        width = 12 if self.selected_tool.get() == "브러시" else 2
        if self.selected_tool.get() == "지우개":
            width = 20
        x, y = self.start_point
        self.canvas.create_line(
            x,
            y,
            event.x,
            event.y,
            fill=color,
            width=width,
            capstyle=tk.ROUND,
            smooth=True,
        )
        self.start_point = (event.x, event.y)

    def _draw_preview(self, event: tk.Event) -> None:
        tool = self.selected_tool.get()
        if tool in {"연필", "브러시", "지우개"}:
            self._draw_freehand(event)
            return
        if self.start_point is None:
            return
        if self.preview_item is not None:
            self.canvas.delete(self.preview_item)
        x, y = self.start_point
        outline = self.active_color
        if tool == "직선":
            self.preview_item = self.canvas.create_line(x, y, event.x, event.y, fill=outline, width=2)
        elif tool == "사각형":
            self.preview_item = self.canvas.create_rectangle(x, y, event.x, event.y, outline=outline, width=2)
        elif tool == "타원":
            self.preview_item = self.canvas.create_oval(x, y, event.x, event.y, outline=outline, width=2)

    def _finish_drawing(self, event: tk.Event) -> None:
        if self.start_point is None:
            return
        tool = self.selected_tool.get()
        if tool in {"연필", "브러시", "지우개"}:
            # 클릭만 한 경우에도 점 하나가 찍히도록 처리한다.
            color = "white" if tool == "지우개" else self.active_color
            width = 20 if tool == "지우개" else (12 if tool == "브러시" else 2)
            self.canvas.create_oval(
                event.x - width / 2,
                event.y - width / 2,
                event.x + width / 2,
                event.y + width / 2,
                fill=color,
                outline=color,
            )
            self.start_point = None
            return
        if tool in {"직선", "사각형", "타원"}:
            self._draw_preview(event)
            self.preview_item = None
        self.start_point = None

    def _show_about(self) -> None:
        messagebox.showinfo("그림판 정보", "Python 클래식 그림판\n1단계 기본 UI")

    def _on_close(self) -> None:
        if messagebox.askyesno("종료", "그림판을 종료하시겠습니까?"):
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
