# -*- coding: utf-8 -*-
"""SVN 상태 (맥스 안전형: TortoiseSVN 겹침 아이콘·셸을 부르지 않음)

작업 폴더의 장부 .svn\\wc.db (SVN 1.7+ 공통 형식, sqlite) 를 읽기 전용으로 열어 판정한다.
 - 파일: 장부의 크기·수정시각과 실제 파일 비교 → 같으면 정상. 크기만 같고 시각이 다르면 원본 지문(sha1)으로 확인
 - 장부에 없음 → 버전관리 밖(?) — 단 svn:ignore / svn:global-ignores / 클라이언트 전역 무시 목록에 걸리면 '무시'
 - 장부에 추가(op_depth>0) → 추가(+), 삭제 예약 → 삭제, actual_node 충돌 기록 → 충돌(!)
 - 폴더: 그 폴더 자체 상태만 (하위 변경까지 보려면 하위 전체를 훑어야 해서 안 함)
반환 {이름: 상태} 상태 = normal | modified | added | deleted | conflict | unversioned | ignored
"""
import os
import re
import time
import fnmatch
import hashlib
import sqlite3
import logging
import threading
import ctypes

log = logging.getLogger("QE.svn")
HASH_LIMIT = 32 * 1048576            # 이보다 큰 파일은 지문 비교 안 함(시각만 다르면 '수정'으로 봄)
_root_cache = {}                     # 폴더 → 작업 폴더 뿌리(또는 None)
_lock = threading.Lock()
_default_ignores = None


def wc_root(folder):
    """folder 가 속한 SVN 작업 폴더 뿌리 (.svn\\wc.db 가 있는 곳), 없으면 None"""
    folder = os.path.normpath(folder)
    with _lock:
        if folder in _root_cache:
            return _root_cache[folder]
    d, found = folder, None
    while True:
        if os.path.isfile(os.path.join(d, ".svn", "wc.db")):
            found = d
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


def wc_db_mtime(root):
    try:
        return os.path.getmtime(os.path.join(root, ".svn", "wc.db"))
    except OSError:
        return 0.0


# ---------------------------------------------------------- 속성(skel) 읽기: "(svn:ignore 7 *.tmp\n svn:eol-style 6 native )"
def _skel_atoms(b):
    out, i, n = [], 0, len(b)
    while i < n:
        c = b[i:i + 1]
        if c in (b"(", b")", b" ", b"\n", b"\t", b"\r"):
            i += 1
            continue
        m = re.match(rb"(\d+) ", b[i:i + 12])
        if m:                                   # 길이 붙은 덩어리
            ln = int(m.group(1))
            s = i + len(m.group(0))
            out.append(b[s:s + ln])
            i = s + ln
            continue
        j = i
        while j < n and b[j:j + 1] not in (b" ", b"(", b")", b"\n", b"\t", b"\r"):
            j += 1
        out.append(b[i:j])
        i = j
    return out


def parse_props(blob):
    if not blob:
        return {}
    a = _skel_atoms(bytes(blob))
    return {a[k].decode("utf-8", "replace"): a[k + 1].decode("utf-8", "replace") for k in range(0, len(a) - 1, 2)}


