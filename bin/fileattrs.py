# -*- coding: utf-8 -*-
"""날짜·속성 일괄 바꾸기 (FILEATTRS_VER 1.0.0, 0.9.109 빌드 3 — 사용자 11/6 '추가 기능 전부', 경쟁 앱 조사 '날짜·속성 일괄')

- 고른 파일·폴더들의 수정한 날짜·만든 날짜·접근한 날짜를 한 번에 정함 (체크한 것만)
- 속성: 읽기 전용·숨김·시스템·보관 — 세 가지 상태 체크(✓ 켬 / 빈칸 끔 / ■ 그대로)
- 폴더면 '안의 파일·폴더까지' 선택 가능(기본 끔)
- 윈도우 함수로 직접 씀(SetFileTime·SetFileAttributes). 되돌리기는 없음 → 실행 전 몇 개를 바꾸는지 보여 주고 확인
로그: bin\\log\\4Dir.log [QE.attrs]
"""
import os
import time
import logging
import datetime

import pywintypes
import win32con
import win32file

from i18n import T
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt

FILEATTRS_VER = "1.0.0"
log = logging.getLogger("QE.attrs")
ATTRS = [("readonly", win32con.FILE_ATTRIBUTE_READONLY), ("hidden", win32con.FILE_ATTRIBUTE_HIDDEN),
         ("system", win32con.FILE_ATTRIBUTE_SYSTEM), ("archive", win32con.FILE_ATTRIBUTE_ARCHIVE)]


def expand(paths, recurse):
    out = []
    for p in paths:
        out.append(p)
        if recurse and os.path.isdir(p):
            for d, dirs, files in os.walk(p):
                out += [os.path.join(d, n) for n in dirs + files]
    return out


def apply(paths, times, attrs):
    """times = {'modified'|'created'|'accessed': epoch 초} · attrs = {이름: True/False} (없으면 그대로) → (성공 수, [오류])"""
    ok, errs = 0, []
    for p in paths:
        try:
            if attrs:
                cur = win32file.GetFileAttributesW(p)
                new = cur
                for name, bit in ATTRS:
                    if name in attrs:
                        new = (new | bit) if attrs[name] else (new & ~bit)
                if new != cur:
                    win32file.SetFileAttributesW(p, new or win32con.FILE_ATTRIBUTE_NORMAL)
            if times:
                ro = win32file.GetFileAttributesW(p) & win32con.FILE_ATTRIBUTE_READONLY
                if ro:   # 읽기 전용이면 날짜를 못 씀 → 잠깐 풀고 되돌림
                    win32file.SetFileAttributesW(p, win32file.GetFileAttributesW(p) & ~win32con.FILE_ATTRIBUTE_READONLY)
                try:
                    flags = win32con.FILE_FLAG_BACKUP_SEMANTICS   # 폴더도 열 수 있게
                    h = win32file.CreateFile(p, 0x100, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                                             None, win32con.OPEN_EXISTING, flags, None)
                    try:
                        conv = lambda k: pywintypes.Time(times[k]) if k in times else None
                        win32file.SetFileTime(h, conv("created"), conv("accessed"), conv("modified"), UTCTimes=False)
                    finally:
                        h.Close()
                finally:
                    if ro:
                        win32file.SetFileAttributesW(p, win32file.GetFileAttributesW(p) | win32con.FILE_ATTRIBUTE_READONLY)
            ok += 1
        except Exception as ex:
            errs.append(f"{p}: {ex}")
            log.warning("날짜·속성 실패 %s: %s", p, ex)
    log.info("날짜·속성 바꿈 %d/%d times=%s attrs=%s", ok, len(paths), {k: time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(v)) for k, v in times.items()}, attrs)
    return ok, errs


