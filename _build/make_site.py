# -*- coding: utf-8 -*-
"""4Dir 공개 사이트 만들기 (MAKE_SITE_VER 1.9.0 — 코드 서명 페이지 = 서명 없음)

python make_site.py [출력 폴더]   (기본: 4Dir\\_site\\out)
- 문구: site_text.py (10개 언어), 버전별 바뀐 점: changelog.py (1.2.0 — 메인 '바뀐 점' + versions.html 지난 버전 받기), 설정: site_config.json (깃허브 계정·후원 주소)
- 버전·크기·지문: _release 의 최신 4Dir_v*.zip + .sha256.txt
- 결과: index.html(영어) + <언어>\\index.html, style.css, img\\, icon.png, version.json(앱 새 버전 알림),
        robots.txt, sitemap.xml, .nojekyll  → 깃허브 무료 페이지(docs 폴더)에 그대로 올림
- 1.3.0: _site\apps\<이름>\ 의 다른 앱 페이지를 /<이름>/ 로 복사(just-downloader)
- 1.9.0: code-signing.html 을 '서명 없음'으로 (SignPath Foundation 거절 10/31, 유료는 법인만 — 사용자 11/3 "서명 없음으로 고쳐"). SignPath 문구·서명 승인 역할 삭제, 빌드 방식·SHA256 확인·개인 정보는 유지
- 1.8.0: 머리줄에 💬 게시판 버튼(10개 언어) → 깃허브 토론 게시판 github.com/gkstmdahr/4Dir/discussions (사용자 10/30)
- 1.7.0: code-signing.html (영어 한 장: 서명 정책·역할·개인 정보 — SignPath 신청 조건) + 모든 페이지 바닥글에 링크
- 1.5.5: 순서 바꿈 — just downloader 는 로고 바로 옆(왼쪽 정렬), 사용법은 오른쪽 언어 선택 옆 (사용자 지시)
- 1.5.4: 폰 폭에서 머리줄이 넘쳐 가로 스크롤 생김 → 두 줄로 내려가게, 언어 글자 숨김(선택 상자만)
- 1.5.3: 위쪽 머리줄 사용법 버튼 옆에 just downloader 버튼(같은 언어의 /just-downloader/<언어>/ 로) — 메인·사용법·지난 버전 페이지 모두
- 1.4.0: 사용법 페이지 <언어>/guide.html (문구 guide_text.py, 그림 bin/guide/<앱언어>/p1..p6.png → img/guide/<앱언어>/). 문구 없는 언어는 페이지·링크 없음
- 바깥 글꼴·광고 없음. 방문 통계만 클라우드플레어 웹 분석(쿠키 없음, 개인 정보 안 남김 — site_config 의 cf_beacon, 1.6.0 10/29 사용자 요청: 광고 판단용 접속량).
로그: _build\\make_site_log.txt
"""
import os
import re
import sys
import json
import time
import html
import shutil

MAKE_SITE_VER = "1.11.0"   # 1.11.0: 개인정보처리방침 privacy.html (구글 드라이브 백업 — 구글 앱 등록에 필요) / 1.10.0: 1.10.0: 받기를 누르면 다운로드는 바로 시작 + 후원 안내 창(막지 않음, 닫기 가능 — 사용자 11/6 PureRef 처럼) / 1.9.3: 1.9.3: support 메일 링크에 제목 말머리 [4Dir] / 1.9.2: 후원 칸 통째로 받기 바로 밑(작은 버튼 뺌), Ko-fi 버튼 글자 = ♥ 4Dir 후원하기 / 1.9.1: 받기 버튼 밑 작은 후원 버튼
SUPPORT = "support@4dir.net"   # 문제 보고 메일 (1.1.1)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SITE_SRC = os.path.join(ROOT, "_site")
REL = os.path.join(ROOT, "_release")
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(SITE_SRC, "out")
LOGF = os.path.join(HERE, "make_site_log.txt")
sys.path.insert(0, HERE)
import site_text as ST  # noqa: E402
import changelog as CL  # noqa: E402
import guide_text as GT  # noqa: E402   (1.4.0)

_logf = open(LOGF, "w", encoding="utf-8")


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    _logf.write(line + "\n")
    _logf.flush()


def site_base(cfg):
    """사이트 주소: 개인 도메인(cfg domain)이 있으면 그것, 없으면 깃허브 무료 페이지 주소 (1.1.0)"""
    if cfg.get("domain"):
        return f"https://{cfg['domain']}/"
    return f"https://{(cfg['owner'] or 'OWNER').lower()}.github.io/{cfg['repo']}/"


def load_config():
    p = os.path.join(HERE, "site_config.json")
    cfg = {"owner": "", "repo": "4Dir", "kofi": "", "sponsors": False}
    if os.path.exists(p):
        cfg.update(json.load(open(p, encoding="utf-8")))
    return cfg


def latest_release():
    vkey = lambda v: tuple(int(x) for x in v.split("."))
    vers = [m.group(1) for f in os.listdir(REL) for m in [re.match(r"^4Dir_v(\d+\.\d+\.\d+)\.zip$", f)] if m]
    if not vers:
        raise SystemExit("_release 에 배포판 zip 이 없음 — make_release 먼저")
    ver = max(vers, key=vkey)
    z = os.path.join(REL, f"4Dir_v{ver}.zip")
    sha = open(z + ".sha256.txt", encoding="utf-8-sig").read().split()[0].lower()
    return ver, z, os.path.getsize(z), sha, time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(z)))


