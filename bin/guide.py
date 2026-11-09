# -*- coding: utf-8 -*-
"""4Dir 사용법 창 — 처음 실행 때 한 번, 그 뒤엔 도구 > 사용법

페이지마다 실제 4Dir 화면 캡처(bin\\guide\\<ko|en>\\pN.png, 빨간 번호 표시) + 오른쪽 설명(번역됨).
번호가 있는 설명 = 그림의 빨간 번호, '•' = 그림에 없는 추가 설명.
그림은 _build 의 사용법 캡처 스크립트로 다시 만듦 (예시 폴더만 씀 — 회사 경로 없음).
"""
import os
import logging

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

import i18n
from i18n import T

log = logging.getLogger("QE.guide")
GUIDE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guide")
VERSION = "2.0.0"   # 2.0.0 (0.9.126): 카테고리 + 움직이는 장면 영상 + 키 표시 (예전 창은 ClassicGuideWindow)


def pages():
    """[(제목, [(번호 또는 None, 설명)])] — 번호 = 그림의 빨간 번호"""
    return [
        (T("화면 구성"), [
            (1, T("레이아웃: 칸 나누기 버튼 (1·2·3·4·6칸, 맨 끝은 직접 지정 — 가로×세로 최대 5×4)")),
            (2, T("즐겨찾기 바: 폴더를 끌어다 놓으면 추가, 우클릭으로 이름 바꾸기·삭제")),
            (3, T("주소줄: 경로 버튼을 누르면 그 폴더로, 빈 곳을 누르면 경로를 직접 입력")),
            (4, T("🔍 빠른 필터 (Ctrl+F): 지금 폴더에서 이름으로 거르기")),
            (5, T("탭: + 로 새 탭 (Ctrl+T), Ctrl+W 로 닫기, 우클릭하면 새 창으로 열기")),
            (6, T("전체 검색 (Ctrl+Shift+F): 색인한 드라이브에서 이름으로 바로 찾기")),
            (7, T("상태줄: 항목 수·선택 수·읽은 시간")),
        ]),
        (T("칸 나누기와 창 구성"), [
            (1, T("칸마다 따로 탭과 폴더 — 마지막에 누른 칸이 파란 테두리 (단축키가 이 칸에 적용)")),
            (2, T("칸 사이 경계를 끌어 크기 조절")),
            (3, T("창 저장/불러오기: 지금 칸 배치와 탭을 이름 붙여 저장, 자동 기록에서 복구")),
            (4, T("탭 우클릭 → 새 창으로 열기 (4Dir 창 또는 윈도우 탐색기)")),
            (None, T("Ctrl+N: 새 창 · 창을 하나씩 닫으면 마지막에 닫은 창 모습으로 다시 열림")),
        ]),
        (T("파일 작업"), [
            (1, T("끌어 놓기: 놓을 폴더가 진하게 표시되고 '→ 폴더(으)로 이동' 안내 (Ctrl = 복사, Shift = 이동)")),
            (None, T("F6: 다른 칸으로 복사 · Shift+F6: 다른 칸으로 이동")),
            (None, T("Ctrl+Z: 되돌리기 (이름 바꾸기·새 폴더·이동·복사·이름 일괄 변경)")),
            (None, T("여러 개 고르고 F2 (또는 우클릭 → 이름 일괄 변경): 이름 일괄 변경 창")),
            (None, T("우클릭 메뉴는 윈도우 탐색기 메뉴 그대로 (압축·TortoiseSVN 등)")),
        ]),
        (T("검색"), [
            (1, T("전체 검색 칸: 단어 여러 개 = 모두 포함, *.max 같은 와일드카드")),
            (2, T("결과는 🔎 탭으로 — '위치' 열에 들어 있는 폴더")),
            (3, T("결과를 두 번 클릭하면 열기, 우클릭 → 폴더 위치 열기")),
            (None, T("도구 > 검색 범위 설정: 색인할 드라이브·폴더 고르기")),
            (None, T("🔍 필터 옆 ⤵ 버튼: 색인 없이 지금 폴더 아래 전체에서 찾기")),
        ]),
        (T("SVN 상태 표시"), [
            (1, T("✓ 초록: 바뀐 것 없음 (폴더는 안쪽 전체)")),
            (2, T("! 빨강: 수정됨 (폴더는 안쪽 어딘가 수정)")),
            (3, T("+ 파랑: 추가 예정")),
            (4, T("? 회색: 버전 관리 밖")),
            (None, T("! 주황 = 충돌, × 빨강 = 삭제 예정")),
            (None, T("큰 작업 폴더는 처음 확인에 시간이 걸림 — 상태줄에 'SVN 확인 중'")),
            (None, T("보기 > 표시 > SVN 상태 표시: 끄고 켜기")),
        ]),
        (T("단축키와 설정"), [
            (1, T("도구 > 단축키 설정: 기능마다 원하는 키로 바꾸기")),
            (None, T("Ctrl+T 새 탭 · Ctrl+W 탭 닫기 · Ctrl+N 새 창 · Ctrl+L / F4 주소줄")),
            (None, T("Ctrl+F 필터 · Ctrl+Shift+F 전체 검색 · F2 이름 바꾸기 · Ctrl+Z 되돌리기")),
            (None, T("Ctrl+Shift+C 경로 복사 · Alt+Enter 속성 · Ctrl+마우스 휠 보기 크기")),
            (None, T("보기 메뉴: 화면 테마(시스템·밝게·어둡게)와 언어")),
            (None, T("문제가 생기면 도구 > 문제 보고용 로그 저장")),
        ]),
    ]


