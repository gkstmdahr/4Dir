# -*- coding: utf-8 -*-
"""엑셀 미리보기 (XLSXPREV_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '미리보기 창에서 형식별로 보기: 엑셀')

- 미리보기 창에 끼우는 위젯: can_handle(path) (.xlsx .xlsm .xltx .xltm, 확장자만 — .xls 옛 형식·.csv 는 False) · make_widget(path, parent)
- 엑셀 부품 없이 직접 읽음 (zipfile + xml.etree): read_sheets(path) -> list · read_cells(path, sheet, rows, cols) -> dict
- 공유 글자열(sharedStrings) · 숫자 · 날짜(기본 날짜 서식 번호 14~22·45~47 + 사용자 서식에 y/m/d/h/s) · 수식은 저장된 결과값
- 병합 칸은 첫 칸에만 값(표에서 칸 합침) · 숨긴 시트는 탭에 '(숨김)'
- 고른 시트의 앞 200줄 × 50칸만 (시트 xml 을 흘려 읽다가 200줄 넘으면 멈춤 — 큰 파일도 빠름). 읽기는 뒤 스레드
- 암호 걸린 파일·깨진 파일은 안내 글
로그: bin\\log\\4Dir.log [QE.xlsxprev]
"""
import os
import re
import time
import zipfile
import logging
import datetime
import threading
import posixpath
import xml.etree.ElementTree as ET

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

XLSXPREV_VER = "1.0.0"
log = logging.getLogger("QE.xlsxprev")
EXTS = {".xlsx", ".xlsm", ".xltx", ".xltm"}
ROWS, COLS = 200, 50
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PNS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DATE_IDS = set(range(14, 23)) | {45, 46, 47}
TIME_IDS = {18, 19, 20, 21, 45, 46, 47}
MERGE_SCAN_MAX = 64 * 1048576   # 병합 칸 찾기용으로 시트 xml 을 끝까지 훑는 한도(풀린 크기)



def _narrow(lab):
    """줄 바꿈 글자표: 폭은 창에 맞춰 줄고 늘되, 높이는 글 길이에 맞게 (heightForWidth 유지)"""
    sp = lab.sizePolicy()
    sp.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
    lab.setSizePolicy(sp)
    lab.setMinimumWidth(1)

def can_handle(path):
    return os.path.splitext(path or "")[1].lower() in EXTS


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def col_name(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


_REF = re.compile(r"([A-Z]+)(\d+)")


def _ref(ref):
    m = _REF.match(ref or "")
    if not m:
        return None
    return int(m.group(2)) - 1, col_index(m.group(1))


def _open(path):
    if not zipfile.is_zipfile(path):
        with open(path, "rb") as f:
            head = f.read(8)
        if head.startswith(b"\xd0\xcf\x11\xe0"):
            raise ValueError(T("암호가 걸린 파일이거나 옛 형식(.xls) 파일이라 볼 수 없음"))
        raise ValueError(T("엑셀 파일이 아니거나 깨짐"))
    return zipfile.ZipFile(path)


def _workbook(z):
    """→ (시트 목록, 1904 날짜 기준인가)"""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {}
    try:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(PNS + "Relationship"):
            t = r.get("Target", "")
            t = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join("xl", t))
            rels[r.get("Id")] = t
    except KeyError:
        pass
    pr = wb.find(NS + "workbookPr")
    d1904 = pr is not None and pr.get("date1904") in ("1", "true")
    sheets = []
    for i, s in enumerate(wb.iter(NS + "sheet")):
        rid = s.get(RNS + "id")
        sheets.append({"index": i, "name": s.get("name", ""), "state": s.get("state", "visible"),
                       "hidden": s.get("state", "visible") != "visible", "target": rels.get(rid, "xl/worksheets/sheet%d.xml" % (i + 1))})
    return sheets, d1904


def read_sheets(path):
    """→ [{index, name, state('visible'|'hidden'|'veryHidden'), hidden, target}]"""
    with _open(path) as z:
        sheets, _ = _workbook(z)
    log.info("시트 목록 %s: %s", path, [(s["name"], s["state"]) for s in sheets])
    return sheets


