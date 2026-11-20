"""Resolve production URLs for both a custom domain and a GitHub project path."""

import json
import posixpath
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://mlps-lab.de"
LAB_HOSTS = {"mlps-lab.de", "www.mlps-lab.de", "cmutschler.de", "www.cmutschler.de"}


def url_key(url):
    p = urlsplit(url)
    if p.hostname in LAB_HOSTS:
        return unquote(p.path) or "/"
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))


@lru_cache(maxsize=1)
def mappings():
    values = json.loads((ROOT / "data/urls.json").read_text(encoding="utf-8"))
    return set(values["routes"]), values["assets"]


def relative(target, page):
    path = posixpath.relpath(target, page or "/")
    if path == ".":
        return "./"
    path = quote(path, safe="/-._~!$&'()*+,;=:@")
    return path + ("/" if target.endswith("/") else "")


def localize(value, page):
    value = (value or "").strip()
    if not value or value.startswith(("#", "mailto:", "tel:", "data:")):
        return value
    if value.lower().startswith(("javascript:", "vbscript:", "file:", "blob:")):
        return ""
    source = urljoin(ORIGIN + page, value)
    p = urlsplit(source)
    if p.scheme not in ("http", "https"):
        return value
    routes, assets = mappings()
    key = url_key(source)
    # A versioned stylesheet may use the same URL path as a previous version.
    full_key = urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))
    target = assets.get(full_key) or assets.get(key)
    query = ""
    if not target and p.hostname in LAB_HOSTS:
        route = (unquote(p.path).rstrip("/") + "/") if p.path else "/"
        if route in routes:
            target = route
            query = p.query
        elif p.path.startswith("/assets/"):
            target = unquote(p.path)
            query = p.query
    if target:
        return urlunsplit(("", "", relative(target, page), query, p.fragment))
    # An original page/asset outside this export should remain reachable
    # from a pre-production preview. The migration inventory lists these.
    return source
