import json
import os
import sys
import time
import tomllib
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
PREVIOUS_URL = "https://shuwa.yuta25.com/videos.json"
JST = timezone(timedelta(hours=9))
PER_CHANNEL = 5
ATTEMPTS = 4


def parse_feed(xml):
    root = ET.fromstring(xml)
    return [
        {
            "id": e.findtext("yt:videoId", namespaces=NS),
            "title": e.findtext("a:title", namespaces=NS),
            "published": e.findtext("a:published", namespaces=NS),
            "channel_id": e.findtext("yt:channelId", namespaces=NS),
            "short": any("/shorts/" in link.get("href", "") for link in e.findall("a:link", NS)),
        }
        for e in root.findall("a:entry", NS)
    ]


def fetch_feed(channel_id, urlopen=urllib.request.urlopen, sleep=time.sleep):
    req = urllib.request.Request(FEED_URL.format(channel_id), headers={"User-Agent": "shuwawawawa-feed"})
    for left in reversed(range(ATTEMPTS)):
        try:
            with urlopen(req, timeout=20) as res:
                return parse_feed(res.read())
        except OSError:
            if not left:
                raise
            sleep(1)


def fetch_previous(urlopen=urllib.request.urlopen):
    try:
        with urlopen(PREVIOUS_URL, timeout=20) as res:
            return json.load(res)
    except (OSError, ValueError):
        return []


def latest(videos):
    newest = sorted(videos, key=lambda v: v["published"], reverse=True)
    return [v for short in (False, True) for v in [v for v in newest if bool(v.get("short")) is short][:PER_CHANNEL]]


def collect(channels, fetch, previous=(), tolerate_outage=False):
    videos, failures = [], 0
    for ch in channels:
        try:
            videos += latest(fetch(ch["id"]))
        except Exception as e:
            failures += 1
            videos += [v for v in previous if v["channel_id"] == ch["id"]]
            print(f"skip {ch['id']}: {e}", file=sys.stderr)
    if failures and (failures == len(channels) or not previous and failures * 2 > len(channels)):
        if not tolerate_outage:
            raise RuntimeError(f"{failures} of {len(channels)} feeds failed")
        print(f"::warning::{failures} of {len(channels)} feeds failed")
    return sorted(videos, key=lambda v: v["published"], reverse=True)


def jst_date(published):
    return datetime.fromisoformat(published).astimezone(JST).strftime("%Y-%m-%d")


def tags(ch):
    return [*ch.get("content", []), ch.get("sign", ""), ch.get("signer", "")]


def tag_spans(ch):
    return "".join(f'<span class="tag">{escape(t)}</span>' for t in tags(ch) if t)


def render(channels, videos):
    by_id = {c["id"]: c for c in channels}
    filters = sorted({t for c in channels for t in [*c.get("content", []), c.get("sign", "")] if t})
    rows = {False: [], True: []}
    for v in videos:
        ch = by_id.get(v["channel_id"], {"name": "", "id": v["channel_id"]})
        vid = escape(v["id"])
        short = bool(v.get("short"))
        # 縦長の正式サムネイル oar2.jpg は無い動画があるので、必ずある冒頭フレームを使う
        rows[short].append(
            f'<li class="video" data-tags="{escape(" ".join(tags(ch)))}">'
            f'<button class="thumb" data-id="{vid}" aria-label="{escape(v["title"])} を再生">'
            f'<img src="https://i.ytimg.com/vi/{vid}/{"frame0" if short else "mqdefault"}.jpg" alt="" loading="lazy"></button>'
            f'<a class="title" href="https://www.youtube.com/{"shorts/" if short else "watch?v="}{vid}">{escape(v["title"])}</a>'
            f'<p class="sub"><a href="https://www.youtube.com/channel/{escape(ch["id"])}">{escape(ch["name"])}</a>'
            f' · <time>{jst_date(v["published"])}</time></p>'
            f'<label class="seen"><input type="checkbox" class="watched" value="{vid}" aria-label="{escape(v["title"])} を視聴済みにする"> 視聴済み</label></li>'
        )
    chan_rows = "".join(
        f'<li data-tags="{escape(" ".join(tags(c)))}"><a href="https://www.youtube.com/channel/{escape(c["id"])}">{escape(c["name"])}</a>'
        f'{tag_spans(c)}<p>{escape(c.get("note", ""))}</p></li>'
        for c in sorted(channels, key=lambda c: c["name"])
    )
    buttons = "".join(f'<button class="filter" aria-pressed="false">{escape(t)}</button>' for t in filters)
    updated = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    return TEMPLATE.format(
        buttons=buttons,
        videos="".join(rows[False]),
        shorts="".join(rows[True]),
        channels=chan_rows,
        count=len(channels),
        updated=updated,
    )


TEMPLATE = (Path(__file__).parent / "template.html").read_text()


def main():
    channels = tomllib.loads(Path("channels.toml").read_text())["channel"]
    videos = collect(channels, fetch_feed, fetch_previous(), tolerate_outage=os.environ.get("GITHUB_EVENT_NAME") == "pull_request")
    out = Path("dist")
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(render(channels, videos))
    (out / "videos.json").write_text(json.dumps(videos, ensure_ascii=False))
    print(f"{len(videos)} videos from {len(channels)} channels")


if __name__ == "__main__":
    main()
