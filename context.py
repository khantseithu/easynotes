"""Context that a video already provides: its chapters and the repos, gists and docs linked in its description."""
import html
import json
import re
import urllib.request
from urllib.parse import urlparse

UA = {"User-Agent": "ytnotes"}
SKIP_HOSTS = ("youtube.com", "youtu.be", "twitter.com", "x.com", "instagram.com", "facebook.com", "tiktok.com",
              "linkedin.com", "discord.gg", "discord.com", "patreon.com", "buymeacoffee.com", "ko-fi.com", "twitch.tv",
              "amzn.to", "amazon.com", "bit.ly", "threads.net", "bsky.app", "reddit.com", "t.me", "spotify.com",
              "apple.com", "substack.com", "gumroad.com", "skool.com", "calendly.com")
GITHUB_SKIP = {"sponsors", "features", "about", "pricing", "topics", "marketplace", "orgs", "settings", "login"}
MANIFESTS = {"package.json", "pyproject.toml", "requirements.txt", "cargo.toml", "go.mod", "gemfile", "pom.xml",
             "build.gradle", "composer.json", "dockerfile", "docker-compose.yml", "compose.yaml", ".env.example",
             "wrangler.toml", "vite.config.ts", "next.config.js", "next.config.ts", "tsconfig.json"}
CODE_EXT = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java", ".kt", ".swift", ".php", ".vue",
            ".svelte", ".sql", ".sh", ".c", ".cpp", ".cs", ".ex", ".dart")
SKIP_PATH = re.compile(r"(^|/)(node_modules|dist|build|vendor|\.git|\.next|test|tests|__tests__|spec|fixtures|"
                       r"examples?|docs?|migrations)/|\.(test|spec|min|d)\.\w+$|lock")
MAX_FILE = 8000
MAX_TOTAL = 60000


def chapters(info):
    return [(c.get("start_time") or 0, (c.get("title") or "").strip()) for c in info.get("chapters") or [] if c.get("title")]


def links(description):
    urls = re.findall(r"https?://[^\s<>\"')\]]+", description or "")
    out = []
    for u in urls:
        u = u.rstrip(".,;:!")
        host = (urlparse(u).hostname or "").removeprefix("www.")
        if host and not any(host == h or host.endswith("." + h) for h in SKIP_HOSTS) and u not in out:
            out.append(u)
    return out


def get(url, raw=False, timeout=20, limit=400000):
    headers = dict(UA)
    if raw:
        headers["Accept"] = "application/vnd.github.raw"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        if not raw and not any(t in ctype for t in ("text", "html", "json")):
            return ""
        return r.read(limit).decode("utf-8", "replace")


def page_text(markup):
    markup = re.sub(r"(?is)<(script|style|nav|header|footer|svg|noscript)\b.*?</\1>", " ", markup)
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", markup)
    body = re.search(r"(?is)<(main|article)\b.*?</\1>", markup)
    text = re.sub(r"(?is)<(pre|code)\b[^>]*>", "\n```\n", body.group(0) if body else markup)
    text = re.sub(r"(?is)</(pre)>", "\n```\n", text)
    text = re.sub(r"(?is)<br\s*/?>|</(p|div|li|h\d|tr)>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return (html.unescape(title.group(1)).strip() + "\n\n" if title else "") + text


def github_repo(owner, repo):
    api = f"https://api.github.com/repos/{owner}/{repo}"
    parts = []
    try:
        parts.append(("README", get(f"{api}/readme", raw=True)[:MAX_FILE * 2]))
    except Exception:
        pass
    try:
        tree = json.loads(get(f"{api}/git/trees/HEAD?recursive=1")).get("tree", [])
    except Exception:
        tree = []
    files = [t for t in tree if t.get("type") == "blob"]
    if files:
        listing = [f["path"] for f in files if not SKIP_PATH.search(f["path"])][:200]
        parts.append(("File tree", "\n".join(listing)))
    manifests = [f for f in files if f["path"].rsplit("/", 1)[-1].lower() in MANIFESTS and f["path"].count("/") <= 1]
    code = sorted((f for f in files if f["path"].endswith(CODE_EXT) and not SKIP_PATH.search(f["path"])
                   and 0 < f.get("size", 0) <= 20000), key=lambda f: (f["path"].count("/"), f["path"]))
    for f in manifests[:6] + code[:10]:
        try:
            parts.append((f["path"], get(f"{api}/contents/{f['path']}", raw=True)[:MAX_FILE]))
        except Exception:
            continue
    return parts


def gist(gid):
    data = json.loads(get(f"https://api.github.com/gists/{gid}"))
    return [(name, (f.get("content") or "")[:MAX_FILE]) for name, f in (data.get("files") or {}).items()]


def source(url):
    """Return (label, [(name, text)]) for one link, or None if it gives nothing useful."""
    p = urlparse(url)
    host = (p.hostname or "").removeprefix("www.")
    segs = [s for s in p.path.split("/") if s]
    if host == "github.com" and len(segs) >= 2 and segs[0] not in GITHUB_SKIP:
        repo = segs[1].removesuffix(".git")
        return f"GitHub repo {segs[0]}/{repo}", github_repo(segs[0], repo)
    if host == "gist.github.com" and segs:
        return f"Gist {segs[-1]}", gist(segs[-1])
    if host == "raw.githubusercontent.com":
        return f"File {'/'.join(segs[-2:])}", [(segs[-1], get(url)[:MAX_FILE])]
    text = page_text(get(url))
    return (f"Page {url}", [("page", text[:MAX_FILE])]) if len(text) > 200 else None


def gather(urls, log=lambda m: None, max_links=6):
    """Fetch linked sources, repos first. Returns (markdown block, list of URLs used)."""
    urls = sorted(urls, key=lambda u: 0 if "github" in u else 1)[:max_links]
    blocks, used, total = [], [], 0
    seen = set()
    for url in urls:
        key = tuple(urlparse(url).path.split("/")[1:3]) if "github.com" in url else url
        if key in seen:
            continue
        seen.add(key)
        log(f"Reading {url}")
        try:
            got = source(url)
        except Exception:
            continue
        if not got or not got[1]:
            continue
        label, parts = got
        chunk = f"### {label} ({url})\n" + "\n".join(f"\n#### {name}\n{text.strip()}" for name, text in parts if text.strip())
        if total + len(chunk) > MAX_TOTAL:
            chunk = chunk[:max(0, MAX_TOTAL - total)]
        if chunk:
            blocks.append(chunk)
            used.append(url)
            total += len(chunk)
        if total >= MAX_TOTAL:
            break
    return "\n\n".join(blocks), used
