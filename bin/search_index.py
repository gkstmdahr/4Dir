# -*- coding: utf-8 -*-
"""4Dir 빠른 전체 검색 색인 (관리자 권한 없이)

- 만들기: 지정한 드라이브/폴더를 os.scandir 로 훑음 (이름·크기·날짜만, 파일 내용·썸네일 안 읽음)
  윈도우 '백그라운드 모드'(낮은 CPU·디스크 우선순위) 스레드에서.
- 보관: 이름을 한 덩어리 글자열(blob) + 위치표(offs)로 → 100만 개도 수십 MB.
- 실시간: 범위마다 ReadDirectoryChangesW(하위 폴더 포함 변경 알림, 관리자 권한 불필요)로 생성·삭제·이름변경 반영(delta).
  알림이 넘치면(대량 작업) 그 범위만 다시 만들기 예약.
- 저장: bin\\index\\index.bin (다음 실행 때 바로 검색 가능, 뒤에서 다시 훑어 갱신)
"""
import os
import re
import time
import zlib
import stat
import array
import bisect
import pickle
import threading
import logging
import ctypes

log = logging.getLogger("QE.search")
IDX_VER = 3   # 2: 수정일 64비트(2038년 넘는 날짜 파일 대응) / 3: 이름 덩어리를 UTF-8 바이트로(메모리 절반, 검색 약 10배)
REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT
SKIP_DIRS = {"$recycle.bin", "system volume information", "$windows.~bt", "$windows.~ws"}
MAX_DELTA = 200_000


def _bg_thread(on):
    """윈도우 스레드 백그라운드 모드 (CPU·디스크 우선순위 낮춤)"""
    try:
        k = ctypes.windll.kernel32
        k.SetThreadPriority(k.GetCurrentThread(), 0x00010000 if on else 0x00020000)
    except Exception:
        pass


def reachable(path, timeout=3.0):
    box = {}
    th = threading.Thread(target=lambda: box.setdefault("ok", os.path.isdir(path)), daemon=True)
    th.start()
    th.join(timeout)
    return box.get("ok", False)


# ================================================================ 검색어 해석
class Query:
    """공백 = AND. 경로 조각(\\ 포함) = 전체 경로에 포함. * ? = 이름 전체 와일드카드. '.max' = 확장자."""

    def __init__(self, text):
        self.text = text.strip()
        self.name_terms, self.path_terms = [], []
        for t in self.text.lower().replace("/", "\\").split():
            if "\\" in t:
                self.path_terms.append(t)
            else:
                self.name_terms.append(t)
        self.checks = [self._name_check(t) for t in self.name_terms]
        # 덩어리(blob)에서 후보 찾을 정규식: 가장 긴 이름 조건 하나
        self.seed = None
        if self.name_terms:
            t = max(self.name_terms, key=lambda x: (("*" not in x and "?" not in x), len(x)))
            pat = self._blob_pattern(t)
            self.seed = re.compile(pat, re.MULTILINE) if pat is not None else None

    @staticmethod
    def _glob_re(t):
        return "".join("[^\n]*" if c == "*" else "[^\n]" if c == "?" else re.escape(c) for c in t)

    @staticmethod
    def _blob_pattern(t):
        """소문자 UTF-8 덩어리용 바이트 정규식 (? = 글자 1개 = 1~4바이트)"""
        def esc(x):
            return re.escape(x.encode("utf-8", "surrogatepass"))
        if "*" in t or "?" in t:
            # 와일드카드 전체 정규식은 느림(234만 개 0.9초) → 가장 긴 글자 조각만 후보로 찾고 정확한 판정은 checks 가 함
            frag = max(re.split(r"[*?]", t), key=len)
            if not frag:
                return None
            return (b"^" if t.startswith(frag) else b"") + esc(frag) + (b"$" if t.endswith(frag) else b"")
        if t.startswith(".") and len(t) > 1 and "." not in t[1:]:
            return esc(t) + b"$"
        return esc(t)

    def _name_check(self, t):
        if "*" in t or "?" in t:
            rx = re.compile("^" + self._glob_re(t) + "$", re.IGNORECASE)
            return lambda n: rx.match(n) is not None
        if t.startswith(".") and len(t) > 1 and "." not in t[1:]:
            return lambda n: n.lower().endswith(t)
        return lambda n: t in n.lower()

    def match(self, name, full):
        if not all(c(name) for c in self.checks):
            return False
        if self.path_terms:
            fl = full.lower()
            return all(p in fl for p in self.path_terms)
        return True

    def empty(self):
        return not self.name_terms and not self.path_terms


