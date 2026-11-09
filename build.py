import sys
import tomllib
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
JST = timezone(timedelta(hours=9))


def parse_feed(xml):
    root = ET.fromstring(xml)
    return [
        {
            "id": e.findtext("yt:videoId", namespaces=NS),
            "title": e.findtext("a:title", namespaces=NS),
            "published": e.findtext("a:published", namespaces=NS),
            "channel_id": e.findtext("yt:channelId", namespaces=NS),
        }
        for e in root.findall("a:entry", NS)
    ]


def fetch_feed(channel_id):
    req = urllib.request.Request(FEED_URL.format(channel_id), headers={"User-Agent": "shuwawawawa-feed"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return parse_feed(res.read())


def collect(channels, fetch):
    videos, failures = [], 0
    for ch in channels:
        try:
            videos += fetch(ch["id"])
        except Exception as e:
            failures += 1
            print(f"skip {ch['id']}: {e}", file=sys.stderr)
    if channels and failures == len(channels):
        raise RuntimeError("every feed failed")
    return sorted(videos, key=lambda v: v["published"], reverse=True)


def jst_date(published):
    return datetime.fromisoformat(published).astimezone(JST).strftime("%Y-%m-%d")


def tags(ch):
    return [*ch.get("content", []), ch.get("sign", ""), ch.get("signer", "")]


def tag_spans(ch):
    return "".join(f'<span class="tag">{escape(t)}</span>' for t in tags(ch) if t)


def render(channels, videos):
    by_id = {c["id"]: c for c in channels}
    filters = sorted({t for c in channels for t in tags(c) if t})
    rows = []
    for v in videos:
        ch = by_id.get(v["channel_id"], {"name": "", "id": v["channel_id"]})
        vid = escape(v["id"])
        rows.append(
            f'<li class="video" data-tags="{escape(" ".join(tags(ch)))}">'
            f'<button class="thumb" data-id="{vid}" aria-label="{escape(v["title"])} を再生">'
            f'<img src="https://i.ytimg.com/vi/{vid}/mqdefault.jpg" alt="" loading="lazy" width="320" height="180"></button>'
            f'<div class="meta"><a class="title" href="https://www.youtube.com/watch?v={vid}">{escape(v["title"])}</a>'
            f'<p class="sub"><a href="https://www.youtube.com/channel/{escape(ch["id"])}">{escape(ch["name"])}</a>'
            f' · <time>{jst_date(v["published"])}</time></p></div></li>'
        )
    chan_rows = "".join(
        f'<li><a href="https://www.youtube.com/channel/{escape(c["id"])}">{escape(c["name"])}</a>'
        f'{tag_spans(c)}<p>{escape(c.get("note", ""))}</p></li>'
        for c in sorted(channels, key=lambda c: c["name"])
    )
    buttons = "".join(f'<button class="filter" aria-pressed="false">{escape(t)}</button>' for t in filters)
    updated = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    return TEMPLATE.format(buttons=buttons, rows="".join(rows), channels=chan_rows, count=len(channels), updated=updated)


TEMPLATE = (Path(__file__).parent / "template.html").read_text()


def main():
    channels = tomllib.loads(Path("channels.toml").read_text())["channel"]
    videos = collect(channels, fetch_feed)
    out = Path("dist")
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(render(channels, videos))
    print(f"{len(videos)} videos from {len(channels)} channels")


if __name__ == "__main__":
    main()
