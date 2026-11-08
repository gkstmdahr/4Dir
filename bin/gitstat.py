# -*- coding: utf-8 -*-
"""Git 상태 (GITSTAT_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 'Git 상태 표시')

- 폴더가 Git 작업 폴더 안이면(위로 올라가며 .git 폴더 또는 .git 파일(작업 나무) 찾기) 그 폴더 항목들의 상태를 돌려줌
- 판정은 git.exe 에 맡김: `git --no-optional-locks --literal-pathspecs -C 뿌리 status --porcelain=v1 -z --ignored=matching -- 폴더`
  창 없이(CREATE_NO_WINDOW) · 낮은 우선순위(BELOW_NORMAL — 3ds Max 등 방해 안 함) · 시간 제한 5초
  --no-optional-locks: 장부(index)를 고쳐 쓰지 않음 (다른 Git 프로그램과 부딪치지 않게)
- git.exe 가 PATH 에 없거나 실패하면 None = '모름' (Git 파일을 직접 해석하지 않음)
- 폴더 항목은 안쪽에 바뀐 파일(수정·추가·삭제)이 있으면 modified, 충돌이 있으면 conflict (porcelain 경로 앞부분으로만 판단, 따로 훑지 않음)
- 같은 폴더를 1초 안에 다시 물으면 기억해 둔 결과 — .git\\index 수정 시각이 바뀌면 버림
- branch(path): HEAD 를 읽어 가지 이름, 떨어진 HEAD 면 짧은 해시(7자리)
반환 folder_status(): {이름: 상태} 상태 = normal | modified | added | deleted | conflict | unversioned | ignored
  Git 작업 폴더 밖이면 {} · git 을 못 쓰면 None
로그: bin\\log\\4Dir.log [QE.git]
"""
import os
import time
import shutil
import logging
import threading
import subprocess

GITSTAT_VER = "1.0.0"
log = logging.getLogger("QE.git")
TIMEOUT = 5.0
CACHE_SEC = 1.0
CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
_CONFLICT = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
_lock = threading.Lock()
_root_cache = {}          # 폴더 → (뿌리, git 폴더) 또는 None
_cache = {}               # 폴더 → (시각, index 수정 시각, 결과)
_git_exe = [False, None]  # [찾아봤나, 경로]


def git_exe():
    """PATH 의 git.exe 경로 (없으면 None) — 한 번만 찾음"""
    with _lock:
        if not _git_exe[0]:
            _git_exe[0] = True
            _git_exe[1] = shutil.which("git")
            log.info("git.exe: %s", _git_exe[1] or "없음 (Git 상태 표시 안 함)")
        return _git_exe[1]


def _gitdir_of(d):
    """d 에 .git 이 있으면 git 폴더 경로 (.git 파일이면 gitdir: 줄을 따라감), 없으면 None"""
    g = os.path.join(d, ".git")
    if os.path.isdir(g):
        return g
    if os.path.isfile(g):
        try:
            with open(g, "r", encoding="utf-8", errors="replace") as f:
                line = f.readline().strip()
        except OSError:
            return None
        if line.lower().startswith("gitdir:"):
            p = line[7:].strip()
            if not os.path.isabs(p):
                p = os.path.join(d, p)
            return os.path.normpath(p)
    return None


def repo_root(path):
    """path 가 속한 Git 작업 폴더 (뿌리, git 폴더) 또는 None"""
    folder = os.path.normpath(path)
    with _lock:
        if folder in _root_cache:
            return _root_cache[folder]
    d, found = folder, None
    while True:
        gd = _gitdir_of(d)
        if gd:
            found = (d, gd)
            break
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    with _lock:
        if len(_root_cache) > 5000:
            _root_cache.clear()
        _root_cache[folder] = found
    return found


def _index_mtime(gitdir):
    try:
        return os.path.getmtime(os.path.join(gitdir, "index"))
    except OSError:
        return 0.0


def branch(path):
    """가지 이름, 떨어진 HEAD 면 짧은 해시. Git 밖이면 None"""
    r = repo_root(path)
    if not r:
        return None
    gd = r[1]
    try:
        with open(os.path.join(gd, "HEAD"), "r", encoding="utf-8", errors="replace") as f:
            head = f.read().strip()
    except OSError as e:
        log.warning("HEAD 읽기 실패 %s: %s", gd, e)
        return None
    if head.startswith("ref:"):
        ref = head[4:].strip()
        return ref[11:] if ref.startswith("refs/heads/") else ref
    return head[:7] if head else None


