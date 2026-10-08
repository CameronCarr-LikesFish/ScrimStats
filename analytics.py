"""
Comms analytics.

Reads every transcript and game recording, lines them up on the shared
real-world clock, works out comms stats per player, and builds
Dashboard.html (open in any browser; nothing is uploaded) plus
Comms stats.csv (for Excel / Google Sheets).

How comms are sorted (phrase lists in Settings\\Callout types.txt):
  SHOTCALLING   the team plan: "we're fighting drake", "reset", "group mid"
  INFORMATION   four kinds:
    Enemy info    where enemies are and what they have ("Kai'Sa no flash")
    My status     about yourself ("I don't have flash", "I need to back")
    Item timers   your items ("I'll have IE for drake", "I won't have item")
    Timers        when things come up ("drag in 40")
  Positive, Accountability, and Frustration, where frustration only counts
  against someone when it's aimed at a teammate ("what are you doing"),
  not at themselves ("fuck this, I'm so bad").

Who a sentence is about is judged from its words: "I / my / me" = yourself,
"you / your" or a teammate's name = a teammate, "he / she / they" or a
champion name = the enemy. It's a rule of thumb, not understanding.
"""

import bisect
import csv
import json
import os
import re
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from common import VERSION, bundled

FIGHT_GAP_S = 15          # kills this close together belong to one fight
FIGHT_MIN_KILLS = 3       # ...and it takes this many to be a teamfight
FIGHT_LEAD_S = 10         # fight comms window: 10 s before the first kill
FIGHT_TAIL_S = 5          # ...to 5 s after the last
BLAME_WINDOW_S = 20       # "right after dying" = within 20 s
OBJECTIVE_SETUP_S = 90    # item calls "before an objective" = within 90 s before
TALK_OVER_GRACE_S = 0.3   # ignore overlaps shorter than this
OBJECTIVE_EVENTS = ("Dragon", "Baron", "Herald", "Horde", "Atakhan", "Elder")

INFO_KINDS = ["Enemy info", "My status", "Item timers", "Timers"]
AT_TEAMMATES = "Frustration at teammates"
AT_SELF = "Frustration at self"

FIRST_PERSON = {"i", "i'm", "im", "i'll", "i've", "i'd", "my", "me", "mine", "myself"}
SECOND_PERSON = {"you", "you're", "youre", "your", "yours", "u", "ur", "y'all", "yall",
                 "you've", "youve", "you'll"}
THIRD_PERSON = {"he", "he's", "hes", "she", "she's", "shes", "they", "they're", "theyre",
                "his", "her", "hers", "their", "them", "him", "enemy", "enemies"}
NOT_REALLY_ITEMS = ("ward", "potion", "trinket", "elixir", "lens", "totem", "cookie", "farsight")

