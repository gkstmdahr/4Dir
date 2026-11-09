# -*- coding: utf-8 -*-
"""PDF 편집 (PDFEDIT_VER 1.0.0, 0.9.122 — 사용자 11/10 'PDF 편집: 라이선스 문제 없는 범위로')

한 창에 두 탭:
- 쪽(Pages): 쪽 그림 목록 — 끌어서 순서 바꾸기, 왼쪽·오른쪽 돌리기, 지우기(Del), 다른 PDF·그림 끼워 넣기(바깥에서 끌어 넣기도), 고른 쪽 빼서 새 파일
- 주석(Annotate): 펜 · 형광펜 · 글상자 · 지우개(이번에 넣은 주석만), 색 · 굵기 · 글자 크기, 되돌리기(Ctrl+Z)
저장: [다른 이름으로 저장] (기본 '이름_편집.pdf') / [원본에 저장] (확인 후 임시 파일 → 바꿔치기)

구현 메모
- 읽기: pypdf(BSD) + QtPdf(PDFium, 그림 그리기). 원본은 바이트로 읽어 메모리에서 다룸 → 원본 파일을 붙잡지 않아 원본에 저장 가능
- 주석은 PDF 표준 주석(/Ink, /FreeText)으로 넣고 겉모양(/AP)을 직접 만들어 넣음 → 아크로뱃·크롬·엣지 등 어디서나 같게 보이고, 다른 PDF 프로그램에서 지우거나 옮길 수 있음
  · 펜/형광펜 = /Ink (형광펜은 반투명 /CA 0.35 + Multiply)
  · 글상자 = /FreeText, 겉모양은 맑은 고딕 등 윈도우 글꼴로 그린 그림(투명 배경, SMask) — 한글 글꼴을 PDF 에 심지 않아도 됨(글자 검색은 안 됨, /Contents 에 글은 남김)
- 좌표: 화면(보이는 방향, 위 왼쪽 0, 단위 pt) ↔ PDF 원래 좌표(쪽 /Rotate + 이번에 돌린 각도 반영) — d2n / n2d
로그: bin\\log\\4Dir.log [QE.pdfedit]
"""
import io
import os
import time
import uuid
import zlib
import logging
import tempfile

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

import pdftools
from pdftools import pypdf
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject,
                           NumberObject, TextStringObject)

try:
    from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions
    HAVE_QTPDF = True
except Exception:   # 배포판에 QtPdf 가 없으면 창 대신 안내
    HAVE_QTPDF = False

PDFEDIT_VER = "1.0.0"
log = logging.getLogger("QE.pdfedit")
THUMB = 150          # 쪽 목록 그림 긴 변(px)
TEXT_SCALE = 4       # 글상자 그림 해상도 (pt 당 px)
HL_ALPHA = 0.35
COLORS = ["#e53935", "#1e88e5", "#212121", "#43a047", "#fdd835", "#fb8c00"]


# ================================================================ 문서·쪽 모델
class Src:
    """원본 파일 하나 (편집 대상 또는 끼워 넣은 파일)"""

    def __init__(self, data, name):
        self.name = name
        self.data = data
        self.reader = pdftools._open_reader(io.BytesIO(data))
        self.qdoc = None
        if HAVE_QTPDF:
            self.buf = QtCore.QBuffer()
            self.buf.setData(QtCore.QByteArray(data))
            self.buf.open(QtCore.QIODevice.ReadOnly)
            self.qdoc = QPdfDocument()
            self.qdoc.load(self.buf)

    def close(self):
        try:
            if self.qdoc is not None:
                self.qdoc.close()
            if getattr(self, "buf", None) is not None:
                self.buf.close()
        except Exception:
            pass


class PageItem:
    """편집 중인 쪽 하나: 어느 원본의 몇 쪽 + 더 돌린 각도 + 이번에 넣은 주석"""

    def __init__(self, src, idx):
        self.src, self.idx = src, idx
        self.rot = 0
        self.annots = []
        pg = src.reader.pages[idx]
        cb = pg.cropbox
        self.x0, self.y0 = float(cb.left), float(cb.bottom)
        self.w, self.h = float(cb.width), float(cb.height)
        self.r0 = int(pg.get("/Rotate", 0) or 0) % 360

    @property
    def R(self):
        return (self.r0 + self.rot) % 360

    def disp_size(self, R=None):
        R = self.R if R is None else R
        return (self.w, self.h) if R in (0, 180) else (self.h, self.w)

    def d2n(self, dx, dy, R=None):
        """화면 좌표(pt, 위 왼쪽 0) → PDF 좌표"""
        R = self.R if R is None else R
        x0, y0, w, h = self.x0, self.y0, self.w, self.h
        if R == 0:
            return x0 + dx, y0 + h - dy
        if R == 90:
            return x0 + dy, y0 + dx
        if R == 180:
            return x0 + w - dx, y0 + dy
        return x0 + w - dy, y0 + h - dx

    def n2d(self, x, y, R=None):
        R = self.R if R is None else R
        x0, y0, w, h = self.x0, self.y0, self.w, self.h
        if R == 0:
            return x - x0, h - (y - y0)
        if R == 90:
            return y - y0, x - x0
        if R == 180:
            return w - (x - x0), y - y0
        return h - (y - y0), w - (x - x0)


