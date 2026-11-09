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
QE_VERSION = "0.9.123"   # ★공개 번호 — 공개 배포할 때만 +1 (v0.9.108 사용자 11/5: 공개 목록이 0.9.99→0.9.101→0.9.107 처럼 건너뛰지 않게)
QE_BUILD = 2             # ★빌드 번호 — 고칠 때마다 +1, 공개한 뒤 다음 고침에서 QE_VERSION+1 · QE_BUILD=1. exe 파일 버전 4번째 자리

import os
import sys
import json
import glob   # 0.9.115 기록 지우기
import re
import time
import stat
import logging
import logging.handlers
import traceback
import ctypes
import subprocess
import ctypes.wintypes
import threading
import zlib

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
if BIN_DIR not in sys.path:   # 배포판 휴대용 파이썬(._pth)은 스크립트 폴더를 자동으로 안 넣음(실측)
    sys.path.insert(0, BIN_DIR)
import datadir  # noqa: E402  0.9.114 빌드 2 (MS 스토어판 1단계): 사용자 데이터 폴더 — 압축판 = bin 그대로, 스토어판 = %LOCALAPPDATA%\4Dir
DATA_DIR = datadir.DATA_DIR
LOG_DIR = os.environ.get("QE_LOG_DIR") or os.path.join(DATA_DIR, "log")   # 시험은 따로 (실제 로그에 섞이지 않게)
STATE_FILE = os.path.join(DATA_DIR, "4Dir_state.json")
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


_FILE_LOG = [None]


def set_file_log(on):
    """로그 파일(4Dir.log) 쓰기 켜고 끄기 — 0.9.118 기록 안 남기기면 끔 (사용자 메일 11/7 Ben: 로그도 쓰면 안 됨)"""
    h = _FILE_LOG[0]
    if on and h is None:
        h = _SafeRotatingHandler(os.path.join(LOG_DIR, "4Dir.log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s", "%H:%M:%S"))
        log.addHandler(h)
        _FILE_LOG[0] = h
    elif not on and h is not None:
        log.removeHandler(h)
        h.close()
        _FILE_LOG[0] = None
        if not log.handlers:
            log.addHandler(logging.NullHandler())


def _private_at_start():
    """설정 파일을 미리 엿봐 '기록 안 남기기'면 처음부터 로그 파일을 안 만듦 (설정을 정식으로 읽기 전 줄도 남지 않게)"""
    if os.environ.get("QE_LOG_DIR"):
        return False
    try:
        import ui_parts as _up
        with open(_up.SETTINGS_FILE, encoding="utf-8") as f:
            return bool(json.load(f).get("private_mode"))
    except Exception:
        return False


if not log.handlers:
    if _private_at_start():
        log.addHandler(logging.NullHandler())
    else:
        set_file_log(True)


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
        f.write(f"\n=== 4Dir v{QE_VERSION} (빌드 {QE_BUILD}) pid={os.getpid()} 시작 {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
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


# 새 버전 알림 '받으러 가기'가 열어도 되는 곳 (v0.9.68): version.json 은 바깥에서 받는 파일 → 사이트가 털려
# page 가 file://…exe 나 다른 사이트로 바뀌어도 누르는 순간 PC 프로그램이 실행되지 않게 (10/29 사용자 승인)
SAFE_PAGE_HOSTS = {"4dir.net": "/", "www.4dir.net": "/", "github.com": "/gkstmdahr/"}


def safe_update_page(page):
    """https + 우리 사이트·우리 깃허브 주소만 그대로, 그 밖은 SITE_URL 로 바꿔 열고 기록"""
    from urllib.parse import urlsplit
    try:
        u = urlsplit(str(page or "").strip())
        prefix = SAFE_PAGE_HOSTS.get((u.hostname or "").lower())
        if u.scheme == "https" and prefix and (u.path or "/").startswith(prefix) and not u.username and not u.password \
                and u.port in (None, 443):
            return u.geturl()
    except ValueError:
        pass
    log.warning("새 버전 알림: 허용 안 된 주소 %r → %s 를 대신 엶", page, SITE_URL)
    return SITE_URL


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
    if datadir.PACKAGED:   # 0.9.114 빌드 2: 스토어판은 스토어가 업데이트함
        log.info("새 버전 확인: 스토어판이라 건너뜀 (스토어가 업데이트)")
        if manual:
            w.show_notice(T("스토어판은 Microsoft Store 가 새 버전을 자동으로 설치합니다  ✕"), ms=6000)
        return
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
        url = safe_update_page(page)
        log.info("새 버전 알림: 받으러 가기 v%s %s", new, url)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))

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
    p = os.path.join(DATA_DIR, "4Dir.ico")   # 0.9.114 빌드 2: 프로그램 폴더가 읽기 전용(스토어판)이면 데이터 폴더에
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
    if datadir.PACKAGED:   # 0.9.114 빌드 2: 스토어판은 윈도우가 앱 정보로 고정 (vbs 없음)
        return
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

import backup  # noqa: E402  (v0.9.94 설정 가져오기 — 준비된 백업을 설정 읽기 전에 바꿔 넣음)
RESTORED = backup.apply_pending(DATA_DIR)
import carryover  # noqa: E402  (v0.9.87 새 버전 폴더 첫 실행 때 이전 버전 설정 가져오기 — 설정 읽는 모듈보다 먼저)
if not datadir.PACKAGED:   # 스토어판은 설정이 버전 폴더 밖이라 이어받기 필요 없음
    carryover.run(BIN_DIR)
import shellops  # noqa: E402  (로그 설정 뒤에 import)
import favorg  # noqa: E402
import favorites  # noqa: E402
import frecent  # noqa: E402  0.9.116 자주 간 폴더
import imginspect  # noqa: E402  0.9.116 그림 자세히 보기·스포이트·두 그림 비교
import sequence  # noqa: E402  0.9.116 연번 그림 묶기·재생·MP4/GIF
import sheets  # noqa: E402  0.9.116 스프라이트 시트·자르기·밀착 인화
import pdftools  # noqa: E402  0.9.116 PDF 합치기·나누기·그림→PDF·쪽 수
import pdfedit  # noqa: E402  0.9.122 PDF 편집 (쪽 돌리기·지우기·순서·끼워 넣기 + 펜·형광펜·글상자 주석)
import datefolders  # noqa: E402  0.9.116 날짜별 폴더 정리
import oplog  # noqa: E402  0.9.116 작업 기록 보기
import gitstat  # noqa: E402  0.9.116 Git 상태 (SVN 과 같은 자리)
import grepsearch  # noqa: E402  0.9.116 파일 내용 찾기
import locksmith  # noqa: E402  0.9.116 파일을 잡고 있는 프로그램
import textdiff  # noqa: E402  0.9.116 두 글자 파일 비교
import imgedit  # noqa: E402  0.9.118 그림 편집 창
import fileutil  # noqa: E402  0.9.116 링크·경로 형식·구조만 복사·나누기/합치기
import session  # noqa: E402
import ui_parts  # noqa: E402
import keymap  # noqa: E402
import search_index  # noqa: E402
import svnstat  # noqa: E402
import thumbs  # noqa: E402
import shellprops  # noqa: E402  (v0.9.75 정렬용 셸 속성)
import vfiles  # noqa: E402  (v0.9.75 아웃룩 첨부 등 가상 파일 끌어 놓기)
import olehook  # noqa: E402  (v0.9.78 끌어 놓기 원래 데이터 직접 받기 — 웹 아웃룩 본문 이미지·여러 개)
import overlays  # noqa: E402
import i18n  # noqa: E402
import foldersize  # noqa: E402  (v0.9.89 폴더 크기)
import labels  # noqa: E402  (v0.9.89 색 라벨·탭 색)
import cloud  # noqa: E402  (v0.9.94 원드라이브 등 동기화 폴더 상태 열)
import palette  # noqa: E402  (v0.9.89 명령 찾기)
import hashview  # noqa: E402  (v0.9.89 확인값 SHA256)
import dupes  # noqa: E402  (빌드 20 중복 파일 찾기)
import archives  # noqa: E402  (빌드 20 압축 파일을 폴더처럼)
import video  # noqa: E402  (빌드 21 미리보기 동영상 — 부품은 처음 고를 때 불러옴)
import contentcmp  # noqa: E402  (v0.9.107 두 칸 비교 — 내용까지)
import memo  # noqa: E402  (v0.9.108 메모 창)
import devices  # noqa: E402  (v0.9.108 빌드 4 휴대폰 등 드라이브 글자 없는 장치)
# 0.9.109 빌드 3 (사용자 11/6 '추가 기능 전부'): 경쟁 앱 조사 후보 10개
import hexview  # noqa: E402  글자·16진수 보기 (F3)
import syncdirs  # noqa: E402  폴더 맞추기
import winhook  # noqa: E402  Win+E 로 4Dir
import ptlink  # noqa: E402  0.9.119 PowerToys 로 Win+E (26H2)
import imgbatch  # noqa: E402  그림 일괄 크기·형식
import spacemap  # noqa: E402  디스크 사용량 트리맵
import tags  # noqa: E402  태그·가상 그룹
import fileattrs  # noqa: E402  날짜·속성 일괄
import userbtns  # noqa: E402  사용자 단추
import ftpfs  # noqa: E402  FTP (archives 를 거쳐 폴더처럼)
import calc  # noqa: E402  0.9.111 계산기 (일반·회계·공학·단위)
import mediaedit  # noqa: E402  0.9.111 동영상·GIF 편집 (ffmpeg)
import toolicons  # noqa: E402  0.9.111 빌드 4 도구 아이콘
# 0.9.116 새 모듈 아이콘 (우클릭 윈도우 메뉴에서도 쓰게)
toolicons.register("imginspect", imginspect.tool_icon)
toolicons.register("imgcompare", imginspect.compare_icon)
toolicons.register("sequence", sequence.tool_icon)
toolicons.register("sheetpack", sheets.pack_icon)
toolicons.register("sheetslice", sheets.slice_icon)
toolicons.register("contact", sheets.contact_icon)
toolicons.register("pdf", pdftools.tool_icon)
toolicons.register("datefolders", datefolders.tool_icon)
toolicons.register("oplog", oplog.tool_icon)
toolicons.register("imgedit", imgedit.tool_icon)
imginspect.PREF_GET = lambda k, d=None: SETTINGS.data.get(k, d)   # 0.9.118 미리보기 상세보기 열림 상태 기억
imginspect.PREF_SET = lambda k, v: SETTINGS.__setitem__(k, v)
toolicons.register("grep", grepsearch.grep_icon)
toolicons.register("lock", locksmith.lock_icon)
toolicons.register("diff", textdiff.diff_icon)
toolicons.register("link", fileutil.link_icon)
toolicons.register("split", fileutil.split_icon)
import pinfix  # noqa: E402  0.9.112 고정 바로가기 새 버전 폴더로
import gdrive  # noqa: E402  0.9.114 구글 드라이브 백업
import funcdesc  # noqa: E402  0.9.113 빌드 2 기능 설명 (메뉴 풍선 도움말·기능 검색)
import fileicons  # noqa: E402  0.9.112 exe 등 파일마다 다른 아이콘


def ti(label, name):
    """우클릭(윈도우 메뉴) 항목 글자 + 도구 아이콘 (0.9.111 빌드 4)"""
    return {"t": label, "bmp": toolicons.hbitmap(name)}


TOOL_ICON_KEYS = [("계산기", "calc"), ("폴더 맞추기", "sync"), ("디스크 사용량 트리맵", "treemap"), ("FTP 연결", "ftp"),
                  ("태그로 보기", "tag"), ("가상 그룹", "group"), ("My메뉴 편집", "userbtn"), ("중복 파일 찾기", "dupes"),
                  ("하위 폴더 펼쳐 보기", "flat"), ("두 칸 비교", "compare"), ("패턴으로 고르기", "pattern"), ("이름 일괄 변경", "rename"),
                  ("Explorer Check", "check"), ("기능 검색", "palette")]


ACTION_ICONS = {"toggle_calc": "calc", "sync_dirs": "sync", "space_map": "treemap", "ftp_connect": "ftp", "find_dupes": "dupes",
                "flat_view": "flat", "compare": "compare", "same_folder": "compare", "select_pattern": "pattern", "batch_rename": "rename",
                "explorer_check": "check", "palette": "palette", "user_buttons": "userbtn", "img_batch": "imgbatch", "file_attrs": "attrs",
                "sha256": "sha", "view_file": "hexview"}


def action_icon(a):
    """0.9.113 기능 id → 아이콘 (My메뉴·기능 고르기). 없으면 None"""
    try:
        if a in ACTION_ICONS:
            return toolicons.icon(ACTION_ICONS[a], 16)
        if a == "toggle_memo":
            return memo_icon()
        if a.startswith("layout_") and a != "layout_custom":
            return layout_icon(a[7:])
        if a == "layout_custom":
            return layout_icon("4")
        if a == "toggle_preview":
            return preview_icon()
        if a == "toggle_chips":
            return chips_icon()
        if a == "rename":
            return toolicons.icon("rename", 16)
        n = toolicons.action_name(a)   # 0.9.116 빌드 2 (게시판: My메뉴 4Dir 기능 단추에 아이콘 없음)
        if n:
            return toolicons.icon(n, 16)
        return app_icon_small()   # 그래도 없으면 4Dir 아이콘 (빈 단추 없게)
    except Exception:
        log.exception("기능 아이콘 %s", a)
    return None


def app_icon_small():
    ic = QtGui.QIcon(os.path.join(BIN_DIR, "4Dir.ico"))
    return ic if not ic.isNull() else None


userbtns.ACTION_ICON = action_icon


# 0.9.116 빌드 2 — 깃허브 이슈 #9 (도구 ▸ 창 저장/불러오기 하위 메뉴가 안 펼쳐짐, QMenu already deleted)
# 원인(재현 qe195): PySide6 6.11 에서 m.addMenu("이름") 이 돌려준 하위 메뉴가 파이썬 소유로 잡힘.
# 'sm.aboutToShow.connect(lambda: fill(sm))' 처럼 자기 신호가 자기를 잡으면 순환 참조 → 파이썬 메모리 정리(gc)가 돌 때
# 실제 메뉴까지 지워짐 (gc.collect() 한 번에 isValid False 확인). 기능 검색이 모은 하위 메뉴 항목(QAction)도 같은 이유로 지워졌음.
# → 이름으로 만드는 하위 메뉴는 부모 메뉴를 주고 직접 만들어 붙임 (부모가 지움 = 윈도우·Qt 기본과 같음). 모든 메뉴에 한 번에 적용.
_QMENU_ADD = QtWidgets.QMenu.addMenu


def _qmenu_add(self, *a):
    if a and isinstance(a[-1], str) and (len(a) == 1 or (len(a) == 2 and isinstance(a[0], QtGui.QIcon))):
        sm = QtWidgets.QMenu(a[-1], self)
        if len(a) == 2:
            sm.setIcon(a[0])
        _QMENU_ADD(self, sm)
        return sm
    return _QMENU_ADD(self, *a)


QtWidgets.QMenu.addMenu = _qmenu_add


class _MenuTipFilter(QtCore.QObject):
    """메뉴 풍선 도움말: 설명이 있는 항목만 (Qt 기본은 설명 없으면 항목 이름을 또 보여 줌)"""

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.ToolTip and isinstance(obj, QtWidgets.QMenu):
            a = obj.actionAt(ev.pos())
            tip = a.property("qe_tip") if a is not None else None
            if tip:
                QtWidgets.QToolTip.showText(ev.globalPos(), tip, obj, obj.actionGeometry(a))
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return False


_MENU_TIP_FILTER = None


def set_menu_tips(m):
    """0.9.113 빌드 2 (사용자 11/6 '각 메뉴에도 툴팁, 무슨 기능인지 모르겠다'): 메뉴 항목에 한 줄 설명 (하위 메뉴까지)"""
    global _MENU_TIP_FILTER
    if _MENU_TIP_FILTER is None:
        _MENU_TIP_FILTER = _MenuTipFilter(QtWidgets.QApplication.instance())
    if not m.property("qe_tips"):
        m.setProperty("qe_tips", True)
        m.installEventFilter(_MENU_TIP_FILTER)
    for a in m.actions():
        if a.isSeparator():
            continue
        tip = funcdesc.tip_for(a.text(), keymap.LABEL)
        a.setProperty("qe_tip", tip or None)
        if a.menu() is not None and a.menu() is not m:
            set_menu_tips(a.menu())


def set_menu_icons(m):
    """Qt 메뉴(도구 메뉴 등) 항목 앞 글자로 도구 아이콘 붙임"""
    keys = [(T(k).replace("&", ""), n) for k, n in TOOL_ICON_KEYS]
    for a in m.actions():
        t = a.text().split("\t")[0].replace("&", "")
        for k, n in keys:
            if t.startswith(k):
                a.setIcon(toolicons.icon(n, 16))
                break
DEV_MIME = "application/x-4dir-devpaths"   # 휴대폰 안 항목 끌기 (파일 주소가 없어 4Dir 안에서만)
DEV_CLIP = {"paths": None, "cut": False, "seq": -1}   # 휴대폰 항목 복사/잘라내기 — 4Dir 안 붙여넣기용 (윈도우 클립보드엔 셸 데이터로도 넣음)
DEV_DRAG = {"paths": None}   # 4Dir 에서 끌기 시작한 휴대폰 항목 (4Dir 칸에 놓으면 이것으로 복사)


class DevSig(QtCore.QObject):
    """휴대폰 작업이 끝남(작업 스레드) → 화면 스레드에서 그 폴더를 보고 있는 칸 다시 읽기"""
    done = QtCore.Signal(str, bool, str, str)   # 다시 읽을 경로, 됐는지, 오류, 새로 생긴 이름(편집할 것)

    def __init__(self):
        super().__init__()
        self.done.connect(self._apply, Qt.QueuedConnection)

    def _apply(self, path, ok, err, edit):
        n = 0
        for w in list(WINDOWS):
            for p in w.panes:
                for v in p.views():
                    if v.path == path:
                        if edit and ok:
                            v.pending_edit = edit
                        v.reload("dev")
                        n += 1
                        if not ok and err:
                            v.status.emit("⚠ " + err)
        log.info("장치 작업 끝 → 칸 %d개 다시 읽음 (ok=%s)", n, ok)
        if n and ok:   # 빌드 18: 휴대폰(MTP)은 새 파일이 목록에 늦게 나옴(바로 읽으면 빠짐, qe177 실측) → 1.5초 뒤 한 번 더
            QtCore.QTimer.singleShot(1500, lambda: [v.reload("dev2") for w in list(WINDOWS) for p in w.panes for v in p.views() if v.path == path])


DEV_SIG = DevSig()


class QueueSig(QtCore.QObject):
    """복사 대기열이 바뀜 (빌드 20) — 작업 스레드에서 와도 화면 스레드에서 단추를 고침"""
    changed = QtCore.Signal()


QUEUE_SIG = QueueSig()
shellops.on_queue_change[0] = QUEUE_SIG.changed.emit
MEMOS = None   # memo.MemoStore — 첫 메모 창을 열 때 만듦 (모든 창 공용)
MEMO_WIN = None   # 빌드 8: 메모 창은 4Dir 창 밖 따로 창 하나 (모든 창 공용)
CALC_WIN = None   # 0.9.111 계산기 창 (모든 창 공용)
PREVIEW_WIN = None   # 빌드 18: 미리보기도 4Dir 창 밖 따로 창 하나 (모든 창 공용, 마지막으로 쓴 창의 고른 파일)


def memo_store():
    global MEMOS
    if MEMOS is None:
        MEMOS = memo.MemoStore(DATA_DIR)
        MEMOS.remind.connect(_memo_remind)
    return MEMOS


def _memo_remind(m):
    """메모 알림 시각 (빌드 13): 메모 창을 앞으로 + 그 메모 강조 + 작업 표시줄 깜빡임 + 알림 줄"""
    w = MEMO_WIN.main if MEMO_WIN is not None and MEMO_WIN.main in WINDOWS else (WINDOWS[0] if WINDOWS else None)
    if w is None:
        return
    w.set_memo(True)
    MEMO_WIN.bring_front()
    MEMO_WIN.panel.reveal(m["id"])
    QtWidgets.QApplication.alert(MEMO_WIN, 0)
    w.show_notice(T("⏰ 메모 알림: {0}").format(m.get("title") or ""), sticky=True)


class TipGate(QtCore.QObject):
    """풍선 도움말 끄기 (빌드 13 사용자: 모든 기능에 툴팁 + 옵션에서 끌 수 있게). 도구줄 » 단추(Qt 가 만듦)에도 설명"""

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.ToolTip:
            if not SETTINGS["tooltips"]:
                return True
            if isinstance(obj, QtWidgets.QToolButton) and obj.objectName() == "qt_toolbar_ext_button" and not obj.toolTip():
                obj.setToolTip(T("가려진 메뉴 더 보기"))
        return False


TIP_GATE = TipGate()
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
        "date_groups": False,   # v0.9.90 날짜별로 묶기 (오늘·어제·이번 주…, 윈도우 탐색기 '그룹화' 와 같게)
        "type_groups": False,   # 빌드 17 형식별로 묶기 (폴더·JPG·PNG…) — 날짜별 묶기와 둘 중 하나
        "type_chips": True,     # 빌드 17 칸 위 형식 단추 줄 [전체][폴더][JPG][PSD]… 누르면 그 형식만
        "chips_global": True,   # 0.9.122 사용자 11/10: 형식 단추를 칸마다 말고 맨 위 한 줄로 → 모든 칸에 같이 적용 (끄면 칸마다)
        "chip_counts": False,   # 0.9.122 사용자 11/10: 단추에 개수 표시 (기본 안 씀)
        "type_badges": True,    # 빌드 17 아이콘 보기 그림 미리보기 왼쪽 위 형식 딱지 (PSD·PNG·GIF…)
        "folder_covers": True,  # 빌드 17 아이콘 보기 폴더에 안에 든 첫 그림을 겹쳐 보여 줌 (네트워크 드라이브 제외)
        "svn_status": True,
        "thumbnails": True,
        "vcs_overlay": True}   # vcs_overlay = SVN 아닌 폴더에서 윈도우 겹침 아이콘(Git·Perforce 등) 표시   # thumbnails = 아이콘 보기에서 그림 미리보기 / 날짜 정렬 때 폴더를 위로 모을지 (기본: 섞어서 날짜순 = 윈도우와 같음)
NPANES = 6   # 처음 만들어 두는 칸 수 (위 줄 0,1,4 / 아래 줄 2,3,5). 직접 지정(가로x세로)이면 필요할 때 더 만듦
MAX_COLS, MAX_ROWS = 5, 4   # 직접 지정 최대 가로 5 x 세로 4 = 20칸
# 칸별 보기 방식
VIEW_MODES = [("details", T("자세히"), 16), ("list", T("목록"), 16), ("small", T("작은 아이콘"), 16),
              ("medium", T("보통 아이콘"), 48), ("large", T("큰 아이콘"), 96), ("xlarge", T("아주 큰 아이콘"), 256)]
MODE_PX = {k: px for k, _, px in VIEW_MODES}
# 정렬 기준 메뉴 (v0.9.75 사용자 의견 — 탐색기 순서). 10 이상 = 열이 없는 정렬(셸 속성, shellprops.py), 4 = 위치 열
SORT_COLS = [(0, T("이름")), (5, T("날짜")), (2, T("유형")), (3, T("크기")), (6, T("길이")), (7, T("만든 날짜")),
             (1, T("수정한 날짜")), (4, T("파일 위치")), (8, T("미디어 작성 날짜")), (9, T("사진 크기")), (12, T("별점")), (13, T("쪽 수"))]
# v0.9.76: 정렬 기준 = 열 번호 (열 5~9 추가, 머리글 우클릭으로 보이기). 0.9.75 에 저장된 열 없는 정렬 번호 10~14 → 새 열 번호
OLD_SORT = {13: 8, 14: 9}   # 0.9.116: 12 는 이제 별점 열 (12→7 변환은 공개 안 한 0.9.75 것이라 뺌)
#   # 0.9.109: 11 은 이제 태그 열   # v0.9.94: 10 은 이제 상태 열 — 0.9.75(공개 안 함) 의 10(날짜) 변환은 뺌
PROP_SORTS = {5: "item_date", 6: "duration", 8: "media_date", 9: "pixels", 13: "pages"}   # 뒤에서 셸 속성을 읽어야 하는 정렬
PROP_COLS = {5: "item_date", 6: "duration", 8: "media_date", 9: "dims", 13: "pages"}       # 그 값을 보여 주는 열
OPT_COLS = [10, 1, 2, 3, 5, 6, 7, 8, 9, 11, 12, 13]   # 12 = 별점 · 13 = 쪽 수 (0.9.116)
#   # 11 = 태그 (0.9.109)   # 10 = 상태(v0.9.94, 동기화 폴더에서만 보임 — 설정 status_col)   # 머리글 우클릭에서 켜고 끄는 열 (이름은 항상, 위치는 검색 결과에서만)
FAV = favorites.Favorites()
# 우클릭 메뉴에서 윈도우 자체의 '즐겨찾기에 추가(F)'(탐색기 빠른 실행 고정)와 헷갈리지 않게 ★QE 표시
QE_FAV = T("★ 4Dir 즐겨찾기")
QE_FAV_ADD = T("★ 4Dir 즐겨찾기에 추가")
SETTINGS = ui_parts.Settings()   # 색상·즐겨찾기 바 펼침·항상 위 (세션과 무관한 전역 설정)
if SETTINGS["private_mode"] and not os.environ.get("QE_LOG_DIR"):   # 0.9.118 기록 안 남기기 = 로그 파일도 안 씀 (시험 로그는 그대로)
    log.info("기록 안 남기기 켜짐 → 로그 파일 쓰기 끔")
    set_file_log(False)
WS_DIR = os.path.join(DATA_DIR, "workspaces")   # 이름 붙여 저장한 창 구성
SINGLE_NAME = "4Dir_single_" + os.environ.get("USERNAME", "user")   # 하나만 실행용 통신 이름
if datadir.PACKAGED:   # 0.9.114 빌드 3: 스토어판과 압축판이 같이 깔려 있어도 서로 넘기지 않게 (설정 폴더가 달라서)
    SINGLE_NAME += "_store"


SEARCH_PREFIX = "🔎 "   # 검색 결과 탭의 '경로' 표시: "🔎 검색어" (전체 검색) / "🔎 검색어 @ 폴더" (그 폴더 아래 찾기)
SEARCH = None          # search_index.SearchIndex (첫 창이 만듦, 모든 창이 같이 씀)
WINDOWS = []           # 열린 4Dir 창들 (Main). 순서 = 마지막에 쓴 창이 맨 뒤


def window_title():
    """0.9.115 (사용자 11/7 '제목 표시줄에 구글 로그인 상태인지 게스트인지'): 연결됨 = ☁ 메일 / 안 됨 = 게스트.
    구글 연결 준비(gdrive_client.json)가 없는 판이면 버전만"""
    t = f"4Dir v{QE_VERSION}"
    try:
        if gdrive.client(BIN_DIR) is None:
            return t
        acct = gdrive.account()
    except Exception:
        log.exception("제목: 구글 연결 상태 읽기 실패")
        return t
    return t + ("   ·   ☁ " + acct + " " + T("백업 중") if acct else "   ·   " + T("게스트 (구글 백업 안 함)"))


def gdrive_offer(w):
    """처음 한 번만: 구글 드라이브 백업 권유 창 (로그인 안 해도 모두 쓸 수 있음을 함께)"""
    try:
        if SETTINGS["gdrive_asked"] or gdrive.client(BIN_DIR) is None or gdrive.account():
            SETTINGS["gdrive_asked"] = True
            return None
    except Exception:
        log.exception("구글 백업 권유: 상태 읽기 실패")
        return None
    SETTINGS["gdrive_asked"] = True
    dlg = QtWidgets.QDialog(w)
    dlg.setWindowTitle(T("구글 드라이브 자동 백업 (선택)"))
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    lay = QtWidgets.QVBoxLayout(dlg)
    lay.setContentsMargins(20, 18, 20, 14)
    lay.setSpacing(12)
    head = QtWidgets.QLabel(T("설정·메모를 구글 드라이브에 백업할까요?"))
    f = head.font()
    f.setPointSizeF(f.pointSizeF() + 2)
    f.setBold(True)
    head.setFont(f)
    lay.addWidget(head)
    # 빌드 3 (사용자 11/7 '줄바꿈하고 간결하게, 개발자에게는 아무것도 전송되지 않습니다 맨 앞에 ### 빨간 글씨')
    body = QtWidgets.QLabel("\n".join("• " + T(x) for x in (
        "로그인하지 않아도 4Dir 는 모두 쓸 수 있습니다.",
        "설정·메모·즐겨찾기·태그는 이 PC 에만 있어서, 포맷하거나 PC 를 바꾸면 사라집니다.",
        "로그인하면 하루 한 번 내 구글 드라이브에 백업하고, 새 PC 에서 되살립니다.")))
    body.setWordWrap(True)
    body.setFixedWidth(460)
    lay.addWidget(body)
    red = QtWidgets.QLabel("### " + T("개발자에게는 아무것도 전송되지 않습니다."))
    red.setStyleSheet("color:#d32f2f; font-weight:bold;")
    lay.addWidget(red)
    tip = QtWidgets.QLabel(T("구글 화면에서 '구글 드라이브' 항목에 꼭 체크하세요.") + "\n" + T("나중에 하려면: 설정 → 백업"))
    tip.setWordWrap(True)
    tip.setStyleSheet("color:#6b7480;")
    lay.addWidget(tip)
    row = QtWidgets.QHBoxLayout()
    row.addStretch(1)
    later = QtWidgets.QPushButton(T("나중에"))
    go = QtWidgets.QPushButton(T("구글로 로그인…"))
    go.setDefault(True)
    row.addWidget(later)
    row.addWidget(go)
    lay.addLayout(row)
    later.clicked.connect(lambda: (log.info("구글 백업 권유: 나중에"), dlg.close()))
    go.clicked.connect(lambda: (log.info("구글 백업 권유: 로그인"), dlg.close(), w.gdrive_login()))
    log.info("구글 백업 권유 창 (처음 한 번)")
    dlg.show()
    return dlg


def refresh_titles():
    t = window_title()
    for w in list(WINDOWS):
        try:
            w.setWindowTitle(t)
        except RuntimeError:
            pass
    log.info("제목 표시줄: %s", t)
SSIG = None            # 검색 색인 알림 (모든 창이 받음)
CLOSED = []            # 다른 창이 남은 채 닫힌 창들 [(시각, 연 순서, 상태)] — 한꺼번에 닫힐 때 원래 메인 고르기
_ORDER = [0]           # 창을 연 순서 번호
UNDO = []              # 되돌리기(Ctrl+Z) 기록 [(종류, 자료, 설명)] — 이름 바꾸기·새 폴더·이동·복사 (삭제는 휴지통에서)
SERVER = None          # 하나만 실행용 통신 (창이 아니라 프로그램 소유 → 첫 창을 닫아도 유지)
THUMBS = None          # 그림 미리보기 (thumbs.Thumbs, 처음 필요할 때 만듦, 모든 창이 같이 씀)
THUMB_MODES = ("small", "medium", "large", "xlarge")   # 미리보기를 보여줄 보기 방식 (자세히·목록은 안 함)
MODELS = []            # 미리보기 완성 알림을 받을 목록 모델들 (약한 참조 대신 닫힐 때 빠짐)
TAGS = tags.Store(os.path.join(DATA_DIR, "4Dir_tags.json"))   # 0.9.109 태그·묶음 — 4Dir 안에만 저장
VIEWMEM = frecent.ViewMem(os.path.join(DATA_DIR, "4Dir_viewmem.json"))   # 0.9.116 폴더마다 보기 기억
FRECENT = frecent.Store(os.path.join(DATA_DIR, "4Dir_frecent.json"))   # 0.9.116 자주 간 폴더 (주소줄 후보)
RATINGS = labels.Ratings(os.path.join(DATA_DIR, "4Dir_ratings.json"))   # 0.9.116 별점 1~5
LABELS = labels.Store(os.path.join(DATA_DIR, "4Dir_labels.json"))   # 색 라벨 (v0.9.89) — 4Dir 안에만 저장


def thumbs_service():
    global THUMBS
    if THUMBS is None:
        THUMBS = thumbs.Thumbs()
        THUMBS.ready.connect(_thumb_ready)
        try:   # 빌드 6: 폴더 표지 바탕 = 윈도우 폴더 아이콘 (탐색기처럼) — 화면 스레드에서 한 번
            thumbs.set_folder_base(shellops.icon_for("folder", True, 256).pixmap(256, 256).toImage())
        except Exception:
            log.exception("폴더 아이콘 바탕 못 받음")
    return THUMBS


OVL = None            # 버전 관리 표시(윈도우 겹침 아이콘) overlays.Overlays


def overlay_service():
    global OVL
    if OVL is None:
        OVL = overlays.Overlays()
        OVL.ready.connect(_ovl_ready)
    return OVL


FICON = None          # 0.9.112 exe 등 파일마다 다른 아이콘 fileicons.FileIcons


def ficon_service():
    global FICON
    if FICON is None:
        FICON = fileicons.FileIcons()
        FICON.ready.connect(_ficon_ready)
    return FICON


def _ficon_ready(path):
    folder = os.path.dirname(path)
    for m in list(MODELS):
        try:
            m.icon_ready(path, folder)
        except RuntimeError:
            MODELS.remove(m)


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


FLAT_Q = "⤵*"   # 빌드 20: 하위 폴더 펼쳐 보기 = 그 폴더 아래 모든 파일 (폴더 아래 찾기와 같은 길, 파일만)


def search_path(q, folder=None):
    return SEARCH_PREFIX + q.strip() + (f" @ {folder}" if folder else "")


def parse_search(p):
    body = p[len(SEARCH_PREFIX):]
    if tags.is_view(body):   # 0.9.110 점검: 태그·가상 그룹 이름에 ' @ ' 가 있으면 폴더로 잘려 빈 목록이던 것
        return body, None
    if " @ " in body:
        q, f = body.rsplit(" @ ", 1)
        return q, f
    return body, None


def norm(p):
    return os.path.normpath(p) if p and p != THIS_PC and not is_search(p) and not devices.is_dev(p) and not archives.is_arc(p) and not ftpfs.is_url(p) else p


def disp_path(p):
    """주소줄에 보여줄 글자 ('내 PC' 표식만 번역, 실제 경로는 그대로)"""
    if devices.is_dev(p):   # 휴대폰: 셸 ID 대신 '기기 › 내장 저장공간 › DCIM'
        return devices.friendly(p)
    if archives.is_arc(p):   # 빌드 20 압축 안: F:\a.zip\그림
        return archives.friendly(p)
    return T(THIS_PC) if p == THIS_PC else p


def tab_title(p):
    if p == THIS_PC:
        return T(THIS_PC)
    if devices.is_dev(p):
        return devices.name_of(p)
    if archives.is_ftp(p):   # 0.9.109
        return "🌐 " + archives.name_of(p)
    if archives.is_arc(p):
        return "🗜 " + archives.name_of(p)
    if is_search(p):
        q, f = parse_search(p)
        if q == FLAT_Q:
            return "⤵ " + T("펼쳐 보기") + (f" — {tab_title(f)}" if f else "")
        if q.startswith(tags.TAG_Q):   # 0.9.109 태그로 보기
            return "🏷 " + q[len(tags.TAG_Q):]
        if q.startswith(tags.SET_Q):   # 0.9.109 묶음
            return "📚 " + q[len(tags.SET_Q):]
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
            if not st:   # 0.9.116 SVN 이 아니면 Git (git.exe 가 있을 때만, 없으면 None)
                g = gitstat.folder_status(self.path, [n for n, _d in self.names])
                if g:
                    st = dict(g)
                    b = gitstat.branch(self.path)
                    if b:
                        st["\0branch"] = b
                    self.sig.svn.emit(self.gen, self.path, st)
                    return
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
            elif devices.is_dev(self.path):   # 휴대폰 안 (셸로 읽음)
                entries = devices.list_dir(self.path, self.cancel)
            elif archives.is_arc(self.path):   # 빌드 20 압축 파일 안 (읽기 전용)
                entries = archives.list_dir(self.path, self.cancel)
            elif is_search(self.path):
                q, folder = parse_search(self.path)

                def rows(lst):
                    return [[n, d, s, m, 0, pth, None, None] for pth, n, d, s, m in lst]
                if tags.is_view(q):   # 0.9.109 태그·그룹 보기 (4Dir 안에 저장한 목록)
                    entries = rows(TAGS.rows(q))
                    self.sig.info.emit(self.gen, T('{0:,}개').format(len(entries)))   # 0.9.110: '찾는 중…' 에 멈춰 있던 것
                elif folder:   # 색인 없이 그 폴더 아래를 바로 훑기 (중간 결과를 계속 보냄)
                    flat = q == FLAT_Q   # 빌드 20 하위 폴더 펼쳐 보기: 파일만, 더 많이
                    total, scanned = search_index.folder_search(
                        folder, "*" if flat else q, self.cancel, lambda b: self.sig.partial.emit(self.gen, rows(b)),
                        limit=50000 if flat else 5000, files_only=flat)
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


def _on_drive(path, d):
    return os.path.splitdrive(path or "")[0].upper() == d


def release_drive(d):
    """Windows 가 드라이브 d('K:')를 꺼내도 되냐고 물음 (v0.9.96) → 4Dir 가 잡고 있는 것 모두 놓음: 폴더 변경 감시·폴더 크기 재기·꺼내기 알림 핸들.
    탭은 그대로 두고, 실제로 빠지면 refresh_drives 가 내 PC 로 옮김. 취소되면 rewatch_drive 로 되돌림"""
    n = 0
    for w in list(WINDOWS):
        for p in w.panes:
            for v in p.views():
                if _on_drive(v.path, d):
                    if v.watcher is not None and v.watcher.directories():
                        v.watcher.removePaths(v.watcher.directories())
                        n += 1
                    if v._fsize_job is not None:
                        v._fsize_job.cancel()
                        v._fsize_job = None
        w._drop_note(d)
    if SEARCH is not None:
        SEARCH.release_drive(d)   # 검색 색인 실시간 감시도 (외장하드도 NTFS 로컬이면 기본 범위에 듦)
    log.info("꺼내기 요청 %s → 감시 %d개 풂, 폴더 크기 재기 멈춤", d, n)


def rewatch_drive(d):
    """꺼내기가 취소됨 → 보이는 탭의 감시 다시"""
    for w in list(WINDOWS):
        for p in w.panes:
            for v in p.views():
                if v.active and _on_drive(v.path, d):
                    v._watch(v.path, v.path)
    if SEARCH is not None:
        SEARCH.rewatch()
    log.info("꺼내기 취소 %s → 감시 다시", d)


def isdir_quick(path, timeout=1.0):
    """os.path.isdir 를 timeout 초만 기다림 (v0.9.96) — 응답 없으면 None (막 꽂은 외장하드·잠든 네트워크 드라이브)"""
    box = {}

    def run():
        box["v"] = os.path.isdir(path)
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    return box.get("v")


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
    for name, p in devices.list_devices():   # 빌드 4: 휴대폰·카메라 등 (드라이브 글자 없음)
        out.append([name, True, -1, 0, 0, p, devices.icon_index(p), name])
    return out


POOL = QtCore.QThreadPool()
POOL.setMaxThreadCount(4)


# ================================================================ 목록 모델
COLS = [T("이름"), T("수정한 날짜"), T("유형"), T("크기"), T("위치"),   # 위치 = 검색 결과에서만 보임
        T("날짜"), T("길이"), T("만든 날짜"), T("미디어 작성 날짜"), T("사진 크기"),   # v0.9.76: 머리글 우클릭으로 보이기 (기본 숨김)
        T("상태"), T("태그"), T("별점"), T("쪽 수")]   # 별점 0.9.116 (처음 별점을 주면 저절로 보임)
#   # 상태 v0.9.94 · 태그 0.9.109 (처음 태그를 붙이면 저절로 보임)   # v0.9.94: 원드라이브 등 동기화 폴더 상태 (탐색기처럼 이름 바로 오른쪽)
COL_WIDTH = (322, 145, 120, 80, 320, 145, 80, 145, 145, 100, 46, 140, 84, 60)


def fmt_duration(sec):
    """길이 표시 (탐색기와 같은 시:분:초)"""
    s = int(round(sec))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


# 두 칸 비교 (v0.9.89): 결과 → (글자색, 풍선 도움말). 이쪽에만·이쪽이 새것 = 굵게 + 골라 둠 (F6 으로 반대쪽에 복사)
CMP_KIND = {"only": ("#1a7f37", T("두 칸 비교: 이쪽에만 있음")),
            "newer": ("#c2410c", T("두 칸 비교: 이쪽이 더 새것")),
            "older": ("#8a8f98", T("두 칸 비교: 반대쪽이 더 새것")),
            "diff": ("#7c3aed", T("두 칸 비교: 날짜는 같고 크기가 다름")),
            "content": ("#dc2626", T("두 칸 비교: 이름·크기는 같은데 내용이 다름")),     # v0.9.107 내용까지 비교
            "dateonly": ("#8a8f98", T("두 칸 비교: 날짜만 다름 (내용은 같음)"))}


GROUP_MARK = "\0"   # 날짜 묶음 제목 줄 (v0.9.90): 이름 앞 글자 — 파일 이름엔 못 쓰는 글자라 실제 파일과 안 겹침


def is_group(e):
    return e[0][:1] == GROUP_MARK


def kind_of(e):
    """형식 단추·형식 묶기용 종류: 폴더 '/', 파일은 소문자 확장명('.jpg'), 확장명 없으면 ''"""
    if e[1]:
        return "/"
    return os.path.splitext(e[0])[1].lower()


def kind_label(k):
    return T("폴더") if k == "/" else (k[1:].upper() if k else T("확장명 없음"))


def type_bucket(e):
    """형식별 묶기 (빌드 17): (순서, 묶음 이름) — 폴더 먼저, 그다음 확장명 가나다(ABC)순, 확장명 없음은 끝"""
    k = kind_of(e)
    return (0, "", kind_label(k)) if k == "/" else ((2, "", kind_label(k)) if not k else (1, k, kind_label(k)))


def date_bucket(ts, now=None):
    """수정한 날짜 → (순서, 묶음 이름). 윈도우 탐색기 '날짜별 그룹' 과 같은 칸: 오늘·어제·이번 주·지난주·이번 달·지난달·올해·오래전.
    주 시작 요일은 윈도우 지역 설정(QLocale)"""
    if not ts:
        return 8, T("날짜 없음")
    now = time.time() if now is None else now
    lt = time.localtime(now)
    today = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    day = 86400
    first = QtCore.QLocale().firstDayOfWeek().value   # 1=월 … 7=일
    back = (lt.tm_wday + 1 - first) % 7               # 오늘이 주 시작에서 며칠째
    week = today - back * day
    month = time.mktime((lt.tm_year, lt.tm_mon, 1, 0, 0, 0, 0, 0, -1))
    pm = (lt.tm_year, lt.tm_mon - 1) if lt.tm_mon > 1 else (lt.tm_year - 1, 12)
    last_month = time.mktime((pm[0], pm[1], 1, 0, 0, 0, 0, 0, -1))
    year = time.mktime((lt.tm_year, 1, 1, 0, 0, 0, 0, 0, -1))
    for i, (start, name) in enumerate(((today, T("오늘")), (today - day, T("어제")), (week, T("이번 주")),
                                       (week - 7 * day, T("지난주")), (month, T("이번 달")), (last_month, T("지난달")),
                                       (year, T("올해")))):
        if ts >= start:
            return i, name
    return 7, T("오래전")


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
        self.cmp = {}      # 이름 → 두 칸 비교 결과 (v0.9.89, Main.compare_panes) — 다시 읽으면 지움
        self.cloud = None       # 동기화 폴더(원드라이브 등) 안이면 그 등록 이름 (v0.9.94 상태 열)
        self.group_on = False   # 자세히 보기일 때만 날짜 묶음 (v0.9.90, Page.set_mode) — 아이콘 보기는 묶지 않음
        self.n_groups = 0       # rows 안 묶음 제목 줄 수 (항목 수 셀 때 뺌)
        self.thumbs_on = False   # 아이콘 보기 + 미리보기 켬 → 그림 파일은 미리보기 (thumbs.py)
        self.covers_ok = False   # 빌드 17 폴더 표지 가능한 폴더 (네트워크·휴대폰·내 PC 아님)
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

    def icon_ready(self, path, folder):
        """0.9.112 파일 고유 아이콘 하나 받음 → 그 줄만 다시 그림"""
        same = os.path.normcase(folder) == os.path.normcase(self.path or "")
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
        self.cmp = {}   # 두 칸 비교 표시는 목록이 바뀌면 지움 (복사 뒤 등)
        if path != self.path:
            self.svn = {}   # 같은 폴더 다시 읽기면 새 상태가 올 때까지 이전 표시 유지(깜빡임 방지)
        # 버전 관리 표시(윈도우): SVN 작업 폴더는 4Dir 배지를 쓰므로 제외. 다시 읽을 때마다 그 폴더 결과는 새로 물어봄(커밋 등)
        self.ovl_on = bool(OPTS["vcs_overlay"] and path and path != THIS_PC and not is_search(path)
                           and svnstat.wc_root(path) is None)
        if self.ovl_on and OVL is not None:
            OVL.forget(path)
        self.path, self.all = path, entries
        self.cloud = cloud.root_of(path) if path and path != THIS_PC and not is_search(path) else None
        # 폴더 표지는 폴더 안을 훑고 첫 그림을 읽으므로 네트워크·클라우드(받기 일어남)·휴대폰·검색 결과는 제외
        self.covers_ok = bool(path and path != THIS_PC and not is_search(path) and not devices.is_dev(path) and not archives.is_arc(path)
                              and self.cloud is None and not foldersize.is_remote(path))
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
        if e[0][:1] == GROUP_MARK:   # 날짜 묶음 제목 줄 — 글자는 CheckDelegate.paint 가 그림
            return e[7] if role == Qt.DisplayRole and c == 0 else None
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
            if c == 11:   # 0.9.109 태그
                return ", ".join(TAGS.tags_of(self.full(e))) if TAGS.files and not e[7] else ""
            if c == 12:   # 0.9.116 별점
                return labels.Ratings.text(RATINGS.get(self.full(e))) if RATINGS.data and not e[7] else ""
            if c == 7:
                ct = 0 if e[7] else shellprops.created(self.full(e), e[3])
                return win_datetime(ct) if ct else ""
            if c in PROP_COLS:   # v0.9.76 셸 속성 열 — 아직 안 읽었으면 빈칸 + 뒤에서 읽기
                if e[1] or e[7]:
                    return win_datetime(e[3]) if c == 5 and e[3] else ""
                d = shellprops.cached(self.full(e), e[3])
                if d is None:
                    self._want_props()
                    return win_datetime(e[3]) if c == 5 and e[3] else ""
                v = d.get(PROP_COLS[c])
                if c == 5:
                    return win_datetime(v or e[3]) if (v or e[3]) else ""
                if v is None:
                    return ""
                if c == 6:
                    return fmt_duration(v)
                if c == 8:
                    return win_datetime(v)
                if c == 13:   # 0.9.116 쪽 수
                    return f"{v:,}"
                return f"{v[0]} x {v[1]}"
        elif role == Qt.EditRole and c == 0:
            return e[0]
        elif c == 10 and self.cloud and role in (Qt.DecorationRole, Qt.ToolTipRole):   # 동기화 상태 (v0.9.94)
            st = cloud.state(e[4])
            return cloud.icon(st, self.icon_px if self.icon_px <= 20 else 16) if role == Qt.DecorationRole else cloud.STATES[st][1]
        elif role == Qt.DecorationRole and c == 0:
            if self.thumbs_on and not e[1] and thumbs.has_preview(e[0]) and not devices.is_dev(self.full(e)) and not archives.is_arc(self.full(e)):   # 휴대폰 사진 미리보기는 2차 · 0.9.121 PDF 첫 쪽
                pm = thumbs_service().get(self.full(e), e[3], self.thumb_px)
                if pm is not None:
                    pm.setDevicePixelRatio(self.thumb_px / max(1, self.icon_px))
                    return pm
            elif self.thumbs_on and e[1] and OPTS["folder_covers"] and self.icon_px >= 48 and self.covers_ok:   # 폴더 표지 (빌드 17)
                pm = thumbs_service().get(self.full(e), e[3], self.thumb_px)
                if pm is not None:
                    pm.setDevicePixelRatio(self.thumb_px / max(1, self.icon_px))
                    return pm
            if self.ovl_on and not (e[5] and e[0].endswith(":\\")):
                pm = overlay_service().get(self.full(e), e[3], self.thumb_px)
                if pm:
                    pm.setDevicePixelRatio(max(1.0, pm.width() / max(1, self.icon_px)))
                    return pm
            if e[6] is None and fileicons.wants(e[0], e[1]):   # 0.9.112 exe 등은 그 파일의 아이콘 (받기 전엔 기본 그림)
                fp = self.full(e)
                if not (devices.is_dev(fp) or archives.is_arc(fp)):
                    idx = ficon_service().get(fp, e[3])
                    if idx is not None and idx >= 0:
                        return shellops.icon_for(e[0], e[1], self.icon_px, idx)
            if e[1] and e[6] is None and self.thumbs_on and OPTS["folder_covers"] and self.icon_px >= 48 and self.covers_ok and thumbs.FOLDER_BASE is None:
                pm = QtGui.QPixmap(thumbs.empty_folder(self.thumb_px))   # 빌드 4: 표지가 직접 그린 폴더일 때만 빈 폴더도 같은 모양 (빌드 6 부터 보통은 윈도우 아이콘 바탕이라 윈도우 아이콘 그대로)
                pm.setDevicePixelRatio(self.thumb_px / max(1, self.icon_px))
                return pm
            return shellops.icon_for(e[0], e[1], self.icon_px, e[6])
        elif role == Qt.TextAlignmentRole and c in (3, 6, 13):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.ForegroundRole and self.cmp and e[0] in self.cmp:
            return QtGui.QColor(CMP_KIND[self.cmp[e[0]]][0])
        elif role == Qt.FontRole and self.cmp and self.cmp.get(e[0]) in ("only", "newer"):
            f = QtGui.QFont()
            f.setBold(True)
            return f
        elif role == Qt.BackgroundRole and LABELS.data:
            lc = LABELS.get(self.full(e))
            b = labels.bg(lc, SETTINGS["dark"]) if lc else ""
            if b:
                return QtGui.QColor(b)
        elif role == Qt.ToolTipRole and c == 0 and self.cmp and e[0] in self.cmp:
            return CMP_KIND[self.cmp[e[0]]][1]
        elif role == Qt.ForegroundRole and c == 12:   # 별점 = 금색
            return QtGui.QColor("#d99a00")
        elif role == Qt.ForegroundRole and c == 11 and TAGS.files and TAGS.tags_of(self.full(e)):   # 태그 = 첫 태그 색
            return QtGui.QColor(TAGS.color(TAGS.tags_of(self.full(e))[0]))
        elif role == Qt.ForegroundRole and (e[4] & HIDDEN_MASK):
            return QtGui.QColor(140, 140, 140)
        elif role == Qt.ForegroundRole:
            # 탐색기와 같게: 이름 = 진한 검정, 날짜·유형·크기 = 회색 (10/6 탐색기 캡처 실측 #000000 / #6d6d6d)
            return LIST_TEXT[bool(SETTINGS["dark"])][0 if c == 0 else 1]
        elif role == Qt.ToolTipRole and c == 0 and e[5]:
            return e[5]
        return None

    # v0.9.94: Qt 가 폴더 열 때 줄마다 flags 를 부름(3만 줄 = 6만 번, 실측) — 매번 enum OR 하면 1.4초 → 미리 만든 값 돌려줌
    _F_ROW = Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemNeverHasChildren | Qt.ItemIsDragEnabled
    _F_NAME = _F_ROW | Qt.ItemIsEditable

    def flags(self, idx):
        r = idx.row()
        if r < 0:
            return Qt.NoItemFlags
        rows = self.rows
        if r < len(rows) and rows[r][0][:1] == GROUP_MARK:
            return Qt.NoItemFlags   # 묶음 제목: 못 고름·키보드 이동도 건너뜀
        return self._F_NAME if idx.column() == 0 and self.path != THIS_PC else self._F_ROW

    def setData(self, idx, value, role=Qt.EditRole):
        if role != Qt.EditRole or idx.column() != 0:
            return False
        e = self.rows[idx.row()]
        new = str(value).strip()
        if not new or new == e[0]:
            return False
        src = self.full(e)
        if archives.is_ftp(src):   # 0.9.109 FTP 이름 바꾸기 — 0.9.110: 뒤 스레드로 (서버가 느리면 화면이 멈추던 것)
            here = self.path

            def run():
                try:
                    ftpfs.rename(src, new)
                    DEV_SIG.done.emit(here, True, "", "")
                except Exception as ex:
                    log.warning("FTP 이름 바꾸기 실패 %s: %s", src, ex)
                    DEV_SIG.done.emit(here, False, T('이름을 바꿀 수 없습니다.\n{0}').format(ex), "")
            threading.Thread(target=run, daemon=True, name="ftp-rename").start()
            e[0] = new
            self.dataChanged.emit(idx, idx)
            return True
        if archives.is_arc(src):   # 압축 안: 읽기 전용
            return False
        if devices.is_dev(src):   # 휴대폰: 셸로 이름 바꾸고 다시 읽음
            here = self.path
            log.info("휴대폰 이름 바꾸기 %s -> %s", e[0], new)
            devices.run_op("rename", 0, [src], new_name=new, done=lambda ok, err: DEV_SIG.done.emit(here, ok, err, ""))
            e[0] = new
            self.dataChanged.emit(idx, idx)
            return True
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
        if TAGS.files or TAGS.sets:
            TAGS.rename(src, dst)   # 0.9.109 태그·묶음도 따라감
        if RATINGS.data:
            RATINGS.rename(src, dst)   # 0.9.116 별점도
        return True

    def sort(self, col, order=Qt.AscendingOrder):
        self.sort_col, self.sort_order = col, order
        self.layoutAboutToBeChanged.emit()
        self._sort()
        self.layoutChanged.emit()

    def _sort(self):
        self.all = self._sorted(self.all)
        self.rows = self._grouped(self._filtered(self.all))

    def _grouped(self, rows):
        """날짜별로 묶기 (v0.9.90): 묶음 제목 줄을 끼움. 묶음 안 순서는 지금 정렬 그대로.
        묶음 순서는 새것부터 — 수정한 날짜 오름차순 정렬일 때만 오래된 것부터"""
        self.n_groups = 0
        by_type = OPTS["type_groups"]
        if not ((OPTS["date_groups"] or by_type) and self.group_on and rows and self.path and self.path != THIS_PC
                and not is_search(self.path)):
            return rows
        now = time.time()
        buckets = {}
        for e in rows:
            buckets.setdefault(type_bucket(e) if by_type else date_bucket(e[3], now), []).append(e)
        keys = sorted(buckets) if by_type else sorted(buckets, reverse=self.sort_col == 1 and self.sort_order == Qt.AscendingOrder)
        out = []
        for k in keys:
            n = len(buckets[k])
            out.append([GROUP_MARK + k[-1], False, -1, 0, 0, "", 0, f"{k[-1]}  ({n:,})"])
            out.extend(buckets[k])
        self.n_groups = len(keys)
        return out

    def count(self):
        """실제 항목 수 (묶음 제목 줄 뺌)"""
        return len(self.rows) - self.n_groups

    propsLoaded = QtCore.Signal(str, int)

    def _load_props(self, items):
        """정렬용 셸 속성을 뒤 스레드에서 읽고 → 같은 폴더·같은 정렬이면 다시 정렬 (v0.9.75)"""
        if getattr(self, "_props_busy", None) == self.path:
            return
        self._props_busy = path = self.path
        col = self.sort_col
        if not getattr(self, "_props_hooked", False):
            self._props_hooked = True
            self.propsLoaded.connect(self._props_done)
        log.info("정렬용 속성 뒤에서 읽기 시작 %s %d개 (정렬 %d)", path, len(items), col)
        import threading

        def work():
            try:
                shellprops.prefetch(items)
            except Exception:
                log.exception("정렬용 속성 읽기 실패")
            try:
                self.propsLoaded.emit(path, col)
            except RuntimeError:   # 탭이 닫혀 모델이 없어짐
                pass
        threading.Thread(target=work, daemon=True, name="sortprops").start()

    def _props_done(self, path, col):
        self._props_busy = None
        if path != self.path:
            return
        if self.sort_col in PROP_SORTS:
            log.info("정렬용 속성 다 읽음 → 다시 정렬 %s", path)
            self.sort(self.sort_col, self.sort_order)
        elif self.rows:   # 열 표시만 (v0.9.76)
            self.dataChanged.emit(self.index(0, 5), self.index(len(self.rows) - 1, len(COLS) - 1), [Qt.DisplayRole])

    def _want_props(self):
        """속성 열이 보이는데 아직 안 읽은 파일 → 이 폴더 미디어 파일을 한 번에 뒤에서 읽기 (v0.9.76)"""
        if getattr(self, "_props_busy", None) == self.path:
            return
        items = [(self.full(e), e[3]) for e in self.all if not e[1] and not e[7]
                 and shellprops.cached(self.full(e), e[3]) is None]
        if items:
            self._load_props(items)

    def _filtered(self, rows):
        """빠른 필터: 이름에 글자 포함(대소문자 무시). * ? 가 있으면 와일드카드. 형식 단추(빌드 17)를 고르면 그 형식만"""
        kinds = getattr(self, "ext_filter", None)
        if kinds:
            rows = [e for e in rows if kind_of(e) in kinds]
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
        self.rows = self._grouped(self._filtered(self.all))
        self.endResetModel()

    def _sorted(self, rows):
        if self.path == THIS_PC:
            return list(rows)
        c, rev = self.sort_col, self.sort_order == Qt.DescendingOrder
        if c in PROP_SORTS:   # v0.9.75: 날짜·길이·미디어 작성 날짜·사진 크기 — 읽어 둔 값으로 정렬, 없는 건 뒤에서 읽고 다시 정렬
            field, missing = PROP_SORTS[c], []

            def key(e, field=field, missing=missing):
                if e[1]:
                    v = None
                else:
                    p = self.full(e)
                    d = shellprops.cached(p, e[3])
                    if d is None:
                        missing.append((p, e[3]))
                        d = {}
                    v = d.get(field)
                if c == 5:
                    return v or e[3]   # 날짜: 찍은 날짜 등 (없으면 수정한 날짜) = 탐색기 '날짜'
                # 값 없는 파일(폴더·문서 등)은 오름·내림 모두 맨 뒤
                return ((v is None) if not rev else (v is not None)), v or 0, shellops.natural_key(e[0])
            dated = c == 5
            out = (sorted(rows, key=key, reverse=rev) if dated and not OPTS["date_folders_first"] else
                   sorted((e for e in rows if e[1]), key=key, reverse=rev) + sorted((e for e in rows if not e[1]), key=key, reverse=rev))
            if missing:
                self._load_props(missing)
            return out
        if c == 7:   # 만든 날짜
            key = lambda e: shellprops.created(self.full(e), e[3])
            if not OPTS["date_folders_first"]:
                return sorted(rows, key=key, reverse=rev)
        elif c == 1:
            key = lambda e: e[3]
        elif c == 2:
            key = lambda e: (shellops.type_for(e[0], e[1]).lower(), shellops.natural_key(e[0]))
        elif c == 3:
            key = lambda e: e[2]
        elif c == 4:
            key = lambda e: ((os.path.dirname(e[5]) if e[5] else "").lower(), shellops.natural_key(e[0]))
        elif c == 12:   # 0.9.116 별점 (오름차순 = 별 많은 것 먼저가 아니라 적은 것 먼저 — 탐색기 숫자 정렬과 같게, 없는 것은 0)
            key = lambda e: (RATINGS.get(self.full(e)), shellops.natural_key(e[0]))
        elif c == 11:   # 0.9.109 태그 (없는 것은 뒤로)
            key = lambda e: (", ".join(TAGS.tags_of(self.full(e))).lower() or "\uffff", shellops.natural_key(e[0]))
        elif c == 10:   # 상태: 클라우드에만 → 이 PC → 항상 유지
            key = lambda e: (cloud.STATES[cloud.state(e[4])][0], shellops.natural_key(e[0]))
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
        ps = [self.full(self.rows[r]) for r in rows]
        if any(devices.is_dev(p) for p in ps):   # 휴대폰 항목: 파일 주소가 없음 → 4Dir 칸끼리만
            md.setData(DEV_MIME, "\n".join(ps).encode("utf-8"))
            return md
        md.setUrls([QtCore.QUrl.fromLocalFile(p) for p in ps])
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
        elif isinstance(opt.widget, QtWidgets.QListView) and opt.widget.viewMode() == QtWidgets.QListView.IconMode:
            # v0.9.96: 아이콘 보기는 모든 칸 같은 크기(uniformItemSizes) → 칸 크기를 격자에 맞춤. 전엔 Qt 가 고른 한 항목의 크기를 다 같이 써서
            # 그 항목이 낮으면(예: K:\ 의 .psd 43px) 모든 이름이 잘림 (11/5 사용자 제보 '외장하드 최상위 보통 아이콘', 재현 rect 90x43)
            g = opt.widget.gridSize()
            if g.isValid():
                return QtCore.QSize(g.width() - 4, g.height() - 4)
        return sz

    def initStyleOption(self, opt, idx):
        super().initStyleOption(opt, idx)
        if OPTS["checkboxes"] and idx.column() == 0 and idx.flags() & Qt.ItemIsSelectable:
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
            # 0.9.121: 윈도우 11 스타일 편집칸은 반투명이라 칸 뒤 원래 이름(확장명)이 비쳐 보임 → 불투명 바탕
            base = ed.palette().color(QtGui.QPalette.Base)
            base.setAlpha(255)
            ed.setStyleSheet(f"QLineEdit{{background:{base.name()};}}")
        return ed

    def setEditorData(self, ed, idx):
        """이름 바꾸기(F2): 윈도우 탐색기처럼 파일은 확장자 앞까지만 선택 (폴더·확장자 없는 이름은 전체).
        0.9.121 (사용자 문의 '이름 바꾸기 때 확장자 안 보이게'): 설정 rename_hide_ext(기본 켬)면 칸에 이름만 — 확장명은 저장할 때 다시 붙임"""
        super().setEditorData(ed, idx)
        if not isinstance(ed, QtWidgets.QLineEdit) or idx.column() != 0:
            return
        rows = getattr(idx.model(), "rows", None)
        isdir = rows[idx.row()][1] if rows and idx.row() < len(rows) else True
        ed.setProperty("hidden_ext", "")
        if SETTINGS["rename_hide_ext"] and not isdir:
            stem, ext = os.path.splitext(ed.text())
            if stem and ext:
                ed.setProperty("hidden_ext", ext)
                ed.setText(stem)
                QtCore.QTimer.singleShot(0, lambda: ed.selectAll() if ed is not None else None)
                return
        stem = os.path.splitext(ed.text())[0]
        if not isdir and 0 < len(stem) < len(ed.text()):
            def sel():   # 보기가 편집칸을 띄운 뒤 '전체 선택'을 하므로 그 다음에 다시 고름
                try:
                    ed.setSelection(0, len(stem))
                except RuntimeError:
                    pass
            QtCore.QTimer.singleShot(0, sel)

    def setModelData(self, ed, model, idx):
        ext = ed.property("hidden_ext") if isinstance(ed, QtWidgets.QLineEdit) else ""
        if ext and idx.column() == 0:   # 숨겨 둔 확장명 다시 붙임 (0.9.121)
            stem = ed.text().strip()
            if stem:
                model.setData(idx, stem + ext, Qt.EditRole)
            return
        super().setModelData(ed, model, idx)

    # SVN 상태 배지 (TortoiseSVN 과 비슷한 색): 정상 초록✓ · 수정 빨강! · 추가 파랑+ · 충돌 주황! · 삭제 빨강× · 밖 회색?
    # 폴더: 안쪽 어딘가 변경 = 빨강!, 없음 = 초록✓ (작업 폴더 전체 감시 svnstat.WcWatch, 처음 훑는 동안은 배지 없음)
    SVN_BADGE = {"normal": ("#2e9d4b", "✓"), "modified": ("#d93025", "!"), "added": ("#1a73e8", "+"),
                 "conflict": ("#f29900", "!"), "deleted": ("#d93025", "×"), "unversioned": ("#8a939c", "?")}

    def paint(self, p, opt, idx):
        rows = getattr(idx.model(), "rows", None)
        if rows and idx.row() < len(rows) and is_group(rows[idx.row()]):
            self._paint_group(p, opt, rows[idx.row()][7])
            return
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

    def _paint_group(self, p, opt, text):
        """날짜 묶음 제목 (v0.9.90): 탐색기처럼 파란 글자 + 오른쪽으로 옅은 선"""
        dark = SETTINGS["dark"]
        col = QtGui.QColor("#7fb2ff" if dark else "#1e5fb4")
        r = opt.rect.adjusted(6, 0, -6, 0)
        f = QtGui.QFont(opt.font)
        f.setPointSizeF(f.pointSizeF() * 1.08 if f.pointSizeF() > 0 else 10)
        p.save()
        p.setFont(f)
        p.setPen(col)
        fm = QtGui.QFontMetrics(f)
        p.drawText(r, int(Qt.AlignLeft | Qt.AlignVCenter), text)
        x = r.left() + fm.horizontalAdvance(text) + 10
        if x < r.right():
            line = QtGui.QColor(col)
            line.setAlpha(70)
            p.setPen(line)
            y = r.center().y() + 1
            p.drawLine(x, y, r.right(), y)
        p.restore()

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
        dps = [self.model().full(self.model().rows[i.row()]) for i in idxs]
        if any(archives.is_arc(p) for p in dps):   # 빌드 20 압축 안: 임시 폴더에 풀어 진짜 파일로 끌기 (복사만)
            real = self.page._arc_real(dps)
            if real:
                md = QtCore.QMimeData()
                md.setUrls([QtCore.QUrl.fromLocalFile(p) for p in real])
                drag = QtGui.QDrag(self)
                drag.setMimeData(md)
                log.info("압축 안에서 끌기 %d개 (임시 폴더에 풂)", len(real))
                drag.exec(Qt.CopyAction, Qt.CopyAction)
            return
        if all(devices.is_dev(p) for p in dps):   # 빌드 6: 휴대폰 항목 → 윈도우 셸 끌기 (탐색기·바탕화면에 놓으면 복사됨)
            DEV_DRAG["paths"] = dps
            try:
                devices.shell_drag(dps)
            finally:
                DEV_DRAG["paths"] = None
            return
        md = self.model().mimeData(idxs)
        if md is None:
            return
        cur = self.currentIndex()
        base = cur.row() if cur.isValid() and any(i.row() == cur.row() for i in idxs) else idxs[0].row()
        e = self.model().rows[base]
        # v0.9.67: 그림 파일은 이미 만들어 둔 미리보기를 끌기 그림으로 (사용자 요청: 빈 jpg 아이콘 대신 원래 그림).
        # 새로 읽지 않음(큰 PSD·max 는 멈칫함) — 없으면 예전처럼 종류 아이콘
        tpm = thumbs_service().peek(self.model().full(e), e[3]) if not e[1] and thumbs.is_image(e[0]) and OPTS["thumbnails"] and not devices.is_dev(self.model().full(e)) and not archives.is_arc(self.model().full(e)) else None
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
        if getattr(self, "_eat_release", None) == ev.button():
            self._eat_release = None   # 마우스 버튼 지정으로 처리한 누름의 뗌 (v0.9.83)
            return
        super().mouseReleaseEvent(ev)
        if ev.button() == Qt.LeftButton and hasattr(self, "_press_sel"):
            sm = self.selectionModel()
            n = len(sm.selectedRows()) if sm else 0
            if n != self._press_sel or getattr(self, "_drag_started", False):
                log.info("마우스 뗌 %s 고른수 %d (누를 때 %d) 끌기=%s", type(self).__name__, n, self._press_sel, getattr(self, "_drag_started", False))

    def mouseDoubleClickEvent(self, ev):
        if keymap.mouse_action(SETTINGS["mouse"], keymap.mouse_combo(ev.button(), ev.modifiers())) != keymap.BUILTIN:
            return   # 마우스 버튼 지정(v0.9.83): 빠르게 두 번 눌러도 기능은 한 번만
        # 빈 곳 더블클릭 → 상위 폴더 (옵션, v0.9.81 사용자 의견: 한 번 클릭은 선택 해제로 씀 → 더블클릭으로)
        if (ev.button() == Qt.LeftButton and SETTINGS["empty_click_up"] and ev.modifiers() == Qt.NoModifier
                and not self.indexAt(ev.position().toPoint()).isValid()
                and self.state() != QtWidgets.QAbstractItemView.EditingState and not is_search(self.page.path)):
            log.info("빈 곳 더블클릭 → 상위 폴더 %s", self.page.path)
            QtCore.QTimer.singleShot(0, self.page.go_up)
            return
        super().mouseDoubleClickEvent(ev)

    def contextMenuEvent(self, ev):
        if getattr(self, "_eat_ctx", False) and ev.reason() != QtGui.QContextMenuEvent.Keyboard:
            self._eat_ctx = False   # 오른쪽 버튼에 다른 기능 지정 (v0.9.83)
            return
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
        md = ev.mimeData()
        if (md.hasUrls() or vfiles.has_virtual(md)) and self.page.path != THIS_PC and not is_search(self.page.path):   # v0.9.75 아웃룩 첨부 등 가상 파일
            ev.acceptProposedAction()
        else:
            if not md.hasUrls():
                log.info("끌기 받지 않음 — 형식 %s", list(md.formats())[:12])   # 아웃룩 등 실측용
            ev.ignore()

    def dragMoveEvent(self, ev):
        md = ev.mimeData()
        if not (md.hasUrls() or vfiles.has_virtual(md)) or self.page.path == THIS_PC or is_search(self.page.path):
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


def _ord(o):
    """Qt.SortOrder → 0/1"""
    return int(o.value if hasattr(o, "value") else o)


def view_sequences(v):
    """칸 목록(이미 읽은 이름)에서 연번 묶음 — 디스크를 다시 읽지 않음. 목록이 바뀌기 전까지 기억 (0.9.116)"""
    rows = v.model_.rows
    key = (v.path, hash(tuple(e[0] for e in rows)))   # 목록 이름이 같으면 다시 안 셈 (id 는 지운 목록 번호를 다시 쓸 수 있어 안 씀)
    c = getattr(v, "_seq_cache", None)
    if c and c[0] == key:
        return c[1]
    t0 = time.time()
    seqs = sequence.find_sequences([e[0] for e in rows if not e[1] and not e[7]], v.path) if v.path and os.path.isdir(v.path) else []
    v._seq_cache = (key, seqs)
    if seqs:
        log.info("연번 묶음 %d개 %s (%.0fms)", len(seqs), v.path, (time.time() - t0) * 1000)
    return seqs


def seq_in_view(v, path):
    b = os.path.basename(path)
    return next((q for q in view_sequences(v) if b in q.names), None)


def copy_text(t):
    QtWidgets.QApplication.clipboard().setText(t)
    log.info("글자 복사 %d자", len(t))


def textdiff_ok(p):
    """글자 비교 메뉴를 보일지 — 확장자로 그림·영상·압축 등은 뺌 (실제 이진 판정은 창이 함)"""
    return os.path.splitext(p)[1].lower() not in (thumbs.IMAGE_EXT if hasattr(thumbs, "IMAGE_EXT") else set()) | {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".psd", ".tga", ".exr", ".dds", ".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav",
        ".zip", ".7z", ".rar", ".exe", ".dll", ".pdf", ".docx", ".xlsx", ".pptx", ".hwp", ".max", ".fbx", ".iso"}


def open_tool(fn, *a, **k):
    """0.9.116 새 도구 창 열기 — 창 테마(스타일) 맞추고 실패하면 로그·알림"""
    try:
        w = fn(*a, **k)
        par = a[0] if a and isinstance(a[0], QtWidgets.QWidget) else None
        if w is not None and par is not None and not w.styleSheet():
            w.setStyleSheet(par.window().styleSheet())
        return w
    except Exception as ex:
        log.exception("도구 창 실패 %s", getattr(fn, "__qualname__", fn))
        QtWidgets.QMessageBox.warning(None, "4Dir", T("열지 못했습니다: {0}").format(ex))
        return None


def refresh_ratings_ui(show_col=False):
    """별점을 주거나 뺌 (0.9.116) → 처음이면 별점 열을 켜고 모든 칸의 별점 칸을 다시 그림"""
    if show_col and 12 not in SETTINGS["columns"]:
        toggle_column(12)
    for w in WINDOWS:
        for p in w.panes:
            for v in p.views():
                m = v.model_
                if m.rows:
                    m.dataChanged.emit(m.index(0, 12), m.index(len(m.rows) - 1, 12))


def refresh_tags_ui(show_col=False):
    """태그를 붙이거나 뗌 (0.9.109) → 처음이면 태그 열을 켜고, 모든 칸의 태그 칸을 다시 그림"""
    if show_col and 11 not in SETTINGS["columns"]:
        toggle_column(11)
    for w in WINDOWS:
        for p in w.panes:
            for v in p.views():
                m = v.model_
                if m.rows:
                    m.dataChanged.emit(m.index(0, 11), m.index(len(m.rows) - 1, 11))


def open_img_edit(path, parent=None):
    """그림 편집 창 (0.9.118). 저장하면 그 폴더 칸을 다시 읽고 새 파일을 고름 + 미리보기 새로"""
    def done(dst):
        d, nm = os.path.dirname(dst), os.path.basename(dst)
        for w in WINDOWS:
            for p in w.panes:
                for v in p.views():
                    if v.path and os.path.normcase(v.path) == os.path.normcase(d):
                        v.pending_select = nm
                        v.reload("imgedit")
        if PREVIEW_WIN is not None and PREVIEW_WIN.pane.isVisible():
            QtCore.QTimer.singleShot(600, PREVIEW_WIN.pane.schedule)
    return open_tool(imgedit.open_editor, parent, path, on_saved=done)


def open_media_edit(path, start=0, parent=None):
    """동영상·GIF 편집 창 (0.9.111). 저장하면 그 폴더를 보는 칸에서 새 파일을 고름"""
    def done(dst):
        d, nm = os.path.dirname(dst), os.path.basename(dst)
        for w in WINDOWS:
            for p in w.panes:
                for v in p.views():
                    if v.path and os.path.normcase(v.path) == os.path.normcase(d):
                        v.pending_select = nm
                        v.reload("edit")
    dlg = mediaedit.EditDialog(path, start, done, parent)
    if parent is not None:
        dlg.setStyleSheet(parent.styleSheet())
    dlg.show()
    return dlg


def remember_ftp(site):
    """최근 FTP 사이트 (0.9.109, 비밀번호는 저장 안 함 — 기억은 윈도우 자격 증명)"""
    SETTINGS["ftp_sites"] = ([site] + [s for s in SETTINGS["ftp_sites"] if s != site])[:10]


def toggle_column(c):
    """머리글 우클릭에서 열 켜고 끄기 → 모든 창·칸·탭에 (v0.9.76). 10(상태)은 설정 status_col 로 (v0.9.94)"""
    if c == 10:
        SETTINGS["status_col"] = not SETTINGS["status_col"]
    else:
        cols = [x for x in SETTINGS["columns"] if x != c] if c in SETTINGS["columns"] else SETTINGS["columns"] + [c]
        SETTINGS["columns"] = [x for x in OPT_COLS if x in cols and x != 10]
    log.info("보일 열 %s", SETTINGS["columns"])
    for w in WINDOWS:
        for p in w.panes:
            for v in p.views():
                v.apply_columns()


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
    # v0.9.89 사용자: 열이 스크롤바까지 차면 오른쪽 빈 곳이 없음 → 오른쪽에도 같은 띠 (빈 곳 더블클릭 = 상위 폴더)
    GUTTER_L, GUTTER_T, GUTTER_R = 14, 6, 14

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
            want = (self.GUTTER_L, hh + self.GUTTER_T, self.GUTTER_R, 0)
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
            if getattr(self, "_eat_ctx", False):
                self._eat_ctx = False
                return True
            log.debug("목록 빈 띠 우클릭 → 폴더 메뉴")
            self.page.context_menu(self, ev)   # 빈 곳 = 폴더 메뉴
            return True
        if t == QtCore.QEvent.MouseButtonPress and self._in_gutter(ev.position().toPoint()):
            if self.page.mouse_override(self, ev, QtCore.QPoint(-1, -1)):   # 빈 띠 = 빈 곳
                return True
            if ev.button() == Qt.LeftButton and not (ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                self.selectionModel().clearSelection()   # 탐색기: 빈 곳 클릭 = 선택 해제
            self.setFocus()
            return True
        if t == QtCore.QEvent.MouseButtonDblClick and self._in_gutter(ev.position().toPoint()):
            # v0.9.89: 왼쪽·오른쪽 빈 띠도 빈 곳 — 더블클릭하면 상위 폴더 (목록 안 빈 곳과 같은 조건)
            if (ev.button() == Qt.LeftButton and SETTINGS["empty_click_up"] and ev.modifiers() == Qt.NoModifier
                    and keymap.mouse_action(SETTINGS["mouse"], keymap.mouse_combo(ev.button(), ev.modifiers())) == keymap.BUILTIN
                    and self.state() != QtWidgets.QAbstractItemView.EditingState and not is_search(self.page.path)):
                log.info("빈 띠 더블클릭 → 상위 폴더 %s", self.page.path)
                QtCore.QTimer.singleShot(0, self.page.go_up)
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
    _wacc = 0

    def _row_step(self):
        """휠 한 칸 = 아이콘 한 줄 (0.9.112 빌드 2 사용자 11/6: 3줄씩 내려가 어디까지 봤는지 헷갈림)"""
        if self.viewMode() == QtWidgets.QListView.ListMode and self.verticalScrollMode() == QtWidgets.QAbstractItemView.ScrollPerItem:
            return 1   # 줄 단위 스크롤바 (작은 아이콘)
        g = self.gridSize()
        if g.isValid() and g.height() > 0:
            return g.height()
        m = self.model()
        if m is not None and m.rowCount():
            return max(1, self.visualRect(m.index(0, 0)).height() + self.spacing())
        return max(1, self.verticalScrollBar().singleStep())

    def wheelEvent(self, ev):
        dy = ev.angleDelta().y()
        if (not (ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)) and dy and ev.pixelDelta().isNull()
                and self.flow() == QtWidgets.QListView.LeftToRight):   # 위아래로 넘기는 보기만 (목록 보기는 옆으로)
            self._wacc += dy
            n = int(self._wacc / 120)   # 고운 휠·터치패드는 조금씩 모아 120 마다 한 줄
            if n:
                self._wacc -= n * 120
                sb = self.verticalScrollBar()
                sb.setValue(sb.value() - n * self._row_step())
            ev.accept()
            return
        super().wheelEvent(ev)

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
    openLocation = QtCore.Signal(str, str)   # v0.9.94 Ctrl+Enter: 파일의 폴더 위치를 새 탭으로 (폴더, 고를 이름)
    lockedNav = QtCore.Signal(str, object)   # v0.9.95 잠긴 탭에서 다른 폴더로 가려 함 → 새 탭으로 (폴더, 고를 이름)
    lockChanged = QtCore.Signal()            # v0.9.95 탭 잠금이 바뀜 → 탭 글자(🔒) 다시
    navWaitDone = QtCore.Signal(int, bool, object)   # v0.9.96 응답 늦은 드라이브 확인 끝 (번호, 폴더인가, 이동 인자)
    fsizeFound = QtCore.Signal(int, str, object)   # (gen, 폴더 이름, 크기) — 폴더 크기 작업 스레드에서 (v0.9.89)
    typesChanged = QtCore.Signal()   # 빌드 17: 폴더를 다 읽음 → 형식 단추 줄 다시
    fsizeDone = QtCore.Signal(int)

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
        self.fsizeFound.connect(self._on_fsize)
        self.fsizeDone.connect(self._on_fsize_done)
        self._fsize_job = None
        self.tab_color = ""   # 탭 색 (v0.9.89, labels.TAB_COLORS 이름 또는 '#rrggbb') — 탭 상태에 저장
        self.locked = False   # 탭 잠금 (v0.9.95, 사용자 의견 '토탈 커맨더처럼') — 다른 폴더는 새 탭으로, 탭 상태에 저장
        self._nav_wait = 0          # 응답 늦은 드라이브 기다림 번호 (v0.9.96) — 그사이 다른 곳으로 가면 버림
        self._pc_retry = 0          # 내 PC 에서 드라이브 정보가 늦을 때 다시 읽은 횟수 (v0.9.96)
        self.navWaitDone.connect(self._on_nav_wait)
        self.from_locked = False   # 잠긴 탭 때문에 열린 새 탭 — 다른 폴더로 갈 때까지 상태줄 앞에 안내
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
        self._spanned = []
        for sig in (self.model_.modelReset, self.model_.layoutChanged, self.model_.rowsInserted):
            sig.connect(self._span_groups)
        _setup_view(self.tree, self)
        self.tree.setItemDelegate(self.delegate)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        h = self.tree.header()
        h.setStretchLastSection(False)
        for c, w in enumerate(COL_WIDTH):   # 탐색기 기본 폭과 같게 (10/6 캡처 실측: 이름 322·날짜 145·유형 120·크기 80)
            h.resizeSection(c, w)
        h.setContextMenuPolicy(Qt.CustomContextMenu)   # v0.9.76: 머리글 우클릭 = 보일 열 고르기 (탐색기와 같게)
        h.customContextMenuRequested.connect(self._header_menu)
        if not SETTINGS["dark"]:   # 머리줄 글자 = 탐색기와 같은 파란 회색 (실측 #4c607a)
            pal = h.palette()
            for role in (QtGui.QPalette.ButtonText, QtGui.QPalette.WindowText, QtGui.QPalette.Text):
                pal.setColor(role, QtGui.QColor("#4c607a"))
            h.setPalette(pal)
        self.tree.setColumnHidden(4, True)   # '위치' 열 = 검색 결과에서만
        h.moveSection(h.visualIndex(10), 1)  # 상태 열은 탐색기처럼 이름 바로 오른쪽 (v0.9.94)
        self.apply_columns()
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

    def _span_groups(self, *_):
        """날짜 묶음 제목 줄은 열 전체에 걸쳐 그림 (v0.9.90). 예전 줄 번호 풀고 새로"""
        rows = self.model_.rows
        root = QtCore.QModelIndex()
        for r in self._spanned:
            if r < len(rows):
                self.tree.setFirstColumnSpanned(r, root, False)
        self._spanned = [r for r, e in enumerate(rows) if is_group(e)] if self.model_.n_groups else []
        for r in self._spanned:
            self.tree.setFirstColumnSpanned(r, root, True)

    # ---------------------------------------------------------- 보기 방식
    def set_mode(self, mode):
        if mode not in MODE_PX:
            mode = "details"
        self.mode = mode
        grp = mode == "details"   # 날짜 묶음은 자세히 보기에서만 (v0.9.90)
        if grp != self.model_.group_on:
            self.model_.group_on = grp
            if OPTS["date_groups"] or OPTS["type_groups"]:
                self.model_.sort(self.model_.sort_col, self.model_.sort_order)
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
        self.tree.sortByColumn(col, order)   # 0.9.116: 옛 번호 변환(OLD_SORT)은 상태 복원에서만 (여기서 하면 별점 열 12 가 7 로 바뀜)  # 모델 정렬 + 머리글 표시 (숨긴 열이면 표시만 안 보임)

    def _vm_ok(self, path=None):
        path = self.path if path is None else path
        return bool(SETTINGS["folder_view_memory"]) and bool(path) and path != THIS_PC and not is_search(path)             and not archives.is_arc(path) and not devices.is_dev(path)

    def _vm_sorted(self, *_a):
        """정렬이 바뀜(머리글 누름·메뉴) → 이 폴더 정렬 기억 (복원·기억 적용 중엔 안 함)"""
        if getattr(self, "_vm_quiet", False):
            return
        if not self._vm_ok():
            self._vm_default_sort = (self.model_.sort_col, _ord(self.model_.sort_order))   # 내 PC·검색 결과 등 = 탭 기본 정렬
            return
        VIEWMEM.remember(self.path, sort=(self.model_.sort_col, _ord(self.model_.sort_order)))

    def apply_view_memory(self, path):
        """0.9.116: 기억한 폴더면 그 보기·정렬로, 아니면 칸의 기본 보기·이 탭의 기본 정렬로 (윈도우 탐색기처럼)"""
        if not SETTINGS["folder_view_memory"]:
            return
        mem = (VIEWMEM.get(path) if self._vm_ok(path) else None) or {}
        pane = getattr(self, "pane_ref", None)
        mode = mem.get("mode") or getattr(pane, "base_mode", None) or self.mode
        cur = (self.model_.sort_col, _ord(self.model_.sort_order))
        srt = tuple(mem["sort"]) if mem.get("sort") else getattr(self, "_vm_default_sort", (0, 0))
        self._vm_quiet = True
        try:
            if mode != self.mode:
                self.set_mode(mode)
                log.info("폴더 보기 %s 보기=%s (%s)", path, mode, "기억" if mem.get("mode") else "칸 기본")
            if (int(srt[0]), int(srt[1])) != cur:
                self.set_sort(int(srt[0]), Qt.SortOrder(int(srt[1])))
                log.info("폴더 보기 %s 정렬=%s (%s)", path, srt, "기억" if mem.get("sort") else "탭 기본")
        finally:
            self._vm_quiet = False

    def apply_columns(self):
        """보일 열 (전역 설정 columns, v0.9.76 머리글 우클릭). 위치(4)는 검색 결과에서만"""
        shown = set(SETTINGS["columns"])
        for c in OPT_COLS:
            if c != 10:
                self.tree.setColumnHidden(c, c not in shown)
        self.tree.setColumnHidden(4, not is_search(getattr(self, "path", "")))
        # 상태 열: 동기화 폴더(원드라이브 등) 안에서만, 설정 status_col 켬일 때 (탐색기와 같게 그 폴더에서만 보임)
        self.tree.setColumnHidden(10, not (SETTINGS["status_col"] and self.model_.cloud))

    def _header_menu(self, pos):
        self.header_menu().exec(self.tree.header().mapToGlobal(pos))

    def header_menu(self):
        """머리글 우클릭 메뉴 (보일 열 고르기) — 띄우지 않고 만들기만 (시험에서도 씀)"""
        m = QtWidgets.QMenu(self)
        shown = set(SETTINGS["columns"])
        for c in OPT_COLS:
            a = m.addAction(T("상태 (원드라이브 등 동기화 폴더에서)") if c == 10 else COLS[c], lambda c=c: toggle_column(c))
            a.setCheckable(True)
            a.setChecked(bool(SETTINGS["status_col"]) if c == 10 else c in shown)
        a = m.addAction(COLS[0])   # 이름은 항상 (탐색기와 같게 끌 수 없음)
        a.setCheckable(True)
        a.setChecked(True)
        a.setEnabled(False)
        m.insertAction(m.actions()[0], a)
        return m

    # ---------------------------------------------------------- 탭별 정렬·열 너비 (다시 켜도·자동 기록에서도 그대로)
    def view_state(self):
        h = self.tree.header()
        return {"sort": [self.model_.sort_col, int(self.model_.sort_order.value)],
                "cols": [h.sectionSize(c) for c in range(h.count())], "color": self.tab_color, "locked": self.locked}

    def set_locked(self, on):
        on = bool(on)
        if on != self.locked:
            self.locked = on
            log.info("탭 %s %s", "잠금" if on else "잠금 해제", self.path)
            self.lockChanged.emit()

    def apply_view_state(self, vs):
        if not vs:
            return
        if labels.tab_hex(vs.get("color")):   # 이름 또는 직접 고른 '#rrggbb' (v0.9.90)
            self.tab_color = vs["color"]
        if vs.get("locked"):
            self.set_locked(True)
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
            col = OLD_SORT.get(int(col), int(col))   # 0.9.75 저장 번호 10~14 → 열 5~9
            if 0 <= col < h.count():
                self._vm_quiet = True
                try:
                    self.set_sort(int(col), Qt.SortOrder(int(order)))
                    self._vm_default_sort = (int(col), int(order))
                finally:
                    self._vm_quiet = False
        except Exception:
            log.exception("탭 정렬·열 너비 복원 실패 %s", vs)

    # ---------------------------------------------------------- 이동
    def navigate(self, path, record=True, select=None, force=False, checked=False):
        path = norm(path) or THIS_PC
        if ftpfs.is_url(path):   # 0.9.109 주소줄 ftp://사용자@서버/경로
            st, pth, pw0 = ftpfs.from_url(path)
            if pw0 is not None:
                try:
                    ftpfs.login(st, pw0)
                except Exception as ex:
                    self.status.emit(f"⚠ FTP: {ex}")
                    return False
            path = ftpfs.make(st, pth)
        if ftpfs.is_ftp(path) and not ftpfs.ready(ftpfs.split(path)[0]):   # 비밀번호 모름 → 연결 창
            r = ftpfs.login_dialog(self, ftpfs.split(path)[0], ftpfs.split(path)[1], SETTINGS["ftp_sites"])
            if not r:
                return False
            path = ftpfs.make(*r)
        if ftpfs.is_ftp(path):
            remember_ftp(ftpfs.split(path)[0])
        if archives.is_arc(path):   # 빌드 20 압축 안: 그 압축 파일이 있고 안쪽이 폴더일 때만
            ok = archives.is_dir(path) and archives.exists(path)
        else:
            ok = True if checked or path == THIS_PC or is_search(path) or devices.is_dev(path) else isdir_quick(path)   # checked = 뒤에서 이미 확인함
        if ok is None:
            # v0.9.96: 막 꽂은 외장하드처럼 응답이 늦은 드라이브 — 화면을 멈추지 않고 뒤에서 기다렸다가 이동
            # (전엔 os.path.isdir 에서 39.6초 '응답 없음', 11/5 사용자 제보·hang.log 확인)
            self._nav_wait += 1
            wid = self._nav_wait
            log.info("드라이브 응답 기다림 → 뒤에서 확인 후 이동 %s", path)
            self.status.emit(T("⏳ 드라이브가 응답하기를 기다리는 중: {0}").format(path))
            args = (path, record, select, force)

            def wait_dir():
                r = os.path.isdir(path)
                self.navWaitDone.emit(wid, r, args)
            threading.Thread(target=wait_dir, daemon=True).start()
            return False
        if not ok:
            log.info("이동 실패(폴더 아님) %s", path)
            self.status.emit(T('⚠ 폴더를 찾을 수 없습니다: {0}').format(path))
            return False
        if self.locked and not force and self.path and path != self.path:   # 잠긴 탭은 그 폴더에 그대로 → 새 탭으로 (v0.9.95)
            log.info("잠긴 탭 %s → 새 탭으로 %s", self.path, path)
            self.lockedNav.emit(path, select)
            return False
        if record and self.path and self.path != path:
            self.back.append(self.path)
            self.fwd.clear()
        old = self.path
        self.path = path
        self.pending_select = select
        if old != path:
            if old:
                self.from_locked = False
            self.model_.filter = ""   # 다른 폴더로 가면 빠른 필터 해제
            self.model_.ext_filter = set()   # 형식 단추도 (빌드 17)
            if THUMBS is not None and old:
                THUMBS.drop_pending(old)   # 떠난 폴더의 아직 안 만든 미리보기 요청은 버림
        if self.active:
            self._watch(old, path)
        log.info("이동 %s -> %s", old, path)
        if old != path and path != THIS_PC and not is_search(path) and not archives.is_arc(path) and not devices.is_dev(path):
            FRECENT.visit(path)   # 0.9.116 자주 간 폴더
        if old != path:
            self.apply_view_memory(path)   # 0.9.116 폴더마다 보기 기억
            self.git_branch = None   # 새 폴더의 Git 상태가 올 때까지 가지 이름 지움
        self.pathChanged.emit(path)
        self.reload(reason="nav")
        return True

    def _on_nav_wait(self, wid, ok, args):
        if wid != self._nav_wait:
            return   # 그사이 다시 기다리기 시작함
        path, record, select, force = args
        log.info("드라이브 응답 옴 %s → %s", path, "이동" if ok else "폴더 아님")
        if ok:
            self.navigate(path, record, select, force, checked=True)
        else:
            self.status.emit(T('⚠ 폴더를 찾을 수 없습니다: {0}').format(path))

    def go_back(self):
        if self.back and self.locked:   # 잠긴 탭: 기록은 그대로 두고 그 폴더를 새 탭으로
            return self.navigate(self.back[-1], record=False)
        if self.back:
            cur = self.path
            p = self.back.pop()
            self.fwd.append(cur)
            self.navigate(p, record=False, select=os.path.basename(cur) if os.path.dirname(cur) == p else None)

    def go_fwd(self):
        if self.fwd and self.locked:
            return self.navigate(self.fwd[-1], record=False)
        if self.fwd:
            self.back.append(self.path)
            self.navigate(self.fwd.pop(), record=False)

    def go_up(self):
        if self.path == THIS_PC:
            return
        if devices.is_dev(self.path):   # 휴대폰: 셸 부모 (맨 위면 내 PC)
            self.navigate(devices.parent_of(self.path) or THIS_PC, select=devices.name_of(self.path))
            return
        if archives.is_arc(self.path):   # 압축 안: 한 단계 위 (맨 위면 압축 파일이 있는 폴더, 그 파일 고름)
            self.navigate(archives.parent_of(self.path), select=archives.name_of(self.path))
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
        if self._fsize_job is not None:   # 폴더 크기 재던 것 중단 (다 읽으면 다시)
            self._fsize_job.cancel()
            self._fsize_job = None
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
        if self._fsize_job is not None:
            self._fsize_job.cancel()

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
        if path == THIS_PC:   # v0.9.96: 막 꽂은 드라이브는 이름·아이콘이 늦게 옴(시간 초과 → 폴더 그림) → 5·10·15·20초 뒤 다시
            late = [e[0] for e in entries if e[6] is None]
            if late and self._pc_retry < 4:
                self._pc_retry += 1
                log.info("내 PC 드라이브 정보 늦음 %s → %d초 뒤 다시 읽기 (%d번째)", late, 5 * self._pc_retry, self._pc_retry)
                QtCore.QTimer.singleShot(5000 * self._pc_retry, lambda: self.path == THIS_PC and self.reload(reason="pc_retry"))
            elif not late:
                self._pc_retry = 0
        keep = self.keep_sel if self.model_.path == path else None
        if keep is not None and self.model_.rows:
            # 읽는 동안 사용자가 고른 것(예: 이름 바꾸고 바로 다른 파일 클릭)을 살림 — 요청 때가 아니라 지금 선택 기준
            keep = self._sel_snapshot()
        self.keep_sel = None
        if is_search(path) and parse_search(path)[1]:
            self.model_.sort(self.model_.sort_col, self.model_.sort_order)   # 폴더 아래 찾기: 다 모은 뒤 정렬
        else:
            self.model_.set_entries(path, entries)
            self.apply_columns()   # 상태 열: 동기화 폴더에서만 (v0.9.94)
            if is_search(path) and not entries and not err and not tags.is_view(parse_search(path)[0]):   # 0.9.110: 빈 태그·그룹엔 검색 범위 안내 안 함
                # 빠른 검색 0개: 네트워크·구글드라이브 등은 처음엔 검색 범위 밖이라 '고장'처럼 보임 → 이유와 범위 설정 안내 (v0.9.68, 10/29)
                main = main_of(self)
                log.info("전체 검색 0개 '%s' → 범위 안내", parse_search(path)[0])
                if main is not None:
                    main.show_notice(T("'{0}' 을(를) 찾지 못했습니다. 네트워크·구글드라이브 같은 곳은 처음엔 검색 범위에 없습니다  ✕")
                                     .format(parse_search(path)[0]), sticky=False, ms=12000,
                                     action=(T("검색 범위 설정…"), main.open_search_roots))
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
                self._start_fsize()
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
        self._start_fsize()
        self.typesChanged.emit()

    # ---------------------------------------------------------- 폴더 크기 (v0.9.89 사용자 11/4)
    def _start_fsize(self):
        """하위 폴더 크기를 뒤에서 재서 크기 칸에 하나씩 (네트워크 드라이브는 안 함). 잰 값은 5분 기억"""
        if self._fsize_job is not None:
            self._fsize_job.cancel()
            self._fsize_job = None
        p = self.path
        if not SETTINGS["folder_size"] or p == THIS_PC or is_search(p) or devices.is_dev(p) or archives.is_arc(p) or foldersize.is_remote(p):
            return
        names = [e[0] for e in self.model_.all if e[1] and not e[5]]
        if not names:
            return
        gen = self.gen
        self._fsize_job = foldersize.Job(p, names, lambda n, sz, g=gen: self.fsizeFound.emit(g, n, sz),
                                         lambda g=gen: self.fsizeDone.emit(g))
        self._fsize_job.start()

    def _on_fsize(self, gen, name, size):
        if gen != self.gen:
            return
        for e in self.model_.all:
            if e[1] and e[0] == name:
                e[2] = size
                break
        for r, e in enumerate(self.model_.rows):
            if e[0] == name:
                ix = self.model_.index(r, 3)
                self.model_.dataChanged.emit(ix, ix, [Qt.DisplayRole])
                break

    def _on_fsize_done(self, gen):
        self._fsize_job = None
        if gen == self.gen and self.model_.sort_col == 3:   # 크기순이면 다 잰 뒤 한 번 다시 정렬
            self.model_.sort(3, self.model_.sort_order)

    # ---------------------------------------------------------- SVN 상태 (TortoiseSVN 겹침 아이콘 대신 장부 직접 읽기)
    def refresh_svn(self, entries=None):
        p = self.path
        if not OPTS["svn_status"] or p == THIS_PC or is_search(p) or devices.is_dev(p) or archives.is_arc(p) or not os.path.isdir(p):
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
        self.git_branch = st.pop("\0branch", None)   # 0.9.116 Git 가지 이름 (상태줄)
        self.model_.svn = st
        self._emit_status()
        root = svnstat.wc_root(path) if st and not self.git_branch else None
        self.svn_root, self.svn_mtime = root, (svnstat.wc_db_mtime(root) if root else 0.0)
        self.view().viewport().update()

    def svn_changed(self):
        """커밋·업데이트는 이 폴더 파일이 아니라 장부(wc.db)만 바꿈 → 창이 다시 활성화될 때 장부 시각으로 확인"""
        r = getattr(self, "svn_root", None)
        if r and OPTS["svn_status"] and svnstat.wc_db_mtime(r) != self.svn_mtime:
            log.info("SVN 장부 바뀜 → 상태 다시 읽음 %s", self.path)
            self.refresh_svn()

    def set_ext_filter(self, kinds):
        """형식 단추 (빌드 17): kinds = {'.jpg', '/'(폴더) …}, 빈 것 = 전체"""
        self.model_.ext_filter = set(kinds)
        self.set_filter(self.model_.filter)
        log.info("형식 거르기 %s → %d/%d", sorted(kinds) or "전체", self.model_.count(), len(self.model_.all))

    def set_filter(self, text):
        self.model_.set_filter(text)
        log.debug("빠른 필터 '%s' → %d/%d", text, len(self.model_.rows), len(self.model_.all))
        if self.model_.rows:
            self.sel.setCurrentIndex(self.model_.index(0, 0), QtCore.QItemSelectionModel.NoUpdate)
        self._emit_status()

    def _emit_status(self):
        n = self.model_.count()
        sr = self.selected_rows()
        s = len(sr)
        txt = T('{0:,}개 항목').format(n)   # 탐색기 상태줄과 같은 말 (읽기 ms 는 상태줄 풍선 도움말로)
        if is_search(self.path):
            q, f = parse_search(self.path)
            txt = f"🔎 '{q}'" + (T(' ({0} 아래)').format(f) if f else T(" (전체)")) + f": {self.search_info}"
        elif self.model_.filter:
            txt = T("필터 '{0}': {1:,} / 전체 {2:,}개").format(self.model_.filter, n, len(self.model_.all))
        elif getattr(self.model_, "ext_filter", None):
            txt = T("형식 {0}: {1:,} / 전체 {2:,}개").format(" · ".join(kind_label(k) for k in sorted(self.model_.ext_filter)), n, len(self.model_.all))
        if s:
            txt += T('    {0:,}개 항목 선택함').format(s)
            fs = [self.model_.rows[r][2] for r in sr if not self.model_.rows[r][1] and self.model_.rows[r][2] >= 0]
            if fs:   # 탐색기처럼 선택한 파일들 크기 합 (폴더는 빼고)
                txt += "  " + size_short(sum(fs))
        self.status_tip = T('읽기 {0:.0f}ms').format(self.last_ms)
        if getattr(self, "svn_pending", False):
            txt += T("   |   SVN 확인 중…")
        if getattr(self, "git_branch", None):
            txt += "   |   " + T("Git 가지: {0}").format(self.git_branch)
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
        if new and new != THIS_PC and not is_search(new) and not devices.is_dev(new) and not archives.is_arc(new):   # 휴대폰·압축은 감시 못 함 → F5
            self.watcher.addPath(new)
            m = main_of(self)
            if m is not None:
                m.note_drive(new)   # v0.9.96 꺼내기 전에 감시를 풀 수 있게
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
        if is_group(e):
            return
        fp = self.model_.full(e)
        if e[1]:
            self.navigate(fp)
            return
        if archives.is_arc(fp):   # 빌드 20 압축 안 파일: 임시 폴더에 풀어서 엶
            self.status.emit(T("압축에서 꺼내는 중: {0}").format(e[0]))
            QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                real = archives.extract_temp([fp])
            except Exception as ex:
                real = []
                log.exception("압축 안 파일 열기 실패 %s", fp)
                self.status.emit(f"⚠ {ex}")
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            if real:
                log.info("압축 안 파일 열기 %s → %s", fp, real[0])
                try:
                    os.startfile(real[0])
                except OSError as ex:
                    self.status.emit(f"⚠ {ex}")
            return
        if SETTINGS["arc_browse"] and archives.is_archive_file(fp) and os.path.isfile(fp):   # 압축 파일 → 4Dir 안에서 폴더처럼 (설정에서 끔)
            log.info("압축 파일 안으로 %s", fp)
            self.navigate(archives.make(fp))
            return
        if devices.is_dev(fp):   # 휴대폰 안 파일: 임시 폴더로 받아서 엶 (탐색기와 같게)
            self.status.emit(T("휴대폰에서 받는 중: {0}").format(e[0]))
            devices.open_file(self.hwnd(), fp, e[0],
                              done=lambda ok, err, loc: DEV_SIG.done.emit("", ok, err or "", ""))
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

    def _arc_real(self, ps):
        """압축 안 항목 → 임시 폴더에 푼 진짜 경로 (보통 경로는 그대로). 실패하면 None"""
        if not any(archives.is_arc(p) for p in ps):
            return ps
        self.status.emit(T("압축에서 꺼내는 중… {0}개").format(len(ps)))
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            real = archives.extract_temp([p for p in ps if archives.is_arc(p)]) + [p for p in ps if not archives.is_arc(p)]
        except Exception as ex:
            log.exception("압축에서 꺼내기 실패")
            self.status.emit(f"⚠ {ex}")
            return None
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        return real

    def do_copy(self, cut=False):
        ps = self.selected_paths()
        if ps and any(archives.is_arc(p) for p in ps):   # 빌드 20 압축 안: 임시 폴더에 풀어 진짜 파일로 클립보드 (탐색기에도 붙여넣기 됨, 잘라내기는 복사로)
            real = self._arc_real(ps)
            if real:
                DEV_CLIP["paths"] = None
                shellops.set_clipboard(real, False)
                self.status.emit(T('{0}개 {1} 됨').format(len(real), T('복사')) + (T(" (압축 안은 잘라내기 대신 복사)") if cut else ""))
            return
        if ps and any(devices.is_dev(p) for p in ps):   # 휴대폰 항목: 윈도우 클립보드에 셸 데이터(탐색기·바탕화면 붙여넣기) + 4Dir 안 붙여넣기용 기억
            on_clip = devices.to_clipboard(ps) if all(devices.is_dev(p) for p in ps) else False
            DEV_CLIP.update(paths=list(ps), cut=cut, seq=shellops.clipboard_info()["seq"])
            log.info("휴대폰 항목 %s %d개 (윈도우 클립보드 %s)", "잘라내기" if cut else "복사", len(ps), on_clip)
            self.status.emit(T('{0}개 {1} 됨').format(len(ps), T('잘라내기') if cut else T('복사')))
            return
        DEV_CLIP["paths"] = None
        if ps and self.path != THIS_PC:
            shellops.set_clipboard(ps, cut)
            self.status.emit(T('{0}개 {1} 됨').format(len(ps), T('잘라내기') if cut else T('복사')))

    def do_paste(self):
        if self.path == THIS_PC or is_search(self.path):
            return
        if archives.is_arc(self.path) and not archives.is_ftp(self.path):   # FTP 는 올리기 (0.9.109)
            self.status.emit(T("⚠ 압축 파일 안은 읽기 전용입니다 (넣기·지우기·이름 바꾸기 안 됨)"))
            return
        if DEV_CLIP["paths"] and DEV_CLIP["seq"] == shellops.clipboard_info()["seq"]:   # 휴대폰에서 복사한 것 (그 뒤 다른 복사 없음)
            ps, cut = list(DEV_CLIP["paths"]), DEV_CLIP["cut"]
            if cut:
                DEV_CLIP["paths"] = None
            log.info("휴대폰 항목 붙여넣기 %d개 → %s", len(ps), self.path)
            self.file_op(ps, self.path, cut, select_in=self)
            return
        ps, cut = shellops.get_clipboard()
        if ps:
            log.info("붙여넣기 %d개 → %s", len(ps), self.path)
            self.file_op(ps, self.path, cut, select_in=self)
        elif self.paste_image():   # 0.9.116 빌드 3 (사용자 11/8 #7): 캡처한 그림 → 지금 폴더에 PNG 파일
            return
        else:   # 예전엔 조용히 끝남 → 원인 확정용으로 클립보드 상태 기록 (10/8 '붙여넣기 안 됨' 간헐)
            info = shellops.clipboard_info()
            changed = info["seq"] != shellops._CLIP_SEQ[0]
            log.warning("붙여넣기: 클립보드에 파일 없음 — %s, 마지막 복사 뒤 바뀜=%s (순번 %d → %d)",
                        info, changed, shellops._CLIP_SEQ[0], info["seq"])
            self.status.emit(T("⚠ 클립보드에 파일이 없습니다"))

    def paste_image(self):
        """클립보드에 파일은 없고 그림만 있으면(캡처·그림 프로그램에서 복사) 지금 폴더에 PNG 로 저장하고 이름 편집 (Files·Directory Opus 처럼)"""
        if archives.is_arc(self.path) or devices.is_dev(self.path) or not os.path.isdir(self.path):
            return False
        md = QtWidgets.QApplication.clipboard().mimeData()
        if md is None or not md.hasImage():
            return False
        img = QtGui.QImage(md.imageData())
        if img.isNull():
            log.warning("붙여넣기: 클립보드 그림을 읽지 못함 (형식 %s)", md.formats()[:8])
            return False
        base = T("붙여넣은 그림") + time.strftime("_%Y%m%d_%H%M%S")
        name, k = base + ".png", 1
        while os.path.exists(os.path.join(self.path, name)):
            name, k = f"{base} ({k}).png", k + 1
        dest = os.path.join(self.path, name)
        t0 = time.time()
        if not img.save(dest, "PNG"):
            log.error("붙여넣기: 그림 저장 실패 %s", dest)
            self.status.emit(T("⚠ 그림을 저장하지 못했습니다: {0}").format(dest))
            return True
        log.info("클립보드 그림 → %s (%dx%d, %d바이트, %.2f초)", dest, img.width(), img.height(), os.path.getsize(dest), time.time() - t0)
        self.status.emit(T("클립보드 그림을 저장했습니다: {0} ({1}×{2})").format(name, img.width(), img.height()))
        self.pending_edit = name
        self.reload(reason="paste_image")
        return True

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
        log.info("다른 칸으로 %s n=%d -> %s", "이동" if move else "복사", len(ps), tab_title(target.path))
        self.file_op(ps, target.path, move, select_in=target)
        self.status.emit(T('{0}개 {1} → {2}').format(len(ps), T('이동') if move else T('복사'), disp_path(target.path)))

    def do_delete(self, permanent=False):
        ps = self.selected_paths()
        if archives.is_ftp(self.path):   # 0.9.109 FTP: 휴지통 없음 → 확인 후 서버에서 지움
            if ps and QtWidgets.QMessageBox.question(self, T("FTP 지우기"), T("서버에서 {0}개를 지웁니다 (휴지통 없음). 계속할까요?").format(len(ps))) == QtWidgets.QMessageBox.Yes:
                self._ftp_bg(lambda: ftpfs.delete(ps), self.path, T("FTP 지움 {0}개").format(len(ps)))
            return
        if archives.is_arc(self.path):
            self.status.emit(T("⚠ 압축 파일 안은 읽기 전용입니다 (넣기·지우기·이름 바꾸기 안 됨)"))
            return
        if ps and any(devices.is_dev(p) for p in ps):   # 휴대폰: 휴지통 없음 → 윈도우가 영구 삭제를 물어봄
            here = self.path
            devices.run_op("delete", self.hwnd(), ps, done=lambda ok, err: DEV_SIG.done.emit(here, ok, err, ""))
            return
        if ps and self.path != THIS_PC:   # 검색 결과에서도 됨 (전체 경로)
            def done(res, aborted, ps=ps):   # 작업 스레드에서 불림
                gone = [p for p in ps if not os.path.exists(p)]
                if gone and not permanent:   # 휴지통으로 간 것 → Ctrl+Z 로 복원 (탐색기와 같게, 10/6 사용자 요청)
                    push_undo("delete", gone, T('삭제 {0}개 ({1})').format(len(gone), os.path.basename(gone[0])))
            shellops.delete(self.hwnd(), ps, permanent, done=done)

    def file_op(self, srcs, tgt, move, select_in=None):
        """복사·이동 (셸 작업) + 되돌리기 기록 + 보고 있는 칸이면 새로 생긴 것 선택"""
        if archives.is_ftp(tgt):   # 0.9.109 FTP 로 올리기 (압축·FTP 안 것은 먼저 꺼내서) — 이동도 복사로
            real = self._arc_real(list(srcs))
            if real:
                log.info("FTP 올리기 %d개 → %s", len(real), archives.friendly(tgt))
                self._ftp_bg(lambda: ftpfs.upload(real, tgt), tgt, T("FTP 올림 {0}개 → {1}").format(len(real), archives.friendly(tgt)))
            return
        if archives.is_arc(tgt):   # 빌드 20: 압축 안에는 못 넣음
            self.status.emit(T("⚠ 압축 파일 안은 읽기 전용입니다 (넣기·지우기·이름 바꾸기 안 됨)"))
            return
        if any(archives.is_arc(x) for x in srcs):   # 압축 안 → 임시 폴더에 풀어 보통 복사 (이동은 복사로)
            real = self._arc_real(list(srcs))
            if not real:
                return
            log.info("압축에서 꺼내 %s → %s (%d개)", "복사" if not move else "복사(이동 대신)", tgt, len(real))
            srcs, move = real, False
        if devices.is_dev(tgt) or any(devices.is_dev(s) for s in srcs):   # 휴대폰이 끼면 IFileOperation (되돌리기 기록 없음)
            src_dir = devices.parent_of(srcs[0]) if devices.is_dev(srcs[0]) else os.path.dirname(os.path.normpath(srcs[0]))

            def done(ok, err):
                DEV_SIG.done.emit(tgt, ok, err, "")
                if move and src_dir:
                    DEV_SIG.done.emit(src_dir, ok, "", "")
            devices.run_op("move" if move else "copy", self.hwnd(), list(srcs), tgt, done=done)
            return
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
        if archives.is_arc(self.path) and not archives.is_ftp(self.path):
            self.status.emit(T("⚠ 압축 파일 안은 읽기 전용입니다 (넣기·지우기·이름 바꾸기 안 됨)"))
            return
        if len(ps) > 1:   # 여러 개 → 이름 일괄 변경 창 (하나면 그 자리에서)
            m = main_of(self)
            if m is not None:
                m.open_batch_rename(ps)
            return
        idx = self.view().currentIndex()
        if idx.isValid() and self.path != THIS_PC:
            self.view().edit(self.model_.index(idx.row(), 0))

    def do_new_folder(self):
        if archives.is_ftp(self.path):   # 0.9.109 FTP 새 폴더
            name, ok = QtWidgets.QInputDialog.getText(self, T("새 폴더"), T("이름"), text=T("새 폴더"))
            if ok and name.strip():
                here = self.path
                self._ftp_bg(lambda: ftpfs.mkdir(here, name.strip()), here, T("FTP 새 폴더: {0}").format(name.strip()))
            return
        if archives.is_arc(self.path):
            self.status.emit(T("⚠ 압축 파일 안은 읽기 전용입니다 (넣기·지우기·이름 바꾸기 안 됨)"))
            return
        if self.path == THIS_PC:
            self.status.emit(T("⚠ 내 PC 에는 새 폴더를 만들 수 없습니다"))
            return
        if is_search(self.path):
            self.status.emit(T("⚠ 검색 결과에는 새 폴더를 만들 수 없습니다"))
            return
        base, n = T("새 폴더"), 1
        name = base
        if devices.is_dev(self.path):   # 휴대폰 안 새 폴더
            have = {e[0].lower() for e in self.model_.all}
            while name.lower() in have:
                n += 1
                name = f"{base} ({n})"
            here = self.path
            log.info("휴대폰 새 폴더 %s", name)
            devices.run_op("newfolder", self.hwnd(), [], here, name, done=lambda ok, err: DEV_SIG.done.emit(here, ok, err, name))
            return
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
        if ev.text() and ev.text() != " " and ev.text().isprintable():
            self._typed_at = time.time()   # 이름 첫 글자로 찾는 중이면 스페이스는 글자로 (빌드 20)
        act = VIEW_KEYS.get(keymap.event_key(ev))
        if not act:
            return False
        if act == "quick_preview" and time.time() - getattr(self, "_typed_at", 0) < 1.0:
            return False
        return self.run_action(act)

    def run_action(self, act):
        """파일 목록 기능 실행 (단축키·마우스 버튼 공용) → 처리했으면 True"""
        if act == "open":
            self.open_selected()
        elif act == "open_new_tab":
            for p in self.selected_paths():
                if os.path.isdir(p):
                    self.openInNewTab.emit(p)
            self.open_location(new_tab=True, files_only=True)   # v0.9.94: 파일이면 그 폴더 위치 (Everything 경로 열기처럼)
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
        elif act == "select_pattern":
            self.select_pattern()
        elif act == "sha256":
            self.show_sha256()
        elif act == "quick_preview":   # 빌드 20 스페이스: 미리보기 창 켜기/끄기 (고른 파일)
            m = main_of(self)
            if m is not None:
                m.set_preview(not (SETTINGS["preview_pane"] and PREVIEW_WIN is not None and PREVIEW_WIN.isVisible()))
        elif act == "flat_view":
            self.flat_view()
        elif act == "find_dupes":
            m = main_of(self)
            if m is not None:
                m.find_dupes(self)
        elif act == "view_file":   # 0.9.109
            self.view_file()
        elif act == "file_attrs":
            ps = self.selected_paths()
            if ps and self.path != THIS_PC and not archives.is_arc(self.path):
                self.file_attrs(ps)
        elif act == "img_batch":
            ps = [p for p in self.selected_paths() if imgbatch.is_image(p)]
            if ps:
                self.img_batch(ps)
        elif act == "space_map":
            ds = [p for p in self.selected_paths() if os.path.isdir(p)]
            self.space_map(ds[0] if ds else self.path)
        else:
            return False
        return True

    # ---------------------------------------------------------- 0.9.109 빌드 3 추가 기능 (칸)
    def view_file(self):
        """F3 글자·16진수 보기 (압축·FTP 안 파일은 꺼내서)"""
        cur = self.selected_paths()
        ps = [p for p in cur if not archives.is_arc(p) and os.path.isfile(p)]
        if not ps and cur and archives.is_arc(cur[0]):
            ps = [p for p in (self._arc_real(cur[:1]) or []) if os.path.isfile(p)]
        if not ps:
            self.status.emit(T("⚠ 파일을 고르세요"))
            return
        dlg = hexview.ViewerDialog(ps[0], self.window())
        dlg.setStyleSheet(self.window().styleSheet())
        dlg.show()
        return dlg

    def set_rating(self, paths, n):
        """별점 주기 (0.9.116) — n=0 이면 빼기"""
        paths = [p for p in (paths or self.selected_paths()) if not archives.is_arc(p) and not devices.is_dev(p)]
        if not paths:
            self.status.emit(T("⚠ 파일을 고르세요"))
            return
        RATINGS.set(paths, n)
        refresh_ratings_ui(show_col=bool(n))
        self.status.emit((T("별점 {0}: {1}개").format(labels.Ratings.text(n), len(paths))) if n else T("별점 뺌: {0}개").format(len(paths)))

    def more_tools(self, paths, dirs):
        """0.9.116 (사용자 11/8 새 기능 33개): 우클릭 '4Dir 도구 ▸' 에 더할 것 [(글자, 함수 또는 하위 목록)]"""
        out = []
        files = [p for p in paths if os.path.isfile(p)]
        imgs = [p for p in files if imginspect.can_open(p)]
        if len(imgs) == 1:
            out.append((ti(T("그림 자세히 보기…"), "imginspect"), lambda: open_tool(imginspect.open_viewer, self.window(), imgs[0])))
        if len(files) == 1 and imgedit.can_edit(files[0]):   # 0.9.118
            out.append((ti(T("그림 편집…"), "imgedit"), lambda: open_img_edit(files[0], self.window())))
        if len(imgs) == 2:
            out.append((ti(T("두 그림 비교…"), "imgcompare"), lambda: open_tool(imginspect.open_compare, self.window(), imgs[0], imgs[1])))
        pics = [p for p in files if thumbs.is_image(os.path.basename(p))]
        if len(files) == 1 and seq_in_view(self, files[0]) is not None:
            out.append((ti(T("연번 그림 재생…"), "sequence"), lambda: open_tool(sequence.open_player, self.window(), os.path.dirname(files[0]), files[0])))
        if len(pics) >= 2:
            out.append((ti(T("스프라이트 시트 만들기…"), "sheetpack"), lambda: open_tool(sheets.open_pack, self.window(), pics)))
            out.append((ti(T("밀착 인화 (검수용 한 장)…"), "contact"), lambda: open_tool(sheets.open_contact, self.window(), pics)))
        if len(pics) == 1:
            out.append((ti(T("시트 자르기…"), "sheetslice"), lambda: open_tool(sheets.open_slice, self.window(), pics[0])))
        loc = main_of(self).open_loc if main_of(self) is not None else None
        pdfs = [p for p in files if p.lower().endswith(".pdf")]
        if len(pdfs) >= 2 or (pdfs and len(pics) and len(pdfs) + len(pics) == len(files)):
            out.append((ti(T("PDF 합치기…"), "pdf"), lambda: open_tool(pdftools.open_merge, self.window(), pdfs + pics if len(pdfs) + len(pics) == len(files) else pdfs, open_loc=loc)))
        if len(pdfs) == 1 and len(files) == 1:
            out.append((ti(T("PDF 편집 (쪽·주석·나누기)…"), "pdf"), lambda: open_tool(pdfedit.open_editor, self.window(), pdfs[0], open_loc=loc)))   # 0.9.123 나누기 창을 합침 (사용자 11/10)
        if pics and not pdfs:
            out.append((ti(T("그림을 PDF 한 파일로 묶기…"), "pdf"), lambda: open_tool(pdftools.open_images_to_pdf, self.window(), pics, open_loc=loc)))
        if len(files) == 2 and all(textdiff_ok(p) for p in files):
            out.append((ti(T("두 글자 파일 비교…"), "diff"), lambda: open_tool(textdiff.open_dialog, self.window(), files[0], files[1])))
        real = [p for p in paths if os.path.exists(p) and not archives.is_arc(p) and not devices.is_dev(p)]
        if real:
            out.append((ti(T("이 파일을 잡고 있는 프로그램…"), "lock"), lambda: open_tool(locksmith.open_dialog, self.window(), real)))
            other = main_of(self).other_pane(main_of(self).pane()) if main_of(self) is not None else None
            ov = other.view() if other is not None else None
            dest = ov.path if ov is not None and ov.path and os.path.isdir(ov.path) and not archives.is_arc(ov.path) else self.path
            out.append((ti(T("링크 만들기 (다른 칸에)…") if dest != self.path else T("링크 만들기…"), "link"),
                        lambda: open_tool(fileutil.make_link, self.window(), real, dest)))
        if dirs and len(dirs) == 1:
            out.append((ti(T("내용 찾기 (이 폴더 안 파일 속 글자)…"), "grep"), lambda: self.grep_here(dirs[0])))
            other = main_of(self).other_pane(main_of(self).pane()) if main_of(self) is not None else None
            ov = other.view() if other is not None else None
            # 빌드 4 (사용자: 메뉴가 안 나온다 — 다른 칸이 '내 PC' 면 숨겼음) → 늘 보이고, 다른 칸에 폴더가 없으면 넣을 곳을 고름
            if ov is not None and ov.path and os.path.isdir(ov.path) and not archives.is_arc(ov.path):
                out.append((ti(T("폴더 구조만 복사 (파일 없이) → 다른 칸"), "flat"), lambda: self.copy_structure(dirs[0], ov.path)))
            else:
                out.append((ti(T("폴더 구조만 복사 (파일 없이)…"), "flat"), lambda: self.copy_structure_pick(dirs[0])))
        if len(files) == 1:
            if files[0].lower().endswith(".001"):
                out.append((ti(T("조각 파일 합치기…"), "split"), lambda: open_tool(fileutil.open_join, self.window(), files[0])))
            else:
                out.append((ti(T("파일 나누기 (메일 첨부용 조각)…"), "split"), lambda: open_tool(fileutil.open_split, self.window(), files[0])))
        if files and os.path.isdir(self.path) and not archives.is_arc(self.path):
            out.append((ti(T("날짜별 폴더로 정리…"), "datefolders"),
                        lambda: open_tool(datefolders.open_dialog, self.window(), files, self.path, on_done=lambda: self.reload("datefolders"))))
        if files:
            out.append((ti(T("여러 파일 한 번에 인쇄…"), "print"), lambda: self.print_files(files)))
        return out

    def grep_here(self, folder=None):
        folder = folder or self.path
        m = main_of(self)
        return open_tool(grepsearch.open_dialog, self.window(), folder, open_cb=(lambda p, line=None: m.open_loc(p, line)) if m else None)

    def copy_structure_pick(self, src):
        """넣을 폴더를 골라 구조만 복사 (다른 칸에 폴더가 없을 때)"""
        dst = QtWidgets.QFileDialog.getExistingDirectory(self.window(), T("폴더 구조를 넣을 곳 고르기"), os.path.dirname(src))
        log.info("구조만 복사 넣을 곳 고름 %s → %r", src, dst)
        if dst:
            self.copy_structure(src, os.path.normpath(dst))

    def copy_structure(self, src, dst_parent):
        """폴더 구조만 복사 (0.9.116 #20) — 뒤 스레드, 끝나면 알림"""
        sg = _undo_signal()
        self.status.emit(T("폴더 구조 복사 중: {0}…").format(os.path.basename(src)))

        def run():
            try:
                n = fileutil.copy_tree_only(src, dst_parent)
                sg.done.emit(T("폴더 구조만 복사함: 폴더 {0}개 → {1}").format(n, dst_parent) + "  ✕")
            except Exception as ex:
                log.exception("구조만 복사 실패 %s → %s", src, dst_parent)
                sg.done.emit(T("⚠ 복사하지 못했습니다: {0}").format(ex) + "  ✕")
        threading.Thread(target=run, daemon=True, name="copytree").start()

    def more_tools_here(self):
        """0.9.116: 빈 곳 우클릭 '4Dir 도구 ▸' 에 더할 것 (지금 폴더 대상)"""
        out = []
        folder = self.path if self.path and os.path.isdir(self.path) and not archives.is_arc(self.path) else None
        if folder:
            out.append((ti(T("내용 찾기 (파일 속 글자)…"), "grep"), lambda: self.grep_here(folder)))
            seqs = view_sequences(self)
            if seqs:
                out.append((ti(T("연번 그림 재생…"), "sequence"),
                            [(f"{q.display}  ({q.count})", (lambda q=q: open_tool(sequence.open_player, self.window(), folder, q)))
                             for q in seqs[:20]]))
        return out

    def print_files(self, paths):
        """고른 문서·그림을 기본 프린터로 차례대로 (윈도우 '인쇄' 동작 — 프로그램마다 다르게 처리). 확인 받고 보냄"""
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            return
        names = "\n".join("• " + os.path.basename(p) for p in paths[:12]) + ("\n…" if len(paths) > 12 else "")
        if QtWidgets.QMessageBox.question(self.window(), T("여러 파일 한 번에 인쇄"),
                                          T("파일 {0}개를 기본 프린터로 보냅니다.\n\n{1}\n\n파일마다 그 파일을 여는 프로그램이 잠깐 열릴 수 있습니다.").format(len(paths), names)) \
                != QtWidgets.QMessageBox.Yes:
            log.info("인쇄 취소 (%d개)", len(paths))
            return
        ok, fails = 0, []
        for p in paths:
            try:
                os.startfile(p, "print")
                ok += 1
            except OSError as ex:
                fails.append((p, ex))
                log.warning("인쇄 실패 %s: %s", p, ex)
        log.info("인쇄 보냄 %d개 / 실패 %d개", ok, len(fails))
        msg = T("인쇄로 보냄: {0}개").format(ok)
        if fails:
            msg = "⚠ " + msg + T(" · 인쇄할 수 없는 파일 {0}개 (예: {1})").format(len(fails), os.path.basename(fails[0][0]))
        self.status.emit(msg)

    def list_rows(self, selected_only=False):
        """지금 목록(거른 그대로 보이는 순서) → [(이름, 전체 경로, 크기, 수정 시각, 폴더인지)]"""
        m = self.model_
        sel = set(os.path.normcase(p) for p in self.selected_paths()) if selected_only else None
        out = []
        for e in m.rows:
            if e[0] is None or (len(e) > 7 and e[7]):   # 묶음 머리줄·내 PC 항목
                continue
            full = m.full(e)
            if sel is not None and os.path.normcase(full) not in sel:
                continue
            out.append((e[0], full, e[2], e[3], bool(e[1])))
        return out

    def export_list(self, kind, selected_only=False, dest=None):
        """파일 목록 내보내기 (0.9.116 #23): names·paths = 클립보드, table = 탭 나눈 표 클립보드(엑셀에 붙여넣기), csv = 파일로 저장"""
        rows = self.list_rows(selected_only)
        if not rows:
            self.status.emit(T("⚠ 내보낼 항목이 없습니다"))
            return None
        if kind == "names":
            text = "\r\n".join(r[0] for r in rows)
        elif kind == "paths":
            text = "\r\n".join(r[1] for r in rows)
        else:
            head = [T("이름"), T("크기(바이트)"), T("수정한 날짜"), T("종류"), T("전체 경로")]
            lines = [head] + [[r[0], "" if r[4] or r[2] < 0 else str(r[2]),
                               time.strftime("%Y-%m-%d %H:%M", time.localtime(r[3])) if r[3] else "",
                               T("폴더") if r[4] else (os.path.splitext(r[0])[1].lstrip(".").upper() or T("파일")), r[1]] for r in rows]
            if kind == "csv":
                import csv
                if dest is None:
                    base = os.path.basename(self.path.rstrip("\\")) or "list"
                    start = os.path.join(os.path.expanduser("~"), "Documents", f"{base}_{T('파일 목록').replace(' ', '_')}_{time.strftime('%Y%m%d')}.csv")
                    dest, _f = QtWidgets.QFileDialog.getSaveFileName(self.window(), T("파일 목록 저장"), start, "CSV (*.csv)")
                    if not dest:
                        return None
                try:
                    with open(dest, "w", encoding="utf-8-sig", newline="") as f:   # 엑셀이 한글을 바로 읽게 BOM
                        csv.writer(f).writerows(lines)
                except OSError as ex:
                    log.exception("목록 저장 실패 %s", dest)
                    self.status.emit(T("⚠ 저장하지 못했습니다: {0}").format(ex))
                    return None
                log.info("파일 목록 CSV 저장 %s (%d줄)", dest, len(rows))
                self.status.emit(T("파일 목록 {0}개를 저장했습니다: {1}").format(len(rows), dest))
                return dest
            text = "\r\n".join("\t".join(c.replace("\t", " ") for c in ln) for ln in lines)
        QtWidgets.QApplication.clipboard().setText(text)
        log.info("파일 목록 복사 %s %d개", kind, len(rows))
        self.status.emit(T("파일 목록 {0}개를 복사했습니다").format(len(rows)))
        return text

    def export_menu_items(self):
        sel = len(self.selected_paths()) > 1
        return [(T("이름만 복사"), lambda: self.export_list("names", sel)), (T("전체 경로 복사"), lambda: self.export_list("paths", sel)),
                (T("표로 복사 (엑셀에 붙여넣기)"), lambda: self.export_list("table", sel)), ("-", None),
                (T("CSV 파일로 저장…"), lambda: self.export_list("csv", sel))]

    def toggle_tag(self, paths, tag):
        on = not all(tag in TAGS.tags_of(p) for p in paths)
        TAGS.toggle(paths, tag, on)
        refresh_tags_ui(show_col=on)
        self.status.emit(T("태그 '{0}' {1}: {2}개").format(tag, T("붙임") if on else T("뗌"), len(paths)))

    def new_tag(self, paths):
        name, ok = QtWidgets.QInputDialog.getText(self, T("새 태그"), T("태그 이름 (예: 검수, 최종, 참고)"))
        if ok and name.strip():
            TAGS.new_tag(name.strip())
            TAGS.toggle(paths, name.strip(), True)
            refresh_tags_ui(show_col=True)
            self.status.emit(T("태그 '{0}' {1}: {2}개").format(name.strip(), T("붙임"), len(paths)))

    def clear_tags(self, paths):
        TAGS.clear(paths)
        refresh_tags_ui()

    def add_to_set(self, name, paths):
        if name is None:
            name, ok = QtWidgets.QInputDialog.getText(self, T("새 가상 그룹"), T("가상 그룹 이름 (흩어진 파일을 한곳에 모아 보기 — 진짜 파일은 그대로)"))
            if not ok or not name.strip():
                return
            name = name.strip()
        n = TAGS.add_to_set(name, paths)
        self.status.emit(T("가상 그룹 '{0}' 에 {1}개 넣음 (도구 ▸ 가상 그룹 에서 열기)").format(name, n))

    def file_attrs(self, paths):
        dlg = fileattrs.AttrDialog(paths, lambda n: self.reload("attrs"), self.window())
        dlg.setStyleSheet(self.window().styleSheet())
        dlg.exec()

    def img_batch(self, paths):
        dlg = imgbatch.ImgBatchDialog(paths, None, self.window())
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.setStyleSheet(self.window().styleSheet())
        dlg.show()
        return dlg

    def space_map(self, root):
        m = main_of(self)
        if m is not None:
            return m.space_map(root)

    def _ftp_bg(self, fn, path, msg):
        """FTP 작업(올리기·지우기·새 폴더)을 뒤 스레드에서 → 끝나면 그 폴더를 보는 칸 다시 읽기 + 알림"""
        self.status.emit("⏳ FTP…")
        sg = _undo_signal()

        def run():
            try:
                fn()
                DEV_SIG.done.emit(path, True, "", "")
                sg.done.emit(msg + "  ✕")
            except Exception as ex:
                log.exception("FTP 작업 실패")
                DEV_SIG.done.emit(path, False, f"FTP: {ex}", "")
        threading.Thread(target=run, daemon=True, name="ftp").start()

    def flat_view(self):
        """하위 폴더 펼쳐 보기 (빌드 20): 이 폴더 아래 모든 파일을 한 목록으로 새 탭에 (위치 열 보임, 색인 없이 바로 훑음)"""
        folder = self.path
        if folder == THIS_PC or is_search(folder) or devices.is_dev(folder) or archives.is_arc(folder) or not os.path.isdir(folder):
            self.status.emit(T("⚠ 폴더 안에서만 쓸 수 있습니다 (내 PC·검색 결과 제외)"))
            return
        m = main_of(self)
        pane = next((p for p in m.panes if self in p.views()), None) if m is not None else None
        log.info("하위 폴더 펼쳐 보기 %s", folder)
        if pane is not None:
            pane.add_tab(search_path(FLAT_Q, folder), activate=True)
        else:
            self.openInNewTab.emit(search_path(FLAT_Q, folder))

    def select_pattern(self):
        """패턴으로 고르기 (v0.9.89): 맞는 것만 골라 둠 — 필터와 달리 다른 항목도 그대로 보임"""
        txt, ok = QtWidgets.QInputDialog.getText(
            self, T("패턴으로 고르기"),
            T("고를 이름 (* = 아무 글자, 여러 개는 ; 로)\n예:  *.max      *_stand*; *.psd"),
            text=SETTINGS["select_pattern"] or "*.max")
        if not ok or not txt.strip():
            return
        SETTINGS["select_pattern"] = txt.strip()
        n = self.select_by_pattern(txt)
        self.status.emit(T("'{0}' 에 맞는 것 {1:,}개 고름").format(txt.strip(), n) if n else T("⚠ '{0}' 에 맞는 것이 없습니다").format(txt.strip()))

    def select_by_pattern(self, txt):
        import fnmatch
        pats = [x.strip().lower() for x in txt.split(";") if x.strip()]
        pats = [x if ("*" in x or "?" in x) else f"*{x}*" for x in pats]
        sel = QtCore.QItemSelection()
        first = None
        for r, e in enumerate(self.model_.rows):
            if is_group(e):
                continue
            nm = (e[7] or e[0]).lower()
            if any(fnmatch.fnmatch(nm, x) for x in pats):
                sel.select(self.model_.index(r, 0), self.model_.index(r, 0))
                first = r if first is None else first
        self.sel.select(sel, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
        if first is not None:
            ix = self.model_.index(first, 0)
            self.sel.setCurrentIndex(ix, QtCore.QItemSelectionModel.NoUpdate)
            self.view().scrollTo(ix)
        n = len(self.selected_rows())
        log.info("패턴으로 고르기 '%s' → %d개 (%s)", txt, n, self.path)
        return n

    def show_sha256(self):
        """확인값(SHA256) 보기 (v0.9.89) — 고른 파일들, 뒤에서 계산"""
        ps = [p for p in self.selected_paths() if os.path.isfile(p)]
        if not ps:
            self.status.emit(T("⚠ 확인값을 볼 파일을 고르세요"))
            return
        dlg = hashview.HashDialog(ps, main_of(self) or self)
        dlg.show()

    def location_of(self, p):
        """파일의 '폴더 위치' (v0.9.94): 바로 가기(.lnk) = 대상이 있는 폴더·대상 이름, 검색 결과 = 그 파일 폴더·이름.
        지금 폴더 안 일반 파일이면 None (이미 그 위치)"""
        if p.lower().endswith(".lnk"):
            tgt = os.path.expandvars(shellops.link_target(p) or "")
            if tgt and os.path.exists(tgt):
                return (tgt, None) if os.path.isdir(tgt) else (os.path.dirname(tgt), os.path.basename(tgt))
            return None
        loc = os.path.dirname(p)
        if self.path and os.path.normcase(loc) == os.path.normcase(self.path):
            return None
        return loc, os.path.basename(p)

    def open_location(self, new_tab=False, files_only=False):
        """고른 파일의 폴더 위치 열기 + 그 파일 고름 (v0.9.94 사용자 의견: Everything '경로 열기')"""
        ps = [p for p in self.selected_paths() if not (files_only and os.path.isdir(p))]
        loc = next((x for x in (self.location_of(p) for p in ps) if x), None)
        if loc is None:
            return False
        log.info("폴더 위치 열기 %s → %s (새 탭 %s)", ps[:1], loc, new_tab)
        if new_tab:
            self.openLocation.emit(loc[0], loc[1] or "")
        else:
            self.navigate(loc[0], select=loc[1])
        return True

    def pick_label(self, paths):
        """색 라벨 직접 고르기 (v0.9.90) — 탭 색과 같은 윈도우 색 고르기 창"""
        start = QtGui.QColor(labels.tab_hex(LABELS.get(paths[0]) if paths else "") or "#3e63dd")
        c = QtWidgets.QColorDialog.getColor(start, self, T("색 라벨"))
        if c.isValid():
            self.set_label(paths, c.name())
        else:
            log.info("색 라벨 직접 고르기 취소")

    def set_label(self, paths, color):
        LABELS.set(paths, color)
        for m in MODELS:   # 같은 폴더를 연 다른 탭·칸도 바로
            if m.rows:
                m.dataChanged.emit(m.index(0, 0), m.index(len(m.rows) - 1, m.columnCount() - 1), [Qt.BackgroundRole])

    def mouse_override(self, view, ev, pos):
        """v0.9.83 마우스 버튼 지정: 이 조합에 기능이 지정돼 있으면 실행하고 True (기본 동작이면 False).
        pos = 목록 안 누른 자리(그 자리 파일을 고르고 실행) / None = 목록 밖(지금 고른 것 그대로)"""
        combo = keymap.mouse_combo(ev.button(), ev.modifiers())
        act = keymap.mouse_action(SETTINGS["mouse"], combo)
        if act == keymap.BUILTIN:
            return False
        if pos is not None:
            idx = view.indexAt(pos)
            if idx.isValid():
                if not self.sel.isSelected(self.model_.index(idx.row(), 0)):   # 누른 파일을 고름 (탐색기 우클릭과 같게)
                    self.sel.select(self.model_.index(idx.row(), 0), QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
                self.sel.setCurrentIndex(self.model_.index(idx.row(), 0), QtCore.QItemSelectionModel.NoUpdate)   # view.setCurrentIndex 는 고른 것을 그 하나로 바꿈(실측)
            else:
                self.sel.clearSelection()   # 빈 곳 = 지금 폴더에 (새 폴더·붙여넣기 등)
        log.info("마우스 %s → %s (자리 %s, 고른 것 %d)", combo, act, None if pos is None else (pos.x(), pos.y()), len(self.selected_paths()))
        view._eat_release = ev.button()   # 뒤따라오는 뗌도 버림 (Qt 가 뗄 때 그 자리 하나만 다시 고름 — 실측)
        if ev.button() == Qt.RightButton:
            view._eat_ctx = True   # 뒤따라오는 우클릭 메뉴 신호는 버림
        if act == keymap.MENU:
            gp = view.viewport().mapToGlobal(pos if pos is not None else QtCore.QPoint(10, 10))
            cev = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, view.viewport().mapFromGlobal(gp), gp)
            QtCore.QTimer.singleShot(0, lambda: self.context_menu(view, cev))
        elif act != keymap.NONE:
            def run():
                if keymap.SCOPE.get(act) == "window":
                    m = main_of(self)
                    fn = m.win_actions.get(act) if m is not None else None
                    if fn:
                        fn()
                elif not self.run_action(act):
                    log.warning("마우스 기능 실행 못 함 %s", act)
            QtCore.QTimer.singleShot(0, run)   # 누름 처리 안에서 대화상자(삭제 확인 등)를 띄우지 않게
        return True

    def handle_mouse(self, view, ev):
        # 마우스 뒤로/앞으로는 Main.eventFilter 가 창 전체에서 처리
        if self.mouse_override(view, ev, ev.position().toPoint()):
            return True
        if ev.button() == Qt.MiddleButton:
            idx = view.indexAt(ev.position().toPoint())
            if idx.isValid() and self.model_.rows[idx.row()][1]:
                self.openInNewTab.emit(self.model_.full(self.model_.rows[idx.row()]))
            return True
        return False

    # ---------------------------------------------------------- 우클릭
    def _dev_menu(self, gp, paths):
        """휴대폰 안 우클릭 메뉴 (빌드 4) — 윈도우 메뉴는 셸 경로가 없어 못 띄움"""
        m = QtWidgets.QMenu(self)
        here = self.path
        if paths:
            if len(paths) == 1:
                m.addAction(mlabel(T("열기"), "open"), self.open_selected)
            if devices.is_dev(here):
                m.addAction(mlabel(T("잘라내기"), "cut"), lambda: self.do_copy(cut=True))
            m.addAction(mlabel(T("복사"), "copy"), self.do_copy)
            m.addSeparator()
            m.addAction(mlabel(T("다른 칸으로 복사"), "send_copy"), lambda: self.send_to_other(False))
            if devices.is_dev(here):
                m.addAction(mlabel(T("다른 칸으로 이동"), "send_move"), lambda: self.send_to_other(True))
                m.addSeparator()
                m.addAction(mlabel(T("이름 바꾸기"), "rename"), self.do_rename)
                m.addAction(mlabel(T("삭제"), "delete"), self.do_delete)
        else:
            m.addAction(mlabel(T("붙여넣기"), "paste"), self.do_paste)
            m.addAction(mlabel(T("새 폴더"), "new_folder"), self.do_new_folder)
            m.addSeparator()
            m.addAction(mlabel(T("새로 고침"), "refresh"), lambda: self.reload("menu"))
        m.exec(gp)

    def _arc_menu(self, gp, paths):
        """압축 파일 안 우클릭 (빌드 20) — 읽기 전용: 열기·복사·다른 칸으로 꺼내기"""
        m = QtWidgets.QMenu(self)
        if paths:
            if len(paths) == 1:
                m.addAction(mlabel(T("열기"), "open"), self.open_selected)
            m.addAction(mlabel(T("복사"), "copy"), self.do_copy)
            m.addSeparator()
            m.addAction(mlabel(T("다른 칸으로 꺼내기 (복사)"), "send_copy"), lambda: self.send_to_other(False))
            if archives.is_ftp(self.path):   # 0.9.109 FTP 는 고치기도 됨
                m.addSeparator()
                m.addAction(mlabel(T("이름 바꾸기"), "rename"), self.do_rename)
                m.addAction(mlabel(T("삭제 (서버에서)"), "delete"), self.do_delete)
        elif archives.is_ftp(self.path):
            m.addAction(mlabel(T("붙여넣기 (올리기)"), "paste"), self.do_paste)
            m.addAction(mlabel(T("새 폴더"), "new_folder"), self.do_new_folder)
            m.addSeparator()
            m.addAction(mlabel(T("새로 고침"), "refresh"), lambda: self.reload("menu"))
            m.addAction(T("FTP 연결 끊기"), lambda: (ftpfs.close_all(), self.navigate(THIS_PC)))
        else:
            arc = archives.split(self.path)[0]
            m.addAction(T("압축 파일 전체를 다른 칸으로 풀기"), lambda: self._arc_extract_all(arc))
            m.addSeparator()
            m.addAction(mlabel(T("새로 고침"), "refresh"), lambda: self.reload("menu"))
        m.exec(gp)

    def _arc_extract_all(self, arc):
        main = main_of(self)
        tp = main.other_pane(self.pane()) if main is not None else None
        tv = tp.view() if tp else None
        if tv is None or tv.path == THIS_PC or is_search(tv.path) or archives.is_arc(tv.path):
            self.status.emit(T("⚠ 보낼 칸이 없습니다 (다른 칸에서 폴더를 열어 두세요)"))
            return
        top = [e[5] for e in archives.list_dir(archives.make(arc))]
        log.info("압축 전체 풀기 %s → %s", arc, tv.path)
        self.file_op(top, tv.path, False, select_in=tv)

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
        if devices.is_dev(self.path) or any(devices.is_dev(p) for p in paths):   # 휴대폰: 윈도우 우클릭 메뉴 대신 4Dir 메뉴
            self._dev_menu(gp, paths)
            return
        if archives.is_arc(self.path):   # 빌드 20 압축 안: 읽기 전용 4Dir 메뉴
            self._arc_menu(gp, paths)
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
        # 0.9.109 빌드 5 (사용자 11/6 '오른쪽 메뉴 정리'): 자주 쓰는 것만 위에, 나머지 4Dir 기능은 '4Dir 도구 ▸' 하나로
        #   순서: 대상 위치 · 새 탭 · 다른 칸으로 복사/이동 · 압축/WebP · 색 라벨/태그/가상 그룹 · 4Dir 도구 ▸ · 윈도우 고정·경로 복사 · 터미널 · ★즐겨찾기
        if paths:
            dirs = [p for p in paths if os.path.isdir(p)]
            if dirs:
                extras.append((mlabel(T("새 탭에서 열기"), "open_new_tab"), lambda: [self.openInNewTab.emit(p) for p in dirs]))
            main = main_of(self)
            if self.path != THIS_PC and main is not None:
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
            if len(paths) == 1 and paths[0].lower().endswith(".lnk") and self.location_of(paths[0]):   # v0.9.94
                extras.insert(0, (mlabel(T("대상 위치 열기"), None), lambda: self.open_location(new_tab=False)))
            if self.path != THIS_PC:   # 색 라벨 (v0.9.89) — 4Dir 안에만 저장
                cur = {LABELS.get(p) for p in paths}
                own = next(iter(cur)) if len(cur) == 1 and next(iter(cur)) and next(iter(cur)) not in labels.TAB_HEX else ""
                extras.append((T("색 라벨"), [({"t": lbl, "chk": cur == {k}}, (lambda k=k: self.set_label(paths, k))) for k, lbl, _s in labels.TAB_COLORS]
                               + [("-", None), ({"t": T("다른 색 고르기…"), "chk": bool(own)}, lambda: self.pick_label(paths)),
                                  (T("색 라벨 지우기"), lambda: self.set_label(paths, None))]))
                rcur = {RATINGS.get(p) for p in paths}   # 0.9.116 별점
                extras.append((ti(T("별점"), "star"), [({"t": labels.Ratings.text(k) + mlabel("", f"rate_{k}"), "chk": rcur == {k}}, (lambda k=k: self.set_rating(paths, k))) for k in range(5, 0, -1)]
                               + [("-", None), (T("별점 빼기"), lambda: self.set_rating(paths, 0))]))
                tg_items = [({"t": t, "chk": all(t in TAGS.tags_of(p) for p in paths)}, (lambda t=t: self.toggle_tag(paths, t))) for t in TAGS.all_tags()]
                extras.append((ti(T("태그"), "tag"), tg_items + ([("-", None)] if tg_items else []) + [(T("새 태그…"), lambda: self.new_tag(paths))]
                               + ([(T("태그 모두 떼기"), lambda: self.clear_tags(paths))] if any(TAGS.tags_of(p) for p in paths) else [])))
                st_items = [(n, (lambda n=n: self.add_to_set(n, paths))) for n in TAGS.all_sets()]
                extras.append((ti(T("가상 그룹에 넣기"), "group"), st_items + ([("-", None)] if st_items else []) + [(T("새 가상 그룹…"), lambda: self.add_to_set(None, paths))]))
                tools = []   # 4Dir 도구 ▸
                if main is not None:
                    tools.append((ti(mlabel(T("이름 일괄 변경…"), "rename" if len(paths) > 1 else None), "rename"), lambda: main.open_batch_rename(self.selected_paths())))
                tools.append((ti(mlabel(T("날짜·속성 바꾸기…"), "file_attrs"), "attrs"), lambda: self.file_attrs(paths)))
                if any(imgbatch.is_image(p) for p in paths):
                    tools.append((ti(mlabel(T("그림 크기·형식 바꾸기…"), "img_batch"), "imgbatch"), lambda: self.img_batch(paths)))
                if any(os.path.isfile(p) for p in paths):
                    tools.append((ti(mlabel(T("확인값(SHA256) 보기"), "sha256"), "sha"), self.show_sha256))
                if len(paths) == 1 and os.path.isfile(paths[0]):
                    tools.append((ti(mlabel(T("글자·16진수로 보기"), "view_file"), "hexview"), self.view_file))
                if dirs:
                    tools.append((ti(mlabel(T("디스크 사용량 트리맵"), "space_map"), "treemap"), lambda: self.space_map(dirs[0])))
                if len(paths) == 1 and mediaedit.can_edit(paths[0]):   # 0.9.111
                    tools.append((ti(T("동영상·GIF 편집…"), "mediaedit"), lambda p=paths[0]: open_media_edit(p, 0, self.window())))
                if main is not None:   # 0.9.112 빌드 3: 파일·폴더 우클릭에도 (사용자: 메뉴가 없다)
                    tools.append((ti(mlabel(T("다른 칸 새 탭에 같은 폴더"), "same_folder"), "compare"), main.same_folder_other))
                tools += self.more_tools(paths, dirs)   # 0.9.116 새 도구들
                extras.append((T("4Dir 도구"), tools))
            if dirs:
                extras.append(({"t": T("윈도우 즐겨찾기에 고정"), "unless": {"pintohome"}}, lambda: self.do_verb(dirs, "pintohome")))
                extras.append(({"t": T("시작 화면에 고정"), "unless": {"pintostartscreen"}}, lambda: self.do_verb(dirs, "pintostartscreen")))
            extras.append(({"t": T("경로로 복사"), "unless": {"copyaspath"}}, lambda: shellops.copy_as_path(paths)))
            extras.append((T("경로 복사 형식"), [(f"{nm}   {txt.splitlines()[0][:60]}", (lambda txt=txt: copy_text(txt)))
                                                for nm, txt in fileutil.path_formats(paths)]))   # 0.9.116 #18
            if len(paths) == 1 and archives.is_archive_file(paths[0]) and os.path.isfile(paths[0]):   # 빌드 20
                extras.append((T("🗜 압축 파일 안 보기 (4Dir)"), lambda p=paths[0]: self.navigate(archives.make(p))))
            if len(paths) == 1 and dirs:
                extras.append((T("터미널에서 열기"), lambda: shellops.open_terminal(dirs[0])))
        favs =[((f"{d['group']} ▸ {d['name']}" if d.get("group") else d["name"]), (lambda p=d["path"]: open_fav_entry(p, self.navigate))) for d in FAV.items]
        if not paths and self.path != THIS_PC:
            favs += [("-", None), (mlabel(T("이 폴더를 ★4Dir 즐겨찾기에 추가"), "add_fav"), lambda: FAV.add(self.path))]
        fav_entry = (QE_FAV, favs or [(T("(비어 있음)"), lambda: None)])
        newfolder = None
        if paths:
            # 0.9.109 빌드 6 (사용자 11/6): ★ 즐겨찾기 둘은 맨 위로 모으고, 나머지는 많이 쓰는 순
            order = [T("대상 위치 열기"), T("새 탭에서 열기"), T("다른 칸으로 복사"), T("다른 칸으로 이동"), T("경로로 복사"), T("경로 복사 형식"),
                     T("압축"), T("WebP 변환"), T("터미널에서 열기"), T("🗜 압축 파일 안 보기 (4Dir)"), T("색 라벨"), T("별점"), T("태그"),
                     T("가상 그룹에 넣기"), T("4Dir 도구"), T("윈도우 즐겨찾기에 고정"), T("시작 화면에 고정")]

            def rank(e):
                t = e[0]["t"] if isinstance(e[0], dict) else e[0]
                t = t.split("	")[0].replace("&", "")
                return next((i for i, o in enumerate(order) if t.startswith(o.replace("&", ""))), len(order))
            files = [p for p in paths if p not in dirs and os.path.isfile(p)]   # 0.9.114 파일도 즐겨찾기에 (이슈 #8)
            extras = [fav_entry] + ([(QE_FAV_ADD, lambda: [FAV.add(p) for p in dirs] + [FAV.add(p, file=True) for p in files])]
                                    if dirs or files else []) + sorted(extras, key=rank)
        else:
            # 빈 곳: 윈도우 탐색기 빈 곳 메뉴 순서 (10/8 사용자 확정) — 새 폴더 · 보기 · 정렬 기준 · 새로 고침 · ★4Dir 즐겨찾기
            # ─ 붙여넣기(복사한 것 없으면 흐림) ─ 윈도우 항목들(윈도우 '새 폴더' 자리에 되돌리기) … 속성
            v = self
            if pane and not pane.tabrow.isVisibleTo(pane):   # v0.9.78: 탭 줄을 숨겨 + 버튼이 없을 때만 (마우스로도 새 탭)
                extras.append((mlabel(T("새 탭"), "new_tab"), lambda: pane.add_tab(self.path, focus=True)))
            extras.append((mlabel(T("새 폴더"), "new_folder", "N"), self.do_new_folder))
            if pane:
                extras.append((mlabel(T("보기"), None, "V"), [({"t": lbl, "chk": pane.mode == k}, (lambda k=k: pane.set_mode(k))) for k, lbl, _ in VIEW_MODES]))
            srt = [({"t": lbl, "chk": c == v.model_.sort_col}, (lambda c=c: v.set_sort(c, v.model_.sort_order))) for c, lbl in SORT_COLS]
            srt += [("-", None)] + [({"t": lbl, "chk": o == v.model_.sort_order}, (lambda o=o: v.set_sort(v.model_.sort_col, o)))
                                    for o, lbl in ((Qt.AscendingOrder, T("오름차순")), (Qt.DescendingOrder, T("내림차순")))]
            extras.append((mlabel(T("정렬 기준"), None, "O"), srt))
            extras.append((mlabel(T("새로 고침"), "refresh", "E"), lambda: self.reload("menu")))
            tools = [(ti(mlabel(T("패턴으로 고르기…"), "select_pattern"), "pattern"), self.select_pattern),   # 0.9.109 빌드 5: 빈 곳도 '4Dir 도구 ▸' 하나로
                     (ti(mlabel(T("하위 폴더 펼쳐 보기"), "flat_view"), "flat"), self.flat_view)]
            if main_of(self) is not None:
                tools.append((ti(mlabel(T("두 칸 비교"), "compare"), "compare"), main_of(self).compare_panes))
                tools.append((ti(mlabel(T("다른 칸 새 탭에 같은 폴더"), "same_folder"), "compare"), main_of(self).same_folder_other))   # 0.9.112
                tools.append((ti(mlabel(T("중복 파일 찾기…"), "find_dupes"), "dupes"), lambda: main_of(self).find_dupes(self)))
            tools.append((ti(mlabel(T("디스크 사용량 트리맵"), "space_map"), "treemap"), lambda: self.space_map(self.path)))
            tools += self.more_tools_here()   # 0.9.116 새 도구들 (지금 폴더 대상)
            extras.append((T("4Dir 도구"), tools))
            extras.append((T("터미널에서 열기"), lambda: shellops.open_terminal(self.path)))   # 윈도우 11 빈 곳 메뉴처럼 (v0.9.54)
            extras.append((ti(T("파일 목록 내보내기"), "export"), self.export_menu_items()))   # 0.9.116 #23
            extras.append(fav_entry)
            extras.append(("-", None))
            extras.append(({"t": mlabel(T("붙여넣기"), "paste", "P"), "off": not shellops.get_clipboard()[0] and not QtWidgets.QApplication.clipboard().mimeData().hasImage()}, self.do_paste))
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
        q = parse_search(self.path)[0]
        if q.startswith(tags.SET_Q):   # 0.9.109 묶음 보기: 진짜 파일은 그대로, 목록에서만 뺌
            extras.insert(0, (T("가상 그룹에서 빼기"), lambda: (TAGS.remove_from_set(q[len(tags.SET_Q):], paths), self.reload("set"))))
        elif q.startswith(tags.TAG_Q):
            extras.insert(0, (T("이 태그 떼기"), lambda: (TAGS.toggle(paths, q[len(tags.TAG_Q):], False), refresh_tags_ui(), self.reload("tag"))))
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
        if ev.mimeData().hasFormat(DEV_MIME):   # 휴대폰 항목을 끌어 옴
            srcs = bytes(ev.mimeData().data(DEV_MIME)).decode("utf-8").split("\n")
        elif DEV_DRAG["paths"]:   # 빌드 6: 4Dir 에서 시작한 휴대폰 셸 끌기를 4Dir 칸에 놓음
            srcs = list(DEV_DRAG["paths"])
        if srcs and (devices.is_dev(tgt) or any(devices.is_dev(s) for s in srcs)):
            move = self.drop_action(view, ev) == Qt.MoveAction
            srcs = [s for s in srcs if s and s != tgt]
            log.info("드롭(휴대폰) %s n=%d -> %s", "이동" if move else "복사", len(srcs), tab_title(tgt))
            if srcs and tgt != THIS_PC:
                self.file_op(srcs, tgt, move)
            ev.setDropAction(Qt.CopyAction)
            ev.accept()
            return
        if not srcs and vfiles.has_virtual(ev.mimeData()):   # v0.9.75: 아웃룩 첨부 등 가상 파일 → 내용을 받아 저장
            try:
                saved, why = vfiles.save(ev.mimeData(), tgt)
            except Exception as ex:
                log.exception("가상 파일 저장 실패 → %s", tgt)
                saved, why = [], str(ex)
            if why == "multi":
                self.status.emit(T("⚠ 여러 개를 한꺼번에 끌어 놓을 수 없습니다 — 하나씩 끌어 놓아 주세요"))
            elif why == "partial":   # v0.9.78: 여러 개 중 일부만 내용을 못 받음
                self.status.emit(T("⚠ 일부 파일은 내용을 받지 못해 저장하지 않았습니다 (로그에 기록)"))
            elif why == "preview":   # v0.9.81: 웹 아웃룩 첨부를 끌면 원본 대신 미리보기 그림(png)만 옴 → v0.9.82 저장 안 함. 다른 파일과 같이 끌면 상태 줄이 덮이므로 알림 줄로
                msg = T("⚠ 웹 메일 첨부는 원본을 받을 수 없어 저장하지 않았습니다 — 메일에서 다운로드하세요")
                self.status.emit(msg)
                main = main_of(self)
                if main is not None:
                    main.show_notice(msg, sticky=False, ms=12000)
            elif why == "empty":   # v0.9.77: 웹 아웃룩 본문 이미지 등 — 내용이 비어 옴
                self.status.emit(T("⚠ 내용을 받지 못해 저장하지 않았습니다 — 웹 메일 본문 이미지는 우클릭 → 다른 이름으로 저장"))
            elif why:
                self.status.emit(T("⚠ 끌어 놓은 파일을 저장하지 못했습니다 (로그에 기록)"))
            if saved and os.path.normcase(tgt) == os.path.normcase(self.path):
                names = [os.path.basename(p) for p in saved]
                self.keep_sel = (names, self.view().verticalScrollBar().value(), names[0], -1)   # 저장한 파일을 골라 둠
                self.reload("vfile")
            ev.setDropAction(Qt.CopyAction)
            ev.accept()
            return
        move = self.drop_action(view, ev) == Qt.MoveAction
        srcs = [s for s in srcs if os.path.normcase(os.path.normpath(s)) != os.path.normcase(tgt)]
        log.info("드롭 %s n=%d -> %s", "이동" if move else "복사", len(srcs), tgt)
        if not srcs:   # v0.9.79: 받을 파일이 없는 끌기(웹 이미지 등) — 무엇이 왔는지 남김
            md = ev.mimeData()
            log.info("드롭할 파일 없음 — 형식 %s / 주소 %s", md.formats(), [u.toString()[:200] for u in md.urls()[:3]])
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
    menu.setToolTipsVisible(True)
    for start, end, g in FAV.entries():
        target = menu.addMenu(favorg.group_icon(16), g) if g else menu   # 묶음 = 하위 메뉴
        if g:
            target.setToolTipsVisible(True)
        for d in FAV.items[start:end]:
            a = target.addAction(fav_icon(d), d["name"])
            a.setToolTip(d["path"])
            a.triggered.connect(lambda _=False, p=d["path"]: open_fav_entry(p, go))
    return menu


# ---------------------------------------------------------------- 파일 즐겨찾기 (0.9.114, GitHub 이슈 #8)
# 파일·바로가기를 즐겨찾기 바에 끌어 놓으면 등록(경로만 기억) → 누르면 윈도우에서 '열기'한 것처럼 연결 프로그램으로.
# 폴더를 가리키는 바로가기는 폴더 즐겨찾기처럼 칸에서 그 폴더로 (목록에서 두 번 누를 때와 같게)
FAV_OWN_ICON = fileicons.OWN_EXT | {".lnk"}   # 파일마다 아이콘이 다른 종류 → 실제 파일에 물어봄(작업 스레드)


def fav_item(path):
    n = os.path.normcase(os.path.normpath(path))
    return next((d for d in FAV.items if os.path.normcase(d["path"]) == n), None)


def fav_icon(d, size=16):
    if not d.get("file"):
        return shellops.icon_for("", True, size)
    p = d["path"]
    if os.path.splitext(p)[1].lower() in FAV_OWN_ICON:
        idx = ficon_service().get(p, 0)   # 없으면 요청만 → 받으면 즐겨찾기 바가 다시 그림(FavPanel._ficon)
        if idx is not None and idx >= 0:
            return shellops.icon_for(p, False, size, sysidx=idx)
    return shellops.icon_for(os.path.basename(p), False, size)


def _fav_notice(text):
    w = QtWidgets.QApplication.activeWindow()
    while w is not None and not hasattr(w, "show_notice"):
        w = w.parentWidget()
    if w is None:
        w = next((x for x in QtWidgets.QApplication.topLevelWidgets() if hasattr(x, "show_notice") and x.isVisible()), None)
    if w is not None:
        w.show_notice(text)


def open_fav_entry(path, go, notice=None):
    """즐겨찾기 열기: 폴더 → go(path) / 파일 → 연결 프로그램 / 폴더 바로가기 → go(대상)"""
    d = fav_item(path)
    if not (d and d.get("file")):
        go(path)
        return
    notice = notice or _fav_notice
    if path.lower().endswith(".lnk"):
        tgt = os.path.expandvars(shellops.link_target(path) or "")
        if tgt and os.path.isdir(tgt):
            log.info("즐겨찾기 폴더 바로가기 %s → %s", path, tgt)
            go(tgt)
            return
    if not os.path.exists(path):
        log.warning("즐겨찾기 파일 없음 %s", path)
        notice(T("⚠ 즐겨찾기 파일을 찾을 수 없습니다 (옮겨졌거나 지워짐): {0}  ✕").format(path))
        return
    log.info("즐겨찾기 파일 열기 %s", path)
    try:
        os.startfile(path)
    except OSError as ex:
        log.warning("즐겨찾기 파일 열기 실패 %s : %s", path, ex)
        notice(f"⚠ {ex}  ✕")


favorg.ITEM_ICON = fav_icon   # 즐겨찾기 정리 창도 같은 아이콘
session.PRIVATE = lambda: bool(SETTINGS["private_mode"])   # 0.9.115 기록 안 남기기
frecent.PRIVATE = session.PRIVATE   # 0.9.116 자주 간 폴더·폴더 보기 기억도


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
        if devices.is_dev(self.path):   # 휴대폰: 하위 폴더 (이름, 셸 경로)
            try:
                out = [(e[0], e[5]) for e in devices.list_dir(self.path) if e[1]]
            except OSError:
                log.warning("탐색 창 휴대폰 폴더 못 읽음")
            out.sort(key=lambda x: shellops.natural_key(x[0]))
            self.sig.subdirs.emit(self.item, out)
            return
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


FAV_FILE_ROLE = Qt.UserRole + 41   # 탐색 창 4Dir 즐겨찾기 중 파일 항목 (0.9.122)


def set_side_favs(mode):
    """설정 → 열린 모든 탐색 창에 바로 적용"""
    SETTINGS["side_favs"] = mode
    n = 0
    for w in QtWidgets.QApplication.allWidgets():
        if isinstance(w, Sidebar):
            w.apply_side_favs()
            n += 1
    log.info("탐색 창 즐겨찾기 = %s (탐색 창 %d개)", mode, n)


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
        self.qe_root = QtWidgets.QTreeWidgetItem([T("즐겨찾기 (4Dir)")])   # 0.9.122 받은 의견: 4Dir 즐겨찾기도 탐색 창에 (설정 side_favs)
        self.fav_root = QtWidgets.QTreeWidgetItem([T("즐겨찾기 (Windows)")])   # 윈도우 탐색기 고정 폴더
        self.pc_root = QtWidgets.QTreeWidgetItem([T(THIS_PC)])
        for r in (self.qe_root, self.fav_root, self.pc_root):
            r.setFont(0, bold)
            r.setFlags(Qt.ItemIsEnabled)
            self.addTopLevelItem(r)
        self.pc_root.setData(0, PATH_ROLE, THIS_PC)
        self.pc_root.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.itemExpanded.connect(self._on_expand)
        self.itemClicked.connect(self._on_click)
        self.fav_root.setToolTip(0, T("윈도우 탐색기에 고정한 폴더 (고정·해제는 윈도우 탐색기에서) · 접었다 펼치면 다시 읽음"))
        self.qe_root.setToolTip(0, T("4Dir 즐겨찾기 (위 즐겨찾기 바와 같은 목록) · 우클릭 > ★ 4Dir 즐겨찾기에 추가 · Ctrl+D"))
        self.refresh_pinned()
        self.refresh_qe_favs()
        FAV.listeners.append(self.refresh_qe_favs)
        self.apply_side_favs()
        self.qe_root.setExpanded(True)
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
        it.setToolTip(0, label if devices.is_dev(path) else path)   # 휴대폰은 셸 ID 대신 이름
        it.setIcon(0, icon)
        it.addChild(QtWidgets.QTreeWidgetItem([DUMMY]))  # 펼칠 수 있게 (펼칠 때 읽음)
        return it

    def apply_side_favs(self):
        """설정 side_favs: both / 4dir / windows → 보일 즐겨찾기 묶음"""
        mode = SETTINGS["side_favs"] if SETTINGS["side_favs"] in ("both", "4dir", "windows") else "both"
        self.qe_root.setHidden(mode == "windows")
        self.fav_root.setHidden(mode == "4dir")

    def refresh_qe_favs(self):
        """4Dir 즐겨찾기 → 탐색 창 (낱개 = 폴더처럼 펼침, 묶음 = 묶음 아래에, 파일 = 누르면 연결 프로그램)"""
        try:
            root = self.qe_root
            was = {(root.child(i).text(0), root.child(i).isExpanded()) for i in range(root.childCount())}
            root.takeChildren()
        except RuntimeError:   # 탐색 창이 닫혀 지워짐 → 목록에서 빠짐
            if self.refresh_qe_favs in FAV.listeners:
                FAV.listeners.remove(self.refresh_qe_favs)
            return
        opened = {t for t, e in was if e}

        def entry(d):
            if d.get("file"):
                it = QtWidgets.QTreeWidgetItem([d["name"]])
                it.setData(0, PATH_ROLE, d["path"])
                it.setData(0, FAV_FILE_ROLE, True)
                it.setToolTip(0, d["path"])
                it.setIcon(0, fav_icon(d))
                return it
            return self._folder_item(d["name"], d["path"], fav_icon(d))
        for start, end, group in FAV.entries():
            if group:
                g = QtWidgets.QTreeWidgetItem([group])
                g.setIcon(0, favorg.group_icon(16))
                g.setFlags(Qt.ItemIsEnabled)
                for d in FAV.items[start:end]:
                    g.addChild(entry(d))
                root.addChild(g)
                if group in opened:
                    g.setExpanded(True)
            else:
                root.addChild(entry(FAV.items[start]))
        if not FAV.items:
            root.addChild(QtWidgets.QTreeWidgetItem([T("(비어 있음 — 우클릭 > ★ 4Dir 즐겨찾기에 추가)")]))
        log.debug("탐색 창 4Dir 즐겨찾기 %d개", len(FAV.items))

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

    def refresh_pc(self):
        POOL.start(PcInfoJob(self.sig))

    def _fill_pc(self, rows):
        # 다시 읽을 때(드라이브 꽂기/빼기, v0.9.95)는 그대로인 항목을 남겨 펼쳐 둔 것이 접히지 않게
        old = {self.pc_root.child(i).data(0, PATH_ROLE): self.pc_root.child(i) for i in range(self.pc_root.childCount())}
        exp = [p for p, it in old.items() if it.isExpanded()]
        self.pc_root.takeChildren()
        for label, path, idx in rows:
            it = old.get(path)
            self.pc_root.addChild(it if it is not None else self._folder_item(label, path, shellops.icon_for("", True, 16, idx)))
            if it is not None and it.text(0) != label:
                it.setText(0, label)
            if it is not None and idx is not None:
                it.setIcon(0, shellops.icon_for("", True, 16, idx))
        late = [path for label, path, idx in rows if idx is None]
        self._pc_retry = getattr(self, "_pc_retry", 0)
        if late and self._pc_retry < 4:   # v0.9.96 막 꽂은 드라이브 정보 늦음 → 다시
            self._pc_retry += 1
            QtCore.QTimer.singleShot(5000 * self._pc_retry, self.refresh_pc)
        elif not late:
            self._pc_retry = 0
        for p in exp:
            if p in old and old[p].treeWidget() is self:
                old[p].setExpanded(True)
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
        if devices.is_dev(path) or archives.is_arc(path):   # 휴대폰·압축 안은 트리 자동 펼치기 안 함
            self._reveal_path = None
            return
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

    def reset_devices(self):
        """휴대폰 항목 아래를 다시 읽게 (빌드 6) — 펼쳐 두었으면 바로 다시 읽음"""
        for i in range(self.pc_root.childCount()):
            it = self.pc_root.child(i)
            if devices.is_dev(it.data(0, PATH_ROLE) or ""):
                was = it.isExpanded()
                it.takeChildren()
                it.addChild(QtWidgets.QTreeWidgetItem([DUMMY]))
                if was:
                    it.setExpanded(False)
                    it.setExpanded(True)

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
            n, cp = n if isinstance(n, tuple) else (n, os.path.join(p, n))   # 휴대폰은 (이름, 셸 경로)
            c = self._folder_item(n, cp, icon)
            it.addChild(c)
            if not devices.is_dev(cp) and self._nc(cp) in was_open:
                reopen.append(c)
        for c in reopen:
            c.setExpanded(True)   # 펼치면 그 안을 다시 읽음
        if getattr(self, "_reveal_wait", None) is it and self._reveal_path:
            self._reveal_wait = None
            self._reveal_step(it)

    def _on_click(self, it, col):
        p = it.data(0, PATH_ROLE)
        if p and it.data(0, FAV_FILE_ROLE):   # 4Dir 즐겨찾기 파일 → 연결 프로그램 (즐겨찾기 바와 같게)
            open_fav_entry(p, self.go.emit)
            return
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
        if devices.is_dev(p):   # 휴대폰: 기기 › 내장 저장공간 › …
            return [(T(THIS_PC), THIS_PC)] + devices.chain(p)
        if archives.is_ftp(p):   # 0.9.109 FTP: 내 PC › 🌐 서버 › 폴더
            return [(T(THIS_PC), THIS_PC)] + archives.chain(p)
        if archives.is_arc(p):   # 압축 안: 압축 파일이 있는 폴더까지 + 압축 › 안쪽
            return Crumbs.segments(os.path.dirname(archives.split(p)[0])) + archives.chain(p)
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


def flash_pane(pane, color="#f76b15", times=3, ms=170):
    """칸 테두리 잠깐 깜빡임 (v0.9.90 두 칸 비교). 마우스는 통과, 끝나면 스스로 지움"""
    f = QtWidgets.QFrame(pane)
    f.setObjectName("flash")
    f.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    f.setStyleSheet("QFrame#flash{border:3px solid %s; background:transparent;}" % color)
    f.setGeometry(pane.rect())
    f.show()
    f.raise_()
    left = [times * 2 - 1]
    t = QtCore.QTimer(f)

    def step():
        left[0] -= 1
        if left[0] < 0:
            t.stop()
            f.deleteLater()
            return
        f.setVisible(not f.isVisible())
    t.timeout.connect(step)
    t.start(ms)
    pane._flash = f   # 시험용
    return f


def gif_icon(kind, fg="#333333", sz=20):
    """GIF 조작 단추 아이콘 (빌드 18, 사용자 참고 그림): prev |◀ · play ▶ · pause ⏸ · stop ■ · next ▶| · save 💾 — 직접 그림"""
    dpr = 2
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(dpr * sz / 20.0, dpr * sz / 20.0)
    c = QtGui.QColor(fg)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    P = QtCore.QPointF
    tri = lambda pts: p.drawPolygon(QtGui.QPolygonF([P(x, y) for x, y in pts]))
    if kind == "prev":
        p.drawRect(QtCore.QRectF(4, 4.5, 2.2, 11))
        tri([(15.5, 4.5), (15.5, 15.5), (7.2, 10)])
    elif kind == "next":
        p.drawRect(QtCore.QRectF(13.8, 4.5, 2.2, 11))
        tri([(4.5, 4.5), (4.5, 15.5), (12.8, 10)])
    elif kind == "play":
        tri([(6, 4), (6, 16), (16, 10)])
    elif kind == "pause":
        p.drawRect(QtCore.QRectF(5.5, 4.5, 3, 11))
        p.drawRect(QtCore.QRectF(11.5, 4.5, 3, 11))
    elif kind == "stop":
        p.drawRoundedRect(QtCore.QRectF(5, 5, 10, 10), 1.2, 1.2)
    elif kind == "autoplay":   # 빌드 28 자동 재생 — 돌아가는 화살표 안에 재생 세모
        p.setBrush(Qt.NoBrush)
        p.setPen(QtGui.QPen(c, 1.6, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QtCore.QRectF(2.5, 2.5, 15, 15), 60 * 16, 290 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        tri([(13.2, 1.2), (17.8, 3.2), (13.8, 6.4)])   # 화살촉
        tri([(8, 6.5), (8, 13.5), (13.5, 10)])
    elif kind in ("sound", "mute"):   # 빌드 24 소리 켜짐/꺼짐 — 스피커 + 물결 / 스피커 + X
        p.drawPolygon(QtGui.QPolygonF([P(3, 7.5), P(6.5, 7.5), P(10.5, 4), P(10.5, 16), P(6.5, 12.5), P(3, 12.5)]))
        p.setBrush(Qt.NoBrush)
        p.setPen(QtGui.QPen(c, 1.6, Qt.SolidLine, Qt.RoundCap))
        if kind == "sound":
            p.drawArc(QtCore.QRectF(9.5, 6.5, 5, 7), -60 * 16, 120 * 16)
            p.drawArc(QtCore.QRectF(9.5, 4, 8.5, 12), -60 * 16, 120 * 16)
        else:
            p.drawLine(P(13, 7.5), P(17.5, 12.5))
            p.drawLine(P(17.5, 7.5), P(13, 12.5))
    elif kind == "edit":   # 0.9.111 가위 (편집)
        p.setBrush(Qt.NoBrush)
        p.setPen(QtGui.QPen(c, 1.6))
        p.drawEllipse(QtCore.QRectF(3, 12, 5, 5))
        p.drawEllipse(QtCore.QRectF(12, 12, 5, 5))
        p.drawLine(QtCore.QPointF(7, 12.5), QtCore.QPointF(15.5, 3))
        p.drawLine(QtCore.QPointF(13, 12.5), QtCore.QPointF(4.5, 3))
    elif kind == "save":
        body = QtGui.QPainterPath()   # 디스켓: 오른쪽 위 모서리를 깎은 몸통 + 위 셔터 + 아래 이름표
        body.moveTo(3.5, 3.5); body.lineTo(13.5, 3.5); body.lineTo(16.5, 6.5); body.lineTo(16.5, 16.5); body.lineTo(3.5, 16.5); body.closeSubpath()
        p.drawPath(body)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)   # 셔터·이름표는 구멍으로 (밝게·어둡게 둘 다 보이게)
        p.drawRect(QtCore.QRectF(6.5, 4.5, 5.5, 3.5))
        p.drawRect(QtCore.QRectF(6, 11, 8, 4.5))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QtGui.QIcon(pm)


def color_dot(hexcol, d=12):
    """메뉴용 색 동그라미 (탭 색)"""
    pm = QtGui.QPixmap(d, d)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor(hexcol))
    p.drawEllipse(1, 1, d - 2, d - 2)
    p.end()
    return QtGui.QIcon(pm)


def arrow_icon(way):
    return QtGui.QIcon(ArrowIcon(way))


# ================================================================ 칸 하나 = 머리줄 + (사이드바 | 탭들) + 상태줄
class PaneTabBar(QtWidgets.QTabBar):
    """칸의 탭줄. 닫기 단추(×)를 탭 안쪽으로 4px (v0.9.56, 사용자: '× 가 탭 밖으로 나갔다').
    윈도우 스타일은 단추를 탭 칸 오른쪽 끝 1px 안에 두는데, 우리 탭은 칸 사이 간격(margin-right 2px)이 있어 실제
    테두리가 2px 안쪽 → 단추가 테두리 위에 걸쳐 밖으로 보였음(측정: 칸 0~79, 단추 63~78, 테두리 77).
    스타일시트 QTabBar::close-button 위치 규칙·앱 스타일 대리 모두 이 단추엔 안 먹음(실측) → 배치가 끝날 때마다 옮김"""
    CLOSE_SHIFT = 4
    countChanged = QtCore.Signal()   # 탭 수가 바뀜 (v0.9.75: 탭 하나면 탭줄 숨김 옵션)

    # 0.9.123 여러 줄 탭: 탭 목록·신호·우클릭·끌어 떼기는 QTabBar 그대로, '놓는 자리·그리기·누르기·끌어 순서 바꾸기'만 직접.
    # tabAt·tabRect 를 파이썬에서 덮어써서 Pane 의 + 단추 자리·가운데 클릭·두 번 누르기·우클릭 메뉴가 그대로 새 자리를 씀
    multi = False

    def __init__(self, *a):
        super().__init__(*a)
        # 탭 선택·추가 때 Qt 가 전체 배치 없이 그 탭 단추만 다시 놓음(실측) → 그 직후에도 옮김
        self.currentChanged.connect(self._fix_later)
        self._rects = []
        self._rows = 1
        self._hover = -1
        self._press = None    # (누른 탭 번호, 누른 자리) — 여러 줄에서 끌어 순서 바꾸기

    def set_multi(self, on):
        on = bool(on)
        if on == self.multi:
            return
        self.multi = on
        self.setUsesScrollButtons(not on)
        self.setMouseTracking(on)
        self._relayout()
        log.info("탭 여러 줄 %s", on)

    def _relayout(self):
        """여러 줄: 탭을 왼쪽부터 놓고 넘치면 다음 줄 (탭 순서 그대로)"""
        if not self.multi:
            self._rects = []
            self._rows = 1
            self.updateGeometry()
            self.update()
            return
        W = max(60, self.width())
        x = y = 0
        rh = 0
        rects = []
        for i in range(self.count()):
            sz = super().tabSizeHint(i)
            w = min(sz.width(), W)
            rh = max(rh, sz.height())
            if x and x + w > W:
                x = 0
                y += 1
            rects.append([x, y, w])
            x += w
        rh = rh or 26
        self._rh = rh
        self._rects = [QtCore.QRect(x, y * rh, w, rh) for x, y, w in rects]
        rows = (rects[-1][1] + 1) if rects else 1
        if rows != self._rows:
            self._rows = rows
            self.updateGeometry()
        self._fix_close_buttons()
        self.update()

    def tabRect(self, i):
        if self.multi:
            return QtCore.QRect(self._rects[i]) if 0 <= i < len(self._rects) else QtCore.QRect()
        return super().tabRect(i)

    def tabAt(self, pos):
        if self.multi:
            for i, r in enumerate(self._rects):
                if r.contains(pos):
                    return i
            return -1
        return super().tabAt(pos)

    def sizeHint(self):
        s = super().sizeHint()
        if self.multi:
            return QtCore.QSize(min(s.width(), 200), max(1, self._rows) * getattr(self, "_rh", s.height()))
        return s

    def minimumSizeHint(self):
        s = super().minimumSizeHint()
        if self.multi:
            return QtCore.QSize(60, max(1, self._rows) * getattr(self, "_rh", s.height()))
        return s

    def mousePressEvent(self, ev):
        if not self.multi:
            return super().mousePressEvent(ev)
        i = self.tabAt(ev.position().toPoint())
        if ev.button() == Qt.LeftButton:
            if i >= 0:
                self._press = (i, ev.position().toPoint())
                self.setCurrentIndex(i)
            self.tabBarClicked.emit(i)
        elif i >= 0 and ev.button() != Qt.RightButton:
            self.tabBarClicked.emit(i)

    def mouseMoveEvent(self, ev):
        if not self.multi:
            return super().mouseMoveEvent(ev)
        pt = ev.position().toPoint()
        h = self.tabAt(pt)
        if h != self._hover:
            self._hover = h
            self.update()
        if self._press and ev.buttons() & Qt.LeftButton and self.isMovable():
            i, p0 = self._press
            if (pt - p0).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                j = self.tabAt(pt)
                if j >= 0 and j != i:
                    self.moveTab(i, j)   # tabMoved 신호 · 현재 탭 번호도 Qt 가 맞춤
                    self._press = (j, pt)
                    self._relayout()

    def mouseReleaseEvent(self, ev):
        if not self.multi:
            return super().mouseReleaseEvent(ev)
        self._press = None

    def mouseDoubleClickEvent(self, ev):
        if not self.multi:
            return super().mouseDoubleClickEvent(ev)
        i = self.tabAt(ev.position().toPoint())
        if i >= 0:
            self.tabBarDoubleClicked.emit(i)

    def leaveEvent(self, ev):
        super().leaveEvent(ev)
        if self.multi and self._hover != -1:
            self._hover = -1
            self.update()

    def wheelEvent(self, ev):
        if not self.multi:
            return super().wheelEvent(ev)
        ev.ignore()   # 여러 줄에선 휠로 탭 바꾸지 않음 (줄이 많아 헷갈림)

    def _paint_multi(self):
        p = QtWidgets.QStylePainter(self)
        cur = self.currentIndex()
        for i in list(range(self.count())):
            if i == cur:
                continue
            self._paint_tab(p, i)
        if 0 <= cur < self.count():
            self._paint_tab(p, cur)   # 고른 탭은 마지막에 (테두리가 위로)
        p.end()

    def _paint_tab(self, p, i):
        opt = QtWidgets.QStyleOptionTab()
        self.initStyleOption(opt, i)
        opt.rect = self.tabRect(i)
        opt.state &= ~QtWidgets.QStyle.State_MouseOver
        if i == self._hover:
            opt.state |= QtWidgets.QStyle.State_MouseOver
        # 모양(배경·테두리)만 스타일로, 글자·아이콘은 직접 — 스타일의 글자 그리기는 Qt 안쪽 한 줄 자리를 써서 잘리고 밀렸음(실제 화면 캡처로 확인)
        opt.text = ""
        opt.icon = QtGui.QIcon()
        p.drawControl(QtWidgets.QStyle.CE_TabBarTabShape, opt)
        r = opt.rect.adjusted(9, 0, -6, 0)
        cb = self.tabButton(i, QtWidgets.QTabBar.RightSide)
        if cb is not None:
            r.setRight(opt.rect.right() - self.CLOSE_SHIFT - cb.width() - 3)
        ic = self.tabIcon(i)
        if not ic.isNull():
            isz = self.iconSize()
            ic.paint(p, QtCore.QRect(r.left(), r.top() + (r.height() - isz.height()) // 2, isz.width(), isz.height()))
            r.setLeft(r.left() + isz.width() + 4)
        sel = i == self.currentIndex()
        f = QtGui.QFont(self.font())
        f.setBold(sel)
        p.setFont(f)
        dark = self.palette().color(QtGui.QPalette.Window).lightness() < 128
        fx = ui_parts.FIXED[dark]
        p.setPen(QtGui.QColor(fx["tab_sel_text"] if sel else fx["tab_text"]))
        txt = QtGui.QFontMetrics(f).elidedText(self.tabText(i), self.elideMode() if self.elideMode() != Qt.ElideNone else Qt.ElideRight, max(10, r.width()))
        p.drawText(r, int(Qt.AlignVCenter | Qt.AlignLeft), txt)

    def _fix_later(self, *_):
        QtCore.QTimer.singleShot(0, self._fix_close_buttons)

    def tabLayoutChange(self):
        super().tabLayoutChange()
        if self.multi:
            self._relayout()
        self._fix_close_buttons()

    def tabInserted(self, index):
        super().tabInserted(index)
        self._fix_later()
        self.countChanged.emit()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self._fix_later()
        self.countChanged.emit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.multi:
            self._relayout()
        self._fix_later()

    color_of = staticmethod(lambda i: "")   # Pane 이 바꿔 끼움: 탭 i 의 색 이름 (v0.9.89)

    def paintEvent(self, ev):
        if self.multi:
            self._paint_multi()
        else:
            super().paintEvent(ev)
        cols = [(i, self.color_of(i)) for i in range(self.count())]
        cols = [(i, labels.tab_hex(c)) for i, c in cols if labels.tab_hex(c)]   # v0.9.90 직접 고른 색도
        if not cols:
            return
        p = QtGui.QPainter(self)
        for i, c in cols:
            r = self.tabRect(i).adjusted(1, 0, -3, 0)   # 탭 사이 간격(오른쪽 2px) 빼고
            col = QtGui.QColor(c)
            tint = QtGui.QColor(col)
            tint.setAlpha(70 if i == self.currentIndex() else 45)
            p.fillRect(r, tint)
            p.fillRect(QtCore.QRect(r.left(), r.top(), r.width(), 3), col)   # 위쪽 진한 띠
        p.end()

    def _fix_close_buttons(self):
        for i in range(self.count()):
            b = self.tabButton(i, QtWidgets.QTabBar.RightSide)
            if b is not None:
                r = self.tabRect(i)
                if self.multi:   # 여러 줄: 줄 높이 가운데로, Qt 가 화면 밖이라 숨긴 단추도 보이게
                    b.move(r.right() - self.CLOSE_SHIFT - b.width(), r.top() + (r.height() - b.height()) // 2)
                    if not b.isVisible() and self.isVisible():
                        b.show()
                else:
                    b.move(r.right() - self.CLOSE_SHIFT - b.width(), b.y())


class ChipBar(QtWidgets.QWidget):
    """형식 단추 줄 (빌드 17, galleryV8 참고): [전체 n] [폴더 n] [JPG n] [PSD n]… 많은 순 + 들어가지 않는 것은 '+N ▾'.
    누르면 그 형식만, Ctrl+누르기 = 여러 개. 형식이 2가지 이상일 때만 보임. 폴더를 옮기면 전체로.
    빌드 18 (사용자 11/5): 단추는 절대 안 눌림(글자 '…' 금지) → 폭에 들어가는 만큼만 보이고 나머지는 '+N ▾',
    15% 작게, 형식마다 색(형식 딱지와 같은 thumbs.BADGE_COLORS, 폴더 노랑, 없는 형식은 확장명으로 정해지는 고정 색)"""
    SCALE = 0.85
    FOLDER = "#d9a520"
    OTHER = ["#5c6bc0", "#00897b", "#c0392b", "#7b1fa2", "#0277bd", "#558b2f", "#ad1457", "#6d4c41", "#00838f", "#ef6c00"]

    def __init__(self, pane):
        super().__init__()
        self.pane = pane
        self.setObjectName("chipBar")
        self.lay = QtWidgets.QHBoxLayout(self)
        self.lay.setContentsMargins(4, 2, 4, 2)
        self.lay.setSpacing(3)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)   # 좁으면 단추를 줄이지 않고 '+N ▾' 로 (창 축소를 막지 않게)
        self.sig = None
        self.chips = []      # [(형식 키, 단추, 고름?)] — 키 None = 전체
        self.more = None
        self.counts = {}
        self.v = None
        self.setVisible(False)

    @classmethod
    def color_of(cls, k):
        if k is None:
            return "#2f6fd0"
        if k == "/":
            return cls.FOLDER
        c = thumbs.BADGE_COLORS.get(k)
        return c or cls.OTHER[zlib.crc32((k or "-").encode()) % len(cls.OTHER)]

    def _style(self, b, k, on):
        c = QtGui.QColor(self.color_of(k))
        dark = self.palette().color(QtGui.QPalette.Window).lightness() < 128
        fg = c.lighter(170) if dark else c.darker(115)
        if on:
            css = f"background:{c.name()}; color:white; border:1px solid {c.name()};"
        else:
            css = (f"background:rgba({c.red()},{c.green()},{c.blue()},{40 if dark else 28}); color:{fg.name()};"
                   f" border:1px solid rgba({c.red()},{c.green()},{c.blue()},170);")
        b.setStyleSheet(f"QToolButton{{{css} border-radius:8px; padding:0px 7px; margin:0;}}"
                        f"QToolButton:hover{{background:rgba({c.red()},{c.green()},{c.blue()},80);}}"
                        "QToolButton::menu-indicator{image:none; width:0;}")
        f = b.font()
        f.setPointSizeF(max(6.0, QtWidgets.QApplication.font().pointSizeF() * self.SCALE))
        b.setFont(f)
        b.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

    def _clear(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().hide()   # 0.9.122: 지워지기 전까지 새 단추와 겹쳐 그려지지 않게
                it.widget().deleteLater()
        self.chips, self.more = [], None

    def refresh(self, v, force=False):
        if v is None or not OPTS["type_chips"] or OPTS["chips_global"] or v.path == THIS_PC or devices.is_dev(v.path):
            self.setVisible(False)
            self.sig = None
            return
        m = v.model_
        counts = {}
        for e in m.all:
            k = kind_of(e)
            counts[k] = counts.get(k, 0) + 1
        sel = set(getattr(m, "ext_filter", set()) or ())
        sig = (id(v), v.path, tuple(sorted(counts.items())), tuple(sorted(sel)))
        if sig == self.sig and not force:
            return
        self.sig = sig
        self._clear()
        if len(counts) < 2 and not sel:
            self.setVisible(False)
            return
        self.v, self.counts = v, counts
        order = (["/"] if "/" in counts else []) + sorted((k for k in counts if k != "/"), key=lambda k: (-counts[k], k))
        self._chip(v, T("전체"), None, len(m.all), not sel)
        for k in order:
            self._chip(v, kind_label(k), k, counts[k], k in sel)
        b = QtWidgets.QToolButton()
        b.setObjectName("chipMore")
        b.setToolTip(T("나머지 형식"))
        b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        b.setFocusPolicy(Qt.NoFocus)
        self._style(b, None, False)
        mm = QtWidgets.QMenu(b)
        mm.aboutToShow.connect(lambda mm=mm: self._fill_more(mm))
        b.setMenu(mm)
        self.lay.addWidget(b)
        self.more = b
        self.lay.addStretch(1)
        self.setVisible(True)
        self._fit()

    def _chip(self, v, label, k, n, on):
        b = QtWidgets.QToolButton()
        b.setObjectName("chip")
        b.setText(f"{label} {n:,}" if OPTS["chip_counts"] else label)   # 0.9.122: 개수는 옵션 (기본 안 씀)
        if not OPTS["chip_counts"]:
            b.setToolTip(f"{label}  ({n:,})")
        b.setCheckable(True)
        b.setChecked(on)
        b.setToolTip((b.toolTip() + "\n" if b.toolTip() else "") + (T("전체 보기") if k is None else T("{0} 만 보기 — Ctrl+누르기 = 여러 형식").format(label)))
        b.setFocusPolicy(Qt.NoFocus)
        self._style(b, k, on)
        b.setMinimumSize(b.sizeHint())   # 0.9.122: 아주 좁아도 1px 도 눌리지 않게 (넘치면 잘림, 글자 '…' 없음)
        b.clicked.connect(lambda *_: self._pick(v, k, bool(QtWidgets.QApplication.keyboardModifiers() & Qt.ControlModifier)))
        self.lay.addWidget(b)
        self.chips.append((k, b, on))
        return b

    def _fit(self):
        """폭에 들어가는 단추만 보임 ('전체'·고른 단추는 항상), 나머지 수는 '+N ▾' (빌드 18)"""
        if not self.chips or self.more is None:
            return
        sp = self.lay.spacing()
        m = self.lay.contentsMargins()
        avail = self.width() - m.left() - m.right()
        must = [i for i, (k, b, on) in enumerate(self.chips) if k is None or on]
        used = sum(self.chips[i][1].sizeHint().width() + sp for i in must)
        show = set(must)
        rest = [i for i in range(len(self.chips)) if i not in show]
        for n_hidden_after, i in enumerate(rest):
            w = self.chips[i][1].sizeHint().width() + sp
            left = len(rest) - n_hidden_after - 1
            self.more.setText(f"+{left} ▾")
            mw = self.more.sizeHint().width() + sp if left else 0
            if used + w + mw > avail:
                break
            used += w
            show.add(i)
        hidden = [i for i in range(len(self.chips)) if i not in show]
        for i, (k, b, on) in enumerate(self.chips):
            b.setVisible(i in show)
        self.more.setText(f"+{len(hidden)} ▾")
        self.more.setVisible(bool(hidden))
        self._hidden = [self.chips[i][0] for i in hidden]

    def _fill_more(self, mm):
        mm.clear()
        sel = set(getattr(self.v.model_, "ext_filter", set()) or ()) if self.v else set()
        for k in getattr(self, "_hidden", []):
            a = mm.addAction(color_dot(self.color_of(k)), f"{kind_label(k)}  ({self.counts.get(k, 0):,})",
                             lambda k=k: self._pick(self.v, k, False))
            a.setCheckable(True)
            a.setChecked(k in sel)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()

    def _pick(self, v, k, add):
        cur = set(getattr(v.model_, "ext_filter", set()) or ())
        if k is None:
            new = set()
        elif add:
            new = cur ^ {k}
        else:
            new = set() if cur == {k} else {k}   # 고른 것을 다시 누르면 전체로
        v.set_ext_filter(new)
        self.refresh(v, force=True)


class GlobalChipBar(ChipBar):
    """형식 단추 맨 위 한 줄 (0.9.122, 사용자 11/10 '칸마다 말고 상단으로 뽑아 전체 적용'): 보이는 모든 칸의 지금 폴더 형식을 합쳐 보여 주고,
    누르면 모든 칸에 같은 형식 거르기. 고른 형식은 폴더를 옮겨도 유지('전체'를 누를 때까지) — main.chip_sel"""

    def __init__(self, main):
        super().__init__(None)
        self.main = main
        self.lay.setContentsMargins(6, 2, 6, 2)

    def views(self):
        out = []
        for p in getattr(self.main, "panes", []):
            if not p.isHidden() and p.view() is not None and p.view().path and p.view().path != THIS_PC and not devices.is_dev(p.view().path):
                out.append(p.view())
        return out

    def refresh_all(self, force=False):
        if not OPTS["type_chips"] or not OPTS["chips_global"]:
            self.setVisible(False)
            self.sig = None
            return
        vs = self.views()
        counts = {}
        for v in vs:
            for e in v.model_.all:
                k = kind_of(e)
                counts[k] = counts.get(k, 0) + 1
        sel = set(self.main.chip_sel)
        for k in sel:
            counts.setdefault(k, 0)
        sig = (tuple(id(v) for v in vs), tuple(v.path for v in vs), tuple(sorted(counts.items())), tuple(sorted(sel)), OPTS["chip_counts"])
        if sig == self.sig and not force:
            return
        self.sig = sig
        self._clear()
        if len(counts) < 2 and not sel:
            self.setVisible(False)
            return
        self.v, self.counts = None, counts
        order = (["/"] if "/" in counts else []) + sorted((k for k in counts if k != "/"), key=lambda k: (-counts[k], k))
        self._chip(None, T("전체"), None, sum(counts.values()), not sel)
        for k in order:
            self._chip(None, kind_label(k), k, counts[k], k in sel)
        b = QtWidgets.QToolButton()
        b.setObjectName("chipMore")
        b.setToolTip(T("나머지 형식"))
        b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        b.setFocusPolicy(Qt.NoFocus)
        self._style(b, None, False)
        mm = QtWidgets.QMenu(b)
        mm.aboutToShow.connect(lambda mm=mm: self._fill_more(mm))
        b.setMenu(mm)
        self.lay.addWidget(b)
        self.more = b
        self.lay.addStretch(1)
        self.setVisible(True)
        self._fit()

    def _fill_more(self, mm):
        mm.clear()
        for k in getattr(self, "_hidden", []):
            a = mm.addAction(color_dot(self.color_of(k)), f"{kind_label(k)}  ({self.counts.get(k, 0):,})", lambda k=k: self._pick(None, k, False))
            a.setCheckable(True)
            a.setChecked(k in self.main.chip_sel)

    def _pick(self, v, k, add):
        cur = set(self.main.chip_sel)
        if k is None:
            new = set()
        elif add:
            new = cur ^ {k}
        else:
            new = set() if cur == {k} else {k}
        self.main.chip_sel = new
        for vv in self.views():
            vv.set_ext_filter(new)
        log.info("형식 단추(맨 위) %s → 칸 %d개", sorted(new) or "전체", len(self.views()))
        self.refresh_all(force=True)

    def apply_to(self, v):
        """폴더를 새로 읽은 칸에도 맨 위에서 고른 형식을 그대로"""
        if OPTS["type_chips"] and OPTS["chips_global"] and self.main.chip_sel and v.path != THIS_PC:
            if set(getattr(v.model_, "ext_filter", set()) or ()) != set(self.main.chip_sel):
                v.set_ext_filter(set(self.main.chip_sel))


class Pane(QtWidgets.QFrame):
    changed = QtCore.Signal()

    def __init__(self, idx, parent=None):
        super().__init__(parent)
        self.idx = idx
        self.shown = True
        self.base_mode = "details"   # 0.9.116: 칸 기본 보기 (새 탭·기억 없는 폴더). self.mode = 지금 탭이 실제로 보이는 보기
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
        # 0.9.116 (사용자 11/8 #21): 몇 글자 치면 자주·최근 간 폴더 후보 / 경로를 치면 그 아래 폴더 후보
        self._addr_model = QtCore.QStringListModel(self)
        self._addr_comp = QtWidgets.QCompleter(self._addr_model, self)
        self._addr_comp.setCompletionMode(QtWidgets.QCompleter.UnfilteredPopupCompletion)
        self._addr_comp.setMaxVisibleItems(12)
        self._addr_comp.setWidget(self.addr)
        self._addr_comp.activated[str].connect(self._addr_pick)
        self.addr.textEdited.connect(self._addr_suggest)
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
        self.bar.color_of = lambda i: getattr(self.pages.get(self.bar.tabData(i)), "tab_color", "")
        self.bar.set_multi(SETTINGS["tab_multirow"])   # 0.9.123 여러 줄 탭
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
        self.chips = ChipBar(self)   # 빌드 17: [전체][폴더][JPG][PSD]… (galleryV8 참고)
        rl.addWidget(self.chips)
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
        self.bar.countChanged.connect(self.update_tabrow)

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

    def refresh_chips(self, v):
        """형식 단추: 칸마다 줄 또는 맨 위 한 줄 (0.9.122)"""
        self.chips.refresh(v)
        mw = main_of(self)
        g = getattr(mw, "global_chips", None) if mw is not None else None
        if g is not None:
            g.apply_to(v)
            QtCore.QTimer.singleShot(0, g.refresh_all)

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
                    k = self.bar.tabData(j)
                    if k != keep and not self.pages[k].locked:   # 잠긴 탭은 남김 (v0.9.95)
                        self.close_tab(j)
            m.addAction(T("다른 탭 모두 닫기 (잠긴 탭은 남김)"), close_others)
            pg = self.pages.get(self.bar.tabData(i))
            if pg is not None:   # 탭 잠금 (v0.9.95) — 잠긴 탭에서 다른 폴더를 열면 새 탭으로
                a = m.addAction(mlabel(T("탭 잠금 (다른 폴더는 새 탭으로)"), "lock_tab"), lambda: self.toggle_lock(i))
                a.setCheckable(True)
                a.setChecked(pg.locked)
            if pg is not None:   # 탭 색 (v0.9.89 사용자 11/4)
                cm = m.addMenu(T("탭 색"))
                for k, lbl, strong in labels.TAB_COLORS:   # v0.9.90 13색 + 직접 고르기
                    a = cm.addAction(color_dot(strong), lbl, lambda k=k: self.set_tab_color(pg, k))
                    a.setCheckable(True)
                    a.setChecked(pg.tab_color == k)
                cm.addSeparator()
                own = pg.tab_color if pg.tab_color and pg.tab_color not in labels.TAB_HEX else ""
                a = cm.addAction(color_dot(own) if own else QtGui.QIcon(), T("다른 색 고르기…"),
                                 lambda: self.pick_tab_color(pg))
                a.setCheckable(True)
                a.setChecked(bool(own))
                cm.addAction(T("색 없음"), lambda: self.set_tab_color(pg, ""))
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
    def pick_tab_color(self, pg):
        """탭 색 직접 고르기 (v0.9.90) — 윈도우 색 고르기 창, 고른 색은 '#rrggbb' 로 저장"""
        start = QtGui.QColor(labels.tab_hex(pg.tab_color) or "#3e63dd")
        c = QtWidgets.QColorDialog.getColor(start, self, T("탭 색"))
        if c.isValid():
            self.set_tab_color(pg, c.name())
        else:
            log.info("탭 색 직접 고르기 취소")

    def set_tab_color(self, pg, color):
        pg.tab_color = color or ""
        log.info("탭 색 pane=%d %s → %s", self.idx, pg.path, color or "없음")
        self.bar.update()
        self.changed.emit()

    def view(self):
        return self.stack.currentWidget()

    def views(self):
        return [self.pages[self.bar.tabData(i)] for i in range(self.bar.count())]

    def add_tab(self, path, activate=True, focus=False):
        v = Page(path, self.base_mode)
        key = id(v)
        self.pages[key] = v
        v.pathChanged.connect(lambda p, v=v: self._on_path(v, p))
        v.typesChanged.connect(lambda v=v: v is self.view() and self.refresh_chips(v))
        v.status.connect(lambda s, v=v: v is self.view() and (self.stat.setText(T("🔒 잠긴 탭이라 새 탭으로 열었습니다") + "  ·  " + s if v.from_locked else s),
                                                             self.stat.setToolTip(getattr(v, "status_tip", ""))))
        v.status.connect(lambda s, v=v: v is self.view() and self._poke_preview())   # 선택·폴더가 바뀌면 상태 글자가 바뀜 (v0.9.58)
        v.openInNewTab.connect(lambda p: self.add_tab(p, activate=False))
        v.openLocation.connect(self._open_location_tab)
        v.lockedNav.connect(lambda p, s, v=v: self._locked_open(v, p, s))
        v.lockChanged.connect(lambda v=v: (self._on_path(v, v.path), self.changed.emit()))
        hd = v.tree.header()   # 정렬·열 너비가 바뀌면 상태 저장 예약(2초 뒤 한 번)
        hd.sortIndicatorChanged.connect(lambda *_: self.changed.emit())
        hd.sortIndicatorChanged.connect(v._vm_sorted)   # 0.9.116 폴더마다 정렬 기억
        v.pane_ref = self
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

    @staticmethod
    def tab_text(v):
        return ("🔒 " if v.locked else "") + tab_title(v.path)

    def _locked_open(self, v, path, select=None):
        """잠긴 탭에서 다른 폴더로 가려 함 (v0.9.95) → 그 탭 바로 오른쪽에 새 탭으로 열고 그쪽으로"""
        i = next((k for k in range(self.bar.count()) if self.bar.tabData(k) == id(v)), -1)
        nv = self.add_tab(path, activate=True)
        nv.pending_select = select
        if 0 <= i < self.bar.count() - 2:
            self.bar.moveTab(self.bar.count() - 1, i + 1)
        nv.tree.setFocus(Qt.OtherFocusReason)
        nv.from_locked = True
        self.stat.setText(T("🔒 잠긴 탭이라 새 탭으로 열었습니다"))

    def toggle_lock(self, i=None):
        i = self.bar.currentIndex() if i is None else i
        v = self.pages.get(self.bar.tabData(i))
        if v is not None:
            v.set_locked(not v.locked)

    def _open_location_tab(self, folder, name):
        """Ctrl+Enter 로 파일의 폴더 위치를 새 탭으로 (v0.9.94) — 그 탭으로 가서 파일 고름"""
        v = self.add_tab(folder, activate=True)
        v.pending_select = name or None

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
        nv.tab_color = v.tab_color   # 탭 색도 따라감 (v0.9.89)
        nv.set_locked(v.locked)      # 잠금도 (v0.9.95)
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
        if v.tab_color and w.pane().view() is not None:
            w.pane().view().tab_color = v.tab_color
        if v.locked and w.pane().view() is not None:
            w.pane().view().set_locked(True)
        for i in range(self.bar.count()):
            if self.bar.tabData(i) == key and self.bar.count() > 1:
                self.close_tab(i)
                break
        return w

    def update_tabrow(self):
        """탭이 하나뿐이면 탭줄 숨김 (옵션, v0.9.75). 새 탭은 Ctrl+T · 가운데 클릭 · 우클릭 '새 탭에서 열기'"""
        show = not (SETTINGS["hide_single_tab"] and self.bar.count() <= 1)
        if self.tabrow.isVisibleTo(self) != show:
            self.tabrow.setVisible(show)

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
        if v is self.view():
            QtCore.QTimer.singleShot(0, lambda p=p: getattr(self.window(), "folder_memo_check", lambda _p: None)(p))
        for i in range(self.bar.count()):
            if self.bar.tabData(i) == id(v):
                self.bar.setTabText(i, self.tab_text(v))
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
        self.refresh_chips(v)
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

    def addr_candidates(self, t):
        """주소줄 글자 → 후보 폴더 목록 (0.9.116). 경로 모양이면 그 폴더의 하위 폴더, 아니면 자주 간 폴더"""
        t = t.strip().strip('"')
        if len(t) < 2:
            return []
        if ":" in t[:3] or t.startswith("\\\\") or t.startswith("%"):
            t2 = os.path.expandvars(t)
            if t2.startswith("\\\\") and t2.count("\\") < 4:   # 네트워크 서버 이름만 친 것 → 훑지 않음 (느림)
                return []
            parent, pre = (t2, "") if t2.endswith(("\\", "/")) else os.path.split(t2)
            if not parent or not isdir_quick(parent):
                return []
            out = []
            try:
                with os.scandir(parent) as it:
                    for e in it:
                        if len(out) >= 40:
                            break
                        if e.name.lower().startswith(pre.lower()) and e.is_dir() and (OPTS["show_hidden"] or not e.name.startswith(".")):
                            out.append(os.path.join(parent, e.name))
            except OSError as ex:
                log.info("주소 후보: 폴더 못 읽음 %s (%s)", parent, ex)
            return sorted(out, key=lambda p: shellops.natural_key(os.path.basename(p)))
        return FRECENT.match(t)

    def _addr_suggest(self, t):
        c = self.addr_candidates(t)
        self._addr_model.setStringList(c)
        if c:
            self._addr_comp.complete()
        else:
            self._addr_comp.popup().hide()

    def _addr_pick(self, p):
        self.addr.setText(p)
        log.info("주소 후보 고름 %s", p)
        self._addr_go()

    def _addr_go(self):
        t = os.path.expandvars(self.addr.text().strip().strip('"'))
        v = self.view()
        if not v:
            return
        if (devices.is_dev(v.path) or archives.is_arc(v.path)) and t == disp_path(v.path):   # 휴대폰·압축: 주소줄 글자는 보여 주기용 → 그대로면 새로 고침
            v.reload("addr")
            self._crumb_back()
            return
        cmd = t.lower()
        if cmd.endswith(".exe"):
            cmd = cmd[:-4]
        if cmd in ("cmd", "powershell", "pwsh") and not os.path.exists(t):   # 탐색기처럼 주소창에 cmd → 지금 폴더에서 (v0.9.70)
            here = v.path if os.path.isdir(v.path) else os.path.expanduser("~")
            shellops.open_console(cmd, here)
            self.addr.setText(disp_path(v.path))
            self._crumb_back()
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
        if ev.type() == QtCore.QEvent.MouseButtonDblClick and obj is self.bar and ev.button() == Qt.LeftButton:   # 0.9.112 빌드 4: 탭 두 번 누르기 = 닫기 (사용자 11/6)
            i = self.bar.tabAt(ev.position().toPoint())
            if i >= 0:
                log.info("탭 두 번 누름 → 닫기 pane=%d tab=%d", self.idx, i)
                self.close_tab(i)
                return True
        return super().eventFilter(obj, ev)

    # ---------------------------------------------------------- 보기
    @property
    def mode(self):
        """지금 탭이 실제로 보이는 보기 (메뉴 체크·Ctrl+휠 순서). 칸 기본은 base_mode (0.9.116)"""
        v = self.view() if hasattr(self, "stack") else None
        return v.mode if v is not None else self.base_mode

    @mode.setter
    def mode(self, m):
        self.base_mode = m

    def set_mode(self, mode):
        cur = self.view()
        if cur is not None and cur._vm_ok():   # 0.9.116 폴더마다 보기 기억: 그 폴더만 바꾸고 기억 (칸 기본은 그대로)
            VIEWMEM.remember(cur.path, mode=mode)
            cur.set_mode(mode)
            log.info("보기 방식 pane=%d %s (이 폴더만: %s)", self.idx, mode, cur.path)
            self.changed.emit()
            return
        self.base_mode = mode
        for v in self.views():
            v.set_mode(mode)
        log.info("보기 방식 pane=%d %s", self.idx, mode)
        self.changed.emit()

    def _poke_preview(self):
        m = main_of(self)
        if m is not None and getattr(m, "preview", None) is not None and m.active_pane is self:
            m.preview.schedule(m)

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
        main = main_of(self)
        if SETTINGS["side_shared"]:   # v0.9.100 공용 탐색 창을 쓰는 중 → v0.9.101 여기서는 숨기기/보이기
            a = show.addAction(T("공용 탐색 창 (창 왼쪽)"), lambda: main.toggle_shared_visible() if main is not None else None)
            a.setCheckable(True)
            a.setChecked(not SETTINGS["side_shared_hidden"])
        else:
            a = show.addAction(T("탐색 창"), lambda: self.toggle_sidebar())
            a.setCheckable(True)
            a.setChecked(bool(getattr(self, "side_on", False)))
        # v0.9.104: 자주 켜고 끄는 것만 (경로 버튼·날짜 정렬 폴더 위로·SVN·그림 미리보기·버전 관리 표시는 설정 창)
        for key, lbl in (("checkboxes", T("항목 확인란")), ("show_ext", T("파일 확장명")), ("show_hidden", T("숨긴 항목")),
                         ("date_groups", T("날짜별로 묶기 (오늘·어제·이번 주…)")), ("type_groups", T("형식별로 묶기 (폴더·JPG·PNG…)")),
                         ("type_chips", T("형식 단추 줄 ([전체][JPG][PSD]…)"))):
            a = show.addAction(lbl, lambda key=key: main.toggle_opt(key) if main is not None else None)
            a.setCheckable(True)
            a.setChecked(OPTS[key])
        set_menu_tips(m)

        # v0.9.103: '탭이 하나면 탭 줄 숨기기' 등 동작 설정은 메뉴줄 '설정'으로 옮김 (사용자 11/5)

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
        main = main_of(self)
        if main is not None and getattr(main, "active_pane", None) is self:   # v0.9.100 공용 탐색 창은 대상 칸 폴더를 따라감
            main.sync_shared_side()

    def set_sidebar(self, on, save=True):
        """칸별 탐색 창 (v0.9.100: side_on = 사용자 설정, 공용 탐색 창이 켜져 있으면 설정은 남기고 화면만 숨김)"""
        self.side_on = bool(on)
        shared = bool(SETTINGS["side_shared"])
        on = self.side_on and not shared
        if on and self.side is None:
            self.side = Sidebar()
            self.side.go.connect(lambda p: self.go(p))
            self.side.goNewTab.connect(lambda p: self.go(p, new_tab=True))
            self.side_host.layout().addWidget(self.side)
        if not on and self.side_host.isVisibleTo(self) and self.body.sizes()[0] >= 60:   # 이슈 #5: 숨기기 전 폭 기억 (공용 모드로 바꿀 때 등)
            self._side_w = self.body.sizes()[0]
        self.side_host.setVisible(on)
        if on and self.body.sizes()[0] < 60:
            total = sum(self.body.sizes()) or 800
            w = int(getattr(self, "_side_w", 0) or 200)
            self.body.setSizes([w, max(total - w, 200)])
        # v0.9.101: 공용 모드에서도 ☰ 보임 → 누르면 공용 탐색 창 숨기기/보이기 (체크 = 공용 창 보임)
        self.btn_side.setChecked(on if not shared else not SETTINGS["side_shared_hidden"])
        self.btn_side.setToolTip(T("공용 탐색 창 보이기/숨기기") if shared else T("탐색 창 보이기/숨기기"))
        if on:
            self.sync_sidebar()
        if save:
            log.info("탐색 창 pane=%d %s", self.idx, on)
            self.changed.emit()

    def _body_sizes(self):
        """저장용 탐색 창·목록 폭 — 숨겨져 0 이면 숨기기 전 폭으로 (이슈 #5)"""
        s = self.body.sizes()
        if s and s[0] < 60 and getattr(self, "_side_w", 0) and len(s) > 1:
            return [self._side_w, max(sum(s) - self._side_w, 200)]
        return s

    def toggle_sidebar(self):
        main = main_of(self)
        if SETTINGS["side_shared"] and main is not None:   # v0.9.101 공용 모드면 공용 탐색 창을 숨기기/보이기
            main.toggle_shared_visible()
            return
        self.set_sidebar(not getattr(self, "side_on", False))

    def state(self):
        return {"tabs": [v.path for v in self.views()], "current": self.bar.currentIndex(), "mode": self.base_mode,
                "sidebar": bool(getattr(self, "side_on", False)), "body": self._body_sizes(),
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
        # v0.9.102 사용자 11/5: 메뉴줄 '즐겨찾기'는 빼고 이 글자를 누르면 즐겨찾기 메뉴
        lbl = QtWidgets.QToolButton()
        lbl.setText(T("즐겨찾기"))   # 화살표는 메뉴 버튼이 붙여 줌(위 메뉴줄과 같은 모양)
        lbl.setToolTip(T("즐겨찾기 메뉴 (추가·정리·윈도우 탐색기에서 가져오기)"))
        lbl.setAutoRaise(True)
        lbl.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        lbl.setCursor(Qt.PointingHandCursor)
        fm = QtWidgets.QMenu(lbl)
        fm.aboutToShow.connect(lambda: (fm.clear(), self.main._fill_fav_menu(fm)))
        lbl.setMenu(fm)
        self.lbl = lbl
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
        lay.insertWidget(0, self.btn_fold, 0, Qt.AlignTop)   # v0.9.105 사용자 11/5: 메뉴줄 ▲ 처럼 왼쪽 끝
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
        ficon_service().ready.connect(self._ficon)   # 0.9.114 파일 즐겨찾기 아이콘
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
                b.setIcon(self._fav_icon(fav_icon(d), self.svn.get(d["path"])))
                b.setText(d["name"])
                b.setProperty("favIndex", start)
                if d.get("file"):   # 0.9.114 이슈 #8
                    b.setToolTip(T('{0}\n클릭: 연결 프로그램으로 열기 · 끌어서 순서 변경 · 우클릭: 이름/삭제').format(d['path']))
                else:
                    b.setToolTip(T('{0}\n클릭: 선택된 칸에서 열기 · Ctrl+클릭: 새 탭 · 끌어서 순서 변경 · 우클릭: 이름/삭제').format(d['path']))
                b.clicked.connect(lambda _=False, p=d["path"]: self.main.open_fav(p))
            b.installEventFilter(self)
            self.flow.addWidget(b)
            self.buttons.append(b)
        if not FAV.items:
            b = QtWidgets.QLabel(T("  폴더·파일을 여기로 끌어다 놓기 · 우클릭 > ★ 4Dir 즐겨찾기에 추가 · Ctrl+D"))
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
        for b in self.fav_buttons():
            i = b.property("favIndex")
            if i is not None and i < len(FAV.items):
                b.setIcon(self._fav_icon(fav_icon(FAV.items[i]), st.get(FAV.items[i]["path"])))
                b.setProperty("svnDone", True)
        log.info("즐겨찾기 SVN 표시 %d개 %s", len(st), {os.path.basename(k.rstrip("\\\\")): v for k, v in list(st.items())[:6]})

    def _ficon(self, path):
        """파일 즐겨찾기(exe·바로가기 등) 진짜 아이콘을 받으면 그 버튼만 다시 그림 (0.9.114)"""
        n = os.path.normcase(path)
        for b in self.fav_buttons():
            i = b.property("favIndex")
            if i is not None and i < len(FAV.items) and os.path.normcase(FAV.items[i]["path"]) == n:
                b.setIcon(self._fav_icon(fav_icon(FAV.items[i]), self.svn.get(FAV.items[i]["path"])))

    def _group_popup(self, b):
        g = b.property("favGroup")
        m = QtWidgets.QMenu(self)
        for d in FAV.items[b.property("favStart"):b.property("favEnd")]:
            a = m.addAction(self._fav_icon(fav_icon(d), self.svn.get(d["path"])), d["name"])
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
        m.addSeparator()
        m.addAction(T("즐겨찾기 줄 숨기기"), self.hide_line)   # 0.9.116 빌드 2
        m.exec(pos)

    def hide_line(self):
        """즐겨찾기를 안 쓰는 사람: 줄째 숨김 (다시: 보기 → 즐겨찾기 줄 보이기)"""
        if SETTINGS["show_favbar"]:
            self.main.toggle_setting("show_favbar")
        self.main.show_notice(T("즐겨찾기 줄을 숨겼습니다. 다시 보려면: 보기 → 즐겨찾기 줄 보이기") + "  ✕", ms=8000,
                              action=(T("되돌리기"), lambda: self.main.toggle_setting("show_favbar")))

    def _fav_menu(self, i, pos):
        d = FAV.items[i]
        m = QtWidgets.QMenu(self)
        if d.get("file"):   # 0.9.114 파일 즐겨찾기
            m.addAction(T("열기"), lambda: self.main.open_fav(d["path"]))
            m.addAction(T("파일 위치 열기"), lambda: self.main.pane().go(os.path.dirname(d["path"]), new_tab=True))
        else:
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
        # 0.9.114 이슈 #8: 파일·바로가기도 등록 (전엔 폴더만). 즐겨찾기 폴더 버튼 '가운데'만 그 폴더로 복사·이동(진하게 표시),
        #   가장자리·사이·빈 곳 = 즐겨찾기 등록(파란 세로줄 + '즐겨찾기에 추가')
        has_dir = fav or any(os.path.exists(u.toLocalFile()) for u in md.urls() if u.isLocalFile())
        for b in self.fav_buttons():
            if not b.geometry().contains(p):
                continue
            g = b.geometry()
            x = p.x() - g.left()
            if not fav and g.width() * 0.25 <= x <= g.width() * 0.75:
                if b.property("favGroup"):
                    if has_dir:
                        return ("into", b)   # 폴더·파일 → 그 묶음에 추가
                elif not FAV.items[b.property("favStart")].get("file") and os.path.isdir(FAV.items[b.property("favStart")]["path"]):
                    return ("into", b)
            if not has_dir:
                return None   # 등록할 수 있는 것(실제 폴더·파일) 없음
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
                if p and os.path.exists(p):
                    FAV.add(p, group=g, file=not os.path.isdir(p))
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
                if p and os.path.exists(p):
                    if FAV.add(p, pos=pos, file=not os.path.isdir(p)):
                        pos += 1
        ev.setDropAction(Qt.CopyAction)
        ev.accept()


# ================================================================ 레이아웃 아이콘 (코드로 그림)
LAYOUTS = [("1", T("1칸")), ("2h", T("2칸 좌우")), ("2v", T("2칸 상하")),
           ("2t", T("2칸 상하 (위 작게)")), ("2b", T("2칸 상하 (아래 작게)")),
           ("3r", T("3칸 (왼쪽 2 + 오른쪽 1)")), ("3l", T("3칸 (왼쪽 1 + 오른쪽 2)")),
           ("3", T("3칸 (위 2 + 아래 1)")), ("3b", T("3칸 (위 1 + 아래 2)")),
           ("4l", T("4칸 (왼쪽 3 + 오른쪽 1)")), ("4r", T("4칸 (왼쪽 1 + 오른쪽 3)")),
           ("4t", T("4칸 (위 3 + 아래 1)")), ("4b", T("4칸 (위 1 + 아래 3)")), ("4", T("4칸")),
           ("3h", T("3칸 가로")), ("6", T("6칸 (3 x 2)"))]
# 0.9.113 (사용자 11/6 '단축키에 기능이 전부 없더라'): 메뉴에만 있던 기능 → 단축키·마우스·기능 검색·My메뉴 공용 기능 표에 더함
SHOW_OPTS = [("checkboxes", T("항목 확인란")), ("show_ext", T("파일 확장명")),
             ("date_groups", T("날짜별로 묶기 (오늘·어제·이번 주…)")), ("type_groups", T("형식별로 묶기 (폴더·JPG·PNG…)"))]
SET_TOGGLES = [("hide_single_tab", T("탭이 하나면 탭 줄 숨기기 (새 탭: Ctrl+T)")), ("empty_click_up", T("빈 곳을 더블클릭하면 상위 폴더로")),
               ("arc_browse", T("압축 파일(ZIP·7Z·RAR…)을 두 번 누르면 4Dir 안에서 폴더처럼 열기")),
               ("folder_size", T("폴더 크기 계산 (크기 칸 — 네트워크 드라이브 제외)")), ("keep_favbar", T("메뉴줄을 접어도 즐겨찾기 줄은 보이기")),
               ("show_favbar", T("즐겨찾기 줄 보이기")),
               ("folder_view_memory", T("폴더마다 보기 기억"))]   # 0.9.116 빌드 2 (사용자 게시판: 안 쓰면 줄째 숨기기)
THEMES = [("system", T("시스템 설정 따름")), ("light", T("밝게 (Light)")), ("dark", T("어둡게 (Dark)"))]


def _extra_actions():
    w = "window"
    out = [(f"view_{k}", T("보기: {0}").format(lbl), "", w, "view") for k, lbl, _px in VIEW_MODES]
    out += [(f"show_{k}", T("표시: {0}").format(lbl), "", w, "view") for k, lbl in SHOW_OPTS]
    out += [(f"sort_{c}", T("정렬: {0}").format(lbl), "", w, "sort") for c, lbl in SORT_COLS]
    out += [("sort_asc", T("정렬: {0}").format(T("오름차순")), "", w, "sort"), ("sort_desc", T("정렬: {0}").format(T("내림차순")), "", w, "sort")]
    out += [(f"layout_{k}", T("레이아웃: {0}").format(lbl), "", w, "layout") for k, lbl in LAYOUTS]
    out += [("layout_custom", T("레이아웃: {0}").format(T("직접 지정 (가로 x 세로)…")), "", w, "layout")]
    out += [("side_shared", T("탐색 창 공용/칸마다 바꾸기"), "", w, "panel"), ("toggle_favbar", T("즐겨찾기 바 펼치기"), "", w, "panel"),
            ("toggle_sysmon", T("CPU·GPU 사용량 표시"), "", w, "panel"), ("toggle_on_top", T("항상 위"), "", w, "panel")]
    out += [(f"rate_{k}", T("별점 주기: {0}").format("★" * k) if k else T("별점 빼기"), "", w, "file") for k in range(6)]   # 0.9.116
    out += [("batch_rename", T("이름 일괄 변경…"), "", w, "tools"), ("explorer_check", T("Explorer Check (탐색기 점검)"), "", w, "tools")]
    out += [("fav_organize", T("즐겨찾기 정리…"), "", w, "fav"), ("fav_import", T("윈도우 탐색기 즐겨찾기 가져오기 (선택)"), "", w, "fav"),
            ("ws_save", T("현재 창 구성 저장…"), "", w, "fav")]
    out += [("keys_settings", T("단축키 설정…"), "", w, "settings"), ("color_settings", T("색상 설정…"), "", w, "settings"),
            ("search_roots", T("검색 범위 설정…"), "", w, "settings")]
    out += [(f"theme_{k}", T("화면 테마: {0}").format(lbl), "", w, "settings") for k, lbl in THEMES]
    out += [(f"set_{k}", T("설정: {0}").format(lbl), "", w, "settings") for k, lbl in SET_TOGGLES]
    out += [("set_allow_multi", T("설정: {0}").format(T("창 여러 개 열기 허용")), "", w, "settings"),
            ("overlay_order", T("겹침 아이콘 순서 정리 (윈도우)…"), "", w, "settings"),
            ("export_settings", T("설정 내보내기 (백업 파일로 저장)…"), "", w, "settings"),
            ("import_settings", T("설정 가져오기 (백업 파일에서 되돌리기)…"), "", w, "settings"),
            ("guide", T("사용법…"), "", w, "settings"), ("check_update", T("새 버전 확인"), "", w, "settings"),
            ("open_logs", T("로그 폴더 열기"), "", w, "settings"), ("save_report", T("문제 보고용 로그 저장… (4Dir 폴더의 reports 에 zip)"), "", w, "settings")]
    return out


keymap.register(_extra_actions())

# 레이아웃 고르기 창의 줄 (v0.9.92 사용자 11/4 '맥스처럼 전부 + 버튼 하나 눌러 팝업') — 맥스 순서 7개씩, 마지막 줄 + 직접 지정
LAYOUT_POPUP_ROWS = [["1", "2h", "2v", "2t", "2b", "3r", "3l"], ["3", "3b", "4l", "4r", "4t", "4b", "4"], ["3h", "6"]]
# 줄마다 보일 칸 번호. 위 줄 = 0,1,4 / 아래 줄 = 2,3,5 (예전 4칸·6칸 저장 상태와 번호 호환)
LAYOUT_ROWS = {"1": [[0]], "2h": [[0, 1]], "2v": [[0], [2]], "3": [[0, 1], [2]],
               "3h": [[0, 1, 4]], "4": [[0, 1], [2, 3]], "6": [[0, 1, 4], [2, 3, 5]],
               "3l": [[0], [1, 3]], "3r": [[0, 2], [1]], "4l": [[0, 4, 2], [1]], "4r": [[0], [1, 5, 3]],
               "2t": [[0], [2]], "2b": [[0], [2]], "3b": [[0], [2, 3]], "4t": [[0, 1, 4], [2]], "4b": [[0], [2, 3, 5]]}
# 세로 줄(열) 단위 배치 (v0.9.90 사용자 의견 '왼쪽 긴 1칸 + 오른쪽 2칸'): 위 목록이 '줄' 대신 '열' — 분할 방향만 바꿔 씀.
# 칸 번호는 4칸 자리와 맞춤 (왼쪽=0 왼쪽 위, 오른쪽 위=1, 오른쪽 아래=3) → 4칸 ↔ 이 배치 오가도 폴더가 제자리
COL_LAYOUTS = {"3l", "3r", "4l", "4r"}
LAYOUT_RATIO = {"2t": (1, 2), "2b": (2, 1)}   # 줄(열) 크기 비율 — 없으면 같게
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
    rows = layout_rows(key) or [[0]]   # v0.9.92: 칸 목록으로 그림 (줄/열·비율 공통)
    x0, y0, x1, y1 = 1, 5, w - 2, h - 2
    cols = key in COL_LAYOUTS
    ratio = LAYOUT_RATIO.get(key) or (1,) * len(rows)
    a0, a1 = (x0, x1) if cols else (y0, y1)
    edges, acc = [a0], 0
    for r in ratio:
        acc += r
        edges.append(a0 + round((a1 - a0) * acc / sum(ratio)))
    for i, row in enumerate(rows):
        s0, s1 = edges[i], edges[i + 1]
        if i:
            p.drawLine(s0, y0, s0, y1) if cols else p.drawLine(x0, s0, x1, s0)
        b0, b1 = (y0, y1) if cols else (x0, x1)
        for j in range(1, len(row)):
            t = b0 + round((b1 - b0) * j / len(row))
            p.drawLine(s0, t, s1, t) if cols else p.drawLine(t, s0, t, s1)
    p.end()
    return QtGui.QIcon(pm)


class LayoutPopup(QtWidgets.QFrame):
    """레이아웃 고르기 창 (v0.9.92): Main.layout_actions 를 그림 버튼으로 (지금 배치는 눌린 표시). 누르면 바로 바뀌고 닫힘"""

    def __init__(self, main):
        super().__init__(main, Qt.Popup)
        self.setObjectName("layoutPopup")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QGridLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
        self.buttons = {}
        for r, keys in enumerate(LAYOUT_POPUP_ROWS):
            for c, k in enumerate(keys):
                lay.addWidget(self._btn(main.layout_actions[k], k), r, c)
        gb = self._btn(main.act_grid, "grid")
        gb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        last = len(LAYOUT_POPUP_ROWS) - 1
        lay.addWidget(gb, last, len(LAYOUT_POPUP_ROWS[-1]), 1, 7 - len(LAYOUT_POPUP_ROWS[-1]), Qt.AlignLeft)

    def _btn(self, act, key):
        b = QtWidgets.QToolButton(self)
        b.setDefaultAction(act)
        b.setIconSize(QtCore.QSize(40, 32))
        b.setAutoRaise(True)
        b.setObjectName("layoutPick")
        act_cb = lambda *_: self.close()
        b.clicked.connect(act_cb)
        self.buttons[key] = b
        return b


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


def chips_icon(sz=20):
    """형식 단추 줄 켜기/끄기 단추 아이콘 (빌드 27, 빌드 28 사용자 '캡슐 하나를 대각선으로 반반'): 파랑 | 주황 캡슐"""
    dpr = 2
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(dpr * sz / 20.0, dpr * sz / 20.0)
    cap = QtGui.QPainterPath()
    cap.addRoundedRect(QtCore.QRectF(1.5, 6, 17, 8), 4, 4)
    P = QtCore.QPointF
    left = QtGui.QPainterPath()
    left.addPolygon(QtGui.QPolygonF([P(0, 0), P(12.5, 0), P(7.5, 20), P(0, 20)]))
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#e07b00"))
    p.drawPath(cap)
    p.setBrush(QtGui.QColor("#2f6fd0"))
    p.drawPath(cap.intersected(left))
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 230), 1.2))   # 가운데 대각선 흰 금
    p.drawLine(P(11.5, 6.3), P(8.5, 13.7))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QtGui.QIcon(pm)


def memo_icon(sz=20):
    """메모 창 버튼 그림 (빌드 7 사용자 11/5 '포스트잇 같은 노란색에 빨간 펜'): 노란 메모지(접힌 귀·줄) + 빨간 펜"""
    dpr = 2
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(dpr, dpr)
    s = sz / 20.0
    # 메모지 (오른쪽 아래 귀 접힘)
    note = QtGui.QPainterPath()
    note.moveTo(2 * s, 3 * s)
    note.lineTo(15 * s, 3 * s)
    note.lineTo(15 * s, 13 * s)
    note.lineTo(11 * s, 17 * s)
    note.lineTo(2 * s, 17 * s)
    note.closeSubpath()
    p.setPen(QtGui.QPen(QtGui.QColor("#c9a200"), 1.0 * s))
    p.setBrush(QtGui.QColor("#ffd84d"))
    p.drawPath(note)
    p.setBrush(QtGui.QColor("#e6b800"))   # 접힌 귀
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(15 * s, 13 * s), QtCore.QPointF(11 * s, 13 * s), QtCore.QPointF(11 * s, 17 * s)]))
    p.setPen(QtGui.QPen(QtGui.QColor("#b38f00"), 1.0 * s))   # 글 줄
    for y in (7, 10, 13):
        p.drawLine(QtCore.QPointF(4.5 * s, y * s), QtCore.QPointF((10 if y == 13 else 12.5) * s, y * s))
    # 빨간 펜 (오른쪽 위 → 메모지 위로 비스듬히)
    p.save()
    p.translate(14.5 * s, 7.5 * s)
    p.rotate(45)
    p.setPen(QtGui.QPen(QtGui.QColor("#8e1b1b"), 0.8 * s))
    p.setBrush(QtGui.QColor("#e53935"))
    p.drawRoundedRect(QtCore.QRectF(-1.6 * s, -8.5 * s, 3.2 * s, 10 * s), 0.8 * s, 0.8 * s)   # 몸통
    p.setBrush(QtGui.QColor("#f2d0a4"))
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(-1.6 * s, 1.5 * s), QtCore.QPointF(1.6 * s, 1.5 * s), QtCore.QPointF(0, 4.6 * s)]))   # 깎은 부분
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#e53935"))
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(-0.6 * s, 3.4 * s), QtCore.QPointF(0.6 * s, 3.4 * s), QtCore.QPointF(0, 4.6 * s)]))   # 펜 끝
    p.restore()
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QtGui.QIcon(pm)


class MemoWindow(QtWidgets.QWidget):
    """메모 창 (빌드 8): 4Dir 창 밖 따로 창, 처음엔 4Dir 창 바로 오른쪽(화면 밖이면 안쪽 끝).
    빌드 10 사용자: 다른 창 뒤로 숨으면 찾기 힘듦 → 작업 표시줄에 나오는 보통 창 + 항상 위(📌).
    닫기 = 메모 창 끄기. 위치·크기는 설정 memo_geo 에 기억"""

    def __init__(self, main):
        super().__init__(None, Qt.Window)
        self._deact = 0.0   # 마지막으로 메모 창이 앞에서 내려간 시각 (4Dir 버튼: 보고 있던 중이면 끄기, 뒤에 숨었으면 앞으로)
        self.setWindowTitle(T("메모") + " — 4Dir")
        self.setWindowIcon(memo_icon(32))
        self.main = main
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.panel = memo.MemoPanel(memo_store(), lambda: bool(SETTINGS["dark"]), on_side=None,
                                    on_close=lambda: self._close_from_panel())
        lay.addWidget(self.panel)
        self.panel.fill_settings = self._fill_settings
        self.panel.on_pin = lambda on: self._toggle_top(on)
        self.panel.open_path = self._open_path        # 빌드 13: Ctrl+클릭 링크
        self.panel.cur_folder = self._cur_folder      # 빌드 13: 폴더 메모
        self.panel.btn_pin.setChecked(bool(SETTINGS["memo_top"]))
        self.setMinimumSize(200, 200)
        self._placed = False
        if SETTINGS["memo_top"]:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        QtGui.QShortcut(QtGui.QKeySequence("Alt+M"), self, lambda: main.set_memo(False))   # 메모 창에서도 Alt+M = 끄기

    def changeEvent(self, ev):
        if ev.type() == QtCore.QEvent.ActivationChange and not self.isActiveWindow():
            self._deact = time.time()
        super().changeEvent(ev)

    def was_front(self):
        """4Dir 버튼을 누르기 바로 전까지 메모 창을 보고 있었나 (누르는 순간 4Dir 로 활성이 넘어감)"""
        return self.isVisible() and not self.isMinimized() and (self.isActiveWindow() or time.time() - self._deact < 0.6)

    def bring_front(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _fill_settings(self, m):
        """메모 ⚙ 메뉴 (빌드 9)"""
        a = m.addAction(T("항상 위에 표시"), lambda: self._toggle_top(not SETTINGS["memo_top"]))
        a.setCheckable(True)
        a.setChecked(bool(SETTINGS["memo_top"]))
        m.addAction(T("메모 파일 위치 열기"), self._open_file_loc)

    def _front_main(self):
        w = self.main if self.main in WINDOWS else (WINDOWS[0] if WINDOWS else self.main)
        return w

    def _cur_folder(self):
        v = self._front_main().pane().view()
        p = getattr(v, "path", "") if v is not None else ""
        return p if p and p != THIS_PC and not is_search(p) and not devices.is_dev(p) and not archives.is_arc(p) else None

    def _open_path(self, path):
        """메모 링크: 폴더 = 4Dir 새 탭, 파일 = 그 폴더 새 탭 + 파일 고름 (없으면 알림)"""
        w = self._front_main()
        path = os.path.normpath(path)
        if os.path.isdir(path):
            w.pane().add_tab(path, activate=True)
        elif os.path.exists(path):
            v = w.pane().add_tab(os.path.dirname(path), activate=True)
            v.pending_select = os.path.basename(path)
        else:
            w.show_notice(T("⚠ 경로를 찾을 수 없습니다: {0}").format(path))
            return
        w.raise_()
        w.activateWindow()

    def _open_file_loc(self):
        """4Dir 새 탭으로 bin 폴더 + 메모 파일 고름"""
        w = WINDOWS[0] if WINDOWS else self.main
        v = w.pane().add_tab(BIN_DIR, activate=True)
        v.pending_select = memo.FILE
        w.raise_()
        w.activateWindow()

    def _toggle_top(self, on):
        SETTINGS["memo_top"] = bool(on)
        if self.windowHandle() is not None:   # 창을 다시 만들지 않고 깜빡임 없이 (메인 '항상 위'와 같은 방식)
            self.windowHandle().setFlag(Qt.WindowStaysOnTopHint, bool(on))
        else:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on))
        self.panel.btn_pin.setChecked(bool(on))
        log.info("메모 창 항상 위 %s", on)

    def _on_screen(self):
        """제목줄까지 화면 안에 들어오게 (빌드 9 사용자 '처음 열었을 때 위가 화면 밖이라 못 움직임')"""
        fg = self.frameGeometry()
        scr = (QtGui.QGuiApplication.screenAt(fg.center()) or self.main.screen() or QtWidgets.QApplication.primaryScreen()).availableGeometry()
        top_pad = self.geometry().top() - fg.top()   # 제목줄 높이
        x = min(max(fg.left(), scr.left()), max(scr.left(), scr.right() - fg.width()))
        y = min(max(fg.top(), scr.top()), max(scr.top(), scr.bottom() - 100))
        h = min(self.height(), scr.height() - top_pad - 8)
        if (x, y) != (fg.left(), fg.top()) or h != self.height():
            self.move(x, y)
            self.resize(self.width(), max(200, h))
            log.info("메모 창 화면 안으로 %s", self.frameGeometry().getRect())

    def show_near(self, main):
        if not self._placed:
            self._placed = True
            geo = SETTINGS["memo_geo"]
            ok = False
            if geo:
                try:
                    ok = self.restoreGeometry(QtCore.QByteArray.fromHex(geo.encode()))
                    scr = QtGui.QGuiApplication.screenAt(self.frameGeometry().center())
                    ok = ok and scr is not None   # 그 모니터가 없어졌으면 다시 자리 잡음
                except Exception:
                    ok = False
            if not ok:
                fg = main.frameGeometry()
                scr = (main.screen() or QtWidgets.QApplication.primaryScreen()).availableGeometry()
                w, h = 300, max(400, min(fg.height(), scr.height()))
                x = fg.right() + 2
                if x + w > scr.right():
                    x = max(scr.left(), scr.right() - w)   # 오른쪽에 자리가 없으면 화면 안쪽 끝
                self.setGeometry(x, max(scr.top(), fg.top()), w, h)
            log.info("메모 창 자리 %s (기억 %s)", self.geometry().getRect(), bool(ok))
        self.show()
        self._on_screen()   # 창 테두리·제목줄이 생긴 뒤 화면 안으로
        self.raise_()

    def save_geo(self):
        if self.isVisible() or self._placed:
            SETTINGS["memo_geo"] = bytes(self.saveGeometry().toHex()).decode()

    def _close_from_panel(self):
        self.close()

    def closeEvent(self, ev):
        self.save_geo()
        if MEMOS is not None:
            MEMOS.save_now()
        ev.accept()
        if SETTINGS["memo_on"] and self.main is not None:
            m = WINDOWS[0] if WINDOWS else self.main
            QtCore.QTimer.singleShot(0, lambda: m.set_memo(False))


class PreviewWindow(QtWidgets.QWidget):
    """미리보기 창 (빌드 18, 사용자 11/5 '메모 창처럼 따로 창'): 4Dir 창 밖, 작업 표시줄에 나오는 보통 창, 처음엔 4Dir 창 오른쪽.
    켜도 칸 크기가 안 바뀜. 위치·크기 preview_geo, 항상 위 preview_top(우클릭). 닫기 = 미리보기 끄기. 숨거나 최소화하면 GIF 멈춤"""

    def __init__(self, main):
        super().__init__(None, Qt.Window)
        self._deact = 0.0
        self._placed = False
        self.setWindowTitle(T("미리보기") + " — 4Dir")
        self.setWindowIcon(preview_icon())
        self.main = main
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.pane = PreviewPane(main)
        lay.addWidget(self.pane)
        self.setMinimumSize(200, 240)
        if SETTINGS["preview_top"]:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        QtGui.QShortcut(QtGui.QKeySequence("Alt+P"), self, lambda: (self.pane.main or main).set_preview(False))
        # 빌드 23 (사용자 11/6): 미리보기 창 어디서든 ← → = 한 장면(막대·띠·화면 같이), 스페이스 = 재생/멈춤 (GIF·동영상)
        for key, fn in (("Left", lambda: self.pane.movie is not None and self.pane._gif_step(-1)),
                        ("Right", lambda: self.pane.movie is not None and self.pane._gif_step(+1)),
                        ("Space", self._space)):
            sc = QtGui.QShortcut(QtGui.QKeySequence(key), self, fn)
            sc.setContext(Qt.WindowShortcut)

    def _space(self):
        """미리보기 창의 스페이스: GIF·동영상이면 재생/멈춤, 아니면 창 닫기 (0.9.109 빌드 4 — 스페이스로 연 창이 앞으로 와 키를 가져가서
        두 번째 스페이스로 안 닫히던 것, qe181 실패 원인)"""
        if self.pane.movie is not None:
            self.pane._gif_toggle()
        else:
            log.info("미리보기 창 스페이스 → 닫기")
            m = self.pane.main or next(iter(WINDOWS), None)
            if m is not None:
                m.set_preview(False)

    def changeEvent(self, ev):
        if ev.type() == QtCore.QEvent.ActivationChange and not self.isActiveWindow():
            self._deact = time.time()
        if ev.type() == QtCore.QEvent.WindowStateChange:
            self.pane.pause_movie(self.isMinimized())   # 최소화 = GIF 멈춤
            if not self.isMinimized():
                self.pane.schedule()   # 되살리면 지금 고른 파일로 다시
        super().changeEvent(ev)

    def was_front(self):
        return self.isVisible() and not self.isMinimized() and (self.isActiveWindow() or time.time() - self._deact < 0.6)

    def bring_front(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def contextMenuEvent(self, ev):
        m = QtWidgets.QMenu(self)
        a = m.addAction(T("항상 위에 표시"), lambda: self._toggle_top(not SETTINGS["preview_top"]))
        a.setCheckable(True)
        a.setChecked(bool(SETTINGS["preview_top"]))
        m.addAction(T("미리보기 창 닫기") + "\tAlt+P", self.close)
        m.exec(ev.globalPos())

    def _toggle_top(self, on):
        SETTINGS["preview_top"] = bool(on)
        if self.windowHandle() is not None:
            self.windowHandle().setFlag(Qt.WindowStaysOnTopHint, bool(on))
        else:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on))
        log.info("미리보기 창 항상 위 %s", on)

    def show_near(self, main):
        if not self._placed:
            self._placed = True
            ok = False
            geo = SETTINGS["preview_geo"]
            if geo:
                try:
                    ok = self.restoreGeometry(QtCore.QByteArray.fromHex(geo.encode()))
                    ok = ok and QtGui.QGuiApplication.screenAt(self.frameGeometry().center()) is not None
                except Exception:
                    ok = False
            if not ok:
                fg = main.frameGeometry()
                scr = (main.screen() or QtWidgets.QApplication.primaryScreen()).availableGeometry()
                w = max(220, int(SETTINGS["preview_w"] or 300) + 40)   # 옛 칸 너비(preview_w)는 처음 크기로만
                h = max(400, min(fg.height(), scr.height()))
                x = fg.right() + 2
                if x + w > scr.right():
                    x = max(scr.left(), scr.right() - w)
                self.setGeometry(x, max(scr.top(), fg.top()), w, h)
            log.info("미리보기 창 자리 %s (기억 %s)", self.geometry().getRect(), bool(ok))
        self.show()
        fg = self.frameGeometry()   # 제목줄까지 화면 안 (메모 창과 같게)
        scr = (QtGui.QGuiApplication.screenAt(fg.center()) or main.screen() or QtWidgets.QApplication.primaryScreen()).availableGeometry()
        x = min(max(fg.left(), scr.left()), max(scr.left(), scr.right() - fg.width()))
        y = min(max(fg.top(), scr.top()), max(scr.top(), scr.bottom() - 100))
        if (x, y) != (fg.left(), fg.top()):
            self.move(x, y)
        self.raise_()

    def save_geo(self):
        if self.isVisible() or self._placed:
            SETTINGS["preview_geo"] = bytes(self.saveGeometry().toHex()).decode()

    def closeEvent(self, ev):
        self.save_geo()
        ev.accept()
        if SETTINGS["preview_pane"]:
            m = self.pane.main if self.pane.main in WINDOWS else (WINDOWS[0] if WINDOWS else self.main)
            QtCore.QTimer.singleShot(0, lambda: m.set_preview(False))


def gear_icon(sz=18, color="#76838f"):   # 밝게·어둡게 둘 다 보이는 회색
    """설정 버튼 그림 (v0.9.104 사용자 11/5 '설정은 아이콘으로'): 톱니바퀴"""
    dpr = 2
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(dpr, dpr)
    c = sz / 2.0
    col = QtGui.QColor(color)
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    for k in range(8):   # 이 8개
        p.save()
        p.translate(c, c)
        p.rotate(k * 45)
        p.drawRoundedRect(QtCore.QRectF(-sz * 0.09, -sz * 0.48, sz * 0.18, sz * 0.22), 1, 1)
        p.restore()
    p.drawEllipse(QtCore.QPointF(c, c), sz * 0.34, sz * 0.34)
    p.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
    p.drawEllipse(QtCore.QPointF(c, c), sz * 0.14, sz * 0.14)   # 가운데 구멍
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QtGui.QIcon(pm)


class SettingsDialog(QtWidgets.QDialog):
    """설정 창 (v0.9.104 사용자 11/5: 설정은 팝업 창에 카테고리로) — 왼쪽 카테고리 · 오른쪽 내용. 바꾸면 바로 적용(메뉴와 같은 함수 호출)"""

    PAGES = ("general", "list", "nav", "vcs", "keys", "colors", "search", "backup", "about")

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(T("설정 (Settings)"))
        self.resize(1000, 700)   # v0.9.105 단축키 표가 안에 들어감
        self.setAttribute(Qt.WA_DeleteOnClose)
        outer = QtWidgets.QHBoxLayout(self)
        self.cats = QtWidgets.QListWidget()
        self.cats.setObjectName("settingsCats")
        self.cats.setFixedWidth(170)
        self.cats.setFrameShape(QtWidgets.QFrame.NoFrame)
        f = self.cats.font()
        f.setPointSizeF(f.pointSizeF() + 1)
        self.cats.setFont(f)
        self.stack = QtWidgets.QStackedWidget()
        left = QtWidgets.QVBoxLayout()   # v0.9.106 사용자 11/5: 카테고리 아래 빈 곳에 후원
        left.addWidget(self.cats)   # 높이는 항목 수만큼 (아래 _fit_cats) → 바로 밑에 후원
        if SITE_URL or DONATE_URL:
            don = QtWidgets.QPushButton(T("♥ 후원하기"))
            don.setObjectName("donateBtn")
            don.setCursor(Qt.PointingHandCursor)
            don.setStyleSheet("QPushButton#donateBtn{background:#e2446b; color:#ffffff; font-weight:bold; border:none;"
                              " border-radius:6px; padding:8px 16px;} QPushButton#donateBtn:hover{background:#c9365b;}")
            don.setFixedWidth(170)
            don.clicked.connect(lambda *_: open_link(DONATE_URL or SITE_URL + "#donate", "후원"))
            self.donate = don
            left.addSpacing(10)
            left.addWidget(don)
        left.addStretch(1)
        outer.addLayout(left)
        right = QtWidgets.QVBoxLayout()
        right.addWidget(self.stack, 1)
        row = QtWidgets.QHBoxLayout()
        note = QtWidgets.QLabel(T("바꾸면 바로 적용됩니다."))
        note.setObjectName("favLabel")
        self.note = note   # 단축키·검색 페이지는 저장·적용 버튼이 따로 있어 숨김
        row.addWidget(note, 1)
        b = QtWidgets.QPushButton(T("닫기"))
        b.clicked.connect(self.close)
        row.addWidget(b)
        right.addLayout(row)
        outer.addLayout(right, 1)
        self.checks = {}
        for key, title, build in (("general", T("일반"), self._p_general), ("list", T("파일 목록"), self._p_list),
                                  ("nav", T("탐색 창"), self._p_nav), ("vcs", T("버전 관리"), self._p_vcs),
                                  ("keys", T("단축키·마우스"), self._p_keys), ("colors", T("색상"), self._p_colors),
                                  ("search", T("검색"), self._p_search), ("backup", T("백업"), self._p_backup),
                                  ("about", T("정보"), self._p_about)):
            w = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(w)
            lay.setContentsMargins(16, 8, 8, 8)
            lay.setSpacing(8)
            h = QtWidgets.QLabel(title)
            hf = h.font()
            hf.setPointSizeF(hf.pointSizeF() + 4)
            hf.setBold(True)
            h.setFont(hf)
            lay.addWidget(h)
            if not build(lay):   # 안에 창을 넣는 페이지는 아래 여백 없이 꽉 채움
                lay.addStretch(1)
            self.stack.addWidget(w)
            it = QtWidgets.QListWidgetItem(title)
            it.setData(Qt.UserRole, key)
            it.setSizeHint(QtCore.QSize(160, 32))
            self.cats.addItem(it)
        self.cats.setFixedHeight(sum(self.cats.sizeHintForRow(i) for i in range(self.cats.count())) + 6)
        self.cats.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.cats.currentRowChanged.connect(lambda r: self.note.setVisible(self.PAGES[r] not in ("keys", "search")))
        self.cats.setCurrentRow(0)
        self._make_copyable()
        log.info("설정 창 열기")

    def _make_copyable(self):
        """설정 창 글자 복사 (0.9.120 빌드 3 사용자 11/10 '글자가 복사가 안 돼서 매번 쳐야 됨'):
        글자 칸은 마우스로 끌어 고르고 Ctrl+C, 체크·단추는 우클릭 '글자 복사'"""
        n = 0
        for lb in self.findChildren(QtWidgets.QLabel):
            if lb.text() and not lb.pixmap():
                lb.setTextInteractionFlags(lb.textInteractionFlags() | Qt.TextSelectableByMouse)
                n += 1
        for b in self.findChildren(QtWidgets.QAbstractButton):
            if b.contextMenuPolicy() == Qt.DefaultContextMenu and b.text().strip():
                b.setContextMenuPolicy(Qt.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda pos, b=b: self._copy_menu(b, pos))
        log.debug("설정 창 글자 복사 가능하게 %d칸", n)

    def _copy_menu(self, w, pos):
        m = QtWidgets.QMenu(self)
        t = w.text().replace("&&", "&").strip()
        m.addAction(T("글자 복사"), lambda: QtWidgets.QApplication.clipboard().setText(t))
        m.exec(w.mapToGlobal(pos))

    def show_page(self, key):
        if key in self.PAGES:
            self.cats.setCurrentRow(self.PAGES.index(key))

    # ---- 부품
    def _check(self, lay, key, label, get, toggle, tip=""):
        cb = QtWidgets.QCheckBox(label)
        cb.setChecked(bool(get()))
        if tip:
            cb.setToolTip(tip)

        def flip(*_):
            if bool(get()) != cb.isChecked():
                toggle()
            cb.setChecked(bool(get()))
            log.info("설정 창: %s = %s", key, bool(get()))
        cb.clicked.connect(flip)
        self.checks[key] = cb
        lay.addWidget(cb)
        return cb

    def _opt(self, lay, key, label, tip=""):
        return self._check(lay, key, label, lambda: OPTS[key], lambda: self.main.toggle_opt(key), tip)

    def _set(self, lay, key, label, tip=""):
        return self._check(lay, key, label, lambda: SETTINGS[key], lambda: self.main.toggle_setting(key), tip)

    def _btn(self, lay, label, fn, desc=""):
        if desc:
            d = QtWidgets.QLabel(desc)
            d.setWordWrap(True)
            lay.addWidget(d)
        b = QtWidgets.QPushButton(label)
        b.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        b.clicked.connect(lambda *_: fn())
        lay.addWidget(b)
        return b

    def _embed(self, lay, make):
        """기존 설정 창(단축키·색상·검색 범위)을 따로 띄우지 않고 이 페이지 안에 (v0.9.105 사용자 11/5).
        저장·적용·취소로 끝나면 같은 자리에 새로 만들어 지금 값으로 다시 보여 줌"""
        box = QtWidgets.QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(box, 1)
        self.embedded = getattr(self, "embedded", {})

        def build():
            dlg, done = make()
            dlg.setWindowFlags(Qt.Widget)
            box.addWidget(dlg)
            self.embedded[make.__name__] = dlg

            def fin(r):
                if done:
                    done(r)
                box.removeWidget(dlg)
                dlg.deleteLater()
                QtCore.QTimer.singleShot(0, build)
            dlg.finished.connect(fin)
            dlg.show()
        build()
        return True

    def _sub(self, lay, text):
        l = QtWidgets.QLabel(text)
        l.setObjectName("favLabel")
        lay.addSpacing(6)
        lay.addWidget(l)

    # ---- 페이지
    def _p_general(self, lay):
        m = self.main
        form = QtWidgets.QFormLayout()
        self.lang = QtWidgets.QComboBox()
        self.lang.addItem(T("윈도우 언어 따름") + f"  ({dict(i18n.LANGS).get(i18n.windows_lang(), 'English')})", None)
        for code, name in i18n.LANGS:
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(SETTINGS["lang"])))
        self.lang.currentIndexChanged.connect(lambda i: m.set_language(self.lang.itemData(i)))
        form.addRow(T("언어 (Language)"), self.lang)
        self.theme = QtWidgets.QComboBox()
        for mode, label in (("system", T("시스템 설정 따름")), ("light", T("밝게 (Light)")), ("dark", T("어둡게 (Dark)"))):
            self.theme.addItem(label, mode)
        self.theme.setCurrentIndex(max(0, self.theme.findData(SETTINGS["theme_mode"])))
        self.theme.currentIndexChanged.connect(lambda i: (m.set_theme_mode(self.theme.itemData(i)), self.setStyleSheet(m.styleSheet())))
        form.addRow(T("화면 테마"), self.theme)
        lay.addLayout(form)
        self._sub(lay, T("창"))
        self._check(lay, "allow_multi", T("창 여러 개 열기 허용"), lambda: SETTINGS["allow_multi"], m.toggle_multi,
                    T("끄면 4Dir 는 하나만 실행되고, 다시 실행하면 기존 창이 앞으로 나옵니다"))
        self._check(lay, "resume_after_reboot", T("재부팅 후 다시 열기 (켜 둔 채 윈도우를 끄면 다음 로그인 때)"),
                    lambda: SETTINGS["resume_after_reboot"], lambda: SETTINGS.__setitem__("resume_after_reboot", not SETTINGS["resume_after_reboot"]))
        self._set(lay, "hide_single_tab", T("탭이 하나면 탭 줄 숨기기 (새 탭: Ctrl+T)"))
        self._set(lay, "tab_multirow", T("탭이 넘치면 여러 줄로"), T("끄면 한 줄 + 좌우 화살표"))
        self._set(lay, "keep_favbar", T("메뉴줄을 접어도 즐겨찾기 줄은 보이기"))
        self._set(lay, "folder_view_memory", T("폴더마다 보기 기억 — 그 폴더에서 바꾼 보기 방식·정렬을 다음에도 그대로"))
        self._set(lay, "show_favbar", T("즐겨찾기 줄 보이기"), T("끄면 즐겨찾기 줄이 통째로 사라집니다. 다시 켜려면: 보기 → 즐겨찾기 줄 보이기"))
        self._check(lay, "private_mode", T("기록 안 남기기 — 열었던 폴더·탭을 저장하지 않고, 켤 때마다 처음 폴더로"),
                    lambda: SETTINGS["private_mode"], m.toggle_private,
                    T("켜면 지금까지 저장된 창 상태와 자동 기록도 지웁니다. 즐겨찾기·메모·설정은 그대로입니다"))
        self._sub(lay, T("도움말"))
        self._set(lay, "tooltips", T("풍선 도움말(툴팁) 보이기 — 단추에 마우스를 올리면 설명"))
        self._sub(lay, T("윈도우"))   # 0.9.109
        # 0.9.120 빌드 2 (사용자 11/10): 두 방식 칸을 다 보여 주고, 이 윈도우에 안 맞는 칸은 흐리게(눌러 볼 수는 있음 — 시험용).
        # 맨 위 체크 = 켜면 이 윈도우에 맞는 방식, 끄면 둘 다 끊음
        self.win_info = QtWidgets.QLabel()
        self.win_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.win_info)
        self._check(lay, "win_e", T("Win+E 를 누르면 탐색기 대신 4Dir 열기"), m.winE_on, lambda: (m.toggle_winE(), self._pt_state()),
                    T("켜면 이 윈도우에 맞는 방식으로 연결, 끄면 두 방식 모두 끊습니다 — 이 사용자 계정에만 적용"))

        def section(title):
            box = QtWidgets.QFrame()
            box.setObjectName("winEBox")
            box.setStyleSheet("#winEBox{border:1px solid rgba(128,128,128,90); border-radius:6px;}")
            bl = QtWidgets.QVBoxLayout(box)
            bl.setContentsMargins(10, 8, 10, 8)
            hr = QtWidgets.QHBoxLayout()
            t = QtWidgets.QLabel(title)
            f = t.font()
            f.setBold(True)
            t.setFont(f)
            hr.addWidget(t)
            tag = QtWidgets.QLabel()
            hr.addWidget(tag)
            hr.addStretch(1)
            bl.addLayout(hr)
            lay.addWidget(box)
            return box, bl, tag

        # ---- 기본 방식 (24H2 이하)
        self.reg_box, rl, self.reg_tag = section(T("기본 방식 — 윈도우 11 24H2 이하"))
        d = QtWidgets.QLabel(T("윈도우 설정(레지스트리)에 'Win+E = 4Dir' 를 적어 둡니다. 따로 설치할 것이 없습니다."))
        d.setWordWrap(True)
        rl.addWidget(d)
        r = QtWidgets.QHBoxLayout()
        self.reg_st = QtWidgets.QLabel()
        r.addWidget(self.reg_st, 1)
        self.reg_btn = QtWidgets.QPushButton()
        self.reg_btn.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.reg_btn.clicked.connect(lambda *_: (m.reg_toggle(), self._pt_state()))
        r.addWidget(self.reg_btn)
        rl.addLayout(r)

        # ---- PowerToys 방식 (26H2 이상)
        self.pt_box, bl, self.pt_tag = section(T("PowerToys 방식 — 윈도우 11 26H2 이상"))
        why = QtWidgets.QLabel(T("윈도우 11 26H2 부터는 윈도우가 Win+E 를 다른 프로그램에 넘기는 기본 방식을 막습니다. "
                                 "그래서 마이크로소프트의 무료 도구 PowerToys 의 '키보드 관리자'가 Win+E 를 받아 4Dir 를 엽니다."))
        why.setWordWrap(True)
        bl.addWidget(why)
        self.pt_rows = {}
        for key, label in (("inst", T("PowerToys 설치")), ("kbm", T("키보드 관리자(Keyboard Manager) 켜기")), ("link", T("Win+E → 4Dir 연결"))):
            r = QtWidgets.QHBoxLayout()
            st = QtWidgets.QLabel()
            r.addWidget(st, 1)
            b = QtWidgets.QPushButton()
            b.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            r.addWidget(b)
            bl.addLayout(r)
            self.pt_rows[key] = (st, b, label)
        self.pt_rows["inst"][1].setText(T("PowerToys 받기"))
        self.pt_rows["inst"][1].clicked.connect(lambda *_: QtGui.QDesktopServices.openUrl(QtCore.QUrl(ptlink.STORE_URL)))
        self.pt_rows["kbm"][1].setText(T("키보드 관리자 켜러 가기"))
        self.pt_rows["kbm"][1].setToolTip(T("PowerToys 설정의 Keyboard Manager 화면을 엽니다 — 'Keyboard Manager 켜기'를 켜 주세요"))
        self.pt_rows["kbm"][1].clicked.connect(lambda *_: (ptlink.open_kbm_settings(), QtCore.QTimer.singleShot(4000, self._pt_state)))
        self.pt_rows["link"][1].setToolTip(T("PowerToys 키보드 관리자에 'Win+E → 4Dir 새 창'을 넣습니다 (원래 설정은 보관). 넣는 값은 이 PC 의 4Dir 위치로 정해집니다"))
        self.pt_rows["link"][1].clicked.connect(lambda *_: (m.pt_toggle(), self._pt_state()))
        gb = QtWidgets.QHBoxLayout()
        g = QtWidgets.QPushButton("🖼 " + T("그림 안내 (손으로 설정하는 법)"))
        g.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        g.clicked.connect(lambda *_: (m.open_pt_guide(self), self._pt_state()))
        gb.addWidget(g)
        rf = QtWidgets.QPushButton(T("상태 다시 보기"))
        rf.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        rf.clicked.connect(lambda *_: self._pt_state())
        gb.addWidget(rf)
        gb.addStretch(1)
        bl.addLayout(gb)
        self._pt_state()

    def _pt_state(self):
        """윈도우 버전 · 두 방식 칸 상태 — 이 윈도우에 맞는 칸은 진하게(✔ 이 PC), 안 맞는 칸은 흐리게(그래도 눌러 볼 수 있음)"""
        txt, build = ptlink.windows_info()
        use_pt = self.main.winE_method() == "pt"
        self.win_info.setText(T("현재 윈도우: {0}").format(txt))
        if "win_e" in self.checks:
            self.checks["win_e"].setChecked(self.main.winE_on())
        for box, tag, fit in ((self.reg_box, self.reg_tag, not use_pt), (self.pt_box, self.pt_tag, use_pt)):
            # 빌드 3 사용자: 흐리게·'필요 없음' 빼고, 안 맞는 칸엔 언제 쓰는지만
            if fit:
                tag.setText("✔ " + T("이 PC 에 맞는 방식"))
                tag.setStyleSheet("color:#1e8e3e; font-weight:bold;")
            else:
                tag.setText(T("— 기본 방식이 안 되면 이 방법을 쓰세요") if box is self.pt_box else "")   # 기본 칸은 제목에 이미 '24H2 이하
                tag.setStyleSheet("")
        on = winhook.ours()
        self.reg_st.setText(("✅ " + T("연결됨 — Win+E 를 누르면 4Dir 새 창")) if on else ("⬜ " + T("연결 안 됨")))
        self.reg_btn.setText(T("끊기") if on else T("연결"))
        inst = ptlink.exe_path() is not None
        kbm = ptlink.kbm_enabled() if inst else None
        lk = inst and ptlink.linked()
        states = {"inst": inst, "kbm": inst and kbm is not False, "link": lk}
        for key, (st, b, label) in self.pt_rows.items():
            ok = states[key]
            st.setText(("✅ " if ok else "⬜ ") + label)
            if key == "link":
                b.setText(T("끊기") if ok else "⚡ " + T("지금 연결"))
                b.setVisible(inst)
            else:
                b.setVisible(not ok and (key == "inst" or inst))
        if lk and not ptlink.running():
            self.pt_rows["link"][0].setText(self.pt_rows["link"][0].text() + "  ·  ⚠ " + T("PowerToys 를 실행해야 동작합니다"))

    def _p_list(self, lay):
        self._sub(lay, T("표시"))
        self._opt(lay, "show_ext", T("파일 확장명"))
        self._set(lay, "rename_hide_ext", T("이름 바꾸기(F2) 때 확장명 숨기기 — 이름만 고치고 확장명은 그대로"))
        self._opt(lay, "show_hidden", T("숨긴 항목"))
        self._opt(lay, "checkboxes", T("항목 확인란"))
        self._opt(lay, "thumbnails", T("그림 미리보기 (아이콘 보기)"))
        self._check(lay, "breadcrumb", T("경로를 버튼으로 (브레드크럼)"), lambda: SETTINGS["breadcrumb"], self.main.toggle_breadcrumb)
        self._sub(lay, T("정렬·묶기"))
        self._opt(lay, "date_folders_first", T("날짜 정렬 때 폴더를 위로 모으기"))
        self._opt(lay, "date_groups", T("날짜별로 묶기 (오늘·어제·이번 주…)"))
        self._opt(lay, "type_groups", T("형식별로 묶기 (폴더·JPG·PNG…)"), T("날짜별 묶기와 둘 중 하나만 — 자세히 보기에서"))
        self._sub(lay, T("형식·그림"))
        self._opt(lay, "type_chips", T("형식 단추 줄 ([전체][JPG][PSD]…)"), T("목록 위 단추를 누르면 그 형식만 보임 (Ctrl+누르기 = 여러 개)"))
        self._opt(lay, "chips_global", T("  형식 단추를 맨 위 한 줄로 — 모든 칸에 같이 적용"), T("끄면 칸마다 따로 단추 줄"))
        self._opt(lay, "chip_counts", T("  형식 단추에 개수 표시"))
        self._opt(lay, "type_badges", T("그림 미리보기에 형식 딱지 (PSD·PNG·GIF…)"), T("보통 아이콘 이상에서"))
        self._opt(lay, "folder_covers", T("폴더 표지 — 폴더 안 첫 그림을 겹쳐 보기"), T("아이콘 보기에서, 네트워크 드라이브 제외"))
        self._sub(lay, T("동작"))
        self._set(lay, "folder_size", T("폴더 크기 계산 (크기 칸 — 네트워크 드라이브 제외)"))
        self._set(lay, "empty_click_up", T("빈 곳을 더블클릭하면 상위 폴더로"))
        self._set(lay, "arc_browse", T("압축 파일(ZIP·7Z·RAR…)을 두 번 누르면 4Dir 안에서 폴더처럼 열기"))   # 빌드 20

    def _p_nav(self, lay):
        m = self.main
        g = QtWidgets.QButtonGroup(self)
        self.nav_radio = {}
        for on, lbl in ((False, T("칸마다 (각 칸 왼쪽, ☰ 버튼)")), (True, T("공용 (창 왼쪽 하나, 고른 칸으로 열림)"))):
            r = QtWidgets.QRadioButton(lbl)
            r.setChecked(bool(SETTINGS["side_shared"]) == on)
            r.toggled.connect(lambda c, on=on: c and (m.set_shared_side(on), self._nav_sync()))
            g.addButton(r)
            lay.addWidget(r)
            self.nav_radio[on] = r
        self.nav_vis = self._check(lay, "side_shared_visible", T("공용 탐색 창 보이기"),
                                   lambda: SETTINGS["side_shared"] and not SETTINGS["side_shared_hidden"], m.toggle_shared_visible)
        self._nav_sync()
        # 0.9.122 받은 의견: 탐색 창 즐겨찾기 — 4Dir / Windows / 둘 다
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(T("탐색 창 즐겨찾기")))
        cb = QtWidgets.QComboBox()
        self.side_favs = cb
        for key, lbl in (("both", T("둘 다 (4Dir 위 · Windows 아래)")), ("4dir", T("4Dir 즐겨찾기만")), ("windows", T("Windows 즐겨찾기만"))):
            cb.addItem(lbl, key)
        cb.setCurrentIndex(max(0, cb.findData(SETTINGS["side_favs"])))
        cb.currentIndexChanged.connect(lambda *_: set_side_favs(cb.currentData()))
        row.addWidget(cb)
        row.addStretch(1)
        lay.addLayout(row)

    def _nav_sync(self):
        self.nav_vis.setEnabled(bool(SETTINGS["side_shared"]))
        self.nav_vis.setChecked(bool(SETTINGS["side_shared"]) and not SETTINGS["side_shared_hidden"])

    def _p_vcs(self, lay):
        self._opt(lay, "svn_status", T("SVN 상태 표시"))
        self._opt(lay, "vcs_overlay", T("버전 관리 표시 — Git·Perforce 등 (윈도우 겹침 아이콘)"))
        lay.addSpacing(8)
        self._btn(lay, T("겹침 아이콘 순서 정리 (윈도우)…"), self.main.open_overlay_order,
                  T("윈도우 겹침 아이콘(OneDrive·SVN 등)이 많아 일부가 안 보일 때 순서를 정리합니다."))

    def _p_keys(self, lay):
        return self._embed(lay, self.main.keys_panel)

    def _p_colors(self, lay):
        return self._embed(lay, self.main.colors_panel)

    def _p_search(self, lay):
        return self._embed(lay, self.main.search_panel)

    def _p_backup(self, lay):
        self._gdrive_box(lay)   # 0.9.114 구글 드라이브 (선택)
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        lay.addWidget(sep)
        self._btn(lay, T("설정 내보내기 (백업 파일로 저장)…"), self.main.export_settings,
                  T("보기·단축키·즐겨찾기·창과 탭(탭 색 포함)·색 라벨·저장한 창 구성을 zip 하나로 저장합니다. 포맷 뒤 되돌리기용."))
        self._btn(lay, T("설정 가져오기 (백업 파일에서 되돌리기)…"), self.main.import_settings)

    def _gdrive_box(self, lay):
        """구글 드라이브 백업 (0.9.114, 선택 사항 — 사용자 11/6 '필수 아님 표시, 포맷하면 메모 등이 날아간다 정도로')"""
        g = QtWidgets.QGroupBox(T("구글 드라이브 자동 백업 (선택)"))
        gl = QtWidgets.QVBoxLayout(g)
        info = QtWidgets.QLabel(T("로그인하지 않아도 4Dir 는 모두 그대로 쓸 수 있습니다. 다만 설정·메모·즐겨찾기·태그는 이 PC 에만 있어서, "
                                  "윈도우를 포맷하거나 PC 를 바꾸면 사라집니다. 구글로 로그인하면 내 구글 드라이브의 4Dir 전용 숨은 공간에 "
                                  "하루 한 번 백업해 두고, 새 PC 에서 그대로 되살릴 수 있습니다. (개발자에게는 아무것도 전송되지 않습니다)"))
        info.setWordWrap(True)
        gl.addWidget(info)
        self.gd_state = QtWidgets.QLabel()
        self.gd_state.setOpenExternalLinks(True)   # 0.9.116 준비 안 된 판: 홈페이지 링크
        self.gd_state.setWordWrap(True)
        gl.addWidget(self.gd_state)
        row = QtWidgets.QHBoxLayout()
        self.gd_login = QtWidgets.QPushButton(T("구글로 로그인…"))
        self.gd_logout = QtWidgets.QPushButton(T("연결 끊기"))
        self.gd_now = QtWidgets.QPushButton(T("지금 백업"))
        self.gd_restore = QtWidgets.QPushButton(T("구글 드라이브에서 되살리기…"))
        for b, fn in ((self.gd_login, self.main.gdrive_login), (self.gd_logout, self.main.gdrive_logout),
                      (self.gd_now, lambda: self.main.gdrive_backup(manual=True)), (self.gd_restore, self.main.gdrive_restore)):
            b.clicked.connect(lambda *_, fn=fn: fn())
            row.addWidget(b)
        row.addStretch(1)
        gl.addLayout(row)
        self.gd_auto = QtWidgets.QCheckBox(T("하루 한 번 자동 백업 (최근 10개 보관)"))
        self.gd_auto.setChecked(bool(SETTINGS["gdrive_auto"]))
        self.gd_auto.toggled.connect(lambda on: (SETTINGS.__setitem__("gdrive_auto", on), log.info("구글 드라이브 자동 백업 %s", on)))
        gl.addWidget(self.gd_auto)
        lay.addWidget(g)
        self.main.gdrive_changed.connect(self._gdrive_refresh)
        self._gdrive_refresh()

    def _gdrive_refresh(self, *_):
        try:
            ready = gdrive.client(BIN_DIR) is not None
            mail = gdrive.account() if ready else ""
            busy = bool(getattr(self.main, "_gd_busy", None))
        except RuntimeError:
            return
        if not ready:   # 0.9.116 (사용자 11/7): 소스로 받은 판 등 → 공식 배포판을 받으라고 안내
            st = T("구글 백업은 홈페이지에서 받은 4Dir 에서 쓸 수 있습니다.") + f' <a href="{SITE_URL}">{SITE_URL.rstrip("/")}</a>'
        elif not mail and not gdrive._cred_read():
            st = T("연결 안 됨")
        else:
            last = SETTINGS["gdrive_last"]
            st = T("연결됨: {0}").format(mail or "?") + "   ·   " + (
                T("마지막 백업: {0}").format(time.strftime("%Y-%m-%d %H:%M", time.localtime(last))) if last else T("아직 백업 없음"))
        if busy:
            st += "   ·   " + str(self.main._gd_busy)
        self.gd_state.setText(st)
        on = ready and bool(gdrive._cred_read())
        self.gd_login.setVisible(ready and not on)
        for b in (self.gd_logout, self.gd_now, self.gd_restore, self.gd_auto):
            b.setVisible(on)
        for b in (self.gd_login, self.gd_logout, self.gd_now, self.gd_restore):
            b.setEnabled(not busy)

    def _p_about(self, lay):
        m = self.main
        v = QtWidgets.QLabel(f"4Dir v{QE_VERSION}  " + T("(빌드 {0})").format(QE_BUILD))
        vf = v.font()
        vf.setPointSizeF(vf.pointSizeF() + 2)
        v.setFont(vf)
        lay.addWidget(v)
        wv = QtWidgets.QLabel(T("윈도우: {0}").format(ptlink.windows_info()[0]))   # 0.9.120 사용자: 윈도우 버전을 4Dir 에서 바로
        wv.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(wv)
        # 후원 버튼은 v0.9.106 부터 왼쪽 카테고리 아래 (모든 페이지에서 보임)
        if SITE_URL:   # 홈페이지 - 4dir.net (링크)
            host = SITE_URL.split("//", 1)[-1].strip("/")
            hp = QtWidgets.QLabel(T("홈페이지") + f' - <a href="{SITE_URL}">{host}</a>')
            hp.setObjectName("homeLink")
            hp.setTextFormat(Qt.RichText)
            hp.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
            hp.linkActivated.connect(lambda *_: open_link(SITE_URL, "홈페이지"))
            lay.addWidget(hp)
        lay.addSpacing(6)
        self._btn(lay, T("새 버전 확인"), lambda: start_update_check(m, manual=True))
        self._check(lay, "update_check", T("시작할 때 새 버전 확인 (하루 한 번)"), lambda: SETTINGS["update_check"],
                    lambda: SETTINGS.__setitem__("update_check", not SETTINGS["update_check"]))
        self._sub(lay, T("도움말"))
        self._btn(lay, T("사용법…"), m.open_guide)
        self._sub(lay, T("문제가 있을 때"))
        self._btn(lay, T("로그 폴더 열기"), lambda: os.startfile(LOG_DIR))
        self._btn(lay, T("문제 보고용 로그 저장… (4Dir 폴더의 reports 에 zip)"), m.save_report)


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
        self.sep = QtWidgets.QFrame()   # 0.9.117 빌드 2: 미리보기와 정보 사이 가는 선
        self.sep.setFrameShape(QtWidgets.QFrame.HLine)
        self.sep.setFrameShadow(QtWidgets.QFrame.Plain)
        self.sep.setStyleSheet("QFrame{color:palette(midlight);}")
        self.name = QtWidgets.QLabel()
        self.name.setWordWrap(True)
        self.name.setTextFormat(Qt.PlainText)
        self.name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.name.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        f = self.name.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 1.5)
        self.name.setFont(f)
        self.info = QtWidgets.QLabel()   # 0.9.117 빌드 2: '이름표 | 값' 표 (사용자: 정신없으니 가독성 좋게)
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        self.info.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._rows = []
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.pic, 1)
        self.gifbar = self._build_gifbar()   # 빌드 17: GIF 장면 조작 (galleryV8 참고)
        lay.addWidget(self.gifbar)
        self.extra = None   # 0.9.116 형식별 미리보기 (코드·글꼴·소리·PSD 레이어·엑셀) — 고를 때마다 새로 만들고 버림
        self.extra_lay = QtWidgets.QVBoxLayout()
        self.extra_lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.extra_lay, 0)
        lay.addWidget(self.sep)
        lay.addWidget(self.name)
        lay.addWidget(self.info)
        self.btn_inspect = QtWidgets.QPushButton(T("🔍 그림 자세히 보기 (확대·스포이트)"))   # 0.9.116 #1 #2
        self.btn_inspect.setVisible(False)
        self.btn_inspect.clicked.connect(self._open_inspect)
        lay.addWidget(self.btn_inspect, 0, Qt.AlignHCenter)
        self.btn_seq = QtWidgets.QPushButton(T("▶ 연번 그림 재생"))   # 0.9.116 #3
        self.btn_seq.setVisible(False)
        self.btn_seq.clicked.connect(lambda: self.cur and open_tool(sequence.open_player, self.window(), os.path.dirname(self.cur[0]), self.cur[0]))
        lay.addWidget(self.btn_seq, 0, Qt.AlignHCenter)
        lay.addStretch(0)
        self.cur = None      # (경로, mtime) — 지금 보여주는 그림 파일
        self.src = None      # 지금 그림 (QPixmap, 창 크기 바뀌면 다시 맞춤)
        self.movie = None    # 움직이는 GIF 재생 (v0.9.64, 사용자 요청) — 고른 파일이 바뀌거나 창이 숨으면 멈추고 버림
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.refresh)

    def schedule(self, main=None):
        try:   # 0.9.118 빌드 3: 누가 다시 그리라고 했는지 (반복될 때 로그에 남김)
            import traceback as _tb
            self._last_callers = (getattr(self, "_last_callers", [])
                                  + [" <- ".join(f"{f.name}:{f.lineno}" for f in _tb.extract_stack(limit=6)[:-1])])[-4:]
        except Exception:
            pass
        if main is not None and main in WINDOWS + [self.main]:
            self.main = main   # 빌드 18: 마지막으로 쓴 4Dir 창의 고른 파일을 보여 줌
        if self.isVisible() and not self.window().isMinimized():   # 빌드 18: 최소화한 미리보기 창은 안 그림 (되살리면 다시)
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
        self._drop_extra()   # 0.9.116 숨으면 소리 재생 등도 멈춤

    # 0.9.116: 형식별 미리보기 모듈 (can_handle(path) · make_widget(path, parent)). 처음 쓸 때 불러옴 (시작 속도 그대로)
    EXTRA_MODS = ("folderprev", "pdfprev", "psdlayers", "fontprev", "audioprev", "xlsxprev", "codeview", "imginspect")   # 0.9.121 PDF 직접 그림   # 0.9.117 폴더 = 안 그림·개수·크기   # 빌드 4: 그림도 창 안에서 확대·스포이트
    KEEP_PIC = ("psdlayers",)   # 그림(윈도우 미리보기)은 그대로 두고 아래에 붙임

    def _drop_extra(self):
        w, self.extra = self.extra, None
        self._extra_key = None
        if w is not None:
            if hasattr(w, "stop"):   # 폴더 세기 등 뒤 작업 멈춤
                w.stop()
            self.extra_lay.removeWidget(w)
            w.hide()
            w.deleteLater()
        lay = self.layout()
        lay.setStretchFactor(self.pic, 1)
        lay.setStretchFactor(self.extra_lay, 0)
        self.pic.setVisible(True)

    def _try_extra(self, path):
        """형식별 미리보기가 맡으면 위젯을 붙이고 True"""
        import importlib
        for name in self.EXTRA_MODS:
            if name == "imginspect" and not OPTS["thumbnails"]:
                continue
            try:
                mod = importlib.import_module(name)
            except ImportError:
                continue
            try:
                if not mod.can_handle(path):
                    continue
                t0 = time.time()
                if name == "imginspect":
                    pv = self.main.pane().view() if self.main.pane() else None
                    sq = (lambda p=path: open_tool(sequence.open_player, self.window(), os.path.dirname(p), p)) \
                        if pv is not None and seq_in_view(pv, path) is not None else None
                    w = mod.make_widget(path, self, nav=self._nav_image, seq=sq,
                                        edit=(lambda p: open_img_edit(p, self.window())) if imgedit.can_edit(path) else None)
                    self.btn_seq.setVisible(False)   # 0.9.118 빌드 2: 연번 재생은 색상 도구 칸 안으로
                elif name == "folderprev":
                    w = mod.make_widget(path, self, thumb=thumbs_service() if OPTS["thumbnails"] else None, open_cb=self._open_from_folder,
                                        icon_for=lambda n, d: shellops.icon_for(n, d, 16), info_cb=self._folder_count)
                else:
                    w = mod.make_widget(path, self)
            except Exception:
                log.exception("미리보기 %s 실패 %s", name, path)
                continue
            if w is None:
                continue
            log.info("미리보기 %s %s (%.0fms)", name, os.path.basename(path), (time.time() - t0) * 1000)
            self.extra = w
            self.extra_lay.addWidget(w)
            keep = name in self.KEEP_PIC
            self.pic.setVisible(keep)
            lay = self.layout()
            lay.setStretchFactor(self.pic, 1 if keep else 0)
            lay.setStretchFactor(self.extra_lay, 2 if keep else 1)
            return keep or True
        return False

    def _set_rows(self, rows):
        """정보 표: [(이름표, 값)] → 왼쪽 회색 이름표 · 오른쪽 값 (빈 값 줄은 뺌)"""
        import html as _h
        self._rows = [(k, v) for k, v in rows if v]
        pal = self.palette()   # 이름표 = 글자색과 바탕색의 중간 (밝은·어두운 테마 둘 다)
        t, bg = pal.color(QtGui.QPalette.WindowText), pal.color(QtGui.QPalette.Window)
        dim = QtGui.QColor((t.red() + bg.red()) // 2, (t.green() + bg.green()) // 2, (t.blue() + bg.blue()) // 2).name()
        trs = "".join(f'<tr><td style="color:{dim}; padding:1px 12px 1px 0; white-space:nowrap;">{_h.escape(k)}</td>'
                      f'<td style="padding:1px 0;">{_h.escape(v)}</td></tr>' for k, v in self._rows)
        self.info.setText(f'<table cellspacing="0" cellpadding="0">{trs}</table>' if trs else "")

    def _set_row(self, key, val):
        rows = list(self._rows)
        for i, (k, _v) in enumerate(rows):
            if k == key:
                rows[i] = (k, val)
                break
        else:
            rows.append((key, val))
        self._set_rows(rows)

    def _folder_count(self, files, dirs, size, state):
        """폴더 미리보기가 센 결과 → 표의 '내용'·'전체 크기' 줄"""
        tail = "" if state == 1 else ("  " + (T("(세는 중…)") if state == 0 else T("(너무 많아 여기까지만 셈)")))
        self._set_row(T("내용"), T("파일 {0}개 · 폴더 {1}개").format(f"{files:,}", f"{dirs:,}") + tail)
        self._set_row(T("전체 크기"), size_short(size) if size_short else str(size))

    def _open_from_folder(self, p):
        """폴더 미리보기에서 두 번 누름 (0.9.117): 폴더면 지금 칸에서 열고, 파일이면 기본 프로그램으로"""
        if os.path.isdir(p):
            pane = self.main.pane()
            if pane and pane.view():
                pane.view().navigate(p)
            return
        try:
            os.startfile(p)
        except OSError as ex:
            log.warning("폴더 미리보기 파일 열기 실패 %s: %s", p, ex)

    def _nav_image(self, d):
        """미리보기 그림 이전/다음 (빌드 5): 지금 칸 목록에서 그림 파일끼리 d 칸 옮겨 선택. 반환 (순번, 전체) — d=0 이면 옮기지 않음"""
        pane = self.main.pane()
        v = pane.view() if pane else None
        if v is None:
            return None
        sel = v.selected_rows()
        if len(sel) != 1:
            return None
        rows = v.model_.rows
        imgs = [i for i, e in enumerate(rows) if not e[1] and imginspect.can_open(e[0])]
        if sel[0] not in imgs:
            return None
        k = imgs.index(sel[0])
        if d:
            j = min(max(k + d, 0), len(imgs) - 1)
            if j != k:
                idx = v.model_.index(imgs[j], 0)
                v.sel.setCurrentIndex(idx, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
                v.view().scrollTo(idx)
                k = j
        return k, len(imgs)

    def _open_inspect(self):
        if self.cur:
            open_tool(imginspect.open_viewer, self.window(), self.cur[0])

    GIF_MAX = 64 * 1048576   # 이보다 큰 GIF 는 움직임 없이 첫 장만 (메모리·CPU)
    GIF_SEEK_MAX = 24 * 1048576   # (파일 크기) 이 크기까지는 모든 장면을 기억
    GIF_CACHE_MAX = 400 * 1048576  # 0.9.118: 또는 풀어 놓은 장면 전체(장면 수 x 가로 x 세로 x 4)가 이만큼까지면 기억. 넘으면 '차례로 풀어 이동'(느린 이동)
    # 빌드 17: 윈도우 미리보기(썸네일 처리기)가 있는 문서·영상은 첫 장면/첫 쪽을 크게 (LibreOffice 없이 — 윈도우·오피스가 주는 것)
    DOC_PREVIEW = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".hwp", ".hwpx", ".mp4", ".mov", ".avi", ".mkv",
                   ".wmv", ".webm", ".m4v", ".fbx", ".obj", ".3mf", ".stl", ".glb", ".svg", ".heic", ".avif", ".raw", ".cr2", ".nef"}

    def _build_gifbar(self):
        """GIF 장면 조작줄: ⏮ ◀ ⏯ ▶ · 장면 막대 · 5/55 · 60ms · 이 장면 PNG 저장"""
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(2)

        def b(text, tip, fn):
            x = QtWidgets.QToolButton()
            x.setText(text)
            x.setToolTip(tip)
            x.setAutoRaise(True)
            x.clicked.connect(fn)
            row.addWidget(x)
            return x
        # 빌드 18 (사용자 11/5 참고 그림): |◀ 이전 · ▶/⏸ 재생 · ■ 정지 · ▶| 다음 — 글자 대신 직접 그린 아이콘 (비슷한 글자가 겹쳐 보이지 않게)
        self.gif_btns = {}
        for kind, tip, fn in (("prev", T("이전 장면 (멈춤)"), lambda: self._gif_step(-1)),
                              ("play", T("재생 / 멈춤"), self._gif_toggle),
                              ("stop", T("정지 (첫 장면)"), self._gif_stop),
                              ("next", T("다음 장면 (멈춤)"), lambda: self._gif_step(+1))):
            x = b("", tip, fn)
            x.setIcon(gif_icon(kind, self._gif_fg()))
            x.setIconSize(QtCore.QSize(20, 20))
            self.gif_btns[kind] = x
        self.gif_play = self.gif_btns["play"]
        self.gif_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.gif_slider.setToolTip(T("장면 고르기 (끌면 그 장면에서 멈춤)"))
        self.gif_slider.valueChanged.connect(lambda n: self._gif_seek(n))   # 빌드 22: 끌기뿐 아니라 누르기·화살표 키도 (_gif_ui 가 고칠 땐 신호 막음)
        self.gif_slider.installEventFilter(self)   # 빌드 22: 막대 아무 데나 누르면 그 자리로 (기본은 한 칸씩만)
        row.addWidget(self.gif_slider, 1)
        ap = b("", T("자동 재생 — 켜면 GIF·동영상을 고르자마자 재생, 끄면 첫 장면에서 멈춘 채"), self._toggle_autoplay)   # 빌드 28 (사용자 11/6 '유저가 선택')
        ap.setIcon(gif_icon("autoplay", self._gif_fg()))
        ap.setIconSize(QtCore.QSize(20, 20))
        ap.setCheckable(True)
        ap.setChecked(bool(SETTINGS["preview_autoplay"]))
        self.gif_btns["autoplay"] = ap
        snd = b("", T("소리 켜기/끄기"), self._toggle_sound)   # 빌드 24 동영상만 보임
        snd.setIconSize(QtCore.QSize(20, 20))
        snd.setVisible(False)
        self.gif_btns["sound"] = snd
        sv = b("", T("지금 장면을 PNG 로 저장"), self._gif_save)
        sv.setIcon(gif_icon("save", self._gif_fg()))
        sv.setIconSize(QtCore.QSize(20, 20))
        self.gif_btns["save"] = sv
        ed = b("", T("편집 — 구간 자르기·화면 자르기·크기·속도·GIF 만들기"), self._open_edit)   # 0.9.111
        ed.setIcon(gif_icon("edit", self._gif_fg()))
        ed.setIconSize(QtCore.QSize(20, 20))
        self.gif_btns["edit"] = ed
        v.addLayout(row)
        self.gif_warn = QtWidgets.QLabel(T("용량이 큰 GIF 라 장면을 옮길 때 잠깐 멈출 수 있습니다"))
        self.gif_warn.setToolTip(T("메모리를 아끼려고 처음부터 차례로 풀어서 찾아갑니다"))
        self.gif_warn.setStyleSheet("QLabel{color:#d32f2f; font-weight:bold;}")   # 0.9.118 빌드 6 (사용자: 렉 생긴다고 빨간 글씨로)
        self.gif_warn.setVisible(False)
        v.addWidget(self.gif_warn)
        self.gif_lbl = QtWidgets.QLabel()
        self.gif_lbl.setAlignment(Qt.AlignHCenter)
        v.addWidget(self.gif_lbl)
        self.gif_strip = QtWidgets.QListWidget()   # 장면 띠 (작은 그림, 누르면 그 장면)
        self.gif_strip.setViewMode(QtWidgets.QListView.IconMode)
        self.gif_strip.setFlow(QtWidgets.QListView.LeftToRight)
        self.gif_strip.setWrapping(False)
        self.gif_strip.setIconSize(QtCore.QSize(48, 48))
        # 빌드 18: 아래 가로 막대 50% 굵게 → 빌드 23 사용자 '너무 두껍다' → Windows 기본 굵기
        sb_h = self.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent)
        self.gif_strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.gif_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.gif_strip.setFixedHeight(48 + self.fontMetrics().height() + 16 + sb_h)   # 그림 + 장면 번호 글자가 안 잘리게
        self.gif_strip.setMovement(QtWidgets.QListView.Static)
        self.gif_strip.setToolTip(T("장면 띠 — 누르면 그 장면, 끌면 옆으로 밀림"))
        self._strip_drag = None   # 빌드 18: 끌어서 밀기 (눌렀던 x, 그때 스크롤 값, 끄는 중?)
        self.gif_strip.viewport().installEventFilter(self)
        self.gif_strip.installEventFilter(self)   # 빌드 23: 띠에 초점이 있어도 ← → 는 장면 이동 (띠 칸만 움직이던 것)
        self.gif_strip.itemClicked.connect(lambda it: self._gif_seek(it.data(Qt.UserRole)))
        v.addWidget(self.gif_strip)
        w.setVisible(False)
        return w

    def _gif_seek(self, n):
        m = self.movie
        if m is None:
            return
        if not self.gif_seekable:   # 0.9.118 (사용자: 슬라이더를 움직여도 장면이 안 움직임) — 큰 GIF 는 멈춘 뒤 차례로 풀어 이동 (끄는 동안은 0.15초 모아서)
            self._seek_target = int(n)
            if not hasattr(self, "_seek_tm"):
                self._seek_tm = QtCore.QTimer(self)
                self._seek_tm.setSingleShot(True)
                self._seek_tm.timeout.connect(self._gif_seek_slow)
            self._seek_tm.start(150)
            return
        n = max(0, min(int(n), m.frameCount() - 1))
        m.setPaused(True)
        ok = m.jumpToFrame(n)
        if not ok:   # 아직 안 지나간 장면은 바로 못 감 (GIF 는 앞에서부터 풀어야 함) → 처음부터 차례로
            steps = 0
            if m.currentFrameNumber() > n:
                m.jumpToFrame(0)
            while m.currentFrameNumber() < n and steps < 5000 and m.jumpToNextFrame():
                steps += 1
            ok = m.currentFrameNumber() == n
        log.debug("GIF 장면 이동 %s → %s (지금 %d)", n, ok, m.currentFrameNumber())
        self._gif_ui()

    def _gif_seek_slow(self):
        m = self.movie
        if m is None:
            return
        t0 = time.time()
        n = max(0, min(self._seek_target, m.frameCount() - 1))
        m.setPaused(True)
        self._seeking = True   # 지나가는 장면은 화면에 안 그림
        try:
            if m.currentFrameNumber() > n:
                m.stop()
                m.start()
                m.setPaused(True)
            steps = 0
            while m.currentFrameNumber() < n and steps < 5000 and m.jumpToNextFrame():
                steps += 1
        finally:
            self._seeking = False
        self._set_pic(m.currentPixmap())
        log.info("GIF 느린 장면 이동 → %d (지금 %d, %d장 풂, %.0fms)", n, m.currentFrameNumber(), steps, (time.time() - t0) * 1000)
        self._gif_ui()

    def _gif_step(self, d):
        m = self.movie
        if m is None:
            return
        if m.state() == QtGui.QMovie.Running:
            m.setPaused(True)
        if d > 0 and not self.gif_seekable:
            m.jumpToNextFrame()
        else:
            self._gif_seek((m.currentFrameNumber() + d) % max(1, m.frameCount()))
        self._gif_ui()

    def _toggle_autoplay(self):
        on = self.gif_btns["autoplay"].isChecked()
        SETTINGS["preview_autoplay"] = on
        log.info("미리보기 자동 재생 %s", "켬" if on else "끔")

    def _toggle_sound(self):
        m = self.movie
        if not isinstance(m, video.VideoMovie):
            return
        on = m.muted()   # 꺼져 있었으면 켬
        m.set_muted(not on)
        SETTINGS["video_sound"] = on
        log.info("미리보기 동영상 소리 %s", "켬" if on else "끔")
        self._gif_ui()

    def _gif_fg(self):
        return self.palette().color(QtGui.QPalette.WindowText).name()

    def _gif_stop(self):
        """■ 정지 = 멈추고 첫 장면 (빌드 18)"""
        m = self.movie
        if m is None:
            return
        m.setPaused(True)
        self._gif_seek(0)
        self._gif_ui()

    def _strip_event(self, ev):
        """장면 띠 끌어서 밀기 (빌드 18): 누르고 움직이면 가로 스크롤을 손으로 밀듯, 놓을 때 장면 이동 안 함. 안 움직이고 놓으면 그 장면"""
        t = ev.type()
        sb = self.gif_strip.horizontalScrollBar()
        if t == QtCore.QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            self._strip_drag = [ev.position().x(), sb.value(), False]
        elif t == QtCore.QEvent.MouseMove and self._strip_drag and ev.buttons() & Qt.LeftButton:
            dx = ev.position().x() - self._strip_drag[0]
            if not self._strip_drag[2] and abs(dx) >= QtWidgets.QApplication.startDragDistance():
                self._strip_drag[2] = True
                self.gif_strip.viewport().setCursor(Qt.ClosedHandCursor)
            if self._strip_drag[2]:
                sb.setValue(int(self._strip_drag[1] - dx))
                return True
        elif t == QtCore.QEvent.MouseButtonRelease and self._strip_drag:
            dragged = self._strip_drag[2]
            self._strip_drag = None
            self.gif_strip.viewport().unsetCursor()
            if dragged:
                log.debug("장면 띠 끌어 밂 → 스크롤 %d", sb.value())
                return True   # 장면 이동 안 함
        return False

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.KeyPress and self.movie is not None and obj in (getattr(self, "gif_strip", None), getattr(self, "gif_slider", None)):
            k = ev.key()   # 빌드 23: 띠·막대에서 ← → = 한 장면 (화면·막대·띠 같이), 스페이스 = 재생/멈춤
            if k in (Qt.Key_Left, Qt.Key_Right) and not ev.modifiers():
                self._gif_step(-1 if k == Qt.Key_Left else +1)
                return True
            if k == Qt.Key_Space and not ev.modifiers():
                self._gif_toggle()
                return True
        if getattr(self, "gif_strip", None) is not None and obj is self.gif_strip.viewport():
            if self._strip_event(ev):
                return True
        if obj is getattr(self, "gif_slider", None) and ev.type() == QtCore.QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            sl = self.gif_slider   # 누른 자리 값으로 바로 (손잡이를 누른 거면 그대로 끌기)
            opt = QtWidgets.QStyleOptionSlider()
            sl.initStyleOption(opt)
            hr = sl.style().subControlRect(QtWidgets.QStyle.CC_Slider, opt, QtWidgets.QStyle.SC_SliderHandle, sl)
            if not hr.contains(ev.position().toPoint()):
                gr = sl.style().subControlRect(QtWidgets.QStyle.CC_Slider, opt, QtWidgets.QStyle.SC_SliderGroove, sl)
                x = int(ev.position().x()) - gr.x() - hr.width() // 2
                v = QtWidgets.QStyle.sliderValueFromPosition(sl.minimum(), sl.maximum(), x, max(1, gr.width() - hr.width()))
                log.debug("장면 막대 누름 → %d", v)
                sl.setValue(v)
        return super().eventFilter(obj, ev)

    def _gif_toggle(self):
        m = self.movie
        if m is None:
            return
        m.setPaused(m.state() == QtGui.QMovie.Running)
        self._gif_ui()

    def _gif_ui(self):
        m = self.movie
        if m is None:
            return
        n, tot = m.currentFrameNumber(), m.frameCount()
        self.gif_play.setIcon(gif_icon("pause" if m.state() == QtGui.QMovie.Running else "play", self._gif_fg()))
        self.gif_slider.blockSignals(True)
        self.gif_slider.setRange(0, max(0, tot - 1))
        self.gif_slider.setValue(max(0, n))
        self.gif_slider.blockSignals(False)
        if isinstance(m, video.VideoMovie):   # 빌드 21: 장면 + 시각 + fps
            ms = int(m.currentTime() - (m._t0 or 0))   # 첫 장면을 0초로 (첫 장면이 0.032초에서 시작하는 영상도 있음)
            tm = lambda x: f"{x // 60000:02d}:{x // 1000 % 60:02d}.{x % 1000:03d}"
            # 빌드 24 (사용자 11/6 '지금 시간인지 전체 시간인지 헷갈림'): 지금 시각 / 전체 길이
            # 빌드 26 (사용자 11/6 '심플하게 49 / 92 frame'): 장면 / 전체 frame · 지금 시각 / 전체 길이 · fps (어느 언어나 같은 글자)
            self.gif_lbl.setText(f"{n + 1} / {tot} frame  ·  {tm(ms)} / {tm(int(m.duration()))}  ·  {m.display_fps()}fps")
            sb = self.gif_btns.get("sound")
            if sb is not None:
                sb.setVisible(m.has_audio())
                sb.setIcon(gif_icon("mute" if m.muted() else "sound", self._gif_fg()))
                sb.setToolTip(T("소리 켜기") if m.muted() else T("소리 끄기"))
        else:
            self.gif_lbl.setText(f"{n + 1} / {tot} frame  ·  {max(0, m.nextFrameDelay())}ms")   # 빌드 26 동영상과 같은 모양
        if self.gif_strip.count() and m.state() != QtGui.QMovie.Running:
            # 빌드 23: 띠 칸 = 장면 번호(동영상은 고르게 뽑아 칸 순서 ≠ 장면 — 전엔 28 을 눌렀는데 82 칸이 골라져 보임, 11/6 사용자)
            row = 0
            for r in range(self.gif_strip.count()):
                if (self.gif_strip.item(r).data(Qt.UserRole) or 0) <= n:
                    row = r
                else:
                    break
            if self.gif_strip.currentRow() != row:
                self.gif_strip.blockSignals(True)
                self.gif_strip.setCurrentRow(row)
                self.gif_strip.blockSignals(False)
            self.gif_strip.scrollToItem(self.gif_strip.item(row))

    def _open_edit(self):
        """0.9.111: 지금 GIF·동영상을 편집 창으로 (지금 장면에서 시작, 미리보기는 멈춤)"""
        m = self.movie
        if m is None:
            return
        path, n = m.fileName(), m.currentFrameNumber()
        try:
            m.setPaused(True)
        except Exception:
            pass
        main = self.main or next(iter(WINDOWS), None)
        open_media_edit(path, n, self.window())

    def _gif_save(self):
        m = self.movie
        if m is None:
            return
        img = m.currentImage()
        base = os.path.splitext(m.fileName())[0]
        dst, _ = QtWidgets.QFileDialog.getSaveFileName(self, T("장면 저장"), f"{base}_{m.currentFrameNumber() + 1:03d}.png", "PNG (*.png)")
        if dst:
            ok = img.save(dst, "PNG")
            log.info("GIF 장면 저장 %s 장면 %d → %s (%s)", m.fileName(), m.currentFrameNumber() + 1, dst, ok)
            self.main.show_notice((T("장면을 저장했습니다: {0}") if ok else T("⚠ 장면 저장 실패: {0}")).format(dst))

    def _gif_strip_fill(self, path):
        """장면 띠: 뒤 스레드에서 장면마다 작은 그림 → 화면 스레드로 (300장까지)"""
        self.gif_strip.clear()
        gen = self._strip_gen = getattr(self, "_strip_gen", 0) + 1
        sig = self._strip_sig

        def work():
            rd = QtGui.QImageReader(path)
            out, i = [], 0
            while i < 300:
                im = rd.read()
                if im.isNull():
                    break
                out.append(im.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                i += 1
            try:
                sig.emit(gen, out)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True, name="gifstrip").start()

    def _on_strip(self, gen, imgs):
        if gen != getattr(self, "_strip_gen", 0) or self.movie is None:
            return
        for i, im in enumerate(imgs):
            if isinstance(im, tuple):   # 동영상 (빌드 21): 고르게 뽑은 장면 = (장면 번호, 그림)
                i, im = im
            it = QtWidgets.QListWidgetItem(QtGui.QIcon(QtGui.QPixmap.fromImage(im)), str(i + 1))
            it.setData(Qt.UserRole, i)
            self.gif_strip.addItem(it)
        self.gif_strip.setEnabled(True)   # 0.9.118: 큰 GIF 도 장면 띠로 이동 (느린 이동, 사용자 '하단 슬라이드 선택이 안 됨')

    def _stop_movie(self):
        if hasattr(self, "gif_warn"):
            self.gif_warn.setVisible(False)
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        vs = getattr(self, "_vstrip", None)
        if vs is not None:   # 빌드 21 동영상 장면 띠 재생기
            vs.close()
            vs.deleteLater()
            self._vstrip = None
        if hasattr(self, "gifbar"):
            self.gifbar.setVisible(False)
        if hasattr(self, "gif_btns") and "sound" in self.gif_btns:
            self.gif_btns["sound"].setVisible(False)   # GIF 엔 소리 단추 없음

    def pause_movie(self, paused):
        """창 최소화 = 멈춤 (보이지 않는데 돌 필요 없음), 다시 열면 이어서"""
        if self.movie is not None:
            self.movie.setPaused(paused)

    def _play_video(self, path, mtime):
        """동영상: 재생(소리 없음, 끝나면 처음부터) + GIF 와 같은 조작줄 (빌드 21). 부품이 없으면 False → 첫 장면 그림"""
        if not video.available():
            return False
        m = video.VideoMovie(path, self, muted=not SETTINGS["video_sound"])
        self.movie = m
        self.gif_seekable = True
        m.frameChanged.connect(lambda _i, m=m: m is self.movie and not getattr(self, "_seeking", False) and (self._set_pic(m.currentPixmap()), self._gif_ui()))
        m.ready.connect(lambda m=m: m is self.movie and (self._gif_ui(), self._video_strip(m)))
        m.failed.connect(lambda _s, m=m, p=path, t=mtime: m is self.movie and self._video_failed(p, t))
        pm = thumbs_service().get(path, mtime, self.PX)   # 첫 장면이 오기 전엔 윈도우 미리보기 그림
        if pm is not None:
            self._set_pic(pm)
        self.gif_strip.clear()
        self.gifbar.setVisible(True)
        if SETTINGS["preview_autoplay"]:
            m.start()
        else:   # 빌드 28: 첫 장면에서 멈춘 채 (▶ 로 재생)
            m.ready.connect(lambda m=m: m is self.movie and m.jumpToFrame(0))
            m.pl.pause()
        log.info("미리보기 동영상 %s (자동 재생 %s)", path, bool(SETTINGS["preview_autoplay"]))
        return True

    def _video_strip(self, m):
        old = getattr(self, "_vstrip", None)
        if old is not None:
            old.close()
            old.deleteLater()
        gen = self._strip_gen = getattr(self, "_strip_gen", 0) + 1
        if not hasattr(self, "_strip_sig"):
            class _S(QtCore.QObject):
                done = QtCore.Signal(int, list)
            self._strip_sig_obj = _S()
            self._strip_sig = self._strip_sig_obj.done
            self._strip_sig.connect(self._on_strip)
        self._vstrip = video.VideoStrip(m.fileName(), m.frameCount(), m.fms, parent=self)
        self._vstrip.done.connect(lambda lst, gen=gen: self._on_strip(gen, lst))

    def _video_failed(self, path, mtime):
        log.info("동영상 재생 못 함 → 첫 장면 그림 %s", path)
        self._stop_movie()
        pm = thumbs_service().get(path, mtime, self.PX)
        self.cur = (path, mtime)
        if pm is not None:
            self._set_pic(pm)

    def _play_gif(self, path, size):
        """움직이는 GIF 면 재생하고 True. 한 장짜리·깨진 파일·너무 큰 파일·재생 부품(qgif) 없음 → False (보통 미리보기로)"""
        if size > self.GIF_MAX or b"gif" not in [bytes(f) for f in QtGui.QMovie.supportedFormats()]:
            return False
        m = QtGui.QMovie(path)
        dim = QtGui.QImageReader(path).size()
        est = max(1, m.frameCount()) * max(1, dim.width()) * max(1, dim.height()) * 4   # 풀어 놓은 장면 전체 크기 추정
        self.gif_seekable = size <= self.GIF_SEEK_MAX or est <= self.GIF_CACHE_MAX
        self._seeking = False
        log.info("GIF 장면 기억 판단 %s 파일 %s · 풀면 약 %s (%dx%d x %d장) → %s", os.path.basename(path), size_short(size), size_short(est),
                 dim.width(), dim.height(), m.frameCount(), "전부 기억" if self.gif_seekable else "차례로 풀어 이동")
        m.setCacheMode(QtGui.QMovie.CacheAll if self.gif_seekable else QtGui.QMovie.CacheNone)   # 다 기억해야 아무 장면으로 이동
        self.gif_warn.setVisible(not self.gif_seekable)
        if not m.isValid() or m.frameCount() == 1:
            m.deleteLater()
            return False
        self.movie = m
        m.frameChanged.connect(lambda _i, m=m: m is self.movie and not getattr(self, "_seeking", False) and (self._set_pic(m.currentPixmap()), self._gif_ui()))
        m.start()
        if not SETTINGS["preview_autoplay"]:   # 빌드 28: 첫 장면에서 멈춘 채
            m.setPaused(True)
        if not hasattr(self, "_strip_sig"):
            class _S(QtCore.QObject):
                done = QtCore.Signal(int, list)
            self._strip_sig_obj = _S()
            self._strip_sig = self._strip_sig_obj.done
            self._strip_sig.connect(self._on_strip)
        self.gifbar.setVisible(True)
        self._gif_strip_fill(path)
        self._gif_ui()
        log.info("미리보기 GIF 재생 %s (장면 %d, %s, 장면 이동 %s)", path, m.frameCount(), size_short(size), self.gif_seekable)
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
        if not self.isVisible() or self.window().isMinimized():
            return
        pane = self.main.pane()
        v = pane.view() if pane else None
        if v is None:
            return
        rows = v.selected_rows()
        if len(rows) == 1 and self.movie is not None and os.path.normcase(self.movie.fileName()) == os.path.normcase(v.model_.full(v.model_.rows[rows[0]])):
            return   # 같은 GIF 가 재생 중 (선택 글자만 다시 그려진 경우) — 처음부터 다시 틀지 않음
        if len(rows) == 1:   # 0.9.118 빌드 3 (사용자: 그림 미리보기가 계속 깜박임) — 같은 파일·같은 수정 시각이면 형식별 화면을 다시 만들지 않음
            e0 = v.model_.rows[rows[0]]
            key = (os.path.normcase(v.model_.full(e0)), e0[3])
            now = time.time()
            self._rf = [t for t in getattr(self, "_rf", []) if now - t < 1.5] + [now]
            if len(self._rf) == 5:
                log.warning("미리보기 다시 그리기가 몰림 (1.5초에 5번) %s — 부른 곳: %s", key[0], " | ".join(getattr(self, "_last_callers", [])))
            if self.extra is not None and getattr(self, "_extra_key", None) == key and self.extra.isVisible():
                return
        ekey = key if len(rows) == 1 else None
        self._stop_movie()
        self._drop_extra()
        self._extra_key = ekey   # _drop_extra 가 지우므로 그 뒤에
        self.btn_inspect.setVisible(False)
        self.btn_seq.setVisible(False)
        if len(rows) != 1:
            self.cur = None
            self._set_pic(None)
            if rows:
                es = [v.model_.rows[r] for r in rows]
                self.name.setText(T('    {0:,}개 항목 선택함').format(len(rows)).strip())   # 상태줄과 같은 문구
                fs = [e[2] for e in es if not e[1] and e[2] >= 0]
                nd = sum(1 for e in es if e[1])
                self._set_rows([(T("파일"), f"{len(es) - nd:,}" if len(es) - nd else ""), (T("폴더"), f"{nd:,}" if nd else ""),
                                (T("크기"), size_short(sum(fs)) if fs else "")])
            else:
                self.name.setText("")
                self._rows = []
                self.info.setText(T("파일을 고르면 여기에 미리보기가 나옵니다"))
            return
        e = v.model_.rows[rows[0]]
        path = v.model_.full(e)
        self.name.setText(e[7] or e[0])
        rows = [(T("종류"), shellops.type_for(e[0], e[1]))]
        if e[1] and os.path.isdir(path) and not (devices.is_dev(path) or archives.is_arc(path)):
            rows += [(T("내용"), T("세는 중…")), (T("전체 크기"), "…")]
        if not e[1] and e[2] >= 0:
            rows.append((T("크기"), win_kbsize(e[2])))
        if e[3]:
            rows.append((T("수정한 날짜"), win_datetime(e[3])))
        self._set_rows(rows)
        pm = None
        if devices.is_dev(path) or archives.is_arc(path):   # 휴대폰·압축 안 파일: 그림 없이 정보만
            self.cur = None
            self._set_pic(None)
            return
        if not e[1] and video.is_video(e[0]) and OPTS["thumbnails"] and self._play_video(path, e[3]):   # 빌드 21 동영상 = GIF 처럼
            self.cur = None
            return
        if not e[1] and e[0].lower().endswith(".gif") and OPTS["thumbnails"] and self._play_gif(path, e[2]):
            self.cur = None
            return
        self.btn_seq.setVisible(not e[1] and thumbs.is_image(e[0]) and seq_in_view(v, path) is not None)
        if (not e[1] or os.path.isdir(path)) and self._try_extra(path):   # 0.9.116 + 0.9.117 폴더 코드·글꼴·소리·PSD 레이어·엑셀·그림(확대·스포이트)
            if not self.pic.isVisible():
                self.cur = None
                self._set_pic(None)
                return
        if not e[1] and OPTS["thumbnails"] and (thumbs.is_image(e[0]) or os.path.splitext(e[0])[1].lower() in self.DOC_PREVIEW):
            self.cur = (path, e[3])
            pm = thumbs_service().get(path, e[3], self.PX)   # 없으면 요청 → 다 되면 _on_ready (문서·영상은 윈도우 미리보기, 없으면 아이콘)
        else:
            self.cur = None
        if pm is None:
            pm = shellops.icon_for(e[0], e[1], 256, e[6]).pixmap(128, 128)
        self._set_pic(pm)
        self.btn_inspect.setVisible(not e[1] and imginspect.can_open(path))


class _GdSig(QtCore.QObject):
    done = QtCore.Signal(str, object, object)   # 일 이름, 결과, 오류 글자(없으면 None)


GD_DUE = 20 * 3600   # 자동 백업 간격 (하루 한 번 — 20시간 지나면)


def gd_result_page(ok, title, msg):
    """구글 로그인 뒤 브라우저에 보이는 결과 페이지 (0.9.119 사용자 11/10: 큰 글자 한 줄은 전문성이 없어 보임)
    — 가운데 카드 · 4Dir 아이콘 · 결과 표시(✓/!) · 제목 · 안내 · 아래 4dir.net. 밝게/어둡게 자동, 바깥 파일 안 씀"""
    import html as _h
    import base64
    icon = ""
    try:
        ba = QtCore.QByteArray()
        buf = QtCore.QBuffer(ba)
        buf.open(QtCore.QIODevice.WriteOnly)
        ui_parts.app_icon().pixmap(96, 96).save(buf, "PNG")
        icon = f"<img class='logo' alt='4Dir' src='data:image/png;base64,{base64.b64encode(bytes(ba)).decode()}'>"
    except Exception:
        log.exception("결과 페이지 아이콘 실패")
    mark = ("<svg viewBox='0 0 24 24' width='22' height='22'><path d='M5 12.5l4.2 4.2L19 7' fill='none' stroke='#fff' stroke-width='2.6' "
            "stroke-linecap='round' stroke-linejoin='round'/></svg>") if ok else            ("<svg viewBox='0 0 24 24' width='22' height='22'><path d='M12 6v8' stroke='#fff' stroke-width='2.6' stroke-linecap='round'/>"
            "<circle cx='12' cy='18' r='1.6' fill='#fff'/></svg>")
    return f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>4Dir</title><style>
:root{{--bg:#f3f5f8;--card:#fff;--fg:#1f2328;--sub:#59636e;--line:#e3e7ec;--ok:#1e8e3e;--bad:#d93025}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181c;--card:#202329;--fg:#e8eaed;--sub:#a0a8b2;--line:#30353c}}}}
*{{box-sizing:border-box}}html,body{{height:100%;margin:0}}
body{{background:var(--bg);color:var(--fg);font-family:'Segoe UI','Malgun Gothic',system-ui,sans-serif;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.08);width:100%;max-width:420px;padding:36px 32px 26px;text-align:center}}
.logo{{width:56px;height:56px;display:block;margin:0 auto 18px}}
.mark{{width:44px;height:44px;border-radius:50%;background:var({'--ok' if ok else '--bad'});display:flex;align-items:center;justify-content:center;margin:0 auto 16px}}
h1{{font-size:20px;font-weight:600;margin:0 0 8px;letter-spacing:-.2px;word-break:keep-all}}p{{font-size:14px;line-height:1.55;color:var(--sub);margin:0;word-break:keep-all}}
.foot{{margin-top:26px;padding-top:14px;border-top:1px solid var(--line);font-size:12px;color:var(--sub)}}.foot a{{color:inherit;text-decoration:none}}
</style></head><body><div class='card'>{icon}<div class='mark'>{mark}</div><h1>{_h.escape(title)}</h1><p>{_h.escape(msg)}</p>
<div class='foot'>4Dir &middot; <a href='https://4dir.net'>4dir.net</a></div></div></body></html>"""


class Main(QtWidgets.QMainWindow):
    gdrive_changed = QtCore.Signal()   # 0.9.114 구글 드라이브 백업 상태 바뀜 (설정 창이 다시 그림)

    def __init__(self, crashed=False, open_path=None, src=None, open_state=None, restore_geometry=False):
        """open_path 가 있으면 '새 창으로 열기' — 저장 상태 대신 칸 1개 + 그 폴더로 시작 (src = 연 창, 위치 기준)
        open_state 가 있으면 그 기록(자동 기록 복구·지난번 함께 열려 있던 창)으로 새 창. restore_geometry = 그때 위치·크기"""
        super().__init__()
        _ORDER[0] += 1
        self.order = _ORDER[0]
        self.setAttribute(Qt.WA_DeleteOnClose)   # 창이 여러 개일 때 닫은 창 메모리 반환
        self.setWindowTitle(window_title())
        self.gdrive_changed.connect(refresh_titles)   # 0.9.115 제목 표시줄에 구글 백업 연결 상태
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
        self._drive_timer = QtCore.QTimer(self)   # 드라이브 꽂기/빼기 알림을 0.6초 묶어 '내 PC' 다시 읽기 (v0.9.95)
        self._drive_timer.setSingleShot(True)
        self._drive_timer.setInterval(600)
        self._drive_timer.timeout.connect(self.refresh_drives)
        self._dev_notes = {}   # 드라이브 'K:' → (열어 둔 핸들, 알림 등록) — 꺼내기 요청을 받으려고 (v0.9.96)
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
        nrow.addWidget(self.notice_close)
        cl.addLayout(nrow)
        cl.addWidget(self.favbar)
        self.chip_sel = set()   # 맨 위 형식 단추에서 고른 형식 (0.9.122)
        self.global_chips = GlobalChipBar(self)
        cl.addWidget(self.global_chips)
        body = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(body)
        bl.setContentsMargins(4, 4, 4, 4)
        # 칸들 | 오른쪽 미리보기 창 (v0.9.58)
        self.hsplit = QtWidgets.QSplitter(Qt.Horizontal)
        self.hsplit.setChildrenCollapsible(False)
        self.hsplit.setHandleWidth(5)
        global PREVIEW_WIN
        if PREVIEW_WIN is None:   # 빌드 18: 미리보기는 따로 창 (켜도 칸 크기 그대로) — 처음 창이 만들고 모두 같이 씀
            PREVIEW_WIN = PreviewWindow(self)
        self.preview = PREVIEW_WIN.pane
        self.hsplit.addWidget(self.vert)
        if SETTINGS["preview_pane"] and not PREVIEW_WIN.isVisible():
            QtCore.QTimer.singleShot(0, lambda: self.set_preview(True))
        # v0.9.100 이슈 #3: 창 왼쪽 전체 높이 공용 탐색 창 | (칸들 | 미리보기)
        self.lsplit = QtWidgets.QSplitter(Qt.Horizontal)
        self.lsplit.setChildrenCollapsible(False)
        self.lsplit.setHandleWidth(5)
        self.shared_side = None   # 처음 켤 때 만듦
        self.shared_host = QtWidgets.QWidget()
        self.shared_host.setObjectName("sharedSideHost")
        QtWidgets.QVBoxLayout(self.shared_host).setContentsMargins(0, 0, 0, 0)
        self.shared_host.setVisible(False)
        self.lsplit.addWidget(self.shared_host)
        self.lsplit.addWidget(self.hsplit)
        self.lsplit.setStretchFactor(0, 0)
        self.lsplit.setStretchFactor(1, 1)
        self.lsplit.splitterMoved.connect(self._shared_moved)
        bl.addWidget(self.lsplit)
        cl.addWidget(body, 1)
        self.setCentralWidget(central)
        if SETTINGS["chrome_collapsed"]:
            self.set_chrome_collapsed(True, save=False)
        self.memo_panel = None
        if getattr(Main, "_last_devices", None) is None:   # 빌드 5: 휴대폰 꽂기/빼기 비교 기준 (뒤에서, 시작 안 늦추게)
            Main._last_devices = ()
            threading.Thread(target=lambda: setattr(Main, "_last_devices", tuple(sorted(n for n, _p in devices.list_devices()))),
                             daemon=True).start()
        if SETTINGS["memo_on"]:   # v0.9.108 메모 창 켜 둔 채 끝냈으면 그대로
            self.set_memo(True, save=False)
        if SETTINGS["side_shared"]:   # v0.9.100 공용 탐색 창 켜 둔 채 끝냈으면 그대로
            self.set_shared_side(True, save=False)
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
            "lock_tab": lambda: self.pane().toggle_lock(),
            "toggle_chips": lambda: self.toggle_opt("type_chips"),   # 빌드 27
            "reopen_tab": lambda: self.reopen_tab(),
            "focus_filter": lambda: self.pane().focus_filter(),
            "global_search": lambda: self.focus_global_search(),
            "next_tab": lambda: self._cycle_tab(1),
            "prev_tab": lambda: self._cycle_tab(-1),
            "focus_addr": focus_addr,
            "toggle_hidden": lambda: self.toggle_opt("show_hidden"),
            "add_fav": add_fav,
            "toggle_chrome": lambda: self.set_chrome_collapsed(not SETTINGS["chrome_collapsed"]),
            "toggle_preview": lambda: self.toggle_preview(),
            "toggle_nav": lambda: self.pane().toggle_sidebar(),
            "toggle_calc": lambda: self.toggle_calc(),   # 0.9.111 계산기
            "toggle_memo": lambda: self.toggle_memo(),   # v0.9.108 메모 창 (빌드 10: 뒤에 숨었으면 앞으로)   # v0.9.101 공용이면 공용 창, 칸마다면 지금 칸
            "compare": lambda: self.compare_panes(),
            "same_folder": lambda: self.same_folder_other(),   # 0.9.112
            "sync_dirs": lambda: self.sync_dirs(),   # 0.9.109
            "ftp_connect": lambda: self.ftp_connect(),
            "user_buttons": lambda: self.edit_user_buttons(),
            "palette": lambda: self.open_palette(),
            "settings": lambda: self.open_settings(),   # v0.9.104
            "ws_latest": lambda: self.load_ws_latest(),   # v0.9.98 이슈 #1 창 구성 단축키
            "ws_slot1": lambda: self.load_ws_slot(1),
            "ws_slot2": lambda: self.load_ws_slot(2),
        }
        for i in range(NPANES):
            self.win_actions[f"pane{i + 1}"] = (lambda i=i: self._focus_pane(i))
        self.win_actions.update(self._extra_win_actions())   # 0.9.113 메뉴에만 있던 기능
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
            SEARCH = search_index.SearchIndex(os.path.join(DATA_DIR, "index"),
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
        if not self.searchbar.isVisible():   # 메뉴줄을 접어 둔 상태면 펼쳐야 검색칸에 커서가 들어감
            self.set_chrome_collapsed(False)
        self.gsearch.setFocus()
        self.gsearch.selectAll()

    def open_search_roots(self):
        return self.open_settings("search")   # v0.9.105 설정 창 안에서

    def search_panel(self):
        """설정 창 '검색' 안에 넣는 검색 범위 설정 (v0.9.105) → (창, 끝났을 때)"""
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
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText(T("적용"))
        bb.button(QtWidgets.QDialogButtonBox.Cancel).setText(T("되돌리기"))
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)

        def done(r):
            if not r:
                return
            roots = [{"path": lst.item(i).data(Qt.UserRole), "on": lst.item(i).checkState() == Qt.Checked} for i in range(lst.count())]
            old = self.search_roots_enabled()
            SETTINGS["search_roots"] = roots
            new = self.search_roots_enabled()
            log.info("검색 범위 %s → %s", old, new)
            if [x.lower() for x in old] != [x.lower() for x in new]:
                self.idx_btn.setText(T("색인 만드는 중"))
                SEARCH.set_roots(new)
            self.show_notice(T("검색 범위를 저장했습니다  ✕"), ms=1500)
        return dlg, done

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

        self.top_menus = []   # (이름, 채우는 함수) — 명령 찾기가 메뉴 항목도 모음 (v0.9.89)

        def menu_btn(text, filler, tip=""):
            self.top_menus.append((text, filler))
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)   # 빌드 13 사용자: 모든 메뉴·기능에 풍선 도움말
            b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            b.setAutoRaise(True)
            m = QtWidgets.QMenu(b)
            m.aboutToShow.connect(lambda: filler(m))
            b.setMenu(m)
            tb.addWidget(b)
            return b

        menu_btn(T("보기"), self._fill_main_view_menu, T("보기 — 칸 나누기 · 탐색 창 · 미리보기 · 항상 위 등 화면 표시"))
        # v0.9.93 사용자 11/4: 글자 메뉴 '레이아웃'은 빼고 도구줄 레이아웃 버튼(고르기 창)만 — 명령 찾기에는 계속 나오게 목록만 남김
        self.top_menus.append((T("레이아웃"), self._fill_layout_menu))
        self.top_menus.append((T("즐겨찾기"), self._fill_fav_menu))   # v0.9.102 메뉴줄에서 뺌(즐겨찾기 바 글자로) — 명령 찾기엔 남김
        self.top_menus.append((T("창 저장/불러오기"), self._fill_session_menu))   # v0.9.103 사용자 11/5: 도구 메뉴 안으로 (명령 찾기엔 남김)
        menu_btn(T("도구"), self._fill_tool_menu, T("도구 — 메모 창 · 창 저장/불러오기 · 폴더 비교 · 찾기 등"))
        self.top_menus.append((T("설정"), self._fill_settings_menu))   # 명령 찾기용 목록 (v0.9.103)
        # v0.9.104 사용자 11/5: 설정은 톱니 아이콘 → 카테고리 설정 창
        self.btn_settings = QtWidgets.QToolButton()
        self.btn_settings.setIcon(gear_icon())
        self.btn_settings.setAutoRaise(True)
        self.btn_settings.setToolTip(T("설정") + "  (Ctrl+,)")
        self.btn_settings.clicked.connect(lambda: self.open_settings())
        # 미리보기 창 켜기/끄기 — 도구 오른쪽 (v0.9.59, 사용자 요청)
        self.act_preview = tb.addAction(preview_icon(), T("미리보기 창"), lambda: self.toggle_preview())
        self.act_preview.setCheckable(True)
        self.act_preview.setChecked(bool(SETTINGS["preview_pane"]))
        # v0.9.108 메모 창 켜기/끄기 (미리보기 버튼 옆)
        self.btn_memo = QtWidgets.QToolButton()
        self.btn_memo.setIcon(memo_icon())   # 빌드 7: 글자 📝 대신 그린 노란 메모지 + 빨간 펜 (작고 흐려 안 보였음)
        self.btn_memo.setCheckable(True)
        self.btn_memo.setAutoRaise(True)
        self.btn_memo.setToolTip(T("메모 창") + "  (Alt+M)")
        self.btn_memo.clicked.connect(lambda: self.toggle_memo())
        tb.addWidget(self.btn_memo)
        self.btn_calc = QtWidgets.QToolButton()   # 0.9.111 빌드 4 (사용자 '계산기도 아이콘')
        self.btn_calc.setIcon(toolicons.icon("calc", 20))
        self.btn_calc.setAutoRaise(True)
        self.btn_calc.setToolTip(T("계산기") + "  (Alt+C)")
        self.btn_calc.clicked.connect(lambda: self.toggle_calc())
        tb.addWidget(self.btn_calc)
        # 빌드 27 (사용자 11/6): 형식 단추 줄(데이터 종류 칩) 켜기/끄기 — 모든 창·칸에 적용
        self.btn_chips = QtWidgets.QToolButton()
        self.btn_chips.setIcon(chips_icon())
        self.btn_chips.setCheckable(True)
        self.btn_chips.setChecked(bool(OPTS["type_chips"]))
        self.btn_chips.setAutoRaise(True)
        self.btn_chips.setToolTip(T("형식 단추 줄 보이기/숨기기 ([전체][JPG][PSD]…) — 모든 칸"))
        self.btn_chips.clicked.connect(lambda: self.toggle_opt("type_chips"))
        tb.addWidget(self.btn_chips)
        # 0.9.109 빌드 3 사용자 단추 (도구 ▸ 사용자 단추 편집…) — 없으면 안 보임
        self.ubar = QtWidgets.QWidget()
        self.ubar_lay = QtWidgets.QHBoxLayout(self.ubar)
        self.ubar_lay.setContentsMargins(0, 0, 0, 0)
        self.ubar_lay.setSpacing(2)
        self.act_ubar = tb.addWidget(self.ubar)
        self.build_user_buttons()
        # 빌드 20 복사 대기열: 복사·이동이 여러 개면 하나씩 — 기다리는 게 있을 때만 '⏳ 대기 n' 이 보임 (누르면 목록·취소·멈춤)
        self.btn_queue = QtWidgets.QToolButton()
        self.btn_queue.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.btn_queue.setAutoRaise(True)
        self.btn_queue.setToolTip(T("복사 대기열 — 복사·이동을 하나씩 차례로 (기다리는 것 취소·멈춤)"))
        qm = QtWidgets.QMenu(self.btn_queue)
        qm.aboutToShow.connect(lambda qm=qm: self._fill_queue_menu(qm))
        self.btn_queue.setMenu(qm)
        self.act_queue = tb.addWidget(self.btn_queue)
        self.act_queue.setVisible(False)
        QUEUE_SIG.changed.connect(self._queue_ui)
        self.act_preview.setToolTip(T("미리보기 창") + (f" ({key_text('toggle_preview')})" if key_text("toggle_preview") else ""))
        tb.addSeparator()
        # v0.9.92 사용자 11/4: 레이아웃이 많아져 도구줄엔 버튼 하나(지금 배치 그림) → 누르면 고르기 창(LayoutPopup)
        self.layout_group = QtGui.QActionGroup(self)
        self.layout_actions = {}
        for key, label in LAYOUTS:
            a = QtGui.QAction(layout_icon(key, 40, 32), label, self)
            a.triggered.connect(lambda _c=False, k=key: self.set_layout(k, equalize=True))
            a.setToolTip(label)
            a.setCheckable(True)
            self.layout_group.addAction(a)
            self.layout_actions[key] = a
        self.act_grid = QtGui.QAction(layout_icon(grid_key(3, 3), 40, 32), T("직접 지정"), self)
        self.act_grid.triggered.connect(self.open_grid_dialog)
        self.act_grid.setToolTip(T("레이아웃: 직접 지정 (가로 x 세로)…"))
        self.act_grid.setCheckable(True)
        self.layout_group.addAction(self.act_grid)
        self.layout_btn = QtWidgets.QToolButton()
        self.layout_btn.setObjectName("layoutBtn")
        self.layout_btn.setAutoRaise(True)
        self.layout_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.layout_btn.setText(T("레이아웃") + " ▾")
        self.layout_btn.clicked.connect(self.show_layout_popup)
        tb.addWidget(self.layout_btn)
        tb.addSeparator()
        self.act_top = tb.addAction(T("📌 항상 위"), self.toggle_on_top)
        self.act_top.setCheckable(True)
        self.act_top.setChecked(SETTINGS["on_top"])
        self.act_top.setToolTip(T("다른 창 위에 항상 표시 (켜기/끄기)"))
        tb.addWidget(self.btn_settings)   # 0.9.109 빌드 1 (사용자 11/6): 설정 톱니는 '항상 위' 뒤로
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
        self.notice_close = QtWidgets.QToolButton()   # v0.9.96 알림 닫기 ✕ (11/5 사용자: 글 끝의 ✕ 가 안 보여 어딜 눌러 닫는지 몰랐음)
        self.notice_close.setObjectName("noticeClose")
        self.notice_close.setText("✕")
        self.notice_close.setToolTip(T("닫기"))
        self.notice_close.setAutoRaise(True)
        self.notice_close.setStyleSheet("QToolButton{font-size:15px; font-weight:bold; padding:0 8px;}")
        self.notice_close.setCursor(Qt.PointingHandCursor)
        self.notice_close.setVisible(False)
        self.notice_close.clicked.connect(lambda: (log.info("알림 닫기 ✕"), self.hide_notice()))
        self._notice_fn2 = None
        self._notice_fn = None
        # 전체 검색칸부터 끝까지는 따로 된 줄(같은 높이 오른쪽) — 창이 좁아도 검색칸이 '»' 안으로 숨지 않게 (v0.9.70: Ctrl+Alt+F 로 불러도 커서를 못 넣던 문제)
        tb = QtWidgets.QToolBar(T("전체 검색"))
        tb.setObjectName("topBar")
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(22, 18))
        self.addToolBar(tb)
        self.searchbar = tb
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
        # v0.9.93 사용자 11/4: 탐색기 점검 ↔ 전체 검색칸 자리 바꿈 → 검색칸·색인 오른쪽으로
        tb.addSeparator()
        self.act_check = tb.addAction(T("Explorer Check (탐색기 점검)"), self.open_check)
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
        # 0.9.109 빌드 2 (사용자 11/6): 메뉴 막대 끝 버전 글자 뺌 — 제목 표시줄에 이미 있음
        self.set_sysmon(SETTINGS["sysmon"], save=False)

    def set_preview(self, on):
        """미리보기 창 켜기/끄기 — 빌드 18 (사용자 11/5): 메모 창처럼 4Dir 창 밖 따로 창, 켜도 칸 크기 그대로. 위치·크기 기억"""
        on = bool(on)
        if PREVIEW_WIN is not None:
            if on:
                PREVIEW_WIN.setStyleSheet(self.styleSheet())
                self.preview.main = self
                PREVIEW_WIN.show_near(self)
                self.preview.schedule(self)
            else:
                PREVIEW_WIN.save_geo()
                PREVIEW_WIN.hide()
        SETTINGS["preview_pane"] = on
        for w in list(WINDOWS) + ([self] if self not in WINDOWS else []):
            if getattr(w, "act_preview", None) is not None:
                w.act_preview.setChecked(on)   # 메뉴·Alt+P 로 바꿔도 버튼 눌림 표시 맞춤
        log.info("미리보기 창 %s", "켬" if on else "끔")

    def _queue_ui(self):
        q = shellops.QUEUE
        n = len(q["pending"])
        busy = q["running"] is not None
        self.act_queue.setVisible(bool(n) or (busy and (n or q["paused"])) or q["paused"])
        self.btn_queue.setText(("⏸ " if q["paused"] else "⏳ ") + T("대기 {0}").format(n))

    def _fill_queue_menu(self, m):
        m.clear()
        q = shellops.QUEUE
        if q["running"] is not None:
            a = m.addAction(T("지금: {0}").format(q["running"]["desc"]))
            a.setEnabled(False)
        if q["pending"]:
            m.addSeparator()
        for j in list(q["pending"]):
            sm = m.addMenu(T("기다림: {0}").format(j["desc"]))
            sm.addAction(T("이 작업 취소"), lambda jid=j["id"]: shellops.queue_cancel(jid))
        m.addSeparator()
        if q["paused"]:
            m.addAction(T("▶ 이어서 하기"), lambda: shellops.queue_pause(False))
        else:
            m.addAction(T("⏸ 다음 작업 멈춤 (지금 것은 계속)"), lambda: shellops.queue_pause(True))

    # ---------------------------------------------------------- 0.9.109 빌드 3 추가 기능 (창)
    def sync_dirs(self):
        """폴더 맞추기: 지금 칸(A)과 다른 칸(B) — 하위 폴더까지 비교 후 복사"""
        a = self.pane()
        b = self.other_pane(a) if a else None
        va, vb = (a.view() if a else None), (b.view() if b else None)
        bad = lambda v: v is None or v.path == THIS_PC or is_search(v.path) or devices.is_dev(v.path) or archives.is_arc(v.path) or not os.path.isdir(v.path)
        if bad(va) or bad(vb):
            self.show_notice(T("⚠ 폴더 맞추기: 두 칸에 폴더를 열어 두세요  ✕"), ms=6000)
            return None
        if os.path.normcase(va.path) == os.path.normcase(vb.path):
            self.show_notice(T("⚠ 두 칸이 같은 폴더입니다  ✕"), ms=5000)
            return None

        def trash(ps, after):
            shellops.delete(self.hwnd_int(), ps, done=lambda res, ab: after())
        dlg = syncdirs.SyncDialog(va.path, vb.path, trash, lambda: [x.reload("sync") for x in (va, vb)], self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.setStyleSheet(self.styleSheet())
        dlg.show()
        log.info("폴더 맞추기 열기 %s ↔ %s", va.path, vb.path)
        return dlg

    def space_map(self, root=None):
        v = self.pane().view() if self.pane() else None
        root = root or (v.path if v else None)
        if not root or root == THIS_PC or is_search(root) or devices.is_dev(root) or archives.is_arc(root) or not os.path.isdir(root):
            self.show_notice(T("⚠ 디스크 사용량 트리맵: 폴더(또는 드라이브)에서 쓰세요  ✕"), ms=5000)
            return None

        def open_cb(path, is_file):
            nv = self.pane().add_tab(os.path.dirname(path) if is_file else path, activate=True)
            if is_file:
                nv.pending_select = os.path.basename(path)
            self.raise_()
            self.activateWindow()
        dlg = spacemap.SpaceMapDialog(root, open_cb, self)
        dlg.setStyleSheet(self.styleSheet())
        dlg.show()
        return dlg

    def ftp_connect(self):
        r = ftpfs.login_dialog(self, None, "/", SETTINGS["ftp_sites"])
        if r:
            remember_ftp(r[0])
            self.pane().add_tab(ftpfs.make(*r), activate=True)

    def edit_user_buttons(self):
        groups = [(cname, [(a, lbl) for a, lbl, _k, _s in rows]) for _c, cname, rows in keymap.grouped(("view", "window"))]   # 0.9.113 4Dir 기능도
        dlg = userbtns.EditDialog(SETTINGS["user_buttons"], self, groups=groups)
        dlg.setStyleSheet(self.styleSheet())
        if dlg.exec():
            SETTINGS["user_buttons"] = dlg.result_items()
            log.info("My메뉴 %d개 저장 (4Dir 기능 %d개)", len(SETTINGS["user_buttons"]), sum(1 for x in SETTINGS["user_buttons"] if x.get("action")))
            for w in WINDOWS:
                w.build_user_buttons()

    def build_user_buttons(self):
        """위쪽 도구줄의 사용자 단추 다시 만들기"""
        if not hasattr(self, "ubar_lay"):
            return
        while self.ubar_lay.count():
            it = self.ubar_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        items = SETTINGS["user_buttons"] or []
        for item in items:
            b = QtWidgets.QToolButton()
            b.setAutoRaise(True)
            ic = userbtns.icon_for(item)
            if not ic.isNull():
                b.setIcon(ic)
            b.setText(item.get("name") or "?")
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if not ic.isNull() else Qt.ToolButtonTextOnly)
            tip = keymap.LABEL.get(item["action"], item["action"]) if item.get("action") else f"{item.get('cmd', '')} {item.get('args', '')}".strip()
            if item.get("action") and key_text(item["action"]):
                tip += f"  ({key_text(item['action'])})"
            b.setToolTip(tip + "\n" + T("우클릭 = My메뉴 편집"))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _p: self.edit_user_buttons())
            b.clicked.connect(lambda _c=False, item=item: self.run_user_button(item))
            self.ubar_lay.addWidget(b)
        self.act_ubar.setVisible(bool(items))

    def run_user_button(self, item):
        if item.get("action"):   # 0.9.113 My메뉴의 4Dir 기능
            try:
                if not self.run_named(item["action"]):
                    self.show_notice(T("⚠ 이 기능은 이 버전에 없습니다: {0}  ✕").format(item.get("name") or item["action"]), ms=6000)
            except Exception as ex:
                log.exception("My메뉴 기능 실행 실패 %s", item["action"])
                self.show_notice(T("⚠ 실행하지 못했습니다: {0}  ✕").format(ex), ms=8000)
            return
        v = self.pane().view() if self.pane() else None
        files = [p for p in (v.selected_paths() if v else []) if not archives.is_arc(p) and not devices.is_dev(p)]
        folder = v.path if v and os.path.isdir(v.path) else ""
        op = self.other_pane(self.pane()) if self.pane() else None
        other = op.view().path if op and op.view() and os.path.isdir(op.view().path) else ""
        try:
            userbtns.run(item, {"files": files, "folder": folder, "other": other})
        except Exception as ex:
            log.exception("사용자 단추 실행 실패")
            self.show_notice(T("⚠ 실행하지 못했습니다: {0}  ✕").format(ex), ms=8000)

    def _pt_cmd(self):
        return winhook.launch_command(os.path.dirname(BIN_DIR))

    @staticmethod
    def winE_method():
        """Win+E 방식 (0.9.120, 사용자 11/10 '체크 하나로'): 윈도우 11 26H2(빌드 26300) 이상 = PowerToys, 그 밑 = 기본(레지스트리)"""
        return "pt" if ptlink.registry_may_fail() else "reg"

    @staticmethod
    def winE_on():
        """체크 표시 = 어느 방식이든 지금 4Dir 가 Win+E 를 받게 되어 있나"""
        try:
            return bool(winhook.ours() or ptlink.linked())
        except Exception:
            log.exception("Win+E 상태 읽기 실패")
            return False

    def pt_link(self):
        """PowerToys 키보드 관리자에 Win+E → 4Dir 새 창 (0.9.119). 없으면 받는 곳, 키보드 관리자가 꺼져 있으면 그 화면 열기"""
        if datadir.PACKAGED:   # 스토어판은 앱 밖 설정 파일을 못 씀 → 그림 안내로 손으로
            self.show_notice(T("스토어판에서는 자동 연결을 할 수 없습니다 — 그림 안내대로 PowerToys 에서 직접 넣어 주세요  ✕"), ms=9000)
            self.open_pt_guide()
            return False
        if ptlink.exe_path() is None:
            self.show_notice(T("PowerToys 가 없습니다 — 설치한 뒤 다시 누르세요  ✕"), ms=9000,
                             action=(T("PowerToys 받기"), lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(ptlink.STORE_URL))))
            return False
        try:
            ok, why = ptlink.link(os.path.dirname(BIN_DIR), self._pt_cmd())
        except Exception as ex:
            log.exception("PowerToys 연결 실패")
            self.show_notice(T("⚠ PowerToys 연결 실패: {0}  ✕").format(ex), ms=10000)
            return False
        if not ok:
            msg = {"admin": T("4Dir 가 관리자 권한으로 실행 중이라 PowerToys 설정을 바꾸지 않았습니다 — 보통 권한으로 다시 켜 주세요")}.get(why, why)
            self.show_notice("⚠ " + msg + "  ✕", ms=10000)
            return False
        if ptlink.kbm_enabled() is False:
            self.show_notice(T("연결했습니다. PowerToys 설정에서 '키보드 관리자'를 켜야 동작합니다  ✕"), ms=15000,
                             action=(T("키보드 관리자 켜러 가기"), ptlink.open_kbm_settings))
        elif not ptlink.running():
            self.show_notice(T("연결했습니다. PowerToys 를 실행하면 Win+E 가 4Dir 를 엽니다  ✕"), ms=12000)
        else:
            self.show_notice(T("연결했습니다 — 이제 Win+E 를 누르면 4Dir 새 창이 열립니다  ✕"), ms=9000)
        return True

    def reg_toggle(self):
        """기본 방식 칸의 [연결]/[끊기] (0.9.120 빌드 2 — 두 칸을 따로 시험할 수 있게)"""
        try:
            if winhook.ours():
                winhook.disable()
                self.show_notice(T("기본 방식 Win+E 연결을 끊었습니다  ✕"), ms=6000)
            elif datadir.PACKAGED:
                self.show_notice(T("스토어판에서는 아직 Win+E 연결을 쓸 수 없습니다  ✕"), ms=6000)
            else:
                winhook.enable(os.path.dirname(BIN_DIR))
                self.show_notice(T("이제 Win+E 를 누르면 4Dir 가 열립니다  ✕"), ms=6000)
        except Exception as ex:
            log.exception("기본 방식 Win+E 바꾸기 실패")
            self.show_notice(T("⚠ 바꾸지 못했습니다: {0}  ✕").format(ex), ms=8000)

    def pt_toggle(self):
        """PowerToys 칸의 [지금 연결]/[끊기]"""
        if ptlink.linked():
            try:
                ptlink.unlink()
                self.show_notice(T("PowerToys 에서 Win+E 연결을 지웠습니다  ✕"), ms=6000)
            except Exception as ex:
                log.exception("PowerToys 연결 끊기 실패")
                self.show_notice(T("⚠ 바꾸지 못했습니다: {0}  ✕").format(ex), ms=8000)
            return
        self.pt_link()

    def open_pt_guide(self, parent=None):
        import ptguide
        prog, args, start = ptlink.launch_parts(os.path.dirname(BIN_DIR), self._pt_cmd())
        dlg = ptguide.PtGuide(parent or self, prog, args, start, on_auto=None if datadir.PACKAGED else self.pt_link)
        dlg.exec()

    def toggle_winE(self):
        """체크 하나 (0.9.120): 켜기 = 윈도우 버전에 맞는 방식 하나, 끄기 = 두 방식 모두 끊음 (사용자 11/10 '체크만 끄면 끊어져야')"""
        root = os.path.dirname(BIN_DIR)
        try:
            if self.winE_on():
                a = winhook.disable() if winhook.ours() else False
                b = ptlink.unlink() if ptlink.exe_path() or ptlink.linked() else False
                log.info("Win+E 끔 (기본 방식 %s, PowerToys %s)", a, b)
                self.show_notice(T("Win+E 는 다시 윈도우 탐색기를 엽니다  ✕"), ms=6000)
                return
            method = self.winE_method()
            log.info("Win+E 켬 — 윈도우 %s → 방식 %s", ptlink.windows_info()[0], method)
            if method == "pt":
                self.pt_link()
                return
            if datadir.PACKAGED:   # 0.9.114 빌드 2: 스토어판은 레지스트리가 앱 안에 갇혀 Win+E 연결이 안 됨
                self.show_notice(T("스토어판에서는 아직 Win+E 연결을 쓸 수 없습니다  ✕"), ms=6000)
                return
            winhook.enable(root)
            self.show_notice(T("이제 Win+E 를 누르면 4Dir 가 열립니다  ✕"), ms=6000)
        except Exception as ex:
            log.exception("Win+E 설정 실패")
            self.show_notice(T("⚠ 바꾸지 못했습니다: {0}  ✕").format(ex), ms=8000)

    def open_tag_view(self, tag):
        return self.pane().add_tab(search_path(tags.TAG_Q + tag), activate=True)

    def open_set_view(self, name):
        return self.pane().add_tab(search_path(tags.SET_Q + name), activate=True)

    def _fill_tags_menu(self, tm):
        tm.clear()
        for t in TAGS.all_tags():
            tm.addAction(f"{t}  ({TAGS.count(t)})", lambda t=t: self.open_tag_view(t))
        if not TAGS.tags:
            a = tm.addAction(T("(태그 없음 — 파일 우클릭 ▸ 태그)"))
            a.setEnabled(False)
            return
        tm.addSeparator()
        dm = tm.addMenu(T("태그 지우기"))
        for t in TAGS.all_tags():
            dm.addAction(t, lambda t=t: (TAGS.delete_tag(t), refresh_tags_ui()))

    def _fill_sets_menu(self, sm):
        sm.clear()
        for n in TAGS.all_sets():
            sm.addAction(f"📚 {n}  ({len(TAGS.sets[n])})", lambda n=n: self.open_set_view(n))
        if TAGS.sets:
            sm.addSeparator()
        sm.addAction(T("새 가상 그룹…"), self._new_set)
        if TAGS.sets:
            dm = sm.addMenu(T("가상 그룹 지우기 (파일은 그대로)"))
            for n in TAGS.all_sets():
                dm.addAction(n, lambda n=n: TAGS.delete_set(n))

    def _new_set(self):
        name, ok = QtWidgets.QInputDialog.getText(self, T("새 가상 그룹"), T("가상 그룹 이름 (흩어진 파일을 한곳에 모아 보기 — 진짜 파일은 그대로)"))
        if ok and name.strip():
            TAGS.new_set(name.strip())
            self.open_set_view(name.strip())

    def open_loc(self, p, line=None):
        """0.9.116 새 도구들 공통: 그 파일이 있는 폴더를 새 탭으로 열고 파일 고르기 (폴더면 그 폴더). line 은 무시"""
        if not p:
            return
        if os.path.isdir(p):
            self.pane().add_tab(p, activate=True)
        else:
            nv = self.pane().add_tab(os.path.dirname(p), activate=True)
            nv.pending_select = os.path.basename(p)
        log.info("도구에서 위치 열기 %s", p)
        self.raise_()
        self.activateWindow()

    def open_oplog(self):
        return open_tool(oplog.open_dialog, self, LOG_DIR, open_loc=self.open_loc)

    def find_dupes(self, v=None):
        """중복 파일 찾기 (빌드 20): 고른 폴더들(없으면 지금 폴더) 아래에서 내용이 같은 파일 → 창에서 골라 휴지통으로"""
        v = v or (self.pane().view() if self.pane() else None)
        if v is None or v.path == THIS_PC or is_search(v.path) or devices.is_dev(v.path) or archives.is_arc(v.path) or not os.path.isdir(v.path):
            self.show_notice(T("⚠ 폴더 안에서만 쓸 수 있습니다 (내 PC·검색 결과 제외)"))
            return
        roots = [p for p in v.selected_paths() if os.path.isdir(p)] or [v.path]

        open_loc = self.open_loc

        def trash(ps, after):
            shellops.delete(self.hwnd_int(), ps, done=lambda res, ab: after())
        dlg = dupes.DupeDialog(roots, open_loc, trash, self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.setStyleSheet(self.styleSheet())
        dlg.show()

    def hwnd_int(self):
        try:
            return int(self.winId())
        except Exception:
            return 0

    def toggle_preview(self):
        """미리보기 버튼·Alt+P (메모와 같게): 꺼져 있으면 켬, 다른 창 뒤에 숨어 있으면 앞으로, 보고 있던 중이면 끔"""
        if SETTINGS["preview_pane"] and PREVIEW_WIN is not None and PREVIEW_WIN.isVisible() and not PREVIEW_WIN.was_front():
            PREVIEW_WIN.bring_front()
            if getattr(self, "act_preview", None) is not None:
                self.act_preview.setChecked(True)
            log.info("미리보기 창 앞으로")
            return
        self.set_preview(not (SETTINGS["preview_pane"] and PREVIEW_WIN is not None and PREVIEW_WIN.isVisible()))

    # ---------------------------------------------------------- 메모 창 (v0.9.108)
    def folder_memo_check(self, path):
        """폴더 메모 (빌드 13): 그 폴더에 붙인 메모가 있으면 알림 줄 + [메모 보기]"""
        if not path or MEMOS is None and not os.path.exists(os.path.join(DATA_DIR, memo.FILE)):
            return
        ms = memo_store().for_folder(path)
        if not ms:
            return
        log.info("폴더 메모 %s → %d장", path, len(ms))
        mid = ms[0]["id"]

        def show():
            self.set_memo(True)
            MEMO_WIN.bring_front()
            MEMO_WIN.panel.reveal(mid)
        names = ", ".join((m.get("title") or "") for m in ms[:3])
        self.show_notice(T("📝 이 폴더 메모: {0}").format(names), action=(T("메모 보기"), show))

    def toggle_calc(self):
        """계산기 창 (0.9.111): 없으면 열고, 뒤에 숨었으면 앞으로, 앞에 있으면 닫기"""
        global CALC_WIN
        if CALC_WIN is not None and CALC_WIN.isVisible():
            if CALC_WIN.isActiveWindow():
                CALC_WIN.close()
                log.info("계산기 닫음")
                return
            CALC_WIN.raise_()
            CALC_WIN.activateWindow()
            return
        if CALC_WIN is None:
            CALC_WIN = calc.CalcWindow(SETTINGS)
            CALC_WIN.setWindowIcon(self.windowIcon())
        CALC_WIN.apply_theme(bool(SETTINGS["dark"]))   # 빌드 6: 4Dir 양식을 덮어씌우면 계산기 디자인이 지워짐(회색 기본 단추) → 계산기 것만
        if not (SETTINGS["calc_geo"] and len(SETTINGS["calc_geo"]) == 5):   # 빌드 6: 예전 크기면 4Dir 창 옆에 새로
            g = self.geometry()
            CALC_WIN.move(g.right() - CALC_WIN.width() - 40, g.top() + 80)
        CALC_WIN.show()
        CALC_WIN.raise_()
        CALC_WIN.activateWindow()
        CALC_WIN.expr.setFocus()
        log.info("계산기 열기")
        return CALC_WIN

    def toggle_memo(self):
        """📌 버튼·Alt+M·도구 메뉴 (빌드 10 사용자 '뒤에 숨으면 껐다 켜야 올라옴'): 꺼져 있으면 켬, 뒤에 숨어 있으면 앞으로, 보고 있던 중이면 끔"""
        if SETTINGS["memo_on"] and MEMO_WIN is not None and MEMO_WIN.isVisible() and not MEMO_WIN.was_front():
            MEMO_WIN.bring_front()
            self.btn_memo.setChecked(True)
            log.info("메모 창 앞으로")
            return
        self.set_memo(not SETTINGS["memo_on"])

    def set_memo(self, on, save=True):
        """메모 창 켜기/끄기 — 빌드 8 사용자 11/5 '아예 밖으로 빼자, 열 때 칸 크기가 바뀌는 건 싫다' → 4Dir 창 옆 따로 창 하나.
        모든 4Dir 창이 같은 메모 창을 씀. 위치·크기 기억"""
        global MEMO_WIN
        on = bool(on)
        if on and MEMO_WIN is None:
            MEMO_WIN = MemoWindow(self)
        if MEMO_WIN is not None:
            if on:
                MEMO_WIN.setStyleSheet(self.styleSheet())
                MEMO_WIN.show_near(self)
                MEMO_WIN.bring_front()
            else:
                MEMO_WIN.hide()
        SETTINGS["memo_on"] = on
        for w in list(WINDOWS) + ([self] if self not in WINDOWS else []):   # 만드는 중인 창(아직 목록에 없음)도
            w.btn_memo.setChecked(on)
            w.memo_panel = MEMO_WIN.panel if MEMO_WIN is not None else None
        if save:
            log.info("메모 창 %s", on)
            self.save_timer.start()

    # ---------------------------------------------------------- 공용 탐색 창 (v0.9.100 이슈 #3)
    def set_shared_side(self, on, save=True):
        """창 왼쪽 전체 높이 탐색 창 하나 — 고른 폴더는 마지막으로 고른 칸(active_pane)으로. 켜면 칸별 탐색 창은 숨김(설정은 남김)"""
        on = bool(on)
        if on and self.shared_side is None:
            self.shared_side = Sidebar()
            self.shared_side.go.connect(lambda p: self._shared_go(p, False))
            self.shared_side.goNewTab.connect(lambda p: self._shared_go(p, True))
            self.shared_host.layout().addWidget(self.shared_side)
        SETTINGS["side_shared"] = on
        if on and save:   # 메뉴에서 '공용'을 고르면 숨김 풀고 보임
            SETTINGS["side_shared_hidden"] = False
        self.shared_host.setVisible(on and not SETTINGS["side_shared_hidden"])
        if on and self.shared_host.isVisibleTo(self):   # 이슈 #4: 시작 때는 창이 아직 안 보여 isVisible() 이 거짓 → 폭 적용을 건너뛰던 것
            self._apply_shared_w()
        for p in self.panes:
            p.set_sidebar(getattr(p, "side_on", False), save=False)
        if on:
            self.sync_shared_side()
        if save:
            log.info("공용 탐색 창 %s (폭 %s, 숨김 %s)", on, SETTINGS["side_shared_w"], SETTINGS["side_shared_hidden"])
            for w in list(WINDOWS):   # 다른 창도 같게 (전역 설정)
                if w is not self:
                    w.set_shared_side(on, save=False)
            self.save_timer.start()

    def _apply_shared_w(self):
        """공용 탐색 창 폭 = 저장한 값 (창 폭이 허락하는 만큼). 창이 아직 안 보이면 처음 보일 때 다시 (showEvent)"""
        w = max(120, int(SETTINGS["side_shared_w"] or 240))
        total = sum(self.lsplit.sizes())
        if not self.isVisible() or total <= 0:
            self._shared_w_pending = True
            total = total or max(self.width(), 1000)
        w = min(w, max(120, total - 200))
        self.lsplit.setSizes([w, max(total - w, 200)])

    def toggle_shared_visible(self):
        """공용 모드인 채로 공용 탐색 창만 숨기기/보이기 (v0.9.101 사용자 11/5) — 모든 창 같이"""
        if not SETTINGS["side_shared"]:
            return
        SETTINGS["side_shared_hidden"] = not SETTINGS["side_shared_hidden"]
        log.info("공용 탐색 창 %s", "숨김" if SETTINGS["side_shared_hidden"] else "보임")
        for w in list(WINDOWS) or [self]:
            w.set_shared_side(True, save=False)
        if self not in WINDOWS:
            self.set_shared_side(True, save=False)
        self.save_timer.start()

    def _shared_moved(self, *_):
        sizes = self.lsplit.sizes()
        if self.shared_host.isVisible():
            SETTINGS["side_shared_w"] = sizes[self.lsplit.indexOf(self.shared_host)]


    def _shared_go(self, path, new_tab):
        """공용 탐색 창에서 고른 폴더 → 대상 칸(마지막으로 고른 보이는 칸). 잠긴 탭은 칸의 이동 규칙대로 새 탭"""
        p = self.active_pane if (self.active_pane in self.panes and self.active_pane.isVisible()) else \
            next((x for x in self.panes if x.isVisible()), self.panes[0])
        log.info("공용 탐색 창 -> 칸 %d %s%s", p.idx, path, " (새 탭)" if new_tab else "")
        p.go(path, new_tab=new_tab)

    def sync_shared_side(self):
        if self.shared_side is not None and self.shared_host.isVisibleTo(self):   # 0.9.110: 창 보이기 전(시작 때 apply_state)에도 (#6 점검)
            ap = getattr(self, "active_pane", None)   # 0.9.110: 시작 중(활성 칸 정하기 전)에도 불림
            v = ap.view() if ap is not None else None
            if v is not None:
                self.shared_side.reveal(v.path)

    def _fill_main_view_menu(self, m):
        self.pane().fill_view_menu(m)
        m.addSeparator()
        sm = m.addMenu(T("탐색 창"))   # v0.9.100 칸마다 / 공용
        g = QtGui.QActionGroup(sm)
        for on, lbl in ((False, T("칸마다 (각 칸 왼쪽, ☰ 버튼)")), (True, T("공용 (창 왼쪽 하나, 고른 칸으로 열림)"))):
            a = sm.addAction(lbl, lambda on=on: self.set_shared_side(on))
            a.setCheckable(True)
            a.setChecked(bool(SETTINGS["side_shared"]) == on)
            g.addAction(a)
        sm.addSeparator()   # v0.9.101 공용 모드인 채로 숨기기
        a = sm.addAction(mlabel(T("공용 탐색 창 보이기"), "toggle_nav"), self.toggle_shared_visible)
        a.setCheckable(True)
        a.setChecked(bool(SETTINGS["side_shared"]) and not SETTINGS["side_shared_hidden"])
        a.setEnabled(bool(SETTINGS["side_shared"]))
        pv = m.addAction(T("미리보기 창") + (("	" + key_text("toggle_preview")) if key_text("toggle_preview") else ""),
                         lambda: self.toggle_preview())
        pv.setCheckable(True)
        pv.setChecked(self.preview.isVisible())
        fav = m.addAction(T("즐겨찾기 바 펼치기"), self.favbar.toggle)
        fav.setCheckable(True)
        fav.setChecked(self.favbar.expanded)
        fav.setEnabled(bool(SETTINGS["show_favbar"]))
        fl = m.addAction(T("즐겨찾기 줄 보이기"), lambda: self.toggle_setting("show_favbar"))   # 0.9.116 빌드 2
        fl.setCheckable(True)
        fl.setChecked(bool(SETTINGS["show_favbar"]))
        mon = m.addAction(T("CPU·GPU 사용량 표시"), lambda: self.set_sysmon(not SETTINGS["sysmon"]))
        mon.setCheckable(True)
        mon.setChecked(SETTINGS["sysmon"])
        top = m.addAction(T("항상 위"), self.toggle_on_top)
        top.setCheckable(True)
        top.setChecked(SETTINGS["on_top"])
        set_menu_tips(m)
        # v0.9.103: 화면 테마·언어·색상·창 여러 개 열기는 '설정' 메뉴로

    def open_settings(self, page=None):
        """설정 창 (v0.9.104) — 창마다 하나, 이미 열려 있으면 앞으로"""
        dlg = getattr(self, "settings_dlg", None)
        try:
            alive = dlg is not None and dlg.isVisible()
        except RuntimeError:
            alive = False
        if not alive:
            dlg = SettingsDialog(self)
            dlg.setStyleSheet(self.styleSheet())
            self.settings_dlg = dlg
            dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        if page:
            dlg.show_page(page)
        return dlg

    def _fill_settings_menu(self, m):
        """메뉴줄 '설정' (v0.9.103 사용자 11/5: 설정 관련은 한곳에) — 보기·도구에 흩어져 있던 설정을 모음"""
        m.clear()
        m.addAction(T("단축키 설정…"), self.open_keys)
        m.addAction(T("색상 설정…"), self.open_colors)
        m.addAction(T("검색 범위 설정…"), self.open_search_roots)
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
        m.addSeparator()   # 동작
        for key, lbl in (("hide_single_tab", T("탭이 하나면 탭 줄 숨기기 (새 탭: Ctrl+T)")),
                         ("tab_multirow", T("탭이 넘치면 여러 줄로")),
                         ("empty_click_up", T("빈 곳을 더블클릭하면 상위 폴더로")),
                         ("arc_browse", T("압축 파일(ZIP·7Z·RAR…)을 두 번 누르면 4Dir 안에서 폴더처럼 열기")),
                         ("folder_size", T("폴더 크기 계산 (크기 칸 — 네트워크 드라이브 제외)")),
                         ("keep_favbar", T("메뉴줄을 접어도 즐겨찾기 줄은 보이기"))):
            a = m.addAction(lbl, lambda key=key: self.toggle_setting(key))
            a.setCheckable(True)
            a.setChecked(bool(SETTINGS[key]))
        multi = m.addAction(T("창 여러 개 열기 허용"), self.toggle_multi)
        multi.setCheckable(True)
        multi.setChecked(SETTINGS["allow_multi"])
        multi.setToolTip(T("끄면 4Dir 는 하나만 실행되고, 다시 실행하면 기존 창이 앞으로 나옵니다"))
        a = m.addAction(T("시작할 때 새 버전 확인 (하루 한 번)"))
        a.setCheckable(True)
        a.setChecked(bool(SETTINGS["update_check"]))
        a.toggled.connect(lambda on: SETTINGS.__setitem__("update_check", on))
        a = m.addAction(T("재부팅 후 다시 열기 (켜 둔 채 윈도우를 끄면 다음 로그인 때)"))
        a.setCheckable(True)
        a.setChecked(bool(SETTINGS["resume_after_reboot"]))
        a.toggled.connect(lambda on: (SETTINGS.__setitem__("resume_after_reboot", on), log.info("재부팅 후 다시 열기 %s", on)))
        m.addAction(T("겹침 아이콘 순서 정리 (윈도우)…"), self.open_overlay_order)
        m.addSeparator()   # 백업
        m.addAction(T("설정 내보내기 (백업 파일로 저장)…"), self.export_settings)
        m.addAction(T("설정 가져오기 (백업 파일에서 되돌리기)…"), self.import_settings)
        m.addSeparator()   # v0.9.104 정보 (메뉴줄엔 안 보이지만 명령 찾기가 이 목록을 씀)
        m.addAction(T("사용법…"), self.open_guide)
        m.addAction(T("새 버전 확인"), lambda: start_update_check(self, manual=True))
        m.addAction(T("로그 폴더 열기"), lambda: os.startfile(LOG_DIR))
        m.addAction(T("문제 보고용 로그 저장… (4Dir 폴더의 reports 에 zip)"), self.save_report)
        set_menu_tips(m)

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
        if ev.type() == QtCore.QEvent.ActivationChange and self.isActiveWindow() and getattr(self, "preview", None) is not None:
            self.preview.schedule(self)   # 빌드 18: 다른 4Dir 창을 쓰면 미리보기도 그 창의 고른 파일로
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
        if t == QtCore.QEvent.KeyPress and (ev.modifiers() & Qt.AltModifier or ev.nativeScanCode() == 0x0D) \
                and obj is QtWidgets.QApplication.focusWidget() and isinstance(obj, QtWidgets.QWidget) and obj.window() is self:
            # 0.9.112 빌드 4 진단: Alt+= 반응 없음 → 기록에 vk=0x17(입력기 전자/반자) 확인 → 빌드 5 기본 키 Ctrl+= (단축키로 처리되면 여기 안 옴)
            log.info("Alt·= 키 입력 %s (key=0x%x vk=0x%x scan=0x%x 글자=%r, 위젯 %s)", keymap.event_key(ev), ev.key(),
                     ev.nativeVirtualKey(), ev.nativeScanCode(), ev.text(), type(obj).__name__)
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
        if t == QtCore.QEvent.MouseButtonPress and ev.button() in (Qt.BackButton, Qt.ForwardButton) and \
                keymap.mouse_action(SETTINGS["mouse"], keymap.mouse_combo(ev.button(), ev.modifiers())) != keymap.BUILTIN:
            w = obj if isinstance(obj, QtWidgets.QWidget) else None
            if w is None or w.window() is not self:
                return super().eventFilter(obj, ev)
            p = w
            while p is not None and not isinstance(p, Pane):
                p = p.parentWidget()
            pg = (p or self.pane()).view()
            if pg is None:
                return True
            lv = pg.view()
            vp = lv.viewport()
            inside = vp is w or vp.isAncestorOf(w)   # 목록 안에서 눌렀으면 그 자리 파일에, 밖이면 지금 고른 것에
            pg.mouse_override(lv, ev, vp.mapFromGlobal(ev.globalPosition().toPoint()) if inside else None)
            return True
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
        return self.open_settings("keys")   # v0.9.105 사용자 11/5: 따로 띄우지 않고 설정 창 안에서

    def keys_panel(self):
        """설정 창 '단축키·마우스' 안에 넣는 단축키 창 (v0.9.105) → (창, 끝났을 때)"""
        dlg = keymap.KeyDialog(SETTINGS["keys"], self, mouse=SETTINGS["mouse"])

        def done(r):
            if r and dlg.result_keys is not None:
                SETTINGS["keys"] = dlg.result_keys
                SETTINGS["mouse"] = dlg.result_mouse or {}
                log.info("마우스 버튼 지정 %s", SETTINGS["mouse"])
                for w in WINDOWS or [self]:
                    w.apply_keys()
                hotkey_register()   # 어디서나 단축키도 새 키로
                self.show_notice(T("단축키를 저장했습니다  ✕"), ms=1000)
        return dlg, done

    def toggle_breadcrumb(self):
        SETTINGS["breadcrumb"] = not SETTINGS["breadcrumb"]
        for p in self.all_panes():
            p.set_breadcrumb(SETTINGS["breadcrumb"])
        log.info("경로 버튼(브레드크럼) %s", SETTINGS["breadcrumb"])

    # ---------------------------------------------------------- 닫은 탭 다시 열기 / 다른 칸
    def note_drive(self, path):
        """그 드라이브의 '꺼내도 되나?' 알림을 받게 등록 (v0.9.96, 11/5 사용자: 4Dir 가 외장하드를 잡고 있어 '사용 중' 꺼내기 실패).
        탐색기처럼 드라이브 뿌리에 빈 핸들 하나 열고 RegisterDeviceNotification → 알림 오면 release_drive 로 감시를 풂"""
        d = os.path.splitdrive(path)[0].upper()
        if len(d) != 2 or d[1] != ":" or d in self._dev_notes or d == os.environ.get("SystemDrive", "C:").upper():
            return
        k = ctypes.windll.kernel32
        if k.GetDriveTypeW(d + "\\") not in (2, 3):   # 이동식·고정만 (네트워크·CD 제외)
            return
        k.CreateFileW.restype = ctypes.c_void_p
        h = k.CreateFileW(d + "\\", 0, 7, None, 3, 0x02000000, None)   # 권한 없이 열기만, 공유 전부, OPEN_EXISTING, BACKUP_SEMANTICS
        if not h or h == ctypes.c_void_p(-1).value:
            log.info("꺼내기 알림 등록 못 함 %s (열기 실패)", d)
            return

        class DBH(ctypes.Structure):
            _fields_ = [("size", ctypes.c_uint32), ("type", ctypes.c_uint32), ("res", ctypes.c_uint32),
                        ("handle", ctypes.c_void_p), ("notify", ctypes.c_void_p), ("guid", ctypes.c_byte * 16),
                        ("nameoff", ctypes.c_long), ("data", ctypes.c_byte * 1)]
        f = DBH(ctypes.sizeof(DBH), 6, 0, h)
        u = ctypes.windll.user32
        u.RegisterDeviceNotificationW.restype = ctypes.c_void_p
        n = u.RegisterDeviceNotificationW(ctypes.c_void_p(int(self.winId())), ctypes.byref(f), 0)
        if not n:
            k.CloseHandle(ctypes.c_void_p(h))
            log.info("꺼내기 알림 등록 실패 %s", d)
            return
        self._dev_notes[d] = (h, n)
        log.info("꺼내기 알림 등록 %s", d)

    def _drop_note(self, d):
        v = self._dev_notes.pop(d, None)
        if v:
            ctypes.windll.user32.UnregisterDeviceNotification(ctypes.c_void_p(v[1]))
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(v[0]))

    def refresh_drives(self):
        """드라이브가 생기거나 없어짐 (v0.9.95) → '내 PC' 를 보고 있는 탭과 탐색 창의 '내 PC' 아래를 다시 읽음"""
        n, gone = 0, []
        have = {d.upper() for d in os.listdrives()}
        for p in self.panes:
            for v in p.views():
                if v.path == THIS_PC:
                    v.reload(reason="drive")
                    n += 1
                    continue
                d = os.path.splitdrive(v.path)[0]
                if len(d) == 2 and d[1] == ":" and not is_search(v.path) and (d.upper() + "\\") not in have:
                    # v0.9.96: 뺀 드라이브에 있던 탭 → 내 PC (전엔 옛 목록이 그대로 남아 폴더를 열면 '찾을 수 없음', 11/5 사용자 제보)
                    gone.append(v.path)
                    v.navigate(THIS_PC, select=d.upper() + "\\", force=True)
            if p.side is not None:
                p.side.refresh_pc()
        if self.shared_side is not None:   # v0.9.100 공용 탐색 창
            self.shared_side.refresh_pc()
        if SEARCH is not None:
            SEARCH.rewatch()   # 다시 꽂은 드라이브의 검색 감시
        log.info("드라이브 바뀜 → 내 PC 탭 %d개 다시 읽음, 뺀 드라이브 탭 → 내 PC %s, 드라이브 %s", n, gone, os.listdrives())


    def _devnode_check(self):
        """장치 연결이 바뀜 → 1.5초·5초 뒤 휴대폰 목록을 보고, 달라졌으면 내 PC 다시 읽기 (빌드 5, 사용자 '휴대폰 다시 연결했는데 안 보임')"""
        if not hasattr(self, "_devnode_timer"):
            self._devnode_timer = QtCore.QTimer(self)
            self._devnode_timer.setSingleShot(True)
            self._devnode_timer.timeout.connect(self._devices_changed)
            self._devnode_late = QtCore.QTimer(self)
            self._devnode_late.setSingleShot(True)
            self._devnode_late.timeout.connect(self._devices_changed)
        self._devnode_timer.start(1500)   # 휴대폰은 잠금 풀고 '파일 전송'을 고른 뒤에야 셸에 나타남 → 두 번 봄
        self._devnode_late.start(5000)

    def _devices_changed(self):
        if self is not (WINDOWS[0] if WINDOWS else self):
            return   # 창이 여러 개면 한 창만 확인 (refresh_drives 가 모든 창을 다시 읽음)
        now = tuple(sorted(n for n, _p in devices.list_devices()))
        old = getattr(Main, "_last_devices", None)
        Main._last_devices = now
        if now == old:
            # 빌드 6 사용자: '파일 전송'을 고르기 전엔 저장공간이 없음 → 고른 뒤에도 이름은 같아 다시 안 읽었음.
            # 장치 연결이 바뀌었으니 휴대폰을 보고 있는 칸·탐색 창의 휴대폰 아래는 다시 읽음
            if now:
                n = 0
                for w in list(WINDOWS):
                    for p in w.panes:
                        for v in p.views():
                            if devices.is_dev(v.path) and v.active:
                                v.reload("devnode")
                                n += 1
                    for sb in [p.side for p in w.panes] + [getattr(w, "shared_side", None)]:
                        if sb is not None:
                            sb.reset_devices()
                log.info("장치 연결 바뀜(이름 같음) → 휴대폰 칸 %d개 다시 읽음", n)
            return
        log.info("휴대폰 등 장치 바뀜 %s → %s", list(old), list(now))
        if len(now) < len(old):   # 빠진 장치 → 휴대폰 안을 보던 탭은 내 PC 로 (드라이브 뺄 때와 같게)
            for w in list(WINDOWS):
                for p in w.panes:
                    for v in p.views():
                        if devices.is_dev(v.path):
                            v.navigate(THIS_PC, force=True)
        for w in list(WINDOWS) or [self]:
            w.refresh_drives()

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
        if any(archives.is_arc(p) or devices.is_dev(p) for p in paths):   # 0.9.110 점검: FTP·압축 안 경로를 os.rename 하려다 전부 실패하던 것
            self.show_notice(T("⚠ 이름 일괄 변경은 이 PC 폴더에서만 됩니다 (FTP·압축 안·휴대폰 제외)  ✕"), ms=6000)
            return

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

    def compare_panes(self):
        """두 칸 비교 (v0.9.89 사용자 11/4): 지금 칸과 다른 칸(직전에 쓰던 칸) 폴더를 이름으로 맞춰 봄 (하위 폴더 안까지는 안 봄).
        이쪽에만·이쪽이 새것 = 굵은 색 글자 + 골라 둠 → F6 이면 그것만 반대쪽으로 복사. 목록을 다시 읽으면 표시가 지워짐"""
        a = self.pane()
        b = self.other_pane(a) if a else None
        va, vb = (a.view() if a else None), (b.view() if b else None)
        bad = lambda v: v is None or v.path == THIS_PC or is_search(v.path)
        if bad(va) or bad(vb):
            self.show_notice(T("⚠ 비교할 다른 칸이 없습니다 — 두 칸에 폴더를 열어 두세요  ✕"), ms=6000)
            return
        if os.path.normcase(va.path) == os.path.normcase(vb.path):
            self.show_notice(T("⚠ 두 칸이 같은 폴더입니다  ✕"), ms=5000)
            return

        def kind(x, y):
            if y is None:
                return "only"
            if x[1] or y[1]:
                return None if x[1] and y[1] else "diff"   # 폴더끼리는 이름만, 폴더↔파일이면 다름
            if abs(x[3] - y[3]) <= 2:   # FAT·네트워크 드라이브는 2초 단위
                return None if x[2] == y[2] else "diff"
            return "newer" if x[3] > y[3] else "older"
        res = []
        A = {e[0].lower(): e for e in va.model_.all}
        B = {e[0].lower(): e for e in vb.model_.all}
        for v, mine, other in ((va, A, B), (vb, B, A)):
            m = v.model_
            m.cmp = {e[0]: k for key, e in mine.items() if (k := kind(e, other.get(key)))}
            sel = QtCore.QItemSelection()
            for r, e in enumerate(m.rows):
                if m.cmp.get(e[0]) in ("only", "newer"):
                    sel.select(m.index(r, 0), m.index(r, 0))
            v.sel.select(sel, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
            if m.rows:
                m.dataChanged.emit(m.index(0, 0), m.index(len(m.rows) - 1, m.columnCount() - 1))
            cnt = {k: sum(1 for x in m.cmp.values() if x == k) for k in CMP_KIND}
            res.append(cnt)
            v.status.emit(T("비교: 이쪽에만 {0} · 이쪽이 새것 {1} · 반대쪽이 새것 {2} · 크기 다름 {3}  (골라 둔 {4}개 → F6 = 반대쪽에 복사)")
                          .format(cnt["only"], cnt["newer"], cnt["older"], cnt["diff"], cnt["only"] + cnt["newer"]))
        log.info("두 칸 비교 %s ↔ %s : %s / %s", va.path, vb.path, res[0], res[1])
        self._cmp_ctx = {"va": va, "vb": vb, "pa": va.path, "pb": vb.path, "A": A, "B": B}   # v0.9.107 내용까지 비교용
        flash_pane(a)
        flash_pane(b)   # 무엇끼리 비교했는지 보이게 (v0.9.90 사용자 11/4 '헷갈림')
        same = not any(any(c.values()) for c in res)
        self.show_notice((T("두 칸 비교: 차이 없음 (이름·날짜·크기 같음)") if same else
                          T("두 칸 비교: 칸 {0} 이쪽에만 {1}·새것 {2} / 칸 {3} 이쪽에만 {4}·새것 {5} — 골라 둔 것을 F6 으로 반대쪽에 복사")
                          .format(a.idx + 1, res[0]["only"], res[0]["newer"], b.idx + 1, res[1]["only"], res[1]["newer"])) + "  ✕",
                         ms=15000, action=(T("내용까지 비교"), self.compare_contents))

    def _cmp_pairs(self):
        """내용 비교할 짝: 양쪽에 같은 이름 파일이고 크기가 같은 것 (크기가 다르면 내용도 다름)"""
        c = self._cmp_ctx
        out = []
        for key, e in c["A"].items():
            o = c["B"].get(key)
            if o is not None and not e[1] and not o[1] and e[2] == o[2]:
                out.append((key, os.path.join(c["pa"], e[0]), os.path.join(c["pb"], o[0]), e[2] or 0))
        return out

    def compare_contents(self):
        """두 칸 비교 뒤 '내용까지 비교' (v0.9.107 사용자 11/5): 이름·크기 같은 파일을 실제로 읽어 맞춰 봄.
        내용 다름 = 빨강, 날짜만 다르고 내용 같음 = 회색('날짜만 다름', F6 고르기에서 뺌). 뒤 스레드 + 멈추기"""
        c = getattr(self, "_cmp_ctx", None)
        if not c or c["va"].path != c["pa"] or c["vb"].path != c["pb"]:
            self.show_notice(T("⚠ 두 칸 비교를 먼저 하세요 (Shift+F2)  ✕"), ms=6000)
            return None
        old = getattr(self, "_cmp_job", None)
        if old is not None:
            old.cancel()
        pairs = self._cmp_pairs()
        if not pairs:
            self.show_notice(T("내용 비교: 이름·크기가 같은 파일이 없습니다  ✕"), ms=6000)
            return None
        job = contentcmp.ContentCompare(pairs, self)
        self._cmp_job = job
        log.info("내용 비교 시작 %s ↔ %s : %d짝 %.1fMB", c["pa"], c["pb"], len(pairs), job.total / 1048576)

        def prog(n, total, done_b, total_b):
            if self._cmp_job is job:
                self.show_notice(T("내용 비교 중 {0}/{1}개 · {2} / {3}").format(n, total, size_short(done_b), size_short(total_b)),
                                 sticky=True, action=(T("멈추기"), job.cancel))
        job.progress.connect(prog)
        job.finished.connect(lambda res, stopped: self._cmp_apply(job, res, stopped))
        job.start()
        return job

    def _cmp_apply(self, job, res, stopped):
        if self._cmp_job is not job:
            return
        self._cmp_job = None
        c = self._cmp_ctx
        n_content = n_date = 0
        for v, mine, path in ((c["va"], c["A"], c["pa"]), (c["vb"], c["B"], c["pb"])):
            m = v.model_
            if v.path != path:   # 그새 다른 폴더로 감
                continue
            for key, r in res.items():
                e = mine.get(key)
                if e is None:
                    continue
                if r == "content" and m.cmp.get(e[0]) is None:   # 날짜·크기 같은데 내용 다름 (날짜가 다르면 '새것' 표시·F6 고르기 그대로)
                    m.cmp[e[0]] = "content"
                    n_content += 1
                elif r == "same" and m.cmp.get(e[0]) in ("newer", "older"):
                    m.cmp[e[0]] = "dateonly"
                    n_date += 1
            sel = QtCore.QItemSelection()
            for row, e in enumerate(m.rows):
                if m.cmp.get(e[0]) in ("only", "newer"):
                    sel.select(m.index(row, 0), m.index(row, 0))
            v.sel.select(sel, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
            if m.rows:
                m.dataChanged.emit(m.index(0, 0), m.index(len(m.rows) - 1, m.columnCount() - 1))
        n_same = sum(1 for v in res.values() if v == "same")
        n_err = sum(1 for v in res.values() if v == "error")
        self.show_notice(T("내용 비교{0}: 내용 다름 {1} (빨강) · 날짜만 다름 {2} (내용 같음) · 같음 {3}{4}").format(
            T(" (멈춤)") if stopped else "", n_content // 2, n_date // 2, n_same,
            T(" · 못 읽음 {0}").format(n_err) if n_err else "") + "  ✕", ms=15000)
        self.last_cmp_result = res

    def _extra_win_actions(self):
        """0.9.113 메뉴에만 있던 기능의 실행 (keymap.register 로 더한 id 와 짝)"""
        cv = lambda: self.pane().view() if self.pane() else None

        def sort(col=None, order=None):
            v = cv()
            if v:
                v.set_sort(v.model_.sort_col if col is None else col, v.model_.sort_order if order is None else order)

        def fav_import():
            n = FAV.reimport()
            self.show_notice(T('윈도우 탐색기 즐겨찾기에서 {0}개 가져옴 (이미 있던 것은 건너뜀)  ✕').format(n))
        acts = {}
        for k, _l, _px in VIEW_MODES:
            acts[f"view_{k}"] = (lambda k=k: self.pane().set_mode(k))
        for k, _l in SHOW_OPTS:
            acts[f"show_{k}"] = (lambda k=k: self.toggle_opt(k))
        for c, _l in SORT_COLS:
            acts[f"sort_{c}"] = (lambda c=c: sort(col=c))
        acts["sort_asc"] = lambda: sort(order=Qt.AscendingOrder)
        acts["sort_desc"] = lambda: sort(order=Qt.DescendingOrder)
        for k, _l in LAYOUTS:
            acts[f"layout_{k}"] = (lambda k=k: self.set_layout(k, equalize=True))
        acts["layout_custom"] = self.open_grid_dialog
        acts["side_shared"] = lambda: self.set_shared_side(not SETTINGS["side_shared"])
        acts["toggle_favbar"] = lambda: self.favbar.toggle()
        for k in range(6):   # 0.9.116 별점 (단축키는 '단축키 설정'에서)
            acts[f"rate_{k}"] = lambda k=k: self.pane().view() and self.pane().view().set_rating(None, k)
        acts["toggle_sysmon"] = lambda: self.set_sysmon(not SETTINGS["sysmon"])
        acts["toggle_on_top"] = lambda: self.toggle_on_top()
        acts["batch_rename"] = lambda: self.open_batch_rename(cv().selected_paths() if cv() else [])
        acts["explorer_check"] = lambda: self.open_check()
        acts["fav_organize"] = lambda: self.open_fav_organizer()
        acts["fav_import"] = fav_import
        acts["ws_save"] = lambda: self.save_workspace()
        acts["keys_settings"] = lambda: self.open_keys()
        acts["color_settings"] = lambda: self.open_colors()
        acts["search_roots"] = lambda: self.open_search_roots()
        for k, _l in THEMES:
            acts[f"theme_{k}"] = (lambda k=k: self.set_theme_mode(k))
        for k, _l in SET_TOGGLES:
            acts[f"set_{k}"] = (lambda k=k: self.toggle_setting(k))
        acts["set_allow_multi"] = lambda: self.toggle_multi()
        acts["overlay_order"] = lambda: self.open_overlay_order()
        acts["export_settings"] = lambda: self.export_settings()
        acts["import_settings"] = lambda: self.import_settings()
        acts["guide"] = lambda: self.open_guide()
        acts["check_update"] = lambda: start_update_check(self, manual=True)
        acts["open_logs"] = lambda: os.startfile(LOG_DIR)
        acts["save_report"] = lambda: self.save_report()
        return acts

    def run_named(self, a):
        """기능 id 하나 실행 (My메뉴·기능 검색 공용). 처리했으면 True"""
        sc = keymap.SCOPE.get(a)
        log.info("기능 실행 %s (%s)", a, sc)
        if sc == "view":
            v = self.pane().view() if self.pane() else None
            return bool(v) and v.run_action(a) is not False
        fn = self.win_actions.get(a)
        if fn is None:
            log.warning("기능 실행: 모르는 기능 %s", a)
            return False
        fn()
        return True

    def open_palette(self):
        """명령 찾기 (v0.9.89, Ctrl+Shift+P): 단축키 기능 + 위 메뉴 항목 전부"""
        dlg = getattr(self, "palette_dlg", None)   # 0.9.113 빌드 2: 따로 창 — 이미 열려 있으면 앞으로
        try:
            if dlg is not None and dlg.isVisible():
                dlg.raise_()
                dlg.activateWindow()
                dlg.edit.setFocus()
                dlg.edit.selectAll()
                return
        except RuntimeError:
            pass
        items, seen = [], set()
        descs = funcdesc.by_action()
        km = keymap.current(SETTINGS["keys"])
        for a, lbl, _k, sc in keymap.ACTIONS:
            if sc == "view":
                fn = (lambda a=a: self.pane().view() and self.pane().view().run_action(a))
            elif sc == "window" and a in self.win_actions and a != "palette":
                fn = self.win_actions[a]
            else:
                continue
            cat = dict(keymap.CATS).get(keymap.CAT.get(a, "tools"), "")
            items.append((lbl, ", ".join(km.get(a, [])), fn, cat, descs.get(a, "")))
            seen.add(lbl)
            if ": " in lbl:   # '보기: 큰 아이콘' 이 있으면 메뉴의 '큰 아이콘' 은 겹치니 뺌
                seen.add(lbl.split(": ", 1)[1])
            seen.add(lbl.split(" (")[0].rstrip("…"))
        self._pal_menus = []   # 메뉴 항목을 실행할 때까지 메뉴를 살려 둠

        def collect(menu, where):
            for act in menu.actions():
                if act.isSeparator() or not act.isEnabled() or not act.isVisible():
                    continue
                name = act.text().split("\t")[0].replace("&&", "\0").replace("&", "").replace("\0", "&").strip()
                if act.menu() is not None:
                    collect(act.menu(), f"{where} ▸ {name}")
                elif name and name not in seen:
                    seen.add(name)
                    items.append((name, "", act.trigger, where, funcdesc.tip_for(name, keymap.LABEL)))
        for title, filler in getattr(self, "top_menus", []):
            mm = QtWidgets.QMenu(self)
            try:
                filler(mm)
            except Exception:
                log.exception("명령 찾기: 메뉴 모으기 실패 %s", title)
                continue
            self._pal_menus.append(mm)
            collect(mm, title)
        order = {n: i for i, (_c, n) in enumerate(keymap.CATS)}   # 분류 순서대로 (메뉴에서 모은 것은 뒤)
        items.sort(key=lambda x: order.get(x[3], len(order)))
        dlg = palette.Palette(items, self)
        dlg.setStyleSheet(self.styleSheet())
        dlg.move(self.mapToGlobal(QtCore.QPoint(max(0, (self.width() - dlg.width()) // 2), 50)))
        log.info("기능 검색 열기 (항목 %d개)", len(items))
        self.palette_dlg = dlg
        dlg.show()
        dlg.edit.setFocus()

    def same_folder_other(self):
        """0.9.112 다른 칸에 지금 칸과 같은 폴더를 새 탭으로 (사용자 제보 11/6 '양쪽 폴더 위치 일치')"""
        a = self.pane()
        b = self.other_pane(a) if a else None
        va = a.view() if a else None
        if va is None or not va.path:
            return
        if b is None:
            self.show_notice(T("⚠ 다른 칸이 없습니다 — 칸을 둘 이상 보이게 하세요  ✕"), ms=6000)
            return
        log.info("다른 칸 새 탭에 같은 폴더 %s (칸 %d → %d)", va.path, a.idx + 1, b.idx + 1)
        b.add_tab(va.path)   # 빌드 4 (사용자 11/6): 다른 칸 지금 폴더는 그대로 두고 새 탭으로 더함
        self.active_pane = a
        self._paint_active()
        va.view().setFocus()
        self.show_notice(T("다른 칸 새 탭에 같은 폴더를 열었습니다  ✕"), ms=3000)

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
        if MEMO_WIN is not None:   # v0.9.108 메모지 색도 밝게/어둡게 (빌드 8: 따로 창)
            MEMO_WIN.setStyleSheet(self.styleSheet())
            MEMO_WIN.panel.restyle()
        if PREVIEW_WIN is not None:   # 빌드 18
            PREVIEW_WIN.setStyleSheet(self.styleSheet())

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
        self.searchbar.setVisible(not on)
        self.favbar.setVisible(bool(SETTINGS["show_favbar"]) and (not on or bool(SETTINGS["keep_favbar"])))   # v0.9.75: 접어도 즐겨찾기는 남길 수 있음 · 0.9.116: 줄째 숨기기
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
        return self.open_settings("colors")   # v0.9.105 설정 창 안에서

    def colors_panel(self):
        """설정 창 '색상' 안에 넣는 색상 설정 (v0.9.105) → (창, 끝났을 때 없음) — 바꾸면 바로 적용"""
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
        row.addWidget(rb)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        return dlg, None

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
            self.show_notice(T("창 구성 '{0}' 을(를) 읽지 못했습니다 (지금 구성은 그대로)  ✕").format(name))   # v0.9.98
            return False
        self.sessions.snapshot(self.collect_state(), force=True)   # 불러오기 전 지금 상태 보관
        log.info("작업 공간 불러오기 %s", path)
        self.apply_state(st, geometry=False)
        self.save_state()
        self.show_notice(T("창 구성 '{0}' 불러옴 (이전 상태는 '자동 기록'에 보관)  ✕").format(name))
        return True

    # v0.9.98 이슈 #1: 단축키로 창 구성 바로 전환 — 최근 저장한 것 · 지정 1 · 지정 2 (불러오기는 메뉴와 같은 load_workspace)
    def _ws_path(self, name):
        return os.path.join(WS_DIR, name + ".json")

    def load_ws_latest(self):
        """최근 저장한 창 구성 = 저장 파일 수정 시각 최신 (불러오기·이름 변경으로는 안 바뀜, 메뉴 목록 순서와 같음)"""
        ws = self._ws_list()
        if not ws:
            log.info("최근 창 구성 단축키: 저장본 없음")
            self.show_notice(T("저장된 창 구성이 없습니다. '창 저장/불러오기 ▸ 현재 창 구성 저장'으로 먼저 저장하세요  ✕"))
            return False
        log.info("최근 창 구성 단축키 → %s", ws[0][0])
        return self.load_workspace(*ws[0])

    def load_ws_slot(self, n):
        name = (SETTINGS["ws_slots"] or {}).get(str(n))
        if not name:
            log.info("지정 %d 단축키: 미지정", n)
            self.show_notice(T("지정 {0} 에 연결된 창 구성이 없습니다. '창 저장/불러오기 ▸ 지정 {0}(으)로 설정'에서 고르세요  ✕").format(n))
            return False
        p = self._ws_path(name)
        if not os.path.isfile(p):   # 다른 저장본으로 대신하지 않음
            log.info("지정 %d 단축키: 파일 없음 %s", n, p)
            self.show_notice(T("지정 {0} 의 창 구성 '{1}' 을(를) 찾을 수 없습니다 (지워졌거나 밖에서 이름이 바뀜)  ✕").format(n, name))
            return False
        log.info("지정 %d 단축키 → %s", n, name)
        return self.load_workspace(name, p)

    def set_ws_slot(self, n, name):
        slots = dict(SETTINGS["ws_slots"] or {})
        if name:
            slots[str(n)] = name
        else:
            slots.pop(str(n), None)
        SETTINGS["ws_slots"] = slots
        log.info("지정 %d = %s", n, name)
        self.show_notice((T("지정 {0} = '{1}'  ✕").format(n, name)) if name else T("지정 {0} 해제  ✕").format(n), ms=2000)

    def rename_workspace(self, name, path, new=None):
        """저장된 창 구성 이름 변경 — 같은 이름이 있으면 덮어쓰지 않음, 지정 1·2 연결은 따라감, 파일 시각 그대로(최근 순서 안 바뀜)"""
        if new is None:
            new, ok = QtWidgets.QInputDialog.getText(self, T("창 구성 이름 변경"), T("새 이름:"), text=name)
            if not ok:
                return False
        new = "".join(c for c in new.strip() if c not in '\\/:*?"<>|')
        if not new or new == name:
            return False
        dst = self._ws_path(new)
        if os.path.exists(dst) and os.path.normcase(dst) != os.path.normcase(path):
            log.info("창 구성 이름 변경 거부(같은 이름 있음) %s → %s", name, new)
            QtWidgets.QMessageBox.warning(self, T("창 구성 이름 변경"), T("같은 이름의 창 구성 '{0}' 이(가) 이미 있습니다. 다른 이름을 쓰세요.").format(new))
            return False
        os.rename(path, dst)
        slots = dict(SETTINGS["ws_slots"] or {})
        for k, v in list(slots.items()):
            if v == name:
                slots[k] = new
        SETTINGS["ws_slots"] = slots
        log.info("창 구성 이름 변경 %s → %s (지정 %s)", name, new, slots)
        self.show_notice(T("창 구성 이름 변경: '{0}' → '{1}'  ✕").format(name, new), ms=2000)
        return True

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

    def show_layout_popup(self):
        """레이아웃 고르기 창 (v0.9.92): 맥스 뷰포트 레이아웃처럼 그림 버튼 격자. 고르면 닫힘"""
        pop = LayoutPopup(self)
        b = self.layout_btn
        pop.adjustSize()
        gp = b.mapToGlobal(QtCore.QPoint(0, b.height()))
        scr = (b.screen() or QtWidgets.QApplication.primaryScreen()).availableGeometry()
        gp.setX(max(scr.left(), min(gp.x(), scr.right() - pop.width())))
        pop.move(gp)
        pop.show()
        self.layout_popup = pop   # 시험용
        log.info("레이아웃 고르기 창 (지금 %s)", self.layout_mode)
        return pop

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
        slots = SETTINGS["ws_slots"] or {}
        mark = {v: k for k, v in sorted(slots.items(), reverse=True)}
        for name, path in ws:
            tag = T("  [지정 {0}]").format(mark[name]) if name in mark else ""
            load.addAction(name + tag, lambda n=name, p=path: self.load_workspace(n, p))
            dele.addAction(name, lambda n=name, p=path: self.delete_workspace(n, p))
        # v0.9.98 이슈 #1: 단축키로 바로 불러오기 (키는 '단축키 설정'에서 정함)
        m.addSeparator()
        a = m.addAction(mlabel(T("최근 저장한 구성 불러오기 ({0})").format(ws[0][0] if ws else T("없음")), "ws_latest"), self.load_ws_latest)
        a.setEnabled(bool(ws))
        for n in (1, 2):
            m.addAction(mlabel(T("지정 {0} 불러오기 ({1})").format(n, slots.get(str(n)) or T("미지정")), f"ws_slot{n}"),
                        lambda n=n: self.load_ws_slot(n))
        for n in (1, 2):
            sm = m.addMenu(T("지정 {0}(으)로 설정").format(n))
            for name, path in ws:
                a = sm.addAction(name, lambda n=n, nm=name: self.set_ws_slot(n, nm))
                a.setCheckable(True)
                a.setChecked(slots.get(str(n)) == name)
            if not ws:
                sm.addAction(T("(저장된 창 구성 없음)")).setEnabled(False)
            sm.addSeparator()
            a = sm.addAction(T("지정 해제"), lambda n=n: self.set_ws_slot(n, None))
            a.setEnabled(bool(slots.get(str(n))))
        ren = m.addMenu(T("이름 변경"))
        for name, path in ws:
            ren.addAction(name, lambda n=name, p=path: self.rename_workspace(n, p))
        if not ws:
            ren.addAction(T("(저장된 창 구성 없음)")).setEnabled(False)
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
        mm = m.addAction(memo_icon(), mlabel(T("메모 창"), "toggle_memo"), lambda: self.toggle_memo())   # 빌드 9: 도구 맨 위
        mm.setCheckable(True)
        mm.setChecked(bool(SETTINGS["memo_on"]))
        m.addAction(mlabel(T("계산기"), "toggle_calc"), self.toggle_calc)   # 0.9.111
        m.addSeparator()
        sm = m.addMenu(T("창 저장/불러오기"))   # v0.9.103 메뉴줄에서 여기로
        sm.aboutToShow.connect(lambda: self._fill_session_menu(sm))
        m.addSeparator()
        m.addAction(T("Explorer Check (탐색기 점검)"), self.open_check)
        m.addAction(T("이름 일괄 변경…"), lambda: self.open_batch_rename(self.pane().view().selected_paths() if self.pane().view() else []))
        m.addAction(mlabel(T("두 칸 비교"), "compare"), self.compare_panes)
        m.addAction(mlabel(T("다른 칸 새 탭에 같은 폴더"), "same_folder"), self.same_folder_other)   # 0.9.112
        m.addAction(mlabel(T("패턴으로 고르기…"), "select_pattern"), lambda: self.pane().view() and self.pane().view().select_pattern())
        m.addAction(mlabel(T("하위 폴더 펼쳐 보기"), "flat_view"), lambda: self.pane().view() and self.pane().view().flat_view())   # 빌드 20
        m.addAction(mlabel(T("중복 파일 찾기…"), "find_dupes"), lambda: self.find_dupes(self.pane().view()))   # 빌드 20
        m.addSeparator()   # 0.9.109 빌드 3
        m.addAction(mlabel(T("폴더 맞추기 (두 칸)…"), "sync_dirs"), self.sync_dirs)
        m.addAction(mlabel(T("디스크 사용량 트리맵"), "space_map"), lambda: self.space_map())
        m.addAction(mlabel(T("FTP 연결…"), "ftp_connect"), self.ftp_connect)
        m.addAction(toolicons.icon("oplog", 16), T("작업 기록 (복사·이동·삭제)…"), self.open_oplog)   # 0.9.116
        m.addAction(toolicons.icon("grep", 16), T("내용 찾기 (파일 속 글자)…"), lambda: self.pane().view() and self.pane().view().grep_here())
        tm = m.addMenu(T("태그로 보기"))
        tm.aboutToShow.connect(lambda: self._fill_tags_menu(tm))
        self._fill_tags_menu(tm)
        sm2 = m.addMenu(T("가상 그룹"))
        sm2.aboutToShow.connect(lambda: self._fill_sets_menu(sm2))
        self._fill_sets_menu(sm2)
        m.addAction(mlabel(T("My메뉴 편집…"), "user_buttons"), self.edit_user_buttons)   # 0.9.113 이름 (사용자 단추 → My메뉴)
        m.addSeparator()
        m.addAction(mlabel(T("기능 검색…"), "palette"), self.open_palette)   # 0.9.113 이름 (명령 찾기 → 기능 검색)
        set_menu_icons(m)   # 0.9.111 빌드 4 도구 아이콘
        set_menu_tips(m)
        # v0.9.104 사용자 11/5: 사용법·로그·문제 보고·새 버전·홈페이지·후원은 설정 창 '정보'로

    def export_settings(self, dest=None):
        """설정 전체 내보내기 (v0.9.94): 보기·단축키·즐겨찾기·창과 탭(탭 색 포함)·색 라벨·창 구성 → zip 하나"""
        self.save_state()
        if dest is None:
            start = os.path.join(os.path.expanduser("~"), "Documents", time.strftime("4Dir_settings_%Y%m%d.zip"))
            dest, _f = QtWidgets.QFileDialog.getSaveFileName(self, T("설정 내보내기"), start, "zip (*.zip)")
            if not dest:
                return None
        try:
            n = backup.export_zip(DATA_DIR, dest, QE_VERSION)
        except Exception as ex:
            log.exception("설정 내보내기 실패 %s", dest)
            QtWidgets.QMessageBox.warning(self, T("설정 내보내기"), T("저장하지 못했습니다.\n{0}").format(ex))
            return None
        self.show_notice(T("설정을 저장했습니다 ({0}개 파일): {1}").format(n, dest) + "  ✕", ms=10000)
        return dest

    # ---------------------------------------------------------- 0.9.114 구글 드라이브 백업 (선택)
    def _gd_run(self, kind, fn, status):
        """뒤 스레드에서 fn() → _gd_done(kind, 결과, 오류)"""
        if getattr(self, "_gd_busy", None):
            log.info("구글 드라이브: 이미 진행 중 (%s) → %s 건너뜀", self._gd_busy, kind)
            return False
        if not hasattr(self, "_gd_sig"):
            self._gd_sig = _GdSig(self)
            self._gd_sig.done.connect(self._gd_done)
        self._gd_busy = status
        self.gdrive_changed.emit()
        sig = self._gd_sig

        def work():
            try:
                r = fn()
                sig.done.emit(kind, r, None)
            except Exception as ex:
                log.exception("구글 드라이브 %s 실패", kind)
                sig.done.emit(kind, None, str(ex) or type(ex).__name__)
        threading.Thread(target=work, daemon=True, name="gdrive-" + kind).start()
        return True

    def _gd_done(self, kind, r, err):
        self._gd_busy = None
        if err == gdrive.NO_DRIVE:   # 0.9.115 구글 화면에서 드라이브 권한 체크를 끄고 넘어감 → 연결 풀고 다시 로그인 안내
            log.warning("구글 드라이브 권한 없음 (%s) → 연결 끊고 다시 로그인 안내", kind)
            gdrive._cred_delete()
            self.show_notice(T("⚠ 구글 드라이브 권한이 빠졌습니다. 다시 '구글로 로그인'을 누르고, 구글 화면에서 '구글 드라이브' 항목에 체크한 뒤 계속을 누르세요  ✕"), sticky=True)
            self.gdrive_changed.emit()
            return
        if kind == "login":
            if err:
                self.show_notice(T("⚠ 구글 로그인을 마치지 못했습니다: {0}  ✕").format(err), ms=10000)
            else:
                self.show_notice(T("구글 드라이브에 연결했습니다: {0} — 바로 첫 백업을 합니다  ✕").format(r or "?"), ms=8000)
                QtCore.QTimer.singleShot(200, lambda: self.gdrive_backup(manual=True))
        elif kind in ("backup", "auto"):
            if err:
                if kind == "backup":
                    self.show_notice(T("⚠ 구글 드라이브 백업 실패: {0}  ✕").format(err), ms=10000)
            else:
                SETTINGS["gdrive_last"], SETTINGS["gdrive_last_name"] = time.time(), r[0]
                log.info("구글 드라이브 백업 완료 %s (%d바이트, %s)", r[0], r[1], "수동" if kind == "backup" else "자동")
                if kind == "backup":
                    self.show_notice(T("구글 드라이브에 백업했습니다 ({0} KB)  ✕").format(max(1, r[1] // 1024)), ms=5000)
        elif kind == "list":
            if err:
                self.show_notice(T("⚠ 구글 드라이브 백업 목록을 받지 못했습니다: {0}  ✕").format(err), ms=10000)
            else:
                self._gd_pick(r)
        elif kind == "download":
            if err:
                self.show_notice(T("⚠ 백업을 받지 못했습니다: {0}  ✕").format(err), ms=10000)
            else:
                self.import_settings(r)
        elif kind == "logout":
            self.show_notice(T("구글 드라이브 연결을 끊었습니다 (드라이브에 있던 백업은 그대로)  ✕"), ms=6000)
        self.gdrive_changed.emit()

    def gdrive_login(self):
        if not gdrive.client(BIN_DIR):
            self.show_notice(T("구글 백업은 홈페이지에서 받은 4Dir 에서 쓸 수 있습니다.") + "  ✕", ms=10000,
                             action=(T("홈페이지 열기"), lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(SITE_URL))))
            return
        stop = self._gd_stop = threading.Event()
        ok = gd_result_page(True, T("구글 드라이브에 연결했습니다"), T("이 탭을 닫고 4Dir 로 돌아가세요. 설정 백업이 곧 시작됩니다."))
        bad = gd_result_page(False, T("연결하지 못했습니다"), T("이 탭을 닫고 4Dir 에서 다시 시도해 주세요."))
        if self._gd_run("login", lambda: gdrive.login(BIN_DIR, done_html=ok, fail_html=bad, stop=stop), T("브라우저에서 로그인 중…")):
            self.show_notice(T("브라우저에서 구글 계정으로 로그인하고 '허용'을 누르세요 (5분 안에)  ✕"), ms=15000)

    def gdrive_logout(self):
        if QtWidgets.QMessageBox.question(self, T("연결 끊기"), T("구글 드라이브 연결을 끊을까요?\n드라이브에 저장된 백업은 지워지지 않습니다.")) != QtWidgets.QMessageBox.Yes:
            return
        self._gd_run("logout", lambda: gdrive.logout(BIN_DIR), T("연결 끊는 중…"))

    def gdrive_backup(self, manual=False):
        """지금 백업 (manual) / 자동 백업 (하루 한 번, 로그인했고 켜 둔 때만)"""
        if not gdrive.client(BIN_DIR) or not gdrive._cred_read():
            return False
        if not manual and (not SETTINGS["gdrive_auto"] or time.time() - float(SETTINGS["gdrive_last"] or 0) < GD_DUE):
            return False
        self.save_state()
        log.info("구글 드라이브 %s 백업 시작", "수동" if manual else "자동")
        return self._gd_run("backup" if manual else "auto", lambda: gdrive.backup_now(BIN_DIR, QE_VERSION, data_dir=DATA_DIR), T("백업 중…"))

    def gdrive_restore(self):
        self._gd_run("list", lambda: gdrive.list_backups(BIN_DIR), T("백업 목록 받는 중…"))

    def _gd_pick(self, files):
        if not files:
            QtWidgets.QMessageBox.information(self, T("구글 드라이브에서 되살리기"), T("구글 드라이브에 4Dir 백업이 아직 없습니다."))
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(T("구글 드라이브에서 되살리기"))
        dlg.resize(560, 360)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(QtWidgets.QLabel(T("되살릴 백업을 고르세요 (새것부터). 고르면 지금 설정을 따로 보관한 뒤 바꾸고 4Dir 를 다시 시작합니다.")))
        lst = QtWidgets.QListWidget()
        for f in files:
            m = re.match(r"4Dir_backup_(\d{8})_(\d{6})_(.*)\.zip$", f.get("name", ""))
            when = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]} {m.group(2)[:2]}:{m.group(2)[2:4]}" if m else f.get("createdTime", "")
            it = QtWidgets.QListWidgetItem(f"{when}   ·   {m.group(3) if m else f.get('name')}   ·   {max(1, int(f.get('size', 0) or 0) // 1024)} KB")
            it.setData(Qt.UserRole, f.get("id"))
            lst.addItem(it)
        lst.setCurrentRow(0)
        lst.itemDoubleClicked.connect(lambda *_: dlg.accept())
        lay.addWidget(lst, 1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText(T("되살리기"))
        bb.button(QtWidgets.QDialogButtonBox.Cancel).setText(T("취소"))
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        self._gd_pick_dlg = dlg   # 시험용
        if not dlg.exec() or lst.currentItem() is None:
            return
        fid = lst.currentItem().data(Qt.UserRole)
        import tempfile
        dest = os.path.join(tempfile.gettempdir(), "4Dir_gdrive_restore.zip")
        log.info("구글 드라이브 백업 되살리기 고름 %s", lst.currentItem().text())
        self._gd_run("download", lambda: gdrive.download(BIN_DIR, fid, dest), T("백업 받는 중…"))

    def import_settings(self, src=None, restart=True):
        """설정 가져오기 (v0.9.94): 백업 zip → 다음 시작 때 적용 → 4Dir 다시 시작. 지금 설정은 bin\\restore_backup 에 보관"""
        if src is None:
            src, _f = QtWidgets.QFileDialog.getOpenFileName(self, T("설정 가져오기"), os.path.join(os.path.expanduser("~"), "Documents"),
                                                            "zip (*.zip)")
            if not src:
                return False
        info = backup.read_manifest(src)
        if info is None:
            QtWidgets.QMessageBox.warning(self, T("설정 가져오기"), T("4Dir 설정 백업 파일이 아닙니다.\n{0}").format(src))
            return False
        if restart and QtWidgets.QMessageBox.question(
                self, T("설정 가져오기"),
                T("이 백업으로 모든 설정을 바꾸고 4Dir 를 다시 시작합니다.\n\n백업: v{0} · {1}\n\n지금 설정은 4Dir 폴더의 bin\\restore_backup 에 따로 보관합니다.")
                .format(info.get("version", "?"), info.get("saved", "?"))) != QtWidgets.QMessageBox.Yes:
            return False
        backup.stage_restore(DATA_DIR, src)
        if restart:
            restart_app()
        return True

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
            info = [f"4Dir {QE_VERSION} build {QE_BUILD}", f"저장 시각 {time.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"윈도우 {platform.platform()} ({platform.version()})", f"파이썬 {sys.version.split()[0]} {sys.executable}",
                    f"Qt {QtCore.qVersion()}", f"실행 위치 {BIN_DIR}", f"데이터 {DATA_DIR} (스토어판 {datadir.PACKAGED})",
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
        subject = f"[4Dir] v{QE_VERSION} problem report"   # 빌드 3: 받은 편지함에서 [4Dir] 말머리로 구분 (사용자 11/5)
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

    def toggle_private(self):
        on = not SETTINGS["private_mode"]
        SETTINGS["private_mode"] = on
        log.info("기록 안 남기기 %s", "켬" if on else "끔")
        if on:
            n = clear_history()
            self.save_state()   # 0.9.118: 화면 설정은 남김 (폴더·탭만 뺀 상태로 다시 씀)
            set_file_log(False)
            n += clear_logs()
            self.show_notice(T("기록 안 남기기를 켰습니다 — 열었던 폴더·탭·자동 기록·로그 {0}개를 지웠습니다. 칸 배치·열 너비 같은 화면 설정은 그대로입니다  ✕").format(n), ms=9000)
        else:
            set_file_log(True)
            log.info("기록 안 남기기 끔 → 로그 파일 다시 씀")
            self.save_state()
            self.show_notice(T("기록 안 남기기를 껐습니다 — 다음부터 지난번 폴더·탭으로 다시 엽니다  ✕"), ms=6000)

    def open_fav(self, path):
        new_tab = bool(QtWidgets.QApplication.keyboardModifiers() & Qt.ControlModifier)
        log.info("즐겨찾기 열기 pane=%d %s new_tab=%s", self.pane().idx, path, new_tab)
        open_fav_entry(path, lambda p: self.pane().go(p, new_tab=new_tab), self.show_notice)   # 0.9.114 파일이면 연결 프로그램

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
            self.sync_shared_side()   # v0.9.100 공용 탐색 창이 새 대상 칸 폴더까지 펼침
            if getattr(self, "preview", None) is not None:   # 미리보기 창: 다른 칸으로 옮기면 그 칸의 선택으로 (v0.9.58)
                self.preview.schedule(self)

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
        cols = key in COL_LAYOUTS   # 열 단위 배치면 분할 방향을 바꿈 (v0.9.90)
        if (self.vert.orientation() == Qt.Horizontal) != cols:
            self.vert.setOrientation(Qt.Horizontal if cols else Qt.Vertical)
            for sp in self.rows:
                sp.setOrientation(Qt.Vertical if cols else Qt.Horizontal)
            log.info("칸 분할 방향 %s", "열(왼쪽·오른쪽)" if cols else "줄(위·아래)")
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
                total = max(self.vert.height() if cols else self.vert.width(), 300)
                sp.setSizes([total // len(row) if not sp.widget(j).isHidden() else 0 for j in range(sp.count())])
            h = max(self.vert.width() if cols else self.vert.height(), 300)
            ratio = LAYOUT_RATIO.get(key) or (1,) * len(rows)   # v0.9.92 위 작게·아래 작게
            self.vert.setSizes([h * ratio[r] // sum(ratio) if r < len(rows) else 0 for r in range(MAX_ROWS)])
        if key in self.layout_actions:
            self.layout_actions[key].setChecked(True)
        else:
            self.act_grid.setIcon(layout_icon(key, 40, 32))
            self.act_grid.setChecked(True)
        g = parse_grid(key)
        self.act_grid.setToolTip(T('레이아웃: 직접 지정 (지금 가로 {0} x 세로 {1})').format(g[0], g[1]) if g else T("레이아웃: 직접 지정 (가로 x 세로)…"))
        if getattr(self, "layout_btn", None) is not None:   # 도구줄 버튼 = 지금 배치 그림
            self.layout_btn.setIcon(layout_icon(key))
            self.layout_btn.setToolTip(T('레이아웃: 직접 지정 (지금 가로 {0} x 세로 {1})').format(g[0], g[1]) if g else
                                       T('레이아웃: {0}').format(dict(LAYOUTS).get(key, key)))
        if not self.active_pane.isVisible():
            self.active_pane = self.panes[0]
        self._paint_active()
        if getattr(self, "global_chips", None) is not None:   # 새로 보이는 칸에도 맨 위에서 고른 형식 (0.9.122)
            for p in self.panes:
                if not p.isHidden() and p.view() is not None:
                    self.global_chips.apply_to(p.view())
            QtCore.QTimer.singleShot(0, self.global_chips.refresh_all)
        log.info("레이아웃 %s", key)
        self.save_timer.start()

    def toggle_setting(self, key):
        """켜고 끄는 전역 설정 (v0.9.75 사용자 의견: 탭 하나면 탭줄 숨김 · 빈 곳 클릭 상위 폴더 · 메뉴줄 접어도 즐겨찾기 남김)"""
        SETTINGS[key] = not SETTINGS[key]
        log.info("설정 %s=%s", key, SETTINGS[key])
        if key == "hide_single_tab":
            for p in self.all_panes():
                p.update_tabrow()
        elif key == "tab_multirow":   # 0.9.123
            for p in self.all_panes():
                p.bar.set_multi(SETTINGS["tab_multirow"])
                p._place_plus()
        elif key == "folder_size":   # 바로 다시 읽어 크기 칸 채우기/비우기
            for p in self.all_panes():
                for v in p.views():
                    v.reload("folder_size")
        elif key in ("keep_favbar", "show_favbar"):
            for w in WINDOWS or [self]:
                w.set_chrome_collapsed(bool(SETTINGS["chrome_collapsed"]), save=False)

    def toggle_opt(self, key):
        OPTS[key] = not OPTS[key]
        if OPTS[key] and key in ("date_groups", "type_groups"):   # 묶기는 둘 중 하나
            OPTS["type_groups" if key == "date_groups" else "date_groups"] = False
        thumbs.BADGES, thumbs.COVERS = OPTS["type_badges"], OPTS["folder_covers"]
        if key in ("type_badges", "folder_covers"):
            thumbs_service().clear()   # 딱지·표지는 미리보기에 그려 넣으므로 다시 만듦
        log.info("보기 옵션 %s=%s", key, OPTS[key])
        if key == "type_chips":   # 빌드 27 위쪽 단추 눌림 표시도 모든 창
            for w in list(WINDOWS) + ([self] if self not in WINDOWS else []):
                if getattr(w, "btn_chips", None) is not None:
                    w.btn_chips.setChecked(bool(OPTS["type_chips"]))
        if key in ("type_chips", "chips_global", "chip_counts"):   # 맨 위 형식 단추 줄 (0.9.122)
            for w in WINDOWS:
                if key != "chip_counts":
                    w.chip_sel = set()
                QtCore.QTimer.singleShot(0, lambda w=w: w.global_chips.refresh_all(force=True))
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
                elif key in ("date_folders_first", "date_groups", "type_groups"):
                    v.model_.sort(v.model_.sort_col, v.model_.sort_order)   # 다시 정렬 (묶기도 여기서)
                elif key in ("type_chips", "chips_global", "chip_counts"):
                    if key != "chip_counts" and getattr(v.model_, "ext_filter", None):
                        v.set_ext_filter(set())   # 방식이 바뀌면 거르기는 풂
                    if v is p.view():
                        p.chips.refresh(v, force=True)
                elif key in ("type_badges", "folder_covers"):
                    v.view().viewport().update()
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
        private = SETTINGS["private_mode"]
        st = st or self.collect_state()
        if private:   # 0.9.118 (Ben 11/7 '설정이 전부 기본값으로 돌아감'): 화면 설정(칸 배치·열 너비·보기·창 위치)은 저장, 열었던 폴더·탭만 뺌
            st = strip_history(st)
        try:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=1)
            os.replace(tmp, STATE_FILE)
            log.debug("상태 저장%s", " (기록 뺌)" if private else "")
            if not private:
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
        if SETTINGS["private_mode"] and st:   # 화면 설정만 쓰고 폴더·탭은 처음 폴더로
            st = strip_history(st)
            log.info("기록 안 남기기 켜짐 → 화면 설정만 불러옴 (폴더·탭은 처음 폴더)")
        self.pending_windows = list(st.get("windows") or [])   # 지난번 함께 열려 있던 창들 → main() 이 엶
        self.apply_state(st, geometry=True)
        return st.get("saved", "")[11:]

    def show_notice(self, text, sticky=None, ms=5000, action=None, action2=None):
        """알림 줄. 보통 알림은 5초 뒤 저절로 닫힘, ⚠ 경고는 눌러서 닫을 때까지 남음.
        action=(버튼 글자, 함수) 이면 알림 오른쪽에 버튼 (누르면 알림 닫고 함수 실행). action2 = 그 옆 보조 버튼 (v0.9.63)"""
        text = text.rstrip()
        if text.endswith("✕"):   # 글 끝의 ✕ 대신 오른쪽 닫기 단추 (v0.9.96)
            text = text[:-1].rstrip()
        self.notice.setText(text)
        self.notice.setVisible(True)
        self.notice_close.setVisible(True)
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
        self.notice_close.setVisible(False)

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
        OPTS["date_groups"] = bool(o.get("date_groups", False))
        OPTS["type_groups"] = bool(o.get("type_groups", False)) and not OPTS["date_groups"]
        for k in ("type_chips", "type_badges", "folder_covers", "chips_global"):
            OPTS[k] = bool(o.get(k, True))
        OPTS["chip_counts"] = bool(o.get("chip_counts", False))
        thumbs.BADGES, thumbs.COVERS = OPTS["type_badges"], OPTS["folder_covers"]
        if getattr(self, "btn_chips", None) is not None:   # 빌드 27 저장된 켬/끔을 위쪽 단추에도
            self.btn_chips.setChecked(OPTS["type_chips"])
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
                if ps["body"][0] >= 60:
                    p._side_w = ps["body"][0]   # 이슈 #5: 공용 모드라 숨긴 채 시작해도 칸별 폭 기억
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
        if SETTINGS["side_shared"]:
            self.sync_shared_side()   # 이슈 #6: 불러온 뒤 공용 탐색 창 선택도 활성 칸 폴더로

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
        olehook.install(int(self.winId()))   # v0.9.78: 창이 다시 만들어지면(항상 위 등) 새 창에 다시 끼움
        if getattr(self, "_shared_w_pending", False):   # 이슈 #4: 처음 보일 때 공용 탐색 창 폭 복원
            self._shared_w_pending = False
            QtCore.QTimer.singleShot(0, lambda: SETTINGS["side_shared"] and self.shared_host.isVisible() and self._apply_shared_w())

    def closeEvent(self, ev):
        last = not [w for w in WINDOWS if w is not self]
        if MEMOS is not None:   # v0.9.108 메모는 닫을 때 바로 저장 (0.6초 기다리지 않음)
            MEMOS.save_now()
        if last:   # 빌드 20: 압축에서 꺼낸 임시 폴더 정리 (이 프로그램 것만)
            try:
                archives.cleanup()
            except Exception:
                log.exception("압축 임시 폴더 정리 실패")
        if MEMO_WIN is not None:
            MEMO_WIN.save_geo()
            if last:   # 마지막 4Dir 창을 닫으면 메모 창도 닫음 (켜 둔 상태는 기억 → 다음에 다시 열림)
                MEMO_WIN.hide()
        if last and CALC_WIN is not None:   # 0.9.111 계산기도 같이 닫음 (위치 기억)
            CALC_WIN.save_geo()
            CALC_WIN.close()
        if PREVIEW_WIN is not None:   # 빌드 18 미리보기 따로 창도 같게
            PREVIEW_WIN.save_geo()
            if last:
                PREVIEW_WIN.pane._stop_movie()
                PREVIEW_WIN.hide()
            elif PREVIEW_WIN.pane.main is self:
                PREVIEW_WIN.pane.main = next(w for w in WINDOWS if w is not self)
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
        if HOTKEY["hwnd"] == int(self.winId()):   # 어디서나 단축키를 받던 창 → 남은 창으로 옮김 (마지막 창이면 해제)
            hotkey_register()
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
            elif m == WM_HOTKEY and ctypes.wintypes.MSG.from_address(int(message)).wParam == HOTKEY["id"]:
                QtCore.QTimer.singleShot(0, on_hotkey)
                return True, 0
            elif m == 0x0219:    # WM_DEVICECHANGE — USB·외장 드라이브 꽂기/빼기 (v0.9.95, 사용자 의견 '내 PC에 외장 드라이브 안 보임')
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.wParam in (0x8000, 0x8004) and msg.lParam and ctypes.c_uint32.from_address(msg.lParam + 4).value == 2:   # 도착/제거 완료, 볼륨
                    mask = ctypes.c_uint32.from_address(msg.lParam + 12).value
                    log.info("드라이브 %s %s", "꽂음" if msg.wParam == 0x8000 else "뺌",
                             "".join(chr(65 + i) for i in range(26) if mask >> i & 1))
                    self._drive_timer.start(600 if msg.wParam == 0x8000 else 0)   # 뺌은 바로 (11/5 사용자 '느리다'), 꽂음은 0.6초 묶음
                elif msg.wParam == 0x0007:   # DBT_DEVNODES_CHANGED — 휴대폰처럼 드라이브 글자 없는 장치는 볼륨 신호가 안 옴 (빌드 5)
                    self._devnode_check()
                elif msg.wParam in (0x8001, 0x8003, 0x8004) and msg.lParam and ctypes.c_uint32.from_address(msg.lParam + 4).value == 6:
                    # DBT_DEVTYP_HANDLE: 꺼내도 되나(8001) / 꺼내기 취소(8003) / 빠짐(8004) — 우리가 등록한 드라이브 핸들
                    h = ctypes.c_void_p.from_address(msg.lParam + 16).value
                    d = next((k for k, v in self._dev_notes.items() if v[0] == h), None)
                    if d:
                        if msg.wParam == 0x8001:
                            release_drive(d)
                        elif msg.wParam == 0x8003:
                            rewatch_drive(d)
                        else:
                            self._drop_note(d)
                        return True, 1
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


# ---------------------------------------------------------------- 어디서나 단축키 (v0.9.68, 10/29 사용자: Everything 처럼 키 하나로 불러 검색)
HOTKEY = {"hwnd": 0, "id": 0x4D31, "key": ""}
WM_HOTKEY = 0x0312
_HK_MODS = {Qt.ControlModifier: 0x2, Qt.AltModifier: 0x1, Qt.ShiftModifier: 0x4, Qt.MetaModifier: 0x8}


def _hotkey_vk(seq):
    """'Ctrl+Alt+F' → (MOD_*, VK). 글자·숫자·F1~F24·Space 만 (그 밖은 None)"""
    ks = QtGui.QKeySequence(seq)
    if ks.isEmpty():
        return None
    kc = ks[0]
    key, mods = kc.key(), kc.keyboardModifiers()
    m = 0
    for q, w_ in _HK_MODS.items():
        if mods & q:
            m |= w_
    k = int(key.value if hasattr(key, "value") else key)
    if Qt.Key_A.value <= k <= Qt.Key_Z.value or Qt.Key_0.value <= k <= Qt.Key_9.value:
        vk = k
    elif Qt.Key_F1.value <= k <= Qt.Key_F24.value:
        vk = 0x70 + (k - Qt.Key_F1.value)
    elif k == Qt.Key_Space.value:
        vk = 0x20
    else:
        return None
    return (m, vk) if m else None   # 조합키 없는 전역 단축키는 다른 프로그램 입력을 가로채므로 안 받음


def hotkey_register():
    """보이는 첫 창에 전역 단축키 등록 (창이 닫히거나 키를 바꾸면 다시). 실패(다른 프로그램이 이미 씀)는 기록만"""
    u = ctypes.windll.user32
    if HOTKEY["hwnd"]:
        u.UnregisterHotKey(ctypes.c_void_p(HOTKEY["hwnd"]), HOTKEY["id"])
        HOTKEY["hwnd"] = 0
    keys = keymap.current(SETTINGS["keys"]).get("global_hotkey") or []
    w = next((x for x in WINDOWS if x.isVisible()), None)
    if not keys or w is None:
        HOTKEY["key"] = ""
        log.info("어디서나 단축키 없음 (키 %s, 창 %s)", keys, bool(w))
        return False
    mv = _hotkey_vk(keys[0])
    if mv is None:
        log.warning("어디서나 단축키 %s 는 쓸 수 없는 조합 (Ctrl/Alt/Shift/Win + 글자·숫자·F키·Space)", keys[0])
        return False
    hwnd = int(w.winId())
    ok = bool(u.RegisterHotKey(ctypes.c_void_p(hwnd), HOTKEY["id"], mv[0] | 0x4000, mv[1]))   # 0x4000 = MOD_NOREPEAT
    if ok:
        HOTKEY.update(hwnd=hwnd, key=keys[0])
    log.info("어디서나 단축키 %s 등록 %s%s", keys[0], "성공" if ok else "실패",
             "" if ok else f" (다른 프로그램이 이미 쓰는 중, 오류 {ctypes.GetLastError()})")
    return ok


def restart_app():
    """4Dir 다시 시작 (v0.9.94 설정 가져오기): 이 프로세스가 끝나길 기다렸다 같은 방법으로 다시 띄우는 작은 도우미 → 창 전부 닫음.
    도우미는 띄우고 바로 끝남(남는 프로세스 없음)"""
    exe, script = sys.executable, os.path.abspath(sys.argv[0])
    code = ("import ctypes,subprocess,sys;k=ctypes.windll.kernel32;h=k.OpenProcess(0x100000,0,%d);"
            "h and k.WaitForSingleObject(h,30000);subprocess.Popen([%r,%r],cwd=%r)") % (os.getpid(), exe, script, BIN_DIR)
    try:
        subprocess.Popen([exe, "-c", code], cwd=BIN_DIR, creationflags=0x00000008 | 0x00000200)   # DETACHED | NEW_GROUP
        log.info("다시 시작 도우미 띄움 %s %s", exe, script)
    except Exception:
        log.exception("다시 시작 도우미 실패 — 창만 닫음")
    for w in list(WINDOWS):
        w.close()


def on_hotkey():
    """마지막에 쓴 창을 앞으로 + 전체 검색칸 (글자 전체 선택 → 바로 입력)"""
    w = WINDOWS[-1] if WINDOWS else None
    if w is None:
        return
    log.info("어디서나 단축키 → 창 앞으로 + 전체 검색칸")
    w.bring_front()
    w.focus_global_search()


# ---------------------------------------------------------------- 윈도우 종료·재부팅 (10/12 사용자: 켜 둔 채 재부팅하면 다시 열려야 함)
SESSION_END = {"on": False}
RUNONCE_KEY = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
RUNONCE_NAME = "4Dir_resume"


def runonce_set(on):
    """다음 로그인 때 4Dir 한 번 실행 (윈도우 RunOnce — 실행되면 윈도우가 스스로 지움, 늘 남는 시작프로그램 아님)"""
    if datadir.PACKAGED:   # 0.9.114 빌드 2: 스토어판은 레지스트리가 앱 안에 갇혀 RunOnce 가 안 먹음 → 2단계(StartupTask)에서
        log.info("다음 로그인 때 다시 열기: 스토어판이라 건너뜀 (%s)", on)
        return
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
    if WINDOWS and msg.get("new_window"):   # 0.9.109 빌드 5 Win+E: 빈 새 창 (칸 1개 · 내 PC) — 사용자 11/6 '새로운 빈 창'
        w = WINDOWS[-1].open_window(THIS_PC)
        w.bring_front()
        return
    if WINDOWS:
        WINDOWS[-1].bring_front(msg.get("path"))


def hand_off_to_running(arg_path, new_window=False):
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
    s.write(json.dumps({"path": arg_path, "new_window": new_window}).encode("utf-8"))
    s.flush()
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    return True


def strip_history(st):
    """상태에서 열었던 폴더·탭·다른 창 목록만 뺀 사본 (칸 배치·나눔 크기·창 위치·보기 옵션·칸 보기 방식·열 너비·정렬은 그대로)"""
    st = json.loads(json.dumps(st))
    st.pop("windows", None)
    for ps in st.get("panes") or []:
        vs = ps.get("views") or []
        cur = min(max(0, ps.get("current", 0) or 0), len(vs) - 1) if vs else 0
        ps["views"] = [dict(vs[cur], color="", locked=False)] if vs else []   # 보던 탭의 정렬·열 너비만
        ps["tabs"] = []          # → 처음 폴더(내 PC)
        ps["current"] = 0
    return st


def clear_logs():
    """로그 파일 지우기 (기록 안 남기기를 켤 때) — 지운 개수"""
    n = 0
    for f in glob.glob(os.path.join(LOG_DIR, "4Dir.log*")):
        try:
            os.remove(f)
            n += 1
        except OSError:
            pass
    return n


def clear_history():
    """기록 안 남기기를 켤 때: 지난 창 상태(4Dir_state.json)와 자동 기록(sessions\\session_*.json) 지움. 지운 개수"""
    n = 0
    for p in [STATE_FILE, STATE_FILE + ".tmp"] + glob.glob(os.path.join(session.SESS_DIR, "session_*.json")):
        try:
            if os.path.exists(p):
                os.remove(p)
                n += 1
        except OSError:
            log.exception("기록 지우기 실패 %s", p)
    FRECENT.clear()   # 0.9.116 자주 간 폴더도
    VIEWMEM.clear()
    log.info("기록 지움 %d개 (창 상태·자동 기록) + 자주 간 폴더", n)
    return n


def neutral_cwd():
    """0.9.115 (사용자 메일 11/7): 실행기가 4Dir 설치 폴더를 작업 폴더로 넘겨줌 → 4Dir 가 띄우는 프로그램(우클릭 메뉴 처리기가 띄운
    AcroTray 등)이 그대로 물려받아 4Dir 를 닫아도 설치 폴더를 잡고 있음(이름 바꾸기·옮기기 안 됨).
    윈도우 탐색기처럼 System32 로 옮김 (모든 경로는 절대 경로라 영향 없음)"""
    before = os.getcwd()
    for d in (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"), os.path.expanduser("~")):
        try:
            os.chdir(d)
            log.info("작업 폴더 %s → %s (띄우는 프로그램이 설치 폴더를 잡지 않게)", before, d)
            return d
        except OSError:
            continue
    log.warning("작업 폴더 옮기기 실패 (그대로 %s)", before)
    return None


def main():
    log.info("=" * 60)
    log.info("데이터 폴더 %s (스토어판 %s)", DATA_DIR, datadir.PACKAGED)
    log.info("4Dir v%s (빌드 %s) 시작 python=%s pid=%d", QE_VERSION, QE_BUILD, sys.version.split()[0], os.getpid())
    arg_path = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else None
    neutral_cwd()
    try:  # 작업표시줄에 파이썬 아이콘 대신 4Dir 아이콘이 보이게
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QtWidgets.QApplication(sys.argv)
    app.installEventFilter(TIP_GATE)   # 빌드 13: 풍선 도움말 끄기
    if "--new-window" in sys.argv[1:] and hand_off_to_running(None, new_window=True):   # Win+E (빌드 5): 켜져 있으면 그 안에 빈 새 창
        log.info("Win+E: 이미 실행 중 → 그 안에 빈 새 창 열고 종료")
        return
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
    if RESTORED:   # v0.9.94 설정 가져오기 적용됨
        w.show_notice(T("설정을 가져왔습니다. 이전 설정은 bin\\restore_backup 에 보관했습니다  ✕"), ms=12000)
    try:
        if not datadir.PACKAGED:
            winhook.refresh(os.path.dirname(BIN_DIR))   # 0.9.109 Win+E 를 켜 뒀으면 지금 4Dir 경로로
    except Exception:
        log.exception("Win+E 경로 갱신 실패")

    def _pinfix():   # 0.9.112 작업 표시줄 고정 바로가기가 지운 옛 버전 폴더를 가리키면 지금 폴더로 (뒤 스레드)
        if datadir.PACKAGED:   # 스토어판은 경로가 안 바뀌어 필요 없음
            return
        import pythoncom
        pythoncom.CoInitialize()
        try:
            pinfix.fix(os.path.dirname(BIN_DIR), QE_VERSION)
        except Exception:
            log.exception("고정 바로가기 고치기 실패")
        finally:
            pythoncom.CoUninitialize()
    threading.Thread(target=_pinfix, daemon=True, name="pinfix").start()
    w.start_single_server()   # 먼저 뜬 창이 이름을 차지 → 다음 실행(창 하나만 모드)이 이 창을 앞으로 부름
    hotkey_register()         # 어디서나 단축키 (v0.9.68)

    def _gd_tick():   # 0.9.114 구글 드라이브 자동 백업 (로그인·자동 켬·20시간 지남일 때만)
        try:
            if WINDOWS:
                WINDOWS[-1].gdrive_backup(manual=False)
        except Exception:
            log.exception("구글 드라이브 자동 백업 확인 실패")
    gd_timer = QtCore.QTimer(app)
    gd_timer.setInterval(6 * 3600 * 1000)
    gd_timer.timeout.connect(_gd_tick)
    gd_timer.start()
    QtCore.QTimer.singleShot(120 * 1000, _gd_tick)
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
    if os.path.exists(os.path.join(DATA_DIR, memo.FILE)):   # 빌드 13: 메모 알림은 메모 창을 안 열어도 울림
        QtCore.QTimer.singleShot(3000, memo_store)
    QtCore.QTimer.singleShot(10000, lambda: WINDOWS and start_update_check(WINDOWS[0]))   # 새 버전 확인 (하루 한 번, 뒤에서)
    first_run = not SETTINGS["guide_shown"]
    # 0.9.115 (사용자 11/7): 처음 한 번 '구글 드라이브에 백업할까요?' 권유 (필수 아님, 나중에 = 설정 → 백업). 사용법 창이 뜨는 첫 실행이면 그 뒤에
    if not SETTINGS["gdrive_asked"] and not os.environ.get("QE_NO_PROMPT"):
        QtCore.QTimer.singleShot(9000 if first_run else 2500, lambda: WINDOWS and gdrive_offer(WINDOWS[0]))
    if not SETTINGS["guide_shown"]:   # 처음 실행 → 사용법 한 번 (다시 보기: 도구 > 사용법)
        def first_guide():
            SETTINGS["guide_shown"] = True
            log.info("처음 실행 — 사용법 보여줌")
            w.open_guide()
        QtCore.QTimer.singleShot(900, first_guide)
    rc = app.exec()
    FRECENT.flush()   # 0.9.116 자주 간 폴더 남은 저장
    VIEWMEM.flush()
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
    busy = POOL.activeThreadCount()
    if busy:   # 느린 네트워크 즐겨찾기 SVN 확인 등이 아직 응답 대기 → 기다리면 창 닫은 뒤 1분 넘게 남음 (11/4 재현 72초)
        log.info("작업 %d개 아직 도는 중 → 기다리지 않고 바로 끝냄", busy)
        logging.shutdown()
        os._exit(rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()
