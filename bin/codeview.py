# -*- coding: utf-8 -*-
"""코드·글자 미리보기 (CODEVIEW_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '미리보기 창에서 형식별로 보기: 코드·글자')

- 미리보기 창에 끼우는 위젯: can_handle(path) (확장자만 봄, 즉시) · make_widget(path, parent) -> QWidget|None
- 코드·글자: 읽기 전용 + 색칠(낱말·글자열·주석·숫자, 밝게/어둡게 두 벌) + 왼쪽 줄 번호 + 고정폭 글꼴(Consolas)
- 앞 2MB 만 읽음(넘으면 '앞 2MB 만 보임'). 글자 방식 = BOM → UTF-8 → CP949 순으로 맞춰 봄
- 색칠은 앞 2만 줄까지만(큰 파일에서 화면 멈춤 방지)
- .md = [꾸민 화면|원문] (꾸민 화면의 링크는 기본 브라우저로) · .json = [나무|원문] (5MB 넘으면 원문만, 깨지면 오류 줄 표시) · .csv/.tsv = [표|원문] (앞 500줄)
- 위에 찾기 칸(Ctrl+F, Enter 다음·Shift+Enter 앞) 과 [줄 바꿈] 전환
- 파일 읽기·json 읽기는 뒤 스레드. 위젯이 지워지면 결과를 버림 (파일은 읽을 때만 잠깐 열고 바로 닫음)
로그: bin\\log\\4Dir.log [QE.codeview]
"""
import os
import re
import csv
import json
import time
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

CODEVIEW_VER = "1.0.0"
log = logging.getLogger("QE.codeview")
TEXT_MAX = 2 * 1048576       # 앞 2MB 만 보임
JSON_TREE_MAX = 5 * 1048576  # 이보다 큰 json 은 원문만
CSV_ROWS = 500
HL_MAX_LINES = 20000         # 색칠할 줄 수 한도

EXTS = {".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".xml", ".html", ".htm", ".css", ".scss",
        ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".cs", ".java", ".kt", ".kts", ".go", ".rs", ".lua",
        ".sh", ".bash", ".bat", ".cmd", ".ps1", ".psm1", ".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml",
        ".md", ".markdown", ".txt", ".log", ".csv", ".tsv", ".sql", ".gd", ".shader", ".hlsl", ".glsl", ".vert",
        ".frag", ".cginc", ".ms", ".mcr", ".mel", ".vbs", ".reg", ".svg", ".php", ".rb", ".swift", ".dart", ".r",
        ".gradle", ".properties", ".env", ".gitignore", ".editorconfig", ".srt", ".nfo"}



def _narrow(lab):
    """줄 바꿈 글자표: 폭은 창에 맞춰 줄고 늘되, 높이는 글 길이에 맞게 (heightForWidth 유지)"""
    sp = lab.sizePolicy()
    sp.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
    lab.setSizePolicy(sp)
    lab.setMinimumWidth(1)

def can_handle(path):
    """확장자만 보고 즉시 판단"""
    name = os.path.basename(path or "").lower()
    ext = os.path.splitext(name)[1]
    if not ext and name.startswith("."):
        ext = name
    return ext in EXTS


# ---------------------------------------------------------------- 언어별 낱말 표
_C_KW = ("auto break case char const continue default do double else enum extern float for goto if inline int long "
         "register return short signed sizeof static struct switch typedef union unsigned void volatile while "
         "bool true false nullptr NULL class public private protected virtual override template typename namespace "
         "using new delete this operator friend try catch throw final abstract interface extends implements import "
         "package super instanceof synchronized boolean byte string var let fun val when object is in as out "
         "func go defer chan map range select type struct fallthrough nil fn mut impl trait pub crate mod use match "
         "loop where self Self dyn ref async await yield foreach readonly sealed get set internal lock event "
         "uniform varying attribute in out inout vec2 vec3 vec4 mat3 mat4 float2 float3 float4 float4x4 half "
         "half2 half3 half4 sampler2D texture2D Texture2D SamplerState cbuffer Shader Properties SubShader Pass "
         "CGPROGRAM ENDCG HLSLPROGRAM ENDHLSL Tags discard precision highp mediump lowp #include #define #if #ifdef "
         "#ifndef #endif #else #pragma #elif")
