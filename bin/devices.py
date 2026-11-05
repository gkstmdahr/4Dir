# -*- coding: utf-8 -*-
"""휴대폰·카메라 등 '드라이브 글자 없는 장치'(MTP) (DEVICES_VER 1.0.0, v0.9.108 사용자 메일 11/5: '갤럭시폰을 연결해도 드라이브로 안 보임')

- 이런 장치는 '내 PC' 아래 셸 항목으로만 있음 → os.scandir 로 못 읽음. 윈도우 셸(IShellItem·IFileOperation)로
  읽기·복사·이동·삭제·이름 바꾸기·새 폴더.
- ★경로 = "::DEV:" + 셸 항목 ID(PIDL) 16진 글자. 셸 파싱 경로(::{20D0…}\\\\?\\usb#…)는 장치 안쪽에서 다시 열리지 않음(실측 11/5:
  SHCreateItemFromParsingName '매개 변수가 틀립니다') → PIDL 로 다시 엶 (S23+ 실측: 22개 폴더 0.08초).
- 표시 이름·부모는 기억(_names·_parents) → 탭 제목·경로 버튼·위로 가기.
- 휴대폰 안 파일 열기 = 탐색기처럼 임시 폴더(%TEMP%\\4Dir_phone)로 받아서 엶.
- 하지 않음: 실시간 변경 감시(F5), 전체 검색 색인, 사진 미리보기, 폴더 크기·SVN.
- COM 은 부르는 스레드마다 초기화.
로그: bin\\log\\4Dir.log  [QE.dev]
"""
import os
import time
import logging
import threading
import tempfile

log = logging.getLogger("QE.dev")
DEVICES_VER = "1.1.1"   # 1.1.1: 보통 경로를 normpath 로 (F:/… 넣기 실패) / 1.1.0: 윈도우 클립보드·끌기(셸 데이터 개체) → 탐색기·바탕화면으로 붙여넣기·끌어 놓기 (빌드 6)
PREFIX = "::DEV:"
THISPC = "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}"
_names = {}     # 경로 → 표시 이름
_parents = {}   # 경로 → 부모 경로 (장치 맨 위면 None = 내 PC)
_lock = threading.Lock()
TEMP_DIR = os.path.join(tempfile.gettempdir(), "4Dir_phone")


def is_dev(p):
    return bool(p) and isinstance(p, str) and p.startswith(PREFIX)


class _Com:
    def __enter__(self):
        import pythoncom
        pythoncom.CoInitialize()
        return self

    def __exit__(self, *a):
        import pythoncom
        pythoncom.CoUninitialize()


def _enc(item):
    from win32com.shell import shell
    return PREFIX + shell.PIDLAsString(shell.SHGetIDListFromObject(item)).hex()


def _item(p):
    """경로 → IShellItem (장치 경로는 PIDL, 보통 경로는 파싱)"""
    from win32com.shell import shell
    if is_dev(p):
        return shell.SHCreateItemFromIDList(shell.StringAsPIDL(bytes.fromhex(p[len(PREFIX):])), shell.IID_IShellItem)
    # 1.1.1: 끌어 놓기·붙여넣기로 온 경로가 'F:/a/b.png' (앞으로 빗금) → 셸이 '매개 변수가 틀립니다'(11/5 집, 폰으로 넣기 실패) → 윈도우 모양으로
    return shell.SHCreateItemFromParsingName(os.path.normpath(p), None, shell.IID_IShellItem)


def _children(item, n=64):
    from win32com.shell import shell
    en = item.BindToHandler(None, shell.BHID_EnumItems, shell.IID_IEnumShellItems)
    while True:
        r = en.Next(n)
        if not r:
            break
        for c in r:
            yield c


def _name(c):
    from win32com.shell import shell, shellcon
    from win32com.propsys import pscon
    try:
        n = c.QueryInterface(shell.IID_IShellItem2).GetString(pscon.PKEY_FileName)
        if n:
            return n
    except Exception:
        pass
    return c.GetDisplayName(shellcon.SIGDN_NORMALDISPLAY)


def _isdir(c):
    from win32com.shell import shellcon
    return bool(c.GetAttributes(shellcon.SFGAO_FOLDER) & shellcon.SFGAO_FOLDER)


