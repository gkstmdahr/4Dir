# -*- coding: utf-8 -*-
"""압축 파일을 폴더처럼 열기 (ARCHIVES_VER 1.0.0, 빌드 20 — 사용자 11/5 '추천 5개 다', 경쟁 앱 조사 1번)

- 경로: '::ARC:' + 압축 파일 경로 + '|' + 안쪽 경로('/' 로 구분, 맨 위 = '')  예) ::ARC:F:\\a.zip|그림/2024
- 읽기 전용: 목록 보기·파일 열기(임시 폴더로 풀어서)·복사해 꺼내기. 안에 넣기·지우기·이름 바꾸기는 안 함
- ZIP: 파이썬 zipfile (한글 이름: UTF-8 표시가 없으면 cp949 로 다시 읽음)
- 7Z·RAR·TAR(.gz .bz2 .xz)·CAB·ISO: 윈도우 내장 tar.exe(bsdtar, libarchive) 로 목록 → 고른 것만 풀기(안 되면 통째로 풀어 꺼냄)
- 임시 폴더 %TEMP%\\4dir_arc\\<번호> — 4Dir 를 끌 때 지움 (cleanup)
로그: bin\\log\\4Dir.log [QE.arc]
"""
import os
import re
import time
import shutil
import logging
import zipfile
import tempfile
import threading
import subprocess

ARCHIVES_VER = "1.0.0"
log = logging.getLogger("QE.arc")
PREFIX = "::ARC:"
EXTS = (".zip", ".7z", ".rar", ".tar", ".tgz", ".tar.gz", ".tbz2", ".tar.bz2", ".txz", ".tar.xz", ".cab", ".iso")
TAR_EXE = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
def _long(p):
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetLongPathNameW(p, buf, 1024)
        return buf.value if 0 < n < 1024 else p
    except Exception:
        return p


TMP_ROOT = os.path.join(_long(tempfile.gettempdir()), "4dir_arc")   # 짧은 이름(GKSTMD~1)이 아닌 긴 경로로
_cache = {}          # 압축 파일 경로(소문자) → (mtime, size, {안쪽 경로: (폴더?, 크기, 날짜)})
_lock = threading.Lock()
_seq = [0]
_LINE = re.compile(r"^([dl-])\S*\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\S+\s+\S+\s+\S+)\s(.+)$")


def is_arc(p):
    return bool(p) and p.startswith(PREFIX)


def is_archive_file(name):
    n = name.lower()
    return n.endswith(EXTS)


def make(arc, inner=""):
    return PREFIX + os.path.normpath(arc) + "|" + inner.strip("/")


def split(p):
    body = p[len(PREFIX):]
    arc, _, inner = body.partition("|")
    return arc, inner.strip("/")


def name_of(p):
    arc, inner = split(p)
    return inner.rsplit("/", 1)[-1] if inner else os.path.basename(arc)


def parent_of(p):
    """한 단계 위: 안쪽 맨 위면 압축 파일이 있는 진짜 폴더"""
    arc, inner = split(p)
    if not inner:
        return os.path.dirname(arc)
    return make(arc, inner.rsplit("/", 1)[0] if "/" in inner else "")


def friendly(p):
    arc, inner = split(p)
    return arc + ("\\" + inner.replace("/", "\\") if inner else "")


def chain(p):
    """경로 버튼용 [(이름, 경로)] — 압축 파일부터 안쪽까지"""
    arc, inner = split(p)
    out = [(os.path.basename(arc), make(arc))]
    acc = ""
    for part in [x for x in inner.split("/") if x]:
        acc = acc + "/" + part if acc else part
        out.append((part, make(arc, acc)))
    return out


def _zip_name(zi):
    if zi.flag_bits & 0x800:
        return zi.filename
    try:   # UTF-8 표시 없음 = 옛 도구가 시스템 코드(한국 윈도우 = cp949)로 씀 → zipfile 은 cp437 로 읽어 깨짐
        return zi.filename.encode("cp437").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return zi.filename


def _index(arc):
    """{안쪽 경로: (폴더?, 크기, 날짜)} — 압축 파일이 그대로면 기억해 둔 것"""
    st = os.stat(arc)
    key = os.path.normcase(arc)
    with _lock:
        c = _cache.get(key)
        if c and c[0] == st.st_mtime and c[1] == st.st_size:
            return c[2]
    t0 = time.time()
    idx = {}
    if arc.lower().endswith(".zip"):
        with zipfile.ZipFile(arc) as z:
            for zi in z.infolist():
                n = _zip_name(zi).replace("\\", "/").strip("/")
                if not n:
                    continue
                isd = zi.is_dir()
                try:
                    mt = time.mktime(zi.date_time + (0, 0, -1))
                except (OverflowError, ValueError):
                    mt = 0
                idx[n] = (isd, -1 if isd else zi.file_size, mt, zi.filename)
    else:
        r = subprocess.run([TAR_EXE, "-tvf", arc], capture_output=True, creationflags=0x08000000, timeout=120)
        if r.returncode != 0 and not r.stdout:
            raise OSError(r.stderr.decode("mbcs", "replace").strip() or f"tar.exe 오류 {r.returncode}")
        for line in r.stdout.decode("mbcs", "replace").splitlines():
            m = _LINE.match(line.rstrip("\r"))
            if not m:
                continue
            kind, size, _date, name = m.groups()
            orig = name
            n = name.replace("\\", "/")
            if n.startswith("./"):
                n = n[2:]
            n = n.strip("/")
            if not n or n == ".":
                continue
            isd = kind == "d"
            idx[n] = (isd, -1 if isd else int(size), st.st_mtime, orig)
    for n in list(idx):   # 목록에 없는 중간 폴더 채움
        parts = n.split("/")
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            if d not in idx:
                idx[d] = (True, -1, 0, None)
    log.info("압축 목록 %s : %d개 %.0fms", os.path.basename(arc), len(idx), (time.time() - t0) * 1000)
    with _lock:
        _cache[key] = (st.st_mtime, st.st_size, idx)
    return idx


