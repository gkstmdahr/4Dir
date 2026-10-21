# -*- coding: utf-8 -*-
"""4Dir 공개 저장소 폴더 만들기 (MAKE_PUBLIC_VER 1.0.4)

python make_public.py   → 4Dir\\_public\\  (깃허브에 올릴 내용 그대로. .git 폴더는 남기고 나머지를 새로 채움)
- 올리는 것: 4Dir.vbs, bin 의 소스(.py)·언어·사용법 그림·아이콘, _build 의 만들기 스크립트, docs\\ (사이트), LICENSE, README
- 안 올리는 것: 개인 데이터(즐겨찾기·설정·상태·세션·색인·로그), _dev(시험·번역 작업), _maxtest, 인계 문서,
  _build\\corp_words.txt(회사 글자 목록), 캐시, 배포판
- 마지막에 회사·개인 글자 검사(UTF-8 / UTF-16 / CP949). 1건이라도 있으면 실패로 끝냄(올리지 말 것).
- 올리기(git push)는 하지 않음 — 사람이 확인 후.
로그: _build\\make_public_log.txt
"""
import os
import re
import sys
import time
import shutil
import subprocess

MAKE_PUBLIC_VER = "1.0.4"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
OUT = os.path.join(ROOT, "_public")
LOGF = os.path.join(HERE, "make_public_log.txt")
sys.path.insert(0, HERE)

BIN_SKIP_DIRS = {"__pycache__", "log", "sessions", "workspaces", "index"}
BIN_SKIP_FILES = re.compile(r"(4Dir_(state|favorites|settings).*|.*\.running|.*\.tmp|.*백업.*)$", re.I)
BUILD_FILES = ["make_release.py", "make_release.bat", "make_guide.py", "make_shots.py", "make_site.py", "site_text.py", "changelog.py",
               "make_public.py"]
_logf = open(LOGF, "w", encoding="utf-8")


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    _logf.write(line + "\n")
    _logf.flush()


def app_version():
    s = open(os.path.join(BIN, "main.py"), encoding="utf-8").read()
    return re.search(r'QE_VERSION = "([^"]+)"', s).group(1)


GITIGNORE = """# 개인 데이터 / personal data (never commit)
bin/4Dir_*.json
bin/*.running
bin/log/
bin/sessions/
bin/workspaces/
bin/index/
reports/
__pycache__/
*.pyc
# build outputs
runtime/
_release/
_build/cache/
_build/*_log.txt
_build/corp_words.txt
_site/out/
"""

ISSUE_TEMPLATE = """name: Problem report
description: Something does not work in 4Dir
labels: [bug]
body:
  - type: markdown
    attributes:
      value: |
        Thanks! In 4Dir use **Tools → Save log for problem report** and attach the zip below.
        No GitHub account? Email the zip to **support@4dir.net** instead.
  - type: input
    id: version
    attributes:
      label: 4Dir version
      description: Shown at the top right of the window (e.g. v0.9.61)
    validations:
      required: true
  - type: input
    id: windows
    attributes:
      label: Windows version
      placeholder: Windows 11 23H2
  - type: textarea
    id: what
    attributes:
      label: What happened?
      description: What you did, what you expected, what happened instead
    validations:
      required: true
  - type: textarea
    id: log
    attributes:
      label: Problem-report zip
      description: Drag the zip from the 4Dir 'reports' folder here
"""

ISSUE_CONFIG = """blank_issues_enabled: true
contact_links:
  - name: Email (no GitHub account needed)
    url: mailto:support@4dir.net
    about: Send the problem-report zip to support@4dir.net
"""

