#!/usr/bin/env python3
"""Fetch weather, sports, and news, and render the Charlotte morning briefing
as a standalone HTML fragment (no dependencies beyond the Python standard
library, so it runs anywhere without a pip install)."""

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

ZIP_CODE = "28277"
EASTERN = ZoneInfo("America/New_York")
OUTPUT_PATH = Path(__file__).parent / "output" / "briefing.html"

SPORTS_TEAMS = [
    {"label": "Virginia Tech Football", "sport": "football/college-football", "team_id": "259"},
    {"label": "Carolina Panthers", "sport": "football/nfl", "team_id": "car"},
    {"label": "Virginia Tech Basketball", "sport": "basketball/mens-college-basketball", "team_id": "259"},
]

NEWS_FEEDS = [
    {"label": "Tech", "url": "https://techcrunch.com/feed/"},
    {"label": "FinTech", "url": "https://www.finextra.com/rss/headlines.aspx"},
    {"label": "Finance", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
    {"label": "Wealth Management", "url": "https://www.wealthmanagement.com/rss.xml"},
    {"label": "Reddit News", "url": "https://www.reddit.com/r/news/top/.rss?limit=5&t=day"},
]

ATOM_NS = "{http://www.w3.org/2005/Atom}"

WEATHER_CODES = {
    0: "Clear sky", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Rain showers", 81: "Rain showers", 82: "Violent rain showers",
    95: "Thunderstorms", 96: "Thunderstorms w/ hail", 99: "Severe thunderstorms",
}


def fetch(url, timeout=10, browser_ua=True):
    # Some RSS hosts (Finextra, WealthManagement.com) 403 the bare Python UA and
    # need to look like a browser; ESPN's API does the opposite and 403s any
    # *custom* UA, only allowing urllib's default. Both quirks are handled here.
    headers = {"User-Agent": "Mozilla/5.0 (compatible; morning-summary/1.0)"} if browser_ua else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_weather():
    try:
        geo = json.loads(fetch(f"https://api.zippopotam.us/us/{ZIP_CODE}"))
        place = geo["places"][0]
        lat, lon = place["latitude"], place["longitude"]
        city, state = place["place name"], place["state abbreviation"]
        params = (
            f"latitude={lat}&longitude={lon}&temperature_unit=fahrenheit&wind_speed_unit=mph"
            "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"
            "&timezone=auto&forecast_days=1"
        )
        data = json.loads(fetch(f"https://api.open-meteo.com/v1/forecast?{params}"))
        cur, daily = data["current"], data["daily"]
        return {
            "ok": True,
            "city": city, "state": state,
            "temp": round(cur["temperature_2m"]),
            "feels_like": round(cur["apparent_temperature"]),
            "wind": round(cur["wind_speed_10m"]),
            "condition": WEATHER_CODES.get(cur["weather_code"], "—"),
            "hi": round(daily["temperature_2m_max"][0]),
            "lo": round(daily["temperature_2m_min"][0]),
            "precip": daily["precipitation_probability_max"][0],
            "sunrise": daily["sunrise"][0][-5:],
            "sunset": daily["sunset"][0][-5:],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def score_of(c):
    s = c.get("score", "?")
    return s.get("displayValue", "?") if isinstance(s, dict) else s


def format_game(dt, comp, name, team_id):
    et = dt.astimezone(EASTERN)
    completed = comp.get("status", {}).get("type", {}).get("completed", False)
    competitors = comp.get("competitors", [])
    game = {
        "dt": dt,
        "date": et.strftime("%a %b %-d"),
        "time": et.strftime("%-I:%M %p ET") if comp.get("timeValid", True) else "Time TBD",
        "completed": completed,
        "outcome": None,  # "W" / "L" / "T" once known
        "text": name,
    }
    try:
        home = next(c for c in competitors if c.get("homeAway") == "home")
        away = next(c for c in competitors if c.get("homeAway") == "away")
        h_name, a_name = home["team"]["shortDisplayName"], away["team"]["shortDisplayName"]
        if completed:
            h_score, a_score = score_of(home), score_of(away)
            game["text"] = f"{a_name} {a_score} @ {h_name} {h_score}"
            ours = next((c for c in competitors if str(c.get("id")) == str(team_id)), None)
            if ours is not None:
                game["outcome"] = "W" if ours.get("winner") else ("T" if h_score == a_score else "L")
        else:
            game["text"] = f"{a_name} @ {h_name}"
    except Exception:
        pass
    return game


def get_sports():
    results = []
    for team in SPORTS_TEAMS:
        entry = {"label": team["label"], "last": None, "next": None, "schedule": [], "error": None}
        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/{team['sport']}/teams/{team['team_id']}/schedule"
            data = json.loads(fetch(url, browser_ua=False))
            games = []
            for e in data.get("events", []):
                dt = datetime.strptime(e["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
                comp = e.get("competitions", [{}])[0]
                games.append(format_game(dt, comp, e.get("name"), team["team_id"]))
            games.sort(key=lambda g: g["dt"])
            entry["schedule"] = games
            past = [g for g in games if g["completed"]]
            future = [g for g in games if not g["completed"]]
            if past:
                entry["last"] = past[-1]
            if future:
                entry["next"] = future[0]
        except Exception as ex:
            entry["error"] = str(ex)
        results.append(entry)
    return results


def strip_html(s):
    return re.sub("<[^<]+?>", "", s or "").strip()


def get_news():
    results = []
    for feed in NEWS_FEEDS:
        entry = {"label": feed["label"], "items": [], "error": None}
        try:
            root = ET.fromstring(fetch(feed["url"]))
            items = root.findall(".//item")
            if items:
                for it in items[:4]:
                    entry["items"].append({
                        "title": strip_html(it.findtext("title", "")),
                        "link": (it.findtext("link", "") or "").strip(),
                    })
            else:
                # Reddit (and other Atom feeds) use <entry>/<link href="…">
                # instead of RSS's <item>/<link>text</link>.
                for it in root.findall(f".//{ATOM_NS}entry")[:4]:
                    link = it.find(f"{ATOM_NS}link")
                    entry["items"].append({
                        "title": strip_html(it.findtext(f"{ATOM_NS}title", "")),
                        "link": ((link.get("href") if link is not None else "") or "").strip(),
                    })
        except Exception as ex:
            entry["error"] = str(ex)
        results.append(entry)
    return results


def render(weather, sports, news):
    today = datetime.now(EASTERN).strftime("%A, %B %-d, %Y")

    # --- weather ---
    if weather["ok"]:
        weather_html = f"""
        <div class="weather">
          <div class="weather-temp">{weather['temp']}<span class="deg">&deg;</span></div>
          <div class="weather-detail">
            <div class="weather-condition">{escape(weather['condition'])}</div>
            <div class="weather-sub">Feels {weather['feels_like']}&deg; &middot; H{weather['hi']}&deg; L{weather['lo']}&deg; &middot; {weather['precip']}% precip &middot; wind {weather['wind']} mph</div>
            <div class="weather-sub">Sunrise {weather['sunrise']} &middot; Sunset {weather['sunset']}</div>
          </div>
        </div>"""
        weather_loc = f"{escape(weather['city'])}, {escape(weather['state'])} {ZIP_CODE}"
    else:
        weather_html = f'<p class="error">Weather unavailable ({escape(weather["error"])}).</p>'
        weather_loc = f"Charlotte, NC {ZIP_CODE}"

    # --- sports ---
    OUTCOME_CLASS = {"W": "tag-win", "L": "tag-loss", "T": "tag-tie"}
    sport_rows = []
    for s in sports:
        if s["error"]:
            sport_rows.append(f'<div class="item"><h3>{escape(s["label"])}</h3><p class="error">Unavailable ({escape(s["error"])}).</p></div>')
            continue

        parts = []
        if s["last"]:
            tag = f' <span class="tag {OUTCOME_CLASS.get(s["last"]["outcome"], "")}">{s["last"]["outcome"]}</span>' if s["last"]["outcome"] else ""
            parts.append(f'<div class="line"><span class="line-date">{s["last"]["date"]}</span> {escape(s["last"]["text"])}{tag}</div>')
        if s["next"]:
            parts.append(f'<div class="line line-next"><span class="line-date">{s["next"]["date"]}, {s["next"]["time"]}</span> {escape(s["next"]["text"])}</div>')
        if not parts:
            parts.append('<p class="muted">No games scheduled.</p>')

        accordion = ""
        if s["schedule"]:
            wins = sum(1 for g in s["schedule"] if g["outcome"] == "W")
            losses = sum(1 for g in s["schedule"] if g["outcome"] == "L")
            record = f" ({wins}-{losses})" if (wins or losses) else ""
            rows = "".join(
                f'<li><span class="line-date">{g["date"]}</span> {escape(g["text"])}'
                + (f' <span class="tag {OUTCOME_CLASS.get(g["outcome"], "")}">{g["outcome"]}</span>' if g["outcome"] else f' <span class="sched-time">{g["time"]}</span>')
                + "</li>"
                for g in s["schedule"]
            )
            accordion = f"""<details class="schedule">
              <summary>Full schedule{record} &middot; {len(s['schedule'])} games</summary>
              <ul>{rows}</ul>
            </details>"""

        sport_rows.append(f'<div class="item"><h3>{escape(s["label"])}</h3>{"".join(parts)}{accordion}</div>')

    # --- news ---
    news_rows = []
    for n in news:
        if n["error"] or not n["items"]:
            body = '<p class="error">Feed unavailable.</p>'
        else:
            lis = "".join(
                f'<li><a href="{escape(it["link"])}">{escape(it["title"])}</a></li>' for it in n["items"]
            )
            body = f"<ul>{lis}</ul>"
        news_rows.append(f'<div class="item"><h3>{escape(n["label"])}</h3>{body}</div>')

    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlotte Morning Briefing</title>
<link rel="manifest" href="manifest.json">
<link rel="icon" href="icons/icon-192.png" type="image/png">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Charlotte AM">
<meta name="theme-color" content="#F4F6F8">
<meta name="theme-color" content="#10151F" media="(prefers-color-scheme: dark)">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,500;0,600;1,500&family=Source+Sans+3:wght@400;600&family=IBM+Plex+Mono:wght@500;600&display=swap">
<style>
  :root {{
    --bg: #F4F6F8;
    --surface: #FFFFFF;
    --ink: #1A2233;
    --muted: #5B6472;
    --accent: #35597A;
    --gold: #B8863C;
    --line: #DDE3E8;
    --good: #2F7D5D;
    --bad: #B23B3B;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #10151F;
      --surface: #1A2130;
      --ink: #E8ECF1;
      --muted: #96A1AF;
      --accent: #6FA0C4;
      --gold: #D9A857;
      --line: #2A323F;
      --good: #4FAE84;
      --bad: #D4736C;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #10151F;
    --surface: #1A2130;
    --ink: #E8ECF1;
    --muted: #96A1AF;
    --accent: #6FA0C4;
    --gold: #D9A857;
    --line: #2A323F;
    --good: #4FAE84;
    --bad: #D4736C;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg);
    color: var(--ink);
    font-family: "Source Sans 3", system-ui, sans-serif;
    padding: 0 20px 48px;
    max-width: 980px;
    margin: 0 auto;
  }}
  a {{ color: var(--accent); }}
  .masthead {{
    padding-block: 28px 18px;
    border-bottom: 2px solid var(--ink);
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }}
  .masthead-id {{
    display: flex;
    align-items: center;
    gap: 14px;
  }}
  .masthead-id .mark {{
    width: 44px;
    height: 44px;
    flex: none;
  }}
  .masthead h1 {{
    font-family: "Newsreader", Georgia, serif;
    font-weight: 600;
    font-size: clamp(1.7rem, 4vw, 2.4rem);
    margin: 0;
    text-wrap: balance;
  }}
  .masthead .kicker {{
    font-family: "IBM Plex Mono", monospace;
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--muted);
    margin-top: 4px;
  }}
  .masthead .meta {{
    font-family: "IBM Plex Mono", monospace;
    font-size: 0.8rem;
    color: var(--muted);
    text-align: right;
  }}
  .weather {{
    display: flex;
    align-items: center;
    gap: 24px;
    padding-block: 22px;
    border-bottom: 1px solid var(--line);
  }}
  .weather-temp {{
    font-family: "IBM Plex Mono", monospace;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    font-size: 4rem;
    color: var(--gold);
    line-height: 1;
  }}
  .weather-temp .deg {{ font-size: 2rem; vertical-align: top; }}
  .weather-condition {{
    font-family: "Newsreader", Georgia, serif;
    font-size: 1.2rem;
    font-style: italic;
  }}
  .weather-sub {{
    font-family: "IBM Plex Mono", monospace;
    font-variant-numeric: tabular-nums;
    font-size: 0.82rem;
    color: var(--muted);
    margin-top: 4px;
  }}
  .weather-loc {{
    font-size: 0.8rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-top: 4px;
  }}
  .sections {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 0;
    margin-top: 8px;
  }}
  .section {{
    padding-block: 22px;
    border-bottom: 1px solid var(--line);
  }}
  .section + .section {{ border-left: 1px solid var(--line); padding-left: 24px; }}
  @media (max-width: 700px) {{
    .section + .section {{ border-left: none; padding-left: 0; }}
  }}
  .section > h2 {{
    font-family: "Newsreader", Georgia, serif;
    font-weight: 600;
    font-size: 1rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--accent);
    margin: 0 0 14px;
  }}
  .item + .item {{ margin-top: 18px; padding-top: 18px; border-top: 1px dashed var(--line); }}
  .item h3 {{
    font-size: 0.95rem;
    font-weight: 600;
    margin: 0 0 6px;
  }}
  .line {{ font-size: 0.9rem; }}
  .line-next {{ color: var(--muted); }}
  .line-date {{
    font-family: "IBM Plex Mono", monospace;
    font-variant-numeric: tabular-nums;
    font-size: 0.78rem;
    color: var(--muted);
    margin-right: 6px;
  }}
  .tag {{
    font-family: "IBM Plex Mono", monospace;
    font-size: 0.7rem;
    font-weight: 600;
    border-radius: 3px;
    padding: 1px 5px;
    margin-left: 4px;
  }}
  .tag-win {{ color: var(--good); border: 1px solid var(--good); }}
  .tag-loss {{ color: var(--bad); border: 1px solid var(--bad); }}
  .tag-tie {{ color: var(--muted); border: 1px solid var(--muted); }}
  .sched-time {{
    font-family: "IBM Plex Mono", monospace;
    font-variant-numeric: tabular-nums;
    font-size: 0.78rem;
    color: var(--muted);
  }}
  details.schedule {{ margin-top: 10px; }}
  details.schedule summary {{
    cursor: pointer;
    font-size: 0.8rem;
    color: var(--accent);
    font-weight: 600;
    list-style: none;
  }}
  details.schedule summary::-webkit-details-marker {{ display: none; }}
  details.schedule summary::before {{ content: "▸ "; display: inline-block; transition: transform 0.15s ease; }}
  details.schedule[open] summary::before {{ transform: rotate(90deg); }}
  details.schedule ul {{
    margin-top: 10px;
    padding-left: 0;
    list-style: none;
    max-height: 260px;
    overflow-y: auto;
  }}
  details.schedule li {{
    padding: 5px 0;
    border-top: 1px dashed var(--line);
  }}
  details.schedule li:first-child {{ border-top: none; }}
  ul {{ margin: 0; padding-left: 1.1em; }}
  li {{ font-size: 0.9rem; margin-bottom: 8px; line-height: 1.4; }}
  .muted {{ color: var(--muted); font-size: 0.88rem; }}
  .error {{ color: var(--bad); font-size: 0.85rem; }}
  code {{ font-family: "IBM Plex Mono", monospace; font-size: 0.85em; }}
</style>

<div class="masthead">
  <div class="masthead-id">
    <svg class="mark" viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="20" fill="#1A2233" />
      <path d="M 30.49 27.34 A 12.8 12.8 0 1 1 30.49 12.66" fill="none" stroke="#B8863C" stroke-width="6" stroke-linecap="round" />
    </svg>
    <div>
      <h1>Charlotte Morning Briefing</h1>
      <div class="kicker">Weather &middot; Sports &middot; Business &amp; Tech News</div>
    </div>
  </div>
  <div class="meta">{escape(today)}</div>
</div>

<div class="weather">
  {weather_html}
</div>
<div class="weather-loc">{weather_loc}</div>

<div class="sections">
  <div class="section">
    <h2>Sports</h2>
    {''.join(sport_rows)}
  </div>
  <div class="section">
    <h2>Business &amp; Tech News</h2>
    {''.join(news_rows)}
  </div>
</div>

<script>
  window.addEventListener("pageshow", (event) => {{
    if (event.persisted) window.location.reload();
  }});
</script>
"""


def main():
    weather = get_weather()
    sports = get_sports()
    news = get_news()
    html = render(weather, sports, news)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html)
    print(str(OUTPUT_PATH))


if __name__ == "__main__":
    main()