_KW = {
    "py": ("and as assert async await break class continue def del elif else except False finally for from global "
           "if import in is lambda None nonlocal not or pass raise return True try while with yield self match case print"),
    "js": ("break case catch class const continue debugger default delete do else export extends false finally for "
           "function if import in instanceof let new null return super switch this throw true try typeof var void "
           "while with yield async await of interface type enum implements private public protected readonly static "
           "undefined as from get set declare namespace keyof"),
    "c": _C_KW,
    "lua": "and break do else elseif end false for function goto if in local nil not or repeat return then true until while self",
    "sh": "if then else elif fi for while until do done case esac function in return export local echo exit set unset read source shift true false",
    "bat": ("echo set if else goto call exit rem for in do not exist errorlevel setlocal endlocal pause start shift "
            "defined equ neq lss leq gtr geq cd pushd popd copy move del mkdir title cls choice"),
    "ps1": ("function param if else elseif foreach for while do until switch return try catch finally throw begin "
            "process end break continue exit filter trap class enum using import-module write-host write-output $true $false $null"),
    "sql": ("select from where insert into update delete create table drop alter join left right inner outer full cross "
            "on group by order having limit offset and or not null is as values set primary key foreign references "
            "index view distinct union all case when then else end exists in like between asc desc count sum avg min "
            "max int integer varchar text date default unique begin commit rollback transaction with"),
    "gd": ("func var const extends class_name signal if elif else for while match return pass self true false null "
           "onready export static enum in not and or break continue preload await is as tool setget yield super"),
    "ms": ("fn function local global if then else do for in while collect case of return exit struct rollout on true "
           "false undefined ok and or not try catch with animate undo at time continue mapped persistent utility "
           "button spinner checkbox edittext dropdownlist listbox group about coordsys by where to"),
    "mel": ("global proc string int float vector matrix if else for in while do return switch case default break "
            "continue true false on off yes no source catch eval"),
    "vbs": ("dim set if then else elseif end sub function for each next to step while wend do loop until select case "
            "exit call true false nothing empty null and or not is new class private public const on error resume createobject"),
    "php": ("echo print if else elseif endif while for foreach as function return class public private protected static "
            "new null true false array use namespace require include try catch throw extends implements"),
    "rb": "def end if elsif else unless while until for in do return class module self nil true false and or not begin rescue ensure yield require puts",
    "log": "ERROR FATAL CRITICAL FAIL FAILED WARN WARNING INFO DEBUG TRACE Exception Traceback",
}
_CASE_INS = {"bat", "ps1", "sql", "ms", "vbs", "log"}
# 확장자 → (낱말 표, 한 줄 주석 표시들, 덩어리 주석 (시작, 끝) 들, 글자열 따옴표, 특별 규칙)
_LANG = {}


def _reg(exts, kw, line, blocks, quotes="\"'", extra=None):
    for e in exts.split():
        _LANG["." + e] = (kw, line, blocks, quotes, extra)


_reg("py pyw", "py", ["#"], [], "\"'")
_reg("js mjs cjs ts tsx jsx", "js", ["//"], [("/*", "*/")], "\"'`")
_reg("c cpp cc cxx h hpp hh cs java kt kts go rs shader hlsl glsl vert frag cginc swift dart gradle scss", "c",
     ["//"], [("/*", "*/")], "\"'`")
_reg("css", None, [], [("/*", "*/")], "\"'", "css")
_reg("lua", "lua", ["--"], [("--[[", "]]")])
_reg("sh bash", "sh", ["#"], [])
_reg("bat cmd", "bat", ["::", "rem "], [], "\"")
_reg("ps1 psm1", "ps1", ["#"], [("<#", "#>")])
_reg("sql", "sql", ["--"], [("/*", "*/")])
_reg("gd", "gd", ["#"], [])
_reg("ms mcr", "ms", ["--"], [("/*", "*/")], "\"")
_reg("mel", "mel", ["//"], [("/*", "*/")], "\"")
_reg("vbs", "vbs", ["'", "rem "], [], "\"")
_reg("php", "php", ["//", "#"], [("/*", "*/")])
_reg("rb r", "rb", ["#"], [])
_reg("ini cfg conf properties env editorconfig gitignore reg", None, [";", "#"], [], "\"", "ini")
_reg("toml", None, ["#"], [], "\"'", "ini")
_reg("yaml yml", None, ["#"], [], "\"'", "yaml")
_reg("json", None, [], [], "\"", "json")
_reg("xml html htm svg", None, [], [("<!--", "-->")], "\"'", "xml")
_reg("md markdown", None, [], [("<!--", "-->")], "`", "md")
_reg("log", "log", [], [], "", "log")
_reg("txt srt nfo csv tsv", None, [], [], "", None)