def list_dir(p, cancel=lambda: False):
    """압축 안 폴더 → [name, is_dir, size, mtime, attrs, full_path, sysidx, label]"""
    arc, inner = split(p)
    try:
        idx = _index(arc)
    except Exception as ex:
        log.exception("압축 목록 실패 %s", arc)
        raise OSError(f"압축 파일을 열 수 없습니다: {os.path.basename(arc)} ({ex})") from ex
    pre = inner + "/" if inner else ""
    out = []
    for n, (isd, size, mt, _o) in idx.items():
        if not n.startswith(pre):
            continue
        rest = n[len(pre):]
        if not rest or "/" in rest:
            continue
        out.append([rest, isd, size, mt, 0, make(arc, n), None, None])
    return out


def exists(p):
    arc, inner = split(p)
    if not os.path.isfile(arc):
        return False
    if not inner:
        return True
    try:
        return inner in _index(arc)
    except Exception:
        return False


def is_dir(p):
    arc, inner = split(p)
    if not inner:
        return True
    try:
        v = _index(arc).get(inner)
    except Exception:
        return False
    return bool(v and v[0])


def _new_tmp():
    with _lock:
        _seq[0] += 1
        d = os.path.join(TMP_ROOT, f"{os.getpid()}_{_seq[0]}")
    os.makedirs(d, exist_ok=True)
    return d


def extract_temp(paths):
    """압축 안 항목들 → 임시 폴더에 풀어 진짜 경로 목록 (폴더는 안쪽 전부). 복사·열기·끌기에 씀"""
    out = []
    by_arc = {}
    for p in paths:
        arc, inner = split(p)
        by_arc.setdefault(arc, []).append(inner)
    for arc, inners in by_arc.items():
        t0 = time.time()
        dest = _new_tmp()
        idx = _index(arc)
        want = []   # 실제로 풀 안쪽 경로 (폴더면 그 아래 전부)
        for inner in inners:
            pre = inner + "/"
            want += [n for n in idx if n == inner or n.startswith(pre)]
        if arc.lower().endswith(".zip"):
            with zipfile.ZipFile(arc) as z:
                byname = {_zip_name(zi).replace("\\", "/").strip("/"): zi for zi in z.infolist()}
                for n in want:
                    isd = idx[n][0]
                    tgt = os.path.join(dest, *n.split("/"))
                    if isd:
                        os.makedirs(tgt, exist_ok=True)
                        continue
                    zi = byname.get(n)
                    if zi is None:
                        continue
                    os.makedirs(os.path.dirname(tgt), exist_ok=True)
                    with z.open(zi) as src, open(tgt, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1048576)
                    mt = idx[n][2]
                    if mt:
                        os.utime(tgt, (mt, mt))
        else:
            names = [idx[n][3] for n in want if idx[n][3] and not idx[n][0]]
            ok = False
            if names:
                r = subprocess.run([TAR_EXE, "-xf", arc, "-C", dest] + names, capture_output=True, creationflags=0x08000000, timeout=3600)
                ok = r.returncode == 0
                if not ok:
                    log.warning("고른 것만 풀기 실패 → 통째로 풀기 %s: %s", os.path.basename(arc), r.stderr.decode("mbcs", "replace")[:200])
            if not ok:
                r = subprocess.run([TAR_EXE, "-xf", arc, "-C", dest], capture_output=True, creationflags=0x08000000, timeout=3600)
                if r.returncode != 0:
                    raise OSError(r.stderr.decode("mbcs", "replace").strip() or "tar.exe 풀기 실패")
            for n in want:
                if idx[n][0]:
                    os.makedirs(os.path.join(dest, *n.split("/")), exist_ok=True)
        for inner in inners:
            rp = os.path.join(dest, *inner.split("/")) if inner else dest
            if os.path.exists(rp):
                out.append(rp)
        log.info("압축에서 꺼냄 %s %d개 → %s %.1f초", os.path.basename(arc), len(want), dest, time.time() - t0)
    return out


def cleanup():
    """4Dir 끌 때: 이 프로그램이 만든 임시 폴더만 지움"""
    if not os.path.isdir(TMP_ROOT):
        return
    for d in os.listdir(TMP_ROOT):
        if d.startswith(f"{os.getpid()}_"):
            shutil.rmtree(os.path.join(TMP_ROOT, d), ignore_errors=True)
