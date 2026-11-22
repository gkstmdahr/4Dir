# -*- coding: utf-8 -*-
"""윈도우 검색 색인으로 문서 내용 찾기 (WINSEARCH_VER 1.0.0, 0.9.145 — 사용자 11/22 '엑셀·워드·한글 내용까지 검색')

- query(text, limit=300, timeout=3.0) -> (rows, ms, err)
  rows = [(전체 경로, 이름, 크기, 수정 시각(초))]  — 폴더는 뺌. 띄어쓰기 = 모든 낱말이 든 것(AND)
  윈도우 검색 서비스(Windows Search)가 미리 읽어 둔 곳만 나옴. 서비스가 꺼졌거나 실패하면 rows=[] · err=까닭
  COM 은 따로 스레드(CoInitialize)에서, timeout 초 넘으면 빈 결과 (화면·일꾼을 오래 잡지 않게)
- scopes() -> 색인되는 폴더 목록 (레지스트리 CrawlScopeManager, 포함 규칙만) · covered(path) -> 그 경로가 색인 범위인가
- 쉴 때 하는 일 없음 — 검색할 때만 질의
로그: bin\\log\\4Dir.log [QE.wsearch]
"""
import os
import re
import time
import logging
import threading

WINSEARCH_VER = "1.0.0"
log = logging.getLogger("QE.wsearch")

_SQL_BAD = re.compile(r"[\"'\x00-\x1f]")


def terms_of(text):
    """검색 글자 → 내용에서 찾을 낱말들. 확장자(.xlsx)·경로(\\)·와일드카드 낱말은 이름 검색용이라 뺌"""
    out = []
    for t in (text or "").split():
        if t.startswith(".") or "\\" in t or "/" in t or "*" in t or "?" in t or t.startswith("-"):
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
            cond = " AND ".join(f'"{t}"' for t in terms)
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
