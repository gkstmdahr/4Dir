# -*- coding: utf-8 -*-
"""문서에서 글자 꺼내기 (DOCTEXT_VER 1.0.0, 0.9.145 — 사용자 11/22 '엑셀·워드·한글 내용까지 검색')

- extract(path, max_chars=2_000_000, cancel=None) -> str | None  (못 읽으면 None, 까닭은 로그)
  · .docx .docm .dotx · .xlsx .xlsm .xltx · .pptx .pptm · .hwpx : zip 안 xml 을 직접 읽음 (부품 설치 없음)
  · .hwp (한글 5.0) : 윈도우 OLE 저장소(pythoncom.StgOpenStorage) → BodyText/Section* → 레코드 중 문단 글자(태그 67)
    압축 표시면 raw deflate(zlib wbits=-15). 암호·배포용 문서는 None
  · .pdf : bin\\vendor\\pypdf, 앞 MAX_PDF_PAGES 쪽
  · 그 밖(.doc .xls .ppt .rtf .odt 등, 위에서 실패한 .hwp 도) : 윈도우에 깔린 내용 필터(IFilter)가 있으면 그것으로
  · 글자 파일 : grepsearch.decode_bytes 와 같은 규칙 (BOM → UTF-8 → CP949)
- is_doc(path) : 위 문서 확장자인가 (글자 파일 아님)
- snippet(text, terms, width) : 찾은 낱말 앞뒤 조각 (한 줄로)
- 쉴 때 하는 일 없음 — 부를 때만 읽음
로그: bin\\log\\4Dir.log [QE.doctext]
"""
import os
import re
import sys
import time
import zlib
import html
import struct
import logging
import zipfile

DOCTEXT_VER = "1.0.0"
log = logging.getLogger("QE.doctext")

