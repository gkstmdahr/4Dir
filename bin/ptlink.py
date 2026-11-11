# -*- coding: utf-8 -*-
"""PowerToys 로 Win+E → 4Dir 연결 (PTLINK_VER 1.0.0, 0.9.119 빌드 3 — 사용자 11/10 '안내 + 자동으로 연결')

왜: 윈도우 11 26H2(빌드 26300~)에서는 레지스트리 방식(winhook)이 Win+E 에 안 먹는 것으로 보임
    (메일 사용자 로그·Directory Opus 포럼 11/1 신고). PowerToys 키보드 관리자는 키 입력을 먼저 가로채므로 경로 변경과 무관.
방식 (PowerToys 원본 소스로 확인, 공식 설정 도구 DSC 와 같은 순서):
  1) %LOCALAPPDATA%\\Microsoft\\PowerToys\\Keyboard Manager\\settings.json 의 activeConfiguration(없으면 'default') → 그 이름.json
  2) remapShortcuts.global 에 항목 하나: originalKeys '260;69'(260 = Win 양쪽, 69 = E), operationType 1(프로그램 실행),
     runProgramAlreadyRunningAction 1(이미 실행 중이어도 하나 더 = 4Dir 가 받아서 새 창), 나머지 0
  3) 이름 있는 이벤트 'PowerToys_KeyboardManager_Event_Settings' 를 울리면 PowerToys 가 다시 읽음 (안 켜져 있으면 다음에 켤 때 읽음)
- 쓰기 전 원본을 '<이름>.4Dir-backup.json' 으로 한 번 보관. 끊기 = 우리 항목(4Dir 실행 명령)만 지움.
- 관리자 권한 PowerToys 와는 상관없이 파일만 씀. 4Dir 가 관리자 권한이면 안내만 (DSC 도 비관리자에서만 씀).
- 1.1.0: PowerToys 0.102 의 새 편집기는 자기 목록 editorSettings.json 을 따로 가짐(엔진 파일을 열 때 가져옴). 엔진 파일만 고치면
  편집기에 '꺼짐' 항목이 남거나, 편집기에서 저장할 때 엔진 파일이 편집기 목록으로 다시 써질 수 있음(실측: 끊은 뒤 편집기에 IsActive false 로 남음)
  → 그 파일이 있으면 같은 항목을 같이 넣고(켬)·지움.
로그: bin\\log\\4Dir.log [QE.ptlink]
"""
import os
import json
import shutil
import ctypes
import logging

PTLINK_VER = "1.2.0"   # 1.2.0 (0.9.131 사용자 11/11 '정보에 비트수'): 윈도우 글자 끝에 64-bit / 64-bit ARM / 32-bit / 1.1.0 (빌드 4, 회사 PC PowerToys 0.102 실측): 새 편집기 목록(editorSettings.json)도 같이 맞춤, 윈도우 버전 글자, 키보드 관리자 화면 바로 열기
log = logging.getLogger("QE.ptlink")
WIN_E = "260;69"
EVENT = "PowerToys_KeyboardManager_Event_Settings"
STORE_URL = "ms-windows-store://pdp/?ProductId=XP89DCGQ3K6VLD"
WEB_URL = "https://learn.microsoft.com/windows/powertoys/install"
BASE = [None]   # 시험은 다른 폴더로 (사용자 PowerToys 설정을 건드리지 않게)


def pt_dir():
    return BASE[0] or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "PowerToys")


def kbm_dir():
    return os.path.join(pt_dir(), "Keyboard Manager")


def exe_path():
    """설치된 PowerToys.exe (없으면 None) — 사용자 설치·전체 설치 둘 다"""
    if BASE[0]:
        p = os.path.join(BASE[0], "PowerToys.exe")
        return p if os.path.isfile(p) else None
    for d in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "PowerToys"),
              os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "PowerToys")):
        p = os.path.join(d, "PowerToys.exe")
        if os.path.isfile(p):
            return p
    return None


def running():
    """PowerToys 가 켜져 있나 (키보드 관리자는 PowerToys 가 켜져 있어야 동작)"""
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq PowerToys.exe", "/NH"], capture_output=True, text=True,
                             creationflags=0x08000000, timeout=5).stdout
        return "PowerToys.exe" in out
    except Exception:
        return False


def _read(p, default=None):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception:
        log.exception("PowerToys 설정 읽기 실패 %s", p)
        return default


def kbm_enabled():
    """PowerToys 전체 설정에서 키보드 관리자가 켜져 있나 — 파일이 없거나 값이 없으면 None(모름, PowerToys 기본은 켬)"""
    d = _read(os.path.join(pt_dir(), "settings.json"), {}) or {}
    v = (d.get("enabled") or {}).get("Keyboard Manager")
    return None if v is None else bool(v)


def config_path():
    st = _read(os.path.join(kbm_dir(), "settings.json"), {}) or {}
    name = ((st.get("properties") or {}).get("activeConfiguration") or {}).get("value") or "default"
    return os.path.join(kbm_dir(), name + ".json")