def image_path(n):
    """언어에 맞는 그림 (한국어는 ko, 나머지는 en, 없으면 다른 쪽)"""
    first = "ko" if i18n.lang == "ko" else "en"
    for d in (first, "en", "ko"):
        p = os.path.join(GUIDE_DIR, d, f"p{n}.png")
        if os.path.exists(p):
            return p
    return None


def marker_html(n):
    return (f"<span style='background:#e53935; color:white; font-weight:bold; border-radius:9px;'>"
            f"&nbsp;{n}&nbsp;</span>")


class ClassicGuideWindow(QtWidgets.QWidget):
    """예전 사용법 창 (그림 + 빨간 번호) — 사이트용 그림(make_guide.py)에서만 씀"""
    def __init__(self, parent=None, start=0):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(T("4Dir 사용법"))
        self.resize(1400, 720)
        self.pages = pages()
        self.i = 0
        lay = QtWidgets.QVBoxLayout(self)
        body = QtWidgets.QHBoxLayout()
        self.img = QtWidgets.QLabel()
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setMinimumSize(640, 400)
        self.img.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        body.addWidget(self.img, 5)
        side = QtWidgets.QVBoxLayout()
        self.title = QtWidgets.QLabel()
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() * 1.5)
        f.setBold(True)
        self.title.setFont(f)
        side.addWidget(self.title)
        self.text = QtWidgets.QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        self.text.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.text.setMinimumWidth(320)
        side.addWidget(self.text)
        # 이전/다음: 설명 바로 밑에 크게 (다음 = 파란색, 마지막 페이지는 '닫기') — 10/5 사용자 요청
        pn = QtWidgets.QHBoxLayout()
        self.prev = QtWidgets.QPushButton(T("◀ 이전"))
        self.prev.setMinimumHeight(44)
        self.prev.setStyleSheet("QPushButton{font-size:14px; padding:0 18px;}")
        self.next = QtWidgets.QPushButton(T("다음 ▶"))
        self.next.setObjectName("guideNext")
        self.next.setMinimumHeight(44)
        self.next.setCursor(Qt.PointingHandCursor)
        self.next.setStyleSheet("QPushButton#guideNext{background:#1a73e8; color:white; font-size:16px; font-weight:bold;"
                                " border:none; border-radius:6px; padding:0 28px;}"
                                "QPushButton#guideNext:hover{background:#1765cc;}"
                                "QPushButton#guideNext:pressed{background:#0b57d0;}")
        self.count = QtWidgets.QLabel()
        self.count.setAlignment(Qt.AlignCenter)
        self.prev.clicked.connect(lambda: self.go(self.i - 1))
        self.next.clicked.connect(self._next)
        pn.addWidget(self.prev)
        pn.addWidget(self.count)
        pn.addWidget(self.next, 1)
        side.addSpacing(8)
        side.addLayout(pn)
        side.addStretch(1)
        sidew = QtWidgets.QWidget()
        sidew.setLayout(side)
        sidew.setMaximumWidth(400)   # 그림을 크게 (설명 칸은 좁게)
        body.addWidget(sidew, 2)
        lay.addLayout(body, 1)
        nav = QtWidgets.QHBoxLayout()
        close = QtWidgets.QPushButton(T("닫기"))
        close.clicked.connect(self.close)
        nav.addStretch(1)
        nav.addWidget(QtWidgets.QLabel(T("다시 보기: 도구 > 사용법")))
        nav.addWidget(close)
        lay.addLayout(nav)
        QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Left), self, lambda: self.go(self.i - 1))
        QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Right), self, lambda: self.go(self.i + 1))
        QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Escape), self, self.close)
        self.go(start)
        log.info("사용법 창 열기 (언어 %s)", i18n.lang)

    def go(self, i):
        self.i = max(0, min(len(self.pages) - 1, i))
        title, items = self.pages[self.i]
        self.title.setText(f"{self.i + 1}. {title}")
        rows = []
        for n, t in items:
            mark = marker_html(n) if n else "&nbsp;&nbsp;•&nbsp;"
            rows.append(f"<p style='margin:0 0 10px 0;'>{mark}&nbsp; {t.replace('<', '&lt;')}</p>")
        self.text.setText("".join(rows))
        self.count.setText(f"{self.i + 1} / {len(self.pages)}")
        self.prev.setEnabled(self.i > 0)
        last = self.i == len(self.pages) - 1
        self.next.setText(T("닫기") if last else T("다음 ▶"))
        self._pix = None
        p = image_path(self.i + 1)
        if p:
            self._pix = QtGui.QPixmap(p)
        self._fit()

    def _next(self):
        if self.i >= len(self.pages) - 1:
            self.close()
        else:
            self.go(self.i + 1)

    def _fit(self):
        if self._pix is None or self._pix.isNull():
            self.img.setText(T("(그림 없음)"))
            return
        self.img.setPixmap(self._pix.scaled(self.img.size() * self.devicePixelRatioF(), Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))
        self.img.pixmap().setDevicePixelRatio(self.devicePixelRatioF()) if self.img.pixmap() else None

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self, "_pix", None) is not None:
            self._fit()


