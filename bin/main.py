# -*- coding: utf-8 -*-
"""4Dir — 4분할 + 탭 파일 관리자 (3ds Max 안전형)

설계 원칙 (맥스 안전):
  1. 목록은 os.scandir 로 직접 읽음. 윈도우 셸 뷰·썸네일·오버레이(SVN/구글드라이브)·속성 핸들러를 부르지 않음.
  2. 파일·일반 폴더 아이콘은 확장자 기준(파일을 열지 않음). 드라이브·특수폴더만 실제 아이콘(작업 스레드, 시간 제한).
  3. 폴더 변경 감시는 화면에 보이는 탭만, 0.5초 묶어서 다시 읽기.
  4. 우클릭 셸 메뉴는 누를 때만.
  5. 유휴 시 타이머·폴링 없음. 애니메이션 없음.

로그: bin\\log\\4Dir.log
"""
QE_VERSION = "0.9.67"

import os
import sys
import json
import re
import time
import stat
import logging
import logging.handlers
import traceback
import ctypes
import subprocess
import ctypes.wintypes

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
if BIN_DIR not in sys.path:   # 배포판 휴대용 파이썬(._pth)은 스크립트 폴더를 자동으로 안 넣음(실측)
    sys.path.insert(0, BIN_DIR)
LOG_DIR = os.environ.get("QE_LOG_DIR") or os.path.join(BIN_DIR, "log")   # 시험은 따로 (실제 로그에 섞이지 않게)
STATE_FILE = os.path.join(BIN_DIR, "4Dir_state.json")
os.makedirs(LOG_DIR, exist_ok=True)

log = logging.getLogger("QE")
log.setLevel(logging.DEBUG)
class _SafeRotatingHandler(logging.handlers.RotatingFileHandler):
    """4Dir 를 여러 개 띄우면(창 여러 개 허용) 다른 쪽이 로그 파일을 열고 있어 이름 바꾸기(회전)가 실패함
    → 오류 대신 그냥 이어 쓰고 1분 뒤 다시 시도 (예전엔 매 줄마다 오류 출력)"""
    _retry_at = 0.0

    def shouldRollover(self, record):
        return time.time() >= self._retry_at and super().shouldRollover(record)

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            self._retry_at = time.time() + 60
            if self.stream is None:
                self.stream = self._open()


if not log.handlers:
    _h = _SafeRotatingHandler(os.path.join(LOG_DIR, "4Dir.log"),
                              maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s", "%H:%M:%S"))
    log.addHandler(_h)


def _excepthook(t, v, tb):
    log.error("처리 안 된 예외:\n%s", "".join(traceback.format_exception(t, v, tb)))


sys.excepthook = _excepthook

# ---- 멈춤 감시 (10/6: 밤사이 '응답 없음'으로 윈도우가 강제로 닫았는데 로그엔 원인이 없었음) ----
import faulthandler  # noqa: E402
HANG_SEC = 8
_hang = {"file": None, "last": 0.0}


def start_hang_watch(app):
    """화면(메인 스레드)이 HANG_SEC 초 넘게 멈추면 그 순간 모든 스레드의 위치를 log\\hang.log 에 남김.
    faulthandler 감시는 파이썬 잠금 없이 C 스레드로 돌아서, 메인이 윈도우 함수 안에서 굳어도 기록됨.
    3초마다 '살아 있음' 재무장만 함 (유휴 CPU 부담 없음). 풀리면 4Dir.log 에 몇 초 멈췄는지 남김.
    PC 절전에서 깨어날 때도 '멈춤'으로 한 번 기록될 수 있음."""
    p = os.path.join(LOG_DIR, "hang.log")
    try:
        if os.path.exists(p) and os.path.getsize(p) > 1_000_000:
            os.replace(p, p + ".1")
        f = open(p, "a", encoding="utf-8")
        f.write(f"\n=== 4Dir v{QE_VERSION} pid={os.getpid()} 시작 {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        f.flush()
        # 프로그램이 통째로 죽는 충돌도 위치 기록. all_threads=False (v0.9.57): 윈도우 셸(속성 창·끌기 등)이 안에서
        # 일부러 던지고 스스로 받는 COM 오류(0x8001010e)도 이 기록 장치가 잡는데, 그때마다 '모든 스레드' 위치를 훑다가
        # 다른 스레드가 움직이는 중이라 기록 장치 자체가 접근 위반으로 4Dir 를 죽임(10/21 실측: 속성 누른 순간 종료,
        # hang.log 가 줄 중간에서 끊기고 윈도우 오류 기록 = python313.dll c0000005). 지금 스레드만 기록하면 안전.
        # 멈춤 감시(dump_traceback_later)는 그대로 모든 스레드 기록.
        faulthandler.enable(file=f, all_threads=False)
        faulthandler.dump_traceback_later(HANG_SEC, exit=False, file=f)
    except Exception:
        log.exception("멈춤 감시 시작 실패")
        return
    _hang["file"] = f
    _hang["last"] = _awake_now()
    t = QtCore.QTimer(app)
    t.setInterval(3000)
    t.timeout.connect(_hang_tick)
    t.start()
    app._hang_timer = t
    log.info("멈춤 감시 시작 (%d초 넘게 멈추면 위치 기록: %s)", HANG_SEC, p)


def _awake_now():
    """PC 절전 시간을 뺀 시계(초). 절전에서 깨어난 걸 멈춤으로 착각하지 않게"""
    v = ctypes.c_ulonglong()
    if ctypes.windll.kernel32.QueryUnbiasedInterruptTime(ctypes.byref(v)):
        return v.value / 1e7
    return time.monotonic()


def _hang_pause(on):
    """끌어다 놓기 동안 멈춤 감시 끔 (바깥 프로그램이 처리하는 시간은 4Dir 멈춤이 아님)"""
    _hang["paused"] = on
    if on:
        faulthandler.cancel_dump_traceback_later()
        return
    _hang["last"] = _awake_now()
    if _hang["file"] is not None:
        faulthandler.dump_traceback_later(HANG_SEC, exit=False, file=_hang["file"])


def window_program_at_cursor():
    """마우스 아래 창의 프로그램 이름 (끌어다 놓은 곳 기록용). 모르면 '?'"""
    try:
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        pt = ctypes.wintypes.POINT()
        u.GetCursorPos(ctypes.byref(pt))
        u.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
        u.WindowFromPoint.restype = ctypes.c_void_p
        h = u.GetAncestor(ctypes.c_void_p(u.WindowFromPoint(pt)), 2)   # GA_ROOT
        pid = ctypes.wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        ph = k.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not ph:
            return f"? (pid {pid.value})"
        try:
            buf = ctypes.create_unicode_buffer(520)
            n = ctypes.wintypes.DWORD(520)
            ok = k.QueryFullProcessImageNameW(ph, 0, buf, ctypes.byref(n))
        finally:
            k.CloseHandle(ph)
        return os.path.basename(buf.value) if ok else f"? (pid {pid.value})"
    except Exception as ex:
        return f"? ({ex})"


def _hang_tick():
    if _hang.get("paused"):
        return
    now = _awake_now()
    gap = now - _hang["last"]
    _hang["last"] = now
    f = _hang["file"]
    if gap > HANG_SEC:
        log.warning("화면 멈춤 있었음 %.1f초 (풀린 시각 %s, 멈춘 위치는 log\\hang.log)", gap, time.strftime("%H:%M:%S"))
        try:
            f.write(f"--- 위 기록 뒤 풀림: 약 {gap:.0f}초 멈춤, 풀린 시각 {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            f.flush()
        except Exception:
            pass
        w = next((x for x in WINDOWS if x.isVisible()), None)   # 알림 + '문제 보고 만들기' 버튼
        if w is not None:
            # 알림은 닫을 때까지 남으므로 언제 멈췄는지 시각을 앞에 붙임 (10/7 사용자 요청) — 번역 문구는 그대로
            w.show_notice(time.strftime("[%H:%M] ") + T("⚠ 4Dir 화면이 약 {0}초 멈췄었습니다. 멈춘 위치를 기록해 두었습니다  ✕").format(f"{gap:.0f}"),
                          sticky=True, action=(T("문제 보고 만들기"), w.save_report))
    faulthandler.dump_traceback_later(HANG_SEC, exit=False, file=f)


def size_short(b):
    """탐색기 상태줄과 같은 짧은 크기 글자 (윈도우 StrFormatByteSizeW — 탐색기가 쓰는 것, 언어 따라감)"""
    buf = ctypes.create_unicode_buffer(32)
    try:
        if ctypes.windll.shlwapi.StrFormatByteSizeW(ctypes.c_longlong(int(b)), buf, 32):
            return buf.value
    except Exception:
        pass
    return f"{b:,}B"


# ---- 새 버전 알림 (웹에서 받은 사람용). 버전 정보 파일 하나만 읽고, 자동 설치는 안 함. 보내는 정보 없음(4Dir 버전 글자만)
# 파일 형식: {"version": "0.9.30", "page": "https://.../download", "notes": "", "notes_i18n": {"ko": "바뀐 점 한 줄", "en": ...}}
# v0.9.65: 바뀐 점은 화면 언어별(notes_i18n, 앱 언어 코드) — 없으면 notes(옛 형식). notes 는 옛 4Dir 가 영어로 띄우지 않게 비워 둠
# ★공개 사이트 주소 (v0.9.48) — 비어 있으면 홈페이지·후원 메뉴를 숨기고 새 버전 확인도 안 함
SITE_URL = "https://4dir.net/"   # 공개 사이트 (10/22 개인 도메인, 깃허브 무료 페이지). 끝에 / 붙일 것. 옛 gkstmdahr.github.io/4Dir/ 는 깃허브가 여기로 넘김
DONATE_URL = "https://ko-fi.com/4dirofficial"   # 후원 페이지 (10/21 개설). 비어 있으면 사이트의 후원 칸(#donate)
SUPPORT_EMAIL = "support@4dir.net"   # 문제 보고 받는 주소 (10/22, 클라우드플레어 메일 전달 → 개발자 지메일)
UPDATE_URL = SITE_URL + "version.json" if SITE_URL else ""


def open_link(url, what):
    log.info("링크 열기 %s %s", what, url)
    QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))


class _UpdateSig(QtCore.QObject):
    done = QtCore.Signal(object, object, bool)   # 결과 dict | None, 오류 글자 | None, 수동 여부


_UPD = {"sig": None, "busy": False}


def _ver_tuple(v):
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("v").split("."))
    except ValueError:
        return ()


def start_update_check(w, manual=False):
    """manual = 도구 메뉴에서 누름 (결과를 항상 알려줌). 자동은 설정 켜짐 + 오늘 아직 안 했을 때만, 새 버전 있을 때만 알림"""
    today = time.strftime("%Y-%m-%d")
    if not UPDATE_URL:
        log.info("새 버전 확인: 주소가 아직 없음 (UPDATE_URL)")
        if manual:
            w.show_notice(T("새 버전 확인 주소가 아직 없습니다 (배포 사이트 준비 중)  ✕"))
        return
    if not manual and (not SETTINGS["update_check"] or SETTINGS["update_last"] == today):
        return
    if _UPD["busy"]:
        return
    if _UPD["sig"] is None:
        _UPD["sig"] = _UpdateSig()
        _UPD["sig"].done.connect(_update_done)
    _UPD["busy"] = True
    _UPD["win"] = w
    import threading
    import urllib.request

    def run():
        t0 = time.time()
        try:
            req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": f"4Dir/{QE_VERSION}"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read(65536).decode("utf-8-sig"))
            log.info("새 버전 확인 %s → %s (%.0fms)", UPDATE_URL, data.get("version"), (time.time() - t0) * 1000)
            _UPD["sig"].done.emit(data, None, manual)
        except Exception as e:
            log.warning("새 버전 확인 실패 %s: %s", UPDATE_URL, e)
            _UPD["sig"].done.emit(None, str(e), manual)
    threading.Thread(target=run, daemon=True, name="update-check").start()


def _update_done(data, err, manual):
    _UPD["busy"] = False
    w = _UPD.get("win")
    if w is None or w not in WINDOWS:
        w = next((x for x in WINDOWS if x.isVisible()), None)
    if data is not None:
        SETTINGS["update_last"] = time.strftime("%Y-%m-%d")
    if w is None:
        return
    if err is not None:
        if manual:
            w.show_notice(T("⚠ 새 버전을 확인하지 못했습니다 (인터넷 연결 확인)  ✕"))
        return
    new = str(data.get("version", ""))
    page = data.get("page") or ""
    if _ver_tuple(new) > _ver_tuple(QE_VERSION):
        notes = (data.get("notes_i18n") or {}).get(i18n.lang) or data.get("notes") or ""
        log.info("새 버전 있음 v%s (지금 v%s) %s 건너뛴버전=%r", new, QE_VERSION, page, SETTINGS["update_skip"])
        if not manual and SETTINGS["update_skip"] == new:
            log.info("새 버전 팝업 생략: 사용자가 v%s 를 건너뛰기로 함", new)
            return
        show_update_notice(w, new, notes, page)
    elif manual:
        w.show_notice(T("지금 최신 버전입니다 (v{0})").format(QE_VERSION))


def show_update_notice(w, new, notes, page):
    """v0.9.63: 새 버전 알림 = 위쪽 알림 줄 (10/22 사용자 요청: 작업 중 팝업은 불편) — 작업을 막지 않고 누를 때까지 남음.
    받으러 가기 = 페이지 열기 / 이 버전 건너뛰기 = 그 버전은 자동 확인 때 다시 안 알림 / 알림 글자(✕) 누름 = 나중에(다음 날 다시)"""
    def get():
        log.info("새 버전 알림: 받으러 가기 v%s %s", new, page)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(page))

    def skip():
        log.info("새 버전 알림: v%s 건너뛰기", new)
        SETTINGS["update_skip"] = new
    text = T("새 버전 4Dir v{0} 이 나왔습니다 (지금 v{1})").format(new, QE_VERSION)
    if notes:
        text += " — " + notes
    w.show_notice(text + "  ✕", sticky=True, action=(T("받으러 가기"), get) if page else None,
                  action2=(T("이 버전 건너뛰기"), skip))


class _UndoSig(QtCore.QObject):
    done = QtCore.Signal(str)


_UNDO_SIG = []


def _undo_signal():
    """뒤에서 끝난 되돌리기 결과 → 보이는 첫 창의 알림 줄 (화면 스레드에서 처음 부를 것)"""
    if not _UNDO_SIG:
        sg = _UndoSig()
        sg.done.connect(lambda msg: next((w for w in WINDOWS if w.isVisible()), None) and
                        next(w for w in WINDOWS if w.isVisible()).show_notice(msg))
        _UNDO_SIG.append(sg)
    return _UNDO_SIG[0]


def report_dir():
    """문제 보고 zip 저장 폴더: <4Dir 폴더>
eports (쓰기 안 되면 %LOCALAPPDATA%Dir
eports)"""
    for d in (os.path.join(os.path.dirname(BIN_DIR), "reports"),
              os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "4Dir", "reports")):
        try:
            os.makedirs(d, exist_ok=True)
            t = os.path.join(d, ".write_test")
            open(t, "w").close()
            os.remove(t)
            return d
        except OSError:
            log.warning("문제 보고 폴더 쓰기 안 됨 %s", d)
    return os.path.expanduser("~")


# ---- 작업표시줄 고정 (10/6: 창을 고정하면 빈 pythonw 가 고정돼 눌러도 안 켜졌음) ----
APP_ID = "4Dir.FileManager"


def _app_ico():
    """창 아이콘을 .ico 파일로 (작업표시줄 고정 아이콘용). 이미 있으면 그대로. PNG 를 담는 ICO 형식."""
    p = os.path.join(BIN_DIR, "4Dir.ico")
    if os.path.exists(p):
        return p
    import struct
    icon = ui_parts.app_icon()
    imgs = []
    for s in (16, 24, 32, 48, 256):
        ba = QtCore.QByteArray()
        buf = QtCore.QBuffer(ba)
        buf.open(QtCore.QIODevice.WriteOnly)
        icon.pixmap(s, s).save(buf, "PNG")
        buf.close()
        imgs.append((s, bytes(ba)))
    head = struct.pack("<HHH", 0, 1, len(imgs))
    off = 6 + 16 * len(imgs)
    ents, data = b"", b""
    for s, b in imgs:
        ents += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), off + len(data))
        data += b
    with open(p, "wb") as f:
        f.write(head + ents + data)
    return p


def set_taskbar_relaunch(w):
    """창에 '다시 실행할 명령'을 달아 둠 → 작업표시줄에 고정하면 4Dir.vbs + 4Dir 아이콘으로 고정됨 (윈도우 표준 방식)"""
    try:
        from win32com.propsys import propsys, pscon
        import pythoncom
        vbs = os.path.join(os.path.dirname(BIN_DIR), "4Dir.vbs")
        if not os.path.exists(vbs):
            log.info("작업표시줄 고정 정보 건너뜀: 실행기 없음 %s", vbs)
            return
        wscript = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wscript.exe")
        cmd = f'"{wscript}" "{vbs}"'
        try:
            ico = _app_ico()
        except Exception:
            log.exception("아이콘 파일 만들기 실패")
            ico = None
        store = propsys.SHGetPropertyStoreForWindow(int(w.winId()), propsys.IID_IPropertyStore)

        def put(key, val):
            store.SetValue(key, propsys.PROPVARIANTType(val, pythoncom.VT_LPWSTR))
        put(pscon.PKEY_AppUserModel_ID, APP_ID)
        put(pscon.PKEY_AppUserModel_RelaunchCommand, cmd)
        put(pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, "4Dir")
        if ico:
            put(pscon.PKEY_AppUserModel_RelaunchIconResource, ico + ",0")
        store.Commit()
        log.info("작업표시줄 고정 정보 설정: %s (아이콘 %s)", cmd, ico)
    except Exception:
        log.exception("작업표시줄 고정 정보 설정 실패")

import shellops  # noqa: E402  (로그 설정 뒤에 import)
import favorg  # noqa: E402
import favorites  # noqa: E402
import session  # noqa: E402
import ui_parts  # noqa: E402
import keymap  # noqa: E402
import search_index  # noqa: E402
import svnstat  # noqa: E402
import thumbs  # noqa: E402
import overlays  # noqa: E402
import i18n  # noqa: E402
from i18n import T  # noqa: E402  (화면 문구 번역)

VIEW_KEYS = {}   # 파일 목록 단축키 {키: 기능} — Main.apply_keys 가 채움


def key_text(action):
    """기능의 지금 단축키(사용자 설정 반영) 첫 번째 → 화면 글자 (없으면 '')"""
    ks = keymap.current(SETTINGS["keys"]).get(action) or []
    # 탐색기 표기처럼 Return → Enter
    return QtGui.QKeySequence(ks[0]).toString(QtGui.QKeySequence.NativeText).replace("Return", "Enter") if ks else ""


def mlabel(text, action=None, mn=None):
    """메뉴 글자: 탐색기처럼 '새 폴더(N)' 밑줄 글자 + 오른쪽에 단축키 (10/8 사용자 요청).
    밑줄 글자 '(&N)' 는 탐색기가 그렇게 쓰는 한·중·일 언어에서만"""
    if mn and i18n.lang in ("ko", "ja", "zh_CN", "zh_TW"):
        text = f"{text}(&{mn})"
    k = key_text(action) if action else ""
    return f"{text}\t{k}" if k else text

THIS_PC = "내 PC"
HIDDEN_MASK = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM
WATCH_DELAY_MS = 500

# 전역 보기 옵션 (모든 칸 공통)
OPTS = {"show_hidden": False, "show_ext": True, "checkboxes": False,
        "date_folders_first": False,
        "svn_status": True,
        "thumbnails": True,
        "vcs_overlay": True}   # vcs_overlay = SVN 아닌 폴더에서 윈도우 겹침 아이콘(Git·Perforce 등) 표시   # thumbnails = 아이콘 보기에서 그림 미리보기 / 날짜 정렬 때 폴더를 위로 모을지 (기본: 섞어서 날짜순 = 윈도우와 같음)
NPANES = 6   # 처음 만들어 두는 칸 수 (위 줄 0,1,4 / 아래 줄 2,3,5). 직접 지정(가로x세로)이면 필요할 때 더 만듦
MAX_COLS, MAX_ROWS = 5, 4   # 직접 지정 최대 가로 5 x 세로 4 = 20칸
# 칸별 보기 방식
VIEW_MODES = [("details", T("자세히"), 16), ("list", T("목록"), 16), ("small", T("작은 아이콘"), 16),
              ("medium", T("보통 아이콘"), 48), ("large", T("큰 아이콘"), 96), ("xlarge", T("아주 큰 아이콘"), 256)]
MODE_PX = {k: px for k, _, px in VIEW_MODES}
SORT_COLS = [(0, T("이름")), (1, T("수정한 날짜")), (2, T("유형")), (3, T("크기"))]
FAV = favorites.Favorites()
# 우클릭 메뉴에서 윈도우 자체의 '즐겨찾기에 추가(F)'(탐색기 빠른 실행 고정)와 헷갈리지 않게 ★QE 표시
QE_FAV = T("★ 4Dir 즐겨찾기")
QE_FAV_ADD = T("★ 4Dir 즐겨찾기에 추가")
SETTINGS = ui_parts.Settings()   # 색상·즐겨찾기 바 펼침·항상 위 (세션과 무관한 전역 설정)
WS_DIR = os.path.join(BIN_DIR, "workspaces")   # 이름 붙여 저장한 창 구성
SINGLE_NAME = "4Dir_single_" + os.environ.get("USERNAME", "user")   # 하나만 실행용 통신 이름


SEARCH_PREFIX = "🔎 "   # 검색 결과 탭의 '경로' 표시: "🔎 검색어" (전체 검색) / "🔎 검색어 @ 폴더" (그 폴더 아래 찾기)
SEARCH = None          # search_index.SearchIndex (첫 창이 만듦, 모든 창이 같이 씀)
WINDOWS = []           # 열린 4Dir 창들 (Main). 순서 = 마지막에 쓴 창이 맨 뒤
SSIG = None            # 검색 색인 알림 (모든 창이 받음)
CLOSED = []            # 다른 창이 남은 채 닫힌 창들 [(시각, 연 순서, 상태)] — 한꺼번에 닫힐 때 원래 메인 고르기
_ORDER = [0]           # 창을 연 순서 번호
UNDO = []              # 되돌리기(Ctrl+Z) 기록 [(종류, 자료, 설명)] — 이름 바꾸기·새 폴더·이동·복사 (삭제는 휴지통에서)
SERVER = None          # 하나만 실행용 통신 (창이 아니라 프로그램 소유 → 첫 창을 닫아도 유지)
THUMBS = None          # 그림 미리보기 (thumbs.Thumbs, 처음 필요할 때 만듦, 모든 창이 같이 씀)
THUMB_MODES = ("small", "medium", "large", "xlarge")   # 미리보기를 보여줄 보기 방식 (자세히·목록은 안 함)
MODELS = []            # 미리보기 완성 알림을 받을 목록 모델들 (약한 참조 대신 닫힐 때 빠짐)


def thumbs_service():
    global THUMBS
    if THUMBS is None:
        THUMBS = thumbs.Thumbs()
        THUMBS.ready.connect(_thumb_ready)
    return THUMBS


OVL = None            # 버전 관리 표시(윈도우 겹침 아이콘) overlays.Overlays


def overlay_service():
    global OVL
    if OVL is None:
        OVL = overlays.Overlays()
        OVL.ready.connect(_ovl_ready)
    return OVL


def _ovl_ready(path, px):
    folder = os.path.dirname(path)
    for m in list(MODELS):
        try:
            m.thumb_ready(path, folder, px, overlay=True)
        except RuntimeError:
            MODELS.remove(m)


def _thumb_ready(path, px):
    folder = os.path.dirname(path)
    for m in list(MODELS):
        try:
            m.thumb_ready(path, folder, px)
        except RuntimeError:   # 지워진 모델
            MODELS.remove(m)


LIST_TEXT = {False: (QtGui.QColor("#000000"), QtGui.QColor("#6d6d6d")),   # 밝게: 이름, 그 밖의 칸
             True: (QtGui.QColor("#ffffff"), QtGui.QColor("#a0a0a0"))}     # 어둡게 (탐색기 어둡게는 아직 실측 안 함)


def tortoise_overlay_icons():
    """TortoiseSVN 이 탐색기에 그리는 겹침 아이콘 그림(설치돼 있으면) → {상태: QIcon}. 4Dir 배지를 탐색기와 같은 그림으로
    (10/6 사용자: 아이콘 채도·명도가 다름 — 실측 채도 0.51 vs 0.36, 차이는 4Dir 가 직접 그린 평평한 배지)"""
    global _TSVN_ICONS
    if _TSVN_ICONS is None:
        _TSVN_ICONS = {}
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\TortoiseOverlays") as k:
                for st, val in (("normal", "NormalIcon"), ("modified", "ModifiedIcon"), ("added", "AddedIcon"),
                                ("conflict", "ConflictIcon"), ("deleted", "DeletedIcon")):
                    try:
                        p = winreg.QueryValueEx(k, val)[0]
                    except OSError:
                        continue
                    if p and os.path.isfile(p):
                        ic = QtGui.QIcon(p)
                        if not ic.isNull():
                            _TSVN_ICONS[st] = ic
        except OSError:
            pass
        log.info("TortoiseSVN 겹침 아이콘 그림 %d개 %s", len(_TSVN_ICONS), sorted(_TSVN_ICONS))
    return _TSVN_ICONS


_TSVN_ICONS = None


class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, ctypes.wintypes.WORD) for n in ("y", "m", "dow", "d", "h", "mi", "s", "ms")]


_DT_CACHE = {}


def win_datetime(ts):
    """탐색기와 같은 날짜·시각 글자 — 윈도우 사용자 지역 설정(짧은 날짜 + 시각, 초 없음). 예: 2026-10-01(목) 오후 9:24
    (10/6 탐색기 캡처와 비교해 맞춤. 같은 분은 한 번만 만듦)"""
    key = int(ts) // 60
    v = _DT_CACHE.get(key)
    if v is None:
        t = time.localtime(ts)
        st = _SYSTEMTIME(t.tm_year, t.tm_mon, (t.tm_wday + 1) % 7, t.tm_mday, t.tm_hour, t.tm_min, 0, 0)
        b = ctypes.create_unicode_buffer(80)
        try:
            k = ctypes.windll.kernel32
            k.GetDateFormatEx(None, 1, ctypes.byref(st), None, b, 80, None)        # DATE_SHORTDATE
            d = b.value
            k.GetTimeFormatEx(None, 2, ctypes.byref(st), None, b, 80)              # TIME_NOSECONDS
            v = f"{d} {b.value}"
        except Exception:
            v = time.strftime("%Y-%m-%d %H:%M", t)
        if len(_DT_CACHE) > 20000:
            _DT_CACHE.clear()
        _DT_CACHE[key] = v
    return v


def win_kbsize(n):
    """탐색기 '크기' 열과 같은 글자 (StrFormatKBSizeW): 1,190KB"""
    b = ctypes.create_unicode_buffer(40)
    try:
        if ctypes.windll.shlwapi.StrFormatKBSizeW(ctypes.c_longlong(int(n)), b, 40):
            return b.value
    except Exception:
        pass
    return f"{(n + 1023) // 1024:,} KB"


def is_search(p):
    return bool(p) and p.startswith(SEARCH_PREFIX)


def search_path(q, folder=None):
    return SEARCH_PREFIX + q.strip() + (f" @ {folder}" if folder else "")


def parse_search(p):
    body = p[len(SEARCH_PREFIX):]
    if " @ " in body:
        q, f = body.rsplit(" @ ", 1)
        return q, f
    return body, None


def norm(p):
    return os.path.normpath(p) if p and p != THIS_PC and not is_search(p) else p


def disp_path(p):
    """주소줄에 보여줄 글자 ('내 PC' 표식만 번역, 실제 경로는 그대로)"""
    return T(THIS_PC) if p == THIS_PC else p


def tab_title(p):
    if p == THIS_PC:
        return T(THIS_PC)
    if is_search(p):
        q, f = parse_search(p)
        return f"🔎 {q}" + (T(' ({0} 아래)').format(tab_title(f)) if f else "")
    b = os.path.basename(p.rstrip("\\/"))
    return b or p


# ================================================================ 폴더 읽기 (작업 스레드)
class ScanSignals(QtCore.QObject):
    done = QtCore.Signal(int, str, list, float, str)  # gen, path, entries, ms, error
    partial = QtCore.Signal(int, list)                 # gen, entries (폴더 아래 찾기 중간 결과)
    info = QtCore.Signal(int, str)                     # gen, 검색 요약
    svn = QtCore.Signal(int, str, object)              # gen, path, {이름: SVN 상태}


class SvnJob(QtCore.QRunnable):
    """폴더 목록을 다 보여준 뒤 SVN 상태를 따로 읽음 (목록 표시를 늦추지 않음)"""
    def __init__(self, gen, path, names, signals):
        super().__init__()
        self.gen, self.path, self.names, self.sig = gen, path, names, signals

    def run(self):
        try:
            st = svnstat.folder_status(self.path, [n for n, _d in self.names])
            root = svnstat.wc_root(self.path) if st else None
            if root:
                # 폴더 배지 = '안쪽 어딘가 변경' (TortoiseSVN 같은 뜻). 작업 폴더 전체 감시는 처음 들어올 때 만듦
                w = svnstat.watch_for(root, lambda r: SVN_SIG.changed.emit(r))
                if w.state != "ready" and any(isd and st.get(n) == "normal" for n, isd in self.names):
                    w.quick_scan(self.path)   # 전체 훑기 기다리지 않고 보고 있는 폴더 안쪽만 먼저 확인
                for n, isd in self.names:
                    if isd and st.get(n) == "normal":
                        dd = w.folder_dirty(os.path.join(self.path, n))
                        if dd is None:
                            st.pop(n, None)          # 아직 모름(큰 폴더, 전체 훑는 중) → 배지 없음 + 상태줄 'SVN 확인 중'
                            st["\0pending"] = True
                        elif dd:
                            st[n] = "modified"
        except Exception:
            log.exception("SVN 상태 읽기 실패 %s", self.path)
            st = {}
        self.sig.svn.emit(self.gen, self.path, st)


class FavSvnJob(QtCore.QRunnable):
    """즐겨찾기 바 폴더들의 SVN 상태 (10/19 사용자: 탐색기 즐겨찾기처럼 SVN 폴더 표시).
    목록 배지와 같은 뜻: 안쪽 어딘가 변경 = modified(빨강), 없음 = normal(초록), 아직 모름(처음 훑는 중) = 없음.
    작업 스레드에서 — 네트워크 드라이브 즐겨찾기가 느려도 화면 안 멈춤"""
    def __init__(self, paths, done):
        super().__init__()
        self.paths, self.done = paths, done

    def run(self):
        out = {}
        for p in self.paths:
            try:
                root = svnstat.wc_root(p) if os.path.isdir(p) else None
                if not root:
                    continue
                w = svnstat.watch_for(root, lambda r: SVN_SIG.changed.emit(r))
                dd = w.folder_dirty(p)
                if dd is not None:
                    out[p] = "modified" if dd else "normal"
            except Exception:
                log.exception("즐겨찾기 SVN 상태 실패 %s", p)
        try:
            self.done.emit(out)
        except RuntimeError:   # 그사이 창이 닫힘
            pass


class FavSvnSig(QtCore.QObject):
    done = QtCore.Signal(dict)


class SvnSig(QtCore.QObject):
    changed = QtCore.Signal(str)    # 작업 폴더 뿌리 — 그 안을 보는 탭은 SVN 배지 다시 읽기


SVN_SIG = SvnSig()


class TreeSig(QtCore.QObject):
    """폴더가 옮겨지거나 복사됨 → 왼쪽 탐색 창들이 그 자리 하위 목록을 다시 읽음 (작업 스레드에서도 보냄)"""
    changed = QtCore.Signal(list)


TREE_SIG = TreeSig()


class ScanJob(QtCore.QRunnable):
    """entry = [name, is_dir, size, mtime, attrs, full_path, sysidx, label]"""

    def __init__(self, gen, path, signals, cancel=None):
        super().__init__()
        self.gen, self.path, self.sig = gen, path, signals
        self.cancel = cancel or (lambda: False)

    def run(self):
        t0 = time.perf_counter()
        entries, err = [], ""
        try:
            if self.path == THIS_PC:
                entries = this_pc_entries()
            elif is_search(self.path):
                q, folder = parse_search(self.path)

                def rows(lst):
                    return [[n, d, s, m, 0, pth, None, None] for pth, n, d, s, m in lst]
                if folder:   # 색인 없이 그 폴더 아래를 바로 훑기 (중간 결과를 계속 보냄)
                    total, scanned = search_index.folder_search(
                        folder, q, self.cancel, lambda b: self.sig.partial.emit(self.gen, rows(b)))
                    self.sig.info.emit(self.gen, T('{0:,}개 찾음 (훑은 항목 {1:,}개)').format(total, scanned) + (T(" — 취소됨") if self.cancel() else ""))
                elif SEARCH is not None:
                    res, total, ms = SEARCH.search(q)
                    entries = rows(res)
                    note = "" if SEARCH.state == "ready" else T(" (색인 만드는 중 — 결과가 덜 나올 수 있음)")
                    self.sig.info.emit(self.gen, T('{0:,}개').format(total) + (T(' (앞 {0:,}개만 표시)').format(len(res)) if total > len(res) else "") + f" · {ms:.0f}ms" + note)
            else:
                # DirEntry.stat() 은 윈도우에서 FindFirstFile 결과를 재사용 → 파일을 열지 않음
                with os.scandir(self.path) as it:
                    for de in it:
                        try:
                            st = de.stat(follow_symlinks=False)
                            isd = de.is_dir(follow_symlinks=False)
                            entries.append([de.name, isd, -1 if isd else st.st_size, st.st_mtime,
                                            st.st_file_attributes, None, None, None])
                        except OSError:
                            entries.append([de.name, False, -1, 0, 0, None, None, None])
        except Exception as e:
            err = str(e)
        self.sig.done.emit(self.gen, self.path, entries, (time.perf_counter() - t0) * 1000, err)


def this_pc_entries():
    """내 PC: 특수 폴더 + 드라이브 (실제 이름·아이콘). 작업 스레드에서 호출."""
    out = []
    for label, fp in shellops.known_folders():
        if os.path.isdir(fp):
            name, idx = shellops.real_info(fp)
            out.append([fp, True, -1, 0, 0, fp, idx, name or label])
    for d in os.listdrives():
        name, idx = shellops.real_info(d)
        out.append([d, True, -1, 0, 0, d, idx, name])
    return out


POOL = QtCore.QThreadPool()
POOL.setMaxThreadCount(4)


# ================================================================ 목록 모델
COLS = [T("이름"), T("수정한 날짜"), T("유형"), T("크기"), T("위치")]   # 위치 = 검색 결과에서만 보임


