import json
import os
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

API_URL = "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&maxResults=50&playlistId={}"
PREVIOUS_URL = "https://shuwa.yuta25.com/videos.json"
JST = timezone(timedelta(hours=9))
PER_CHANNEL = 5
ATTEMPTS = 4


def parse_items(body, channel_id):
    return [
        {
            "id": i["contentDetails"]["videoId"],
            "title": i["snippet"]["title"],
            "published": i["contentDetails"]["videoPublishedAt"],
            "channel_id": channel_id,
        }
        for i in body["items"]
        if "videoPublishedAt" in i["contentDetails"]
    ]


def fetch_playlist(playlist_id, key, urlopen, sleep):
    req = urllib.request.Request(API_URL.format(playlist_id), headers={"X-Goog-Api-Key": key})
    for left in reversed(range(ATTEMPTS)):
        try:
            with urlopen(req, timeout=20) as res:
                return json.load(res)
        except OSError as e:
            if not left or getattr(e, "code", 500) < 500:
                raise
            sleep(1)


def fetch_channel(channel_id, key, urlopen=urllib.request.urlopen, sleep=time.sleep):
    # UU + チャンネル ID の UC 以降 = 全アップロード、UUSH + 同 = ショートのみ。ショートが無いチャンネルは UUSH が 404 になる
    uploads = parse_items(fetch_playlist("UU" + channel_id[2:], key, urlopen, sleep), channel_id)
    try:
        shorts = {v["id"] for v in parse_items(fetch_playlist("UUSH" + channel_id[2:], key, urlopen, sleep), channel_id)}
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        shorts = set()
    return [{**v, "short": v["id"] in shorts} for v in uploads]


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
            raise RuntimeError(f"{failures} of {len(channels)} channels failed")
        print(f"::warning::{failures} of {len(channels)} channels failed")
    return sorted(videos, key=lambda v: v["published"], reverse=True)


def jst_date(published):
    return datetime.fromisoformat(published).astimezone(JST).strftime("%Y-%m-%d")


def tags(ch):
    return [*ch.get("content", []), ch.get("sign", ""), ch.get("signer", "")]


def tag_spans(ch):
    return "".join(f'<span class="tag">{escape(t)}</span>' for t in tags(ch) if t)


def new_count(n):
    return f'<small class="new">新着 {n}</small>' if n else ""


def render(channels, videos, now=None):
    now = now or datetime.now(JST)
    by_id = {c["id"]: c for c in channels}
    filters = sorted({t for c in channels for t in [*c.get("content", []), c.get("sign", "")] if t})
    rows, new = {False: [], True: []}, {False: 0, True: 0}
    for v in videos:
        ch = by_id.get(v["channel_id"], {"name": "", "id": v["channel_id"]})
        vid = escape(v["id"])
        short = bool(v.get("short"))
        new[short] += now - datetime.fromisoformat(v["published"]) < timedelta(days=1)
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
    updated = now.astimezone(JST).strftime("%Y-%m-%d %H:%M")
    return TEMPLATE.format(
        buttons=buttons,
        videos="".join(rows[False]),
        shorts="".join(rows[True]),
        new_videos=new_count(new[False]),
        new_shorts=new_count(new[True]),
        channels=chan_rows,
        count=len(channels),
        updated=updated,
    )


TEMPLATE = (Path(__file__).parent / "template.html").read_text()


def main():
    channels = tomllib.loads(Path("channels.toml").read_text())["channel"]
    key = os.environ.get("YOUTUBE_API_KEY", "")
    on_pr = os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
    if not key and not on_pr:
        sys.exit("YOUTUBE_API_KEY is not set")
    videos = collect(channels, lambda cid: fetch_channel(cid, key), fetch_previous(), tolerate_outage=on_pr)
    out = Path("dist")
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(render(channels, videos))
    (out / "videos.json").write_text(json.dumps(videos, ensure_ascii=False))
    print(f"{len(videos)} videos from {len(channels)} channels")


if __name__ == "__main__":
    main()
