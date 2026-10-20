# -*- coding: utf-8 -*-
"""윈도우 탐색기 점검·해결 (Explorer Check)

점검은 전부 읽기만 한다. 해결 버튼은 현재 사용자 설정(HKCU)·사용자 폴더만 건드린다.
보안 주의(2026-09-17 사고): 다른 프로세스의 스레드/대기사슬을 들여다보는 기법은 쓰지 않는다.
  탐색기 정보는 WMI(윈도우 기본 관리 서비스)로, 응답 여부는 창에 '빈 메시지'를 보내 2초 안에 답하는지만 본다.
환경변수 QE_CHECK_DRYRUN=1 이면 해결 동작을 실제로 하지 않고 로그만 남긴다(테스트용).
"""
import os
import time
import glob
import threading
import subprocess
import winreg
import ctypes
import ctypes.wintypes as wt
import logging
import i18n
from i18n import T   # 화면 문구 번역
import xml.etree.ElementTree as ET
from collections import Counter

log = logging.getLogger("QE.check")
DRYRUN = os.environ.get("QE_CHECK_DRYRUN") == "1"

OK, WARN, BAD, INFO = T("정상"), T("주의"), T("문제"), T("참고")

K_ADV = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
K_EXP = r"Software\Microsoft\Windows\CurrentVersion\Explorer"
K_BAGS = r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell"
K_OVERLAY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\ShellIconOverlayIdentifiers"
RECENT_DIR = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Recent")
THUMB_GLOB = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Explorer\thumbcache_*.db")
NO_WINDOW = 0x08000000


class Result:
    def __init__(self, key, title, value, level, detail, fixes=()):
        self.key, self.title, self.value, self.level, self.detail = key, title, value, level, detail
        self.fixes = list(fixes)  # [(버튼글자, 동작id)]

    def text(self):
        return f"[{self.level}] {self.title}: {self.value} — {self.detail}"


# ================================================================ 도우미
def _reg_get(root, path, name, default=None):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def _reg_subkey_count(root, path):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryInfoKey(k)[0]
    except OSError:
        return 0


def _reg_subkeys(root, path):
    out = []
    try:
        with winreg.OpenKey(root, path) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                out.append(winreg.EnumKey(k, i))
    except OSError:
        pass
    return out


def _count_bags(root, path):
    """Bags 아래 폴더별 기록 수 (Bags\\<번호>)"""
    return _reg_subkey_count(root, path + r"\Bags")


def _explorer_procs():
    """WMI 로 explorer.exe 정보 (메모리MB, 핸들, 스레드, 시작시각)"""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    rows = []
    try:
        wmi = win32com.client.GetObject("winmgmts:")
        res = wmi.ExecQuery("SELECT ProcessId,WorkingSetSize,HandleCount,ThreadCount,CreationDate FROM Win32_Process WHERE Name='explorer.exe'")
        for p in res:
            cd = str(p.CreationDate or "")
            started = f"{cd[4:6]}-{cd[6:8]} {cd[8:10]}:{cd[10:12]}" if len(cd) >= 12 else "?"
            rows.append({"pid": int(p.ProcessId), "mb": int(int(p.WorkingSetSize or 0) / 1048576),
                         "handles": int(p.HandleCount or 0), "threads": int(p.ThreadCount or 0), "start": started})
            del p
        del res, wmi  # COM 해제는 CoUninitialize 전에
    finally:
        pythoncom.CoUninitialize()
    return rows


_user32 = ctypes.windll.user32
_EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _explorer_windows():
    out = []

    def cb(h, _):
        buf = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(h, buf, 64)
        if buf.value in ("CabinetWClass", "Shell_TrayWnd") and _user32.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(260)
            _user32.GetWindowTextW(h, t, 260)
            out.append((h, buf.value, t.value or (T("작업표시줄") if buf.value == "Shell_TrayWnd" else "")))
        return True
    _user32.EnumWindows(_EnumProc(cb), 0)
    return out