# 색 두 벌: 낱말, 글자열, 주석, 숫자, 형식(태그·키·제목)
COLORS = {False: {"kw": "#0033b3", "str": "#067d17", "com": "#8c8c8c", "num": "#1750eb", "type": "#871094",
                  "lnbg": "#f3f3f3", "lnfg": "#9a9a9a", "cur": "#fff8d6", "err": "#ffd6d6", "find": "#ffe066"},
          True: {"kw": "#cc7832", "str": "#6a8759", "com": "#7f848e", "num": "#6897bb", "type": "#c792ea",
                 "lnbg": "#232427", "lnfg": "#6b737c", "cur": "#2d2f33", "err": "#5a2424", "find": "#6b5a12"}}


def is_dark(w):
    return w.palette().color(QtGui.QPalette.Base).lightness() < 128


def decode_bytes(b, truncated=False):
    """BOM → UTF-8 → CP949 → (글자, 글자 방식 이름)"""
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", "replace"), "UTF-8 (BOM)"
    if b.startswith(b"\xff\xfe"):
        return b[2:].decode("utf-16-le", "replace"), "UTF-16 LE"
    if b.startswith(b"\xfe\xff"):
        return b[2:].decode("utf-16-be", "replace"), "UTF-16 BE"
    try:
        return b.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError as ex:
        if truncated and ex.start >= len(b) - 3:   # 2MB 경계에서 글자가 잘림
            try:
                return b[:ex.start].decode("utf-8"), "UTF-8"
            except UnicodeDecodeError:
                pass
    # 홀수 자리마다 0 이 많으면 BOM 없는 UTF-16
    sample = b[:4096]
    if len(sample) > 16 and sample[1::2].count(0) > len(sample) // 4:
        return b.decode("utf-16-le", "replace"), "UTF-16 LE"
    try:
        return b.decode("cp949"), "CP949"
    except UnicodeDecodeError as ex:
        if truncated and ex.start >= len(b) - 1:   # 2MB 경계에서 두 바이트 글자가 잘림
            try:
                return b[:ex.start].decode("cp949"), "CP949"
            except UnicodeDecodeError:
                pass
        return b.decode("cp949", "replace"), "CP949"


def read_text(path, limit=TEXT_MAX):
    """앞 limit 바이트만 읽기 → dict(text, enc, size, truncated)"""
    t0 = time.time()
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        b = f.read(limit)
    trunc = size > limit
    text, enc = decode_bytes(b, trunc)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    log.info("읽음 %s (%d바이트, 잘림=%s, %s, %.0fms)", path, size, trunc, enc, (time.time() - t0) * 1000)
    return {"text": text, "enc": enc, "size": size, "truncated": trunc}


