import contextlib
import io
import json
import unittest

import build

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>テストch</title>
 <entry>
  <yt:videoId>aaa</yt:videoId>
  <yt:channelId>UC1</yt:channelId>
  <title>手話で&lt;自己紹介&gt;</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=aaa"/>
  <published>2026-11-01T00:00:00+00:00</published>
 </entry>
 <entry>
  <yt:videoId>bbb</yt:videoId>
  <yt:channelId>UC1</yt:channelId>
  <title>二本目</title>
  <link rel="alternate" href="https://www.youtube.com/shorts/bbb"/>
  <published>2026-10-01T00:00:00+00:00</published>
 </entry>
</feed>"""


def video(vid, published, channel_id="UC1"):
    return {"id": vid, "title": vid, "published": published, "channel_id": channel_id}


class ParseFeedTest(unittest.TestCase):
    def test_returns_every_entry(self):
        self.assertEqual([v["id"] for v in build.parse_feed(FEED)], ["aaa", "bbb"])

    def test_reads_title(self):
        self.assertEqual(build.parse_feed(FEED)[0]["title"], "手話で<自己紹介>")

    def test_reads_published(self):
        self.assertEqual(build.parse_feed(FEED)[0]["published"], "2026-11-01T00:00:00+00:00")

    def test_reads_channel_id(self):
        self.assertEqual(build.parse_feed(FEED)[0]["channel_id"], "UC1")

    def test_video_linked_as_shorts_is_short(self):
        self.assertTrue(build.parse_feed(FEED)[1]["short"])

    def test_video_linked_as_watch_is_not_short(self):
        self.assertFalse(build.parse_feed(FEED)[0]["short"])


class FetchFeedTest(unittest.TestCase):
    def urlopen(self, failures):
        calls = []

        def urlopen(req, timeout):
            calls.append(req)
            if len(calls) <= failures:
                raise OSError("HTTP Error 404: Not Found")
            return io.BytesIO(FEED.encode())

        return urlopen, calls

    def test_retries_until_feed_is_served(self):
        urlopen, _ = self.urlopen(failures=2)
        videos = build.fetch_feed("UC1", urlopen=urlopen, sleep=lambda s: None)
        self.assertEqual([v["id"] for v in videos], ["aaa", "bbb"])

    def test_gives_up_after_max_attempts(self):
        urlopen, calls = self.urlopen(failures=99)
        with self.assertRaises(OSError):
            build.fetch_feed("UC1", urlopen=urlopen, sleep=lambda s: None)
        self.assertEqual(len(calls), build.ATTEMPTS)

    def test_waits_between_attempts_only(self):
        urlopen, _ = self.urlopen(failures=99)
        waits = []
        with self.assertRaises(OSError):
            build.fetch_feed("UC1", urlopen=urlopen, sleep=waits.append)
        self.assertEqual(len(waits), build.ATTEMPTS - 1)


class CollectTest(unittest.TestCase):
    def test_sorts_newest_first_across_channels(self):
        feeds = {
            "UC1": [video("b", "2026-10-02"), video("e", "2026-09-01")],
            "UC2": [video("a", "2026-11-01", "UC2"), video("d", "2026-09-15", "UC2")],
            "UC3": [video("c", "2026-10-01", "UC3")],
        }
        result = build.collect([{"id": c} for c in feeds], feeds.get)
        self.assertEqual([v["id"] for v in result], ["a", "b", "c", "d", "e"])

    def test_keeps_only_latest_videos_per_channel(self):
        feed = [video(f"v{i}", f"2026-10-{20 - i:02d}") for i in range(8)]
        result = build.collect([{"id": "UC1"}], lambda cid: feed)
        self.assertEqual([v["id"] for v in result], ["v0", "v1", "v2", "v3", "v4"])

    def test_keeps_latest_shorts_apart_from_latest_videos(self):
        feed = [{**video(f"s{i}", f"2026-11-{20 - i:02d}"), "short": True} for i in range(7)]
        feed += [video(f"v{i}", f"2026-10-{20 - i:02d}") for i in range(7)]
        result = build.collect([{"id": "UC1"}], lambda cid: feed)
        self.assertEqual([v["id"] for v in result], [f"s{i}" for i in range(5)] + [f"v{i}" for i in range(5)])

    def test_skips_channel_whose_fetch_fails(self):
        def fetch(cid):
            if cid == "UC2":
                raise OSError("404")
            return [video("ok", "2026-11-01", cid)]

        result = build.collect([{"id": "UC1"}, {"id": "UC2"}], fetch)
        self.assertEqual([v["id"] for v in result], ["ok"])

    def fetch_only_uc3(self, cid):
        if cid != "UC3":
            raise OSError("404")
        return [video("new", "2026-11-02", cid)]

    def test_raises_when_most_fetches_fail_and_nothing_to_carry_over(self):
        with self.assertRaises(RuntimeError):
            build.collect([{"id": "UC1"}, {"id": "UC2"}, {"id": "UC3"}], self.fetch_only_uc3)

    def test_keeps_going_when_most_fetches_fail_but_previous_exists(self):
        previous = [video("kept", "2026-10-01", "UC1")]
        result = build.collect([{"id": "UC1"}, {"id": "UC2"}, {"id": "UC3"}], self.fetch_only_uc3, previous)
        self.assertEqual([v["id"] for v in result], ["new", "kept"])

    def test_raises_when_every_fetch_fails(self):
        def fetch(cid):
            raise OSError("down")

        with self.assertRaises(RuntimeError):
            build.collect([{"id": "UC1"}], fetch)

    def collect_through_outage(self, previous=()):
        def fetch(cid):
            raise OSError("down")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            videos = build.collect([{"id": "UC1"}], fetch, previous, tolerate_outage=True)
        return videos, out.getvalue()

    def test_returns_nothing_instead_of_raising_when_outage_is_tolerated(self):
        self.assertEqual(self.collect_through_outage()[0], [])

    def test_warns_when_outage_is_tolerated(self):
        self.assertIn("::warning::", self.collect_through_outage()[1])

    def fetch_only_uc1(self, cid):
        if cid != "UC1":
            raise OSError("404")
        return [video("new", "2026-11-02", cid)]

    def test_carries_over_previous_videos_of_failed_channel(self):
        previous = [video("kept", "2026-10-01", "UC2")]
        result = build.collect([{"id": "UC1"}, {"id": "UC2"}], self.fetch_only_uc1, previous)
        self.assertEqual([v["id"] for v in result], ["new", "kept"])

    def test_ignores_previous_videos_of_fetched_channel(self):
        previous = [video("old", "2026-10-01", "UC1")]
        result = build.collect([{"id": "UC1"}, {"id": "UC2"}], self.fetch_only_uc1, previous)
        self.assertEqual([v["id"] for v in result], ["new"])

    def test_drops_previous_videos_of_removed_channel(self):
        previous = [video("gone", "2026-10-01", "UC9")]
        result = build.collect([{"id": "UC1"}, {"id": "UC2"}], self.fetch_only_uc1, previous)
        self.assertEqual([v["id"] for v in result], ["new"])

    def test_raises_when_every_fetch_fails_even_with_previous(self):
        def fetch(cid):
            raise OSError("down")

        with self.assertRaises(RuntimeError):
            build.collect([{"id": "UC1"}], fetch, [video("kept", "2026-10-01")])

    def test_carries_over_every_channel_when_outage_is_tolerated(self):
        result, _ = self.collect_through_outage([video("kept", "2026-10-01")])
        self.assertEqual([v["id"] for v in result], ["kept"])


class FetchPreviousTest(unittest.TestCase):
    def test_reads_published_videos(self):
        videos = [video("a", "2026-11-01")]
        urlopen = lambda url, timeout: io.BytesIO(json.dumps(videos).encode())
        self.assertEqual(build.fetch_previous(urlopen), videos)

    def test_returns_nothing_when_unavailable(self):
        def urlopen(url, timeout):
            raise OSError("HTTP Error 404: Not Found")

        self.assertEqual(build.fetch_previous(urlopen), [])

    def test_returns_nothing_when_not_json(self):
        urlopen = lambda url, timeout: io.BytesIO(b"<html>")
        self.assertEqual(build.fetch_previous(urlopen), [])


class RenderTest(unittest.TestCase):
    channels = [{"id": "UC1", "name": "テストch", "content": ["学習"], "sign": "日本手話", "signer": "ろう者", "note": "<b>"}]

    def html(self):
        return build.render(
            self.channels,
            [
                {"id": "aaa", "title": "<script>", "published": "2026-11-01T00:00:00+00:00", "channel_id": "UC1"},
                {"id": "sss", "title": "短い", "published": "2026-11-02T00:00:00+00:00", "channel_id": "UC1", "short": True},
            ],
        )

    def list_of(self, name):
        return self.html().split(f'<ul data-view="{name}"')[1].split("</ul>")[0]

    def test_lists_short_under_shorts(self):
        self.assertIn('data-id="sss"', self.list_of("shorts"))

    def test_leaves_short_out_of_videos(self):
        self.assertNotIn('data-id="sss"', self.list_of("videos"))

    def test_lists_video_without_short_flag_under_videos(self):
        self.assertIn('data-id="aaa"', self.list_of("videos"))

    def test_links_short_to_youtube_shorts(self):
        self.assertIn("https://www.youtube.com/shorts/sss", self.html())

    def test_video_has_watched_checkbox(self):
        self.assertIn('<input type="checkbox" class="watched" value="aaa"', self.html())

    def test_channel_carries_tags_for_filtering(self):
        self.assertIn('data-tags="学習 日本手話 ろう者"', self.list_of("channels"))

    def test_escapes_video_title(self):
        self.assertIn("&lt;script&gt;", self.html())

    def test_escapes_channel_note(self):
        self.assertNotIn("<b>", self.html())

    def test_links_video_to_youtube(self):
        self.assertIn("https://www.youtube.com/watch?v=aaa", self.html())

    def test_shows_channel_name_on_video(self):
        self.assertIn("テストch", self.html())

    def test_shows_signer_when_published(self):
        self.assertIn("ろう者", self.html())

    def test_signer_is_not_a_filter(self):
        self.assertNotIn('aria-pressed="false">ろう者<', self.html())

    def test_content_is_a_filter(self):
        self.assertIn('aria-pressed="false">学習<', self.html())


if __name__ == "__main__":
    unittest.main()
