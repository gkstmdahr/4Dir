# -*- coding: utf-8 -*-
"""그림 일괄 크기·형식 바꾸기 (IMGBATCH_VER 1.0.0, 0.9.109 빌드 3 — 사용자 11/6 '추가 기능 전부', 경쟁 앱 조사 '이미지 일괄 크기·형식')

- 고른 그림들(PNG·JPG·WebP·BMP·GIF 첫 장면) → 크기: 그대로 / 긴 쪽 최대 N px / 비율 % / 가로×세로 안에 맞춤
- 형식: 그대로 · JPG · PNG · WebP · BMP, JPG·WebP 품질
- 저장: 원본 옆 새 폴더(기본 '변환됨') 또는 같은 폴더에 이름 뒤 글자 붙여서. 원본은 절대 덮어쓰지 않음, 같은 이름이면 'name (1)'
- 작게만: 원본이 더 작으면 키우지 않음(기본 켬). JPG 로 바꿀 때 투명한 곳은 흰 바탕
- Qt 그림 읽기·쓰기만 씀(QImage — 뒤 스레드에서 안전). 프로그램 실행 없음
로그: bin\\log\\4Dir.log [QE.imgbatch]
"""
import os
import time
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

IMGBATCH_VER = "1.0.0"
log = logging.getLogger("QE.imgbatch")
SRC_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
FORMATS = [("same", None), ("jpg", ".jpg"), ("png", ".png"), ("webp", ".webp"), ("bmp", ".bmp")]


def is_image(p):
    return os.path.splitext(p)[1].lower() in SRC_EXT


def new_size(w, h, mode, a, b, shrink_only):
    """mode: keep / long(a px) / pct(a %) / box(a×b 안에 맞춤)"""
    if mode == "long":
        s = a / max(w, h)
    elif mode == "pct":
        s = a / 100.0
    elif mode == "box":
        s = min(a / w, b / h)
    else:
        s = 1.0
    if shrink_only and s > 1:
        s = 1.0
    return max(1, round(w * s)), max(1, round(h * s))


def _free(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def convert_one(src, opt):
    """opt = {mode, a, b, shrink, fmt, quality, out: 'folder'|'suffix', folder, suffix} → 저장한 경로"""
    img = QtGui.QImage(src)
    if img.isNull():
        raise OSError(T("그림을 읽을 수 없습니다"))
    w, h = img.width(), img.height()
    nw, nh = new_size(w, h, opt["mode"], opt["a"], opt["b"], opt["shrink"])
    if (nw, nh) != (w, h):
        img = img.scaled(nw, nh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    ext = dict(FORMATS)[opt["fmt"]] or os.path.splitext(src)[1].lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext == ".gif":   # Qt 는 GIF 를 쓰지 못함 → PNG
        ext = ".png"
    if ext in (".jpg", ".bmp") and img.hasAlphaChannel():
        bg = QtGui.QImage(img.size(), QtGui.QImage.Format_RGB32)
        bg.fill(Qt.white)
        p = QtGui.QPainter(bg)
        p.drawImage(0, 0, img)
        p.end()
        img = bg
    name = os.path.splitext(os.path.basename(src))[0]
    if opt["out"] == "folder":
        d = os.path.join(os.path.dirname(src), opt["folder"])
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, name + ext)
    else:
        dst = os.path.join(os.path.dirname(src), name + opt["suffix"] + ext)
    if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(src)):
        dst = os.path.join(os.path.dirname(src), name + "_1" + ext)   # 원본은 절대 덮어쓰지 않음
    dst = _free(dst)
    wr = QtGui.QImageWriter(dst, ext[1:].encode())
    if ext in (".jpg", ".webp"):
        wr.setQuality(int(opt["quality"]))
    if not wr.write(img):
        raise OSError(wr.errorString())
    return dst, (w, h), (nw, nh)


class _Sig(QtCore.QObject):
    progress = QtCore.Signal(int, str)
    finished = QtCore.Signal(list, list, float)


