# -*- coding: utf-8 -*-
"""구글 드라이브 백업 (GDRIVE_VER 1.0.0, 0.9.114 — 사용자 11/6 '포맷하면 설정·메모가 다 날아감, 구글 로그인으로 클라우드에')

- 저장 위치 = 그 사용자 자신의 구글 드라이브 안 '앱 전용 숨은 공간'(appDataFolder). 드라이브 파일 목록엔 안 보이고 4Dir 만 읽고 씀.
  개발자 서버·드라이브로는 아무것도 안 감. 권한 범위 drive.appdata(구글 분류: 민감하지 않음) + openid email(누구 계정인지 표시용).
- 로그인: 브라우저로 구글 로그인 → 이 PC 의 127.0.0.1 임시 주소로 돌아옴(PKCE). 받은 '다시 받기 열쇠'(refresh token)는
  윈도우 자격 증명 관리자(4Dir/GoogleDrive)에 저장 — 설정 파일에 안 남김.
- 앱 등록 정보(client_id·client_secret)는 bin\\gdrive_client.json. 데스크톱 앱 값은 구글 문서상 비밀이 아님(설치형 앱은 숨길 수 없음).
  파일이 없으면 기능은 '준비 안 됨'.
- 백업 = backup.export_zip 과 같은 zip (설정·창·즐겨찾기·라벨·태그·메모) → 이름 4Dir_backup_<시각>_<PC>.zip, 최근 KEEP 개만 남김.
- 모든 통신은 뒤 스레드에서 부를 것 (이 모듈은 막히는 함수만 제공). 주소들은 시험용으로 바꿀 수 있음(ENDPOINTS).
로그: bin\\log\\4Dir.log [QE.gdrive] — 열쇠·토큰 값은 기록하지 않음
"""
import os
import re
import json
import time
import uuid
import base64
import socket
import hashlib
import logging
import secrets
import threading
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

GDRIVE_VER = "1.1.0"   # 1.1.0 (0.9.115): 드라이브 권한 빠진 로그인 알아채기
log = logging.getLogger("QE.gdrive")
SCOPES = "https://www.googleapis.com/auth/drive.appdata openid email"
ENDPOINTS = {
    "auth": "https://accounts.google.com/o/oauth2/v2/auth",
    "token": "https://oauth2.googleapis.com/token",
    "revoke": "https://oauth2.googleapis.com/revoke",
    "api": "https://www.googleapis.com/drive/v3",
    "upload": "https://www.googleapis.com/upload/drive/v3",
}
CRED_TARGET = "4Dir/GoogleDrive"
KEEP = 10
TIMEOUT = 60
_TOK = {"access": None, "exp": 0.0}
_LOCK = threading.Lock()


class GDriveError(Exception):
    pass


DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.appdata"
NO_DRIVE = "no_drive_permission"   # 0.9.115: 구글 로그인 화면에서 드라이브 권한 체크를 끄고 넘어감 (11/7 실제 발생 — 받은 권한 email openid 만)


# ---------------------------------------------------------------- 앱 등록 정보·열쇠 보관
def client(bin_dir):
    """(client_id, client_secret) 또는 None — bin\\gdrive_client.json"""
    p = os.path.join(bin_dir, "gdrive_client.json")
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        d = d.get("installed", d)   # 구글 콘솔에서 받은 json 그대로 넣어도 됨
        if d.get("client_id"):
            return d["client_id"], d.get("client_secret", "")
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("gdrive_client.json 읽기 실패")
    return None


def _cred_read():
    try:
        import win32cred
        c = win32cred.CredRead(CRED_TARGET, win32cred.CRED_TYPE_GENERIC)
        blob = c["CredentialBlob"]
        raw = blob.decode("utf-16-le") if isinstance(blob, bytes) else blob
        return json.loads(raw)
    except Exception:
        return None


def _cred_write(d):
    import win32cred
    win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC, "TargetName": CRED_TARGET, "UserName": d.get("email", ""),
                         "CredentialBlob": json.dumps(d), "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)


