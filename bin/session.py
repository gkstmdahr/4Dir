# -*- coding: utf-8 -*-
"""세션(창·탭 상태) 저장과 크래시 복구

- 현재 상태: bin\\4Dir_state.json (바뀔 때마다 2초 묶어서 저장 — main.py)
- 시각별 보관: bin\\sessions\\session_YYYYMMDD_HHMMSS.json 최근 20개 (탭 구성이 바뀌었을 때만, 1분에 최대 1개)
- 비정상 종료 감지: 실행 중 bin\\4Dir.running(pid) 를 두고 정상 종료 때 지움.
  다음 실행 때 파일이 남아 있고 그 pid 가 살아있지 않으면 '지난번 비정상 종료'.
"""
import os
import json
import time
import glob
import logging
from i18n import T   # 화면 문구 번역
import ctypes

log = logging.getLogger("QE.session")
BIN_DIR = os.path.dirname(os.path.abspath(__file__))
SESS_DIR = os.path.join(BIN_DIR, "sessions")
RUN_FILE = os.path.join(BIN_DIR, "4Dir.running")
KEEP = 20
MIN_GAP = 60


def _sig(st):
    """탭 구성 비교용 (창 위치·칸 크기는 무시)"""
    return json.dumps([st.get("layout"), [p.get("tabs") for p in st.get("panes", [])]], ensure_ascii=False)


class Sessions:
    def __init__(self):
        os.makedirs(SESS_DIR, exist_ok=True)
        self._last_sig = None
        self._last_time = 0
        snaps = self.list()
        if snaps:
            try:
                with open(snaps[0][1], encoding="utf-8") as f:
                    self._last_sig = _sig(json.load(f))
            except Exception:
                pass

    def snapshot(self, st, force=False):
        sig = _sig(st)
        now = time.time()
        if sig == self._last_sig or (not force and now - self._last_time < MIN_GAP):
            return False
        fn = os.path.join(SESS_DIR, time.strftime("session_%Y%m%d_%H%M%S.json"))
        with open(fn, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        self._last_sig, self._last_time = sig, now
        old = self.list()[KEEP:]
        for _label, p in old:
            try:
                os.remove(p)
            except OSError:
                pass
        log.info("세션 보관 %s (지운 옛 기록 %d)", os.path.basename(fn), len(old))
        return True

    def list(self, visible=None):
        """[(표시글자, 경로)] 최신순. visible(st) = 그 기록에서 보이던 칸 번호들 (없으면 전부)"""
        out = []
        for p in sorted(glob.glob(os.path.join(SESS_DIR, "session_*.json")), reverse=True):
            b = os.path.basename(p)[8:-5]  # YYYYMMDD_HHMMSS
            label = f"{b[4:6]}-{b[6:8]} {b[9:11]}:{b[11:13]}:{b[13:15]}"
            try:
                with open(p, encoding="utf-8") as f:
                    st = json.load(f)
                panes = st.get("panes", [])
                idx = [i for i in (visible(st) if visible else range(len(panes))) if i < len(panes)]
                tabs = sum(len(panes[i].get("tabs", [])) for i in idx)
                a = st.get("active", 0)
                ap = panes[a] if a in idx else (panes[idx[0]] if idx else {})
                tl = ap.get("tabs", [""])
                first = tl[min(max(ap.get("current", 0), 0), len(tl) - 1)] if tl else ""
                nm = os.path.basename(first.rstrip(chr(92))) or first
                nm = T(nm) if nm == "내 PC" else nm   # '내 PC' 표식만 번역 (실제 폴더 이름은 그대로)
                label += T('  —  {0}칸 · 탭 {1}개  ({2})').format(len(idx), tabs, nm)
            except Exception:
                label += T("  —  (읽기 실패)")
            out.append((label, p))
        return out

    @staticmethod
    def read(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)


def _pid_alive(pid):
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return code.value == 259  # STILL_ACTIVE


def _boot_time():
    """마지막 부팅 시각(초, time.time 기준)"""
    try:
        f = ctypes.windll.kernel32.GetTickCount64
        f.restype = ctypes.c_ulonglong
        return time.time() - f() / 1000.0
    except Exception:
        return 0.0


def start_running():
    """반환: 지난번이 비정상 종료였으면 True.
    윈도우 종료·재부팅으로 끝난 건 비정상 아님 (10/12 사용자: 재부팅했는데 문제 보고 알림이 뜸):
    - 윈도우가 끈다고 알려 왔을 때 mark_shutdown() 이 'pid shutdown' 으로 적어 둠
    - 그래도 못 적었으면 표시 파일이 마지막 부팅보다 먼저 만들어졌는지로 판단"""
    crashed = False
    if os.path.exists(RUN_FILE):
        try:
            parts = open(RUN_FILE).read().split()
            pid = int(parts[0]) if parts else 0
        except Exception:
            parts, pid = [], 0
        try:
            before_boot = os.path.getmtime(RUN_FILE) < _boot_time() - 5
        except OSError:
            before_boot = False
        if pid and _pid_alive(pid) and not before_boot:
            why = "다른 인스턴스 실행 중"
        elif "shutdown" in parts:
            why = "윈도우 종료로 끝남 (정상)"
        elif before_boot:
            why = "부팅 전 기록 → 재부팅으로 끝남 (정상)"
        else:
            crashed = True
            why = "비정상 종료로 판단"
        log.warning("실행 표시 파일 남아 있음 %s → %s", parts, why)
    with open(RUN_FILE, "w") as f:
        f.write(str(os.getpid()))
    return crashed


def mark_shutdown():
    """윈도우 종료·로그오프 중 — 다음 시작 때 비정상 종료로 보지 않게"""
    try:
        with open(RUN_FILE, "w") as f:
            f.write(f"{os.getpid()} shutdown {time.strftime('%Y-%m-%d %H:%M:%S')}")
    except OSError:
        log.exception("종료 표시 실패")


def stop_running():
    try:
        if os.path.exists(RUN_FILE) and open(RUN_FILE).read().strip() == str(os.getpid()):
            os.remove(RUN_FILE)
    except OSError:
        pass
