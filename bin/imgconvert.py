# -*- coding: utf-8 -*-
"""그림 변환 — 우클릭 'WebP 변환 → PNG로 저장 / JPG로 저장' (v0.9.66, 10/24 사용자 요청: webp → png·jpg; 메뉴는 webp 만, 함수는 png·jpg·gif 도 됨)

- Qt 그림 읽기·쓰기만 씀(부품: qwebp.dll·qjpeg.dll, 배포판 PySide6 plugins/imageformats). 프로그램 실행 없음.
- 원본은 그대로 둠(지우기는 사용자가 직접). 같은 이름이 있으면 덮어쓰지 않고 'name (1).png'.
- JPG 는 투명이 없음 → 투명한 곳은 흰 바탕. 움직이는 그림(webp·gif)은 첫 장면만.
- 뒤 스레드에서 불러도 됨(QImage 만 씀, QPixmap 안 씀).
"""
import os
import logging

from PySide6 import QtGui, QtCore

log = logging.getLogger("QE.imgconvert")
VERSION = "1.1.0"
SRC_EXT = {".webp", ".png", ".jpg", ".jpeg", ".bmp", ".gif"}
TARGET = {"png": ".png", "jpg": ".jpg"}
SAME = {"png": {".png"}, "jpg": {".jpg", ".jpeg"}}
JPG_QUALITY = 92


def can_convert(path):
    return os.path.splitext(path)[1].lower() in SRC_EXT and os.path.isfile(path)


def webp_only(paths):
    """우클릭 'WebP 변환' 대상 = webp 파일만 (1.1.0)"""
    return [p for p in paths if p.lower().endswith(".webp")]


def targets_for(paths, fmt):
    """fmt 로 바꿀 대상만 (이미 그 형식인 것·그림 아닌 것 뺌)"""
    return [p for p in paths if can_convert(p) and os.path.splitext(p)[1].lower() not in SAME[fmt]]


def _free_name(folder, stem, ext):
    out = os.path.join(folder, stem + ext)
    n = 1
    while os.path.exists(out):
        out = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return out


def convert(path, fmt):
    """그림 하나를 fmt('png'|'jpg') 로. 반환 (만든 경로, 움직이는 그림이었나). 실패하면 OSError"""
    r = QtGui.QImageReader(path)
    r.setAutoTransform(True)   # 사진 회전 정보(EXIF) 반영
    animated = r.supportsAnimation() and r.imageCount() > 1
    img = r.read()
    if img.isNull():
        raise OSError(f"읽지 못함: {r.errorString()}")
    if fmt == "jpg" and img.hasAlphaChannel():
        bg = QtGui.QImage(img.size(), QtGui.QImage.Format_RGB32)
        bg.fill(QtCore.Qt.white)
        p = QtGui.QPainter(bg)
        p.drawImage(0, 0, img)
        p.end()
        img = bg
    folder, name = os.path.split(path)
    out = _free_name(folder, os.path.splitext(name)[0], TARGET[fmt])
    ok = img.save(out, "JPG", JPG_QUALITY) if fmt == "jpg" else img.save(out, "PNG")
    if not ok:
        raise OSError("저장하지 못함 (쓰기 권한·디스크 공간 확인, 또는 그림 부품 없음)")
    log.info("변환 %s → %s (%dx%d, 움직임=%s)", path, out, img.width(), img.height(), animated)
    return out, animated


def convert_many(paths, fmt):
    """반환 (만든 경로들, 첫 장면만 쓴 개수, [(경로, 오류)])"""
    made, anim, fails = [], 0, []
    for p in targets_for(paths, fmt):
        try:
            out, a = convert(p, fmt)
            made.append(out)
            anim += a
        except Exception as ex:
            log.warning("변환 실패 %s: %s", p, ex)
            fails.append((p, str(ex)))
    return made, anim, fails
