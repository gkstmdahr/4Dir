# -*- coding: utf-8 -*-
"""날짜별 폴더 정리 (DATEFOLDERS_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '회계·인사 팀용 날짜별 폴더로 정리')

- 고른 파일들을 기준 날짜(수정 날짜 / 사진 찍은 날짜 / 만든 날짜)에 따라 기준 폴더 아래 날짜 폴더로 옮김
- 사진 찍은 날짜 = JPG 의 EXIF DateTimeOriginal 을 직접 읽음(부품 없음, 앞 128KB 만). 없으면 수정 날짜
- 폴더 모양: 2026\\11월 · 2026-11 · 2026\\2026-11-08 · 2026-11-08
- 옮기기 전 미리보기 표(파일 → 새 위치). 같은 이름이 있으면 'name (1)'. 폴더는 옮기지 않음
- [되돌리기]: 이번에 옮긴 것만 원래 자리로 (기록은 모듈 메모리 + 로그, 디스크에 따로 안 남김). 비게 된 새 폴더는 지움
- plan(paths, base_dir, mode, fmt) → [(원래, 새)] 순수 함수. 옮기기는 뒤 스레드
로그: bin\\log\\4Dir.log [QE.datefolders]
"""
import os
import time
import shutil
import struct
import logging
import datetime
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

DATEFOLDERS_VER = "1.0.0"
log = logging.getLogger("QE.datefolders")
MODES = ["mtime", "exif", "ctime"]
FORMATS = ["y_m", "y-m", "y_ymd", "ymd"]
JPG_EXT = {".jpg", ".jpeg", ".jpe"}
HISTORY = []   # [{"pairs": [(원래, 새)…], "dirs": [새로 만든 폴더…]}] — 이번 실행 동안 옮긴 묶음 (되돌리기용, 메모리만)


# ---------------------------------------------------------------- 사진 찍은 날짜 (EXIF)
def exif_date(path):
    """JPG 의 EXIF DateTimeOriginal(없으면 DateTimeDigitized) → datetime. 없거나 못 읽으면 None"""
    if os.path.splitext(path)[1].lower() not in JPG_EXT:
        return None
    try:
        with open(path, "rb") as f:
            data = f.read(131072)
    except OSError:
        return None
    try:
        if data[:2] != b"\xff\xd8":
            return None
        i = 2
        while i + 4 <= len(data):
            if data[i] != 0xFF:
                return None
            mk = data[i + 1]
            if mk in (0xD8, 0x01) or 0xD0 <= mk <= 0xD7:
                i += 2
                continue
            if mk in (0xD9, 0xDA):   # 그림 데이터 시작 = 더 이상 정보 칸 없음
                return None
            ln = struct.unpack(">H", data[i + 2:i + 4])[0]
            seg = data[i + 4:i + 2 + ln]
            if mk == 0xE1 and seg[:6] == b"Exif\x00\x00":
                return _tiff_date(seg[6:])
            i += 2 + ln
    except Exception as ex:
        log.debug("EXIF 못 읽음 %s: %s", path, ex)
    return None


