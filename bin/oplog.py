# -*- coding: utf-8 -*-
"""작업 기록 보기 (OPLOG_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '회계·인사 팀용 — 언제 무엇을 옮기고 지웠는지')

- 4Dir 로그(log_dir 안 4Dir.log, 4Dir.log.1 …)에서 파일 작업 줄만 골라 표로: 날짜·시간 / 작업 / 대상 / 결과
- 읽는 줄 (실제 로그 모양 11/8 확인):
  [QE.shell] '파일작업 시작 copy|move|delete n=.. dst=.. flags=0x.. first=[..]' + '파일작업 끝 … result=0 aborted=False' (짝 맞춰 결과)
  [QE] '이름변경 전체경로 -> 새이름' · '이름변경 실패 a -> b : 이유' · '새 폴더 경로' · '되돌리기 종류 설명'
  [QE.rename] '이름 일괄 변경 N개 완료 (첫: a → b)' · '이름 일괄 변경 실패'
  [QE.datefolders] '옮기기 끝 …' · [QE.pdftools] '합치기 끝 …' 등은 넣지 않음 (파일 작업만)
- 로그 줄에는 시각만 있고 날짜가 없음 → 파일의 마지막 수정 날짜에서 거꾸로 시각이 되감길 때마다 하루씩 빼서 날짜를 붙임
  (4Dir 를 며칠 안 켠 빈 날은 알 수 없어 그보다 앞 날짜는 하루 이틀 틀릴 수 있음)
- 날짜 고르기(오늘·어제·이번 주·전체) · 이름 찾기 · 두 번 누르면 그 위치 열기(open_loc 콜백)
- 읽기만 함(로그 파일을 바꾸지 않음). 큰 로그(파일당 2MB)는 뒤 스레드에서
로그: bin\\log\\4Dir.log [QE.oplog]
"""
import os
import re
import ast
import time
import logging
import datetime
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

OPLOG_VER = "1.0.0"
log = logging.getLogger("QE.oplog")
LINE = re.compile(r"^(\d\d):(\d\d):(\d\d)\.(\d{3}) (\w+) \[([^\]]+)\] (.*)$")
R_START = re.compile(r"^파일작업 시작 (\w+) n=(\d+) dst=(.*?) flags=0x([0-9a-fA-F]+) first=(\[.*\])\s*$")
R_END = re.compile(r"^파일작업 끝 (\w+) result=(\S+) aborted=(\w+)")
R_RENAME = re.compile(r"^이름변경 (.+?) -> (.+)$")
R_RENAME_FAIL = re.compile(r"^이름변경 실패 (.+?) -> (.+?) : (.*)$")
R_NEWDIR = re.compile(r"^새 폴더 (.+)$")
R_BATCH = re.compile(r"^이름 일괄 변경 (\d+)개 완료 \(첫: (.*) → (.*)\)$")
R_BATCH_FAIL = re.compile(r"^이름 일괄 변경 실패")
R_UNDO = re.compile(r"^되돌리기 (copy|move|delete|rename|newfolder|batch\w*) (.*)$")
KINDS = {"copy": "복사", "move": "이동", "trash": "휴지통으로", "delete": "영구 삭제", "rename": "이름 바꾸기",
         "batch": "이름 일괄 변경", "newfolder": "새 폴더", "undo": "되돌리기"}
FOF_ALLOWUNDO = 0x40


def kind_text(k):
    return T(KINDS.get(k, k))


def _first(s):
    try:
        v = ast.literal_eval(s)
        return v[0] if v else ""
    except Exception:
        return s.strip("[]'\"")