def _responds(hwnd, timeout_ms=2000):
    """창에 빈 메시지(WM_NULL)를 보내 timeout 안에 답하는지. 반환 (응답여부, ms)"""
    res = ctypes.c_size_t()
    t0 = time.perf_counter()
    r = _user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x0002 | 0x0001, timeout_ms, ctypes.byref(res))  # SMTO_ABORTIFHUNG|SMTO_BLOCK
    return bool(r), (time.perf_counter() - t0) * 1000


def _with_timeout(fn, sec):
    """fn 을 별도 스레드에서 sec 초 제한으로 실행. 반환 (끝났는가, 결과, 걸린초)"""
    box = {}

    def run():
        try:
            box["v"] = fn()
        except Exception as e:
            box["v"] = e
    t0 = time.perf_counter()
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(sec)
    return (not th.is_alive()), box.get("v"), time.perf_counter() - t0


def _events(channel, xpath, limit=200):
    import win32evtlog
    out = []
    try:
        h = win32evtlog.EvtQuery(channel, win32evtlog.EvtQueryReverseDirection, xpath)
    except Exception as e:
        log.warning("이벤트 조회 실패 %s : %s", channel, e)
        return out
    ns = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
    while len(out) < limit:
        batch = win32evtlog.EvtNext(h, 50)
        if not batch:
            break
        for ev in batch:
            root = ET.fromstring(win32evtlog.EvtRender(ev, win32evtlog.EvtRenderEventXml))
            eid = int(root.find("e:System/e:EventID", ns).text)
            when = root.find("e:System/e:TimeCreated", ns).get("SystemTime", "")[:19].replace("T", " ")
            data = {d.get("Name") or str(i): (d.text or "") for i, d in enumerate(root.findall("e:EventData/e:Data", ns))}
            out.append((eid, when, data))
    return out


def _utc_to_local(s):
    try:
        import calendar
        t = calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M:%S"))
        return time.strftime("%m-%d %H:%M", time.localtime(t))
    except Exception:
        return s


# ================================================================ 점검 항목
def check_process():
    rows = _explorer_procs()
    if not rows:
        return Result("proc", T("Explorer Process (탐색기 프로세스)"), T("실행 안 됨"), BAD,
                      T("탐색기가 꺼져 있습니다. 바탕화면·작업표시줄이 안 보이면 다시 시작하세요."),
                      [(T("Restart (다시 시작)"), "restart")])
    worst = max(rows, key=lambda r: r["mb"])
    val = " / ".join(T('메모리 {0:,}MB, 핸들 {1:,}, 시작 {2}').format(r['mb'], r['handles'], r['start']) for r in rows)
    lvl = WARN if any(r["mb"] >= 1024 or r["handles"] >= 10000 for r in rows) else OK
    det = (T("메모리 1GB 또는 핸들 1만 이상 — 오래 켜두면 쌓이는 상태. 다시 시작하면 풀립니다.") if lvl == WARN
           else T('프로세스 {0}개, 가장 큰 것 {1:,}MB — 정상 범위.').format(len(rows), worst['mb']))
    return Result("proc", T("Explorer Process (탐색기 프로세스)"), val, lvl, det, [(T("Restart (다시 시작)"), "restart")] if lvl != OK else [])


def check_responsive():
    wins = _explorer_windows()
    if not wins:
        return Result("resp", T("Window Response (창 응답)"), T("열린 탐색기 창 없음"), INFO, T("점검할 창이 없습니다."))
    hung, slow = [], []
    for h, cls, title in wins:
        ok, ms = _responds(h)
        log.info("창응답 %s '%s' ok=%s %.0fms", cls, title, ok, ms)
        if not ok:
            hung.append(title)
        elif ms > 500:
            slow.append(f"{title}({ms:.0f}ms)")
    val = T('창 {0}개 중 멈춤 {1}개').format(len(wins), len(hung)) + (T(', 느림 {0}개').format(len(slow)) if slow else "")
    if hung:
        return Result("resp", T("Window Response (창 응답)"), val, BAD,
                      T("2초 안에 응답 없는 창: ") + ", ".join(hung[:5]) + T(". 원인을 보려면 작업관리자 > 세부 정보 > explorer.exe 우클릭 > '대기 체인 분석'."),
                      [(T("Restart (다시 시작)"), "restart")])
    return Result("resp", T("Window Response (창 응답)"), val, WARN if slow else OK,
                  (T("응답이 느린 창: ") + ", ".join(slow[:5])) if slow else T("모든 창이 즉시 응답합니다."))


