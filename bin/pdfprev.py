# -*- coding: utf-8 -*-
"""PDF 미리보기 (PDFPREV_VER 1.0.0, 0.9.121 — 사용자 11/10 '우리 툴에서 pdf 가 보이나?')

- 전엔 윈도우 미리보기(썸네일 처리기)에만 맡겨, 처리기가 없는 PC(회사 PC 실측)에서는 아이콘만 나왔음
  → Qt 에 들어 있는 PDF 부품(QtPdf, PDFium)으로 4Dir 가 직접 그림. 윈도우·Acrobat 설정과 상관없이 모든 PC
- 미리보기 창에 끼우는 위젯: can_handle(path) · make_widget(path, parent)  (main.PreviewPane.EXTRA_MODS 규칙)
  쪽 그림(창 폭에 맞춤) · ◀ n / N ▶ · 마우스 휠(맨 아래·맨 위에서 다음·이전 쪽) · 두 번 누르면 기본 프로그램으로 열기
- first_page(path, px) -> QImage : 아이콘 보기 미리보기(thumbs)용 첫 쪽 — 작업 스레드에서 부름
- 암호 걸린 PDF·깨진 파일은 안내 글. QtPdf 가 없는 판(옛 배포판)이면 can_handle False → 예전처럼 윈도우 미리보기
로그: bin\\log\\4Dir.log [QE.pdfprev]
"""
import os
import time
import logging

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

PDFPREV_VER = "1.1.0"   # 1.1.0: 파일을 붙잡지 않음(메모리로 읽음 — 미리보기 중에도 이름 바꾸기·지우기·원본에 저장), [주석][쪽 편집][나누기] 단추, 저장하면 다시 그림 / 1.0.1: 주석도 그림(PDF 편집)
log = logging.getLogger("QE.pdfprev")
try:
    from PySide6.QtPdf import QPdfDocument
except Exception:   # 부품이 없는 판
    QPdfDocument = None


def available():
    return QPdfDocument is not None


def can_handle(path):
    return available() and path.lower().endswith(".pdf") and os.path.isfile(path)


def _opts():
    """주석(펜·형광펜·글상자 등)도 같이 그림 — 0.9.122 PDF 편집"""
    from PySide6.QtPdf import QPdfDocumentRenderOptions
    o = QPdfDocumentRenderOptions()
    o.setRenderFlags(QPdfDocumentRenderOptions.RenderFlag.Annotations)
    return o


def _open(path):
    """파일을 바이트로 읽어 메모리에서 엶 → 파일을 붙잡지 않음 (0.9.123: 미리보기 중 원본에 저장·이름 바꾸기·지우기가 '액세스 거부' 되던 것)"""
    d = QPdfDocument()
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as ex:
        log.info("PDF 못 읽음 %s %s", path, ex)
        data = b""
    buf = QtCore.QBuffer(d)
    buf.setData(QtCore.QByteArray(data))
    buf.open(QtCore.QIODevice.ReadOnly)
    d._buf = buf
    d.load(buf)   # 장치로 열면 돌려주는 값이 없음 → 오류는 error() 로
    return d, d.error()


_VIEWS = []   # 열려 있는 미리보기 (편집 창이 저장하면 다시 그림)


def reload(path):
    """path 를 보여 주는 미리보기를 새 내용으로 (PDF 편집 저장 뒤)"""
    n = 0
    for v in list(_VIEWS):
        try:
            if os.path.normcase(v.path) == os.path.normcase(path):
                v.reload()
                n += 1
        except RuntimeError:
            _VIEWS.remove(v)
    log.info("PDF 미리보기 다시 그림 %s (%d개)", path, n)


def first_page(path, px):
    """첫 쪽을 px 상자 안에 맞춘 그림 (실패하면 None) — 작업 스레드에서 써도 됨(위젯 없음)"""
    if not available():
        return None
    try:
        d, err = _open(path)
        if d.status() != QPdfDocument.Status.Ready or d.pageCount() < 1:
            log.info("PDF 첫 쪽 못 읽음 %s (%s)", path, err)
            return None
        sz = d.pagePointSize(0)
        k = min(px / max(1.0, sz.width()), px / max(1.0, sz.height()))
        im = d.render(0, QtCore.QSize(max(1, int(sz.width() * k)), max(1, int(sz.height() * k))), _opts())
        d.close()
        if im.isNull():
            return None
        out = QtGui.QImage(im.size(), QtGui.QImage.Format_RGB32)   # PDF 는 투명 바탕일 수 있음 → 흰 종이
        out.fill(QtGui.QColor("#ffffff"))
        p = QtGui.QPainter(out)
        p.drawImage(0, 0, im)
        p.end()
        return out
    except Exception:
        log.exception("PDF 첫 쪽 실패 %s", path)
        return None