def parse(lines, last_date=None):
    """로그 줄(오래된 것부터) → [dict(date, time, kind, target, dest, count, result, ok)] (오래된 것부터).
    last_date = 마지막 줄의 날짜(datetime.date, 보통 파일 수정 날짜). 없으면 date=None. 해석 못 하는 줄은 무시"""
    recs = []
    pending = {}   # 작업 이름 → [기록…] (시작했고 끝 줄을 기다리는 것)
    stamps = []    # 줄마다 (초) — 날짜 맞추기용 (기록에 붙은 줄 번호)
    for raw in lines:
        m = LINE.match(raw.rstrip("\r\n"))
        if not m:
            continue
        hh, mi, ss, ms, lvl, name, msg = m.groups()
        sec = int(hh) * 3600 + int(mi) * 60 + int(ss)
        stamps.append(sec)
        li = len(stamps) - 1
        tm = f"{hh}:{mi}:{ss}"
        rec = None
        if name == "QE.shell":
            a = R_START.match(msg)
            if a:
                op, n, dst, flags, first = a.groups()
                if op == "delete":
                    op = "trash" if int(flags, 16) & FOF_ALLOWUNDO else "delete"
                elif op not in ("copy", "move", "rename"):
                    continue
                rec = {"time": tm, "kind": op, "target": _first(first), "dest": "" if dst == "None" else dst,
                       "count": int(n), "result": T("끝나지 않음"), "ok": None, "_li": li}
                pending.setdefault(a.group(1), []).append(rec)
            else:
                b = R_END.match(msg)
                if b and pending.get(b.group(1)):
                    r = pending[b.group(1)].pop(0)
                    res, ab = b.group(2), b.group(3) == "True"
                    if ab:
                        r["result"], r["ok"] = T("취소"), False
                    elif res == "0":
                        r["result"], r["ok"] = T("완료"), True
                    else:
                        r["result"], r["ok"] = T("실패 (코드 {0})").format(res), False
                continue
        elif name == "QE":
            a = R_RENAME_FAIL.match(msg) or R_RENAME.match(msg)
            if a and a.re is R_RENAME_FAIL:
                rec = {"time": tm, "kind": "rename", "target": a.group(1), "dest": os.path.basename(a.group(2)), "count": 1,
                       "result": T("실패"), "ok": False, "_li": li}
            elif a:
                rec = {"time": tm, "kind": "rename", "target": a.group(1), "dest": a.group(2), "count": 1,
                       "result": T("완료"), "ok": True, "_li": li}
            else:
                b = R_NEWDIR.match(msg)
                if b and ("\\" in b.group(1) or "/" in b.group(1)):
                    rec = {"time": tm, "kind": "newfolder", "target": b.group(1).strip(), "dest": "", "count": 1,
                           "result": T("완료"), "ok": True, "_li": li}
                else:
                    c = R_UNDO.match(msg)
                    if c and not msg.startswith("되돌리기 기록"):
                        rec = {"time": tm, "kind": "undo", "target": c.group(2), "dest": "", "count": 1,
                               "result": T("완료"), "ok": True, "undo_of": c.group(1), "_li": li}
        elif name == "QE.rename":
            a = R_BATCH.match(msg)
            if a:
                rec = {"time": tm, "kind": "batch", "target": a.group(2), "dest": a.group(3), "count": int(a.group(1)),
                       "result": T("완료"), "ok": True, "_li": li}
            elif R_BATCH_FAIL.match(msg):
                rec = {"time": tm, "kind": "batch", "target": "", "dest": "", "count": 0,
                       "result": T("실패 (원래대로 되돌림)"), "ok": False, "_li": li}
        if rec:
            recs.append(rec)
    # 날짜: 끝 줄 = last_date, 거꾸로 가며 시각이 커지면(= 그 앞날) 하루 빼기
    day_of = [None] * len(stamps)
    if last_date is not None and stamps:
        d = last_date
        nxt = stamps[-1]
        for i in range(len(stamps) - 1, -1, -1):
            if stamps[i] > nxt + 60:   # 1분 넘게 되감김 = 날 바뀜 (창 여러 개가 섞어 쓴 몇 초 어긋남은 무시)
                d -= datetime.timedelta(days=1)
            day_of[i] = d
            nxt = stamps[i]
    for r in recs:
        r["date"] = day_of[r.pop("_li")]
    return recs


