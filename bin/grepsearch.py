# -*- coding: utf-8 -*-
"""파일 내용 찾기 (GREPSEARCH_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '파일 내용 찾기(grep)')

- open_dialog(parent, folder, open_cb=None) → 창: 찾을 글자 · [정규식] [대소문자 구분] [낱말 단위] · 파일 이름 거르기('*.py;*.txt', 빈칸=전부)
  · 하위 폴더 포함 · 건너뛸 폴더(기본 .git .svn .hg node_modules __pycache__ .vs .idea) · 큰 파일(기본 20MB 넘음) 건너뜀
- 이진 파일(앞 8KB 에 0 바이트)은 건너뜀. 글자 방식: BOM → UTF-8 → CP949 순
- 뒤 스레드로 찾음(화면 안 멈춤), 결과는 나무: 파일(찾은 수) ▸ 줄번호: 그 줄(찾은 부분 굵게·색). 진행 '파일 N개 중 M개에서 K곳'. 취소
- 결과 두 번 누르기 → open_cb(path, line) (없으면 os.startfile). 우클릭: 파일 위치 열기(open_cb(path, None)) · 경로 복사 · 결과 목록 복사
- 찾은 곳이 너무 많으면(MAX_HITS) 거기서 멈추고 알림
- search(...) 는 창 없이 쓰는 순수 함수 (시험·다른 기능용)
로그: bin\\log\\4Dir.log [QE.grep]
"""
import os
import re
import html
import time
import fnmatch
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

GREPSEARCH_VER = "1.0.0"
log = logging.getLogger("QE.grep")
DEFAULT_SKIP = ".git;.svn;.hg;node_modules;__pycache__;.vs;.idea"
DEFAULT_MAX_MB = 20
MAX_HITS = 50000
LINE_SHOW = 400            # 결과에 보일 줄 최대 글자


def decode_bytes(b):
    """BOM → UTF-8 → CP949. 이진(앞 8KB 에 0 바이트)이면 None"""
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", "replace")
    if b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff"):
        return b.decode("utf-16", "replace")
    if b"\x00" in b[:8192]:
        return None
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp949", "replace")


def make_pattern(text, regex=False, case=False, word=False):
    """찾을 글자 → re 패턴 (잘못된 정규식이면 re.error)"""
    p = text if regex else re.escape(text)
    if word:
        p = r"\b(?:" + p + r")\b"
    return re.compile(p, 0 if case else re.IGNORECASE)


def split_list(s):
    return [x.strip() for x in re.split(r"[;,]", s or "") if x.strip()]


def search(folder, pattern, masks=None, recurse=True, skip_dirs=None, max_bytes=DEFAULT_MAX_MB * 1048576,
           cancel=lambda: False, on_file=None, on_progress=None, max_hits=MAX_HITS):
    """folder 안 파일 내용 찾기. on_file(path, [(줄번호, 줄, [(시작, 끝)])]) 은 찾은 파일마다.
    반환 dict(files=훑은 파일 수, matched=찾은 파일 수, hits=곳 수, skipped_big, skipped_bin, errors, stopped)"""
    masks = [m.lower() for m in (masks or []) if m and m != "*" and m != "*.*"]
    skip = {d.lower() for d in (skip_dirs or [])}
    st = dict(files=0, matched=0, hits=0, skipped_big=0, skipped_bin=0, errors=0, stopped=False)
    t0 = time.perf_counter()
    last = [0.0]
    stack = [folder]
    log.info("내용 찾기 시작 %s 패턴=%r 거르기=%s 하위=%s 건너뛸 폴더=%s 크기제한=%d",
             folder, pattern.pattern, masks, recurse, sorted(skip), max_bytes)
    while stack:
        if cancel():
            st["stopped"] = True
            break
        d = stack.pop()
        try:
            it = sorted(os.scandir(d), key=lambda e: e.name.lower())
        except OSError as e:
            st["errors"] += 1
            log.debug("폴더 못 읽음 %s: %s", d, e)
            continue
        subs = []
        for e in it:
            if cancel():
                st["stopped"] = True
                break
            try:
                if e.is_dir(follow_symlinks=False):
                    if recurse and e.name.lower() not in skip and not e.is_junction():
                        subs.append(e.path)
                    continue
                if not e.is_file():
                    continue
            except OSError:
                continue
            nm = e.name.lower()
            if masks and not any(fnmatch.fnmatchcase(nm, m) for m in masks):
                continue
            st["files"] += 1
            try:
                size = e.stat().st_size
                if size > max_bytes:
                    st["skipped_big"] += 1
                    continue
                with open(e.path, "rb") as f:
                    b = f.read()
            except OSError as ex:
                st["errors"] += 1
                log.debug("파일 못 읽음 %s: %s", e.path, ex)
                continue
            text = decode_bytes(b)
            if text is None:
                st["skipped_bin"] += 1
                continue
            if pattern.search(text):
                res = []
                for no, line in enumerate(text.splitlines(), 1):
                    spans = [(m.start(), m.end()) for m in pattern.finditer(line) if m.end() > m.start()]
                    if spans:
                        res.append((no, line, spans))
                        st["hits"] += len(spans)
                if res:
                    st["matched"] += 1
                    if on_file:
                        on_file(e.path, res)
                if st["hits"] >= max_hits:
                    st["stopped"] = "max"
                    break
            now = time.perf_counter()
            if on_progress and now - last[0] > 0.1:
                last[0] = now
                on_progress(dict(st), e.path)
        if st["stopped"]:
            break
        stack.extend(reversed(subs))
    st["sec"] = round(time.perf_counter() - t0, 3)
    log.info("내용 찾기 끝 %s: %s", folder, st)
    return st


