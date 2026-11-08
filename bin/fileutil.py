# -*- coding: utf-8 -*-
"""작은 파일 작업 모음 (FILEUTIL_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '링크 만들기·경로 복사 형식·폴더 구조만 복사·파일 나누기/합치기')

- 링크 만들기 make_link(parent, targets, dest_dir) 창: [바로 가기(.lnk)] [심볼릭 링크] [정션(폴더만)] [하드 링크(파일만, 같은 드라이브만)]
  · 바로 가기 = WScript.Shell(win32com) · 심볼릭 = CreateSymbolicLinkW + 권한 없이 만들기(0x2) — 실패하면 개발자 모드/관리자 안내
  · 정션 = _winapi.CreateJunction (안 되면 cmd /c mklink /J 를 창 없이) · 하드 링크 = os.link
  · 같은 이름이 있으면 '이름 (1)' — 원본은 절대 덮어쓰지 않음. 창 없이 쓰려면 create_link(kind, target, dest_dir)
- 경로 복사 형식 path_formats(paths) → [(이름, 글자)] : 그대로 · 따옴표 · 앞으로 빗금 · 빗금 두 번 · 파이썬 r"" · WSL · 파일 주소 · 이름만 · 폴더만
  여러 개면 줄바꿈으로 이음 (메뉴는 주 작업자가 붙임)
- 폴더 구조만 복사 copy_tree_only(src, dst_parent, cb=None, cancel=None) → 만든 폴더 수 (파일 없이, 이미 있으면 '이름 (1)')
  뒤 스레드용 순수 함수. 링크·정션 폴더는 따라가지 않음(끝없이 도는 것 방지)
- 파일 나누기 split_file(path, part_bytes, cb, cancel) → '이름.001' '.002'… + '이름.sfv'(조각별 CRC32 · 원래 이름·크기)
  합치기 join_files(first_part_path, cb, cancel) → .001 부터 이어 붙여 원래 이름으로(있으면 (1)), sfv 가 있으면 CRC 확인 결과
  창 open_split(parent, path) (10MB/25MB(메일)/100MB/700MB(CD)/4GB(USB FAT32)/직접 입력) · open_join(parent, path) — 진행·취소
  취소하면 만들던 조각·합친 파일은 지움(새로 만든 것만)
로그: bin\\log\\4Dir.log [QE.fileutil]
"""
import os
import re
import time
import zlib
import ctypes
import logging
import threading
import subprocess
import urllib.parse

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

FILEUTIL_VER = "1.0.0"
log = logging.getLogger("QE.fileutil")
CHUNK = 4 * 1048576
CREATE_NO_WINDOW = 0x08000000
SYMLINK_PRIV_MSG = "심볼릭 링크를 만들 권한이 없습니다. 윈도우 설정 > 개발자 모드를 켜거나 관리자 권한으로 실행하세요"


def unique_path(path):
    """있으면 '이름 (1).확장자', '이름 (2)…'"""
    if not os.path.lexists(path):
        return path
    d, nm = os.path.split(path)
    stem, ext = os.path.splitext(nm)
    if os.path.isdir(path) and not os.path.islink(path):
        stem, ext = nm, ""
    i = 1
    while True:
        p = os.path.join(d, f"{stem} ({i}){ext}")
        if not os.path.lexists(p):
            return p
        i += 1


# ====================================================================== a. 링크 만들기
KINDS = ["lnk", "symlink", "junction", "hardlink"]
KIND_NAMES = {"lnk": "바로 가기 (.lnk)", "symlink": "심볼릭 링크", "junction": "정션 (폴더만)", "hardlink": "하드 링크 (파일만, 같은 드라이브만)"}


def can_link(kind, target, dest_dir):
    """만들 수 없으면 이유 글자, 되면 None"""
    isdir = os.path.isdir(target)
    if not os.path.exists(target):
        return T("대상이 없습니다")
    if kind == "junction" and not isdir:
        return T("정션은 폴더만 됩니다")
    if kind == "hardlink":
        if isdir:
            return T("하드 링크는 파일만 됩니다")
        if os.path.splitdrive(os.path.abspath(target))[0].lower() != os.path.splitdrive(os.path.abspath(dest_dir))[0].lower():
            return T("하드 링크는 같은 드라이브 안에서만 됩니다")
    return None


def link_name(kind, target, dest_dir):
    nm = os.path.basename(os.path.normpath(target)) or os.path.splitdrive(target)[0].rstrip(":")
    if kind == "lnk":
        nm += ".lnk"
    return unique_path(os.path.join(dest_dir, nm))


