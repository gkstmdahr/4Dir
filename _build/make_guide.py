# -*- coding: utf-8 -*-
"""4Dir 사용법 그림 만들기 (MAKE_GUIDE_VER 1.0.1)

python make_guide.py ko   → bin\\guide\\ko\\p1..p6.png (실제 4Dir 화면 + 빨간 번호) + full_p1..6.png (설명 포함 한 장)
python make_guide.py en   → bin\\guide\\en\\...
- 예시 폴더만 씀(%TEMP%\\4dir_guide_demo, 일반 이름) — 회사 경로·파일 없음. 끝나면 지움.
- 사용자 설정·상태·즐겨찾기는 건드리지 않음(전부 임시 파일).
- 창은 1번(주 모니터 아닌) 모니터에 띄움. 실제 마우스·키보드 안 씀.
로그: _build\\make_guide_log.txt
"""
import os
import sys
import time
import shutil
import stat
import subprocess
import tempfile

LANG = sys.argv[1] if len(sys.argv) > 1 else "ko"
HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
sys.path.insert(0, BIN)
LOGF = os.path.join(HERE, "make_guide_log.txt")


def log(msg):
    line = time.strftime("%H:%M:%S ") + f"[{LANG}] " + msg
    print(line)
    with open(LOGF, "a", encoding="utf-8") as f:
        f.write(line + "\n")


import i18n  # noqa: E402
from i18n import T  # noqa: E402
i18n.init(LANG)
import main as M  # noqa: E402
import session, ui_parts, keymap, guide  # noqa: E402,E401
from PySide6 import QtWidgets, QtCore, QtGui  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

# 예시 폴더: 드라이브 맨 위(주소줄에 사용자 이름·회사 경로가 안 보이게). 이미 있으면(우리 것 아님) 멈춤
TMP = os.path.splitdrive(BIN)[0] + os.sep + "4Dir_Demo"
MARK = os.path.join(TMP, ".4dir_guide_demo")
if os.path.exists(TMP) and not os.path.exists(MARK):
    raise SystemExit(f"{TMP} 가 이미 있음 (4Dir 예시 폴더 아님) — 지우지 않고 멈춤")
OUT = os.path.join(BIN, "guide", LANG)
SVN_BIN = r"C:\Program Files\TortoiseSVN\bin"


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


# ---------------------------------------------------------------- 예시 폴더
rm(TMP)
os.makedirs(TMP)
touch(MARK, "4Dir make_guide.py 예시 폴더 — 끝나면 지움")
PROJ = os.path.join(TMP, "Project")
for d in ("Characters/Hero", "Characters/Monster", "Environments/Forest", "Effects", "Renders"):
    os.makedirs(os.path.join(PROJ, d), exist_ok=True)
for n in ("hero_idle.max", "hero_run.max", "hero_attack_01.max", "hero_attack_02.max", "hero_skin.max",
          "texture_body.png", "texture_face.png", "notes.txt"):
    touch(os.path.join(PROJ, n), n * 20)
for n in ("monster_idle.max", "monster_walk.max"):
    touch(os.path.join(PROJ, "Characters", "Monster", n))
for n in ("hero_idle.max", "hero_run.max"):
    touch(os.path.join(PROJ, "Characters", "Hero", n))
for n in ("tree_01.max", "rock_01.max"):
    touch(os.path.join(PROJ, "Environments", "Forest", n))

# SVN 예시 (임시 저장소)
WC = os.path.join(TMP, "svn_project")
have_svn = os.path.exists(os.path.join(SVN_BIN, "svn.exe"))
if have_svn:
    svn, admin = os.path.join(SVN_BIN, "svn.exe"), os.path.join(SVN_BIN, "svnadmin.exe")
    repo = os.path.join(TMP, "repo")
    subprocess.run([admin, "create", repo], check=True)
    subprocess.run([svn, "checkout", "-q", "file:///" + repo.replace("\\", "/"), WC], check=True)
    for p in ("Characters/hero.max", "Characters/monster.max", "Props/barrel.max", "Props/crate.max",
              "level_01.max", "level_02.max"):
        touch(os.path.join(WC, p), p)
    subprocess.run([svn, "add", "-q", "--force", "."], cwd=WC, check=True)
    subprocess.run([svn, "commit", "-q", "-m", "init"], cwd=WC, check=True)
    subprocess.run([svn, "update", "-q"], cwd=WC, check=True)
    time.sleep(1.1)
    touch(os.path.join(WC, "Characters", "hero.max"), "changed")     # 수정 → Characters 빨강
    touch(os.path.join(WC, "level_02.max"), "changed!!")              # 수정 파일
    touch(os.path.join(WC, "new_model.max"), "new")
    subprocess.run([svn, "add", "-q", "new_model.max"], cwd=WC, check=True)   # 추가
    touch(os.path.join(WC, "temp_notes.txt"), "tmp")                  # 버전 관리 밖

