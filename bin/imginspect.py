# -*- coding: utf-8 -*-
"""그림 자세히 보기·스포이트·두 그림 비교 (IMGINSPECT_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '게임 아트 작업자용 그림 자세히 보기·스포이트·두 그림 비교')

- open_viewer(parent, path): 휠 = 마우스 위치 기준 확대/축소(1/16 ~ 64배), 끌기 = 이동, [창에 맞춤] [1:1] [배율 ▾]
  4배 이상은 가장 가까운 픽셀로(뭉개지지 않게), 8배 이상은 픽셀 격자 선(끄기 가능). 투명한 곳은 회색 바둑판(밝은/어두운)
- 채널 [RGBA][R][G][B][A]: R/G/B = 그 채널을 회색으로, A = 불투명 흰색 ~ 투명 검정. 바이트 묶음 건너뛰기 자르기(bytes[2::4])로 만듦
  (파이썬 픽셀 반복 없음 — 4096x4096 실측 시간은 로그 '채널')
- 아래 줄: 마우스 아래 픽셀 x,y · RGBA · HEX(#RRGGBB, 반투명이면 #RRGGBBAA) · 그림 크기·비트 깊이·파일 크기
- 스포이트: 짧은 클릭 = 그 색을 '고른 색' 칸에 + HEX 클립보드 복사 + 알림. [RGB 복사] [HEX 복사], 최근 고른 색 8개(누르면 다시 복사)
- [주요 색 뽑기]: 64칸 이하로 줄인 뒤 색을 16단계로 묶어 많이 나온 순, 비슷한 색(거리 < 48)은 합침, 완전 투명 제외 → 6개
  [팔레트 PNG 저장] = 같은 폴더 '이름_palette.png' (있으면 '이름_palette (1).png'). 원본은 건드리지 않음
- 같은 폴더 이전/다음 그림: ← → 키 또는 단추 (이름 순, 숫자는 크기 순)
- open_compare(parent, a, b): [나란히] [겹쳐서 밀대] [차이](다른 픽셀 빨강 + 개수·비율). 크기가 다르면 안내 + 왼쪽 위 기준으로 맞춤
  두 쪽 확대·이동은 함께. 차이 계산 = 큰 정수 XOR + 건너뛰기 자르기(파이썬 픽셀 반복 없음)
- 그림 읽기·채널·차이 계산은 뒤 스레드(threading). 창을 닫으면 결과를 버리고 그림 메모리 반환. 쉬는 동안 타이머 없음
- 읽는 형식 = 이 Qt 가 읽을 수 있는 것(QImageReader.supportedImageFormats). PSD·EXR 등은 can_open() False
- 1.1.0 (0.9.116 빌드 4, 사용자 11/8 '따로 창을 열어야 되나? 미리보기 창에서 바로'): 미리보기 창 안 그림 = PreviewWidget
  (휠 확대·끌기 이동·짧은 클릭 스포이트(HEX 복사)·마우스 아래 x,y·HEX, [맞춤][1:1][배율][⤢ 큰 창]). main 미리보기 창이
  can_handle/make_widget 으로 붙임. 너무 큰 그림(PREVIEW_MAX_PX 넘음)은 예전처럼 윈도우 미리보기 그림만
- 1.2.0 (빌드 5, 사용자 11/8): 끌어서 그림이 화면 밖으로 나가던 것 → Canvas.clamp (작으면 창 안, 크면 가장자리가 창 안으로 못 들어옴).
  미리보기 창에 자세히 보기 기능 전부(이전/다음 = 파일 목록 선택을 옮김, 채널, 어두운 바둑판, 픽셀 격자, 고른 색·최근 색·주요 색·팔레트 저장,
  아래 줄 좌표·RGBA·HEX·크기·비트·용량). 채널·바둑판·격자·최근 색은 다음 그림에도 이어짐(_PSTATE)
- 1.4.0 (0.9.118 빌드 2, 사용자 11/8): [상세보기] → [색상 도구], 고른 색 = 'HEX #791110 [HEX 복사]' · 'R 121, G 17, B 16 [RGB 복사]' 두 줄,
  ◀ ▶ 는 그림 밖 양옆 칸으로(그림을 가리지 않음), ↺ ↻ 는 직접 그린 아이콘(rotate_icon), 연번 그림 재생 단추는 색상 도구 칸 안(seq 가 있을 때)
- 1.3.0 (0.9.118, 사용자 11/8): ◀ ▶ 를 그림 양옆(겹친 단추)으로, 맨 위 [상세보기] 단추 — 눌러야 채널·고른 색·최근·주요 색·팔레트가 보임
  (열고 닫은 상태 기억: main 이 PREF_GET/PREF_SET 으로 설정 preview_detail), 맞춤·1:1·배율·배경 어둡게·격자는 그림 아래 줄로.
  ↺ ↻ 회전 = 바로 파일에 저장(rotate_file): JPG 는 다시 압축하지 않고 EXIF 방향 값만 바꿈(화질 그대로, 다른 정보 유지),
  PNG·BMP·WebP 등 Qt 가 쓸 수 있는 형식은 돌린 그림으로 다시 저장(임시 파일 → 바꿔치기), 못 쓰는 형식(PSD·TGA 등)은 안내만
로그: bin\\log\\4Dir.log [QE.imginspect]
"""
import os
import re
import time
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

IMGINSPECT_VER = "1.5.1"   # 1.5.1: own_nav=False 면 자기 ◀ ▶ 숨김(미리보기 창 양끝 공용 단추 하나로) / 1.5.0 (0.9.129 사용자 11/10 미리보기 통일): − / + 단추, Canvas.set_pixmap(GIF·동영상 장면), zoom_buttons 공용 줄, ◀ ▶ = 폴더의 모든 파일
log = logging.getLogger("QE.imginspect")
P = QtCore.QPointF
R = QtCore.QRectF

ZOOMS = [1 / 16, 1 / 12, 1 / 8, 1 / 6, 1 / 4, 1 / 3, 1 / 2, 2 / 3, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64]
ZMIN, ZMAX = ZOOMS[0], ZOOMS[-1]
NEAREST_FROM = 4      # 이 배율 이상은 가장 가까운 픽셀로
GRID_FROM = 8         # 이 배율 이상은 격자 선
NEVER = {"psd", "psb", "exr", "hdr", "kra", "xcf", "tif", "tiff"}   # tif 는 이 Qt 에 플러그인 없음(있으면 아래에서 다시 켬)
_fmts = None


def _formats():
    global _fmts
    if _fmts is None:
        _fmts = {bytes(f).decode("ascii", "ignore").lower() for f in QtGui.QImageReader.supportedImageFormats()}
        _fmts |= {"jpeg", "jpg"} if "jpg" in _fmts or "jpeg" in _fmts else set()
        log.info("읽을 수 있는 그림 형식: %s", sorted(_fmts))
    return _fmts


def can_open(path):
    """이 창으로 열 수 있는 그림인지 (확장자만 보고 빠르게)"""
    ext = os.path.splitext(path or "")[1].lower().lstrip(".")
    if not ext:
        return False
    f = _formats()
    if ext in NEVER and ext not in f:
        return False
    return ext in f


