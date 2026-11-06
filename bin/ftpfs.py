# -*- coding: utf-8 -*-
"""FTP 를 폴더처럼 (FTPFS_VER 1.0.0, 0.9.109 빌드 3 — 사용자 11/6 '추가 기능 전부', 경쟁 앱 조사 'FTP')

- 경로: '::FTP:' + 사이트 + '|' + 서버 안 경로   예) ::FTP:ftp://me@example.com:21|/pub/docs
  사이트 = 'ftp://사용자@호스트:포트' 또는 'ftps://…'(TLS). 주소줄에 ftp://호스트/경로 를 쳐도 됨
- 압축 파일 안 보기(archives)와 같은 길: 목록 보기·열기(임시 폴더로 받아서)·복사해 꺼내기·끌기는 archives 가 이 모듈로 넘김
- 더해서: 올리기(다른 칸에서 복사·끌어 놓기·붙여넣기) · 새 폴더 · 지우기 · 이름 바꾸기
- 비밀번호: 처음 들어갈 때 물음. '기억'을 켜면 윈도우 자격 증명(Credential Manager, 이름 4Dir:사이트)에만 저장 — 4Dir 설정 파일에는 안 씀
- 연결은 사이트마다 하나, 잠금으로 차례대로. 끊기면 한 번 다시 연결
로그: bin\\log\\4Dir.log [QE.ftp] (비밀번호는 로그에 안 남김)
"""
import os
import re
import time
import ftplib
import socket
import calendar
import logging
import tempfile
import threading
from urllib.parse import urlsplit, unquote

FTPFS_VER = "1.1.0"   # 1.1.0 (0.9.110 점검): 서버 이름으로 임시 폴더 밖에 쓰기 막기 · UTF-8 아닌 서버(CP949) · 연결 잠금 기다림 한도
#   · 내 PC 쪽 오류(디스크 가득 등)를 끊김으로 착각해 처음부터 다시 하던 것 · LIST 날짜(해 넘김·2/29) · MLSD 시간 · 로그인 중 전송 깨짐
log = logging.getLogger("QE.ftp")
PREFIX = "::FTP:"
TIMEOUT = 15
LOCK_WAIT = 30    # 다른 작업(올리기 등)이 연결을 쓰는 중이면 이만큼만 기다리고 '사용 중' 오류 (화면이 오래 멈추지 않게)
NET_ERRORS = (ftplib.error_temp, ftplib.error_reply, EOFError, ConnectionError, TimeoutError, socket.timeout, socket.gaierror)
_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def safe_name(name):
    """서버가 준 이름을 이 PC 에 쓸 수 있나 — '..\\..\\x' 같은 이름으로 임시 폴더 밖에 쓰는 것 막기 (점검 1)"""
    if not name or name in (".", "..") or _BAD_NAME.search(name) or name.rstrip(" .") != name:
        return False
    return name.split(".")[0].lower() not in _RESERVED
_sites = {}       # 사이트 → {"pw", "conn", "lock"}
_dirs = {}        # (사이트, 경로) → {이름: (폴더?, 크기, 날짜)}
_glock = threading.Lock()
_seq = [0]


def _long(p):
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetLongPathNameW(p, buf, 1024)
        return buf.value if 0 < n < 1024 else p
    except Exception:
        return p


TMP_ROOT = os.path.join(_long(tempfile.gettempdir()), "4dir_ftp")


class NeedLogin(OSError):
    pass


# ---------------------------------------------------------------- 경로
def is_ftp(p):
    return bool(p) and p.startswith(PREFIX)


def is_url(t):
    t = (t or "").strip().lower()
    return t.startswith("ftp://") or t.startswith("ftps://")


def site_of(scheme, user, host, port):
    return f"{scheme}://{user or 'anonymous'}@{host}:{port or 21}"


def parse_site(site):
    u = urlsplit(site)
    return {"tls": u.scheme == "ftps", "user": unquote(u.username or "anonymous"), "host": u.hostname or "", "port": u.port or 21}


