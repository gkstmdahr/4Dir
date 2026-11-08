# -*- coding: utf-8 -*-
"""PDF 도구 (PDFTOOLS_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '회계·인사 팀용 PDF 합치기·나누기·그림을 PDF 로')

- 합치기 open_merge: 고른 PDF(+그림 jpg/png 는 한 쪽으로) 순서 바꿔(끌기·위/아래) → 첫 파일 폴더에 '합본_YYYYMMDD.pdf'
- 나누기 open_split: [쪽마다 한 파일] [쪽 범위로 빼기 '1-3,5,8-'] [N쪽씩] → '이름_쪽1-3.pdf' 또는 '이름_나눔' 폴더
- 그림 → PDF images_to_pdf / open_images_to_pdf: QPdfWriter 300dpi, A4(그림 방향 따라 세로·가로) 또는 그림 크기 그대로, 여백, 사진 회전(EXIF) 반영
- page_count(path): PDF 쪽 수(pypdf, 쪽 목록 /Count 만 읽음), docx/pptx = docProps/app.xml 의 Pages/Slides, 그 밖·깨짐·암호 = None
- 암호 걸린 PDF 는 '다룰 수 없습니다' 안내. 원본은 절대 안 바꿈, 같은 이름이 있으면 'name (1)'
- 무거운 일은 뒤 스레드 + 진행 표시 + 취소 (창을 닫으면 멈춤)
로그: bin\\log\\4Dir.log [QE.pdftools]
"""
import os
import re
import sys
import time
import zipfile
import logging
import tempfile
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
import pypdf  # noqa: E402

PDFTOOLS_VER = "1.0.0"
log = logging.getLogger("QE.pdftools")
logging.getLogger("pypdf").setLevel(logging.ERROR)   # 깨진 PDF 경고가 로그를 채우지 않게
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
OFFICE_TAG = {".docx": "Pages", ".pptx": "Slides"}
DPI = 300


class Locked(Exception):
    """암호 걸린 PDF"""


def is_pdf(p):
    return os.path.splitext(p)[1].lower() == ".pdf"


def is_image(p):
    return os.path.splitext(p)[1].lower() in IMG_EXT


def unique_path(path, is_dir=False):
    """이미 있으면 'name (1).ext' … (폴더는 확장자 없이)"""
    if not os.path.exists(path):
        return path
    stem, ext = (path, "") if is_dir else os.path.splitext(path)
    k = 1
    while os.path.exists(f"{stem} ({k}){ext}"):
        k += 1
    return f"{stem} ({k}){ext}"


def _open_reader(path):
    """PdfReader. 암호면 빈 암호로만 열어 보고 안 되면 Locked"""
    r = pypdf.PdfReader(path, strict=False)
    if r.is_encrypted:
        try:
            ok = r.decrypt("")
        except Exception as ex:
            log.info("암호 PDF (풀기 실패 %s) %s", type(ex).__name__, path)
            raise Locked(path)
        if not ok:
            log.info("암호 PDF %s", path)
            raise Locked(path)
    return r


# ---------------------------------------------------------------- 쪽 수
def page_count(path):
    """PDF·docx·pptx 쪽 수. 모르면 None (엑셀·hwpx·깨짐·암호). 목록 열에서 쓰므로 빠르게"""
    t0 = time.perf_counter()
    ext = os.path.splitext(path)[1].lower()
    n = None
    try:
        if ext == ".pdf":
            r = pypdf.PdfReader(path, strict=False)
            if r.is_encrypted:
                n = None
            else:
                try:   # 쪽 목록의 /Count 만 (쪽을 하나하나 읽지 않음)
                    n = int(r.trailer["/Root"]["/Pages"]["/Count"])
                except Exception:
                    n = len(r.pages)
        elif ext in OFFICE_TAG:
            with zipfile.ZipFile(path) as z:
                xml = z.read("docProps/app.xml").decode("utf-8", "replace")
            m = re.search(r"<(?:\w+:)?%s>\s*(\d+)\s*<" % OFFICE_TAG[ext], xml)
            n = int(m.group(1)) if m else None
    except Exception as ex:
        log.info("쪽 수 못 읽음 %s: %s %s", path, type(ex).__name__, ex)
        n = None
    if ext in (".pdf",) or ext in OFFICE_TAG:
        log.debug("쪽 수 %s = %s (%.1fms)", os.path.basename(path), n, (time.perf_counter() - t0) * 1000)
    return n


