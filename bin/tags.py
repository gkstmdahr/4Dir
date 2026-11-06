# -*- coding: utf-8 -*-
"""태그 · 가상 그룹 (TAGS_VER 1.0.0, 0.9.109 빌드 3 — 사용자 11/6 '추가 기능 전부', 경쟁 앱 조사 '태그'·'가상 그룹 폴더')

태그: 파일·폴더에 글자 꼬리표를 여러 개 붙임(예: '검수', '최종', '참고'). 색 라벨(한 개, 색만)과 따로.
  - 목록의 '태그' 열(머리글 우클릭, 처음 태그를 붙이면 저절로 켜짐) · 우클릭 '태그 ▸' · 도구 '태그로 보기 ▸'(그 태그가 붙은 것 모아 보기)
묶음: 여러 폴더에 흩어진 파일·폴더를 한 이름 아래 모아 둔 '가상 폴더'. 진짜 파일은 그 자리에 그대로(옮기거나 복사하지 않음)
  - 우클릭 '묶음에 넣기 ▸' · 도구 '묶음 ▸' 열기·새로 만들기·지우기 · 묶음 보기에서 우클릭 '묶음에서 빼기'
저장: 4Dir 안에만 (bin\\4Dir_tags.json) — 파일 자체는 건드리지 않음. 경로 기준이라 4Dir 밖에서 이름을 바꾸거나 옮기면 떨어짐
  (4Dir 안에서 이름 바꾸기는 따라감: rename())
보기 경로: 검색 결과와 같은 길 — 검색어 '🏷:태그' · '📚:묶음' (main.ScanJob 이 여기 목록을 받음)
로그: bin\\log\\4Dir.log [QE.tags]
"""
import os
import json
import time
import logging

from i18n import T

TAGS_VER = "1.0.0"
log = logging.getLogger("QE.tags")
TAG_Q = "🏷:"
SET_Q = "📚:"
PALETTE = ["#0090ff", "#e5484d", "#30a46c", "#f76b15", "#8e4ec6", "#e2b203", "#e93d82", "#12a594", "#8b8d98", "#a07553"]