# ---------------------------------------------------------------- 4Dir (임시 설정)
M.STATE_FILE = os.path.join(TMP, "state.json")
M.FAV.path = os.path.join(TMP, "fav.json")
M.WS_DIR = os.path.join(TMP, "ws")
session.SESS_DIR = os.path.join(TMP, "sessions")
M.SETTINGS = ui_parts.Settings(os.path.join(TMP, "settings.json"))
M.SETTINGS.data.update({"search_roots": [{"path": PROJ, "on": True}], "theme_mode": "light", "sysmon": False,
                        "breadcrumb": True, "lang": LANG})
M.FAV.items = [{"name": "Project", "path": PROJ}, {"name": "Characters", "path": os.path.join(PROJ, "Characters")},
               {"name": "Renders", "path": os.path.join(PROJ, "Renders")}]
app = QtWidgets.QApplication([])
i18n.apply_font(app)
app.setQuitOnLastWindowClosed(False)


def wait(ms):
    t = time.time()
    while time.time() - t < ms / 1000:
        app.processEvents()
        time.sleep(0.01)


def until(cond, sec):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


scr = [s for s in app.screens() if "(1)" in s.name()] or [s for s in app.screens() if s is not app.primaryScreen()] or [app.primaryScreen()]
G = scr[0].availableGeometry()
w = M.Main()
w.resize(1100, 640)
w.move(G.x() + 40, G.y() + 40)
w.show()
w.activateWindow()
wait(800)
os.makedirs(OUT, exist_ok=True)


def rect_of(widget, pad=2):
    tl = widget.mapTo(w, QtCore.QPoint(0, 0))
    return QtCore.QRect(tl, widget.size()).adjusted(-pad, -pad, pad, pad)


def union(*rs):
    r = rs[0]
    for x in rs[1:]:
        r = r.united(x)
    return r