# ---------------------------------------------------------------- 쪽 범위 '1-3,5,8-'
def parse_ranges(text, n):
    """'1-3,5,8-' → [0,1,2,4,7,…,n-1] (0부터). 틀리면 ValueError(설명)"""
    out = []
    parts = [x.strip() for x in re.split(r"[,，\s]+", text or "") if x.strip()]
    if not parts:
        raise ValueError(T("쪽 번호를 적어 주세요 (예: 1-3,5,8-)"))
    for part in parts:
        m = re.fullmatch(r"(\d*)\s*[-~]\s*(\d*)", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else n
        elif part.isdigit():
            a = b = int(part)
        else:
            raise ValueError(T("'{0}' 은(는) 쪽 번호로 읽을 수 없습니다").format(part))
        if a < 1 or b > n or a > b:
            raise ValueError(T("'{0}' 은(는) 1 ~ {1} 쪽 밖입니다").format(part, n))
        out += [k for k in range(a - 1, b) if k not in out]
    return out


def _range_label(idx):
    """[0,1,2,4] → '1-3,5'"""
    s, run = [], []
    for k in sorted(idx):
        if run and k == run[-1] + 1:
            run.append(k)
        else:
            if run:
                s.append(f"{run[0] + 1}-{run[-1] + 1}" if len(run) > 1 else f"{run[0] + 1}")
            run = [k]
    if run:
        s.append(f"{run[0] + 1}-{run[-1] + 1}" if len(run) > 1 else f"{run[0] + 1}")
    return ",".join(s)


# ---------------------------------------------------------------- 그림 → PDF
def _read_image(path):
    rd = QtGui.QImageReader(path)
    rd.setAutoTransform(True)   # 사진의 EXIF 회전
    img = rd.read()
    if img.isNull():
        log.warning("그림 못 읽음 %s: %s", path, rd.errorString())
    return img


def images_to_pdf(paths, out_path, page="A4", margin_mm=10, cb=None, cancel=lambda: False):
    """그림 여러 장 → PDF 한 파일 (한 장 = 한 쪽). page='A4' (그림 방향 따라 세로/가로) | 'fit' (그림 크기 그대로, 300dpi 기준).
    cb(완료, 전체). 돌려줌: 넣은 쪽 수 (0 이면 실패 — 파일 안 남김)"""
    t0 = time.time()
    log.info("그림→PDF 시작 %d장 → %s page=%s margin=%smm", len(paths), out_path, page, margin_mm)
    wr = QtGui.QPdfWriter(out_path)
    wr.setResolution(DPI)
    wr.setCreator("4Dir")
    wr.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0), QtGui.QPageLayout.Millimeter)
    painter = None
    n = 0
    try:
        for i, p in enumerate(paths):
            if cancel():
                log.info("그림→PDF 취소 (%d/%d)", i, len(paths))
                break
            img = _read_image(p)
            if img.isNull():
                continue
            land = img.width() > img.height()
            if page == "fit":
                w_mm = img.width() / DPI * 25.4 + 2 * margin_mm
                h_mm = img.height() / DPI * 25.4 + 2 * margin_mm
                ps = QtGui.QPageSize(QtCore.QSizeF(w_mm, h_mm), QtGui.QPageSize.Millimeter, "", QtGui.QPageSize.ExactMatch)
                lay = QtGui.QPageLayout(ps, QtGui.QPageLayout.Portrait, QtCore.QMarginsF(0, 0, 0, 0), QtGui.QPageLayout.Millimeter)
            else:
                lay = QtGui.QPageLayout(QtGui.QPageSize(QtGui.QPageSize.A4),
                                        QtGui.QPageLayout.Landscape if land else QtGui.QPageLayout.Portrait,
                                        QtCore.QMarginsF(0, 0, 0, 0), QtGui.QPageLayout.Millimeter)
            if painter is None:
                wr.setPageLayout(lay)
                painter = QtGui.QPainter()
                if not painter.begin(wr):
                    log.error("그림→PDF: 파일을 만들 수 없음 %s", out_path)
                    painter = None
                    return 0
                painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
            else:
                wr.setPageLayout(lay)
                wr.newPage()
            full = lay.fullRectPixels(DPI)
            m = margin_mm / 25.4 * DPI
            box = QtCore.QRectF(full).adjusted(m, m, -m, -m)
            sc = min(box.width() / img.width(), box.height() / img.height())
            w, h = img.width() * sc, img.height() * sc
            tgt = QtCore.QRectF(box.x() + (box.width() - w) / 2, box.y() + (box.height() - h) / 2, w, h)
            painter.drawImage(tgt, img)
            n += 1
            log.info("  쪽 %d: %s %dx%d %s", n, os.path.basename(p), img.width(), img.height(),
                     "fit" if page == "fit" else ("A4 가로" if land else "A4 세로"))
            if cb:
                cb(i + 1, len(paths))
    except Exception:
        log.exception("그림→PDF 실패")
        n = 0
    finally:
        if painter is not None:
            painter.end()
        del wr
    if n == 0 or cancel():
        try:
            os.remove(out_path)
        except OSError:
            pass
        return 0
    log.info("그림→PDF 끝 %d쪽 %.1f초 %s", n, time.time() - t0, out_path)
    return n