# ---------------------------------------------------------------- 색칠
class Highlighter(QtGui.QSyntaxHighlighter):
    def __init__(self, doc, ext, dark):
        super().__init__(doc)
        self.ext = ext
        kw, self.line_marks, self.blocks, quotes, self.extra = _LANG.get(ext, (None, [], [], "", None))
        opt = QtCore.QRegularExpression.CaseInsensitiveOption if kw in _CASE_INS else QtCore.QRegularExpression.NoPatternOption
        self.kw_re = None
        if kw:
            words = sorted(set(_KW[kw].split()), key=len, reverse=True)
            body = "|".join(re.escape(w) for w in words)
            self.kw_re = QtCore.QRegularExpression(r"(?<![\w$#-])(?:" + body + r")(?![\w-])", opt)
        self.num_re = QtCore.QRegularExpression(r"\b(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b")
        # 글자열과 한 줄 주석을 한 정규식으로 — 글자열 안의 # 은 주석이 아님
        parts = []
        for q in quotes:
            qq = re.escape(q)
            parts.append(qq + r"(?:\\.|[^" + ("\\\\" + q if q != "`" else "\\\\`") + r"])*" + qq + "?")
        self.n_str = len(parts)
        for m in self.line_marks:
            if m.endswith(" "):   # rem
                parts.append(r"(?:^|(?<=[\s@]))" + re.escape(m.strip()) + r"(?:\s.*)?$")
            elif m in (";", "#") and self.extra == "ini":
                parts.append(r"^\s*" + re.escape(m) + ".*$")
            else:
                parts.append(re.escape(m) + ".*$")
        self.sc_re = None
        if parts:
            self.sc_re = QtCore.QRegularExpression("|".join("(" + p + ")" for p in parts),
                                                   QtCore.QRegularExpression.CaseInsensitiveOption if kw in _CASE_INS else
                                                   QtCore.QRegularExpression.NoPatternOption)
        ex = {"xml": [r"</?[\w:.-]+|/?>", r"\b[\w:.-]+(?=\s*=)"],
              "json": [r"\"(?:\\.|[^\"\\])*\"(?=\s*:)", r"\b(?:true|false|null)\b"],
              "ini": [r"^\s*\[[^\]]*\]", r"^\s*[\w.\-\s]+?(?=\s*[=:])"],
              "yaml": [r"^\s*-?\s*[\w.\-\"' ]+?(?=:(\s|$))", r"^---$"],
              "css": [r"[.#]?[\w-]+(?=\s*\{)", r"[\w-]+(?=\s*:)"],
              "md": [r"^#{1,6}\s.*$", r"\[[^\]]*\]\([^)]*\)", r"\*\*[^*]+\*\*", r"^\s*(?:[-*+]|\d+\.)\s"],
              "log": [r"^\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:[.,]\d+)?"]}.get(self.extra, [])
        self.type_res = [QtCore.QRegularExpression(p) for p in ex]
        self.set_dark(dark)

    def set_dark(self, dark):
        c = COLORS[bool(dark)]

        def fmt(col, italic=False, bold=False):
            f = QtGui.QTextCharFormat()
            f.setForeground(QtGui.QColor(col))
            if italic:
                f.setFontItalic(True)
            if bold:
                f.setFontWeight(QtGui.QFont.Bold)
            return f
        self.f_kw = fmt(c["kw"], bold=True)
        self.f_str = fmt(c["str"])
        self.f_com = fmt(c["com"], italic=True)
        self.f_num = fmt(c["num"])
        self.f_type = fmt(c["type"])
        self.calls = 0

    def highlightBlock(self, text):
        self.calls += 1
        blk = self.currentBlock()
        if blk.blockNumber() >= HL_MAX_LINES or len(text) > 4000:
            self.setCurrentBlockState(-1 if self.previousBlockState() != 1 else 1)
            return
        if self.kw_re is not None:
            it = self.kw_re.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), self.f_kw)
        if self.extra not in ("md",):
            it = self.num_re.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), self.f_num)
        for r in self.type_res:
            it = r.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), self.f_type)
        if self.sc_re is not None:
            it = self.sc_re.globalMatch(text)
            while it.hasNext():
                m = it.next()
                is_str = any(m.capturedStart(i + 1) >= 0 for i in range(self.n_str))
                if self.extra == "json" and is_str and self.format(m.capturedStart()) == self.f_type:
                    continue
                self.setFormat(m.capturedStart(), m.capturedLength(), self.f_str if is_str else self.f_com)
        # 덩어리 주석 (/* */ 등) — 상태 1 = 주석 안에서 줄이 끝남
        self.setCurrentBlockState(0)
        if not self.blocks:
            return
        pos = 0
        inside = self.previousBlockState() == 1
        bs, be = self.blocks[0]
        while pos <= len(text):
            if inside:
                end = text.find(be, pos)
                if end < 0:
                    self.setFormat(pos, len(text) - pos, self.f_com)
                    self.setCurrentBlockState(1)
                    return
                self.setFormat(pos, end + len(be) - pos, self.f_com)
                pos = end + len(be)
                inside = False
            else:
                st = text.find(bs, pos)
                if st < 0:
                    return
                if self.format(st) == self.f_str or self.format(st) == self.f_com:
                    pos = st + len(bs)
                    continue
                pos = st
                inside = True
                pos_after = st + len(bs)
                end = text.find(be, pos_after)
                if end < 0:
                    self.setFormat(st, len(text) - st, self.f_com)
                    self.setCurrentBlockState(1)
                    return
                self.setFormat(st, end + len(be) - st, self.f_com)
                pos = end + len(be)
                inside = False


# ---------------------------------------------------------------- 줄 번호 붙은 글자 칸
class _LineArea(QtWidgets.QWidget):
    def __init__(self, ed):
        super().__init__(ed)
        self.ed = ed

    def sizeHint(self):
        return QtCore.QSize(self.ed.line_area_width(), 0)

    def paintEvent(self, ev):
        self.ed.paint_lines(ev)