def render_base(item, long_px):
    """원본 쪽 그림 (원래 /Rotate 반영, 이번 회전 전). 긴 변 long_px"""
    if item.src.qdoc is None:
        return QtGui.QImage()
    sz = item.src.qdoc.pagePointSize(item.idx)
    if sz.width() <= 0 or sz.height() <= 0:
        return QtGui.QImage()
    k = long_px / max(sz.width(), sz.height())
    opt = QPdfDocumentRenderOptions()
    opt.setRenderFlags(QPdfDocumentRenderOptions.RenderFlag.Annotations)
    im = item.src.qdoc.render(item.idx, QtCore.QSize(max(1, round(sz.width() * k)), max(1, round(sz.height() * k))), opt)
    if im.isNull():
        return im
    out = QtGui.QImage(im.size(), QtGui.QImage.Format_RGB32)
    out.fill(Qt.white)   # PDF 배경이 투명이면 흰 종이로
    p = QtGui.QPainter(out)
    p.drawImage(0, 0, im)
    p.end()
    return out


def framed(img, box):
    """쪽 그림을 같은 크기 칸 가운데에 + 테두리·그림자 (흰 쪽이 배경과 섞이지 않게, 쪽 번호 줄이 가지런하게)"""
    out = QtGui.QImage(box, box, QtGui.QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    if img.isNull():
        return out
    m = 6
    sc = img.scaled(box - m * 2, box - m * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    x = (box - sc.width()) // 2
    y = (box - sc.height()) // 2
    p = QtGui.QPainter(out)
    p.fillRect(x + 3, y + 3, sc.width(), sc.height(), QtGui.QColor(0, 0, 0, 50))
    p.drawImage(x, y, sc)
    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 110), 1))
    p.drawRect(x, y, sc.width() - 1, sc.height() - 1)
    p.end()
    return out


def rotated(img, deg):
    if not deg or img.isNull():
        return img
    return img.transformed(QtGui.QTransform().rotate(deg), Qt.SmoothTransformation)


# ================================================================ 글상자 그림
def text_font(size_pt, scale=1.0):
    f = QtGui.QFont("Malgun Gothic")
    f.setPixelSize(max(1, round(size_pt * scale)))
    return f


def text_box_size(text, size_pt, max_w_pt):
    """글이 들어갈 상자 크기(pt). 폭은 max_w_pt 안에서 줄바꿈"""
    fm = QtGui.QFontMetricsF(text_font(size_pt, TEXT_SCALE))
    r = fm.boundingRect(QtCore.QRectF(0, 0, max_w_pt * TEXT_SCALE, 1e6), int(Qt.TextWordWrap | Qt.AlignLeft), text or " ")
    pad = size_pt * 0.3
    return r.width() / TEXT_SCALE + pad * 2, r.height() / TEXT_SCALE + pad * 2


def text_image(a):
    """글상자 주석 → 투명 배경 그림 (화면 방향, 만들 때 기준)"""
    dw, dh = a["dsize"]
    im = QtGui.QImage(max(1, round(dw * TEXT_SCALE)), max(1, round(dh * TEXT_SCALE)), QtGui.QImage.Format_ARGB32)
    im.fill(Qt.transparent)
    p = QtGui.QPainter(im)
    p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
    p.setFont(text_font(a["size"], TEXT_SCALE))
    p.setPen(QtGui.QColor(a["color"]))
    pad = a["size"] * 0.3 * TEXT_SCALE
    p.drawText(QtCore.QRectF(pad, pad, im.width() - pad * 2, im.height() - pad * 2), int(Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop), a["text"])
    p.end()
    return im


def make_text_annot(item, text, dx, dy, size, color, max_w=None):
    """화면 좌표 (dx,dy) 에 글상자 주석"""
    dw_page, dh_page = item.disp_size()
    max_w = max_w or max(60.0, min(260.0, dw_page - dx - 6))
    bw, bh = text_box_size(text, size, max_w)
    R = item.R
    corners = [item.d2n(dx, dy), item.d2n(dx + bw, dy), item.d2n(dx + bw, dy + bh), item.d2n(dx, dy + bh)]   # 위왼·위오·아래오·아래왼 (만들 때 화면 기준)
    return {"kind": "text", "text": text, "size": size, "color": color, "dsize": (bw, bh), "Rc": R, "corners": corners, "id": uuid.uuid4().hex[:12]}


# ================================================================ 저장 (pypdf)
def _rgb(c):
    q = QtGui.QColor(c)
    return [FloatObject(round(q.redF(), 4)), FloatObject(round(q.greenF(), 4)), FloatObject(round(q.blueF(), 4))]


def _num(v):
    return FloatObject(round(float(v), 3))


def _stream(w, data, extra):
    s = DecodedStreamObject()
    s.set_data(data)
    for k, v in extra.items():
        s[NameObject(k)] = v
    s = s.flate_encode()
    return w._add_object(s)


def _annot_common(a, sub, rect):
    d = DictionaryObject()
    d[NameObject("/Type")] = NameObject("/Annot")
    d[NameObject("/Subtype")] = NameObject(sub)
    d[NameObject("/Rect")] = ArrayObject([_num(v) for v in rect])
    d[NameObject("/F")] = NumberObject(4)   # 인쇄
    d[NameObject("/NM")] = TextStringObject("4Dir-" + a["id"])
    d[NameObject("/T")] = TextStringObject("4Dir")
    d[NameObject("/M")] = TextStringObject(time.strftime("D:%Y%m%d%H%M%S"))
    d[NameObject("/C")] = ArrayObject(_rgb(a["color"]))
    return d