THX = {   # 1.10.0 받기 뒤 후원 안내 (제목, 본문, 나중에)
    "en": ("Your download has started", "4Dir is free and always will be. If it helps you, a small donation keeps the updates coming.", "Maybe later"),
    "ko": ("다운로드가 시작됐습니다", "4Dir 는 앞으로도 무료입니다. 도움이 됐다면 작은 후원이 다음 업데이트의 힘이 됩니다.", "다음에 할게요"),
    "zh-CN": ("下载已开始", "4Dir 永久免费。如果它对你有帮助，一点小小的捐助能让更新持续下去。", "以后再说"),
    "zh-TW": ("下載已開始", "4Dir 永久免費。如果它對你有幫助，一點小小的贊助能讓更新持續下去。", "下次再說"),
    "ja": ("ダウンロードを開始しました", "4Dir はこれからも無料です。役に立ったなら、少額の寄付が次のアップデートの力になります。", "また今度"),
    "es": ("La descarga ha comenzado", "4Dir es y seguirá siendo gratis. Si te resulta útil, una pequeña donación mantiene las actualizaciones.", "Quizá luego"),
    "de": ("Der Download hat begonnen", "4Dir ist und bleibt kostenlos. Wenn es dir hilft, hält eine kleine Spende die Updates am Laufen.", "Vielleicht später"),
    "fr": ("Le téléchargement a commencé", "4Dir est et restera gratuit. S'il vous aide, un petit don permet de continuer les mises à jour.", "Plus tard"),
    "pt-BR": ("O download começou", "O 4Dir é e continuará gratuito. Se ele ajuda você, uma pequena doação mantém as atualizações.", "Talvez depois"),
    "ru": ("Загрузка началась", "4Dir бесплатен и останется таким. Если он вам помогает, небольшое пожертвование поддержит обновления.", "Может, позже"),
}


def thx_box(lang, kofi_url, don_label):
    """받기 버튼을 누르면 뜨는 후원 안내 (다운로드는 링크 그대로 시작 — 막지 않음)"""
    if not kofi_url:
        return ""
    h, b, later = THX.get(lang, THX["en"])
    e = html.escape
    return (f'<div id="thx" class="thx" hidden role="dialog" aria-modal="true" aria-labelledby="thx-h"><div class="thx-in">'
            f'<button class="thx-x" type="button" aria-label="close" onclick="document.getElementById(\'thx\').hidden=true">✕</button>'
            f'<h2 id="thx-h">⬇ {e(h)}</h2><p>{e(b)}</p>'
            f'<p><a class="btn don" href="{e(kofi_url)}" rel="noopener" target="_blank">♥ {e(don_label)}</a> '
            f'<button class="btn line sm" type="button" onclick="document.getElementById(\'thx\').hidden=true">{e(later)}</button></p>'
            '</div></div>'
            "<script>(function(){var b=document.getElementById('dl'),t=document.getElementById('thx');if(!b||!t)return;"
            "b.addEventListener('click',function(){setTimeout(function(){t.hidden=false},300)});"
            "t.addEventListener('click',function(ev){if(ev.target===t)t.hidden=true});"
            "document.addEventListener('keydown',function(ev){if(ev.key==='Escape')t.hidden=true})})();</script>")


