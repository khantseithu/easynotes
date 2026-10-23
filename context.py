"""Video chapters and article page text."""
import html
import re
import urllib.request

UA = {"User-Agent": "ytnotes"}


def chapters(info):
    return [(c.get("start_time") or 0, (c.get("title") or "").strip()) for c in info.get("chapters") or [] if c.get("title")]


def get(url, timeout=20, limit=400000):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        if not any(t in ctype for t in ("text", "html", "json")):
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