def log_files(log_dir):
    """오래된 것부터 [4Dir.log.3, .2, .1, 4Dir.log] (있는 것만)"""
    out = []
    for k in range(9, 0, -1):
        p = os.path.join(log_dir, f"4Dir.log.{k}")
        if os.path.isfile(p):
            out.append(p)
    p = os.path.join(log_dir, "4Dir.log")
    if os.path.isfile(p):
        out.append(p)
    return out


def read_all(log_dir, cancel=lambda: False):
    """로그 폴더의 모든 파일 → 기록 (최근 것이 위)"""
    t0 = time.time()
    recs = []
    for p in log_files(log_dir):
        if cancel():
            return []
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()   # 날짜 맞추기에 모든 줄의 시각이 필요
            last = datetime.date.fromtimestamp(os.path.getmtime(p))
        except OSError as ex:
            log.warning("로그 못 읽음 %s: %s", p, ex)
            continue
        got = parse(lines, last)
        log.info("로그 읽음 %s %d줄 → 작업 %d개", os.path.basename(p), len(lines), len(got))
        recs += got
    recs.reverse()
    log.info("작업 기록 %d개 (%.2f초) %s", len(recs), time.time() - t0, log_dir)
    return recs


def in_range(rec, which, today=None):
    """which: 0 오늘 · 1 어제 · 2 이번 주(월요일부터) · 3 전체"""
    if which == 3:
        return True
    d = rec.get("date")
    if d is None:
        return False
    today = today or datetime.date.today()
    if which == 0:
        return d == today
    if which == 1:
        return d == today - datetime.timedelta(days=1)
    return today - datetime.timedelta(days=today.weekday()) <= d <= today


