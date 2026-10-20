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
VERSION = "1.0.2"


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


class GuideWindow(QtWidgets.QWidget):
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