def check_network():
    drives = {}
    for sub in _reg_subkeys(winreg.HKEY_CURRENT_USER, "Network"):
        drives[sub.upper() + ":"] = _reg_get(winreg.HKEY_CURRENT_USER, "Network\\" + sub, "RemotePath", "")
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if mask & (1 << i):
            d = chr(65 + i) + ":"
            if ctypes.windll.kernel32.GetDriveTypeW(d + "\\") == 4:  # DRIVE_REMOTE
                drives.setdefault(d, "")
    if not drives:
        return Result("net", T("Network Drives (네트워크 드라이브)"), T("없음"), OK, T("연결된 네트워크 드라이브가 없습니다."))
    bad, parts = [], []
    for d, remote in sorted(drives.items()):
        done, v, sec = _with_timeout(lambda d=d: os.path.isdir(d + "\\"), 3)
        ok = done and v is True
        log.info("네트워크드라이브 %s %s done=%s ok=%s %.2fs", d, remote, done, v, sec)
        parts.append(f"{d} {T('응답 ') + format(sec * 1000, '.0f') + 'ms' if ok else T('응답 없음')}")
        if not ok:
            bad.append(f"{d} ({remote})")
    if bad:
        return Result("net", T("Network Drives (네트워크 드라이브)"), ", ".join(parts), BAD,
                      T("응답 없는 드라이브: ") + ", ".join(bad) + T(". 탐색기·'보내기' 메뉴·파일 대화상자가 이 드라이브를 기다리며 멈출 수 있습니다. "
                      "자주 안 쓰면 탐색기 '내 PC'에서 우클릭 > 연결 끊기."))
    return Result("net", T("Network Drives (네트워크 드라이브)"), ", ".join(parts), OK, T("모두 응답합니다."))


def check_separate():
    v = _reg_get(winreg.HKEY_CURRENT_USER, K_ADV, "SeparateProcess", 0)
    if v == 1:
        return Result("sep", T("Separate Process (창 별도 프로세스)"), T("켜짐"), OK, T("창 하나가 멈춰도 바탕화면·작업표시줄은 살아 있습니다."))
    return Result("sep", T("Separate Process (창 별도 프로세스)"), T("꺼짐"), WARN,
                  T("탐색기 창과 바탕화면·작업표시줄이 한 프로세스라, 창 하나가 멈추면 전체가 같이 멈춥니다. 켜면 다음 탐색기 시작부터 적용."),
                  [(T("Turn On (켜기)"), "sep_on")])


def check_quick_access():
    rec = _reg_get(winreg.HKEY_CURRENT_USER, K_EXP, "ShowRecent", 1)
    frq = _reg_get(winreg.HKEY_CURRENT_USER, K_EXP, "ShowFrequent", 1)
    n = len(glob.glob(os.path.join(RECENT_DIR, "*.lnk")))
    val = T('최근 파일 표시 {0}, 자주 쓰는 폴더 {1}, 최근 기록 {2}개').format(T('켜짐') if rec else T('꺼짐'), T('켜짐') if frq else T('꺼짐'), n)
    fixes = []
    if rec or frq:
        fixes.append((T("Hide Recent (표시 끄기)"), "qa_off"))
    if n:
        fixes.append((T("Clear History (기록 비우기)"), "recent_clear"))
    lvl = WARN if (rec or frq) and n >= 200 else OK
    det = (T("홈/빠른 실행을 열 때마다 최근 항목을 다시 확인합니다(끊긴 네트워크 경로가 섞이면 멈춤). 끄거나 비우면 빨라집니다.")
           if lvl == WARN else T("부담 적은 상태입니다."))
    return Result("qa", T("Quick Access (빠른 실행 최근 항목)"), val, lvl, det, fixes if lvl == WARN else [])