def _ensure_module_settings():
    """키보드 관리자를 한 번도 안 연 PC — 모듈 설정 파일이 없으면 PowerToys 가 아무것도 안 읽음 → 기본 모양으로 만듦"""
    p = os.path.join(kbm_dir(), "settings.json")
    if os.path.isfile(p):
        return
    os.makedirs(kbm_dir(), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"properties": {"activeConfiguration": {"value": "default"}, "keyboardConfigurations": {"value": ["default"]}},
                   "name": "Keyboard Manager", "version": "1"}, f)
    log.info("PowerToys 키보드 관리자 설정 파일 새로 만듦 %s", p)


def _blank():
    return {"remapKeys": {"inProcess": []}, "remapKeysToText": {"inProcess": []},
            "remapShortcuts": {"global": [], "appSpecific": []}, "remapShortcutsToText": {"global": [], "appSpecific": []}}


def _is_ours(e, prog=None):
    p = (e.get("runProgramFilePath") or "") + " " + (e.get("runProgramArgs") or "")
    return e.get("originalKeys") == WIN_E and int(e.get("operationType") or 0) == 1 and "4dir" in p.lower()


def find_win_e():
    """지금 Win+E 에 걸린 PowerToys 항목 (없으면 None)"""
    d = _read(config_path(), None)
    if not d:
        return None
    for e in ((d.get("remapShortcuts") or {}).get("global") or []):
        if e.get("originalKeys") == WIN_E:
            return e
    return None


def linked():
    e = find_win_e()
    return bool(e and _is_ours(e))


def launch_parts(root, winhook_cmd):
    """winhook 실행 명령 문자열 → (프로그램, 인수, 시작 폴더)"""
    cmd = winhook_cmd.strip()
    if cmd.startswith('"'):
        prog, _, rest = cmd[1:].partition('"')
    else:
        prog, _, rest = cmd.partition(" ")
    return prog, rest.strip(), root


def link(root, winhook_cmd):
    """Win+E → 4Dir 새 창. 다른 프로그램이 Win+E 를 쓰고 있었으면 그 항목은 우리 것으로 바꿈(보관본 있음). 돌려줌: (ok, 메시지 키)"""
    if exe_path() is None:
        return False, "not_installed"
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return False, "admin"
    except Exception:
        pass
    _ensure_module_settings()
    cp = config_path()
    d = _read(cp, None)
    if d is None:
        d = _blank()
    elif os.path.isfile(cp):
        bk = cp[:-5] + ".4Dir-backup.json"
        if not os.path.exists(bk):
            shutil.copyfile(cp, bk)
            log.info("PowerToys 설정 보관 %s", bk)
    for k, v in _blank().items():
        d.setdefault(k, v)
    d["remapShortcuts"].setdefault("global", [])
    prog, args, start = launch_parts(root, winhook_cmd)
    old = [e for e in d["remapShortcuts"]["global"] if e.get("originalKeys") == WIN_E]
    if old and not _is_ours(old[0]):
        log.warning("PowerToys Win+E 에 다른 항목이 있었음 → 바꿈 (보관본에 남음): %s", old[0])
    d["remapShortcuts"]["global"] = [e for e in d["remapShortcuts"]["global"] if e.get("originalKeys") != WIN_E]
    d["remapShortcuts"]["global"].append({
        "originalKeys": WIN_E, "operationType": 1, "secondKeyOfChord": 0,
        "runProgramFilePath": prog, "runProgramArgs": args, "runProgramStartInDir": start,
        "runProgramElevationLevel": 0, "runProgramAlreadyRunningAction": 1, "runProgramStartWindowType": 0,
        "unicodeText": "*Unsupported*"})
    tmp = cp + ".4dirtmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cp)
    try:
        _editor_sync(prog, args, start, True)
    except Exception:
        log.exception("PowerToys 새 편집기 목록 맞추기 실패 (엔진 파일은 씀)")
    sig = signal()
    log.info("PowerToys Win+E → 4Dir 연결: %s %s (파일 %s, 다시 읽기 신호 %s, 키보드 관리자 %s)", prog, args, cp, sig, kbm_enabled())
    return True, "ok"


def unlink():
    try:
        ed = _editor_sync("", "", "", False)
    except Exception:
        log.exception("PowerToys 새 편집기 목록에서 지우기 실패")
        ed = False
    cp = config_path()
    d = _read(cp, None)
    if not d:
        return ed
    g = (d.get("remapShortcuts") or {}).get("global") or []
    keep = [e for e in g if not _is_ours(e)]
    if len(keep) == len(g):
        if ed:
            signal()
        return ed
    d["remapShortcuts"]["global"] = keep
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    log.info("PowerToys Win+E 연결 끊음 (%s, 신호 %s)", cp, signal())
    return True


def signal():
    """PowerToys 키보드 관리자에게 '설정 다시 읽기' — 안 켜져 있으면 False (다음에 켤 때 읽음)"""
    k = ctypes.windll.kernel32
    k.OpenEventW.restype = ctypes.c_void_p
    h = k.OpenEventW(0x0002, False, EVENT)   # EVENT_MODIFY_STATE
    if not h:
        return False
    try:
        return bool(k.SetEvent(ctypes.c_void_p(h)))
    finally:
        k.CloseHandle(ctypes.c_void_p(h))