def _create_symlink(dst, target, isdir):
    """CreateSymbolicLinkW (+ 권한 없이 만들기 0x2) → 0 성공, 아니면 윈도우 오류 번호"""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateSymbolicLinkW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    k.CreateSymbolicLinkW.restype = ctypes.c_ubyte
    if k.CreateSymbolicLinkW(dst, target, (1 if isdir else 0) | 0x2):
        return 0
    return ctypes.get_last_error() or -1


def create_link(kind, target, dest_dir):
    """→ (성공, 만든 경로 또는 오류 글자)"""
    target = os.path.normpath(target)
    why = can_link(kind, target, dest_dir)
    if why:
        log.info("링크 못 만듦 %s %s: %s", kind, target, why)
        return False, why
    dst = link_name(kind, target, dest_dir)
    isdir = os.path.isdir(target)
    try:
        if kind == "lnk":
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            try:
                sh = win32com.client.Dispatch("WScript.Shell")
                sc = sh.CreateShortcut(dst)
                sc.TargetPath = target
                sc.WorkingDirectory = target if isdir else os.path.dirname(target)
                sc.Save()
            finally:
                pythoncom.CoUninitialize()
        elif kind == "symlink":
            err = _create_symlink(dst, target, isdir)
            if err:
                log.warning("심볼릭 링크 실패 %s → %s 오류 %d", dst, target, err)
                if err in (1314, 5):     # 권한 없음
                    return False, T(SYMLINK_PRIV_MSG)
                return False, T("만들지 못했습니다 (오류 {0})").format(err)
        elif kind == "junction":
            try:
                import _winapi
                _winapi.CreateJunction(target, dst)
            except (ImportError, AttributeError, OSError) as e:
                log.info("CreateJunction 실패(%s) → mklink /J 로", e)
                cp = subprocess.run(["cmd", "/c", "mklink", "/J", dst, target], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, creationflags=CREATE_NO_WINDOW)
                if cp.returncode != 0 or not os.path.isdir(dst):
                    return False, T("만들지 못했습니다 (오류 {0})").format(cp.returncode)
        elif kind == "hardlink":
            os.link(target, dst)
        else:
            return False, "kind?"
    except Exception as e:
        log.exception("링크 만들기 실패 %s %s → %s", kind, target, dst)
        return False, T("만들지 못했습니다: {0}").format(e)
    log.info("링크 만듦 %s: %s → %s", kind, dst, target)
    return True, dst


class LinkDialog(QtWidgets.QDialog):
    def __init__(self, parent, targets, dest_dir):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowIcon(link_icon(32))
        self.targets = [targets] if isinstance(targets, str) else list(targets)
        self.dest_dir = dest_dir
        self.created = []
        self.setWindowTitle(T("링크 만들기"))
        self.resize(560, 360)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(T("대상 {0}개 → 만들 곳: {1}").format(len(self.targets), dest_dir)))
        lst = QtWidgets.QListWidget()
        lst.addItems(self.targets)
        lst.setMaximumHeight(90)
        lay.addWidget(lst)
        box = QtWidgets.QGroupBox(T("종류"))
        bl = QtWidgets.QVBoxLayout(box)
        self.radios = {}
        for k in KINDS:
            r = QtWidgets.QRadioButton(T(KIND_NAMES[k]))
            self.radios[k] = r
            bl.addWidget(r)
            r.toggled.connect(self._update)
        lay.addWidget(box)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info, 1)
        bb = QtWidgets.QDialogButtonBox()
        self.b_ok = bb.addButton(T("만들기"), QtWidgets.QDialogButtonBox.AcceptRole)
        bb.addButton(T("닫기"), QtWidgets.QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.run)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.radios["lnk"].setChecked(True)

    def kind(self):
        return next(k for k, r in self.radios.items() if r.isChecked())

    def _update(self):
        k = self.kind()
        bad = [(t, can_link(k, t, self.dest_dir)) for t in self.targets]
        bad = [(t, w) for t, w in bad if w]
        if bad:
            self.info.setText(T("만들 수 없는 항목 {0}개: {1}").format(len(bad), bad[0][1]))
        else:
            self.info.setText(T("만들 이름: {0}").format(os.path.basename(link_name(k, self.targets[0], self.dest_dir))))
        self.b_ok.setEnabled(len(bad) < len(self.targets))

    def run(self):
        k = self.kind()
        ok, msgs = 0, []
        for t in self.targets:
            s, r = create_link(k, t, self.dest_dir)
            if s:
                ok += 1
                self.created.append(r)
            else:
                msgs.append(f"{os.path.basename(t)}: {r}")
        txt = T("{0}개 만들었습니다").format(ok)
        if msgs:
            txt += "\n" + "\n".join(msgs[:8])
        self.info.setText(txt)
        if not msgs:
            QtCore.QTimer.singleShot(600, self.accept)