def check_bags():
    n = _count_bags(winreg.HKEY_CURRENT_USER, K_BAGS)
    lvl = WARN if n >= 3000 else OK
    det = (T('폴더마다 보기 설정(아이콘 크기·정렬 등)을 {0:,}개 기억 중. 기본 한도 5,000 근처가 되면 폴더 열 때 느려집니다. 초기화하면 폴더별 보기 설정이 기본값으로 돌아갑니다(탐색기 다시 시작 포함).').format(n) if lvl == WARN else T('{0:,}개 — 정상 범위.').format(n))
    return Result("bags", T("Folder View Memory (폴더 보기 기억)"), T('{0:,}개').format(n), lvl, det,
                  [(T("Reset (초기화)"), "bags_reset")] if lvl == WARN else [])


def check_thumbcache():
    files = glob.glob(THUMB_GLOB)
    mb = sum(os.path.getsize(f) for f in files if os.path.exists(f)) / 1048576
    lvl = WARN if mb >= 500 else OK
    return Result("thumb", T("Thumbnail Cache (썸네일 캐시)"), f"{mb:,.0f}MB", lvl,
                  T("캐시가 크면 썸네일 보기 폴더가 느려질 수 있습니다. 비우면 다시 만들어집니다(탐색기 다시 시작 포함).") if lvl == WARN else T("정상 범위."),
                  [(T("Clear (비우기)"), "thumb_clear")])


def check_overlays():
    names = sorted(_reg_subkeys(winreg.HKEY_LOCAL_MACHINE, K_OVERLAY))
    n = len(names)
    if n <= 15:
        return Result("ovl", T("Icon Overlays (아이콘 겹침 표시)"), T('{0}개').format(n), OK, T("윈도우 한도(15개) 이내."))
    dropped = names[15:]
    return Result("ovl", T("Icon Overlays (아이콘 겹침 표시)"), T('{0}개 (한도 15)').format(n), WARN,
                  T("폴더를 열 때마다 등록된 겹침 표시 프로그램(SVN·구글드라이브 등)이 파일마다 불립니다. 15개를 넘는 것은 표시도 안 됩니다: ")
                  + ", ".join(x.strip() for x in dropped) + T(". 정리는 관리자 권한 필요 — 요청 시 안내."))


def check_crashes(days=30):
    ms = days * 86400000
    evs = _events("Application", f"*[System[(EventID=1000 or EventID=1002) and TimeCreated[timediff(@SystemTime) <= {ms}]]]", 500)
    ex = [(eid, w, d) for eid, w, d in evs if (d.get("AppName") or d.get("0") or "").lower() == "explorer.exe"]
    if not ex:
        return Result("crash", T('Crashes (최근 {0}일 탐색기 강제종료)').format(days), T("0건"), OK, T("기록 없음."))
    crashes = [d.get("ModuleName", "?") for eid, w, d in ex if eid == 1000]
    hangs = sum(1 for eid, _, _ in ex if eid == 1002)
    mods = Counter(crashes).most_common(5)
    last = _utc_to_local(ex[0][1])
    det = T('오류 종료 {0}건, 응답 없음 종료 {1}건, 마지막 {2}.').format(len(crashes), hangs, last)
    if mods:
        det += T(" 오류를 낸 파일: ") + ", ".join(T('{0} {1}회').format(m, c) for m, c in mods) + "."
    return Result("crash", T('Crashes (최근 {0}일 탐색기 강제종료)').format(days), T('{0}건').format(len(ex)), WARN if len(ex) >= 3 else INFO, det)


