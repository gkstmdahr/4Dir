# -*- coding: utf-8 -*-
"""가상 파일 끌어 놓기 (VFILES_VER 1.0.0, v0.9.75 사용자 의견: 아웃룩 첨부 파일을 끌어 놓으면 안 됨)

아웃룩 첨부·메일, 압축 프로그램 창 안의 파일 등은 '진짜 파일 경로'(CF_HDROP)가 아니라
FileGroupDescriptorW(이름 목록) + FileContents(내용) 로 넘어옴 → 이름을 읽고 내용을 받아 대상 폴더에 저장.
- Qt 는 FileContents 를 한 개(첫 번째)만 꺼내 줌 → 1.1.0 부터 olehook 으로 원래 데이터를 직접 받음(여러 개·스트림·웹 아웃룩 본문 이미지). 못 감쌌을 때만 예전 방식.
- 끌어 놓을 때마다 받은 형식·이름·크기를 로그에 자세히 남김 (아웃룩 실측 전 — 로그로 확인)
"""
import os
import re
import json
import html as _html
import struct
import logging

import olehook

log = logging.getLogger("QE")

VFILES_VER = "1.2.1"
FMT_FGD = 'application/x-qt-windows-mime;value="FileGroupDescriptorW"'
FMT_FC = 'application/x-qt-windows-mime;value="FileContents"'
_FD_SIZE = 592   # FILEDESCRIPTORW 한 개 바이트 수
_BAD = '<>:"/\\|?*'


def has_virtual(md):
    """진짜 경로 없이 가상 파일만 있는 끌기인가"""
    try:
        if md is None or not md.hasFormat(FMT_FGD):
            return False
        # 1.1.1: 웹 페이지 이미지는 이름표와 함께 인터넷 주소(https…)도 줌 → '진짜 파일 경로'만 없으면 가상 파일로 (전엔 주소가 있으면 건너뜀)
        return not any(u.isLocalFile() for u in md.urls())
    except Exception:
        return False


def names(md):
    """FileGroupDescriptorW → [(이름, 크기 또는 None, 폴더인가)]"""
    b = bytes(md.data(FMT_FGD))
    if len(b) < 4:
        return []
    n = struct.unpack_from("<I", b, 0)[0]
    out = []
    for i in range(n):
        o = 4 + i * _FD_SIZE
        if o + _FD_SIZE > len(b):
            break
        flags, = struct.unpack_from("<I", b, o)
        attrs, = struct.unpack_from("<I", b, o + 36)
        hi, lo = struct.unpack_from("<II", b, o + 64)
        raw = b[o + 72:o + 72 + 520].decode("utf-16-le", "replace")
        nm = raw.split("\x00", 1)[0]
        size = (hi << 32 | lo) if flags & 0x40 else None   # FD_FILESIZE
        out.append((nm, size, bool(attrs & 0x10)))
    return out


def _safe(nm):
    base = nm.rsplit(chr(92), 1)[-1]   # 이름표의 하위 경로(폴더\파일)는 마지막 이름만. '/' 는 경로가 아니라 못 쓰는 글자 → _
    nm = "".join("_" if c in _BAD or ord(c) < 32 else c for c in base)
    return nm.strip(" .") or "attachment"


def _unique(folder, nm):
    p = os.path.join(folder, nm)
    if not os.path.exists(p):
        return p
    base, ext = os.path.splitext(nm)
    k = 2
    while os.path.exists(os.path.join(folder, f"{base} ({k}){ext}")):
        k += 1
    return os.path.join(folder, f"{base} ({k}){ext}")


_MAGIC = ((b"\x89PNG", ".png"), (b"GIF8", ".gif"), (b"\xff\xd8\xff", ".jpg"), (b"BM", ".bmp"))
_SAME = {".jpg": (".jpg", ".jpeg", ".jpe", ".jfif")}


def _kind(data):
    """내용 앞 몇 바이트로 그림 종류 → 확장자 (모르면 None)"""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    for m, e in _MAGIC:
        if data.startswith(m):
            return e
    return None


def _hints(md, items):
    """1.2.0: 웹 아웃룩은 이름표에 내부 번호(uuid)만 줌 → 원래 이름 [(이름, 원본 크기 또는 None)] (items 와 같은 순서, 못 찾으면 None)
    - 첨부: 크롬 사용자 형식 'attachment' 의 attachmentFiles[].name/size (11/3 실측)
    - 본문 이미지: html 의 <img alt="원래 이름"> (그림 하나일 때만)"""
    if not items or any(d or chr(92) in n for n, _, d in items):
        return None
    try:
        if md.hasFormat(FMT_CWEB):
            for k, v in _chromium_custom(bytes(md.data(FMT_CWEB))):
                if k == "attachment":
                    fs = json.loads(v).get("attachmentFiles") or []
                    if len(fs) == len(items) and all(f.get("name") for f in fs):
                        return [(f["name"], f.get("size")) for f in fs]
        if len(items) == 1 and md.hasHtml():
            imgs = re.findall(r"<img\b[^>]*>", md.html(), re.I)
            m = re.search(r'\balt="([^"]+)"', imgs[0]) if len(imgs) == 1 else None
            if m:
                return [(_html.unescape(m.group(1)), None)]
    except Exception:
        log.exception("원래 이름 찾기 실패")
    return None


def _named(nm, data):
    """원래 이름 + 실제 내용 종류로 확장자 맞춤 (첨부 gif 를 끌면 아웃룩은 미리보기 png 를 줌 → '이름.png')"""
    k = _kind(data)
    base, ext = os.path.splitext(nm)
    if k and ext.lower() not in _SAME.get(k, (k,)):
        return base + k
    return nm