# ---------------------------------------------------------------- 합치기·나누기 (순수 함수)
def merge(paths, out_path, cb=None, cancel=lambda: False, page="A4", margin_mm=10):
    """PDF·그림 → 한 PDF. 돌려줌: 전체 쪽 수. 암호 PDF 는 Locked, 실패는 예외 (만들던 파일은 지움)"""
    t0 = time.time()
    log.info("합치기 시작 %d개 → %s", len(paths), out_path)
    w = pypdf.PdfWriter()
    tmp = []
    try:
        for i, p in enumerate(paths):
            if cancel():
                log.info("합치기 취소 (%d/%d)", i, len(paths))
                return 0
            if is_pdf(p):
                r = _open_reader(p)
                for pg in r.pages:
                    w.add_page(pg)
                log.info("  + %s (%d쪽)", os.path.basename(p), len(r.pages))
            elif is_image(p):
                fd, tp = tempfile.mkstemp(prefix="4dir_img_", suffix=".pdf")
                os.close(fd)
                tmp.append(tp)
                if images_to_pdf([p], tp, page, margin_mm) <= 0:
                    raise IOError(T("그림을 읽을 수 없습니다: {0}").format(os.path.basename(p)))
                r = pypdf.PdfReader(tp)
                for pg in r.pages:
                    w.add_page(pg)
                log.info("  + 그림 %s (1쪽)", os.path.basename(p))
            else:
                log.info("  건너뜀(PDF·그림 아님) %s", p)
            if cb:
                cb(i + 1, len(paths))
        n = len(w.pages)
        if n == 0:
            raise IOError(T("합칠 쪽이 없습니다"))
        with open(out_path, "wb") as f:
            w.write(f)
        log.info("합치기 끝 %d쪽 %.1f초 %s", n, time.time() - t0, out_path)
        return n
    except BaseException:
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except OSError:
            pass
        raise
    finally:
        try:
            w.close()
        except Exception:
            pass
        for tp in tmp:
            try:
                os.remove(tp)
            except OSError:
                pass


def merge_name(first):
    return unique_path(os.path.join(os.path.dirname(first), T("합본") + "_" + time.strftime("%Y%m%d") + ".pdf"))


def split(path, mode, arg=None, cb=None, cancel=lambda: False):
    """mode='each' | 'range'(arg='1-3,5') | 'every'(arg=N). 돌려줌: 만든 파일 목록. 암호 = Locked, 범위 틀림 = ValueError"""
    t0 = time.time()
    r = _open_reader(path)
    n = len(r.pages)
    stem = os.path.splitext(os.path.basename(path))[0]
    folder = os.path.dirname(path)
    log.info("나누기 시작 %s (%d쪽) mode=%s arg=%r", path, n, mode, arg)
    if mode == "range":
        idx = parse_ranges(str(arg), n)
        jobs = [(idx, os.path.join(folder, f"{stem}_{T('쪽')}{_range_label(idx)}.pdf"))]
        jobs = [(a, unique_path(b)) for a, b in jobs]
    else:
        step = 1 if mode == "each" else max(1, int(arg or 1))
        out_dir = unique_path(os.path.join(folder, f"{stem}_{T('나눔')}"), is_dir=True)
        os.makedirs(out_dir)
        wd = len(str(n))
        jobs = []
        for a in range(0, n, step):
            b = min(n, a + step)
            lab = str(a + 1).zfill(wd) if b - a == 1 else f"{str(a + 1).zfill(wd)}-{str(b).zfill(wd)}"
            jobs.append((list(range(a, b)), os.path.join(out_dir, f"{stem}_{T('쪽')}{lab}.pdf")))
    made = []
    for k, (idx, out) in enumerate(jobs):
        if cancel():
            log.info("나누기 취소 (%d/%d)", k, len(jobs))
            break
        w = pypdf.PdfWriter()
        for i in idx:
            w.add_page(r.pages[i])
        with open(out, "wb") as f:
            w.write(f)
        w.close()
        made.append(out)
        if cb:
            cb(k + 1, len(jobs))
    log.info("나누기 끝 %d개 %.1f초 (첫 %s)", len(made), time.time() - t0, made[:1])
    return made