# ================================================================ 색인 덩어리 (한 번 만든 뒤 바뀌지 않음)
class Snapshot:
    def __init__(self):
        self.roots = []
        self.dirs = []                 # 폴더 경로 목록 (번호 = 위치)
        self.blob = b"\n"              # "\n이름\n이름\n..." UTF-8 바이트
        self.lblob = b"\n"             # 위의 소문자판 (검색용, 저장 안 함)
        self.offs = array.array("Q")   # 이름 i 의 blob 시작 위치(바이트)
        self.par = array.array("I")    # 이름 i 의 폴더 번호
        self.isdir = bytearray()
        self.size = array.array("q")
        self.mtime = array.array("q")
        self.built = 0.0

    def __len__(self):
        return len(self.offs)

    def name(self, i):
        end = self.offs[i + 1] - 1 if i + 1 < len(self.offs) else len(self.blob) - 1
        return self.blob[self.offs[i]:end].decode("utf-8", "surrogatepass")

    def full(self, i):
        return os.path.join(self.dirs[self.par[i]], self.name(i))

    # ---------------------------------------------------------- 저장/불러오기
    def save(self, path):
        data = pickle.dumps((IDX_VER, self.roots, self.dirs, self.blob, self.offs.tobytes(), self.par.tobytes(),
                             bytes(self.isdir), self.size.tobytes(), self.mtime.tobytes(), self.built), protocol=5)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(zlib.compress(data, 1))
        os.replace(tmp, path)

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            t = pickle.loads(zlib.decompress(f.read()))
        if t[0] != IDX_VER:
            raise ValueError("색인 형식이 다름")
        s = cls()
        s.roots, s.dirs, s.blob = t[1], t[2], t[3]
        s.lblob = s.blob.lower()
        s.offs.frombytes(t[4])
        s.par.frombytes(t[5])
        s.isdir = bytearray(t[6])
        s.size.frombytes(t[7])
        s.mtime.frombytes(t[8])
        s.built = t[9]
        return s


def build_snapshot(roots, cancel, progress=None):
    """roots 를 훑어 Snapshot 생성. cancel() 이 True 면 None"""
    _bg_thread(True)
    t0 = time.time()
    s = Snapshot()
    s.roots = list(roots)
    names = []
    n_last = 0
    try:
        for root in roots:
            if not reachable(root):
                log.warning("색인: 응답 없음, 건너뜀 %s", root)
                continue
            stack = [root]
            while stack:
                if cancel():
                    return None
                d = stack.pop()
                did = len(s.dirs)
                s.dirs.append(d)
                sub = []
                try:
                    with os.scandir(d) as it:
                        for e in it:
                            try:
                                st = e.stat(follow_symlinks=False)
                                dd = e.is_dir(follow_symlinks=False)
                            except OSError:
                                continue
                            names.append(e.name)
                            s.par.append(did)
                            s.isdir.append(1 if dd else 0)
                            s.size.append(-1 if dd else st.st_size)
                            s.mtime.append(int(st.st_mtime) if st.st_mtime > 0 else 0)
                            if dd and not (st.st_file_attributes & REPARSE) and e.name.lower() not in SKIP_DIRS:
                                sub.append(e.path)
                except OSError:
                    pass
                stack.extend(reversed(sub))
                if progress and len(names) - n_last >= 50_000:
                    n_last = len(names)
                    progress(len(names), root)
        pos = 1
        offs = s.offs
        enc = []
        for n in names:
            b = n.encode("utf-8", "surrogatepass")
            enc.append(b)
            offs.append(pos)
            pos += len(b) + 1
        del names
        s.blob = b"\n" + b"\n".join(enc) + b"\n"
        del enc
        s.lblob = s.blob.lower()
        s.built = time.time()
        log.info("색인 완료 범위 %s: 항목 %s, 폴더 %s, %.1f초, 글자열 %.1fMB",
                 roots, f"{len(s):,}", f"{len(s.dirs):,}", time.time() - t0, len(s.blob) / 1048576)
        return s
    finally:
        _bg_thread(False)