MAX_BYTES = 50 * 1048576     # 이보다 큰 문서는 안 읽음
MAX_PDF_PAGES = 300
ZIP_PARTS = {
    ".docx": (r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$",),
    ".docm": (r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$",),
    ".dotx": (r"word/(document|header\d*|footer\d*)\.xml$",),
    ".xlsx": (r"xl/sharedStrings\.xml$", r"xl/worksheets/sheet\d+\.xml$", r"xl/workbook\.xml$"),
    ".xlsm": (r"xl/sharedStrings\.xml$", r"xl/worksheets/sheet\d+\.xml$", r"xl/workbook\.xml$"),
    ".xltx": (r"xl/sharedStrings\.xml$", r"xl/worksheets/sheet\d+\.xml$"),
    ".pptx": (r"ppt/slides/slide\d+\.xml$", r"ppt/notesSlides/notesSlide\d+\.xml$"),
    ".pptm": (r"ppt/slides/slide\d+\.xml$", r"ppt/notesSlides/notesSlide\d+\.xml$"),
    ".hwpx": (r"Contents/section\d+\.xml$", r"Contents/header\.xml$"),
    ".odt": (r"content\.xml$",), ".ods": (r"content\.xml$",), ".odp": (r"content\.xml$",),
}
HWP_EXT = {".hwp", ".hwt"}   # .hwt = 한글 서식 (같은 형식)
IFILTER_EXT = {".doc", ".dot", ".xls", ".xlt", ".ppt", ".pps", ".rtf", ".msg", ".vsd", ".vsdx", ".xps"}
DOC_EXT = set(ZIP_PARTS) | IFILTER_EXT | HWP_EXT | {".pdf"}

_BREAK = re.compile(r"</(?:w:p|a:p|hp:p|text:p|text:h|row|si|w:tr)>|<(?:w:br|w:tab|a:br|hp:lineBreak|hp:tab|text:line-break|text:tab)\b[^>]*/?>")
_TAG = re.compile(r"<[^>]+>")
_SHEET_NAME = re.compile(r'<sheet\b[^>]*\bname="([^"]*)"')


def is_doc(path):
    return os.path.splitext(path)[1].lower() in DOC_EXT


def _xml_text(data, part):
    s = data.decode("utf-8", "replace")
    if part.endswith("workbook.xml"):
        return "\n".join(html.unescape(n) for n in _SHEET_NAME.findall(s))
    if "/worksheets/" in part:   # 시트: 칸 안 글자(inlineStr)만 — 공유 글자는 sharedStrings 에서
        s = "".join(re.findall(r"<is>.*?</is>", s, re.S))
    s = _BREAK.sub("\n", s)
    s = _TAG.sub("", s)
    return html.unescape(s)


def _zip_text(path, ext, max_chars, cancel):
    pats = [re.compile(p) for p in ZIP_PARTS[ext]]
    out, n = [], 0
    with zipfile.ZipFile(path) as z:
        names = [nm for nm in z.namelist() if any(p.search(nm) for p in pats)]
        names.sort(key=lambda nm: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", nm)])
        for nm in names:
            if cancel is not None and cancel():
                return None
            t = _xml_text(z.read(nm), nm)
            out.append(t)
            n += len(t)
            if n >= max_chars:
                break
    return "\n".join(out)[:max_chars]


# ---------------------------------------------------------------- 한글 5.0
HWPTAG_PARA_TEXT = 67          # HWPTAG_BEGIN(0x10) + 51
_CHAR_CTRL = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}   # 1글자 크기 제어 (나머지 0~31 은 8글자 크기)


def _para_text(b):
    out = []
    n = len(b) // 2
    i = 0
    while i < n:
        c = b[2 * i] | (b[2 * i + 1] << 8)
        if c >= 32:
            out.append(chr(c))
            i += 1
        elif c in _CHAR_CTRL:
            if c in (10, 13):
                out.append("\n")
            elif c in (30, 31):
                out.append(" ")
            i += 1
        else:
            if c == 9:
                out.append("\t")
            i += 8
    return "".join(out)


def _records(data):
    pos, n = 0, len(data)
    while pos + 4 <= n:
        h = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        tag, size = h & 0x3FF, (h >> 20) & 0xFFF
        if size == 0xFFF:
            if pos + 4 > n:
                return
            size = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        yield tag, data[pos:pos + size]
        pos += size


def _stream_bytes(stg, name):
    from win32com import storagecon as stgc
    st = stg.OpenStream(name, None, stgc.STGM_READ | stgc.STGM_SHARE_EXCLUSIVE, 0)
    parts = []
    while True:
        b = st.Read(1048576)
        if not b:
            break
        parts.append(b)
    return b"".join(parts)


def _open_root(path):
    import pythoncom
    from win32com import storagecon as stgc
    last = None
    for mode in (stgc.STGM_READ | stgc.STGM_SHARE_DENY_WRITE,
                 stgc.STGM_READ | stgc.STGM_SHARE_DENY_NONE | stgc.STGM_TRANSACTED):   # 한글에서 열어 둔 파일
        try:
            return pythoncom.StgOpenStorage(path, None, mode, None, 0)
        except Exception as ex:   # noqa: BLE001
            last = ex
    raise last


def _hwp_text(path, max_chars, cancel):
    import pythoncom
    from win32com import storagecon as stgc
    pythoncom.CoInitialize()
    try:
        root = _open_root(path)
        hdr = _stream_bytes(root, "FileHeader")
        if not hdr.startswith(b"HWP Document File"):
            log.info("한글 아님(머리 다름) %s", path)
            return None
        prop = struct.unpack_from("<I", hdr, 36)[0]
        if prop & 0x2:
            log.info("한글 암호 문서 → 못 읽음 %s", path)
            return None
        if prop & 0x4:
            log.info("한글 배포용 문서 → 못 읽음 %s", path)
            return None
        compressed = bool(prop & 0x1)
        body = root.OpenStorage("BodyText", None, stgc.STGM_READ | stgc.STGM_SHARE_EXCLUSIVE, None, 0)
        secs = sorted((st[0] for st in body.EnumElements() if st[0].startswith("Section")),
                      key=lambda s: int(re.sub(r"\D", "", s) or 0))
        out, n = [], 0
        for sname in secs:
            if cancel is not None and cancel():
                return None
            data = _stream_bytes(body, sname)
            if compressed:
                data = zlib.decompress(data, -15)
            for tag, rec in _records(data):
                if tag == HWPTAG_PARA_TEXT:
                    t = _para_text(rec)
                    out.append(t)
                    n += len(t)
            out.append("\n")
            if n >= max_chars:
                break
        return "".join(out)[:max_chars]
    finally:
        pythoncom.CoUninitialize()


# ---------------------------------------------------------------- PDF
def _pdf_text(path, max_chars, cancel):
    vend = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
    if vend not in sys.path:
        sys.path.insert(0, vend)
    import pypdf
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    r = pypdf.PdfReader(path)
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:   # noqa: BLE001
            log.info("PDF 암호 → 못 읽음 %s", path)
            return None
    out, n = [], 0
    for i, pg in enumerate(r.pages):
        if i >= MAX_PDF_PAGES or (cancel is not None and cancel()):
            break
        try:
            t = pg.extract_text() or ""
        except Exception:   # noqa: BLE001
            continue
        out.append(t)
        n += len(t)
        if n >= max_chars:
            break
    return "\n".join(out)[:max_chars]


# ---------------------------------------------------------------- 윈도우 내용 필터
def _ifilter_text(path, max_chars, cancel):
    import pythoncom
    from win32comext.ifilter import ifilter
    from win32comext.ifilter.ifiltercon import CHUNK_TEXT, IFILTER_INIT_APPLY_INDEX_ATTRIBUTES, IFILTER_INIT_INDEXING_ONLY
    pythoncom.CoInitialize()
    filt = None
    try:
        filt = ifilter.LoadIFilter(path)
        filt.Init(IFILTER_INIT_APPLY_INDEX_ATTRIBUTES | IFILTER_INIT_INDEXING_ONLY)
        out, n = [], 0
        while n < max_chars:
            if cancel is not None and cancel():
                return None
            try:
                chunk = filt.GetChunk()
            except pythoncom.com_error as ex:
                if ex.hresult in (ifilter.FILTER_E_END_OF_CHUNKS, ifilter.FILTER_E_EMBEDDING_UNAVAILABLE,
                                  ifilter.FILTER_E_LINK_UNAVAILABLE):
                    break
                raise
            if chunk[2] != CHUNK_TEXT:   # (id, breaktype, flags, ...)
                continue
            if out and chunk[1] != 0:   # 실측: 한 문단이 '다음'|' 달 출시…' 처럼 나뉘어 옴 — 끊김 없음(0)이면 붙임
                out.append("\n")
            while n < max_chars:
                try:
                    t = filt.GetText()
                except pythoncom.com_error as ex:
                    if ex.hresult in (ifilter.FILTER_E_NO_MORE_TEXT, ifilter.FILTER_E_NO_TEXT):
                        break
                    raise
                out.append(t)
                n += len(t)
        filt = None   # COM 개체를 CoUninitialize 전에 놓음
        return "".join(out)[:max_chars]
    finally:
        filt = None
        pythoncom.CoUninitialize()


def _plain_text(path, max_chars):
    with open(path, "rb") as f:
        b = f.read(max_chars * 2)
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", "replace")
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return b.decode("utf-16", "replace")
    if b"\x00" in b[:8192]:
        return None
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp949", "replace")


def extract(path, max_chars=2_000_000, cancel=None):
    """문서 → 글자 (못 읽으면 None). 예외는 밖으로 안 냄"""
    ext = os.path.splitext(path)[1].lower()
    t0 = time.perf_counter()
    how = ""
    try:
        sz = os.path.getsize(path)
        if sz > MAX_BYTES:
            log.info("문서가 커서 건너뜀 %.0fMB %s", sz / 1048576, path)
            return None
        text = None
        if ext in ZIP_PARTS:
            how = "zip"
            text = _zip_text(path, ext, max_chars, cancel)
        elif ext in HWP_EXT:
            how = "hwp"
            try:
                text = _hwp_text(path, max_chars, cancel)
            except Exception as ex:   # noqa: BLE001
                log.info("한글 직접 읽기 실패(%s) → 윈도우 필터 %s", ex, path)
                text = None
            if text is None:
                how = "hwp→ifilter"
                text = _ifilter_text(path, max_chars, cancel)
        elif ext == ".pdf":
            how = "pdf"
            text = _pdf_text(path, max_chars, cancel)
        elif ext in IFILTER_EXT:
            how = "ifilter"
            text = _ifilter_text(path, max_chars, cancel)
        else:
            how = "text"
            text = _plain_text(path, max_chars)
        ms = (time.perf_counter() - t0) * 1000
        if ms > 1000:
            log.info("문서 읽기 느림 %s %s %d자 %.0fms", how, path, len(text or ""), ms)
        return text
    except zipfile.BadZipFile:
        log.info("zip 형식 아님(암호 걸린 오피스 문서일 수 있음) %s", path)
    except Exception as ex:   # noqa: BLE001
        log.info("문서 읽기 실패 %s %s: %s", how, path, ex)
    return None


def snippet(text, terms, width=60):
    """찾은 낱말 앞뒤 조각 (공백·줄바꿈은 한 칸으로). 못 찾으면 앞부분"""
    if not text:
        return ""
    low = text.lower()
    pos = -1
    for t in terms:
        if t:
            pos = low.find(t.lower())
            if pos >= 0:
                break
    if pos < 0:
        s = text[:width * 2]
    else:
        a = max(0, pos - width)
        s = ("…" if a > 0 else "") + text[a:pos + width] + ("…" if pos + width < len(text) else "")
    return re.sub(r"\s+", " ", s).strip()