def _client_global_ignores():
    """svn 클라이언트 전역 무시 목록 (%APPDATA%\\Subversion\\config → 없으면 svn 기본값)"""
    global _default_ignores
    if _default_ignores is not None:
        return _default_ignores
    pats = None
    cfg = os.path.join(os.environ.get("APPDATA", ""), "Subversion", "config")
    try:
        sec = ""
        with open(cfg, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if s.startswith("["):
                    sec = s.lower()
                elif sec == "[miscellany]" and s.startswith("global-ignores") and "=" in s:
                    pats = s.split("=", 1)[1].split()
    except OSError:
        pass
    if pats is None:
        pats = "*.o *.lo *.la *.al .libs *.so *.so.[0-9]* *.a *.pyc *.pyo __pycache__ *.rej *~ #*# .#* .*.swp .DS_Store [Tt]humbs.db".split()
    _default_ignores = pats
    return pats


def _ignored(name, pats):
    return any(fnmatch.fnmatchcase(name, p) for p in pats)


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _sha1_eol(path):
    """svn:eol-style 파일: 줄바꿈을 LF 로 맞춘 뒤 지문 (원본 장부는 LF 기준)"""
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(data.replace(b"\r\n", b"\n")).hexdigest()


def judge_file(full, tsize, mtime, cks, props, st=None):
    """버전관리 중인 파일 하나: 'normal' / 'modified' / None(디스크에 없음)"""
    if st is None:
        try:
            st = os.stat(full)
        except OSError:
            return None
    if tsize is not None and tsize >= 0 and st.st_size != tsize:
        return "modified"
    if mtime and abs(st.st_mtime_ns // 1000 - int(mtime)) < 1000 and tsize is not None and tsize >= 0:
        return "normal"
    # 크기는 같은데 시각이 다름(또는 장부에 크기 없음) → 원본 지문으로 확인 (svn 과 같은 방식)
    if not cks or not str(cks).startswith("$sha1$") or st.st_size > HASH_LIMIT:
        return "modified"
    try:
        p = parse_props(props)
        h = _sha1_eol(full) if "svn:eol-style" in p else _sha1(full)
        return "normal" if h == str(cks)[6:] else "modified"
    except OSError:
        return "modified"


def folder_status(folder, names=None):
    """folder 안 항목들의 SVN 상태 {이름: 상태}. SVN 작업 폴더가 아니면 {} (빠르게)"""
    t0 = time.perf_counter()
    root = wc_root(folder)
    if not root:
        return {}
    folder = os.path.normpath(folder)
    if os.path.basename(folder).lower() == ".svn" or (os.sep + ".svn" + os.sep) in folder + os.sep:
        return {}
    rel = "" if folder == root else os.path.relpath(folder, root).replace("\\", "/")
    db = os.path.join(root, ".svn", "wc.db")
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error as e:
        log.warning("wc.db 열기 실패 %s: %s", db, e)
        return {}
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(actual_node)")}
        rows = con.execute("SELECT local_relpath, op_depth, presence, kind, translated_size, last_mod_time, checksum, "
                           "properties FROM nodes WHERE parent_relpath=?", (rel,)).fetchall()
        conflict_cols = [c for c in ("conflict_data", "tree_conflict_data", "conflict_old", "conflict_new",
                                     "conflict_working", "prop_reject") if c in cols]
        where = " OR ".join(f"{c} IS NOT NULL" for c in conflict_cols) or "0"
        conflicts = {r[0].rsplit("/", 1)[-1] for r in con.execute(
            f"SELECT local_relpath FROM actual_node WHERE parent_relpath=? AND ({where})", (rel,))}
        # 무시 목록: 이 폴더의 svn:ignore + 위 폴더들의 svn:global-ignores
        ign = list(_client_global_ignores())
        anc = rel
        first = True
        while True:
            r = con.execute("SELECT properties FROM nodes WHERE local_relpath=? ORDER BY op_depth DESC LIMIT 1",
                            (anc,)).fetchone()
            props = parse_props(r[0]) if r else {}
            if first:
                ign += props.get("svn:ignore", "").split()
                first = False
            ign += props.get("svn:global-ignores", "").split()
            if not anc:
                break
            anc = anc.rsplit("/", 1)[0] if "/" in anc else ""
        pristine = {}
    except sqlite3.Error as e:
        log.warning("wc.db 읽기 실패(잠김 등) %s: %s", db, e)
        con.close()
        return {}
    # 이름별 가장 위 층(op_depth 최대)이 지금 작업 상태
    work, base = {}, {}
    for lr, depth, presence, kind, tsize, mtime, cks, props in rows:
        nm = lr.rsplit("/", 1)[-1]
        if depth == 0:
            base[nm] = (presence, kind, tsize, mtime, cks, props)
        if nm not in work or depth > work[nm][0]:
            work[nm] = (depth, presence, kind, tsize, mtime, cks, props)
    out = {}
    on_disk = names if names is not None else os.listdir(folder)
    disk = set(on_disk)
    for nm in on_disk:
        if nm == ".svn":
            continue
        w = work.get(nm)
        if nm in conflicts:
            out[nm] = "conflict"
            continue
        if w is None or w[1] in ("not-present", "excluded", "server-excluded") or (w[0] > 0 and w[1] == "base-deleted"):
            if w is not None and w[0] > 0 and w[1] == "base-deleted":
                out[nm] = "deleted"         # 삭제 예약인데 디스크엔 남아 있음
            else:
                out[nm] = "ignored" if _ignored(nm, ign) else "unversioned"
            continue
        depth, presence, kind, tsize, mtime, cks, props = w
        if depth > 0:
            out[nm] = "added"
            continue
        if kind != "file":
            out[nm] = "normal"
            continue
        r = judge_file(os.path.join(folder, nm), tsize, mtime, cks, props)
        if r:
            out[nm] = r
    # 장부에는 있는데 디스크에 없는 파일(누락/삭제)은 목록에 안 보이므로 표시 안 함
    con.close()
    n = {}
    for s in out.values():
        n[s] = n.get(s, 0) + 1
    log.debug("SVN 상태 %s: %s %.1fms", folder, n, (time.perf_counter() - t0) * 1000)
    return out


# ================================================================ 작업 폴더 전체: '안쪽에 변경 있음' 폴더 표시 (TortoiseSVN 처럼)
# 변경 = 수정 / 추가 / 삭제 예약 / 충돌 / 누락(장부엔 있는데 디스크에 없음). 버전관리 밖(?) 파일은 폴더를 빨갛게 하지 않음(Tortoise 기본과 같음)
DIRTY = ("modified", "added", "deleted", "conflict", "missing")


def _connect(root):
    return sqlite3.connect(f"file:{os.path.join(root, '.svn', 'wc.db')}?mode=ro", uri=True, timeout=2.0)


def _structural(con):
    """추가·삭제 예약(op_depth>0)·충돌 경로 {relpath: 상태}"""
    out = {}
    for lr, presence in con.execute("SELECT local_relpath, presence FROM nodes WHERE op_depth>0"):
        out[lr] = "deleted" if presence == "base-deleted" else "added"
    cols = {r[1] for r in con.execute("PRAGMA table_info(actual_node)")}
    cc = [c for c in ("conflict_data", "tree_conflict_data", "conflict_old", "conflict_new", "conflict_working",
                      "prop_reject") if c in cols]
    if cc:
        for (lr,) in con.execute(f"SELECT local_relpath FROM actual_node WHERE {' OR '.join(c + ' IS NOT NULL' for c in cc)}"):
            out[lr] = "conflict"
    return out


QUICK_MAX = 30000   # 먼저 확인은 장부 파일이 이보다 적은 폴더만 (많으면 전체 훑기를 기다림)


def _under(sub):
    """relpath 범위 조건 (sub 아래). '/' 다음 글자는 '0' → 색인 쓰는 범위 비교"""
    return ("local_relpath >= ? AND local_relpath < ?", (sub + "/", sub + "0")) if sub else ("1=1", ())


def scan_wc(root, cancel=lambda: False, sub=""):
    """작업 폴더(또는 그 안 sub 폴더만)를 훑어 변경 경로 {relpath: 상태}. 전체는 작업 프로세스에서 실행 — 메모리 많이 씀"""
    t0 = time.time()
    con = _connect(root)
    cond, args = _under(sub)
    wc = {r[0]: r[1:] for r in con.execute(
        "SELECT local_relpath, translated_size, last_mod_time, checksum, properties FROM nodes "
        f"WHERE op_depth=0 AND kind='file' AND presence='normal' AND {cond}", args)}
    dirty = _structural(con)
    if sub:
        dirty = {k: v for k, v in dirty.items() if k == sub or k.startswith(sub + "/")}
    con.close()
    seen = set()
    stack, n = [os.path.join(root, sub.replace("/", os.sep)) if sub else root], 0
    while stack:
        if cancel():
            return None
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.name == ".svn":
                        continue
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                            continue
                        rel = os.path.relpath(e.path, root).replace("\\", "/")
                        row = wc.get(rel)
                        if row is None:
                            continue
                        seen.add(rel)
                        n += 1
                        r = judge_file(e.path, row[0], row[1], row[2], row[3], e.stat(follow_symlinks=False))
                        if r == "modified" and rel not in dirty:
                            dirty[rel] = "modified"
                    except OSError:
                        continue
        except OSError:
            continue
    for rel in wc:
        if rel not in seen and rel not in dirty:
            dirty[rel] = "missing"
    log.info("SVN 작업 폴더 훑기 %s%s: 장부 파일 %s, 변경 %d, %.1f초", root, f" [{sub}]" if sub else "",
             f"{len(wc):,}", len(dirty), time.time() - t0)
    return dirty


def count_under(root, sub):
    con = _connect(root)
    try:
        cond, args = _under(sub)
        return con.execute(f"SELECT COUNT(*) FROM nodes WHERE op_depth=0 AND kind='file' AND {cond}", args).fetchone()[0]
    finally:
        con.close()


def ancestors(rel):
    out = [""]
    parts = rel.split("/")[:-1]
    for i in range(len(parts)):
        out.append("/".join(parts[:i + 1]))
    return out


class WcWatch:
    """작업 폴더 하나: 처음 1회 전체 훑기(작업 프로세스) + 이후 윈도우 변경 알림으로 바뀐 파일만 다시 판정(실시간)"""

    def __init__(self, root, notify):
        self.root = root
        self.notify = notify            # notify(root) — 화면 다시 그리기 요청 (작업 스레드에서 불림)
        self.dirty = {}                 # relpath → 상태
        self.dirty_dirs = set()         # 변경을 안에 품은 폴더 relpath ('' = 뿌리)
        self.state = "scanning"
        self.lock = threading.Lock()
        self._cancel = False
        self._pending = set()
        self._timer = None
        self._worker = None
        self.quick = {}                 # 전체 훑기 전 '먼저 확인'한 폴더 relpath → 그 안 변경 품은 폴더들
        threading.Thread(target=self._initial, daemon=True, name=f"svn-scan {root}").start()
        threading.Thread(target=self._watch, daemon=True, name=f"svn-watch {root}").start()

    def _rel(self, folder):
        return "" if os.path.normcase(folder) == os.path.normcase(self.root) else \
            os.path.relpath(folder, self.root).replace("\\", "/")

    def folder_dirty(self, folder):
        """folder(절대경로) 안 어딘가에 변경이 있나. 아직 모르면 None (전체 훑기 중이고 먼저 확인도 안 한 곳)"""
        rel = self._rel(folder)
        with self.lock:
            if self.state == "ready":
                return rel in self.dirty_dirs
            for q, dd in self.quick.items():   # 먼저 확인한 폴더 안쪽이면 그 결과 + 그사이 실시간 변경
                if rel == q or rel.startswith(q + "/") or not q:
                    live = set()
                    for k, v in self.dirty.items():
                        live.update(ancestors(k))
                    return rel in dd or rel in live
        return None

    def quick_scan(self, folder):
        """전체 훑기 전에 이 폴더 안쪽만 먼저 확인 (보고 있는 폴더). 성공하면 True"""
        if self.state == "ready":
            return True
        rel = self._rel(folder)
        with self.lock:
            if any(rel == q or rel.startswith(q + "/") or not q for q in self.quick):
                return True
        t0 = time.time()
        try:
            n = count_under(self.root, rel)
            if n > QUICK_MAX:
                log.info("SVN 먼저 확인 생략 %s (장부 파일 %s개 > %s) → 전체 훑기 기다림", folder, f"{n:,}", f"{QUICK_MAX:,}")
                return False
            res = scan_wc(self.root, lambda: self._cancel or self.state == "ready", sub=rel)
        except Exception:
            log.exception("SVN 먼저 확인 실패 %s", folder)
            return False
        if res is None:
            return self.state == "ready"
        dd = set()
        for k, v in res.items():
            dd.update(ancestors(k))
            if v in ("added", "deleted", "conflict", "missing"):
                dd.add(k)
        with self.lock:
            self.quick[rel] = dd
        log.info("SVN 먼저 확인 %s: 장부 파일 %s, 변경 %d, %.2f초", folder, f"{n:,}", len(res), time.time() - t0)
        return True

    def _rebuild_dirs(self):
        dd = set()
        for rel in self.dirty:
            dd.update(ancestors(rel))
            if self.dirty[rel] in ("added", "deleted", "conflict", "missing"):
                dd.add(rel)      # 추가·삭제된 '폴더' 자체도 (안에서 본 상태로)
        self.dirty_dirs = dd

    def _initial(self):
        import subprocess
        import sys
        import json
        t0 = time.time()
        cmd = [sys.executable, "-B", "-X", "utf8", os.path.abspath(__file__), "--scan", self.root, str(os.getpid())]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                 creationflags=0x08000000 | 0x00004000, encoding="utf-8", errors="replace")
            self._worker = p
            out, _ = p.communicate()
            res = json.loads(out.strip().splitlines()[-1]) if out.strip() else None
        except Exception:
            log.exception("SVN 전체 훑기 작업 실패 → 4Dir 안에서 훑음 %s", self.root)
            res = scan_wc(self.root, lambda: self._cancel)
        self._worker = None
        if self._cancel or res is None:
            return
        with self.lock:
            res.update(self.dirty)       # 훑는 동안 들어온 실시간 변경이 이김
            self.dirty = res
            self._rebuild_dirs()
        self.state = "ready"
        self.quick = {}
        log.info("SVN 전체 상태 준비 %s: 변경 %d, 변경 품은 폴더 %d, %.1f초", self.root, len(self.dirty),
                 len(self.dirty_dirs), time.time() - t0)
        self.notify(self.root)

    def _watch(self):
        import win32file
        import win32con
        try:
            h = win32file.CreateFile(self.root, 0x0001, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE |
                                     win32con.FILE_SHARE_DELETE, None, win32con.OPEN_EXISTING,
                                     win32con.FILE_FLAG_BACKUP_SEMANTICS, None)
        except Exception as e:
            log.warning("SVN 감시 시작 실패 %s: %s", self.root, e)
            return
        self._h = h
        flags = (win32con.FILE_NOTIFY_CHANGE_FILE_NAME | win32con.FILE_NOTIFY_CHANGE_DIR_NAME |
                 win32con.FILE_NOTIFY_CHANGE_SIZE | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)
        log.info("SVN 실시간 감시 시작 %s", self.root)
        try:
            while not self._cancel:
                try:
                    res = win32file.ReadDirectoryChangesW(h, 65536, True, flags, None, None)
                except Exception as e:
                    if not self._cancel:
                        log.warning("SVN 감시 끊김 %s: %s", self.root, e)
                    break
                with self.lock:
                    if not res:
                        self._pending.add("*")          # 알림 넘침 → 전체 다시
                    for _a, rel in res or []:
                        self._pending.add(rel.replace("\\", "/"))
                if self._timer:
                    self._timer.cancel()
                self._timer = threading.Timer(0.5, self._apply)     # 0.5초 모아서 한 번에
                self._timer.daemon = True
                self._timer.start()
        finally:
            try:
                h.Close()
            except Exception:
                pass
            log.info("SVN 실시간 감시 끝 %s", self.root)

    def _apply(self):
        with self.lock:
            pend, self._pending = self._pending, set()
        if not pend or self._cancel:
            return
        t0 = time.perf_counter()
        if "*" in pend:
            log.info("SVN 알림 넘침 → 전체 다시 훑기 %s", self.root)
            self.state = "scanning"
            threading.Thread(target=self._initial, daemon=True).start()
            return
        wcdb = any(p.lower().startswith(".svn/") for p in pend)
        files = {p for p in pend if not p.lower().startswith(".svn/") and p.lower() != ".svn"}
        try:
            con = _connect(self.root)
        except sqlite3.Error:
            return
        try:
            new = dict(self.dirty)
            if wcdb:
                # 커밋·업데이트·되돌리기 = 장부가 바뀜 → 추가/삭제/충돌 다시 읽고, 기존 변경 파일들 다시 판정
                files |= {r for r, s in new.items() if s in ("modified", "missing")}
                new = {r: s for r, s in new.items() if s in ("modified", "missing")}
                new.update(_structural(con))
            for rel in files:
                full = os.path.join(self.root, rel.replace("/", os.sep))
                if os.path.isdir(full):
                    continue
                row = con.execute("SELECT translated_size, last_mod_time, checksum, properties FROM nodes "
                                  "WHERE local_relpath=? AND op_depth=0 AND kind='file' AND presence='normal'",
                                  (rel,)).fetchone()
                if row is None:
                    # 장부에 없는 파일: 지워진 '폴더' 안 파일들은 폴더 단위로 누락 확인
                    if not os.path.exists(full):
                        for (lr,) in con.execute("SELECT local_relpath FROM nodes WHERE op_depth=0 AND kind='file' AND "
                                                 "presence='normal' AND (local_relpath LIKE ? ESCAPE '\\') LIMIT 5000",
                                                 (rel.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%",)):
                            if not os.path.exists(os.path.join(self.root, lr.replace("/", os.sep))):
                                new[lr] = "missing"
                    continue
                r = judge_file(full, *row)
                if r is None:
                    new[rel] = "missing"
                elif r == "modified":
                    if new.get(rel) not in ("added", "conflict", "deleted"):
                        new[rel] = "modified"
                elif new.get(rel) in ("modified", "missing"):
                    del new[rel]
        except sqlite3.Error as e:
            log.warning("SVN 실시간 판정 실패 %s: %s", self.root, e)
            return
        finally:
            con.close()
        changed = new != self.dirty
        with self.lock:
            self.dirty = new
            self._rebuild_dirs()
        log.debug("SVN 실시간 %s: 알림 %d개 → 변경 %d개 (%s) %.1fms", self.root, len(pend), len(new),
                  "바뀜" if changed else "그대로", (time.perf_counter() - t0) * 1000)
        if changed or wcdb:
            self.notify(self.root)

    def stop(self):
        self._cancel = True
        if self._worker is not None and self._worker.poll() is None:
            self._worker.kill()
        try:
            import win32file
            win32file.CancelIoEx(self._h, None)
        except Exception:
            pass


_watches = {}


def watch_for(root, notify):
    """작업 폴더마다 감시 하나 (처음 들어갈 때 만듦)"""
    with _lock:
        w = _watches.get(root)
        if w is None:
            w = _watches[root] = WcWatch(root, notify)
        return w


def stop_all():
    with _lock:
        for w in _watches.values():
            w.stop()
        _watches.clear()


def _worker_main(argv):
    """python svnstat.py --scan <작업 폴더> <4Dir pid> → 마지막 줄에 JSON {relpath: 상태}. 4Dir 이 꺼지면 스스로 중단"""
    import sys
    import json
    root, ppid = argv[0], int(argv[1])
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = ctypes.c_void_p
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass(ctypes.c_void_p(k.GetCurrentProcess()), 0x00100000)   # 백그라운드 모드
    hp = k.OpenProcess(0x00100000, False, ppid)
    last = [0.0, False]

    def cancel():
        now = time.time()
        if now - last[0] > 1.0:
            last[0] = now
            last[1] = not hp or k.WaitForSingleObject(ctypes.c_void_p(hp), 0) == 0
        return last[1]
    res = scan_wc(root, cancel)
    if res is None:
        return 2
    sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--scan":
        sys.exit(_worker_main(sys.argv[2:]))