def check_appx(days=7):
    ms = days * 86400000
    evs = _events("Microsoft-Windows-AppXDeploymentServer/Operational",
                  f"*[System[EventID=642 and TimeCreated[timediff(@SystemTime) <= {ms}]]]", 50)
    if not evs:
        return Result("appx", T('Pending App Updates (최근 {0}일 앱 업데이트 대기)').format(days), T("0건"), OK, T("기록 없음."))
    pk = Counter((d.get("PackageMoniker") or "?").split("_")[0] for _, _, d in evs)
    return Result("appx", T('Pending App Updates (최근 {0}일 앱 업데이트 대기)').format(days), T('{0}건').format(len(evs)), INFO,
                  T("로그인 직후 탐색기 먹통과 겹친 적 있는 기록(앱 업데이트가 등록을 기다림): ")
                  + ", ".join(T('{0} {1}회').format(k, v) for k, v in pk.most_common(5)) + T('. 마지막 {0}.').format(_utc_to_local(evs[0][1])))


CHECKS = [check_process, check_responsive, check_network, check_separate, check_quick_access,
          check_bags, check_thumbcache, check_overlays, check_crashes, check_appx]


def run_all(progress=None):
    out = []
    for fn in CHECKS:
        t0 = time.perf_counter()
        try:
            r = fn()
        except Exception as e:
            log.exception("점검 실패 %s", fn.__name__)
            r = Result(fn.__name__, fn.__name__, T("점검 실패"), INFO, str(e))
        log.info("점검 %s → [%s] %s (%.0fms)", r.key, r.level, r.value, (time.perf_counter() - t0) * 1000)
        out.append(r)
        if progress:
            progress(r)
    return out


# ================================================================ 해결 동작
def _reg_set(path, name, value):
    log.info("레지스트리 설정 HKCU\\%s %s=%s dryrun=%s", path, name, value, DRYRUN)
    if DRYRUN:
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)


def _reg_delete_tree(path):
    log.info("레지스트리 삭제 HKCU\\%s dryrun=%s", path, DRYRUN)
    if DRYRUN:
        return
    f = ctypes.windll.advapi32.RegDeleteTreeW
    f.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    log.info("RegDeleteTree rc=%s", f(ctypes.c_void_p(int(winreg.HKEY_CURRENT_USER)), path))  # 하위키 전부
    try:  # 빈 키 자체 제거
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass


def _delete_files(pattern):
    files = glob.glob(pattern)
    ok = 0
    for f in files:
        if DRYRUN:
            ok += 1
            continue
        try:
            os.remove(f)
            ok += 1
        except OSError:
            pass
    log.info("파일 삭제 %s : %d/%d dryrun=%s", pattern, ok, len(files), DRYRUN)
    return ok, len(files)


def _explorer_running():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq explorer.exe", "/NH"], capture_output=True, text=True,
                       creationflags=NO_WINDOW)
    return "explorer.exe" in r.stdout.lower()


def restart_explorer(between=None):
    """탐색기 종료 → (between: 잠긴 파일/설정 정리) → 다시 시작. 반환 메시지"""
    log.info("탐색기 다시 시작 요청 between=%s dryrun=%s", between.__name__ if between else None, DRYRUN)
    if DRYRUN:
        if between:
            between()
        return T("미리보기: 탐색기 종료·재시작 생략")
    subprocess.run(["taskkill", "/F", "/IM", "explorer.exe"], capture_output=True, creationflags=NO_WINDOW)
    for _ in range(25):
        if not _explorer_running():
            break
        time.sleep(0.2)
    log.info("탐색기 종료됨=%s", not _explorer_running())
    msg = ""
    if between:
        msg = between() or ""
    subprocess.Popen(["explorer.exe"], creationflags=NO_WINDOW)
    for _ in range(25):
        if _explorer_running():
            break
        time.sleep(0.2)
    log.info("탐색기 다시 실행됨=%s", _explorer_running())
    return (T("탐색기를 다시 시작했습니다. ") + msg).strip()


def _clear_thumb():
    ok, n = _delete_files(THUMB_GLOB)
    return T('썸네일 캐시 {0}/{1}개 삭제.').format(ok, n)


def _reset_bags():
    _reg_delete_tree(K_BAGS + r"\Bags")
    _reg_delete_tree(K_BAGS + r"\BagMRU")
    return T("폴더 보기 기억을 초기화했습니다.")