class PdfView(QtWidgets.QWidget):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.page = 0
        t0 = time.time()
        self.doc, err = _open(path)
        self.n = self.doc.pageCount() if self.doc.status() == QPdfDocument.Status.Ready else 0
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.sc = QtWidgets.QScrollArea()
        self.sc.setWidgetResizable(True)
        self.sc.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.sc.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.pic = QtWidgets.QLabel()
        self.pic.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.pic.setToolTip(T("두 번 누르면 기본 프로그램으로 열기 · 휠로 쪽 넘기기"))
        self.sc.setWidget(self.pic)
        lay.addWidget(self.sc, 1)
        bar = QtWidgets.QHBoxLayout()
        bar.addStretch(1)
        self.b_prev = QtWidgets.QToolButton()
        self.b_prev.setText("◀")
        self.b_prev.setToolTip(T("이전 쪽"))
        self.b_prev.clicked.connect(lambda: self.go(self.page - 1))
        bar.addWidget(self.b_prev)
        self.lbl = QtWidgets.QLabel()
        bar.addWidget(self.lbl)
        self.b_next = QtWidgets.QToolButton()
        self.b_next.setText("▶")
        self.b_next.setToolTip(T("다음 쪽"))
        self.b_next.clicked.connect(lambda: self.go(self.page + 1))
        bar.addWidget(self.b_next)
        bar.addStretch(1)
        # 0.9.123 사용자: 미리보기에서 바로 PDF 편집 (그 탭 · 지금 쪽으로)
        self.edit_btns = []
        for tab, text, tip in (("annot", T("주석"), T("펜·형광펜·글상자 (PDF 편집)")), ("pages", T("쪽 편집"), T("쪽 돌리기·지우기·순서·끼워 넣기 (PDF 편집)")),
                               ("split", T("나누기"), T("쪽마다·범위·몇 쪽씩 나누기 (PDF 편집)"))):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setObjectName("pdfEditBtn")
            b.clicked.connect(lambda *_, t=tab: self.open_edit(t))
            bar.addWidget(b)
            self.edit_btns.append(b)
        lay.addLayout(bar)
        _VIEWS.append(self)
        self.pic.mouseDoubleClickEvent = lambda ev: os.startfile(self.path)
        self.sc.viewport().installEventFilter(self)
        if self.n == 0:
            st = self.doc.status()
            msg = T("암호가 걸린 PDF 라 미리보기를 할 수 없습니다") if err == QPdfDocument.Error.IncorrectPassword else T("PDF 를 읽지 못했습니다")
            self.pic.setText(msg)
            self.pic.setWordWrap(True)
            for b in [self.b_prev, self.b_next] + self.edit_btns:
                b.setVisible(False)
            log.info("PDF 미리보기 못 함 %s (%s, %s)", path, err, st)
        else:
            log.info("PDF 미리보기 %s (%d쪽, 열기 %.0fms)", path, self.n, (time.time() - t0) * 1000)
            QtCore.QTimer.singleShot(0, lambda: self.go(0))

    def go(self, i):
        if not self.n:
            return
        self.page = max(0, min(self.n - 1, i))
        w = max(120, self.sc.viewport().width() - 8)
        sz = self.doc.pagePointSize(self.page)
        dpr = self.devicePixelRatioF() or 1.0
        h = int(w * sz.height() / max(1.0, sz.width()))
        t0 = time.time()
        im = self.doc.render(self.page, QtCore.QSize(int(w * dpr), int(h * dpr)), _opts())
        out = QtGui.QImage(im.size(), QtGui.QImage.Format_RGB32)
        out.fill(QtGui.QColor("#ffffff"))
        p = QtGui.QPainter(out)
        p.drawImage(0, 0, im)
        p.end()
        out.setDevicePixelRatio(dpr)
        self.pic.setPixmap(QtGui.QPixmap.fromImage(out))
        self.lbl.setText(f" {self.page + 1} / {self.n} ")
        self.b_prev.setEnabled(self.page > 0)
        self.b_next.setEnabled(self.page < self.n - 1)
        self.sc.verticalScrollBar().setValue(0)
        log.debug("PDF 쪽 %d/%d 그림 %.0fms", self.page + 1, self.n, (time.time() - t0) * 1000)

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.Wheel and self.n > 1:   # 맨 아래서 아래로 = 다음 쪽, 맨 위에서 위로 = 이전 쪽
            sb = self.sc.verticalScrollBar()
            dy = ev.angleDelta().y()
            if dy < 0 and sb.value() >= sb.maximum() and self.page < self.n - 1:
                self.go(self.page + 1)
                return True
            if dy > 0 and sb.value() <= sb.minimum() and self.page > 0:
                self.go(self.page - 1)
                sb.setValue(sb.maximum())
                return True
        return False

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.n and abs(ev.size().width() - ev.oldSize().width()) > 20:
            QtCore.QTimer.singleShot(0, lambda: self.go(self.page))

    def open_edit(self, tab):
        import pdfedit
        log.info("미리보기 → PDF 편집 %s 탭=%s 쪽=%d", self.path, tab, self.page + 1)
        win = self.window()
        d = pdfedit.open_editor(win, self.path, tab=tab, page=self.page)
        if d is not None and not d.styleSheet() and win is not None:
            d.setStyleSheet(win.styleSheet())
        return d

    def reload(self):
        page = self.page
        try:
            self.doc.close()
        except Exception:
            pass
        self.doc, err = _open(self.path)
        self.n = self.doc.pageCount() if self.doc.status() == QPdfDocument.Status.Ready else 0
        if self.n:
            self.go(min(page, self.n - 1))

    def stop(self):
        if self in _VIEWS:
            _VIEWS.remove(self)
        try:
            self.doc.close()
        except Exception:
            pass


def make_widget(path, parent=None):
    return PdfView(path, parent)