def page(lang, cfg, rel):
    t = ST.T[lang]
    ver, zpath, zsize, sha, date = rel
    owner = cfg["owner"] or "OWNER"
    repo_url = f"https://github.com/{owner}/{cfg['repo']}"
    base = site_base(cfg)
    dl_url = f"{repo_url}/releases/download/v{ver}/{os.path.basename(zpath)}"
    up = "" if lang == "en" else "../"
    fmt = dict(ver=ver, size=f"{zsize / 1048576:.0f} MB", date=date)
    e = html.escape
    url_of = lambda lg: base + ("" if lg == "en" else lg + "/")
    alts = "\n".join(f'<link rel="alternate" hreflang="{lg}" href="{url_of(lg)}">' for lg in ST.LANGS)
    alts += f'\n<link rel="alternate" hreflang="x-default" href="{base}">'
    opts = "".join(f'<option value="{up}{"" if lg == "en" else lg + "/"}"{" selected" if lg == lang else ""}>{e(ST.NAMES[lg])}</option>'
                   for lg in ST.LANGS)
    feats = "".join(f'<div class="card"><h3>{e(h)}</h3><p>{e(p)}</p></div>' for h, p in t["feats"])
    how = "".join(f"<li>{s}</li>" for s in t["how"])          # <b> 허용 (문구는 우리가 씀)
    news = "".join(f"<li>{x}</li>" for x in CL.items(ver, lang))   # <b> 허용 (문구는 우리가 씀)
    faq = "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in t["faq"])
    img = ST.APP_LANG[lang]
    btns = []
    if cfg["kofi"]:
        btns.append(f'<a class="btn don" href="https://ko-fi.com/{e(cfg["kofi"])}" rel="noopener">♥ {e(t["don_h"])}</a>')   # 1.9.2 사용자 11/5: 'Ko-fi' 대신 위와 같은 이름
    if cfg["sponsors"]:
        btns.append(f'<a class="btn don" href="https://github.com/sponsors/{e(owner)}" rel="noopener">♥ GitHub Sponsors</a>')
    donate = (f'<section id="donate"><h2>{e(t["don_h"])}</h2><p>{e(t["don"])}</p><p class="btns">{"".join(btns)}</p></section>'
              if btns else "")
    redirect = ""
    if lang == "en":   # 맨 위 주소로 처음 온 사람만 브라우저 언어 페이지로 (직접 고른 언어는 기억)
        m = {lg.lower(): lg for lg in ST.LANGS if lg != "en"}
        redirect = ("<script>(function(){try{if(localStorage.getItem('4dir-lang'))return;"
                    f"var m={json.dumps(m)};var L=(navigator.languages||[navigator.language]);"
                    "for(var i=0;i<L.length;i++){var l=(L[i]||'').toLowerCase();if(l.indexOf('en')===0)return;"
                    "if(l==='zh-hk'||l==='zh-mo'||l.indexOf('zh-hant')===0)l='zh-tw';if(l.indexOf('zh')===0&&!m[l])l='zh-cn';"
                    "if(l.indexOf('pt')===0)l='pt-br';var k=m[l]||m[l.split('-')[0]];if(k){location.replace(k+'/');return;}}}catch(e){}})();</script>")
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(t["title"])}</title>
<meta name="description" content="{e(t["desc"])}">
<link rel="canonical" href="{url_of(lang)}">
{alts}
<meta property="og:title" content="{e(t["title"])}">
<meta property="og:description" content="{e(t["desc"])}">
<meta property="og:image" content="{base}img/{img}_1.png">
<meta property="og:type" content="website">
<link rel="icon" href="{up}icon.png">
<link rel="stylesheet" href="{up}style.css">
{redirect}
</head>
<body>
<header class="top"><div class="wrap">
<a class="logo" href="{up}"><img src="{up}icon.png" alt="" width="28" height="28">4Dir</a>
{app_nav(lang, up)}{guide_nav(lang)}{board_nav(lang)}<label class="lang">{e(t["lang"])} <select onchange="try{{localStorage.setItem('4dir-lang',1)}}catch(e){{}};location.href=this.value">{opts}</select></label>
</div></header>
<main class="wrap">
<section class="hero">
<h1>{e(t["tagline"])}</h1>
<p class="sub">{e(t["sub"])}</p>
<p><a id="dl" class="btn big" href="{dl_url}">⬇ {e(t["dl"].format(**fmt))}</a></p>
<p class="note">{e(t["dlnote"].format(**fmt))}</p>
{guide_hero(lang)}</section>
{donate}
{thx_box(lang, ("https://ko-fi.com/" + cfg["kofi"]) if cfg["kofi"] else "", t["don_h"])}
<section class="news"><h2>{e(t["new_h"].format(**fmt))}</h2><ul>{news}</ul><p><a href="versions.html">{e(t["hist_link"])} →</a></p></section>
<figure class="shot"><img src="{up}img/{img}_1.png" alt="{e(t["shot1"])}" width="1280" height="760"><figcaption>{e(t["shot1"])}</figcaption></figure>
<section><h2>{e(t["feat_h"])}</h2><div class="grid">{feats}</div></section>
<figure class="shot"><img src="{up}img/{img}_2.png" alt="{e(t["shot2"])}" width="1280" height="760" loading="lazy"><figcaption>{e(t["shot2"])}</figcaption></figure>
<section id="install"><h2>{e(t["how_h"])}</h2><ol>{how}</ol><p class="tip">{t["smart"]}</p>
<h3>{e(t["sha_h"])}</h3><p>{t["sha"].format(**fmt)}</p><p><code class="sha">{sha}</code></p></section>
<section id="faq"><h2>{e(t["faq_h"])}</h2>{faq}</section>
</main>
<footer><div class="wrap">
<a href="{repo_url}">{e(t["src"])}</a> · <a href="{repo_url}/issues">{e(t["issues"])}</a> · <a href="mailto:{SUPPORT}?subject=%5B4Dir%5D%20">{SUPPORT}</a> · <a href="{repo_url}/releases">v{ver}</a> · <a href="{up}code-signing.html">Code signing policy</a>
<p>{e(t["lic"])}</p>
</div></footer>
</body>
</html>
"""


def guide_nav(lang):
    """위쪽 줄 '사용법' 링크 (1.4.0) — 그 언어 사용법 문구가 있을 때만"""
    g = GT.GUIDE.get(lang)
    return f'<a class="nav" href="guide.html">{html.escape(g["link"])}</a>' if g else ""


BOARD_URL = "https://github.com/gkstmdahr/4Dir/discussions"   # 1.8.0: 깃허브 토론 게시판
BOARD = {"en": "Community", "ko": "게시판", "zh-CN": "社区", "zh-TW": "社群", "ja": "掲示板", "es": "Comunidad",
         "de": "Forum", "fr": "Communauté", "pt-BR": "Comunidade", "ru": "Форум"}


def board_nav(lang):
    """1.8.0: 위쪽 줄 '게시판' 버튼 — 사용법 옆, 깃허브 토론 게시판으로"""
    return f'<a class="nav board" href="{BOARD_URL}">💬 {html.escape(BOARD.get(lang, BOARD["en"]))}</a>'


def app_nav(lang, up, first=False):
    """1.5.3: 다른 앱 just downloader 버튼 — 같은 언어 페이지로. 1.5.5: 로고 옆 왼쪽(margin-right:auto 로 나머지를 오른쪽으로 밂), first 는 안 씀"""
    href = f"{up}just-downloader/" + ("" if lang == "en" else lang + "/")
    return f'<a class="nav app{" first" if first else ""}" href="{href}">📱 just downloader</a>'


def guide_hero(lang):
    g = GT.GUIDE.get(lang)
    return f'<p><a class="btn line" href="guide.html">📖 {html.escape(g["title"])} →</a></p>' if g else ""   # 1.4.3: 글자 링크 → 테두리 버튼 (작아서 안 보임)


def guide_page(lang, cfg, rel):
    """사용법 (1.4.0): 절마다 실제 화면 그림(빨간 번호) + 번호 설명 + 덧붙임"""
    g, t = GT.GUIDE[lang], ST.T[lang]
    e = html.escape
    repo_url = f"https://github.com/{cfg['owner'] or 'OWNER'}/{cfg['repo']}"
    base = site_base(cfg)
    up = "" if lang == "en" else "../"
    glangs = [lg for lg in ST.LANGS if lg in GT.GUIDE]
    url_of = lambda lg: base + ("" if lg == "en" else lg + "/") + "guide.html"
    alts = "\n".join(f'<link rel="alternate" hreflang="{lg}" href="{url_of(lg)}">' for lg in glangs)
    opts = "".join(f'<option value="{up}{"" if lg == "en" else lg + "/"}guide.html"{" selected" if lg == lang else ""}>{e(ST.NAMES[lg])}</option>'
                   for lg in glangs)
    img = guide_img_lang(lang)
    toc = "".join(f'<li><a href="#{s["id"]}">{e(s["h"])}</a></li>' for s in g["sections"]) + f'<li><a href="#etc">{e(g["etc_h"])}</a></li>'
    secs = []
    for s in g["sections"]:
        ps = "".join(f"<p>{x}</p>" for x in s.get("p", []))
        nums = "".join(f"<li>{x}</li>" for x in s.get("nums", []))   # <b>·<kbd> 허용 (문구는 우리가 씀)
        after = "".join(f"<p>{x}</p>" for x in s.get("after", []))
        secs.append(f'<section class="gs" id="{s["id"]}"><h2>{e(s["h"])}</h2>{ps}'
                    f'<figure class="shot"><img src="{up}img/guide/{img}/p{s["img"]}.png" alt="{e(s["h"])}" loading="lazy"></figure>'
                    f'<ol class="marks">{nums}</ol>{after}<p class="totop"><a href="#">{e(g["top"])} ↑</a></p></section>')
    etc = "".join(f"<li>{x}</li>" for x in g["etc"])
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(g["title"])} — 4Dir</title>
<meta name="description" content="{e(g["intro"][:150])}">
<link rel="canonical" href="{url_of(lang)}">
{alts}
<link rel="icon" href="{up}icon.png">
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<header class="top"><div class="wrap">
<a class="logo" href="./"><img src="{up}icon.png" alt="" width="28" height="28">4Dir</a>
{app_nav(lang, up, True)}{board_nav(lang)}<label class="lang">{e(t["lang"])} <select onchange="try{{localStorage.setItem('4dir-lang',1)}}catch(e){{}};location.href=this.value">{opts}</select></label>
</div></header>
<div class="gwrap">
<aside class="side"><nav><b>{e(g["toc"])}</b><ol>{toc}</ol></nav></aside>
<main class="guide">
<p><a href="./">{e(t["home"])}</a></p>
<h1>{e(g["title"])}</h1>
<p class="sub">{e(g["intro"])}</p>
<nav class="toc"><b>{e(g["toc"])}</b><ol>{toc}</ol></nav>
{"".join(secs)}
<section class="gs" id="etc"><h2>{e(g["etc_h"])}</h2><ul>{etc}</ul></section>
</main>
</div>
<script>(function(){{try{{var L=document.querySelectorAll('.side a'),m={{}};L.forEach(function(a){{m[a.getAttribute('href').slice(1)]=a}});
var io=new IntersectionObserver(function(es){{es.forEach(function(x){{if(x.isIntersecting){{L.forEach(function(a){{a.classList.remove('on')}});var a=m[x.target.id];a&&a.classList.add('on')}}}})}},{{rootMargin:'-20% 0px -70% 0px'}});
document.querySelectorAll('section.gs').forEach(function(s){{io.observe(s)}})}}catch(e){{}}}})();</script>
<footer><div class="wrap">
<a href="{repo_url}">{e(t["src"])}</a> · <a href="{repo_url}/issues">{e(t["issues"])}</a> · <a href="mailto:{SUPPORT}?subject=%5B4Dir%5D%20">{SUPPORT}</a> · <a href="{up}code-signing.html">Code signing policy</a>
<p>{e(t["lic"])}</p>
</div></footer>
</body>
</html>
"""


