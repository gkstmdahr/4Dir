# -*- coding: utf-8 -*-
"""설정 전체 내보내기·가져오기 (BACKUP_VER 1.0.0, v0.9.94 사용자 11/4: '포맷하고 원래대로 셋팅 돌려서 쓰기 위해')

- 내보내기: 설정(보기·단축키·마우스·검색 범위·언어 등) 4Dir_settings.json, 창·칸·탭 상태(탭 색·정렬·열 너비 포함) 4Dir_state.json,
  즐겨찾기 4Dir_favorites.json, 색 라벨 4Dir_labels.json, 저장한 창 구성 workspaces\\, 자동 기록 sessions\\ → zip 하나
  (+ 4Dir_backup.json = 어느 버전에서 언제 만든 백업인지). 검색 색인(index)·로그는 안 넣음(다시 만들어짐·개인 기록).
- 가져오기: zip 을 bin\\_restore_pending\\ 에 풀어 둠 → 4Dir 다시 시작 → 시작하자마자(설정 읽기 전) apply_pending 이
  지금 설정을 bin\\restore_backup\\설정백업_<시각>.zip 으로 보관한 뒤 바꿔 넣음. (켜져 있는 동안 바꾸면 닫을 때 저장이 덮어써서)
- 안전: zip 안 이름은 정해진 파일·폴더만 받음(..\\ 경로 등 무시).
로그: bin\\log\\4Dir.log  [QE.backup]
"""
import os
import json
import time
import shutil
import zipfile
import logging

BACKUP_VER = "1.0.0"
FILES = ("4Dir_settings.json", "4Dir_state.json", "4Dir_favorites.json", "4Dir_labels.json")
DIRS = ("workspaces", "sessions")
MANIFEST = "4Dir_backup.json"
PENDING = "_restore_pending"
KEEP_DIR = "restore_backup"
log = logging.getLogger("QE.backup")


def _items(bin_dir):
    """(zip 안 이름, 실제 경로) 목록"""
    out = [(f, os.path.join(bin_dir, f)) for f in FILES if os.path.isfile(os.path.join(bin_dir, f))]
    for d in DIRS:
        base = os.path.join(bin_dir, d)
        for root, _ds, fs in os.walk(base):
            for f in fs:
                full = os.path.join(root, f)
                out.append((os.path.relpath(full, bin_dir).replace("\\", "/"), full))
    return out


def export_zip(bin_dir, dest, version=""):
    """설정 전체를 zip 으로 → 넣은 항목 수"""
    items = _items(bin_dir)
    tmp = dest + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, full in items:
            z.write(full, arc)
        z.writestr(MANIFEST, json.dumps({"app": "4Dir", "version": version, "backup_ver": BACKUP_VER,
                                         "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
                                         "items": [a for a, _f in items]}, ensure_ascii=False, indent=1))
    os.replace(tmp, dest)
    log.info("설정 내보내기 %s → %s (%d개)", bin_dir, dest, len(items))
    return len(items)


def _allowed(name):
    n = name.replace("\\", "/")
    if n.startswith("/") or ".." in n.split("/") or ":" in n:
        return False
    return n in FILES or any(n.startswith(d + "/") and len(n) > len(d) + 1 for d in DIRS)


def read_manifest(src):
    """백업 zip 정보 (아니면 None)"""
    try:
        with zipfile.ZipFile(src) as z:
            info = json.loads(z.read(MANIFEST).decode("utf-8"))
        return info if info.get("app") == "4Dir" else None
    except Exception as ex:
        log.warning("백업 파일 아님 %s : %s", src, ex)
        return None


def stage_restore(bin_dir, src):
    """가져올 백업을 _restore_pending 에 풀어 둠 → 받은 항목 수 (다음 시작 때 적용)"""
    pend = os.path.join(bin_dir, PENDING)
    shutil.rmtree(pend, ignore_errors=True)
    os.makedirs(pend)
    n = 0
    with zipfile.ZipFile(src) as z:
        for name in z.namelist():
            if name.endswith("/") or not _allowed(name):
                continue
            out = os.path.join(pend, *name.replace("\\", "/").split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(name) as r, open(out, "wb") as w:
                shutil.copyfileobj(r, w)
            n += 1
    log.info("설정 가져오기 준비 %s → %s (%d개, 다음 시작 때 적용)", src, pend, n)
    return n


def apply_pending(bin_dir):
    """시작할 때(설정 읽기 전): 준비된 백업이 있으면 지금 설정을 보관하고 바꿔 넣음 → 적용했으면 True"""
    pend = os.path.join(bin_dir, PENDING)
    if not os.path.isdir(pend):
        return False
    try:
        keep = os.path.join(bin_dir, KEEP_DIR)
        os.makedirs(keep, exist_ok=True)
        old = os.path.join(keep, time.strftime("설정백업_%Y%m%d_%H%M%S.zip"))
        export_zip(bin_dir, old, "before-restore")
        have = [f for f in FILES if os.path.isfile(os.path.join(pend, f))]
        for f in FILES:   # 백업에 없는 파일(예: 색 라벨 없던 버전)은 지움 → 백업 그대로
            dst = os.path.join(bin_dir, f)
            if f in have:
                shutil.copy2(os.path.join(pend, f), dst)
            elif os.path.exists(dst):
                os.remove(dst)
        for d in DIRS:
            dst = os.path.join(bin_dir, d)
            shutil.rmtree(dst, ignore_errors=True)
            if os.path.isdir(os.path.join(pend, d)):
                shutil.copytree(os.path.join(pend, d), dst)
        shutil.rmtree(pend, ignore_errors=True)
        log.info("설정 가져오기 적용: %s (이전 설정 보관 %s)", have, old)
        return True
    except Exception:
        log.exception("설정 가져오기 적용 실패 — 준비 폴더 남겨 둠 %s", pend)
        return False
