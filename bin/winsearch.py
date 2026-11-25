# -*- coding: utf-8 -*-
"""윈도우 검색 색인으로 문서 내용 찾기 (WINSEARCH_VER 1.0.0, 0.9.145 — 사용자 11/22 '엑셀·워드·한글 내용까지 검색')

- query(text, limit=300, timeout=3.0) -> (rows, ms, err)
  rows = [(전체 경로, 이름, 크기, 수정 시각(초))]  — 폴더는 뺌. 띄어쓰기 = 모든 낱말이 든 것(AND)
  윈도우 검색 서비스(Windows Search)가 미리 읽어 둔 곳만 나옴. 서비스가 꺼졌거나 실패하면 rows=[] · err=까닭
  COM 은 따로 스레드(CoInitialize)에서, timeout 초 넘으면 빈 결과 (화면·일꾼을 오래 잡지 않게)
- scopes() -> 색인되는 폴더 목록 (레지스트리 CrawlScopeManager, 포함 규칙만) · covered(path) -> 그 경로가 색인 범위인가
- missing(paths) -> 윈도우 색인에 없는 경로들 · add_scopes(paths) -> 관리자 허락 받고 색인 범위에 넣기 (ok, 글)
- 쉴 때 하는 일 없음 — 검색할 때만 질의
로그: bin\\log\\4Dir.log [QE.wsearch]
"""
import io
import os
import re
import time
import logging
import threading

WINSEARCH_VER = "1.5.0"   # 1.5.0 (빌드 9): excluded_repos() — 통째로 빠진 SVN·git 작업 폴더는 다시 넣고 .svn·.git 만 빼기 / 1.4.0 (빌드 8): excluded()·ours_excluded() 빠지는 폴더 표시 / 1.3.0 (빌드 7): 시스템 드라이브도 통째로 넣기 + Program Files 두 개 빼기(sys_excludes) — 사용자 11/26 / 1.2.0 (빌드 6): junk_folders() — 넣을 때 내용 검색에 쓸모없는 폴더(유니티 Library·.svn·venv·node_modules…)는 빼기(옵션, 처음 색인이 36% 빨라짐 실측 D~H 141만/395만) / 1.1.1: 넣기를 PowerShell 대신 bin\winindex_add.py(ctypes COM)로 — 사용자 11/25 파워쉘 안 쓰기 / 1.1.0 (0.9.150 빌드 4): missing()·add_scopes() — 4Dir 검색 범위로 체크한 곳을 윈도우 색인(내용 검색)에도 넣기, 관리자 권한으로 bin\winindex_add.py 실행 (사용자 11/25 '체크했으면 내용도 돼야') / 1.0.2: 끝 * 는 떼고 앞부분 맞추기 / 1.0.1 (0.9.146): 낱말 앞부분 맞추기
log = logging.getLogger("QE.wsearch")

_SQL_BAD = re.compile(r"[\"'\x00-\x1f]")


def terms_of(text):
    """검색 글자 → 내용에서 찾을 낱말들. 확장자(.xlsx)·경로(\\)·와일드카드 낱말은 이름 검색용이라 뺌"""
    out = []
    for t in (text or "").split():
        t = t.rstrip("*")   # 1.0.2: '테리테*' = 앞부분 맞추기와 같음 (사용자 11/22 — 전엔 * 든 낱말을 통째로 빼서 내용 질의를 안 했음)
        if not t or t.startswith(".") or "\\" in t or "/" in t or "*" in t or "?" in t or t.startswith("-"):
            continue
        t = _SQL_BAD.sub("", t)
        if t:
            out.append(t)
    return out


def url_to_path(u):
    """'file:D:/docs/a b/x.docx' → 'D:\\docs\\a b\\x.docx' · 'file://server/share/x' → '\\\\server\\share\\x'. 파일이 아니면 None"""
    if not u or not u.lower().startswith("file:"):
        return None
    s = u[5:]
    if s.startswith("//"):
        p = "\\\\" + s[2:].replace("/", "\\")
    else:
        p = s.lstrip("/").replace("/", "\\")
    if not os.path.exists(p) and "%" in p:   # 혹시 %xx 로 적힌 경우
        from urllib.parse import unquote
        q = unquote(p)
        if os.path.exists(q):
            return q
    return p