def _shared(z):
    try:
        data = z.open("xl/sharedStrings.xml")
    except KeyError:
        return []
    out = []
    with data:
        for ev, el in ET.iterparse(data, events=("end",)):
            if el.tag == NS + "si":
                out.append("".join(t.text or "" for t in el.iter(NS + "t") if not _in_phonetic(el, t)))
                el.clear()
    return out


def _in_phonetic(si, t):
    # 일본어 읽는 법(rPh) 안의 글자는 빼기
    for rph in si.iter(NS + "rPh"):
        if t in list(rph.iter(NS + "t")):
            return True
    return False


def _styles(z):
    """→ 서식 번호(cellXfs 순번) → 'date'|'time'|'datetime'|'pct0'|'pct2'|None"""
    try:
        st = ET.fromstring(z.read("xl/styles.xml"))
    except KeyError:
        return []
    custom = {}
    nf = st.find(NS + "numFmts")
    if nf is not None:
        for f in nf.iter(NS + "numFmt"):
            custom[int(f.get("numFmtId", "0"))] = f.get("formatCode", "")
    out = []
    xfs = st.find(NS + "cellXfs")
    for xf in (xfs.iter(NS + "xf") if xfs is not None else []):
        fid = int(xf.get("numFmtId", "0"))
        kind = None
        if fid in DATE_IDS:
            kind = "time" if fid in (18, 19, 20, 21, 45, 46, 47) else ("datetime" if fid == 22 else "date")
        elif fid == 9:
            kind = "pct0"
        elif fid == 10:
            kind = "pct2"
        elif fid in custom:
            code = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", custom[fid]).lower()
            has_t = "h" in code or "s" in code
            has_d = "y" in code or "d" in code or ("m" in code and not has_t)
            if has_d and has_t:
                kind = "datetime"
            elif has_d:
                kind = "date"
            elif has_t and ("h" in code):
                kind = "time"
            elif code.endswith("%"):
                kind = "pct2" if "." in code else "pct0"
        out.append(kind)
    return out


def excel_date(v, d1904=False):
    base = datetime.datetime(1904, 1, 1) if d1904 else datetime.datetime(1899, 12, 30)
    return base + datetime.timedelta(days=v)


def _num(s):
    try:
        v = float(s)
    except ValueError:
        return s
    if v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return "%.15g" % v


def _is_num(s):
    """숫자·백분율이면 오른쪽 맞춤"""
    try:
        float(s.rstrip("%"))
        return True
    except ValueError:
        return False


def _fmt(v, kind, d1904):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return v
    if kind in ("date", "datetime", "time"):
        try:
            dt = excel_date(x, d1904)
        except (OverflowError, ValueError):
            return _num(v)
        if kind == "time" and x < 1:
            return dt.strftime("%H:%M:%S")
        if kind == "date" or (dt.hour == dt.minute == dt.second == 0 and kind != "time"):
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if kind == "pct0":
        return "%.0f%%" % (x * 100)
    if kind == "pct2":
        return "%.2f%%" % (x * 100)
    return _num(v)