def _show_line(line, spans):
    """줄 → (보일 글자, 보일 칸 기준 spans) — 너무 길면 첫 찾은 곳 근처만"""
    off = 0
    if len(line) > LINE_SHOW:
        off = max(0, spans[0][0] - 60)
        line = line[off:off + LINE_SHOW]
    out = [(max(0, a - off), min(len(line), b - off)) for a, b in spans if b - off > 0 and a - off < len(line)]
    return line, out


def line_html(line, spans, col):
    line, spans = _show_line(line, spans)
    parts, pos = [], 0
    for a, b in spans:
        if a < pos:
            continue
        parts.append(html.escape(line[pos:a]))
        parts.append(f'<b style="color:{col}">{html.escape(line[a:b])}</b>')
        pos = b
    parts.append(html.escape(line[pos:]))
    return "".join(parts).replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")


class _HtmlDelegate(QtWidgets.QStyledItemDelegate):
    """결과 줄: HTML(찾은 부분 굵게·색)로 그림"""
    ROLE = Qt.UserRole + 5

    def paint(self, p, opt, idx):
        h = idx.data(self.ROLE)
        if not h:
            return super().paint(p, opt, idx)
        o = QtWidgets.QStyleOptionViewItem(opt)
        self.initStyleOption(o, idx)
        o.text = ""
        st = o.widget.style() if o.widget else QtWidgets.QApplication.style()
        st.drawControl(QtWidgets.QStyle.CE_ItemViewItem, o, p, o.widget)
        doc = QtGui.QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(o.font)
        fg = o.palette.color(QtGui.QPalette.HighlightedText if o.state & QtWidgets.QStyle.State_Selected else QtGui.QPalette.Text)
        doc.setHtml(f'<span style="color:{fg.name()};white-space:pre">{h}</span>')
        r = st.subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, o, o.widget)
        p.save()
        p.setClipRect(r)
        p.translate(r.left(), r.top() + max(0, (r.height() - doc.size().height()) / 2))
        doc.drawContents(p)
        p.restore()


class _Bridge(QtCore.QObject):
    file_found = QtCore.Signal(str, object)
    progress = QtCore.Signal(object, str)
    done = QtCore.Signal(object)