# ---------------------------------------------------------------- 아이콘
def _icon_pm(draw, sz, dpr=2):
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(sz * dpr / 20.0, sz * dpr / 20.0)
    draw(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def _pen(col, w=1.2):
    return QtGui.QPen(QtGui.QColor(col), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)


def tool_icon(sz=16):
    """돋보기 + 스포이트"""
    def d(p):
        p.setPen(_pen("#1d4ed8", 1.3))
        p.setBrush(QtGui.QColor("#dbeafe"))
        p.drawEllipse(P(7.5, 7.5), 5.5, 5.5)
        p.setPen(_pen("#1d4ed8", 2.4))
        p.drawLine(P(11.6, 11.6), P(14.2, 14.2))
        # 스포이트 (오른쪽 위 → 왼쪽 아래 비스듬히)
        p.setPen(_pen("#374151", 1.0))
        p.setBrush(QtGui.QColor("#f97316"))
        p.drawPolygon(QtGui.QPolygonF([P(16.2, 9.0), P(19.0, 11.8), P(13.2, 17.6), P(10.4, 14.8)]))
        p.setPen(_pen("#374151", 1.6))
        p.drawLine(P(11.2, 16.8), P(9.4, 18.6))
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#e5484d"))
        p.drawEllipse(P(5.5, 6.0), 1.4, 1.4)
        p.setBrush(QtGui.QColor("#3fae68"))
        p.drawEllipse(P(9.0, 8.5), 1.4, 1.4)
    return QtGui.QIcon(_icon_pm(d, sz))


def rotate_icon(cw, color="#333333", sz=18):
    """둥근 화살표 (cw=True 오른쪽/시계, False 왼쪽/반시계) — 위쪽이 트인 원, 끝에서 도는 방향을 가리키는 화살촉 (20칸 기준 좌표)"""
    import math as _m

    def d(p):
        cx, cy, r = 10.0, 10.5, 6.2
        a0, a1 = (60.0, -240.0) if cw else (120.0, 420.0)   # 화면에서 보는 각도(0=오른쪽, 90=위). cw 는 줄어드는 쪽으로 돎
        n = 40
        pts = []
        for k in range(n + 1):
            f = _m.radians(a0 + (a1 - a0) * k / n)
            pts.append(P(cx + r * _m.cos(f), cy - r * _m.sin(f)))
        p.setPen(QtGui.QPen(QtGui.QColor(color), 2.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QtGui.QPolygonF(pts[:-2]))
        e, q = pts[-1], pts[-4]
        tx, ty = e.x() - q.x(), e.y() - q.y()
        ln = _m.hypot(tx, ty) or 1.0
        tx, ty = tx / ln, ty / ln
        nx, ny = -ty, tx
        tip = P(e.x() + tx * 2.6, e.y() + ty * 2.6)
        b1 = P(e.x() - tx * 2.2 + nx * 3.4, e.y() - ty * 2.2 + ny * 3.4)
        b2 = P(e.x() - tx * 2.2 - nx * 3.4, e.y() - ty * 2.2 - ny * 3.4)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor(color))
        p.drawPolygon(QtGui.QPolygonF([tip, b1, b2]))
    return QtGui.QIcon(_icon_pm(d, sz))


def checker_icon(color="#333333", sz=18):
    """바둑판 (어두운 칸 + 밝은 칸)"""
    def d(p):
        p.setPen(QtGui.QPen(QtGui.QColor(color), 1.0))
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawRect(R(3, 3, 14, 14))
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#555555"))
        p.drawRect(R(3, 3, 7, 7)); p.drawRect(R(10, 10, 7, 7))
    return QtGui.QIcon(_icon_pm(d, sz))


def grid_icon(color="#333333", sz=18):
    """픽셀 격자 (#)"""
    def d(p):
        p.setPen(QtGui.QPen(QtGui.QColor(color), 1.3))
        p.setBrush(Qt.NoBrush)
        p.drawRect(R(3, 3, 14, 14))
        for v in (7.67, 12.33):
            p.drawLine(P(v, 3), P(v, 17)); p.drawLine(P(3, v), P(17, v))
    return QtGui.QIcon(_icon_pm(d, sz))


def compare_icon(sz=16):
    """두 그림을 가운데 세로선으로 나눈 모양"""
    def d(p):
        p.setPen(_pen("#475569", 1.0))
        p.setBrush(QtGui.QColor("#60a5fa"))
        p.drawRect(R(2.5, 4.5, 7.5, 11))
        p.setBrush(QtGui.QColor("#fb923c"))
        p.drawRect(R(10, 4.5, 7.5, 11))
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawEllipse(P(6.2, 8.0), 1.4, 1.4)
        p.drawEllipse(P(13.8, 8.0), 1.4, 1.4)
        p.setPen(_pen("#111827", 1.6))
        p.drawLine(P(10, 2.0), P(10, 18.0))
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#111827"))
        p.drawPolygon(QtGui.QPolygonF([P(8.0, 10), P(10, 8.4), P(12.0, 10), P(10, 11.6)]))
    return QtGui.QIcon(_icon_pm(d, sz))


# ---------------------------------------------------------------- 그림 계산 (뒤 스레드에서 써도 됨 — QImage 만)
def load_image(path):
    """(원본 QImage, ARGB32 QImage, 오류글자). 원본은 비트 깊이 표시용"""
    t = time.perf_counter()
    rd = QtGui.QImageReader(path)
    rd.setAutoTransform(True)
    src = rd.read()
    if src.isNull():
        log.info("그림 못 읽음 %s : %s", path, rd.errorString())
        return None, None, rd.errorString()
    img = src.convertToFormat(QtGui.QImage.Format_ARGB32)
    log.info("그림 읽음 %s %dx%d 형식=%s %.0fms", path, img.width(), img.height(), src.format(), (time.perf_counter() - t) * 1000)
    return src, img, ""


def _raw(img):
    """ARGB32 바이트 (한 줄 = 4*가로, 메모리 순서 B,G,R,A)"""
    if img.format() != QtGui.QImage.Format_ARGB32:
        img = img.convertToFormat(QtGui.QImage.Format_ARGB32)
    b = bytes(img.constBits())
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    if bpl != w * 4:   # ARGB32 는 늘 4*가로지만 혹시 모를 때
        b = b"".join(b[y * bpl:y * bpl + w * 4] for y in range(h))
    return b


def _gray(data, w, h):
    return QtGui.QImage(data, w, h, w, QtGui.QImage.Format_Grayscale8).copy()


def channel_image(img, ch):
    """ch = 'R','G','B','A' → 회색 QImage. A: 불투명=흰, 투명=검정"""
    t = time.perf_counter()
    b = _raw(img)
    off = {"B": 0, "G": 1, "R": 2, "A": 3}[ch]
    out = _gray(b[off::4], img.width(), img.height())
    log.info("채널 %s %dx%d %.0fms", ch, img.width(), img.height(), (time.perf_counter() - t) * 1000)
    return out


def hex_of(c):
    s = "#%02X%02X%02X" % (c.red(), c.green(), c.blue())
    return s + ("%02X" % c.alpha() if c.alpha() < 255 else "")


def rgb_of(c):
    s = "%d, %d, %d" % (c.red(), c.green(), c.blue())
    return s + (", %d" % c.alpha() if c.alpha() < 255 else "")


def dominant_colors(img, n=6, merge=48):
    """[(QColor, 비율 0~1)] 많이 나온 순. 완전 투명 제외"""
    t = time.perf_counter()
    small = img
    if img.width() > 64 or img.height() > 64:
        small = img.scaled(64, 64, Qt.KeepAspectRatio, Qt.FastTransformation)
    b = _raw(small)
    buckets = {}
    for i in range(0, len(b), 4):
        if b[i + 3] == 0:
            continue
        bb, gg, rr = b[i], b[i + 1], b[i + 2]
        k = (rr >> 4, gg >> 4, bb >> 4)
        e = buckets.get(k)
        if e is None:
            buckets[k] = [1, rr, gg, bb]
        else:
            e[0] += 1; e[1] += rr; e[2] += gg; e[3] += bb
    total = sum(e[0] for e in buckets.values())
    chosen = []   # [count, r, g, b]
    for cnt, sr, sg, sb in sorted(buckets.values(), key=lambda e: -e[0]):
        r, g, bl = sr / cnt, sg / cnt, sb / cnt
        for c in chosen:
            if (c[1] - r) ** 2 + (c[2] - g) ** 2 + (c[3] - bl) ** 2 < merge * merge:
                c[0] += cnt
                break
        else:
            chosen.append([cnt, r, g, bl])
    chosen.sort(key=lambda c: -c[0])
    res = [(QtGui.QColor(round(c[1]), round(c[2]), round(c[3])), c[0] / total) for c in chosen[:n]] if total else []
    log.info("주요 색 %s (묶음 %d, 픽셀 %d, %.0fms)", [(hex_of(c), round(f, 3)) for c, f in res], len(buckets), total,
             (time.perf_counter() - t) * 1000)
    return res


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    k = 1
    while os.path.exists(f"{base} ({k}){ext}"):
        k += 1
    return f"{base} ({k}){ext}"


def save_palette(colors, src_path, cell=64):
    """색들을 가로 띠 PNG 로 같은 폴더 '이름_palette.png'. 저장한 경로 (실패 None)"""
    if not colors:
        return None
    base = os.path.splitext(os.path.basename(src_path))[0]
    out = unique_path(os.path.join(os.path.dirname(src_path), base + "_palette.png"))
    im = QtGui.QImage(cell * len(colors), cell, QtGui.QImage.Format_ARGB32)
    p = QtGui.QPainter(im)
    for i, c in enumerate(colors):
        p.fillRect(i * cell, 0, cell, cell, c)
    p.end()
    ok = im.save(out, "PNG")
    log.info("팔레트 저장 %s ok=%s 색=%s", out, ok, [hex_of(c) for c in colors])
    return out if ok else None


def pad_to(img, w, h):
    if img.width() == w and img.height() == h:
        return img
    out = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
    out.fill(0)
    p = QtGui.QPainter(out)
    p.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
    p.drawImage(0, 0, img)
    p.end()
    return out


_T255 = bytes([0] + [255] * 255)


def diff_image(a, b):
    """같은 크기 ARGB32 두 장 → (차이 그림 ARGB32, 다른 픽셀 수). 같은 곳 = A 를 흐리게, 다른 곳 = 빨강"""
    t = time.perf_counter()
    w, h = a.width(), a.height()
    npx = w * h
    ra, rb = _raw(a), _raw(b)
    x = (int.from_bytes(ra, "little") ^ int.from_bytes(rb, "little")).to_bytes(len(ra), "little")
    del ra, rb
    pix = (int.from_bytes(x[0::4], "little") | int.from_bytes(x[1::4], "little") |
           int.from_bytes(x[2::4], "little") | int.from_bytes(x[3::4], "little")).to_bytes(npx, "little")
    del x
    count = npx - pix.count(0)
    al = pix.translate(_T255)
    red = bytearray(npx * 4)
    red[2::4] = al
    red[3::4] = al
    redimg = QtGui.QImage(bytes(red), w, h, w * 4, QtGui.QImage.Format_ARGB32).copy()
    out = QtGui.QImage(w, h, QtGui.QImage.Format_RGB32)   # 흰 바탕 불투명 (바둑판 위면 빨강이 덜 보임)
    out.fill(QtGui.QColor("#ffffff"))
    p = QtGui.QPainter(out)
    p.setOpacity(0.25)
    p.drawImage(0, 0, a)
    p.setOpacity(1.0)
    p.drawImage(0, 0, redimg)
    p.end()
    log.info("차이 %dx%d 다른 픽셀 %d (%.3f%%) %.0fms", w, h, count, count * 100.0 / max(1, npx), (time.perf_counter() - t) * 1000)
    return out, count


def _natkey(s):
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", s)]


def folder_images(path):
    d = os.path.dirname(path)
    try:
        names = [e.name for e in os.scandir(d) if e.is_file() and can_open(e.name)]
    except OSError:
        log.exception("폴더 읽기 실패 %s", d)
        return [path]
    return [os.path.join(d, n) for n in sorted(names, key=_natkey)]


def _size_text(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024.0


def depth_text(src):
    F = QtGui.QImage
    f = src.format()
    if f in (F.Format_Indexed8, F.Format_Mono, F.Format_MonoLSB):
        return T("{0}비트 (색 목록)").format(src.depth())
    if f == F.Format_Grayscale8:
        return T("8비트 회색")
    if f == F.Format_Grayscale16:
        return T("16비트 회색")
    if f in (F.Format_RGBA64, F.Format_RGBA64_Premultiplied, F.Format_RGBX64):
        return T("채널당 16비트")
    if src.hasAlphaChannel():
        return T("32비트 (투명 있음)")
    return T("24비트")


# ---------------------------------------------------------------- 뒤 스레드 실행
class _Bridge(QtCore.QObject):
    done = QtCore.Signal(object)


class _Worker:
    """threading 으로 fn 실행 → 결과를 화면 스레드의 cb 로. 창을 닫으면(stop) 결과는 버림"""

    def __init__(self):
        self.bridge = _Bridge()
        self.bridge.done.connect(self._deliver)
        self.gen = 0
        self.alive = True

    def run(self, tag, fn, cb):
        g = self.gen

        def job():
            try:
                res = fn()
            except Exception as e:   # noqa
                log.exception("뒤 작업 실패 %s", tag)
                res = e
            if self.alive:
                try:
                    self.bridge.done.emit((g, tag, res, cb))
                except RuntimeError:
                    pass
        threading.Thread(target=job, name="imginspect-" + tag, daemon=True).start()

    def _deliver(self, pack):
        g, tag, res, cb = pack
        if not self.alive or g != self.gen:
            log.info("지난 결과 버림 %s", tag)
            return
        cb(res)

    def stop(self):
        self.alive = False
        self.gen += 1


# ---------------------------------------------------------------- 보기 상태 (여러 칸이 함께 씀)
class View(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.s = 1.0
        self.ox = 0.0
        self.oy = 0.0
        self.auto_fit = True

    def set(self, s, ox, oy):
        self.s, self.ox, self.oy = min(ZMAX, max(ZMIN, s)), ox, oy
        self.changed.emit()

    def zoom_at(self, s, px, py):
        s = min(ZMAX, max(ZMIN, s))
        ix, iy = (px - self.ox) / self.s, (py - self.oy) / self.s
        self.auto_fit = False
        self.set(s, px - ix * s, py - iy * s)

    def step(self, up, px, py):
        cur = self.s
        if up:
            nxt = next((z for z in ZOOMS if z > cur * 1.001), ZMAX)
        else:
            nxt = next((z for z in reversed(ZOOMS) if z < cur / 1.001), ZMIN)
        self.zoom_at(nxt, px, py)

    def fit(self, iw, ih, vw, vh):
        if iw <= 0 or ih <= 0 or vw <= 4 or vh <= 4:
            return
        s = min((vw - 8) / iw, (vh - 8) / ih)
        s = min(ZMAX, max(ZMIN, s))
        self.auto_fit = True
        self.set(s, (vw - iw * s) / 2, (vh - ih * s) / 2)

    def actual(self, iw, ih, vw, vh):
        self.auto_fit = False
        self.set(1.0, round((vw - iw) / 2), round((vh - ih) / 2))


def checker_brush(dark):
    c1, c2 = ("#3c3c3c", "#2a2a2a") if dark else ("#ffffff", "#cccccc")
    pm = QtGui.QPixmap(16, 16)
    pm.fill(QtGui.QColor(c1))
    p = QtGui.QPainter(pm)
    p.fillRect(0, 0, 8, 8, QtGui.QColor(c2))
    p.fillRect(8, 8, 8, 8, QtGui.QColor(c2))
    p.end()
    return QtGui.QBrush(pm)


class Canvas(QtWidgets.QWidget):
    """그림 한 장(또는 밀대 모드면 두 장)을 View 에 맞춰 그림. 휠=확대, 끌기=이동, 짧은 클릭=picked"""
    hovered = QtCore.Signal(int, int)   # 그림 밖이면 -1,-1
    picked = QtCore.Signal(int, int)

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        view.changed.connect(self.update)
        self.pm = None
        self.pm_b = None          # 밀대 모드 오른쪽 그림
        self.split = 0.5          # 밀대 위치 (창 가로 비율)
        self.iw = self.ih = 0
        self.dark_checker = False
        self._brush = checker_brush(False)
        self.grid = True
        self.message = ""
        self._press = None
        self._drag = None         # 'pan' / 'split'
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(160, 120)
        self.setCursor(Qt.CrossCursor)

    def set_image(self, img):
        self.pm = QtGui.QPixmap.fromImage(img) if img is not None else None
        if img is not None:
            self.iw, self.ih = img.width(), img.height()
        self.update()

    def set_pixmap(self, pm):
        """GIF·동영상 장면을 그대로 (1.5.0) — 크기가 같으면 확대·위치 유지, 처음·크기 바뀜 + 자동 맞춤이면 맞춤"""
        if pm is None or pm.isNull():
            self.pm = None
            self.update()
            return
        new = self.pm is None or (pm.width(), pm.height()) != (self.iw, self.ih)
        self.pm = pm
        self.iw, self.ih = pm.width(), pm.height()
        if new and self.view.auto_fit and self.width() > 4:
            self.view.fit(self.iw, self.ih, self.width(), self.height())
        self.update()

    def set_image_b(self, img):
        self.pm_b = QtGui.QPixmap.fromImage(img) if img is not None else None
        self.update()

    def set_checker(self, dark):
        self.dark_checker = dark
        self._brush = checker_brush(dark)
        self.update()

    def nearest(self):
        return self.view.s >= NEAREST_FROM

    def to_image(self, pos):
        v = self.view
        return int((pos.x() - v.ox) // v.s), int((pos.y() - v.oy) // v.s)

    def split_x(self):
        return self.width() * self.split

    def clamp(self):
        """1.2.0: 그림이 창보다 작으면 창 안에, 크면 가장자리가 창 안쪽으로 들어오지 않게 (끌어서 화면 밖으로 사라지지 않음)"""
        v = self.view
        if self.pm is None or self.iw <= 0:
            return
        W, H = self.width(), self.height()
        iw, ih = self.iw * v.s, self.ih * v.s

        def lim(o, size, view):
            return min(max(o, 0), view - size) if size <= view else min(max(o, view - size), 0)
        ox, oy = lim(v.ox, iw, W), lim(v.oy, ih, H)
        if (ox, oy) != (v.ox, v.oy):
            v.set(v.s, ox, oy)

    # --- 그리기
    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Base))
        if self.pm is None:
            if self.message:
                p.setPen(self.palette().color(QtGui.QPalette.Text))
                p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            p.end()
            return
        v = self.view
        s = v.s
        W, H = self.width(), self.height()
        x0 = max(0, int((0 - v.ox) // s)); y0 = max(0, int((0 - v.oy) // s))
        x1 = min(self.iw, int((W - v.ox) // s) + 1); y1 = min(self.ih, int((H - v.oy) // s) + 1)
        if x1 <= x0 or y1 <= y0:
            p.end()
            return
        tgt = R(v.ox + x0 * s, v.oy + y0 * s, (x1 - x0) * s, (y1 - y0) * s)
        srcr = R(x0, y0, x1 - x0, y1 - y0)
        p.save()
        p.setBrushOrigin(0, 0)
        p.fillRect(tgt, self._brush)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, not self.nearest())
        if self.pm_b is None:
            p.drawPixmap(tgt, self.pm, srcr)
        else:
            sx = self.split_x()
            p.setClipRect(R(0, 0, sx, H))
            p.drawPixmap(tgt, self.pm, srcr)
            p.setClipRect(R(sx, 0, W - sx, H))
            p.drawPixmap(tgt, self.pm_b, srcr)
            p.setClipping(False)
        p.restore()
        if self.grid and s >= GRID_FROM:
            p.setPen(QtGui.QPen(QtGui.QColor(128, 128, 128, 110), 1))
            lines = [QtCore.QLineF(v.ox + x * s, tgt.top(), v.ox + x * s, tgt.bottom()) for x in range(x0, x1 + 1)]
            lines += [QtCore.QLineF(tgt.left(), v.oy + y * s, tgt.right(), v.oy + y * s) for y in range(y0, y1 + 1)]
            p.drawLines(lines)
        if self.pm_b is not None:
            sx = self.split_x()
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 3))
            p.drawLine(P(sx, 0), P(sx, H))
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1))
            p.drawLine(P(sx, 0), P(sx, H))
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 180), 1))
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(P(sx, H / 2), 9, 9)
            p.setPen(QtGui.QPen(QtGui.QColor("#333333"), 1.5))
            p.drawLine(P(sx - 4, H / 2), P(sx - 1, H / 2 - 3)); p.drawLine(P(sx - 4, H / 2), P(sx - 1, H / 2 + 3))
            p.drawLine(P(sx + 4, H / 2), P(sx + 1, H / 2 - 3)); p.drawLine(P(sx + 4, H / 2), P(sx + 1, H / 2 + 3))
            f = p.font(); f.setBold(True); p.setFont(f)
            for txt, x, al in (("A", 6, Qt.AlignLeft), ("B", W - 26, Qt.AlignRight)):
                r = QtCore.QRectF(x, 4, 20, 18)
                p.setPen(Qt.NoPen); p.setBrush(QtGui.QColor(0, 0, 0, 140)); p.drawRoundedRect(r, 3, 3)
                p.setPen(QtGui.QColor("#ffffff")); p.drawText(r, Qt.AlignCenter, txt)
        p.end()

    # --- 마우스
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        self.setFocus()
        pos = e.position()
        self._press = (pos, self.view.ox, self.view.oy)
        self._drag = "split" if self.pm_b is not None and abs(pos.x() - self.split_x()) <= 8 else "pan"
        if self._drag == "pan":
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._press is not None and (e.buttons() & Qt.LeftButton):
            p0, ox, oy = self._press
            if self._drag == "split":
                self.split = min(1.0, max(0.0, pos.x() / max(1, self.width())))
                self.update()
            else:
                self.view.auto_fit = False
                self.view.set(self.view.s, ox + pos.x() - p0.x(), oy + pos.y() - p0.y())
                self.clamp()
        elif self.pm_b is not None:
            self.setCursor(Qt.SplitHCursor if abs(pos.x() - self.split_x()) <= 8 else Qt.CrossCursor)
        x, y = self.to_image(pos)
        if 0 <= x < self.iw and 0 <= y < self.ih and self.pm is not None:
            self.hovered.emit(x, y)
        else:
            self.hovered.emit(-1, -1)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press is None:
            return super().mouseReleaseEvent(e)
        p0 = self._press[0]
        pos = e.position()
        drag = self._drag
        self._press = None
        self._drag = None
        self.setCursor(Qt.CrossCursor)
        if drag == "pan" and abs(pos.x() - p0.x()) + abs(pos.y() - p0.y()) < 4:
            x, y = self.to_image(pos)
            if 0 <= x < self.iw and 0 <= y < self.ih and self.pm is not None:
                self.picked.emit(x, y)

    def leaveEvent(self, e):
        self.hovered.emit(-1, -1)

    def wheelEvent(self, e):
        if self.pm is None:
            return
        dy = e.angleDelta().y()
        if dy == 0:
            return
        pos = e.position()
        self.view.step(dy > 0, pos.x(), pos.y())
        self.clamp()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.view.auto_fit and self.pm is not None and self.isVisible():
            self.view.fit(self.iw, self.ih, self.width(), self.height())


