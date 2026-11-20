#!/usr/bin/env python3
"""Create a reviewable publication-data directory from the chair's WordPress WXR.
Requires Python 3.11+ and uses only the standard library. No network access.

python scripts/import_publications.py --wxr /path/to/all.xml --output ../papers-review
The full-site WXR supplies the profile shortcodes and the six selected figures.
A media or publications WXR from the same export can be supplied in addition.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

WP = "{http://wordpress.org/export/1.2/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


def read_items(paths):
    items = {}
    for path in paths:
        for item in ET.parse(path).findall("./channel/item"):
            key = item.findtext(WP + "post_id", "")
            if not key.isdigit():
                continue
            previous = items.get(key)
            if previous is None or item.findtext(WP + "post_modified_gmt", "") > previous.findtext(WP + "post_modified_gmt", ""):
                items[key] = item
    return items


def public(item):
    return item.findtext(WP + "status") == "publish" and not item.findtext(WP + "post_password", "")


def meta(item):
    values = defaultdict(list)
    for field in item.findall(WP + "postmeta"):
        key = field.findtext(WP + "meta_key")
        value = field.findtext(WP + "meta_value", "")
        if key and value.strip():
            values[key].append(value)
    return values


def site_asset(url):
    parsed = urlsplit(url)
    if parsed.hostname in {"mlps-lab.de", "www.mlps-lab.de", "cmutschler.de", "www.cmutschler.de"}:
        return parsed.path
    return url


# WordPress stores image sizes in a serialized attachment metadata array.
# Read the named image-size records as text. No PHP is evaluated.
SIZE = re.compile(r's:\d+:"([^"]+)";a:\d+:\{s:4:"file";s:\d+:"([^"]+)";'
                  r's:5:"width";i:(\d+);s:6:"height";i:(\d+);')
DIMENSIONS = re.compile(r's:5:"width";i:(\d+);s:6:"height";i:(\d+);')


def attachment_image(item, size):
    attachment = item.findtext(WP + "attachment_url", "")
    if not attachment:
        raise ValueError("Attachment has no public URL")
    fields = meta(item)
    serialized = next(iter(fields["_wp_attachment_metadata"]), "")
    dimensions = DIMENSIONS.search(serialized)
    full = (0, 0, site_asset(attachment))
    if dimensions:
        full = (int(dimensions[1]), int(dimensions[2]), full[2])
    options = {name: (int(w), int(h), site_asset(urljoin(attachment, file)))
               for name, file, w, h in SIZE.findall(serialized)}
    width, height, src = options.get(size, full)
    image = {"src": src, "alt": next(iter(fields["_wp_attachment_image_alt"]), "")}
    if width and height:
        image.update(width=width, height=height)
        candidates = {}
        if full[0]:
            # Omit cropped thumbnails; use the same aspect ratio as the
            # displayed image. One pixel of resizing round-off is normal.
            for w, h, candidate in [*options.values(), full]:
                if abs(h - height * w / width) <= max(1, w / width):
                    candidates[f"{w}w"] = candidate
        if len(candidates) > 1:
            image["sizes"] = f"(max-width: {width}px) 100vw, {width}px"
            image["sources"] = candidates
    return image


class HighlightsParser(HTMLParser):
    """Extract the image ID and verbatim caption from each displayed figure."""
    def __init__(self):
        super().__init__()
        self.figures = []
        self.current = None
        self.in_caption = False

    def handle_starttag(self, tag, attrs):
        if tag == "figure":
            self.current = {"caption": ""}
        elif self.current is not None:
            if tag == "img":
                attributes = dict(attrs)
                self.current["src"] = attributes.get("src", "")
                match = re.search(r"\bwp-image-(\d+)\b", attributes.get("class", ""))
                self.current["id"] = match[1] if match else None
            if tag == "figcaption":
                self.in_caption = True

    def handle_data(self, text):
        if self.current is not None and self.in_caption:
            self.current["caption"] += text

    def handle_endtag(self, tag):
        if tag == "figcaption":
            self.in_caption = False
        elif tag == "figure" and self.current is not None:
            self.figures.append(self.current)
            self.current = None


def read_views(items):
    views, profile_ids, featured = {}, {}, []
    for item in items.values():
        if item.findtext(WP + "post_type") != "page" or not public(item):
            continue
        route = urlsplit(item.findtext("link", "")).path
        body = item.findtext(CONTENT, "")
        for shortcode in re.findall(r"\[pods\b([^\]]*)\]", body, re.I):
            attrs = {k: val for k, _, val in re.findall(r'''([\w-]+)\s*=\s*(["'])(.*?)\2''', shortcode, re.S)}
            if attrs.get("name") != "publication" or attrs.get("template") != "Publication Card":
                continue
            if attrs.get("orderby") != "year.meta_value DESC, t.post_title ASC":
                raise ValueError(f"Review the new publication sort definition on {route}")
            view = {"per_page": int(attrs["limit"]), "top_pager": attrs.get("pagination_location") == "both",
                    "pagination": "default" if attrs.get("pagination_type") == "paginate" else "advanced"}
            if "where" in attrs:
                match = re.fullmatch(r"lehrstuhl_autoren\.ID\s*=\s*(\d+)", attrs["where"])
                if not match:
                    raise ValueError(f"Review the new publication filter on {route}")
                view["profile"] = route.strip("/")
                profile_ids[match[1]] = view["profile"]
            views[route] = view
            if route == "/publications/":
                parser = HighlightsParser()
                parser.feed(body)
                featured = parser.figures
    if "/publications/" not in views:
        raise ValueError("Include the full-site WXR with the Publications page and person pages")
    return views, profile_ids, featured


def paper_from(item, items, profile_ids):
    fields = meta(item)
    get = lambda field: next(iter(fields[field]), "").strip()
    detail = urlsplit(item.findtext("link", "")).path
    paper = {"title": item.findtext("title", ""), "authors": [a.strip() for a in get("authors_text").split(",") if a.strip()],
             "date": get("year"), "venue": get("venue"), "detail_url": detail}
    people = fields["lehrstuhl_autoren"]
    if not people and get("_pods_lehrstuhl_autoren"):
        # Older Pods versions may store only the array; in this export the
        # individual WP relationship rows are also present.
        people = re.findall(r'i:\d+;i:(\d+);', get("_pods_lehrstuhl_autoren"))
    if set(people) - set(profile_ids):
        raise ValueError(f"Unrecognized profile relation on {detail}: {sorted(set(people) - set(profile_ids))}")
    paper["profiles"] = [profile_ids[key] for key in dict.fromkeys(people)]
    optional = {"pdf_url": "pdf_url", "doi": "doi", "description": "abstract", "bibtex": "bibtex"}
    for source, dest in optional.items():
        if value := get(source):
            paper[dest] = unescape(value) if source == "description" else value
    links = {label: get(field) for label, field in (("Website", "website_url"), ("Code", "code_url")) if get(field)}
    if links:
        paper["links"] = links
    if image_id := get("_thumbnail_id"):
        if image_id not in items:
            raise ValueError(f"Missing attachment {image_id} for {detail}; include the media WXR")
        image = attachment_image(items[image_id], "medium")
        image["class"] = "attachment-medium size-medium"
        paper["image"] = image
    return paper


def write_toml(path, record):
    def scalar(value):
        if isinstance(value, str):
            if "\n" in value and "'''" not in value and not value.endswith("'") and "\r" not in value:
                return "'''\n" + value + "'''"
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, list):
            return "[" + ", ".join(map(scalar, value)) + "]"
        if type(value) is int:
            return str(value)
        raise ValueError(f"Unsupported TOML scalar {value!r}")

    def key(name):
        return name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else scalar(name)

    lines = []
    def section(fields, prefix):
        if prefix:
            lines.extend(["", "[" + ".".join(prefix) + "]"])
        for name, value in fields.items():
            if not isinstance(value, dict):
                lines.append(f"{key(name)} = {scalar(value)}")
        for name, value in fields.items():
            if isinstance(value, dict):
                section(value, [*prefix, key(name)])
    section(record, [])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def import_files(paths, output):
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Choose an empty review directory: {output}")
    items = read_items(paths)
    views, profile_ids, figures = read_views(items)
    papers, titles = {}, defaultdict(list)
    for key, item in items.items():
        if item.findtext(WP + "post_type") != "publication" or not public(item):
            continue
        paper = paper_from(item, items, profile_ids)
        slug = item.findtext(WP + "post_name", "").strip()
        # The source post ID distinguishes colliding titles or truncated slugs.
        short = re.sub(r"[^\w-]+", "-", slug)[:72].strip("-")
        filename = f"{short}-{key}" if short else f"paper-{key}"
        papers[filename] = paper
        titles[paper["title"].casefold()].append(filename)
    if not papers:
        raise ValueError("No public publications were found")
    for position, fig in enumerate(figures, start=1):
        caption = " ".join(fig["caption"].split())
        title, _, citation = caption.rpartition(" (")
        keys = titles[title.casefold()] if citation.endswith(")") else titles[caption.casefold()]
        if len(keys) != 1:
            raise ValueError(f"Cannot unambiguously match highlighted paper {caption!r}")
        feature = {"position": position, "citation": citation[:-1]} if citation.endswith(")") else {"position": position}
        if fig.get("id") in items:
            image = attachment_image(items[fig["id"]], "full")
            image["class"] = f"wp-image-{fig['id']}"
            feature["image"] = image
        elif fig.get("src"):
            feature["image"] = {"src": site_asset(fig["src"]), "alt": ""}
        papers[keys[0]]["highlight"] = feature
    folder = output / "publications"
    folder.mkdir(parents=True, exist_ok=True)
    for name, paper in sorted(papers.items()):
        write_toml(folder / (name + ".toml"), paper)
    (output / "publication-views.json").write_text(json.dumps(views, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return papers, views


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wxr", type=Path, nargs="+", required=True, help="One full WXR plus any supplemental WXR files")
    parser.add_argument("--output", type=Path, required=True, help="New empty directory for review")
    args = parser.parse_args()
    papers, views = import_files(args.wxr, args.output)
    print(f"Imported {len(papers)} public papers and {len(views)} list views to {args.output}")


if __name__ == "__main__":
    main()