def from_url(url):
    """'ftp://me@host:21/pub' → (사이트, '/pub') · 주소에 비밀번호가 있으면 함께 돌려줌"""
    u = urlsplit(url.strip())
    site = site_of(u.scheme.lower(), unquote(u.username or ""), u.hostname or "", u.port)
    return site, (unquote(u.path) or "/"), (unquote(u.password) if u.password else None)


def make(site, path="/"):
    path = "/" + path.strip("/") if path.strip("/") else "/"
    return PREFIX + site + "|" + path


def split(p):
    body = p[len(PREFIX):]
    site, _, path = body.partition("|")
    return site, ("/" + path.strip("/")) if path.strip("/") else "/"


def name_of(p):
    site, path = split(p)
    return path.rsplit("/", 1)[-1] if path != "/" else parse_site(site)["host"]


def parent_of(p):
    site, path = split(p)
    if path == "/":
        return "내 PC"   # main.THIS_PC
    return make(site, path.rsplit("/", 1)[0] or "/")


def friendly(p):
    site, path = split(p)
    s = parse_site(site)
    return f"{'ftps' if s['tls'] else 'ftp'}://{s['user']}@{s['host']}{'' if s['port'] == 21 else ':' + str(s['port'])}{path}"


def chain(p):
    site, path = split(p)
    out = [("🌐 " + parse_site(site)["host"], make(site, "/"))]
    acc = ""
    for part in [x for x in path.split("/") if x]:
        acc += "/" + part
        out.append((part, make(site, acc)))
    return out


# ---------------------------------------------------------------- 연결
def _cred_target(site):
    return "4Dir:" + site


def saved_password(site):
    try:
        import win32cred
        c = win32cred.CredRead(_cred_target(site), win32cred.CRED_TYPE_GENERIC)
        b = c["CredentialBlob"]
        return b.decode("utf-16-le") if isinstance(b, bytes) else b
    except Exception:
        return None


def save_password(site, pw):
    try:
        import win32cred
        win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC, "TargetName": _cred_target(site), "UserName": parse_site(site)["user"],
                             "CredentialBlob": pw, "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)
        log.info("비밀번호 윈도우 자격 증명에 저장 %s", site)
    except Exception:
        log.exception("자격 증명 저장 실패")


def forget_password(site):
    try:
        import win32cred
        win32cred.CredDelete(_cred_target(site), win32cred.CRED_TYPE_GENERIC, 0)
    except Exception:
        pass


def ready(site):
    """비밀번호를 알고 있거나(이번 실행·자격 증명) 익명이면 True"""
    with _glock:
        s = _sites.get(site)
    if s and s.get("pw") is not None:
        return True
    if parse_site(site)["user"] == "anonymous":
        return True
    return saved_password(site) is not None


def _open(site, pw, enc="utf-8"):
    s = parse_site(site)
    t0 = time.time()
    ftp = ftplib.FTP_TLS(timeout=TIMEOUT) if s["tls"] else ftplib.FTP(timeout=TIMEOUT)
    ftp.encoding = enc   # UTF-8 이 아닌 서버면 _call 이 cp949 로 다시 연결
    ftp.connect(s["host"], s["port"])
    ftp.login(s["user"], pw if pw is not None else ("anonymous@" if s["user"] == "anonymous" else ""))
    if s["tls"]:
        ftp.prot_p()
    try:
        ftp.sendcmd("OPTS UTF8 ON")
    except ftplib.Error:
        pass
    ftp.set_pasv(True)
    log.info("FTP 연결 %s://%s@%s:%s %.0fms", "ftps" if s["tls"] else "ftp", s["user"], s["host"], s["port"], (time.time() - t0) * 1000)
    return ftp