# ---------------------------------------------------------------- 공용 작은 부품
def _tb(text, tip="", check=False):
    b = QtWidgets.QToolButton()
    b.setText(text)
    if tip:
        b.setToolTip(tip)
    b.setCheckable(check)
    b.setFocusPolicy(Qt.NoFocus)
    b.setAutoRaise(False)
    b.setObjectName("imgTb")
    return b


# 켜진 단추가 밝게·어둡게 둘 다 잘 보이게 (색은 palette 기준)
BTN_STYLE = ("QToolButton#imgTb{padding:2px 7px; border:1px solid palette(mid); border-radius:3px; background:palette(button);}"
             "QToolButton#imgTb:hover{border-color:palette(highlight);}"
             "QToolButton#imgTb:checked{background:palette(highlight); color:palette(highlighted-text); border-color:palette(highlight);}"
             "QToolButton#imgTb:disabled{color:palette(mid);}"
             "QToolButton#imgTb::menu-indicator{subcontrol-position:right center; right:3px;}"
             "QToolButton#imgTb[popupMode=\"2\"]{padding-right:14px;}")


class Swatch(QtWidgets.QToolButton):
    def __init__(self, sz=22, parent=None):
        super().__init__(parent)
        self.color = None
        self.setFixedSize(sz, sz)
        self.setFocusPolicy(Qt.NoFocus)
        self.set_color(None)

    def set_color(self, c):
        self.color = QtGui.QColor(c) if c is not None else None
        if c is None:
            self.setStyleSheet("QToolButton{border:1px dashed palette(mid); background:transparent;}")
            self.setToolTip("")
        else:
            self.setStyleSheet("QToolButton{border:1px solid palette(mid); background:%s;}" % self.color.name(QtGui.QColor.HexArgb))
            self.setToolTip(hex_of(self.color) + "   (" + rgb_of(self.color) + ")")