def ink_annot(w, a):
    pts = a["pts"]
    hw = a["width"] / 2 + 1
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    rect = [min(xs) - hw, min(ys) - hw, max(xs) + hw, max(ys) + hw]
    hl = a["kind"] == "hl"
    r, g, b = (float(x) for x in _rgb(a["color"]))
    ops = ["q", "/GS0 gs" if hl else "", f"{r:.4f} {g:.4f} {b:.4f} RG", f"{a['width']:.2f} w", "1 J 1 j"]
    ops.append(f"{pts[0][0]:.2f} {pts[0][1]:.2f} m")
    for x, y in (pts[1:] or [(pts[0][0] + 0.01, pts[0][1])]):
        ops.append(f"{x:.2f} {y:.2f} l")
    ops += ["S", "Q"]
    res = DictionaryObject()
    if hl:
        gs = DictionaryObject({NameObject("/Type"): NameObject("/ExtGState"), NameObject("/CA"): FloatObject(HL_ALPHA),
                               NameObject("/ca"): FloatObject(HL_ALPHA), NameObject("/BM"): NameObject("/Multiply")})
        res[NameObject("/ExtGState")] = DictionaryObject({NameObject("/GS0"): gs})
    ap = _stream(w, "\n".join(o for o in ops if o).encode("latin-1"), {
        "/Type": NameObject("/XObject"), "/Subtype": NameObject("/Form"),
        "/BBox": ArrayObject([_num(v) for v in rect]), "/Resources": res})
    d = _annot_common(a, "/Ink", rect)
    d[NameObject("/InkList")] = ArrayObject([ArrayObject([_num(v) for p in pts for v in p])])
    d[NameObject("/BS")] = DictionaryObject({NameObject("/W"): _num(a["width"])})
    if hl:
        d[NameObject("/CA")] = FloatObject(HL_ALPHA)
        d[NameObject("/IT")] = NameObject("/InkHighlight")   # 형광펜 표시 (읽는 프로그램 참고용)
    d[NameObject("/AP")] = DictionaryObject({NameObject("/N"): ap})
    return d


def text_annot(w, a):
    im = text_image(a).convertToFormat(QtGui.QImage.Format_RGBA8888)
    iw, ih = im.width(), im.height()
    raw = bytes(im.constBits())[: iw * ih * 4]
    rgb = bytearray(iw * ih * 3)
    alpha = bytearray(iw * ih)
    rgb[0::3], rgb[1::3], rgb[2::3] = raw[0::4], raw[1::4], raw[2::4]
    alpha[:] = raw[3::4]
    smask = _stream(w, bytes(alpha), {"/Type": NameObject("/XObject"), "/Subtype": NameObject("/Image"), "/Width": NumberObject(iw),
                                      "/Height": NumberObject(ih), "/ColorSpace": NameObject("/DeviceGray"), "/BitsPerComponent": NumberObject(8)})
    img = _stream(w, bytes(rgb), {"/Type": NameObject("/XObject"), "/Subtype": NameObject("/Image"), "/Width": NumberObject(iw),
                                  "/Height": NumberObject(ih), "/ColorSpace": NameObject("/DeviceRGB"), "/BitsPerComponent": NumberObject(8),
                                  "/SMask": smask})
    bw, bh = a["dsize"]
    Rc = a["Rc"]
    # 겉모양: 상자(화면 방향) 를 쪽 회전만큼 반대로 돌려 PDF 좌표에 놓음 → 화면에서 똑바로 보임 (BBox 를 Matrix 로 바꾼 뒤 /Rect 에 맞춰짐)
    mat = {0: [1, 0, 0, 1], 90: [0, 1, -1, 0], 180: [-1, 0, 0, -1], 270: [0, -1, 1, 0]}[Rc]
    res = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): img})})
    ap = _stream(w, f"q {bw:.3f} 0 0 {bh:.3f} 0 0 cm /Im0 Do Q".encode("latin-1"), {
        "/Type": NameObject("/XObject"), "/Subtype": NameObject("/Form"),
        "/BBox": ArrayObject([_num(0), _num(0), _num(bw), _num(bh)]),
        "/Matrix": ArrayObject([NumberObject(v) for v in mat] + [NumberObject(0), NumberObject(0)]), "/Resources": res})
    xs = [c[0] for c in a["corners"]]
    ys = [c[1] for c in a["corners"]]
    rect = [min(xs), min(ys), max(xs), max(ys)]
    d = _annot_common(a, "/FreeText", rect)
    d[NameObject("/Contents")] = TextStringObject(a["text"])
    r, g, b = (float(x) for x in _rgb(a["color"]))
    d[NameObject("/DA")] = TextStringObject(f"/Helv {a['size']:.1f} Tf {r:.3f} {g:.3f} {b:.3f} rg")
    d[NameObject("/BS")] = DictionaryObject({NameObject("/W"): NumberObject(0)})
    if Rc:
        d[NameObject("/Rotate")] = NumberObject(Rc)
    d[NameObject("/AP")] = DictionaryObject({NameObject("/N"): ap})
    return d


def build_pdf(items, out_path):
    """쪽 목록 → 새 PDF 파일 (임시에 쓴 뒤 바꿔치기). 돌려줌: 쪽 수"""
    t0 = time.time()
    w = pypdf.PdfWriter()
    n_ann = 0
    for it in items:
        pg = w.add_page(it.src.reader.pages[it.idx])
        if it.rot:
            pg.rotate(it.rot)
        for a in it.annots:
            d = ink_annot(w, a) if a["kind"] in ("ink", "hl") else text_annot(w, a)
            w.add_annotation(len(w.pages) - 1, d)
            n_ann += 1
    folder = os.path.dirname(out_path) or "."
    fd, tmp = tempfile.mkstemp(prefix="~4dir_", suffix=".pdf", dir=folder)
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            w.write(f)
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    finally:
        w.close()
    log.info("저장 %d쪽 주석 %d개 %.2f초 → %s", len(items), n_ann, time.time() - t0, out_path)
    return len(items)