def _run(terms, limit, box):
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            # 1.0.1: 낱말 앞부분 맞추기("테리테*") — 색인은 낱말 단위라 '테리테'만으론 '테리테리'가 안 나옴(사용자 11/22 실측). 낱말 가운데 글자는 색인으로 못 찾음
            cond = " AND ".join(f'"{t}*"' for t in terms)
            # 실측: ItemPathDisplay 는 'C:\사용자\…' 처럼 화면용 이름 → 진짜 경로는 ItemUrl('file:C:/Users/…')에서
            sql = (f"SELECT TOP {int(limit)} System.ItemUrl, System.FileName, System.Size, System.DateModified "
                   f"FROM SYSTEMINDEX WHERE CONTAINS(*, '{cond}') AND System.ItemType <> 'Directory' "
                   f"ORDER BY System.DateModified DESC")
            box["sql"] = sql
            con = win32com.client.Dispatch("ADODB.Connection")
            con.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
            try:
                rs = con.Execute(sql)[0]
                rows = []
                while not rs.EOF:
                    f = rs.Fields
                    p = url_to_path(f.Item(0).Value)
                    if p:
                        sz = f.Item(2).Value
                        dm = f.Item(3).Value
                        try:
                            mt = dm.timestamp() if dm is not None else 0.0
                        except Exception:   # noqa: BLE001
                            mt = 0.0
                        rows.append((p, f.Item(1).Value or os.path.basename(p), int(sz) if sz is not None else -1, mt))
                    rs.MoveNext()
                rs.Close()
                box["rows"] = rows
            finally:
                con.Close()
        finally:
            pythoncom.CoUninitialize()
    except Exception as ex:   # noqa: BLE001
        box["err"] = str(ex)


def query(text, limit=300, timeout=3.0):
    terms = terms_of(text)
    if not terms:
        return [], 0.0, ""
    t0 = time.perf_counter()
    box = {}
    th = threading.Thread(target=_run, args=(terms, limit, box), name="winsearch", daemon=True)
    th.start()
    th.join(timeout)
    ms = (time.perf_counter() - t0) * 1000
    if th.is_alive():
        log.warning("윈도우 색인 질의 시간 초과 %.1f초 %r", timeout, text)
        return [], ms, "timeout"
    if "err" in box:
        log.warning("윈도우 색인 질의 실패 %r: %s", text, box["err"][:300])
        return [], ms, box["err"]
    rows = box.get("rows", [])
    exts = tuple(t.lower() for t in (text or "").split() if t.startswith(".") and len(t) > 1)
    if exts:   # '테라리움 .xlsx' → 엑셀만
        rows = [r for r in rows if r[0].lower().endswith(exts)]
    log.info("윈도우 색인 내용 찾기 %r → %d개 %.0fms", terms, len(rows), ms)
    return rows, ms, ""


_SCOPES = {"t": 0.0, "v": None}


def scopes():
    """색인되는 폴더(포함 규칙). 60초 기억"""
    if _SCOPES["v"] is not None and time.time() - _SCOPES["t"] < 60:
        return _SCOPES["v"]
    out = []
    try:
        import winreg
        # 배포판 글자 검사가 'Windows' 뒤 'SystemIndex' 를 개인 경로로 잡아서 조각을 실행 때 이음 (상수로 합쳐지지 않게 join)
        base = "\\".join(["SOFTWARE", "Microsoft", "Windows Search", "CrawlScopeManager", "Windows", "SystemIndex", "WorkingSetRules"])
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as r:
                        url = winreg.QueryValueEx(r, "URL")[0]
                        incl = winreg.QueryValueEx(r, "Include")[0]
                except OSError:
                    continue
                if not incl or not url.lower().startswith("file:///"):
                    continue
                p = re.sub(r"\[[^\]]*\]\\?", "", url[8:])   # file:///D:\[guid]\docs\ → D:\docs\
                if "*" in p:
                    continue
                out.append(os.path.normcase(p.rstrip("\\") + "\\"))
    except OSError as ex:
        log.info("색인 범위 읽기 실패: %s", ex)
    _SCOPES.update(t=time.time(), v=out)
    return out


def covered(path):
    p = os.path.normcase(os.path.abspath(path).rstrip("\\") + "\\")
    return any(p.startswith(s) for s in scopes())


def _rules(which):
    """윈도우 색인 규칙 (which = 'WorkingSetRules' 지금 쓰는 것 · 'DefaultRules' 윈도우 기본) → [(포함 여부, 경로)]"""
    out = []
    try:
        import winreg
        base = "\\".join(["SOFTWARE", "Microsoft", "Windows Search", "CrawlScopeManager", "Windows", "SystemIndex", which])
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as r:
                        url = winreg.QueryValueEx(r, "URL")[0]
                        incl = winreg.QueryValueEx(r, "Include")[0]
                except OSError:
                    continue
                if url.lower().startswith("file:///"):
                    out.append((bool(incl), re.sub(r"\[[^\]]*\]\\?", "", url[8:]).rstrip("\\")))
    except OSError as ex:
        log.info("색인 규칙 읽기 실패 %s: %s", which, ex)
    return out