def login(site, pw, remember=False):
    """비밀번호 확인 겸 연결 (실패하면 예외). remember = 윈도우 자격 증명에 저장"""
    with _glock:
        old = _sites.get(site)
    enc = old.get("enc", "utf-8") if old else "utf-8"
    ftp = _open(site, pw, enc)
    if old is not None:   # 점검 5: 같은 사이트 전송 중이면 끝날 때까지 기다렸다 바꿈 (전엔 쓰던 연결을 그냥 닫아 전송이 깨짐)
        if not old["lock"].acquire(timeout=LOCK_WAIT):
            ftp.close()
            raise OSError("FTP 사용 중 — 잠시 뒤 다시")
        try:
            if old.get("conn") is not None:
                try:
                    old["conn"].close()
                except Exception:
                    pass
            old.update(pw=pw, conn=ftp)
        finally:
            old["lock"].release()
    else:
        with _glock:
            _sites[site] = {"pw": pw, "conn": ftp, "lock": threading.RLock(), "enc": enc}
    if remember and pw:
        save_password(site, pw)
    return True


def _session(site):
    with _glock:
        s = _sites.get(site)
        if s is None:
            pw = saved_password(site)
            if pw is None and parse_site(site)["user"] != "anonymous":
                raise NeedLogin(f"FTP 로그인 필요: {site}")
            s = _sites[site] = {"pw": pw, "conn": None, "lock": threading.RLock(), "enc": "utf-8"}
    return s


def _call(site, fn):
    """연결을 잡고 fn(ftp) — 끊겼으면 한 번 다시 연결"""
    s = _session(site)
    if not s["lock"].acquire(timeout=LOCK_WAIT):   # 점검 3: 다른 작업이 오래 쓰면 무한정 기다리지 않음
        raise OSError("FTP 사용 중 — 다른 작업(올리기·받기)이 끝난 뒤 다시")
    try:
        for attempt in (1, 2):
            had = s["conn"] is not None
            try:
                if s["conn"] is None:
                    s["conn"] = _open(site, s["pw"], s.get("enc", "utf-8"))
                return fn(s["conn"])
            except UnicodeDecodeError:   # 점검 2: UTF-8 이 아닌 서버(옛 한국 서버 = CP949) → 그 사이트는 cp949 로 다시
                if s.get("enc", "utf-8") != "utf-8" or attempt == 2:
                    raise
                log.warning("FTP 이름이 UTF-8 아님 → cp949 로 다시 연결 %s", site)
                s["enc"] = "cp949"
                _drop(s)
            except NET_ERRORS as ex:   # 점검 6: 네트워크 오류만 다시 연결 (디스크 가득·쓸 수 없는 이름 같은 내 PC 오류는 그대로 알림)
                log.warning("FTP 끊김/오류 (%d) %s", attempt, ex)
                _drop(s)
                if attempt == 2 or not had:   # 점검 4: 처음 연결부터 안 되면 또 시도하지 않음 (응답 없는 서버로 목록 일꾼이 오래 묶이던 것)
                    raise
            except OSError as ex:
                if isinstance(ex, (ConnectionError, TimeoutError)) or getattr(ex, "winerror", None) in (10053, 10054, 10060, 10061):
                    log.warning("FTP 연결 오류 (%d) %s", attempt, ex)
                    _drop(s)
                    if attempt == 2 or not had:
                        raise
                else:
                    raise
    finally:
        s["lock"].release()


def _drop(s):
    try:
        if s["conn"] is not None:
            s["conn"].close()
    except Exception:
        pass
    s["conn"] = None


def close_all():
    with _glock:
        for s in _sites.values():
            try:
                if s.get("conn") is not None:
                    s["conn"].quit()
            except Exception:
                pass
            s["conn"] = None


# ---------------------------------------------------------------- 목록
_LIST = re.compile(r"^([dl-])\S+\s+\d+\s+\S+(?:\s+\S+)?\s+(\d+)\s+(\w{3}\s+\d+\s+[\d:]+)\s+(.+)$")   # 그룹 칸 없는 서버도
_DOS = re.compile(r"^(\d\d)-(\d\d)-(\d\d)\s+(\d\d):(\d\d)(AM|PM)\s+(<DIR>|\d+)\s+(.+)$")   # IIS·DOS 형식


