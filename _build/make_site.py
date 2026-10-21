# -*- coding: utf-8 -*-
"""4Dir 공개 사이트 만들기 (MAKE_SITE_VER 1.2.0)

python make_site.py [출력 폴더]   (기본: 4Dir\\_site\\out)
- 문구: site_text.py (10개 언어), 버전별 바뀐 점: changelog.py (1.2.0 — 메인 '바뀐 점' + versions.html 지난 버전 받기), 설정: site_config.json (깃허브 계정·후원 주소)
- 버전·크기·지문: _release 의 최신 4Dir_v*.zip + .sha256.txt
- 결과: index.html(영어) + <언어>\\index.html, style.css, img\\, icon.png, version.json(앱 새 버전 알림),
        robots.txt, sitemap.xml, .nojekyll  → 깃허브 무료 페이지(docs 폴더)에 그대로 올림
- 바깥 스크립트·글꼴·추적 코드 없음(사이트 하나로 끝). 광고 없음.
로그: _build\\make_site_log.txt
"""
import os
import re
import sys
import json
import time
import html
import shutil

MAKE_SITE_VER = "1.2.0"
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
        btns.append(f'<a class="btn don" href="https://ko-fi.com/{e(cfg["kofi"])}" rel="noopener">♥ Ko-fi</a>')
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
<label class="lang">{e(t["lang"])} <select onchange="try{{localStorage.setItem('4dir-lang',1)}}catch(e){{}};location.href=this.value">{opts}</select></label>
</div></header>
<main class="wrap">
<section class="hero">
<h1>{e(t["tagline"])}</h1>
<p class="sub">{e(t["sub"])}</p>
<p><a class="btn big" href="{dl_url}">⬇ {e(t["dl"].format(**fmt))}</a></p>
<p class="note">{e(t["dlnote"].format(**fmt))}</p>
</section>
<section class="news"><h2>{e(t["new_h"].format(**fmt))}</h2><ul>{news}</ul><p><a href="versions.html">{e(t["hist_link"])} →</a></p></section>
<figure class="shot"><img src="{up}img/{img}_1.png" alt="{e(t["shot1"])}" width="1280" height="760"><figcaption>{e(t["shot1"])}</figcaption></figure>
<section><h2>{e(t["feat_h"])}</h2><div class="grid">{feats}</div></section>
<figure class="shot"><img src="{up}img/{img}_2.png" alt="{e(t["shot2"])}" width="1280" height="760" loading="lazy"><figcaption>{e(t["shot2"])}</figcaption></figure>
<section id="install"><h2>{e(t["how_h"])}</h2><ol>{how}</ol><p class="tip">{t["smart"]}</p>
<h3>{e(t["sha_h"])}</h3><p>{t["sha"].format(**fmt)}</p><p><code class="sha">{sha}</code></p></section>
{donate}
<section><h2>{e(t["faq_h"])}</h2>{faq}</section>
</main>
<footer><div class="wrap">
<a href="{repo_url}">{e(t["src"])}</a> · <a href="{repo_url}/issues">{e(t["issues"])}</a> · <a href="mailto:{SUPPORT}">{SUPPORT}</a> · <a href="{repo_url}/releases">v{ver}</a>
<p>{e(t["lic"])}</p>
</div></footer>
</body>
</html>
"""


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
<label class="lang">{e(t["lang"])} <select onchange="try{{localStorage.setItem('4dir-lang',1)}}catch(e){{}};location.href=this.value">{opts}</select></label>
</div></header>
<main class="wrap">
<p><a href="./">{e(t["home"])}</a></p>
<section><h1>{e(t["hist_h"])}</h1><p class="sub">{e(t["hist_intro"])}</p>
{"".join(rows)}
</section>
</main>
<footer><div class="wrap">
<a href="{repo_url}">{e(t["src"])}</a> · <a href="{repo_url}/releases">GitHub Releases</a> · <a href="mailto:{SUPPORT}">{SUPPORT}</a>
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
.btn.don{background:var(--don);margin:4px}
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
.btn.sm{padding:5px 12px;font-size:14px}a.sha{font-size:13px;color:var(--mut)}.tag{font-size:12px;background:var(--acc);color:#fff;border-radius:10px;padding:1px 8px;vertical-align:middle}
@media (max-width:600px){.hero{padding:32px 0 16px}.sub{font-size:16px}.grid{grid-template-columns:1fr}}
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
        assert len(t["feats"]) == 6 and len(t["how"]) == 3 and len(t["faq"]) == 3, lang
        d = OUT if lang == "en" else os.path.join(OUT, lang)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(page(lang, cfg, rel))
        with open(os.path.join(d, "versions.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(versions_page(lang, cfg, rel))
    open(os.path.join(OUT, "style.css"), "w", encoding="utf-8", newline="\n").write(CSS)
    shutil.copytree(os.path.join(SITE_SRC, "img"), os.path.join(OUT, "img"))
    log(f"아이콘 {'만듦' if make_icon(os.path.join(OUT, 'icon.png')) else '없음'}")
    owner = cfg["owner"] or "OWNER"
    base = site_base(cfg)
    ver = rel[0]
    json.dump({"version": ver, "page": base, "notes": ""}, open(os.path.join(OUT, "version.json"), "w", encoding="utf-8"))
    open(os.path.join(OUT, "robots.txt"), "w", encoding="utf-8").write(f"User-agent: *\nAllow: /\nSitemap: {base}sitemap.xml\n")
    urls = "".join(f"<url><loc>{base}{'' if lg == 'en' else lg + '/'}{pg}</loc></url>" for lg in ST.LANGS for pg in ("", "versions.html"))
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
