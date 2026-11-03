# -*- coding: utf-8 -*-
"""winget(마이크로소프트 설치 목록) 등록 파일 만들기 (MAKE_WINGET_VER 1.0.0)

결과: <4Dir>\\_release\\winget\\<버전>\\gkstmdahr.4Dir.yaml / .installer.yaml / .locale.en-US.yaml
- 버전 = bin\\main.py 의 QE_VERSION, zip 지문 = _release\\4Dir_v<버전>.zip.sha256.txt (깃허브 릴리스에 올린 것과 같은 파일이어야 함)
- 방식: zip 안의 4Dir_v<버전>\\4Dir.exe 를 휴대용(portable)으로 — winget 이 다른 폴더(Links)에 링크를 만들어 실행
  → 실행기 1.1.0 부터 링크를 따라가 진짜 폴더를 찾음 (1.0.0 은 '프로그램 파일을 찾을 수 없음', 11/3 재현)
- 올리기: microsoft/winget-pkgs 의 manifests\\g\\gkstmdahr\\4Dir\\<버전>\\ 에 세 파일을 넣어 PR (사용자 확인 후)
로그: _build\\make_winget_log.txt
"""
import os
import re
import sys
import time

MAKE_WINGET_VER = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = "gkstmdahr.4Dir"
LOG = os.path.join(HERE, "make_winget_log.txt")
_logf = None


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line)
    _logf.write(line + "\n")
    _logf.flush()


def main():
    global _logf
    _logf = open(LOG, "w", encoding="utf-8")
    src = open(os.path.join(ROOT, "bin", "main.py"), encoding="utf-8").read()
    ver = re.search(r'QE_VERSION = "([^"]+)"', src).group(1)
    log(f"make_winget {MAKE_WINGET_VER}: 4Dir {ver}")
    shaf = os.path.join(ROOT, "_release", f"4Dir_v{ver}.zip.sha256.txt")
    if not os.path.exists(shaf):
        raise SystemExit(f"지문 파일 없음 {shaf} — make_release.py 먼저")
    sha = open(shaf, encoding="utf-8").read().split()[0].upper()
    if not re.fullmatch(r"[0-9A-F]{64}", sha):
        raise SystemExit(f"지문 모양이 이상함: {sha}")
    log(f"zip 지문 {sha}")
    out = os.path.join(ROOT, "_release", "winget", ver)
    os.makedirs(out, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    url = f"https://github.com/gkstmdahr/4Dir/releases/download/v{ver}/4Dir_v{ver}.zip"
    files = {
        f"{PKG}.yaml": f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.version.1.10.0.schema.json

PackageIdentifier: {PKG}
PackageVersion: {ver}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.10.0
""",
        f"{PKG}.installer.yaml": f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.1.10.0.schema.json

PackageIdentifier: {PKG}
PackageVersion: {ver}
InstallerType: zip
NestedInstallerType: portable
NestedInstallerFiles:
- RelativeFilePath: 4Dir_v{ver}\\4Dir.exe
  PortableCommandAlias: 4dir
ReleaseDate: {today}
Installers:
- Architecture: x64
  InstallerUrl: {url}
  InstallerSha256: {sha}
ManifestType: installer
ManifestVersion: 1.10.0
""",
        f"{PKG}.locale.en-US.yaml": f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.defaultLocale.1.10.0.schema.json

PackageIdentifier: {PKG}
PackageVersion: {ver}
PackageLocale: en-US
Publisher: gkstmdahr
PublisherUrl: https://github.com/gkstmdahr
PublisherSupportUrl: https://github.com/gkstmdahr/4Dir/discussions
Author: gkstmdahr
PackageName: 4Dir
PackageUrl: https://4dir.net/
License: GPL-3.0
LicenseUrl: https://github.com/gkstmdahr/4Dir/blob/main/LICENSE
ShortDescription: Portable multi-pane file manager with up to 20 panes and tabs in every pane
Description: 4Dir splits one window into up to 20 panes, each with its own tabs. It has instant file-name search with its own index, thumbnails and preview for images, PSD and 3ds Max files, the real Windows right-click menu, batch rename and ZIP/7z/TAR compression. Free, open source, no ads, no account.
Tags:
- file-manager
- file-explorer
- multi-pane
- tabs
- portable
- open-source
ReleaseNotesUrl: https://github.com/gkstmdahr/4Dir/releases/tag/v{ver}
ManifestType: defaultLocale
ManifestVersion: 1.10.0
""",
    }
    for name, body in files.items():
        with open(os.path.join(out, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        log(f"  {name} ({len(body)} 글자)")
    log(f"완료 → {out}  (PR 경로: manifests/g/gkstmdahr/4Dir/{ver}/)")


if __name__ == "__main__":
    main()