# ---------------------------------------------------------------- 아이콘
def tool_icon(sz=16):
    """시계 + 목록"""
    dpr = 2
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(sz * dpr / 20.0, sz * dpr / 20.0)
    p.setPen(QtGui.QPen(QtGui.QColor("#475569"), 1.0))
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawRect(QtCore.QRectF(2.5, 1.5, 11, 15))
    p.setPen(QtGui.QPen(QtGui.QColor("#94a3b8"), 1.1))
    for k in range(4):
        y = 4.5 + k * 2.8
        p.drawLine(QtCore.QPointF(4.5, y), QtCore.QPointF(11.5, y))
    p.setPen(QtGui.QPen(QtGui.QColor("#1d6fd6"), 1.2))
    p.setBrush(QtGui.QColor("#dbeafe"))
    p.drawEllipse(QtCore.QRectF(9.5, 9.5, 9, 9))
    p.setPen(QtGui.QPen(QtGui.QColor("#1d6fd6"), 1.3, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QtCore.QPointF(14, 14), QtCore.QPointF(14, 11.3))
    p.drawLine(QtCore.QPointF(14, 14), QtCore.QPointF(16.2, 15.2))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QtGui.QIcon(pm)


# ---------------------------------------------------------------- 창
class _Sig(QtCore.QObject):
    done = QtCore.Signal(list)


class OpLogDialog(QtWidgets.QDialog):
    COLS = ["날짜·시간", "작업", "대상", "옮긴 곳·새 이름", "결과"]

    def __init__(self, parent, log_dir, open_loc=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(T("작업 기록") + " — 4Dir")
        self.setWindowIcon(tool_icon(20))
        self.resize(980, 540)
        self.log_dir, self.open_loc = log_dir, open_loc
        self.recs = []
        self._cancel = False
        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.c_when = QtWidgets.QComboBox()
        self.c_when.addItems([T("오늘"), T("어제"), T("이번 주"), T("전체")])
        self.c_when.setCurrentIndex(0)
        self.e_find = QtWidgets.QLineEdit()
        self.e_find.setPlaceholderText(T("파일·폴더 이름으로 찾기"))
        self.e_find.setClearButtonEnabled(True)
        btn_re = QtWidgets.QPushButton(T("새로 읽기"))
        btn_re.clicked.connect(self.reload)
        row.addWidget(QtWidgets.QLabel(T("언제")))
        row.addWidget(self.c_when)
        row.addWidget(self.e_find, 1)
        row.addWidget(btn_re)
        lay.addLayout(row)
        self.table = QtWidgets.QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([T(c) for c in self.COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.verticalHeader().setDefaultSectionSize(22)
        for c, w in enumerate((140, 100, 330, 270)):
            self.table.setColumnWidth(c, w)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._open)
        lay.addWidget(self.table, 1)
        self.status = QtWidgets.QLabel()
        lay.addWidget(self.status)
        note = QtWidgets.QLabel(T("두 번 누르면 그 위치를 엽니다. 4Dir 에서 한 작업만 나옵니다 (탐색기에서 한 것은 없음)."))
        lay.addWidget(note)
        self.c_when.currentIndexChanged.connect(self.fill)
        self.e_find.textChanged.connect(self.fill)
        self.sig = _Sig()
        self.sig.done.connect(self._on_read)
        log.info("작업 기록 창 열기 %s", log_dir)
        self.reload()

    def reload(self):
        self.status.setText(T("기록 읽는 중…"))

        def work():
            try:
                res = read_all(self.log_dir, lambda: self._cancel)
            except Exception:
                log.exception("작업 기록 읽기 실패")
                res = []
            try:
                self.sig.done.emit(res)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True, name="oplog").start()

    def _on_read(self, recs):
        self.recs = recs
        self.fill()

    def shown(self):
        which = self.c_when.currentIndex()
        q = self.e_find.text().strip().lower()
        out = []
        for r in self.recs:
            if not in_range(r, which):
                continue
            if q and q not in (r["target"] + " " + r["dest"]).lower():
                continue
            out.append(r)
        return out

    def fill(self, *_):
        rows = self.shown()
        self.table.setRowCount(len(rows))
        red = QtGui.QColor("#c0392b")
        for i, r in enumerate(rows):
            when = (r["date"].strftime("%Y-%m-%d ") if r.get("date") else "") + r["time"]
            tgt = r["target"]
            if r["count"] > 1 and r["kind"] in ("copy", "move", "trash", "delete", "batch"):
                tgt = T("{0} 외 {1}개").format(tgt, r["count"] - 1)
            kt = kind_text(r["kind"])
            if r["kind"] == "undo" and r.get("undo_of") in KINDS:
                kt += f" ({kind_text(r['undo_of'])})"
            vals = [when, kt, tgt, r["dest"], r["result"]]
            for c, v in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(v)
                if c in (2, 3):
                    it.setToolTip(v)
                if c == 4 and r.get("ok") is False:
                    it.setForeground(red)
                if c == 1 and r["kind"] == "delete":
                    it.setForeground(red)
                self.table.setItem(i, c, it)
            self.table.item(i, 0).setData(Qt.UserRole, r)
        self.status.setText(T("{0}개 작업 (전체 {1}개)").format(len(rows), len(self.recs)))

    def _open(self, row, col):
        it = self.table.item(row, 0)
        r = it.data(Qt.UserRole) if it else None
        if not r:
            return
        # 지금 있을 곳: 이동·복사 = 옮긴 폴더, 이름 바꾸기 = 새 이름, 그 밖 = 대상
        p = r["target"]
        if r["kind"] in ("copy", "move") and r["dest"]:
            p = os.path.join(r["dest"], os.path.basename(r["target"]))
        elif r["kind"] in ("rename", "batch") and r["dest"]:
            p = r["dest"] if os.path.isabs(r["dest"]) else os.path.join(os.path.dirname(r["target"]), r["dest"])
        if not os.path.isabs(p):
            log.info("작업 기록 열기: 경로 모름 %r", p)
            return
        log.info("작업 기록 열기 %s", p)
        if self.open_loc:
            self.open_loc(p)
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(p if os.path.isdir(p) else os.path.dirname(p)))

    def closeEvent(self, ev):
        self._cancel = True
        super().closeEvent(ev)


def open_dialog(parent, log_dir, open_loc=None):
    d = OpLogDialog(parent, log_dir, open_loc)
    d.show()
    return d
