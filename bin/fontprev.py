# -*- coding: utf-8 -*-
"""글꼴 미리보기 (FONTPREV_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '미리보기 창에서 형식별로 보기: 글꼴')

- 미리보기 창에 끼우는 위젯: can_handle(path) (.ttf .otf .ttc .otc, 확장자만) · make_widget(path, parent) -> QWidget|None
- 글꼴 파일을 뒤 스레드에서 읽고(글꼴 이름표·글자 모양 수는 파일에서 직접 읽음 — name·maxp 표), 화면 쪽에서
  QFontDatabase.addApplicationFontFromData 로 이 4Dir 안에만 잠깐 올림 (윈도우에 설치하지 않음)
- 견본: 한글 '다람쥐 헌 쳇바퀴에 타고파' · 영문 pangram · 숫자·기호 — 크기 12/18/24/36/60. 견본 문장 직접 입력 칸
- 묶음 글꼴(.ttc)은 글꼴 고르기 칸. 80MB 넘는 파일은 안 읽음
- 위젯이 지워지면 removeApplicationFont (올린 글꼴을 내림), 파일은 읽을 때만 열고 바로 닫음
로그: bin\\log\\4Dir.log [QE.fontprev]
"""
import os
import time
import struct
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

FONTPREV_VER = "1.0.0"
log = logging.getLogger("QE.fontprev")
EXTS = {".ttf", ".otf", ".ttc", ".otc"}
MAX_BYTES = 80 * 1048576
SIZES = (12, 18, 24, 36, 60)
SAMPLE = "다람쥐 헌 쳇바퀴에 타고파\nThe quick brown fox jumps over the lazy dog\n0123456789 !@#$%^&*()_+-=[]{};:'\",.<>/?"



def _narrow(lab):
    """줄 바꿈 글자표: 폭은 창에 맞춰 줄고 늘되, 높이는 글 길이에 맞게 (heightForWidth 유지)"""
    sp = lab.sizePolicy()
    sp.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
    lab.setSizePolicy(sp)
    lab.setMinimumWidth(1)

def can_handle(path):
    return os.path.splitext(path or "")[1].lower() in EXTS


# ---------------------------------------------------------------- 파일에서 이름표 읽기
def _face_info(b, off):
    """sfnt 한 개(off 위치) → dict(family, style, full, version, glyphs)"""
    num = struct.unpack_from(">H", b, off + 4)[0]
    tables = {}
    for i in range(num):
        tag, _, toff, tlen = struct.unpack_from(">4sIII", b, off + 12 + i * 16)
        tables[tag] = (toff, tlen)
    out = {"glyphs": 0, "names": {}}
    if b"maxp" in tables:
        out["glyphs"] = struct.unpack_from(">H", b, tables[b"maxp"][0] + 4)[0]
    if b"name" in tables:
        noff = tables[b"name"][0]
        _, cnt, soff = struct.unpack_from(">HHH", b, noff)
        best = {}   # nameID → (점수, 글자)
        for i in range(cnt):
            pid, eid, lid, nid, ln, so = struct.unpack_from(">HHHHHH", b, noff + 6 + i * 12)
            if nid not in (1, 2, 4, 5, 16, 17):
                continue
            raw = b[noff + soff + so: noff + soff + so + ln]
            if pid == 3 or pid == 0:
                s = raw.decode("utf-16-be", "replace")
                score = {0x412: 3, 0x409: 2}.get(lid, 1) if pid == 3 else 1
            elif pid == 1 and lid == 0:
                s = raw.decode("mac_roman", "replace")
                score = 0
            else:
                continue
            if nid not in best or score > best[nid][0]:
                best[nid] = (score, s)
        out["names"] = {k: v[1] for k, v in best.items()}
    n = out["names"]
    out["family"] = n.get(16) or n.get(1) or ""
    out["style"] = n.get(17) or n.get(2) or ""
    out["full"] = n.get(4) or ""
    out["version"] = n.get(5) or ""
    return out