# ================================================================ 색인 전체 (덩어리 + 실시간 변경분 + 감시)
class SearchIndex:
    def __init__(self, store_dir, notify=None):
        self.store = store_dir
        os.makedirs(store_dir, exist_ok=True)
        self.path = os.path.join(store_dir, "index.bin")
        self.notify = notify or (lambda kind, info: None)
        self.roots = []
        self.base = Snapshot()
        self.lock = threading.Lock()
        self.added = {}            # 경로(소문자) → (이름, 폴더여부, 크기, 날짜, 원래경로, 시각)
        self.removed = {}          # 경로(소문자) → 시각
        self.removed_pfx = {}      # 지워진 폴더 경로(소문자)+"\\" → 시각
        self.state = "idle"        # idle | loading | building | ready
        self._cancel = False
        self._build_th = None
        self._watchers = {}        # root → (thread, handle)
        self._rebuild_timer = None
        self._worker = None        # 색인 작업 프로세스 (subprocess.Popen)
        self.events = 0

    # ---------------------------------------------------------- 시작/정지
    def start(self, roots):
        """범위를 정하고: 저장본 불러오기 → 감시 시작 → 뒤에서 다시 만들기"""
        self.roots = [os.path.normpath(r) + ("\\" if len(os.path.normpath(r)) == 2 else "") for r in roots]
        threading.Thread(target=self._start_bg, daemon=True, name="index-start").start()

    def _start_bg(self):
        self.state = "loading"
        if os.path.exists(self.path):
            try:
                t0 = time.time()
                snap = Snapshot.load(self.path)
                if [r.lower() for r in snap.roots] == [r.lower() for r in self.roots]:
                    self.base = snap
                    self.state = "ready"
                    log.info("색인 저장본 불러옴 %s개 %.1f초 (만든 시각 %s)", f"{len(snap):,}", time.time() - t0,
                             time.strftime("%m-%d %H:%M", time.localtime(snap.built)))
                    self.notify("ready", len(snap))
                else:
                    log.info("저장본 범위가 달라 새로 만듦")
            except Exception:
                log.exception("색인 저장본 불러오기 실패 → 새로 만듦")
        self._start_watchers()
        self.rebuild()

    def stop(self):
        self._cancel = True
        w = getattr(self, "_worker", None)
        if w is not None and w.poll() is None:
            w.kill()   # 내가 띄운 색인 작업 프로세스만
            log.info("색인 작업 프로세스 중지")
        for root, (th, h) in list(self._watchers.items()):
            try:
                ctypes.windll.kernel32.CancelIoEx(ctypes.c_void_p(int(h)), None)
            except Exception:
                pass
        self._watchers.clear()

    def set_roots(self, roots):
        self.stop()
        if self._build_th and self._build_th.is_alive():
            self._build_th.join(10)   # 이전 만들기가 끝나야 새 범위로 다시 만들 수 있음
        self._cancel = False
        with self.lock:
            self.added.clear()
            self.removed.clear()
            self.removed_pfx.clear()
        self.base = Snapshot()
        self.start(roots)

    # ---------------------------------------------------------- 만들기
    def rebuild(self):
        if self._build_th and self._build_th.is_alive():
            return
        self._build_th = threading.Thread(target=self._rebuild_bg, daemon=True, name="index-build")
        self._build_th.start()

    def _build_in_worker(self):
        """색인 만들기를 별도 작업 프로세스에서 → 끝나면 그 프로세스는 종료되어 메모리(최고 1GB)를 통째로 돌려줌.
        4Dir 본체는 결과 파일만 불러옴. 반환: Snapshot / None(취소·실패)"""
        import subprocess
        import sys
        exe = sys.executable
        out = self.path + ".new"
        cmd = [exe, "-B", "-X", "utf8", os.path.abspath(__file__), "--build", out, str(os.getpid())] + self.roots
        log.info("색인 작업 프로세스 시작: %s", " ".join(cmd))
        t0 = time.time()
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 creationflags=0x08000000 | 0x00004000,   # 창 없음 + 낮은 우선순위
                                 encoding="utf-8", errors="replace")
        except Exception:
            log.exception("작업 프로세스 실행 실패 → 4Dir 안에서 만듦")
            return build_snapshot(self.roots, lambda: self._cancel, lambda n, root: self.notify("progress", (n, root)))
        self._worker = p
        ok = False
        for line in p.stdout:
            line = line.rstrip()
            if line.startswith("P "):
                _, n, root = line.split(" ", 2)
                self.notify("progress", (int(n), root))
            elif line.startswith("OK"):
                ok = True
            elif line:
                log.info("작업 프로세스: %s", line)
            if self._cancel:
                break
        if self._cancel and p.poll() is None:
            p.kill()
        rc = p.wait()
        self._worker = None
        log.info("색인 작업 프로세스 끝 rc=%s %.1f초", rc, time.time() - t0)
        if self._cancel or not ok or not os.path.exists(out):
            return None
        snap = Snapshot.load(out)
        os.replace(out, self.path)   # 작업 프로세스가 이미 저장함 → 이름만 바꿈
        return snap

    def _rebuild_bg(self):
        if not self.roots:
            self.state = "ready"
            self.notify("ready", 0)
            return
        was_ready = self.state == "ready"
        self.state = "building" if not was_ready else "ready"
        start = time.time()
        self.notify("building", 0)
        try:
            snap = self._build_in_worker()
        except Exception:
            log.exception("색인 만들기 실패")
            snap = None
        if snap is None:
            if not was_ready and not self._cancel:
                self.state = "ready"
                self.notify("ready", len(self.base))
            return
        with self.lock:
            self.base = snap
            # 다시 만들기 시작 전 변경분은 새 덩어리에 이미 들어 있음 → 정리
            self.added = {k: v for k, v in self.added.items() if v[5] >= start}
            self.removed = {k: t for k, t in self.removed.items() if t >= start}
            self.removed_pfx = {k: t for k, t in self.removed_pfx.items() if t >= start}
        self.state = "ready"
        self.notify("ready", len(snap))
        log.info("새 색인 적용 %s개 (저장본 %.1fMB)", f"{len(snap):,}",
                 os.path.getsize(self.path) / 1048576 if os.path.exists(self.path) else 0)

    def _schedule_rebuild(self, why):
        log.info("색인 다시 만들기 예약 (%s)", why)
        if self._rebuild_timer:
            self._rebuild_timer.cancel()
        self._rebuild_timer = threading.Timer(15.0, self.rebuild)
        self._rebuild_timer.daemon = True
        self._rebuild_timer.start()

    # ---------------------------------------------------------- 실시간 감시 (ReadDirectoryChangesW)
    def _start_watchers(self):
        for root in self.roots:
            if root in self._watchers:
                continue
            th = threading.Thread(target=self._watch, args=(root,), daemon=True, name=f"watch {root}")
            self._watchers[root] = (th, 0)
            th.start()

    def _watch(self, root):
        import win32file
        import win32con
        if not reachable(root):
            log.warning("감시: 응답 없음 %s", root)
            return
        try:
            h = win32file.CreateFile(root, 0x0001, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                                     None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_BACKUP_SEMANTICS, None)
        except Exception as e:
            log.warning("감시 시작 실패 %s: %s", root, e)
            return
        self._watchers[root] = (threading.current_thread(), int(h))
        log.info("실시간 감시 시작 %s", root)
        flags = (win32con.FILE_NOTIFY_CHANGE_FILE_NAME | win32con.FILE_NOTIFY_CHANGE_DIR_NAME |
                 win32con.FILE_NOTIFY_CHANGE_SIZE | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)
        try:
            while not self._cancel:
                try:
                    res = win32file.ReadDirectoryChangesW(h, 65536, True, flags, None, None)
                except Exception as e:
                    if not self._cancel:
                        log.warning("감시 끊김 %s: %s", root, e)
                    break
                if not res:
                    self._schedule_rebuild(f"알림 넘침 {root}")
                    continue
                self._apply(root, res)
        finally:
            try:
                h.Close()
            except Exception:
                pass
            log.info("실시간 감시 끝 %s", root)

    def _apply(self, root, res):
        now = time.time()
        for action, rel in res:
            full = os.path.join(root, rel)
            key = full.lower()
            self.events += 1
            if action in (2, 4):            # 삭제 / 이름변경 전
                with self.lock:
                    self.added.pop(key, None)
                    self.removed[key] = now
                    self.removed_pfx[key + "\\"] = now
            else:                           # 추가 / 수정 / 이름변경 후
                try:
                    st = os.stat(full, follow_symlinks=False)
                except OSError:
                    continue
                dd = stat.S_ISDIR(st.st_mode)
                with self.lock:
                    self.removed.pop(key, None)
                    self.removed_pfx.pop(key + "\\", None)
                    self.added[key] = (os.path.basename(full), dd, -1 if dd else st.st_size, int(st.st_mtime), full, now)
                if dd and action in (1, 5):    # 새로 생긴/옮겨 온 폴더 → 안의 것도 넣음
                    self._add_tree(full, now)
        if len(self.added) > MAX_DELTA:
            self._schedule_rebuild("변경분이 너무 많음")

    def _add_tree(self, d, now):
        stack = [d]
        n = 0
        while stack and n < 100_000:
            p = stack.pop()
            try:
                with os.scandir(p) as it:
                    for e in it:
                        try:
                            st = e.stat(follow_symlinks=False)
                            dd = e.is_dir(follow_symlinks=False)
                        except OSError:
                            continue
                        with self.lock:
                            self.added[e.path.lower()] = (e.name, dd, -1 if dd else st.st_size, int(st.st_mtime), e.path, now)
                        n += 1
                        if dd and not (st.st_file_attributes & REPARSE):
                            stack.append(e.path)
            except OSError:
                pass

    # ---------------------------------------------------------- 검색
    def count(self):
        return len(self.base) + len(self.added)

    def search(self, text, limit=5000):
        """반환 (결과[(경로, 이름, 폴더여부, 크기, 날짜)], 전체 일치 수, ms)"""
        t0 = time.perf_counter()
        q = Query(text)
        if q.empty():
            return [], 0, 0.0
        base = self.base
        with self.lock:
            added = dict(self.added)
            removed = dict(self.removed)
            rpfx = tuple(self.removed_pfx)
        out, total = [], 0

        def gone(fl):
            return fl in removed or fl in added or (rpfx and fl.startswith(rpfx))

        if q.seed is not None and len(base):
            last = -1
            offs = base.offs
            for m in q.seed.finditer(base.lblob):
                i = bisect.bisect_right(offs, m.start()) - 1
                if i == last or i < 0:
                    continue
                last = i
                name = base.name(i)
                if not all(c(name) for c in q.checks):
                    continue
                full = os.path.join(base.dirs[base.par[i]], name)
                if q.path_terms and not all(p in full.lower() for p in q.path_terms):
                    continue
                if (removed or added or rpfx) and gone(full.lower()):
                    continue
                total += 1
                if len(out) < limit:
                    out.append((full, name, bool(base.isdir[i]), base.size[i], base.mtime[i]))
        elif q.path_terms and len(base):    # 경로 조각만 있는 검색: 폴더 경로에서 찾기
            hit_dirs = {k for k, d in enumerate(base.dirs) if all(p in d.lower() + "\\" for p in q.path_terms)}
            for i in range(len(base)):
                if base.par[i] in hit_dirs:
                    name = base.name(i)
                    full = os.path.join(base.dirs[base.par[i]], name)
                    if (removed or added or rpfx) and gone(full.lower()):
                        continue
                    total += 1
                    if len(out) < limit:
                        out.append((full, name, bool(base.isdir[i]), base.size[i], base.mtime[i]))
        for key, (name, dd, size, mt, full, _t) in added.items():
            if q.match(name, full):
                total += 1
                if len(out) < limit:
                    out.append((full, name, dd, size, mt))
        ms = (time.perf_counter() - t0) * 1000
        log.info("검색 '%s' → %s개 (표시 %d) %.0fms", text, f"{total:,}", len(out), ms)
        return out, total, ms