def _zoom_text(s):
    pc = s * 100
    return f"{pc:.0f}%" if pc >= 10 else (f"{pc:.2f}".rstrip("0").rstrip(".") + "%")


def zoom_buttons(view, canvas):
    """[맞춤][1:1][−][배율 ▾][+] — 미리보기 GIF·동영상 공용 (1.5.0, 그림 미리보기와 같은 모양·동작). 단추 목록을 돌려줌"""
    def fit():
        view.fit(canvas.iw, canvas.ih, canvas.width(), canvas.height())

    def one():
        view.actual(canvas.iw, canvas.ih, canvas.width(), canvas.height())
        canvas.clamp()

    def step(up):
        view.step(up, canvas.width() / 2, canvas.height() / 2)
        canvas.clamp()

    def setz(z):
        view.zoom_at(z, canvas.width() / 2, canvas.height() / 2)
        canvas.clamp()
    b_fit = _tb(T("맞춤"), T("창에 맞춤 (F)")); b_fit.clicked.connect(fit)
    b_one = _tb("1:1", T("실제 크기 (1)")); b_one.clicked.connect(one)
    b_out = _tb("−", T("축소")); b_out.clicked.connect(lambda: step(False))
    b_zoom = _ZoomButton(setz); b_zoom.setMinimumWidth(58)
    b_in = _tb("+", T("확대")); b_in.clicked.connect(lambda: step(True))
    view.changed.connect(lambda: b_zoom.setText(_zoom_text(view.s)))
    b_zoom.setText(_zoom_text(view.s))
    return [b_fit, b_one, b_out, b_zoom, b_in]


class _ZoomButton(QtWidgets.QToolButton):
    """확대 배율 표시 + 누르면 배율 고르기"""

    def __init__(self, on_pick, parent=None):
        super().__init__(parent)
        self.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName("imgTb")
        self.setToolTip(T("확대 배율"))
        m = QtWidgets.QMenu(self)
        for z in (1 / 4, 1 / 2, 1, 2, 4, 8, 16, 32, 64):
            m.addAction(_zoom_text(z), lambda z=z: on_pick(z))
        self.setMenu(m)
        self.setMinimumWidth(64)


def _notice_label():
    lb = QtWidgets.QLabel("")
    lb.setStyleSheet("QLabel{color:#1a7f37; font-weight:bold;}")
    return lb


# ---------------------------------------------------------------- 자세히 보기 창
class ImageViewer(QtWidgets.QWidget):
    def __init__(self, path, parent=None):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.path = path
        self.src = self.img = None
        self.chan = "RGBA"
        self.cache = {}
        self.disp = None
        self.picked = None
        self.recent = []
        self.main_colors = []
        self.worker = _Worker()
        self.view = View()
        self.view.changed.connect(self._on_view)
        self.setWindowIcon(tool_icon(20))
        self.setStyleSheet(BTN_STYLE)
        self.resize(980, 720)

        top = QtWidgets.QHBoxLayout(); top.setSpacing(3)
        self.b_prev = _tb("◀", T("이전 그림 (←)")); self.b_prev.clicked.connect(lambda: self.go(-1))
        self.b_next = _tb("▶", T("다음 그림 (→)")); self.b_next.clicked.connect(lambda: self.go(1))
        self.lb_pos = QtWidgets.QLabel("")
        self.b_fit = _tb(T("창에 맞춤")); self.b_fit.clicked.connect(self.fit)
        self.b_one = _tb(T("1:1 실제 크기")); self.b_one.clicked.connect(self.actual)
        self.b_zoom = _ZoomButton(self.set_zoom)
        self.b_zout = _tb("−", T("축소")); self.b_zout.clicked.connect(lambda: self._step(False))   # 1.5.0
        self.b_zin = _tb("+", T("확대")); self.b_zin.clicked.connect(lambda: self._step(True))
        for w in (self.b_prev, self.b_next, self.lb_pos):
            top.addWidget(w)
        top.addSpacing(10)
        for w in (self.b_fit, self.b_one, self.b_zout, self.b_zoom, self.b_zin):
            top.addWidget(w)
        top.addSpacing(10)
        self.ch_btns = {}
        grp = QtWidgets.QButtonGroup(self); grp.setExclusive(True)
        for ch in ("RGBA", "R", "G", "B", "A"):
            b = _tb(ch, T("채널 보기: {0}").format(ch), True)
            b.clicked.connect(lambda _=False, ch=ch: self.set_channel(ch))
            grp.addButton(b); top.addWidget(b); self.ch_btns[ch] = b
        self.ch_btns["RGBA"].setChecked(True)
        top.addSpacing(10)
        self.b_checker = _tb(T("어두운 바둑판"), T("투명한 곳 배경을 밝게/어둡게"), True)
        self.b_checker.toggled.connect(self._on_checker)
        self.b_grid = _tb(T("픽셀 격자"), T("8배 이상 확대하면 픽셀 경계선"), True)
        self.b_grid.setChecked(True)
        self.b_grid.toggled.connect(self._on_grid)
        top.addWidget(self.b_checker); top.addWidget(self.b_grid)
        top.addStretch(1)

        self.canvas = Canvas(self.view)
        self.canvas.hovered.connect(self._on_hover)
        self.canvas.picked.connect(self.pick)
        self.canvas.message = T("읽는 중…")

        # 색 줄
        colors = QtWidgets.QHBoxLayout(); colors.setSpacing(4)
        colors.addWidget(QtWidgets.QLabel(T("고른 색")))
        self.sw_pick = Swatch(26)
        self.sw_pick.clicked.connect(lambda: self.copy_hex())
        self.lb_pick = QtWidgets.QLabel("—")
        self.lb_pick.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lb_pick.setMinimumWidth(170)
        self.b_rgb = _tb(T("RGB 복사")); self.b_rgb.clicked.connect(self.copy_rgb)
        self.b_hex = _tb(T("HEX 복사")); self.b_hex.clicked.connect(self.copy_hex)
        for w in (self.sw_pick, self.lb_pick, self.b_rgb, self.b_hex):
            colors.addWidget(w)
        colors.addSpacing(10)
        colors.addWidget(QtWidgets.QLabel(T("최근")))
        self.sw_recent = []
        for i in range(8):
            s = Swatch(20)
            s.clicked.connect(lambda _=False, i=i: self._recopy(self.sw_recent[i]))
            colors.addWidget(s); self.sw_recent.append(s)
        colors.addSpacing(10)
        self.b_main = _tb(T("주요 색 뽑기"), T("그림에서 많이 쓰인 색 6개"))
        self.b_main.clicked.connect(self.extract_main)
        colors.addWidget(self.b_main)
        self.sw_main = []
        for i in range(6):
            s = Swatch(22)
            s.clicked.connect(lambda _=False, i=i: self._recopy(self.sw_main[i]))
            s.setVisible(False)
            colors.addWidget(s); self.sw_main.append(s)
        self.b_pal = _tb(T("팔레트 PNG 저장"), T("주요 색을 가로 띠 그림으로 같은 폴더에 저장"))
        self.b_pal.clicked.connect(self.save_palette)
        self.b_pal.setEnabled(False)
        colors.addWidget(self.b_pal)
        colors.addStretch(1)

        # 상태 줄
        st = QtWidgets.QHBoxLayout(); st.setSpacing(12)
        self.lb_xy = QtWidgets.QLabel("")
        self.lb_rgba = QtWidgets.QLabel("")
        self.lb_hex = QtWidgets.QLabel("")
        self.lb_notice = _notice_label()
        self.lb_info = QtWidgets.QLabel("")
        for w, mw in ((self.lb_xy, 90), (self.lb_rgba, 150), (self.lb_hex, 90)):
            w.setMinimumWidth(mw); st.addWidget(w)
        st.addWidget(self.lb_notice)
        st.addStretch(1)
        st.addWidget(self.lb_info)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 4); lay.setSpacing(4)
        lay.addLayout(top)
        lay.addWidget(self.canvas, 1)
        lay.addLayout(colors)
        lay.addLayout(st)
        self._notice_tm = QtCore.QTimer(self); self._notice_tm.setSingleShot(True)
        self._notice_tm.timeout.connect(lambda: self.lb_notice.setText(""))
        self.load(path)

    # --- 읽기
    def load(self, path):
        log.info("자세히 보기 열기 %s", path)
        self.path = path
        self.worker.gen += 1
        self.cache = {}
        self.main_colors = []
        for s in self.sw_main:
            s.setVisible(False)
        self.b_pal.setEnabled(False)
        self.setWindowTitle(os.path.basename(path) + " — " + T("그림 자세히 보기"))
        files = folder_images(path)
        nc = os.path.normcase
        idx = next((i for i, f in enumerate(files) if nc(f) == nc(path)), -1)
        self.files, self.idx = files, idx
        self.lb_pos.setText(f"{idx + 1} / {len(files)}  {os.path.basename(path)}" if idx >= 0 else os.path.basename(path))
        self.b_prev.setEnabled(idx > 0)
        self.b_next.setEnabled(0 <= idx < len(files) - 1)
        self.canvas.message = T("읽는 중…")
        self.worker.run("load", lambda: load_image(path), self._loaded)

    def _loaded(self, res):
        if isinstance(res, Exception):
            res = (None, None, str(res))
        src, img, err = res
        if img is None:
            self.src = self.img = self.disp = None
            self.canvas.set_image(None)
            self.canvas.message = T("이 그림을 읽을 수 없습니다") + ("\n" + err if err else "")
            self.lb_info.setText("")
            self.canvas.update()
            return
        self.src, self.img = src, img
        self.cache = {"RGBA": img}
        try:
            fsz = os.path.getsize(self.path)
        except OSError:
            fsz = 0
        self.lb_info.setText(f"{img.width()} x {img.height()} · {depth_text(src)} · {_size_text(fsz)}")
        self.canvas.message = ""
        self._show_channel(self.chan)
        self.fit()

    # --- 채널
    def set_channel(self, ch):
        log.info("채널 바꿈 %s", ch)
        self.chan = ch
        self.ch_btns[ch].setChecked(True)
        if self.img is None:
            return
        if ch in self.cache:
            self._show_channel(ch)
            return
        img = self.img
        self.worker.run("chan", lambda: channel_image(img, ch), lambda out, ch=ch: self._chan_done(ch, out))

    def _chan_done(self, ch, out):
        if isinstance(out, Exception):
            return
        self.cache[ch] = out
        if self.chan == ch:
            self._show_channel(ch)

    def _show_channel(self, ch):
        self.disp = self.cache.get(ch)
        self.canvas.set_image(self.disp)

    # --- 보기
    def fit(self):
        if self.img is not None:
            self.view.fit(self.img.width(), self.img.height(), self.canvas.width(), self.canvas.height())

    def actual(self):
        if self.img is not None:
            self.view.actual(self.img.width(), self.img.height(), self.canvas.width(), self.canvas.height())

    def set_zoom(self, z):
        self.view.zoom_at(z, self.canvas.width() / 2, self.canvas.height() / 2)

    def _on_view(self):
        self.b_zoom.setText(_zoom_text(self.view.s))

    def _step(self, up):   # 1.5.0 − / +
        self.view.step(up, self.canvas.width() / 2, self.canvas.height() / 2)
        self.canvas.clamp()

    def _on_checker(self, on):
        self.canvas.set_checker(on)

    def _on_grid(self, on):
        self.canvas.grid = on
        self.canvas.update()

    # --- 픽셀 정보·스포이트
    def color_at(self, x, y):
        return self.img.pixelColor(x, y)

    def _on_hover(self, x, y):
        if x < 0 or self.img is None:
            self.lb_xy.setText(""); self.lb_rgba.setText(""); self.lb_hex.setText("")
            return
        c = self.color_at(x, y)
        self.lb_xy.setText(f"x {x}, y {y}")
        self.lb_rgba.setText(f"RGBA {c.red()}, {c.green()}, {c.blue()}, {c.alpha()}")
        self.lb_hex.setText(hex_of(c))

    def notice(self, text):
        self.lb_notice.setText(text)
        self._notice_tm.start(2500)

    def _copy(self, text):
        QtWidgets.QApplication.clipboard().setText(text)
        self.notice(T("{0} 복사함").format(text))
        log.info("클립보드 복사 %s", text)

    def pick(self, x, y):
        if self.img is None:
            return
        c = self.color_at(x, y)
        log.info("스포이트 (%d,%d) %s", x, y, hex_of(c))
        self.set_picked(c)
        self._copy(hex_of(c))

    def set_picked(self, c):
        self.picked = QtGui.QColor(c)
        self.sw_pick.set_color(c)
        self.lb_pick.setText(f"{hex_of(c)}   ({rgb_of(c)})")
        self.recent = [k for k in self.recent if k.rgba() != c.rgba()]
        self.recent.insert(0, QtGui.QColor(c))
        self.recent = self.recent[:8]
        for i, s in enumerate(self.sw_recent):
            s.set_color(self.recent[i] if i < len(self.recent) else None)

    def copy_hex(self):
        if self.picked is not None:
            self._copy(hex_of(self.picked))

    def copy_rgb(self):
        if self.picked is not None:
            self._copy(rgb_of(self.picked))

    def _recopy(self, sw):
        if sw.color is not None:
            c = QtGui.QColor(sw.color)   # set_picked 가 칸 순서를 바꾸므로 먼저 잡아 둠
            self.set_picked(c)
            self._copy(hex_of(c))

    # --- 주요 색
    def extract_main(self):
        if self.img is None:
            return
        img = self.img
        self.b_main.setEnabled(False)
        self.worker.run("main", lambda: dominant_colors(img), self._main_done)

    def _main_done(self, res):
        self.b_main.setEnabled(True)
        if isinstance(res, Exception):
            return
        self.main_colors = [c for c, _ in res]
        for i, s in enumerate(self.sw_main):
            if i < len(res):
                s.set_color(res[i][0])
                s.setToolTip(f"{hex_of(res[i][0])}  {res[i][1] * 100:.1f}%")
            s.setVisible(i < len(res))
        self.b_pal.setEnabled(bool(res))
        if not res:
            self.notice(T("색이 있는 픽셀이 없습니다"))

    def save_palette(self):
        out = save_palette(self.main_colors, self.path)
        if out:
            self.notice(T("저장함: {0}").format(os.path.basename(out)))
        else:
            self.notice(T("저장하지 못했습니다"))
        self.last_palette = out
        return out

    # --- 이전/다음
    def go(self, d):
        if not getattr(self, "files", None) or self.idx < 0:
            return
        j = self.idx + d
        if 0 <= j < len(self.files):
            self.load(self.files[j])

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Left, Qt.Key_PageUp):
            self.go(-1)
        elif k in (Qt.Key_Right, Qt.Key_PageDown):
            self.go(1)
        elif k == Qt.Key_F:
            self.fit()
        elif k == Qt.Key_1:
            self.actual()
        elif k == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        log.info("자세히 보기 닫음 %s", self.path)
        self.worker.stop()
        self.cache = {}
        self.src = self.img = self.disp = None
        self.canvas.set_image(None)
        super().closeEvent(e)


