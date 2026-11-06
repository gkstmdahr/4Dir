# -*- coding: utf-8 -*-
"""탐색기 대신 4Dir 열기 — Win+E (WINHOOK_VER 1.0.0, 0.9.109 빌드 3 — 사용자 11/6 '추가 기능 전부', 경쟁 앱 조사 '탐색기 대신 열기')

- 켜면: 이 사용자 계정(HKCU)에만 'Win+E·작업 표시줄 탐색기 = 4Dir' 명령을 씀. 관리자 권한 필요 없음, 다른 사용자·시스템은 그대로
  HKCU\\Software\\Classes\\CLSID\\{52205fd8-5dfb-447d-801a-d0b52f2e83e1}\\shell\\opennewwindow\\command
    (기본값) = 4Dir 실행 명령, DelegateExecute = ''   (다른 파일 관리자들도 쓰는 방식)
- 끄면: 우리가 만든 키만 지움 (표식 값 4Dir=1 이 있을 때만) → 원래 탐색기로 돌아옴
- 폴더 더블클릭·다른 프로그램의 '폴더 열기'는 바꾸지 않음 (Win+E 만)
- 4Dir 폴더를 옮기면 명령이 틀어짐 → 켤 때마다·시작할 때 지금 경로로 다시 씀(refresh)
로그: bin\\log\\4Dir.log [QE.winhook]
"""
import os
import logging
import winreg

WINHOOK_VER = "1.2.0"   # 1.2.0 (0.9.110 점검): 끌 때 우리 것만 지움·이전 값 되돌림, 다른 프로그램이 가져간 Win+E 는 안 빼앗음
log = logging.getLogger("QE.winhook")
CLSID = r"Software\Classes\CLSID\{52205fd8-5dfb-447d-801a-d0b52f2e83e1}"
BASE = [CLSID]   # 시험은 다른 곳으로 바꿈 (사용자 레지스트리를 건드리지 않게)


def _key():
    return BASE[0]


def launch_command(root):
    """4Dir 실행 명령 — 1.1.0 (0.9.109 빌드 5, 사용자 11/6 'Win+E = 빈 새 창'): 실행기(exe·vbs)는 옵션을 넘기지 않음
    → 들어 있는 파이썬으로 본체를 직접 '--new-window' 와 함께 (켜져 있으면 그 안에 칸 1개·내 PC 새 창, 꺼져 있으면 보통 시작).
    파이썬이 없으면(소스만) 예전처럼 exe / vbs"""
    pyw = os.path.join(root, "runtime", "pythonw.exe")
    for m in ("main.pyc", "main.py"):
        mp = os.path.join(root, "bin", m)
        if os.path.isfile(pyw) and os.path.isfile(mp):
            return f'"{pyw}" "{mp}" --new-window'
    exe = os.path.join(root, "4Dir.exe")
    if os.path.isfile(exe):
        return f'"{exe}"'
    vbs = os.path.join(root, "4Dir.vbs")
    ws = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wscript.exe")
    return f'"{ws}" "{vbs}"'


HKCU = winreg.HKEY_CURRENT_USER
ONW = r"\shell\opennewwindow"   # 우리 표식(4Dir=1)·이전 값(4Dir_prev…)은 이 키에 (1.2.0 — 예전엔 CLSID 키 자체에 표식)


def status():
    """None = 꺼짐, 그 밖 = 지금 써 있는 명령"""
    try:
        with winreg.OpenKey(HKCU, _key() + ONW + r"\command") as k:
            v, _t = winreg.QueryValueEx(k, "")
            return v or None
    except OSError:
        return None


def _val(sub, name):
    try:
        with winreg.OpenKey(HKCU, sub) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def ours():
    return _val(_key() + ONW, "4Dir") == 1 or _val(_key(), "4Dir") == 1   # 뒤쪽 = 1.0·1.1 이 남긴 표식


def is_4dir_cmd(cmd):
    c = (cmd or "").lower()
    return "4dir" in c and ("main.py" in c or "4dir.exe" in c or "4dir.vbs" in c)


