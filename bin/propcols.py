# -*- coding: utf-8 -*-
"""자세히 보기의 윈도우 속성 열 (PROPCOLS_VER 1.0.0, 0.9.147 — 사용자 11/23 '파일 속성의 설명란을 쓰는데 자세히 보기에서 더 보고 싶다, 탐색기처럼 전부 고르기')

- 탐색기 '세부 정보 선택'과 같은 목록: 윈도우 속성 시스템(IPropertySystem.EnumeratePropertyDescriptions, 보이는 것) — all_props()
- 값: 파일의 IPropertyStore 에서 읽고 탐색기와 같은 글(IPropertyDescription.FormatForDisplay) — 날짜·크기·여러 값 그대로
  정렬용 값은 원래 값(숫자·날짜는 숫자, 글은 소문자, 여러 값은 '; ')
- COMMON = 설명 묶음(메모·제목·주제·태그·만든 이) — 머리글 우클릭에 바로 보임
- 캐시 (경로 소문자, 수정 시각, 속성 이름) → (보일 글, 정렬 값). 읽기는 prefetch(뒤 스레드, CoInitialize) — 열이 켜져 있을 때만 부름
- PickDialog: 전체 목록에서 찾아 체크 (탐색기 '자세히…' 창)
- COM 개체는 스레드마다 따로(threading.local), 속성 키(PROPERTYKEY)만 같이 씀
로그: bin\\log\\4Dir.log [QE.props]
"""
import os
import time
import logging
import threading

PROPCOLS_VER = "1.0.0"
log = logging.getLogger("QE.props")

COMMON = ["System.Comment", "System.Title", "System.Subject", "System.Keywords", "System.Author"]
MAX_COLS = 20          # 고를 수 있는 속성 열 수 (main 의 자리 수와 같음)
_cache = {}            # (경로 소문자, mtime, 이름) → (글, 정렬 값)
_CACHE_MAX = 300000
_keys = {}             # 이름 → PROPERTYKEY
_names = {}            # 이름 → 보일 이름 (UI 스레드에서 채움)
_tl = threading.local()
_BIDI = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮"), None)


def _ps():
    from win32com.propsys import propsys
    return propsys


def _key(name):
    k = _keys.get(name)
    if k is None:
        k = _keys[name] = _ps().PSGetPropertyKeyFromName(name)
    return k


def _desc(name):
    """스레드마다 IPropertyDescription 기억"""
    d = getattr(_tl, "desc", None)
    if d is None:
        d = _tl.desc = {}
    v = d.get(name)
    if v is None:
        ps = _ps()
        v = d[name] = ps.PSGetPropertyDescription(_key(name), ps.IID_IPropertyDescription)
    return v


_ALL = {"v": None}


def all_props():
    """[(이름, 보일 이름)] 보일 이름 순 — 처음 한 번만 (약 300개, 수 ms)"""
    if _ALL["v"] is not None:
        return _ALL["v"]
    t0 = time.perf_counter()
    out = []
    try:
        ps = _ps()
        sysp = ps.PSGetPropertySystem(ps.IID_IPropertySystem)
        lst = sysp.EnumeratePropertyDescriptions(3, ps.IID_IPropertyDescriptionList)   # PDEF_VIEWABLE
        for i in range(lst.GetCount()):
            try:
                d = lst.GetAt(i, ps.IID_IPropertyDescription)
                nm, dn = d.GetCanonicalName(), d.GetDisplayName()
            except Exception:   # 보일 이름 없는 속성
                continue
            if nm and dn:
                out.append((nm, dn))
                _names[nm] = dn
    except Exception:
        log.exception("속성 목록 읽기 실패")
    out.sort(key=lambda x: x[1].lower())
    _ALL["v"] = out
    log.info("윈도우 속성 목록 %d개 %.0fms", len(out), (time.perf_counter() - t0) * 1000)
    return out


def display_name(name):
    if name not in _names:
        try:
            _names[name] = _desc(name).GetDisplayName() or name
        except Exception:
            _names[name] = name.split(".")[-1]
    return _names[name]


def label(name, taken=()):
    """열 머리 글 — 4Dir 고정 열과 이름이 같으면(태그·크기 등) ' (윈도우)' 를 붙여 구분"""
    dn = display_name(name)
    return f"{dn} (Windows)" if dn in taken else dn


def cached(path, mtime, name):
    return _cache.get((path.lower(), mtime, name))


def _sortval(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v).lower()
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return float(v)
    if hasattr(v, "timestamp"):
        try:
            return v.timestamp()
        except Exception:
            return None
    return str(v).lower()