def open_viewer(parent, path):
    w = ImageViewer(path, parent)
    w.show()
    return w


# ---------------------------------------------------------------- 비교 창
class CompareWindow(QtWidgets.QWidget):
    MODES = ("side", "slider", "diff")

    def __init__(self, path_a, path_b, parent=None):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.pa, self.pb = path_a, path_b
        self.ia = self.ib = None      # 맞춘(같은 크기) ARGB32
        self.diff = None
        self.diff_count = None
        self.mode = "side"
        self._loaded = {}
        self.worker = _Worker()
        self.view = View()
        self.view.changed.connect(lambda: self.b_zoom.setText(_zoom_text(self.view.s)))
        self.setWindowIcon(compare_icon(20))
        self.setStyleSheet(BTN_STYLE)
        self.setWindowTitle(f"{os.path.basename(path_a)}  ↔  {os.path.basename(path_b)} — " + T("두 그림 비교"))
        self.resize(1100, 700)

        top = QtWidgets.QHBoxLayout(); top.setSpacing(3)
        grp = QtWidgets.QButtonGroup(self); grp.setExclusive(True)
        self.mode_btns = {}
        for m, name in (("side", T("나란히")), ("slider", T("겹쳐서 밀대")), ("diff", T("차이"))):
            b = _tb(name, "", True)
            b.clicked.connect(lambda _=False, m=m: self.set_mode(m))
            grp.addButton(b); top.addWidget(b); self.mode_btns[m] = b
        self.mode_btns["side"].setChecked(True)
        top.addSpacing(10)
        self.b_fit = _tb(T("창에 맞춤")); self.b_fit.clicked.connect(self.fit)
        self.b_one = _tb(T("1:1 실제 크기")); self.b_one.clicked.connect(self.actual)
        self.b_zoom = _ZoomButton(self.set_zoom)
        self.b_checker = _tb(T("어두운 바둑판"), T("투명한 곳 배경을 밝게/어둡게"), True)
        self.b_checker.toggled.connect(self._on_checker)
        for w in (self.b_fit, self.b_one, self.b_zoom):
            top.addWidget(w)
        top.addSpacing(10)
        top.addWidget(self.b_checker)
        top.addSpacing(10)
        self.lb_warn = QtWidgets.QLabel("")
        self.lb_warn.setStyleSheet("QLabel{color:#c2410c; font-weight:bold;}")
        top.addWidget(self.lb_warn)
        top.addStretch(1)

        self.cv_a = Canvas(self.view); self.cv_b = Canvas(self.view)
        self.cv_s = Canvas(self.view); self.cv_d = Canvas(self.view)
        self.canvases = (self.cv_a, self.cv_b, self.cv_s, self.cv_d)
        for c in self.canvases:
            c.message = T("읽는 중…")
            c.hovered.connect(self._on_hover)
            c.grid = True
        side = QtWidgets.QWidget()
        sl = QtWidgets.QGridLayout(side); sl.setContentsMargins(0, 0, 0, 0); sl.setSpacing(4)
        self.lb_a = QtWidgets.QLabel("A: " + os.path.basename(path_a))
        self.lb_b = QtWidgets.QLabel("B: " + os.path.basename(path_b))
        sl.addWidget(self.lb_a, 0, 0); sl.addWidget(self.lb_b, 0, 1)
        sl.addWidget(self.cv_a, 1, 0); sl.addWidget(self.cv_b, 1, 1)
        sl.setRowStretch(1, 1)
        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(side); self.stack.addWidget(self.cv_s); self.stack.addWidget(self.cv_d)

        st = QtWidgets.QHBoxLayout(); st.setSpacing(12)
        self.lb_xy = QtWidgets.QLabel(""); self.lb_xy.setMinimumWidth(90)
        self.lb_px = QtWidgets.QLabel(""); self.lb_px.setMinimumWidth(260)
        self.lb_diff = QtWidgets.QLabel("")
        self.lb_info = QtWidgets.QLabel("")
        st.addWidget(self.lb_xy); st.addWidget(self.lb_px); st.addWidget(self.lb_diff)
        st.addStretch(1); st.addWidget(self.lb_info)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 4); lay.setSpacing(4)
        lay.addLayout(top)
        lay.addWidget(self.stack, 1)
        lay.addLayout(st)
        log.info("비교 열기 A=%s B=%s", path_a, path_b)
        self.worker.run("loadA", lambda: load_image(path_a), lambda r: self._one_loaded("a", r))
        self.worker.run("loadB", lambda: load_image(path_b), lambda r: self._one_loaded("b", r))

    def _one_loaded(self, k, res):
        if isinstance(res, Exception):
            res = (None, None, str(res))
        self._loaded[k] = res
        if len(self._loaded) < 2:
            return
        (_, a, ea), (_, b, eb) = self._loaded["a"], self._loaded["b"]
        if a is None or b is None:
            msg = T("이 그림을 읽을 수 없습니다") + "\n" + (self.pa if a is None else self.pb)
            for c in self.canvases:
                c.message = msg; c.update()
            return
        W, H = max(a.width(), b.width()), max(a.height(), b.height())
        if a.size() != b.size():
            self.lb_warn.setText(T("크기가 다름: A {0} · B {1} → 왼쪽 위 기준으로 맞춤").format(
                f"{a.width()}x{a.height()}", f"{b.width()}x{b.height()}"))
            log.info("크기 다름 A %dx%d B %dx%d → %dx%d", a.width(), a.height(), b.width(), b.height(), W, H)
        self.size_a, self.size_b = a.size(), b.size()
        self.ia, self.ib = pad_to(a, W, H), pad_to(b, W, H)
        self.lb_a.setText(f"A: {os.path.basename(self.pa)}  ({a.width()}x{a.height()})")
        self.lb_b.setText(f"B: {os.path.basename(self.pb)}  ({b.width()}x{b.height()})")
        self.lb_info.setText(f"{W} x {H}")
        self.cv_a.set_image(self.ia); self.cv_b.set_image(self.ib)
        self.cv_s.set_image(self.ia); self.cv_s.set_image_b(self.ib)
        for c in self.canvases:
            c.message = ""
        self.cv_d.message = T("차이 계산 중…")
        ia, ib = self.ia, self.ib
        self.worker.run("diff", lambda: diff_image(ia, ib), self._diff_done)
        self.fit()

    def _diff_done(self, res):
        if isinstance(res, Exception):
            self.cv_d.message = T("차이를 계산하지 못했습니다"); self.cv_d.update()
            return
        self.diff, self.diff_count = res
        self.cv_d.message = ""
        self.cv_d.set_image(self.diff)
        n = self.ia.width() * self.ia.height()
        if self.diff_count == 0:
            self.lb_diff.setText(T("두 그림이 같습니다"))
        else:
            self.lb_diff.setText(T("다른 픽셀 {0}개 ({1}%)").format(f"{self.diff_count:,}", f"{self.diff_count * 100.0 / n:.3f}"))

    def current_canvas(self):
        return {"side": self.cv_a, "slider": self.cv_s, "diff": self.cv_d}[self.mode]

    def set_mode(self, m):
        log.info("비교 보기 방식 %s", m)
        self.mode = m
        self.mode_btns[m].setChecked(True)
        self.stack.setCurrentIndex(self.MODES.index(m))
        if self.view.auto_fit:
            QtCore.QTimer.singleShot(0, self.fit)

    def fit(self):
        if self.ia is None:
            return
        c = self.current_canvas()
        self.view.fit(self.ia.width(), self.ia.height(), c.width(), c.height())

    def actual(self):
        if self.ia is None:
            return
        c = self.current_canvas()
        self.view.actual(self.ia.width(), self.ia.height(), c.width(), c.height())

    def set_zoom(self, z):
        c = self.current_canvas()
        self.view.zoom_at(z, c.width() / 2, c.height() / 2)

    def _on_checker(self, on):
        for c in self.canvases:
            c.set_checker(on)

    def _on_hover(self, x, y):
        if x < 0 or self.ia is None:
            self.lb_xy.setText(""); self.lb_px.setText("")
            return
        ca, cb = self.ia.pixelColor(x, y), self.ib.pixelColor(x, y)
        self.lb_xy.setText(f"x {x}, y {y}")
        same = "=" if ca.rgba() == cb.rgba() else "≠"
        self.lb_px.setText(f"A {hex_of(ca)}  {same}  B {hex_of(cb)}")

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_1:
            self.set_mode("side")
        elif k == Qt.Key_2:
            self.set_mode("slider")
        elif k == Qt.Key_3:
            self.set_mode("diff")
        elif k == Qt.Key_F:
            self.fit()
        elif k == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        log.info("비교 닫음")
        self.worker.stop()
        self.ia = self.ib = self.diff = None
        for c in self.canvases:
            c.set_image(None); c.set_image_b(None)
        super().closeEvent(e)


