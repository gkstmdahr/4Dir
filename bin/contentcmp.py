# -*- coding: utf-8 -*-
"""두 칸 비교 — 내용까지 비교 (CONTENTCMP_VER 1.0.0, v0.9.107 사용자 11/5 '같은 파일인데 내용 다른 것도 잡나?')

- 이름·크기가 같은 파일 짝만 실제로 읽어 맞춰 봄 (크기가 다르면 내용은 당연히 다름 → 안 읽음).
- 두 파일을 같이 조금씩 읽다가 첫 다른 곳에서 멈춤 (해시보다 빠름, 끝까지 같을 때만 끝까지 읽음).
- 뒤 스레드에서 돌고 진행(짝 수·바이트)을 알림. cancel() 하면 다음 덩어리에서 멈춤.
결과: {이름: "same" | "content" | "error"}
로그: bin\\log\\4Dir.log  [QE.cmp]
"""
import os
import time
import logging
import threading

from PySide6 import QtCore

CONTENTCMP_VER = "1.0.0"
CHUNK = 1 << 20
log = logging.getLogger("QE.cmp")


def same_content(p1, p2, cancel=lambda: False, on_bytes=None, chunk=CHUNK):
    """같으면 True, 다르면 False, 멈추면 None (읽기 오류는 예외)"""
    with open(p1, "rb") as f1, open(p2, "rb") as f2:
        while True:
            if cancel():
                return None
            a = f1.read(chunk)
            b = f2.read(chunk)
            if on_bytes:
                on_bytes(len(a))
            if a != b:
                return False
            if not a:
                return True


class ContentCompare(QtCore.QObject):
    progress = QtCore.Signal(int, int, object, object)   # 끝난 짝, 전체 짝, 읽은 바이트, 전체 바이트
    finished = QtCore.Signal(dict, bool)                # 결과, 멈췄는지

    def __init__(self, pairs, parent=None):
        """pairs = [(이름, 이쪽 경로, 반대쪽 경로, 크기)]"""
        super().__init__(parent)
        self.pairs = list(pairs)
        self._stop = False
        self.total = sum(p[3] for p in self.pairs)
        self.th = None

    def cancel(self):
        self._stop = True

    def start(self):
        self.th = threading.Thread(target=self._run, daemon=True, name="content-cmp")
        self.th.start()

    def _run(self):
        res, done_bytes, last = {}, [0], [0.0]
        t0 = time.time()

        def on_bytes(n):
            done_bytes[0] += n
            now = time.time()
            if now - last[0] > 0.2:
                last[0] = now
                self.progress.emit(len(res), len(self.pairs), done_bytes[0], self.total)
        for name, p1, p2, _size in self.pairs:
            if self._stop:
                break
            try:
                r = same_content(p1, p2, lambda: self._stop, on_bytes)
            except OSError as ex:
                log.warning("내용 비교 못 읽음 %s : %s", name, ex)
                res[name] = "error"
                continue
            if r is None:
                break
            res[name] = "same" if r else "content"
        self.progress.emit(len(res), len(self.pairs), done_bytes[0], self.total)
        log.info("내용 비교 %d/%d짝 %.1fMB %.1f초 (멈춤 %s) 다름 %d",
                 len(res), len(self.pairs), done_bytes[0] / 1048576, time.time() - t0, self._stop,
                 sum(1 for v in res.values() if v == "content"))
        self.finished.emit(res, self._stop)