def save(n, marks, base=None, extra=None):
    """화면을 잡아 빨간 테두리 + 번호. marks = [(번호, QRect(창 좌표))]"""
    pm = base or w.grab()
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    if extra:
        extra(p)
    red = QtGui.QColor("#e53935")
    for m in marks:
        num, r = m[0], m[1]
        right = len(m) > 2 and m[2] == "right"   # 번호를 오른쪽에 (왼쪽 아이콘·배지를 가리지 않게)
        p.setPen(QtGui.QPen(red, 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(r), 4, 4)
        c = QtCore.QPointF(r.right() + 14, r.center().y()) if right else QtCore.QPointF(r.left() + 2, r.top() + 2)
        p.setPen(Qt.NoPen)
        p.setBrush(red)
        p.drawEllipse(c, 11, 11)
        f = p.font()
        f.setBold(True)
        f.setPixelSize(14)
        p.setFont(f)
        p.setPen(QtGui.QColor("white"))
        p.drawText(QtCore.QRectF(c.x() - 11, c.y() - 11, 22, 22), Qt.AlignCenter, str(num))
    p.end()
    path = os.path.join(OUT, f"p{n}.png")
    pm.save(path)
    log(f"p{n}.png 저장 {pm.width()}x{pm.height()} 표시 {len(marks)}개")


# ---------------------------------------------------------------- 1. 화면 구성
w.set_layout("2h", equalize=True)
wait(200)
a, b = w.panes[0], w.panes[1]
a.view().navigate(PROJ)
b.view().navigate(os.path.join(PROJ, "Characters"))
b.add_tab(os.path.join(PROJ, "Renders"), activate=False)
wait(700)
a.view().tree.setFocus()
tb = w.topbar
lay_ws = [tb.widgetForAction(act) for act in list(w.layout_actions.values()) + [w.act_grid] if tb.widgetForAction(act)]
save(1, [
    (1, union(*[rect_of(x) for x in lay_ws])),
    (2, rect_of(w.favbar, 0)),
    (3, rect_of(a.addr_stack)),
    (4, rect_of(a.btn_find)),
    (5, union(rect_of(a.bar), rect_of(a.findChild(QtWidgets.QToolButton, "plusTab")))),
    (6, rect_of(w.gsearch)),
    (7, rect_of(a.stat)),
])

# ---------------------------------------------------------------- 2. 칸 나누기와 창 구성
w.set_layout("4", equalize=True)
wait(300)
for p_, d in zip(w.panes[:4], (PROJ, os.path.join(PROJ, "Characters"), os.path.join(PROJ, "Environments"), os.path.join(PROJ, "Effects"))):
    p_.view().navigate(d)
wait(700)
w.panes[0].view().tree.setFocus()
wait(200)
h = w.rows[0].handle(1)
menu_btn = next((x for x in tb.findChildren(QtWidgets.QToolButton) if x.text().startswith(T("창 저장/불러오기")[:4])), None)
marks = [(1, rect_of(w.panes[0], 0)), (2, rect_of(h, 3))]
if menu_btn is not None:
    marks.append((3, rect_of(menu_btn)))
marks.append((4, rect_of(w.panes[1].bar)))
save(2, marks)

# ---------------------------------------------------------------- 3. 파일 작업 (끌어 놓기)
w.set_layout("1", equalize=True)
wait(300)
v = w.panes[0].view()
v.navigate(PROJ)
wait(500)
tv = v.tree
names = {e[0]: i for i, e in enumerate(v.model_.rows)}
sm = tv.selectionModel()
sm.clearSelection()
for n in ("hero_idle.max", "hero_run.max", "hero_attack_01.max"):
    sm.select(v.model_.index(names[n], 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
tv.setCurrentIndex(v.model_.index(names["hero_idle.max"], 0))
tv.setFocus()
md = v.model_.mimeData([v.model_.index(names[n], 0) for n in ("hero_idle.max", "hero_run.max", "hero_attack_01.max")])
fr = names["Characters"]
pos = tv.visualRect(v.model_.index(fr, 0)).center() + QtCore.QPoint(40, 0)
tv.dragMoveEvent(QtGui.QDragMoveEvent(pos, Qt.CopyAction | Qt.MoveAction, md, Qt.LeftButton, Qt.NoModifier))
wait(300)
hint_pm = M.DROP_HINT.grab() if M.DROP_HINT is not None and M.DROP_HINT.isVisible() else None
icon = M.shellops.icon_for("hero_idle.max", False, 48)
icon = icon if isinstance(icon, QtGui.QIcon) else QtGui.QIcon(icon)
dpm, hot = M.drag_pixmap(icon, 3, 1.0)
cur = tv.viewport().mapTo(w, pos)


def draw_drag(p):
    p.drawPixmap(cur - hot, dpm)
    if hint_pm is not None:
        p.drawPixmap(cur + QtCore.QPoint(16, 6), hint_pm)
    # 커서 화살표
    arrow = QtGui.QPolygonF([QtCore.QPointF(0, 0), QtCore.QPointF(0, 17), QtCore.QPointF(4.5, 13), QtCore.QPointF(8, 20),
                             QtCore.QPointF(10.5, 19), QtCore.QPointF(7, 12), QtCore.QPointF(12, 12)])
    p.save()
    p.translate(cur)
    p.setPen(QtGui.QPen(QtGui.QColor("black"), 1))
    p.setBrush(QtGui.QColor("white"))
    p.drawPolygon(arrow)
    p.restore()


row_r = tv.visualRect(v.model_.index(fr, 0))
row_r = QtCore.QRect(tv.viewport().mapTo(w, QtCore.QPoint(0, row_r.top())), QtCore.QSize(tv.viewport().width(), row_r.height()))
save(3, [(1, row_r.adjusted(-2, -2, 2, 2))], extra=draw_drag)
tv.dragLeaveEvent(QtGui.QDragLeaveEvent())
M.drop_hint(None)
wait(100)

# ---------------------------------------------------------------- 4. 검색
ok = until(lambda: M.SEARCH is not None and M.SEARCH.state == "ready", 40)
log(f"색인 준비 {ok} ({M.SEARCH.count() if M.SEARCH else 0}개)")
w.gsearch.setText("hero")
w.do_global_search("hero")
wait(1200)
v = w.panes[0].view()
w.panes[0].view().tree.setFocus()
pb = w.panes[0].bar
tab_r = pb.tabRect(pb.currentIndex())
tab_r = QtCore.QRect(pb.mapTo(w, tab_r.topLeft()), tab_r.size())
r0 = v.tree.visualRect(v.model_.index(0, 0))
row0 = QtCore.QRect(v.tree.viewport().mapTo(w, QtCore.QPoint(0, r0.top())), QtCore.QSize(v.tree.viewport().width(), r0.height()))
save(4, [(1, rect_of(w.gsearch)), (2, tab_r.adjusted(-2, -2, 2, 2)), (3, row0.adjusted(-2, -2, 2, 2))])

# ---------------------------------------------------------------- 5. SVN
if have_svn:
    v.navigate(WC)
    until(lambda: all(e[0] in v.model_.svn for e in v.model_.rows), 20)
    wait(500)
    st = v.model_.svn
    log(f"SVN 배지 {st}")
    idx = {e[0]: i for i, e in enumerate(v.model_.rows)}

    def icon_r(name):
        r = v.tree.visualRect(v.model_.index(idx[name], 0))
        tl = v.tree.viewport().mapTo(w, r.topLeft())
        return QtCore.QRect(tl, QtCore.QSize(min(r.width(), 26 + v.tree.fontMetrics().horizontalAdvance(name)), r.height())).adjusted(-2, -2, 2, 2)
    marks = []
    for num, want in ((1, "normal"), (2, "modified"), (3, "added"), (4, "unversioned")):
        nm = next((n for n in idx if st.get(n) == want), None)
        if nm:
            marks.append((num, icon_r(nm), "right"))
    v.tree.setFocus()
    save(5, marks)

# ---------------------------------------------------------------- 6. 단축키 설정
dlg = keymap.KeyDialog(M.SETTINGS["keys"], w)
dlg.move(G.x() + 80, G.y() + 60)
dlg.show()
wait(600)
pm = dlg.grab()
tl = dlg.search.mapTo(dlg, QtCore.QPoint(0, 0))
sr = QtCore.QRect(tl, dlg.search.size()).adjusted(-2, -2, 2, 2)
p = QtGui.QPainter(pm)
p.setRenderHint(QtGui.QPainter.Antialiasing)
red = QtGui.QColor("#e53935")
first = QtCore.QRect(QtCore.QPoint(6, sr.bottom() + 6), QtCore.QSize(pm.width() / pm.devicePixelRatio() - 12, 140))
for num, r in ((1, first),):
    p.setPen(QtGui.QPen(red, 2.5))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QtCore.QRectF(r), 4, 4)
    c = QtCore.QPointF(r.left() + 2, r.top() + 2)
    p.setPen(Qt.NoPen)
    p.setBrush(red)
    p.drawEllipse(c, 11, 11)
    f = p.font()
    f.setBold(True)
    f.setPixelSize(14)
    p.setFont(f)
    p.setPen(QtGui.QColor("white"))
    p.drawText(QtCore.QRectF(c.x() - 11, c.y() - 11, 22, 22), Qt.AlignCenter, "1")
p.end()
pm.save(os.path.join(OUT, "p6.png"))
log(f"p6.png 저장 {pm.width()}x{pm.height()}")
dlg.close()

# ---------------------------------------------------------------- 설명까지 한 장 (웹 게시용)
g = guide.GuideWindow()
g.resize(1400, 720)
g.move(G.x() + 20, G.y() + 20)
g.show()
wait(500)
for i in range(len(g.pages)):
    g.go(i)
    wait(250)
    g.grab().save(os.path.join(OUT, f"full_p{i + 1}.png"))
log("full_p1..6.png 저장")
g.close()
w.close()
wait(400)
if M.SEARCH:
    M.SEARCH.stop()
M.svnstat.stop_all()
wait(300)
rm(TMP)
log("끝 — 예시 폴더 지움")