class DirModel(QtCore.QAbstractTableModel):
    renamed = QtCore.Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = ""
        self.all = []      # 폴더의 전체 항목 (정렬됨)
        self.rows = []     # 화면에 보이는 항목 (빠른 필터 적용)
        self.filter = ""
        self.sort_col, self.sort_order = 0, Qt.AscendingOrder
        self.icon_px = 16
        self.svn = {}      # 이름 → SVN 상태 (svnstat.folder_status, 따로 늦게 채움)
        self.thumbs_on = False   # 아이콘 보기 + 미리보기 켬 → 그림 파일은 미리보기 (thumbs.py)
        self.thumb_px = 16       # 실제 화면 픽셀 크기 (배율 반영)
        self.ovl_on = False      # SVN 아닌 폴더 + 설정 켬 → 윈도우 겹침 아이콘(Git·Perforce 등) (overlays.py)
        MODELS.append(self)
        self.destroyed.connect(lambda *_a, m=self: MODELS.remove(m) if m in MODELS else None)   # 탭 닫으면 빠짐

    def thumb_ready(self, path, folder, px, overlay=False):
        """미리보기·겹침 아이콘 하나 완성 → 그 줄만 다시 그림"""
        if (not self.ovl_on if overlay else not self.thumbs_on) or px != self.thumb_px:
            return
        same = os.path.normcase(folder) == os.path.normcase(self.path)
        low = path.lower()
        for r, e in enumerate(self.rows):
            if (same and not e[5] and os.path.join(self.path, e[0]).lower() == low) or (e[5] and e[5].lower() == low):
                ix = self.index(r, 0)
                self.dataChanged.emit(ix, ix, [Qt.DecorationRole])
                return

    def full(self, e):
        return e[5] or os.path.join(self.path, e[0])

    def svn_status(self, row):
        if not self.svn or row >= len(self.rows):
            return None
        return self.svn.get(self.rows[row][0])

    def set_entries(self, path, entries):
        self.beginResetModel()
        if path != self.path:
            self.svn = {}   # 같은 폴더 다시 읽기면 새 상태가 올 때까지 이전 표시 유지(깜빡임 방지)
        # 버전 관리 표시(윈도우): SVN 작업 폴더는 4Dir 배지를 쓰므로 제외. 다시 읽을 때마다 그 폴더 결과는 새로 물어봄(커밋 등)
        self.ovl_on = bool(OPTS["vcs_overlay"] and path and path != THIS_PC and not is_search(path)
                           and svnstat.wc_root(path) is None)
        if self.ovl_on and OVL is not None:
            OVL.forget(path)
        self.path, self.all = path, entries
        self._sort()
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(COLS)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if o == Qt.Horizontal and role == Qt.DisplayRole:
            return COLS[s]
        return None

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        e, c = self.rows[idx.row()], idx.column()
        if role == Qt.DisplayRole:
            if c == 0:
                if e[7]:
                    return e[7]
                if not OPTS["show_ext"] and not e[1]:
                    return os.path.splitext(e[0])[0] or e[0]
                return e[0]
            if c == 1:
                return win_datetime(e[3]) if e[3] else ""
            if c == 2:
                if e[5] and e[0].endswith(":\\"):
                    return T("드라이브")
                return shellops.type_for(e[0], e[1])
            if c == 3:
                return "" if e[2] < 0 else win_kbsize(e[2])
            if c == 4:
                return os.path.dirname(e[5]) if e[5] and not e[7] else ""
        elif role == Qt.EditRole and c == 0:
            return e[0]
        elif role == Qt.DecorationRole and c == 0:
            if self.thumbs_on and not e[1] and thumbs.is_image(e[0]):
                pm = thumbs_service().get(self.full(e), e[3], self.thumb_px)
                if pm is not None:
                    pm.setDevicePixelRatio(self.thumb_px / max(1, self.icon_px))
                    return pm
            if self.ovl_on and not (e[5] and e[0].endswith(":\\")):
                pm = overlay_service().get(self.full(e), e[3], self.thumb_px)
                if pm:
                    pm.setDevicePixelRatio(max(1.0, pm.width() / max(1, self.icon_px)))
                    return pm
            return shellops.icon_for(e[0], e[1], self.icon_px, e[6])
        elif role == Qt.TextAlignmentRole and c == 3:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.ForegroundRole and (e[4] & HIDDEN_MASK):
            return QtGui.QColor(140, 140, 140)
        elif role == Qt.ForegroundRole:
            # 탐색기와 같게: 이름 = 진한 검정, 날짜·유형·크기 = 회색 (10/6 탐색기 캡처 실측 #000000 / #6d6d6d)
            return LIST_TEXT[bool(SETTINGS["dark"])][0 if c == 0 else 1]
        elif role == Qt.ToolTipRole and c == 0 and e[5]:
            return e[5]
        return None

    def flags(self, idx):
        f = super().flags(idx)
        if idx.isValid():
            f |= Qt.ItemIsDragEnabled
            if idx.column() == 0 and self.path != THIS_PC:
                f |= Qt.ItemIsEditable
        return f

    def setData(self, idx, value, role=Qt.EditRole):
        if role != Qt.EditRole or idx.column() != 0:
            return False
        e = self.rows[idx.row()]
        new = str(value).strip()
        if not new or new == e[0]:
            return False
        src = self.full(e)
        dst = os.path.join(os.path.dirname(src), new)   # 검색 결과는 항목마다 폴더가 다름
        try:
            os.rename(src, dst)
        except OSError as ex:
            log.warning("이름변경 실패 %s -> %s : %s", src, dst, ex)
            QtWidgets.QMessageBox.warning(None, T("이름 바꾸기"), T('이름을 바꿀 수 없습니다.\n{0}').format(ex))
            return False
        log.info("이름변경 %s -> %s", src, new)
        push_undo("rename", (dst, src), T('이름 바꾸기 ({0} → {1})').format(os.path.basename(src), new))
        e[0] = new
        if e[5]:
            e[5] = dst
        self.dataChanged.emit(idx, idx)
        self.renamed.emit(src, dst)
        return True

    def sort(self, col, order=Qt.AscendingOrder):
        self.sort_col, self.sort_order = col, order
        self.layoutAboutToBeChanged.emit()
        self._sort()
        self.layoutChanged.emit()

    def _sort(self):
        self.all = self._sorted(self.all)
        self.rows = self._filtered(self.all)

    def _filtered(self, rows):
        """빠른 필터: 이름에 글자 포함(대소문자 무시). * ? 가 있으면 와일드카드."""
        f = self.filter.strip().lower()
        if not f:
            return list(rows)
        if "*" in f or "?" in f:
            import fnmatch
            pat = f if ("*" in f[0] + f[-1]) else f"*{f}*"
            return [e for e in rows if fnmatch.fnmatch((e[7] or e[0]).lower(), pat)]
        return [e for e in rows if f in (e[7] or e[0]).lower()]

    def append_rows(self, rows):
        """폴더 아래 찾기 중간 결과 추가"""
        self.all.extend(rows)
        new = self._filtered(rows)
        if new:
            self.beginInsertRows(QtCore.QModelIndex(), len(self.rows), len(self.rows) + len(new) - 1)
            self.rows.extend(new)
            self.endInsertRows()

    def set_filter(self, text):
        self.filter = text or ""
        self.beginResetModel()
        self.rows = self._filtered(self.all)
        self.endResetModel()

    def _sorted(self, rows):
        if self.path == THIS_PC:
            return list(rows)
        c, rev = self.sort_col, self.sort_order == Qt.DescendingOrder
        if c == 1:
            key = lambda e: e[3]
        elif c == 2:
            key = lambda e: (shellops.type_for(e[0], e[1]).lower(), shellops.natural_key(e[0]))
        elif c == 3:
            key = lambda e: e[2]
        elif c == 4:
            key = lambda e: ((os.path.dirname(e[5]) if e[5] else "").lower(), shellops.natural_key(e[0]))
        else:
            key = lambda e: shellops.natural_key(e[0])
        if c == 1 and not OPTS["date_folders_first"]:
            # 수정한 날짜 정렬: 윈도우 탐색기처럼 폴더·파일을 섞어서 날짜순 (기본)
            return sorted(rows, key=key, reverse=rev)
        dirs = sorted((e for e in rows if e[1]), key=key, reverse=rev)
        files = sorted((e for e in rows if not e[1]), key=key, reverse=rev)
        return dirs + files  # 이름·유형·크기 정렬은 폴더가 위

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, idxs):
        md = QtCore.QMimeData()
        rows = sorted({i.row() for i in idxs})
        md.setUrls([QtCore.QUrl.fromLocalFile(self.full(self.rows[r])) for r in rows])
        return md

    def supportedDragActions(self):
        return Qt.CopyAction | Qt.MoveAction | Qt.LinkAction


# ================================================================ 항목 확인란 (선택 상태를 체크박스로 표시)
class _SelArrows(QtCore.QObject):
    """이름 편집칸: 고른 글자가 있을 때 → = 고른 끝(마지막 글자 바로 뒤), ← = 고른 처음 (윈도우 탐색기와 같게).
    Qt 기본은 커서에서 한 칸 더 가서 F2 뒤 → 를 누르면 '.' 오른쪽에 붙었음 (10/6 사용자 지적)"""

    def eventFilter(self, ed, ev):
        if (ev.type() == QtCore.QEvent.KeyPress and ev.key() in (Qt.Key_Up, Qt.Key_Down)
                and not (ev.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier))
                and isinstance(ed, QtWidgets.QLineEdit)):
            return self._edit_next(ed, -1 if ev.key() == Qt.Key_Up else 1)
        if (ev.type() == QtCore.QEvent.KeyPress and ev.key() in (Qt.Key_Right, Qt.Key_Left)
                and not (ev.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier))
                and isinstance(ed, QtWidgets.QLineEdit) and ed.hasSelectedText()):
            a = ed.selectionStart()
            b = a + len(ed.selectedText())
            ed.deselect()
            ed.setCursorPosition(b if ev.key() == Qt.Key_Right else a)
            return True
        return False

    def _edit_next(self, ed, step):
        """이름 편집 중 ↑↓ = 지금 이름 확정 + 위/아래 항목 이름 편집 (10/7 사용자 요청).
        이름 바꾸기(setData)는 줄 순서를 안 바꾸고, 편집 중 목록 다시 읽기는 끝날 때까지 미뤄지므로 줄 번호 그대로 씀"""
        vp = ed.parentWidget()
        view = vp.parentWidget() if vp is not None else None
        if not isinstance(view, QtWidgets.QAbstractItemView):
            return False
        cur = view.currentIndex()
        m = view.model()
        row = cur.row() + step
        if not cur.isValid() or not (0 <= row < m.rowCount()):
            return True   # 맨 위·맨 아래: 편집 그대로
        dl = view.itemDelegate()
        page = getattr(view, "page", None)
        dl.commitData.emit(ed)   # 이름 바꾸기 → 목록 다시 읽기 요청은 편집 중이라 미뤄짐
        log.info("이름 편집 %s → 다음 항목 %d", "↑" if step < 0 else "↓", row)
        # 편집칸을 닫으면 미룬 다시 읽기가 바로 돌아 다음 편집칸을 닫아버림 → 다음 편집이 끝날 때까지 계속 미룸
        pend = page.reload_after_edit if page is not None else False
        if page is not None:
            page.reload_after_edit = False
        dl.closeEditor.emit(ed, QtWidgets.QAbstractItemDelegate.NoHint)
        nxt = m.index(row, 0)
        view.setCurrentIndex(nxt)
        view.selectionModel().select(nxt, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
        view.scrollTo(nxt)
        view.edit(nxt)
        if page is not None:
            page.reload_after_edit = page.reload_after_edit or pend
            if not page.editing() and page.reload_after_edit:   # 다음 항목 편집 못 열면 바로 다시 읽기
                page.editor_closed()
        return True


_SEL_ARROWS = _SelArrows()


def paint_svn_badge(p, r, cell, st):
    """아이콘 자리 r 에 SVN 배지 (목록·즐겨찾기 바 공용). cell = 잘리지 않게 맞출 바깥 칸"""
    ts = tortoise_overlay_icons().get(st)
    if ts is not None:   # TortoiseSVN 그림이 있으면 탐색기와 똑같이: 아이콘 크기 그대로 겹쳐 그림(그림 안에서 왼쪽 아래)
        ts.paint(p, r, Qt.AlignCenter)
        return
    # 16px 아이콘 → 11px (9px 는 모양이 안 보였음, 사용자 지적), 큰 아이콘은 26px 까지.
    # 아이콘 안쪽 왼쪽 아래에 그림 — 칸 왼쪽 끝 밖으로 나가 잘리지 않게
    d = max(11, min(26, int(min(r.width(), r.height()) * 0.42)))
    x = max(r.left(), cell.left() + 1)
    y = min(r.bottom() - d + 2, cell.bottom() - d)
    badge = QtCore.QRectF(x, y, d, d)
    col, ch = CheckDelegate.SVN_BADGE[st]
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1))
    p.setBrush(QtGui.QColor(col))
    p.drawEllipse(badge)
    # 기호는 글자 대신 선으로 그림 — 작은 크기에서도 모양이 또렷하게
    pen = QtGui.QPen(QtGui.QColor("#ffffff"), max(1.6, d * 0.16), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    cx, cy, k = badge.center().x(), badge.center().y(), d * 0.26
    L = QtCore.QLineF
    if ch == "✓":
        p.drawPolyline([QtCore.QPointF(cx - k, cy), QtCore.QPointF(cx - k * 0.25, cy + k * 0.8), QtCore.QPointF(cx + k, cy - k * 0.8)])
    elif ch == "+":
        p.drawLine(L(cx - k, cy, cx + k, cy))
        p.drawLine(L(cx, cy - k, cx, cy + k))
    elif ch == "×":
        p.drawLine(L(cx - k * 0.8, cy - k * 0.8, cx + k * 0.8, cy + k * 0.8))
        p.drawLine(L(cx - k * 0.8, cy + k * 0.8, cx + k * 0.8, cy - k * 0.8))
    elif ch == "!":
        p.drawLine(L(cx, cy - k * 1.05, cx, cy + k * 0.2))
        p.drawPoint(QtCore.QPointF(cx, cy + k * 0.95))
    else:   # ?
        f = p.font()
        f.setBold(True)
        f.setPixelSize(max(8, int(d * 0.85)))
        p.setFont(f)
        p.drawText(badge, Qt.AlignCenter, ch)
    p.restore()


class CheckDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, sel, parent=None):
        super().__init__(parent)
        self.sel = sel

    def sizeHint(self, opt, idx):
        # 줄 높이를 탐색기와 같게 = 글자 높이 + 5 (100% 배율에서 21px — 10/6 탐색기 캡처 실측, 예전 4Dir 20px)
        sz = super().sizeHint(opt, idx)
        if isinstance(opt.widget, QtWidgets.QTreeView):
            sz.setHeight(max(sz.height(), opt.fontMetrics.height() + 5))
        return sz

    def initStyleOption(self, opt, idx):
        super().initStyleOption(opt, idx)
        if OPTS["checkboxes"] and idx.column() == 0:
            opt.features |= QtWidgets.QStyleOptionViewItem.HasCheckIndicator
            opt.checkState = Qt.Checked if self.sel.isSelected(idx) else Qt.Unchecked

    def createEditor(self, parent, opt, idx):
        ed = super().createEditor(parent, opt, idx)
        if isinstance(ed, QtWidgets.QLineEdit) and idx.column() == 0:
            # 탐색기처럼 파일 이름에 못 쓰는 글자는 입력이 안 되고 풍선 안내
            ed.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression('[^\\\\/:*?"<>|]*'), ed))
            ed.inputRejected.connect(lambda ed=ed: QtWidgets.QToolTip.showText(
                ed.mapToGlobal(QtCore.QPoint(0, ed.height())),
                T("파일 이름에는 다음 문자를 사용할 수 없습니다:") + '\n\\ / : * ? " < > |', ed))
            ed.installEventFilter(_SEL_ARROWS)
        return ed

    def setEditorData(self, ed, idx):
        """이름 바꾸기(F2): 윈도우 탐색기처럼 파일은 확장자 앞까지만 선택 (폴더·확장자 없는 이름은 전체)"""
        super().setEditorData(ed, idx)
        if not isinstance(ed, QtWidgets.QLineEdit) or idx.column() != 0:
            return
        rows = getattr(idx.model(), "rows", None)
        isdir = rows[idx.row()][1] if rows and idx.row() < len(rows) else True
        stem = os.path.splitext(ed.text())[0]
        if not isdir and 0 < len(stem) < len(ed.text()):
            def sel():   # 보기가 편집칸을 띄운 뒤 '전체 선택'을 하므로 그 다음에 다시 고름
                try:
                    ed.setSelection(0, len(stem))
                except RuntimeError:
                    pass
            QtCore.QTimer.singleShot(0, sel)

    # SVN 상태 배지 (TortoiseSVN 과 비슷한 색): 정상 초록✓ · 수정 빨강! · 추가 파랑+ · 충돌 주황! · 삭제 빨강× · 밖 회색?
    # 폴더: 안쪽 어딘가 변경 = 빨강!, 없음 = 초록✓ (작업 폴더 전체 감시 svnstat.WcWatch, 처음 훑는 동안은 배지 없음)
    SVN_BADGE = {"normal": ("#2e9d4b", "✓"), "modified": ("#d93025", "!"), "added": ("#1a73e8", "+"),
                 "conflict": ("#f29900", "!"), "deleted": ("#d93025", "×"), "unversioned": ("#8a939c", "?")}

    def paint(self, p, opt, idx):
        super().paint(p, opt, idx)
        if idx.column() != 0 or not OPTS["svn_status"]:
            return
        m = idx.model()
        st = m.svn_status(idx.row()) if hasattr(m, "svn_status") else None
        if not st or st not in self.SVN_BADGE:
            return
        o = QtWidgets.QStyleOptionViewItem(opt)
        self.initStyleOption(o, idx)
        w = opt.widget
        r = (w.style() if w else QtWidgets.QApplication.style()).subElementRect(
            QtWidgets.QStyle.SE_ItemViewItemDecoration, o, w)
        if r.width() <= 0:
            return
        paint_svn_badge(p, r, opt.rect, st)

    def editorEvent(self, ev, model, opt, idx):
        if OPTS["checkboxes"] and idx.column() == 0 and ev.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick):
            o = QtWidgets.QStyleOptionViewItem(opt)
            self.initStyleOption(o, idx)
            w = opt.widget
            r = (w.style() if w else QtWidgets.QApplication.style()).subElementRect(
                QtWidgets.QStyle.SE_ItemViewItemCheckIndicator, o, w)
            if r.contains(ev.position().toPoint()):
                self.sel.select(idx, QtCore.QItemSelectionModel.Toggle | QtCore.QItemSelectionModel.Rows)
                return True
        return super().editorEvent(ev, model, opt, idx)


# ================================================================ 보기(자세히/아이콘) — 이벤트는 Page 가 처리
DROP_HINT = None   # 끌고 있을 때 커서 옆 '→ 폴더(으)로 이동' 안내 (프로그램에 하나)


def drop_hint(text=None, gpos=None):
    """text 가 None 이면 숨김"""
    global DROP_HINT
    if text is None:
        if DROP_HINT is not None:
            DROP_HINT.hide()
        return
    if DROP_HINT is None:
        DROP_HINT = QtWidgets.QLabel(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowTransparentForInput)
        DROP_HINT.setAttribute(Qt.WA_ShowWithoutActivating)
        DROP_HINT.setObjectName("dropHint")
    t = SETTINGS[SETTINGS.theme_key()]
    dark = SETTINGS["dark"]
    DROP_HINT.setStyleSheet("QLabel#dropHint{background:%s; color:%s; border:1px solid %s; padding:2px 6px;}"
                            % ("#2b2b2b" if dark else "#ffffff", "#e8e8e8" if dark else "#1f1f1f",
                               ui_parts.qcolor(t.get("sel_border", "#3f94dcff")).name()))
    DROP_HINT.setText(text)
    DROP_HINT.adjustSize()
    DROP_HINT.move(gpos + QtCore.QPoint(16, 6))
    DROP_HINT.show()
    DROP_HINT.raise_()