class CodeEdit(QtWidgets.QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        f = QtGui.QFont("Consolas")
        f.setStyleHint(QtGui.QFont.Monospace)
        f.setPointSize(9)
        self.setFont(f)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.area = _LineArea(self)
        self.blockCountChanged.connect(self._upd_width)
        self.updateRequest.connect(self._upd_area)
        self.err_line = -1
        self.find_sel = []
        self._upd_width()

    def line_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 10 + self.fontMetrics().horizontalAdvance("9") * max(2, digits)

    def _upd_width(self, *_):
        self.setViewportMargins(self.line_area_width(), 0, 0, 0)

    def _upd_area(self, rect, dy):
        if dy:
            self.area.scroll(0, dy)
        else:
            self.area.update(0, rect.y(), self.area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._upd_width()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        cr = self.contentsRect()
        self.area.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.line_area_width(), cr.height()))

    def paint_lines(self, ev):
        c = COLORS[is_dark(self)]
        p = QtGui.QPainter(self.area)
        p.fillRect(ev.rect(), QtGui.QColor(c["lnbg"]))
        p.setPen(QtGui.QColor(c["lnfg"]))
        p.setFont(self.font())
        blk = self.firstVisibleBlock()
        n = blk.blockNumber()
        top = round(self.blockBoundingGeometry(blk).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(blk).height())
        h = self.fontMetrics().height()
        w = self.area.width() - 5
        while blk.isValid() and top <= ev.rect().bottom():
            if blk.isVisible() and bottom >= ev.rect().top():
                if n == self.err_line:
                    p.fillRect(0, top, self.area.width(), h, QtGui.QColor(c["err"]))
                p.drawText(0, top, w, h, Qt.AlignRight, str(n + 1))
            blk = blk.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(blk).height())
            n += 1
        p.end()

    def mark_error(self, line):
        """line = 0부터. 빨간 줄 표시 + 그 줄로 이동"""
        self.err_line = line
        blk = self.document().findBlockByNumber(max(0, line))
        cur = QtGui.QTextCursor(blk)
        self.setTextCursor(cur)
        self.centerCursor()
        self._apply_sel()

    def _apply_sel(self):
        sels = list(self.find_sel)
        if self.err_line >= 0:
            s = QtWidgets.QTextEdit.ExtraSelection()
            s.format.setBackground(QtGui.QColor(COLORS[is_dark(self)]["err"]))
            s.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
            s.cursor = QtGui.QTextCursor(self.document().findBlockByNumber(self.err_line))
            sels.insert(0, s)
        self.setExtraSelections(sels)


# ---------------------------------------------------------------- 뒤 스레드 도우미
class _Bridge(QtCore.QObject):
    done = QtCore.Signal(object)


def _run_bg(owner, fn, slot, cancel):
    br = _Bridge(owner)
    br.done.connect(slot)

    def work():
        try:
            r = fn()
        except Exception as ex:
            log.exception("뒤 작업 실패")
            r = ex
        if cancel.is_set():
            log.info("위젯이 지워져 결과 버림")
            return
        try:
            br.done.emit(r)
        except RuntimeError:
            pass
    threading.Thread(target=work, daemon=True, name="codeview").start()


# ---------------------------------------------------------------- json 나무 (펼칠 때 아래 항목을 만듦)
def _jtype(v):
    if isinstance(v, dict):
        return T("묶음") + " {%d}" % len(v)
    if isinstance(v, list):
        return T("목록") + " [%d]" % len(v)
    if isinstance(v, str):
        return T("글자")
    if isinstance(v, bool):
        return T("참거짓")
    if isinstance(v, (int, float)):
        return T("숫자")
    return "null"


def _jval(v):
    if isinstance(v, dict) or isinstance(v, list):
        return ""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    s = json.dumps(v, ensure_ascii=False) if isinstance(v, str) else str(v)
    return s if len(s) <= 300 else s[:300] + "…"