# ================================================================ 주석 그리기 (화면)
def paint_annots(p, item, k, skip=None):
    """item 의 주석을 화면 그림 위에 (k = px/pt)"""
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    for a in item.annots:
        if a is skip:
            continue
        if a["kind"] in ("ink", "hl"):
            path = QtGui.QPainterPath()
            for i, (x, y) in enumerate(a["pts"]):
                dx, dy = item.n2d(x, y)
                (path.moveTo if i == 0 else path.lineTo)(dx * k, dy * k)
            if len(a["pts"]) == 1:
                path.lineTo(path.currentPosition() + QtCore.QPointF(0.01, 0))
            c = QtGui.QColor(a["color"])
            p.save()
            if a["kind"] == "hl":
                c.setAlphaF(HL_ALPHA)
                p.setCompositionMode(QtGui.QPainter.CompositionMode_Multiply)
            p.setPen(QtGui.QPen(c, a["width"] * k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            p.restore()
        else:
            im = a.get("_img")
            if im is None:
                im = a["_img"] = text_image(a)
            quad = QtGui.QPolygonF([QtCore.QPointF(*[v * k for v in item.n2d(*c)]) for c in a["corners"]])
            src = QtGui.QPolygonF([QtCore.QPointF(0, 0), QtCore.QPointF(im.width(), 0), QtCore.QPointF(im.width(), im.height()), QtCore.QPointF(0, im.height())])
            tf = QtGui.QTransform()
            if QtGui.QTransform.quadToQuad(src, quad, tf):
                p.save()
                p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
                p.setTransform(tf, True)
                p.drawImage(0, 0, im)
                p.restore()


def hit_annot(item, x, y, tol):
    """PDF 좌표 (x,y) 에 닿은 마지막 주석"""
    for a in reversed(item.annots):
        if a["kind"] in ("ink", "hl"):
            t = max(tol, a["width"] / 2 + 2)
            if any((px - x) ** 2 + (py - y) ** 2 <= t * t for px, py in a["pts"]):
                return a
        else:
            xs = [c[0] for c in a["corners"]]
            ys = [c[1] for c in a["corners"]]
            if min(xs) - tol <= x <= max(xs) + tol and min(ys) - tol <= y <= max(ys) + tol:
                return a
    return None


class PageCanvas(QtWidgets.QWidget):
    """주석 탭 쪽 그림 + 펜/형광펜/글상자/지우개"""
    changed = QtCore.Signal()

    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg
        self.item = None
        self.base = QtGui.QImage()
        self.k = 1.0
        self.cur = None       # 그리는 중인 선
        self.editor = None    # 글상자 입력칸
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_item(self, item, width_px):
        self.commit_text()
        self.item = item
        if item is None:
            self.base = QtGui.QImage()
            self.setFixedSize(10, 10)
            self.update()
            return
        dw, dh = item.disp_size()
        self.k = max(0.2, width_px / dw)
        long_px = max(dw, dh) * self.k * self.devicePixelRatioF()
        img = render_base(item, min(long_px, 4000))
        self.base = rotated(img, item.rot)
        self.setFixedSize(round(dw * self.k), round(dh * self.k))
        self.update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), Qt.white)
        if not self.base.isNull():
            p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
            p.drawImage(QtCore.QRectF(self.rect()), self.base)
        if self.item is not None:
            paint_annots(p, self.item, self.k)
            if self.cur is not None:
                tmp = self.item.annots
                self.item.annots = [self.cur]
                paint_annots(p, self.item, self.k)
                self.item.annots = tmp
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 60), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()

    def _n(self, pos):
        return self.item.d2n(pos.x() / self.k, pos.y() / self.k)

    def mousePressEvent(self, ev):
        if self.item is None or ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)
        tool = self.dlg.tool
        if self.editor is not None:
            self.commit_text()
            if tool == "text":
                return
        if tool in ("ink", "hl"):
            self.cur = {"kind": tool, "pts": [self._n(ev.position())], "color": self.dlg.color_for(tool),
                        "width": self.dlg.width_for(tool), "id": uuid.uuid4().hex[:12]}
        elif tool == "erase":
            self._erase(ev.position())
        elif tool == "text":
            self.open_editor(ev.position())

    def mouseMoveEvent(self, ev):
        if self.cur is not None and ev.buttons() & Qt.LeftButton:
            n = self._n(ev.position())
            last = self.cur["pts"][-1]
            if (n[0] - last[0]) ** 2 + (n[1] - last[1]) ** 2 >= (0.6 / max(self.k, 0.1)) ** 2 * 4:
                self.cur["pts"].append(n)
                self.update()
        elif self.dlg.tool == "erase" and ev.buttons() & Qt.LeftButton:
            self._erase(ev.position())

    def mouseReleaseEvent(self, ev):
        if self.cur is not None:
            a, self.cur = self.cur, None
            self.dlg.add_annot(self.item, a)
            self.update()

    def _erase(self, pos):
        x, y = self._n(pos)
        a = hit_annot(self.item, x, y, 4 / self.k)
        if a is not None:
            self.dlg.remove_annot(self.item, a)
            self.update()

    # ---- 글상자
    def open_editor(self, pos):
        e = QtWidgets.QPlainTextEdit(self)
        e.setObjectName("pdfTextEditor")
        size = self.dlg.text_size()
        e.setFont(text_font(size, self.k))
        e.setStyleSheet(f"QPlainTextEdit{{background:rgba(255,255,255,200); color:{self.dlg.color_for('text')}; border:1px dashed #1e88e5;}}")
        e.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        e.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        dw, dh = self.item.disp_size()
        x = pos.x()
        y = pos.y()
        wpx = max(80, min(260 * self.k, self.width() - x - 4))
        e.setGeometry(round(x), round(y), round(wpx), round(size * self.k * 2.4))
        e.textChanged.connect(lambda e=e: e.setFixedHeight(max(round(size * self.k * 2.4), round(e.document().size().height() * QtGui.QFontMetricsF(e.font()).lineSpacing()) + 12)))
        e.installEventFilter(self)
        e.show()
        e.setFocus()
        self.editor = (e, x / self.k, y / self.k, wpx / self.k, size)

    def eventFilter(self, obj, ev):
        if self.editor is not None and obj is self.editor[0] and ev.type() == QtCore.QEvent.KeyPress:
            if ev.key() == Qt.Key_Escape:
                self.commit_text(cancel=True)
                return True
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and ev.modifiers() & Qt.ControlModifier:
                self.commit_text()
                return True
        return super().eventFilter(obj, ev)

    def commit_text(self, cancel=False):
        if self.editor is None:
            return
        e, dx, dy, wpt, size = self.editor
        self.editor = None
        text = e.toPlainText().rstrip()
        e.hide()
        e.deleteLater()
        if cancel or not text.strip() or self.item is None:
            return
        a = make_text_annot(self.item, text, dx, dy, size, self.dlg.color_for("text"), max_w=wpt)
        self.dlg.add_annot(self.item, a)
        self.update()