def open_compare(parent, path_a, path_b):
    w = CompareWindow(path_a, path_b, parent)
    w.show()
    return w


# ---------------------------------------------------------------- 회전 저장 (1.3.0)
import struct as _st

# EXIF 방향 값 ↔ (좌우 뒤집기 먼저 했나, 그다음 시계 방향 90도 몇 번)
_ORI = {1: (0, 0), 6: (0, 1), 3: (0, 2), 8: (0, 3), 2: (1, 0), 7: (1, 1), 4: (1, 2), 5: (1, 3)}
_ORI_BACK = {v: k for k, v in _ORI.items()}


def next_orientation(cur, cw):
    """지금 방향 값에 시계(cw=True)/반시계 90도를 더한 새 방향 값"""
    m, k = _ORI.get(cur or 1, (0, 0))
    return _ORI_BACK[(m, (k + (1 if cw else -1)) % 4)]


def _jpeg_segments(data):
    """(마커, 시작, 길이 포함 끝) — SOS 전까지"""
    if data[:2] != b"\xff\xd8":
        raise ValueError("JPEG 아님")
    i, out = 2, []
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            raise ValueError("JPEG 구조 이상 @%d" % i)
        mk = data[i + 1]
        if mk == 0xFF:
            i += 1
            continue
        if mk in (0xD8, 0x01) or 0xD0 <= mk <= 0xD7:
            i += 2
            continue
        ln = _st.unpack(">H", data[i + 2:i + 4])[0]
        out.append((mk, i, i + 2 + ln))
        if mk == 0xDA:
            break
        i += 2 + ln
    return out


def jpeg_rotate(path, cw):
    """JPG 를 다시 압축하지 않고 EXIF 방향(0x0112)만 바꿈 → 새 방향 값"""
    data = bytearray(open(path, "rb").read())
    segs = _jpeg_segments(data)
    exif = next(((a, b) for mk, a, b in segs if mk == 0xE1 and data[a + 4:a + 10] == b"Exif\x00\x00"), None)
    if exif is None:   # EXIF 없음 → 방향만 든 작은 EXIF 를 SOI(·JFIF) 뒤에 넣음
        new = next_orientation(1, cw)
        tiff = b"II*\x00" + _st.pack("<I", 8) + _st.pack("<H", 1) + _st.pack("<HHIHH", 0x0112, 3, 1, new, 0) + _st.pack("<I", 0)
        body = b"Exif\x00\x00" + tiff
        seg = b"\xff\xe1" + _st.pack(">H", len(body) + 2) + body
        at = next((b for mk, a, b in segs if mk == 0xE0), 2)
        data[at:at] = seg
        log.info("JPG 방향: EXIF 없음 → 새로 넣음 %d", new)
    else:
        a, b = exif
        t = a + 10                    # TIFF 머리 시작
        bo = "<" if data[t:t + 2] == b"II" else ">"
        ifd = _st.unpack(bo + "I", data[t + 4:t + 8])[0]
        n = _st.unpack(bo + "H", data[t + ifd:t + ifd + 2])[0]
        ent = None
        for j in range(n):
            e = t + ifd + 2 + j * 12
            if _st.unpack(bo + "H", data[e:e + 2])[0] == 0x0112:
                ent = e
                break
        if ent is not None:
            cur = _st.unpack(bo + "H", data[ent + 8:ent + 10])[0]
            new = next_orientation(cur, cw)
            data[ent + 8:ent + 10] = _st.pack(bo + "H", new)
            log.info("JPG 방향: %d → %d (EXIF 값만)", cur, new)
        else:   # 방향 항목이 없음 → IFD0 를 항목 하나 더해 APP1 끝에 새로 쓰고 가리키는 곳만 바꿈 (다른 정보 위치는 그대로)
            new = next_orientation(1, cw)
            entries = [bytes(data[t + ifd + 2 + j * 12:t + ifd + 2 + (j + 1) * 12]) for j in range(n)]
            nxt = bytes(data[t + ifd + 2 + n * 12:t + ifd + 2 + n * 12 + 4])
            entries.append(_st.pack(bo + "HHI", 0x0112, 3, 1) + _st.pack(bo + "HH", new, 0))
            entries.sort(key=lambda x: _st.unpack(bo + "H", x[:2])[0])
            tail = b - t
            pad = b"\x00" if tail % 2 else b""
            new_ifd = tail + len(pad)
            blob = pad + _st.pack(bo + "H", len(entries)) + b"".join(entries) + nxt
            if (b - a - 2) + len(blob) + 2 > 65533:
                raise ValueError("EXIF 가 너무 커서 방향을 넣을 수 없음")
            data[b:b] = blob
            data[t + 4:t + 8] = _st.pack(bo + "I", new_ifd)
            data[a + 2:a + 4] = _st.pack(">H", (b - a - 2) + len(blob))
            log.info("JPG 방향: 항목 없음 → IFD0 새로 (%d)", new)
    tmp = path + ".4dir_tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return new


def rotate_file(path, cw):
    """그림 파일을 90도 돌려 바로 저장 → (성공, 알림 글자)"""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    t0 = time.perf_counter()
    try:
        if ext in ("jpg", "jpeg", "jpe", "jfif"):
            jpeg_rotate(path, cw)
            log.info("회전 저장(JPG 무손실) %s %s %.0fms", path, "시계" if cw else "반시계", (time.perf_counter() - t0) * 1000)
            return True, T("돌려서 저장함 (화질 그대로)")
        writable = {bytes(f).decode("ascii", "ignore").lower() for f in QtGui.QImageWriter.supportedImageFormats()}
        if ext not in writable:
            log.info("회전 저장 못 함(쓸 수 없는 형식) %s", path)
            return False, T("이 형식은 돌려서 저장할 수 없습니다")
        with open(path, "rb") as f:   # 메모리로 읽음 — 읽기 부품이 파일을 잡고 있으면 바꿔치기(os.replace)가 막힘
            raw = f.read()
        buf = QtCore.QBuffer()
        buf.setData(QtCore.QByteArray(raw))
        buf.open(QtCore.QIODevice.ReadOnly)
        rd = QtGui.QImageReader(buf, ext.encode())
        rd.setAutoTransform(True)
        img = rd.read()
        del rd
        buf.close()
        if img.isNull():
            return False, T("이 그림을 읽을 수 없습니다")
        img = img.transformed(QtGui.QTransform().rotate(90 if cw else -90))
        tmp = path + ".4dir_tmp." + ext
        wr = QtGui.QImageWriter(tmp, ext.encode())
        if ext in ("webp",):
            wr.setQuality(100)
        okw = wr.write(img)
        err = wr.errorString()
        del wr   # 쓴 파일 닫기 (바꿔치기 전에)
        if not okw:
            try:
                os.remove(tmp)
            except OSError:
                pass
            log.warning("회전 저장 실패 %s: %s", path, err)
            return False, T("저장하지 못했습니다")
        os.replace(tmp, path)
        log.info("회전 저장(다시 저장) %s %s %.0fms", path, "시계" if cw else "반시계", (time.perf_counter() - t0) * 1000)
        return True, T("돌려서 저장함")
    except Exception as ex:
        log.exception("회전 저장 실패 %s", path)
        return False, T("저장하지 못했습니다") + f": {ex}"


# ---------------------------------------------------------------- 미리보기 창 안 (1.1.0)
PREVIEW_MAX_PX = 60_000_000   # 이보다 픽셀이 많으면 미리보기 창에서는 원본을 읽지 않음 (메모리·시간)


def can_handle(path):
    """main 미리보기 창이 물어봄 — 이 Qt 가 읽는 정지 그림이고 너무 크지 않으면 True (머리만 읽음, 빠름)"""
    if not can_open(path) or path.lower().endswith((".gif", ".ico")):
        return False
    try:
        sz = QtGui.QImageReader(path).size()
    except Exception:
        return False
    return sz.isValid() and 0 < sz.width() * sz.height() <= PREVIEW_MAX_PX


def make_widget(path, parent=None, nav=None, edit=None, seq=None, own_nav=True):
    w = PreviewWidget(path, parent, nav, edit, seq)
    w.own_nav = own_nav
    if not own_nav:   # 1.5.1 미리보기 창 양끝 공용 ◀ ▶ 를 씀 — 자기 단추는 자리도 안 차지
        for b in (w.b_prev, w.b_next):
            sp = b.sizePolicy(); sp.setRetainSizeWhenHidden(False); b.setSizePolicy(sp)
            b.setVisible(False)
    return w