# ---------------------------------------------------------------- 아이콘
def tool_icon(sz=16):
    """빨간 PDF 종이"""
    dpr = 2
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(sz * dpr / 20.0, sz * dpr / 20.0)
    path = QtGui.QPainterPath()
    path.moveTo(4, 1.5)
    path.lineTo(12.5, 1.5)
    path.lineTo(16.5, 5.5)
    path.lineTo(16.5, 18.5)
    path.lineTo(4, 18.5)
    path.closeSubpath()
    p.setPen(QtGui.QPen(QtGui.QColor("#9f1d1d"), 1.0))
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawPath(path)
    p.setBrush(QtGui.QColor("#f3c2c2"))
    p.drawPolygon([QtCore.QPointF(12.5, 1.5), QtCore.QPointF(12.5, 5.5), QtCore.QPointF(16.5, 5.5)])
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#dc2626"))
    p.drawRoundedRect(QtCore.QRectF(1.5, 10, 14, 6.5), 1.2, 1.2)
    f = QtGui.QFont("Segoe UI")
    f.setPixelSize(6)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QtGui.QColor("#ffffff"))
    p.drawText(QtCore.QRectF(1.5, 10, 14, 6.5), Qt.AlignCenter, "PDF")
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QtGui.QIcon(pm)


# ---------------------------------------------------------------- 창 공통
class _Sig(QtCore.QObject):
    progress = QtCore.Signal(int, int)
    done = QtCore.Signal(object, str)    # (결과, 오류 글)
    counts = QtCore.Signal(str, object)  # (경로, 쪽 수)


def _err_text(ex):
    if isinstance(ex, Locked):
        return T("암호가 걸린 PDF 는 다룰 수 없습니다:\n{0}").format(os.path.basename(str(ex)))
    if isinstance(ex, ValueError):
        return str(ex)
    if isinstance(ex, pypdf.errors.PdfReadError):
        return T("PDF 를 읽을 수 없습니다 (파일이 깨졌을 수 있음)")
    return T("처리하다 오류가 났습니다: {0}").format(ex)


class _ToolDlg(QtWidgets.QDialog):
    """진행 막대 + 뒤 스레드 실행 + 창 닫으면 취소"""

    def __init__(self, parent, title, open_loc=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(title + " — 4Dir")
        self.setWindowIcon(tool_icon(20))
        self.open_loc = open_loc
        self._cancel = False
        self._busy = False
        self.sig = _Sig()
        self.sig.progress.connect(self._on_progress)
        self.sig.done.connect(self._on_done)
        self.prog = QtWidgets.QProgressBar()
        self.prog.setVisible(False)
        self.result = QtWidgets.QLabel()
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.btn_show = QtWidgets.QPushButton(T("만든 파일 위치 열기"))
        self.btn_show.setVisible(False)
        self.btn_show.clicked.connect(self._show_out)
        self._out = None

    def run_bg(self, fn):
        self._busy = True
        self._cancel = False
        self.prog.setRange(0, 0)
        self.prog.setVisible(True)
        self.result.setText(T("만드는 중…"))
        self.btn_show.setVisible(False)
        self._set_busy(True)

        def work():
            try:
                res, err = fn(), ""
            except Exception as ex:
                if not isinstance(ex, (Locked, ValueError)):
                    log.exception("작업 실패")
                res, err = None, _err_text(ex)
            try:
                self.sig.done.emit(res, err)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True, name="pdftools").start()

    def _cb(self, a, b):
        try:
            self.sig.progress.emit(a, b)
        except RuntimeError:
            pass

    def _on_progress(self, a, b):
        self.prog.setRange(0, max(1, b))
        self.prog.setValue(a)

    def _on_done(self, res, err):
        self._busy = False
        self.prog.setVisible(False)
        self._set_busy(False)
        if err:
            self.result.setText("⚠ " + err)
            QtWidgets.QMessageBox.warning(self, self.windowTitle(), err)
        else:
            self.finished_ok(res)

    def _set_busy(self, on):
        pass

    def finished_ok(self, res):
        pass

    def _show_out(self):
        if not self._out:
            return
        if self.open_loc:
            self.open_loc(self._out)
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(self._out)))

    def closeEvent(self, ev):
        self._cancel = True
        super().closeEvent(ev)