def _mtime(s):
    try:
        return calendar.timegm(time.strptime(s[:14], "%Y%m%d%H%M%S"))   # MLSD 는 UTC (점검 9: 서머타임 1시간 어긋남)
    except ValueError:
        return 0


def _listing(ftp, path):
    out = {}
    try:
        for name, f in ftp.mlsd(path, facts=["type", "size", "modify"]):
            t = f.get("type", "")
            if t in ("cdir", "pdir") or name in (".", ".."):
                continue
            isd = t == "dir"
            out[name] = (isd, -1 if isd else int(f.get("size", 0) or 0), _mtime(f.get("modify", "")))
        return out
    except ftplib.error_perm:
        pass   # MLSD 없는 옛 서버 → LIST
    lines = []
    ftp.retrlines("LIST " + path, lines.append)
    now = time.time()
    for ln in lines:
        m = _LIST.match(ln)
        if not m:
            dm = _DOS.match(ln)
            if dm:
                mo, dd, yy, hh, mi, ap, sz, name = dm.groups()
                h = int(hh) % 12 + (12 if ap == "PM" else 0)
                try:
                    mt = time.mktime((2000 + int(yy) if int(yy) < 70 else 1900 + int(yy), int(mo), int(dd), h, int(mi), 0, 0, 0, -1))
                except (OverflowError, ValueError):
                    mt = 0
                if name not in (".", ".."):
                    out[name] = (sz == "<DIR>", -1 if sz == "<DIR>" else int(sz), mt)
            continue
        kind, size, date, name = m.groups()
        if kind == "l":
            name = name.split(" -> ")[0]
        if name in (".", ".."):
            continue
        mt = 0
        if ":" in date:   # 'Dec 20 10:00' = 최근 6개월 — 올해로 보고, 미래면 작년 (점검 7: 해 넘김·2/29)
            y = time.localtime(now).tm_year
            for yy in (y, y - 1):
                try:
                    mt = time.mktime(time.strptime(f"{yy} {date}", "%Y %b %d %H:%M"))
                except ValueError:
                    continue
                if mt <= now + 86400:
                    break
        else:
            try:
                mt = time.mktime(time.strptime(date, "%b %d %Y"))
            except ValueError:
                mt = 0
        out[name] = (kind == "d", -1 if kind == "d" else int(size), mt)
    return out


def list_dir(p, cancel=lambda: False):
    site, path = split(p)
    t0 = time.time()
    try:
        idx = _call(site, lambda ftp: _listing(ftp, path))
    except NeedLogin:
        raise
    except Exception as ex:
        log.exception("FTP 목록 실패 %s", friendly(p))
        raise OSError(f"FTP: {ex}") from ex
    _dirs[(site, path)] = idx
    log.info("FTP 목록 %s : %d개 %.0fms", friendly(p), len(idx), (time.time() - t0) * 1000)
    base = path.rstrip("/")
    return [[n, d, s, m, 0, make(site, base + "/" + n), None, None] for n, (d, s, m) in idx.items()]


def exists(p):
    return True   # 실제 확인은 목록 읽을 때 (주소 칠 때마다 서버에 묻지 않음)


def is_dir(p):
    site, path = split(p)
    if path == "/":
        return True
    par, _, name = path.rpartition("/")
    v = _dirs.get((site, par or "/"), {}).get(name)
    return True if v is None else v[0]


# ---------------------------------------------------------------- 받기·올리기
def _new_tmp():
    with _glock:
        _seq[0] += 1
        d = os.path.join(TMP_ROOT, f"{os.getpid()}_{_seq[0]}")
    os.makedirs(d, exist_ok=True)
    return d


