# -*- coding: utf-8 -*-
"""새 버전 폴더에서 처음 실행할 때 이전 버전 폴더의 설정 가져오기 (CARRYOVER_VER 1.0.1)

배경: 배포판 zip 은 버전마다 폴더 이름이 달라서(4Dir_v0.9.86, 4Dir_v0.9.87 ...) 설정이 bin 안에 있으면
새 버전은 빈 설정으로 시작함. winget 업데이트도 같은 부모 폴더에 새 버전 폴더를 만듦.
- 언제: 내 bin 에 설정·상태·즐겨찾기 파일이 하나도 없을 때만 (이미 쓰던 폴더는 손대지 않음)
- 어디서: 내 4Dir 폴더와 같은 부모 아래 다른 '4Dir*' 폴더의 bin 중 설정 파일이 가장 최근에 바뀐 곳
- 무엇을: 4Dir_settings.json / 4Dir_state.json / 4Dir_favorites.json / workspaces 폴더 (복사만 — 원본은 그대로)
  sessions(시각별 보관)·index(검색 색인, 다시 만들어짐)·log·4Dir.running 은 안 가져옴
로그: bin\\log\\4Dir.log  [QE.carryover]
"""
import os
import glob
import shutil
import logging

CARRYOVER_VER = "1.0.1"   # 1.0.1: 로그에 경로를 원래 대소문자로
FILES = ("4Dir_settings.json", "4Dir_state.json", "4Dir_favorites.json")
DIRS = ("workspaces",)
log = logging.getLogger("QE.carryover")


def _newest(bin_dir):
    t = [os.path.getmtime(os.path.join(bin_dir, f)) for f in FILES if os.path.isfile(os.path.join(bin_dir, f))]
    return max(t) if t else 0


def run(bin_dir):
    """가져왔으면 가져온 bin 경로, 아니면 '' """
    try:
        have = [f for f in FILES if os.path.exists(os.path.join(bin_dir, f))]
        if have:
            return ""
        me = os.path.abspath(os.path.dirname(bin_dir))
        parent = os.path.dirname(me)
        cands = []
        for d in glob.glob(os.path.join(parent, "4Dir*")):
            b = os.path.join(d, "bin")
            if os.path.normcase(os.path.abspath(d)) == os.path.normcase(me) or not os.path.isdir(b):
                continue
            t = _newest(b)
            if t:
                cands.append((t, b))
        log.info("carryover %s: 내 설정 없음, 부모 %s 에서 후보 %d개 %s", CARRYOVER_VER, parent, len(cands),
                 [os.path.basename(os.path.dirname(b)) for t, b in sorted(cands, reverse=True)])
        if not cands:
            return ""
        src = max(cands)[1]
        done = []
        for f in FILES:
            s = os.path.join(src, f)
            if os.path.isfile(s):
                try:
                    shutil.copy2(s, os.path.join(bin_dir, f))
                    done.append(f)
                except OSError as e:
                    log.warning("carryover 복사 실패 %s: %s", f, e)
        for d in DIRS:
            s = os.path.join(src, d)
            if os.path.isdir(s) and not os.path.exists(os.path.join(bin_dir, d)):
                try:
                    shutil.copytree(s, os.path.join(bin_dir, d))
                    done.append(d + "\\")
                except OSError as e:
                    log.warning("carryover 폴더 복사 실패 %s: %s", d, e)
        log.info("carryover: %s 에서 가져옴 %s", src, done)
        return src if done else ""
    except Exception:
        log.exception("carryover 오류 (설정 없이 계속)")
        return ""
