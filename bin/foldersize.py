# -*- coding: utf-8 -*-
"""폴더 크기 (v0.9.89 사용자 11/4: 크기 칸에 폴더 크기도 — 큰 순서로 정렬).
목록을 다 보여준 뒤 뒤 스레드에서 폴더마다 안쪽 전체 크기를 더해 하나씩 알림. 다른 폴더로 가면 취소.
- 네트워크 드라이브·UNC 는 계산 안 함 (느리고 서버에 부담) → 빈칸
- 바로가기 폴더(정션·심볼릭 링크)는 따라가지 않음 (같은 것을 두 번 세거나 끝없이 도는 것 방지)
- 한 번 잰 값은 5분 동안 기억 (파일이 바뀔 때마다 다시 읽어도 처음부터 안 잼)
"""
import os
import time
import ctypes
import logging
import threading

log = logging.getLogger("QE.fsize")
CACHE_SEC = 300
_cache = {}            # normcase(폴더) → (크기, 잰 시각)
_lock = threading.Lock()


def is_remote(path):
    """네트워크 경로인가 (UNC 또는 네트워크 드라이브 문자)"""
    if path.startswith("\\\\"):
        return True
    root = os.path.splitdrive(path)[0] + "\\"
    try:
        return ctypes.windll.kernel32.GetDriveTypeW(root) == 4   # DRIVE_REMOTE
    except Exception:
        return False


def cached(path):
    with _lock:
        v = _cache.get(os.path.normcase(path))
    if v and time.time() - v[1] < CACHE_SEC:
        return v[0]
    return None


def forget(path):
    """그 폴더와 위쪽 폴더들 기억 지움 (안에서 파일이 바뀜)"""
    p = os.path.normcase(path)
    with _lock:
        for k in [k for k in _cache if p == k or p.startswith(k.rstrip("\\") + "\\")]:
            _cache.pop(k, None)


def measure(path, cancel):
    """폴더 안 전체 파일 크기 합. cancel() 이 참이면 None"""
    total, stack = 0, [path]
    while stack:
        if cancel():
            return None
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for de in it:
                    try:
                        if de.is_dir(follow_symlinks=False):
                            if not de.is_symlink() and not (de.stat(follow_symlinks=False).st_file_attributes & 0x400):   # 0x400 = 정션 등 재분석 지점
                                stack.append(de.path)
                        else:
                            total += de.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    with _lock:
        _cache[os.path.normcase(path)] = (total, time.time())
    return total


class Job(threading.Thread):
    """folder 안 하위 폴더들(names) 크기를 차례로 재서 found(name, size) · 다 끝나면 done()"""

    def __init__(self, folder, names, found, done):
        super().__init__(daemon=True, name=f"fsize {folder}")
        self.folder, self.names, self.found, self.done = folder, names, found, done
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        t0, n = time.time(), 0
        for name in self.names:
            if self.cancelled:
                break
            p = os.path.join(self.folder, name)
            s = cached(p)
            if s is None:
                s = measure(p, lambda: self.cancelled)
                n += 1
            if s is None or self.cancelled:
                break
            try:
                self.found(name, s)
            except RuntimeError:   # 탭이 닫힘
                return
        log.info("폴더 크기 %s: 폴더 %d개 (새로 잰 것 %d) %.1f초%s", self.folder, len(self.names), n, time.time() - t0,
                 " — 취소" if self.cancelled else "")
        if not self.cancelled:
            try:
                self.done()
            except RuntimeError:
                pass
