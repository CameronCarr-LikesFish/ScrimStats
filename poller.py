"""
Game recorder (the "event poller").

While a League game is running, the game serves a small web API on this PC
(https://127.0.0.1:2999). This checks it once per second and writes every
game event (kills, dragons, towers...) to Game recordings\\game_<date>_<time>.jsonl,
stamped with BOTH the real-world time ("wall_clock") and the in-game clock
("game_time"), so the game can be lined up with the voice recording later.

File contents, one JSON object per line:
  meta        first line: version, start time, timezone
  clock_sync  every 10 s: one (wall_clock, game_time) pair
  players     once: which player is on which champion
  event       each game event exactly as the game reported it, plus the
              wall_clock and game_time of the poll that first saw it
  end         last line, when the file closes normally
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timezone

import requests
import urllib3

from common import VERSION

API_BASE = "https://127.0.0.1:2999/liveclientdata"
POLL_INTERVAL_S = 1.0
CLOCK_SYNC_INTERVAL_S = 10.0
HEARTBEAT_INTERVAL_S = 60.0
# (connect, read) limits. The game is on this PC, so it connects in
# milliseconds; Windows takes ~2 s to say nothing is there, so keep this short.
REQUEST_TIMEOUT_S = (1.0, 2.0)
GAME_GONE_AFTER_S = 5.0          # silence this long = the game closed
NEW_GAME_CLOCK_DROP_S = 10.0     # clock jumping back this much = a new game

# The game uses a self-signed certificate; the connection never leaves this PC.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def format_wall_clock(unix_seconds):
    """ISO 8601 local time with timezone, e.g. 2026-09-30T19:30:15.123-04:00"""
    return (datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
            .astimezone().isoformat(timespec="milliseconds"))


def wall_clock_now():
    return format_wall_clock(time.time())


def format_game_clock(seconds):
    try:
        seconds = max(0, int(seconds))
    except (TypeError, ValueError):
        return "??:??"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def shout_case(name):
    """'ChampionKill' -> 'CHAMPION_KILL'"""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", str(name)).upper()


class GameRecording:
    """The .jsonl file for one game, plus what we've seen so far."""

    def __init__(self, folder, wall_clock, game_time):
        folder.mkdir(parents=True, exist_ok=True)
        local_now = datetime.now().astimezone()
        stem = "game_" + local_now.strftime("%Y-%m-%d_%H%M%S")
        path = folder / f"{stem}.jsonl"
        suffix = 2
        while path.exists():
            path = folder / f"{stem}_{suffix}.jsonl"
            suffix += 1
        self.path = path
        self.file = open(path, "x", encoding="utf-8", newline="\n")
        self.seen_event_ids = set()
        self.events_logged = 0
        self.last_game_time = game_time
        self.last_clock_sync = None
        self.last_heartbeat = time.monotonic()
        self.first_event_batch = True
        self.players_written = False
        self.last_players_attempt = None
        self.champion_of = {}
        self.write({
            "type": "meta",
            "script_version": VERSION,
            "started_at": wall_clock,
            "timezone": local_now.tzname(),
            "utc_offset": local_now.isoformat()[-6:],
            "game_time_at_start": game_time,
            "api": API_BASE,
            "poll_interval_s": POLL_INTERVAL_S,
            "clock_sync_interval_s": CLOCK_SYNC_INTERVAL_S,
        })

    def write(self, record):
        """Append one line and push it to disk immediately, so a crash or
        closed window never leaves a half-written file."""
        self.file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())

    def close(self, reason):
        try:
            self.write({"type": "end", "wall_clock": wall_clock_now(), "reason": reason,
                        "events_logged": self.events_logged,
                        "last_game_time": self.last_game_time})
        finally:
            self.file.close()