def _save_direct(obj, items, folder, hints=None):
    """1.1.0: 원래 데이터(IDataObject)에서 lindex 0,1,2… 로 하나씩 받기 (탐색기와 같은 방식) — 여러 개·폴더째·스트림 다 됨
    1.2.0: hints(원래 이름) 있으면 그 이름으로
    1.2.1: 원본 크기와 다르면(웹 아웃룩 첨부 = 원본 대신 미리보기 png) 저장 안 함 → 'preview' (사용자 11/3: 헷갈리니 막아)"""
    tops, made, skipped, out, preview = {}, [], [], [], []
    for i, (nm, size, isdir) in enumerate(items):
        parts = [p for p in nm.split(chr(92)) if p]
        if not parts:
            continue
        data = None if isdir else olehook.get_bytes(obj, "FileContents", i)
        if data and size is not None and len(data) > size:
            data = data[:size]   # 한 덩어리(HGLOBAL)는 실제보다 크게 잡혀 올 수 있음
        if not isdir:
            log.info("가상 파일 내용 [%d] %s : 받은 %s바이트, 이름표 크기 %s", i, nm, None if data is None else len(data), size)
            if not data and size != 0:
                skipped.append(nm)
                continue
        if hints and data:
            hn, hs = hints[i]
            parts = [_named(hn, data)]
            log.info("가상 파일 원래 이름 [%d] %s → %s (원본 크기 %s, 받은 %d)", i, nm, parts[0], hs, len(data))
            if hs and hs != len(data):
                preview.append(hn)
                continue
        top = parts[0]
        if top not in tops:   # 맨 위 이름만 겹치면 '(2)' — 폴더째 끌면 안쪽은 그 폴더 아래로
            tops[top] = os.path.basename(_unique(folder, _safe(top)))
            out.append(os.path.join(folder, tops[top]))
        dst = os.path.join(folder, tops[top], *[_safe(p) for p in parts[1:]])
        if isdir:
            os.makedirs(dst, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data or b"")
        made.append(dst)
        log.info("가상 파일 저장 %s (%d바이트)", dst, len(data or b""))
    if skipped:
        log.warning("가상 파일 내용 못 받음 %d개 %s", len(skipped), skipped[:10])
    out = [p for p in out if os.path.exists(p)]
    if preview:
        log.warning("가상 파일 원본 아님(미리보기 그림) → 저장 안 함 %d개 %s", len(preview), preview[:10])
    if preview:
        return out, "preview"
    if not made and not out:
        return [], "empty"
    return out, ("partial" if skipped else "preview" if preview else None)


FMT_CWEB = 'application/x-qt-windows-mime;value="Chromium Web Custom MIME Data Format"'


def _chromium_custom(b):
    """크롬 'Web Custom MIME' (Pickle: 길이·개수·(형식, 값) 문자열 쌍, UTF-16 4바이트 정렬) → [(형식, 값)]"""
    out, o = [], 8
    try:
        n = struct.unpack_from("<I", b, 4)[0]
        for _ in range(min(n * 2, 40)):
            ln = struct.unpack_from("<I", b, o)[0]; o += 4
            out.append(b[o:o + ln * 2].decode("utf-16-le", "replace")); o += (ln * 2 + 3) // 4 * 4
    except Exception:
        pass
    return list(zip(out[0::2], out[1::2]))


def _log_extra(md):
    """1.1.2 진단: 이름표가 uuid 로 올 때 원래 이름이 다른 형식에 있는지 (웹 아웃룩 사용자 질문 11/2)"""
    try:
        if md.hasFormat(FMT_CWEB):
            log.info("가상 파일 진단 크롬 사용자 형식 %s", [(k, v[:600]) for k, v in _chromium_custom(bytes(md.data(FMT_CWEB)))])
        if md.hasHtml():
            log.info("가상 파일 진단 html %s", md.html()[:800])
        if md.hasText():
            log.info("가상 파일 진단 글자 %s", md.text()[:300])
    except Exception:
        log.exception("가상 파일 진단 로그 실패")


def save(md, folder):
    """끌어 놓은 가상 파일을 folder 에 저장 → (저장한 경로들, 안내 글자 또는 None)"""
    fmts = [f for f in md.formats()]
    items = names(md)
    obj = olehook.current()
    log.info("가상 파일 끌어 놓기 → %s : 이름 %s / 형식 %s / 직접 받기 %s", folder, items, fmts, obj is not None)
    _log_extra(md)
    if not items:
        return [], None
    if obj is not None:
        return _save_direct(obj, items, folder, _hints(md, items))
    files = [it for it in items if not it[2]]
    if len(files) != 1 or len(items) != 1:
        log.warning("가상 파일 %d개(폴더 포함 %d) — Qt 는 내용 1개만 꺼낼 수 있어 저장 안 함", len(files), len(items))
        return [], "multi"
    data = bytes(md.data(FMT_FC))
    nm, size, _ = files[0]
    log.info("가상 파일 내용 %s : 받은 %d바이트, 이름표 크기 %s", nm, len(data), size)
    if not data:   # 1.0.1: 크기 표시 없이 빈 내용(웹 아웃룩 본문 이미지)도 저장 안 함 — 전엔 0바이트 파일이 생김
        return [], "empty"
    dst = _unique(folder, _safe(nm))
    with open(dst, "wb") as f:
        f.write(data)
    log.info("가상 파일 저장 %s (%d바이트)", dst, len(data))
    return [dst], None