ACTIONS = {
    # 동작id: (확인창 문구, 실행함수)
    "restart": (T("탐색기를 강제로 닫고 다시 시작합니다.\n열려 있던 탐색기 창은 닫힙니다('윈도우탐색기 백업' 툴이 켜져 있으면 자동 복원)."),
                lambda: restart_explorer()),
    "sep_on": (T("'창 별도 프로세스'를 켭니다. 다음 탐색기 시작부터 적용됩니다."),
               lambda: (_reg_set(K_ADV, "SeparateProcess", 1), T("켰습니다. 탐색기를 다시 시작하거나 다음 로그인부터 적용."))[1]),
    "qa_off": (T("빠른 실행(홈)에 최근 파일·자주 쓰는 폴더 표시를 끕니다.\n(고정해 둔 폴더는 그대로)"),
               lambda: (_reg_set(K_EXP, "ShowRecent", 0), _reg_set(K_EXP, "ShowFrequent", 0), T("껐습니다. 새로 여는 탐색기 창부터 적용."))[2]),
    "recent_clear": (T("최근 사용 기록(바로가기 목록)을 지웁니다.\n파일 자체는 지워지지 않습니다. 고정해 둔 빠른 실행 폴더도 그대로."),
                     lambda: T("최근 기록 {}/{}개 지움.").format(*_delete_files(os.path.join(RECENT_DIR, "*.lnk")))),
    "bags_reset": (T("폴더별 보기 설정(아이콘 크기·정렬·열 너비 등) 기억을 모두 지우고 탐색기를 다시 시작합니다.\n열려 있던 탐색기 창은 닫힙니다."),
                   lambda: restart_explorer(_reset_bags)),
    "thumb_clear": (T("썸네일 캐시를 비우고 탐색기를 다시 시작합니다.\n열려 있던 탐색기 창은 닫힙니다."),
                    lambda: restart_explorer(_clear_thumb)),
}


def do_action(aid):
    log.info("해결 실행 %s", aid)
    try:
        msg = ACTIONS[aid][1]()
        log.info("해결 결과 %s : %s", aid, msg)
        return True, msg
    except Exception as e:
        log.exception("해결 실패 %s", aid)
        return False, str(e)