def drag_pixmap(icon, n, dpr, thumb=False):
    """윈도우 탐색기 같은 끌기 그림: 반투명 상자 + 큰 아이콘 + (여러 개면) 파란 개수 표시. 커서는 상자 아래.
    thumb=True 면 그림 미리보기라 상자를 거의 꽉 채움 (v0.9.67)"""
    W, H, B = 96, 96, 14     # 상자 크기, 상자 아래 여백(커서 자리)
    pm = QtGui.QPixmap(int(W * dpr), int((H + B) * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 70), 1))
    p.setBrush(QtGui.QColor(255, 255, 255, 190))
    p.drawRoundedRect(QtCore.QRectF(0.5, 0.5, W - 1, H - 1), 4, 4)
    if icon is not None and not icon.isNull():
        s_ = 84 if thumb else 56
        icon.paint(p, QtCore.QRect((W - s_) // 2, (H - s_) // 2, s_, s_))
    if n > 1:
        f = p.font()
        f.setBold(True)
        f.setPixelSize(13)
        p.setFont(f)
        txt = str(n)
        bw = max(20, QtGui.QFontMetrics(f).horizontalAdvance(txt) + 10)
        r = QtCore.QRect((W - bw) // 2, (H - 20) // 2, bw, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#0067c0"))
        p.drawRect(r)
        p.setPen(QtGui.QColor("#ffffff"))
        p.drawText(r, Qt.AlignCenter, txt)
    p.end()
    return pm, QtCore.QPoint(W // 2, H + B - 2)


class DragScrollMixin:
    """끄는 중 위/아래 자동 스크롤 (파일 목록·왼쪽 탐색 창 공용). 스크롤 뒤 _drag_retarget() 으로 커서 밑 대상 갱신"""
    _as_timer = None  # 끄는 중 위/아래 자동 스크롤 (탐색기처럼: 넓은 구역 + 가장자리일수록 빠르게 + 열 제목 위 = 위로)
    _as_dir = 0
    AS_ZONE = 48      # 위·아래 가장자리에서 이 안쪽이면 스크롤 (Qt 기본 16 은 너무 좁아 '뜨문뜨문' — 10/5 사용자 보고)

    def _autoscroll(self, y):
        """끄는 중 커서 y(목록 안 좌표, 열 제목 위면 음수) → 스크롤 방향·속도"""
        h = self.viewport().height()
        zone = min(self.AS_ZONE, max(16, h // 4))
        if y < zone:
            d, dist = -1, max(0, y)
        elif y > h - zone:
            d, dist = 1, max(0, h - y)
        else:
            self._stop_autoscroll()
            return
        sb = self.verticalScrollBar()
        if (d < 0 and sb.value() <= sb.minimum()) or (d > 0 and sb.value() >= sb.maximum()):
            self._stop_autoscroll()
            return
        frac = 1.0 - min(dist, zone) / zone          # 0(구역 끝) ~ 1(가장자리·열 제목)
        if self._as_timer is None:
            self._as_timer = QtCore.QTimer(self)
            self._as_timer.timeout.connect(self._autoscroll_tick)
        self._as_dir = d
        self._as_timer.setInterval(int(170 - 140 * frac))   # 170ms → 30ms
        if not self._as_timer.isActive():
            self._as_timer.start()

    def _autoscroll_tick(self):
        sb = self.verticalScrollBar()
        step = 1 if self.verticalScrollMode() == QtWidgets.QAbstractItemView.ScrollPerItem else max(8, sb.singleStep())
        old = sb.value()
        sb.setValue(old + self._as_dir * step)
        if sb.value() == old:
            self._stop_autoscroll()
            return
        # 목록이 움직였으니 커서 밑 대상을 다시 진하게 (커서는 그대로)
        pos = getattr(self, "_as_pos", None)
        if pos is not None and pos.y() >= 0:
            self._drag_retarget(pos)

    def _drag_retarget(self, pos):
        pass

    def _stop_autoscroll(self):
        if self._as_timer is not None and self._as_timer.isActive():
            self._as_timer.stop()
        self._as_dir = 0



class ViewMixin(DragScrollMixin):
    page = None
    _drop_row = -1   # 끌어서 놓을 폴더 줄 (진하게 표시)

    def _drag_retarget(self, pos):
        idx = self.indexAt(pos)
        rows = self.model().rows
        self._set_drop_row(idx.row() if idx.isValid() and idx.row() < len(rows) and rows[idx.row()][1] else -1)

    def eventFilter(self, obj, ev):
        """열 제목(헤더) 위로 끌고 올라가도 계속 위로 스크롤 (탐색기와 같게). 놓는 건 무시"""
        t = ev.type()
        if t in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove) and ev.mimeData().hasUrls():
            ev.setDropAction(Qt.IgnoreAction)
            ev.accept()
            self._as_pos = QtCore.QPoint(10, 0)   # 맨 위 줄 기준
            self._autoscroll(-1)
            return True
        if t in (QtCore.QEvent.DragLeave, QtCore.QEvent.Drop):
            self._stop_autoscroll()
            if t == QtCore.QEvent.Drop:
                ev.ignore()
                return True
        return False

    def startDrag(self, actions):
        """Qt 기본은 고른 줄 전체를 그림으로 끌어 폴더를 가림 → 작은 상자 그림(탐색기와 같게)"""
        idxs = [i for i in self.selectionModel().selectedIndexes() if i.column() == 0]
        self._drag_started = True
        log.info("끌기 시작 %s %d개", type(self).__name__, len(idxs))   # 10/24 '하나 끌었는데 여러 개 선택됨' 진단
        if not idxs:
            return
        md = self.model().mimeData(idxs)
        if md is None:
            return
        cur = self.currentIndex()
        base = cur.row() if cur.isValid() and any(i.row() == cur.row() for i in idxs) else idxs[0].row()
        e = self.model().rows[base]
        # v0.9.67: 그림 파일은 이미 만들어 둔 미리보기를 끌기 그림으로 (사용자 요청: 빈 jpg 아이콘 대신 원래 그림).
        # 새로 읽지 않음(큰 PSD·max 는 멈칫함) — 없으면 예전처럼 종류 아이콘
        tpm = thumbs_service().peek(self.model().full(e), e[3]) if not e[1] and thumbs.is_image(e[0]) and OPTS["thumbnails"] else None
        if tpm is not None and not tpm.isNull():
            icon = QtGui.QIcon(tpm)
        else:
            icon = shellops.icon_for(e[0], e[1], 48, e[6])
            icon = icon if isinstance(icon, QtGui.QIcon) else QtGui.QIcon(icon)
        pm, hot = drag_pixmap(icon, len(idxs), self.devicePixelRatioF(), thumb=tpm is not None)
        log.info("끌기 그림 %s", "미리보기" if tpm is not None else "종류 아이콘")
        hot = self._grab_hotspot(base, hot)
        drag = QtGui.QDrag(self)
        drag.setMimeData(md)
        drag.setPixmap(pm)
        drag.setHotSpot(hot)
        log.info("끌기 시작 %d개 (%s)", len(idxs), e[0])
        # 바깥 프로그램에 놓으면 그 프로그램이 처리를 끝낼 때까지 윈도우가 4Dir 를 붙잡음(맥스가 .max 여는 동안 등).
        # → 끌기 중엔 멈춤 기록·알림을 끄고, 끝나면 '받는 프로그램 대기 시간'을 로그에만 남김 (10/7 사용자 승인)
        _hang_pause(True)
        t0 = _awake_now()
        last = [t0]
        tick = QtCore.QTimer()
        tick.setInterval(200)   # 끌고 있는 동안만 (윈도우 끌기 루프 안에서도 돎). 받는 쪽 처리 중엔 안 돎
        tick.timeout.connect(lambda: last.__setitem__(0, _awake_now()))
        tick.start()
        res = None
        try:
            res = drag.exec(actions, Qt.CopyAction)
        finally:
            tick.stop()
            end = _awake_now()
            _hang_pause(False)
            drop_hint(None)
            self._set_drop_row(-1)
            self._stop_autoscroll()
        wait = end - last[0]
        if drag.target() is None:   # 4Dir 밖에 놓음 (4Dir 칸에 놓은 건 '드롭 …' 로그가 따로 남음)
            prog = window_program_at_cursor()
            log.info("끌기 끝 → 바깥 프로그램 %s, 결과=%s, 받는 쪽 처리 대기 %.1f초 (끌기 전체 %.1f초)",
                     prog, getattr(res, "name", res), wait, end - t0)
            if wait > HANG_SEC:
                log.warning("바깥 프로그램 %s 가 놓은 파일을 처리하는 동안 %.1f초 기다림 — 4Dir 멈춤 아님, 알림 안 띄움", prog, wait)

    def _set_drop_row(self, r):
        if r != self._drop_row:
            self._drop_row = r
            self.viewport().update()

    def keyPressEvent(self, ev):
        if not self.page.handle_key(self, ev):
            super().keyPressEvent(ev)

    def _grab_hotspot(self, row, default):
        """끌기 그림의 커서 자리 = 처음 누른 곳이 항목 안에서 있던 자리 (v0.9.67, 10/24 사용자: 탐색기는 잡은 아이콘 자리에서
        따라오는데 4Dir 는 그림이 마우스 위로 올라감). 그림 상자 96x96 안으로 비율을 옮김. 누른 곳을 모르면 예전 자리"""
        pos = getattr(self, "_press_pos", None)
        if pos is None:
            return default
        r = self.visualRect(self.model().index(row, 0))
        if not r.isValid() or r.width() <= 0 or r.height() <= 0:
            return default
        W, H = 96, 96
        dx, dy = pos.x() - r.left(), pos.y() - r.top()
        if isinstance(self, QtWidgets.QTreeView):   # 자세히: 줄은 낮고 넓음 → 가로는 왼쪽(아이콘 쪽)부터 그대로, 세로는 가운데 기준
            hx = max(4, min(W - 4, dx))
            hy = max(4, min(H - 4, H // 2 + dy - r.height() // 2))
        else:   # 아이콘·목록: 항목 칸 안의 비율 그대로
            hx = max(4, min(W - 4, int(dx * W / r.width())))
            hy = max(4, min(H - 4, int(dy * H / r.height())))
        return QtCore.QPoint(hx, hy)

    def mousePressEvent(self, ev):
        # 진단 기록 (10/24 사용자: 파일 하나를 끌었는데 여러 개가 선택됨) — 누른 곳이 항목인지, 이미 골라져 있었는지
        if ev.button() == Qt.LeftButton:
            pos = ev.position().toPoint()
            idx = self.indexAt(pos)
            sm = self.selectionModel()
            self._drag_started = False
            self._press_pos = pos   # 끌기 그림을 잡은 자리 기준으로 (v0.9.67, 탐색기와 같게)
            self._press_sel = len(sm.selectedRows()) if sm else 0
            log.info("마우스 누름 %s 위치=%d,%d 항목=%s 이미골라짐=%s 고른수=%d", type(self).__name__, pos.x(), pos.y(),
                     self.model().rows[idx.row()][0] if idx.isValid() and idx.row() < len(self.model().rows) else "(빈 곳)",
                     bool(idx.isValid() and sm and sm.isSelected(self.model().index(idx.row(), 0))), self._press_sel)
        if not self.page.handle_mouse(self, ev):
            super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        if ev.button() == Qt.LeftButton and hasattr(self, "_press_sel"):
            sm = self.selectionModel()
            n = len(sm.selectedRows()) if sm else 0
            if n != self._press_sel or getattr(self, "_drag_started", False):
                log.info("마우스 뗌 %s 고른수 %d (누를 때 %d) 끌기=%s", type(self).__name__, n, self._press_sel, getattr(self, "_drag_started", False))

    def contextMenuEvent(self, ev):
        if ev.reason() == QtGui.QContextMenuEvent.Keyboard:
            cur = self.currentIndex()
            if cur.isValid() and self.selectionModel().isSelected(cur):
                r = self.visualRect(cur)
                pos = QtCore.QPoint(r.left() + min(40, r.width() // 2), r.center().y())
            else:
                pos = QtCore.QPoint(10, 10)   # 고른 것 없음 → 빈 곳 메뉴
            ev = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Keyboard, pos, self.viewport().mapToGlobal(pos))
        self.page.context_menu(self, ev)

    def wheelEvent(self, ev):
        """Ctrl+휠 = 보기 크기 바꾸기 (탐색기와 같게: 위로 = 크게)"""
        if ev.modifiers() & Qt.ControlModifier:
            pane = self.page.pane()
            order = [k for k, _, _ in VIEW_MODES]
            if pane is not None and ev.angleDelta().y():
                i = order.index(pane.mode) if pane.mode in order else 0
                i = max(0, min(len(order) - 1, i + (1 if ev.angleDelta().y() > 0 else -1)))
                if order[i] != pane.mode:
                    pane.set_mode(order[i])
                    log.info("Ctrl+휠 보기 → %s", order[i])
            ev.accept()
            return
        super().wheelEvent(ev)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() and self.page.path != THIS_PC and not is_search(self.page.path):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        if not ev.mimeData().hasUrls() or self.page.path == THIS_PC or is_search(self.page.path):
            ev.ignore()
            drop_hint(None)
            self._set_drop_row(-1)
            return
        super().dragMoveEvent(ev)  # Qt 기본 (가장자리 16px)
        self._as_pos = ev.position().toPoint()
        self._autoscroll(self._as_pos.y())   # 넓은 구역 + 가장자리일수록 빠르게
        act = self.page.drop_action(self, ev)
        ev.setDropAction(act)
        ev.accept()
        # 놓을 곳: 폴더 줄 위면 그 폴더(진하게), 아니면 지금 폴더
        pos = ev.position().toPoint()
        idx = self.indexAt(pos)
        row = idx.row() if idx.isValid() and self.model().rows[idx.row()][1] else -1
        srcs = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if row >= 0 and any(os.path.normcase(s) == os.path.normcase(self.model().full(self.model().rows[row])) for s in srcs):
            row = -1   # 끌고 있는 폴더 자기 자신 위
        self._set_drop_row(row)
        tgt = self.page._drop_target(self, ev) if row >= 0 else self.page.path
        same = srcs and all(os.path.normcase(os.path.dirname(s)) == os.path.normcase(tgt) for s in srcs)
        if same:   # 원래 있던 폴더 → 안내 없음 (탐색기와 같게)
            drop_hint(None)
        else:
            name = os.path.basename(tgt.rstrip("\\")) or tgt
            fmt = T("→ {0}(으)로 이동") if act == Qt.MoveAction else T("→ {0}(으)로 복사")
            drop_hint(fmt.format(name), self.viewport().mapToGlobal(pos))

    def dragLeaveEvent(self, ev):
        drop_hint(None)
        self._set_drop_row(-1)
        # 열 제목으로 나간 거면(위로 스크롤 계속) 멈추지 않음 — 헤더가 이어받음
        hdr = self.header() if hasattr(self, "header") else None
        if hdr is None or not hdr.rect().contains(hdr.mapFromGlobal(QtGui.QCursor.pos())):
            self._stop_autoscroll()
        super().dragLeaveEvent(ev)

    def dropEvent(self, ev):
        drop_hint(None)
        self._set_drop_row(-1)
        self._stop_autoscroll()
        self.page.drop(self, ev)

    def closeEditor(self, editor, hint):
        super().closeEditor(editor, hint)
        self.page.editor_closed()


def _in_active_pane(w):
    while w is not None and not isinstance(w, Pane):
        w = w.parentWidget()
    return bool(w is not None and w.property("active"))


def _drop_paint(view, painter, r):
    """끌어서 놓을 폴더 표시: 선택 색을 섞어 칠하고(글자는 그대로 진하게 — 밝게=곱하기, 어둡게=스크린) 진한 테두리"""
    t = SETTINGS[SETTINGS.theme_key()]
    painter.save()
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_Screen if SETTINGS["dark"]
                               else QtGui.QPainter.CompositionMode_Multiply)
    painter.fillRect(r, ui_parts.qcolor(t.get("sel", "#cce8ffff")))
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
    painter.setPen(QtGui.QPen(ui_parts.qcolor(t.get("sel_border", "#3f94dcff")), 2))
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(r.adjusted(1, 1, -1, -1))
    painter.restore()


class HoverHeader(QtWidgets.QHeaderView):
    """목록 머리줄: 마우스 올린 열 칸 바탕색 (탐색기와 같게, 10/8 사용자 요청 — 탐색기 캡처 실측 #d9ebf9).
    윈도우11 스타일은 머리줄 마우스 올림을 안 그려서 직접 칠함. 밝게 = '어둡게 섞기'(min)로 칠해 글자·정렬 표시는 그대로"""
    HOVER_LIGHT = QtGui.QColor("#d9ebf9")

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._hover = -1
        self.setMouseTracking(True)
        # QTreeView 가 기본 머리줄에 해 주던 설정 그대로 (setHeader 로 바꾸면 안 해 줌)
        self.setSectionsMovable(True)
        self.setStretchLastSection(True)
        self.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def _set_hover(self, i):
        if i != self._hover:
            self._hover = i
            self.viewport().update()

    def mouseMoveEvent(self, ev):
        self._set_hover(self.logicalIndexAt(ev.position().toPoint()) if not ev.buttons() else -1)
        super().mouseMoveEvent(ev)

    def viewportEvent(self, ev):
        if ev.type() in (QtCore.QEvent.Leave, QtCore.QEvent.HoverLeave):   # 마우스 이벤트는 머리줄 viewport 로 옴
            self._set_hover(-1)
        return super().viewportEvent(ev)

    def paintSection(self, painter, rect, logical):
        super().paintSection(painter, rect, logical)
        if logical != self._hover:
            return
        painter.save()
        if SETTINGS["dark"]:   # 어둡게: 바탕보다 조금 밝게, 밝게 섞기(max) — 어둡게 탐색기는 아직 실측 전
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_Lighten)
            col = self.palette().button().color().lighter(135)
        else:
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_Darken)
            col = self.HOVER_LIGHT
        painter.fillRect(rect, col)
        painter.restore()


class DetailView(ViewMixin, QtWidgets.QTreeView):
    # 탐색기처럼 목록 왼쪽·머리줄 아래에 빈 띠 → 파일이 꽉 차도 빈 곳을 눌러 폴더 메뉴(커밋 등)·선택 해제 가능 (10/6 사용자 요청)
    GUTTER_L, GUTTER_T = 14, 6

    def updateGeometries(self):
        super().updateGeometries()
        if getattr(self, "_gutter_busy", False):
            return
        self._gutter_busy = True
        try:
            if not self.autoFillBackground():   # 빈 띠도 목록 바탕색(Base)으로 — 안 하면 어둡게 테마에서 띠만 밝게 보임(실측 #26292e vs #1e1f22)
                self.setBackgroundRole(QtGui.QPalette.Base)
                self.setAutoFillBackground(True)
            h = self.header()
            hh = h.height() if not h.isHidden() else 0
            m = self.viewportMargins()
            want = (self.GUTTER_L, hh + self.GUTTER_T, 0, 0)
            if (m.left(), m.top(), m.right(), m.bottom()) != want:
                self.setViewportMargins(*want)
            vg = self.viewport().geometry()
            if not h.isHidden():
                h.setGeometry(vg.left(), vg.top() - self.GUTTER_T - hh, vg.width(), hh)
        finally:
            self._gutter_busy = False

    def _in_gutter(self, pos):
        """pos(이 위젯 좌표)가 목록 바깥 빈 띠인지 (머리줄·스크롤바 제외)"""
        if self.viewport().geometry().contains(pos) or self.header().geometry().contains(pos):
            return False
        for sb in (self.verticalScrollBar(), self.horizontalScrollBar()):
            if sb.isVisible() and sb.geometry().contains(sb.parentWidget().mapFrom(self, pos)):
                return False
        return self.rect().contains(pos)

    def event(self, ev):
        t = ev.type()
        if t == QtCore.QEvent.ContextMenu and ev.reason() != QtGui.QContextMenuEvent.Keyboard and self._in_gutter(ev.pos()):
            log.debug("목록 빈 띠 우클릭 → 폴더 메뉴")
            self.page.context_menu(self, ev)   # 빈 곳 = 폴더 메뉴
            return True
        if t == QtCore.QEvent.MouseButtonPress and self._in_gutter(ev.position().toPoint()):
            if ev.button() == Qt.LeftButton and not (ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                self.selectionModel().clearSelection()   # 탐색기: 빈 곳 클릭 = 선택 해제
            self.setFocus()
            return True
        return super().event(ev)

    def drawRow(self, painter, option, index):
        if index.row() == self._drop_row:
            r = QtCore.QRect(option.rect)
            r.setLeft(0)
            r.setRight(self.header().length() - self.header().offset() - 1)   # 탐색기처럼 마지막 열 끝까지 (창 끝까지 아님)
            super().drawRow(painter, option, index)
            _drop_paint(self, painter, r)
            return
        super().drawRow(painter, option, index)
        # 윈도우 탐색기처럼 선택한 줄 전체에 테두리 (칸마다 아니라 줄 하나로) — 10/2 사용자 요청
        if self.selectionModel() is not None and self.selectionModel().isSelected(index):
            t = SETTINGS[SETTINGS.theme_key()]
            col = ui_parts.qcolor(t.get("sel_border" if _in_active_pane(self) else "sel_border_off", "#66b2eaff"))
            painter.save()
            painter.setPen(QtGui.QPen(col, 1))
            painter.setBrush(Qt.NoBrush)
            r = QtCore.QRect(option.rect)
            r.setLeft(0)
            r.setRight(self.header().length() - self.header().offset() - 1)   # 탐색기처럼 마지막 열 끝까지 (창 끝까지 아님)
            painter.drawRect(r.adjusted(0, 0, -1, -1))
            painter.restore()


class IconView(ViewMixin, QtWidgets.QListView):
    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self._drop_row >= 0:
            p = QtGui.QPainter(self.viewport())
            _drop_paint(self, p, self.visualRect(self.model().index(self._drop_row, 0)))
            p.end()


def _setup_view(v, page):
    v.page = page
    v.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
    # F2(키표) + 선택된 항목을 천천히 한 번 더 클릭 → 이름 바꾸기 (탐색기와 같게)
    v.setEditTriggers(QtWidgets.QAbstractItemView.EditKeyPressed | QtWidgets.QAbstractItemView.SelectedClicked)
    v.setDragEnabled(True)
    v.setAcceptDrops(True)
    v.setDropIndicatorShown(False)
    if isinstance(v, QtWidgets.QTreeView):   # 열 제목 위로 끌어도 위로 스크롤
        for hw in (v.header(), v.header().viewport()):   # 끌기 이벤트는 헤더의 viewport 로 옴
            hw.setAcceptDrops(True)
            hw.installEventFilter(v)   # Qt 기본 얇은 상자 대신 _drop_paint 로 줄 전체 진하게
    v.setDragDropMode(QtWidgets.QAbstractItemView.DragDrop)
    v.setDefaultDropAction(Qt.CopyAction)
    v.setFrameShape(QtWidgets.QFrame.NoFrame)


# ================================================================ 탭 하나 = 폴더 보기
class Page(QtWidgets.QWidget):
    pathChanged = QtCore.Signal(str)
    status = QtCore.Signal(str)
    openInNewTab = QtCore.Signal(str)

    def __init__(self, path, mode="details", parent=None):
        super().__init__(parent)
        self.model_ = DirModel(self)
        self.sel = QtCore.QItemSelectionModel(self.model_)
        self.delegate = CheckDelegate(self.sel, self)
        self.path = ""
        self.mode = "details"
        self.back, self.fwd = [], []
        self.gen = 0
        self.active = False           # 화면에 보이는 탭인가 (감시 대상)
        self.pending_select = None    # 다음 읽기 후 선택할 이름
        self.new_from = None          # (그때 있던 이름들, 시각, 방식, 폴더) — 붙여넣기 등으로 새로 생긴 것 선택
        self.pending_edit = None      # 다음 읽기 후 이름편집 시작할 이름
        self.keep_sel = None
        self.reload_after_edit = False
        self.last_ms = 0.0
        self.scan_count = 0
        self.sig = ScanSignals()
        self.sig.done.connect(self._on_scanned)
        self.sig.partial.connect(self._on_partial)
        self.sig.info.connect(self._on_info)
        self.sig.svn.connect(self._on_svn)
        self.search_info = ""
        self._token = [False]   # 진행 중인 읽기/찾기 취소용
        self.watcher = None
        self.watch_timer = QtCore.QTimer(self)
        self.watch_timer.setSingleShot(True)
        self.watch_timer.setInterval(WATCH_DELAY_MS)
        self.watch_timer.timeout.connect(lambda: self.reload(reason="watch"))

        self.tree = DetailView()
        self.tree.setHeader(HoverHeader(self.tree))
        self.tree.setModel(self.model_)
        self.tree.setSelectionModel(self.sel)
        _setup_view(self.tree, self)
        self.tree.setItemDelegate(self.delegate)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        h = self.tree.header()
        h.setStretchLastSection(False)
        for c, w in enumerate((322, 145, 120, 80, 320)):   # 탐색기 기본 폭과 같게 (10/6 캡처 실측: 이름 322·날짜 145·유형 120·크기 80)
            h.resizeSection(c, w)
        if not SETTINGS["dark"]:   # 머리줄 글자 = 탐색기와 같은 파란 회색 (실측 #4c607a)
            pal = h.palette()
            for role in (QtGui.QPalette.ButtonText, QtGui.QPalette.WindowText, QtGui.QPalette.Text):
                pal.setColor(role, QtGui.QColor("#4c607a"))
            h.setPalette(pal)
        self.tree.setColumnHidden(4, True)   # '위치' 열 = 검색 결과에서만
        self.tree.doubleClicked.connect(self._activate)

        self.icons = IconView()
        self.icons.setModel(self.model_)
        self.icons.setSelectionModel(self.sel)
        _setup_view(self.icons, self)
        self.icons.setItemDelegate(self.delegate)
        self.icons.setMovement(QtWidgets.QListView.Static)
        self.icons.setResizeMode(QtWidgets.QListView.Adjust)
        self.icons.setUniformItemSizes(True)
        self.icons.doubleClicked.connect(self._activate)

        self.stack = QtWidgets.QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.tree)
        self.stack.addWidget(self.icons)

        self.model_.renamed.connect(lambda a, b: self.reload(reason="rename"))
        self.sel.selectionChanged.connect(lambda *_: self._emit_status())
        self.set_mode(mode)
        self.navigate(path, record=False)

    def view(self):
        return self.stack.currentWidget()

    # ---------------------------------------------------------- 보기 방식
    def set_mode(self, mode):
        if mode not in MODE_PX:
            mode = "details"
        self.mode = mode
        px = MODE_PX[mode]
        self.model_.icon_px = px
        self.model_.thumbs_on = mode in THUMB_MODES and OPTS["thumbnails"]
        self.model_.thumb_px = int(round(px * (self.devicePixelRatioF() or 1.0)))
        if mode == "details":
            self.stack.setCurrentWidget(self.tree)
        else:
            v = self.icons
            if mode == "list":
                v.setViewMode(QtWidgets.QListView.ListMode)
                v.setFlow(QtWidgets.QListView.TopToBottom)
                v.setWrapping(True)
                v.setGridSize(QtCore.QSize())
                v.setSpacing(1)
            elif mode == "small":
                v.setViewMode(QtWidgets.QListView.ListMode)
                v.setFlow(QtWidgets.QListView.LeftToRight)
                v.setWrapping(True)
                v.setGridSize(QtCore.QSize(200, 22))
                v.setSpacing(0)
            else:
                v.setViewMode(QtWidgets.QListView.IconMode)
                v.setFlow(QtWidgets.QListView.LeftToRight)
                v.setWrapping(True)
                v.setWordWrap(True)
                v.setSpacing(4)
                v.setGridSize(QtCore.QSize(max(px + 40, 90), px + 44))
            v.setIconSize(QtCore.QSize(px, px))
            # v0.9.67: setMovement(Static)·setViewMode 가 Qt 안에서 '끌기'를 꺼 버림 → 아이콘·목록 보기에서 파일을 끌면
            # 끌기 대신 사각형 선택이 됨(10/24 사용자 제보 '하나 끌었는데 여러 개 선택', 재현: dragEnabled=False 실측). 다시 켬
            v.setMovement(QtWidgets.QListView.Static)   # 아이콘 자리 옮기기는 계속 막음
            v.setDragEnabled(True)
            v.setDragDropMode(QtWidgets.QAbstractItemView.DragDrop)
            v.setDefaultDropAction(Qt.CopyAction)
            self.stack.setCurrentWidget(v)
        self.model_.layoutChanged.emit()
        log.debug("보기 방식 %s path=%s", mode, self.path)

    def set_sort(self, col, order):
        self.tree.sortByColumn(col, order)  # 모델 정렬 + 머리글 표시

    # ---------------------------------------------------------- 탭별 정렬·열 너비 (다시 켜도·자동 기록에서도 그대로)
    def view_state(self):
        h = self.tree.header()
        return {"sort": [self.model_.sort_col, int(self.model_.sort_order.value)],
                "cols": [h.sectionSize(c) for c in range(h.count())]}

    def apply_view_state(self, vs):
        if not vs:
            return
        try:
            h = self.tree.header()
            old_default = {0: 280, 1: 125, 3: 85}    # v0.9.30 까지 기본 폭 → 손대지 않은 열이면 탐색기 기본 폭으로 (날짜가 길어져 잘리지 않게)
            new_default = {0: 322, 1: 145, 3: 80}
            for c, w in enumerate(vs.get("cols") or []):
                if c < h.count() and w > 10:
                    if old_default.get(c) == int(w):
                        w = new_default[c]
                    h.resizeSection(c, int(w))
            col, order = vs.get("sort") or [0, 0]
            if 0 <= int(col) < h.count():
                self.set_sort(int(col), Qt.SortOrder(int(order)))
        except Exception:
            log.exception("탭 정렬·열 너비 복원 실패 %s", vs)

    # ---------------------------------------------------------- 이동
    def navigate(self, path, record=True, select=None):
        path = norm(path) or THIS_PC
        if path != THIS_PC and not is_search(path) and not os.path.isdir(path):
            log.info("이동 실패(폴더 아님) %s", path)
            self.status.emit(T('⚠ 폴더를 찾을 수 없습니다: {0}').format(path))
            return False
        if record and self.path and self.path != path:
            self.back.append(self.path)
            self.fwd.clear()
        old = self.path
        self.path = path
        self.pending_select = select
        if old != path:
            self.model_.filter = ""   # 다른 폴더로 가면 빠른 필터 해제
            if THUMBS is not None and old:
                THUMBS.drop_pending(old)   # 떠난 폴더의 아직 안 만든 미리보기 요청은 버림
        if self.active:
            self._watch(old, path)
        log.info("이동 %s -> %s", old, path)
        self.pathChanged.emit(path)
        self.reload(reason="nav")
        return True

    def go_back(self):
        if self.back:
            cur = self.path
            p = self.back.pop()
            self.fwd.append(cur)
            self.navigate(p, record=False, select=os.path.basename(cur) if os.path.dirname(cur) == p else None)

    def go_fwd(self):
        if self.fwd:
            self.back.append(self.path)
            self.navigate(self.fwd.pop(), record=False)

    def go_up(self):
        if self.path == THIS_PC:
            return
        parent = os.path.dirname(self.path.rstrip("\\"))
        if not parent or parent == self.path or (len(self.path) <= 3 and self.path.endswith(":\\")):
            self.navigate(THIS_PC, select=self.path)
        else:
            self.navigate(parent, select=os.path.basename(self.path.rstrip("\\")))

    # ---------------------------------------------------------- 읽기
    def editing(self):
        return self.view().state() == QtWidgets.QAbstractItemView.EditingState

    def reload(self, reason="manual"):
        # 이름 편집 중에 목록을 새로 읽으면 편집창이 닫힘 → 편집 끝날 때까지 미룸
        if self.editing():
            self.reload_after_edit = True
            log.debug("읽기 보류(이름 편집 중) reason=%s", reason)
            return
        if self.keep_sel is None and self.model_.path == self.path:
            self.keep_sel = self._sel_snapshot()
        self.gen += 1
        self.scan_count += 1
        log.debug("읽기 요청 gen=%d reason=%s path=%s", self.gen, reason, self.path)
        self._token[0] = True               # 이전 찾기 취소
        self._token = tok = [False]
        srch = is_search(self.path)
        self.tree.setColumnHidden(4, not srch)   # '위치' 열은 검색 결과에서만
        if srch:
            self.search_info = T("찾는 중…")
            if parse_search(self.path)[1]:      # 폴더 아래 찾기: 중간 결과를 바로 채우므로 먼저 비움
                self.keep_sel = None
                self.model_.set_entries(self.path, [])
            self._emit_status()
        POOL.start(ScanJob(self.gen, self.path, self.sig, cancel=lambda: tok[0]))

    def _sel_snapshot(self):
        cur = self.view().currentIndex()
        return (self.selected_names(), self.view().verticalScrollBar().value(),
                self.model_.rows[cur.row()][0] if cur.isValid() and cur.row() < len(self.model_.rows) else None,
                cur.row() if cur.isValid() else -1)

    def cancel_jobs(self):
        self._token[0] = True

    def _on_partial(self, gen, rows):
        if gen == self.gen:
            self.model_.append_rows(rows)
            self.search_info = T('찾는 중… {0:,}개').format(len(self.model_.all))
            self._emit_status()

    def _on_info(self, gen, text):
        if gen == self.gen:
            self.search_info = text

    def _on_scanned(self, gen, path, entries, ms, err):
        if gen != self.gen:
            return  # 이미 다른 폴더로 이동함
        self.last_ms = ms
        if err:
            log.warning("읽기 에러 %s : %s", path, err)
            self.status.emit(f"⚠ {err}")
        if not OPTS["show_hidden"]:
            entries = [e for e in entries if not (e[4] & HIDDEN_MASK)]
        log.info("읽기 완료 path=%s n=%d %.1fms", path, len(entries), ms)
        keep = self.keep_sel if self.model_.path == path else None
        if keep is not None and self.model_.rows:
            # 읽는 동안 사용자가 고른 것(예: 이름 바꾸고 바로 다른 파일 클릭)을 살림 — 요청 때가 아니라 지금 선택 기준
            keep = self._sel_snapshot()
        self.keep_sel = None
        if is_search(path) and parse_search(path)[1]:
            self.model_.sort(self.model_.sort_col, self.model_.sort_order)   # 폴더 아래 찾기: 다 모은 뒤 정렬
        else:
            self.model_.set_entries(path, entries)
        names = {e[0]: i for i, e in enumerate(self.model_.rows)}
        v, sm = self.view(), self.sel
        if self.pending_edit and self.pending_edit in names:
            idx = self.model_.index(names[self.pending_edit], 0)
            v.setCurrentIndex(idx)
            v.scrollTo(idx)
            v.edit(idx)
        elif self.pending_select and self.pending_select in names:
            idx = self.model_.index(names[self.pending_select], 0)
            v.setCurrentIndex(idx)
            v.scrollTo(idx, QtWidgets.QAbstractItemView.PositionAtCenter)
        elif self.new_from is not None and time.time() - self.new_from[1] < 30 and \
                os.path.normcase(self.new_from[3]) == os.path.normcase(path) and \
                [n for n in names if n not in self.new_from[0]]:
            # ★붙여넣은 그 폴더에서만 (10/13: 같은 이름 덮어쓰기라 새 것이 없으면 기다림이 남아, 30초 안에 다른 폴더로 들어가면 전부 선택됐음)
            # 붙여넣기·끌어 놓기·다른 칸으로 보내기 → 새로 생긴 것을 선택 (탐색기와 같게)
            new = [n for n in names if n not in self.new_from[0]]
            edit = len(self.new_from) > 2 and self.new_from[2] == "edit" and len(new) == 1
            self.new_from = None
            if edit:   # 새로 만들기로 생긴 것 → 이름 편집
                idx = self.model_.index(names[new[0]], 0)
                v.setCurrentIndex(idx)
                v.scrollTo(idx)
                v.edit(idx)
                log.info("새로 생긴 것 이름 편집 %s", new[0])
                self.pending_edit = self.pending_select = None
                self._emit_status()
                self.refresh_svn(entries)
                return
            sm.clearSelection()
            for n in new:
                sm.select(self.model_.index(names[n], 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
            first = self.model_.index(min(names[n] for n in new), 0)
            sm.setCurrentIndex(first, QtCore.QItemSelectionModel.NoUpdate)
            v.scrollTo(first)
            log.info("새로 생긴 것 선택 %d개 %s", len(new), new[:3])
        elif keep:
            selnames, scroll, cur, cur_row = keep
            hit = 0
            for n in selnames:
                if n in names:
                    hit += 1
                    sm.select(self.model_.index(names[n], 0),
                              QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
            if cur in names:
                sm.setCurrentIndex(self.model_.index(names[cur], 0), QtCore.QItemSelectionModel.NoUpdate)
            elif selnames and not hit and cur_row >= 0 and self.model_.rows:
                # 고른 것이 지워짐 → 그 자리(다음) 항목 선택 (탐색기와 같게)
                i = self.model_.index(min(cur_row, len(self.model_.rows) - 1), 0)
                sm.setCurrentIndex(i, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
            v.verticalScrollBar().setValue(scroll)
        elif self.model_.rows:
            sm.setCurrentIndex(self.model_.index(0, 0), QtCore.QItemSelectionModel.NoUpdate)
        self.pending_edit = self.pending_select = None
        self._emit_status()
        self.refresh_svn(entries)

    # ---------------------------------------------------------- SVN 상태 (TortoiseSVN 겹침 아이콘 대신 장부 직접 읽기)
    def refresh_svn(self, entries=None):
        p = self.path
        if not OPTS["svn_status"] or p == THIS_PC or is_search(p) or not os.path.isdir(p):
            if self.model_.svn:
                self.model_.svn = {}
                self.view().viewport().update()
            return
        names = [(e[0], bool(e[1])) for e in (entries if entries is not None else self.model_.all)]
        self.svn_root = None
        POOL.start(SvnJob(self.gen, p, names, self.sig))

    def _on_svn(self, gen, path, st):
        if gen != self.gen or path != self.path:
            return
        self.svn_pending = bool(st.pop("\0pending", False))
        self.model_.svn = st
        self._emit_status()
        root = svnstat.wc_root(path) if st else None
        self.svn_root, self.svn_mtime = root, (svnstat.wc_db_mtime(root) if root else 0.0)
        self.view().viewport().update()

    def svn_changed(self):
        """커밋·업데이트는 이 폴더 파일이 아니라 장부(wc.db)만 바꿈 → 창이 다시 활성화될 때 장부 시각으로 확인"""
        r = getattr(self, "svn_root", None)
        if r and OPTS["svn_status"] and svnstat.wc_db_mtime(r) != self.svn_mtime:
            log.info("SVN 장부 바뀜 → 상태 다시 읽음 %s", self.path)
            self.refresh_svn()

    def set_filter(self, text):
        self.model_.set_filter(text)
        log.debug("빠른 필터 '%s' → %d/%d", text, len(self.model_.rows), len(self.model_.all))
        if self.model_.rows:
            self.sel.setCurrentIndex(self.model_.index(0, 0), QtCore.QItemSelectionModel.NoUpdate)
        self._emit_status()

    def _emit_status(self):
        n = len(self.model_.rows)
        sr = self.selected_rows()
        s = len(sr)
        txt = T('{0:,}개 항목').format(n)   # 탐색기 상태줄과 같은 말 (읽기 ms 는 상태줄 풍선 도움말로)
        if is_search(self.path):
            q, f = parse_search(self.path)
            txt = f"🔎 '{q}'" + (T(' ({0} 아래)').format(f) if f else T(" (전체)")) + f": {self.search_info}"
        elif self.model_.filter:
            txt = T("필터 '{0}': {1:,} / 전체 {2:,}개").format(self.model_.filter, n, len(self.model_.all))
        if s:
            txt += T('    {0:,}개 항목 선택함').format(s)
            fs = [self.model_.rows[r][2] for r in sr if not self.model_.rows[r][1] and self.model_.rows[r][2] >= 0]
            if fs:   # 탐색기처럼 선택한 파일들 크기 합 (폴더는 빼고)
                txt += "  " + size_short(sum(fs))
        self.status_tip = T('읽기 {0:.0f}ms').format(self.last_ms)
        if getattr(self, "svn_pending", False):
            txt += T("   |   SVN 확인 중…")
        self.status.emit(txt)

    def editor_closed(self):
        if self.reload_after_edit:
            self.reload_after_edit = False
            self.reload(reason="after-edit")

    # ---------------------------------------------------------- 감시 (보이는 탭만)
    def set_active(self, on):
        if on == self.active:
            return
        self.active = on
        if on:
            self._watch(None, self.path)
            self.reload(reason="show")  # 숨어 있던 사이 바뀐 것 반영
        else:
            self._watch(self.path, None)
            self.watch_timer.stop()

    def _watch(self, old, new):
        if self.watcher is None:
            self.watcher = QtCore.QFileSystemWatcher(self)
            self.watcher.directoryChanged.connect(self._on_dir_changed)
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        if new and new != THIS_PC and not is_search(new):
            self.watcher.addPath(new)
        log.debug("감시 %s -> %s", old, new)

    def _on_dir_changed(self, p):
        log.debug("변경감지 %s", p)
        if not self.watch_timer.isActive():
            self.watch_timer.start()

    # ---------------------------------------------------------- 선택
    def selected_rows(self):
        return sorted({i.row() for i in self.sel.selectedIndexes() if i.row() < len(self.model_.rows)})

    def selected_names(self):
        return [self.model_.rows[r][0] for r in self.selected_rows()]

    def selected_paths(self):
        return [self.model_.full(self.model_.rows[r]) for r in self.selected_rows()]

    # ---------------------------------------------------------- 열기
    def _activate(self, idx):
        if not idx.isValid():
            return
        e = self.model_.rows[idx.row()]
        fp = self.model_.full(e)
        if e[1]:
            self.navigate(fp)
            return
        if fp.lower().endswith(".lnk"):   # 폴더 바로 가기 → 탐색기처럼 이 칸에서 그 폴더로 (v0.9.55, 사용자 요청)
            tgt = os.path.expandvars(shellops.link_target(fp))
            if tgt and os.path.isdir(tgt):
                log.info("폴더 바로 가기 %s → %s", fp, tgt)
                self.navigate(tgt)
                return
            log.info("바로 가기 대상이 폴더 아님(%s) → 윈도우로 열기", tgt or "경로 없음")
        log.info("파일 열기 %s", fp)
        try:
            os.startfile(fp)
        except OSError as ex:
            log.warning("열기 실패 %s : %s", fp, ex)
            self.status.emit(f"⚠ {ex}")

    def open_selected(self):
        rows = self.selected_rows()
        cur = self.view().currentIndex()
        if not rows and cur.isValid():
            rows = [cur.row()]
        if len(rows) == 1:
            self._activate(self.model_.index(rows[0], 0))
        else:
            for r in rows:
                if not self.model_.rows[r][1]:
                    self._activate(self.model_.index(r, 0))

    # ---------------------------------------------------------- 파일 작업
    def hwnd(self):
        return int(self.window().winId())

    def do_copy(self, cut=False):
        ps = self.selected_paths()
        if ps and self.path != THIS_PC:
            shellops.set_clipboard(ps, cut)
            self.status.emit(T('{0}개 {1} 됨').format(len(ps), T('잘라내기') if cut else T('복사')))

    def do_paste(self):
        if self.path == THIS_PC or is_search(self.path):
            return
        ps, cut = shellops.get_clipboard()
        if ps:
            log.info("붙여넣기 %d개 → %s", len(ps), self.path)
            self.file_op(ps, self.path, cut, select_in=self)
        else:   # 예전엔 조용히 끝남 → 원인 확정용으로 클립보드 상태 기록 (10/8 '붙여넣기 안 됨' 간헐)
            info = shellops.clipboard_info()
            changed = info["seq"] != shellops._CLIP_SEQ[0]
            log.warning("붙여넣기: 클립보드에 파일 없음 — %s, 마지막 복사 뒤 바뀜=%s (순번 %d → %d)",
                        info, changed, shellops._CLIP_SEQ[0], info["seq"])
            self.status.emit(T("⚠ 클립보드에 파일이 없습니다"))

    def do_compress(self, fmt):
        """선택 항목 압축 (윈도우 내장 tar.exe, 뒤 스레드). 끝나면 알림 — 새 파일은 폴더 감시로 목록에 나타남 (v0.9.54)"""
        folder, names = self.path, self.selected_names()
        if not names or folder == THIS_PC or is_search(folder):
            return
        sg = _undo_signal()   # 화면 스레드에서 만들어 둠 (뒤 스레드는 emit 만)
        self.status.emit(T("압축 중: {0}…").format(names[0] if len(names) == 1 else T("{0} 외 {1}개").format(names[0], len(names) - 1)))
        import threading

        def run():
            try:
                out, sec = shellops.compress(folder, names, fmt)
                sg.done.emit(T("압축 완료: {0} ({1}초)  ✕").format(os.path.basename(out), f"{sec:.1f}"))
            except Exception as ex:
                log.exception("압축 실패")
                sg.done.emit(T("⚠ 압축하지 못했습니다: {0}  ✕").format(ex))
        threading.Thread(target=run, daemon=True, name="compress").start()

    def do_convert(self, paths, fmt):
        """WebP 변환 (v0.9.66, 사용자 요청: webp → png·jpg). webp 만 대상(메뉴 이름과 맞춤). 원본은 그대로, 같은 폴더에 새 파일. 뒤 스레드 → 끝나면 알림"""
        import imgconvert
        todo = imgconvert.targets_for(imgconvert.webp_only(paths), fmt)
        if not todo:
            return
        sg = _undo_signal()
        self.status.emit(T("변환 중: {0}…").format(os.path.basename(todo[0]) if len(todo) == 1 else T("{0} 외 {1}개").format(os.path.basename(todo[0]), len(todo) - 1)))
        log.info("변환 시작 %s %d개: %s", fmt, len(todo), todo[:5])
        import threading

        def run():
            made, anim, fails = imgconvert.convert_many(todo, fmt)
            msg = T("변환 완료: {0} {1}개 만듦").format(fmt.upper(), len(made))
            if anim:
                msg += T(" (움직이는 그림 {0}개는 첫 장면만)").format(anim)
            if fails:
                msg = ("⚠ " + msg + T(" · 실패 {0}개: {1}").format(len(fails), os.path.basename(fails[0][0]))) if made else T("⚠ 변환하지 못했습니다: {0}").format(fails[0][1])
            sg.done.emit(msg + "  ✕")
        threading.Thread(target=run, daemon=True, name="convert").start()

    def do_verb(self, paths, verb):
        """윈도우 셸 동사(즐겨찾기에 고정·시작 화면에 고정) — 실패하면 알림"""
        for p in paths:
            try:
                shellops.shell_verb(p, verb)
            except OSError:
                self.status.emit(T("⚠ 이 윈도우에서는 지원되지 않습니다: {0}").format(os.path.basename(p) or p))
                return

    def send_to_other(self, move=False, target=None):
        """선택 항목을 다른 칸(기본: 직전에 쓰던 칸)의 현재 폴더로 복사/이동"""
        ps = self.selected_paths()
        main = main_of(self)
        if not ps or self.path == THIS_PC or main is None:
            return
        if target is None:
            tp = main.other_pane(self.pane())
            target = tp.view() if tp else None
        if target is None or target.path == THIS_PC or is_search(target.path):
            self.status.emit(T("⚠ 보낼 칸이 없습니다 (다른 칸에서 폴더를 열어 두세요)"))
            return
        if os.path.normcase(target.path) == os.path.normcase(self.path):
            self.status.emit(T("⚠ 같은 폴더입니다"))
            return
        log.info("다른 칸으로 %s n=%d -> %s", "이동" if move else "복사", len(ps), target.path)
        self.file_op(ps, target.path, move, select_in=target)
        self.status.emit(T('{0}개 {1} → {2}').format(len(ps), T('이동') if move else T('복사'), target.path))

    def do_delete(self, permanent=False):
        ps = self.selected_paths()
        if ps and self.path != THIS_PC:   # 검색 결과에서도 됨 (전체 경로)
            def done(res, aborted, ps=ps):   # 작업 스레드에서 불림
                gone = [p for p in ps if not os.path.exists(p)]
                if gone and not permanent:   # 휴지통으로 간 것 → Ctrl+Z 로 복원 (탐색기와 같게, 10/6 사용자 요청)
                    push_undo("delete", gone, T('삭제 {0}개 ({1})').format(len(gone), os.path.basename(gone[0])))
            shellops.delete(self.hwnd(), ps, permanent, done=done)

    def file_op(self, srcs, tgt, move, select_in=None):
        """복사·이동 (셸 작업) + 되돌리기 기록 + 보고 있는 칸이면 새로 생긴 것 선택"""
        try:
            before = set(os.listdir(tgt))
        except OSError:
            before = None
        if select_in is not None and before is not None:
            select_in.new_from = ({e[0] for e in select_in.model_.all}, time.time(), "select", select_in.path)
        src_by_name = {os.path.basename(os.path.normpath(s)).lower(): os.path.normpath(s) for s in srcs}
        has_dir = any(os.path.isdir(x) for x in srcs)

        def done(res, aborted):   # 작업 스레드에서 불림 — 기록만
            if has_dir:   # 폴더가 움직임 → 탐색 창 트리도 고침
                TREE_SIG.changed.emit([tgt] + ([os.path.dirname(os.path.normpath(x)) for x in srcs] if move else []))
            if before is None or res != 0:
                return
            try:
                new = sorted(set(os.listdir(tgt)) - before)
            except OSError:
                return
            if not new:
                return
            if move:
                pairs = [(os.path.join(tgt, n), src_by_name[n.lower()]) for n in new if n.lower() in src_by_name]
                if pairs:
                    push_undo("move", pairs, T('이동 {0}개').format(len(pairs)))
            else:
                push_undo("copy", [os.path.join(tgt, n) for n in new], T('복사 {0}개').format(len(new)))
        shellops.copy_or_move(self.hwnd(), srcs, tgt, move, done=done)

    def copy_path(self):
        """Ctrl+Shift+C: 고른 것의 전체 경로를 따옴표로 묶어 복사 (윈도우 11 '경로로 복사'와 같게). 없으면 지금 폴더"""
        ps = self.selected_paths() or ([self.path] if self.path != THIS_PC and not is_search(self.path) else [])
        if ps:
            QtWidgets.QApplication.clipboard().setText("\r\n".join(f'"{p}"' for p in ps))
            self.status.emit(T('경로 복사: {0}개').format(len(ps)))
            log.info("경로 복사 %d개 %s", len(ps), ps[:2])

    def show_properties(self):
        """Alt+Enter: 속성 창 (여러 개면 묶음, 없으면 지금 폴더)"""
        if self.path == THIS_PC or is_search(self.path):
            ps = self.selected_paths()
            if ps:
                shellops.properties(self.hwnd(), os.path.dirname(ps[0]), [os.path.basename(ps[0])])
            return
        shellops.properties(self.hwnd(), self.path, self.selected_names())

    def do_rename(self):
        ps = self.selected_paths()
        if len(ps) > 1:   # 여러 개 → 이름 일괄 변경 창 (하나면 그 자리에서)
            m = main_of(self)
            if m is not None:
                m.open_batch_rename(ps)
            return
        idx = self.view().currentIndex()
        if idx.isValid() and self.path != THIS_PC:
            self.view().edit(self.model_.index(idx.row(), 0))

    def do_new_folder(self):
        if self.path == THIS_PC:
            self.status.emit(T("⚠ 내 PC 에는 새 폴더를 만들 수 없습니다"))
            return
        if is_search(self.path):
            self.status.emit(T("⚠ 검색 결과에는 새 폴더를 만들 수 없습니다"))
            return
        base, n = T("새 폴더"), 1
        name = base
        while os.path.exists(os.path.join(self.path, name)):
            n += 1
            name = f"{base} ({n})"
        try:
            os.mkdir(os.path.join(self.path, name))
        except OSError as ex:
            self.status.emit(f"⚠ {ex}")
            return
        log.info("새 폴더 %s", os.path.join(self.path, name))
        push_undo("newfolder", os.path.join(self.path, name), T('새 폴더 ({0})').format(name))
        self.pending_edit = name
        self.reload(reason="newfolder")

    # ---------------------------------------------------------- 키보드·마우스
    def handle_key(self, view, ev):
        """파일 목록 단축키 — 키 → 기능은 keymap(보기 > 단축키 설정에서 변경)"""
        if self.editing():
            return False
        act = VIEW_KEYS.get(keymap.event_key(ev))
        if not act:
            return False
        if act == "open":
            self.open_selected()
        elif act == "open_new_tab":
            for p in self.selected_paths():
                if os.path.isdir(p):
                    self.openInNewTab.emit(p)
        elif act == "up":
            self.go_up()
        elif act == "back":
            self.go_back()
        elif act == "fwd":
            self.go_fwd()
        elif act == "refresh":
            self.reload(reason="key")
        elif act in ("send_copy", "send_move"):
            self.send_to_other(move=act == "send_move")
        elif act == "rename":
            self.do_rename()
        elif act in ("delete", "delete_perm"):
            self.do_delete(permanent=act == "delete_perm")
        elif act == "new_folder":
            self.do_new_folder()
        elif act in ("copy", "cut"):
            self.do_copy(act == "cut")
        elif act == "paste":
            self.do_paste()
        elif act == "undo":
            m = main_of(self)
            if m is not None:
                m.undo(self)
        elif act == "copy_path":
            self.copy_path()
        elif act == "properties":
            self.show_properties()
        else:
            return False
        return True

    def handle_mouse(self, view, ev):
        # 마우스 뒤로/앞으로는 Main.eventFilter 가 창 전체에서 처리
        if ev.button() == Qt.MiddleButton:
            idx = view.indexAt(ev.position().toPoint())
            if idx.isValid() and self.model_.rows[idx.row()][1]:
                self.openInNewTab.emit(self.model_.full(self.model_.rows[idx.row()]))
            return True
        return False

    # ---------------------------------------------------------- 우클릭
    def context_menu(self, view, ev):
        idx = view.indexAt(view.viewport().mapFromGlobal(ev.globalPos()))
        if idx.isValid() and not self.sel.isSelected(self.model_.index(idx.row(), 0)):
            self.sel.select(self.model_.index(idx.row(), 0), QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
            view.setCurrentIndex(self.model_.index(idx.row(), 0))
        if not idx.isValid():
            self.sel.clearSelection()
        paths = self.selected_paths() if idx.isValid() else []
        names = self.selected_names() if idx.isValid() else []
        gp = ev.globalPos()
        dpr = self.devicePixelRatioF()  # 화면 배율 보정 (Qt 논리좌표 → 물리 픽셀)
        x, y = int(gp.x() * dpr), int(gp.y() * dpr)
        pane = self.pane()

        if is_search(self.path):
            self._search_menu(gp, x, y, paths)
            return

        if self.path == THIS_PC and not paths:
            # 내 PC 빈 곳: 윈도우 메뉴가 없으므로 기본 메뉴를 직접 보여줌 (아무것도 안 뜨면 고장처럼 보임)
            m = QtWidgets.QMenu(self)
            if pane:
                pane.fill_view_menu(m.addMenu(mlabel(T("보기"), None, "V")))
                pane.fill_sort_menu(m.addMenu(mlabel(T("정렬 기준"), None, "O")))
            m.addAction(mlabel(T("새로 고침"), "refresh", "E"), lambda: self.reload("menu"))
            m.addSeparator()
            fill_fav_menu(m.addMenu(QE_FAV), self.navigate, None)
            m.addSeparator()
            for label, uri in WIN_SETTINGS:
                m.addAction(label, lambda uri=uri: open_settings(uri))
            m.addAction(T("속성 (시스템 정보)"), lambda: open_settings("ms-settings:about"))
            m.exec(gp)
            return

        # 윈도우 메뉴 맨 위에 끼워 넣는 우리 항목: [(표시, 콜백) 또는 (표시, [(하위표시, 콜백)…])]
        extras = []
        if paths:
            dirs = [p for p in paths if os.path.isdir(p)]
            if dirs:
                extras.append((mlabel(T("새 탭에서 열기"), "open_new_tab"), lambda: [self.openInNewTab.emit(p) for p in dirs]))
                extras.append((QE_FAV_ADD, lambda: [FAV.add(p) for p in dirs]))
            main = main_of(self)
            if self.path != THIS_PC and main is not None:
                extras.append((mlabel(T("이름 일괄 변경…"), "rename" if len(paths) > 1 else None), lambda: main.open_batch_rename(self.selected_paths())))
                tg = [(T('칸 {0}: {1}').format(p.idx + 1, p.view().path), p.view()) for p in main.panes
                      if p.isVisible() and p is not pane and p.view() and p.view().path != THIS_PC]
                if tg:
                    extras.append((mlabel(T("다른 칸으로 복사"), "send_copy"), [(t, (lambda v=v: self.send_to_other(False, v))) for t, v in tg]))
                    extras.append((mlabel(T("다른 칸으로 이동"), "send_move"), [(t, (lambda v=v: self.send_to_other(True, v))) for t, v in tg]))
            # 윈도우 11 새 메뉴에만 있는 것 (v0.9.54, 사용자 제보) — "unless" = 윈도우 메뉴에 그 동사가 있으면 우리 것은 숨김
            if self.path != THIS_PC:
                extras.append((mlabel(T("압축"), None), [(T("ZIP 파일"), lambda: self.do_compress("zip")),
                                                         (T("7z 파일"), lambda: self.do_compress("7z")),
                                                         (T("TAR 파일"), lambda: self.do_compress("tar"))]))
                import imgconvert   # WebP 변환 (v0.9.66) — webp 를 골랐을 때만 (사용자: '그림 변환' 은 뭔지 모름 → 이름·대상을 webp 로)
                conv = [(lbl, (lambda f=f: self.do_convert(paths, f))) for f, lbl in (("png", T("PNG로 저장")), ("jpg", T("JPG로 저장")))
                        if imgconvert.targets_for(imgconvert.webp_only(paths), f)]
                if conv and not is_search(self.path):
                    extras.append((mlabel(T("WebP 변환"), None), conv))
            if dirs:
                extras.append(({"t": T("윈도우 즐겨찾기에 고정"), "unless": {"pintohome"}}, lambda: self.do_verb(dirs, "pintohome")))
                extras.append(({"t": T("시작 화면에 고정"), "unless": {"pintostartscreen"}}, lambda: self.do_verb(dirs, "pintostartscreen")))
            extras.append(({"t": T("경로로 복사"), "unless": {"copyaspath"}}, lambda: shellops.copy_as_path(paths)))
            if len(paths) == 1 and dirs:
                extras.append((T("터미널에서 열기"), lambda: shellops.open_terminal(dirs[0])))
        favs =[((f"{d['group']} ▸ {d['name']}" if d.get("group") else d["name"]), (lambda p=d["path"]: self.navigate(p))) for d in FAV.items]
        if not paths and self.path != THIS_PC:
            favs += [("-", None), (mlabel(T("이 폴더를 ★4Dir 즐겨찾기에 추가"), "add_fav"), lambda: FAV.add(self.path))]
        fav_entry = (QE_FAV, favs or [(T("(비어 있음)"), lambda: None)])
        newfolder = None
        if paths:
            extras.append(fav_entry)
        else:
            # 빈 곳: 윈도우 탐색기 빈 곳 메뉴 순서 (10/8 사용자 확정) — 새 폴더 · 보기 · 정렬 기준 · 새로 고침 · ★4Dir 즐겨찾기
            # ─ 붙여넣기(복사한 것 없으면 흐림) ─ 윈도우 항목들(윈도우 '새 폴더' 자리에 되돌리기) … 속성
            v = self
            extras.append((mlabel(T("새 폴더"), "new_folder", "N"), self.do_new_folder))
            if pane:
                extras.append((mlabel(T("보기"), None, "V"), [({"t": lbl, "chk": pane.mode == k}, (lambda k=k: pane.set_mode(k))) for k, lbl, _ in VIEW_MODES]))
            srt = [({"t": lbl, "chk": c == v.model_.sort_col}, (lambda c=c: v.set_sort(c, v.model_.sort_order))) for c, lbl in SORT_COLS]
            srt += [("-", None)] + [({"t": lbl, "chk": o == v.model_.sort_order}, (lambda o=o: v.set_sort(v.model_.sort_col, o)))
                                    for o, lbl in ((Qt.AscendingOrder, T("오름차순")), (Qt.DescendingOrder, T("내림차순")))]
            extras.append((mlabel(T("정렬 기준"), None, "O"), srt))
            extras.append((mlabel(T("새로 고침"), "refresh", "E"), lambda: self.reload("menu")))
            extras.append((T("터미널에서 열기"), lambda: shellops.open_terminal(self.path)))   # 윈도우 11 빈 곳 메뉴처럼 (v0.9.54)
            extras.append(fav_entry)
            extras.append(("-", None))
            extras.append(({"t": mlabel(T("붙여넣기"), "paste", "P"), "off": not shellops.get_clipboard()[0]}, self.do_paste))
            main = main_of(self)
            undo_t = mlabel(T("되돌리기"), None, "U") + (" — " + UNDO[-1][2].replace("&", "&&") if UNDO else "")
            undo_t += ("\t" + key_text("undo")) if key_text("undo") else ""
            newfolder = ({"t": undo_t, "off": not UNDO},
                         {T("새 폴더"), "새 폴더", "new folder"},   # 윈도우 '새 폴더' 항목 글자 (윈도우 언어)
                         lambda: main.undo(self) if main is not None else None)

        spec, calls = [], []
        for label, cb in extras:
            if label == "-":
                spec.append("-")
            elif isinstance(cb, list):
                spec.append((label, [t for t, _ in cb]))
                calls += [c for t, c in cb if t != "-"]
            else:
                spec.append(label)
                calls.append(cb)
        if newfolder:
            calls.append(newfolder[2])
        folder, items = (self.path, names) if self.path != THIS_PC else ("", paths)
        before = {e[0] for e in self.model_.all}
        try:
            r = shellops.ShellMenu.show(self.hwnd(), folder, items, x, y, extras=spec,
                                        newfolder=newfolder[:2] if newfolder else None,
                                        extended=bool(QtWidgets.QApplication.keyboardModifiers() & Qt.ShiftModifier))
        except Exception:
            log.exception("셸메뉴 실패 → 기본 메뉴")
            r = self._fallback_menu(gp, names)
        if r and r[0] == "rename":
            self.do_rename()
        elif r and r[0] == "extra":
            calls[r[1]]()
        elif r and r[0] == "invoked" and not paths and (r[1] == "NewFolder" or r[1].startswith(".")):
            # '새로 만들기 ▸ 폴더/텍스트 문서…' → 생긴 항목을 이름 편집 상태로 (탐색기와 같게, 10/8 사용자 요청)
            self.new_from = (before, time.time(), "edit", self.path)
            log.info("새로 만들기(%s) → 생기면 이름 편집", r[1])

    def _search_menu(self, gp, x, y, paths):
        """검색 결과 우클릭: 맨 위 '폴더 위치 열기' + (같은 폴더 항목이면) 윈도우 메뉴"""
        if not paths:
            m = QtWidgets.QMenu(self)
            m.addAction(T("다시 검색"), lambda: self.reload("menu"))
            m.exec(gp)
            return
        first = paths[0]
        loc, nm = os.path.dirname(first), os.path.basename(first)
        extras = [(T("폴더 위치 열기"), lambda: self.navigate(loc, select=nm)),
                  (T("새 탭에서 폴더 위치 열기"), lambda: self.openInNewTab.emit(loc))]
        if main_of(self) is not None:
            extras.append((mlabel(T("이름 일괄 변경…"), "rename" if len(paths) > 1 else None), lambda: main_of(self).open_batch_rename(self.selected_paths())))
        parents = {os.path.normcase(os.path.dirname(pth)) for pth in paths}
        if len(parents) == 1:
            try:
                r = shellops.ShellMenu.show(self.hwnd(), loc, [os.path.basename(pth) for pth in paths], x, y,
                                            extras=[t for t, _ in extras],
                                            extended=bool(QtWidgets.QApplication.keyboardModifiers() & Qt.ShiftModifier))
                if r and r[0] == "rename":
                    self.do_rename()
                elif r and r[0] == "extra":
                    extras[r[1]][1]()
                return
            except Exception:
                log.exception("검색 결과 셸메뉴 실패 → 기본 메뉴")
        # 여러 폴더의 항목을 한꺼번에 고르면 윈도우 메뉴를 만들 수 없어 기본 메뉴
        m = QtWidgets.QMenu(self)
        for t, cb in extras:
            m.addAction(t, cb)
        m.addSeparator()
        m.addAction(T("열기"), self.open_selected)
        m.addAction(T("복사"), lambda: self.do_copy(False))
        m.addAction(T("잘라내기"), lambda: self.do_copy(True))
        m.addAction(T("삭제 (휴지통)"), self.do_delete)
        m.exec(gp)

    def _fallback_menu(self, pos, names):
        m = QtWidgets.QMenu(self)
        if names:
            m.addAction(mlabel(T("열기"), "open", "O"), self.open_selected)
            m.addAction(mlabel(T("복사"), "copy", "C"), lambda: self.do_copy(False))
            m.addAction(mlabel(T("잘라내기"), "cut", "T"), lambda: self.do_copy(True))
            m.addAction(mlabel(T("삭제"), "delete", "D"), self.do_delete)
            m.addAction(mlabel(T("이름 바꾸기"), "rename", "M"), self.do_rename)
        m.addAction(mlabel(T("붙여넣기"), "paste", "P"), self.do_paste)
        m.addAction(mlabel(T("새 폴더"), "new_folder", "N"), self.do_new_folder)
        m.exec(pos)
        return None

    def pane(self):
        w = self.parentWidget()
        while w is not None and not isinstance(w, Pane):
            w = w.parentWidget()
        return w

    # ---------------------------------------------------------- 드래그 앤 드롭
    def _drop_target(self, view, ev):
        idx = view.indexAt(ev.position().toPoint())
        if idx.isValid():
            e = self.model_.rows[idx.row()]
            if e[1]:
                return self.model_.full(e)
        return self.path

    def drop_action(self, view, ev):
        m = ev.modifiers()
        if m & Qt.ControlModifier:
            return Qt.CopyAction
        if m & Qt.ShiftModifier:
            return Qt.MoveAction
        srcs = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        tgt = self._drop_target(view, ev)
        same_drive = srcs and os.path.splitdrive(srcs[0])[0].lower() == os.path.splitdrive(tgt)[0].lower()
        return Qt.MoveAction if same_drive else Qt.CopyAction

    def drop(self, view, ev):
        srcs = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        tgt = self._drop_target(view, ev)
        move = self.drop_action(view, ev) == Qt.MoveAction
        srcs = [s for s in srcs if os.path.normcase(os.path.normpath(s)) != os.path.normcase(tgt)]
        log.info("드롭 %s n=%d -> %s", "이동" if move else "복사", len(srcs), tgt)
        if srcs:
            self.file_op(srcs, tgt, move, select_in=self if os.path.normcase(tgt) == os.path.normcase(self.path) else None)
        # 원본 쪽(탐색기 등)이 따로 지우지 않도록 '복사'로 응답 — 이동은 우리가 직접 처리함
        ev.setDropAction(Qt.CopyAction)
        ev.accept()


# 예전 이름 호환(테스트 스크립트 등)
FileView = Page


WIN_SETTINGS = [(T("디스플레이 설정"), "ms-settings:display"), (T("개인 설정"), "ms-settings:personalization")]


def open_settings(uri):
    log.info("윈도우 설정 열기 %s", uri)
    try:
        os.startfile(uri)
    except OSError:
        log.exception("설정 열기 실패 %s", uri)


def fill_fav_menu(menu, go, new_tab):
    """즐겨찾기 하위메뉴 채우기. go(path) = 이동, new_tab(path) = 새 탭(없으면 생략)"""
    menu.clear()
    if not FAV.items:
        a = menu.addAction(T("(비어 있음)"))
        a.setEnabled(False)
    icon = shellops.icon_for("", True, 16)
    menu.setToolTipsVisible(True)
    for start, end, g in FAV.entries():
        target = menu.addMenu(favorg.group_icon(16), g) if g else menu   # 묶음 = 하위 메뉴
        if g:
            target.setToolTipsVisible(True)
        for d in FAV.items[start:end]:
            a = target.addAction(icon, d["name"])
            a.setToolTip(d["path"])
            a.triggered.connect(lambda _=False, p=d["path"]: go(p))
    return menu


# ================================================================ 사이드바 (탐색 창)
class SideSignals(QtCore.QObject):
    pc = QtCore.Signal(list)              # [(label, path, sysidx)]
    subdirs = QtCore.Signal(object, list)  # item, [names]
    pinned = QtCore.Signal(object)         # 윈도우 고정 폴더 [{name, path}] / None(응답 없음)


class PinnedJob(QtCore.QRunnable):
    """윈도우 탐색기에 고정한 폴더 읽기 (2초 안에 답 없으면 None)"""
    def __init__(self, sig):
        super().__init__()
        self.sig = sig

    def run(self):
        self.sig.pinned.emit(favorites.windows_pinned(2.0))


class PcInfoJob(QtCore.QRunnable):
    def __init__(self, sig):
        super().__init__()
        self.sig = sig

    def run(self):
        rows = [(e[7], e[5], e[6]) for e in this_pc_entries()]
        self.sig.pc.emit(rows)


class SubdirJob(QtCore.QRunnable):
    def __init__(self, sig, item, path):
        super().__init__()
        self.sig, self.item, self.path = sig, item, path

    def run(self):
        out = []
        try:
            with os.scandir(self.path) as it:
                for de in it:
                    try:
                        if de.is_dir(follow_symlinks=False) and not (de.stat(follow_symlinks=False).st_file_attributes & HIDDEN_MASK and not OPTS["show_hidden"]):
                            out.append(de.name)
                    except OSError:
                        pass
        except OSError:
            pass
        out.sort(key=shellops.natural_key)
        self.sig.subdirs.emit(self.item, out)


PATH_ROLE = Qt.UserRole + 1
DUMMY = "…"


class Sidebar(DragScrollMixin, QtWidgets.QTreeWidget):
    go = QtCore.Signal(str)
    goNewTab = QtCore.Signal(str)
    _drop_item = None    # 끌어서 놓을 폴더 (진하게 표시)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setUniformRowHeights(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setExpandsOnDoubleClick(False)
        self.sig = SideSignals()
        self.sig.pc.connect(self._fill_pc)
        self.sig.subdirs.connect(self._fill_sub)
        self.sig.pinned.connect(self._fill_pinned)
        self._pinned_at = 0.0
        bold = self.font()
        bold.setBold(True)
        self.fav_root = QtWidgets.QTreeWidgetItem([T("즐겨찾기 (Windows)")])   # 윈도우 탐색기 고정 폴더 (4Dir 즐겨찾기는 상단 바)
        self.pc_root = QtWidgets.QTreeWidgetItem([T(THIS_PC)])
        for r in (self.fav_root, self.pc_root):
            r.setFont(0, bold)
            r.setFlags(Qt.ItemIsEnabled)
            self.addTopLevelItem(r)
        self.pc_root.setData(0, PATH_ROLE, THIS_PC)
        self.pc_root.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.itemExpanded.connect(self._on_expand)
        self.itemClicked.connect(self._on_click)
        self.fav_root.setToolTip(0, T("윈도우 탐색기에 고정한 폴더 (고정·해제는 윈도우 탐색기에서) · 접었다 펼치면 다시 읽음"))
        self.refresh_pinned()
        self.fav_root.setExpanded(True)
        self.pc_root.setExpanded(True)
        POOL.start(PcInfoJob(self.sig))
        # 파일·폴더를 끌어다 트리의 폴더에 놓기 (윈도우 탐색기처럼) — 표시는 파일 목록과 같게
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self._expand_timer = QtCore.QTimer(self)
        self._expand_timer.setSingleShot(True)
        self._expand_timer.setInterval(700)     # 접힌 폴더 위에 잠깐 머물면 펼침
        self._expand_timer.timeout.connect(self._hover_expand)
        self.setDragEnabled(True)               # 트리의 폴더를 끌어 다른 폴더·칸으로 (탐색기처럼)
        TREE_SIG.changed.connect(self._refresh_paths)

    def startDrag(self, actions):
        it = self.currentItem()
        path = it.data(0, PATH_ROLE) if it is not None else None
        if not path or path == THIS_PC or not os.path.isdir(path) or len(os.path.normpath(path)) <= 3:
            return   # '내 PC'·드라이브·그룹 제목은 못 끎
        md = QtCore.QMimeData()
        md.setUrls([QtCore.QUrl.fromLocalFile(path)])
        icon = it.icon(0) if not it.icon(0).isNull() else shellops.icon_for("", True, 48)
        pm, hot = drag_pixmap(icon, 1, self.devicePixelRatioF())
        drag = QtGui.QDrag(self)
        drag.setMimeData(md)
        drag.setPixmap(pm)
        drag.setHotSpot(hot)
        log.info("탐색 창에서 끌기 시작 %s", path)
        try:
            drag.exec(Qt.CopyAction | Qt.MoveAction | Qt.LinkAction, Qt.CopyAction)
        finally:
            drop_hint(None)
            self._set_drop_item(None)
            self._stop_autoscroll()

    def _refresh_paths(self, paths):
        """그 폴더들의 하위 목록을 이미 읽어 둔 항목만 다시 읽음 (폴더가 옮겨진 뒤)"""
        want = {self._nc(x) for x in paths if x}
        stack = [self.invisibleRootItem()]
        n = 0
        while stack:
            it = stack.pop()
            for i in range(it.childCount()):
                c = it.child(i)
                p = c.data(0, PATH_ROLE)
                loaded = not (c.childCount() == 1 and c.child(0).text(0) == DUMMY)
                if p and p != THIS_PC and loaded and self._nc(p) in want:
                    POOL.start(SubdirJob(self.sig, c, p))
                    n += 1
                if loaded:
                    stack.append(c)
        if n:
            log.info("탐색 창 다시 읽기 %d곳 %s", n, list(want)[:3])

    # ---------------------------------------------------------- 끌어 놓기 (트리의 폴더 안으로)
    def _target(self, pos, md):
        """놓을 폴더 항목 (못 놓는 곳이면 None)"""
        it = self.itemAt(pos)
        path = it.data(0, PATH_ROLE) if it is not None else None
        if not path or path == THIS_PC or not os.path.isdir(path):
            return it, None
        srcs = [os.path.normcase(os.path.normpath(u.toLocalFile())) for u in md.urls() if u.isLocalFile()]
        t = os.path.normcase(os.path.normpath(path))
        if any(t == x or t.startswith(x.rstrip("\\") + "\\") for x in srcs):
            return it, None          # 자기 자신·자기 안쪽으로는 못 놓음
        if srcs and all(os.path.dirname(x) == t for x in srcs):
            return it, None          # 원래 있던 폴더 (탐색기처럼 아무 일 없음)
        return it, path

    @staticmethod
    def _action(ev, tgt):
        m = ev.modifiers()
        if m & Qt.ControlModifier:
            return Qt.CopyAction
        if m & Qt.ShiftModifier:
            return Qt.MoveAction
        srcs = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        same = srcs and os.path.splitdrive(srcs[0])[0].lower() == os.path.splitdrive(tgt)[0].lower()
        return Qt.MoveAction if same else Qt.CopyAction

    def _set_drop_item(self, it):
        if it is not self._drop_item:
            self._drop_item = it
            self.viewport().update()

    def _drag_retarget(self, pos):
        md = getattr(self, "_drag_md", None)
        if md is not None:
            self._set_drop_item(self._target(pos, md)[1] and self.itemAt(pos))

    def _hover_expand(self):
        it = getattr(self, "_hover_item", None)
        if it is not None and it.childCount() and not it.isExpanded():
            it.setExpanded(True)

    def drawRow(self, painter, option, index):
        super().drawRow(painter, option, index)
        if self._drop_item is not None and self.itemFromIndex(index) is self._drop_item:
            r = QtCore.QRect(option.rect)
            r.setLeft(0)
            r.setRight(self.viewport().width() - 1)
            _drop_paint(self, painter, r)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        md = ev.mimeData()
        if not md.hasUrls():
            ev.ignore()
            return
        pos = ev.position().toPoint()
        self._drag_md, self._as_pos = md, pos
        self._autoscroll(pos.y())
        it, path = self._target(pos, md)
        if it is not getattr(self, "_hover_item", None):
            self._hover_item = it
            self._expand_timer.start()
        if path is None:
            self._set_drop_item(None)
            drop_hint(None)
            ev.ignore()
            return
        self._set_drop_item(it)
        act = self._action(ev, path)
        ev.setDropAction(act)
        ev.accept()
        fmt = T("→ {0}(으)로 이동") if act == Qt.MoveAction else T("→ {0}(으)로 복사")
        drop_hint(fmt.format(it.text(0)), self.viewport().mapToGlobal(pos))

    def dragLeaveEvent(self, ev):
        self._set_drop_item(None)
        self._stop_autoscroll()
        self._expand_timer.stop()
        drop_hint(None)

    def dropEvent(self, ev):
        pos = ev.position().toPoint()
        it, path = self._target(pos, ev.mimeData())
        self._set_drop_item(None)
        self._stop_autoscroll()
        self._expand_timer.stop()
        drop_hint(None)
        if path is None:
            ev.ignore()
            return
        srcs = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        move = self._action(ev, path) == Qt.MoveAction
        w = self.parentWidget()
        while w is not None and not isinstance(w, Pane):
            w = w.parentWidget()
        v = w.view() if w is not None else None
        log.info("탐색 창으로 놓기 %s n=%d -> %s", "이동" if move else "복사", len(srcs), path)
        if v is not None and srcs:
            v.file_op(srcs, path, move, select_in=v if os.path.normcase(v.path) == os.path.normcase(path) else None)
        ev.setDropAction(Qt.CopyAction)   # 원본 쪽이 따로 지우지 않게 (이동은 우리가 처리)
        ev.accept()

    def _folder_item(self, label, path, icon):
        it = QtWidgets.QTreeWidgetItem([label])
        it.setData(0, PATH_ROLE, path)
        it.setToolTip(0, path)
        it.setIcon(0, icon)
        it.addChild(QtWidgets.QTreeWidgetItem([DUMMY]))  # 펼칠 수 있게 (펼칠 때 읽음)
        return it

    def refresh_pinned(self):
        self._pinned_at = time.time()
        POOL.start(PinnedJob(self.sig))

    def _fill_pinned(self, items):
        try:
            self.fav_root.takeChildren()
        except RuntimeError:
            return
        if items is None:
            self.fav_root.addChild(QtWidgets.QTreeWidgetItem([T("(응답 없음 — 접었다 펼치면 다시 읽음)")]))
            return
        if not items:
            self.fav_root.addChild(QtWidgets.QTreeWidgetItem([T("(비어 있음)")]))
        for d in items:
            self.fav_root.addChild(self._folder_item(d["name"], d["path"], shellops.icon_for("", True, 16)))

    def _fill_pc(self, rows):
        self.pc_root.takeChildren()
        for label, path, idx in rows:
            self.pc_root.addChild(self._folder_item(label, path, shellops.icon_for("", True, 16, idx)))
        if getattr(self, "_reveal_path", None):
            self.reveal(self._reveal_path)       # 내 PC 목록이 늦게 와서 미뤄 둔 것

    # ---------------------------------------------------------- 지금 폴더까지 펼치기 (칸과 동기화)
    @staticmethod
    def _nc(p):
        return os.path.normcase(os.path.normpath(p)).rstrip("\\")

    def reveal(self, path):
        """'내 PC' 아래에서 path 까지 한 단계씩 펼치고 선택. 하위 목록은 펼칠 때 읽으므로 비동기로 이어감"""
        self._reveal_path = path
        self._reveal_wait = None
        if not path or path == THIS_PC or is_search(path):
            if path == THIS_PC:
                self._select(self.pc_root)
            self._reveal_path = None
            return
        tgt = self._nc(path)
        best, blen = None, -1
        for i in range(self.pc_root.childCount()):       # 가장 길게 겹치는 시작점 (예: E:\Downloads\x → '다운로드')
            it = self.pc_root.child(i)
            ip = it.data(0, PATH_ROLE)
            if not ip or it.text(0) == DUMMY:
                continue
            n = self._nc(ip)
            if (tgt == n or tgt.startswith(n + "\\")) and len(n) > blen:
                best, blen = it, len(n)
        if best is None:
            return                                         # 내 PC 목록 아직 → _fill_pc 가 다시 부름
        self._reveal_step(best)

    def _reveal_step(self, it):
        tgt = self._nc(self._reveal_path or "")
        if not tgt:
            return
        if self._nc(it.data(0, PATH_ROLE)) == tgt:
            self._select(it)
            self._reveal_path = None
            return
        if it.childCount() == 1 and it.child(0).text(0) == DUMMY:
            self._reveal_wait = it                         # 하위 읽기 끝나면(_fill_sub) 이어서
            if it.isExpanded():
                self._on_expand(it)
            else:
                it.setExpanded(True)
            return
        it.setExpanded(True)
        for i in range(it.childCount()):
            c = it.child(i)
            cp = c.data(0, PATH_ROLE)
            if cp and (tgt == self._nc(cp) or tgt.startswith(self._nc(cp) + "\\")):
                self._reveal_step(c)
                return
        self._select(it)                                   # 숨김 폴더 등 목록에 없음 → 가장 가까운 곳
        self._reveal_path = None

    def _select(self, it):
        self.blockSignals(True)
        self.setCurrentItem(it)
        self.blockSignals(False)
        self.scrollToItem(it, QtWidgets.QAbstractItemView.PositionAtCenter)

    def _on_expand(self, it):
        if it is self.fav_root:
            if time.time() - self._pinned_at > 3:   # 펼칠 때마다 윈도우 고정 목록 다시 읽음 (연달아 누르면 한 번)
                self.refresh_pinned()
            return
        if it.childCount() == 1 and it.child(0).text(0) == DUMMY:
            p = it.data(0, PATH_ROLE)
            if p and p != THIS_PC:
                POOL.start(SubdirJob(self.sig, it, p))

    def _fill_sub(self, it, names):
        try:
            p = it.data(0, PATH_ROLE)
            # 다시 읽을 때 펼쳐져 있던 하위 폴더는 다시 펼침 (폴더 옮긴 뒤 트리가 접히지 않게)
            was_open = {self._nc(it.child(i).data(0, PATH_ROLE)) for i in range(it.childCount())
                        if it.child(i).isExpanded() and it.child(i).data(0, PATH_ROLE)}
            it.takeChildren()
        except RuntimeError:
            return
        icon = shellops.icon_for("", True, 16)
        reopen = []
        for n in names:
            c = self._folder_item(n, os.path.join(p, n), icon)
            it.addChild(c)
            if self._nc(os.path.join(p, n)) in was_open:
                reopen.append(c)
        for c in reopen:
            c.setExpanded(True)   # 펼치면 그 안을 다시 읽음
        if getattr(self, "_reveal_wait", None) is it and self._reveal_path:
            self._reveal_wait = None
            self._reveal_step(it)

    def _on_click(self, it, col):
        p = it.data(0, PATH_ROLE)
        if p:
            if QtWidgets.QApplication.mouseButtons() & Qt.MiddleButton:
                self.goNewTab.emit(p)
            else:
                self.go.emit(p)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            it = self.itemAt(ev.position().toPoint())
            if it and it.data(0, PATH_ROLE):
                self.goNewTab.emit(it.data(0, PATH_ROLE))
            return
        super().mousePressEvent(ev)

    def contextMenuEvent(self, ev):
        it = self.itemAt(ev.pos())
        if not it or not it.data(0, PATH_ROLE):
            return
        p = it.data(0, PATH_ROLE)
        m = QtWidgets.QMenu(self)
        m.addAction(T("열기"), lambda: self.go.emit(p))
        m.addAction(T("새 탭에서 열기"), lambda: self.goNewTab.emit(p))
        if p != THIS_PC:
            m.addAction(QE_FAV_ADD, lambda: FAV.add(p))
        m.exec(ev.globalPos())


# ================================================================ 경로 버튼 (브레드크럼, 옵션)
CRUMB_ROOM = 40   # 경로 버튼 줄 오른쪽에 늘 비워 둘 폭(px) — 클릭해서 주소 입력·복사할 자리


class Crumbs(QtWidgets.QFrame):
    """'D: > 000.작업 > (c8)...' 버튼 줄. 버튼=그 폴더로 이동, 빈 곳 클릭=입력칸으로 전환. 넘치면 앞부분을 '…' 메뉴로."""
    go = QtCore.Signal(str)
    edit = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("crumbs")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setCursor(Qt.IBeamCursor)
        self.lay = QtWidgets.QHBoxLayout(self)
        self.lay.setContentsMargins(2, 0, 2, 0)
        self.lay.setSpacing(0)
        self.path = ""

    @staticmethod
    def segments(p):
        if not p or p == THIS_PC:
            return [(T(THIS_PC), THIS_PC)]
        if is_search(p):   # 검색 탭: 드라이브 조각 없이 검색어 하나
            return [(T(THIS_PC), THIS_PC), (tab_title(p), p)]
        out = [(T(THIS_PC), THIS_PC)]
        drive, rest = os.path.splitdrive(p)
        acc = drive + "\\"
        out.append((drive, acc))
        for part in [x for x in rest.split("\\") if x]:
            acc = os.path.join(acc, part)
            out.append((part, acc))
        return out

    def set_path(self, p):
        self.path = p
        self._rebuild()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._rebuild()

    def _rebuild(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().hide()          # 지워지기 전까지 겹쳐 보이지 않게 즉시 숨김
                it.widget().deleteLater()
        segs = self.segments(self.path)
        # 버튼·구분자 실제 폭으로 계산 (예전엔 글자폭+22 로 어림해 실제로는 오른쪽 끝까지 꽉 참)
        # 오른쪽에 CRUMB_ROOM 만큼은 항상 비워 둠 → 빈 곳 클릭으로 경로 입력칸(전체 주소 복사)이 쉬움 (10/6 사용자 요청)
        btns = []
        for lbl, p in segs:
            b = QtWidgets.QToolButton(self)   # 부모를 먼저 줘야 스타일(여백)이 들어간 실제 폭이 나옴
            b.hide()
            b.setText(lbl)
            b.setAutoRaise(True)
            b.setCursor(Qt.ArrowCursor)
            b.setToolTip(disp_path(p))
            b.clicked.connect(lambda _=False, p=p: self.go.emit(p))
            btns.append(b)
        probe = QtWidgets.QLabel("›", self)
        probe.setStyleSheet("color:#8a939c; padding:0 1px;")
        probe.hide()
        probe.ensurePolished()
        sep_w = probe.sizeHint().width()
        probe.deleteLater()
        for b in btns:
            b.ensurePolished()
        widths = [b.sizeHint().width() + sep_w for b in btns]
        avail = max(self.width() - CRUMB_ROOM - 30, 80)   # 30 = 앞쪽 '…' 버튼 자리
        start = 0
        while start < len(segs) - 1 and sum(widths[start:]) > avail:
            start += 1
        for b in btns[:start]:
            b.deleteLater()
        if start:
            more = QtWidgets.QToolButton()
            more.setText("…")
            more.setAutoRaise(True)
            more.setCursor(Qt.ArrowCursor)
            mm = QtWidgets.QMenu(more)
            for lbl, p in segs[:start]:
                mm.addAction(lbl, lambda p=p: self.go.emit(p))
            more.setMenu(mm)
            more.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            self.lay.addWidget(more)
        for k, b in enumerate(btns[start:]):
            if k or start:
                sep = QtWidgets.QLabel("›")
                sep.setStyleSheet("color:#8a939c; padding:0 1px;")
                self.lay.addWidget(sep)
            self.lay.addWidget(b)
            b.show()
        self.lay.addStretch(1)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.edit.emit()   # 빈 곳 클릭 → 경로 입력칸
        super().mousePressEvent(ev)


def state_panes(st):
    """저장 상태에서 보이던 칸 번호들 (자동 기록 목록 표시용)"""
    rows = layout_rows(st.get("layout", "4")) or LAYOUT_ROWS["4"]
    return sorted({i for row in rows for i in row})


def push_undo(kind, data, label):
    UNDO.append((kind, data, label))
    del UNDO[:-30]
    log.info("되돌리기 기록 %s %s (쌓인 %d)", kind, label, len(UNDO))


def open_in_explorer(path):
    """윈도우 탐색기 새 창으로 그 폴더 열기 (4Dir 이 탐색기와 다르게 동작하는 일을 할 때)"""
    target = "shell:MyComputerFolder" if path == THIS_PC else path
    log.info("윈도우 탐색기로 열기 %s", target)
    try:
        subprocess.Popen(["explorer.exe", target])
    except OSError:
        log.exception("탐색기 열기 실패 %s", target)


def main_of(w):
    """w 가 들어 있는 4Dir 창 (Main). 창이 여러 개여도 각자 자기 창"""
    win = w.window()
    return win if isinstance(win, Main) else None


# ================================================================ 뒤로·앞으로·위로 화살표 (윈도우 탐색기처럼 같은 굵기·크기, 방향만 다름)
class ArrowIcon(QtGui.QIconEngine):
    """선 화살표를 그릴 때마다 현재 글자색으로 그림 → 밝게/어둡게 테마를 바꿔도 자동으로 맞음, 고해상도 화면도 선명"""
    ANGLE = {"back": 0, "up": 90, "fwd": 180}

    def __init__(self, way):
        super().__init__()
        self.way = way

    def clone(self):
        return ArrowIcon(self.way)

    def paint(self, p, rect, mode, state):
        pal = QtWidgets.QApplication.palette()
        grp = QtGui.QPalette.Disabled if mode == QtGui.QIcon.Disabled else QtGui.QPalette.Active
        s = min(rect.width(), rect.height())
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.translate(QtCore.QRectF(rect).center())
        p.rotate(self.ANGLE[self.way])
        pen = QtGui.QPen(pal.color(grp, QtGui.QPalette.ButtonText), max(1.3, s * 0.085))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        h = s * 0.34   # 왼쪽을 가리키는 화살표를 기준으로 그리고 돌림
        p.drawLine(QtCore.QPointF(h, 0), QtCore.QPointF(-h, 0))
        p.drawPolyline([QtCore.QPointF(-h + s * 0.30, -s * 0.30), QtCore.QPointF(-h, 0), QtCore.QPointF(-h + s * 0.30, s * 0.30)])
        p.restore()

    def scaledPixmap(self, size, mode, state, scale):
        pm = QtGui.QPixmap(size * scale)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        self.paint(p, QtCore.QRect(QtCore.QPoint(0, 0), size * scale), mode, state)
        p.end()
        pm.setDevicePixelRatio(scale)
        return pm

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, 1.0)


def arrow_icon(way):
    return QtGui.QIcon(ArrowIcon(way))


# ================================================================ 칸 하나 = 머리줄 + (사이드바 | 탭들) + 상태줄
class PaneTabBar(QtWidgets.QTabBar):
    """칸의 탭줄. 닫기 단추(×)를 탭 안쪽으로 4px (v0.9.56, 사용자: '× 가 탭 밖으로 나갔다').
    윈도우 스타일은 단추를 탭 칸 오른쪽 끝 1px 안에 두는데, 우리 탭은 칸 사이 간격(margin-right 2px)이 있어 실제
    테두리가 2px 안쪽 → 단추가 테두리 위에 걸쳐 밖으로 보였음(측정: 칸 0~79, 단추 63~78, 테두리 77).
    스타일시트 QTabBar::close-button 위치 규칙·앱 스타일 대리 모두 이 단추엔 안 먹음(실측) → 배치가 끝날 때마다 옮김"""
    CLOSE_SHIFT = 4

    def __init__(self, *a):
        super().__init__(*a)
        # 탭 선택·추가 때 Qt 가 전체 배치 없이 그 탭 단추만 다시 놓음(실측) → 그 직후에도 옮김
        self.currentChanged.connect(self._fix_later)

    def _fix_later(self, *_):
        QtCore.QTimer.singleShot(0, self._fix_close_buttons)

    def tabLayoutChange(self):
        super().tabLayoutChange()
        self._fix_close_buttons()

    def tabInserted(self, index):
        super().tabInserted(index)
        self._fix_later()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self._fix_later()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fix_later()

    def _fix_close_buttons(self):
        for i in range(self.count()):
            b = self.tabButton(i, QtWidgets.QTabBar.RightSide)
            if b is not None:
                r = self.tabRect(i)
                b.move(r.right() - self.CLOSE_SHIFT - b.width(), b.y())


class Pane(QtWidgets.QFrame):
    changed = QtCore.Signal()

    def __init__(self, idx, parent=None):
        super().__init__(parent)
        self.idx = idx
        self.shown = True
        self.mode = "details"
        self.pages = {}
        self.setObjectName("pane")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- 머리줄: 뒤로 앞으로 위로 새로고침 새폴더 | 주소 | 보기 | 탐색창
        head = QtWidgets.QWidget()
        head.setObjectName("paneHead")
        # 칸이 좁아지면 머리줄 끝이 가려지게(창 가로 축소를 막지 않도록)
        head.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        bar = QtWidgets.QHBoxLayout(head)
        bar.setContentsMargins(4, 3, 4, 3)
        bar.setSpacing(2)
        st = self.style()

        def btn(icon, tip, fn, text=None):
            b = QtWidgets.QToolButton()
            if icon is not None:
                b.setIcon(st.standardIcon(icon) if isinstance(icon, QtWidgets.QStyle.StandardPixmap) else icon)
            if text:
                b.setText(text)
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if icon is not None else Qt.ToolButtonTextOnly)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            if fn:
                b.clicked.connect(fn)
            bar.addWidget(b)
            return b

        self.btn_side = btn(None, T("탐색 창 보이기/숨기기"), self.toggle_sidebar, "☰")
        self.btn_side.setCheckable(True)
        btn(arrow_icon("back"), T("뒤로 (Alt+←)"), lambda: self.view() and self.view().go_back())
        btn(arrow_icon("fwd"), T("앞으로 (Alt+→)"), lambda: self.view() and self.view().go_fwd())
        btn(arrow_icon("up"), T("상위 폴더 (Backspace)"), lambda: self.view() and self.view().go_up())
        btn(QtWidgets.QStyle.SP_FileDialogNewFolder, T("새 폴더 (Ctrl+Shift+N)"), lambda: self.view() and self.view().do_new_folder())
        btn(QtWidgets.QStyle.SP_BrowserReload, T("새로 고침 (F5)"), lambda: self.view() and self.view().reload("button"))
        # 주소: 전체 경로 입력칸(기본) 또는 경로 버튼(브레드크럼, 옵션) — 버튼 모드에서 빈 곳 클릭하면 입력칸
        self.addr = QtWidgets.QLineEdit()
        self.addr.setPlaceholderText(T("경로 입력 후 Enter (Ctrl+L)"))
        self.addr.returnPressed.connect(self._addr_go)
        self.addr.installEventFilter(self)
        self.crumbs = Crumbs()
        self.crumbs.go.connect(lambda p: self.go(p))
        self.crumbs.edit.connect(self._crumb_edit)
        self.addr_stack = QtWidgets.QStackedWidget()
        self.addr_stack.addWidget(self.addr)
        self.addr_stack.addWidget(self.crumbs)
        self.addr_stack.setFixedHeight(self.addr.sizeHint().height())
        self.addr_stack.setMinimumWidth(60)
        self.crumbs.setMinimumWidth(0)
        bar.addWidget(self.addr_stack, 1)
        # 빠른 필터 (현재 폴더에서 이름으로 거르기)
        self.filt = QtWidgets.QLineEdit()
        self.filt.setPlaceholderText(T("🔍 필터 (Ctrl+F)"))
        self.filt.setClearButtonEnabled(True)
        self.filt.setMinimumWidth(50)
        self.filt.setMaximumWidth(150)
        self.filt.setToolTip(T("현재 폴더에서 이름에 이 글자가 든 것만 보기 (* ? 와일드카드 가능) · Esc 로 지우기"))
        self.filt.textChanged.connect(self._on_filter)
        self.filt.installEventFilter(self)
        # 평소엔 🔍 버튼만 (주소줄을 넓게) → 누르거나 Ctrl+F 면 필터칸이 펼쳐짐 (10/2 사용자 제안)
        self.btn_find = btn(None, T("빠른 필터 (Ctrl+F)"), self.open_filter, "🔍")
        bar.addWidget(self.filt)
        self.btn_deep = btn(None, T("이 폴더 아래 전부에서 찾기 — 필터 글자로 (필터칸에서 Shift+Enter)"), self.folder_search, "⤵")
        self.filt.setVisible(False)
        self.btn_deep.setVisible(False)
        self.btn_view = btn(None, T("보기 방식·표시 옵션"), None, T("보기"))
        self.btn_view.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        vm = QtWidgets.QMenu(self.btn_view)
        vm.aboutToShow.connect(lambda: self.fill_view_menu(vm))
        self.btn_view.setMenu(vm)
        lay.addWidget(head)

        # ---- 본문: 사이드바 | (탭 줄 + 탭 내용)
        self.body = QtWidgets.QSplitter(Qt.Horizontal)
        self.body.setChildrenCollapsible(False)
        self.body.setHandleWidth(3)
        self.side = None   # 처음 보일 때 생성(가볍게)
        self.side_host = QtWidgets.QWidget()
        self.side_host.setObjectName("sideHost")
        QtWidgets.QVBoxLayout(self.side_host).setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.side_host)

        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        tabrow = QtWidgets.QWidget()
        tabrow.setObjectName("tabRow")
        tl = QtWidgets.QHBoxLayout(tabrow)
        tl.setContentsMargins(4, 3, 4, 0)
        tl.setSpacing(2)
        self.bar = PaneTabBar()
        self.bar.setTabsClosable(True)
        self.bar.setMovable(True)
        self.bar.setExpanding(False)
        self.bar.setDrawBase(False)
        self.bar.setElideMode(Qt.ElideRight)
        self.bar.setUsesScrollButtons(True)
        self.bar.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        tl.addWidget(self.bar)
        tl.addSpacing(36)   # + 버튼 자리(탭이 넘칠 때)
        # + 버튼: 마지막 탭 바로 오른쪽에 붙어 다님 (_place_plus)
        plus = QtWidgets.QToolButton(tabrow)
        plus.setObjectName("plusTab")
        plus.setText("+")
        plus.setToolTip(T("새 탭 (Ctrl+T)"))
        plus.setAutoRaise(True)
        plus.setFixedSize(34, 26)   # 예전 24x22 는 너무 작음 (10/5 사용자 요청)
        plus.clicked.connect(lambda: self.add_tab(self.view().path if self.view() else THIS_PC, focus=True))
        self.plus = plus
        rl.addWidget(tabrow)
        self.stack = QtWidgets.QStackedWidget()
        rl.addWidget(self.stack, 1)
        self.body.addWidget(right)
        self.body.setStretchFactor(1, 1)
        self.body.splitterMoved.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.body, 1)

        self.bar.tabCloseRequested.connect(self.close_tab)
        self.bar.currentChanged.connect(self._on_tab_changed)
        # 탭을 누르면 그 칸이 활성 + 목록에 키보드 포커스 (탭줄은 클릭해도 포커스를 안 가져가 칸이 안 바뀌었음, 10/13 사용자 지적)
        # 바로 하면 탭 바뀜(currentChanged)보다 먼저라 이전 탭 목록에 포커스 → 다음 차례에
        self.bar.tabBarClicked.connect(lambda i: QtCore.QTimer.singleShot(0, self._focus_current))
        self.bar.tabMoved.connect(lambda *_: self.changed.emit())
        self.bar.installEventFilter(self)
        tabrow.installEventFilter(self)
        self.tabrow = tabrow

        self.bar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.bar.customContextMenuRequested.connect(self._tab_menu)

        self.stat = QtWidgets.QLabel()
        self.stat.setObjectName("paneStatus")
        self.stat.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)   # 긴 상태 글자가 창 축소를 막지 않게
        lay.addWidget(self.stat)
        self._prev = None
        self.set_sidebar(False, save=False)
        self.set_breadcrumb(SETTINGS["breadcrumb"])

    # ---------------------------------------------------------- 주소: 경로 버튼(브레드크럼) / 입력칸
    def set_breadcrumb(self, on):
        self.breadcrumb = on
        self.addr_stack.setCurrentWidget(self.crumbs if on else self.addr)

    def _crumb_edit(self):
        self.addr_stack.setCurrentWidget(self.addr)
        self.addr.setFocus()
        self.addr.selectAll()

    def _crumb_back(self):
        if self.breadcrumb:
            self.addr_stack.setCurrentWidget(self.crumbs)

    # ---------------------------------------------------------- 빠른 필터
    def _on_filter(self, text):
        v = self.view()
        if v:
            v.set_filter(text)

    def folder_search(self):
        """필터 글자로 지금 폴더 아래 전부를 바로 훑어 찾기 (색인 없이) → 새 탭"""
        q = self.filt.text().strip()
        v = self.view()
        if not q:
            self.focus_filter()
            self.stat.setText(T("필터칸에 찾을 글자를 쓰고 ⤵ (또는 Shift+Enter)"))
            return
        if not v or v.path == THIS_PC or is_search(v.path):
            self.stat.setText(T("⚠ 폴더 안에서만 쓸 수 있습니다 (내 PC·검색 결과 제외)"))
            return
        folder = v.path
        self.filt.blockSignals(True)
        self.filt.clear()
        self.filt.blockSignals(False)
        v.set_filter("")
        log.info("폴더 아래 찾기 '%s' @ %s", q, folder)
        self.add_tab(search_path(q, folder))

    def focus_filter(self):
        self.open_filter()

    def open_filter(self):
        self.btn_find.setVisible(False)
        self.filt.setVisible(True)
        self.btn_deep.setVisible(True)
        self.filt.setFocus()
        self.filt.selectAll()

    def sync_filter_visibility(self):
        if self.filt.text():
            self.btn_find.setVisible(False)
            self.filt.setVisible(True)
            self.btn_deep.setVisible(True)
        elif not self.filt.hasFocus():
            self.close_filter_if_empty()

    def close_filter_if_empty(self):
        """필터 글자가 없으면 접고 🔍 버튼만 (글자가 있으면 걸려 있다는 걸 보이게 열어 둠)"""
        if self.filt.text():
            return
        self.filt.setVisible(False)
        self.btn_deep.setVisible(False)
        self.btn_find.setVisible(True)

    # ---------------------------------------------------------- 탭줄 우클릭
    def _tab_menu(self, pos):
        i = self.bar.tabAt(pos)
        m = QtWidgets.QMenu(self)
        m.addAction(mlabel(T("새 탭"), "new_tab"), lambda: self.add_tab(self.view().path if self.view() else THIS_PC))
        if i >= 0:
            m.addAction(mlabel(T("이 탭 닫기"), "close_tab"), lambda: self.close_tab(i))

            def close_others():
                keep = self.bar.tabData(i)
                for j in reversed(range(self.bar.count())):
                    if self.bar.tabData(j) != keep:
                        self.close_tab(j)
            m.addAction(T("다른 탭 모두 닫기"), close_others)
        main = main_of(self)
        if main is not None and i >= 0:
            m.addSeparator()
            tp = self.pages[self.bar.tabData(i)].path
            m.addAction(T("새 창으로 열기"), lambda: main.open_window(tp))
            a = m.addAction(T("새 창으로 열기 (윈도우 탐색기)"), lambda: open_in_explorer(tp))
            a.setEnabled(not is_search(tp))   # 검색 결과는 탐색기로 못 엶
        if main is not None:
            m.addSeparator()
            rec = m.addMenu(T("최근 닫은 탭 (Ctrl+Shift+T)"))
            if not main.closed_tabs:
                a = rec.addAction(T("(없음)"))
                a.setEnabled(False)
            for k, (pidx, p) in enumerate(reversed(main.closed_tabs)):
                rec.addAction(f"{tab_title(p)}   —   {p}", lambda k=k: main.reopen_tab(len(main.closed_tabs) - 1 - k, self))
        m.exec(self.bar.mapToGlobal(pos))

    # ---------------------------------------------------------- 탭
    def view(self):
        return self.stack.currentWidget()

    def views(self):
        return [self.pages[self.bar.tabData(i)] for i in range(self.bar.count())]

    def add_tab(self, path, activate=True, focus=False):
        v = Page(path, self.mode)
        key = id(v)
        self.pages[key] = v
        v.pathChanged.connect(lambda p, v=v: self._on_path(v, p))
        v.status.connect(lambda s, v=v: v is self.view() and (self.stat.setText(s), self.stat.setToolTip(getattr(v, "status_tip", ""))))
        v.status.connect(lambda s, v=v: v is self.view() and self._poke_preview())   # 선택·폴더가 바뀌면 상태 글자가 바뀜 (v0.9.58)
        v.openInNewTab.connect(lambda p: self.add_tab(p, activate=False))
        hd = v.tree.header()   # 정렬·열 너비가 바뀌면 상태 저장 예약(2초 뒤 한 번)
        hd.sortIndicatorChanged.connect(lambda *_: self.changed.emit())
        hd.sectionResized.connect(lambda *_: self.changed.emit())
        self.stack.addWidget(v)
        i = self.bar.addTab(tab_title(v.path))
        self.bar.setTabData(i, key)
        self.bar.setTabToolTip(i, disp_path(v.path))
        if activate or self.bar.count() == 1:
            self.bar.setCurrentIndex(i)
            self._on_tab_changed(i)
        if focus:   # + 버튼·Ctrl+T: 바로 새 탭 목록에서 방향키·Enter
            v.tree.setFocus(Qt.OtherFocusReason)
        log.info("탭 추가 pane=%d path=%s (탭 %d개)", self.idx, v.path, self.bar.count())
        self.changed.emit()
        return v

    def tab_drag(self, key, press):
        """탭을 마우스에 붙여 끌기. 놓은 곳(커서 위치)으로 판단: 다른 칸 → 그 칸으로 옮김, 4Dir 창 밖 → 새 창"""
        if key not in self.pages:
            return
        i = next((k for k in range(self.bar.count()) if self.bar.tabData(k) == key), -1)
        if i < 0:
            return
        # QTabBar 자체 '순서 바꾸기 끌기'를 끝냄 (안 하면 탭이 떠 있는 채로 남음)
        gp = self.bar.mapToGlobal(press)
        QtWidgets.QApplication.sendEvent(self.bar, QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease, QtCore.QPointF(press), QtCore.QPointF(gp), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        i = next((k for k in range(self.bar.count()) if self.bar.tabData(k) == key), i)
        pm = self._tab_image(i)
        img = QtGui.QPixmap(pm.size())
        img.setDevicePixelRatio(pm.devicePixelRatio())
        img.fill(Qt.transparent)
        p = QtGui.QPainter(img)
        p.setOpacity(0.85)
        p.drawPixmap(0, 0, pm)
        p.end()
        md = QtCore.QMimeData()
        md.setData(TAB_MIME, str(key).encode())
        drag = QtGui.QDrag(self.bar)
        drag.setMimeData(md)
        drag.setPixmap(img)
        drag.setHotSpot(QtCore.QPoint(min(30, img.width() // 2), img.height() // 2))
        log.info("탭 끌기 시작 pane=%d %s", self.idx, self.pages[key].path)
        tm = QtCore.QTimer()
        tm.setInterval(40)   # 끄는 동안만 (끝나면 멈춤) — 커서 옆 안내
        tm.timeout.connect(lambda: self._tab_drag_hint(key))
        tm.start()
        try:
            drag.exec(Qt.MoveAction)
        finally:
            tm.stop()
            drop_hint(None)
        self.finish_tab_drop(key, QtGui.QCursor.pos())

    def _tab_image(self, i):
        """끌 때 마우스에 붙는 탭 그림. 탭줄을 그대로 찍으면 QTabBar 가 옮기던 탭이 비켜 그려져 왼쪽 빈칸·잘림(10/6 사용자 보고)
        → 같은 모양 탭줄을 따로 하나 만들어 그 탭만 그림"""
        tmp = PaneTabBar(self.tabrow)   # 같은 부모 = 같은 스타일 (닫기 단추 위치도 같게)
        tmp.setDrawBase(False)
        tmp.setExpanding(False)   # 진짜 탭줄과 같게 (안 하면 탭 옆에 빈 회색 칸이 붙음 — 실측 100px vs 80px)
        tmp.setTabsClosable(self.bar.tabsClosable())
        tmp.setFont(self.bar.font())
        tmp.addTab(self.bar.tabIcon(i), self.bar.tabText(i))
        tmp.setCurrentIndex(0)
        tmp.resize(tmp.sizeHint())
        pm = tmp.grab(tmp.tabRect(0))
        tmp.deleteLater()
        return pm

    def _tab_target(self, gpos):
        """('pane', 칸, 탭줄 끼울 자리) | ('new', None, None) 4Dir 창 밖 | ('none', ...) 4Dir 창 안의 다른 곳·같은 칸"""
        w = QtWidgets.QApplication.widgetAt(gpos)
        if w is DROP_HINT:
            w = None
        x = w
        while x is not None and not isinstance(x, Pane):
            x = x.parentWidget()
        if x is not None and isinstance(x.window(), Main):
            if x is self:
                return ("none", None, None)
            at = x.bar.tabAt(x.bar.mapFromGlobal(gpos))
            return ("pane", x, at)
        if w is not None and isinstance(w.window(), Main):
            return ("none", None, None)
        if any(m.isVisible() and m.frameGeometry().contains(gpos) for m in WINDOWS):
            return ("none", None, None)
        return ("new", None, None)

    def _tab_drag_hint(self, key):
        gp = QtGui.QCursor.pos()
        kind, tgt, _ = self._tab_target(gp)
        if kind == "new":
            drop_hint(T("＋ 새 창으로 열기"), gp)
        elif kind == "pane":
            main = main_of(tgt)
            same = main is main_of(self)
            drop_hint((T("→ 칸 {0} 에 탭 추가").format(tgt.idx + 1) if same else T("→ 다른 창의 칸 {0} 에 탭 추가").format(tgt.idx + 1)), gp)
        else:
            drop_hint(None)

    def finish_tab_drop(self, key, gpos):
        kind, tgt, at = self._tab_target(gpos)
        v = self.pages.get(key)
        if v is None:
            return
        log.info("탭 놓기 pane=%d %s → %s", self.idx, v.path, kind if kind != "pane" else f"칸 {tgt.idx}")
        if kind == "new":
            return self.tear_off(key, gpos)
        if kind != "pane":
            return
        nv = tgt.add_tab(v.path, activate=True)
        if 0 <= at < tgt.bar.count() - 1:
            tgt.bar.moveTab(tgt.bar.count() - 1, at)
        main = main_of(tgt)
        if main is not None:
            main.active_pane = tgt
            main._paint_active()
            main.activateWindow()
        nv.view().setFocus()
        for i in range(self.bar.count()):
            if self.bar.tabData(i) == key and self.bar.count() > 1:   # 칸의 마지막 탭이면 남김
                self.close_tab(i)
                break
        tgt.changed.emit()
        return nv

    def tear_off(self, key, gpos):
        """탭을 창 밖에 놓음 → 그 폴더로 새 창(놓은 자리), 원래 탭은 닫음(칸의 마지막 탭이면 남김)"""
        main = main_of(self)
        v = self.pages.get(key)
        if main is None or v is None:
            return
        log.info("탭 끌어내기 → 새 창 pane=%d %s at %s", self.idx, v.path, gpos.toTuple())
        w = main.open_window(v.path)
        w.move(gpos.x() - 60, gpos.y() - 15)
        for i in range(self.bar.count()):
            if self.bar.tabData(i) == key and self.bar.count() > 1:
                self.close_tab(i)
                break
        return w

    def close_tab(self, i):
        if self.bar.count() <= 1:
            return  # 칸마다 최소 1개
        key = self.bar.tabData(i)
        v = self.pages.pop(key)
        v.set_active(False)
        v.cancel_jobs()   # 진행 중인 폴더 아래 찾기 멈춤
        self.bar.removeTab(i)
        self.stack.removeWidget(v)
        log.info("탭 닫기 pane=%d path=%s", self.idx, v.path)
        main = main_of(self)
        if main is not None:
            main.closed_tabs.append((self.idx, v.path))   # Ctrl+Shift+T 로 다시 열기
            del main.closed_tabs[:-20]
        v.deleteLater()
        self._on_tab_changed(self.bar.currentIndex())
        self.changed.emit()

    def close_all(self):
        for v in self.views():
            v.set_active(False)
            self.stack.removeWidget(v)
            v.deleteLater()
        self.pages.clear()
        self._prev = None
        while self.bar.count():
            self.bar.removeTab(0)

    def _on_path(self, v, p):
        for i in range(self.bar.count()):
            if self.bar.tabData(i) == id(v):
                self.bar.setTabText(i, tab_title(p))
                self.bar.setTabToolTip(i, disp_path(p))
                self.bar.updateGeometry()
        if v is self.view():
            self.addr.setText(disp_path(p))
            self.crumbs.set_path(p)
            self.sync_sidebar()
            if self.filt.text():
                self.filt.blockSignals(True)
                self.filt.clear()   # 다른 폴더로 가면 필터 해제 (Page.navigate 도 비움)
                self.filt.blockSignals(False)
            self.close_filter_if_empty()   # 폴더를 옮기면 필터칸에 커서가 있어도 접음
        self.changed.emit()

    def _focus_current(self):
        v = self.view()
        if v is not None:
            v.view().setFocus(Qt.MouseFocusReason)

    def _on_tab_changed(self, i):
        # 탭 추가·닫기·바꾸기 뒤 탭줄 크기 다시 계산 — 안 하면 가끔 탭줄 높이가 0으로 남아 탭이 사라짐
        # (10/6 사용자 보고, 저장 상태로 열 때 재현: 탭 2개+두 번째가 현재 탭인 칸, updateGeometry 로 23px 복구 실측)
        self.bar.updateGeometry()
        if i < 0 or self.bar.tabData(i) not in self.pages:
            return
        v = self.pages[self.bar.tabData(i)]
        if self._prev is not None and self._prev is not v:
            try:
                self._prev.set_active(False)
            except RuntimeError:
                pass
        self.stack.setCurrentWidget(v)
        self._prev = v
        self.addr.setText(disp_path(v.path))
        self.crumbs.set_path(v.path)
        self.sync_sidebar()
        self.filt.blockSignals(True)
        self.filt.setText(v.model_.filter)   # 탭마다 자기 필터
        self.filt.blockSignals(False)
        self.sync_filter_visibility()
        v.set_active(self.shown)
        v._emit_status()
        self.changed.emit()

    def set_shown(self, on):
        self.shown = on
        if self.view():
            self.view().set_active(on)

    def _addr_go(self):
        t = os.path.expandvars(self.addr.text().strip().strip('"'))
        v = self.view()
        if not v:
            return
        if not t or t in (THIS_PC, T(THIS_PC)):
            v.navigate(THIS_PC)
        elif os.path.isfile(t):
            v.navigate(os.path.dirname(t), select=os.path.basename(t))
        else:
            v.navigate(t)
        self._crumb_back()
        v.view().setFocus()

    def go(self, path, new_tab=False):
        if new_tab:
            self.add_tab(path)
        elif self.view():
            self.view().navigate(path)
            self.view().view().setFocus()

    def _place_plus(self):
        n = self.bar.count()
        if not n:
            return
        r = self.bar.tabRect(n - 1)
        x = self.bar.mapTo(self.tabrow, r.topRight()).x() + 3
        x = min(x, self.tabrow.width() - self.plus.width() - 2)
        y = self.bar.mapTo(self.tabrow, r.topLeft()).y() + (r.height() - self.plus.height()) // 2
        self.plus.move(x, max(y, 0))
        self.plus.raise_()

    def eventFilter(self, obj, ev):
        if not (hasattr(self, "filt") and hasattr(self, "bar") and hasattr(self, "tabrow")):   # 만드는 중에 불린 이벤트
            return super().eventFilter(obj, ev)
        if (obj is self.filt and ev.type() == QtCore.QEvent.KeyPress and ev.key() in (Qt.Key_Return, Qt.Key_Enter)
                and ev.modifiers() & Qt.ShiftModifier):
            self.folder_search()
            return True
        if obj is self.filt and ev.type() == QtCore.QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.filt.clear()
            self.close_filter_if_empty()
            if self.view():
                self.view().view().setFocus()
            return True
        if obj is self.filt and ev.type() == QtCore.QEvent.FocusOut:
            # ⤵ 버튼을 누르러 가는 중이면 닫지 않음 (글자가 없으면 ⤵ 도 할 일이 없으니 그냥 닫힘)
            QtCore.QTimer.singleShot(0, self.close_filter_if_empty)
        if obj is self.addr:
            # 처음 클릭 = 경로 전체 선택 (탐색기와 같음). 이미 입력 중이면 보통 클릭(커서 위치 이동).
            # Qt 는 누름 이벤트 전에 포커스부터 줌(실측) → '클릭으로 포커스가 들어옴'을 표시해 두고 바로 다음 누름에서 전체 선택
            if ev.type() == QtCore.QEvent.FocusIn and ev.reason() == Qt.MouseFocusReason:
                self._addr_first_click = True
            elif ev.type() == QtCore.QEvent.MouseButtonPress and getattr(self, "_addr_first_click", False):
                self._addr_first_click = False
                if ev.button() == Qt.LeftButton:
                    self.addr.selectAll()
                    return True
            elif ev.type() == QtCore.QEvent.FocusOut:
                self._addr_first_click = False
            if ev.type() == QtCore.QEvent.KeyPress and ev.key() == Qt.Key_Escape:
                self.addr.setText(disp_path(self.view().path) if self.view() else "")
                self._crumb_back()
                if self.view():
                    self.view().view().setFocus()
                return True
            if ev.type() == QtCore.QEvent.FocusOut:
                QtCore.QTimer.singleShot(0, self._crumb_back)
        # 탭 추가·닫기·이동·글자 변경·크기 변경 모두 탭줄 다시 그리기로 이어짐 → 그때 + 위치 맞춤(같은 위치면 아무 일 없음)
        if obj is self.bar and ev.type() == QtCore.QEvent.Paint:
            self._place_plus()
        # 탭 끌기 (윈도우 탐색기처럼): 탭줄 안 좌우 = 순서 바꾸기(QTabBar), 위아래로 벗어나면 탭이 마우스에 붙어 다님
        #   → 다른 칸에 놓기 = 그 칸에 탭 추가 / 4Dir 창 밖에 놓기 = 새 창 / 커서 옆에 어떻게 될지 안내
        if obj is self.bar and ev.type() == QtCore.QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            i = self.bar.tabAt(ev.position().toPoint())
            self._tear = (self.bar.tabData(i), ev.position().toPoint()) if i >= 0 else None
        elif obj is self.bar and ev.type() == QtCore.QEvent.MouseMove and getattr(self, "_tear", None) and ev.buttons() & Qt.LeftButton:
            # 탭줄을 위아래로 벗어나거나, 좌우로 탭줄 끝을 넘어가면(다른 창·화면 밖으로 바로 끌 때) 탭이 떨어짐 (10/6 사용자: 탭줄 높이로 옆 창에 끌면 순서만 바뀜)
            pt = ev.position().toPoint()
            if not self.bar.rect().adjusted(-TAB_DETACH, -TAB_DETACH, TAB_DETACH, TAB_DETACH).contains(pt):
                key, press = self._tear
                self._tear = None
                QtCore.QTimer.singleShot(0, lambda k=key, p=press: self.tab_drag(k, p))
                return True
        elif obj is self.bar and ev.type() == QtCore.QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
            self._tear = None
        if obj is self.bar and ev.type() == QtCore.QEvent.MouseButtonRelease and ev.button() == Qt.MiddleButton:
            i = self.bar.tabAt(ev.position().toPoint())
            if i >= 0:
                self.close_tab(i)
                return True
        if ev.type() == QtCore.QEvent.MouseButtonDblClick and (obj is self.tabrow or (obj is self.bar and self.bar.tabAt(ev.position().toPoint()) < 0)):
            self.add_tab(self.view().path if self.view() else THIS_PC)
            return True
        return super().eventFilter(obj, ev)

    # ---------------------------------------------------------- 보기
    def set_mode(self, mode):
        self.mode = mode
        for v in self.views():
            v.set_mode(mode)
        log.info("보기 방식 pane=%d %s", self.idx, mode)
        self.changed.emit()

    def _poke_preview(self):
        m = main_of(self)
        if m is not None and getattr(m, "preview", None) is not None and m.active_pane is self:
            m.preview.schedule()

    def fill_view_menu(self, m):
        m.clear()
        g = QtGui.QActionGroup(m)
        for k, lbl, _ in VIEW_MODES:
            a = m.addAction(lbl, lambda k=k: self.set_mode(k))
            a.setCheckable(True)
            a.setChecked(self.mode == k)
            g.addAction(a)
        m.addSeparator()
        self.fill_sort_menu(m.addMenu(T("정렬 기준")))
        show = m.addMenu(T("표시"))
        a = show.addAction(T("탐색 창"), lambda: self.toggle_sidebar())
        a.setCheckable(True)
        a.setChecked(self.side_host.isVisible())
        main = main_of(self)
        a = show.addAction(T("경로를 버튼으로 (브레드크럼)"), lambda: main.toggle_breadcrumb() if main is not None else None)
        a.setCheckable(True)
        a.setChecked(SETTINGS["breadcrumb"])
        for key, lbl in (("checkboxes", T("항목 확인란")), ("show_ext", T("파일 확장명")), ("show_hidden", T("숨긴 항목")),
                         ("date_folders_first", T("날짜 정렬 때 폴더를 위로 모으기")),
                         ("svn_status", T("SVN 상태 표시")),
                         ("thumbnails", T("그림 미리보기 (아이콘 보기)")),
                         ("vcs_overlay", T("버전 관리 표시 — Git·Perforce 등 (윈도우 겹침 아이콘)"))):
            a = show.addAction(lbl, lambda key=key: main.toggle_opt(key) if main is not None else None)
            a.setCheckable(True)
            a.setChecked(OPTS[key])

    def fill_sort_menu(self, m):
        m.clear()
        v = self.view()
        cur = v.model_.sort_col if v else 0
        order = v.model_.sort_order if v else Qt.AscendingOrder
        g = QtGui.QActionGroup(m)
        for c, lbl in SORT_COLS:
            a = m.addAction(lbl, lambda c=c: v and v.set_sort(c, v.model_.sort_order))
            a.setCheckable(True)
            a.setChecked(c == cur)
            g.addAction(a)
        m.addSeparator()
        g2 = QtGui.QActionGroup(m)
        for o, lbl in ((Qt.AscendingOrder, T("오름차순")), (Qt.DescendingOrder, T("내림차순"))):
            a = m.addAction(lbl, lambda o=o: v and v.set_sort(v.model_.sort_col, o))
            a.setCheckable(True)
            a.setChecked(o == order)
            g2.addAction(a)

    # ---------------------------------------------------------- 사이드바
    def sync_sidebar(self):
        """왼쪽 탐색 창을 지금 폴더까지 펼치고 선택 (탐색기의 '현재 폴더까지 확장'과 같음, 10/2 사용자 요청)"""
        if self.side is not None and self.side_host.isVisible() and self.view() is not None:
            self.side.reveal(self.view().path)

    def set_sidebar(self, on, save=True):
        if on and self.side is None:
            self.side = Sidebar()
            self.side.go.connect(lambda p: self.go(p))
            self.side.goNewTab.connect(lambda p: self.go(p, new_tab=True))
            self.side_host.layout().addWidget(self.side)
        self.side_host.setVisible(on)
        if on and self.body.sizes()[0] < 60:
            total = sum(self.body.sizes()) or 800
            self.body.setSizes([200, max(total - 200, 200)])
        self.btn_side.setChecked(on)
        if on:
            self.sync_sidebar()
        if save:
            log.info("탐색 창 pane=%d %s", self.idx, on)
            self.changed.emit()

    def toggle_sidebar(self):
        self.set_sidebar(not self.side_host.isVisible())

    def state(self):
        return {"tabs": [v.path for v in self.views()], "current": self.bar.currentIndex(), "mode": self.mode,
                "sidebar": self.side_host.isVisible(), "body": self.body.sizes(),
                "views": [v.view_state() for v in self.views()]}   # 탭별 정렬·열 너비 (v0.7.1)


# ================================================================ 즐겨찾기 패널 (여러 줄 줄바꿈, 접기/펼치기 — 칸을 아래로 밀어내므로 겹치지 않음)
FAV_MIME = "application/x-qe-fav"
TAB_MIME = "application/x-4dir-tab"
TAB_DETACH = 25   # 탭을 탭줄 위아래로 이만큼(px) 벗어나게 끌면 탭이 떨어져 마우스에 붙음


class FavPanel(QtWidgets.QFrame):
    """상단 즐겨찾기 바. 버튼 = 낱개 즐겨찾기 또는 묶음(눌러서 목록). 버튼마다 favStart/favEnd = FAV.items 구간"""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("favPanel")
        self.setAcceptDrops(True)
        self._press = None
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 4, 2)
        lay.setSpacing(4)
        lbl = QtWidgets.QLabel(T("즐겨찾기"))
        lbl.setObjectName("favLabel")
        lbl.setFixedHeight(25)   # 버튼 한 줄 높이와 맞춤
        lbl.setContextMenuPolicy(Qt.CustomContextMenu)
        lbl.customContextMenuRequested.connect(lambda _p: self._bar_menu(QtGui.QCursor.pos()))
        lay.addWidget(lbl, 0, Qt.AlignTop)
        self.box = QtWidgets.QWidget()
        self.box.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)   # 창 가로 축소를 막지 않게
        self.box.setContextMenuPolicy(Qt.CustomContextMenu)
        self.box.customContextMenuRequested.connect(lambda _p: self._bar_menu(QtGui.QCursor.pos()))
        self.flow = ui_parts.FlowLayout(self.box, spacing=2)
        lay.addWidget(self.box, 1)
        self.btn_fold = QtWidgets.QToolButton()
        self.btn_fold.setAutoRaise(True)
        self.btn_fold.clicked.connect(self.toggle)
        lay.addWidget(self.btn_fold, 0, Qt.AlignTop)
        self.buttons = []
        self.svn = {}   # 즐겨찾기 경로 → SVN 상태 (FavSvnJob)
        self._svn_sig = FavSvnSig(self)
        self._svn_sig.done.connect(self._svn_apply)
        self._svn_timer = QtCore.QTimer(self)
        self._svn_timer.setSingleShot(True)
        self._svn_timer.setInterval(400)   # 실시간 변경이 몰려도 한 번만
        self._svn_timer.timeout.connect(self._svn_start)
        SVN_SIG.changed.connect(self._svn_changed)
        FAV.listeners.append(self.rebuild)
        self.rebuild()
        self.set_expanded(SETTINGS["fav_expanded"], save=False)

    def fav_buttons(self):
        return [b for b in self.buttons if b.property("favStart") is not None]

    def rebuild(self):
        try:
            for b in self.buttons:
                self.flow.removeWidget(b)
                b.hide()          # deleteLater 는 나중에 지워져 그 사이 새 버튼과 겹쳐 보임(첫 즐겨찾기 추가 때 안내 글자 겹침 실측)
                b.deleteLater()
        except RuntimeError:
            return
        self.buttons = []
        icon = shellops.icon_for("", True, 16)
        for start, end, group in FAV.entries():
            b = QtWidgets.QToolButton(self.box)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setAutoRaise(True)
            b.setProperty("favStart", start)
            b.setProperty("favEnd", end)
            if group:
                b.setIcon(favorg.group_icon(16))
                b.setText(f"{group} ▾")
                b.setProperty("favGroup", group)
                b.setToolTip(T('묶음 {0} ({1}개)\n클릭: 목록 · 끌어서 순서 변경 · 우클릭: 즐겨찾기 정리').format(group, end - start))
                b.clicked.connect(lambda _=False, b=b: self._group_popup(b))
            else:
                d = FAV.items[start]
                b.setIcon(self._fav_icon(icon, self.svn.get(d["path"])))
                b.setText(d["name"])
                b.setProperty("favIndex", start)
                b.setToolTip(T('{0}\n클릭: 선택된 칸에서 열기 · Ctrl+클릭: 새 탭 · 끌어서 순서 변경 · 우클릭: 이름/삭제').format(d['path']))
                b.clicked.connect(lambda _=False, p=d["path"]: self.main.open_fav(p))
            b.installEventFilter(self)
            self.flow.addWidget(b)
            self.buttons.append(b)
        if not FAV.items:
            b = QtWidgets.QLabel(T("  폴더를 여기로 끌어다 놓기 · 우클릭 > ★ 4Dir 즐겨찾기에 추가 · Ctrl+D"))
            b.setStyleSheet("color:#8a939c;")
            self.flow.addWidget(b)
            self.buttons.append(b)
        self._apply_height()
        self._svn_timer.start()

    # ---------------------------------------------------------- SVN 표시 (탐색기 즐겨찾기처럼, 10/19)
    def _fav_icon(self, base, st):
        if not st or not OPTS["svn_status"]:
            return base
        dpr = self.devicePixelRatioF() or 1.0
        pm = QtGui.QPixmap(int(16 * dpr), int(16 * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        base.paint(p, QtCore.QRect(0, 0, 16, 16))
        paint_svn_badge(p, QtCore.QRect(0, 0, 16, 16), QtCore.QRect(0, 0, 16, 16), st)
        p.end()
        return QtGui.QIcon(pm)

    def _svn_start(self):
        if not OPTS["svn_status"]:
            if self.svn:
                self._svn_apply({}, force=True)
            return
        paths = [d["path"] for d in FAV.items]
        if paths:
            POOL.start(FavSvnJob(paths, self._svn_sig.done))

    def _svn_changed(self, root):
        rc = os.path.normcase(root)
        if any(os.path.normcase(d["path"]).startswith(rc) for d in FAV.items):
            self._svn_timer.start()

    def _svn_apply(self, st, force=False):
        if not force and st == self.svn and all(b.property("svnDone") for b in self.fav_buttons() if b.property("favIndex") is not None):
            return
        self.svn = st
        icon = shellops.icon_for("", True, 16)
        for b in self.fav_buttons():
            i = b.property("favIndex")
            if i is not None and i < len(FAV.items):
                b.setIcon(self._fav_icon(icon, st.get(FAV.items[i]["path"])))
                b.setProperty("svnDone", True)
        log.info("즐겨찾기 SVN 표시 %d개 %s", len(st), {os.path.basename(k.rstrip("\\\\")): v for k, v in list(st.items())[:6]})

    def _group_popup(self, b):
        g = b.property("favGroup")
        m = QtWidgets.QMenu(self)
        icon = shellops.icon_for("", True, 16)
        for d in FAV.items[b.property("favStart"):b.property("favEnd")]:
            a = m.addAction(self._fav_icon(icon, self.svn.get(d["path"])), d["name"])
            a.setToolTip(d["path"])
            a.triggered.connect(lambda _=False, p=d["path"]: self.main.open_fav(p))
        m.setToolTipsVisible(True)
        m.addSeparator()
        m.addAction(T("즐겨찾기 정리…"), lambda: self.main.open_fav_organizer(select_group=g))
        log.info("즐겨찾기 묶음 열기 %s", g)
        m.exec(b.mapToGlobal(QtCore.QPoint(0, b.height())))
        b.setDown(False)

    # ---------------------------------------------------------- 접기/펼치기
    def set_expanded(self, on, save=True):
        self.expanded = on
        self.btn_fold.setText("▲" if on else "▼")
        self.btn_fold.setToolTip(T("즐겨찾기 접기 (한 줄만)") if on else T("즐겨찾기 펼치기 (전부 보기)"))
        self._apply_height()
        if save:
            SETTINGS["fav_expanded"] = on
            log.info("즐겨찾기 바 %s", "펼침" if on else "접힘")

    def toggle(self):
        self.set_expanded(not self.expanded)

    def _apply_height(self):
        if not hasattr(self, "expanded"):
            return
        one = self.flow.row_height()
        if self.expanded:
            self.box.setMaximumHeight(16777215)
            self.box.setMinimumHeight(self.flow.heightForWidth(max(self.box.width(), 200)))
        else:
            self.box.setMinimumHeight(one)
            self.box.setMaximumHeight(one)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.expanded:
            h = self.flow.heightForWidth(self.box.width())
            if h != self.box.minimumHeight():
                self.box.setMinimumHeight(h)

    # ---------------------------------------------------------- 끌어서 순서 변경 / 폴더 끌어다 추가
    def _index_at(self, pt):
        """패널 좌표 pt → 끼워 넣을 즐겨찾기 자리(FAV.items 번호, 여러 줄 고려)"""
        p = self.box.mapFrom(self, pt)
        for b in self.fav_buttons():
            g = b.geometry()
            if p.y() < g.top():
                return b.property("favStart")
            if g.top() <= p.y() <= g.bottom() and p.x() < g.center().x():
                return b.property("favStart")
        return len(FAV.items)

    def eventFilter(self, obj, ev):
        start = obj.property("favStart") if isinstance(obj, QtWidgets.QWidget) else None
        if start is not None:
            t = ev.type()
            if t == QtCore.QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
                self._press = (obj, ev.position().toPoint())
            elif t == QtCore.QEvent.MouseMove and self._press and self._press[0] is obj \
                    and (ev.position().toPoint() - self._press[1]).manhattanLength() > 8:
                md = QtCore.QMimeData()
                md.setData(FAV_MIME, f"{obj.property('favStart')}:{obj.property('favEnd')}".encode())
                drag = QtGui.QDrag(obj)
                drag.setMimeData(md)
                drag.setPixmap(obj.grab())
                self._press = None
                obj.setDown(False)
                log.info("즐겨찾기 끌기 시작 [%s:%s] %s", obj.property("favStart"), obj.property("favEnd"), obj.text())
                r = drag.exec(Qt.MoveAction)
                log.info("즐겨찾기 끌기 끝 결과=%s", r)
                return True
            elif t == QtCore.QEvent.MouseButtonRelease:
                self._press = None
            elif t == QtCore.QEvent.ContextMenu:
                if obj.property("favGroup"):
                    self._bar_menu(ev.globalPos(), group=obj.property("favGroup"))
                else:
                    self._fav_menu(start, ev.globalPos())
                return True
        return super().eventFilter(obj, ev)

    def _bar_menu(self, pos, group=None):
        """즐겨찾기 바 빈 곳·묶음 버튼 우클릭"""
        m = QtWidgets.QMenu(self)
        m.addAction(T("즐겨찾기 정리…"), lambda: self.main.open_fav_organizer(select_group=group))
        m.exec(pos)

    def _fav_menu(self, i, pos):
        d = FAV.items[i]
        m = QtWidgets.QMenu(self)
        m.addAction(T("선택된 칸에서 열기"), lambda: self.main.open_fav(d["path"]))
        m.addAction(T("새 탭에서 열기"), lambda: self.main.pane().go(d["path"], new_tab=True))
        m.addSeparator()

        def rename():
            t, ok = QtWidgets.QInputDialog.getText(self, T("즐겨찾기 이름 바꾸기"), T("이름:"), text=d["name"])
            if ok and t.strip():
                FAV.rename(i, t.strip())
        m.addAction(T("이름 바꾸기"), rename)
        m.addAction(T("삭제"), lambda: FAV.remove(i))
        m.addSeparator()
        m.addAction(T("즐겨찾기 정리…"), lambda: self.main.open_fav_organizer())
        m.exec(pos)

    # 끌어 놓을 자리 표시 (윈도우 탐색기처럼): 즐겨찾기 가운데 = 그 폴더(묶음) 안으로(진하게), 가장자리·사이 = 끼워 넣기(파란 세로줄)
    def _drop_spot(self, ev):
        """('into', 버튼) | ('gap', FAV.items 자리) | None"""
        md = ev.mimeData()
        p = self.box.mapFrom(self, ev.position().toPoint())
        fav = md.hasFormat(FAV_MIME)
        if not fav and not md.hasUrls():
            return None
        has_dir = fav or any(os.path.isdir(u.toLocalFile()) for u in md.urls() if u.isLocalFile())
        for b in self.fav_buttons():
            if not b.geometry().contains(p):
                continue
            g = b.geometry()
            x = p.x() - g.left()
            if not fav and g.width() * 0.25 <= x <= g.width() * 0.75:
                if b.property("favGroup"):
                    if has_dir:
                        return ("into", b)   # 폴더 → 그 묶음에 추가
                elif os.path.isdir(FAV.items[b.property("favStart")]["path"]):
                    return ("into", b)
            if not has_dir:
                return None   # 파일만 → 즐겨찾기에 못 넣음 (가장자리·사이)
            return ("gap", b.property("favStart") if x < g.width() / 2 else b.property("favEnd"))
        if not has_dir:
            return None
        return ("gap", self._index_at(ev.position().toPoint()))

    def _show_spot(self, spot, ev=None):
        t = SETTINGS[SETTINGS.theme_key()]
        col = ui_parts.qcolor(t.get("sel_border", "#3f94dcff")).name()
        sel = ui_parts.qcolor(t.get("sel", "#cce8ffff")).name()
        for b in self.fav_buttons():
            want = bool(spot and spot[0] == "into" and b is spot[1])
            if bool(b.property("dropInto")) != want:
                b.setProperty("dropInto", want)
                b.setStyleSheet(f"QToolButton{{background:{sel}; border:2px solid {col}; border-radius:3px;}}" if want else "")
        if not hasattr(self, "_line"):
            self._line = QtWidgets.QFrame(self.box)
            self._line.setFixedWidth(3)
        if spot and spot[0] == "gap":
            btns = self.fav_buttons()
            if btns:
                after = [b for b in btns if b.property("favStart") >= spot[1]]
                if after:
                    g = after[0].geometry()
                    x = g.left() - 3
                else:
                    g = btns[-1].geometry()
                    x = g.right() + 1
                self._line.setGeometry(max(0, x), g.top(), 3, g.height())
            else:
                self._line.setGeometry(0, 0, 3, self.flow.row_height())
            self._line.setStyleSheet(f"background:{col}; border-radius:1px;")
            self._line.show()
            self._line.raise_()
        else:
            self._line.hide()
        # 커서 옆 안내
        if ev is None or not spot or ev.mimeData().hasFormat(FAV_MIME):
            drop_hint(None)
        elif spot[0] == "into":
            b = spot[1]
            if b.property("favGroup"):
                drop_hint(T("↗ 묶음 {0} 에 추가").format(b.property("favGroup")), self.mapToGlobal(ev.position().toPoint()))
            else:
                d = FAV.items[b.property("favStart")]
                fmt = T("→ {0}(으)로 이동") if self._drop_action(ev, d["path"]) == Qt.MoveAction else T("→ {0}(으)로 복사")
                drop_hint(fmt.format(d["name"]), self.mapToGlobal(ev.position().toPoint()))
        else:
            drop_hint(T("↗ 즐겨찾기에 추가"), self.mapToGlobal(ev.position().toPoint()))

    @staticmethod
    def _drop_action(ev, tgt):
        m = ev.modifiers()
        if m & Qt.ControlModifier:
            return Qt.CopyAction
        if m & Qt.ShiftModifier:
            return Qt.MoveAction
        srcs = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        same = srcs and os.path.splitdrive(srcs[0])[0].lower() == os.path.splitdrive(tgt)[0].lower()
        return Qt.MoveAction if same else Qt.CopyAction

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(FAV_MIME) or ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        spot = self._drop_spot(ev)
        self._show_spot(spot, ev)
        if spot is None:
            ev.ignore()
            return
        if spot[0] == "into" and not spot[1].property("favGroup"):
            ev.setDropAction(self._drop_action(ev, FAV.items[spot[1].property("favStart")]["path"]))
        else:
            ev.setDropAction(Qt.MoveAction if ev.mimeData().hasFormat(FAV_MIME) else Qt.LinkAction
                             if ev.possibleActions() & Qt.LinkAction else Qt.CopyAction)
        ev.accept()

    def dragLeaveEvent(self, ev):
        self._show_spot(None)
        super().dragLeaveEvent(ev)

    def dropEvent(self, ev):
        spot = self._drop_spot(ev)
        self._show_spot(None)
        md = ev.mimeData()
        log.info("즐겨찾기 바에 놓기 spot=%s 순서바꾸기=%s", (spot[0], spot[1] if spot and spot[0] == "gap" else spot and spot[1].text()) if spot else None,
                 md.hasFormat(FAV_MIME))
        if spot and spot[0] == "into" and spot[1].property("favGroup"):
            g = spot[1].property("favGroup")
            for u in md.urls():
                p = u.toLocalFile()
                if p and os.path.isdir(p):
                    FAV.add(p, group=g)
            ev.setDropAction(Qt.CopyAction)
            ev.accept()
            return
        if spot and spot[0] == "into":
            tgt = FAV.items[spot[1].property("favStart")]["path"]
            srcs = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            srcs = [x for x in srcs if os.path.normcase(os.path.normpath(x)) != os.path.normcase(os.path.normpath(tgt))]
            move = self._drop_action(ev, tgt) == Qt.MoveAction
            v = self.main.pane().view() if self.main.pane() else None
            log.info("즐겨찾기 폴더로 놓기 %s n=%d -> %s", "이동" if move else "복사", len(srcs), tgt)
            if srcs and v is not None:
                v.file_op(srcs, tgt, move)
            ev.setDropAction(Qt.CopyAction)   # 원본 쪽이 따로 지우지 않게 (이동은 우리가 처리)
            ev.accept()
            return
        if spot is None:
            ev.ignore()
            return
        pos = spot[1]
        if md.hasFormat(FAV_MIME):
            a, b = (int(x) for x in bytes(md.data(FAV_MIME)).decode().split(":"))
            FAV.move_block(a, b, pos)
        else:
            for u in md.urls():
                p = u.toLocalFile()
                if p and os.path.isdir(p):
                    FAV.add(p, pos=pos)
                    pos += 1
        ev.setDropAction(Qt.CopyAction)
        ev.accept()


# ================================================================ 레이아웃 아이콘 (코드로 그림)
LAYOUTS = [("1", T("1칸")), ("2h", T("2칸 좌우")), ("2v", T("2칸 상하")), ("3", T("3칸 (위 2 + 아래 1)")),
           ("3h", T("3칸 가로")), ("4", T("4칸")), ("6", T("6칸 (3 x 2)"))]
# 줄마다 보일 칸 번호. 위 줄 = 0,1,4 / 아래 줄 = 2,3,5 (예전 4칸·6칸 저장 상태와 번호 호환)
LAYOUT_ROWS = {"1": [[0]], "2h": [[0, 1]], "2v": [[0], [2]], "3": [[0, 1], [2]],
               "3h": [[0, 1, 4]], "4": [[0, 1], [2, 3]], "6": [[0, 1, 4], [2, 3, 5]]}
# 직접 지정(가로x세로)의 칸 번호: 기존 6칸 자리는 그대로, 나머지는 위→아래, 왼→오 순서로 6번부터
_SLOT = [(0, 0), (0, 1), (1, 0), (1, 1), (0, 2), (1, 2)]
_SLOT += [(r, c) for r in range(MAX_ROWS) for c in range(MAX_COLS) if (r, c) not in _SLOT]
SLOT_OF = {rc: i for i, rc in enumerate(_SLOT)}


def grid_key(cols, rows):
    return f"g{cols}x{rows}"


def parse_grid(key):
    """'g5x2' → (5, 2), 아니면 None"""
    m = re.fullmatch(r"g(\d)x(\d)", key or "")
    if not m:
        return None
    c, r = int(m.group(1)), int(m.group(2))
    return (c, r) if 1 <= c <= MAX_COLS and 1 <= r <= MAX_ROWS else None


def layout_rows(key):
    """레이아웃 → 줄마다 칸 번호 목록 (없는 키면 None)"""
    if key in LAYOUT_ROWS:
        return LAYOUT_ROWS[key]
    g = parse_grid(key)
    if g:
        cols, rows = g
        return [[SLOT_OF[(r, c)] for c in range(cols)] for r in range(rows)]
    return None


def layout_icon(key, w=22, h=18):
    pm = QtGui.QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, False)
    p.setPen(QtGui.QPen(QtGui.QColor("#3a4652"), 1))
    p.setBrush(QtGui.QColor("#ffffff"))
    r = QtCore.QRect(1, 1, w - 3, h - 3)
    p.drawRect(r)
    p.fillRect(QtCore.QRect(2, 2, w - 4, 3), QtGui.QColor("#5b8ed6"))   # 제목줄 느낌
    g = parse_grid(key)
    if g:   # 직접 지정: 가로 cols, 세로 rows 로 나눈 선
        cols, rows = g
        for i in range(1, cols):
            x = 1 + i * (w - 3) // cols
            p.drawLine(x, 5, x, h - 2)
        for j in range(1, rows):
            y = 5 + j * (h - 7) // rows
            p.drawLine(1, y, w - 2, y)
        p.end()
        return QtGui.QIcon(pm)
    cx, cy = 1 + (w - 3) // 2, 5 + (h - 7) // 2
    t1, t2 = 1 + (w - 3) // 3, 1 + 2 * (w - 3) // 3
    if key in ("2h", "4"):
        p.drawLine(cx, 5, cx, h - 2)
    if key in ("2v", "4", "3", "6"):
        p.drawLine(1, cy, w - 2, cy)
    if key == "3":
        p.drawLine(cx, 5, cx, cy)
    if key in ("3h", "6"):
        p.drawLine(t1, 5, t1, h - 2)
        p.drawLine(t2, 5, t2, h - 2)
    p.end()
    return QtGui.QIcon(pm)


def preview_icon(w=22, h=18):
    """미리보기 창 버튼 그림 (v0.9.59): 레이아웃 아이콘과 같은 창 모양 — 왼쪽 목록 줄 + 오른쪽 그림 칸(산·해)"""
    pm = QtGui.QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, False)
    p.setPen(QtGui.QPen(QtGui.QColor("#3a4652"), 1))
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawRect(QtCore.QRect(1, 1, w - 3, h - 3))
    p.fillRect(QtCore.QRect(2, 2, w - 4, 3), QtGui.QColor("#5b8ed6"))   # 제목줄
    sx = 1 + (w - 3) * 5 // 9                                           # 목록 | 미리보기 경계
    p.drawLine(sx, 5, sx, h - 2)
    for y in range(7, h - 3, 3):                                         # 왼쪽 목록 줄
        p.drawLine(3, y, sx - 2, y)
    pic = QtCore.QRect(sx + 2, 7, w - sx - 5, h - 11)                    # 오른쪽 그림 칸
    p.fillRect(pic, QtGui.QColor("#cfe3ff"))
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#3c8d4a"))                                 # 산
    p.drawPolygon(QtGui.QPolygon([QtCore.QPoint(pic.left(), pic.bottom() + 1), QtCore.QPoint(pic.left() + pic.width() // 2, pic.top() + 2),
                                  QtCore.QPoint(pic.right() + 1, pic.bottom() + 1)]))
    p.setBrush(QtGui.QColor("#f2b01e"))                                 # 해
    p.drawEllipse(QtCore.QPoint(pic.right() - 1, pic.top() + 1), 1, 1)
    p.end()
    return QtGui.QIcon(pm)


# 화면 색상은 ui_parts.build_style(SETTINGS[theme 또는 theme_dark]) 로 만든다 (보기 > 색상 설정에서 변경)


class SearchSig(QtCore.QObject):
    ev = QtCore.Signal(str, object)   # 색인 작업 스레드 → 화면 (kind, info)


def drive_list():
    """[(드라이브, 표시이름, 기본 색인 여부)] — 로컬+NTFS/ReFS 만 기본 켬"""
    out = []
    k = ctypes.windll.kernel32
    kinds = {2: T("이동식"), 3: T("로컬"), 4: T("네트워크"), 5: "CD"}
    for d in os.listdrives():
        t = k.GetDriveTypeW(d)
        vol, fs = ctypes.create_unicode_buffer(64), ctypes.create_unicode_buffer(32)
        ok = k.GetVolumeInformationW(d, vol, 64, None, None, None, fs, 32) if t != 4 else 0   # 네트워크는 응답 대기 피함
        on = t == 3 and ok and fs.value.upper() in ("NTFS", "REFS")
        out.append((d, f"{d}  {vol.value}  [{kinds.get(t, '?')}{(' ' + fs.value) if fs.value else ''}]", bool(on)))
    return out


# ================================================================ 메인 창
class PreviewPane(QtWidgets.QFrame):
    """오른쪽 미리보기 창 (v0.9.58, 사용자 요청 — 자세히 보기에서도 그림을 크게).
    지금 칸에서 고른 파일 하나를 크게: 그림 파일(.max·.psd 포함)은 미리보기(thumbs, 뒤 스레드), 나머지는 큰 아이콘 + 정보.
    선택이 바뀔 때만 120ms 묶어 다시 그림(유휴 시 타이머 없음). 숨겨져 있으면 아무것도 안 함."""
    PX = 512   # 미리보기 요청 크기 (창에 맞춰 줄여 그림, 2배 넘게는 안 늘림)

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("previewPane")
        self.setMinimumWidth(160)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self.pic = QtWidgets.QLabel()
        self.pic.setAlignment(Qt.AlignCenter)
        self.pic.setMinimumHeight(120)
        self.pic.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        self.name = QtWidgets.QLabel()
        self.name.setWordWrap(True)
        self.name.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        f = self.name.font()
        f.setBold(True)
        self.name.setFont(f)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        self.info.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.pic, 1)
        lay.addWidget(self.name)
        lay.addWidget(self.info)
        lay.addStretch(0)
        self.cur = None      # (경로, mtime) — 지금 보여주는 그림 파일
        self.src = None      # 지금 그림 (QPixmap, 창 크기 바뀌면 다시 맞춤)
        self.movie = None    # 움직이는 GIF 재생 (v0.9.64, 사용자 요청) — 고른 파일이 바뀌거나 창이 숨으면 멈추고 버림
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.refresh)

    def schedule(self):
        if self.isVisible():
            self.timer.start()

    def showEvent(self, ev):
        super().showEvent(ev)
        thumbs_service().ready.connect(self._on_ready, Qt.UniqueConnection)
        self.refresh()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._stop_movie()

    GIF_MAX = 64 * 1048576   # 이보다 큰 GIF 는 움직임 없이 첫 장만 (메모리·CPU)

    def _stop_movie(self):
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None

    def pause_movie(self, paused):
        """창 최소화 = 멈춤 (보이지 않는데 돌 필요 없음), 다시 열면 이어서"""
        if self.movie is not None:
            self.movie.setPaused(paused)

    def _play_gif(self, path, size):
        """움직이는 GIF 면 재생하고 True. 한 장짜리·깨진 파일·너무 큰 파일·재생 부품(qgif) 없음 → False (보통 미리보기로)"""
        if size > self.GIF_MAX or b"gif" not in [bytes(f) for f in QtGui.QMovie.supportedFormats()]:
            return False
        m = QtGui.QMovie(path)
        m.setCacheMode(QtGui.QMovie.CacheNone)
        if not m.isValid() or m.frameCount() == 1:
            m.deleteLater()
            return False
        self.movie = m
        m.frameChanged.connect(lambda _i, m=m: m is self.movie and self._set_pic(m.currentPixmap()))
        m.start()
        log.info("미리보기 GIF 재생 %s (장면 %d, %s)", path, m.frameCount(), size_short(size))
        return True

    def _on_ready(self, path, px):
        if self.cur and px == self.PX and os.path.normcase(path) == os.path.normcase(self.cur[0]) and self.isVisible():
            self.refresh()

    def _set_pic(self, pm):
        self.src = pm
        self._fit()

    def _fit(self):
        if self.src is None or self.src.isNull():
            self.pic.clear()
            return
        w, h = max(1, self.pic.width() - 4), max(1, self.pic.height() - 4)
        sw, sh = self.src.width(), self.src.height()
        k = min(w / sw, h / sh, 2.0)   # 작은 그림(PSD 내장 160px 등)은 2배까지만 키움
        self.pic.setPixmap(self.src.scaled(max(1, int(sw * k)), max(1, int(sh * k)), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def refresh(self):
        if not self.isVisible():
            return
        pane = self.main.pane()
        v = pane.view() if pane else None
        if v is None:
            return
        rows = v.selected_rows()
        if len(rows) == 1 and self.movie is not None and os.path.normcase(self.movie.fileName()) == os.path.normcase(v.model_.full(v.model_.rows[rows[0]])):
            return   # 같은 GIF 가 재생 중 (선택 글자만 다시 그려진 경우) — 처음부터 다시 틀지 않음
        self._stop_movie()
        if len(rows) != 1:
            self.cur = None
            self._set_pic(None)
            if rows:
                es = [v.model_.rows[r] for r in rows]
                self.name.setText(T('    {0:,}개 항목 선택함').format(len(rows)).strip())   # 상태줄과 같은 문구
                fs = [e[2] for e in es if not e[1] and e[2] >= 0]
                self.info.setText(size_short(sum(fs)) if fs else "")
            else:
                self.name.setText("")
                self.info.setText(T("파일을 고르면 여기에 미리보기가 나옵니다"))
            return
        e = v.model_.rows[rows[0]]
        path = v.model_.full(e)
        self.name.setText(e[7] or e[0])
        lines = [shellops.type_for(e[0], e[1])]
        if not e[1] and e[2] >= 0:
            lines.append(win_kbsize(e[2]))
        if e[3]:
            lines.append(T("수정한 날짜") + ": " + win_datetime(e[3]))
        self.info.setText("\n".join(x for x in lines if x))
        pm = None
        if not e[1] and e[0].lower().endswith(".gif") and OPTS["thumbnails"] and self._play_gif(path, e[2]):
            self.cur = None
            return
        if not e[1] and thumbs.is_image(e[0]) and OPTS["thumbnails"]:
            self.cur = (path, e[3])
            pm = thumbs_service().get(path, e[3], self.PX)   # 없으면 요청 → 다 되면 _on_ready
        else:
            self.cur = None
        if pm is None:
            pm = shellops.icon_for(e[0], e[1], 256, e[6]).pixmap(128, 128)
        self._set_pic(pm)


class Main(QtWidgets.QMainWindow):
    def __init__(self, crashed=False, open_path=None, src=None, open_state=None, restore_geometry=False):
        """open_path 가 있으면 '새 창으로 열기' — 저장 상태 대신 칸 1개 + 그 폴더로 시작 (src = 연 창, 위치 기준)
        open_state 가 있으면 그 기록(자동 기록 복구·지난번 함께 열려 있던 창)으로 새 창. restore_geometry = 그때 위치·크기"""
        super().__init__()
        _ORDER[0] += 1
        self.order = _ORDER[0]
        self.setAttribute(Qt.WA_DeleteOnClose)   # 창이 여러 개일 때 닫은 창 메모리 반환
        self.setWindowTitle(f"4Dir v{QE_VERSION}")
        self.resize(1400, 850)
        self.layout_mode = "4"
        self.crashed = crashed
        self.closed_tabs = []    # [(칸 번호, 경로)] 최근 닫은 탭 (최대 20)
        self.prev_pane = None    # 직전에 쓰던 칸 (F6 대상)
        self.sessions = session.Sessions()
        self.save_timer = QtCore.QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(2000)
        self.save_timer.timeout.connect(self.save_state)
        self.setWindowIcon(ui_parts.app_icon())
        self.setAcceptDrops(True)   # 끌고 온 탭 받기 (목록·사이드바가 안 받는 끌기는 여기까지 올라옴)
        self.apply_theme(app_wide=not WINDOWS)
        hints = QtWidgets.QApplication.instance().styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_scheme)
        SVN_SIG.changed.connect(self._on_svn_changed)

        # 칸 배치: 세로 분할(self.vert) 안에 줄(self.rows[0..3], 가로 분할). 칸은 레이아웃에 따라 줄 사이를 옮겨 다님
        self.panes = []
        self.vert = QtWidgets.QSplitter(Qt.Vertical)
        self.rows = [QtWidgets.QSplitter(Qt.Horizontal) for _ in range(MAX_ROWS)]
        for s in self.rows:
            self.vert.addWidget(s)
        for s in self.rows + [self.vert]:
            s.setChildrenCollapsible(False)
            s.setHandleWidth(5)
            s.splitterMoved.connect(lambda *_: self.save_timer.start())
        self.top, self.bot = self.rows[0], self.rows[1]   # 예전 이름 (테스트·저장 호환)
        self._ensure_panes(NPANES)
        self._build_top_bar()
        central = QtWidgets.QWidget()
        central.setObjectName("central")
        cl = QtWidgets.QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.favbar = FavPanel(self)       # 즐겨찾기: 칸 위에 자리 차지 → 펼쳐도 칸과 안 겹침
        # 접었을 때만 보이는 얇은 줄 — 누르면 메뉴·즐겨찾기 다시 펼침
        self.chrome_strip = QtWidgets.QPushButton("▼")
        self.chrome_strip.setObjectName("chromeStrip")
        self.chrome_strip.setFlat(True)
        self.chrome_strip.setFixedHeight(14)
        self.chrome_strip.setCursor(Qt.PointingHandCursor)
        self.chrome_strip.setStyleSheet("QPushButton{font-size:10px; padding:0; border:none; border-bottom:1px solid rgba(128,128,128,90);} QPushButton:hover{background:rgba(47,111,208,40);}")
        self.chrome_strip.setToolTip(T("메뉴·즐겨찾기 펼치기") + " (Ctrl+Shift+M)")
        self.chrome_strip.clicked.connect(lambda: self.set_chrome_collapsed(False))
        self.chrome_strip.setVisible(False)
        cl.addWidget(self.chrome_strip)
        nrow = QtWidgets.QHBoxLayout()   # 알림 + (필요할 때) 오른쪽 버튼 — 예: '문제 보고 만들기'
        nrow.setContentsMargins(0, 0, 0, 0)
        nrow.setSpacing(4)
        nrow.addWidget(self.notice, 1)
        nrow.addWidget(self.notice_act)
        nrow.addWidget(self.notice_act2)
        cl.addLayout(nrow)
        cl.addWidget(self.favbar)
        body = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(body)
        bl.setContentsMargins(4, 4, 4, 4)
        # 칸들 | 오른쪽 미리보기 창 (v0.9.58)
        self.hsplit = QtWidgets.QSplitter(Qt.Horizontal)
        self.hsplit.setChildrenCollapsible(False)
        self.hsplit.setHandleWidth(5)
        self.preview = PreviewPane(self)
        self.hsplit.addWidget(self.vert)
        self.hsplit.addWidget(self.preview)
        self.hsplit.setStretchFactor(0, 1)
        self.hsplit.setStretchFactor(1, 0)
        self.hsplit.splitterMoved.connect(self._preview_moved)
        self.preview.setVisible(bool(SETTINGS["preview_pane"]))
        bl.addWidget(self.hsplit)
        cl.addWidget(body, 1)
        self.setCentralWidget(central)
        if SETTINGS["chrome_collapsed"]:
            self.set_chrome_collapsed(True, save=False)
        if SETTINGS["on_top"]:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        # 창 전체 단축키 (keymap, 보기 > 단축키 설정에서 변경)
        def add_fav():
            v = self.pane().view()
            if v and v.path != THIS_PC:
                FAV.add(v.path)

        def focus_addr():
            p = self.pane()
            p._crumb_edit() if p.breadcrumb else (p.addr.setFocus(), p.addr.selectAll())
        self.win_actions = {
            "new_tab": lambda: self.pane().add_tab(self.pane().view().path, focus=True),
            "new_window": lambda: self.open_window(self.pane().view().path if self.pane().view() else THIS_PC),
            "close_tab": lambda: self.pane().close_tab(self.pane().bar.currentIndex()),
            "reopen_tab": lambda: self.reopen_tab(),
            "focus_filter": lambda: self.pane().focus_filter(),
            "global_search": lambda: self.focus_global_search(),
            "next_tab": lambda: self._cycle_tab(1),
            "prev_tab": lambda: self._cycle_tab(-1),
            "focus_addr": focus_addr,
            "toggle_hidden": lambda: self.toggle_opt("show_hidden"),
            "add_fav": add_fav,
            "toggle_chrome": lambda: self.set_chrome_collapsed(not SETTINGS["chrome_collapsed"]),
            "toggle_preview": lambda: self.set_preview(not self.preview.isVisible()),
        }
        for i in range(NPANES):
            self.win_actions[f"pane{i + 1}"] = (lambda i=i: self._focus_pane(i))
        self.shortcuts = []
        self.apply_keys()
        # 마우스 뒤로/앞으로: 창 어디서 눌러도(주소줄·탭줄·사이드바 포함) 그 칸에서 동작.
        # 버튼 신호(XButton)와 '브라우저 뒤로' 키 신호(일부 마우스 드라이버) 둘 다 받음
        QtWidgets.QApplication.instance().installEventFilter(self)

        self.active_pane = self.panes[0]
        QtWidgets.QApplication.instance().focusChanged.connect(self._on_focus)

        if open_path or open_state:
            st0 = dict(open_state) if open_state else {"layout": "1", "panes": [{"tabs": [open_path]}]}
            st0["opts"] = dict(OPTS)   # 보기 옵션은 지금 것 그대로 (기록 속 옵션으로 다른 창까지 바꾸지 않음)
            self.apply_state(st0, geometry=restore_geometry and bool(st0.get("geometry")))
            if src is not None and not restore_geometry:
                g = src.normalGeometry() if src.isMaximized() else src.geometry()
                self.resize(g.size())
                self.move(g.x() + 40, g.y() + 40)
            saved = ""
        else:
            saved = self.load_state()
        if self.crashed:
            self.show_notice(T("⚠ 지난번에 비정상 종료됨 — 마지막 저장 상태({0})로 복원했습니다. 다른 시점은 '세션 복구' 메뉴  ✕").format(saved or '?'),
                             action=(T("문제 보고 만들기"), self.save_report))
            log.warning("비정상 종료 후 복원 (저장 %s)", saved)
        self.sessions.snapshot(self.collect_state(), force=True)
        self._init_done = True
        # 빠른 전체 검색 색인: 창이 뜬 뒤 2초 후 시작 (저장본 즉시 불러오고 뒤에서 갱신)
        global SEARCH, SSIG
        if SSIG is None:
            SSIG = SearchSig()
        SSIG.ev.connect(self._on_index_event)
        if SEARCH is None:   # 첫 창만 색인을 만듦, 다음 창들은 같이 씀
            SEARCH = search_index.SearchIndex(os.path.join(BIN_DIR, "index"),
                                              notify=lambda k, i: SSIG.ev.emit(k, i))
            QtCore.QTimer.singleShot(2000, lambda: SEARCH and SEARCH.start(self.search_roots_enabled()))
        elif SEARCH.state == "ready":
            self._on_index_event("ready", None)
        WINDOWS.append(self)
        log.info("창 열기 (열린 창 %d개)%s", len(WINDOWS), f" 새 창 {open_path}" if open_path else "")

    # ---------------------------------------------------------- 빠른 전체 검색
    def search_roots_enabled(self):
        return [r["path"] for r in self.search_roots() if r.get("on")]

    def search_roots(self):
        """[{path, on}] — 설정에 없으면 기본: 로컬 NTFS 드라이브 켬, 나머지(구글드라이브·네트워크·이동식) 끔"""
        roots = SETTINGS["search_roots"]
        if roots is None:
            roots = [{"path": d, "on": default_on} for d, _label, default_on in drive_list()]
        return roots

    def _on_index_event(self, kind, info):
        if kind == "progress":
            n, root = info
            self.idx_btn.setText(T('색인 중 {0:.0f}만').format(n / 10000))
        elif kind == "building":
            if SEARCH and SEARCH.state == "ready":
                self.idx_btn.setText(T('색인 {0:,} (갱신 중)').format(SEARCH.count()))
            else:
                self.idx_btn.setText(T("색인 만드는 중"))
        elif kind == "ready":
            self.idx_btn.setText(T('색인 {0:,}').format(SEARCH.count()) if SEARCH else T("색인"))
            # 이미 열린 전체 검색 탭은 새 색인으로 다시 검색
            for p in self.panes:
                for v in p.views():
                    if is_search(v.path) and not parse_search(v.path)[1] and v.active:
                        v.reload("index-ready")

    def do_global_search(self, text):
        q = text.strip()
        if not q:
            return
        pane = self.pane()
        v = pane.view()
        if v and is_search(v.path) and not parse_search(v.path)[1]:
            v.navigate(search_path(q), record=False)     # 지금 검색 탭을 새 검색어로 (기록 안 쌓음)
        else:
            pane.add_tab(search_path(q))
        log.info("전체 검색 '%s' (칸 %d)", q, pane.idx + 1)

    def focus_global_search(self):
        self.gsearch.setFocus()
        self.gsearch.selectAll()

    def open_search_roots(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(T("검색 범위 설정 (Search Scope)"))
        dlg.resize(520, 420)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(QtWidgets.QLabel(T("체크한 드라이브·폴더의 파일 이름을 색인합니다 (내용은 안 읽음). 관리자 권한 없이 실시간 반영.\n"
                                       "구글드라이브·네트워크 드라이브는 느리거나 연결이 끊기면 오래 걸릴 수 있어 기본 꺼짐.")))
        lst = QtWidgets.QListWidget()
        labels = {d: lbl for d, lbl, _on in drive_list()}
        for r in self.search_roots():
            it = QtWidgets.QListWidgetItem(labels.get(r["path"], r["path"]))
            it.setData(Qt.UserRole, r["path"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if r.get("on") else Qt.Unchecked)
            lst.addItem(it)
        lay.addWidget(lst, 1)
        row = QtWidgets.QHBoxLayout()

        def add_folder():
            d = QtWidgets.QFileDialog.getExistingDirectory(dlg, T("색인할 폴더 고르기"))
            if d:
                d = os.path.normpath(d)
                it = QtWidgets.QListWidgetItem(d)
                it.setData(Qt.UserRole, d)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked)
                lst.addItem(it)

        def remove():
            for it in lst.selectedItems():
                if len(it.data(Qt.UserRole)) > 3:   # 드라이브는 지우지 않고 체크만 끔
                    lst.takeItem(lst.row(it))
        b1 = QtWidgets.QPushButton(T("폴더 추가…"))
        b1.clicked.connect(add_folder)
        b2 = QtWidgets.QPushButton(T("선택한 폴더 빼기"))
        b2.clicked.connect(remove)
        b3 = QtWidgets.QPushButton(T("지금 색인 다시 만들기"))
        b3.clicked.connect(lambda: (SEARCH.rebuild(), self.idx_btn.setText(T("색인 갱신 중"))))
        for b in (b1, b2, b3):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        info = QtWidgets.QLabel(T("지금 색인: {0:,}개 · 실시간 변경 알림 {1:,}건 · 저장 위치 bin\\index").format(SEARCH.count(), SEARCH.events) if SEARCH else "")
        info.setStyleSheet("color:#888;")
        lay.addWidget(info)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec():
            roots = [{"path": lst.item(i).data(Qt.UserRole), "on": lst.item(i).checkState() == Qt.Checked} for i in range(lst.count())]
            old = self.search_roots_enabled()
            SETTINGS["search_roots"] = roots
            new = self.search_roots_enabled()
            log.info("검색 범위 %s → %s", old, new)
            if [x.lower() for x in old] != [x.lower() for x in new]:
                self.idx_btn.setText(T("색인 만드는 중"))
                SEARCH.set_roots(new)

    # ---------------------------------------------------------- 상단 메뉴 + 레이아웃 아이콘
    def _build_top_bar(self):
        tb = QtWidgets.QToolBar(T("메뉴"))
        tb.setObjectName("topBar")
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(22, 18))
        self.addToolBar(tb)
        self.topbar = tb
        # 맨 앞 = 접기 버튼 (맨 끝에 두면 창이 좁을 때 '…' 안으로 밀림)
        fold = tb.addAction("▲", lambda: self.set_chrome_collapsed(True))
        fold.setToolTip(T("메뉴·즐겨찾기 접기") + " (Ctrl+Shift+M)")
        #   메뉴줄 맨 앞 앱 아이콘은 뺌 — 창 제목줄 아이콘과 중복(10/2 사용자 지시)

        def menu_btn(text, filler):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            b.setAutoRaise(True)
            m = QtWidgets.QMenu(b)
            m.aboutToShow.connect(lambda: filler(m))
            b.setMenu(m)
            tb.addWidget(b)
            return b

        menu_btn(T("보기"), self._fill_main_view_menu)
        menu_btn(T("레이아웃"), self._fill_layout_menu)
        menu_btn(T("즐겨찾기"), self._fill_fav_menu)
        menu_btn(T("창 저장/불러오기"), self._fill_session_menu)
        menu_btn(T("도구"), self._fill_tool_menu)
        # 미리보기 창 켜기/끄기 — 도구 오른쪽 (v0.9.59, 사용자 요청)
        self.act_preview = tb.addAction(preview_icon(), T("미리보기 창"), lambda: self.set_preview(not self.preview.isVisible()))
        self.act_preview.setCheckable(True)
        self.act_preview.setChecked(bool(SETTINGS["preview_pane"]))
        self.act_preview.setToolTip(T("미리보기 창") + (f" ({key_text('toggle_preview')})" if key_text("toggle_preview") else ""))
        tb.addSeparator()
        self.layout_group = QtGui.QActionGroup(self)
        self.layout_actions = {}
        for key, label in LAYOUTS:
            a = tb.addAction(layout_icon(key), label, lambda k=key: self.set_layout(k, equalize=True))
            a.setToolTip(T('레이아웃: {0}').format(label))
            a.setCheckable(True)
            self.layout_group.addAction(a)
            self.layout_actions[key] = a
        self.act_grid = tb.addAction(layout_icon(grid_key(3, 3)), T("직접 지정"), self.open_grid_dialog)
        self.act_grid.setToolTip(T("레이아웃: 직접 지정 (가로 x 세로)…"))
        self.act_grid.setCheckable(True)
        self.layout_group.addAction(self.act_grid)
        # 격자 아이콘만으론 6칸 버튼과 구분이 안 됨(10/8 사용자 지적) → 아이콘 옆에 '직접 지정' 글자
        gb = tb.widgetForAction(self.act_grid)
        if isinstance(gb, QtWidgets.QToolButton):
            gb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.addSeparator()
        self.act_top = tb.addAction(T("📌 항상 위"), self.toggle_on_top)
        self.act_top.setCheckable(True)
        self.act_top.setChecked(SETTINGS["on_top"])
        self.act_top.setToolTip(T("다른 창 위에 항상 표시 (켜기/끄기)"))
        tb.addSeparator()
        tb.addAction(T("Explorer Check (탐색기 점검)"), self.open_check)
        # 알림 줄 (비정상 종료 복원·언어 바꿈 등) — 클릭하면 닫힘.
        # 상단 메뉴줄 안에 두면 창이 좁을 때 '…' 안으로 밀려 안 보임(10/2 사용자 지적, 1168px 재현) → 메뉴줄 아래 한 줄로
        self.notice = QtWidgets.QPushButton()
        self.notice.setObjectName("notice")
        self.notice.setFlat(True)
        self.notice.setCursor(Qt.PointingHandCursor)
        self.notice.setStyleSheet("text-align:left;")
        self.notice.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.notice.clicked.connect(self.hide_notice)
        self.notice.setVisible(False)
        self.notice_act = QtWidgets.QPushButton()   # 알림 옆 버튼 (비정상 종료·멈춤 → 문제 보고 만들기)
        self.notice_act.setObjectName("noticeAct")
        self.notice_act.setCursor(Qt.PointingHandCursor)
        self.notice_act.setVisible(False)
        self.notice_act.clicked.connect(self._notice_act_clicked)
        self.notice_act2 = QtWidgets.QPushButton()   # 보조 버튼 (예: 새 버전 '이 버전 건너뛰기', v0.9.63)
        self.notice_act2.setObjectName("noticeAct2")
        self.notice_act2.setCursor(Qt.PointingHandCursor)
        self.notice_act2.setVisible(False)
        self.notice_act2.clicked.connect(self._notice_act2_clicked)
        self._notice_fn2 = None
        self._notice_fn = None
        tb.addSeparator()
        self.gsearch = QtWidgets.QLineEdit()
        self.gsearch.setObjectName("gsearch")
        self.gsearch.setPlaceholderText(T("🔎 전체 검색 (Ctrl+Shift+F)"))
        self.gsearch.setClearButtonEnabled(True)
        self.gsearch.setMinimumWidth(110)
        self.gsearch.setMaximumWidth(260)
        self.gsearch.setToolTip(T("색인한 드라이브·폴더에서 이름으로 바로 찾기\n"
                                "여러 단어 = 모두 포함 · *.max 같은 와일드카드 · .txt = 확장자 · \\anim\\ = 경로에 포함\n"
                                "결과는 선택된 칸의 '🔎' 탭에 · Esc = 지우기"))
        self.gs_timer = QtCore.QTimer(self)
        self.gs_timer.setSingleShot(True)
        self.gs_timer.setInterval(350)
        self.gs_timer.timeout.connect(lambda: self.do_global_search(self.gsearch.text()))
        self.gsearch.textChanged.connect(lambda _t: self.gs_timer.start())
        self.gsearch.returnPressed.connect(lambda: (self.gs_timer.stop(), self.do_global_search(self.gsearch.text())))
        tb.addWidget(self.gsearch)
        self.idx_btn = QtWidgets.QToolButton()
        self.idx_btn.setObjectName("idxStatus")
        self.idx_btn.setAutoRaise(True)
        self.idx_btn.setText(T("색인 준비 중"))
        self.idx_btn.setToolTip(T("검색 색인 상태 — 눌러서 검색 범위 설정"))
        self.idx_btn.clicked.connect(self.open_search_roots)
        tb.addWidget(self.idx_btn)
        sp = QtWidgets.QWidget()
        sp.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        tb.addWidget(sp)
        # CPU·GPU 사용량 (1.5초마다, 창 최소화·표시 끔이면 멈춤)
        self.mon_label = QtWidgets.QLabel()
        self.mon_label.setObjectName("sysmon")
        self.mon_label.setTextFormat(Qt.RichText)
        self.mon_act = tb.addWidget(self.mon_label)
        self.mon = None
        self.mon_timer = QtCore.QTimer(self)
        self.mon_timer.setInterval(1500)
        self.mon_timer.timeout.connect(self._update_mon)
        ver = QtWidgets.QLabel(f"  v{QE_VERSION}  ")
        ver.setStyleSheet("color:#888;")
        tb.addWidget(ver)
        self.set_sysmon(SETTINGS["sysmon"], save=False)

    def set_preview(self, on):
        """오른쪽 미리보기 창 보이기/숨기기 (v0.9.58). 너비는 기억"""
        on = bool(on)
        if on and not self.preview.isVisible():
            self.preview.setVisible(True)
            total = sum(self.hsplit.sizes()) or self.width()
            pw = max(160, min(int(SETTINGS["preview_w"] or 300), total // 2))
            self.hsplit.setSizes([max(200, total - pw), pw])
        elif not on:
            self.preview.setVisible(False)
        SETTINGS["preview_pane"] = on
        if getattr(self, "act_preview", None) is not None:
            self.act_preview.setChecked(on)   # 메뉴·Alt+P 로 바꿔도 버튼 눌림 표시 맞춤
        log.info("미리보기 창 %s", "켬" if on else "끔")

    def _preview_moved(self, *_):
        if self.preview.isVisible():
            SETTINGS["preview_w"] = self.hsplit.sizes()[1]

    def _fill_main_view_menu(self, m):
        self.pane().fill_view_menu(m)
        m.addSeparator()
        pv = m.addAction(T("미리보기 창") + (("	" + key_text("toggle_preview")) if key_text("toggle_preview") else ""),
                         lambda: self.set_preview(not self.preview.isVisible()))
        pv.setCheckable(True)
        pv.setChecked(self.preview.isVisible())
        fav = m.addAction(T("즐겨찾기 바 펼치기"), self.favbar.toggle)
        fav.setCheckable(True)
        fav.setChecked(self.favbar.expanded)
        tm = m.addMenu(T("화면 테마"))
        grp = QtGui.QActionGroup(tm)
        for mode, label in (("system", T("시스템 설정 따름")), ("light", T("밝게 (Light)")), ("dark", T("어둡게 (Dark)"))):
            a = tm.addAction(label, lambda md=mode: self.set_theme_mode(md))
            a.setCheckable(True)
            a.setChecked(SETTINGS["theme_mode"] == mode)
            grp.addAction(a)
        lm = m.addMenu(T("언어") + " (Language)" if i18n.lang != "en" else "Language")
        lg = QtGui.QActionGroup(lm)
        cur = SETTINGS["lang"]
        a = lm.addAction(T("윈도우 언어 따름") + f"  ({dict(i18n.LANGS).get(i18n.windows_lang(), 'English')})",
                         lambda: self.set_language(None))
        a.setCheckable(True)
        a.setChecked(cur is None)
        lg.addAction(a)
        lm.addSeparator()
        for code, name in i18n.LANGS:
            a = lm.addAction(name, lambda c=code: self.set_language(c))
            a.setCheckable(True)
            a.setChecked(cur == code)
            lg.addAction(a)
        top = m.addAction(T("항상 위"), self.toggle_on_top)
        top.setCheckable(True)
        top.setChecked(SETTINGS["on_top"])
        mon = m.addAction(T("CPU·GPU 사용량 표시"), lambda: self.set_sysmon(not SETTINGS["sysmon"]))
        mon.setCheckable(True)
        mon.setChecked(SETTINGS["sysmon"])
        multi = m.addAction(T("창 여러 개 열기 허용"), self.toggle_multi)
        multi.setCheckable(True)
        multi.setChecked(SETTINGS["allow_multi"])
        multi.setToolTip(T("끄면 4Dir 는 하나만 실행되고, 다시 실행하면 기존 창이 앞으로 나옵니다"))
        m.addAction(T("색상 설정…"), self.open_colors)
        m.addAction(T("단축키 설정…"), self.open_keys)

    # ---------------------------------------------------------- CPU·GPU 사용량
    def set_sysmon(self, on, save=True):
        if on and self.mon is None:
            import sysmon
            self.mon = sysmon.SysMon()
            self.mon.cpu()   # 첫 기준값
        self.mon_act.setVisible(on)
        if on and not self.isMinimized():
            self.mon_timer.start()
            QtCore.QTimer.singleShot(300, self._update_mon)
        else:
            self.mon_timer.stop()
        if save:
            SETTINGS["sysmon"] = on
            log.info("사용량 표시 %s", on)

    def _update_mon(self):
        if not self.mon:
            return
        t0 = time.perf_counter()

        def col(v):
            if SETTINGS["dark"]:
                return "#ff6b6b" if v >= 85 else ("#ffb74d" if v >= 60 else "#66d17a")
            return "#c62828" if v >= 85 else ("#e08a00" if v >= 60 else "#2e7d32")
        parts = []
        c = self.mon.cpu()
        if c is not None:
            parts.append(f"CPU <b style='color:{col(c)}'>{c:3.0f}%</b>")
        g = self.mon.gpu()
        if g:
            u, used, total = g
            parts.append(f"GPU <b style='color:{col(u)}'>{u:3d}%</b>")
            parts.append(f"VRAM <b style='color:{col(used * 100 / total)}'>{used:.1f}</b>/{total:.0f}GB")
        self.mon_label.setText("&nbsp;&nbsp;".join(parts) + "&nbsp;&nbsp;")
        if self.mon.gpu_name:
            self.mon_label.setToolTip(T('{0}\n1.5초마다 갱신 · 보기 메뉴에서 끄기').format(self.mon.gpu_name))
        ms = (time.perf_counter() - t0) * 1000
        if ms > 20:
            log.warning("사용량 갱신 느림 %.1fms", ms)

    def changeEvent(self, ev):
        # 최소화하면 사용량 갱신·GIF 재생 멈춤 (보이지 않는데 돌 필요 없음)
        if ev.type() == QtCore.QEvent.WindowStateChange and hasattr(self, "preview"):
            self.preview.pause_movie(self.isMinimized())
        if ev.type() == QtCore.QEvent.WindowStateChange and hasattr(self, "mon_timer"):
            if self.isMinimized():
                self.mon_timer.stop()
            elif SETTINGS["sysmon"]:
                self.mon_timer.start()
        # 창이 다시 활성화됨(TortoiseSVN 커밋·업데이트 창에서 돌아옴 등) → 보이는 탭의 SVN 장부가 바뀌었으면 상태만 다시 읽음
        if ev.type() == QtCore.QEvent.ActivationChange and self.isActiveWindow() and self in WINDOWS:
            WINDOWS.remove(self)
            WINDOWS.append(self)
        if ev.type() == QtCore.QEvent.ActivationChange and self.isActiveWindow() and hasattr(self, "panes"):
            for p in self.panes:
                v = p.view() if p.isVisible() else None
                if v is not None:
                    v.svn_changed()
        super().changeEvent(ev)

    # ---------------------------------------------------------- 마우스 뒤로/앞으로 (앱 전체 이벤트 필터)
    def eventFilter(self, obj, ev):
        t = ev.type()
        if t != QtCore.QEvent.MouseButtonPress and t != QtCore.QEvent.KeyPress:
            return False
        if t == QtCore.QEvent.KeyPress and ev.key() == Qt.Key_Escape and obj is getattr(self, "gsearch", None):
            self.gsearch.clear()
            v = self.pane().view()
            if v:
                v.view().setFocus()
            return True
        # 검색(필터)칸이 열려 있을 때 그 밖 어디든(탭줄·머리줄·다른 칸 등) 누르면 접음 (글자가 있으면 그대로)
        if t == QtCore.QEvent.MouseButtonPress and isinstance(obj, QtWidgets.QWidget) and hasattr(self, "panes"):
            for p in self.panes:
                if p.filt.isVisible() and not any(x is obj or x.isAncestorOf(obj) for x in (p.filt, p.btn_find, p.btn_deep)):
                    p.close_filter_if_empty()
        if t == QtCore.QEvent.MouseButtonPress and ev.button() in (Qt.BackButton, Qt.ForwardButton):
            kind, back = T("마우스 버튼"), ev.button() == Qt.BackButton
        elif t == QtCore.QEvent.KeyPress and ev.key() in (Qt.Key_Back, Qt.Key_Forward):
            kind, back = T("브라우저 키"), ev.key() == Qt.Key_Back
        else:
            return super().eventFilter(obj, ev)
        w = obj if isinstance(obj, QtWidgets.QWidget) else None
        if w is None or w.window() is not self:
            return super().eventFilter(obj, ev)
        p = w
        while p is not None and not isinstance(p, Pane):
            p = p.parentWidget()
        pane = p or self.pane()
        log.info("뒤로/앞으로 입력: %s %s (위젯 %s) → 칸 %d", kind, "뒤로" if back else "앞으로", type(obj).__name__, pane.idx + 1)
        v = pane.view()
        if v:
            v.go_back() if back else v.go_fwd()
        return True

    # ---------------------------------------------------------- 단축키
    def apply_keys(self):
        """설정의 단축키를 적용 (창 전체 = QShortcut, 파일 목록 = VIEW_KEYS 표)"""
        km = keymap.current(SETTINGS["keys"])
        for s in self.shortcuts:
            s.setEnabled(False)
            s.deleteLater()
        self.shortcuts = []
        VIEW_KEYS.clear()
        for a, keys in km.items():
            for k in keys:
                if keymap.SCOPE[a] == "view":
                    VIEW_KEYS[k] = a
                elif a in self.win_actions:
                    s = QtGui.QShortcut(QtGui.QKeySequence(k), self, self.win_actions[a])
                    self.shortcuts.append(s)
        log.info("단축키 적용: 창 %d개, 목록 %d개, 바꾼 것 %s", len(self.shortcuts), len(VIEW_KEYS), SETTINGS["keys"])

    def open_keys(self):
        dlg = keymap.KeyDialog(SETTINGS["keys"], self)
        if dlg.exec() and dlg.result_keys is not None:
            SETTINGS["keys"] = dlg.result_keys
            for w in WINDOWS or [self]:
                w.apply_keys()
            self.show_notice(T("단축키를 저장했습니다  ✕"), ms=1000)

    def toggle_breadcrumb(self):
        SETTINGS["breadcrumb"] = not SETTINGS["breadcrumb"]
        for p in self.all_panes():
            p.set_breadcrumb(SETTINGS["breadcrumb"])
        log.info("경로 버튼(브레드크럼) %s", SETTINGS["breadcrumb"])

    # ---------------------------------------------------------- 닫은 탭 다시 열기 / 다른 칸
    def reopen_tab(self, k=None, pane=None):
        if not self.closed_tabs:
            return
        k = len(self.closed_tabs) - 1 if k is None else k
        pidx, path = self.closed_tabs[k]
        del self.closed_tabs[k]
        target = pane or (self.panes[pidx] if pidx < len(self.panes) and self.panes[pidx].isVisible() else self.pane())
        if path != THIS_PC and not os.path.isdir(path):
            self.show_notice(T('⚠ 폴더가 없어 다시 열 수 없습니다: {0}  ✕').format(path))
            return
        log.info("닫은 탭 다시 열기 pane=%d %s", target.idx, path)
        target.add_tab(path)

    def open_guide(self):
        """사용법 창 (그림 + 설명, 페이지 넘기기)"""
        import guide
        g = guide.GuideWindow()
        g.setStyleSheet(self.styleSheet())
        fg = self.frameGeometry()
        g.move(fg.center() - QtCore.QPoint(g.width() // 2, g.height() // 2))
        g.show()
        g.activateWindow()
        return g

    def open_overlay_order(self):
        """윈도우 겹침 아이콘 순서 정리 창 — .reg 를 만들어 주고 탐색기로 보여줌 (적용은 사용자가 더블클릭)"""
        import overlayorder
        for tw in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(tw, overlayorder.OverlayOrder) and tw.isVisible():
                tw.raise_()
                tw.activateWindow()
                return tw
        out = os.path.join(os.path.dirname(report_dir()), "overlay_reg")

        def saved(path):
            try:
                subprocess.Popen(["explorer.exe", "/select,", path])
            except OSError:
                log.exception("탐색기 열기 실패 %s", path)
        w = overlayorder.OverlayOrder(out, on_saved=saved)
        w.setStyleSheet(self.styleSheet())
        w.show()
        w.activateWindow()
        return w

    def open_fav_organizer(self, select_group=None):
        """즐겨찾기 정리 창 (하나만). 띄워 둔 채로 4Dir 계속 사용 가능"""
        for tw in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(tw, favorg.FavOrganizer) and tw.isVisible():
                tw.raise_()
                tw.activateWindow()
                return tw
        w = favorg.FavOrganizer(FAV, SETTINGS, select_group=select_group)
        w.setStyleSheet(self.styleSheet())
        w.show()
        w.activateWindow()
        return w

    def open_batch_rename(self, paths):
        """이름 일괄 변경 창 (BatchNamer 방식). 적용하면 되돌리기 기록 + 보이는 칸 새로 읽기"""
        import batchrename

        def done(pairs):
            push_undo("batch", pairs, T('이름 일괄 변경 {0}개').format(len(pairs)))
            for p in self.all_panes():
                v = p.view()
                if v is not None and v.active and v.path != THIS_PC:
                    v.reload("batch-rename")
        w = batchrename.BatchRename(paths, SETTINGS, on_done=done)
        w.setStyleSheet(self.styleSheet())
        w.show()
        w.activateWindow()
        log.info("이름 일괄 변경 창 %d개", len(paths))
        return w

    def undo(self, page):
        """Ctrl+Z: 마지막 작업 되돌리기 (탐색기처럼 창 상관없이 프로그램 전체 기록에서)"""
        if not UNDO:
            page.status.emit(T("되돌릴 작업이 없습니다"))
            return
        kind, data, label = UNDO.pop()
        hwnd = page.hwnd()
        log.info("되돌리기 %s %s", kind, label)
        try:
            if kind == "rename":
                new, old = data
                if os.path.exists(new) and not os.path.exists(old):
                    os.rename(new, old)
                else:
                    raise OSError(T("파일이 바뀌어 되돌릴 수 없습니다"))
            elif kind == "newfolder":
                if os.path.isdir(data) and not os.listdir(data):
                    shellops.delete(hwnd, [data], silent=True)
                else:
                    raise OSError(T("폴더가 비어 있지 않아 되돌리지 않습니다"))
            elif kind == "move":
                by_dir = {}
                for cur, orig in data:
                    if os.path.exists(cur):
                        by_dir.setdefault(os.path.dirname(orig), []).append(cur)
                for d, items in by_dir.items():
                    shellops.copy_or_move(hwnd, items, d, True)
            elif kind == "batch":
                import batchrename
                if not all(os.path.exists(new) for new, _old in data):
                    raise OSError(T("파일이 바뀌어 되돌릴 수 없습니다"))
                if batchrename.rename_all(list(data)) is None:
                    raise OSError(T("되돌리다 오류 — 로그 확인"))
            elif kind == "copy":
                items = [p for p in data if os.path.exists(p)]
                if items:
                    shellops.delete(hwnd, items)   # 휴지통 (윈도우 확인 창은 설정대로)
            elif kind == "delete":
                # 휴지통에서 복원: 휴지통 훑기가 수 초 걸릴 수 있어(실측 2.6초) 뒤에서. 끝나면 상태줄에 결과 (감시가 목록 갱신)
                page.status.emit(T("↶ 휴지통에서 되돌리는 중… {0}").format(label))

                sig = _undo_signal()

                def run(paths=list(data), label=label):
                    ok, miss = shellops.restore_from_recycle(paths)
                    # 상태줄은 복원 직후 목록 새로고침이 덮어써서 안 보임 → 알림 줄로 (화면 스레드에서)
                    sig.done.emit(T('↶ 되돌림: {0}').format(label) if not miss else
                                  T('⚠ 휴지통에서 {0}개를 찾지 못했습니다 (휴지통을 비웠거나 이미 복원됨)').format(len(miss)))
                import threading
                threading.Thread(target=run, daemon=True, name="undo-delete").start()
                return
            page.status.emit(T('↶ 되돌림: {0}').format(label))
        except OSError as ex:
            log.warning("되돌리기 실패 %s: %s", label, ex)
            page.status.emit(T('⚠ 되돌리기 실패: {0} — {1}').format(label, ex))
        for p in self.all_panes():   # 감시가 꺼진 칸도 곧바로 보이게
            v = p.view()
            if v is not None and v.active and v.path != THIS_PC and not is_search(v.path):
                v.reload("undo")

    def all_panes(self):
        """열린 모든 창의 칸 (보기 옵션처럼 프로그램 전체에 걸리는 설정을 바꿀 때)"""
        return [p for w in WINDOWS for p in getattr(w, "panes", [])] or self.panes

    def open_window(self, path):
        """탭 우클릭 '새 창으로 열기' — 이 창과 똑같은 창, 칸 1개 + 그 폴더 (같은 프로그램 안 → 바로 열림)"""
        t0 = time.perf_counter()
        w = Main(open_path=path, src=self)
        w.show()
        w.activateWindow()
        log.info("새 창 열기 %.0fms %s", (time.perf_counter() - t0) * 1000, path)
        return w

    def other_pane(self, cur):
        """다른 칸으로 보낼 대상: 직전에 쓰던 칸(보이면), 아니면 보이는 다른 칸 중 첫 번째"""
        if self.prev_pane is not None and self.prev_pane is not cur and self.prev_pane.isVisible():
            return self.prev_pane
        for p in self.panes:
            if p is not cur and p.isVisible():
                return p
        return None

    def toggle_multi(self):
        SETTINGS["allow_multi"] = not SETTINGS["allow_multi"]
        log.info("창 여러 개 허용 %s", SETTINGS["allow_multi"])
        self.show_notice((T("창 여러 개 열기 허용: 다시 실행하면 새 창이 열립니다") if SETTINGS["allow_multi"]
                          else T("창 하나만: 다시 실행하면 이 창이 앞으로 나옵니다")) + "  ✕")

    # ---------------------------------------------------------- 하나만 실행: 두 번째 실행이 보낸 신호 받기
    def start_single_server(self):
        """하나만 실행용 통신 시작 (프로그램에 하나 — 창을 닫아도 유지)"""
        global SERVER
        if SERVER is not None:
            return
        from PySide6 import QtNetwork
        SERVER = QtNetwork.QLocalServer(QtWidgets.QApplication.instance())
        if not SERVER.listen(SINGLE_NAME):
            QtNetwork.QLocalServer.removeServer(SINGLE_NAME)   # 비정상 종료로 남은 이름 정리
            if not SERVER.listen(SINGLE_NAME):
                log.warning("단일 실행 서버 시작 실패: %s", SERVER.errorString())
                return
        SERVER.newConnection.connect(_on_second_launch)
        log.info("단일 실행 서버 대기 %s", SINGLE_NAME)

    def bring_front(self, path=None):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        try:
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except Exception:
            pass
        if path and os.path.isdir(path):
            self.pane().add_tab(path)

    # ---------------------------------------------------------- 색상·항상 위
    def apply_theme(self, app_wide=True):
        """app_wide=False: 프로그램 전체 색(팔레트)은 이미 맞음 → 이 창 스타일만 (새 창 열 때 0.6초 절약, 실측)"""
        mode = SETTINGS["theme_mode"]
        dark = ui_parts.system_dark() if mode == "system" else mode == "dark"
        SETTINGS.data["dark"] = dark
        app = QtWidgets.QApplication.instance()
        # Qt 기본 스타일도 같은 쪽으로 (윈도우가 어둡게인데 '밝게'를 고른 경우 등)
        hints = app.styleHints()
        if app_wide and hasattr(hints, "setColorScheme"):
            hints.setColorScheme(Qt.ColorScheme.Unknown if mode == "system" else
                                 Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light)
        if app_wide:
            ui_parts.apply_palette(app, dark)
            i18n.apply_font(app)   # 스타일을 바꾸면 메뉴 글꼴이 윈도우 기본으로 돌아감(실측)
        self.setStyleSheet(ui_parts.build_style(SETTINGS[SETTINGS.theme_key()], dark))
        if getattr(self, "mon", None):
            self._update_mon()

    def _on_svn_changed(self, root):
        """작업 폴더 안 변경(실시간)·처음 훑기 끝 → 그 안을 보고 있는 탭의 SVN 배지만 다시 읽음"""
        rc = os.path.normcase(root)
        for p in self.panes:   # 창마다 이 신호를 따로 받음 → 자기 칸만
            v = p.view() if p.isVisible() else None
            if v is not None and v.path and os.path.normcase(v.path).startswith(rc) and OPTS["svn_status"]:
                v.refresh_svn()

    def set_chrome_collapsed(self, on, save=True):
        """상단 메뉴줄 + 즐겨찾기 바 접기 → 칸 위에 얇은 줄 하나만 (누르거나 Ctrl+Shift+M 으로 다시 펼침)"""
        self.topbar.setVisible(not on)
        self.favbar.setVisible(not on)
        self.chrome_strip.setVisible(on)
        if save:
            SETTINGS["chrome_collapsed"] = on
            log.info("메뉴·즐겨찾기 %s", "접음" if on else "펼침")

    def set_theme_mode(self, mode):
        SETTINGS["theme_mode"] = mode
        for k, w in enumerate(WINDOWS or [self]):
            w.apply_theme(app_wide=k == 0)
        log.info("화면 테마 %s → 어둡게=%s", mode, SETTINGS["dark"])

    def _on_system_scheme(self, *_):
        """윈도우 '앱 모드'가 바뀜 → '시스템 설정 따름'일 때만 따라감"""
        if SETTINGS["theme_mode"] == "system" and ui_parts.system_dark() != SETTINGS["dark"]:
            for k, w in enumerate(WINDOWS or [self]):   # 창이 여러 개면 처음 받은 창이 모두 바꿈
                w.apply_theme(app_wide=k == 0)
            log.info("윈도우 앱 모드 바뀜 → 어둡게=%s", SETTINGS["dark"])

    def set_language(self, code):
        """화면 언어 저장 → 다시 시작하면 적용 (None = 윈도우 표시 언어 따름)"""
        SETTINGS["lang"] = code
        new = code or i18n.windows_lang()
        log.info("언어 선택 %s (적용될 언어 %s, 지금 %s)", code, new, i18n.lang)
        if new != i18n.lang:
            # 안내는 '새 언어'로 (사용자가 읽을 수 있게) — 그 언어 파일에서 직접 찾음
            ko = "4Dir 를 다시 시작하면 언어가 바뀝니다  ✕"
            msg = ko if new == "ko" else (i18n._load(new).get(ko) or i18n._load("en").get(ko) or T(ko))
            self.show_notice(msg, sticky=True)   # 다시 시작해야 하는 안내 — 남겨 둠

    def toggle_dark(self):
        self.set_theme_mode("light" if SETTINGS["dark"] else "dark")

    def open_colors(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(T("색상 설정 (Colors)"))
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(QtWidgets.QLabel(T("각 영역 색을 바꿉니다. 색 선택 창 아래 '알파'로 투명도도 바꿀 수 있습니다. 바로 적용됩니다.")))
        grid = QtWidgets.QGridLayout()
        lay.addLayout(grid)
        tk = SETTINGS.theme_key()   # 지금 켜진 테마(밝게/어둡게)의 색을 고침
        theme = dict(SETTINGS[tk])
        swatches = {}

        def paint(key):
            q = ui_parts.qcolor(theme[key])
            swatches[key].setStyleSheet(
                f"background:{ui_parts.css(theme[key])}; border:1px solid #888; min-width:70px; min-height:20px;")
            swatches[key].setText(f"{q.name()}  α{q.alpha()}")

        def pick(key):
            q = QtWidgets.QColorDialog.getColor(ui_parts.qcolor(theme[key]), dlg, ui_parts.THEME_KEYS[key][0],
                                                QtWidgets.QColorDialog.ShowAlphaChannel)
            if q.isValid():
                theme[key] = ui_parts.hexa(q)
                paint(key)
                SETTINGS[tk] = dict(theme)
                self.apply_theme()
                log.info("색상 변경 %s=%s", key, theme[key])

        for r, (key, (label, _l, _d)) in enumerate(ui_parts.THEME_KEYS.items()):
            grid.addWidget(QtWidgets.QLabel(label), r, 0)
            b = QtWidgets.QPushButton()
            b.clicked.connect(lambda _=False, k=key: pick(k))
            swatches[key] = b
            grid.addWidget(b, r, 1)
            paint(key)

        def reset():
            theme.update({k: (v[2] if SETTINGS["dark"] else v[1]) for k, v in ui_parts.THEME_KEYS.items()})
            for k in swatches:
                paint(k)
            SETTINGS[tk] = dict(theme)
            self.apply_theme()
            log.info("색상 기본값 복원")
        row = QtWidgets.QHBoxLayout()
        rb = QtWidgets.QPushButton(T("기본값으로"))
        rb.clicked.connect(reset)
        cb = QtWidgets.QPushButton(T("닫기"))
        cb.clicked.connect(dlg.accept)
        row.addWidget(rb)
        row.addStretch(1)
        row.addWidget(cb)
        lay.addLayout(row)
        dlg.exec()

    def toggle_on_top(self):
        on = not SETTINGS["on_top"]
        SETTINGS["on_top"] = on
        # QWidget.setWindowFlag 는 창을 숨기고 새로 만들어 깜박임 → 떠 있는 창(QWindow)의 속성만 바로 바꿈
        self.windowHandle().setFlag(Qt.WindowStaysOnTopHint, on)
        self.act_top.setChecked(on)
        log.info("항상 위 %s", on)

    # ---------------------------------------------------------- 작업 공간(이름 붙인 창 구성) 저장/불러오기
    def _ws_list(self):
        os.makedirs(WS_DIR, exist_ok=True)
        out = []
        for fn in sorted(os.listdir(WS_DIR), key=lambda n: os.path.getmtime(os.path.join(WS_DIR, n)), reverse=True):
            if fn.endswith(".json"):
                out.append((fn[:-5], os.path.join(WS_DIR, fn)))
        return out

    def save_workspace(self):
        name, ok = QtWidgets.QInputDialog.getText(self, T("현재 창 구성 저장"), T("이름 (같은 이름이면 덮어씀):"),
                                                  text=time.strftime(T("작업_%m%d_%H%M")))
        name = "".join(c for c in name.strip() if c not in '\\/:*?"<>|')
        if not ok or not name:
            return
        os.makedirs(WS_DIR, exist_ok=True)
        p = os.path.join(WS_DIR, name + ".json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.collect_state(), f, ensure_ascii=False, indent=1)
        log.info("작업 공간 저장 %s", p)
        self.show_notice(T("창 구성 '{0}' 저장됨  ✕").format(name), ms=1000)   # 저장 알림은 1초 (10/5 사용자 요청)

    def load_workspace(self, name, path):
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            log.exception("작업 공간 읽기 실패 %s", path)
            return
        self.sessions.snapshot(self.collect_state(), force=True)   # 불러오기 전 지금 상태 보관
        log.info("작업 공간 불러오기 %s", path)
        self.apply_state(st, geometry=False)
        self.save_state()
        self.show_notice(T("창 구성 '{0}' 불러옴 (이전 상태는 '자동 기록'에 보관)  ✕").format(name))

    def delete_workspace(self, name, path):
        if QtWidgets.QMessageBox.question(self, T("삭제"), T("저장된 창 구성 '{0}' 을(를) 지울까요?").format(name)) == QtWidgets.QMessageBox.Yes:
            os.remove(path)
            log.info("작업 공간 삭제 %s", path)

    def _fill_layout_menu(self, m):
        m.clear()
        for key, label in LAYOUTS:
            a = m.addAction(layout_icon(key), label, lambda k=key: self.set_layout(k, equalize=True))
            a.setCheckable(True)
            a.setChecked(self.layout_mode == key)
        m.addSeparator()
        g = parse_grid(self.layout_mode)
        a = m.addAction(layout_icon(self.layout_mode if g else grid_key(3, 3)),
                        T('직접 지정 (지금 가로 {0} x 세로 {1})…').format(g[0], g[1]) if g else T("직접 지정 (가로 x 세로)…"), self.open_grid_dialog)
        a.setCheckable(True)
        a.setChecked(bool(g))

    def open_grid_dialog(self):
        """가로 x 세로 칸 수를 입력받아 나눔 (최대 5 x 4)"""
        g = parse_grid(self.layout_mode)
        if not g:   # 지금 미리 정한 배치면 그 모양에 가까운 값으로 시작
            rows = layout_rows(self.layout_mode) or [[0]]
            g = (max(len(r) for r in rows), len(rows))
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(T("칸 나누기 직접 지정 (Custom Layout)"))
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(QtWidgets.QLabel(T('가로(왼쪽→오른쪽) 칸 수와 세로(위→아래) 줄 수를 정합니다. 최대 가로 {0} x 세로 {1}.').format(MAX_COLS, MAX_ROWS)))
        form = QtWidgets.QFormLayout()
        sc, sr = QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
        sc.setRange(1, MAX_COLS)
        sr.setRange(1, MAX_ROWS)
        sc.setValue(g[0])
        sr.setValue(g[1])
        form.addRow(T("가로 칸 수 (Columns)"), sc)
        form.addRow(T("세로 줄 수 (Rows)"), sr)
        lay.addLayout(form)
        prev = QtWidgets.QLabel()
        prev.setAlignment(Qt.AlignCenter)
        lay.addWidget(prev)

        def upd():
            prev.setPixmap(layout_icon(grid_key(sc.value(), sr.value()), 110, 86).pixmap(110, 86))
            prev.setToolTip(T('총 {0}칸').format(sc.value() * sr.value()))
            ok.setText(T('적용 (총 {0}칸)').format(sc.value() * sr.value()))
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        ok = bb.button(QtWidgets.QDialogButtonBox.Ok)
        ok.setMinimumWidth(130)
        bb.button(QtWidgets.QDialogButtonBox.Cancel).setText(T("취소"))
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        sc.valueChanged.connect(upd)
        sr.valueChanged.connect(upd)
        upd()
        if dlg.exec():
            log.info("레이아웃 직접 지정 가로 %d x 세로 %d", sc.value(), sr.value())
            self.set_layout(grid_key(sc.value(), sr.value()), equalize=True)
        else:   # 취소 → 툴바 체크를 원래 레이아웃으로
            self.set_layout(self.layout_mode)

    def _fill_fav_menu(self, m):
        fill_fav_menu(m, self.open_fav, None)
        m.addSeparator()
        v = self.pane().view()
        a = m.addAction(T("현재 폴더를 즐겨찾기에 추가 (Ctrl+D)"), lambda: FAV.add(v.path))
        a.setEnabled(bool(v) and v.path != THIS_PC)

        def reimport():
            n = FAV.reimport()
            self.show_notice(T('윈도우 탐색기 즐겨찾기에서 {0}개 가져옴 (이미 있던 것은 건너뜀)  ✕').format(n))
        m.addSeparator()
        m.addAction(T("즐겨찾기 정리…"), self.open_fav_organizer)
        m.addAction(T("윈도우 탐색기 즐겨찾기 가져오기 (선택)"), reimport)

    def _fill_session_menu(self, m):
        m.clear()
        m.addAction(T("현재 창 구성 저장…"), self.save_workspace)
        ws = self._ws_list()
        load = m.addMenu(T("불러오기"))
        dele = m.addMenu(T("삭제"))
        if not ws:
            for mm in (load, dele):
                a = mm.addAction(T("(저장된 창 구성 없음)"))
                a.setEnabled(False)
        for name, path in ws:
            load.addAction(name, lambda n=name, p=path: self.load_workspace(n, p))
            dele.addAction(name, lambda n=name, p=path: self.delete_workspace(n, p))
        m.addSeparator()
        auto = m.addMenu(T("자동 기록에서 복구 (크래시 대비)"))
        snaps = self.sessions.list(visible=state_panes)
        if not snaps:
            a = auto.addAction(T("(보관된 기록 없음)"))
            a.setEnabled(False)
        for label, path in snaps:
            auto.addAction(label, lambda p=path: self.restore_session(p))
        auto.addSeparator()
        auto.addAction(T("자동 기록 폴더 열기"), lambda: os.startfile(session.SESS_DIR))

    def _fill_tool_menu(self, m):
        m.clear()
        m.addAction(T("사용법…"), self.open_guide)
        m.addSeparator()
        m.addAction(T("Explorer Check (탐색기 점검)"), self.open_check)
        m.addAction(T("이름 일괄 변경…"), lambda: self.open_batch_rename(self.pane().view().selected_paths() if self.pane().view() else []))
        m.addAction(T("단축키 설정…"), self.open_keys)
        m.addAction(T("검색 범위 설정…"), self.open_search_roots)
        m.addAction(T("로그 폴더 열기"), lambda: os.startfile(LOG_DIR))
        m.addAction(T("문제 보고용 로그 저장… (4Dir 폴더의 reports 에 zip)"), self.save_report)
        m.addAction(T("겹침 아이콘 순서 정리 (윈도우)…"), self.open_overlay_order)
        m.addSeparator()
        m.addAction(T("새 버전 확인"), lambda: start_update_check(self, manual=True))
        a = m.addAction(T("시작할 때 새 버전 확인 (하루 한 번)"))
        a.setCheckable(True)
        a.setChecked(bool(SETTINGS["update_check"]))
        a.toggled.connect(lambda on: SETTINGS.__setitem__("update_check", on))
        a = m.addAction(T("재부팅 후 다시 열기 (켜 둔 채 윈도우를 끄면 다음 로그인 때)"))
        a.setCheckable(True)
        a.setChecked(bool(SETTINGS["resume_after_reboot"]))
        a.toggled.connect(lambda on: (SETTINGS.__setitem__("resume_after_reboot", on), log.info("재부팅 후 다시 열기 %s", on)))
        if SITE_URL or DONATE_URL:   # 주소가 정해진 것만 (0.9.50: 후원은 사이트 없이도)
            m.addSeparator()
            if SITE_URL:
                m.addAction(T("4Dir 홈페이지"), lambda: open_link(SITE_URL, "홈페이지"))
            m.addAction(T("♥ 후원하기 (개발 응원)"), lambda: open_link(DONATE_URL or SITE_URL + "#donate", "후원"))

    def save_report(self):
        """로그·설정·화면 상태·버전 정보를 zip 하나로 4Dir 폴더의 reports 에 저장 → 사용자는 이 파일만 보내면 됨.
        (10/6 사용자: 바탕 화면에 두면 지저분함) 프로그램 폴더에 못 쓰면(예: Program Files) 내 로컬 앱 데이터Dir
eports.
        색인(검색 이름 목록)·즐겨찾기·세션 기록은 넣지 않음"""
        import zipfile
        import platform
        desk = report_dir()
        name = T('4Dir_문제보고_v{0}_{1}.zip').format(QE_VERSION, time.strftime('%Y%m%d_%H%M%S'))
        out = os.path.join(desk, name)
        if QtWidgets.QMessageBox.question(
                self, T("문제 보고용 로그 저장"),
                T('다음을 zip 하나로 저장합니다.\n\n  · 실행 기록(로그)\n  · 설정과 지금 칸·탭 구성 (열어 둔 폴더 경로가 들어 있습니다)\n  · 4Dir·윈도우·파이썬 버전, 화면 배율\n\n검색 색인·즐겨찾기·파일 내용은 넣지 않습니다.\n\n저장 위치: {0}').format(out)) != QtWidgets.QMessageBox.Yes:
            return
        try:
            self.save_state()
            scr = self.screen()
            info = [f"4Dir {QE_VERSION}", f"저장 시각 {time.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"윈도우 {platform.platform()} ({platform.version()})", f"파이썬 {sys.version.split()[0]} {sys.executable}",
                    f"Qt {QtCore.qVersion()}", f"실행 위치 {BIN_DIR}",
                    f"화면 {scr.size().width()}x{scr.size().height()} 배율 {scr.devicePixelRatio():.2f} DPI {scr.logicalDotsPerInch():.0f}" if scr else "화면 ?",
                    f"레이아웃 {self.layout_mode}, 칸 {len(self.panes)}개", f"화면 테마 {SETTINGS['theme_mode']} 어둡게={SETTINGS['dark']}",
                    f"검색 색인 {SEARCH.state if SEARCH else '-'} {SEARCH.count() if SEARCH else 0}개"]
            n = 0
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("정보.txt", "\r\n".join(info))
                for f in sorted(os.listdir(LOG_DIR)):
                    if f.lower().startswith("4dir") or f.lower().endswith(".log") or ".log." in f.lower():
                        z.write(os.path.join(LOG_DIR, f), "log/" + f)
                        n += 1
                # 설정은 파일이 없을 수도 있으니(아무것도 안 바꾼 경우) 지금 쓰는 값을 그대로 기록
                z.writestr("4Dir_settings.json", json.dumps(SETTINGS.data, ensure_ascii=False, indent=1))
                if os.path.exists(STATE_FILE):
                    z.write(STATE_FILE, "4Dir_state.json")
            log.info("문제 보고용 로그 저장 %s (로그 %d개, %.0fKB)", out, n, os.path.getsize(out) / 1024)
        except Exception as e:
            log.exception("문제 보고용 로그 저장 실패")
            QtWidgets.QMessageBox.warning(self, T("문제 보고용 로그 저장"), T('저장하지 못했습니다:\n{0}').format(e))
            return
        # 저장한 파일을 윈도우 탐색기 새 창에서 선택해 보여줌 (10/6 사용자: 쓰던 탭을 건드리지 말 것)
        log.info("문제 보고 파일을 탐색기에서 보여줌 %s", out)
        try:
            subprocess.Popen(["explorer.exe", "/select,", out])
        except OSError:
            log.exception("탐색기 열기 실패 %s", out)
        QtWidgets.QApplication.clipboard().setText(out)   # 경로를 바로 붙여 넣을 수 있게 (메일·대화창)
        # v0.9.61: 깃허브 계정 없이도 보낼 수 있게 '메일로 보내기' (support@4dir.net) — 메일 창 + 탐색기에서 zip 끌어 넣기
        self.show_notice(T('저장했고 파일 경로를 복사했습니다: {0} — 이 파일을 {1} 로 보내 주세요  ✕').format(out, SUPPORT_EMAIL), sticky=True,
                         action=(T("메일로 보내기"), lambda: self.mail_report(out)))

    def mail_report(self, path):
        """문제 보고 메일 창 열기 (mailto). 첨부는 메일 프로그램 규칙상 자동으로 못 넣음 → 탐색기에 zip 을 보여 주고 끌어 넣게 안내.
        메일 프로그램이 없으면 주소를 복사하고 알림"""
        import platform
        from urllib.parse import quote
        subject = f"4Dir v{QE_VERSION} problem report"
        body = (chr(13) + chr(10)).join([T("어떤 문제가 있었나요? (무엇을 하다가, 어떻게 됐는지)"), "", "", "----",
                             f"4Dir {QE_VERSION} / {platform.platform()}",
                             T("첨부할 파일: {0}").format(os.path.basename(path)),
                             T("(탐색기에 보이는 이 zip 파일을 메일 창에 끌어다 놓아 주세요)")])
        url = f"mailto:{SUPPORT_EMAIL}?subject={quote(subject)}&body={quote(body)}"
        ok = QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
        log.info("문제 보고 메일 창 열기 %s → %s", SUPPORT_EMAIL, ok)
        try:
            subprocess.Popen(["explorer.exe", "/select,", path])
        except OSError:
            log.exception("탐색기 열기 실패 %s", path)
        if not ok:
            QtWidgets.QApplication.clipboard().setText(SUPPORT_EMAIL)
            self.show_notice(T("메일 프로그램을 열지 못했습니다. 주소를 복사했습니다: {0} — 쓰시는 메일에서 zip 을 첨부해 보내 주세요  ✕").format(SUPPORT_EMAIL), sticky=True)

    def open_fav(self, path):
        new_tab = bool(QtWidgets.QApplication.keyboardModifiers() & Qt.ControlModifier)
        log.info("즐겨찾기 열기 pane=%d %s new_tab=%s", self.pane().idx, path, new_tab)
        self.pane().go(path, new_tab=new_tab)

    def restore_session(self, path):
        """자동 기록 복구 → 그 시점 창 구성을 새 창으로 (지금 창은 그대로)"""
        try:
            st = self.sessions.read(path)
        except Exception:
            log.exception("세션 읽기 실패 %s", path)
            self.show_notice(T("⚠ 기록을 읽을 수 없습니다  ✕"))
            return
        log.info("세션 복구 → 새 창 %s (레이아웃 %s)", path, st.get("layout"))
        w = Main(open_state=st, src=self)
        w.show()
        w.activateWindow()
        return w

    # ---------------------------------------------------------- 활성 칸
    def pane(self):
        return self.active_pane

    def _on_focus(self, old, new):
        w = new
        while w is not None and not isinstance(w, Pane):
            w = w.parentWidget()
        if w is not None and w is not self.active_pane and w.window() is self:
            self.prev_pane = self.active_pane   # F6 '다른 칸으로' 대상
            self.active_pane = w
            self._paint_active()
            if getattr(self, "preview", None) is not None:   # 미리보기 창: 다른 칸으로 옮기면 그 칸의 선택으로 (v0.9.58)
                self.preview.schedule()

    def _paint_active(self):
        for p in self.panes:
            on = p is self.active_pane
            if p.property("active") == on:
                continue
            p.setProperty("active", on)
            p.style().unpolish(p)
            p.style().polish(p)
            # 선택색(진하게/옅게)이 칸의 active 속성에 달려 있어 목록 보기도 다시 입힘
            for v in p.findChildren(QtWidgets.QAbstractItemView):
                v.style().unpolish(v)
                v.style().polish(v)
                v.viewport().update()

    def _focus_pane(self, i):
        p = self.panes[i]
        if p.isVisible() and p.view():
            p.view().view().setFocus()

    def _cycle_tab(self, d):
        b = self.pane().bar
        if b.count() > 1:
            b.setCurrentIndex((b.currentIndex() + d) % b.count())

    def open_check(self):
        import explorer_check
        if getattr(self, "_check_dlg", None) is None:
            self._check_dlg = explorer_check.make_dialog(self)
        self._check_dlg.show()
        self._check_dlg.raise_()
        log.info("탐색기 점검 창 열기")

    # ---------------------------------------------------------- 레이아웃·보기 옵션
    def _ensure_panes(self, n):
        """칸을 n 개까지 만들어 둠 (직접 지정으로 칸이 늘 때). 새 칸은 '내 PC' 탭 하나, 처음엔 숨김"""
        while len(self.panes) < n:
            i = len(self.panes)
            p = Pane(i)
            p.changed.connect(self.save_timer.start)
            self.rows[_SLOT[i][0]].addWidget(p)
            p.hide()
            p.set_shown(False)
            if getattr(self, "_init_done", False):
                p.add_tab(THIS_PC, activate=False)
                p.set_shown(False)
            self.panes.append(p)
            log.info("칸 %d 만듦 (전체 %d)", i + 1, len(self.panes))

    def set_layout(self, key, equalize=False):
        rows = layout_rows(key)
        if rows is None:
            key, rows = "4", LAYOUT_ROWS["4"]
        changed = key != self.layout_mode
        self.layout_mode = key
        self._ensure_panes(max(i for row in rows for i in row) + 1)
        used = {i for row in rows for i in row}
        # 쓰는 칸을 해당 줄 앞쪽 순서대로 옮김 (insertWidget = 이미 있으면 자리 이동)
        for r, row in enumerate(rows):
            for pos, i in enumerate(row):
                if self.rows[r].indexOf(self.panes[i]) != pos:
                    self.rows[r].insertWidget(pos, self.panes[i])
        for i, p in enumerate(self.panes):
            on = i in used
            p.setVisible(on)
            p.set_shown(on)
        for r, s in enumerate(self.rows):
            s.setVisible(r < len(rows))
        if equalize and changed:
            # 메뉴로 레이아웃을 바꾸면 보이는 칸을 같은 너비·높이로
            for r, row in enumerate(rows):
                sp = self.rows[r]
                total = max(self.vert.width(), 300)
                sp.setSizes([total // len(row) if not sp.widget(j).isHidden() else 0 for j in range(sp.count())])
            h = max(self.vert.height(), 300)
            self.vert.setSizes([h // len(rows) if r < len(rows) else 0 for r in range(MAX_ROWS)])
        if key in self.layout_actions:
            self.layout_actions[key].setChecked(True)
        else:
            self.act_grid.setIcon(layout_icon(key))
            self.act_grid.setChecked(True)
        g = parse_grid(key)
        self.act_grid.setToolTip(T('레이아웃: 직접 지정 (지금 가로 {0} x 세로 {1})').format(g[0], g[1]) if g else T("레이아웃: 직접 지정 (가로 x 세로)…"))
        if not self.active_pane.isVisible():
            self.active_pane = self.panes[0]
        self._paint_active()
        log.info("레이아웃 %s", key)
        self.save_timer.start()

    def toggle_opt(self, key):
        OPTS[key] = not OPTS[key]
        log.info("보기 옵션 %s=%s", key, OPTS[key])
        if key == "svn_status":   # 즐겨찾기 바 SVN 표시도 같이 켜고 끔
            for w in WINDOWS:
                w.favbar._svn_timer.start()
        for p in self.all_panes():
            for v in p.views():
                if key == "show_hidden":
                    if v.active:
                        v.reload("hidden")
                    else:
                        v.keep_sel = None
                        v.model_.path = ""  # 다시 보일 때 새로 읽음
                elif key == "date_folders_first":
                    v.model_.sort(v.model_.sort_col, v.model_.sort_order)   # 다시 정렬
                elif key == "svn_status":
                    v.refresh_svn() if v.active else setattr(v.model_, "svn", {})
                elif key == "thumbnails":
                    v.set_mode(v.mode)
                    v.view().viewport().update()
                elif key == "vcs_overlay":
                    v.model_.ovl_on = bool(OPTS["vcs_overlay"] and v.path and v.path != THIS_PC and not is_search(v.path)
                                           and svnstat.wc_root(v.path) is None)
                    v.model_.layoutChanged.emit()
                    v.view().viewport().update()
                else:
                    v.model_.layoutChanged.emit()
                    v.view().viewport().update()
        self.save_timer.start()

    # ---------------------------------------------------------- 상태 저장/복원
    def collect_state(self):
        return {
            "version": QE_VERSION,
            "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "layout": self.layout_mode,
            "geometry": bytes(self.saveGeometry().toHex()).decode(),
            # [세로 분할, 줄1, 줄2, ...] — 줄 안 순서는 레이아웃이 정함(보이는 칸이 앞)
            "splitters": [self.vert.sizes()] + [s.sizes() for s in self.rows],
            "opts": dict(OPTS),
            # 독립 창 칸이 활성이면 저장은 메인 칸 기준 (직전 메인 칸, 없으면 1번)
            "active": self.panes.index(self.active_pane if self.active_pane in self.panes else
                                       self.prev_pane if self.prev_pane in self.panes else self.panes[0]),
            "panes": [p.state() for p in self.panes],
        }

    def save_state(self, st=None):
        if st is None and SESSION_END["on"]:
            return   # 윈도우 종료 중: 창 전부 묶음을 이미 저장함 → 남은 창의 자동 저장이 덮어쓰지 않게
        st = st or self.collect_state()
        try:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=1)
            os.replace(tmp, STATE_FILE)
            log.debug("상태 저장")
            self.sessions.snapshot(st)
        except Exception:
            log.exception("상태 저장 실패")

    def load_state(self):
        st = {}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, encoding="utf-8") as f:
                    st = json.load(f)
                log.info("상태 불러옴 %s (저장 %s)", STATE_FILE, st.get("saved"))
            except Exception:
                log.exception("상태 파일 깨짐 → 최근 세션에서 복원 시도")
                snaps = self.sessions.list()
                if snaps:
                    try:
                        st = self.sessions.read(snaps[0][1])
                    except Exception:
                        st = {}
        self.pending_windows = list(st.get("windows") or [])   # 지난번 함께 열려 있던 창들 → main() 이 엶
        self.apply_state(st, geometry=True)
        return st.get("saved", "")[11:]

    def show_notice(self, text, sticky=None, ms=5000, action=None, action2=None):
        """알림 줄. 보통 알림은 5초 뒤 저절로 닫힘, ⚠ 경고는 눌러서 닫을 때까지 남음.
        action=(버튼 글자, 함수) 이면 알림 오른쪽에 버튼 (누르면 알림 닫고 함수 실행). action2 = 그 옆 보조 버튼 (v0.9.63)"""
        self.notice.setText(text)
        self.notice.setVisible(True)
        self._notice_fn = action[1] if action else None
        self.notice_act.setText(action[0] if action else "")
        self.notice_act.setVisible(bool(action))
        self._notice_fn2 = action2[1] if action2 else None
        self.notice_act2.setText(action2[0] if action2 else "")
        self.notice_act2.setVisible(bool(action2))
        if not hasattr(self, "notice_timer"):
            self.notice_timer = QtCore.QTimer(self)
            self.notice_timer.setSingleShot(True)
            self.notice_timer.timeout.connect(self.hide_notice)
        if sticky is None:
            sticky = text.lstrip().startswith("⚠")
        if sticky:
            self.notice_timer.stop()
        else:
            self.notice_timer.start(ms)

    def hide_notice(self):
        self.notice.setVisible(False)
        self.notice_act.setVisible(False)
        self.notice_act2.setVisible(False)

    def _notice_act_clicked(self):
        fn = self._notice_fn
        self.hide_notice()
        if fn:
            log.info("알림 버튼 누름: %s", self.notice_act.text())
            fn()

    def _notice_act2_clicked(self):
        fn = self._notice_fn2
        self.hide_notice()
        if fn:
            log.info("알림 보조 버튼 누름: %s", self.notice_act2.text())
            fn()

    def apply_state(self, st, geometry=True):
        o = st.get("opts") or {}
        OPTS["show_hidden"] = bool(o.get("show_hidden", st.get("show_hidden", False)))
        OPTS["show_ext"] = bool(o.get("show_ext", True))
        OPTS["checkboxes"] = bool(o.get("checkboxes", False))
        OPTS["date_folders_first"] = bool(o.get("date_folders_first", False))
        OPTS["svn_status"] = bool(o.get("svn_status", True))
        OPTS["thumbnails"] = bool(o.get("thumbnails", True))
        OPTS["vcs_overlay"] = bool(o.get("vcs_overlay", True))
        panes = st.get("panes") or []
        lr = layout_rows(st.get("layout", "4")) or LAYOUT_ROWS["4"]
        self._ensure_panes(max(len(panes), max(i for row in lr for i in row) + 1))
        for i, p in enumerate(self.panes):
            ps = panes[i] if i < len(panes) else {}
            p.close_all()
            p.mode = ps.get("mode", "details") if ps.get("mode") in MODE_PX else "details"
            tabs = ps.get("tabs") or [THIS_PC]
            vstates = ps.get("views") or []
            for k, t in enumerate(tabs):
                if t != THIS_PC and not os.path.isdir(t):
                    log.info("저장된 탭 경로 없음 → 내 PC: %s", t)
                    t = THIS_PC
                pg = p.add_tab(t, activate=False)
                if pg is not None and k < len(vstates):
                    pg.apply_view_state(vstates[k])
            cur = min(max(ps.get("current", 0), 0), p.bar.count() - 1)
            p.bar.setCurrentIndex(cur)
            p._on_tab_changed(cur)
            if ps.get("body"):
                p.body.setSizes(ps["body"])
            p.set_sidebar(bool(ps.get("sidebar", False)), save=False)
        if geometry and st.get("geometry"):
            self.restoreGeometry(QtCore.QByteArray.fromHex(st["geometry"].encode()))
        self.set_layout(st.get("layout", "4"))
        sp = st.get("splitters")
        if sp and len(sp) >= 3:   # 예전(v0.6.4 이전) = [세로, 위 줄, 아래 줄], 지금 = [세로, 줄1..줄4]
            vs = list(sp[0]) + [0] * (MAX_ROWS - len(sp[0]))
            self.vert.setSizes(vs[:MAX_ROWS])
            for s, sizes in zip(self.rows, sp[1:]):
                if sizes:
                    s.setSizes(sizes)
        a = st.get("active", 0)
        if 0 <= a < len(self.panes) and self.panes[a].isVisible():
            self.active_pane = self.panes[a]
        self._paint_active()

    # 끌고 온 탭: 커서 모양만 '놓을 수 있음'으로. 실제 옮기기는 끌기를 시작한 칸이 놓은 위치로 처리 (Pane.finish_tab_drop)
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(TAB_MIME):
            ev.acceptProposedAction()
        else:
            super().dragEnterEvent(ev)

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(TAB_MIME):
            ev.acceptProposedAction()
        else:
            super().dragMoveEvent(ev)

    def dropEvent(self, ev):
        if ev.mimeData().hasFormat(TAB_MIME):
            ev.acceptProposedAction()
        else:
            super().dropEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        if not getattr(self, "_relaunch_set", False):   # 작업표시줄 고정 → 4Dir 실행기로 (창마다 한 번)
            self._relaunch_set = True
            set_taskbar_relaunch(self)

    def closeEvent(self, ev):
        last = not [w for w in WINDOWS if w is not self]
        st = self.collect_state()
        now = time.time()
        if SESSION_END["on"]:
            pass   # 윈도우 종료 중: 열린 창 전부를 on_session_end 가 이미 한 묶음으로 저장함 (덮어쓰지 않음)
        elif not last:
            CLOSED.append((now, self.order, st))
            del CLOSED[:-10]
            self.save_state(st)   # 하나씩 닫으면 마지막에 닫은 창이 다음 실행 때 복원됨
        else:
            # 여러 창이 한꺼번에(2초 안) 닫힘(프로그램 교체·윈도우 종료·'모든 창 닫기') → 먼저 연 창(원래 메인) 기준
            cand = sorted([c for c in CLOSED if now - c[0] < 2.0] + [(now, self.order, st)], key=lambda c: c[1])
            st = dict(cand[0][2])   # 먼저 연 창 = 메인
            if len(cand) > 1:
                # 한꺼번에 닫힘(업데이트·윈도우 종료·모든 창 닫기) → 나머지 창도 다음에 같이 다시 엶 (10/5 사용자 요청)
                st["windows"] = [c[2] for c in cand[1:]]
                log.info("한꺼번에 닫힘(%d개) → 먼저 연 창(%d번)이 메인, 나머지 %d개도 다음에 같이 엶",
                         len(cand), cand[0][1], len(cand) - 1)
            self.save_state(st)
        if not SESSION_END["on"]:
            self.sessions.snapshot(st, force=True)
            if last:
                runonce_set(False)   # 사용자가 직접 끔 → 다음 로그인 때 다시 열지 않음 (종료가 취소됐던 흔적 정리)
        for p in self.panes:
            for v in p.views():
                v.set_active(False)
        self.mon_timer.stop()
        if self.mon:
            self.mon.close()
        for p in self.panes:
            for v in p.views():
                v.cancel_jobs()
        if self.favbar.rebuild in FAV.listeners:
            FAV.listeners.remove(self.favbar.rebuild)
        if self in WINDOWS:
            WINDOWS.remove(self)
        if last:   # 마지막 창 → 프로그램 전체 정리 (색인·SVN 감시)
            for tw in QtWidgets.QApplication.topLevelWidgets():   # 이름 일괄 변경·사용법 창도 같이 (남은 프로세스 없게)
                if tw.__class__.__name__ in ("BatchRename", "GuideWindow", "FavOrganizer", "OverlayOrder") and tw.isVisible():
                    tw.close()
            global SEARCH
            if SEARCH:
                SEARCH.stop()
                SEARCH = None   # 같은 프로그램에서 창을 다시 만들면 새로 시작
            svnstat.stop_all()
            log.info("종료 (마지막 창)")
        else:
            log.info("창 닫기 (남은 창 %d개)", len(WINDOWS))
        super().closeEvent(ev)

    # ---------------------------------------------------------- 우클릭 메뉴의 하위메뉴(새로 만들기·보내기·연결 프로그램) 채우기
    def nativeEvent(self, et, message):
        try:
            m = ctypes.wintypes.MSG.from_address(int(message)).message
            if m == 0x0011:      # WM_QUERYENDSESSION — 윈도우 종료·재부팅·로그오프 (Qt commitDataRequest 와 함께, 먼저 오는 쪽)
                on_session_end()
            elif m == 0x0016 and not ctypes.wintypes.MSG.from_address(int(message)).wParam:   # WM_ENDSESSION(FALSE) = 취소됨
                on_session_end_cancelled()
        except Exception:
            log.exception("종료 알림 처리 실패")
        if shellops.ShellMenu.current is not None:
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message in shellops.MENU_MSGS:
                    handled, res = shellops.ShellMenu.forward(msg.message, msg.wParam, msg.lParam)
                    if handled and msg.message != shellops.WM_INITMENUPOPUP:
                        return True, res
            except Exception:
                log.exception("메뉴 메시지 전달 실패")
        return super().nativeEvent(et, message)


# ---------------------------------------------------------------- 윈도우 종료·재부팅 (10/12 사용자: 켜 둔 채 재부팅하면 다시 열려야 함)
SESSION_END = {"on": False}
RUNONCE_KEY = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
RUNONCE_NAME = "4Dir_resume"


def runonce_set(on):
    """다음 로그인 때 4Dir 한 번 실행 (윈도우 RunOnce — 실행되면 윈도우가 스스로 지움, 늘 남는 시작프로그램 아님)"""
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUNONCE_KEY) as k:
            if on:
                vbs = os.path.join(os.path.dirname(BIN_DIR), "4Dir.vbs")
                cmd = f'"{os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wscript.exe")}" "{vbs}"'
                winreg.SetValueEx(k, RUNONCE_NAME, 0, winreg.REG_SZ, cmd)
                log.info("다음 로그인 때 다시 열기 등록 (RunOnce) %s", cmd)
            else:
                try:
                    winreg.DeleteValue(k, RUNONCE_NAME)
                    log.info("다음 로그인 때 다시 열기 등록 지움")
                except FileNotFoundError:
                    pass
    except OSError:
        log.exception("RunOnce %s 실패", "등록" if on else "지우기")


def on_session_end(*_):
    """윈도우가 끈다고 알려 옴(WM_QUERYENDSESSION) → 열린 창 전부를 한 묶음으로 저장 + 정상 종료 표시 + 다음 로그인 때 다시 열기.
    (예전: 창이 하나씩 몇 초 간격으로 닫혀 '한꺼번에(2초)' 판정이 빠지고, 정리 중에 꺼져 비정상 종료로 오판)"""
    if SESSION_END["on"]:
        return
    SESSION_END["on"] = True
    ws = sorted(WINDOWS, key=lambda w: w.order)
    if ws:
        st = dict(ws[0].collect_state())
        if len(ws) > 1:
            st["windows"] = [w.collect_state() for w in ws[1:]]
        ws[0].save_state(st)
        ws[0].sessions.snapshot(st, force=True)
    session.mark_shutdown()
    again = bool(SETTINGS["resume_after_reboot"])   # 도구 > 재부팅 후 다시 열기
    if again:
        runonce_set(True)
    log.info("윈도우 종료·로그오프 알림 → 창 %d개 저장, 다음 로그인 때 다시 열기=%s", len(ws), again)


def on_session_end_cancelled():
    """다른 프로그램이 종료를 막아 윈도우가 안 꺼짐 → 원래대로"""
    if not SESSION_END["on"]:
        return
    SESSION_END["on"] = False
    runonce_set(False)
    session.start_running()
    log.info("윈도우 종료 취소됨 → 다시 열기 등록 지움")


def _on_second_launch():
    """다시 실행됨 → 마지막에 쓴 창을 앞으로 (경로가 오면 그 창에 새 탭)"""
    c = SERVER.nextPendingConnection()
    if c is None:
        return
    c.waitForReadyRead(500)
    try:
        msg = json.loads(bytes(c.readAll()).decode("utf-8") or "{}")
    except Exception:
        msg = {}
    c.disconnectFromServer()
    log.info("다시 실행 감지 → 마지막에 쓴 창 앞으로 %s (창 %d개)", msg, len(WINDOWS))
    if WINDOWS:
        WINDOWS[-1].bring_front(msg.get("path"))


def hand_off_to_running(arg_path):
    """창 하나만 모드: 이미 실행 중이면 그 창에 알리고 True (이 프로세스는 종료)"""
    from PySide6 import QtNetwork
    s = QtNetwork.QLocalSocket()
    s.connectToServer(SINGLE_NAME)
    if not s.waitForConnected(400):
        return False
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # 기존 창이 앞으로 나올 수 있게 허락
    except Exception:
        pass
    s.write(json.dumps({"path": arg_path}).encode("utf-8"))
    s.flush()
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    return True


def main():
    log.info("=" * 60)
    log.info("4Dir v%s 시작 python=%s pid=%d", QE_VERSION, sys.version.split()[0], os.getpid())
    arg_path = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else None
    try:  # 작업표시줄에 파이썬 아이콘 대신 4Dir 아이콘이 보이게
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QtWidgets.QApplication(sys.argv)
    if not SETTINGS["allow_multi"] and hand_off_to_running(arg_path):
        log.info("창 하나만 모드: 이미 실행 중 → 기존 창으로 넘기고 종료")
        return
    crashed = session.start_running()
    runonce_set(False)   # 남은 '다음 로그인 때 다시 열기' 정리 (RunOnce 로 켜졌으면 윈도우가 이미 지움)
    app.commitDataRequest.connect(on_session_end)   # 윈도우 종료·로그오프 알림 (Qt 세션 관리)
    start_hang_watch(app)
    app.setApplicationName("4Dir")
    app.setWindowIcon(ui_parts.app_icon())
    i18n.apply_font(app)   # 언어별 글꼴 (목록·메뉴 등 종류별 글꼴까지)
    FAV.load()
    w = Main(crashed=crashed)
    w.show()
    w.start_single_server()   # 먼저 뜬 창이 이름을 차지 → 다음 실행(창 하나만 모드)이 이 창을 앞으로 부름
    if arg_path:
        w.pane().add_tab(arg_path)
    for ws in getattr(w, "pending_windows", []):   # 지난번 한꺼번에 닫힌 창들도 그대로 다시
        try:
            x = Main(open_state=ws, restore_geometry=True)
            x.show()
        except Exception:
            log.exception("함께 닫힌 창 다시 열기 실패")
    if getattr(w, "pending_windows", None):
        log.info("지난번 창 %d개 더 다시 엶", len(w.pending_windows))
        w.raise_()
        w.activateWindow()
    QtCore.QTimer.singleShot(10000, lambda: WINDOWS and start_update_check(WINDOWS[0]))   # 새 버전 확인 (하루 한 번, 뒤에서)
    if not SETTINGS["guide_shown"]:   # 처음 실행 → 사용법 한 번 (다시 보기: 도구 > 사용법)
        def first_guide():
            SETTINGS["guide_shown"] = True
            log.info("처음 실행 — 사용법 보여줌")
            w.open_guide()
        QtCore.QTimer.singleShot(900, first_guide)
    rc = app.exec()
    # 복사해 둔 파일 목록을 창을 닫은 뒤에도 붙여넣을 수 있게 클립보드에 확정 (탐색기와 동일 동작)
    try:
        log.info("클립보드 확정 hr=%s", ctypes.windll.ole32.OleFlushClipboard())
    except Exception:
        log.exception("클립보드 확정 실패")
    POOL.waitForDone(3000)
    if THUMBS is not None:
        THUMBS.stop()
    if OVL is not None:
        OVL.stop()
    session.stop_running()
    log.info("프로세스 종료 rc=%s", rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()