def make_link(parent, targets, dest_dir):
    d = LinkDialog(parent, targets, dest_dir)
    d.show()
    return d


# ====================================================================== b. 경로 복사 형식
def _file_url(p):
    p = os.path.abspath(p)
    if p.startswith("\\\\"):
        return "file:" + urllib.parse.quote(p.replace("\\", "/"), safe="/:")
    return "file:///" + urllib.parse.quote(p.replace("\\", "/"), safe="/:")


def _wsl(p):
    p = os.path.abspath(p)
    drv, rest = os.path.splitdrive(p)
    if len(drv) == 2 and drv[1] == ":":
        return "/mnt/" + drv[0].lower() + rest.replace("\\", "/")
    return p.replace("\\", "/")


def _py(p):
    if p.endswith("\\") or '"' in p:
        return '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return 'r"' + p + '"'


def path_formats(paths):
    """→ [(이름, 글자)] — 여러 개면 줄바꿈으로 이음"""
    if isinstance(paths, str):
        paths = [paths]
    ps = [os.path.normpath(p) if not re.match(r"^[A-Za-z]:\\?$", p) else p[:2] + "\\" for p in paths]
    fm = [
        (T("그대로"), lambda p: p),
        (T("따옴표"), lambda p: f'"{p}"'),
        (T("앞으로 빗금"), lambda p: p.replace("\\", "/")),
        (T("빗금 두 번"), lambda p: p.replace("\\", "\\\\")),
        (T("파이썬"), _py),
        ("WSL", _wsl),
        (T("파일 주소"), _file_url),
        (T("이름만"), lambda p: os.path.basename(p.rstrip("\\")) or p),
        (T("폴더만"), lambda p: os.path.dirname(p.rstrip("\\")) or p),
    ]
    return [(nm, "\n".join(f(p) for p in ps)) for nm, f in fm]


# ====================================================================== c. 폴더 구조만 복사
def copy_tree_only(src, dst_parent, cb=None, cancel=None):
    """src 이름의 폴더를 dst_parent 에 만들고 하위 폴더만 똑같이 → 만든 폴더 수. cancel() 이 참이면 멈춤"""
    src = os.path.normpath(src)
    top = unique_path(os.path.join(dst_parent, os.path.basename(src)))
    cancel = cancel or (lambda: False)
    t0 = time.perf_counter()
    n = 0
    os.makedirs(top)
    n += 1
    stack = [(src, top)]
    while stack:
        if cancel():
            log.info("구조만 복사 취소 %s (%d개 만듦)", src, n)
            break
        s, d = stack.pop()
        try:
            it = list(os.scandir(s))
        except OSError as e:
            log.warning("폴더 못 읽음 %s: %s", s, e)
            continue
        for e in it:
            try:
                if not e.is_dir(follow_symlinks=False) or e.is_junction():
                    continue
            except OSError:
                continue
            nd = os.path.join(d, e.name)
            try:
                os.makedirs(nd, exist_ok=True)
            except OSError as ex:
                log.warning("폴더 못 만듦 %s: %s", nd, ex)
                continue
            n += 1
            if cb:
                cb(n, e.path)
            stack.append((e.path, nd))
    log.info("구조만 복사 %s → %s 폴더 %d개 %.0fms", src, top, n, (time.perf_counter() - t0) * 1000)
    return n


# ====================================================================== d. 나누기·합치기
def _part_name(base, i):
    return f"{base}.{i:03d}"


