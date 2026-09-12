#!/usr/bin/env python3
"""Basic tests for morning_summary.py.

Network-touching functions (get_weather, get_sports, get_news) are tested by
mocking morning_summary.fetch, so the suite runs offline and fast.
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import morning_summary as ms


class ScoreOfTests(unittest.TestCase):
    def test_dict_score(self):
        self.assertEqual(ms.score_of({"score": {"displayValue": "24"}}), "24")

    def test_plain_score(self):
        self.assertEqual(ms.score_of({"score": "24"}), "24")

    def test_missing_score(self):
        self.assertEqual(ms.score_of({}), "?")


class StripHtmlTests(unittest.TestCase):
    def test_removes_tags(self):
        self.assertEqual(ms.strip_html("<p>Hello <b>world</b></p>"), "Hello world")

    def test_handles_none(self):
        self.assertEqual(ms.strip_html(None), "")


class FormatGameTests(unittest.TestCase):
    def _competitors(self, home_score=None, away_score=None, winner_id=None):
        home = {"homeAway": "home", "id": "259", "team": {"shortDisplayName": "Hokies"}}
        away = {"homeAway": "away", "id": "999", "team": {"shortDisplayName": "Rival"}}
        if home_score is not None:
            home["score"] = home_score
        if away_score is not None:
            away["score"] = away_score
        if winner_id is not None:
            home["winner"] = winner_id == "259"
            away["winner"] = winner_id == "999"
        return [home, away]

    def test_completed_win(self):
        dt = datetime(2024, 9, 7, 17, 0, tzinfo=timezone.utc)
        comp = {
            "status": {"type": {"completed": True}},
            "competitors": self._competitors("30", "10", winner_id="259"),
        }
        game = ms.format_game(dt, comp, "Rival at Hokies", "259")
        self.assertTrue(game["completed"])
        self.assertEqual(game["outcome"], "W")
        self.assertEqual(game["text"], "Rival 10 @ Hokies 30")

    def test_completed_loss(self):
        dt = datetime(2024, 9, 7, 17, 0, tzinfo=timezone.utc)
        comp = {
            "status": {"type": {"completed": True}},
            "competitors": self._competitors("10", "30", winner_id="999"),
        }
        game = ms.format_game(dt, comp, "Rival at Hokies", "259")
        self.assertEqual(game["outcome"], "L")

    def test_tie(self):
        dt = datetime(2024, 9, 7, 17, 0, tzinfo=timezone.utc)
        comp = {
            "status": {"type": {"completed": True}},
            "competitors": self._competitors("14", "14"),
        }
        game = ms.format_game(dt, comp, "Rival at Hokies", "259")
        self.assertEqual(game["outcome"], "T")

    def test_upcoming_game(self):
        dt = datetime(2024, 9, 7, 17, 0, tzinfo=timezone.utc)
        comp = {"status": {"type": {"completed": False}}, "competitors": self._competitors()}
        game = ms.format_game(dt, comp, "Rival at Hokies", "259")
        self.assertFalse(game["completed"])
        self.assertIsNone(game["outcome"])
        self.assertEqual(game["text"], "Rival @ Hokies")

    def test_malformed_competitors_falls_back_to_name(self):
        dt = datetime(2024, 9, 7, 17, 0, tzinfo=timezone.utc)
        comp = {"status": {"type": {"completed": False}}, "competitors": []}
        game = ms.format_game(dt, comp, "Rival at Hokies", "259")
        self.assertEqual(game["text"], "Rival at Hokies")


class GetWeatherTests(unittest.TestCase):
    GEO = b'{"places": [{"latitude": "35.05", "longitude": "-80.83", "place name": "Charlotte", "state abbreviation": "NC"}]}'
    FORECAST = (
        b'{"current": {"temperature_2m": 71.4, "apparent_temperature": 70.1, '
        b'"weather_code": 1, "wind_speed_10m": 5.2}, '
        b'"daily": {"temperature_2m_max": [78.0], "temperature_2m_min": [58.0], '
        b'"precipitation_probability_max": [10], "sunrise": ["2024-09-07T07:03"], '
        b'"sunset": ["2024-09-07T19:41"]}}'
    )

    @patch.object(ms, "fetch")
    def test_ok_path(self, mock_fetch):
        mock_fetch.side_effect = [self.GEO, self.FORECAST]
        weather = ms.get_weather()
        self.assertTrue(weather["ok"])
        self.assertEqual(weather["city"], "Charlotte")
        self.assertEqual(weather["temp"], 71)
        self.assertEqual(weather["condition"], "Mostly clear")
        self.assertEqual(weather["sunrise"], "07:03")

    @patch.object(ms, "fetch")
    def test_error_path(self, mock_fetch):
        mock_fetch.side_effect = OSError("timed out")
        weather = ms.get_weather()
        self.assertFalse(weather["ok"])
        self.assertIn("timed out", weather["error"])


class GetSportsTests(unittest.TestCase):
    SCHEDULE = b"""{
        "events": [
            {
                "date": "2024-09-07T17:00Z",
                "name": "Rival at Hokies",
                "competitions": [{
                    "status": {"type": {"completed": true}},
                    "competitors": [
                        {"homeAway": "home", "id": "259", "team": {"shortDisplayName": "Hokies"}, "score": "30", "winner": true},
                        {"homeAway": "away", "id": "999", "team": {"shortDisplayName": "Rival"}, "score": "10", "winner": false}
                    ]
                }]
            },
            {
                "date": "2024-09-14T17:00Z",
                "name": "Hokies at Next",
                "competitions": [{
                    "status": {"type": {"completed": false}},
                    "competitors": [
                        {"homeAway": "away", "id": "259", "team": {"shortDisplayName": "Hokies"}},
                        {"homeAway": "home", "id": "111", "team": {"shortDisplayName": "Next"}}
                    ]
                }]
            }
        ]
    }"""

    @patch.object(ms, "fetch")
    def test_ok_path(self, mock_fetch):
        mock_fetch.return_value = self.SCHEDULE
        results = ms.get_sports()
        self.assertEqual(len(results), len(ms.SPORTS_TEAMS))
        entry = results[0]
        self.assertIsNone(entry["error"])
        self.assertEqual(entry["last"]["outcome"], "W")
        self.assertIsNotNone(entry["next"])
        self.assertEqual(len(entry["schedule"]), 2)

    @patch.object(ms, "fetch")
    def test_error_path(self, mock_fetch):
        mock_fetch.side_effect = OSError("boom")
        results = ms.get_sports()
        self.assertTrue(all(r["error"] for r in results))


class GetNewsTests(unittest.TestCase):
    RSS = b"""<?xml version="1.0"?>
    <rss><channel>
        <item><title>Story &lt;b&gt;One&lt;/b&gt;</title><link>https://example.com/1</link></item>
        <item><title>Story Two</title><link>https://example.com/2</link></item>
        <item><title>Story Three</title><link>https://example.com/3</link></item>
        <item><title>Story Four</title><link>https://example.com/4</link></item>
        <item><title>Story Five</title><link>https://example.com/5</link></item>
    </channel></rss>"""

    @patch.object(ms, "fetch")
    def test_ok_path_caps_at_four_items(self, mock_fetch):
        mock_fetch.return_value = self.RSS
        results = ms.get_news()
        self.assertEqual(len(results), len(ms.NEWS_FEEDS))
        entry = results[0]
        self.assertIsNone(entry["error"])
        self.assertEqual(len(entry["items"]), 4)
        self.assertEqual(entry["items"][0]["title"], "Story One")

    @patch.object(ms, "fetch")
    def test_error_path(self, mock_fetch):
        mock_fetch.side_effect = OSError("boom")
        results = ms.get_news()
        self.assertTrue(all(r["error"] and not r["items"] for r in results))


class RenderTests(unittest.TestCase):
    def _ok_weather(self):
        return {
            "ok": True, "city": "Charlotte", "state": "NC", "temp": 71,
            "feels_like": 70, "wind": 5, "condition": "Mostly clear",
            "hi": 78, "lo": 58, "precip": 10, "sunrise": "07:03", "sunset": "19:41",
        }

    def _ok_sports(self):
        win_game = {"date": "Sat Sep 7", "text": "Rival 10 @ Hokies 30", "outcome": "W", "time": None}
        next_game = {"date": "Sat Sep 14", "text": "Hokies @ Next", "outcome": None, "time": "1:00 PM ET"}
        return [{
            "label": "Virginia Tech Football", "error": None,
            "last": win_game, "next": next_game, "schedule": [win_game, next_game],
        }]

    def _ok_news(self):
        return [{"label": "Tech", "error": None, "items": [{"title": "Story", "link": "https://example.com"}]}]

    def test_all_sections_ok(self):
        html = ms.render(self._ok_weather(), self._ok_sports(), self._ok_news())
        self.assertIn("Charlotte Morning Briefing", html)
        self.assertIn("71", html)
        self.assertIn("Virginia Tech Football", html)
        self.assertIn("tag-win", html)
        self.assertIn("Full schedule (1-0)", html)
        self.assertIn("Story", html)

    def test_error_sections(self):
        weather = {"ok": False, "error": "timed out"}
        sports = [{"label": "Panthers", "error": "boom", "last": None, "next": None, "schedule": []}]
        news = [{"label": "Tech", "error": "boom", "items": []}]
        html = ms.render(weather, sports, news)
        self.assertIn("Weather unavailable", html)
        self.assertIn("Unavailable (boom)", html)
        self.assertIn("Feed unavailable.", html)


if __name__ == "__main__":
    unittest.main()