class _FileList(QtWidgets.QListWidget):
    """끌어서 순서 바꾸기 + 바깥에서 파일 끌어 넣기"""
    dropped = QtCore.Signal(list)

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() and ev.source() is not self:
            ev.acceptProposedAction()
        else:
            super().dragEnterEvent(ev)

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasUrls() and ev.source() is not self:
            ev.acceptProposedAction()
        else:
            super().dragMoveEvent(ev)

    def dropEvent(self, ev):
        if ev.mimeData().hasUrls() and ev.source() is not self:
            self.dropped.emit([u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()])
            ev.acceptProposedAction()
        else:
            super().dropEvent(ev)

    def paths(self):
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def move_sel(self, d):
        rows = sorted(self.row(i) for i in self.selectedItems())
        if not rows or (d < 0 and rows[0] == 0) or (d > 0 and rows[-1] == self.count() - 1):
            return
        for r in (rows if d < 0 else reversed(rows)):
            it = self.takeItem(r)
            self.insertItem(r + d, it)
        self.clearSelection()
        for r in rows:
            self.item(r + d).setSelected(True)
        self.setCurrentRow(rows[0] + d)

    def remove_sel(self):
        for it in self.selectedItems():
            self.takeItem(self.row(it))


def _side_buttons(dlg, lst, add_fn):
    col = QtWidgets.QVBoxLayout()
    for text, fn in ((T("위로"), lambda: lst.move_sel(-1)), (T("아래로"), lambda: lst.move_sel(1)),
                     (T("목록에서 빼기"), lst.remove_sel), (T("파일 더하기…"), add_fn)):
        b = QtWidgets.QPushButton(text)
        b.clicked.connect(fn)
        col.addWidget(b)
    col.addStretch(1)
    return col