def read_cells(path, sheet=0, rows=ROWS, cols=COLS, cancel=None):
    """sheet = 순번 또는 이름 → dict(name, cells=[[글자]], nrows, ncols, merged=[(r0,c0,r1,c1)], more_rows, more_cols, formulas)"""
    t0 = time.time()
    with _open(path) as z:
        sheets, d1904 = _workbook(z)
        if isinstance(sheet, str):
            sh = next((s for s in sheets if s["name"] == sheet), None)
        else:
            sh = sheets[sheet] if 0 <= sheet < len(sheets) else None
        if sh is None:
            raise ValueError(T("시트가 없음: {0}").format(sheet))
        ss = _shared(z)
        styles = _styles(z)
        grid = [[""] * cols for _ in range(rows)]
        nrows = ncols = 0
        more_rows = more_cols = False
        formulas = 0
        try:
            info = z.getinfo(sh["target"])
        except KeyError:
            raise ValueError(T("시트 내용이 없음: {0}").format(sh["name"]))
        with z.open(info) as fx:
            r_auto = -1
            for ev, el in ET.iterparse(fx, events=("end",)):
                tag = el.tag
                if tag == NS + "c":
                    pass
                elif tag == NS + "row":
                    rr = el.get("r")
                    ri = int(rr) - 1 if rr else r_auto + 1
                    r_auto = ri
                    if ri >= rows:
                        more_rows = True
                        el.clear()
                        break
                    c_auto = -1
                    for c in el.iter(NS + "c"):
                        p = _ref(c.get("r"))
                        ci = p[1] if p else c_auto + 1
                        c_auto = ci
                        if ci >= cols:
                            more_cols = True
                            continue
                        t = c.get("t", "n")
                        vel = c.find(NS + "v")
                        v = vel.text if vel is not None else None
                        if c.find(NS + "f") is not None:
                            formulas += 1
                        if t == "s" and v is not None:
                            try:
                                v = ss[int(v)]
                            except (ValueError, IndexError):
                                v = "?"
                        elif t == "inlineStr":
                            v = "".join(x.text or "" for x in c.iter(NS + "t"))
                        elif t == "b":
                            v = "TRUE" if v == "1" else "FALSE"
                        elif t in ("str", "e"):
                            v = v or ""
                        elif v is not None:
                            si = int(c.get("s", "0"))
                            v = _fmt(v, styles[si] if si < len(styles) else None, d1904)
                        if v is None or v == "":
                            continue
                        grid[ri][ci] = v
                        nrows = max(nrows, ri + 1)
                        ncols = max(ncols, ci + 1)
                    el.clear()
                    if cancel is not None and cancel.is_set():
                        break
                elif tag == NS + "sheetData":
                    break
        merged = []
        if info.file_size <= MERGE_SCAN_MAX and not (cancel is not None and cancel.is_set()):
            pat = re.compile(rb'<(?:\w+:)?mergeCell\s+ref="([A-Z]+\d+):([A-Z]+\d+)"')
            tail = b""
            with z.open(info) as fx:
                while True:
                    b = fx.read(1048576)
                    if not b:
                        break
                    buf = tail + b
                    for m in pat.finditer(buf):
                        a, e = _ref(m.group(1).decode()), _ref(m.group(2).decode())
                        if a and e and a[0] < rows and a[1] < cols:
                            merged.append((a[0], a[1], min(e[0], rows - 1), min(e[1], cols - 1)))
                    tail = buf[-200:] if len(buf) > 200 else b""
                    # 바로 앞 조각 끝에 걸친 것은 다음 조각에서 다시 잡힘 → 중복 제거
            merged = sorted(set(merged))
        for (r0, c0, r1, c1) in merged:
            nrows = max(nrows, r1 + 1)
            ncols = max(ncols, c1 + 1)
    cells = [row[:ncols] for row in grid[:nrows]]
    out = {"name": sh["name"], "hidden": sh["hidden"], "cells": cells, "nrows": nrows, "ncols": ncols, "merged": merged,
           "more_rows": more_rows, "more_cols": more_cols, "formulas": formulas}
    log.info("칸 읽음 %s [%s] %d줄×%d칸 병합 %d 수식 %d 더있음=%s/%s %.0fms", path, sh["name"], nrows, ncols, len(merged),
             formulas, more_rows, more_cols, (time.time() - t0) * 1000)
    return out


# ---------------------------------------------------------------- 화면
class _Bridge(QtCore.QObject):
    done = QtCore.Signal(object, object)   # (무엇, 결과)