def _tiff_date(t):
    bo = {b"II": "<", b"MM": ">"}.get(t[:2])
    if not bo:
        return None
    u16 = lambda o: struct.unpack(bo + "H", t[o:o + 2])[0]
    u32 = lambda o: struct.unpack(bo + "I", t[o:o + 4])[0]

    def entries(off):
        n = u16(off)
        for k in range(n):
            e = off + 2 + k * 12
            yield u16(e), u16(e + 2), u32(e + 4), e + 8

    def text(cnt, voff_pos):
        o = u32(voff_pos) if cnt > 4 else voff_pos
        return t[o:o + cnt].split(b"\x00")[0].decode("ascii", "replace").strip()

    ifd0 = u32(4)
    exif_off, dt0 = None, None
    for tag, typ, cnt, vp in entries(ifd0):
        if tag == 0x8769:
            exif_off = u32(vp)
        elif tag == 0x0132 and typ == 2:
            dt0 = text(cnt, vp)
    found = {}
    if exif_off:
        for tag, typ, cnt, vp in entries(exif_off):
            if tag in (0x9003, 0x9004) and typ == 2:
                found[tag] = text(cnt, vp)
    for s in (found.get(0x9003), found.get(0x9004)):
        if s:
            try:
                return datetime.datetime.strptime(s[:19], "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue
    return None


def file_date(path, mode):
    """mode: mtime(수정) / exif(사진 찍은, 없으면 수정) / ctime(만든) → datetime"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    if mode == "exif":
        d = exif_date(path)
        if d:
            return d
    ts = st.st_ctime if mode == "ctime" else st.st_mtime   # 윈도우: st_ctime = 만든 날짜
    return datetime.datetime.fromtimestamp(ts)


def folder_for(d, fmt):
    """날짜 → 상대 폴더 경로"""
    if fmt == "y_m":
        return os.path.join(f"{d.year}", T("{0}월").format(d.month))
    if fmt == "y-m":
        return f"{d.year}-{d.month:02d}"
    if fmt == "y_ymd":
        return os.path.join(f"{d.year}", d.strftime("%Y-%m-%d"))
    return d.strftime("%Y-%m-%d")


def _free_name(path, taken):
    """이미 있거나(디스크) 이번 계획에 잡힌 이름이면 'name (1).ext'"""
    stem, ext = os.path.splitext(path)
    cand, k = path, 0
    while os.path.exists(cand) or os.path.normcase(cand) in taken:
        k += 1
        cand = f"{stem} ({k}){ext}"
    return cand


def plan(paths, base_dir, mode="mtime", fmt="y_m"):
    """[(원래, 새)] — 폴더·없는 파일·이미 그 자리인 것은 뺌. 디스크는 안 바꿈"""
    out, taken = [], set()
    base_dir = os.path.normpath(base_dir)
    for p in paths:
        p = os.path.normpath(p)
        if not os.path.isfile(p):
            continue
        d = file_date(p, mode)
        if d is None:
            continue
        dst_dir = os.path.join(base_dir, folder_for(d, fmt))
        dst = os.path.join(dst_dir, os.path.basename(p))
        if os.path.normcase(dst) == os.path.normcase(p):
            continue
        dst = _free_name(dst, taken)
        taken.add(os.path.normcase(dst))
        out.append((p, dst))
    log.info("계획 %d개 → %d개 옮김 base=%s mode=%s fmt=%s", len(paths), len(out), base_dir, mode, fmt)
    return out


def _mv(a, b):
    if os.path.splitdrive(a)[0].lower() == os.path.splitdrive(b)[0].lower():
        os.rename(a, b)
    else:
        shutil.move(a, b)


def execute(pairs, cb=None, cancel=lambda: False):
    """계획대로 옮김 → (옮긴 [(원래, 새)], 실패 [(원래, 이유)]). 옮긴 것은 HISTORY 에 남김"""
    done, fail, made = [], [], []
    t0 = time.time()
    for i, (src, dst) in enumerate(pairs):
        if cancel():
            log.info("옮기기 취소 %d/%d", i, len(pairs))
            break
        try:
            dd = os.path.dirname(dst)
            if not os.path.isdir(dd):
                # 새로 만드는 폴더를 위에서부터 기억 (되돌릴 때 비면 지움)
                chain, x = [], dd
                while x and not os.path.isdir(x):
                    chain.append(x)
                    x = os.path.dirname(x)
                os.makedirs(dd)
                made += reversed(chain)
            if os.path.exists(dst):
                dst = _free_name(dst, set())
            _mv(src, dst)
            done.append((src, dst))
            log.info("옮김 %s → %s", src, dst)
        except OSError as ex:
            log.warning("옮기기 실패 %s → %s: %s", src, dst, ex)
            fail.append((src, str(ex)))
        if cb:
            cb(i + 1, len(pairs))
    if done:
        HISTORY.append({"pairs": list(done), "dirs": made})
    log.info("옮기기 끝 %d개 성공 · %d개 실패 · 새 폴더 %d개 %.1f초", len(done), len(fail), len(made), time.time() - t0)
    return done, fail


def undo(done=None):
    """마지막(또는 주어진) 옮기기를 되돌림 → (되돌린 수, 못 한 [(경로, 이유)])"""
    ent = None
    if done is None:
        if not HISTORY:
            return 0, []
        ent = HISTORY[-1]
    else:
        want = [tuple(x) for x in done]
        ent = next((h for h in reversed(HISTORY) if [tuple(x) for x in h["pairs"]] == want), None)
    if ent is not None:
        done = ent["pairs"]
    back, fail = 0, []
    for src, dst in reversed(done):
        try:
            if os.path.exists(src):
                raise OSError(T("원래 자리에 같은 이름이 생겼습니다"))
            os.makedirs(os.path.dirname(src), exist_ok=True)
            _mv(dst, src)
            back += 1
            log.info("되돌림 %s → %s", dst, src)
        except OSError as ex:
            log.warning("되돌리기 실패 %s: %s", dst, ex)
            fail.append((dst, str(ex)))
    gone = 0
    for d in reversed(ent["dirs"] if ent else []):   # 아래 폴더부터
        try:
            os.rmdir(d)   # 비었을 때만 지워짐
            gone += 1
        except OSError:
            pass
    if ent in HISTORY:
        HISTORY.remove(ent)
    log.info("되돌리며 비게 된 새 폴더 %d개 지움", gone)
    log.info("되돌리기 끝 %d개 · 실패 %d개", back, len(fail))
    return back, fail


# ---------------------------------------------------------------- 아이콘
def tool_icon(sz=16):
    """달력 + 폴더"""
    dpr = 2
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(sz * dpr / 20.0, sz * dpr / 20.0)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#d9a420"))
    p.drawRoundedRect(QtCore.QRectF(1, 6, 6, 3), 0.8, 0.8)
    p.setBrush(QtGui.QColor("#f2c14e"))
    p.drawRoundedRect(QtCore.QRectF(1, 7.5, 14, 10.5), 1.2, 1.2)
    p.setPen(QtGui.QPen(QtGui.QColor("#475569"), 0.9))
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawRoundedRect(QtCore.QRectF(9, 2, 10, 10), 1.2, 1.2)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#dc2626"))
    p.drawRoundedRect(QtCore.QRectF(9, 2, 10, 3), 1.2, 1.2)
    p.setBrush(QtGui.QColor("#64748b"))
    for r in range(2):
        for c in range(3):
            p.drawRect(QtCore.QRectF(10.6 + c * 2.7, 6.4 + r * 2.4, 1.6, 1.4))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QtGui.QIcon(pm)


# ---------------------------------------------------------------- 창
class _Sig(QtCore.QObject):
    planned = QtCore.Signal(int, list)
    progress = QtCore.Signal(int, int)
    moved = QtCore.Signal(list, list)


class DateFolderDialog(QtWidgets.QDialog):
    def __init__(self, parent, paths, base_dir, on_done=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(T("날짜별 폴더로 정리") + " — 4Dir")
        self.setWindowIcon(tool_icon(20))
        self.resize(820, 520)
        self.paths = [os.path.normpath(p) for p in paths if p and os.path.isfile(p)]
        self.base_dir = os.path.normpath(base_dir)
        self.on_done = on_done     # on_done() — 옮기거나 되돌린 뒤 4Dir 쪽 새로 읽기
        self.pairs, self.moved = [], None
        self._gen = 0
        self._cancel = False
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QLabel(T("고른 파일 {0}개를 날짜에 맞는 폴더로 옮깁니다.\n기준 폴더: {1}").format(len(self.paths), self.base_dir))
        top.setWordWrap(True)
        lay.addWidget(top)
        form = QtWidgets.QFormLayout()
        self.c_mode = QtWidgets.QComboBox()
        self.c_mode.addItems([T("수정한 날짜"), T("사진 찍은 날짜 (없으면 수정한 날짜)"), T("만든 날짜")])
        self.c_fmt = QtWidgets.QComboBox()
        d = datetime.date.today()
        for f in FORMATS:
            self.c_fmt.addItem(folder_for(d, f))
        form.addRow(T("어떤 날짜로"), self.c_mode)
        form.addRow(T("폴더 모양 (예)"), self.c_fmt)
        lay.addLayout(form)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([T("파일"), T("옮길 곳")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setColumnWidth(0, 300)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        self.prog = QtWidgets.QProgressBar()
        self.prog.setVisible(False)
        lay.addWidget(self.prog)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bot = QtWidgets.QHBoxLayout()
        self.btn_undo = QtWidgets.QPushButton(T("되돌리기 (원래 자리로)"))
        self.btn_undo.setVisible(False)
        self.btn_undo.clicked.connect(self.do_undo)
        bot.addWidget(self.btn_undo)
        bot.addStretch(1)
        self.btn_go = QtWidgets.QPushButton(T("옮기기"))
        self.btn_go.setStyleSheet("font-weight:bold;")
        self.btn_go.clicked.connect(self.go)
        close = QtWidgets.QPushButton(T("닫기"))
        close.clicked.connect(self.close)
        bot.addWidget(self.btn_go)
        bot.addWidget(close)
        lay.addLayout(bot)
        self.sig = _Sig()
        self.sig.planned.connect(self._on_planned)
        self.sig.progress.connect(lambda a, b: (self.prog.setRange(0, max(1, b)), self.prog.setValue(a)))
        self.sig.moved.connect(self._on_moved)
        self.c_mode.currentIndexChanged.connect(self.replan)
        self.c_fmt.currentIndexChanged.connect(self.replan)
        log.info("날짜 정리 창 열기 %d개 base=%s", len(self.paths), self.base_dir)
        self.replan()

    def _emit(self, sig, *a):
        try:
            sig.emit(*a)
        except RuntimeError:
            pass

    def replan(self, *_):
        self._gen += 1
        g = self._gen
        mode, fmt = MODES[self.c_mode.currentIndex()], FORMATS[self.c_fmt.currentIndex()]
        self.btn_go.setEnabled(False)
        self.status.setText(T("날짜 읽는 중…"))

        def work():
            try:
                res = plan(self.paths, self.base_dir, mode, fmt)
            except Exception:
                log.exception("계획 실패")
                res = []
            self._emit(self.sig.planned, g, res)
        threading.Thread(target=work, daemon=True, name="datefolders-plan").start()

    def _on_planned(self, g, pairs):
        if g != self._gen:
            return
        self.pairs = pairs
        self.table.setRowCount(len(pairs))
        for r, (src, dst) in enumerate(pairs):
            a = QtWidgets.QTableWidgetItem(os.path.basename(src))
            a.setToolTip(src)
            rel = os.path.relpath(dst, self.base_dir)
            b = QtWidgets.QTableWidgetItem(rel)
            b.setToolTip(dst)
            if os.path.basename(dst) != os.path.basename(src):
                b.setForeground(QtGui.QColor("#c26a00"))
                b.setToolTip(dst + "\n" + T("같은 이름이 있어 번호를 붙였습니다"))
            self.table.setItem(r, 0, a)
            self.table.setItem(r, 1, b)
        skip = len(self.paths) - len(pairs)
        txt = T("옮길 파일 {0}개").format(len(pairs))
        if skip:
            txt += "  ·  " + T("이미 제자리인 것 {0}개는 그대로 둠").format(skip)
        self.status.setText(txt)
        self.btn_go.setEnabled(bool(pairs) and self.moved is None)

    def go(self):
        if not self.pairs:
            return
        if QtWidgets.QMessageBox.question(self, self.windowTitle(),
                                          T("파일 {0}개를 표에 보이는 곳으로 옮길까요?\n(옮긴 뒤 [되돌리기] 로 원래 자리로 돌릴 수 있습니다)").format(len(self.pairs))) != QtWidgets.QMessageBox.Yes:
            return
        pairs = list(self.pairs)
        self.btn_go.setEnabled(False)
        self.c_mode.setEnabled(False)
        self.c_fmt.setEnabled(False)
        self.prog.setVisible(True)
        log.info("옮기기 누름 %d개", len(pairs))

        def work():
            try:
                done, fail = execute(pairs, lambda a, b: self._emit(self.sig.progress, a, b), lambda: self._cancel)
            except Exception:
                log.exception("옮기기 오류")
                done, fail = [], [("", "error")]
            self._emit(self.sig.moved, done, fail)
        threading.Thread(target=work, daemon=True, name="datefolders-move").start()

    def _on_moved(self, done, fail):
        self.prog.setVisible(False)
        self.moved = done
        txt = T("✔ {0}개 옮겼습니다").format(len(done))
        if fail:
            txt += "  ·  ⚠ " + T("{0}개는 옮기지 못했습니다 (사용 중이거나 권한 없음)").format(len(fail))
        self.status.setText(txt)
        self.btn_undo.setVisible(bool(done))
        self.btn_undo.setEnabled(bool(done))
        if self.on_done:
            self.on_done()

    def do_undo(self):
        if not self.moved:
            return
        if QtWidgets.QMessageBox.question(self, self.windowTitle(),
                                          T("방금 옮긴 {0}개를 원래 자리로 돌릴까요?").format(len(self.moved))) != QtWidgets.QMessageBox.Yes:
            return
        back, fail = undo(self.moved)
        self.moved = None
        self.btn_undo.setEnabled(False)
        txt = T("↶ {0}개를 원래 자리로 돌렸습니다").format(back)
        if fail:
            txt += "  ·  ⚠ " + T("{0}개는 돌리지 못했습니다").format(len(fail))
        self.status.setText(txt)
        self.c_mode.setEnabled(True)
        self.c_fmt.setEnabled(True)
        if self.on_done:
            self.on_done()
        self.replan()

    def closeEvent(self, ev):
        self._cancel = True
        self._gen += 1
        super().closeEvent(ev)


def open_dialog(parent, paths, base_dir, on_done=None):
    d = DateFolderDialog(parent, paths, base_dir, on_done)
    d.show()
    return d