def enable(root):
    cmd = launch_command(root)
    cur = status()
    if not ours() and cur is not None:   # 1.2.0: 다른 프로그램 값은 보관 → 끌 때 되돌림
        log.warning("Win+E 이미 다른 프로그램이 씀: %s — 보관하고 바꿈", cur)
        with winreg.CreateKey(HKCU, _key() + ONW) as k:
            winreg.SetValueEx(k, "4Dir_prev", 0, winreg.REG_SZ, cur)
            de = _val(_key() + ONW + r"\command", "DelegateExecute")
            if de is not None:
                winreg.SetValueEx(k, "4Dir_prev_de", 0, winreg.REG_SZ, de)
    with winreg.CreateKey(HKCU, _key() + ONW) as k:
        winreg.SetValueEx(k, "4Dir", 0, winreg.REG_DWORD, 1)
    with winreg.CreateKey(HKCU, _key() + ONW + r"\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        winreg.SetValueEx(k, "DelegateExecute", 0, winreg.REG_SZ, "")
    log.info("Win+E → 4Dir 켬: %s", cmd)
    return cmd


def _empty(sub):
    try:
        with winreg.OpenKey(HKCU, sub) as k:
            n_sub, n_val, _t = winreg.QueryInfoKey(k)
            return n_sub == 0 and n_val == 0
    except OSError:
        return False


def _del_value(sub, name):
    try:
        with winreg.OpenKey(HKCU, sub, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def _del_if_empty(sub):
    if _empty(sub):
        try:
            winreg.DeleteKey(HKCU, sub)
        except OSError:
            pass


def disable():
    """1.2.0: 우리가 쓴 것만 지움 — 이전 프로그램 값이 있으면 되돌리고, 빈 키만 정리 (예전엔 CLSID 키 통째로 지워 다른 값까지 지움)"""
    if not ours():
        log.info("Win+E 끄기: 우리 키 아님/없음 → 그대로")
        return False
    prev = _val(_key() + ONW, "4Dir_prev")
    prev_de = _val(_key() + ONW, "4Dir_prev_de")
    cmdk = _key() + ONW + r"\command"
    if prev is not None:
        with winreg.CreateKey(HKCU, cmdk) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, prev)
            if prev_de is not None:
                winreg.SetValueEx(k, "DelegateExecute", 0, winreg.REG_SZ, prev_de)
            else:
                try:
                    winreg.DeleteValue(k, "DelegateExecute")
                except OSError:
                    pass
        log.info("Win+E → 이전 프로그램 값 되돌림: %s", prev)
    else:
        _del_value(cmdk, "")
        _del_value(cmdk, "DelegateExecute")
        _del_if_empty(cmdk)
    for name in ("4Dir", "4Dir_prev", "4Dir_prev_de"):
        _del_value(_key() + ONW, name)
    _del_value(_key(), "4Dir")
    _del_if_empty(_key() + ONW)
    _del_if_empty(_key() + r"\shell")
    _del_if_empty(_key())
    log.info("Win+E → 탐색기로 되돌림")
    return True


def refresh(root):
    """켜 둔 상태면 지금 4Dir 경로로 명령을 다시 씀 (폴더를 옮겼거나 새 버전 폴더).
    1.2.0: 지금 명령이 4Dir 것일 때만 — 다른 프로그램이 나중에 가져갔으면 건드리지 않음"""
    cur = status()
    if ours() and is_4dir_cmd(cur) and cur != launch_command(root):
        if _val(_key(), "4Dir") == 1 and _val(_key() + ONW, "4Dir") != 1:   # 1.0·1.1 표식 → 새 자리로 옮김
            with winreg.CreateKey(HKCU, _key() + ONW) as k:
                winreg.SetValueEx(k, "4Dir", 0, winreg.REG_DWORD, 1)
            _del_value(_key(), "4Dir")
        enable(root)
        log.info("Win+E 명령 경로 갱신")