def signing_page(cfg):
    """코드 서명 정책 (1.7.0 SignPath 신청용 → 1.9.0 서명 없음: 빌드 방식·SHA256 확인·개인 정보)"""
    repo_url = f"https://github.com/{cfg['owner'] or 'OWNER'}/{cfg['repo']}"
    owner = cfg["owner"] or "OWNER"
    base = site_base(cfg)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>4Dir - Code signing policy</title>
<meta name="description" content="4Dir release files are not code-signed: how they are built, how to check them, and what data 4Dir sends.">
<link rel="canonical" href="{base}code-signing.html">
<link rel="icon" href="icon.png">
<link rel="stylesheet" href="style.css">
</head>
<body>
<header class="top"><div class="wrap">
<a class="logo" href="./"><img src="icon.png" alt="" width="28" height="28">4Dir</a>
</div></header>
<main class="wrap">
<p><a href="./">Home</a></p>
<section><h1>Code signing policy</h1>
<p class="tip">Status: release files are <b>not</b> code-signed. Windows may show a SmartScreen warning the first time you run 4Dir
(<b>More info &gt; Run anyway</b>). To make sure the file is genuine, check the SHA256 fingerprint shown on the download page and on
<a href="{repo_url}/releases">GitHub Releases</a>.</p>
<h2>How release files are built</h2>
<ul>
<li><code>4Dir.exe</code> — the small starter program in the release zip. It only starts the bundled Python with 4Dir's program files
(the same job as <code>4Dir.vbs</code>). Source: <a href="{repo_url}/blob/main/launcher/4Dir_launcher.cs">launcher/4Dir_launcher.cs</a>.</li>
<li>It is built by GitHub Actions directly from the public source code (<a href="{repo_url}/actions">build logs</a>,
workflow <a href="{repo_url}/blob/main/.github/workflows/build-exe.yml">build-exe.yml</a>).</li>
<li>The bundled Python runtime (<code>python.exe</code>, <code>pythonw.exe</code>) is the official build, signed by the Python Software Foundation.
Third-party components keep their own licenses (see the <code>licenses</code> folder in the zip).</li>
</ul>
<h2>Maintainer</h2>
<ul>
<li><a href="https://github.com/{owner}">{owner}</a> — writes, reviews and publishes every release.</li>
</ul>
<h2 id="privacy">Privacy policy</h2>
<p>This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it.</p>
<p>Network access: the new-version check (once a day 4Dir reads <code>{base}version.json</code>, a small public file; nothing about you or your files is sent),
and the optional Google Drive backup if you sign in. Full details: <a href="privacy.html">Privacy policy</a>. There is no telemetry and no ads.</p>
</section>
</main>
<footer><div class="wrap">
<a href="{repo_url}">Source code</a> · <a href="{repo_url}/issues">Issues</a> · <a href="mailto:{SUPPORT}?subject=%5B4Dir%5D%20">{SUPPORT}</a>
</div></footer>
</body>
</html>
"""


def privacy_page(cfg):
    """1.11.0 개인정보처리방침 (영어 + 한국어) — 구글 OAuth 동의 화면에 넣는 주소"""
    repo_url = f"https://github.com/{cfg['owner'] or 'OWNER'}/{cfg['repo']}"
    base = site_base(cfg)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>4Dir - Privacy policy</title>
<meta name="description" content="What data 4Dir uses: new-version check, optional Google Drive backup stored in your own Drive.">
<link rel="canonical" href="{base}privacy.html">
<link rel="icon" href="icon.png">
<link rel="stylesheet" href="style.css">
</head>
<body>
<header class="top"><div class="wrap">
<a class="logo" href="./"><img src="icon.png" alt="" width="28" height="28">4Dir</a>
</div></header>
<main class="wrap">
<p><a href="./">Home</a> · <a href="#ko">한국어</a></p>
<section><h1>Privacy policy</h1>
<p>Last updated: 2026-11-06. 4Dir is a free Windows file manager made by an individual developer. 4Dir has no servers that receive your data, no telemetry and no ads.</p>
<h2>Data on your PC</h2>
<p>Settings, tabs, favorites, labels, tags and memos are stored only in the 4Dir folder on your PC.</p>
<h2>New-version check</h2>
<p>Once a day 4Dir downloads <code>{base}version.json</code> (a small public file). Nothing about you or your files is sent. You can turn this off in Settings.</p>
<h2>Google Drive backup (optional)</h2>
<ul>
<li>Only if you choose <b>Sign in with Google</b>. 4Dir works fully without it.</li>
<li>4Dir asks for these Google permissions only: <code>drive.appdata</code> (a hidden folder in <b>your own</b> Google Drive that only 4Dir can use)
and <code>openid email</code> (to show which account is connected). 4Dir cannot see any other files in your Drive.</li>
<li>What is stored: a zip of your 4Dir settings, tabs, favorites, labels, tags and memos — once a day, the latest 10 are kept.</li>
<li>The data goes directly from your PC to your Google Drive. It is never sent to the developer or any other server.
The sign-in key (refresh token) is stored in the Windows Credential Manager on your PC.</li>
<li>To stop: Settings &gt; Backup &gt; <b>Disconnect</b> (this also revokes the permission). To delete the backups:
Google Drive &gt; Settings &gt; Manage apps &gt; 4Dir &gt; Delete hidden app data. You can also remove access at
<a href="https://myaccount.google.com/permissions">myaccount.google.com/permissions</a>.</li>
<li>4Dir's use of information received from Google APIs adheres to the
<a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data Policy</a>, including the Limited Use requirements.</li>
</ul>
<h2>Contact</h2>
<p><a href="mailto:{SUPPORT}?subject=%5B4Dir%5D%20">{SUPPORT}</a> · <a href="{repo_url}/issues">GitHub Issues</a></p>
</section>
<section id="ko"><h1>개인정보처리방침</h1>
<p>최종 수정: 2026-11-06. 4Dir 는 개인 개발자가 만든 무료 윈도우 파일 관리자입니다. 사용자 정보를 받는 서버·사용 기록 수집·광고가 없습니다.</p>
<h2>PC 에 있는 정보</h2>
<p>설정·탭·즐겨찾기·라벨·태그·메모는 사용자 PC 의 4Dir 폴더에만 저장됩니다.</p>
<h2>새 버전 확인</h2>
<p>하루 한 번 <code>{base}version.json</code>(작은 공개 파일)을 읽습니다. 사용자나 파일에 대한 정보는 보내지 않으며, 설정에서 끌 수 있습니다.</p>
<h2>구글 드라이브 백업 (선택)</h2>
<ul>
<li><b>구글로 로그인</b>을 직접 고른 경우에만 동작합니다. 로그인하지 않아도 4Dir 의 모든 기능을 쓸 수 있습니다.</li>
<li>요청하는 구글 권한은 <code>drive.appdata</code>(<b>사용자 본인</b> 구글 드라이브 안의 4Dir 전용 숨은 폴더)와 <code>openid email</code>(연결된 계정 표시용)뿐입니다. 드라이브의 다른 파일은 볼 수 없습니다.</li>
<li>저장하는 것: 4Dir 설정·탭·즐겨찾기·라벨·태그·메모 zip — 하루 한 번, 최근 10개만 보관.</li>
<li>정보는 사용자 PC 에서 사용자 구글 드라이브로 바로 갑니다. 개발자나 다른 서버로는 보내지 않습니다. 로그인 열쇠는 PC 의 윈도우 자격 증명 관리자에 저장됩니다.</li>
<li>그만두기: 설정 &gt; 백업 &gt; <b>연결 끊기</b>(권한도 취소). 백업 지우기: 구글 드라이브 &gt; 설정 &gt; 앱 관리 &gt; 4Dir &gt; 숨겨진 앱 데이터 삭제.
<a href="https://myaccount.google.com/permissions">myaccount.google.com/permissions</a> 에서도 권한을 없앨 수 있습니다.</li>
<li>구글 API 에서 받은 정보는 Google API 서비스 사용자 데이터 정책(제한적 사용 요건 포함)을 따릅니다.</li>
</ul>
<h2>문의</h2>
<p><a href="mailto:{SUPPORT}?subject=%5B4Dir%5D%20">{SUPPORT}</a></p>
</section>
</main>
<footer><div class="wrap">
<a href="{repo_url}">Source code</a> · <a href="code-signing.html">Code signing policy</a> · <a href="privacy.html">Privacy</a>
</div></footer>
</body>
</html>
"""


