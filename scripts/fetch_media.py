#!/usr/bin/env python3
"""Recover public WordPress originals and update existing offline links."""
import argparse
import html
import json
import os
import re
import sys
import tempfile
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.error import URLError
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from paths import LAB_HOSTS, ORIGIN, ROOT, relative

UPLOAD = "/wp-content/uploads/"
MEDIA_PATH = re.compile(r"/wp-content/uploads/\d{4}/(?:0[1-9]|1[0-2])/[^/\\\x00-\x1f]+")
MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf"}
SIGNATURES = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff",
              ".jpeg": b"\xff\xd8\xff", ".gif": (b"GIF87a", b"GIF89a"), ".pdf": b"%PDF-"}
# Match whole attributes, including unrelated ones, to leave their values untouched.
ATTRIBUTE = re.compile(r"""\s+([^\s="'<>/`]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""")
BASE = re.compile(r"""<base\s+href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def media_path(url):
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    if (parsed.scheme != "https" or parsed.netloc not in {"mlps-lab.de", "www.mlps-lab.de"}
            or parsed.query or parsed.fragment or not MEDIA_PATH.fullmatch(path)
            or PurePosixPath(path).suffix.lower() not in MIMES):
        raise ValueError(f"Unexpected public media URL {url!r}")
    return path


class MediaRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        media_path(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def matches_file_type(prefix, suffix):
    if suffix == ".webp":
        return prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP"
    return prefix.startswith(SIGNATURES[suffix])


@lru_cache(maxsize=None)
def present(path):
    try:
        with path.open("rb") as stream:
            return matches_file_type(stream.read(16), path.suffix.lower())
    except FileNotFoundError:
        return False


def write_atomic(path, data):
    mode = (path.stat().st_mode & 0o777) if path.exists() else 0o644
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
        tmp = Path(out.name)
    try:
        tmp.write_bytes(data)
        tmp.chmod(mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def download(opener, public_url, destination):
    url_path = media_path(public_url)
    suffix = destination.suffix.lower()
    netloc = urlsplit(public_url).netloc
    url = urlunsplit(("https", netloc, quote(url_path, safe="/-._~"), "", ""))
    req = Request(url, headers={"User-Agent": "MLPS-Lab-public-media-migration/1.0"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with opener.open(req, timeout=25) as response:
        media_path(response.geturl())
        if response.status != 200:
            raise ValueError(f"HTTP {response.status}")
        mime = response.headers.get_content_type().lower()
        if mime not in {MIMES[suffix], "application/octet-stream", "binary/octet-stream"}:
            raise ValueError(f"Unexpected Content-Type {mime}")
        prefix = response.read(16)
        if not matches_file_type(prefix, suffix):
            raise ValueError("File signature disagrees with its extension")
        expected = response.headers.get("Content-Length")
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as out:
            tmp = Path(out.name)
        try:
            with tmp.open("wb") as out:
                out.write(prefix)
                while chunk := response.read(256 * 1024):
                    out.write(chunk)
            if expected is not None and tmp.stat().st_size != int(expected):
                raise ValueError("Incomplete response")
            tmp.chmod(0o644)
            os.replace(tmp, destination)
            present.cache_clear()
        finally:
            tmp.unlink(missing_ok=True)


def variants(row, original):
    folder = PurePosixPath(original).parent
    result = []
    for name in [row.get("local_variant"), *row.get("variants", [])]:
        if not name:
            continue
        path = str(folder / name)
        if name != PurePosixPath(name).name or not MEDIA_PATH.fullmatch(path):
            raise ValueError(f"Unexpected variant name {name!r}")
        if name.lower().endswith(PurePosixPath(original).suffix.lower()) and path not in result:
            result.append(path)
    return result


def scan(catalog, docs):
    # Each mapping leads to a real file with its true name and extension.
    mapping = {}
    counts = {"original": 0, "variant": 0, "remote": 0}
    for row in catalog:
        source = media_path(row["url"])
        names = [source, *variants(row, source)]
        local = [name for name in names if present(docs / name[1:])]
        state = "original" if source in local else "variant" if local else "remote"
        counts[state] += 1
        if local:
            for name in names:
                mapping[name] = name if name in local else local[0]
    return mapping, counts


def rewrite_value(value, page, mapping):
    if not value or value.startswith(("#", "data:", "mailto:", "tel:")):
        return value, False
    parsed = urlsplit(urljoin(ORIGIN + page, value))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LAB_HOSTS:
        return value, False
    source = unquote(parsed.path)
    target = mapping.get(source)
    if not target:
        return value, False
    result = urlunsplit(("", "", relative(target, page), "", parsed.fragment))
    return result, target != source


def rewrite_srcset(value, page, mapping):
    if "data:" in value:
        return value
    entries, fallback = [], []
    changed = False
    for entry in value.split(","):
        fields = entry.split()
        if not fields:
            continue
        target, alternate = rewrite_value(fields[0], page, mapping)
        changed |= target != fields[0] or alternate
        if alternate:
            fallback.append(target)
        else:
            entries.append(" ".join([target, *fields[1:]]))
    if not changed:
        return value
    # Another rendition can have a different pixel width from the source candidate.
    return ", ".join(dict.fromkeys(entries or fallback[:1]))


class MediaLinks(HTMLParser):
    def __init__(self, document, page, mapping):
        super().__init__(convert_charrefs=False)
        self.page = page
        self.mapping = mapping
        self.changes = []
        self.lines = [0, *(match.end() for match in re.finditer("\n", document))]

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        if UPLOAD not in raw and "wp-content%2Fuploads" not in raw:
            return
        line, col = self.getpos()
        offset = self.lines[line - 1] + col
        for match in ATTRIBUTE.finditer(raw):
            key = match[1].lower()
            if key not in {"src", "href", "poster", "srcset", "data-src", "data-srcset"}:
                continue
            group = next(i for i in (2, 3, 4) if match[i] is not None)
            value = html.unescape(match[group])
            if key.endswith("srcset"):
                updated = rewrite_srcset(value, self.page, self.mapping)
            else:
                updated, _ = rewrite_value(value, self.page, self.mapping)
            if updated != value:
                self.changes.append((offset + match.start(group), offset + match.end(group),
                                     html.escape(updated, quote=True)))

    handle_startendtag = handle_starttag


def relink(docs, data_path, mapping):
    data = json.loads(data_path.read_text(encoding="utf-8"))
    before = dict(data["assets"])
    for key in before:
        parsed = urlsplit(key)
        if not parsed.netloc or parsed.hostname in LAB_HOSTS:
            source = unquote(parsed.path)
            if source in mapping:
                data["assets"][key] = mapping[source]
    for source, target in mapping.items():
        data["assets"][source] = target
        data["assets"][ORIGIN + source] = target
    if data["assets"] != before:
        write_atomic(data_path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())
    changed = 0
    for file in docs.rglob("*.html"):
        document = file.read_text(encoding="utf-8")
        page = "/" + file.relative_to(docs).as_posix()
        base = BASE.search(document)
        page = urlsplit(urljoin(ORIGIN + page, html.unescape(base[1]) if base else "./")).path
        parser = MediaLinks(document, page, mapping)
        parser.feed(document)
        parser.close()
        if parser.changes:
            for start, end, value in reversed(parser.changes):
                document = document[:start] + value + document[end:]
            write_atomic(file, document.encode())
            changed += 1
    return changed


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    mode = arg.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="print local inventory only (offline)")
    mode.add_argument("--relink-only", action="store_true", help="use files already copied into docs (offline)")
    arg.add_argument("--missing-only", action="store_true", help="fetch only items with no local rendition")
    opts = arg.parse_args()
    catalog = json.loads((ROOT / "data/media-sources.json").read_text(encoding="utf-8"))["files"]
    docs = ROOT / "docs"
    mapping, counts = scan(catalog, docs)
    failures = 0
    if not opts.check:
        if not opts.relink_only:
            opener = build_opener(MediaRedirect())
            for row in catalog:
                url = row["url"]
                source = media_path(url)
                target = docs / source[1:]
                if present(target) or (opts.missing_only and source in mapping):
                    continue
                try:
                    if target.exists():
                        raise ValueError("Existing file has an unexpected signature; inspect it before replacing")
                    download(opener, url, target)
                    print(f"Saved {source}", flush=True)
                except (OSError, URLError, ValueError) as error:
                    failures += 1
                    print(f"{source}: {error}", file=sys.stderr, flush=True)
            mapping, counts = scan(catalog, docs)
        changed = relink(docs, ROOT / "data/urls.json", mapping)
        print(f"Updated HTML files: {changed}")
    print(f"Original: {counts['original']}, alternate size: {counts['variant']}, "
          f"remote only: {counts['remote']}")
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