class AttrDialog(QtWidgets.QDialog):
    def __init__(self, paths, done_cb=None, parent=None):
        super().__init__(parent)
        self.paths = list(paths)
        self.done_cb = done_cb
        self.setWindowTitle(T("날짜·속성 바꾸기") + f" — {len(self.paths)}")
        lay = QtWidgets.QVBoxLayout(self)
        first = self.paths[0]
        try:
            st = os.stat(first)
            cur = {"modified": st.st_mtime, "created": st.st_ctime, "accessed": st.st_atime}
            a0 = win32file.GetFileAttributesW(first)
        except OSError:
            cur, a0 = {}, 0
        g = QtWidgets.QGroupBox(T("날짜 (체크한 것만 바꿈)"))
        gl = QtWidgets.QGridLayout(g)
        self.tchk, self.tedit = {}, {}
        for i, (k, lbl) in enumerate((("modified", T("수정한 날짜")), ("created", T("만든 날짜")), ("accessed", T("접근한 날짜")))):
            c = QtWidgets.QCheckBox(lbl)
            e = QtWidgets.QDateTimeEdit(QtCore.QDateTime.fromSecsSinceEpoch(int(cur.get(k, time.time()))))
            e.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            e.setCalendarPopup(True)
            e.setEnabled(False)
            c.toggled.connect(e.setEnabled)
            now = QtWidgets.QPushButton(T("지금"))
            now.clicked.connect(lambda _c=False, e=e, c=c: (c.setChecked(True), e.setDateTime(QtCore.QDateTime.currentDateTime())))
            gl.addWidget(c, i, 0)
            gl.addWidget(e, i, 1)
            gl.addWidget(now, i, 2)
            self.tchk[k], self.tedit[k] = c, e
        lay.addWidget(g)
        g2 = QtWidgets.QGroupBox(T("속성 (■ = 그대로)"))
        gl2 = QtWidgets.QHBoxLayout(g2)
        self.achk = {}
        many = len(self.paths) > 1
        for (name, bit), lbl in zip(ATTRS, (T("읽기 전용"), T("숨김"), T("시스템"), T("보관"))):
            c = QtWidgets.QCheckBox(lbl)
            c.setTristate(True)
            c.setCheckState(Qt.PartiallyChecked if many else (Qt.Checked if a0 & bit else Qt.Unchecked))
            self._a_init = getattr(self, "_a_init", {})
            self._a_init[name] = c.checkState()
            gl2.addWidget(c)
            self.achk[name] = c
        lay.addWidget(g2)
        self.recurse = QtWidgets.QCheckBox(T("폴더 안의 파일·폴더까지"))
        self.recurse.setVisible(any(os.path.isdir(p) for p in self.paths))
        lay.addWidget(self.recurse)
        self.info = QtWidgets.QLabel(T("대상: {0}").format(first if not many else T("{0} 외 {1}개").format(os.path.basename(first), len(self.paths) - 1)))
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText(T("바꾸기"))
        bb.accepted.connect(self.run)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        times = {k: self.tedit[k].dateTime().toSecsSinceEpoch() for k in self.tchk if self.tchk[k].isChecked()}
        attrs = {n: c.checkState() == Qt.Checked for n, c in self.achk.items()
                 if c.checkState() != Qt.PartiallyChecked and c.checkState() != self._a_init[n]}
        return times, attrs

    def run(self):
        times, attrs = self.values()
        if not times and not attrs:
            self.reject()
            return
        targets = expand(self.paths, self.recurse.isChecked())
        if len(targets) > len(self.paths) and QtWidgets.QMessageBox.question(
                self, T("날짜·속성 바꾸기"), T("안쪽까지 {0}개를 바꿉니다. 계속할까요?").format(len(targets))) != QtWidgets.QMessageBox.Yes:
            return
        ok, errs = apply(targets, times, attrs)
        if errs:
            QtWidgets.QMessageBox.warning(self, T("날짜·속성 바꾸기"), T("{0}개 바꿈, 실패 {1}개").format(ok, len(errs)) + "\n\n" + "\n".join(errs[:20]))
        if self.done_cb:
            self.done_cb(ok)
        self.accept()