class ImgBatchDialog(QtWidgets.QDialog):
    def __init__(self, paths, done_cb=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.paths = [p for p in paths if is_image(p) and os.path.isfile(p)]
        self.done_cb = done_cb
        self.sig = _Sig()
        self.sig.progress.connect(self._on_progress)
        self.sig.finished.connect(self._on_finished)
        self.stop = False
        self.setWindowTitle(T("그림 크기·형식 바꾸기") + f" — {len(self.paths)}")
        lay = QtWidgets.QVBoxLayout(self)
        f = QtWidgets.QFormLayout()
        self.mode = QtWidgets.QComboBox()
        for k, t in (("keep", T("그대로")), ("long", T("긴 쪽 최대 (px)")), ("pct", T("비율 (%)")), ("box", T("가로×세로 안에 맞춤 (px)"))):
            self.mode.addItem(t, k)
        self.mode.setCurrentIndex(1)
        self.a = QtWidgets.QSpinBox()
        self.a.setRange(1, 20000)
        self.a.setValue(1920)
        self.b = QtWidgets.QSpinBox()
        self.b.setRange(1, 20000)
        self.b.setValue(1080)
        szr = QtWidgets.QHBoxLayout()
        szr.addWidget(self.mode)
        szr.addWidget(self.a)
        self.x_lbl = QtWidgets.QLabel("×")
        szr.addWidget(self.x_lbl)
        szr.addWidget(self.b)
        f.addRow(T("크기"), szr)
        self.shrink = QtWidgets.QCheckBox(T("원본보다 크게 키우지 않음"))
        self.shrink.setChecked(True)
        f.addRow("", self.shrink)
        self.fmt = QtWidgets.QComboBox()
        for k, t in (("same", T("원본 형식 그대로")), ("jpg", "JPG"), ("png", "PNG"), ("webp", "WebP"), ("bmp", "BMP")):
            self.fmt.addItem(t, k)
        self.quality = QtWidgets.QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(90)
        fr = QtWidgets.QHBoxLayout()
        fr.addWidget(self.fmt)
        fr.addWidget(QtWidgets.QLabel(T("품질 (JPG·WebP)")))
        fr.addWidget(self.quality)
        f.addRow(T("형식"), fr)
        self.out_folder = QtWidgets.QRadioButton(T("새 폴더에:"))
        self.out_folder.setChecked(True)
        self.folder = QtWidgets.QLineEdit(T("변환됨"))
        self.out_suffix = QtWidgets.QRadioButton(T("같은 폴더, 이름 뒤에:"))
        self.suffix = QtWidgets.QLineEdit("_small")
        o1 = QtWidgets.QHBoxLayout()
        o1.addWidget(self.out_folder)
        o1.addWidget(self.folder)
        o2 = QtWidgets.QHBoxLayout()
        o2.addWidget(self.out_suffix)
        o2.addWidget(self.suffix)
        f.addRow(T("저장"), o1)
        f.addRow("", o2)
        lay.addLayout(f)
        lay.addWidget(QtWidgets.QLabel(T("원본은 바꾸지 않습니다. 같은 이름이 있으면 '이름 (1)' 로 저장합니다.")))
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, max(1, len(self.paths)))
        self.bar.setValue(0)
        lay.addWidget(self.bar)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        bot = QtWidgets.QHBoxLayout()
        bot.addStretch(1)
        self.b_run = QtWidgets.QPushButton(T("바꾸기"))
        self.b_run.setDefault(True)
        self.b_close = QtWidgets.QPushButton(T("닫기"))
        bot.addWidget(self.b_run)
        bot.addWidget(self.b_close)
        lay.addLayout(bot)
        self.mode.currentIndexChanged.connect(self._mode_ui)
        self.fmt.currentIndexChanged.connect(self._mode_ui)
        self.b_run.clicked.connect(self.run)
        self.b_close.clicked.connect(self.close)
        self._mode_ui()
        if not self.paths:
            self.info.setText(T("바꿀 수 있는 그림이 없습니다 (PNG·JPG·WebP·BMP·GIF)"))
            self.b_run.setEnabled(False)

    def _mode_ui(self):
        m = self.mode.currentData()
        self.a.setVisible(m != "keep")
        self.b.setVisible(m == "box")
        self.x_lbl.setVisible(m == "box")
        self.a.setSuffix(" %" if m == "pct" else " px")
        if m == "pct" and self.a.value() > 1000:
            self.a.setValue(50)
        if m != "pct" and self.a.value() <= 100:
            self.a.setValue(1920)
        self.quality.setEnabled(self.fmt.currentData() in ("jpg", "webp", "same"))

    def options(self):
        return {"mode": self.mode.currentData(), "a": self.a.value(), "b": self.b.value(), "shrink": self.shrink.isChecked(),
                "fmt": self.fmt.currentData(), "quality": self.quality.value(),
                "out": "folder" if self.out_folder.isChecked() else "suffix",
                "folder": self.folder.text().strip() or T("변환됨"), "suffix": self.suffix.text() or "_1"}

    def run(self):
        opt = self.options()
        self.b_run.setEnabled(False)
        self.stop = False
        log.info("그림 일괄 바꾸기 %d개 %s", len(self.paths), opt)

        def work():
            t0 = time.time()
            done, errs = [], []
            for i, p in enumerate(self.paths):
                if self.stop:
                    break
                self.sig.progress.emit(i, os.path.basename(p))
                try:
                    dst, s0, s1 = convert_one(p, opt)
                    done.append(dst)
                    log.info("  %s %dx%d → %s %dx%d", os.path.basename(p), s0[0], s0[1], dst, s1[0], s1[1])
                except Exception as ex:
                    errs.append(f"{os.path.basename(p)}: {ex}")
                    log.warning("  실패 %s: %s", p, ex)
            self.sig.finished.emit(done, errs, time.time() - t0)
        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, i, name):
        self.bar.setValue(i)
        self.info.setText(f"{i + 1}/{len(self.paths)}  {name}")

    def _on_finished(self, done, errs, sec):
        self.bar.setValue(len(self.paths))
        msg = T("{0}개 저장 ({1:.1f}초)").format(len(done), sec)
        if done:
            msg += "\n" + os.path.dirname(done[0])
        if errs:
            msg += "\n" + T("실패 {0}개").format(len(errs)) + ":\n" + "\n".join(errs[:10])
        self.info.setText(msg)
        self.b_run.setEnabled(True)
        if self.done_cb and done:
            self.done_cb(done)

    def closeEvent(self, ev):
        self.stop = True
        super().closeEvent(ev)