def guide_img_lang(lang):
    """사용법 그림 폴더(앱 언어 코드). 그 언어 그림이 없으면 영어, 그것도 없으면 한국어"""
    for c in (ST.APP_LANG[lang], "en", "ko"):
        if os.path.isfile(os.path.join(ROOT, "bin", "guide", c, "p1.png")):
            return c
    raise SystemExit("사용법 그림 없음 — make_guide.py 먼저")


def _beacon(html_, cfg):
    """방문 통계 (1.6.0): 클라우드플레어 웹 분석 코드를 </body> 앞에. 쿠키 없음. cf_beacon 없으면 그대로"""
    tok = (cfg.get("cf_beacon") or "").strip()
    if not tok or "</body>" not in html_:
        return html_
    tag = ("<script defer src='https://static.cloudflareinsights.com/beacon.min.js' "
           f"data-cf-beacon='{{\"token\": \"{tok}\"}}'></script>")
    return html_.replace("</body>", tag + chr(10) + "</body>", 1)


def versions_page(lang, cfg, rel):
    """지난 버전 받기 + 버전별 바뀐 점 (1.2.0). 받기 = 깃허브 릴리스의 각 버전 zip"""
    t = ST.T[lang]
    ver = rel[0]
    e = html.escape
    repo_url = f"https://github.com/{cfg['owner'] or 'OWNER'}/{cfg['repo']}"
    base = site_base(cfg)
    up = "" if lang == "en" else "../"
    url_of = lambda lg: base + ("" if lg == "en" else lg + "/") + "versions.html"
    alts = "\n".join(f'<link rel="alternate" hreflang="{lg}" href="{url_of(lg)}">' for lg in ST.LANGS)
    opts = "".join(f'<option value="{up}{"" if lg == "en" else lg + "/"}versions.html"{" selected" if lg == lang else ""}>{e(ST.NAMES[lg])}</option>'
                   for lg in ST.LANGS)
    rows = []
    for v, d, _ in CL.CHANGES:
        z = f"{repo_url}/releases/download/v{v}/4Dir_v{v}.zip"
        tag = f' <span class="tag">{e(t["hist_latest"])}</span>' if v == ver else ""
        lis = "".join(f"<li>{x}</li>" for x in CL.items(v, lang))
        rows.append(f'<article class="ver" id="v{v}"><div class="vh"><h3>v{v}{tag}</h3><span class="date">{d}</span>'
                    f'<a class="btn sm" href="{z}">⬇ {e(t["hist_dl"])}</a> <a class="sha" href="{z}.sha256.txt">SHA256</a></div><ul>{lis}</ul></article>')
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(t["hist_title"])}</title>
<meta name="description" content="{e(t["hist_intro"])}">
<link rel="canonical" href="{url_of(lang)}">
{alts}
<link rel="icon" href="{up}icon.png">
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<header class="top"><div class="wrap">
<a class="logo" href="./"><img src="{up}icon.png" alt="" width="28" height="28">4Dir</a>
{app_nav(lang, up, True)}{board_nav(lang)}<label class="lang">{e(t["lang"])} <select onchange="try{{localStorage.setItem('4dir-lang',1)}}catch(e){{}};location.href=this.value">{opts}</select></label>
</div></header>
<main class="wrap">
<p><a href="./">{e(t["home"])}</a></p>
<section><h1>{e(t["hist_h"])}</h1><p class="sub">{e(t["hist_intro"])}</p>
{"".join(rows)}
</section>
</main>
<footer><div class="wrap">
<a href="{repo_url}">{e(t["src"])}</a> · <a href="{repo_url}/releases">GitHub Releases</a> · <a href="mailto:{SUPPORT}?subject=%5B4Dir%5D%20">{SUPPORT}</a> · <a href="{up}code-signing.html">Code signing policy</a>
<p>{e(t["lic"])}</p>
</div></footer>
</body>
</html>
"""


CSS = """:root{--bg:#f7f8fa;--fg:#1d2330;--mut:#5b6475;--card:#fff;--line:#e2e5eb;--acc:#1f6feb;--acc2:#1859c4;--don:#e0446b;--code:#eef1f5}
@media (prefers-color-scheme:dark){:root{--bg:#15181e;--fg:#e6e9ef;--mut:#9aa3b2;--card:#1d2129;--line:#2c313b;--acc:#4c8dff;--acc2:#6aa1ff;--don:#ff5c86;--code:#252a33}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 "Segoe UI","Malgun Gothic","Microsoft YaHei","Yu Gothic UI",system-ui,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:0 16px}
a{color:var(--acc)}
.top{border-bottom:1px solid var(--line);background:var(--card)}
.top .wrap{display:flex;align-items:center;justify-content:space-between;height:56px;gap:12px}
.logo{display:flex;align-items:center;gap:8px;font-weight:700;font-size:20px;color:var(--fg);text-decoration:none}
.lang{font-size:14px;color:var(--mut)}.lang select{font:inherit;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);max-width:46vw}
.hero{text-align:center;padding:48px 0 24px}
.hero h1{font-size:clamp(26px,4.4vw,42px);line-height:1.25;margin:0 0 12px}
.sub{color:var(--mut);font-size:18px;margin:0 0 24px}
.note{color:var(--mut);font-size:14px}
.btn{display:inline-block;padding:10px 18px;border-radius:8px;background:var(--acc);color:#fff;text-decoration:none;font-weight:600}
.btn:hover{background:var(--acc2)}.btn.big{font-size:19px;padding:14px 28px}
.btn.don{background:var(--don);margin:4px}.hero-don{margin-top:4px}
.btn.line{background:transparent;color:var(--acc);border:2px solid var(--acc);padding:8px 20px;font-size:17px}.btn.line:hover{background:var(--acc);color:#fff}
.shot{margin:24px 0;text-align:center}.shot img{max-width:100%;height:auto;border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,.12)}
figcaption{color:var(--mut);font-size:14px;margin-top:6px}
section{margin:40px 0}h2{font-size:26px;margin:0 0 16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px}.card h3{margin:0 0 6px;font-size:18px}.card p{margin:0;color:var(--mut)}
ol li{margin:6px 0}.tip{background:var(--card);border-left:4px solid var(--acc);padding:10px 14px;border-radius:6px}
code{background:var(--code);padding:2px 6px;border-radius:4px;font-family:Consolas,monospace;font-size:14px;word-break:break-all}
code.sha{display:inline-block;max-width:100%}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:8px 0}summary{cursor:pointer;font-weight:600}
#donate{text-align:center;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:24px 16px}
footer{border-top:1px solid var(--line);padding:24px 0;color:var(--mut);font-size:14px;text-align:center}
.news{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin:8px 0 24px}.news h2{font-size:20px;margin:0 0 8px}.news ul{margin:0 0 8px;padding-left:20px}.news p{margin:0}
.ver{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:12px 0}.ver ul{margin:8px 0 0;padding-left:20px}
.vh{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px}.vh h3{margin:0;font-size:20px}.date{color:var(--mut);font-size:14px}
.thx{position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:50;padding:16px}.thx[hidden]{display:none}
.thx-in{position:relative;background:var(--card);color:inherit;max-width:440px;width:100%;border-radius:12px;padding:22px 24px;box-shadow:0 10px 40px rgba(0,0,0,.3);text-align:center}
.thx-in h2{margin:0 0 8px;font-size:20px}.thx-x{position:absolute;top:8px;right:10px;border:0;background:none;font-size:18px;cursor:pointer;color:inherit}
.btn.sm{padding:5px 12px;font-size:14px}a.sha{font-size:13px;color:var(--mut)}.tag{font-size:12px;background:var(--acc);color:#fff;border-radius:10px;padding:1px 8px;vertical-align:middle}
.fast{font-size:clamp(18px,2.6vw,24px);font-weight:700;margin:0 0 8px}.fast a{color:var(--acc);text-decoration:none}.fast a:hover{text-decoration:underline}
.nav{margin-left:auto;margin-right:8px;font-weight:700;text-decoration:none;color:var(--acc);border:2px solid var(--acc);border-radius:8px;padding:5px 14px;white-space:nowrap}.nav:hover{background:var(--acc);color:#fff}.nav.app{margin-left:0;margin-right:auto}.nav.app+.nav{margin-left:0}.nav+.nav.board{margin-left:0}.nav.app+.nav.board{margin-left:auto}@media (max-width:600px){.nav{padding:4px 8px;font-size:13px;margin-right:0}.top .wrap{height:auto;flex-wrap:wrap;gap:8px;padding-top:8px;padding-bottom:8px}.lang{font-size:0;margin-left:auto}.lang select{font-size:14px}}
.gwrap{max-width:1080px;margin:0 auto;padding:0 16px}.side{display:none}
@media (min-width:1100px){.gwrap{max-width:1360px;display:grid;grid-template-columns:230px minmax(0,1fr);gap:36px}.side{display:block}
.side nav{position:sticky;top:16px;max-height:calc(100vh - 32px);overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-top:16px}
.side ol{margin:6px 0 0;padding-left:20px}.side li{margin:4px 0}.side a{text-decoration:none;color:var(--fg)}.side a:hover{color:var(--acc)}.side a.on{color:var(--acc);font-weight:700}.guide .toc{display:none}}
.guide h1{font-size:clamp(26px,4vw,36px);margin:16px 0 8px}.toc{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 18px;margin:16px 0 8px}.toc ol{margin:6px 0 0;padding-left:22px;columns:2;column-gap:32px}
.gs{margin:48px 0}.gs h2{border-bottom:1px solid var(--line);padding-bottom:6px}.gs .shot{margin:16px 0}
ol.marks{list-style:none;counter-reset:m;padding-left:0}ol.marks li{counter-increment:m;position:relative;padding-left:34px;margin:10px 0}
ol.marks li::before{content:counter(m);position:absolute;left:0;top:1px;width:22px;height:22px;border-radius:50%;background:#e03131;color:#fff;font-size:13px;font-weight:700;text-align:center;line-height:22px}
kbd{display:inline-block;border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 5px;font:13px Consolas,monospace;background:var(--card)}
.totop{text-align:right;font-size:14px}
@media (max-width:600px){.hero{padding:32px 0 16px}.sub{font-size:16px}.grid{grid-template-columns:1fr}.toc ol{columns:1}}
"""


def make_icon(dst):
    """4Dir.ico → icon.png (PySide6 있으면). 없으면 건너뜀"""
    try:
        from PySide6 import QtGui, QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # noqa: F841
        ico = QtGui.QIcon(os.path.join(ROOT, "bin", "4Dir.ico"))
        pm = ico.pixmap(64, 64)
        return pm.save(dst)
    except Exception as ex:
        log(f"아이콘 변환 실패 {ex}")
        return False


def main():
    cfg = load_config()
    rel = latest_release()
    log(f"사이트 만들기 v{MAKE_SITE_VER} → {OUT}  계정={cfg['owner'] or '(아직 없음 → OWNER 로 표시)'} 배포판 v{rel[0]} {rel[2] / 1048576:.1f}MB")
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    assert CL.CHANGES[0][0] == rel[0], f"changelog.py 맨 위({CL.CHANGES[0][0]})가 배포판 v{rel[0]} 이 아님 — 바뀐 점 먼저 적을 것"
    assert all(len(it) == len(CL.ORDER) for _, _, its in CL.CHANGES for it in its), "changelog 항목 언어 수 틀림"
    for lang in ST.LANGS:
        t = ST.T[lang]
        assert set(t) == set(ST.T["en"]), (lang, set(ST.T["en"]) ^ set(t))
        assert len(t["feats"]) == 6 and len(t["how"]) == 3 and len(t["faq"]) == 5, lang
        d = OUT if lang == "en" else os.path.join(OUT, lang)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_beacon(page(lang, cfg, rel), cfg))
        with open(os.path.join(d, "versions.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_beacon(versions_page(lang, cfg, rel), cfg))
        if lang in GT.GUIDE:   # 1.4.0 사용법
            g = GT.GUIDE[lang]
            assert set(g) == set(GT.GUIDE["ko"]), (lang, set(GT.GUIDE["ko"]) ^ set(g))
            with open(os.path.join(d, "guide.html"), "w", encoding="utf-8", newline="\n") as f:
                f.write(_beacon(guide_page(lang, cfg, rel), cfg))
            src = os.path.join(ROOT, "bin", "guide", guide_img_lang(lang))
            dst = os.path.join(OUT, "img", "guide", guide_img_lang(lang))
            if not os.path.isdir(dst):
                os.makedirs(dst)
                for i in sorted({s["img"] for s in GT.GUIDE[lang]["sections"]}):   # 1.4.1: 글에 쓰인 그림만 (p7~ 추가)
                    f = os.path.join(src, f"p{i}.png")
                    if not os.path.isfile(f):   # 1.5.2: 그 언어 그림이 없으면(예: SVN 그림은 TortoiseSVN 있는 PC 에서만) 영어 → 한국어 그림
                        alt = "en" if lang != "ko" and os.path.isfile(os.path.join(ROOT, "bin", "guide", "en", f"p{i}.png")) else "ko"
                        f = os.path.join(ROOT, "bin", "guide", alt, f"p{i}.png")
                        log(f"  사용법 그림 p{i} — {guide_img_lang(lang)} 에 없어 {alt} 것으로")
                    shutil.copy2(f, dst)
            log(f"사용법 {lang} (그림 {guide_img_lang(lang)})")
    with open(os.path.join(OUT, "code-signing.html"), "w", encoding="utf-8", newline="\n") as f:   # 1.7.0
        f.write(_beacon(signing_page(cfg), cfg))
    log("코드 서명 정책 code-signing.html")
    with open(os.path.join(OUT, "privacy.html"), "w", encoding="utf-8", newline="\n") as f:   # 1.11.0
        f.write(_beacon(privacy_page(cfg), cfg))
    log("개인정보처리방침 privacy.html")
    open(os.path.join(OUT, "style.css"), "w", encoding="utf-8", newline="\n").write(CSS)
    shutil.copytree(os.path.join(SITE_SRC, "img"), os.path.join(OUT, "img"), dirs_exist_ok=True)
    # 1.3.0: 다른 앱 소개 페이지(_site\apps\<이름>\ → 사이트 /<이름>/) 그대로 복사 — 예: just-downloader. 매번 OUT 을 지우므로 여기서 다시 넣어야 남는다
    app_urls = []
    apps = os.path.join(SITE_SRC, "apps")
    for nm in (sorted(os.listdir(apps)) if os.path.isdir(apps) else []):
        assert nm not in ST.LANGS and nm not in ("img",), f"앱 폴더 이름 충돌: {nm}"
        shutil.copytree(os.path.join(apps, nm), os.path.join(OUT, nm))
        for a, _, fs in os.walk(os.path.join(apps, nm)):
            app_urls += [os.path.relpath(os.path.join(a, f), apps).replace(os.sep, "/").replace("index.html", "") for f in fs if f.endswith(".html")]
        log(f"앱 페이지 {nm} 복사")
    log(f"아이콘 {'만듦' if make_icon(os.path.join(OUT, 'icon.png')) else '없음'}")
    owner = cfg["owner"] or "OWNER"
    base = site_base(cfg)
    ver = rel[0]
    # 1.5.0: 앱 새 버전 알림 줄에 나올 바뀐 점 (앱 언어 코드별, 글자만). notes 는 옛 4Dir(영어로 띄움) 때문에 비움
    strip = lambda x: html.unescape(re.sub(r"<[^>]+>", "", x))   # 1.8.1: &gt; 같은 글자 표시도 풀어서 (앱 알림은 HTML 아님)
    notes = {ST.APP_LANG[lg]: " / ".join(strip(x) for x in CL.items(ver, lg)) for lg in ST.LANGS}
    json.dump({"version": ver, "page": base, "notes": "", "notes_i18n": notes}, open(os.path.join(OUT, "version.json"), "w", encoding="utf-8"), ensure_ascii=False)
    open(os.path.join(OUT, "robots.txt"), "w", encoding="utf-8").write(f"User-agent: *\nAllow: /\nSitemap: {base}sitemap.xml\n")
    urls = "".join(f"<url><loc>{base}{'' if lg == 'en' else lg + '/'}{pg}</loc></url>" for lg in ST.LANGS for pg in ("", "versions.html") + (("guide.html",) if lg in GT.GUIDE else ()))
    urls += "".join(f"<url><loc>{base}{u}</loc></url>" for u in sorted(app_urls))   # 1.3.0
    urls += f"<url><loc>{base}code-signing.html</loc></url>"   # 1.7.0
    open(os.path.join(OUT, "sitemap.xml"), "w", encoding="utf-8").write(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    if cfg.get("domain"):   # 깃허브 무료 페이지의 개인 도메인 표시 파일 (1.1.0)
        with open(os.path.join(OUT, "CNAME"), "w", encoding="ascii", newline="") as f:
            f.write(cfg["domain"] + chr(10))
        log(f"개인 도메인 {cfg['domain']} (CNAME)")
    n = sum(len(fs) for _, _, fs in os.walk(OUT))
    mb = sum(os.path.getsize(os.path.join(a, f)) for a, _, fs in os.walk(OUT) for f in fs) / 1048576
    log(f"완료: 파일 {n}개 {mb:.1f}MB, 언어 {len(ST.LANGS)}개, version.json = {ver}, 지난 버전 {len(CL.CHANGES)}개")


if __name__ == "__main__":
    main()