class Store:
    def __init__(self, path):
        self.path = path
        self.tags = {}    # 이름 → 색
        self.files = {}   # 경로(소문자) → [태그…]
        self.real = {}    # 경로(소문자) → 실제 경로 (대소문자 그대로)
        self.sets = {}    # 묶음 이름 → [경로…]
        self.load()

    # ------------------------------------------------------------ 저장
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self.tags = dict(d.get("tags", {}))
            self.real = dict(d.get("real", {}))
            self.files = {k: list(v) for k, v in d.get("files", {}).items() if v}
            self.sets = {k: list(v) for k, v in d.get("sets", {}).items()}
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("태그 파일 읽기 실패 %s", self.path)

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ver": TAGS_VER, "tags": self.tags, "files": self.files, "real": self.real, "sets": self.sets},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    @staticmethod
    def key(p):
        return os.path.normcase(os.path.normpath(p))

    # ------------------------------------------------------------ 태그
    def all_tags(self):
        return sorted(self.tags, key=str.lower)

    def color(self, tag):
        return self.tags.get(tag, "#8b8d98")

    def tags_of(self, p):
        if not self.files:
            return []
        return self.files.get(self.key(p), [])

    def new_tag(self, name, color=None):
        name = name.strip()
        if not name:
            return None
        if name not in self.tags:
            self.tags[name] = color or PALETTE[len(self.tags) % len(PALETTE)]
            self.save()
            log.info("새 태그 %s %s", name, self.tags[name])
        return name

    def set_color(self, tag, color):
        if tag in self.tags:
            self.tags[tag] = color
            self.save()

    def toggle(self, paths, tag, on):
        """paths 에 tag 붙이기(on)·떼기"""
        if on:
            self.new_tag(tag)
        n = 0
        for p in paths:
            k = self.key(p)
            cur = self.files.get(k, [])
            if on and tag not in cur:
                self.files[k] = cur + [tag]
                self.real[k] = os.path.normpath(p)
                n += 1
            elif not on and tag in cur:
                cur = [t for t in cur if t != tag]
                if cur:
                    self.files[k] = cur
                else:
                    self.files.pop(k, None)
                    self.real.pop(k, None)
                n += 1
        self.save()
        log.info("태그 %s %s %d개", tag, "붙임" if on else "뗌", n)
        return n

    def clear(self, paths):
        for p in paths:
            k = self.key(p)
            self.files.pop(k, None)
            self.real.pop(k, None)
        self.save()

    def delete_tag(self, tag):
        self.tags.pop(tag, None)
        for k in list(self.files):
            v = [t for t in self.files[k] if t != tag]
            if v:
                self.files[k] = v
            else:
                self.files.pop(k)
                self.real.pop(k, None)
        self.save()
        log.info("태그 지움 %s", tag)

    def rename_tag(self, old, new):
        new = new.strip()
        if not new or old not in self.tags or new == old:
            return False
        self.tags[new] = self.tags.pop(old)
        for k, v in self.files.items():
            self.files[k] = [new if t == old else t for t in v]
        self.save()
        return True

    def files_with(self, tag):
        return [self.real.get(k, k) for k, v in self.files.items() if tag in v]

    def count(self, tag):
        return sum(1 for v in self.files.values() if tag in v)

    # ------------------------------------------------------------ 묶음
    def all_sets(self):
        return sorted(self.sets, key=str.lower)

    def new_set(self, name):
        name = name.strip()
        if name and name not in self.sets:
            self.sets[name] = []
            self.save()
            log.info("새 묶음 %s", name)
        return name or None

    def add_to_set(self, name, paths):
        self.new_set(name)
        have = {self.key(p) for p in self.sets[name]}
        add = [os.path.normpath(p) for p in paths if self.key(p) not in have]
        self.sets[name] += add
        self.save()
        log.info("묶음 %s 에 %d개 넣음 (전체 %d)", name, len(add), len(self.sets[name]))
        return len(add)

    def remove_from_set(self, name, paths):
        drop = {self.key(p) for p in paths}
        before = len(self.sets.get(name, []))
        self.sets[name] = [p for p in self.sets.get(name, []) if self.key(p) not in drop]
        self.save()
        return before - len(self.sets[name])

    def delete_set(self, name):
        self.sets.pop(name, None)
        self.save()
        log.info("묶음 지움 %s", name)

    def rename_set(self, old, new):
        new = new.strip()
        if not new or old not in self.sets or new in self.sets:
            return False
        self.sets[new] = self.sets.pop(old)
        self.save()
        return True

    # ------------------------------------------------------------ 공통
    def rename(self, old, new):
        """4Dir 안에서 이름 바꿈·옮김 → 태그·묶음도 따라감 (폴더면 그 아래도)"""
        ko, kn = self.key(old), self.key(new)
        changed = False
        for k in list(self.files):
            if k == ko or k.startswith(ko + os.sep):
                nk = kn + k[len(ko):]
                self.files[nk] = self.files.pop(k)
                r = self.real.pop(k, k)
                self.real[nk] = os.path.normpath(new) + r[len(os.path.normpath(old)):]
                changed = True
        for name, lst in self.sets.items():
            for i, p in enumerate(lst):
                k = self.key(p)
                if k == ko or k.startswith(ko + os.sep):
                    lst[i] = os.path.normpath(new) + p[len(os.path.normpath(old)):]
                    changed = True
        if changed:
            self.save()
            log.info("태그·묶음 경로 따라감 %s → %s", old, new)

    def rows(self, q):
        """보기 목록 (TAG_Q·SET_Q 검색어) → [(경로, 이름, 폴더?, 크기, 날짜)] — 없어진 것은 '(없음)' 으로 남김"""
        t0 = time.time()
        if q.startswith(TAG_Q):
            ps = self.files_with(q[len(TAG_Q):])
        elif q.startswith(SET_Q):
            ps = list(self.sets.get(q[len(SET_Q):], []))
        else:
            return []
        out = []
        for p in ps:
            try:
                st = os.stat(p)
                isd = os.path.isdir(p)
                out.append((p, os.path.basename(p.rstrip("\\/")) or p, isd, -1 if isd else st.st_size, st.st_mtime))
            except OSError:
                out.append((p, os.path.basename(p) + T("  (없음)"), False, -1, 0))
        log.info("%s 보기 %d개 %.0fms", q, len(out), (time.time() - t0) * 1000)
        return out


def is_view(q):
    return q.startswith(TAG_Q) or q.startswith(SET_Q)