README_EN = """# 4Dir

**Multi-pane tabbed file manager for Windows — free, portable, light on your PC.**

[Website & download]({site}) · [Releases]({repo}/releases) · [한국어](README.ko.md)

> **Download the release zip from [Releases]({repo}/releases/latest)** (`4Dir_v….zip`).
> The green **Code → Download ZIP** button gives source code only — it won't run without Python 3.12+ and PySide6.

![4Dir](docs/img/en_1.png)

- **Up to 20 panes** — 1/2/3/4/6 pane layouts with one click, or any grid up to 5 × 4. Tabs in every pane.
- **Stays out of the way** — reads folders directly (no Windows shell view), no timers or polling when idle. Safe next to 3ds Max, games and other heavy apps.
- **Instant search** — its own file-name index with real-time updates, no admin rights.
- **SVN status** — badges read straight from `.svn`; Git / Perforce through Windows overlays.
- **Feels like Explorer** — same shortcuts, full Windows context menu, drag & drop.
- **Portable** — settings stay in the folder. Light/dark theme, 10 languages.

## Install

1. Download the zip from [Releases]({repo}/releases).
2. Right-click the zip → Properties → **Unblock** → OK.
3. Extract anywhere and run **4Dir.vbs**.

The release zip contains the official python.org embeddable Python, PySide6 (Qt, LGPL-3.0) and pywin32 — nothing to install.

## Run from source

Python 3.13 + `pip install PySide6 pywin32`, then run `4Dir.vbs` (uses `pythonw` on PATH) or `pythonw bin/main.py`.
Build a release: `python _build/make_release.py` (needs your own `_build/corp_words.txt`, one forbidden word per line).

## Problems / feedback

In 4Dir: **Tools → Save log for problem report → Send by email**, or email the zip to **support@4dir.net**. GitHub users can also open an [issue]({repo}/issues/new/choose).

## Support

4Dir is free and has no ads. If it saves you time, you can support development on the [website]({site}#donate).

## License

GPL-3.0 — see [LICENSE](LICENSE). The name "4Dir" and its icon identify the original project; please use a different name for forks.
"""

README_KO = """# 4Dir

**윈도우용 여러 칸 분할 + 탭 파일 관리자 — 무료, 설치 없음, PC 를 무겁게 하지 않음.**

[사이트·받기]({site}ko/) · [배포판]({repo}/releases) · [English](README.md)

> **[배포판(Releases)]({repo}/releases/latest) 에서 zip 을 받으세요** (`4Dir_v….zip`).
> 초록색 **Code → Download ZIP** 은 소스 코드만 들어 있어서, 파이썬 3.12 이상과 PySide6 가 없으면 실행되지 않습니다.

![4Dir](docs/img/ko_1.png)

- **최대 20칸** — 1·2·3·4·6칸 버튼 하나로, 또는 가로 5 × 세로 4 까지. 칸마다 탭.
- **PC 를 무겁게 하지 않음** — 윈도우 셸 화면 없이 폴더를 직접 읽고, 쉴 때는 타이머·폴링 없음. 3ds Max·게임 옆에 켜 둬도 안전.
- **바로 찾는 검색** — 자체 파일 이름 색인, 실시간 갱신, 관리자 권한 필요 없음.
- **SVN 상태** — `.svn` 을 직접 읽어 표시. Git·Perforce 는 윈도우 겹침 아이콘.
- **탐색기와 같은 손맛** — 같은 단축키, 윈도우 우클릭 메뉴, 끌어다 놓기.
- **휴대용** — 설정은 폴더 안에만. 밝게/어둡게, 10개 언어.

## 설치

1. [배포판]({repo}/releases)에서 zip 을 받습니다.
2. zip 우클릭 → 속성 → **차단 해제** → 확인.
3. 아무 곳에나 풀고 **4Dir.vbs** 실행.

## 문제 보고·의견

4Dir 에서 **도구 → 문제 보고용 로그 저장 → 메일로 보내기**, 또는 zip 을 **support@4dir.net** 으로 보내 주세요. 깃허브 사용자는 [문제 보고(Issue)]({repo}/issues/new/choose)도 됩니다.

## 후원

4Dir 는 무료이고 광고가 없습니다. 도움이 됐다면 [사이트]({site}ko/#donate)에서 후원할 수 있습니다.

## 라이선스

GPL-3.0 — [LICENSE](LICENSE). "4Dir" 이름과 아이콘은 원작 프로젝트 표시이므로, 고쳐서 따로 배포할 때는 다른 이름을 써 주세요.
"""


def scan(out):
    """회사·개인 글자 검사. 목록 = corp_words.txt (비공개)"""
    cw = os.path.join(HERE, "corp_words.txt")
    if not os.path.exists(cw):
        raise SystemExit("corp_words.txt 없음 — 검사 없이 공개하지 않음")
    words = [w.strip() for w in open(cw, encoding="utf-8").read().splitlines() if w.strip()]   # 이 PC 경로도 이 파일에
    hits = []
    for a, ds, fs in os.walk(out):
        if ".git" in ds:
            ds.remove(".git")
        for f in fs:
            p = os.path.join(a, f)
            data = (f + "\n").encode("utf-8").lower() + open(p, "rb").read().lower()
            for w in words:
                for enc in ("utf-8", "utf-16-le", "cp949"):
                    try:
                        b = w.lower().encode(enc)
                    except UnicodeEncodeError:
                        continue
                    if b in data:
                        hits.append(f"{os.path.relpath(p, out)}: {w} ({enc})")
                        break
    return hits


