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
  RESOURCES     asking for gold, farm, waves, camps ("I need gold for this")
  VISION        three kinds: warding ("I warded tri"), asking for vision
                ("we have no vision", "buy pinks") and sweeping ("I swept it")
  Positive, Accountability, and Flame: blaming or insulting phrases aimed at
  a teammate ("what are you doing", "you're so useless"). Swearing and
  frustration on their own ("fuck this", "I'm so bad") aren't flame.

Who a sentence is about is judged from its words: "I / my / me" = yourself,
"you / your" or a teammate's name = a teammate, "he / she / they" or a
champion name = the enemy. It's a rule of thumb, not understanding.

Every game is split into three parts, per player, so each stat can be seen
for the laning phase and later:
  Early   until the first outer tower in that player's lane falls (either
          team's), at most 20:00. Junglers: the first outer tower anywhere.
          Lane comes from the Role on the roster (no role = bot lane).
  Mid     from then until 30:00, or until the first inhibitor falls.
  Late    the rest.
"""

import bisect
import csv
import json
import os
import re
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from common import VERSION, SeenEvents, bundled

FIGHT_GAP_S = 15          # kills this close together belong to one fight
FIGHT_MIN_KILLS = 3       # ...and it takes this many to be a teamfight
FIGHT_LEAD_S = 10         # fight comms window: 10 s before the first kill
FIGHT_TAIL_S = 5          # ...to 5 s after the last
BLAME_WINDOW_S = 20       # "right after dying" = within 20 s
OBJECTIVE_SETUP_S = 150   # item/gold talk "before an objective" = within 2½ min before
TALK_OVER_GRACE_S = 0.3   # ignore overlaps shorter than this
OBJECTIVE_EVENTS = ("Dragon", "Baron", "Herald", "Horde", "Atakhan", "Elder")
EARLY_GAME_MAX_S = 20 * 60   # laning phase ends by 20:00 even if no tower has fallen
LATE_GAME_FROM_S = 30 * 60   # late game from 30:00 (or the first inhibitor)
PHASES = ("early", "mid", "late")

INFO_KINDS = ["Enemy info", "My status", "Item timers", "Timers"]
VISION_KINDS = ["Warding", "Vision requests", "Sweeping"]
AT_TEAMMATES = "Flame at teammates"
AT_SELF = "Frustration"     # exclamations ("oh fuck"): not shown, not scored
NEGATIVE = "Negative"       # defeatist / complaining: "we're so fucked", "ff"
CONTEXT_BEFORE_S, CONTEXT_AFTER_S = 45, 20   # "more context" around a quoted line
FLAME_REACH = 5             # "you" / a teammate's name within this many words of a flame phrase
DEFAULT_ROSTER = "Team"
ROLES = ("Top", "Jungle", "Mid", "Bot", "Support")
LANE_OF_ROLE = {"top": "top", "jungle": "any", "mid": "mid", "bot": "bot", "support": "bot"}

FIRST_PERSON = {"i", "i'm", "im", "i'll", "i've", "i'd", "my", "me", "mine", "myself"}
SECOND_PERSON = {"you", "you're", "youre", "your", "yours", "u", "ur", "y'all", "yall",
                 "you've", "youve", "you'll"}
THIRD_PERSON = {"he", "he's", "hes", "she", "she's", "shes", "they", "they're", "theyre",
                "his", "her", "hers", "their", "them", "him", "enemy", "enemies"}
NOT_REALLY_ITEMS = ("ward", "potion", "trinket", "elixir", "lens", "totem", "cookie", "farsight")

COUNT_FIELDS = ["minutes", "talk_s", "team_talk_s", "words", "fights", "fights_spoke",
                "fight_words", "deaths", "deaths_blamed", "talk_overs", "objectives",
                "objectives_itemcall", "team_shotcalls", "talk_zh_s", "plays",
                "vision", "vision_minutes"]


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

def load_rosters(path):
    """Roster.txt: a [Roster name] line starts each roster (Varsity, JV...),
    then one line per player:  Name | discord1, discord2 | Riot#ID, Alt#ID | Role
    Lines before any [name] belong to a roster called "Team" (older files).
    Someone on two rosters is listed in both.
    Returns {"rosters": [names in order], "players": [{name, discord, riot, role, roster}]}."""
    rosters, players, current = [], [], None
    for line in read_list_file(path):
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip() or DEFAULT_ROSTER
            if current not in rosters:
                rosters.append(current)
            continue
        parts = [p.strip() for p in line.split("|")]
        if not parts[0]:
            continue
        if current is None:
            current = DEFAULT_ROSTER
            rosters.append(current)
        split = lambda i: [x.strip() for x in parts[i].split(",") if x.strip()] if len(parts) > i else []
        role = parts[3].title() if len(parts) > 3 and parts[3].title() in ROLES else ""
        players.append({"name": parts[0], "discord": split(1), "riot": split(2),
                        "role": role, "roster": current})
    return {"rosters": rosters, "players": players}


def load_roster(path):
    """Every player on every roster (one entry per roster they're on)."""
    return load_rosters(path)["players"]


def write_roster_template(path, discord_names, riot_counts):
    lines = [
        "# Your team's rosters. A [Name] line starts each roster, then one",
        "# line per person:",
        "#",
        "#     Name | Discord username(s) | Riot ID(s) | Role",
        "#",
        "# - Name: whatever you want to see on the dashboard.",
        "# - Discord username: as in Craig's audio file names",
        "#   (\"1-alex.flac\" -> alex). Several? Separate with commas.",
        "# - Riot ID: in-game name with tag, e.g. MidDiff#NA1. Add alt",
        "#   accounts with commas. Needed for the fight, death and objective stats.",
        "# - Role: Top, Jungle, Mid, Bot or Support (decides when their laning",
        "#   phase ends). Can be left empty.",
        "# - Coaches and subs can be listed too (Riot ID can be left empty).",
        "# - Keep the same Name when someone changes accounts, so their history",
        "#   stays together.",
        "#",
        "# Example (delete the # at the start of the lines to use them):",
        "# [Varsity]",
        "# Alex | alex | MidDiff#NA1 | Mid",
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
        # Older settings files have no Flame line: their Frustration phrases
        # are used for flame instead.
        self.flame = "Flame" if "Flame" in categories else "Frustration"

    @staticmethod
    def near_me(words, span, me_positions):
        start, end = span
        return any(start - SELF_REACH <= p < end + SELF_REACH for p in me_positions)

    def english_kinds(self, text):
        words = plain_words(text).split()
        me_positions = [i for i, w in enumerate(words) if w in FIRST_PERSON]
        you_positions = ([i for i, w in enumerate(words) if w in SECOND_PERSON]
                         + [i for a, b in self.teammates.spans(words) for i in range(a, b)])
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
            if not spans:
                continue
            if name == self.flame:
                # Flame is aimed at someone: "you" or a teammate's name close by.
                # "Holy shit, you live?" or "I'm not stupid, you know" aren't flame.
                if any(a - FLAME_REACH <= p < b + FLAME_REACH for a, b in spans for p in you_positions):
                    found.add(AT_TEAMMATES)
                elif name == "Frustration":
                    found.add(AT_SELF)
            elif name == "Frustration":
                found.add(AT_SELF)
            else:
                found.add(name)
        return found

    def chinese_kinds(self, text):
        """The same rules for Chinese: phrases are found anywhere in the line
        (Chinese has no spaces), and 我 / 你 / 他 decide who it's about."""
        text = text.lower()          # so mixed lines match ("没有Flash" = "没有flash")
        me_positions = [m.start() for m in ZH_ME.finditer(text)]
        lowered = text
        you_positions = [m.start() for m in ZH_YOU.finditer(text)]
        for n in self.teammates_raw:
            start = lowered.find(n)
            while start >= 0:
                you_positions.append(start)
                start = lowered.find(n, start + 1)
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
            if not hits:
                continue
            if name == self.flame:
                if any(h[0] - SELF_REACH_ZH <= p < h[1] + SELF_REACH_ZH for h in hits for p in you_positions):
                    found.add(AT_TEAMMATES)
                elif name == "Frustration":
                    found.add(AT_SELF)
            elif name == "Frustration":
                found.add(AT_SELF)
            else:
                found.add(name)
        return found

    fix = None   # Corrections.txt, applied to every line (set in build())

    def classify(self, text, text_en=None):
        if self.fix:
            # So a correction added today also fixes older transcripts' stats.
            text, text_en = self.fix(text), (self.fix(text_en) if text_en else text_en)
        found = self.english_kinds(text_en or text)
        if has_chinese(text):
            found |= self.chinese_kinds(text)
        if AT_TEAMMATES in found:
            found.discard(AT_SELF)
            found.discard("Shotcalling")   # "why did you go in" is blame, not a call
        # "Buy pinks" / "I swept it" mention wards too, but the more specific
        # kind is what they are; plain ward talk is Warding.
        if found & {"Vision requests", "Sweeping"}:
            found.discard("Warding")
        if found & set(VISION_KINDS):
            found.add("Vision talk")
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


def player_id(p):
    """A player's account name as the recorder saves it ("#" = no Riot ID)."""
    riot = p.get("riotId") or ""
    return riot if riot not in ("", "#") else (p.get("summonerName") or "")


def player_signature(players):
    return tuple(sorted(f"{p.get('riotId') or p.get('summonerName')}|{p.get('championName')}"
                        for p in players if isinstance(p, dict)))


def clock_went_back(observations):
    clock = [gt for gt, _ in sorted(observations, key=lambda o: o[1])]
    return any(later < earlier - 10 for earlier, later in zip(clock, clock[1:]))


def read_game_file(path):
    records = read_jsonl(path)
    walls, observations, players, raw_events, scores = [], [], [], [], []
    spectator, as_player, active_team = False, False, None
    for r in records:
        stamp = r.get("wall_clock") or r.get("started_at")
        if stamp:
            walls.append(parse_iso(stamp))
        if r.get("wall_clock") and r.get("game_time") is not None and r.get("type") in ("clock_sync", "event"):
            observations.append((float(r["game_time"]), parse_iso(r["wall_clock"])))
        if r.get("type") == "players":
            players = r.get("players", [])
            spectator = spectator or bool(r.get("spectator"))
            # Only newer recordings say so outright; older ones are "unknown".
            as_player = r.get("spectator") is False
            active_team = r.get("active_team")
        elif r.get("type") == "scores" and r.get("game_time") is not None:
            scores.append((float(r["game_time"]), {str(p.get("id") or "").lower(): p.get("vision")
                                                   for p in r.get("players", []) if p.get("id")}))
        elif r.get("type") == "event":
            raw_events.append(r)
    if not walls:
        return None
    if clock_went_back(observations):
        spectator, as_player = True, False       # the clock went back: a spectator rewind
    # Whose point of view this file's Win/Lose is from: a player's own side;
    # for a spectator, the blue side (ORDER). (Checked against which nexus
    # towers fell: a spectator's "Win" was blue's win both times.) None: a
    # player's recording from before 2.4.3, side unknown.
    view = "ORDER" if spectator else (active_team if as_player else None)
    for r in raw_events:
        r["_view"] = view
    return {"file": path.name, "start": min(walls), "end": max(walls), "players": players,
            "signature": player_signature(players), "observations": observations,
            "raw_events": raw_events, "scores": scores, "spectator": spectator,
            "as_player": as_player}


def load_games(paths_list, delays=None):
    """Read every game recording, merge pieces of the same game (older
    versions split a spectated game at every rewind; a teammate's recording
    of the same game can be added too), drop repeated events, and put every
    event on the real-world clock."""
    pieces = sorted((g for g in (read_game_file(p) for p in paths_list) if g), key=lambda g: g["start"])
    merged = []
    for piece in pieces:
        last = merged[-1] if merged else None
        if (last and piece["signature"] and piece["signature"] == last["signature"]
                and piece["start"] - last["end"] < SAME_GAME_GAP_S):
            last["files"].append(piece["file"])
            last["end"] = max(last["end"], piece["end"])
            last["pieces"].append(piece)
        else:
            merged.append({**piece, "files": [piece["file"]], "pieces": [piece]})
    games = []
    for g in merged:
        parts = g["pieces"]
        observations = [o for p in parts for o in p["observations"]]
        spectator = any(p["spectator"] for p in parts) or clock_went_back(observations)
        # A player's own recording of a spectated game is live: no spectator
        # delay, and it has the dragons and barons (the spectator feed doesn't).
        live_parts = [p for p in parts if p["as_player"]]
        player_view = spectator and bool(live_parts)
        if player_view:
            observations = [o for p in live_parts for o in p["observations"]]
        real_time = live_timeline(observations)
        # A spectator delay set in the app (Games tab) for this game, if any.
        delay = 0.0 if player_view else float(
            (delays or {}).get(g["files"][0], SPECTATOR_DELAY_S if spectator else 0.0))

        def to_wall(game_seconds, real_time=real_time, delay=delay, start=g["start"]):
            """Game clock -> real-world time this moment was heard on Discord."""
            real = real_time(game_seconds)
            return (real if real is not None else start + game_seconds) - delay

        events, seen, end_result, result_side = [], SeenEvents(), None, None
        raw = [r for p in parts for r in p["raw_events"]]
        for r in sorted(raw, key=lambda r: parse_iso(r["wall_clock"])):
            if seen.is_repeat(r):
                continue
            wall = (to_wall(float(r["EventTime"])) if r.get("EventTime") is not None
                    else parse_iso(r["wall_clock"]) - delay)
            events.append({**r, "wall": wall})
            if r.get("EventName") == "GameEnd" and end_result is None:
                end_result, result_side = r.get("Result"), r.get("_view")
        # The game ran from game clock 0 to the furthest moment anyone saw.
        # (A spectator who keeps rewinding after the end doesn't make it longer.)
        last_moment = max((gt for gt, _ in observations), default=0.0)
        games.append({"file": g["files"][0], "files": g["files"], "delay": delay,
                      "start": to_wall(0.0) if observations else g["start"],
                      "end": to_wall(last_moment) if observations else g["end"],
                      "players": g["players"], "events": events,
                      "winner": winner_team(events, end_result, result_side),
                      "end_result": end_result, "result": end_result,
                      "spectator": spectator, "player_view": player_view,
                      "to_wall": to_wall, "max_game_time": last_moment,
                      "scores": sorted(s for p in parts for s in p["scores"])})
    return games


NEXUS_NEW = re.compile(r"Turret_T(Order|Chaos)_L1_P[45]", re.I)
NEXUS_OLD = re.compile(r"Turret_T([12])_C_0[12]", re.I)


def winner_team(events, end_result, result_side):
    """Which side won ("ORDER" / "CHAOS"), or None if it can't be told.
    1. The side that lost both nexus towers in the last 3 minutes lost.
    2. Otherwise the game's own Win/Lose, read from the right side's view."""
    times = [float(e["EventTime"]) for e in events if e.get("EventTime") is not None]
    last = max(times, default=0.0)
    down = defaultdict(set)
    for e in events:
        if e.get("EventName") != "TurretKilled" or e.get("EventTime") is None:
            continue
        name = str(e.get("TurretKilled"))
        m, old = NEXUS_NEW.search(name), NEXUS_OLD.search(name)
        if (m or old) and float(e["EventTime"]) >= last - 180:
            side = m.group(1).upper() if m else ("ORDER" if old.group(1) == "1" else "CHAOS")
            down[side].add(name)
    losers = [side for side, towers in down.items() if len(towers) >= 2]
    if len(losers) == 1:
        return "CHAOS" if losers[0] == "ORDER" else "ORDER"
    if end_result in ("Win", "Lose") and result_side in ("ORDER", "CHAOS"):
        other = "CHAOS" if result_side == "ORDER" else "ORDER"
        return result_side if end_result == "Win" else other
    return None


def our_side(game, roster):
    """The side most of our roster's accounts were on."""
    sides = Counter(p.get("team") for p in game["players"] if roster.game_player(p))
    return sides.most_common(1)[0][0] if sides else None


def our_result(game, roster):
    """"Win" / "Lose" for our team, or None if unknown."""
    side = our_side(game, roster)
    if game.get("winner") and side:
        return "Win" if game["winner"] == side else "Lose"
    if not game.get("spectator"):
        return game.get("end_result")       # an older player recording: assume it's one of us
    return None


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


def kill_clusters(game):
    """Kills close together, as fights. Returns (teamfights as comms windows,
    start times of every fight of any size: the "plays")."""
    kills = sorted(e["wall"] for e in game["events"] if e.get("EventName") == "ChampionKill")
    clusters = []
    for k in kills:
        if clusters and k - clusters[-1][-1] <= FIGHT_GAP_S:
            clusters[-1].append(k)
        else:
            clusters.append([k])
    teamfights = [(c[0] - FIGHT_LEAD_S, c[-1] + FIGHT_TAIL_S)
                  for c in clusters if len(c) >= FIGHT_MIN_KILLS]
    return teamfights, [c[0] for c in clusters]


# ---------------------------------------------------------------------------
# Drafts from Drafter.lol
# ---------------------------------------------------------------------------
# A scrim drafted on drafter.lol (then locked in blind in League) has its
# pick order, bans and sides on the draft's public page. The app reads that
# page once when a link is pasted in (Games tab) and keeps the result in
# _data/drafts.json. Each draft game is matched to a recorded game by its
# ten champions.

DRAFTER_LINK = re.compile(r"drafter\.lol/draft/([A-Za-z0-9_-]+)")
DRAFT_FIELDS = (["draftId", "id", "patch", "drafterBlue", "drafterRed", "firstPick", "fearless", "createdAt"]
                + [f"{side}{kind}{n}" for side in ("blue", "red") for kind in ("Ban", "Pick") for n in range(1, 6)])


def fetch_drafter(link):
    """Every finished draft on a drafter.lol draft or series page."""
    m = DRAFTER_LINK.search(link or "")
    if not m:
        raise ValueError("That isn't a drafter.lol draft link (it should look like drafter.lol/draft/abc123).")
    import requests
    page = requests.get(f"https://drafter.lol/draft/{m.group(1)}", timeout=20,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ScrimStats"}).text
    # The page carries its data in Next.js "flight" chunks: JSON strings to join.
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', page)
    payload = "".join(json.loads('"' + c + '"') for c in chunks)
    drafts, decoder = {}, json.JSONDecoder()
    for start in re.finditer(r'\{"id":\d+,"draftId":', payload):
        try:
            d, _ = decoder.raw_decode(payload, start.start())
        except ValueError:
            continue
        if d.get("done") and d.get("bluePick1"):
            drafts[d["draftId"]] = {k: d.get(k) for k in DRAFT_FIELDS}
    if not drafts:
        raise ValueError("No finished drafts on that page yet.")
    ordered = sorted(drafts.values(), key=lambda d: d.get("id") or 0)
    for n, d in enumerate(ordered, 1):
        d["gameNumber"] = n
    return {"id": m.group(1), "link": f"https://drafter.lol/draft/{m.group(1)}",
            "fetched": datetime.now().astimezone().isoformat(timespec="seconds"), "drafts": ordered}


def load_drafts(paths):
    try:
        return json.loads((paths.data / "drafts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def add_drafter_link(paths, link):
    series = fetch_drafter(link)
    saved = load_drafts(paths)
    saved[series["id"]] = series
    (paths.data / "drafts.json").write_text(json.dumps(saved, indent=1, ensure_ascii=False), encoding="utf-8")
    return series


def remove_drafter_link(paths, series_id):
    saved = load_drafts(paths)
    saved.pop(series_id, None)
    (paths.data / "drafts.json").write_text(json.dumps(saved, indent=1, ensure_ascii=False), encoding="utf-8")


def _plain(name):
    return re.sub(r"[^a-z]", "", str(name or "").lower())


# The few champions whose key isn't just their name without punctuation.
ODD_KEYS = {"MonkeyKing": "Wukong", "Nunu": "Nunu & Willump", "Renata": "Renata Glasc"}


def champion_names_by_key(paths=None):
    """Drafter uses Riot's internal keys ("MonkeyKing", "Chogath"); the game
    uses display names ("Wukong", "Cho'Gath"). Key -> display name, from the
    icon lists (shipped with the app, or downloaded into _data)."""
    ids = {}
    for source in [bundled("champions") / "ids.json"] + ([paths.data / "champions" / "ids.json"] if paths else []):
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            ids.update(data.get("ids", data) if isinstance(data, dict) else {})
        except (OSError, ValueError):
            pass
    names = dict(ODD_KEYS)
    names.update({key: name for name, key in ids.items() if isinstance(key, str)})
    return names


class DraftMatcher:
    """Finds the draft for a recorded game: the one sharing at least 8 of
    its 10 champions (a late swap doesn't break the match)."""

    def __init__(self, saved, paths=None):
        names = champion_names_by_key(paths)
        self.games = []
        for series in saved.values():
            for d in series.get("drafts", []):
                sides = {side: [names.get(d.get(f"{side}Pick{n}"), d.get(f"{side}Pick{n}")) for n in range(1, 6)]
                         for side in ("blue", "red")}
                bans = {side: [names.get(d.get(f"{side}Ban{n}"), d.get(f"{side}Ban{n}"))
                               for n in range(1, 6) if d.get(f"{side}Ban{n}")] for side in ("blue", "red")}
                self.games.append((series["id"], d, sides, bans))

    def find(self, ours, theirs):
        """ours / theirs: champion display names. Returns the draft as seen by us."""
        mine, everyone = {_plain(c) for c in ours}, {_plain(c) for c in ours + theirs}
        best, best_overlap = None, 0
        for series_id, d, sides, bans in self.games:
            overlap = len(everyone & {_plain(c) for side in sides.values() for c in side})
            if overlap > best_overlap:
                best, best_overlap = (series_id, d, sides, bans), overlap
        if not best or best_overlap < 8:
            return None
        series_id, d, sides, bans = best
        side = max(("blue", "red"), key=lambda s: len(mine & {_plain(c) for c in sides[s]}))
        other = "red" if side == "blue" else "blue"
        return {"series": series_id, "game": d.get("gameNumber"), "patch": d.get("patch"),
                "side": side, "we_first": d.get("firstPick") == side,
                "team": d.get("drafterBlue") if side == "blue" else d.get("drafterRed"),
                "opponent": d.get("drafterRed") if side == "blue" else d.get("drafterBlue"),
                "fearless": bool(d.get("fearless")),
                "picks": sides[side], "their_picks": sides[other],
                "bans": bans[side], "their_bans": bans[other]}


# ---------------------------------------------------------------------------
# Early / mid / late game
# ---------------------------------------------------------------------------

TURRET_NEW = re.compile(r"Turret_T(Order|Chaos)_L(\d)_P(\d)", re.I)
TURRET_OLD = re.compile(r"Turret_T([12])_([LCR])_(\d+)", re.I)
# Lane numbers in the newer tower names. Worked out from recorded games:
# top laners took the L2 towers and bot laners the L0 ones, and the two
# nexus towers are L1 (mid). P3 is the outer tower.
NEW_LANES = {"0": "bot", "1": "mid", "2": "top"}
OLD_LANES = {"L": "top", "C": "mid", "R": "bot"}


def turret_lane(name):
    """(lane, is it the lane's outer tower?) from a tower's name."""
    m = TURRET_NEW.search(name or "")
    if m:
        return NEW_LANES.get(m.group(2)), m.group(3) == "3"
    m = TURRET_OLD.search(name or "")
    if m:
        lane = OLD_LANES[m.group(2).upper()]
        return lane, int(m.group(3)) == (5 if lane == "mid" else 3)
    return None, False


def phase_times(game):
    """When the game moves on, in game seconds: early_end(lane) and late."""
    outer, inhib = {}, None
    for e in game["events"]:
        if e.get("EventTime") is None:
            continue
        t = float(e["EventTime"])
        if e.get("EventName") == "TurretKilled":
            lane, is_outer = turret_lane(e.get("TurretKilled"))
            if lane and is_outer:
                outer[lane] = min(outer.get(lane, t), t)
        elif e.get("EventName") == "InhibKilled":
            inhib = t if inhib is None else min(inhib, t)
    late = min(LATE_GAME_FROM_S, inhib if inhib is not None else LATE_GAME_FROM_S)

    def early_end(lane):
        t = (min(outer.values(), default=EARLY_GAME_MAX_S) if lane == "any"
             else outer.get(lane, EARLY_GAME_MAX_S))
        return min(t, EARLY_GAME_MAX_S, late)
    return early_end, late


def lane_of(role, entry):
    """Which lane's towers end someone's laning phase. Smite = jungler."""
    if any("smite" in str(s).lower() for s in (entry or {}).get("spells") or []):
        return "any"
    return LANE_OF_ROLE.get((role or "").lower(), "bot")


def to_game_time(game, wall):
    """Real-world time -> game clock (the reverse of game["to_wall"])."""
    lo, hi = 0.0, game["max_game_time"] + 3600
    for _ in range(40):
        mid = (lo + hi) / 2
        if game["to_wall"](mid) < wall:
            lo = mid
        else:
            hi = mid
    return lo


def vision_between(game, entry, g0, g1):
    """How much vision score a player added between two game-clock times,
    from the recorder's 30-second snapshots. None if there are none."""
    if not entry or not game["scores"]:
        return None
    key = player_id(entry).lower()
    points = sorted([(0.0, 0.0)] + [(gt, float(v[key])) for gt, v in game["scores"]
                                    if v.get(key) is not None])
    if len(points) == 1:
        return None
    times = [p[0] for p in points]

    def at(g):
        i = bisect.bisect_right(times, g)
        if i >= len(points):
            return points[-1][1]
        (ga, va), (gb, vb) = points[i - 1], points[i]
        return va + (vb - va) * (g - ga) / (gb - ga) if gb > ga else vb
    return max(0.0, at(g1) - at(g0))


class Roster:
    def __init__(self, players, roster_names=None):
        self.players = players
        self.names = list(dict.fromkeys(p["name"] for p in players))   # each person once
        self.roster_names = roster_names or list(dict.fromkeys(p["roster"] for p in players))
        self.by_discord = {d.lower(): p["name"] for p in players for d in p["discord"]}
        self.by_riot = {}
        self.roles, self.rosters_of = {}, defaultdict(set)
        for p in players:
            for rid in p["riot"]:
                self.by_riot[rid.lower()] = p["name"]
                self.by_riot.setdefault(rid.split("#")[0].strip().lower(), p["name"])
            if p.get("role"):
                self.roles.setdefault(p["name"], p["role"])
            self.rosters_of[p["name"]].add(p.get("roster") or DEFAULT_ROSTER)
        self.empty = not players

    @classmethod
    def load(cls, path):
        data = load_rosters(path)
        return cls(data["players"], data["rosters"])

    def speaker(self, discord_name):
        return discord_name if self.empty else self.by_discord.get(discord_name.lower())

    def game_player(self, entry):
        for key in (entry.get("riotId") or "", entry.get("summonerName") or ""):
            for variant in (key, key.split("#")[0]):
                if variant and variant.lower() in self.by_riot:
                    return self.by_riot[variant.lower()]
        return None

    def role(self, name):
        return self.roles.get(name, "")

    def team_of(self, present):
        """Which roster played: the one with the most of these people on it."""
        best, best_count = None, 0
        for r in self.roster_names:
            count = sum(1 for name in present if r in self.rosters_of.get(name, ()))
            if count > best_count:
                best, best_count = r, count
        return best


# ---------------------------------------------------------------------------
# Turning transcripts + games into numbers
# ---------------------------------------------------------------------------

def analyze_session(path, games, roster, classifier, warnings, reviews=None, drafts=None):
    records = read_jsonl(path)
    meta = next((r for r in records if r.get("type") == "meta"), None)
    # A line with no words in it ("...") is a sound the speech model couldn't
    # make out: a laugh, a sigh, background noise. It isn't talking.
    utterances = [r for r in records if r.get("type") == "utterance"
                  and (re.search(r"\w", r.get("text") or "") or has_chinese(r.get("text")))]
    if not meta:
        warnings.append(f"{path.name}: no meta line; skipped.")
        return [], set(), [], [], []
    start = meta.get("audio_start_t") or (utterances[0]["t"] if utterances else None)
    if start is None:
        return [], set(), [], [], []
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
        # Flame / Not flame decisions made in the dashboard replace the automatic call.
        u["qid"] = f"{session_id}|{u['t']:.2f}|{u['speaker']}"
        u["auto_kind"] = ("Flame" if u["counts"].get(AT_TEAMMATES)
                          else NEGATIVE if u["counts"].get(NEGATIVE) else None)
        verdict = (reviews or {}).get(u["qid"])
        if verdict in ("not", "negative", "flame"):
            u["counts"].pop(AT_TEAMMATES, None)
            u["counts"].pop(NEGATIVE, None)
            if verdict == "flame":
                u["counts"][AT_TEAMMATES] = 1
                u["counts"].pop("Shotcalling", None)
            elif verdict == "negative":
                u["counts"][NEGATIVE] = 1
        u["review"] = verdict
    # Who started talking while someone else was mid-sentence.
    ordered = sorted(utterances, key=lambda u: u["t"])
    for i, u in enumerate(ordered):
        u["over"] = any(other["speaker"] != u["speaker"]
                        and other["t"] < u["t"] < other["t_end"] - TALK_OVER_GRACE_S
                        for other in ordered[max(0, i - 20):i])
    track_players = {roster.speaker(t["speaker"]) for t in meta.get("tracks", [])} - {None}

    in_session = sorted((g for g in games if g["start"] < end and g["end"] > start),
                        key=lambda g: g["start"])
    segments = [(max(g["start"], start), min(g["end"], end), g, n)
                for n, g in enumerate(in_session, 1)]
    if not segments:
        segments = [(start, end, None, None)]
        warnings.append(f"Session {date} ({session_id}): no recorded games found, so all "
                        "speech counts and fight/death/objective stats are missing.")

    base = {"session": session_id, "date": date.isoformat(),
            "week": (date - timedelta(days=date.weekday())).isoformat(),
            "month": date.strftime("%Y-%m")}
    rows, played = [], []
    for w0, w1, game, number in segments:
        if w1 <= w0:
            continue
        segment = [u for u in utterances if w0 <= u["t"] < w1]
        present = set(track_players)
        entries = {}
        fights, plays, deaths, objectives = [], [], defaultdict(list), []
        if game:
            fights, plays = kill_clusters(game)
            lookup = name_lookup(game["players"])
            for entry in game["players"]:
                name = roster.game_player(entry)
                if name:
                    present.add(name)
                    entries.setdefault(name, entry)
            for e in game["events"]:
                kind = str(e.get("EventName", ""))
                if kind == "ChampionKill":
                    victim = lookup.get(str(e.get("VictimName", "")).lower())
                    name = roster.game_player(victim) if victim else None
                    if name:
                        deaths[name].append(e["wall"])
                elif kind.endswith("Kill") and any(o in kind for o in OBJECTIVE_EVENTS):
                    objectives.append(e["wall"])
            early_end, late = phase_times(game)
        team = roster.team_of(present)
        result = our_result(game, roster) if game else None
        ours, theirs, side = [], [], None
        if game:
            side = our_side(game, roster)
            for entry in game["players"]:
                if not entry.get("championName"):
                    continue
                if side and entry.get("team") == side:
                    ours.append([entry["championName"], roster.game_player(entry) or ""])
                elif side:
                    theirs.append(entry["championName"])
        draft = drafts.find([c for c, _ in ours], theirs) if drafts and ours else None
        played.append({**base, "game": number, "game_file": game["file"] if game else None,
                       "minutes": round((w1 - w0) / 60, 3), "result": result, "roster": team,
                       "ours": ours, "theirs": theirs, "draft": draft,
                       "side": {"ORDER": "blue", "CHAOS": "red"}.get(side)})
        played[-1]["_window"] = (w0, w1, game, early_end if game else None,
                                 late if game else None, entries)

        for player in sorted(present):
            said = [u for u in segment if u["player"] == player]
            if game:
                lane = lane_of(roster.role(player), entries.get(player))
                early, later = game["to_wall"](early_end(lane)), game["to_wall"](late)
                windows = [("early", w0, min(early, w1)), ("mid", max(early, w0), min(later, w1)),
                           ("late", max(later, w0), w1)]
            else:
                windows = [(None, w0, w1)]
            for phase, a, b in windows:
                if b - a <= 0:
                    continue
                window = [u for u in segment if a <= u["t"] < b]
                mine = [u for u in window if u["player"] == player]
                fights_here = [f for f in fights if a <= f[0] + FIGHT_LEAD_S < b]
                objectives_here = [o for o in objectives if a <= o < b]
                my_deaths = [d for d in deaths[player] if a <= d < b]
                vision = (vision_between(game, entries.get(player), to_game_time(game, a),
                                         to_game_time(game, b)) if game else None)
                cats = Counter()
                for u in mine:
                    cats.update(u["counts"])
                rows.append({
                    **base,
                    "game": number,
                    "game_file": game["file"] if game else None,
                    "result": result,
                    "roster": team,
                    "phase": phase,
                    "player": player,
                    "minutes": round((b - a) / 60, 3),
                    "talk_s": round(sum(u["t_end"] - u["t"] for u in mine), 2),
                    "team_talk_s": round(sum(u["t_end"] - u["t"] for u in window), 2),
                    "words": sum(u["n_words"] for u in mine),
                    "fights": len(fights_here),
                    "fights_spoke": sum(1 for f0, f1 in fights_here
                                        if any(u["t"] < f1 and u["t_end"] > f0 for u in said)),
                    "fight_words": sum(u["n_words"] for f0, f1 in fights_here
                                       for u in said if f0 <= u["t"] < f1),
                    "plays": sum(1 for p in plays if a <= p < b) + len(objectives_here),
                    "deaths": len(my_deaths),
                    "deaths_blamed": sum(1 for d in my_deaths
                                         if any(d <= u["t"] <= d + BLAME_WINDOW_S
                                                and u["counts"].get(AT_TEAMMATES) for u in said)),
                    "talk_overs": sum(1 for u in mine if u["over"]),
                    "talk_zh_s": round(sum(u["t_end"] - u["t"] for u in mine
                                           if u.get("language") == "zh"), 2),
                    "team_shotcalls": sum(u["counts"].get("Shotcalling", 0) for u in window),
                    "objectives": len(objectives_here),
                    "objectives_itemcall": sum(
                        1 for o in objectives_here
                        if any(o - OBJECTIVE_SETUP_S <= u["t"] <= o
                               and (u["counts"].get("Item timers") or u["counts"].get("Resources"))
                               for u in said)),
                    "vision": round(vision, 2) if vision is not None else 0,
                    "vision_minutes": round((b - a) / 60, 3) if vision is not None else 0,
                    "cats": {k: v for k, v in cats.items() if v},
                })

    # Word-for-word quotes of every flame line (and other negative lines),
    # so they can be looked at directly, with when they were said.
    quotes = []
    by_time = sorted(utterances, key=lambda u: u["t"])
    starts = [u["t"] for u in by_time]
    for u in utterances:
        kind = ("Flame" if u["counts"].get(AT_TEAMMATES)
                else NEGATIVE if u["counts"].get(NEGATIVE) else None)
        if not kind and not u["review"] and not u["auto_kind"]:
            continue
        where = next((g for g in played if g["_window"][0] <= u["t"] < g["_window"][1]), None)
        clock = phase = None
        if where and where["_window"][2]:
            w0, w1, game, early_end, late, entries = where["_window"]
            clock = to_game_time(game, u["t"])
            lane = lane_of(roster.role(u["player"]), entries.get(u["player"]))
            phase = "early" if clock < early_end(lane) else "mid" if clock < late else "late"
        # What was said around it, by everyone, for the "more context" button.
        lo = bisect.bisect_left(starts, u["t"] - CONTEXT_BEFORE_S)
        hi = bisect.bisect_right(starts, u["t"] + CONTEXT_AFTER_S)
        context = [[datetime.fromtimestamp(c["t"]).strftime("%H:%M:%S"), c["player"] or c["speaker"],
                    c["text"], c is u] for c in by_time[lo:hi]]
        quotes.append({**base, "id": u["qid"], "review": u["review"], "auto_kind": u["auto_kind"],
                       "kind": kind or "Cleared", "context": context,
                       "player": u["player"] or u["speaker"],
                       "on_roster": u["player"] is not None,
                       "game": where["game"] if where else None,
                       "roster": where["roster"] if where else roster.team_of({u["player"]}),
                       "clock": round(clock) if clock is not None else None, "phase": phase,
                       "time": datetime.fromtimestamp(u["t"]).strftime("%H:%M:%S"),
                       "text": u.get("text", ""),
                       "text_en": u.get("text_en", "") if u.get("language") == "zh" else ""})
    # Between games: everything said outside the recorded games, kept apart
    # from the in-game stats (only when this session has recorded games).
    between = []
    windows = [g["_window"] for g in played if g["_window"][2]]
    if windows:
        gap_minutes = max(0.0, (end - start) - sum(w[1] - w[0] for w in windows)) / 60
        outside = [u for u in utterances if not any(w[0] <= u["t"] < w[1] for w in windows)]
        team = roster.team_of(track_players)
        for name in sorted({u["player"] or u["speaker"] for u in outside}):
            mine = [u for u in outside if (u["player"] or u["speaker"]) == name]
            cats = Counter()
            for u in mine:
                cats.update(u["counts"])
            between.append({**base, "roster": team, "player": name,
                            "on_roster": mine[0]["player"] is not None,
                            "minutes": round(gap_minutes, 2),
                            "talk_s": round(sum(u["t_end"] - u["t"] for u in mine), 1),
                            "words": sum(u["n_words"] for u in mine),
                            "cats": {k: v for k, v in cats.items() if v}})
    for g in played:
        del g["_window"]
    return rows, unmapped, played, quotes, between


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
    stats["item_or_gold_talk_before_objectives_%"] = pct(t["objectives_itemcall"], t["objectives"])
    stats["resource_calls_per_10min"] = per10(c["Resources"])
    stats["vision_talk_per_10min"] = per10(c["Vision talk"])
    for kind in VISION_KINDS:
        stats[f"{kind.lower().replace(' ', '_')}_per_10min"] = per10(c[kind])
    stats["vision_score_per_10min"] = (round(10 * t["vision"] / t["vision_minutes"], 2)
                                       if t["vision_minutes"] >= 5 else "")
    stats["shotcalls_per_10min"] = per10(c["Shotcalling"])
    stats["objective_mentions_per_10min"] = per10(c["Objectives"])
    stats["accountability_per_10_plays"] = (round(10 * c["Accountability"] / t["plays"], 2)
                                            if t["plays"] >= 5 else "")
    stats["positivity_%"] = pct(c["Positive"], c["Positive"] + c[AT_TEAMMATES], 3)
    stats["flame_at_teammates_per_10min"] = per10(c[AT_TEAMMATES])
    stats["negative_talk_per_10min"] = per10(c[NEGATIVE])
    stats["blame_after_death_%"] = pct(t["deaths_blamed"], t["deaths"], 2)
    stats["fight_presence_%"] = pct(t["fights_spoke"], t["fights"])
    stats["words_per_teamfight"] = round(t["fight_words"] / t["fights"], 1) if t["fights"] else ""
    stats["talk_overs_per_10min"] = per10(t["talk_overs"])
    stats["chinese_share_%"] = pct(t["talk_zh_s"], t["talk_s"])
    return stats


def write_csv(path, rows):
    """One line per player per session: whole games ("all"), then the early,
    mid and late game separately."""
    by_session = defaultdict(list)
    for r in rows:
        by_session[(r["date"], r["session"], r["player"])].append(r)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = None
        for (date, session, player), everything in sorted(by_session.items()):
            for phase in ("all",) + PHASES:
                group = everything if phase == "all" else [r for r in everything if r["phase"] == phase]
                if not group:
                    continue
                t = add_up(group)
                games = {r["game"]: r["result"] for r in group if r["game"]}
                team_calls = t["team_shotcalls"]
                row = {"date": date, "session": session, "roster": group[0]["roster"] or "",
                       "player": player, "part_of_game": phase, "games": len(games),
                       "wins": list(games.values()).count("Win"),
                       "losses": list(games.values()).count("Lose"),
                       "minutes": round(t["minutes"], 1), "deaths": t["deaths"], "fights": t["fights"],
                       "plays": t["plays"], **derived_stats(t),
                       "shotcall_share_%": round(100 * t["cats"]["Shotcalling"] / team_calls, 1) if team_calls else ""}
                if writer is None:
                    writer = csv.DictWriter(f, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)


# ---------------------------------------------------------------------------
# Build everything
# ---------------------------------------------------------------------------

def load_flame_reviews(paths):
    """Lines marked in the dashboard: {line id: "flame" | "negative" | "not" (neither)}."""
    try:
        return json.loads((paths.data / "flame_reviews.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_flame_review(paths, line_id, verdict):
    reviews = load_flame_reviews(paths)
    if verdict in ("flame", "negative", "not"):
        reviews[str(line_id)] = verdict
    else:
        reviews.pop(str(line_id), None)        # undone: back to the automatic call
    (paths.data / "flame_reviews.json").write_text(json.dumps(reviews, indent=1, ensure_ascii=False),
                                                   encoding="utf-8")


def champion_icons(paths, names, log=print):
    """Small square icons for these champions, from Riot's Data Dragon,
    saved in _data/champions so each is downloaded once. Returns
    {name: "data:image/png;base64,..."}; champions it can't get are left out
    (the dashboard shows their initials instead)."""
    import base64
    shipped = bundled("champions")              # every champion, packed in with the app
    try:
        shipped_ids = json.loads((shipped / "ids.json").read_text(encoding="utf-8"))["ids"]
    except (OSError, ValueError, KeyError):
        shipped_ids = {}
    icons = {}
    for n in list(names):
        if n in shipped_ids and (shipped / f"{shipped_ids[n]}.png").exists():
            icons[n] = "data:image/png;base64," + base64.b64encode(
                (shipped / f"{shipped_ids[n]}.png").read_bytes()).decode("ascii")
    # Champions newer than the app: downloaded once into _data/champions.
    folder = paths.data / "champions"
    ids_path = folder / "ids.json"
    try:
        ids = json.loads(ids_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ids = {}
    names = {n for n in names if n and n not in icons}
    missing = [n for n in names if n not in ids or not (folder / f"{ids[n]}.png").exists()]
    if missing:
        try:
            import requests
            version = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=5).json()[0]
            if any(n not in ids for n in missing):
                data = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json",
                                    timeout=10).json()["data"]
                ids.update({c["name"]: c["id"] for c in data.values()})
                folder.mkdir(parents=True, exist_ok=True)
                ids_path.write_text(json.dumps(ids, ensure_ascii=False, indent=0), encoding="utf-8")
            for n in missing:
                if n in ids and not (folder / f"{ids[n]}.png").exists():
                    image = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/"
                                         f"{ids[n]}.png", timeout=10)
                    if image.ok and image.content[:4] == b"\x89PNG":
                        (folder / f"{ids[n]}.png").write_bytes(image.content)
        except Exception as error:
            log(f"  (Champion icons not downloaded: {type(error).__name__}. They'll be tried again next time.)")
    for n in names:
        path = folder / f"{ids.get(n, '')}.png"
        if n in ids and path.exists():
            icons[n] = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    return icons


def font_css():
    """Lato, embedded in the dashboard so it looks the same opened anywhere, offline."""
    import base64
    ranges = {"latin": "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
              "latin-ext": "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF"}
    out = []
    for weight in (400, 700):
        for subset, unicode_range in ranges.items():
            path = bundled("ui") / "fonts" / f"lato-{subset}-{weight}-normal.woff2"
            if path.exists():
                data = base64.b64encode(path.read_bytes()).decode("ascii")
                out.append(f'@font-face {{ font-family: "Lato"; font-style: normal; font-weight: {weight}; '
                           f'font-display: swap; src: url(data:font/woff2;base64,{data}) format("woff2"); '
                           f'unicode-range: {unicode_range}; }}')
    return "\n".join(out)


def load_game_delays(paths):
    """Per-game spectator delays set in the app: {first file name: seconds}."""
    path = paths.data / "game_delays.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_game_delay(paths, game_file, seconds):
    delays = load_game_delays(paths)
    if seconds:
        delays[game_file] = float(seconds)
    else:
        delays.pop(game_file, None)
    (paths.data / "game_delays.json").write_text(json.dumps(delays, indent=1), encoding="utf-8")


def game_list(paths):
    """Every recorded game, merged and summarised, for the app's Games tab."""
    files = sorted(paths.games.glob("game_*.jsonl")) if paths.games.is_dir() else []
    roster = Roster.load(paths.roster)
    drafts = DraftMatcher(load_drafts(paths), paths)
    out = []
    for g in load_games(files, load_game_delays(paths)):
        ours = [n for n in (roster.game_player(p) for p in g["players"]) if n]
        side = our_side(g, roster)
        champs = [p.get("championName") for p in g["players"] if p.get("championName")]
        mine = [p.get("championName") for p in g["players"] if side and p.get("team") == side]
        draft = drafts.find(mine, [c for c in champs if c not in mine]) if mine else None
        out.append({
            "id": g["file"], "start": g["start"], "end": g["end"], "pieces": len(g["files"]),
            "spectator": g["spectator"], "player_view": g["player_view"],
            "delay": g["delay"], "result": our_result(g, roster),
            "kills": sum(1 for e in g["events"] if e.get("EventName") == "ChampionKill"),
            "objectives": sum(1 for e in g["events"] if str(e.get("EventName", "")).endswith("Kill")
                              and any(o in str(e.get("EventName")) for o in OBJECTIVE_EVENTS)),
            "champions": [p.get("championName") for p in g["players"]],
            "our_players": ours,
            "roster": roster.team_of(set(ours)),
            "draft": f"Game {draft['game']} of drafter.lol/draft/{draft['series']}" if draft else None,
        })
    return out[::-1]


def roster_candidates(paths):
    """Who appears in the recordings, to pick from in the app's Roster tab:
    the Discord names in transcripts and the Riot IDs in games."""
    discord = {}
    for path in sorted(paths.transcripts.glob("comms_*.jsonl")) if paths.transcripts.is_dir() else []:
        for r in read_jsonl(path)[:1]:
            for t in r.get("tracks", []):
                d = discord.setdefault(t["speaker"], {"name": t["speaker"], "lines": 0, "sessions": 0})
                d["lines"] += t.get("lines", 0)
                d["sessions"] += 1
    riot = {}
    files = sorted(paths.games.glob("game_*.jsonl")) if paths.games.is_dir() else []
    for g in load_games(files):
        for p in g["players"]:
            rid = p.get("riotId") or p.get("summonerName")
            if not rid or rid == "#" or p.get("isBot"):
                continue
            entry = riot.setdefault(rid, {"riotId": rid, "games": 0, "champions": []})
            entry["games"] += 1
            if p.get("championName") and p["championName"] not in entry["champions"]:
                entry["champions"].append(p["championName"])
    return {"discord": sorted(discord.values(), key=lambda d: -d["lines"]),
            "riot": sorted(riot.values(), key=lambda r: -r["games"])}


def save_roster(paths, rosters, players):
    """Write Roster.txt from the app's Rosters tab.
    rosters: names in order; players: [{name, discord: [], riot: [], role, roster}]."""
    def clean(values):
        return ", ".join(str(x).strip().replace("|", "/").replace(",", " ")
                         for x in values if str(x).strip())
    names = [str(r).strip().replace("[", "(").replace("]", ")") for r in rosters if str(r).strip()]
    for p in players:
        if p.get("roster") and p["roster"] not in names:
            names.append(p["roster"])
    names = names or [DEFAULT_ROSTER]
    lines = ["# Your team's rosters (edited in the app: Rosters tab).",
             "# [Roster name], then one line per player:",
             "# Name | Discord username(s) | Riot ID(s) | Role"]
    for r in names:
        lines += ["", f"[{r}]"]
        for p in players:
            name = str(p.get("name", "")).strip().replace("|", "/")
            if name and (p.get("roster") or names[0]) == r:
                role = p.get("role") if p.get("role") in ROLES else ""
                lines.append(f"{name} | {clean(p.get('discord', []))} | {clean(p.get('riot', []))} | {role}")
    paths.roster.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(paths, log=print, open_browser=True, open_roster=True):
    """Rebuild Dashboard.html and Comms stats.csv. Returns the dashboard path."""
    transcripts = sorted(paths.transcripts.glob("comms_*.jsonl")) if paths.transcripts.is_dir() else []
    game_files = sorted(paths.games.glob("game_*.jsonl")) if paths.games.is_dir() else []
    log(f"Found {len(transcripts)} transcript(s) and {len(game_files)} recorded game(s).")
    games = load_games(game_files, load_game_delays(paths))

    if not paths.roster.exists():
        discord_names = set()
        for path in transcripts:
            for r in read_jsonl(path):
                if r.get("type") == "meta":
                    discord_names.update(t["speaker"] for t in r.get("tracks", []))
        riot_counts = Counter(p.get("riotId") for g in games for p in g["players"]
                              if p.get("riotId") and p.get("riotId") != "#")
        write_roster_template(paths.roster, discord_names, riot_counts)
        log("No roster yet: open the Rosters tab to say who's who.")
        if open_roster and os.name == "nt":
            os.startfile(paths.roster)

    roster = Roster.load(paths.roster)
    vocab = {}
    if paths.vocab.exists():
        try:
            vocab = json.loads(paths.vocab.read_text(encoding="utf-8"))
        except ValueError:
            pass
    teammate_names = roster.names + [d for p in roster.players for d in p["discord"]]
    classifier = Classifier(load_categories(paths.callouts), vocab, teammate_names)
    try:
        from transcriber import TermFixer, read_corrections
        corrections = read_corrections(paths)
        if corrections:
            classifier.fix = TermFixer({}, [], {}, corrections).fix
    except Exception as error:         # the stats still work without corrections
        log(f"  (Corrections not applied to the stats: {error})")

    warnings, all_rows, unmapped, played, quotes, between = [], [], set(), [], [], []
    drafts = DraftMatcher(load_drafts(paths), paths)
    if roster.empty:
        warnings.append("No roster yet, so people are shown by Discord name and fight/death/objective "
                        "stats are missing. Open the Rosters tab to say who's who.")
    for path in transcripts:
        rows, missing, games_here, said, outside = analyze_session(
            path, games, roster, classifier, warnings, load_flame_reviews(paths), drafts)
        quotes.extend(said)
        between.extend(outside)
        all_rows.extend(rows)
        played.extend(games_here)
        unmapped |= missing
    if unmapped:
        warnings.append("These Discord names aren't on a roster (Rosters tab), so their comms only count "
                        "toward the team total: " + ", ".join(sorted(unmapped)))
    watched = [g for g in games if g.get("spectator") and not g.get("player_view")]
    if watched:
        warnings.append(
            f"{len(watched)} game(s) were only recorded by a spectator. League doesn't tell "
            "spectators about dragons, barons or heralds, so \"item or gold talk before objectives\" "
            "can't be worked out for those games. Fix: have one of the five players also record "
            "(see the Games tab). Spectators may also see the game late: set the delay per game in "
            "the Games tab.")
    if roster.players and games:
        seen = {n for g in games for n in (roster.game_player(p) for p in g["players"]) if n}
        missing_riot = [n for n in roster.names
                        if any(p["riot"] for p in roster.players if p["name"] == n) and n not in seen]
        if missing_riot:
            warnings.append("No recorded games have these players' accounts (check them in the "
                            "Rosters tab): " + ", ".join(missing_riot))
    no_role = [n for n in roster.names if not roster.role(n)
               and any(p["riot"] for p in roster.players if p["name"] == n)
               and any(r["player"] == n and r["phase"] for r in all_rows)]
    if no_role:
        warnings.append("No role set for " + ", ".join(no_role) + " (Rosters tab). Their laning phase "
                        "is taken to end with the bot lane's first tower.")

    order = list(roster.names)
    for r in all_rows:
        if r["player"] not in order:
            order.append(r["player"])
    players = [p for p in order if any(r["player"] == p for r in all_rows)]
    roster_list = []
    for name in roster.roster_names:
        members = [p["name"] for p in roster.players if p["roster"] == name]
        members += [r["player"] for r in all_rows if r["roster"] == name]   # subs who played
        roster_list.append({"name": name, "players": [p for p in dict.fromkeys(members) if p in players]})

    data = {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "version": VERSION,
        "players": players,
        "rosters": roster_list,
        "info_kinds": INFO_KINDS,
        "vision_kinds": VISION_KINDS,
        "rows": all_rows,
        "games": played,
        "quotes": quotes,
        "between": between,
        "icons": champion_icons(paths, {c for g in played for c in
                                        [x[0] for x in g["ours"]] + g["theirs"]
                                        + ((g["draft"] or {}).get("bans", []) + (g["draft"] or {}).get("their_bans", []))},
                                log),
        "warnings": warnings,
    }
    template = bundled("dashboard_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = template.replace("/*__DATA__*/null", payload).replace("/*__FONTS__*/", font_css())
    paths.dashboard.write_text(page, encoding="utf-8")
    if all_rows:
        write_csv(paths.csv, all_rows)

    for w in warnings:
        log("  Note: " + w)
    sessions = len({g["session"] for g in played})
    log(f"Dashboard updated: {sessions} session(s), {len(players)} player(s).")
    if open_browser:
        webbrowser.open(paths.dashboard.as_uri())
    return paths.dashboard


if __name__ == "__main__":
    from common import Paths
    build(Paths().ensure())