def _cred_delete():
    try:
        import win32cred
        win32cred.CredDelete(CRED_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception:
        pass


def account():
    """연결된 구글 계정 이메일 (없으면 '')"""
    d = _cred_read()
    return (d or {}).get("email", "") if d and d.get("refresh") else ""


# ---------------------------------------------------------------- 통신
def _req(method, url, data=None, headers=None, raw=False, timeout=TIMEOUT):
    req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}, **{"User-Agent": "4Dir"}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return body if raw else (json.loads(body.decode("utf-8")) if body else {})
    except urllib.error.HTTPError as ex:
        msg = ex.read().decode("utf-8", "replace")[:400]
        log.warning("구글 응답 오류 %s %s → %s %s", method, url.split("?")[0], ex.code, msg)
        if ex.code == 403 and ("insufficientPermissions" in msg or "insufficient authentication scopes" in msg):
            raise GDriveError(NO_DRIVE)
        raise GDriveError(f"HTTP {ex.code}: {msg}")
    except (urllib.error.URLError, socket.timeout, OSError) as ex:
        log.warning("구글 연결 실패 %s %s : %s", method, url.split("?")[0], ex)
        raise GDriveError(str(ex))


def _form(url, fields):
    return _req("POST", url, urllib.parse.urlencode(fields).encode(), {"Content-Type": "application/x-www-form-urlencoded"})


def _email_from_id_token(tok):
    try:
        part = tok.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part)).get("email", "")
    except Exception:
        return ""


class _Catch(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self.server.result = {k: v[0] for k, v in q.items()}
        ok = "code" in self.server.result
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = self.server.done_html if ok else self.server.fail_html
        self.wfile.write(msg.encode("utf-8"))

    def log_message(self, *a):
        pass


def login(bin_dir, opener=None, wait=300, done_html="<h2>4Dir: OK</h2>", fail_html="<h2>4Dir: failed</h2>", stop=None):
    """브라우저로 구글 로그인 → 이메일. opener(url) = 브라우저 여는 함수(시험용). stop = threading.Event (취소)"""
    c = client(bin_dir)
    if not c:
        raise GDriveError("no client")
    cid, csec = c
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    srv = HTTPServer(("127.0.0.1", 0), _Catch)
    srv.result, srv.done_html, srv.fail_html = None, done_html, fail_html
    srv.timeout = 1
    redirect = f"http://127.0.0.1:{srv.server_address[1]}/"
    url = ENDPOINTS["auth"] + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "access_type": "offline", "prompt": "consent"})
    log.info("구글 로그인 시작 (돌아올 주소 %s)", redirect)
    (opener or webbrowser.open)(url)
    t0 = time.time()
    try:
        while srv.result is None and time.time() - t0 < wait and not (stop and stop.is_set()):
            srv.handle_request()
    finally:
        srv.server_close()
    r = srv.result
    if r is None:
        log.info("구글 로그인: 응답 없음 (취소 또는 %d초 지남)", wait)
        raise GDriveError("timeout")
    if r.get("state") != state or "code" not in r:
        log.warning("구글 로그인 거절/상태 불일치: %s", {k: v for k, v in r.items() if k != "code"})
        raise GDriveError(r.get("error", "denied"))
    tok = _form(ENDPOINTS["token"], {"client_id": cid, "client_secret": csec, "code": r["code"], "code_verifier": verifier,
                                     "grant_type": "authorization_code", "redirect_uri": redirect})
    if not tok.get("refresh_token"):
        raise GDriveError("no refresh token")
    granted = tok.get("scope")
    log.info("구글 로그인 받은 권한: %s", granted)
    if granted is not None and DRIVE_SCOPE not in granted.split():
        log.warning("구글 로그인: 드라이브 권한 없이 넘어옴 → 허가 취소, 저장 안 함")
        try:
            _form(ENDPOINTS["revoke"], {"token": tok["refresh_token"]})
        except GDriveError:
            pass
        raise GDriveError(NO_DRIVE)
    email = _email_from_id_token(tok.get("id_token", ""))
    _cred_write({"refresh": tok["refresh_token"], "email": email})
    with _LOCK:
        _TOK["access"], _TOK["exp"] = tok.get("access_token"), time.time() + int(tok.get("expires_in", 3600)) - 60
    log.info("구글 로그인 완료: %s", email or "(이메일 모름)")
    return email


def logout(bin_dir):
    """연결 끊기: 구글 쪽 허가 취소(되면) + 이 PC 열쇠 지움"""
    d = _cred_read()
    if d and d.get("refresh"):
        try:
            _form(ENDPOINTS["revoke"], {"token": d["refresh"]})
        except GDriveError:
            log.warning("구글 허가 취소 실패 (이 PC 열쇠는 지움)")
    _cred_delete()
    with _LOCK:
        _TOK["access"], _TOK["exp"] = None, 0.0
    log.info("구글 드라이브 연결 끊음")