class XlsxView(QtWidgets.QWidget):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.sheets = []
        self.cur = None
        self.req = 0
        self.cancel = threading.Event()
        self.destroyed.connect(self.cancel.set)
        self.setMinimumWidth(150)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.tabs = QtWidgets.QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._tab)
        lay.addWidget(self.tabs)
        self.note = QtWidgets.QLabel(T("읽는 중…"))
        self.note.setWordWrap(True)
        _narrow(self.note)
        lay.addWidget(self.note)
        self.table = QtWidgets.QTableWidget()
        self.table.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(self.table.fontMetrics().height() + 6)
        self.table.horizontalHeader().setDefaultSectionSize(80)
        lay.addWidget(self.table, 1)
        self.br = _Bridge(self)
        self.br.done.connect(self._on_done)
        log.info("열기 %s", path)
        self._bg("sheets", lambda: read_sheets(path))

    def _bg(self, what, fn):
        br, cancel = self.br, self.cancel

        def work():
            try:
                r = fn()
            except Exception as ex:
                if not isinstance(ex, (ValueError, zipfile.BadZipFile, KeyError, ET.ParseError)):
                    log.exception("읽기 실패")
                else:
                    log.info("읽기 실패 %s", ex)
                r = ex
            if cancel.is_set():
                return
            try:
                br.done.emit(what, r)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True, name="xlsxprev").start()

    def _on_done(self, what, r):
        if isinstance(r, Exception):
            msg = str(r) if isinstance(r, ValueError) else T("엑셀 파일이 아니거나 깨짐") + " (%s)" % r
            self.note.setText(msg)
            return
        if what == "sheets":
            self.sheets = r
            self.tabs.blockSignals(True)
            dim = self.palette().color(QtGui.QPalette.PlaceholderText)
            for s in r:
                i = self.tabs.addTab(s["name"] + (" (" + T("숨김") + ")" if s["hidden"] else ""))
                if s["hidden"]:
                    self.tabs.setTabTextColor(i, dim)
            self.tabs.blockSignals(False)
            first = next((s["index"] for s in r if not s["hidden"]), 0)
            if r:
                self.tabs.setCurrentIndex(first)
                self._tab(first)
            else:
                self.note.setText(T("시트가 없음"))
        elif what[0] == "cells" and what[1] == self.req:
            self._show(r)

    def _tab(self, i):
        if i < 0 or i >= len(self.sheets):
            return
        self.req += 1
        req = self.req
        self.note.setText(T("읽는 중…"))
        path = self.path
        cancel = self.cancel
        self._bg(("cells", req), lambda: read_cells(path, i, ROWS, COLS, cancel))

    def _show(self, d):
        self.cur = d
        t = self.table
        t.clear()
        t.setRowCount(d["nrows"])
        t.setColumnCount(d["ncols"])
        t.setHorizontalHeaderLabels([col_name(i) for i in range(d["ncols"])])
        for ri, row in enumerate(d["cells"]):
            for ci, v in enumerate(row):
                if v != "":
                    it = QtWidgets.QTableWidgetItem(v)
                    if _is_num(v):
                        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    t.setItem(ri, ci, it)
        t.clearSpans()
        for (r0, c0, r1, c1) in d["merged"]:
            if r1 > r0 or c1 > c0:
                t.setSpan(r0, c0, r1 - r0 + 1, c1 - c0 + 1)
        parts = [T("시트 {0}개").format(len(self.sheets)), T("{0}줄 × {1}칸").format(d["nrows"], d["ncols"])]
        if d["more_rows"] or d["more_cols"]:
            parts.append(T("앞 {0}줄 × {1}칸만 보임").format(ROWS, COLS))
        if d["formulas"]:
            parts.append(T("수식 {0}개 (저장된 결과값)").format(d["formulas"]))
        if d["hidden"]:
            parts.append(T("숨긴 시트"))
        if not d["nrows"]:
            parts.append(T("빈 시트"))
        self.note.setText(" · ".join(parts))


def make_widget(path, parent=None):
    if not can_handle(path) or not os.path.isfile(path):
        return None
    try:
        return XlsxView(path, parent)
    except Exception:
        log.exception("위젯 만들기 실패 %s", path)
        return None