def _download(ftp, rpath, lpath, isd, n):
    if isd:
        os.makedirs(lpath, exist_ok=True)
        for name, (d, _s, _m) in _listing(ftp, rpath).items():
            if not safe_name(name):   # 점검 1: '..\\..\\x' 같은 이름 → 임시 폴더 밖에 쓰지 않게 건너뜀
                log.warning("FTP 받기: 이 PC 에 쓸 수 없는 이름 건너뜀 %r", name)
                continue
            _download(ftp, rpath.rstrip("/") + "/" + name, os.path.join(lpath, name), d, n)
        return
    with open(lpath, "wb") as f:
        ftp.retrbinary("RETR " + rpath, f.write, 1048576)
    n[0] += 1


def extract_temp(paths):
    """FTP 항목들 → 임시 폴더로 받아 진짜 경로 목록 (열기·복사·끌기)"""
    out = []
    t0 = time.time()
    dest = _new_tmp()
    n = [0]
    for p in paths:
        site, path = split(p)
        name = path.rsplit("/", 1)[-1] or parse_site(site)["host"]
        if not safe_name(name):
            name = _BAD_NAME.sub("_", name).rstrip(" .") or "_"
        lp = os.path.join(dest, name)
        _call(site, lambda ftp: _download(ftp, path, lp, is_dir(p), n))
        out.append(lp)
    log.info("FTP 받음 %d개 파일 → %s %.1f초", n[0], dest, time.time() - t0)
    return out


def _upload(ftp, lpath, rpath, n):
    if os.path.isdir(lpath):
        try:
            ftp.mkd(rpath)
        except ftplib.error_perm:
            pass   # 이미 있음
        for name in os.listdir(lpath):
            _upload(ftp, os.path.join(lpath, name), rpath.rstrip("/") + "/" + name, n)
        return
    with open(lpath, "rb") as f:
        ftp.storbinary("STOR " + rpath, f, 1048576)
    n[0] += 1


def upload(srcs, dst_dir_path):
    """진짜 파일·폴더들 → FTP 폴더 (같은 이름은 덮어씀)"""
    site, path = split(dst_dir_path)
    t0 = time.time()
    n = [0]
    for s in srcs:
        _call(site, lambda ftp, s=s: _upload(ftp, s, path.rstrip("/") + "/" + os.path.basename(os.path.normpath(s)), n))
    _dirs.pop((site, path), None)
    log.info("FTP 올림 %d개 파일 → %s %.1f초", n[0], friendly(dst_dir_path), time.time() - t0)
    return n[0]


def _rm(ftp, rpath, isd):
    if not isd:
        try:
            ftp.delete(rpath)
            return
        except ftplib.error_perm:   # 목록 기억이 없어 파일로 봤는데 폴더인 경우 → 폴더로 다시
            isd = True
    if isd:
        for name, (d, _s, _m) in _listing(ftp, rpath).items():
            _rm(ftp, rpath.rstrip("/") + "/" + name, d)
        ftp.rmd(rpath)


def delete(paths):
    """FTP 에서 지움 (휴지통 없음 — 부르는 쪽이 확인)"""
    for p in paths:
        site, path = split(p)
        _call(site, lambda ftp, path=path, p=p: _rm(ftp, path, is_dir(p)))
        log.info("FTP 지움 %s", friendly(p))


def mkdir(dir_p, name):
    site, path = split(dir_p)
    rp = path.rstrip("/") + "/" + name
    _call(site, lambda ftp: ftp.mkd(rp))
    log.info("FTP 새 폴더 %s", rp)
    return make(site, rp)


def rename(p, new_name):
    site, path = split(p)
    rp = path.rsplit("/", 1)[0] + "/" + new_name
    _call(site, lambda ftp: ftp.rename(path, rp))
    log.info("FTP 이름 바꿈 %s → %s", path, rp)
    return make(site, rp)


def cleanup():
    close_all()
    if not os.path.isdir(TMP_ROOT):
        return
    import shutil
    for d in os.listdir(TMP_ROOT):
        if d.startswith(f"{os.getpid()}_"):
            shutil.rmtree(os.path.join(TMP_ROOT, d), ignore_errors=True)