class JsonTree(QtWidgets.QTreeWidget):
    CHILD_MAX = 2000   # 한 묶음에서 보이는 아래 항목 수

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels([T("키"), T("값"), T("형식")])
        self.setUniformRowHeights(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        self.header().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.header().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.itemExpanded.connect(self._fill)
        self._vals = {}
        self.made = 0

    def load(self, data):
        self.clear()
        self._vals.clear()
        self.made = 0
        root = QtWidgets.QTreeWidgetItem(self, ["(" + T("맨 위") + ")", _jval(data), _jtype(data)])
        self._prep(root, data)
        root.setExpanded(True)
        self.resizeColumnToContents(0)
        self.setColumnWidth(0, min(self.columnWidth(0) + 20, 260))

    def _prep(self, it, v):
        self.made += 1
        if isinstance(v, (dict, list)) and v:
            self._vals[id(it)] = (it, v)
            QtWidgets.QTreeWidgetItem(it, ["…"])   # 펼침 표시용 빈 항목

    def _fill(self, it):
        ent = self._vals.pop(id(it), None)
        if not ent:
            return
        v = ent[1]
        it.takeChildren()
        items = list(v.items()) if isinstance(v, dict) else list(enumerate(v))
        kids = []
        for k, x in items[:self.CHILD_MAX]:
            c = QtWidgets.QTreeWidgetItem([str(k) if isinstance(v, dict) else "[%d]" % k, _jval(x), _jtype(x)])
            kids.append((c, x))
        it.addChildren([c for c, _ in kids])
        for c, x in kids:
            self._prep(c, x)
        if len(items) > self.CHILD_MAX:
            QtWidgets.QTreeWidgetItem(it, ["…", T("{0}개 더 있음 (원문에서 보기)").format(len(items) - self.CHILD_MAX), ""])

    def count_all(self):
        n = 0
        stack = [self.invisibleRootItem()]
        while stack:
            it = stack.pop()
            for i in range(it.childCount()):
                c = it.child(i)
                if c.text(0) != "…":
                    n += 1
                stack.append(c)
        return n


# ---------------------------------------------------------------- 본 위젯
class CodeView(QtWidgets.QWidget):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.ext = os.path.splitext(path)[1].lower()
        self.cancel = threading.Event()
        self.destroyed.connect(self.cancel.set)
        self.info = None
        self.json_data = None
        self.json_error = None
        self.hl = None
        self.setMinimumWidth(150)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(3)
        self.mode_btns = []
        modes = {".md": [T("꾸민 화면"), T("원문")], ".markdown": [T("꾸민 화면"), T("원문")],
                 ".json": [T("나무"), T("원문")], ".csv": [T("표"), T("원문")], ".tsv": [T("표"), T("원문")]}.get(self.ext)
        self.grp = QtWidgets.QButtonGroup(self)
        self.grp.setExclusive(True)
        for i, m in enumerate(modes or []):
            b = QtWidgets.QToolButton()
            b.setText(m)
            b.setCheckable(True)
            b.setAutoRaise(True)
            self.grp.addButton(b, i)
            bar.addWidget(b)
            self.mode_btns.append(b)
        self.grp.idClicked.connect(self.set_mode)
        self.find = QtWidgets.QLineEdit()
        self.find.setPlaceholderText(T("찾기 (Ctrl+F)"))
        self.find.setClearButtonEnabled(True)
        self.find.setMinimumWidth(40)
        self.find.returnPressed.connect(lambda: self.find_next(False))
        self.find.textChanged.connect(self._find_changed)
        bar.addWidget(self.find, 1)
        self.wrap = QtWidgets.QToolButton()
        self.wrap.setText(T("줄 바꿈"))
        self.wrap.setCheckable(True)
        self.wrap.setAutoRaise(True)
        self.wrap.setToolTip(T("긴 줄을 창 폭에 맞춰 접기"))
        self.wrap.toggled.connect(self.set_wrap)
        bar.addWidget(self.wrap)
        lay.addLayout(bar)
        self.note = QtWidgets.QLabel(T("읽는 중…"))
        self.note.setWordWrap(True)
        _narrow(self.note)
        f = self.note.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        self.note.setFont(f)
        lay.addWidget(self.note)
        self.stack = QtWidgets.QStackedWidget()
        self.edit = CodeEdit()
        self.stack.addWidget(self.edit)
        self.rich = None
        self.tree = None
        self.table = None
        self.alt = None
        lay.addWidget(self.stack, 1)
        for seq in ("Ctrl+F",):
            sc = QtGui.QShortcut(QtGui.QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(self.focus_find)
        sc = QtGui.QShortcut(QtGui.QKeySequence("Shift+Return"), self.find)
        sc.setContext(Qt.WidgetShortcut)
        sc.activated.connect(lambda: self.find_next(True))
        sc = QtGui.QShortcut(QtGui.QKeySequence("F3"), self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(lambda: self.find_next(False))
        self.find.installEventFilter(self)
        log.info("열기 %s (형식 %s)", path, self.ext)
        _run_bg(self, lambda: read_text(path), self._on_text, self.cancel)

    # ---- 읽기 결과
    def _on_text(self, r):
        if isinstance(r, Exception):
            self.note.setText(T("읽을 수 없음: {0}").format(r))
            return
        self.info = r
        t0 = time.time()
        self.edit.setPlainText(r["text"])
        self.hl = Highlighter(self.edit.document(), self.ext, is_dark(self))
        lines = self.edit.blockCount()
        parts = [T("{0}줄").format("{:,}".format(lines)), r["enc"], _size(r["size"])]
        if r["truncated"]:
            parts.insert(0, T("앞 2MB 만 보임"))
        self.base_note = " · ".join(parts)
        self.note.setText(self.base_note)
        log.info("글자 칸 채움 %d줄 %.0fms", lines, (time.time() - t0) * 1000)
        if self.ext in (".md", ".markdown"):
            self.rich = QtWidgets.QTextBrowser()
            self.rich.setOpenExternalLinks(False)
            self.rich.setOpenLinks(False)
            self.rich.anchorClicked.connect(self._open_link)
            self.rich.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.rich.document().setDefaultStyleSheet("pre, code { font-family: Consolas; }")
            self.rich.setSearchPaths([os.path.dirname(self.path)])
            self.rich.document().setBaseUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(self.path) + "/"))
            self.rich.setMarkdown(r["text"])
            self.alt = self.rich
            self.stack.addWidget(self.rich)
            self.set_mode(0)
        elif self.ext in (".csv", ".tsv"):
            self.table = self._make_table(r["text"])
            self.alt = self.table
            self.stack.addWidget(self.table)
            self.set_mode(0)
        elif self.ext == ".json":
            if r["size"] > JSON_TREE_MAX:
                self.note.setText(self.base_note + " · " + T("5MB 넘는 json 은 원문만 보임"))
                for b in self.mode_btns:
                    b.hide()
                self.set_mode(1)
            else:
                self.note.setText(self.base_note + " · " + T("나무 만드는 중…"))
                self.set_mode(1)
                _run_bg(self, lambda: _parse_json(self.path), self._on_json, self.cancel)
        else:
            self.set_mode(-1)

    def _on_json(self, r):
        if isinstance(r, Exception):
            self.note.setText(self.base_note + " · " + T("읽을 수 없음: {0}").format(r))
            return
        ok, val = r
        if not ok:
            self.json_error = val
            ln, col, msg = val
            self.note.setText(self.base_note + " · " + T("깨진 json: {0}줄 {1}칸 — {2}").format(ln, col, msg))
            self.note.setStyleSheet("color:#d04040;")
            self.mode_btns[0].setEnabled(False)
            self.set_mode(1)
            self.edit.mark_error(ln - 1)
            log.info("깨진 json %s 줄 %d 칸 %d %s", self.path, ln, col, msg)
            return
        self.json_data = val
        self.tree = JsonTree()
        self.tree.load(val)
        self.alt = self.tree
        self.stack.addWidget(self.tree)
        self.note.setText(self.base_note)
        self.set_mode(0)
        log.info("json 나무 %d 항목(처음 보이는 것)", self.tree.count_all())

    def _make_table(self, text):
        t0 = time.time()
        allp = text.split("\n", CSV_ROWS + 1)
        lines = allp[:CSV_ROWS]
        self.csv_trunc = len(allp) > CSV_ROWS and any(allp[CSV_ROWS:])
        head = "\n".join(lines[:20])
        delim = "\t" if self.ext == ".tsv" else ","
        if self.ext != ".tsv":
            try:
                delim = csv.Sniffer().sniff(head, delimiters=",;\t|").delimiter
            except Exception:
                pass
        rows = list(csv.reader(lines, delimiter=delim))
        while rows and not any(rows[-1]):
            rows.pop()
        ncol = max((len(x) for x in rows), default=0)
        tb = QtWidgets.QTableWidget(len(rows), ncol)
        tb.setFrameShape(QtWidgets.QFrame.NoFrame)
        tb.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        tb.verticalHeader().setDefaultSectionSize(tb.fontMetrics().height() + 6)
        tb.horizontalHeader().setDefaultSectionSize(90)
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                tb.setItem(i, j, QtWidgets.QTableWidgetItem(v))
        log.info("csv 표 %d줄 × %d칸, 나눔표=%r, %.0fms", len(rows), ncol, delim, (time.time() - t0) * 1000)
        return tb

    # ---- 전환
    def set_mode(self, i):
        """i = 0 꾸민 화면/나무/표, 1 원문, -1 원문만(전환 없음)"""
        if i == 0 and self.alt is not None:
            self.stack.setCurrentWidget(self.alt)
        else:
            self.stack.setCurrentWidget(self.edit)
            i = 1 if self.mode_btns else -1
        if 0 <= i < len(self.mode_btns):
            self.mode_btns[i].setChecked(True)
        raw = self.stack.currentWidget() is self.edit
        self.wrap.setEnabled(raw)
        if self.ext in (".csv", ".tsv") and i == 0 and getattr(self, "csv_trunc", False):
            self.note.setText(self.base_note + " · " + T("표는 앞 {0}줄만").format(CSV_ROWS))
        elif self.ext in (".csv", ".tsv") and getattr(self, "base_note", None):
            self.note.setText(self.base_note)

    def set_wrap(self, on):
        self.edit.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth if on else QtWidgets.QPlainTextEdit.NoWrap)
        log.info("줄 바꿈 %s", on)

    # ---- 찾기
    def focus_find(self):
        self.find.setFocus()
        self.find.selectAll()

    def eventFilter(self, o, ev):
        if o is self.find and ev.type() == QtCore.QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.find.clear()
            return True
        return super().eventFilter(o, ev)

    def _find_changed(self, s):
        self.find_next(False, restart=True)

    def find_next(self, back=False, restart=False):
        s = self.find.text()
        w = self.stack.currentWidget()
        if w is self.tree and self.tree is not None:
            return self._find_tree(s, back)
        if w is self.table and self.table is not None:
            return self._find_table(s, back)
        ed = self.rich if w is self.rich and self.rich is not None else self.edit
        if not s:
            self.edit.find_sel = []
            self.edit._apply_sel()
            self.find.setStyleSheet("")
            return False
        if restart:
            c = ed.textCursor()
            c.setPosition(c.selectionStart())
            ed.setTextCursor(c)
        flags = QtGui.QTextDocument.FindFlag(0)
        if back:
            flags |= QtGui.QTextDocument.FindBackward
        found = ed.find(s, flags)
        if not found:   # 끝까지 갔으면 처음부터
            c = ed.textCursor()
            c.movePosition(QtGui.QTextCursor.End if back else QtGui.QTextCursor.Start)
            ed.setTextCursor(c)
            found = ed.find(s, flags)
        self.find.setStyleSheet("" if found else "background:%s;" % COLORS[is_dark(self)]["err"])
        if ed is self.edit:
            sel = QtWidgets.QTextEdit.ExtraSelection()
            sel.format.setBackground(QtGui.QColor(COLORS[is_dark(self)]["find"]))
            sel.cursor = self.edit.textCursor()
            self.edit.find_sel = [sel] if found else []
            self.edit._apply_sel()
        return found

    def _find_tree(self, s, back):
        if not s:
            return False
        its = self.tree.findItems(s, Qt.MatchContains | Qt.MatchRecursive, 0) + \
            self.tree.findItems(s, Qt.MatchContains | Qt.MatchRecursive, 1)
        its = [i for i in its if i.text(0) != "…"]
        if its:
            cur = self.tree.currentItem()
            idx = (its.index(cur) + (-1 if back else 1)) % len(its) if cur in its else 0
            self.tree.setCurrentItem(its[idx])
        self.find.setStyleSheet("" if its else "background:%s;" % COLORS[is_dark(self)]["err"])
        return bool(its)

    def _find_table(self, s, back):
        if not s:
            return False
        its = self.table.findItems(s, Qt.MatchContains)
        if its:
            cur = self.table.currentItem()
            idx = (its.index(cur) + (-1 if back else 1)) % len(its) if cur in its else 0
            self.table.setCurrentItem(its[idx])
        self.find.setStyleSheet("" if its else "background:%s;" % COLORS[is_dark(self)]["err"])
        return bool(its)

    def _open_link(self, url):
        log.info("링크 열기 %s", url.toString())
        if url.scheme() in ("", "file") and not url.isLocalFile():
            url = QtCore.QUrl.fromLocalFile(os.path.join(os.path.dirname(self.path), url.toString()))
        QtGui.QDesktopServices.openUrl(url)

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == QtCore.QEvent.PaletteChange and self.hl is not None:
            self.hl.set_dark(is_dark(self))
            self.hl.rehighlight()


def _parse_json(path):
    t0 = time.time()
    with open(path, "rb") as f:
        b = f.read(JSON_TREE_MAX + 1)
    text, _ = decode_bytes(b)
    try:
        v = json.loads(text)
        log.info("json 읽음 %.0fms", (time.time() - t0) * 1000)
        return True, v
    except json.JSONDecodeError as ex:
        return False, (ex.lineno, ex.colno, ex.msg)


def _size(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return ("%d %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= 1024.0


def make_widget(path, parent=None):
    """미리보기 창용 위젯. 못 다루면 None"""
    if not can_handle(path) or not os.path.isfile(path):
        return None
    try:
        return CodeView(path, parent)
    except Exception:
        log.exception("위젯 만들기 실패 %s", path)
        return None