class Poller:
    """Checks the game once a second. Call run() in a background thread and
    set stop_event to stop; the current file is always closed cleanly.

    log(text) receives the human-readable lines; status(text) receives a
    short one-line summary for the app window."""

    def __init__(self, folder, log=print, status=lambda text: None):
        self.folder = folder
        self.log = log
        self.status = status
        self.session = requests.Session()
        self.session.verify = False
        self.recording = None
        self.last_answer = None
        self.said_waiting = False
        self.last_error_text = None

    # --- talking to the game ---

    def fetch(self, endpoint):
        """Parsed JSON, or None when there's no game (connection refused is
        normal between games) or the game isn't ready yet."""
        try:
            response = self.session.get(f"{API_BASE}/{endpoint}", timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def read_game_clock(self):
        """The game clock plus the real time it matches: the midpoint of the
        request, since the game read its clock somewhere in between."""
        before = time.time()
        stats = self.fetch("gamestats")
        after = time.time()
        if not isinstance(stats, dict) or "gameTime" not in stats:
            return None
        try:
            game_time = float(stats["gameTime"])
        except (TypeError, ValueError):
            return None
        return format_wall_clock((before + after) / 2), game_time

    # --- the once-per-second step ---

    def tick(self):
        clock = self.read_game_clock()
        if clock is None:
            self.on_no_game_response()
            return
        self.last_answer = time.monotonic()
        wall_clock, game_time = clock

        if self.recording is None:
            self.start_recording(wall_clock, game_time)
        elif game_time < self.recording.last_game_time - NEW_GAME_CLOCK_DROP_S:
            self.log("Game clock jumped backwards, so this is a new game.")
            self.finish_recording("new_game_detected")
            self.start_recording(wall_clock, game_time)

        rec = self.recording
        rec.last_game_time = game_time
        now = time.monotonic()

        if (rec.last_clock_sync is None
                or now - rec.last_clock_sync >= CLOCK_SYNC_INTERVAL_S - POLL_INTERVAL_S / 2):
            rec.write({"type": "clock_sync", "wall_clock": wall_clock, "game_time": game_time})
            rec.last_clock_sync = now

        if not rec.players_written:
            self.try_record_players(wall_clock, game_time)

        feed = self.fetch("eventdata")
        events = feed.get("Events") if isinstance(feed, dict) else None
        if isinstance(events, list):
            self.log_new_events(events, wall_clock, game_time)

        self.status(f"Recording {rec.path.name}  ·  game clock {format_game_clock(game_time)}"
                    f"  ·  {rec.events_logged} events")
        if now - rec.last_heartbeat >= HEARTBEAT_INTERVAL_S:
            self.log(f"  … still recording: game clock {format_game_clock(game_time)}, "
                     f"{rec.events_logged} events so far")
            rec.last_heartbeat = now

    def on_no_game_response(self):
        if self.recording is None:
            if not self.said_waiting:
                self.log("Waiting for a game…")
                self.status("Waiting for a game…")
                self.said_waiting = True
            return
        if time.monotonic() - self.last_answer >= GAME_GONE_AFTER_S:
            self.finish_recording("game_closed")

    def log_new_events(self, events, wall_clock, game_time):
        rec = self.recording
        new_events = [e for e in events
                      if isinstance(e, dict) and e.get("EventID") not in rec.seen_event_ids]
        if rec.first_event_batch and new_events and game_time > 60:
            self.log(f"  (Started mid-game: catching up on {len(new_events)} earlier events.)")
        rec.first_event_batch = False
        for event in new_events:
            record = {"type": "event", "wall_clock": wall_clock, "game_time": game_time}
            record.update(event)
            rec.write(record)
            rec.seen_event_ids.add(event.get("EventID"))
            rec.events_logged += 1
            self.log(self.describe(event))
            if event.get("EventName") == "GameEnd":
                self.log("Game over. The file stays open until the game window closes.")

    def try_record_players(self, wall_clock, game_time):
        rec = self.recording
        now = time.monotonic()
        if rec.last_players_attempt is not None and now - rec.last_players_attempt < 10:
            return
        rec.last_players_attempt = now
        players = self.fetch("playerlist")
        if not isinstance(players, list) or not players:
            return
        summary = []
        for p in players:
            if not isinstance(p, dict):
                continue
            champion = p.get("championName")
            for key in ("riotId", "riotIdGameName", "summonerName"):
                name = p.get(key)
                if name and champion:
                    rec.champion_of[name] = champion
                    rec.champion_of[name.split("#")[0]] = champion
            summary.append({key: p.get(key) for key in
                            ("riotId", "summonerName", "championName", "team", "position", "isBot")})
        rec.write({"type": "players", "wall_clock": wall_clock, "game_time": game_time,
                   "players": summary})
        rec.players_written = True

    def describe(self, event):
        """One readable line for the app window (the file gets the raw event)."""
        def who(name):
            return self.recording.champion_of.get(name, name) if name else "?"

        name = event.get("EventName", "?")
        killer = who(event.get("KillerName"))
        if name == "ChampionKill":
            text = f"{killer} killed {who(event.get('VictimName'))}"
            assisters = event.get("Assisters") or []
            if assisters:
                text += " (assist: " + ", ".join(who(a) for a in assisters) + ")"
        elif name == "Multikill":
            text = f"{killer} multikill x{event.get('KillStreak', '?')}"
        elif name == "FirstBlood":
            text = f"{who(event.get('Recipient'))} got first blood"
        elif name == "Ace":
            text = f"{who(event.get('Acer'))} aced (team {event.get('AcingTeam', '?')})"
        elif name == "DragonKill":
            text = f"{killer} took {event.get('DragonType', '?')} dragon"
        elif name == "TurretKilled":
            text = f"{killer} destroyed {event.get('TurretKilled', 'a turret')}"
        elif name == "InhibKilled":
            text = f"{killer} destroyed {event.get('InhibKilled', 'an inhibitor')}"
        elif name == "GameEnd":
            text = f"Result: {event.get('Result', '?')}"
        elif "KillerName" in event:
            text = f"by {killer}"
        else:
            text = ""
        if str(event.get("Stolen", "")).lower() == "true":
            text += " (STOLEN)"
        line = f"[{format_game_clock(event.get('EventTime'))}] {shout_case(name)}"
        return f"{line} — {text}" if text else line

    # --- files ---

    def start_recording(self, wall_clock, game_time):
        self.recording = GameRecording(self.folder, wall_clock, game_time)
        self.said_waiting = False
        self.log(f"Game detected → {self.recording.path.name}")

    def finish_recording(self, reason):
        rec = self.recording
        self.recording = None
        rec.close(reason)
        label = {"game_closed": "Game ended", "new_game_detected": "Previous game closed",
                 "stopped_by_user": "Recording stopped"}.get(reason, "Recording closed")
        self.log(f"{label}: {rec.events_logged} events saved to {rec.path.name}")

    # --- main loop ---

    def run(self, stop_event):
        next_tick = time.monotonic()
        while not stop_event.is_set():
            try:
                self.tick()
            except Exception as error:
                text = f"{type(error).__name__}: {error}"
                if text != self.last_error_text:
                    self.log(f"Unexpected problem (still running): {text}")
                    self.last_error_text = text
            next_tick += POLL_INTERVAL_S
            delay = next_tick - time.monotonic()
            if delay > 0:
                stop_event.wait(delay)       # wakes immediately when stopped
            else:
                next_tick = time.monotonic()
        if self.recording is not None:
            self.finish_recording("stopped_by_user")
        self.status("Not recording")


if __name__ == "__main__":
    # Developer use: run the recorder in a console. Ctrl+C stops it cleanly.
    from common import Paths
    stop = threading.Event()
    worker = threading.Thread(target=Poller(Paths().ensure().games).run, args=(stop,))
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.5)
    except KeyboardInterrupt:
        stop.set()
        worker.join()