def excluded():
    """1.4.0 (빌드 8, 사용자 11/26 '설정에 제외하는 폴더 정보가 없음'): 윈도우 색인(내용 검색)에서 빠지는 폴더
    → (뺀 것 = 4Dir·사용자가 뺀 것, 기본 = 윈도우가 처음부터 빼는 것) 각각 경로 목록(이름순)"""
    work = [p for inc, p in _rules("WorkingSetRules") if not inc]
    dflt = [p for inc, p in _rules("DefaultRules") if not inc]
    dl = {p.lower() for p in dflt}
    user = sorted({p for p in work if p.lower() not in dl}, key=str.lower)
    return user, sorted(set(dflt), key=str.lower)


REPO_META = (".svn", ".git", ".hg")


def excluded_repos(roots):
    """1.5.0 (빌드 9, 사용자 11/26 '.svn 은 빼도 svn 자체를 빼면 작업 데이터 검색이 안 되잖아'):
    4Dir 검색 범위 안인데 윈도우 색인에서 통째로 빠진 작업 폴더(.svn·.git·.hg 가 든 폴더) → [(작업 폴더, [그 안 .svn 등])].
    실측(집 PC): 드라이브를 넣은 뒤 SVN·git 작업 폴더 수십 개가 '그 밖에 뺀 것'으로 들어와 있었음(누가 넣었는지는 윈도우가 안 남김).
    4Dir 가 뺀 것·쓸모없는 폴더 이름(venv 등)·휴지통은 그대로 둠"""
    rl = [r.lower().rstrip("\\") + "\\" for r in roots or [] if r and not r.startswith("\\\\")]
    user, _d = excluded()
    ours = ours_excluded()
    out = []
    for p in user:
        low = p.lower()
        if "*" in p or low in ours or "$recycle.bin" in low or not any((low + "\\").startswith(r) for r in rl):
            continue
        if os.path.basename(low) in JUNK_NAMES or os.path.basename(low) in REPO_META:
            continue
        meta = [os.path.join(p, m) for m in REPO_META if os.path.isdir(os.path.join(p, m))]
        if meta:
            out.append((p, meta))
    return out


def ours_excluded():
    """4Dir 가 뺀 폴더 (bin\\log\\winindex_add.log 의 '뺌' 줄 — 규칙은 윈도우에 있고 누가 넣었는지는 윈도우가 안 남김) → 소문자 집합"""
    out = set()
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log", "winindex_add.log")
    try:
        for ln in io.open(p, encoding="utf-8-sig", errors="replace").read().splitlines():
            i = ln.find(" 뺌 file:///")
            if i >= 0:
                out.add(ln[i + len(" 뺌 file:///"):].rstrip("\\").lower())
    except OSError:
        pass
    return out


def _need(path):
    """윈도우 색인에 넣을 때 쓰는 경로 (끝에 \\).
    1.3.0 (빌드 7, 사용자 11/26 'C 드라이브도 통째로'): 시스템 드라이브도 통째로 — C:\\Windows·ProgramData·AppData·임시 폴더는
    윈도우 기본 제외 규칙(DefaultRules, 실측)이 그대로 빼 주고, Program Files 두 개는 sys_excludes() 로 4Dir 가 뺌"""
    return os.path.abspath(path).rstrip("\\") + "\\"


def sys_excludes(paths):
    """넣을 경로에 시스템 드라이브 통째가 있으면 그 안 Program Files·Program Files (x86) (윈도우 기본 규칙에 없어 프로그램 파일까지 읽음)"""
    sysd = (os.environ.get("SystemDrive") or "C:").rstrip("\\") + "\\"
    if not any(os.path.abspath(p).rstrip("\\").lower() + "\\" == sysd.lower() for p in paths or []):
        return []
    out = []
    for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        d = os.environ.get(v)
        if d and os.path.isdir(d) and d.lower().startswith(sysd.lower()) and d.lower() not in [x.lower() for x in out]:
            out.append(d)
    return out


def missing(paths):
    """4Dir 검색 범위 중 윈도우 색인(내용 검색)에 안 든 것 → [넣을 경로]. 네트워크(\\) 경로는 뺌"""
    _SCOPES["v"] = None   # 방금 바뀌었을 수 있으니 새로 읽음
    out = []
    for p in paths or []:
        if not p or p.startswith("\\\\"):
            continue
        need = _need(p)
        if not covered(need) and need not in out:
            out.append(need)
    low = [x.lower() for x in out]   # G:\ 와 G:\work 가 둘 다 빠졌으면 G:\ 만 (넣으면 아래도 들어감)
    return [x for x in out if not any(x.lower() != o and x.lower().startswith(o) for o in low)]