def _run_status(root, rel):
    exe = git_exe()
    if not exe:
        return None
    cmd = [exe, "--no-optional-locks", "--literal-pathspecs", "-C", root, "status", "--porcelain=v1", "-z",
           "--ignored=matching", "--", rel or "."]
    t0 = time.perf_counter()
    try:
        cp = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=TIMEOUT, creationflags=CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS)
    except subprocess.TimeoutExpired:
        log.warning("git status 시간 초과(%.0f초) %s -- %s", TIMEOUT, root, rel)
        return None
    except OSError as e:
        log.warning("git 실행 실패 %s: %s", exe, e)
        return None
    ms = (time.perf_counter() - t0) * 1000
    if cp.returncode != 0:
        log.warning("git status 실패 코드 %d %s -- %s: %s", cp.returncode, root, rel,
                    cp.stderr.decode("utf-8", "replace").strip()[:500])
        return None
    log.debug("git status %s -- %s: %d바이트 %.1fms", root, rel, len(cp.stdout), ms)
    return cp.stdout


def parse_porcelain(raw):
    """porcelain v1 -z 결과 → [(XY, 경로)] (경로는 뿌리 기준 '/' 구분, 폴더면 끝에 '/')"""
    out = []
    parts = raw.decode("utf-8", "replace").split("\0")
    i = 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        xy, p = e[:2], e[3:]
        out.append((xy, p))
        if xy[0] in "RC":       # 이름 바뀜: 다음 칸은 옛 이름
            i += 1
    return out


def _state(xy):
    if xy in _CONFLICT:
        return "conflict"
    if xy == "??":
        return "unversioned"
    if xy == "!!":
        return "ignored"
    if xy[0] in "ARC":
        return "added"
    if "D" in xy:
        return "deleted"
    return "modified"


_RANK = {"conflict": 5, "deleted": 4, "added": 3, "modified": 2}


def folder_status(folder, names=None):
    """folder 안 항목들의 Git 상태 {이름: 상태}. Git 밖이면 {} · git 을 못 쓰면 None"""
    t0 = time.perf_counter()
    folder = os.path.normpath(folder)
    r = repo_root(folder)
    if not r:
        return {}
    root, gd = r
    low = folder.lower() + os.sep
    if (os.sep + ".git" + os.sep) in low or low.startswith(gd.lower() + os.sep):
        return {}
    im = _index_mtime(gd)
    now = time.time()
    with _lock:
        c = _cache.get(folder)
        if c and now - c[0] < CACHE_SEC and c[1] == im:
            res = c[2]
            log.debug("Git 상태 기억 사용 %s", folder)
            if res is None or names is None:
                return None if res is None else dict(res)
            want = set(names)
            return {k: v for k, v in res.items() if k in want}
    if not git_exe():
        return None
    rel = "" if os.path.normcase(folder) == os.path.normcase(root) else os.path.relpath(folder, root).replace("\\", "/")
    raw = _run_status(root, rel)
    if raw is None:
        with _lock:
            _cache[folder] = (now, im, None)
        return None
    pre = rel + "/" if rel else ""
    whole = None            # 폴더 자체가 무시·버전 밖이면 안쪽 전부 같은 상태
    direct, inner = {}, {}
    for xy, p in parse_porcelain(raw):
        if pre and pre.startswith(p) and p.endswith("/"):
            whole = _state(xy)
            continue
        if pre and not p.startswith(pre):
            continue
        sub = p[len(pre):]
        nm, _sep, rest = sub.rstrip("/").partition("/")
        if not nm:
            continue
        st = _state(xy)
        if not rest:      # 같은 이름이 두 번(예: 삭제 예약 + 버전 밖) 나오면 더 중요한 쪽
            if _RANK.get(st, 1 if st == "unversioned" else 0) >= _RANK.get(direct.get(nm), 1 if direct.get(nm) == "unversioned" else 0):
                direct[nm] = st
        elif st in _RANK:     # 안쪽 변경 → 폴더 표시 (버전 밖·무시 파일은 변경으로 안 봄)
            k = "conflict" if st == "conflict" else "modified"
            if _RANK.get(inner.get(nm), 0) < _RANK[k]:
                inner[nm] = k
    try:
        on_disk = names if names is not None else os.listdir(folder)
    except OSError as e:
        log.warning("폴더 읽기 실패 %s: %s", folder, e)
        return {}
    out = {}
    for nm in on_disk:
        if nm == ".git":
            continue
        if whole:
            out[nm] = whole
        elif nm in direct:
            out[nm] = direct[nm]
        elif nm in inner:
            out[nm] = inner[nm]
        else:
            out[nm] = "normal"
    if names is None:
        with _lock:
            if len(_cache) > 500:
                _cache.clear()
            _cache[folder] = (now, im, dict(out))
    n = {}
    for s in out.values():
        n[s] = n.get(s, 0) + 1
    log.debug("Git 상태 %s (뿌리 %s): %s %.1fms", folder, root, n, (time.perf_counter() - t0) * 1000)
    return out


def clear_cache():
    with _lock:
        _cache.clear()
        _root_cache.clear()