class GrepDialog(QtWidgets.QDialog):
    def __init__(self, parent, folder, open_cb=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowIcon(grep_icon(32))
        self.folder = folder
        self.open_cb = open_cb
        self.setWindowTitle(T("파일 내용 찾기") + f" — {folder}")
        self.resize(900, 620)
        self._cancel = False
        self._thread = None
        self._results = []          # [(path, rows)]
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        form = QtWidgets.QGridLayout()
        self.q = QtWidgets.QLineEdit()
        self.q.setPlaceholderText(T("찾을 글자"))
        self.q.setClearButtonEnabled(True)
        form.addWidget(QtWidgets.QLabel(T("찾을 글자")), 0, 0)
        form.addWidget(self.q, 0, 1, 1, 3)
        self.c_regex = QtWidgets.QCheckBox(T("정규식"))
        self.c_case = QtWidgets.QCheckBox(T("대소문자 구분"))
        self.c_word = QtWidgets.QCheckBox(T("낱말 단위"))
        opt = QtWidgets.QHBoxLayout()
        for c in (self.c_regex, self.c_case, self.c_word):
            opt.addWidget(c)
        opt.addStretch(1)
        form.addLayout(opt, 1, 1, 1, 3)
        self.mask = QtWidgets.QLineEdit()
        self.mask.setPlaceholderText(T("예: *.py;*.txt (빈칸 = 전부)"))
        form.addWidget(QtWidgets.QLabel(T("파일 이름")), 2, 0)
        form.addWidget(self.mask, 2, 1)
        self.c_sub = QtWidgets.QCheckBox(T("하위 폴더 포함"))
        self.c_sub.setChecked(True)
        form.addWidget(self.c_sub, 2, 2)
        self.max_mb = QtWidgets.QSpinBox()
        self.max_mb.setRange(1, 4096)
        self.max_mb.setValue(DEFAULT_MAX_MB)
        self.max_mb.setSuffix(" MB")
        self.max_mb.setPrefix(T("최대 크기") + " ")
        form.addWidget(self.max_mb, 2, 3)
        self.skip = QtWidgets.QLineEdit(DEFAULT_SKIP)
        form.addWidget(QtWidgets.QLabel(T("건너뛸 폴더")), 3, 0)
        form.addWidget(self.skip, 3, 1, 1, 3)
        form.setColumnStretch(1, 1)
        lay.addLayout(form)
        bar = QtWidgets.QHBoxLayout()
        self.b_go = QtWidgets.QPushButton(T("찾기"))
        self.b_go.setDefault(True)
        self.b_stop = QtWidgets.QPushButton(T("취소"))
        self.b_stop.setEnabled(False)
        self.status = QtWidgets.QLabel(T("폴더: {0}").format(folder))
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bar.addWidget(self.b_go)
        bar.addWidget(self.b_stop)
        bar.addWidget(self.status, 1)
        lay.addLayout(bar)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setItemDelegate(_HtmlDelegate(self.tree))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        lay.addWidget(self.tree, 1)
        self.bridge = _Bridge()
        self.bridge.file_found.connect(self._add_file)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.done.connect(self._on_done)
        self.b_go.clicked.connect(self.start)
        self.q.returnPressed.connect(self.start)
        self.b_stop.clicked.connect(self.stop)
        self.tree.itemDoubleClicked.connect(self._activate)
        self.tree.customContextMenuRequested.connect(self._menu)
        QtGui.QShortcut(QtGui.QKeySequence("Escape"), self, self._esc)
        log.info("내용 찾기 창 열기 %s", folder)

    def _hit_color(self):
        pal = self.palette()
        dark = pal.color(QtGui.QPalette.Window).lightness() < 128
        return "#ff9f43" if dark else "#c2410c"

    def start(self):
        if self._thread is not None:
            return
        text = self.q.text()
        if not text:
            self.status.setText(T("찾을 글자를 넣으세요"))
            return
        try:
            pat = make_pattern(text, self.c_regex.isChecked(), self.c_case.isChecked(), self.c_word.isChecked())
        except re.error as e:
            self.status.setText(T("정규식이 잘못됨: {0}").format(e))
            log.info("정규식 오류 %r: %s", text, e)
            return
        self.tree.clear()
        self._results = []
        self._col = self._hit_color()
        self._cancel = False
        self.b_go.setEnabled(False)
        self.b_stop.setEnabled(True)
        self.status.setText(T("찾는 중…"))
        args = dict(masks=split_list(self.mask.text()), recurse=self.c_sub.isChecked(),
                    skip_dirs=split_list(self.skip.text()), max_bytes=self.max_mb.value() * 1048576)
        br = self.bridge

        def run():
            st = None
            try:
                st = search(self.folder, pat, cancel=lambda: self._cancel,
                            on_file=lambda p, r: br.file_found.emit(p, r),
                            on_progress=lambda s, p: br.progress.emit(s, p), **args)
            except Exception:
                log.exception("내용 찾기 오류")
            br.done.emit(st)
        self._thread = threading.Thread(target=run, name="grep", daemon=True)
        self._thread.start()

    def stop(self):
        self._cancel = True
        log.info("내용 찾기 취소 요청")

    def _esc(self):
        if self._thread is not None:
            self.stop()
        else:
            self.close()

    @staticmethod
    def _prog_text(st):
        return T("파일 {0:,}개 중 {1:,}개에서 {2:,}곳").format(st["files"], st["matched"], st["hits"])

    def _on_progress(self, st, path):
        self.status.setText(self._prog_text(st) + " — " + os.path.basename(path))

    def _add_file(self, path, rows):
        self._results.append((path, rows))
        try:
            rel = os.path.relpath(path, self.folder)
        except ValueError:
            rel = path
        n = sum(len(s) for _no, _l, s in rows)
        it = QtWidgets.QTreeWidgetItem([f"{rel}  ({n:,})"])
        it.setData(0, Qt.UserRole, (path, None))
        it.setToolTip(0, path)
        f = it.font(0)
        f.setBold(True)
        it.setFont(0, f)
        kids = []
        for no, line, spans in rows:
            k = QtWidgets.QTreeWidgetItem([f"{no}: {line[:LINE_SHOW]}"])
            k.setData(0, Qt.UserRole, (path, no))
            k.setData(0, _HtmlDelegate.ROLE, f"{no}: " + line_html(line, spans, self._col))
            kids.append(k)
        it.addChildren(kids)
        self.tree.addTopLevelItem(it)
        if self.tree.topLevelItemCount() <= 30:
            it.setExpanded(True)

    def _on_done(self, st):
        self._thread = None
        self.b_go.setEnabled(True)
        self.b_stop.setEnabled(False)
        if st is None:
            self.status.setText(T("찾다가 오류가 났습니다 (기록 파일 참고)"))
            return
        s = self._prog_text(st)
        extra = []
        if st["stopped"] == "max":
            extra.append(T("너무 많아 {0:,}곳에서 멈춤").format(MAX_HITS))
        elif st["stopped"]:
            extra.append(T("취소됨"))
        if st["skipped_bin"]:
            extra.append(T("이진 파일 {0:,}개 건너뜀").format(st["skipped_bin"]))
        if st["skipped_big"]:
            extra.append(T("큰 파일 {0:,}개 건너뜀").format(st["skipped_big"]))
        self.status.setText(" · ".join([s] + extra))
        self.last_stats = st

    def _activate(self, it, _col=0):
        d = it.data(0, Qt.UserRole)
        if not d:
            return
        path, line = d
        log.info("결과 열기 %s 줄 %s", path, line)
        if self.open_cb:
            self.open_cb(path, line)
        else:
            try:
                os.startfile(path)
            except OSError as e:
                self.status.setText(T("열 수 없음: {0}").format(e))

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        m = QtWidgets.QMenu(self)
        if it is not None and it.data(0, Qt.UserRole):
            path = it.data(0, Qt.UserRole)[0]
            m.addAction(T("파일 위치 열기"), lambda: self._reveal(path))
            m.addAction(T("경로 복사"), lambda: QtWidgets.QApplication.clipboard().setText(path))
        a = m.addAction(T("결과 목록 복사"), self.copy_all)
        a.setEnabled(bool(self._results))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _reveal(self, path):
        if self.open_cb:
            self.open_cb(path, None)
        else:
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    def results_text(self):
        out = []
        for path, rows in self._results:
            out.append(path)
            for no, line, _s in rows:
                out.append(f"  {no}: {line}")
        return "\n".join(out)

    def copy_all(self):
        QtWidgets.QApplication.clipboard().setText(self.results_text())

    def closeEvent(self, ev):
        self._cancel = True
        th = self._thread
        if th is not None:
            th.join(2.0)
        try:
            self.bridge.file_found.disconnect()
            self.bridge.progress.disconnect()
            self.bridge.done.disconnect()
        except (RuntimeError, TypeError):
            pass
        log.info("내용 찾기 창 닫기")
        super().closeEvent(ev)


def open_dialog(parent, folder, open_cb=None):
    d = GrepDialog(parent, folder, open_cb)
    d.show()
    return d


def grep_icon(sz=16):
    """문서 + 돋보기"""
    def draw(p):
        p.setPen(QtGui.QPen(QtGui.QColor("#6b7280"), 1.0))
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawRect(QtCore.QRectF(2.5, 1.5, 11, 15))
        p.setPen(QtGui.QPen(QtGui.QColor("#9ca3af"), 1.2))
        for y in (5, 8, 11):
            p.drawLine(QtCore.QPointF(4.5, y), QtCore.QPointF(11.5, y))
        p.setPen(QtGui.QPen(QtGui.QColor("#f59e0b"), 1.2))
        p.drawLine(QtCore.QPointF(4.5, 8), QtCore.QPointF(8.5, 8))
        p.setPen(QtGui.QPen(QtGui.QColor("#1d6fd6"), 1.8))
        p.setBrush(QtGui.QColor(255, 255, 255, 180))
        p.drawEllipse(QtCore.QPointF(13, 12.5), 3.6, 3.6)
        p.setPen(QtGui.QPen(QtGui.QColor("#1d6fd6"), 2.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QtCore.QPointF(15.8, 15.3), QtCore.QPointF(18.3, 17.8))
    return _icon(sz, draw)


def _icon(sz, draw):
    pm = QtGui.QPixmap(sz * 2, sz * 2)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.scale(sz * 2 / 20.0, sz * 2 / 20.0)
    draw(p)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return QtGui.QIcon(pm)
