# -*- coding: utf-8 -*-
"""글자·16진수 보기 (HEXVIEW_VER 1.0.0, 0.9.109 빌드 3 — 사용자 11/6 '추가 기능 전부', 경쟁 앱 조사 '글자/16진수 보기')

- F3 (또는 우클릭·도구): 고른 파일을 따로 창에서 봄. 읽기만 함(파일을 고치지 않음)
- 글자: 앞 8MB 까지. 인코딩 = BOM → UTF-8 → CP949(한국어 윈도우) 순으로 맞춰 봄, 위에서 바꿀 수 있음. 줄 바꿈 켜기/끄기
- 16진수: 파일 크기와 상관없이 — 화면에 보이는 줄만 그때그때 파일에서 읽어 그림(1GB 파일도 메모리 거의 안 씀)
- 글자 찾기(Ctrl+F) · 16진수 칸에서 위치로 가기(Ctrl+G)
로그: bin\\log\\4Dir.log [QE.hexview]
"""
import os
import logging

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

HEXVIEW_VER = "1.0.0"
log = logging.getLogger("QE.hexview")
TEXT_MAX = 8 * 1048576
ENCODINGS = ["auto", "utf-8", "cp949", "utf-16", "latin-1", "shift_jis", "gb18030", "big5"]


def guess_encoding(b):
    """앞부분 바이트로 인코딩 추측 → (인코딩, 글자인가)"""
    if b.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", True
    if b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff"):
        return "utf-16", True
    sample = b[:65536]
    head = sample[:8192]
    ctrl = sum(1 for c in head if c < 9 or (13 < c < 32 and c != 27))
    if b"\x00" in head or ctrl > len(head) // 20:   # 0 바이트·제어 글자가 섞이면 글자 파일이 아님
        return "latin-1", False
    for enc in ("utf-8", "cp949"):
        try:
            sample.decode(enc)
            return enc, True
        except UnicodeDecodeError as ex:
            if enc == "utf-8" and ex.start >= len(sample) - 4:   # 잘린 끝 글자 때문이면 UTF-8
                return enc, True
    return "cp949", True