COUNT_FIELDS = ["minutes", "talk_s", "team_talk_s", "words", "fights", "fights_spoke",
                "fight_words", "deaths", "deaths_blamed", "talk_overs", "objectives",
                "objectives_itemcall", "team_shotcalls", "talk_zh_s"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_iso(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def read_jsonl(path):
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except ValueError:
                pass
    return records


def read_list_file(path):
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")]


def plain_words(text):
    """Lowercase, no punctuation except apostrophes, padded with spaces so
    whole-word matching is a simple search."""
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return " " + " ".join(text.split()) + " "


class PhraseMatcher:
    """Finds whole-word phrases in a line of text, quickly. At each word it
    takes the longest phrase that fits, so "what the fuck" is found once,
    not also as "fuck"."""

    def __init__(self, phrases):
        self.by_first = defaultdict(list)
        for phrase in {tuple(plain_words(p).split()) for p in phrases}:
            if phrase:
                self.by_first[phrase[0]].append(phrase)
        for options in self.by_first.values():
            options.sort(key=len, reverse=True)

    def spans(self, words):
        """(start, end) word positions of every match."""
        found, i = [], 0
        while i < len(words):
            for phrase in self.by_first.get(words[i], ()):
                if tuple(words[i:i + len(phrase)]) == phrase:
                    found.append((i, i + len(phrase)))
                    i += len(phrase)
                    break
            else:
                i += 1
        return found


# ---------------------------------------------------------------------------
# Roster and classification
# ---------------------------------------------------------------------------

def load_roster(path):
    """Roster.txt lines:  Name | discord1, discord2 | Riot#ID, Alt#ID"""
    players = []
    for line in read_list_file(path):
        parts = [p.strip() for p in line.split("|")]
        if not parts[0]:
            continue
        split = lambda i: [x.strip() for x in parts[i].split(",") if x.strip()] if len(parts) > i else []
        players.append({"name": parts[0], "discord": split(1), "riot": split(2)})
    return players


def write_roster_template(path, discord_names, riot_counts):
    lines = [
        "# Your team's roster. One line per person:",
        "#",
        "#     Name | Discord username(s) | Riot ID(s)",
        "#",
        "# - Name: whatever you want to see on the dashboard.",
        "# - Discord username: as in Craig's audio file names",
        "#   (\"1-alex.flac\" -> alex). Several? Separate with commas.",
        "# - Riot ID: in-game name with tag, e.g. MidDiff#NA1. Add alt",
        "#   accounts with commas. Needed for the fight, death and objective stats.",
        "# - Coaches and subs can be listed too (Riot ID can be left empty).",
        "# - Keep the same Name when someone changes accounts, so their history",
        "#   stays together.",
        "#",
        "# Example (delete the # at the start of a line to use it):",
        "# Alex | alex | MidDiff#NA1",
        "#",
        "# Found in your recordings so far:",
        "#   Discord names: " + (", ".join(sorted(discord_names)) or "(none yet)"),
        "#   Riot IDs seen most often: " + (", ".join(
            f"{rid} ({n} games)" for rid, n in riot_counts.most_common(12)) or "(none yet)"),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def load_categories(path):
    categories = {}
    for line in read_list_file(path):
        if ":" in line:
            name, phrases = line.split(":", 1)
            # Chinese commas (，、) separate phrases too.
            parts = re.split(r"[,，、]", phrases)
            categories[name.strip()] = [p.strip() for p in parts if p.strip()]
    return categories


def item_phrases(vocab):
    """Every item name as people might say it: 'infinity edge',
    'zhonya's hourglass', 'zhonyas hourglass', 'zhonya's', 'zhonyas'."""
    phrases = set()
    for name in vocab.get("items", []):
        if any(word in name.lower() for word in NOT_REALLY_ITEMS):
            continue
        full = plain_words(name).strip()
        variants = {full, full.replace("'s", "s")}
        first = full.split()[0]
        if first.endswith("'s") and len(first) > 4:           # "Rabadon's Deathcap" -> "rabadon's"
            variants |= {first, first.replace("'s", "s")}
        phrases |= {v for v in variants if len(v) >= 3}
    return phrases


SELF_REACH = 4      # "I/my" must be within this many words of a status/item word
SELF_REACH_ZH = 6   # ...or, in Chinese, this many characters of 我

CJK = re.compile(r"[㐀-鿿豈-﫿]")
ZH_ME = re.compile(r"我(?!们)")                         # 我 = I, but 我们 = we
ZH_YOU = re.compile(r"你")                               # 你 / 你们 = you (a teammate)
ZH_THEM = re.compile(r"他|她|它|对面|敌方|对方")          # he / she / they / the other team


def has_chinese(text):
    return bool(CJK.search(text or ""))


def word_count(text):
    """Words in a line. Chinese has no spaces, so its characters are counted
    at the usual ~1.5 characters per word; everything else is split on spaces."""
    chinese_chars = len(CJK.findall(text))
    other_words = len(CJK.sub(" ", text).split())
    return other_words + round(chinese_chars / 1.5)


class Classifier:
    """Decides which kinds of comms one line of speech contains. Each kind
    counts once per line: a line is roughly one callout.

    A line is checked in English (the line itself, or the translation of a
    Chinese line) and, if it has Chinese in it, with the Chinese phrases
    against the original wording. A type counts if either finds it."""

    def __init__(self, categories, vocab, teammate_names):
        self.matchers, self.chinese = {}, {}
        for name, phrases in categories.items():
            english = [p for p in phrases if not has_chinese(p)]
            chinese = [p for p in phrases if has_chinese(p)]
            if name == "Item timers":
                english += sorted(item_phrases(vocab))
                chinese += [i for i in vocab.get("items_zh", [])
                            if not any(w in i for w in ("守卫", "药水", "饰品", "合剂"))]
            self.matchers[name] = PhraseMatcher(english)
            # Longest first, so 我的锅 is found before 锅 would be.
            self.chinese[name] = sorted({p.lower() for p in chinese}, key=len, reverse=True)
        champions = vocab.get("champions", [])
        self.champions = PhraseMatcher(champions + [c.replace("'", "") for c in champions])
        self.champions_zh = sorted({n for names in vocab.get("champions_zh", {}).values()
                                    for n in ([names] if isinstance(names, str) else names)},
                                   key=len, reverse=True)
        self.teammates = PhraseMatcher([n for n in teammate_names if n])
        self.teammates_raw = [n.lower() for n in teammate_names if n]

    @staticmethod
    def near_me(words, span, me_positions):
        start, end = span
        return any(start - SELF_REACH <= p < end + SELF_REACH for p in me_positions)

    def english_kinds(self, text):
        words = plain_words(text).split()
        me_positions = [i for i, w in enumerate(words) if w in FIRST_PERSON]
        you = bool(set(words) & SECOND_PERSON) or bool(self.teammates.spans(words))
        them = bool(set(words) & THIRD_PERSON) or bool(self.champions.spans(words))
        found = set()
        for name, matcher in self.matchers.items():
            spans = matcher.spans(words)
            if name in ("My status", "Item timers"):
                # Only about yourself, and the "I/my" has to be close by:
                # "I think Ahri is missing, she has no flash" isn't my status.
                spans = [s for s in spans if self.near_me(words, s, me_positions)]
            if name == "Enemy info" and me_positions and not them:
                spans = []          # "I have no flash" is my status, not enemy info
            if spans:
                found.add((AT_TEAMMATES if you else AT_SELF) if name == "Frustration" else name)
        return found

    def chinese_kinds(self, text):
        """The same rules for Chinese: phrases are found anywhere in the line
        (Chinese has no spaces), and 我 / 你 / 他 decide who it's about."""
        text = text.lower()          # so mixed lines match ("没有Flash" = "没有flash")
        me_positions = [m.start() for m in ZH_ME.finditer(text)]
        lowered = text
        you = bool(ZH_YOU.search(text)) or any(n in lowered for n in self.teammates_raw)
        them = (bool(ZH_THEM.search(text)) or any(c in text for c in self.champions_zh)
                or bool(self.champions.spans(plain_words(text).split())))
        found = set()
        for name, phrases in self.chinese.items():
            hits = []
            remaining = text
            for phrase in phrases:
                start = remaining.find(phrase)
                while start >= 0:
                    hits.append((start, start + len(phrase)))
                    remaining = remaining[:start] + "\x00" * len(phrase) + remaining[start + len(phrase):]
                    start = remaining.find(phrase)
            if name in ("My status", "Item timers"):
                hits = [h for h in hits
                        if any(h[0] - SELF_REACH_ZH <= p < h[1] + SELF_REACH_ZH for p in me_positions)]
            if name == "Enemy info" and me_positions and not them:
                hits = []
            if hits:
                found.add((AT_TEAMMATES if you else AT_SELF) if name == "Frustration" else name)
        return found

    def classify(self, text, text_en=None):
        found = self.english_kinds(text_en or text)
        if has_chinese(text):
            found |= self.chinese_kinds(text)
        if AT_TEAMMATES in found:
            found.discard(AT_SELF)
            found.discard("Shotcalling")   # "why did you go in" is blame, not a call
        return Counter({name: 1 for name in found})


# ---------------------------------------------------------------------------
# Game recordings
# ---------------------------------------------------------------------------

SPECTATOR_DELAY_S = 0.0   # if spectators see the game late, how many seconds (see warnings)
SAME_GAME_GAP_S = 20 * 60  # files of the same players this close together are one game


def live_timeline(observations):
    """Turns (game time, real time) observations into a function that gives
    the real time each moment of the game actually happened.

    A viewer can only ever be BEHIND the live game, never ahead: at any
    observation, real - game is at least the live offset. So the live offset
    for game moment g is the smallest (real - game) among all observations at
    or after g. That copes with:
      - spectator rewinds and replays (those observations have a bigger gap,
        so they're ignored),
      - game pauses (the gap grows after a pause, and moments before the pause
        still use the smaller gap from before it)."""
    obs = sorted((g, w) for g, w in observations if g is not None)
    if not obs:
        return lambda g: None
    games = [g for g, _ in obs]
    suffix, best = [], float("inf")
    for g, w in reversed(obs):
        best = min(best, w - g)
        suffix.append(best)
    suffix.reverse()

    def real_time(g):
        i = bisect.bisect_left(games, g)
        return g + (suffix[i] if i < len(obs) else suffix[-1])
    return real_time


def event_key(event):
    """What makes an event the same event (a spectator rewind replays events
    with new IDs): its type, game time, and who was involved."""
    return (event.get("EventName"), round(float(event.get("EventTime") or 0), 1),
            event.get("KillerName"), event.get("VictimName"), event.get("DragonType"),
            event.get("TurretKilled"), event.get("InhibKilled"), event.get("Acer"))


def player_signature(players):
    return tuple(sorted(f"{p.get('riotId') or p.get('summonerName')}|{p.get('championName')}"
                        for p in players if isinstance(p, dict)))


def read_game_file(path):
    records = read_jsonl(path)
    walls, observations, players, raw_events, spectator = [], [], [], [], False
    previous = None
    for r in records:
        stamp = r.get("wall_clock") or r.get("started_at")
        if stamp:
            walls.append(parse_iso(stamp))
        if r.get("wall_clock") and r.get("game_time") is not None and r.get("type") in ("clock_sync", "event"):
            observations.append((float(r["game_time"]), parse_iso(r["wall_clock"])))
        if r.get("type") == "clock_sync" and r.get("game_time") is not None:
            if previous is not None and r["game_time"] < previous - 10:
                spectator = True               # the clock went back: a spectator rewind
            previous = r["game_time"]
        elif r.get("type") == "players":
            players = r.get("players", [])
            spectator = spectator or bool(r.get("spectator"))
        elif r.get("type") == "event":
            raw_events.append(r)
    if not walls:
        return None
    return {"file": path.name, "start": min(walls), "end": max(walls), "players": players,
            "signature": player_signature(players), "observations": observations,
            "raw_events": raw_events, "spectator": spectator}


def load_games(paths_list):
    """Read every game recording, merge pieces of the same game (older
    versions split a spectated game at every rewind), drop repeated events,
    and put every event on the real-world clock."""
    pieces = sorted((g for g in (read_game_file(p) for p in paths_list) if g), key=lambda g: g["start"])
    merged = []
    for piece in pieces:
        last = merged[-1] if merged else None
        if (last and piece["signature"] and piece["signature"] == last["signature"]
                and piece["start"] - last["end"] < SAME_GAME_GAP_S):
            last["files"].append(piece["file"])
            last["end"] = max(last["end"], piece["end"])
            last["observations"] += piece["observations"]
            last["raw_events"] += piece["raw_events"]
            last["spectator"] = last["spectator"] or piece["spectator"]
        else:
            merged.append({**piece, "files": [piece["file"]]})
    games = []
    for g in merged:
        # The game clock going backwards anywhere means a spectator rewound.
        clock = [gt for gt, _ in sorted(g["observations"], key=lambda o: o[1])]
        if any(later < earlier - 10 for earlier, later in zip(clock, clock[1:])):
            g["spectator"] = True
        real_time = live_timeline(g["observations"])
        delay = SPECTATOR_DELAY_S if g["spectator"] else 0.0
        events, seen, result = [], set(), None
        for r in sorted(g["raw_events"], key=lambda r: parse_iso(r["wall_clock"])):
            key = event_key(r)
            if key in seen:
                continue
            seen.add(key)
            wall = real_time(r.get("EventTime")) if r.get("EventTime") is not None else parse_iso(r["wall_clock"])
            events.append({**r, "wall": wall - delay})
            if r.get("EventName") == "GameEnd":
                result = r.get("Result")
        starts = [e["wall"] for e in events if e.get("EventName") == "GameStart"]
        games.append({"file": g["files"][0], "files": g["files"],
                      "start": (min(starts) if starts else g["start"]) - 0,
                      "end": g["end"], "players": g["players"], "events": events,
                      "result": result, "spectator": g["spectator"]})
    return games


def name_lookup(game_players):
    lookup = {}
    for p in game_players:
        riot, summoner = p.get("riotId") or "", p.get("summonerName") or ""
        for variant in (riot, riot.split("#")[0], summoner, summoner.split("#")[0]):
            if variant and variant != "#":
                lookup.setdefault(variant.lower(), p)
    for p in game_players:
        if p.get("championName"):
            lookup.setdefault(p["championName"].lower(), p)
    return lookup


def teamfight_windows(game):
    kills = sorted(e["wall"] for e in game["events"] if e.get("EventName") == "ChampionKill")
    clusters = []
    for k in kills:
        if clusters and k - clusters[-1][-1] <= FIGHT_GAP_S:
            clusters[-1].append(k)
        else:
            clusters.append([k])
    return [(c[0] - FIGHT_LEAD_S, c[-1] + FIGHT_TAIL_S)
            for c in clusters if len(c) >= FIGHT_MIN_KILLS]


class Roster:
    def __init__(self, players):
        self.players = players
        self.by_discord = {d.lower(): p["name"] for p in players for d in p["discord"]}
        self.by_riot = {}
        for p in players:
            for rid in p["riot"]:
                self.by_riot[rid.lower()] = p["name"]
                self.by_riot.setdefault(rid.split("#")[0].strip().lower(), p["name"])
        self.empty = not players

    def speaker(self, discord_name):
        return discord_name if self.empty else self.by_discord.get(discord_name.lower())

    def game_player(self, entry):
        for key in (entry.get("riotId") or "", entry.get("summonerName") or ""):
            for variant in (key, key.split("#")[0]):
                if variant and variant.lower() in self.by_riot:
                    return self.by_riot[variant.lower()]
        return None


# ---------------------------------------------------------------------------
# Turning transcripts + games into numbers
# ---------------------------------------------------------------------------

def analyze_session(path, games, roster, classifier, warnings):
    records = read_jsonl(path)
    meta = next((r for r in records if r.get("type") == "meta"), None)
    utterances = [r for r in records if r.get("type") == "utterance"]
    if not meta:
        warnings.append(f"{path.name}: no meta line; skipped.")
        return [], set()
    start = meta.get("audio_start_t") or (utterances[0]["t"] if utterances else None)
    if start is None:
        return [], set()
    track_lengths = [t.get("duration_s") or 0 for t in meta.get("tracks", [])]
    end = max([start + max(track_lengths, default=0)] + [u["t_end"] for u in utterances])
    session_id = meta.get("craig_recording_id", path.stem)
    date = datetime.fromtimestamp(start).date()

    unmapped = set()
    for u in utterances:
        u["player"] = roster.speaker(u["speaker"])
        if u["player"] is None:
            unmapped.add(u["speaker"])
        u["counts"] = classifier.classify(u["text"], u.get("text_en"))
        u["n_words"] = word_count(u["text"])
    track_players = {roster.speaker(t["speaker"]) for t in meta.get("tracks", [])} - {None}

    in_session = sorted((g for g in games if g["start"] < end and g["end"] > start),
                        key=lambda g: g["start"])
    segments = [(max(g["start"], start), min(g["end"], end), g, n)
                for n, g in enumerate(in_session, 1)]
    if not segments:
        segments = [(start, end, None, None)]
        warnings.append(f"Session {date} ({session_id}): no recorded games found, so all "
                        "speech counts and fight/death/objective stats are missing.")

    rows = []
    for w0, w1, game, number in segments:
        minutes = (w1 - w0) / 60
        if minutes <= 0:
            continue
        window = [u for u in utterances if w0 <= u["t"] < w1]
        team_talk = sum(u["t_end"] - u["t"] for u in window)
        team_shotcalls = sum(u["counts"].get("Shotcalling", 0) for u in window)
        present = set(track_players)
        fights, deaths, objectives = [], defaultdict(list), []
        if game:
            fights = teamfight_windows(game)
            lookup = name_lookup(game["players"])
            for entry in game["players"]:
                name = roster.game_player(entry)
                if name:
                    present.add(name)
            for e in game["events"]:
                kind = str(e.get("EventName", ""))
                if kind == "ChampionKill":
                    victim = lookup.get(str(e.get("VictimName", "")).lower())
                    name = roster.game_player(victim) if victim else None
                    if name:
                        deaths[name].append(e["wall"])
                elif kind.endswith("Kill") and any(o in kind for o in OBJECTIVE_EVENTS):
                    objectives.append(e["wall"])

        talk_overs = Counter()
        ordered = sorted(window, key=lambda u: u["t"])
        for i, u in enumerate(ordered):
            for other in ordered[max(0, i - 20):i]:
                if (other["speaker"] != u["speaker"]
                        and other["t"] < u["t"] < other["t_end"] - TALK_OVER_GRACE_S):
                    talk_overs[u["player"]] += 1
                    break

        for player in sorted(present):
            mine = [u for u in window if u["player"] == player]
            cats = Counter()
            for u in mine:
                cats.update(u["counts"])
            rows.append({
                "session": session_id,
                "date": date.isoformat(),
                "week": (date - timedelta(days=date.weekday())).isoformat(),
                "month": date.strftime("%Y-%m"),
                "game": number,
                "game_file": game["file"] if game else None,
                "result": game["result"] if game else None,
                "player": player,
                "minutes": round(minutes, 3),
                "talk_s": round(sum(u["t_end"] - u["t"] for u in mine), 2),
                "team_talk_s": round(team_talk, 2),
                "words": sum(u["n_words"] for u in mine),
                "fights": len(fights),
                "fights_spoke": sum(1 for f0, f1 in fights
                                    if any(u["t"] < f1 and u["t_end"] > f0 for u in mine)),
                "fight_words": sum(u["n_words"] for f0, f1 in fights
                                   for u in mine if f0 <= u["t"] < f1),
                "deaths": len(deaths[player]),
                "deaths_blamed": sum(1 for d in deaths[player]
                                     if any(d <= u["t"] <= d + BLAME_WINDOW_S
                                            and u["counts"].get(AT_TEAMMATES) for u in mine)),
                "talk_overs": talk_overs[player],
                "talk_zh_s": round(sum(u["t_end"] - u["t"] for u in mine
                                       if u.get("language") == "zh"), 2),
                "team_shotcalls": team_shotcalls,
                "objectives": len(objectives),
                "objectives_itemcall": sum(1 for o in objectives
                                           if any(o - OBJECTIVE_SETUP_S <= u["t"] <= o
                                                  and u["counts"].get("Item timers") for u in mine)),
                "cats": {k: v for k, v in cats.items() if v},
            })
    return rows, unmapped


# ---------------------------------------------------------------------------
# CSV (same formulas as the dashboard)
# ---------------------------------------------------------------------------

def add_up(rows):
    total = {f: 0 for f in COUNT_FIELDS}
    total["cats"] = Counter()
    for r in rows:
        for f in COUNT_FIELDS:
            total[f] += r.get(f, 0)
        total["cats"].update(r["cats"])
    return total


def derived_stats(t):
    enough = t["minutes"] >= 5
    per10 = lambda n: round(10 * n / t["minutes"], 2) if enough else ""
    pct = lambda a, b, minimum=1: round(100 * a / b, 1) if b >= minimum else ""
    c = t["cats"]
    stats = {"words_per_min": round(t["words"] / t["minutes"], 2) if enough else "",
             "talk_share_%": pct(t["talk_s"], t["team_talk_s"]),
             "info_per_10min": per10(sum(c[k] for k in INFO_KINDS))}
    for kind in INFO_KINDS:
        stats[f"{kind.lower().replace(' ', '_')}_per_10min"] = per10(c[kind])
    stats["item_timers_before_objectives_%"] = pct(t["objectives_itemcall"], t["objectives"])
    stats["shotcalls_per_10min"] = per10(c["Shotcalling"])
    stats["objective_mentions_per_10min"] = per10(c["Objectives"])
    stats["accountability_per_10min"] = per10(c["Accountability"])
    stats["positivity_%"] = pct(c["Positive"], c["Positive"] + c[AT_TEAMMATES], 3)
    stats["frustration_at_teammates_per_10min"] = per10(c[AT_TEAMMATES])
    stats["blame_after_death_%"] = pct(t["deaths_blamed"], t["deaths"], 2)
    stats["fight_presence_%"] = pct(t["fights_spoke"], t["fights"])
    stats["words_per_teamfight"] = round(t["fight_words"] / t["fights"], 1) if t["fights"] else ""
    stats["talk_overs_per_10min"] = per10(t["talk_overs"])
    stats["chinese_share_%"] = pct(t["talk_zh_s"], t["talk_s"])
    return stats


def write_csv(path, rows):
    by_session = defaultdict(list)
    for r in rows:
        by_session[(r["date"], r["session"], r["player"])].append(r)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = None
        for (date, session, player), group in sorted(by_session.items()):
            t = add_up(group)
            results = [g["result"] for g in group]
            team_calls = t["team_shotcalls"]
            row = {"date": date, "session": session, "player": player,
                   "games": sum(1 for g in group if g["game"]),
                   "wins": results.count("Win"), "losses": results.count("Lose"),
                   "minutes": round(t["minutes"], 1), "deaths": t["deaths"], "fights": t["fights"],
                   **derived_stats(t),
                   "shotcall_share_%": round(100 * t["cats"]["Shotcalling"] / team_calls, 1) if team_calls else ""}
            if writer is None:
                writer = csv.DictWriter(f, fieldnames=list(row))
                writer.writeheader()
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Build everything
# ---------------------------------------------------------------------------

def build(paths, log=print, open_browser=True, open_roster=True):
    """Rebuild Dashboard.html and Comms stats.csv. Returns the dashboard path."""
    transcripts = sorted(paths.transcripts.glob("comms_*.jsonl")) if paths.transcripts.is_dir() else []
    game_files = sorted(paths.games.glob("game_*.jsonl")) if paths.games.is_dir() else []
    log(f"Found {len(transcripts)} transcript(s) and {len(game_files)} recorded game(s).")
    games = load_games(game_files)

    if not paths.roster.exists():
        discord_names = set()
        for path in transcripts:
            for r in read_jsonl(path):
                if r.get("type") == "meta":
                    discord_names.update(t["speaker"] for t in r.get("tracks", []))
        riot_counts = Counter(p.get("riotId") for g in games for p in g["players"]
                              if p.get("riotId") and p.get("riotId") != "#")
        write_roster_template(paths.roster, discord_names, riot_counts)
        log("Created Settings\\Roster.txt. Fill it in and save it, then rebuild the dashboard.")
        if open_roster and os.name == "nt":
            os.startfile(paths.roster)

    roster = Roster(load_roster(paths.roster))
    vocab = {}
    if paths.vocab.exists():
        try:
            vocab = json.loads(paths.vocab.read_text(encoding="utf-8"))
        except ValueError:
            pass
    teammate_names = [p["name"] for p in roster.players] + [d for p in roster.players for d in p["discord"]]
    classifier = Classifier(load_categories(paths.callouts), vocab, teammate_names)

    warnings, all_rows, unmapped = [], [], set()
    if roster.empty:
        warnings.append("Roster.txt has no players yet, so people are shown by Discord name "
                        "and fight/death/objective stats are missing. Fill in Settings\\Roster.txt.")
    for path in transcripts:
        rows, missing = analyze_session(path, games, roster, classifier, warnings)
        all_rows.extend(rows)
        unmapped |= missing
    if unmapped:
        warnings.append("These Discord names aren't in Roster.txt, so their comms only count "
                        "toward the team total: " + ", ".join(sorted(unmapped)))
    watched = [g for g in games if g.get("spectator")]
    if watched:
        warnings.append(
            f"{len(watched)} game(s) were recorded while spectating (with rewinds). Event times use "
            "the moments you were watching live. If spectators in your custom lobby see the game "
            "late, every event in those games is late by that much: do the clock test (a player "
            "reads out their game clock on Discord) and tell Claude the difference.")
    if roster.players and games:
        seen = {n for g in games for n in (roster.game_player(p) for p in g["players"]) if n}
        missing_riot = [p["name"] for p in roster.players if p["riot"] and p["name"] not in seen]
        if missing_riot:
            warnings.append("No recorded games have these players' Riot IDs (check spelling in "
                            "Roster.txt): " + ", ".join(missing_riot))

    order = [p["name"] for p in roster.players]
    for r in all_rows:
        if r["player"] not in order:
            order.append(r["player"])
    players = [p for p in order if any(r["player"] == p for r in all_rows)]

    sessions = defaultdict(lambda: {"games": set(), "wins": 0, "losses": 0, "minutes": 0})
    counted = set()
    for r in all_rows:
        s = sessions[(r["date"], r["session"])]
        if (r["session"], r["game"]) not in counted:
            counted.add((r["session"], r["game"]))
            s["minutes"] += r["minutes"]
            if r["game"]:
                s["games"].add(r["game"])
                s["wins"] += r["result"] == "Win"
                s["losses"] += r["result"] == "Lose"

    data = {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "version": VERSION,
        "players": players,
        "info_kinds": INFO_KINDS,
        "rows": all_rows,
        "sessions": [{"date": d, "session": sid, "games": len(s["games"]), "wins": s["wins"],
                      "losses": s["losses"], "minutes": round(s["minutes"], 1)}
                     for (d, sid), s in sorted(sessions.items())],
        "warnings": warnings,
    }
    template = bundled("dashboard_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    paths.dashboard.write_text(template.replace("/*__DATA__*/null", payload), encoding="utf-8")
    if all_rows:
        write_csv(paths.csv, all_rows)

    for w in warnings:
        log("  Note: " + w)
    log(f"Dashboard updated: {len(data['sessions'])} session(s), {len(players)} player(s).")
    if open_browser:
        webbrowser.open(paths.dashboard.as_uri())
    return paths.dashboard


if __name__ == "__main__":
    from common import Paths
    build(Paths().ensure())