# 다음 그림으로 넘어가도 이어지는 것 (미리보기 위젯은 파일마다 새로 만듦)
_PSTATE = {"chan": "RGBA", "dark": False, "grid": True, "recent": [], "picked": None, "focus": False, "detail": False}
PREVIEW_STYLE = BTN_STYLE + ("QToolButton#imgTb{padding:2px 6px;}"
                             "QToolButton#navBtn{background:rgba(0,0,0,70); color:white; border:none; border-radius:5px; font-size:15px;}"
                             "QToolButton#navBtn:hover{background:rgba(0,0,0,150);}")
PREF_GET = None   # main 이 설정 읽기·쓰기를 넣어 줌 (상세보기 열림 상태를 껐다 켜도 기억)
PREF_SET = None


def _pref(key, default):
    try:
        return PREF_GET(key, default) if PREF_GET else _PSTATE.get(key, default)
    except Exception:
        return default


class PreviewWidget(QtWidgets.QWidget):
    """미리보기 창 안 그림 (1.2.0 — 자세히 보기 창 기능 전부)
    휠 = 확대, 끌기 = 이동, 짧은 클릭 = 스포이트(HEX 복사), ← → = 이전/다음 그림(파일 목록 선택을 옮김), F = 맞춤, 1 = 1:1"""

    def __init__(self, path, parent=None, nav=None, edit=None, seq=None):
        super().__init__(parent)
        self.path = path
        self.edit = edit          # edit(경로): 그림 편집 창 (0.9.118)
        self.seq = seq            # seq(): 연번 그림 재생 (연번 그림일 때만)
        self.nav = nav            # nav(d): d 칸 옮김 (0 이면 안 옮김) → (지금 순번 0부터, 전체) 또는 None
        self.src = self.img = None
        self.cache = {}
        self.main_colors = []
        self.worker = _Worker()
        self.view = View()
        self.view.changed.connect(self._on_view)
        self.setStyleSheet(PREVIEW_STYLE)

        # 맨 위: [상세보기] — 눌러야 채널·색 도구가 보임 (열림 상태 기억)
        top = QtWidgets.QHBoxLayout(); top.setSpacing(3)
        self.b_detail = _tb(T("색상 도구"), T("채널·고른 색·최근 색·주요 색·팔레트 저장"), True)
        self.b_detail.setChecked(bool(_pref("preview_detail", False)))
        self.b_detail.toggled.connect(self._on_detail)
        top.addWidget(self.b_detail); top.addStretch(1)
        self.b_edit = _tb("✎ " + T("편집"), T("그림 편집 창 (자르기·글자·화살표·모자이크·밝기 등)"))   # 아래 줄은 좁아 위로
        self.b_edit.clicked.connect(lambda: self.edit and self.edit(self.path))
        self.b_edit.setVisible(edit is not None)
        top.addWidget(self.b_edit)

        # 상세 칸: 채널 / 고른 색 / 최근 / 주요 색
        self.detail = QtWidgets.QWidget()
        dl = QtWidgets.QVBoxLayout(self.detail); dl.setContentsMargins(0, 0, 0, 0); dl.setSpacing(4)
        r2 = QtWidgets.QHBoxLayout(); r2.setSpacing(3)
        self.ch_btns = {}
        grp = QtWidgets.QButtonGroup(self); grp.setExclusive(True)
        for ch in ("RGBA", "R", "G", "B", "A"):
            b = _tb(ch, T("채널 보기: {0}").format(ch), True)
            b.clicked.connect(lambda _=False, ch=ch: self.set_channel(ch))
            grp.addButton(b); r2.addWidget(b); self.ch_btns[ch] = b
        self.ch_btns[_PSTATE["chan"]].setChecked(True)
        r2.addStretch(1)
        r3 = QtWidgets.QGridLayout(); r3.setHorizontalSpacing(6); r3.setVerticalSpacing(3)
        r3.addWidget(QtWidgets.QLabel(T("고른 색")), 0, 0)
        self.sw_pick = Swatch(22); self.sw_pick.clicked.connect(self.copy_hex)
        r3.addWidget(self.sw_pick, 0, 1, 2, 1, Qt.AlignVCenter)
        self.lb_pick = QtWidgets.QLabel("HEX —"); self.lb_pick.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lb_rgb = QtWidgets.QLabel("R —, G —, B —"); self.lb_rgb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        for lb in (self.lb_pick, self.lb_rgb):
            lb.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.b_hex = _tb(T("HEX 복사"), T("#791110 같은 글자로 복사")); self.b_hex.clicked.connect(self.copy_hex)
        self.b_rgb = _tb(T("RGB 복사"), T("121, 17, 16 같은 숫자로 복사")); self.b_rgb.clicked.connect(self.copy_rgb)
        r3.addWidget(self.lb_pick, 0, 2); r3.addWidget(self.b_hex, 0, 3)
        r3.addWidget(self.lb_rgb, 1, 2); r3.addWidget(self.b_rgb, 1, 3)
        r3.setColumnStretch(2, 1)
        r4 = QtWidgets.QHBoxLayout(); r4.setSpacing(3)
        r4.addWidget(QtWidgets.QLabel(T("최근")))
        self.sw_recent = []
        for i in range(8):
            sw = Swatch(20); sw.clicked.connect(lambda _=False, i=i: self._recopy(self.sw_recent[i]))
            r4.addWidget(sw); self.sw_recent.append(sw)
        r4.addStretch(1)
        r5 = QtWidgets.QHBoxLayout(); r5.setSpacing(3)
        self.b_main = _tb(T("주요 색 뽑기"), T("그림에서 많이 쓰인 색 6개")); self.b_main.clicked.connect(self.extract_main)
        r5.addWidget(self.b_main)
        self.sw_main = []
        for i in range(6):
            sw = Swatch(20); sw.clicked.connect(lambda _=False, i=i: self._recopy(self.sw_main[i])); sw.setVisible(False)
            r5.addWidget(sw); self.sw_main.append(sw)
        r5.addStretch(1)
        self.b_pal = _tb(T("팔레트 PNG 저장"), T("주요 색을 가로 띠 그림으로 같은 폴더에 저장"))
        self.b_pal.clicked.connect(self.save_palette); self.b_pal.setEnabled(False)
        r5.addWidget(self.b_pal)
        for r in (r2, r3, r4, r5):
            dl.addLayout(r)
        self.b_seq = _tb("▶ " + T("연번 그림 재생"), T("이름에 번호가 이어진 그림들을 영상처럼 재생"))
        self.b_seq.clicked.connect(lambda: self.seq and self.seq())
        self.b_seq.setVisible(seq is not None)
        r6 = QtWidgets.QHBoxLayout(); r6.addWidget(self.b_seq); r6.addStretch(1)
        dl.addLayout(r6)
        self.detail.setVisible(self.b_detail.isChecked())

        # 그림 + 양옆 ◀ ▶ (그림 위에 겹침)
        self.canvas = Canvas(self.view)
        self.canvas.setMinimumSize(120, 100)
        self.canvas.message = T("읽는 중…")
        self.canvas.hovered.connect(self._on_hover)
        self.canvas.picked.connect(self.pick)
        self.canvas.setToolTip(T("휠 = 확대·축소, 끌기 = 이동, 클릭 = 그 색 복사 (스포이트)"))
        self.canvas.installEventFilter(self)
        self.b_prev = QtWidgets.QToolButton(); self.b_prev.setObjectName("navBtn"); self.b_prev.setText("◀")
        self.b_next = QtWidgets.QToolButton(); self.b_next.setObjectName("navBtn"); self.b_next.setText("▶")
        for b, tip, d in ((self.b_prev, T("이전 파일 (←)"), -1), (self.b_next, T("다음 파일 (→)"), 1)):   # 1.5.0 폴더의 모든 파일   # 1.4.0: 그림 밖 양옆 (그림을 가리지 않음)
            b.setToolTip(tip); b.setFixedSize(22, 64); b.setFocusPolicy(Qt.NoFocus); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, d=d: self.go(d))
            sp = b.sizePolicy(); sp.setRetainSizeWhenHidden(True); b.setSizePolicy(sp)   # 끝 그림에서 숨어도 자리는 그대로 (그림이 들썩이지 않게)
        mid = QtWidgets.QHBoxLayout(); mid.setSpacing(3)
        mid.addWidget(self.b_prev, 0, Qt.AlignVCenter); mid.addWidget(self.canvas, 1); mid.addWidget(self.b_next, 0, Qt.AlignVCenter)
        self.pos_text = ""

        # 그림 아래: 정보 줄 / 맞춤 1:1 배율 ↺ ↻ · 배경 어둡게 격자
        self.lb_st = QtWidgets.QLabel("")
        self.lb_st.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.lb_st.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bot = QtWidgets.QHBoxLayout(); bot.setSpacing(3)
        self.b_fit = _tb(T("맞춤"), T("창에 맞춤 (F)")); self.b_fit.clicked.connect(self.fit)
        self.b_one = _tb("1:1", T("실제 크기 (1)")); self.b_one.clicked.connect(self.actual)
        self.b_zoom = _ZoomButton(self.set_zoom); self.b_zoom.setMinimumWidth(58)
        self.b_zout = _tb("−", T("축소")); self.b_zout.clicked.connect(lambda: self._step(False))   # 1.5.0 (사용자 '확대 축소 단추가 없다')
        self.b_zin = _tb("+", T("확대")); self.b_zin.clicked.connect(lambda: self._step(True))
        self.b_rl = _tb("", T("왼쪽으로 돌리기 (바로 저장)")); self.b_rl.clicked.connect(lambda: self.rotate(False))
        self.b_rr = _tb("", T("오른쪽으로 돌리기 (바로 저장)")); self.b_rr.clicked.connect(lambda: self.rotate(True))
        fg = self.palette().color(QtGui.QPalette.ButtonText).name()
        self.b_rl.setIcon(rotate_icon(False, fg)); self.b_rr.setIcon(rotate_icon(True, fg))
        for b_ in (self.b_rl, self.b_rr):
            b_.setIconSize(QtCore.QSize(18, 18))
        self.b_checker = _tb("", T("배경 어둡게") + " — " + T("투명한 곳 뒤에 까는 바둑판을 어둡게 (밝은 그림의 가장자리 확인용)"), True)
        self.b_grid = _tb("", T("픽셀 격자 — 8배 이상 확대하면 픽셀 경계선"), True)
        self.b_checker.setIcon(checker_icon(fg)); self.b_grid.setIcon(grid_icon(fg))   # 좁은 창에서 글자 단추가 잘려 그림 단추로
        for b_ in (self.b_checker, self.b_grid):
            b_.setIconSize(QtCore.QSize(18, 18))
        for w in (self.b_fit, self.b_one, self.b_zout, self.b_zoom, self.b_zin):
            bot.addWidget(w)
        bot.addSpacing(6); bot.addWidget(self.b_rl); bot.addWidget(self.b_rr)

        bot.addStretch(1); bot.addWidget(self.b_checker); bot.addWidget(self.b_grid)
        self.b_checker.setChecked(_PSTATE["dark"]); self.canvas.set_checker(_PSTATE["dark"])
        self.b_grid.setChecked(_PSTATE["grid"]); self.canvas.grid = _PSTATE["grid"]
        self.b_checker.toggled.connect(self._on_checker)
        self.b_grid.toggled.connect(self._on_grid)

        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(4)
        lay.addLayout(top)
        lay.addWidget(self.detail)
        lay.addLayout(mid, 1)
        lay.addWidget(self.lb_st)
        lay.addLayout(bot)
        fm = self.fontMetrics()   # 좁은 창에서 한글 단추 글자가 '배…게' 처럼 잘리던 것 — 글자 폭만큼은 늘 확보
        for b in self.findChildren(QtWidgets.QToolButton):
            if b.objectName() == "imgTb" and b.text() and not isinstance(b, (Swatch, _ZoomButton)):
                b.setMinimumWidth(fm.horizontalAdvance(b.text()) + 16)
        self.info = ""
        self._msg = ""
        self._tm = QtCore.QTimer(self); self._tm.setSingleShot(True)
        self._tm.timeout.connect(lambda: self._set_msg(""))
        self._show_recent()
        if _PSTATE["picked"] is not None:
            self._show_picked(_PSTATE["picked"])
        self._update_pos()
        log.info("미리보기 창 그림 %s 채널 %s", path, _PSTATE["chan"])
        self.worker.run("pload", lambda: load_image(path), self._loaded)

    # --- 읽기
    def _loaded(self, res):
        if isinstance(res, Exception):
            res = (None, None, str(res))
        src, img, err = res
        if img is None:
            self.canvas.message = T("이 그림을 읽을 수 없습니다")
            self.canvas.set_image(None)
            return
        self.src, self.img = src, img
        self.cache = {"RGBA": img}
        try:
            fsz = os.path.getsize(self.path)
        except OSError:
            fsz = 0
        self.info_img = f"{img.width()} x {img.height()} · {depth_text(src)} · {_size_text(fsz)}"
        self.info = (self.pos_text + "   " if self.pos_text else "") + self.info_img
        self._set_msg("")
        self.canvas.message = ""
        if _PSTATE["chan"] == "RGBA":
            self.canvas.set_image(img)
        else:
            self.set_channel(_PSTATE["chan"])
        self.fit()

    def showEvent(self, e):
        super().showEvent(e)
        if _PSTATE["focus"]:   # ← → 로 넘어왔으면 계속 키로 넘길 수 있게
            self.canvas.setFocus()
        QtCore.QTimer.singleShot(0, self.fit)

    # --- 이전/다음 (파일 목록의 선택을 옮김 → 미리보기 창이 새 그림으로)
    def _update_pos(self):
        info = self.nav(0) if self.nav else None
        if not info:
            self.pos_text = ""
            self.b_prev.setVisible(False); self.b_next.setVisible(False)
            return
        i, n = info
        self.pos_text = f"{i + 1} / {n}"
        own = getattr(self, "own_nav", True)
        self.b_prev.setVisible(own and i > 0); self.b_next.setVisible(own and i < n - 1)

    def _on_detail(self, on):
        """상세보기 열고 닫기 — 상태 기억"""
        self.detail.setVisible(on)
        _PSTATE["detail"] = on
        try:
            if PREF_SET:
                PREF_SET("preview_detail", bool(on))
        except Exception:
            log.exception("상세보기 상태 저장 실패")
        log.info("미리보기 상세보기 %s", "열기" if on else "닫기")
        QtCore.QTimer.singleShot(0, self.fit)

    def rotate(self, cw):
        """90도 돌려 바로 파일에 저장 (JPG 는 화질 그대로) — 화면 그림도 같이 돌림"""
        ok, msg = rotate_file(self.path, cw)
        self._notice(msg)
        if ok and self.img is not None:
            tr = QtGui.QTransform().rotate(90 if cw else -90)
            self.img = self.img.transformed(tr)
            self.src = self.src.transformed(tr) if self.src is not None else None
            self.cache = {"RGBA": self.img}
            if _PSTATE["chan"] == "RGBA":
                self.canvas.set_image(self.img)
            else:
                self.set_channel(_PSTATE["chan"])
            try:
                fsz = os.path.getsize(self.path)
            except OSError:
                fsz = 0
            self.info_img = f"{self.img.width()} x {self.img.height()} · {depth_text(self.src or self.img)} · {_size_text(fsz)}"
            self.info = (self.pos_text + "   " if self.pos_text else "") + self.info_img
            self.fit()
        return ok

    def go(self, d):
        if self.nav:
            _PSTATE["focus"] = self.canvas.hasFocus() or _PSTATE["focus"]
            log.info("미리보기 %s 그림", "다음" if d > 0 else "이전")
            self.nav(d)

    # --- 채널·보기
    def set_channel(self, ch):
        _PSTATE["chan"] = ch
        self.ch_btns[ch].setChecked(True)
        if self.img is None:
            return
        if ch in self.cache:
            self.canvas.set_image(self.cache[ch])
            return
        img = self.img
        self.worker.run("chan", lambda: channel_image(img, ch), lambda out, ch=ch: self._chan_done(ch, out))

    def _chan_done(self, ch, out):
        if isinstance(out, Exception):
            return
        self.cache[ch] = out
        if _PSTATE["chan"] == ch:
            self.canvas.set_image(out)

    def _on_checker(self, on):
        _PSTATE["dark"] = on
        self.canvas.set_checker(on)

    def _on_grid(self, on):
        _PSTATE["grid"] = on
        self.canvas.grid = on
        self.canvas.update()

    def fit(self):
        if self.img is not None:
            self.view.fit(self.img.width(), self.img.height(), self.canvas.width(), self.canvas.height())

    def actual(self):
        if self.img is not None:
            self.view.actual(self.img.width(), self.img.height(), self.canvas.width(), self.canvas.height())
            self.canvas.clamp()

    def set_zoom(self, z):
        self.view.zoom_at(z, self.canvas.width() / 2, self.canvas.height() / 2)
        self.canvas.clamp()

    def _step(self, up):   # 1.5.0 − / +
        self.view.step(up, self.canvas.width() / 2, self.canvas.height() / 2)
        self.canvas.clamp()

    def _on_view(self):
        self.b_zoom.setText(_zoom_text(self.view.s))

    # --- 아래 줄
    def _set_msg(self, t):
        self._msg = t
        self.lb_st.setStyleSheet("QLabel{color:#1a7f37; font-weight:bold;}" if t else "")
        self.lb_st.setText(t or self.info)

    def _on_hover(self, x, y):
        if self._msg:
            return
        if x < 0 or self.img is None:
            self.lb_st.setText(self.info)
            return
        c = self.img.pixelColor(x, y)
        self.lb_st.setText(f"x {x}, y {y}   RGBA {c.red()}, {c.green()}, {c.blue()}, {c.alpha()}   {hex_of(c)}")

    def _notice(self, t):
        self._set_msg(t)
        self._tm.start(2000)

    # --- 스포이트·색
    def _copy(self, text):
        QtWidgets.QApplication.clipboard().setText(text)
        self._notice(T("{0} 복사함").format(text))
        log.info("미리보기 클립보드 %s", text)

    def pick(self, x, y):
        if self.img is None:
            return
        c = self.img.pixelColor(x, y)
        log.info("미리보기 스포이트 (%d,%d) %s", x, y, hex_of(c))
        self._set_picked(c)
        self._copy(hex_of(c))

    def _show_picked(self, c):
        self.sw_pick.set_color(c)
        self.lb_pick.setText("HEX  " + hex_of(c))
        self.lb_rgb.setText(f"R {c.red()},  G {c.green()},  B {c.blue()}" + (f",  A {c.alpha()}" if c.alpha() < 255 else ""))

    def _show_recent(self):
        rc = _PSTATE["recent"]
        for i, sw in enumerate(self.sw_recent):
            sw.set_color(rc[i] if i < len(rc) else None)

    def _set_picked(self, c):
        c = QtGui.QColor(c)
        _PSTATE["picked"] = c
        rc = [k for k in _PSTATE["recent"] if k.rgba() != c.rgba()]
        rc.insert(0, c)
        _PSTATE["recent"] = rc[:8]
        self._show_picked(c)
        self._show_recent()

    def copy_hex(self):
        if _PSTATE["picked"] is not None:
            self._copy(hex_of(_PSTATE["picked"]))

    def copy_rgb(self):
        if _PSTATE["picked"] is not None:
            self._copy(rgb_of(_PSTATE["picked"]))

    def _recopy(self, sw):
        if sw.color is not None:
            c = QtGui.QColor(sw.color)
            self._set_picked(c)
            self._copy(hex_of(c))

    def extract_main(self):
        if self.img is None:
            return
        img = self.img
        self.b_main.setEnabled(False)
        self.worker.run("main", lambda: dominant_colors(img), self._main_done)

    def _main_done(self, res):
        self.b_main.setEnabled(True)
        if isinstance(res, Exception):
            return
        self.main_colors = [c for c, _ in res]
        for i, sw in enumerate(self.sw_main):
            if i < len(res):
                sw.set_color(res[i][0])
                sw.setToolTip(f"{hex_of(res[i][0])}  {res[i][1] * 100:.1f}%")
            sw.setVisible(i < len(res))
        self.b_pal.setEnabled(bool(res))
        if not res:
            self._notice(T("색이 있는 픽셀이 없습니다"))

    def save_palette(self):
        out = save_palette(self.main_colors, self.path)
        self._notice(T("저장함: {0}").format(os.path.basename(out)) if out else T("저장하지 못했습니다"))
        self.last_palette = out
        return out

    # --- 키
    def eventFilter(self, obj, e):
        if obj is self.canvas and e.type() == QtCore.QEvent.KeyPress:
            k = e.key()
            if k in (Qt.Key_Left, Qt.Key_PageUp):
                self.go(-1); return True
            if k in (Qt.Key_Right, Qt.Key_PageDown):
                self.go(1); return True
            if k == Qt.Key_F:
                self.fit(); return True
            if k == Qt.Key_1:
                self.actual(); return True
        if obj is self.canvas and e.type() == QtCore.QEvent.FocusOut:
            _PSTATE["focus"] = False
        return super().eventFilter(obj, e)

    def hideEvent(self, e):
        """미리보기 창이 다른 파일로 바뀌거나 숨으면 결과·그림 메모리 버림"""
        self.worker.stop()
        self.cache = {}
        self.src = self.img = None
        self.canvas.set_image(None)
        super().hideEvent(e)