# ================================================================ 2.0.0 새 사용법 창 (0.9.126 사용자 '카테고리별로, 실제로 움직이는 영상으로')
# 왼쪽 카테고리 · 오른쪽 번호·제목 + 움직이는 장면(bin\guide\demo\<ko|en>\<id>.mp4, _build\make_demos.py 로 찍음) + 설명 + 키 표시
def topics():
    """[(카테고리, [(id, 제목, [설명…], [키 묶음…])])] — 키 묶음 = ("Ctrl", "T") 처럼 누르는 키들"""
    return [
        (T("화면 영역 안내"), [
            ("layout", T("칸 나누기 (레이아웃)"), [T("도구줄의 레이아웃 단추로 1·2·3·4·6칸, 직접 지정(가로×세로)까지 나눕니다."),
                                                 T("칸마다 따로 폴더·탭을 엽니다. 누른 칸이 파란 테두리로 '지금 칸'이 됩니다.")], [("Ctrl", "1~6")]),
            ("tabs", T("탭 · 여러 줄 탭"), [T("+ 로 새 탭, × 로 닫기. 탭을 끌어 순서를 바꾸거나 다른 칸·창 밖으로 떼어 냅니다."),
                                         T("탭이 넘치면 아래 줄로 내려갑니다 (설정 ▸ 일반에서 끌 수 있음).")], [("Ctrl", "T"), ("Ctrl", "W"), ("Ctrl", "Shift", "T")]),
            ("favbar", T("즐겨찾기 줄"), [T("자주 쓰는 폴더를 즐겨찾기 줄에 끌어다 놓으면 추가됩니다. 누르면 지금 칸에서 열립니다."),
                                       T("우클릭으로 이름 바꾸기·지우기·묶음 만들기.")], [("Ctrl", "D")]),
            ("navpane", T("탐색 창 · 폴더 고정"), [T("왼쪽 탐색 창 맨 위에 4Dir 즐겨찾기, 그 아래 Windows 즐겨찾기·내 PC."),
                                                T("📌 폴더 고정을 켜면 다른 폴더를 열어도 트리가 그대로 — 펼쳐 둔 폴더로 파일을 끌어 옮길 때 편합니다.")], []),
            ("address", T("주소줄"), [T("경로 단추를 누르면 그 폴더로, 빈 곳을 누르면 경로를 직접 입력합니다.")], [("Alt", "D"), ("Ctrl", "L")]),
            ("chips", T("형식 단추"), [T("맨 위 [전체][JPG][PNG]… 단추를 누르면 모든 칸이 그 형식만 보여 줍니다. Ctrl+누르기 = 여러 형식.")], []),
            ("views", T("보기 방식"), [T("자세히·목록·아이콘(작은~아주 큰)을 바꿉니다. 폴더마다·칸마다·전부 같게는 설정 ▸ 일반에서.")], [("Ctrl", T("휠"))]),
            ("preview", T("미리보기 창"), [T("그림·동영상·PDF·문서를 고르면 바로 보입니다. PDF 는 쪽 넘기기, ✎ 편집으로 바로 편집.")], [("Alt", "P"), ("Space",)]),
            ("memo", T("메모"), [T("할 일·체크 목록·그림을 붙여 두는 메모 창. 알림 시간도 넣을 수 있습니다.")], [("Alt", "M")]),
        ]),
        (T("파일 작업"), [
            ("dragcopy", T("칸끼리 복사 · 이동"), [T("파일을 다른 칸으로 끌어 놓으면 복사(다른 드라이브) 또는 이동(같은 드라이브)."),
                                               T("Ctrl 끌기 = 복사, Shift 끌기 = 이동. F6 / Shift+F6 = 고른 것을 옆 칸으로 복사 / 이동.")], [("F6",), ("Shift", "F6")]),
            ("sidedrop", T("탐색 창에 끌어 놓기"), [T("파일을 왼쪽 탐색 창의 폴더 위에 놓아도 복사·이동됩니다.")], []),
            ("samefolder", T("옆 칸에 같은 폴더"), [T("지금 폴더를 옆 칸에도 엽니다. 새 탭으로 열지, 보던 탭을 바꿀지는 설정 ▸ 일반에서.")], [("Ctrl", "=")]),
            ("typeahead", T("글자로 찾기"), [T("파일 목록에서 이름 앞글자를 빠르게 치면(1초 안) 그 이름으로 갑니다. 예: de → debug.")], []),
            ("rename", T("이름 바꾸기 · 일괄 변경"), [T("F2 = 이름 바꾸기 (확장명은 그대로). 여러 개를 고르고 F2 = 이름 일괄 변경 창(번호·바꾸기·대소문자).")], [("F2",)]),
            ("fitcols", T("열 너비 자동 맞춤"), [T("자세히 보기에서 긴 이름도 다 보이게 열 너비를 맞춥니다. 머리글 우클릭으로도.")], [("Ctrl", "Num +")]),
        ]),
        (T("도구"), [
            ("search", T("전체 검색"), [T("맨 위 검색칸에 치면 색인한 폴더 전체에서 바로 찾습니다. 검색 범위는 설정 ▸ 검색.")], [("Ctrl", "Shift", "F")]),
            ("compare", T("두 칸 비교"), [T("두 칸의 같은 이름 파일을 비교해 한쪽에만 있거나 더 새것을 골라 줍니다 → F6 으로 반대쪽에 복사.")], [("Shift", "F2")]),
            ("pdf", T("PDF 편집"), [T("PDF 우클릭 ▸ 4Dir 도구 ▸ PDF 편집 또는 미리보기의 ✎ 편집."),
                                   T("쪽: 돌리기·지우기·순서·끼워 넣기 / 주석: 펜·형광펜·글상자 / 나누기: 쪽마다·범위·몇 쪽씩.")], []),
            ("imgedit", T("그림 편집"), [T("그림 우클릭 ▸ 4Dir 도구 ▸ 그림 편집 또는 미리보기의 ✎ 편집 — 자르기·글자·화살표·모자이크·밝기.")], []),
            ("thispc", T("내 PC"), [T("드라이브마다 전체 크기·남은 공간과 사용량 막대 (윈도우 탐색기처럼).")], []),
            ("settings", T("설정"), [T("언어·테마·창·탭·보기 방식·탐색 창·단축키·색상·검색·백업을 한곳에서. 바꾸면 바로 적용.")], [("Ctrl", ",")]),
        ]),
    ]