def list_devices():
    """[(표시 이름, 경로)] — 내 PC 아래 파일 시스템이 아닌 폴더(휴대폰·카메라 등)"""
    from win32com.shell import shellcon
    out = []
    try:
        with _Com():
            for c in _children(_item(THISPC)):
                a = c.GetAttributes(shellcon.SFGAO_FILESYSTEM | shellcon.SFGAO_FOLDER)
                if (a & shellcon.SFGAO_FOLDER) and not (a & shellcon.SFGAO_FILESYSTEM):
                    nm = c.GetDisplayName(shellcon.SIGDN_NORMALDISPLAY)
                    p = _enc(c)
                    with _lock:
                        _names[p] = nm
                        _parents[p] = None
                    out.append((nm, p))
    except Exception:
        log.exception("장치 목록 실패")
    if out:
        log.info("장치 %d개 %s", len(out), [n for n, _p in out])
    return out


def list_dir(path, cancel=lambda: False):
    """장치 안 폴더 → [name, is_dir, size, mtime, attrs, full_path, sysidx, label]"""
    from win32com.shell import shell
    from win32com.propsys import pscon
    t0 = time.time()
    out = []
    with _Com():
        try:
            it = _item(path)
            kids = list(_children(it))
        except Exception as ex:
            raise OSError(f"장치 폴더를 열 수 없습니다 (연결이 끊겼거나 휴대폰이 잠겨 있음): {name_of(path)}") from ex
        for c in kids:
            if cancel():
                break
            isd = _isdir(c)
            size, mt = -1, 0
            try:
                c2 = c.QueryInterface(shell.IID_IShellItem2)
                if not isd:
                    size = int(c2.GetUInt64(pscon.PKEY_Size) or 0)
                mt = c2.GetFileTime(pscon.PKEY_DateModified).timestamp()
            except Exception:
                pass
            nm = _name(c)
            p = _enc(c)
            with _lock:
                _names[p] = nm
                _parents[p] = path
            out.append([nm, isd, size if not isd else -1, mt, 0, p, None, None])
    log.info("장치 폴더 읽기 %s : %d개 %.0fms", name_of(path), len(out), (time.time() - t0) * 1000)
    return out


def name_of(path):
    with _lock:
        n = _names.get(path)
    if n:
        return n
    from win32com.shell import shellcon
    try:
        with _Com():
            n = _item(path).GetDisplayName(shellcon.SIGDN_NORMALDISPLAY)
    except Exception:
        n = "?"
    with _lock:
        _names[path] = n
    return n


def parent_of(path):
    """부모 경로 (장치 맨 위면 None = 내 PC)"""
    with _lock:
        if path in _parents:
            return _parents[path]
    from win32com.shell import shellcon
    par = None
    try:
        with _Com():
            pi = _item(path).GetParent()
            if pi.GetDisplayName(shellcon.SIGDN_DESKTOPABSOLUTEPARSING) != THISPC:
                par = _enc(pi)
                with _lock:
                    _names.setdefault(par, pi.GetDisplayName(shellcon.SIGDN_NORMALDISPLAY))
    except Exception:
        log.exception("장치 부모 찾기 실패")
    with _lock:
        _parents[path] = par
    return par


def chain(path):
    """장치 맨 위부터 path 까지 [(이름, 경로)]"""
    out, p, guard = [], path, 0
    while p and guard < 40:
        out.append((name_of(p), p))
        p = parent_of(p)
        guard += 1
    return list(reversed(out))


def icon_index(path):
    """시스템 아이콘 번호 (휴대폰 그림) — 못 구하면 None(폴더 그림)"""
    try:
        from win32com.shell import shell, shellcon
        with _Com():
            pidl = shell.SHGetIDListFromObject(_item(path))
            _r, info = shell.SHGetFileInfo(pidl, 0, shellcon.SHGFI_PIDL | shellcon.SHGFI_SYSICONINDEX)
            return info[1]
    except Exception:
        log.exception("장치 아이콘 실패")
        return None


def data_object(paths):
    """셸 데이터 개체 (탐색기가 휴대폰 파일을 끌거나 복사할 때 쓰는 것과 같은 것) — 화면 스레드에서"""
    from win32com.shell import shell
    pidls = [shell.StringAsPIDL(bytes.fromhex(p[len(PREFIX):])) for p in paths if is_dev(p)]
    arr = shell.SHCreateShellItemArrayFromIDLists(pidls)
    import pythoncom
    return arr.BindToHandler(None, shell.BHID_DataObject, pythoncom.IID_IDataObject)


def to_clipboard(paths):
    """휴대폰 항목을 윈도우 클립보드에 (탐색기·바탕화면에서 붙여넣기 됨). 화면 스레드에서 부를 것"""
    import pythoncom
    try:
        pythoncom.OleSetClipboard(data_object(paths))
        log.info("휴대폰 항목 클립보드 %d개", len(paths))
        return True
    except Exception:
        log.exception("휴대폰 클립보드 실패")
        return False