def read(path, names):
    """한 파일의 속성들 → {이름: (글, 정렬 값)} (COM 은 부른 스레드에서 CoInitialize 되어 있어야)"""
    ps = _ps()
    out = {}
    st = ps.SHGetPropertyStoreFromParsingName(path, None, 0, ps.IID_IPropertyStore)
    for nm in names:
        try:
            pv = st.GetValue(_key(nm))
            raw = pv.GetValue()
            if raw is None or raw == "" or raw == () or raw == []:
                out[nm] = ("", None)
                continue
            try:
                txt = _desc(nm).FormatForDisplay(pv, 0)
            except Exception:
                txt = "; ".join(map(str, raw)) if isinstance(raw, (list, tuple)) else str(raw)
            out[nm] = ((txt or "").translate(_BIDI).replace("\r", " ").replace("\n", " "), _sortval(raw))
        except Exception:
            out[nm] = ("", None)
    return out


def prefetch(items, names, cancel=None, progress=None):
    """items=[(경로, mtime)] 를 뒤 스레드에서 읽어 캐시. progress() 는 0.4초마다 (화면 갱신용). 돌려줌 (읽은 수, 실패 수, ms)"""
    import pythoncom
    pythoncom.CoInitialize()
    t0 = time.perf_counter()
    last = t0
    n = fail = 0
    try:
        if len(_cache) > _CACHE_MAX:
            _cache.clear()
        for path, mt in items:
            if cancel is not None and cancel():
                break
            need = [nm for nm in names if (path.lower(), mt, nm) not in _cache]
            if not need:
                continue
            try:
                vals = read(path, need)
            except Exception:
                vals = {nm: ("", None) for nm in need}
                fail += 1
            lp = path.lower()
            for nm, v in vals.items():
                _cache[(lp, mt, nm)] = v
            n += 1
            if progress is not None and time.perf_counter() - last > 0.4:
                last = time.perf_counter()
                progress()
    finally:
        _tl.desc = None   # 이 스레드의 COM 개체는 CoUninitialize 전에 놓음
        pythoncom.CoUninitialize()
    ms = (time.perf_counter() - t0) * 1000
    log.info("속성 열 %d개 읽기 %d파일 %.0fms (실패 %d) %s", len(names), n, ms, fail, names)
    return n, fail, ms


# ---------------------------------------------------------------- 고르기 창 (탐색기 '세부 정보 선택')
def pick(parent, chosen, taken=()):
    """전체 속성 목록에서 고르기 → 새 목록(고른 순서 유지) 또는 None(취소)"""
    from i18n import T
    from PySide6 import QtWidgets
    from PySide6.QtCore import Qt
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(T("자세히 보기에 보일 열 고르기"))
    dlg.resize(460, 560)
    lay = QtWidgets.QVBoxLayout(dlg)
    lay.addWidget(QtWidgets.QLabel(T("파일 속성(윈도우)에서 열로 보일 항목을 고르세요. 최대 {0}개").format(MAX_COLS)))
    find = QtWidgets.QLineEdit()
    find.setPlaceholderText(T("찾기 (예: 메모, 제목, 카메라)"))
    find.setClearButtonEnabled(True)
    lay.addWidget(find)
    lst = QtWidgets.QListWidget()
    lay.addWidget(lst, 1)
    info = QtWidgets.QLabel()
    lay.addWidget(info)
    sel = list(chosen)
    props = all_props()
    order = [p for p in props if p[0] in sel] + [p for p in props if p[0] not in sel]
    for nm, dn in order:
        it = QtWidgets.QListWidgetItem(f"{label(nm, taken)}    ({nm})")
        it.setData(Qt.UserRole, nm)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if nm in sel else Qt.Unchecked)
        lst.addItem(it)

    def count():
        info.setText(T("고른 열 {0}개").format(len(sel)))

    def changed(it):
        nm = it.data(Qt.UserRole)
        if it.checkState() == Qt.Checked and nm not in sel:
            if len(sel) >= MAX_COLS:
                lst.blockSignals(True)
                it.setCheckState(Qt.Unchecked)
                lst.blockSignals(False)
                info.setText(T("최대 {0}개까지 고를 수 있습니다").format(MAX_COLS))
                return
            sel.append(nm)
        elif it.checkState() != Qt.Checked and nm in sel:
            sel.remove(nm)
        count()

    def filt(t):
        t = t.strip().lower()
        for i in range(lst.count()):
            it = lst.item(i)
            lst.setRowHidden(i, bool(t) and t not in it.text().lower())

    lst.itemChanged.connect(changed)
    find.textChanged.connect(filt)
    count()
    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    dlg._lst, dlg._find = lst, find   # 시험용
    if parent is not None:
        dlg.setStyleSheet(parent.window().styleSheet())
    if getattr(pick, "test_hook", None):
        return pick.test_hook(dlg, sel)
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return None
    log.info("속성 열 고름 %s", sel)
    return sel