def _access(bin_dir):
    with _LOCK:
        if _TOK["access"] and time.time() < _TOK["exp"]:
            return _TOK["access"]
    d = _cred_read()
    c = client(bin_dir)
    if not d or not d.get("refresh") or not c:
        raise GDriveError("not connected")
    tok = _form(ENDPOINTS["token"], {"client_id": c[0], "client_secret": c[1], "refresh_token": d["refresh"], "grant_type": "refresh_token"})
    with _LOCK:
        _TOK["access"], _TOK["exp"] = tok["access_token"], time.time() + int(tok.get("expires_in", 3600)) - 60
        return _TOK["access"]


def _auth(bin_dir):
    return {"Authorization": "Bearer " + _access(bin_dir)}


# ---------------------------------------------------------------- 백업 파일
def list_backups(bin_dir):
    """[{id, name, size, createdTime}] 새것부터"""
    q = urllib.parse.urlencode({"spaces": "appDataFolder", "fields": "files(id,name,size,createdTime)",
                                "orderBy": "createdTime desc", "pageSize": 100, "q": "name contains '4Dir_backup_'"})
    r = _req("GET", ENDPOINTS["api"] + "/files?" + q, headers=_auth(bin_dir))
    return r.get("files", [])


def upload(bin_dir, path, name):
    """zip 올리기 → 파일 id"""
    with open(path, "rb") as f:
        data = f.read()
    b = "4dir" + uuid.uuid4().hex
    meta = json.dumps({"name": name, "parents": ["appDataFolder"]}).encode()
    body = (f"--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta +
            f"\r\n--{b}\r\nContent-Type: application/zip\r\n\r\n".encode() + data + f"\r\n--{b}--\r\n".encode())
    r = _req("POST", ENDPOINTS["upload"] + "/files?uploadType=multipart&fields=id,name,size",
             body, dict(_auth(bin_dir), **{"Content-Type": f"multipart/related; boundary={b}"}), timeout=300)
    log.info("구글 드라이브에 올림 %s (%d바이트) id=%s", name, len(data), r.get("id"))
    return r.get("id")


def download(bin_dir, fid, dest):
    data = _req("GET", ENDPOINTS["api"] + f"/files/{urllib.parse.quote(fid)}?alt=media", headers=_auth(bin_dir), raw=True, timeout=300)
    with open(dest, "wb") as f:
        f.write(data)
    log.info("구글 드라이브에서 받음 %s → %s (%d바이트)", fid, dest, len(data))
    return dest


def delete(bin_dir, fid):
    _req("DELETE", ENDPOINTS["api"] + f"/files/{urllib.parse.quote(fid)}", headers=_auth(bin_dir), raw=True)


def prune(bin_dir, keep=KEEP):
    """오래된 백업 지움 (최근 keep 개 남김) → 지운 수"""
    fs = list_backups(bin_dir)
    n = 0
    for f in fs[keep:]:
        try:
            delete(bin_dir, f["id"])
            n += 1
        except GDriveError:
            log.warning("오래된 백업 지우기 실패 %s", f.get("name"))
    if n:
        log.info("오래된 구글 드라이브 백업 %d개 지움 (남김 %d)", n, keep)
    return n


def backup_name(pc=None):
    pc = re.sub(r"[^A-Za-z0-9_-]", "", pc if pc is not None else os.environ.get("COMPUTERNAME", "PC"))[:24] or "PC"
    return time.strftime("4Dir_backup_%Y%m%d_%H%M%S_") + pc + ".zip"


def backup_now(bin_dir, version, tmp_dir=None, data_dir=None):
    """설정 zip 만들어 올리고 오래된 것 정리 → (이름, 크기)"""
    import tempfile
    import backup
    name = backup_name()
    tmp = os.path.join(tmp_dir or tempfile.gettempdir(), name)
    try:
        backup.export_zip(data_dir or bin_dir, tmp, version)   # 0.9.114 빌드 2: 설정은 DATA_DIR (스토어판)
        size = os.path.getsize(tmp)
        upload(bin_dir, tmp, name)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    prune(bin_dir)
    return name, size
