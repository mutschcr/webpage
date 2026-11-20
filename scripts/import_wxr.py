#!/usr/bin/env python3
"""Prepare an offline review copy from an owner's local WordPress WXR export.

    python3 scripts/import_wxr.py export.xml --out ../wxr-review

pages.json preserves public routes, titles, post types and a cleaned version
of content:encoded. Use scripts/import_publications.py --wxr for publication
metadata. report.json records skipped items and duplicate public routes.
Review against the existing site before merging. A new output directory outside
this project is required. Python 3.11+; no dependencies or network access.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
PUBLIC_TYPES = {"page", "post", "w4pl"}
EMAIL = re.compile(r"[\w.!#$%&'*+/=?^_\x60{|}~-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
WP_VERSION = re.compile(r"^\{(https?://wordpress\.org/export/1\.[012]/)\}wxr_version$")
DOCTYPE_ERROR = "WXR-Dateien mit einer zusätzlichen XML-Dokumenttypdeklaration werden nicht verarbeitet."



class LocalTree(ET.TreeBuilder):
    def doctype(self, name: str, public_id: str, system_id: str) -> None:
        raise ValueError(DOCTYPE_ERROR)


def safe_url(value: str) -> bool:
    """Accept ordinary links; credentials, mail addresses and active schemes are omitted."""
    if not value or value != value.strip() or value.startswith("//"):
        return False
    try:
        parsed = urlsplit(value)
        decoded = unquote(value)
        if ("\\" in decoded or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
                or EMAIL.search(decoded) or parsed.username is not None or parsed.password is not None):
            return False
        if parsed.scheme:
            return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
        return not parsed.netloc and ":" not in value.split("/", 1)[0]
    except ValueError:
        return False


def public_route(value: str, hosts: set[str]) -> str | None:
    if not safe_url(value):
        return None
    parsed = urlsplit(value)
    if parsed.hostname not in hosts or parsed.query or parsed.fragment:
        return None
    try:
        if parsed.port not in {None, 80, 443}:
            return None
    except ValueError:
        return None
    path = parsed.path or "/"
    decoded = unquote(path)
    if (not path.startswith("/") or "//" in path or "%" in decoded
            or decoded.count("/") != path.count("/") or any(c in decoded for c in "?#")
            or set(decoded.split("/")) & {".", "..", "wp-admin", "wp-login.php", "wp-json"}):
        return None
    return path if path.endswith("/") or "." in path.rsplit("/", 1)[-1] else path + "/"


class EditorialHTML(HTMLParser):
    """Keep editorial HTML for review; omit forms, scripts, comments and embedded documents."""

    tags = set("a abbr address article aside b blockquote br caption cite code col colgroup dd del "
               "details div dl dt em figcaption figure h1 h2 h3 h4 h5 h6 hr i img kbd li mark ol p "
               "pre q s section small span strong sub summary sup table tbody td tfoot th thead tr u ul".split())
    void = {"br", "col", "hr", "img"}
    drop = {"script", "style", "iframe", "form", "object", "svg", "math", "template", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.text: list[str] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.drop:
            self.hidden.append(tag)
        if self.hidden or tag not in self.tags:
            return
        kept = []
        for key, value in attrs:
            if value is None:
                continue
            if (tag, key) in {("a", "href"), ("img", "src")} and safe_url(value):
                kept.append((key, value))
            elif key in {"id", "class", "alt", "title", "width", "height", "colspan", "rowspan", "scope"}:
                kept.append((key, EMAIL.sub("[E-Mail]", value)))
        self.parts.append("<" + tag + "".join(f' {k}="{escape(v, quote=True)}"' for k, v in kept) + ">")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden:
            if self.hidden[-1] == tag:
                self.hidden.pop()
        elif tag in self.tags and tag not in self.void:
            self.parts.append(f"</{tag}>")
            if tag in {"p", "h1", "h2", "h3", "h4", "li", "div"}:
                self.text.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            data = EMAIL.sub("[E-Mail]", data)
            self.parts.append(escape(data, quote=False))
            self.text.append(data)


def editorial(value: str) -> EditorialHTML:
    parser = EditorialHTML()
    parser.feed(value)
    parser.close()
    return parser


def collect(source: Path, hosts: set[str]) -> tuple[dict, dict]:
    parser = ET.XMLParser(target=LocalTree())
    channel = ET.parse(source, parser=parser).getroot().find("channel")
    if channel is None:
        raise ValueError("Das ausgewählte XML enthält keinen RSS-Kanal.")
    wp = next((f"{{{m[1]}}}" for child in channel if (m := WP_VERSION.fullmatch(child.tag))), None)
    if wp is None:
        raise ValueError("Die WXR-Version 1.0, 1.1 oder 1.2 konnte nicht erkannt werden.")
    pages = {}
    skipped = Counter()
    duplicate_routes = []
    for item in channel.findall("item"):
        kind = item.findtext(wp + "post_type", "")
        if kind not in PUBLIC_TYPES:
            skipped["other_type"] += 1
            continue
        if item.findtext(wp + "status") != "publish" or item.findtext(wp + "post_password") != "":
            skipped["not_public_or_password_not_confirmed"] += 1
            continue
        route = public_route(item.findtext("link", "").strip(), hosts)
        title = EMAIL.sub("[E-Mail]", unescape(item.findtext("title", "").strip()))
        if not route or not title:
            skipped["unusable_route_or_title"] += 1
            continue
        if route in pages:
            duplicate_routes.append(route)
            continue
        content = item.findtext(CONTENT, "")
        pages[route] = {"type": kind, "title": title, "content_html": "".join(editorial(content).parts)}
    report = {"page_count": len(pages), "skipped": dict(skipped),
              "duplicate_public_routes": duplicate_routes}
    return pages, report


def write_review(out: Path, pages: dict, report: dict) -> None:
    if out.resolve().is_relative_to(ROOT):
        raise ValueError("Bitte einen neuen Ausgabeordner außerhalb des Website-Projekts wählen.")
    if out.exists() or out.is_symlink():
        raise FileExistsError(f"Der Ausgabeordner existiert bereits: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=".wxr-stage-") as tmp:
        staging = Path(tmp)
        for name, data in (("pages.json", pages), ("report.json", report)):
            (staging / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        out.mkdir(mode=0o700, exist_ok=False)
        for name in ("pages.json", "report.json"):
            (staging / name).rename(out / name)


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("wxr", type=Path, help="Lokale WXR-XML-Datei")
    cli.add_argument("--out", type=Path, required=True, help="Neuer, separater Ausgabeordner")
    cli.add_argument("--also-host", action="append", default=[], help="Zusätzlicher eigener historischer Hostname")
    args = cli.parse_args()
    hosts = {"mlps-lab.de", "www.mlps-lab.de", *(h.lower() for h in args.also_host)}
    if not all(re.fullmatch(r"[a-z0-9.-]+", h) for h in hosts):
        cli.error("--also-host erwartet einen einzelnen Hostnamen ohne Protokoll oder Pfad.")
    try:
        pages, report = collect(args.wxr, hosts)
        write_review(args.out, pages, report)
    except (OSError, ValueError, ET.ParseError) as error:
        cli.exit(1, f"WXR-Import: {error}\n")
    print(f"{len(pages)} öffentliche Inhalte in {args.out}.")


if __name__ == "__main__":
    main()