def clip_path(tid):
    """장면 영상 (한국어는 ko, 나머지는 en, 없으면 다른 쪽)"""
    first = "ko" if i18n.lang == "ko" else "en"
    for d in (first, "en", "ko"):
        p = os.path.join(GUIDE_DIR, "demo", d, tid + ".mp4")
        if os.path.exists(p):
            return p
    return None


def keycaps(keys):
    """("Ctrl","T") → 키 모양 HTML"""
    cap = ("<span style='background:#ffffff; color:#202124; border:1px solid #9aa0a6; border-bottom:2px solid #80868b;"
           " border-radius:4px; padding:1px 7px; font-weight:bold;'>&nbsp;{0}&nbsp;</span>")
    return " + ".join(cap.format(k.replace("<", "&lt;")) for k in keys)


class GuideWindow(QtWidgets.QWidget):
    """사용법 2.0 — 왼쪽 카테고리 목록 · 오른쪽 움직이는 장면 + 설명. ←/→ 앞뒤, Esc 닫기"""

    def __init__(self, parent=None, start=0):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(T("4Dir 사용법"))
        self.resize(1240, 760)
        self.flat = []    # [(id, 제목, 설명, 키, 트리 항목)]
        self.movie = None
        lay = QtWidgets.QHBoxLayout(self)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(250)
        self.tree.setIndentation(14)
        self.tree.setObjectName("guideTree")
        bold = self.tree.font()
        bold.setBold(True)
        bold.setPointSizeF(bold.pointSizeF() + 1)
        n = 0
        for cat, items in topics():
            c = QtWidgets.QTreeWidgetItem([cat])
            c.setFont(0, bold)
            c.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(c)
            for tid, title, lines, keys in items:
                n += 1
                it = QtWidgets.QTreeWidgetItem([f"{n}  {title}"])
                it.setData(0, Qt.UserRole, len(self.flat))
                c.addChild(it)
                self.flat.append((tid, title, lines, keys, it))
            c.setExpanded(True)
        sc = QtWidgets.QTreeWidgetItem([T("단축키 모음")])
        sc.setFont(0, bold)
        sc.setData(0, Qt.UserRole, -1)
        self.tree.addTopLevelItem(sc)
        self.tree.currentItemChanged.connect(self._on_item)
        lay.addWidget(self.tree)
        right = QtWidgets.QVBoxLayout()
        self.title = QtWidgets.QLabel()
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() * 1.6)
        f.setBold(True)
        self.title.setFont(f)
        right.addWidget(self.title)
        self.stage = QtWidgets.QStackedWidget()
        self.video = QtWidgets.QLabel()
        self.video.setAlignment(Qt.AlignCenter)
        self.video.setMinimumSize(640, 360)
        self.video.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.video.setStyleSheet("background:#1f2329; border-radius:8px;")
        self.keys_page = QtWidgets.QTextBrowser()
        self.keys_page.setOpenLinks(False)
        self.stage.addWidget(self.video)
        self.stage.addWidget(self.keys_page)
        right.addWidget(self.stage, 1)
        self.text = QtWidgets.QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text.setMinimumHeight(90)
        right.addWidget(self.text)
        nav = QtWidgets.QHBoxLayout()
        self.prev = QtWidgets.QPushButton(T("◀ 이전"))
        self.prev.setMinimumHeight(40)
        self.next = QtWidgets.QPushButton(T("다음 ▶"))
        self.next.setObjectName("guideNext")
        self.next.setMinimumHeight(40)
        self.next.setCursor(Qt.PointingHandCursor)
        self.next.setStyleSheet("QPushButton#guideNext{background:#03C75A; color:white; font-size:15px; font-weight:bold;"
                                " border:none; border-radius:6px; padding:0 30px;} QPushButton#guideNext:hover{background:#02b350;}")
        self.count = QtWidgets.QLabel()
        self.prev.clicked.connect(lambda: self.go(self.i - 1))
        self.next.clicked.connect(self._next)
        close = QtWidgets.QPushButton(T("닫기"))
        close.setMinimumHeight(40)
        close.clicked.connect(self.close)
        nav.addWidget(QtWidgets.QLabel(T("다시 보기: 설정 ▸ 정보 ▸ 사용법")))
        nav.addStretch(1)
        nav.addWidget(self.count)
        nav.addWidget(self.prev)
        nav.addWidget(self.next)
        nav.addWidget(close)
        right.addLayout(nav)
        lay.addLayout(right, 1)
        QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Left), self, lambda: self.go(self.i - 1))
        QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Right), self, lambda: self.go(self.i + 1))
        QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Escape), self, self.close)
        self.i = -2
        self.go(max(0, min(start, len(self.flat) - 1)))
        log.info("사용법 창 2.0 열기 (언어 %s, 주제 %d개)", i18n.lang, len(self.flat))

    def _on_item(self, it, _prev=None):
        if it is None:
            return
        i = it.data(0, Qt.UserRole)
        if i is None:
            return
        if i == -1:
            self._show_keys()
        elif i != self.i:
            self.go(i)

    def go(self, i):
        i = max(0, min(len(self.flat) - 1, i))
        self.i = i
        tid, title, lines, keys, it = self.flat[i]
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(it)
        self.tree.blockSignals(False)
        self.title.setText(f"<span style='background:#1a73e8; color:white; border-radius:10px;'>&nbsp;{i + 1}&nbsp;</span>&nbsp; {title}")
        rows = [f"<p style='margin:0 0 6px 0;'>• {ln.replace('<', '&lt;')}</p>" for ln in lines]
        if keys:
            rows.append("<p style='margin:10px 0 0 0;'>" + T("단축키") + ":&nbsp; " + " &nbsp;·&nbsp; ".join(keycaps(k) for k in keys) + "</p>")
        self.text.setText("".join(rows))
        self.count.setText(f"{i + 1} / {len(self.flat)}")
        self.prev.setEnabled(i > 0)
        self.next.setText(T("닫기") if i == len(self.flat) - 1 else T("다음 ▶"))
        self.stage.setCurrentWidget(self.video)
        self._play(clip_path(tid))
        log.info("사용법 %d %s", i + 1, tid)

    def _play(self, path):
        if self.movie is not None:
            try:
                self.movie.stop()
                self.movie.deleteLater()
            except RuntimeError:
                pass
            self.movie = None
        self.video.setPixmap(QtGui.QPixmap())
        if not path:
            self.video.setText(T("(장면 영상 없음)"))
            return
        import video
        if not video.available():
            self.video.setText(T("(동영상 부품이 없어 장면을 보여 줄 수 없습니다)"))
            return
        self.video.setText("")
        m = video.VideoMovie(path, self, muted=True)
        m.frameChanged.connect(self._frame)
        m.start()
        self.movie = m

    def _frame(self, *_):
        if self.movie is None:
            return
        im = self.movie.currentImage()
        if im is None or im.isNull():
            return
        sz = self.video.size()
        pm = QtGui.QPixmap.fromImage(im).scaled(sz.width() - 8, sz.height() - 8, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.video.setPixmap(pm)

    def _show_keys(self):
        """단축키 모음 (지금 설정된 키)"""
        import keymap
        km = keymap.current(_settings_keys())
        rows = []
        for cat, title in keymap.CATS:
            acts = [a for a, *_ in keymap.ACTIONS if keymap.CAT.get(a) == cat and km.get(a)]
            if not acts:
                continue
            rows.append(f"<h3 style='margin:12px 0 4px 0;'>{title}</h3><table cellspacing='4'>")
            for a in acts:
                ks = " &nbsp; ".join(keycaps(k.split("+")) for k in km[a])
                rows.append(f"<tr><td style='padding-right:18px;'>{keymap.LABEL[a]}</td><td>{ks}</td></tr>")
            rows.append("</table>")
        self.keys_page.setHtml("".join(rows))
        self.stage.setCurrentWidget(self.keys_page)
        self.title.setText(T("단축키 모음"))
        self.text.setText(T("바꾸려면: 설정 ▸ 단축키·마우스"))
        if self.movie is not None:
            self.movie.stop()

    def _next(self):
        if self.i >= len(self.flat) - 1:
            self.close()
        else:
            self.go(self.i + 1)

    def closeEvent(self, ev):
        if self.movie is not None:
            try:
                self.movie.stop()
            except RuntimeError:
                pass
        super().closeEvent(ev)


def _settings_keys():
    try:
        import main
        return main.SETTINGS["keys"]
    except Exception:
        return {}