# ================================================================ 쪽 목록
class PageList(QtWidgets.QListWidget):
    dropped = QtCore.Signal(list, int)   # (바깥 파일들, 넣을 자리)
    reordered = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setIconSize(QtCore.QSize(THUMB, THUMB))
        self.setGridSize(QtCore.QSize(THUMB + 24, THUMB + 34))
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setMovement(QtWidgets.QListView.Snap)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setWordWrap(True)
        self.setSpacing(4)

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
            it = self.itemAt(ev.position().toPoint())
            row = self.row(it) + 1 if it is not None else self.count()
            self.dropped.emit([u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()], row)
            ev.acceptProposedAction()
            return
        super().dropEvent(ev)
        self.reordered.emit()


# ================================================================ 창
class PdfEditDialog(QtWidgets.QDialog):
    def __init__(self, parent, path, open_loc=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.path = os.path.normpath(path)
        self.open_loc = open_loc
        self.setWindowTitle(T("PDF 편집") + " — " + os.path.basename(self.path) + " — 4Dir")
        self.setWindowIcon(pdftools.tool_icon(20))
        self.resize(1000, 760)
        self.srcs = []
        self.items = []
        self.dirty = False
        self.undo = []        # [(item, 주석)] 넣은 순서 — 되돌리기
        self.tool = "ink"
        self.colors = {"ink": COLORS[0], "hl": COLORS[4], "text": COLORS[2]}
        self.cur = 0
        self._thumb_q = []
        lay = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_pages(), T("쪽 (Pages)"))
        self.tabs.addTab(self._build_annot(), T("주석 (Annotate)"))
        self.tabs.currentChanged.connect(self._on_tab)
        self.info = QtWidgets.QLabel()
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bot = QtWidgets.QHBoxLayout()
        bot.addWidget(self.info, 1)
        self.btn_saveas = QtWidgets.QPushButton(T("다른 이름으로 저장…"))
        self.btn_saveas.setStyleSheet("font-weight:bold;")
        self.btn_saveas.clicked.connect(self.save_as)
        self.btn_save = QtWidgets.QPushButton(T("원본에 저장"))
        self.btn_save.clicked.connect(self.save_over)
        close = QtWidgets.QPushButton(T("닫기"))
        close.clicked.connect(self.close)
        for b in (self.btn_saveas, self.btn_save, close):
            bot.addWidget(b)
        lay.addLayout(bot)
        self._thumb_timer = QtCore.QTimer(self)
        self._thumb_timer.setInterval(0)
        self._thumb_timer.timeout.connect(self._thumb_step)
        QtGui.QShortcut(QtGui.QKeySequence.Undo, self, self.undo_last)
        self.ok = self._load()
        log.info("PDF 편집 창 열기 %s (%d쪽) PDFEDIT_VER %s", self.path, len(self.items), PDFEDIT_VER)

    # ---------------------------------------------------- 만들기
    def _build_pages(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel(T("끌어서 순서 바꾸기 · Ctrl/Shift 로 여러 쪽 · 바깥에서 PDF·그림을 끌어 넣으면 그 자리에 끼워 넣기")))
        self.list = PageList()
        self.list.dropped.connect(self.insert_files)
        self.list.reordered.connect(self._sync_order)
        self.list.itemDoubleClicked.connect(lambda it: self.goto(self.list.row(it), annotate=True))
        QtGui.QShortcut(QtGui.QKeySequence.Delete, self.list, self.delete_sel)
        left.addWidget(self.list, 1)
        lay.addLayout(left, 1)
        col = QtWidgets.QVBoxLayout()
        for text, fn in ((T("⟲ 왼쪽으로 돌리기"), lambda: self.rotate_sel(-90)), (T("⟳ 오른쪽으로 돌리기"), lambda: self.rotate_sel(90)),
                         (T("쪽 지우기 (Del)"), self.delete_sel), (T("PDF·그림 끼워 넣기…"), self.insert_dialog),
                         (T("고른 쪽 빼서 새 파일…"), self.extract_sel)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            b.setMinimumWidth(b.sizeHint().width() + 8)   # 글자 잘리지 않게
            col.addWidget(b)
        col.addStretch(1)
        lay.addLayout(col)
        return w

    def _tool_btn(self, key, text, tip):
        b = QtWidgets.QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(True)
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b.clicked.connect(lambda *_: self.set_tool(key))
        self.tool_btns[key] = b
        return b

    def _build_annot(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        bar = QtWidgets.QHBoxLayout()
        self.tool_btns = {}
        for key, text, tip in (("ink", T("펜"), T("자유롭게 그리기")), ("hl", T("형광펜"), T("반투명 굵은 선 — 글자 위에 칠하기")),
                               ("text", T("글상자"), T("누른 곳에 글 쓰기 — Ctrl+Enter 또는 다른 곳 누르면 끝, Esc 취소")),
                               ("erase", T("지우개"), T("이번에 넣은 주석을 눌러 지우기"))):
            bar.addWidget(self._tool_btn(key, text, tip))
        bar.addSpacing(10)
        self.color_btns = []
        for c in COLORS:
            b = QtWidgets.QToolButton()
            b.setCheckable(True)
            b.setFixedSize(22, 22)
            b.setToolTip(c)
            b.setStyleSheet(f"QToolButton{{background:{c}; border:2px solid transparent; border-radius:11px;}}"
                            "QToolButton:checked{border:2px solid #1e88e5;}")
            b.clicked.connect(lambda *_, c=c: self.set_color(c))
            bar.addWidget(b)
            self.color_btns.append((c, b))
        bar.addSpacing(10)
        bar.addWidget(QtWidgets.QLabel(T("굵기")))
        self.sp_width = QtWidgets.QDoubleSpinBox()
        self.sp_width.setRange(0.5, 40)
        self.sp_width.setSingleStep(0.5)
        self.sp_width.setValue(2.0)
        self.sp_width.setSuffix(" pt")
        bar.addWidget(self.sp_width)
        bar.addWidget(QtWidgets.QLabel(T("글자 크기")))
        self.sp_text = QtWidgets.QSpinBox()
        self.sp_text.setRange(6, 72)
        self.sp_text.setValue(12)
        self.sp_text.setSuffix(" pt")
        bar.addWidget(self.sp_text)
        b_undo = QtWidgets.QToolButton()
        b_undo.setText(T("되돌리기"))
        b_undo.setToolTip("Ctrl+Z")
        b_undo.clicked.connect(self.undo_last)
        bar.addWidget(b_undo)
        bar.addStretch(1)
        self.b_prev = QtWidgets.QToolButton()
        self.b_prev.setText("◀")
        self.b_prev.setToolTip(T("이전 쪽"))
        self.b_prev.clicked.connect(lambda: self.goto(self.cur - 1))
        self.lbl_page = QtWidgets.QLabel()
        self.b_next = QtWidgets.QToolButton()
        self.b_next.setText("▶")
        self.b_next.setToolTip(T("다음 쪽"))
        self.b_next.clicked.connect(lambda: self.goto(self.cur + 1))
        for x in (self.b_prev, self.lbl_page, self.b_next):
            bar.addWidget(x)
        lay.addLayout(bar)
        self.sc = QtWidgets.QScrollArea()
        self.sc.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.sc.setBackgroundRole(QtGui.QPalette.Dark)
        self.canvas = PageCanvas(self)
        self.sc.setWidget(self.canvas)
        lay.addWidget(self.sc, 1)
        self.set_tool("ink")
        return w

    # ---------------------------------------------------- 읽기
    def _load(self):
        try:
            data = open(self.path, "rb").read()
            s = Src(data, os.path.basename(self.path))
        except pdftools.Locked:
            self._fail(T("암호가 걸린 PDF 는 다룰 수 없습니다:\n{0}").format(os.path.basename(self.path)))
            return False
        except Exception as ex:
            log.info("PDF 편집: 못 읽음 %s %s %s", self.path, type(ex).__name__, ex)
            self._fail(T("PDF 를 읽을 수 없습니다 (파일이 깨졌을 수 있음)") + "\n" + os.path.basename(self.path))
            return False
        if not HAVE_QTPDF:
            self._fail(T("PDF 그림 부품(QtPdf)이 없어 편집할 수 없습니다"))
            return False
        self.srcs.append(s)
        self.items = [PageItem(s, i) for i in range(len(s.reader.pages))]
        self._fill_list()
        self._update_info()
        return True

    def _fail(self, msg):
        self.info.setText("⚠ " + msg)
        self.tabs.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.btn_saveas.setEnabled(False)

    # ---------------------------------------------------- 쪽 목록
    def _fill_list(self, select=None):
        self.list.clear()
        ph = QtGui.QPixmap(THUMB, THUMB)
        ph.fill(QtGui.QColor("#eeeeee"))
        for i, it in enumerate(self.items):
            li = QtWidgets.QListWidgetItem(QtGui.QIcon(ph), self._label(i, it))
            li.setData(Qt.UserRole, id(it))
            li.setTextAlignment(Qt.AlignHCenter)
            self.list.addItem(li)
        self._thumb_q = list(range(len(self.items)))
        self._thumb_timer.start()
        if select:
            for r in select:
                if 0 <= r < self.list.count():
                    self.list.item(r).setSelected(True)

    def _label(self, i, it):
        extra = []
        if it.src is not self.srcs[0]:
            extra.append("+")
        if it.annots:
            extra.append("✎")
        return f"{i + 1}" + (" " + "".join(extra) if extra else "")

    def _thumb_step(self):
        if not self._thumb_q:
            self._thumb_timer.stop()
            return
        r = self._thumb_q.pop(0)
        if r < self.list.count() and r < len(self.items):
            self._set_thumb(r)

    def _set_thumb(self, r):
        it = self.items[r]
        cache = getattr(it, "_thumb", None)
        if cache is None:
            cache = it._thumb = render_base(it, THUMB * 2)
        img = rotated(cache, it.rot)
        if it.annots and not img.isNull():
            img = img.copy()
            p = QtGui.QPainter(img)
            paint_annots(p, it, img.width() / it.disp_size()[0])
            p.end()
        pm = QtGui.QPixmap.fromImage(framed(img, THUMB * 2))
        pm.setDevicePixelRatio(2)
        self.list.item(r).setIcon(QtGui.QIcon(pm))
        self.list.item(r).setText(self._label(r, it))

    def _sync_order(self):
        """끌어서 순서 바꾼 뒤 목록 순서를 쪽 목록에 반영"""
        by_id = {id(it): it for it in self.items}
        new = [by_id[self.list.item(r).data(Qt.UserRole)] for r in range(self.list.count())]
        if [id(x) for x in new] != [id(x) for x in self.items]:
            self.items = new
            self._mark()
            log.info("쪽 순서 바꿈")
            for r in range(self.list.count()):
                self.list.item(r).setText(self._label(r, self.items[r]))

    def sel_rows(self):
        return sorted(self.list.row(i) for i in self.list.selectedItems())

    def rotate_sel(self, deg):
        rows = self.sel_rows() or ([self.list.currentRow()] if self.list.currentRow() >= 0 else [])
        for r in rows:
            self.items[r].rot = (self.items[r].rot + deg) % 360
            self._set_thumb(r)
        if rows:
            self._mark()
            log.info("쪽 돌리기 %+d° %s", deg, [r + 1 for r in rows])

    def delete_sel(self):
        rows = self.sel_rows()
        if not rows:
            return
        if len(rows) >= len(self.items):
            QtWidgets.QMessageBox.information(self, self.windowTitle(), T("쪽을 모두 지울 수는 없습니다"))
            return
        self.items = [it for r, it in enumerate(self.items) if r not in set(rows)]
        self.undo = [(i, a) for i, a in self.undo if i in self.items]
        log.info("쪽 지우기 %s", [r + 1 for r in rows])
        self._fill_list(select=[min(rows[0], len(self.items) - 1)])
        self._mark()

    def insert_dialog(self):
        fs, _ = QtWidgets.QFileDialog.getOpenFileNames(self, T("PDF·그림 끼워 넣기"), os.path.dirname(self.path),
                                                       T("PDF·그림") + " (*.pdf *.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff *.gif)")
        if fs:
            rows = self.sel_rows()
            self.insert_files(fs, rows[-1] + 1 if rows else len(self.items))

    def insert_files(self, paths, at):
        new = []
        for p in paths:
            try:
                if pdftools.is_pdf(p):
                    s = Src(open(p, "rb").read(), os.path.basename(p))
                elif pdftools.is_image(p):
                    fd, tp = tempfile.mkstemp(prefix="4dir_img_", suffix=".pdf")
                    os.close(fd)
                    try:
                        if pdftools.images_to_pdf([p], tp) <= 0:
                            raise IOError(T("그림을 읽을 수 없습니다: {0}").format(os.path.basename(p)))
                        s = Src(open(tp, "rb").read(), os.path.basename(p))
                    finally:
                        try:
                            os.remove(tp)
                        except OSError:
                            pass
                else:
                    continue
            except Exception as ex:
                log.info("끼워 넣기 실패 %s %s", p, ex)
                QtWidgets.QMessageBox.warning(self, self.windowTitle(), pdftools._err_text(ex) + "\n" + os.path.basename(p))
                continue
            self.srcs.append(s)
            new += [PageItem(s, i) for i in range(len(s.reader.pages))]
        if not new:
            return
        at = max(0, min(at, len(self.items)))
        self.items[at:at] = new
        log.info("끼워 넣기 %d쪽 @%d (%s)", len(new), at + 1, [os.path.basename(p) for p in paths])
        self._fill_list(select=list(range(at, at + len(new))))
        self._mark()

    def extract_sel(self):
        rows = self.sel_rows()
        if not rows:
            QtWidgets.QMessageBox.information(self, self.windowTitle(), T("뺄 쪽을 먼저 고르세요"))
            return
        stem = os.path.splitext(self.path)[0]
        out = pdftools.unique_path(f"{stem}_{T('쪽')}{pdftools._range_label(rows)}.pdf")
        try:
            build_pdf([self.items[r] for r in rows], out)
        except Exception as ex:
            log.exception("빼기 실패")
            QtWidgets.QMessageBox.warning(self, self.windowTitle(), pdftools._err_text(ex))
            return
        self.info.setText(T("✔ {0}쪽을 새 파일로 뺐습니다: {1}").format(len(rows), out))

    # ---------------------------------------------------- 주석
    def set_tool(self, key):
        self.canvas.commit_text()
        self.tool = key
        for k, b in self.tool_btns.items():
            b.setChecked(k == key)
        c = self.colors.get(key)
        for cc, b in self.color_btns:
            b.setChecked(cc == c)
            b.setEnabled(key != "erase")
        self.sp_width.blockSignals(True)
        self.sp_width.setValue({"ink": 2.0, "hl": 12.0}.get(key, self.sp_width.value()))
        self.sp_width.blockSignals(False)
        self.canvas.setCursor(Qt.IBeamCursor if key == "text" else Qt.PointingHandCursor if key == "erase" else Qt.CrossCursor)

    def set_color(self, c):
        if self.tool in self.colors:
            self.colors[self.tool] = c
        for cc, b in self.color_btns:
            b.setChecked(cc == c)

    def color_for(self, tool):
        return self.colors.get(tool, COLORS[0])

    def width_for(self, tool):
        return float(self.sp_width.value())

    def text_size(self):
        return int(self.sp_text.value())

    def add_annot(self, item, a):
        item.annots.append(a)
        self.undo.append((item, a))
        self._mark()
        log.info("주석 넣기 %s %d쪽 (%s)", a["kind"], self.items.index(item) + 1,
                 f"{len(a['pts'])}점" if "pts" in a else repr(a.get("text", ""))[:40])

    def remove_annot(self, item, a):
        if a in item.annots:
            item.annots.remove(a)
            self.undo = [(i, x) for i, x in self.undo if x is not a]
            self._mark()
            log.info("주석 지우기 %s %d쪽", a["kind"], self.items.index(item) + 1)

    def undo_last(self):
        self.canvas.commit_text(cancel=True)
        while self.undo:
            item, a = self.undo.pop()
            if a in item.annots:
                item.annots.remove(a)
                self._mark()
                self.canvas.update()
                log.info("되돌리기 %s", a["kind"])
                return

    def goto(self, i, annotate=False):
        if not self.items:
            return
        self.cur = max(0, min(i, len(self.items) - 1))
        if annotate and self.tabs.currentIndex() != 1:
            self.tabs.setCurrentIndex(1)   # → _on_tab 이 보여 줌
            return
        self._show_page()

    def _on_tab(self, i):
        self.canvas.commit_text()
        if i == 1:
            rows = self.sel_rows()
            if rows and not (0 <= self.cur < len(self.items) and self.cur in rows):
                self.cur = rows[0]
            QtCore.QTimer.singleShot(0, self._show_page)
        else:
            for r in range(self.list.count()):
                self._set_thumb(r)

    def _show_page(self):
        if not self.items:
            return
        self.cur = max(0, min(self.cur, len(self.items) - 1))
        wpx = max(200, self.sc.viewport().width() - 24)
        it = self.items[self.cur]
        dw, dh = it.disp_size()
        if dh / dw * wpx > self.sc.viewport().height() * 1.6:   # 세로가 아주 길면 높이에 맞춤 쪽으로
            wpx = max(200, min(wpx, (self.sc.viewport().height() - 24) * dw / dh * 1.6))
        self.canvas.set_item(it, wpx)
        self.lbl_page.setText(f" {self.cur + 1} / {len(self.items)} ")
        self.b_prev.setEnabled(self.cur > 0)
        self.b_next.setEnabled(self.cur < len(self.items) - 1)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.tabs.currentIndex() == 1 and self.items:
            QtCore.QTimer.singleShot(0, self._show_page)

    # ---------------------------------------------------- 저장
    def _mark(self):
        self.dirty = True
        self._update_info()

    def _update_info(self):
        n_ann = sum(len(it.annots) for it in self.items)
        self.info.setText(T("모두 {0}쪽 · 넣은 주석 {1}개").format(len(self.items), n_ann) + ("  · " + T("저장 안 함") if self.dirty else ""))

    def save_as(self):
        self.canvas.commit_text()
        stem = os.path.splitext(self.path)[0]
        sug = pdftools.unique_path(f"{stem}_{T('편집')}.pdf")
        out, _ = QtWidgets.QFileDialog.getSaveFileName(self, T("다른 이름으로 저장"), sug, "PDF (*.pdf)")
        if out:
            self._save(out)

    def save_over(self):
        self.canvas.commit_text()
        if QtWidgets.QMessageBox.question(self, self.windowTitle(), T("원본 파일을 바꿉니다. 되돌릴 수 없습니다.\n{0}\n\n저장할까요?").format(self.path)) \
                != QtWidgets.QMessageBox.Yes:
            return
        self._save(self.path)

    def _save(self, out):
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            n = build_pdf(self.items, out)
        except PermissionError:
            log.info("저장 실패(사용 중) %s", out)
            QtWidgets.QMessageBox.warning(self, self.windowTitle(), T("파일을 다른 프로그램이 쓰고 있어 저장하지 못했습니다:\n{0}").format(out))
            return False
        except Exception as ex:
            log.exception("저장 실패")
            QtWidgets.QMessageBox.warning(self, self.windowTitle(), pdftools._err_text(ex))
            return False
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.dirty = False
        self._update_info()
        self.info.setText(self.info.text() + "  ·  " + T("✔ 저장했습니다: {0}").format(out))
        self.saved = out
        return n

    def closeEvent(self, ev):
        self.canvas.commit_text()
        if self.dirty:
            r = QtWidgets.QMessageBox.question(self, self.windowTitle(), T("저장하지 않은 편집이 있습니다. 저장하지 않고 닫을까요?"),
                                               QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
            if r != QtWidgets.QMessageBox.Yes:
                ev.ignore()
                return
        self._thumb_timer.stop()
        for s in self.srcs:
            s.close()
        log.info("PDF 편집 창 닫기 %s", self.path)
        super().closeEvent(ev)


def open_editor(parent, path, open_loc=None):
    d = PdfEditDialog(parent, path, open_loc)
    d.show()
    return d
