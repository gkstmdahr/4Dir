# -*- coding: utf-8 -*-
"""즐겨찾기 목록 (즐겨찾기 바·사이드바·우클릭 메뉴가 같은 목록 하나를 공유)

파일: bin\\4Dir_favorites.json  [{"name":..., "path":..., "group": 묶음 이름(없으면 맨 위)}, ...]
묶음(group): 같은 묶음 항목은 목록에서 항상 붙어 있음(normalize). 바·메뉴에서는 묶음 하나 = 버튼/하위메뉴 하나.
즐겨찾기는 사용자가 직접 등록한 것만 (윈도우 탐색기 즐겨찾기와 별개). 처음엔 비어 있음.
윈도우 탐색기 '즐겨찾기(고정 항목)'은 메뉴에서 원할 때만 가져온다(읽기만).
"""
import os
import json
import time
import logging

log = logging.getLogger("QE.fav")
BIN_DIR = os.path.dirname(os.path.abspath(__file__))
FAV_FILE = os.path.join(BIN_DIR, "4Dir_favorites.json")
QUICK_ACCESS = "shell:::{3936E9E4-D92C-4EEE-A85A-BC16D5EA0819}"   # 즐겨찾기(고정+자주 쓰는 폴더)


class Favorites:
    def __init__(self, path=FAV_FILE):
        self.path = path
        self.items = []
        self.listeners = []

    # ---------------------------------------------------------- 읽기/쓰기
    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.items = [d for d in json.load(f) if d.get("path")]
                log.info("즐겨찾기 %d개 불러옴", len(self.items))
                return
            except Exception:
                log.exception("즐겨찾기 파일 깨짐 → 빈 목록")
        self.items = []
        self.save()

    def normalize(self):
        """같은 묶음 항목을 그 묶음 첫 항목 자리에 모음 (순서는 유지)"""
        out, seen = [], set()
        for d in self.items:
            g = d.get("group") or ""
            if not g:
                d.pop("group", None)
                out.append(d)
            elif g not in seen:
                seen.add(g)
                out += [x for x in self.items if (x.get("group") or "") == g]
        self.items = out

    def entries(self):
        """바·메뉴용: [(start, end, 묶음 이름 or None)] — 낱개는 end = start + 1"""
        out, i = [], 0
        while i < len(self.items):
            g = self.items[i].get("group") or ""
            j = i + 1
            if g:
                while j < len(self.items) and (self.items[j].get("group") or "") == g:
                    j += 1
            out.append((i, j, g or None))
            i = j
        return out

    def groups(self):
        return [g for _, _, g in self.entries() if g]

    def save(self):
        self.normalize()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
        for fn in self.listeners:
            try:
                fn()
            except Exception:
                log.exception("즐겨찾기 갱신 알림 실패")

    # ---------------------------------------------------------- 편집
    def add(self, path, name=None, pos=None, group=None):
        path = os.path.normpath(path)
        if any(os.path.normcase(d["path"]) == os.path.normcase(path) for d in self.items):
            log.info("즐겨찾기 이미 있음 %s", path)
            return False
        d = {"name": name or (os.path.basename(path.rstrip("\\")) or path), "path": path}
        if group:   # 묶음 안으로 → 그 묶음 맨 끝
            d["group"] = group
            last = max((k for k, x in enumerate(self.items) if x.get("group") == group), default=None)
            if last is not None:
                pos = last + 1
        if pos is None:
            self.items.append(d)
        else:
            self.items.insert(pos, d)
        log.info("즐겨찾기 추가 %s", path)
        self.save()
        return True

    def remove(self, i):
        d = self.items.pop(i)
        log.info("즐겨찾기 삭제 %s", d["path"])
        self.save()

    def rename(self, i, name):
        self.items[i]["name"] = name
        self.save()

    def move(self, i, j):
        d = self.items.pop(i)
        self.items.insert(j, d)
        self.save()

    def move_block(self, start, end, pos):
        """items[start:end] (낱개 또는 묶음 하나)를 pos(옮기기 전 기준 자리) 앞으로. 제자리면 False"""
        if start <= pos <= end:
            return False
        blk = self.items[start:end]
        rest = self.items[:start] + self.items[end:]
        k = pos if pos < start else pos - (end - start)
        self.items = rest[:k] + blk + rest[k:]
        log.info("즐겨찾기 순서 [%d:%d] -> %d", start, end, k)
        self.save()
        return True

    def replace_all(self, items):
        """정리 창에서 확인 → 목록 통째로 바꿈"""
        self.items = [dict(d) for d in items if d.get("path")]
        log.info("즐겨찾기 정리 적용: %d개, 묶음 %s", len(self.items),
                 sorted({d["group"] for d in self.items if d.get("group")}))
        self.save()

    def reimport(self):
        added = 0
        for d in import_windows_pinned():
            if self.add(d["path"], d["name"]):
                added += 1
        return added


def windows_pinned(timeout=2.0):
    """왼쪽 탐색 창용: 윈도우 탐색기에 고정한 폴더 목록 (읽기만).
    끊긴 네트워크 폴더가 고정돼 있으면 셸이 멈출 수 있어 따로 돌리고 timeout 초 안에 답이 없으면 None"""
    import threading
    box = {}
    th = threading.Thread(target=lambda: box.setdefault("r", import_windows_pinned()), daemon=True, name="win-pinned")
    t0 = time.time()
    th.start()
    th.join(timeout)
    if "r" not in box:
        log.warning("윈도우 고정 폴더 읽기 %.1f초 안에 응답 없음 → 건너뜀", timeout)
        return None
    log.info("윈도우 고정 폴더 %d개 (%.0fms)", len(box["r"]), (time.time() - t0) * 1000)
    return box["r"]


def import_windows_pinned():
    """윈도우 탐색기 즐겨찾기 중 '고정된' 폴더만 (System.Home.IsPinned=True)"""
    out = []
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        sh = win32com.client.Dispatch("Shell.Application")
        ns = sh.NameSpace(QUICK_ACCESS)
        for it in (ns.Items() if ns else []):
            try:
                pinned = it.ExtendedProperty("System.Home.IsPinned")
            except Exception:
                pinned = None
            if it.IsFolder and pinned and it.Path and not it.Path.startswith("::"):
                out.append({"name": it.Name, "path": it.Path})
        del ns, sh
    except Exception:
        log.exception("윈도우 즐겨찾기 가져오기 실패")
    log.info("윈도우 고정 즐겨찾기 %d개 가져옴", len(out))
    return out