def split_file(path, part_bytes, cb=None, cancel=None):
    """→ dict(parts=[조각 경로], sfv=경로, size, stopped). cb(한 바이트 수, 전체)"""
    cancel = cancel or (lambda: False)
    size = os.path.getsize(path)
    part_bytes = max(1, int(part_bytes))
    nparts = max(1, (size + part_bytes - 1) // part_bytes)
    d, nm = os.path.split(path)
    base = os.path.join(d, nm)
    k = 0
    while os.path.lexists(_part_name(base, 1)) or os.path.lexists(base + ".sfv"):   # 이미 있으면 '이름 (1)'
        k += 1
        st, ext = os.path.splitext(nm)
        base = os.path.join(d, f"{st} ({k}){ext}")
    log.info("나누기 %s 크기 %d 조각 %d바이트 → %d개 (%s.001…)", path, size, part_bytes, nparts, base)
    parts, crcs, done = [], [], 0
    try:
        with open(path, "rb") as f:
            for i in range(1, nparts + 1):
                pp = _part_name(base, i)
                crc, left = 0, part_bytes
                with open(pp, "xb") as o:
                    parts.append(pp)
                    while left > 0:
                        if cancel():
                            raise InterruptedError
                        b = f.read(min(CHUNK, left))
                        if not b:
                            break
                        o.write(b)
                        crc = zlib.crc32(b, crc)
                        left -= len(b)
                        done += len(b)
                        if cb:
                            cb(done, size)
                crcs.append(crc)
        sfv = base + ".sfv"
        with open(sfv, "x", encoding="utf-8", newline="\r\n") as s:
            s.write("; 4Dir split\n")
            s.write(f"; original={nm}\n; size={size}\n; parts={nparts}\n")
            for pp, c in zip(parts, crcs):
                s.write(f"{os.path.basename(pp)} {c:08X}\n")
    except InterruptedError:
        log.info("나누기 취소 → 만든 조각 %d개 지움", len(parts))
        for pp in parts:
            try:
                os.remove(pp)
            except OSError:
                pass
        return dict(parts=[], sfv=None, size=size, stopped=True)
    log.info("나누기 끝 %d개 + %s", len(parts), sfv)
    return dict(parts=parts, sfv=sfv, size=size, stopped=False)


def read_sfv(path):
    """→ (원래 이름|None, 크기|None, {조각 이름 소문자: CRC})"""
    orig, size, crcs = None, None, {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith(";"):
                m = re.match(r";\s*original=(.+)$", line)
                if m:
                    orig = m.group(1).strip()
                m = re.match(r";\s*size=(\d+)", line)
                if m:
                    size = int(m.group(1))
                continue
            m = re.match(r"(.+?)\s+([0-9A-Fa-f]{8})$", line)
            if m:
                crcs[m.group(1).strip().lower()] = int(m.group(2), 16)
    return orig, size, crcs


def part_base(first):
    """'이름.001' → '이름' (아니면 None)"""
    m = re.match(r"^(.*)\.(\d{3})$", first)
    return m.group(1) if m else None


def join_files(first_part_path, cb=None, cancel=None):
    """→ dict(path=만든 파일, parts=조각 수, size, crc_ok=True|False|None(sfv 없음), bad=[CRC 다른 조각], stopped)"""
    cancel = cancel or (lambda: False)
    base = part_base(first_part_path)
    if base is None:
        raise ValueError(T("'.001' 로 끝나는 첫 조각을 고르세요"))
    first = _part_name(base, 1)
    parts, i = [], 1
    while os.path.isfile(_part_name(base, i)):
        parts.append(_part_name(base, i))
        i += 1
    if not parts:
        raise FileNotFoundError(first)
    sfv = base + ".sfv"
    orig, osize, crcs = (None, None, {})
    if os.path.isfile(sfv):
        try:
            orig, osize, crcs = read_sfv(sfv)
        except OSError as e:
            log.warning("sfv 읽기 실패 %s: %s", sfv, e)
    d = os.path.dirname(first)
    out = unique_path(os.path.join(d, orig or os.path.basename(base)))
    total = sum(os.path.getsize(p) for p in parts)
    log.info("합치기 %s 조각 %d개 %d바이트 → %s (sfv %s)", first, len(parts), total, out, bool(crcs))
    bad, done = [], 0
    try:
        with open(out, "xb") as o:
            for pp in parts:
                crc = 0
                with open(pp, "rb") as f:
                    while True:
                        if cancel():
                            raise InterruptedError
                        b = f.read(CHUNK)
                        if not b:
                            break
                        o.write(b)
                        crc = zlib.crc32(b, crc)
                        done += len(b)
                        if cb:
                            cb(done, total)
                want = crcs.get(os.path.basename(pp).lower())
                if want is not None and want != crc:
                    bad.append(os.path.basename(pp))
    except InterruptedError:
        log.info("합치기 취소 → %s 지움", out)
        try:
            os.remove(out)
        except OSError:
            pass
        return dict(path=None, parts=len(parts), size=done, crc_ok=None, bad=[], stopped=True)
    crc_ok = None
    if crcs:
        crc_ok = not bad and len(crcs) == len(parts) and (osize is None or osize == total)
    log.info("합치기 끝 %s %d바이트 CRC확인=%s 틀린 조각=%s", out, total, crc_ok, bad)
    return dict(path=out, parts=len(parts), size=total, crc_ok=crc_ok, bad=bad, stopped=False)


class _Bridge(QtCore.QObject):
    progress = QtCore.Signal(object, object)
    done = QtCore.Signal(object)


class _WorkDialog(QtWidgets.QDialog):
    """나누기·합치기 공통: 진행 막대 + 취소, 뒤 스레드"""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowIcon(split_icon(32))
        self.setWindowTitle(title)
        self._cancel = False
        self._th = None
        self.result = None
        self.lay = QtWidgets.QVBoxLayout(self)
        self.top = QtWidgets.QFormLayout()
        self.lay.addLayout(self.top)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.lay.addWidget(self.bar)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        self.lay.addWidget(self.info)
        bb = QtWidgets.QHBoxLayout()
        bb.addStretch(1)
        self.b_go = QtWidgets.QPushButton(T("시작"))
        self.b_cancel = QtWidgets.QPushButton(T("닫기"))
        bb.addWidget(self.b_go)
        bb.addWidget(self.b_cancel)
        self.lay.addLayout(bb)
        self.br = _Bridge()
        self.br.progress.connect(self._prog)
        self.br.done.connect(self._done)
        self.b_go.clicked.connect(self.start)
        self.b_cancel.clicked.connect(self._cancel_or_close)

    def _cancel_or_close(self):
        if self._th is not None:
            self._cancel = True
        else:
            self.close()

    def _prog(self, a, b):
        self.bar.setValue(int(a * 1000 / max(1, b)))
        self.info.setText(T("{0:,} / {1:,} MB").format(a // 1048576, b // 1048576))

    def work(self, cb, cancel):
        raise NotImplementedError

    def start(self):
        if self._th is not None:
            return
        self._cancel = False
        self.b_go.setEnabled(False)
        self.b_cancel.setText(T("취소"))
        br = self.br
        last = [0.0]

        def cb(a, b):
            now = time.perf_counter()
            if now - last[0] > 0.05 or a >= b:
                last[0] = now
                br.progress.emit(a, b)

        def run():
            try:
                r = self.work(cb, lambda: self._cancel)
            except Exception as e:
                log.exception("작업 실패")
                r = dict(error=str(e))
            br.done.emit(r)
        self._th = threading.Thread(target=run, name="fileutil", daemon=True)
        self._th.start()

    def _done(self, r):
        self._th = None
        self.result = r
        self.b_cancel.setText(T("닫기"))
        self.b_go.setEnabled(True)
        self.show_result(r)

    def show_result(self, r):
        pass

    def closeEvent(self, ev):
        self._cancel = True
        if self._th is not None:
            self._th.join(3.0)
        try:
            self.br.progress.disconnect()
            self.br.done.disconnect()
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(ev)


SPLIT_SIZES = [("10 MB", 10 * 1048576), ("25 MB (" + "메일" + ")", 25 * 1048576), ("100 MB", 100 * 1048576),
               ("700 MB (CD)", 700 * 1048576), ("4 GB (USB FAT32)", 4095 * 1048576)]


class SplitDialog(_WorkDialog):
    def __init__(self, parent, path):
        super().__init__(parent, T("파일 나누기") + f" — {os.path.basename(path)}")
        self.path = path
        self.size = os.path.getsize(path)
        self.top.addRow(T("파일"), QtWidgets.QLabel(f"{os.path.basename(path)}  ({self.size:,} " + T("바이트") + ")"))
        self.combo = QtWidgets.QComboBox()
        for nm, v in SPLIT_SIZES:
            self.combo.addItem(nm.replace("메일", T("메일")), v)
        self.combo.addItem(T("직접 입력"), 0)
        self.combo.setCurrentIndex(1)
        self.custom = QtWidgets.QSpinBox()
        self.custom.setRange(1, 1024 * 1024)
        self.custom.setValue(50)
        self.custom.setSuffix(" MB")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.combo)
        row.addWidget(self.custom)
        self.top.addRow(T("조각 크기"), row)
        self.count = QtWidgets.QLabel()
        self.top.addRow("", self.count)
        self.combo.currentIndexChanged.connect(self._upd)
        self.custom.valueChanged.connect(self._upd)
        self.resize(460, 220)
        self._upd()

    def part_bytes(self):
        v = self.combo.currentData()
        return v if v else self.custom.value() * 1048576

    def _upd(self):
        self.custom.setEnabled(not self.combo.currentData())
        n = max(1, (self.size + self.part_bytes() - 1) // self.part_bytes())
        self.count.setText(T("조각 {0:,}개 + 확인용 .sfv 파일").format(n))

    def work(self, cb, cancel):
        return split_file(self.path, self.part_bytes(), cb, cancel)

    def show_result(self, r):
        if r.get("error"):
            self.info.setText(T("실패: {0}").format(r["error"]))
        elif r["stopped"]:
            self.info.setText(T("취소됨 — 만들던 조각은 지웠습니다"))
            self.bar.setValue(0)
        else:
            self.bar.setValue(1000)
            self.info.setText(T("조각 {0}개를 만들었습니다: {1}").format(len(r["parts"]), os.path.basename(r["parts"][0]) + " …"))


class JoinDialog(_WorkDialog):
    def __init__(self, parent, path):
        super().__init__(parent, T("파일 합치기") + f" — {os.path.basename(path)}")
        self.path = path
        base = part_base(path)
        n = 0
        if base:
            while os.path.isfile(_part_name(base, n + 1)):
                n += 1
        self.top.addRow(T("첫 조각"), QtWidgets.QLabel(os.path.basename(path)))
        self.top.addRow(T("조각 수"), QtWidgets.QLabel(f"{n:,}"))
        self.top.addRow(T("확인용"), QtWidgets.QLabel(T("있음 (.sfv) — 합친 뒤 확인") if base and os.path.isfile(base + ".sfv") else T("없음")))
        if not n:
            self.b_go.setEnabled(False)
            self.info.setText(T("'.001' 로 끝나는 첫 조각을 고르세요"))
        self.resize(460, 220)

    def work(self, cb, cancel):
        return join_files(self.path, cb, cancel)

    def show_result(self, r):
        if r.get("error"):
            self.info.setText(T("실패: {0}").format(r["error"]))
        elif r["stopped"]:
            self.info.setText(T("취소됨 — 합치던 파일은 지웠습니다"))
            self.bar.setValue(0)
        else:
            self.bar.setValue(1000)
            s = T("합쳤습니다: {0}").format(os.path.basename(r["path"]))
            if r["crc_ok"] is True:
                s += " · " + T("확인 결과 원본과 같습니다")
            elif r["crc_ok"] is False:
                s += " · " + T("확인 결과 다릅니다! 깨진 조각: {0}").format(", ".join(r["bad"]) or "?")
            self.info.setText(s)


def open_split(parent, path):
    d = SplitDialog(parent, path)
    d.show()
    return d


def open_join(parent, path):
    d = JoinDialog(parent, path)
    d.show()
    return d


# ====================================================================== 아이콘
def link_icon(sz=16):
    """사슬 고리 두 개"""
    def draw(p):
        p.setBrush(Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QColor("#1d6fd6"), 2.2))
        p.save()
        p.translate(10, 10)
        p.rotate(-45)
        p.drawRoundedRect(QtCore.QRectF(-8.5, -3, 9.5, 6), 3, 3)
        p.setPen(QtGui.QPen(QtGui.QColor("#3fae68"), 2.2))
        p.drawRoundedRect(QtCore.QRectF(-1, -3, 9.5, 6), 3, 3)
        p.restore()
    return _icon(sz, draw)


def split_icon(sz=16):
    """파일이 두 조각으로 갈라짐"""
    def draw(p):
        p.setPen(QtGui.QPen(QtGui.QColor("#6b7280"), 1.0))
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawRect(QtCore.QRectF(2.5, 2.5, 7, 15))
        p.setBrush(QtGui.QColor("#e8f0fe"))
        p.drawRect(QtCore.QRectF(11.5, 2.5, 7, 15))
        p.setPen(QtGui.QPen(QtGui.QColor("#e5484d"), 1.4, Qt.DashLine))
        p.drawLine(QtCore.QPointF(10.5, 1), QtCore.QPointF(10.5, 19))
        p.setPen(QtGui.QPen(QtGui.QColor("#9ca3af"), 1.2))
        for y in (6, 9, 12):
            p.drawLine(QtCore.QPointF(4, y), QtCore.QPointF(8, y))
            p.drawLine(QtCore.QPointF(13, y), QtCore.QPointF(17, y))
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