class _DropSource:
    _com_interfaces_ = None
    _public_methods_ = ["QueryContinueDrag", "GiveFeedback"]

    def QueryContinueDrag(self, escape, keystate):
        import winerror
        if escape:
            return winerror.DRAGDROP_S_CANCEL
        if not keystate & 0x0001:   # MK_LBUTTON 뗌
            return winerror.DRAGDROP_S_DROP
        return 0

    def GiveFeedback(self, effect):
        import winerror
        return winerror.DRAGDROP_S_USEDEFAULTCURSORS


def shell_drag(paths, allow_move=False):
    """휴대폰 항목 끌기 (탐색기·바탕화면·4Dir 칸 어디로든). 놓을 때까지 기다림 — 화면 스레드에서. 반환 = 놓은 효과(0 = 취소)"""
    import pythoncom
    from win32com.server.util import wrap
    _DropSource._com_interfaces_ = [pythoncom.IID_IDropSource]
    try:
        eff = pythoncom.DoDragDrop(data_object(paths), wrap(_DropSource(), pythoncom.IID_IDropSource), 1 | (2 if allow_move else 0))
        log.info("휴대폰 끌기 %d개 → 효과 %s", len(paths), eff)
        return eff
    except Exception:
        log.exception("휴대폰 끌기 실패")
        return 0


def friendly(path):
    return " › ".join(n for n, _p in chain(path))


# ---------------------------------------------------------------- 파일 작업 (IFileOperation)
def run_op(kind, hwnd, srcs, dst=None, new_name=None, done=None, silent=False):
    """kind: copy / move / delete / rename / newfolder. 보통 경로·장치 경로 섞여도 됨.
    작업 스레드에서 실행, done(ok, err) 은 그 스레드에서 부름"""
    def run():
        import pythoncom
        from win32com.shell import shell, shellcon
        ok, err = False, ""
        t0 = time.time()
        log.info("장치 작업 시작 %s n=%d dst=%s name=%s first=%s", kind, len(srcs),
                 (name_of(dst) if is_dev(dst) else dst), new_name, [name_of(s) if is_dev(s) else s for s in srcs[:1]])
        try:
            with _Com():
                fo = pythoncom.CoCreateInstance(shell.CLSID_FileOperation, None, pythoncom.CLSCTX_ALL, shell.IID_IFileOperation)
                if hwnd:
                    fo.SetOwnerWindow(hwnd)
                fl = shellcon.FOF_NOCONFIRMMKDIR | shellcon.FOF_ALLOWUNDO
                if silent:   # 시험용: 진행 창·확인 창 없이
                    fl |= shellcon.FOF_SILENT | shellcon.FOF_NOCONFIRMATION | shellcon.FOF_NOERRORUI
                fo.SetOperationFlags(fl)
                if kind in ("copy", "move"):
                    d = _item(dst)
                    for s in srcs:
                        (fo.CopyItem if kind == "copy" else fo.MoveItem)(_item(s), d, None, None)
                elif kind == "delete":
                    for s in srcs:
                        fo.DeleteItem(_item(s), None)
                elif kind == "rename":
                    fo.RenameItem(_item(srcs[0]), new_name, None)
                elif kind == "newfolder":
                    fo.NewItem(_item(dst), 0x10, new_name, None, None)   # FILE_ATTRIBUTE_DIRECTORY
                fo.PerformOperations()
                ok = not fo.GetAnyOperationsAborted()
        except Exception as ex:
            err = str(ex)
            log.exception("장치 작업 실패 %s", kind)
        log.info("장치 작업 끝 %s ok=%s %.1f초 %s", kind, ok, time.time() - t0, err)
        if done:
            try:
                done(ok, err)
            except Exception:
                log.exception("장치 작업 done 콜백 예외")
    threading.Thread(target=run, daemon=True, name="dev-op").start()


def open_file(hwnd, path, name, done=None):
    """휴대폰 안 파일 열기: 임시 폴더로 받아서 윈도우로 엶 (탐색기와 같은 방식)"""
    os.makedirs(TEMP_DIR, exist_ok=True)
    local = os.path.join(TEMP_DIR, name)
    if os.path.exists(local):
        try:
            os.remove(local)
        except OSError:
            pass

    def after(ok, err):
        if ok and os.path.exists(local):
            try:
                os.startfile(local)
                log.info("장치 파일 열기 %s → %s", name, local)
            except OSError as ex:
                ok, err = False, str(ex)
        if done:
            done(ok, err, local)
    run_op("copy", hwnd, [path], TEMP_DIR, done=after)
