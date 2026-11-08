# -*- coding: utf-8 -*-
"""자주 간 폴더 (FRECENT_VER 1.0.0, 0.9.116 빌드 3 — 사용자 11/8 #21 '주소줄 몇 글자 → 자주·최근 간 폴더 순 후보', XYplorer·zoxide 방식)

- 4Dir 칸에서 폴더로 들어갈 때마다 기록: {경로: [들어간 횟수, 마지막 시각]} (4Dir_frecent.json, 최대 600개 — 넘으면 점수 낮은 것부터 버림)
- 점수 = 횟수 × 최근 가중치 (1시간 안 ×4, 하루 안 ×2, 일주일 안 ×1, 그보다 오래 ×0.5, 한 달 넘음 ×0.25)
- 찾기 match(글자): 띄어 쓴 낱말이 모두 경로에 들어간 것 (대소문자 무시). 마지막 폴더 이름에 들어가면 앞으로, 이름이 그 글자로 시작하면 더 앞으로.
  지금 없는 폴더는 후보에서 빼고 기록에서도 지움 (네트워크 경로는 확인 안 함 — 느릴 수 있음)
- 저장: 바뀐 뒤 처음 save_soon() 부를 때 3초 뒤 한 번 (타이머는 바뀌었을 때만, 쉬는 동안 없음) + 끝날 때 flush()
- 기록 안 남기기(private) 켜져 있으면 기록하지 않음 (PRIVATE 훅)
로그: QE.frecent
"""
import os
import json
import time
import logging

FRECENT_VER = "1.0.0"
log = logging.getLogger("QE.frecent")
MAX_ITEMS = 600
PRIVATE = lambda: False   # main 이 바꿈


def _weight(age):
    if age < 3600:
        return 4.0
    if age < 86400:
        return 2.0
    if age < 7 * 86400:
        return 1.0
    if age < 30 * 86400:
        return 0.5
    return 0.25


class Store:
    def __init__(self, path):
        self.path = path
        self.data = {}
        self.dirty = False
        self._timer = None
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                self.data = {k: [int(v[0]), float(v[1])] for k, v in d.items() if isinstance(v, list) and len(v) == 2}
        except Exception:
            log.exception("자주 간 폴더 파일 깨짐 → 빈 것으로 %s", path)

    def visit(self, path, now=None):
        if PRIVATE() or not path:
            return
        now = now or time.time()
        k = os.path.normpath(path)
        c = self.data.get(k, [0, 0])
        self.data[k] = [c[0] + 1, now]
        if len(self.data) > MAX_ITEMS:
            drop = sorted(self.data, key=lambda p: self.score(p, now))[: len(self.data) - MAX_ITEMS]
            for p in drop:
                self.data.pop(p, None)
            log.info("자주 간 폴더 %d개 넘음 → 점수 낮은 %d개 버림", MAX_ITEMS, len(drop))
        self.dirty = True
        self.save_soon()

    def score(self, p, now=None):
        c, t = self.data.get(p, (0, 0))
        return c * _weight((now or time.time()) - t)

    def match(self, text, limit=12, exists=os.path.isdir):
        words = [w for w in text.lower().replace("/", "\\").split() if w]
        if not words:
            return []
        now = time.time()
        out, gone = [], []
        for p in self.data:
            lp = p.lower()
            if not all(w in lp for w in words):
                continue
            name = os.path.basename(lp.rstrip("\\")) or lp
            rank = 2 if name.startswith(words[-1]) else (1 if words[-1] in name else 0)
            out.append((rank, self.score(p, now), p))
        out.sort(key=lambda x: (-x[0], -x[1], x[2].lower()))
        res = []
        for _r, _s, p in out:
            if not p.startswith("\\\\") and not exists(p):
                gone.append(p)
                continue
            res.append(p)
            if len(res) >= limit:
                break
        if gone:
            for p in gone:
                self.data.pop(p, None)
            self.dirty = True
            self.save_soon()
            log.info("없어진 폴더 %d개 기록에서 지움: %s", len(gone), gone[:3])
        return res

    def top(self, limit=15):
        now = time.time()
        return sorted(self.data, key=lambda p: -self.score(p, now))[:limit]

    def clear(self):
        self.data = {}
        self.dirty = True
        self.flush()

    def save_soon(self):
        try:
            from PySide6 import QtCore
            if QtCore.QCoreApplication.instance() is None:
                return self.flush()
            if self._timer is None:
                self._timer = QtCore.QTimer()
                self._timer.setSingleShot(True)
                self._timer.setInterval(3000)
                self._timer.timeout.connect(self.flush)
            if not self._timer.isActive():
                self._timer.start()
        except Exception:
            log.exception("저장 예약 실패")
            self.flush()

    def flush(self):
        if not self.dirty:
            return
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError:
            log.exception("자주 간 폴더 저장 실패 %s", self.path)


class ViewMem:
    """폴더마다 보기 기억 (0.9.116 빌드 3, 사용자 11/8 #22 — Directory Opus '폴더 형식'·윈도우 탐색기처럼).
    사용자가 그 폴더에서 보기 방식(자세히·큰 아이콘…)이나 정렬을 바꾸면 기억 → 다음에 들어가면 그대로.
    기억 없는 폴더는 칸의 기본 보기. 4Dir_viewmem.json {경로(소문자): {"mode": .., "sort": [열, 순서]}} 최대 3000개(오래된 것부터 버림)"""
    MAX = 3000

    def __init__(self, path):
        self.path = path
        self.data = {}
        self.dirty = False
        self._timer = None
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    self.data = {k: v for k, v in json.load(f).items() if isinstance(v, dict)}
        except Exception:
            log.exception("폴더 보기 기억 파일 깨짐 → 빈 것으로 %s", path)

    def get(self, folder):
        return self.data.get(os.path.normcase(os.path.normpath(folder))) if self.data and folder else None

    def remember(self, folder, mode=None, sort=None):
        if PRIVATE() or not folder:
            return
        k = os.path.normcase(os.path.normpath(folder))
        d = dict(self.data.pop(k, {}))   # 다시 넣어 '최근' 순서 맨 뒤로
        if mode:
            d["mode"] = mode
        if sort is not None:
            d["sort"] = [int(sort[0]), int(sort[1])]
        self.data[k] = d
        while len(self.data) > self.MAX:
            self.data.pop(next(iter(self.data)))
        self.dirty = True
        log.info("폴더 보기 기억 %s → %s", folder, d)
        Store.save_soon(self)

    def forget(self, folder):
        if self.data.pop(os.path.normcase(os.path.normpath(folder)), None) is not None:
            self.dirty = True
            Store.save_soon(self)
            log.info("폴더 보기 기억 지움 %s", folder)

    def clear(self):
        self.data = {}
        self.dirty = True
        self.flush()

    flush = Store.flush
