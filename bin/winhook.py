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

WINHOOK_VER = "1.1.0"
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


def status():
    """None = 꺼짐, 그 밖 = 지금 써 있는 명령"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _key() + r"\shell\opennewwindow\command") as k:
            v, _t = winreg.QueryValueEx(k, "")
            return v or None
    except OSError:
        return None


def ours():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _key()) as k:
            return winreg.QueryValueEx(k, "4Dir")[0] == 1
    except OSError:
        return False


def enable(root):
    cmd = launch_command(root)
    if status() is not None and not ours():
        log.warning("Win+E 이미 다른 프로그램이 씀: %s — 덮어씀", status())
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _key()) as k:
        winreg.SetValueEx(k, "4Dir", 0, winreg.REG_DWORD, 1)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _key() + r"\shell\opennewwindow\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        winreg.SetValueEx(k, "DelegateExecute", 0, winreg.REG_SZ, "")
    log.info("Win+E → 4Dir 켬: %s", cmd)
    return cmd


def _delete_tree(root, sub):
    with winreg.OpenKey(root, sub, 0, winreg.KEY_ALL_ACCESS) as k:
        while True:
            try:
                child = winreg.EnumKey(k, 0)
            except OSError:
                break
            _delete_tree(root, sub + "\\" + child)
    winreg.DeleteKey(root, sub)


def disable():
    if not ours():
        log.info("Win+E 끄기: 우리 키 아님/없음 → 그대로")
        return False
    _delete_tree(winreg.HKEY_CURRENT_USER, _key())
    log.info("Win+E → 탐색기로 되돌림")
    return True


def refresh(root):
    """켜 둔 상태면 지금 4Dir 경로로 명령을 다시 씀 (폴더를 옮겼거나 새 버전 폴더)"""
    if ours() and status() != launch_command(root):
        enable(root)
        log.info("Win+E 명령 경로 갱신")