# ---------------------------------------------------------------- 합치기 창
class MergeDialog(_ToolDlg):
    def __init__(self, parent, paths, open_loc=None):
        super().__init__(parent, T("PDF 합치기"), open_loc)
        self.resize(640, 460)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(T("위에서부터 차례로 한 파일로 합칩니다. 끌어서 순서를 바꿀 수 있습니다.\n그림 파일(JPG·PNG)은 A4 한 쪽으로 들어갑니다. 원본 파일은 바뀌지 않습니다.")))
        row = QtWidgets.QHBoxLayout()
        self.list = _FileList()
        self.list.dropped.connect(self.add_paths)
        self.list.model().rowsMoved.connect(lambda *a: self._total())
        self.list.model().rowsRemoved.connect(lambda *a: self._total())
        row.addWidget(self.list, 1)
        row.addLayout(_side_buttons(self, self.list, self._add_files))
        lay.addLayout(row, 1)
        self.total = QtWidgets.QLabel()
        lay.addWidget(self.total)
        lay.addWidget(self.prog)
        lay.addWidget(self.result)
        bot = QtWidgets.QHBoxLayout()
        bot.addWidget(self.btn_show)
        bot.addStretch(1)
        self.btn_go = QtWidgets.QPushButton(T("합치기"))
        self.btn_go.setDefault(True)
        self.btn_go.setStyleSheet("font-weight:bold;")
        self.btn_go.clicked.connect(self.go)
        close = QtWidgets.QPushButton(T("닫기"))
        close.clicked.connect(self.close)
        bot.addWidget(self.btn_go)
        bot.addWidget(close)
        lay.addLayout(bot)
        self.counts = {}
        self.sig.counts.connect(self._on_count)
        self.add_paths(paths)
        log.info("합치기 창 열기 %d개", self.list.count())

    def add_paths(self, paths):
        have = {os.path.normcase(p) for p in self.list.paths()}
        new = [os.path.normpath(p) for p in paths if p and os.path.isfile(p) and (is_pdf(p) or is_image(p))
               and os.path.normcase(os.path.normpath(p)) not in have]
        skipped = [p for p in paths if p and not (is_pdf(p) or is_image(p))]
        if skipped:
            log.info("합치기: PDF·그림 아닌 것 뺌 %d개 %s", len(skipped), skipped[:3])
        for p in new:
            it = QtWidgets.QListWidgetItem(os.path.basename(p))
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            self.list.addItem(it)
        need = [p for p in new if is_pdf(p)]
        for p in new:
            if is_image(p):
                self.counts[p] = 1
        self._refresh_items()
        if need:
            def work():
                for p in need:
                    try:
                        _open_reader(p)
                        n = page_count(p)
                    except Locked:
                        n = "locked"
                    except Exception:
                        n = None
                    try:
                        self.sig.counts.emit(p, n)
                    except RuntimeError:
                        return
            threading.Thread(target=work, daemon=True, name="pdf-count").start()

    def _on_count(self, p, n):
        self.counts[p] = n
        self._refresh_items()

    def _refresh_items(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            p = it.data(Qt.UserRole)
            n = self.counts.get(p, "?")
            if n == "locked":
                tail = T("암호 걸림 — 합칠 수 없음")
                it.setForeground(QtGui.QColor("#c0392b"))
            elif n is None:
                tail = T("읽을 수 없음")
                it.setForeground(QtGui.QColor("#c0392b"))
            elif n == "?":
                tail = T("쪽 수 세는 중…")
            else:
                tail = (T("그림 1쪽") if is_image(p) else T("{0}쪽").format(n))
            it.setText(f"{os.path.basename(p)}    —  {tail}")
        self._total()

    def _total(self):
        ps = self.list.paths()
        ns = [self.counts.get(p) for p in ps]
        tot = sum(n for n in ns if isinstance(n, int))
        bad = sum(1 for n in ns if n == "locked" or n is None)
        txt = T("{0}개 파일 · 모두 {1}쪽").format(len(ps), tot)
        if bad:
            txt += "  ·  ⚠ " + T("빨간 줄 {0}개는 합칠 수 없습니다 — 목록에서 빼 주세요").format(bad)
        self.total.setText(txt)
        if not self._busy:
            self.btn_go.setEnabled(len(ps) >= 1 and not bad)

    def _add_files(self):
        fs, _ = QtWidgets.QFileDialog.getOpenFileNames(self, T("파일 더하기"), os.path.dirname(self.list.paths()[0]) if self.list.count() else "",
                                                       T("PDF·그림") + " (*.pdf *.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff)")
        if fs:
            self.add_paths(fs)

    def _set_busy(self, on):
        self.btn_go.setEnabled(not on)
        self.list.setEnabled(not on)

    def go(self):
        ps = self.list.paths()
        if not ps:
            return
        out = merge_name(ps[0])
        self._out = out
        log.info("합치기 누름 %d개 → %s", len(ps), out)
        self.run_bg(lambda: merge(ps, out, self._cb, lambda: self._cancel))

    def finished_ok(self, n):
        if not n:
            self.result.setText(T("취소했습니다"))
            return
        self.result.setText(T("✔ {0}쪽짜리 파일을 만들었습니다:\n{1}").format(n, self._out))
        self.btn_show.setVisible(True)
        self._total()


# ---------------------------------------------------------------- 나누기 창
class SplitDialog(_ToolDlg):
    def __init__(self, parent, path, open_loc=None):
        super().__init__(parent, T("PDF 쪽 나누기·빼기"), open_loc)
        self.path = os.path.normpath(path)
        self.resize(560, 330)
        lay = QtWidgets.QVBoxLayout(self)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        box = QtWidgets.QGroupBox(T("어떻게 나눌까요?"))
        g = QtWidgets.QGridLayout(box)
        self.r_each = QtWidgets.QRadioButton(T("쪽마다 한 파일"))
        self.r_range = QtWidgets.QRadioButton(T("원하는 쪽만 빼서 한 파일로"))
        self.r_every = QtWidgets.QRadioButton(T("몇 쪽씩 나누기"))
        self.r_range.setChecked(True)
        self.e_range = QtWidgets.QLineEdit()
        self.e_range.setPlaceholderText(T("예: 1-3,5,8-   (8- 는 8쪽부터 끝까지)"))
        self.e_range.textChanged.connect(lambda *_: self.r_range.setChecked(True))
        self.sp_every = QtWidgets.QSpinBox()
        self.sp_every.setRange(1, 9999)
        self.sp_every.setValue(2)
        self.sp_every.setSuffix(T("쪽씩"))
        self.sp_every.valueChanged.connect(lambda *_: self.r_every.setChecked(True))
        g.addWidget(self.r_each, 0, 0)
        g.addWidget(QtWidgets.QLabel(T("→ '{0}' 폴더에 쪽마다 파일").format(os.path.splitext(os.path.basename(self.path))[0] + "_" + T("나눔"))), 0, 1)
        g.addWidget(self.r_range, 1, 0)
        g.addWidget(self.e_range, 1, 1)
        g.addWidget(self.r_every, 2, 0)
        g.addWidget(self.sp_every, 2, 1)
        lay.addWidget(box)
        lay.addWidget(QtWidgets.QLabel(T("원본 파일은 바뀌지 않습니다. 새 파일은 같은 폴더에 만듭니다.")))
        lay.addWidget(self.prog)
        lay.addWidget(self.result)
        lay.addStretch(1)
        bot = QtWidgets.QHBoxLayout()
        bot.addWidget(self.btn_show)
        bot.addStretch(1)
        self.btn_go = QtWidgets.QPushButton(T("나누기"))
        self.btn_go.setDefault(True)
        self.btn_go.setStyleSheet("font-weight:bold;")
        self.btn_go.clicked.connect(self.go)
        close = QtWidgets.QPushButton(T("닫기"))
        close.clicked.connect(self.close)
        bot.addWidget(self.btn_go)
        bot.addWidget(close)
        lay.addLayout(bot)
        self.n = None
        try:
            _open_reader(self.path)
            self.n = page_count(self.path)
        except Locked:
            self.info.setText(T("암호가 걸린 PDF 는 다룰 수 없습니다:\n{0}").format(os.path.basename(self.path)))
        except Exception as ex:
            log.info("나누기 창: 못 읽음 %s %s", self.path, ex)
        if self.n:
            self.info.setText(T("파일: {0}\n모두 {1}쪽").format(os.path.basename(self.path), self.n))
        elif not self.info.text():
            self.info.setText(T("PDF 를 읽을 수 없습니다 (파일이 깨졌을 수 있음)") + "\n" + os.path.basename(self.path))
        self.btn_go.setEnabled(bool(self.n))
        log.info("나누기 창 열기 %s (%s쪽)", self.path, self.n)

    def _set_busy(self, on):
        self.btn_go.setEnabled(not on and bool(self.n))

    def go(self):
        if self.r_each.isChecked():
            mode, arg = "each", None
        elif self.r_every.isChecked():
            mode, arg = "every", self.sp_every.value()
        else:
            mode, arg = "range", self.e_range.text()
            try:
                parse_ranges(arg, self.n)
            except ValueError as ex:
                QtWidgets.QMessageBox.warning(self, self.windowTitle(), str(ex))
                return
        log.info("나누기 누름 mode=%s arg=%r", mode, arg)
        self.run_bg(lambda: split(self.path, mode, arg, self._cb, lambda: self._cancel))

    def finished_ok(self, made):
        if not made:
            self.result.setText(T("취소했습니다"))
            return
        self._out = made[0]
        where = made[0] if len(made) == 1 else os.path.dirname(made[0])
        self.result.setText(T("✔ 파일 {0}개를 만들었습니다:\n{1}").format(len(made), where))
        self.btn_show.setVisible(True)


# ---------------------------------------------------------------- 그림 → PDF 창
class ImagesDialog(_ToolDlg):
    def __init__(self, parent, paths, open_loc=None):
        super().__init__(parent, T("그림을 PDF 로 묶기"), open_loc)
        self.resize(620, 480)
        self.picked = [os.path.normpath(p) for p in paths if p and os.path.isfile(p) and is_image(p)]
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(T("그림 한 장이 PDF 한 쪽이 됩니다. 끌어서 순서를 바꿀 수 있습니다.")))
        row = QtWidgets.QHBoxLayout()
        self.list = _FileList()
        self.list.dropped.connect(self.add_paths)
        row.addWidget(self.list, 1)
        row.addLayout(_side_buttons(self, self.list, self._add_files))
        lay.addLayout(row, 1)
        form = QtWidgets.QFormLayout()
        self.c_order = QtWidgets.QComboBox()
        self.c_order.addItems([T("이름 순서"), T("고른 순서")])
        self.c_order.currentIndexChanged.connect(self._reorder)
        self.c_page = QtWidgets.QComboBox()
        self.c_page.addItems([T("A4 (그림 방향 따라 세로·가로)"), T("그림 크기 그대로")])
        self.sp_margin = QtWidgets.QSpinBox()
        self.sp_margin.setRange(0, 50)
        self.sp_margin.setValue(10)
        self.sp_margin.setSuffix(" mm")
        form.addRow(T("순서"), self.c_order)
        form.addRow(T("쪽 크기"), self.c_page)
        form.addRow(T("여백"), self.sp_margin)
        lay.addLayout(form)
        lay.addWidget(self.prog)
        lay.addWidget(self.result)
        bot = QtWidgets.QHBoxLayout()
        bot.addWidget(self.btn_show)
        bot.addStretch(1)
        self.btn_go = QtWidgets.QPushButton(T("PDF 만들기"))
        self.btn_go.setDefault(True)
        self.btn_go.setStyleSheet("font-weight:bold;")
        self.btn_go.clicked.connect(self.go)
        close = QtWidgets.QPushButton(T("닫기"))
        close.clicked.connect(self.close)
        bot.addWidget(self.btn_go)
        bot.addWidget(close)
        lay.addLayout(bot)
        self._reorder()
        log.info("그림→PDF 창 열기 %d장", len(self.picked))

    def _fill(self, ps):
        self.list.clear()
        for p in ps:
            it = QtWidgets.QListWidgetItem(os.path.basename(p))
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            self.list.addItem(it)
        self.btn_go.setEnabled(bool(ps))

    def _reorder(self, *_):
        cur = self.list.paths() if self.list.count() else list(self.picked)
        if self.c_order.currentIndex() == 0:
            import shellops
            cur = sorted(cur, key=lambda p: shellops.natural_key(os.path.basename(p)))
        else:
            pos = {p: i for i, p in enumerate(self.picked)}
            cur = sorted(cur, key=lambda p: pos.get(p, 1 << 30))
        self._fill(cur)

    def add_paths(self, paths):
        have = {os.path.normcase(p) for p in self.list.paths()}
        new = [os.path.normpath(p) for p in paths if p and os.path.isfile(p) and is_image(p) and os.path.normcase(os.path.normpath(p)) not in have]
        self.picked += new
        self._fill(self.list.paths() + new)

    def _add_files(self):
        fs, _ = QtWidgets.QFileDialog.getOpenFileNames(self, T("파일 더하기"), os.path.dirname(self.list.paths()[0]) if self.list.count() else "",
                                                       T("그림") + " (*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff *.gif)")
        if fs:
            self.add_paths(fs)

    def _set_busy(self, on):
        self.btn_go.setEnabled(not on and self.list.count() > 0)
        self.list.setEnabled(not on)

    def go(self):
        ps = self.list.paths()
        if not ps:
            return
        stem = os.path.splitext(os.path.basename(ps[0]))[0]
        out = unique_path(os.path.join(os.path.dirname(ps[0]), f"{stem}_{T('묶음')}.pdf"))
        self._out = out
        page = "fit" if self.c_page.currentIndex() == 1 else "A4"
        mg = self.sp_margin.value()
        log.info("그림→PDF 누름 %d장 → %s", len(ps), out)
        self.run_bg(lambda: images_to_pdf(ps, out, page, mg, self._cb, lambda: self._cancel))

    def finished_ok(self, n):
        if not n:
            self.result.setText("⚠ " + T("PDF 를 만들지 못했습니다 (그림을 읽을 수 없거나 취소)"))
            return
        self.result.setText(T("✔ {0}쪽짜리 파일을 만들었습니다:\n{1}").format(n, self._out))
        self.btn_show.setVisible(True)


# ---------------------------------------------------------------- 진입 함수
def open_merge(parent, paths, open_loc=None):
    d = MergeDialog(parent, paths, open_loc)
    d.show()
    return d


def open_split(parent, path, open_loc=None):
    d = SplitDialog(parent, path, open_loc)
    d.show()
    return d


def open_images_to_pdf(parent, paths, open_loc=None):
    d = ImagesDialog(parent, paths, open_loc)
    d.show()
    return d