def _editor_path():
    return os.path.join(kbm_dir(), "editorSettings.json")


def _editor_sync(prog, args, start, on):
    """새 편집기 목록에 Win+E → 4Dir 를 넣거나(on) 지움. 파일이 없으면(옛 편집기·안 열어 봄) 아무것도 안 함"""
    p = _editor_path()
    d = _read(p, None)
    if not isinstance(d, dict) or "ShortcutSettingsDictionary" not in d:
        return False
    sd = d.setdefault("ShortcutSettingsDictionary", {})
    prof = d.get("ActiveProfile") or "default"
    pd = d.setdefault("ProfileDictionary", {})
    ops = d.setdefault("ShortcutsByOperationType", {})
    mine = [k for k, v in sd.items() if (v.get("Shortcut") or {}).get("OriginalKeys") == WIN_E
            and int((v.get("Shortcut") or {}).get("OperationType") or 0) == 1
            and (on or "4dir" in (((v.get("Shortcut") or {}).get("ProgramPath") or "") + " " + ((v.get("Shortcut") or {}).get("ProgramArgs") or "")).lower())]   # 끊을 땐 4Dir 것만
    if not on and not mine:
        return False   # 지울 것 없음 (파일 그대로)
    for k in mine:   # 우리 것(또는 Win+E 프로그램 실행 항목)을 지우고 → on 이면 새로 하나
        sd.pop(k, None)
        for lst in list(pd.values()) + list(ops.values()):
            if isinstance(lst, list) and k in lst:
                lst.remove(k)
    if on:
        import uuid
        k = str(uuid.uuid4())
        sd[k] = {"Id": k, "Shortcut": {"OriginalKeys": WIN_E, "TargetKeys": "", "TargetApp": "", "OperationType": 1,
                                       "ExactMatch": False, "TargetText": "", "ProgramPath": prog, "ProgramArgs": args,
                                       "StartInDirectory": start, "Elevation": 0, "IfRunningAction": 1, "Visibility": 0,
                                       "UriToOpen": "", "Condition": 0},
                 "Profiles": [prof], "IsActive": True}
        pd.setdefault(prof, []).append(k)
        ops.setdefault("RunProgram", []).append(k)
    tmp = p + ".4dirtmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    log.info("PowerToys 새 편집기 목록 %s (%s, 지운 옛 항목 %d)", "넣음" if on else "지움", p, len(mine))
    return True


def open_kbm_settings():
    """PowerToys 설정의 Keyboard Manager 화면 바로 열기 (PowerToys 지원 인수 --open-settings=KBM, 원본 소스·실측 확인)"""
    exe = exe_path()
    if not exe:
        return False
    import subprocess
    subprocess.Popen([exe, "--open-settings=KBM"], close_fds=True)
    log.info("PowerToys 키보드 관리자 설정 열기")
    return True


def windows_info():
    """(보이는 글자, 빌드 번호) — 예 ('Windows 11 24H2 (빌드 26100.6584)', 26100). 레지스트리 ProductName 은 11 에서도 10 이라 빌드로 판단"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            def g(n, d=""):
                try:
                    return winreg.QueryValueEx(key, n)[0]
                except OSError:
                    return d
            build = int(g("CurrentBuild", "0") or 0)
            ubr = g("UBR", "")
            disp = g("DisplayVersion", "") or g("ReleaseId", "")
        name = "Windows 11" if build >= 22000 else "Windows 10"
        return f"{name} {disp} ({build}{'.' + str(ubr) if ubr != '' else ''}) · {windows_arch()}".replace("  ", " "), build
    except Exception:
        return "Windows ?", 0


def windows_arch():
    """윈도우 자체의 비트수 (4Dir 프로그램이 아니라 PC) — IsWow64Process2 의 '원래 기계'. 없으면(옛 윈도우 10) 환경 변수"""
    names = {0x8664: "64-bit", 0xAA64: "64-bit ARM", 0x014C: "32-bit", 0x01C4: "32-bit ARM"}
    try:
        import ctypes
        k = ctypes.windll.kernel32
        pm, nm = ctypes.c_ushort(0), ctypes.c_ushort(0)
        if k.IsWow64Process2(k.GetCurrentProcess(), ctypes.byref(pm), ctypes.byref(nm)):
            return names.get(nm.value, f"0x{nm.value:04X}")
    except Exception:
        pass
    a = (os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE") or "").upper()
    return {"AMD64": "64-bit", "ARM64": "64-bit ARM", "X86": "32-bit"}.get(a, a or "?")


def windows_build():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            return int(winreg.QueryValueEx(key, "CurrentBuild")[0])
    except Exception:
        return 0


def registry_may_fail():
    """26H2(빌드 26300 이상)는 레지스트리 방식이 Win+E 에 안 먹는 것으로 보임 (확정 아님 — 신고 기준)"""
    return windows_build() >= 26300