def main():
    ver = app_version()
    import site_text  # noqa: F401  (문법 확인)
    import json
    cfg = {"owner": "", "repo": "4Dir"}
    if os.path.exists(os.path.join(HERE, "site_config.json")):
        cfg.update(json.load(open(os.path.join(HERE, "site_config.json"), encoding="utf-8")))
    owner = cfg["owner"] or "OWNER"
    repo = f"https://github.com/{owner}/{cfg['repo']}"
    from make_site import site_base
    site = site_base(cfg)
    log(f"공개 저장소 만들기 v{MAKE_PUBLIC_VER} — 4Dir v{ver} → {OUT}  계정={cfg['owner'] or '(아직 없음 → OWNER)'}")
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):   # .git 만 남기고 비움 (우리 결과물 폴더)
        if f == ".git":
            continue
        p = os.path.join(OUT, f)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)

    shutil.copy2(os.path.join(ROOT, "4Dir.vbs"), os.path.join(OUT, "4Dir.vbs"))
    nb = 0
    for a, ds, fs in os.walk(BIN):
        ds[:] = [d for d in ds if d not in BIN_SKIP_DIRS]
        for f in fs:
            if BIN_SKIP_FILES.match(f) or f.endswith(".pyc"):
                continue
            rel = os.path.relpath(os.path.join(a, f), BIN)
            dst = os.path.join(OUT, "bin", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(a, f), dst)
            nb += 1
    log(f"bin {nb}개 복사 (개인 데이터 제외)")
    os.makedirs(os.path.join(OUT, "_build"))
    for f in BUILD_FILES:
        if os.path.exists(os.path.join(HERE, f)):
            shutil.copy2(os.path.join(HERE, f), os.path.join(OUT, "_build", f))
    log(f"_build {len(os.listdir(os.path.join(OUT, '_build')))}개 복사 (corp_words.txt 제외)")

    r = subprocess.run([sys.executable, "-u", "-X", "utf8", os.path.join(HERE, "make_site.py"), os.path.join(OUT, "docs")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    log("사이트: " + (r.stdout.strip().splitlines() or ["(출력 없음)"])[-1])
    if r.returncode:
        log(r.stderr[-2000:])
        raise SystemExit("사이트 만들기 실패")

    shutil.copy2(os.path.join(HERE, "cache", "GPL-3.0.txt"), os.path.join(OUT, "LICENSE"))
    open(os.path.join(OUT, ".gitignore"), "w", encoding="utf-8", newline="\n").write(GITIGNORE)
    open(os.path.join(OUT, "README.md"), "w", encoding="utf-8", newline="\n").write(README_EN.format(site=site, repo=repo))
    open(os.path.join(OUT, "README.ko.md"), "w", encoding="utf-8", newline="\n").write(README_KO.format(site=site, repo=repo))
    # 깃허브 문제 보고 양식 (1.0.3) — 버전·증상·로그 zip 칸 + 깃허브 계정 없으면 메일 안내
    tdir = os.path.join(OUT, ".github", "ISSUE_TEMPLATE")
    os.makedirs(tdir, exist_ok=True)
    open(os.path.join(tdir, "bug_report.yml"), "w", encoding="utf-8", newline="\n").write(ISSUE_TEMPLATE)
    open(os.path.join(tdir, "config.yml"), "w", encoding="utf-8", newline="\n").write(ISSUE_CONFIG)

    hits = scan(OUT)
    n = sum(len(fs) for a, _, fs in os.walk(OUT) if ".git" not in a.split(os.sep))
    log(f"회사·개인 글자 검사: {len(hits)}건 {hits}")
    log(f"완료: 파일 {n}개 → {OUT}")
    if hits:
        raise SystemExit("회사·개인 글자가 있음 — 올리지 말 것 (로그 확인)")


if __name__ == "__main__":
    main()