def folder_search(root, text, cancel, batch_cb, limit=5000):
    """색인 없이 root 아래를 바로 훑으며 찾기. batch_cb(목록) 로 0.5초마다 넘김. 반환 (전체 일치 수, 훑은 개수)"""
    q = Query(text)
    if q.empty():
        return 0, 0
    stack = [root]
    total = scanned = 0
    buf, t_last = [], time.time()
    while stack:
        if cancel():
            break
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    scanned += 1
                    try:
                        st = e.stat(follow_symlinks=False)
                        dd = e.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    if dd and not (st.st_file_attributes & REPARSE) and e.name.lower() not in SKIP_DIRS:
                        stack.append(e.path)
                    if q.match(e.name, e.path):
                        total += 1
                        if total <= limit:
                            buf.append((e.path, e.name, dd, -1 if dd else st.st_size, int(st.st_mtime)))
        except OSError:
            pass
        if buf and time.time() - t_last > 0.5:
            batch_cb(buf)
            buf, t_last = [], time.time()
    if buf:
        batch_cb(buf)
    return total, scanned


# ================================================================ 색인 작업 프로세스 (4Dir 본체가 띄움)
def _worker_main(argv):
    """python search_index.py --build <저장경로> <4Dir pid> <범위...>
    다 만들면 저장하고 'OK' 출력 후 종료. 4Dir 이 꺼지면(pid 사라짐) 스스로 중단 — 잔류 프로세스 없음."""
    import sys
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    out, ppid, roots = argv[0], int(argv[1]), argv[2:]
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = ctypes.c_void_p
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass(ctypes.c_void_p(k.GetCurrentProcess()), 0x00100000)   # 프로세스 백그라운드 모드(CPU·디스크·메모리 우선순위 낮춤)
    hp = k.OpenProcess(0x00100000, False, ppid)   # SYNCHRONIZE: 4Dir 살아 있는지만 확인
    last = [0.0, False]

    def cancel():
        now = time.time()
        if now - last[0] > 1.0:
            last[0] = now
            last[1] = not hp or k.WaitForSingleObject(ctypes.c_void_p(hp), 0) == 0
        return last[1]

    def progress(n, root):
        print(f"P {n} {root}", flush=True)

    snap = build_snapshot(roots, cancel, progress)
    if snap is None:
        print("4Dir 종료됨 → 중단", flush=True)
        return 2
    t0 = time.time()
    snap.save(out)
    print(f"저장 {os.path.getsize(out) / 1048576:.1f}MB {time.time() - t0:.1f}초", flush=True)
    print("OK", flush=True)
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--build":
        sys.exit(_worker_main(sys.argv[2:]))