# ================================================================ 점검 창
def make_dialog(parent=None):
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt

    COLORS = {OK: "#2e7d32", WARN: "#e08a00", BAD: "#c62828", INFO: "#546e7a"}

    class Sig(QtCore.QObject):
        one = QtCore.Signal(object)
        done = QtCore.Signal()
        acted = QtCore.Signal(str, bool, str)

    class Dlg(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle(T("Explorer Check (탐색기 점검)"))
            self.resize(1150, 580)
            self.results = []
            self.sig = Sig()
            self.sig.one.connect(self._add)
            self.sig.done.connect(self._done)
            self.sig.acted.connect(self._acted)
            lay = QtWidgets.QVBoxLayout(self)
            top = QtWidgets.QLabel(T("윈도우 탐색기가 느리거나 멈출 때 원인을 점검하고, 안전한 것은 버튼으로 바로 해결합니다. 점검은 읽기만 합니다."))
            top.setWordWrap(True)
            lay.addWidget(top)
            bar = QtWidgets.QHBoxLayout()
            self.btn_run = QtWidgets.QPushButton(T("Check All (모두 점검)"))
            self.btn_run.clicked.connect(self.run)
            self.btn_copy = QtWidgets.QPushButton(T("Copy Report (결과 복사)"))
            self.btn_copy.clicked.connect(self.copy)
            self.btn_restart = QtWidgets.QPushButton(T("Restart Explorer (탐색기 다시 시작)"))
            self.btn_restart.clicked.connect(lambda: self.act("restart"))
            self.status = QtWidgets.QLabel("")
            for w in (self.btn_run, self.btn_copy, self.btn_restart):
                bar.addWidget(w)
            bar.addWidget(self.status, 1)
            lay.addLayout(bar)
            self.tbl = QtWidgets.QTableWidget(0, 5)
            self.tbl.setHorizontalHeaderLabels([T("항목"), T("현재 상태"), T("판정"), T("설명"), T("해결")])
            self.tbl.verticalHeader().setVisible(False)
            self.tbl.setWordWrap(True)
            self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            h = self.tbl.horizontalHeader()
            for c, wdt in enumerate((210, 230, 50, 420, 200)):
                self.tbl.setColumnWidth(c, wdt)
            h.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
            # 판정 열: 언어마다 글자 길이가 달라(독일어 'Achtung' 잘림 실측) 글자에 맞춰 넓힘
            fm = self.tbl.fontMetrics()
            self.tbl.setColumnWidth(2, max(50, max(fm.horizontalAdvance(s) for s in (T("판정"), OK, WARN, BAD, INFO)) + 24))
            lay.addWidget(self.tbl, 1)
            if DRYRUN:
                self.status.setText(T("미리보기 모드: 해결 버튼은 실제로 바꾸지 않습니다"))

        def run(self):
            self.tbl.setRowCount(0)
            self.results = []
            self.btn_run.setEnabled(False)
            self.status.setText(T("점검 중…"))
            threading.Thread(target=lambda: (run_all(self.sig.one.emit), self.sig.done.emit()), daemon=True).start()

        def _add(self, r):
            self.results.append(r)
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            for c, t in enumerate((r.title, r.value, r.level, r.detail)):
                it = QtWidgets.QTableWidgetItem(t)
                if c == 2:
                    it.setForeground(QtGui.QColor(COLORS.get(r.level, "#000")))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.tbl.setItem(row, c, it)
            if r.fixes:
                cell = QtWidgets.QWidget()
                hl = QtWidgets.QVBoxLayout(cell)
                hl.setContentsMargins(2, 2, 2, 2)
                for label, aid in r.fixes:
                    b = QtWidgets.QPushButton(label)
                    b.clicked.connect(lambda _=False, a=aid: self.act(a))
                    hl.addWidget(b)
                self.tbl.setCellWidget(row, 4, cell)
            self.tbl.resizeRowToContents(row)

        def _done(self):
            self.btn_run.setEnabled(True)
            n = Counter(r.level for r in self.results)
            self.status.setText(T('점검 끝 — 문제 {0} · 주의 {1} · 정상 {2}').format(n.get(BAD, 0), n.get(WARN, 0), n.get(OK, 0))
                                + (T("   (미리보기 모드)") if DRYRUN else ""))

        def act(self, aid):
            text = ACTIONS[aid][0]
            if QtWidgets.QMessageBox.question(self, T("확인"), text + T("\n\n진행할까요?")) != QtWidgets.QMessageBox.Yes:
                log.info("해결 취소 %s", aid)
                return
            self.status.setText(T("처리 중…"))
            threading.Thread(target=lambda: self.sig.acted.emit(aid, *do_action(aid)), daemon=True).start()

        def _acted(self, aid, ok, msg):
            self.status.setText((T("완료: ") if ok else T("실패: ")) + msg)
            QtCore.QTimer.singleShot(1500, self.run)  # 바뀐 상태 다시 점검

        def copy(self):
            txt = T("탐색기 점검 결과 ") + time.strftime("%Y-%m-%d %H:%M") + "\n" + "\n".join(r.text() for r in self.results)
            QtGui.QGuiApplication.clipboard().setText(txt)
            self.status.setText(T("결과를 복사했습니다"))

        def showEvent(self, ev):
            super().showEvent(ev)
            if not self.results:
                QtCore.QTimer.singleShot(100, self.run)

    return Dlg()


def main():
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:   # 배포판 휴대용 파이썬은 스크립트 폴더를 자동으로 안 넣음
        sys.path.insert(0, here)
    import main as qe  # 로그 설정(bin\log\4Dir.log) 재사용
    from PySide6 import QtWidgets
    log.info("탐색기 점검 단독 실행 v%s", qe.QE_VERSION)
    app = QtWidgets.QApplication(sys.argv)
    i18n.apply_font(app)   # 언어별 글꼴 (목록·메뉴 등 종류별 글꼴까지)
    d = make_dialog()
    d.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
