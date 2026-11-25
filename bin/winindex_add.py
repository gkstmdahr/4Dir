# -*- coding: utf-8 -*-
"""winindex_add.py v1.1.0 (4Dir 0.9.150 빌드 6 — 빼기(--list '-경로') 추가, 사용자 11/25 '옵션에 넣던가') — 4Dir 검색 범위로 체크한 곳을 윈도우 색인(내용 검색)에도 넣기

PowerShell 을 쓰지 않음 (사용자 11/25 '파워쉘 안 쓰기 — CPU 많이 씀'). 윈도우 검색 COM(ISearchCrawlScopeManager)을
ctypes 로 직접 부름. 윈도우 검색 범위 바꾸기는 관리자만 되므로 4Dir 가 관리자 권한(runas)으로 이 파일을 pythonw 로 실행.
  pythonw winindex_add.py G:\\ H:\\        넣기
  pythonw winindex_add.py --check G:\\     바꾸지 않고 들어 있는지만 기록
로그: bin\\log\\winindex_add.log (마지막 'RESULT ok=… fail=…' 줄을 4Dir 가 읽음). 끝나면 바로 종료(상주 없음)
"""
import os
import sys
import time
import ctypes
from ctypes import wintypes, POINTER, byref, c_void_p, c_int, c_wchar_p, HRESULT

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "log", "winindex_add.log")


def write_log(m):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")


class GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    def __init__(self, s):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(c_wchar_p("{" + s + "}"), byref(self))


CLSID_CSearchManager = GUID("7D096C5F-AC08-4F1F-BEB7-5C22C517CE39")
IID_ISearchManager = GUID("AB310581-AC80-11D1-8DF3-00C04FB6EF69")
# 표 순서(vtable 자리): IUnknown 0~2 · ISearchManager.GetCatalog 10 · ISearchCatalogManager.GetCrawlScopeManager 28
# ISearchCrawlScopeManager: AddUserScopeRule 8 · IncludedInCrawlScope 13 · SaveAll 16 · Release 2


def _call(obj, idx, argtypes, *args):
    vt = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(HRESULT, c_void_p, *argtypes)(vt[idx])
    return fn(obj, *args)


def _release(obj):
    if obj:
        vt = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)(vt[2])(obj)


def crawl_scope_manager():
    ole = ctypes.oledll.ole32
    ole.CoInitialize(None)
    mgr, cat, csm = c_void_p(), c_void_p(), c_void_p()
    ole.CoCreateInstance(byref(CLSID_CSearchManager), None, 1 | 4, byref(IID_ISearchManager), byref(mgr))   # INPROC|LOCAL
    _call(mgr, 10, [c_wchar_p, POINTER(c_void_p)], "SystemIndex", byref(cat))
    _call(cat, 28, [POINTER(c_void_p)], byref(csm))
    _release(cat)
    _release(mgr)
    return csm


def included(csm, url):
    v = c_int(0)
    _call(csm, 13, [c_wchar_p, POINTER(c_int)], url, byref(v))
    return bool(v.value)


def progress():
    """윈도우 색인 진행 → (색인된 수, 남은 수). 관리자 권한 필요 없음 (4Dir 0.9.150 빌드 10 — 설정 ▸ 검색 진행률).
    ISearchCatalogManager: NumberOfItems 15 · NumberOfItemsToIndex 16 (바로·알림·큰 작업 셋의 합을 남은 수로)"""
    from ctypes import c_long
    ole = ctypes.oledll.ole32
    try:
        ole.CoInitialize(None)
    except OSError:
        pass   # 이미 다른 방식으로 초기화된 스레드 (Qt 화면 스레드 등) — 그대로 씀
    mgr, cat = c_void_p(), c_void_p()
    ole.CoCreateInstance(byref(CLSID_CSearchManager), None, 1 | 4, byref(IID_ISearchManager), byref(mgr))
    try:
        _call(mgr, 10, [c_wchar_p, POINTER(c_void_p)], "SystemIndex", byref(cat))
        n, a, b, c = c_long(), c_long(), c_long(), c_long()
        _call(cat, 15, [POINTER(c_long)], byref(n))
        _call(cat, 16, [POINTER(c_long)] * 3, byref(a), byref(b), byref(c))
        return n.value, a.value + b.value + c.value
    finally:
        _release(cat)
        _release(mgr)


def main(argv):
    """인자: [--check] [--list 파일] [경로…]  — 경로 = 넣기. --list 파일의 줄: '+경로' 넣기 · '-경로' 빼기(내용 검색 제외)"""
    check = "--check" in argv
    items = []   # (넣기 여부, 경로)
    it = iter(argv)
    for a in it:
        if a == "--check":
            continue
        if a == "--list":
            fn = next(it, "")
            try:
                with open(fn, encoding="utf-8-sig") as f:
                    for ln in f.read().splitlines():
                        if ln[:1] in "+-" and ln[1:].strip():
                            items.append((ln[0] == "+", ln[1:].strip()))
            except OSError as ex:
                write_log("RESULT error 목록 파일 못 읽음 %s : %s" % (fn, ex))
                return 1
            continue
        items.append((True, a))
    write_log("시작 check=%s 넣기 %d · 빼기 %d" % (check, sum(1 for i, _ in items if i), sum(1 for i, _ in items if not i)))
    ok = fail = 0
    try:
        csm = crawl_scope_manager()
        todo = [(inc, "file:///" + p.rstrip("\\") + "\\") for inc, p in items]
        for inc, u in todo:
            try:
                before = included(csm, u)
            except OSError as ex:   # 없는 드라이브 등
                fail += 1
                write_log("  못 읽음 %s : %s" % (u, ex))
                continue
            if check:
                write_log("  %s 들어 있음=%s" % (u, before))
                continue
            if before == inc:
                ok += 1   # 이미 원하는 상태
                continue
            try:
                _call(csm, 8, [c_wchar_p, c_int, c_int, wintypes.DWORD], u, 1 if inc else 0, 0, 0)   # 아래 규칙 덮어쓰지 않음
                ok += 1
                write_log("  %s %s" % ("넣음" if inc else "뺌", u))
            except OSError as ex:
                fail += 1
                write_log("  실패 %s : %s" % (u, ex))
        if not check:
            _call(csm, 16, [])
            write_log("  저장(SaveAll)")
        wrong = 0
        for inc, u in todo:
            try:
                if not check and included(csm, u) != inc:
                    wrong += 1
                    write_log("  확인: 원하는 상태 아님 %s (넣기=%s)" % (u, inc))
            except OSError as ex:
                write_log("  확인 못 함 %s : %s" % (u, ex))
        _release(csm)
        write_log("RESULT ok=%d fail=%d wrong=%d" % (ok, fail, wrong))
        return 0 if not (fail or wrong) else 2
    except Exception as ex:
        write_log("RESULT error %r" % (ex,))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
