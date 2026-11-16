"""도움말 대화상자. 내용은 데이터로 분리해 UI 코드와 독립적으로 수정할 수 있다."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QHeaderView,
)

APP_NAME = "Python 그림판"
APP_VERSION = "0.1.0"

USAGE_HTML = """
<h3>기본 사용법</h3>
<ol>
  <li>왼쪽 <b>도구</b> 패널에서 연필·브러시·도형 등 도구를 고릅니다.</li>
  <li><b>색상</b> 패널의 팔레트에서 전경색을, 배경색 칸에서 배경색을 정합니다.
      <b>+</b> 버튼으로 원하는 색을 직접 고를 수 있습니다.</li>
  <li>캔버스에서 마우스를 누른 채 움직여 그립니다.</li>
  <li><b>도구 옵션</b>에서 굵기를, 텍스트 도구에서는 글꼴과 크기를 바꿉니다.</li>
  <li>하단의 슬라이더로 확대/축소(25%~400%)합니다.</li>
</ol>
<h3>글씨 쓰기 (텍스트 도구)</h3>
<ol>
  <li><b>텍스트</b> 도구(T)를 고르고 캔버스에서 글씨를 넣을 곳을 <b>클릭</b>합니다. 드래그하면 상자 크기를 정할 수 있습니다.</li>
  <li><b>키보드로 타이핑</b>합니다. 한글도 입력할 수 있고, Enter는 줄바꿈입니다.</li>
  <li><b>Ctrl+Enter</b> 또는 <b>상자 밖을 클릭</b>하거나 다른 도구를 고르면 글씨가 확정됩니다. <b>Esc</b>는 취소입니다.</li>
  <li>글꼴과 크기는 왼쪽 <b>텍스트</b> 패널에서 바꿉니다. 글자색은 현재 전경색입니다. 확정한 글씨는 Ctrl+Z로 되돌릴 수 있습니다.</li>
</ol>
<h3>칠판 색상</h3>
<p>왼쪽 <b>칠판 색상</b>의 라디오 버튼으로 캔버스 바탕을 <b>흰색·검정·칠판 초록·남색·회색·투명</b> 중에서 고릅니다.
이미 그린 그림은 그대로 두고 바탕만 바뀌며, 보기 메뉴와 하단 상태 표시줄에서도 같은 선택을 할 수 있습니다.
어두운 칠판에서 안 보이는 펜 색(예: 검정)은 자동으로 흰색으로 바뀌고, 지우개 색도 칠판색에 맞춰집니다.</p>
<h3>화면 테마</h3>
<p>보기 ▸ <b>화면 테마</b>에서 시스템 설정에 맞춤 / 밝게 / 어둡게를 고릅니다. 선택은 저장되며, 캔버스(칠판) 색에는 영향이 없습니다.</p>
<h3>선택과 삭제</h3>
<p><b>선택</b> 도구로 영역을 지정한 뒤 <b>Delete</b> 또는 <b>Backspace</b>를 누르면
선택 영역(또는 텍스트 상자)이 삭제됩니다.</p>
<h3>보기</h3>
<p>보기 메뉴에서 격자, 눈금, 배경(흰색/투명)을 바꿀 수 있고, 이미지 메뉴에서
캔버스 크기를 변경할 수 있습니다.</p>
"""

# (기능, 단축키)
SHORTCUTS = [
    ("연필", "P"),
    ("브러시", "B"),
    ("지우개", "E"),
    ("직선", "L"),
    ("사각형", "R"),
    ("타원", "O"),
    ("선택", "S"),
    ("영역 삭제", "D"),
    ("색 채우기", "F"),
    ("색 선택", "I"),
    ("텍스트", "T"),
    ("실행 취소", "Ctrl+Z"),
    ("다시 실행", "Ctrl+Y"),
    ("선택 영역/텍스트 상자 삭제", "Delete / Backspace"),
    ("새로 만들기", "Ctrl+N"),
    ("열기", "Ctrl+O"),
    ("저장", "Ctrl+S"),
    ("다른 이름으로 저장", "Ctrl+Shift+S"),
    ("격자 표시", "Ctrl+G"),
    ("파일 브라우저", "Ctrl+B"),
    ("도구상자 표시/숨김", "Ctrl+Shift+T"),
    ("도움말", "F1"),
]

ABOUT_HTML = f"""
<h3>{APP_NAME}</h3>
<p>버전 {APP_VERSION}</p>
<p>클래식 Windows 그림판의 사용성을 참고한 PySide6 기반 그림판입니다.</p>
<p>Produced by yundo</p>
<p>개발 문서는 프로젝트의 <code>docs/</code> 폴더에 있습니다.</p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("도움말")
        self.resize(480, 420)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        usage = QTextBrowser()
        usage.setHtml(USAGE_HTML)
        tabs.addTab(usage, "사용법")

        table = QTableWidget(len(SHORTCUTS), 2)
        table.setHorizontalHeaderLabels(["기능", "단축키"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for row, (name, keys) in enumerate(SHORTCUTS):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(keys))
        tabs.addTab(table, "단축키")

        about = QTextBrowser()
        about.setHtml(ABOUT_HTML)
        tabs.addTab(about, "정보")

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def show_help(parent=None, tab: int = 0) -> None:
    dialog = HelpDialog(parent)
    dialog.findChild(QTabWidget).setCurrentIndex(tab)
    dialog.exec()