# ---------------------------------------------------------------- 연결 창 (도구 ▸ FTP 연결… · 주소줄 ftp:// · 비밀번호 모를 때)
def login_dialog(parent, site=None, path="/", recent=()):
    """연결 창 → 성공하면 (사이트, 경로), 취소면 None. 비밀번호 확인까지 여기서 함"""
    from i18n import T
    from PySide6 import QtWidgets
    s = parse_site(site) if site else {"tls": False, "user": "anonymous", "host": "", "port": 21}
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(T("FTP 연결"))
    lay = QtWidgets.QVBoxLayout(dlg)
    f = QtWidgets.QFormLayout()
    rec = QtWidgets.QComboBox()
    rec.addItem(T("(새 연결)"), None)
    for r in recent:
        rec.addItem(friendly(make(r)), r)
    host = QtWidgets.QLineEdit(s["host"])
    host.setPlaceholderText("ftp.example.com")
    port = QtWidgets.QSpinBox()
    port.setRange(1, 65535)
    port.setValue(s["port"])
    user = QtWidgets.QLineEdit("" if s["user"] == "anonymous" else s["user"])
    user.setPlaceholderText(T("비우면 익명(anonymous)"))
    pw = QtWidgets.QLineEdit()
    pw.setEchoMode(QtWidgets.QLineEdit.Password)
    tls = QtWidgets.QCheckBox(T("암호화 (FTPS)"))
    tls.setChecked(s["tls"])
    remember = QtWidgets.QCheckBox(T("비밀번호 기억 (윈도우 자격 증명에 저장)"))
    folder = QtWidgets.QLineEdit(path or "/")
    if recent:
        f.addRow(T("최근"), rec)
    f.addRow(T("서버"), host)
    f.addRow(T("포트"), port)
    f.addRow(T("사용자"), user)
    f.addRow(T("비밀번호"), pw)
    f.addRow(T("폴더"), folder)
    f.addRow("", tls)
    f.addRow("", remember)
    lay.addLayout(f)
    err = QtWidgets.QLabel()
    err.setStyleSheet("color:#d33;")
    err.setWordWrap(True)
    lay.addWidget(err)
    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    bb.button(QtWidgets.QDialogButtonBox.Ok).setText(T("연결"))
    lay.addWidget(bb)
    out = {}

    def pick_recent(_i):
        r = rec.currentData()
        if r:
            ps = parse_site(r)
            host.setText(ps["host"])
            port.setValue(ps["port"])
            user.setText("" if ps["user"] == "anonymous" else ps["user"])
            tls.setChecked(ps["tls"])
            pw.setText(saved_password(r) or "")
    rec.currentIndexChanged.connect(pick_recent)

    def go():
        h = host.text().strip()
        if is_url(h):   # 주소를 통째로 붙여넣었으면 나눠 씀
            st, pth, p0 = from_url(h)
            ps = parse_site(st)
            h = ps["host"]
            host.setText(h)
            port.setValue(ps["port"])
            user.setText("" if ps["user"] == "anonymous" else ps["user"])
            folder.setText(pth)
            if p0:
                pw.setText(p0)
        if not h:
            err.setText(T("서버 주소를 넣으세요"))
            return
        st = site_of("ftps" if tls.isChecked() else "ftp", user.text().strip() or "anonymous", h, port.value())
        p = pw.text() if user.text().strip() else None
        try:
            from PySide6 import QtGui
            QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtGui.Qt.WaitCursor))
            try:
                login(st, p, remember.isChecked())
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
        except Exception as ex:
            log.warning("FTP 로그인 실패 %s: %s", st, ex)
            err.setText(T("연결하지 못했습니다: {0}").format(ex))
            return
        out["r"] = (st, folder.text().strip() or "/")
        dlg.accept()
    bb.accepted.connect(go)
    bb.rejected.connect(dlg.reject)
    (pw if site and s["user"] != "anonymous" else host).setFocus()
    dlg.exec()
    return out.get("r")
