# -*- coding: utf-8 -*-
"""정렬용 파일 속성 (SHELLPROPS_VER 1.0.0, v0.9.75 사용자 의견: 정렬 기준에 날짜·길이·만든 날짜·미디어 작성 날짜·사진 크기)

- 윈도우 탐색기와 같은 값: 윈도우 속성 시스템(IPropertyStore)에서 읽음 — 날짜(System.ItemDate)·길이(System.Media.Duration)·
  미디어 작성 날짜(System.Media.DateEncoded)·사진 크기(System.Image.HorizontalSize×VerticalSize)
- 느린 셸 읽기는 그림·영상·소리 확장자만 (나머지 파일은 값 없음 → 탐색기처럼 정렬 맨 뒤, 날짜는 수정한 날짜)
- 결과는 (경로, 수정 시각) 기준으로 기억 → 같은 폴더 다시 정렬은 바로
"""
import os
import time
import logging

log = logging.getLogger("QE")

SHELLPROPS_VER = "1.2.0"   # 1.2.0 (0.9.116): 쪽 수(PDF·워드·파워포인트) / 1.1.0: 사진 크기 가로·세로(열 표시)
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif", ".jfif", ".ico", ".dng",
             ".cr2", ".nef", ".arw", ".raw"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".mpg", ".mpeg", ".webm", ".flv", ".3gp", ".ts", ".mts", ".m2ts"}
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus", ".aiff", ".aif"}
PAGE_EXT = {".pdf", ".docx", ".pptx"}   # 1.2.0 쪽 수 열 (pdftools.page_count — 셸 안 부름)
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT | AUDIO_EXT | PAGE_EXT

_cache = {}   # (경로 소문자, mtime) → dict
_CACHE_MAX = 200000


def _ts(v):
    """셸 날짜 값(pywintypes datetime) → 초"""
    try:
        return v.timestamp()
    except Exception:
        return None


def _read(path):
    if os.path.splitext(path)[1].lower() in PAGE_EXT:   # 1.2.0 문서 쪽 수
        try:
            import pdftools
            return {"pages": pdftools.page_count(path)}
        except Exception:
            log.exception("쪽 수 못 읽음 %s", path)
            return {"pages": None}
    from win32com.propsys import propsys, pscon
    out = {}
    try:
        st = propsys.SHGetPropertyStoreFromParsingName(path, None, 0, propsys.IID_IPropertyStore)   # GPS_DEFAULT
    except Exception as ex:
        log.debug("속성 못 읽음 %s : %s", path, ex)
        return out

    def get(key):
        try:
            return st.GetValue(key).GetValue()
        except Exception:
            return None
    ext = os.path.splitext(path)[1].lower()
    d = get(pscon.PKEY_ItemDate)
    out["item_date"] = _ts(d) if d is not None else None
    if ext in VIDEO_EXT or ext in AUDIO_EXT:
        dur = get(pscon.PKEY_Media_Duration)   # 100나노초 단위
        out["duration"] = int(dur) / 1e7 if dur else None
        de = get(pscon.PKEY_Media_DateEncoded)
        out["media_date"] = _ts(de) if de is not None else None
    if ext in IMAGE_EXT:
        w, h = get(pscon.PKEY_Image_HorizontalSize), get(pscon.PKEY_Image_VerticalSize)
        out["pixels"] = int(w) * int(h) if w and h else None
        out["dims"] = (int(w), int(h)) if w and h else None   # 1.1.0: 열 표시용 '가로 x 세로'
    return out


def props(path, mtime):
    """그림·영상·소리 파일의 정렬용 속성 dict (없으면 빈 dict)"""
    if os.path.splitext(path)[1].lower() not in MEDIA_EXT:
        return {}
    k = (path.lower(), mtime)
    r = _cache.get(k)
    if r is None:
        if len(_cache) > _CACHE_MAX:
            _cache.clear()
        r = _cache[k] = _read(path)
    return r


def cached(path, mtime):
    """이미 읽어 둔 값만 (없으면 None — 아직 안 읽음). 미디어가 아니면 빈 dict"""
    if os.path.splitext(path)[1].lower() not in MEDIA_EXT:
        return {}
    return _cache.get((path.lower(), mtime))


_ctime = {}


def created(path, mtime=None):
    """만든 날짜 (초). 못 읽으면 0. mtime 을 주면 기억해 둠(열 표시가 그릴 때마다 디스크를 읽지 않게)"""
    k = (path.lower(), mtime) if mtime is not None else None
    if k is not None and k in _ctime:
        return _ctime[k]
    try:
        s = os.stat(path)
        v = getattr(s, "st_birthtime", s.st_ctime)
    except OSError:
        v = 0
    if k is not None:
        if len(_ctime) > _CACHE_MAX:
            _ctime.clear()
        _ctime[k] = v
    return v


def prefetch(paths_mtimes):
    """여러 파일 한 번에 (뒤 스레드에서 — 파일당 약 12ms 실측). 걸린 시간·개수 기록"""
    import pythoncom
    pythoncom.CoInitialize()
    t = time.perf_counter()
    n = 0
    try:
        for p, m in paths_mtimes:
            if os.path.splitext(p)[1].lower() in MEDIA_EXT and (p.lower(), m) not in _cache:
                props(p, m)
                n += 1
    finally:
        pythoncom.CoUninitialize()
    if n:
        log.info("정렬용 속성 읽음 %d개 %.2f초", n, time.perf_counter() - t)
    return n