class HexWidget(QtWidgets.QAbstractScrollArea):
    """16진수 보기: 한 줄 16바이트, 보이는 줄만 파일에서 읽음"""
    W = 16

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.size = os.path.getsize(path)
        self.f = open(path, "rb")
        self.mark = -1   # 위치로 가기 표시
        f = QtGui.QFont("Consolas")
        f.setStyleHint(QtGui.QFont.Monospace)
        f.setPointSize(10)
        self.setFont(f)
        self.viewport().setFont(f)
        self._metrics()
        self.verticalScrollBar().valueChanged.connect(self.viewport().update)

    def _metrics(self):
        fm = QtGui.QFontMetrics(self.font())
        self.lh = fm.height() + 2
        self.cw = fm.horizontalAdvance("0")
        self._range()

    def lines(self):
        return (self.size + self.W - 1) // self.W

    def _range(self):
        vis = max(1, self.viewport().height() // self.lh)
        sb = self.verticalScrollBar()
        sb.setRange(0, max(0, self.lines() - vis))
        sb.setPageStep(vis)
        sb.setSingleStep(1)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._range()

    def close_file(self):
        try:
            self.f.close()
        except Exception:
            pass

    def goto(self, off):
        off = max(0, min(off, max(0, self.size - 1)))
        self.mark = off
        self.verticalScrollBar().setValue(max(0, off // self.W - 2))
        self.viewport().update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self.viewport())
        pal = self.palette()
        p.fillRect(self.viewport().rect(), pal.base())
        first = self.verticalScrollBar().value()
        vis = self.viewport().height() // self.lh + 1
        self.f.seek(first * self.W)
        data = self.f.read(vis * self.W)
        fg = pal.text().color()
        dim = QtGui.QColor(fg)
        dim.setAlpha(130)
        x_hex = self.cw * 11
        x_txt = x_hex + self.cw * (self.W * 3 + 2)
        for i in range(vis):
            chunk = data[i * self.W:(i + 1) * self.W]
            if not chunk:
                break
            y = i * self.lh
            base = (first + i) * self.W
            p.setPen(dim)
            p.drawText(QtCore.QRect(4, y, x_hex, self.lh), Qt.AlignVCenter, f"{base:08X}")
            for j, b in enumerate(chunk):
                xx = x_hex + j * self.cw * 3 + (self.cw if j >= 8 else 0)
                if base + j == self.mark:
                    p.fillRect(QtCore.QRect(xx - 2, y, self.cw * 2 + 4, self.lh), QtGui.QColor(255, 200, 0, 120))
                p.setPen(dim if b == 0 else fg)
                p.drawText(QtCore.QRect(xx, y, self.cw * 3, self.lh), Qt.AlignVCenter, f"{b:02X}")
            p.setPen(fg)
            txt = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            p.drawText(QtCore.QRect(x_txt, y, self.cw * (self.W + 2), self.lh), Qt.AlignVCenter, txt)
        p.end()

    def wheelEvent(self, ev):
        sb = self.verticalScrollBar()
        sb.setValue(sb.value() - ev.angleDelta().y() // 40)


class ViewerDialog(QtWidgets.QDialog):
    """글자·16진수 보기 창 (따로 창, 여러 개 열 수 있음)"""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.path = path
        self.setWindowTitle(T("보기") + f" — {os.path.basename(path)}")
        self.resize(900, 640)
        self.size = os.path.getsize(path)
        with open(path, "rb") as f:
            self.head = f.read(TEXT_MAX)
        self.enc, is_text = guess_encoding(self.head)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        bar = QtWidgets.QHBoxLayout()
        self.b_text = QtWidgets.QPushButton(T("글자"))
        self.b_hex = QtWidgets.QPushButton(T("16진수"))
        for b in (self.b_text, self.b_hex):
            b.setCheckable(True)
            b.setAutoExclusive(True)
            bar.addWidget(b)
        self.enc_box = QtWidgets.QComboBox()
        self.enc_box.addItems([T("자동") + f" ({self.enc})"] + ENCODINGS[1:])
        self.enc_box.setToolTip(T("글자 인코딩 — 글자가 깨지면 바꿔 보세요"))
        bar.addWidget(self.enc_box)
        self.wrap = QtWidgets.QCheckBox(T("줄 바꿈"))
        self.wrap.setChecked(True)
        bar.addWidget(self.wrap)
        self.find_edit = QtWidgets.QLineEdit()
        self.find_edit.setPlaceholderText(T("찾기 (Enter = 다음)"))
        self.find_edit.setClearButtonEnabled(True)
        bar.addWidget(self.find_edit, 1)
        self.goto_edit = QtWidgets.QLineEdit()
        self.goto_edit.setPlaceholderText(T("위치 (16진수 예: 1F00)"))
        self.goto_edit.setFixedWidth(150)
        bar.addWidget(self.goto_edit)
        lay.addLayout(bar)
        self.stack = QtWidgets.QStackedWidget()
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        mono = QtGui.QFont("Consolas")
        mono.setStyleHint(QtGui.QFont.Monospace)
        mono.setPointSize(10)
        self.text.setFont(mono)
        self.hex = HexWidget(path)
        self.stack.addWidget(self.text)
        self.stack.addWidget(self.hex)
        lay.addWidget(self.stack, 1)
        self.info = QtWidgets.QLabel()
        lay.addWidget(self.info)
        self.b_text.clicked.connect(lambda: self.set_mode("text"))
        self.b_hex.clicked.connect(lambda: self.set_mode("hex"))
        self.enc_box.currentIndexChanged.connect(lambda _i: self._load_text())
        self.wrap.toggled.connect(lambda on: self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth if on else QtWidgets.QPlainTextEdit.NoWrap))
        self.find_edit.returnPressed.connect(self.find_next)
        self.goto_edit.returnPressed.connect(self.goto)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+F"), self, lambda: (self.find_edit.setFocus(), self.find_edit.selectAll()))
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+G"), self, lambda: (self.set_mode("hex"), self.goto_edit.setFocus(), self.goto_edit.selectAll()))
        QtGui.QShortcut(QtGui.QKeySequence("Escape"), self, self.close)
        self._load_text()
        self.set_mode("text" if is_text else "hex")
        log.info("보기 열기 %s 크기 %d 인코딩 %s 글자=%s", path, self.size, self.enc, is_text)

    def cur_enc(self):
        i = self.enc_box.currentIndex()
        return self.enc if i <= 0 else ENCODINGS[i]

    def _load_text(self):
        s = self.head.decode(self.cur_enc(), "replace")
        if "\x00" in s:
            s = s.replace("\x00", "·")
        self.text.setPlainText(s)
        self._info()

    def set_mode(self, mode):
        self.mode = mode
        self.b_text.setChecked(mode == "text")
        self.b_hex.setChecked(mode == "hex")
        self.stack.setCurrentIndex(0 if mode == "text" else 1)
        self.enc_box.setEnabled(mode == "text")
        self.wrap.setEnabled(mode == "text")
        self._info()

    def _info(self):
        if not hasattr(self, "mode"):
            return
        s = T("{0:,} 바이트").format(self.size)
        if self.mode == "text":
            s += f" · {self.cur_enc()} · " + T("{0:,}줄").format(self.text.blockCount())
            if self.size > TEXT_MAX:
                s += " · " + T("앞 {0}MB 만 보임 — 전체는 16진수에서").format(TEXT_MAX // 1048576)
        self.info.setText(s)

    def find_next(self):
        q = self.find_edit.text()
        if not q:
            return
        if self.mode == "text":
            if not self.text.find(q):
                self.text.moveCursor(QtGui.QTextCursor.Start)   # 끝까지 갔으면 처음부터
                if not self.text.find(q):
                    self.info.setText(T("못 찾음: {0}").format(q))
            return
        # 16진수: 글자(UTF-8) 또는 '4D 5A' 같은 바이트로 찾음, 지금 표시 다음부터
        try:
            needle = bytes.fromhex(q) if all(c in "0123456789abcdefABCDEF " for c in q) and len(q.replace(" ", "")) % 2 == 0 else q.encode("utf-8")
        except ValueError:
            needle = q.encode("utf-8")
        start = self.hex.mark + 1 if self.hex.mark >= 0 else 0
        pos = self._scan(needle, start)
        if pos < 0 and start > 0:
            pos = self._scan(needle, 0)
        if pos < 0:
            self.info.setText(T("못 찾음: {0}").format(q))
        else:
            self.hex.goto(pos)
            self.info.setText(T("찾음: 위치 {0:X}").format(pos))

    def _scan(self, needle, start):
        with open(self.path, "rb") as f:
            f.seek(start)
            off, tail = start, b""
            while True:
                b = f.read(4 * 1048576)
                if not b:
                    return -1
                buf = tail + b
                i = buf.find(needle)
                if i >= 0:
                    return off - len(tail) + i
                tail = buf[-(len(needle) - 1):] if len(needle) > 1 else b""
                off += len(b)

    def goto(self):
        t = self.goto_edit.text().strip().lower().replace("0x", "")
        try:
            off = int(t, 16)
        except ValueError:
            self.info.setText(T("위치는 16진수로 (예: 1F00)"))
            return
        self.set_mode("hex")
        self.hex.goto(off)

    def closeEvent(self, ev):
        self.hex.close_file()
        super().closeEvent(ev)
