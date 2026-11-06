# -*- coding: utf-8 -*-
"""디스크 사용량 트리맵 (SPACEMAP_VER 1.0.0, 0.9.109 빌드 3 — 사용자 11/6 '추가 기능 전부', 경쟁 앱 조사 '디스크 사용량 트리맵')

- 폴더 아래 전체를 뒤 스레드에서 훑어 크기를 모음 → 사각형 크기 = 용량 (정사각형에 가깝게 나누는 squarified 방식)
- 사각형 = 폴더(파랑 계열)·파일(형식별 색). 한 번 누르면 그 폴더로 들어감, 오른쪽 클릭·[위로] = 한 단계 위
- 두 번 누르기 = 4Dir 칸에서 그 위치 열기. 마우스를 올리면 이름·크기·비율
- 아주 작은 것(전체의 0.1% 미만)은 '작은 항목 n개'로 묶음
- 읽기만 함. 훑은 결과는 창을 닫으면 버림
로그: bin\\log\\4Dir.log [QE.spacemap]
"""
import os
import time
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

SPACEMAP_VER = "1.1.0"   # 1.1.0 (0.9.110 점검): 정션 건너뜀 · 훑기 실패해도 멈추지 않음
log = logging.getLogger("QE.spacemap")
SKIP = {"$recycle.bin", "system volume information"}
EXT_COLORS = {
    "img": ("#e5484d", {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".psd", ".tga", ".tif", ".tiff", ".exr", ".hdr"}),
    "video": ("#8e4ec6", {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm", ".m4v"}),
    "audio": ("#e93d82", {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}),
    "arc": ("#f76b15", {".zip", ".7z", ".rar", ".tar", ".gz", ".iso", ".cab"}),
    "doc": ("#30a46c", {".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".hwp", ".md", ".csv"}),
    "code": ("#12a594", {".py", ".js", ".cs", ".cpp", ".h", ".json", ".xml", ".html", ".css", ".ts"}),
    "bin": ("#8b8d98", {".exe", ".dll", ".sys", ".msi", ".pyd", ".lib", ".obj", ".pdb"}),
    "3d": ("#e2b203", {".max", ".fbx", ".obj", ".blend", ".ma", ".mb", ".unity", ".prefab", ".anim", ".uasset"}),
}
EXT2COLOR = {e: c for c, exts in EXT_COLORS.values() for e in exts}


def size_text(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:,.0f} {u}" if u == "B" else f"{n:,.1f} {u}"
        n /= 1024.0


class Node:
    __slots__ = ("name", "path", "size", "is_dir", "kids", "parent", "files")

    def __init__(self, name, path, is_dir, parent=None):
        self.name, self.path, self.is_dir, self.parent = name, path, is_dir, parent
        self.size, self.kids, self.files = 0, [], 0


def build(root, cancel=lambda: False, progress=lambda n: None):
    """폴더 나무 (크기 합 포함). 파일 수 progress 로 알림"""
    top = Node(os.path.basename(root.rstrip("\\/")) or root, root, True)
    count = [0]

    def walk(node):
        try:
            it = os.scandir(node.path)
        except OSError:
            return
        with it:
            for de in it:
                if cancel():
                    return
                try:
                    if de.is_dir(follow_symlinks=False):
                        if de.name.lower() in SKIP or de.is_symlink() or de.is_junction():   # 0.9.110: 정션도 (자기 위를 가리키면 끝없이·크기 부풀림)
                            continue
                        k = Node(de.name, de.path, True, node)
                        walk(k)
                    else:
                        k = Node(de.name, de.path, False, node)
                        k.size = de.stat(follow_symlinks=False).st_size
                        k.files = 1
                        count[0] += 1
                        if count[0] % 5000 == 0:
                            progress(count[0])
                except OSError:
                    continue
                node.kids.append(k)
                node.size += k.size
                node.files += k.files
    walk(top)
    return top


def squarify(items, x, y, w, h):
    """items = [(크기, 물건)] 큰 순 → [(QRectF, 물건)] — Bruls 등 squarified treemap"""
    out = []
    total = float(sum(s for s, _ in items))
    if total <= 0 or w <= 0 or h <= 0:
        return out
    scale = w * h / total
    rest = [(s * scale, o) for s, o in items if s > 0]

    def worst(row, side):
        s = sum(a for a, _ in row)
        mx, mn = max(a for a, _ in row), min(a for a, _ in row)
        return max(side * side * mx / (s * s), (s * s) / (side * side * mn))
    while rest:
        side = min(w, h)
        row = [rest[0]]
        i = 1
        while i < len(rest) and worst(row + [rest[i]], side) <= worst(row, side):
            row.append(rest[i])
            i += 1
        rest = rest[i:]
        s = sum(a for a, _ in row)
        if w >= h:   # 왼쪽에 세로 줄
            cw = s / h
            yy = y
            for a, o in row:
                hh = a / cw
                out.append((QtCore.QRectF(x, yy, cw, hh), o))
                yy += hh
            x += cw
            w -= cw
        else:        # 위에 가로 줄
            ch = s / w
            xx = x
            for a, o in row:
                ww = a / ch
                out.append((QtCore.QRectF(xx, y, ww, ch), o))
                xx += ww
            y += ch
            h -= ch
    return out


class MapView(QtWidgets.QWidget):
    entered = QtCore.Signal(object)    # 폴더로 들어감
    opened = QtCore.Signal(object)     # 두 번 누름
    up = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.node = None
        self.rects = []
        self.hover = None
        self.setMouseTracking(True)
        self.setMinimumSize(300, 200)

    def set_node(self, node):
        self.node = node
        self.hover = None
        self._layout()
        self.update()

    def resizeEvent(self, ev):
        self._layout()
        super().resizeEvent(ev)

    def _layout(self):
        self.rects = []
        n = self.node
        if n is None or n.size <= 0:
            return
        kids = sorted((k for k in n.kids if k.size > 0), key=lambda k: -k.size)
        small = [k for k in kids if k.size < n.size * 0.001]
        big = [k for k in kids if k.size >= n.size * 0.001]
        items = [(k.size, k) for k in big]
        if small:
            items.append((sum(k.size for k in small), ("small", len(small))))
        items.sort(key=lambda t: -t[0])
        r = self.rect().adjusted(2, 2, -2, -2)
        self.rects = squarify(items, r.x(), r.y(), r.width(), r.height())

    @staticmethod
    def color(o):
        if isinstance(o, tuple):
            return QtGui.QColor("#666")
        if o.is_dir:
            return QtGui.QColor("#3e7bd6")
        return QtGui.QColor(EXT2COLOR.get(os.path.splitext(o.name)[1].lower(), "#9aa4b2"))

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), self.palette().base())
        if not self.rects:
            p.drawText(self.rect(), Qt.AlignCenter, T("비어 있음") if self.node is not None else T("훑는 중…"))
            return
        f = p.font()
        for rc, o in self.rects:
            c = self.color(o)
            if o is self.hover:
                c = c.lighter(130)
            g = QtGui.QLinearGradient(rc.topLeft(), rc.bottomRight())
            g.setColorAt(0, c.lighter(115))
            g.setColorAt(1, c.darker(115))
            p.fillRect(rc, g)
            p.setPen(QtGui.QPen(self.palette().base().color(), 1))
            p.drawRect(rc)
            if rc.width() > 40 and rc.height() > 16:
                if isinstance(o, tuple):
                    name = T("작은 항목 {0}개").format(o[1])
                    sz = sum(k.size for k in self.node.kids if 0 < k.size < self.node.size * 0.001)
                else:
                    name, sz = o.name + ("\\" if o.is_dir else ""), o.size
                p.save()
                p.setClipRect(rc)
                p.setPen(Qt.white)
                p.setFont(f)
                p.drawText(rc.adjusted(4, 2, -3, -2), Qt.AlignLeft | Qt.AlignTop, name if rc.height() < 34 else name + chr(10) + size_text(sz))
                p.restore()
        p.end()

    def at(self, pos):
        for rc, o in self.rects:
            if rc.contains(QtCore.QPointF(pos)):
                return o
        return None

    def mouseMoveEvent(self, ev):
        o = self.at(ev.position().toPoint())
        if o is not self.hover:
            self.hover = o
            self.update()
            if o is None:
                QtWidgets.QToolTip.hideText()
            else:
                if isinstance(o, tuple):
                    t = T("작은 항목 {0}개").format(o[1])
                else:
                    t = f"{o.path}\n{size_text(o.size)}  ({o.size * 100.0 / max(1, self.node.size):.1f}%)" + (T("\n파일 {0:,}개").format(o.files) if o.is_dir else "")
                QtWidgets.QToolTip.showText(ev.globalPosition().toPoint(), t, self)

    def leaveEvent(self, ev):
        self.hover = None
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.RightButton or ev.button() == Qt.BackButton:
            self.up.emit()
            return
        o = self.at(ev.position().toPoint())
        if ev.button() == Qt.LeftButton and o is not None and not isinstance(o, tuple) and o.is_dir:
            self.entered.emit(o)

    def mouseDoubleClickEvent(self, ev):
        o = self.at(ev.position().toPoint())
        if o is not None and not isinstance(o, tuple):
            self.opened.emit(o)


class _Sig(QtCore.QObject):
    built = QtCore.Signal(object, float)
    progress = QtCore.Signal(int)


class SpaceMapDialog(QtWidgets.QDialog):
    def __init__(self, root, open_cb, parent=None):
        """open_cb(경로, 파일인가) = 4Dir 칸에서 열기"""
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.root, self.open_cb = root, open_cb
        self.stop = False
        self.setWindowTitle(T("디스크 사용량 트리맵") + f" — {root}")
        self.resize(1000, 700)
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.b_up = QtWidgets.QPushButton("↑ " + T("위로"))
        self.b_up.setEnabled(False)
        self.where = QtWidgets.QLabel(T("훑는 중…"))
        self.b_re = QtWidgets.QPushButton(T("다시 훑기"))
        top.addWidget(self.b_up)
        top.addWidget(self.where, 1)
        top.addWidget(self.b_re)
        lay.addLayout(top)
        self.view = MapView()
        lay.addWidget(self.view, 1)
        legend = QtWidgets.QLabel("  ".join(f"<span style='color:{c}'>■</span> {n}" for n, c in
                                            ((T("폴더"), "#3e7bd6"), (T("그림"), "#e5484d"), (T("영상"), "#8e4ec6"), (T("소리"), "#e93d82"),
                                             (T("압축 파일"), "#f76b15"), (T("문서"), "#30a46c"), (T("코드"), "#12a594"), (T("프로그램"), "#8b8d98"),
                                             (T("3D·게임"), "#e2b203"))) + "  ·  " + T("누르면 들어감 · 오른쪽 클릭 = 위로 · 두 번 누르면 4Dir 에서 열기"))
        legend.setTextFormat(Qt.RichText)
        legend.setWordWrap(True)
        lay.addWidget(legend)
        self.sig = _Sig()
        self.sig.built.connect(self._on_built)
        self.sig.progress.connect(lambda n: self.where.setText(T("훑는 중… 파일 {0:,}개").format(n)))
        self.view.entered.connect(self.enter)
        self.view.up.connect(self.go_up)
        self.view.opened.connect(lambda o: self.open_cb(o.path, not o.is_dir))
        self.b_up.clicked.connect(self.go_up)
        self.b_re.clicked.connect(self.rescan)
        self.rescan()

    def rescan(self):
        self.b_re.setEnabled(False)
        self.view.set_node(None)
        self.where.setText(T("훑는 중…"))

        def work():
            t0 = time.time()
            try:
                tree = build(self.root, lambda: self.stop, lambda n: not self.stop and self.sig.progress.emit(n))
            except Exception:   # 0.9.110: 너무 깊은 폴더 등 → '훑는 중…' 에 멈추지 않고 빈 지도
                log.exception("용량 지도 훑기 실패 %s", self.root)
                tree = Node(os.path.basename(self.root.rstrip(chr(92) + "/")) or self.root, self.root, True)
            if not self.stop:
                self.sig.built.emit(tree, time.time() - t0)
        threading.Thread(target=work, daemon=True).start()

    def _on_built(self, tree, sec):
        if self.stop:
            return
        log.info("디스크 사용량 트리맵 %s: %s, 파일 %d개 %.1f초", self.root, size_text(tree.size), tree.files, sec)
        self.b_re.setEnabled(True)
        self.enter(tree)

    def enter(self, node):
        self.view.set_node(node)
        self.b_up.setEnabled(node.parent is not None)
        self.where.setText(f"{node.path}   —   {size_text(node.size)} · " + T("파일 {0:,}개").format(node.files))

    def go_up(self):
        n = self.view.node
        if n is not None and n.parent is not None:
            self.enter(n.parent)

    def closeEvent(self, ev):
        self.stop = True
        super().closeEvent(ev)