def read_font_info(path):
    """글꼴 파일 → dict(data=bytes, faces=[...], size)"""
    t0 = time.time()
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise ValueError(T("파일이 너무 큼 ({0}MB 넘음)").format(MAX_BYTES // 1048576))
    with open(path, "rb") as f:
        b = f.read()
    faces = []
    try:
        if b[:4] == b"ttcf":
            n = struct.unpack_from(">I", b, 8)[0]
            for i in range(min(n, 64)):
                faces.append(_face_info(b, struct.unpack_from(">I", b, 12 + i * 4)[0]))
        elif b[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            faces.append(_face_info(b, 0))
        else:
            raise ValueError(T("글꼴 파일이 아님"))
    except struct.error:
        raise ValueError(T("글꼴 파일이 깨짐"))
    log.info("글꼴 읽음 %s %d바이트 얼굴 %d개 %.0fms", path, size, len(faces), (time.time() - t0) * 1000)
    return {"data": b, "faces": faces, "size": size}


def _remove_font(fid):
    ok = QtGui.QFontDatabase.removeApplicationFont(fid)
    log.info("글꼴 내림 id=%d (%s)", fid, ok)


class _Bridge(QtCore.QObject):
    done = QtCore.Signal(object)


class FontView(QtWidgets.QWidget):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.fid = -1
        self.families = []
        self.faces = []
        self.cancel = threading.Event()
        self.destroyed.connect(self.cancel.set)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        self.setMinimumWidth(150)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.info = QtWidgets.QLabel(T("읽는 중…"))
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        _narrow(self.info)
        lay.addWidget(self.info)
        self.pick = QtWidgets.QComboBox()
        self.pick.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.pick.setMinimumContentsLength(8)
        self.pick.hide()
        self.pick.currentIndexChanged.connect(self._draw)
        lay.addWidget(self.pick)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText(T("견본 문장 직접 입력"))
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self._draw)
        lay.addWidget(self.edit)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QtWidgets.QWidget()
        self.blay = QtWidgets.QVBoxLayout(body)
        self.blay.setContentsMargins(2, 2, 2, 2)
        self.blay.setSpacing(2)
        self.samples = []
        for sz in SIZES:
            cap = QtWidgets.QLabel("%d px" % sz)
            f = cap.font()
            f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
            cap.setFont(f)
            cap.setForegroundRole(QtGui.QPalette.PlaceholderText)
            lab = QtWidgets.QLabel()
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            _narrow(lab)
            self.blay.addWidget(cap)
            self.blay.addWidget(lab)
            self.samples.append((sz, lab))
        self.blay.addStretch(1)
        self.scroll.setWidget(body)
        lay.addWidget(self.scroll, 1)
        log.info("열기 %s", path)
        br = _Bridge(self)
        br.done.connect(self._on_info)
        cancel = self.cancel

        def work():
            try:
                r = read_font_info(path)
            except Exception as ex:
                log.info("글꼴 읽기 실패 %s: %s", path, ex)
                r = ex
            if cancel.is_set():
                return
            try:
                br.done.emit(r)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True, name="fontprev").start()

    def _on_info(self, r):
        if isinstance(r, Exception):
            self.info.setText(T("글꼴을 볼 수 없음: {0}").format(r))
            return
        t0 = time.time()
        self.fid = QtGui.QFontDatabase.addApplicationFontFromData(QtCore.QByteArray(r["data"]))
        r["data"] = None
        if self.fid < 0:
            self.info.setText(T("글꼴을 볼 수 없음: {0}").format(T("올리기 실패")))
            log.info("addApplicationFontFromData 실패 %s", self.path)
            return
        self.destroyed.connect(lambda *_a, fid=self.fid: _remove_font(fid))
        self.families = QtGui.QFontDatabase.applicationFontFamilies(self.fid)
        self.faces = r["faces"]
        self.size = r["size"]
        log.info("글꼴 올림 id=%d 이름=%s %.0fms", self.fid, self.families, (time.time() - t0) * 1000)
        if len(self.faces) > 1:
            self.pick.blockSignals(True)
            for i, fc in enumerate(self.faces):
                self.pick.addItem(" ".join(x for x in (fc["family"], fc["style"]) if x) or str(i + 1))
            self.pick.blockSignals(False)
            self.pick.show()
        self._draw()

    def current_face(self):
        i = max(0, self.pick.currentIndex())
        return self.faces[i] if i < len(self.faces) else {"family": "", "style": "", "glyphs": 0, "version": ""}

    def qfont(self, px):
        fc = self.current_face()
        fam = fc["family"] if fc["family"] in self.families else (self.families[0] if self.families else fc["family"])
        f = QtGui.QFontDatabase.font(fam, fc["style"], 12) if fc["style"] in QtGui.QFontDatabase.styles(fam) else QtGui.QFont(fam)
        f.setPixelSize(px)
        return f

    def _draw(self, *_):
        if self.fid < 0:
            return
        fc = self.current_face()
        fam = fc["family"] or (self.families[0] if self.families else "")
        styles = QtGui.QFontDatabase.styles(fam) if fam else []
        lines = [T("이름: {0}").format(fam),
                 T("스타일: {0}").format(fc["style"] or ", ".join(styles)),
                 T("글자 모양 수: {0:,}").format(fc["glyphs"])]
        if len(self.faces) > 1:
            lines.append(T("묶음 글꼴: {0}개").format(len(self.faces)))
        if fc.get("version"):
            lines.append(fc["version"])
        self.info.setText("\n".join(lines))
        text = self.edit.text() or SAMPLE
        for px, lab in self.samples:
            lab.setFont(self.qfont(px))
            lab.setText(text)


def make_widget(path, parent=None):
    if not can_handle(path) or not os.path.isfile(path):
        return None
    try:
        return FontView(path, parent)
    except Exception:
        log.exception("위젯 만들기 실패 %s", path)
        return None