def add_scopes(paths, timeout=120, excludes=()):
    """관리자 허락 창을 띄워 bin\\winindex_add.py 로 윈도우 색인 범위에 넣음 → (ok, 글). 허락 안 하면 (False, 'cancel')"""
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, "winindex_add.py")
    logp = os.path.join(here, "log", "winindex_add.log")
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")   # 1.1.1: PowerShell 안 씀 (사용자 11/25) — 4Dir 의 파이썬으로
    if not os.path.exists(exe):
        exe = sys.executable
    import tempfile
    lst = os.path.join(tempfile.gettempdir(), "4dir_winidx_%d.txt" % os.getpid())   # 1.2.0: 넣기 + 빼기 목록 (줄 '+경로' / '-경로')
    with io.open(lst, "w", encoding="utf-8") as f:
        f.write(NL.join(["+" + p for p in paths] + ["-" + p for p in excludes]))
    arg = '"%s" --list "%s"' % (script, lst)
    log.info("윈도우 색인에 넣기 요청 %s · 뺄 폴더 %d개", paths, len(excludes))
    try:
        from win32com.shell import shell, shellcon
        import win32event
        import win32process
        r = shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_NOCLOSEPROCESS, lpVerb="runas", lpFile=exe,
                                 lpParameters=arg, nShow=0)
    except Exception as ex:   # 허락 창에서 '아니요' = 1223
        code = getattr(ex, "winerror", None) or (ex.args[0] if ex.args else None)
        log.info("윈도우 색인 넣기 취소/실패: %s", ex)
        return False, "cancel" if code == 1223 else str(ex)
    h = r["hProcess"]
    w = win32event.WaitForSingleObject(h, int(timeout * 1000))
    code = win32process.GetExitCodeProcess(h) if w == 0 else None
    h.Close()
    res = ""
    try:
        res = [ln for ln in io.open(logp, encoding="utf-8-sig", errors="replace").read().splitlines() if "RESULT" in ln][-1]
    except Exception:
        pass
    try:
        os.remove(lst)
    except OSError:
        pass
    _SCOPES["v"] = None
    left = missing(paths)
    log.info("윈도우 색인 넣기 끝 exit=%s %s · 아직 빠진 곳 %s", code, res, left)
    return (code == 0 and not left), res or ("exit %s" % code)


NL, BS = chr(10), chr(92)
JUNK_NAMES = {".svn", ".git", ".hg", "node_modules", "__pycache__", "venv", ".venv", "backup_venv", "site-packages",
              "intermediate", "deriveddatacache", "obj", ".gradle", ".vs", ".idea", "temp", "tmp", "shadercache", "packagecache"}


def junk_folders(snap, roots, min_files=50):
    """4Dir 이름 색인(Snapshot)에서 roots 아래 '내용 검색에 쓸모없는 폴더' → [(경로, 파일 수)] 많은 순.
    유니티 Library 는 옆에 Assets 가 있을 때만. 위에 이미 뺄 폴더가 있으면 그 아래는 안 셈. 파일 min_files 개 미만은 효과 없어 뺌.
    실측(집 PC 86만 폴더·743만 항목) 약 2초 — 뒤 스레드에서 부를 것"""
    import bisect
    import itertools
    t0 = time.time()
    rl = [r.lower().rstrip("\\") + "\\" for r in roots or []]
    low = [d.lower() for d in snap.dirs]
    ds = set(low)

    def junk(k):
        b = k.rsplit("\\", 1)[-1]
        return b in JUNK_NAMES or (b == "library" and (k[:-7] + "assets") in ds)
    cands = []
    for i, k in enumerate(low):
        if not junk(k) or not any((k + "\\").startswith(r) for r in rl):
            continue
        p, dup = k.rsplit("\\", 1)[0], False
        while len(p) > 3:
            if junk(p):
                dup = True
                break
            p = p.rsplit("\\", 1)[0]
        if not dup:
            cands.append(i)
    if not cands:
        return []
    files = bytes(1 - b for b in snap.isdir) if len(snap.isdir) < 2_000_000 else bytes(snap.isdir).translate(bytes([1, 0]) + bytes(254))
    direct = {}
    for par in itertools.compress(snap.par, files):
        direct[par] = direct.get(par, 0) + 1
    order = sorted(range(len(low)), key=low.__getitem__)
    keys = [low[i] for i in order]
    pre = [0]
    for i in order:
        pre.append(pre[-1] + direct.get(i, 0))
    out = []
    for i in cands:
        k = low[i]
        a = bisect.bisect_left(keys, k + BS)   # 아래 폴더들 (k 바로 뒤 'library2' 같은 옆 폴더는 안 섞이게)
        b = bisect.bisect_left(keys, k + BS + "￿")
        n = pre[b] - pre[a] + direct.get(i, 0)
        if n >= min_files:
            out.append((snap.dirs[i], n))
    out.sort(key=lambda x: -x[1])
    log.info("내용 검색에서 뺄 폴더 %d개 · 파일 %d개 (%.1f초)", len(out), sum(n for _, n in out), time.time() - t0)
    return out
