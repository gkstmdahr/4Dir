# -*- coding: utf-8 -*-
"""4Dir 사이트용 화면 그림 (MAKE_SHOTS_VER 1.0.2)

python make_shots.py <언어코드...>   → _site\\img\\<언어>_1.png (4칸·밝게), <언어>_2.png (3칸·어둡게)
- make_guide.py 와 같은 방식: 예시 폴더(드라이브 맨 위 4Dir_Demo, 일반 이름)만 쓰고 끝나면 지움.
- 사용자 설정·상태·즐겨찾기·실행 표시 파일은 전부 임시 파일로 돌림(건드리지 않음).
- 창은 화면 밖(-30000) 좌표에 띄우고 위젯 그리기(grab)로 찍음 → 사용자 화면에 안 보이고 포커스도 안 뺏음.
- '종류' 열은 숨김 (윈도우가 OS 언어로 주는 글자라 사이트 언어와 안 맞음).
로그: _build\\make_shots_log.txt
"""
import os
import sys
import time
import shutil
import stat

LANGS = sys.argv[1:] or ["en"]
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
OUT = os.path.join(ROOT, "_site", "img")
sys.path.insert(0, BIN)
os.chdir(BIN)
LOGF = os.path.join(HERE, "make_shots_log.txt")


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    with open(LOGF, "a", encoding="utf-8") as f:
        f.write(line + "\n")


if len(LANGS) > 1:   # 열 제목 등은 import 때 번역이 정해짐 → 언어마다 따로 실행 (1.0.2)
    import subprocess
    bad = [lg for lg in LANGS if subprocess.run([sys.executable, "-u", "-X", "utf8", os.path.abspath(__file__), lg]).returncode]
    log(f"전체 끝 — 실패 언어 {bad}")
    sys.exit(1 if bad else 0)

import i18n  # noqa: E402
i18n.init(LANGS[0])
import main as M  # noqa: E402
import session, ui_parts  # noqa: E402,E401
from PySide6 import QtWidgets, QtCore  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

TMP = os.path.splitdrive(BIN)[0] + os.sep + "4Dir_Demo"
MARK = os.path.join(TMP, ".4dir_guide_demo")
if os.path.exists(TMP) and not os.path.exists(MARK):
    raise SystemExit(f"{TMP} 가 이미 있음 (4Dir 예시 폴더 아님) — 지우지 않고 멈춤")


def rm(p):
    def onerr(f, path, _):
        os.chmod(path, stat.S_IWRITE)
        f(path)
    if os.path.exists(p):
        shutil.rmtree(p, onerror=onerr)


def touch(p, s="x"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


rm(TMP)
os.makedirs(TMP)
touch(MARK, "4Dir make_shots.py 예시 폴더 — 끝나면 지움")
PROJ = os.path.join(TMP, "Project")
for d in ("Characters/Hero", "Characters/Monster", "Environments/Forest", "Environments/Desert", "Effects",
          "Renders/Turntable", "Docs", "Audio"):
    os.makedirs(os.path.join(PROJ, d), exist_ok=True)
FILES = {"": ["hero_idle.max", "hero_run.max", "hero_attack_01.max", "hero_attack_02.max", "hero_skin.max",
              "texture_body.png", "texture_face.png", "notes.txt", "readme.md"],
         "Characters/Hero": ["hero_idle.max", "hero_run.max", "hero_jump.max", "hero_diffuse.png", "hero_normal.png"],
         "Characters/Monster": ["monster_idle.max", "monster_walk.max", "monster_roar.wav"],
         "Environments/Forest": ["tree_01.max", "tree_02.max", "rock_01.max", "grass.png"],
         "Renders": ["shot_010.mp4", "shot_020.mp4", "poster.jpg"],
         "Docs": ["schedule.xlsx", "design.pdf", "todo.txt"]}
for sub, names in FILES.items():
    for i, n in enumerate(names):
        touch(os.path.join(PROJ, sub, n), n * (40 + i * 37))

M.STATE_FILE = os.path.join(TMP, "state.json")
M.FAV.path = os.path.join(TMP, "fav.json")
M.WS_DIR = os.path.join(TMP, "ws")
session.SESS_DIR = os.path.join(TMP, "sessions")
session.RUN_FILE = os.path.join(TMP, "4Dir.running")
M.SETTINGS = ui_parts.Settings(os.path.join(TMP, "settings.json"))
M.SETTINGS.data.update({"search_roots": [{"path": PROJ, "on": True}], "theme_mode": "light", "sysmon": False,
                        "breadcrumb": True, "update_check": False})
M.FAV.items = [{"name": "Project", "path": PROJ}, {"name": "Characters", "path": os.path.join(PROJ, "Characters")},
               {"name": "Renders", "path": os.path.join(PROJ, "Renders")}, {"name": "Docs", "path": os.path.join(PROJ, "Docs")}]
app = QtWidgets.QApplication([])
i18n.apply_font(app)
app.setQuitOnLastWindowClosed(False)


def wait(ms):
    t = time.time()
    while time.time() - t < ms / 1000:
        app.processEvents()
        time.sleep(0.01)


def hide_type_col(w):
    for p in w.panes:
        for v in p.findChildren(QtWidgets.QTreeView):
            h = v.header()
            for c in range(h.count()):
                t = v.model().headerData(c, Qt.Horizontal) if v.model() else ""
                hide = [i18n.T("유형"), i18n.T("종류"), "유형", "종류", "Type"]
                if i18n.lang != "ko":   # 날짜는 윈도우 지역 형식(이 PC = 한국어)이라 다른 언어 그림에선 숨김
                    hide += [i18n.T("수정한 날짜"), "수정한 날짜", "Date modified"]
                if t in hide:
                    h.hideSection(c)


os.makedirs(OUT, exist_ok=True)
log(f"시작 언어 {LANGS} 예시 {TMP}")
for lang in LANGS:
    i18n.init(lang)
    for theme, layout, n in (("light", "4", 1), ("dark", "3", 2)):
        M.SETTINGS["theme_mode"] = theme
        for f in ("state.json",):   # 이전 창의 탭이 이어지지 않게 (1.0.2)
            if os.path.exists(os.path.join(TMP, f)):
                os.remove(os.path.join(TMP, f))
        rm(os.path.join(TMP, "sessions"))
        w = M.Main()
        w.setAttribute(Qt.WA_ShowWithoutActivating)
        w.resize(1280, 760)
        w.move(-30000, -30000)
        w.show()
        wait(500)
        w.set_layout(layout, equalize=True)
        wait(200)
        paths = [PROJ, os.path.join(PROJ, "Characters", "Hero"), os.path.join(PROJ, "Environments", "Forest"),
                 os.path.join(PROJ, "Docs")]
        for p, path in zip(w.panes, paths):
            p.view().navigate(path)
        w.panes[0].add_tab(os.path.join(PROJ, "Renders"), activate=False)
        w.panes[1].add_tab(os.path.join(PROJ, "Characters", "Monster"), activate=False)
        wait(900)
        hide_type_col(w)
        w.panes[0].view().tree.setFocus()
        wait(300)
        out = os.path.join(OUT, f"{lang}_{n}.png")
        pm = w.grab()
        pm.save(out)
        log(f"{lang} {theme} 칸{layout} → {out} {pm.width()}x{pm.height()} {os.path.getsize(out) // 1024}KB")
        w.close()
        wait(400)
if M.SEARCH:
    M.SEARCH.stop()
M.svnstat.stop_all()
wait(300)
rm(TMP)
log("끝 — 예시 폴더 지움")
app.quit()
