"""
ScrimStats Recorder: the small program a teammate runs during scrims.

It only records games (the same recorder as ScrimStats, no transcription,
no dashboard) and, when each game ends, posts the file to the team's
Discord channel so the person running ScrimStats gets it automatically.

Files sit next to the program:
  ScrimStats Recorder.exe
  recorder.json        the Discord webhook link (made by ScrimStats) and name
  Game recordings\\     every game recorded, kept here as well

Close the window (or press Ctrl+C) to stop. Anything that couldn't be sent
(no internet) is sent the next time it starts.
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

from common import VERSION
import discord_link
from poller import Poller

HERE = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
FOLDER = HERE / "Game recordings"
SENT = FOLDER / ".sent.json"


def say(text):
    # Plain characters only: the console window can't show "…" or "—".
    text = str(text).replace("…", "...").replace("—", "-").replace("→", "->").replace("·", "|")
    print(time.strftime("%H:%M:%S"), " ", text, flush=True)


def load_config():
    try:
        return json.loads((HERE / "recorder.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Sender:
    """Posts finished games to Discord, one at a time, in the background."""

    def __init__(self, webhook, name, roster=()):
        self.webhook, self.name, self.roster = webhook, name, roster
        self.lock = threading.Lock()
        try:
            self.sent = set(json.loads(SENT.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            self.sent = set()

    def send_waiting(self):
        """Every finished game not sent yet (including ones from before)."""
        with self.lock:
            for path in sorted(FOLDER.glob("game_*.jsonl")):
                if path.name in self.sent or not finished(path):
                    continue
                ok, reason = discord_link.scrim_check(path, self.roster)
                if not ok:
                    self.sent.add(path.name)          # never sent: solo queue, ARAM, a duo's game...
                    say(f"Not sending {path.name}: {reason}. (Kept on this PC.)")
                    continue
                try:
                    discord_link.post_game(self.webhook, path, self.name)
                    self.sent.add(path.name)
                    say(f"Sent {path.name} to Discord.")
                except Exception as error:
                    say(f"Couldn't send {path.name} yet ({type(error).__name__}). It'll be retried.")
                    break
            FOLDER.mkdir(exist_ok=True)
            SENT.write_text(json.dumps(sorted(self.sent)), encoding="utf-8")


def finished(path):
    """A file whose game has ended (its last line is the "end" record), or an
    older file the recorder isn't writing to any more."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, path.stat().st_size - 400))
            tail = f.read().decode("utf-8", "replace")
        return '"type": "end"' in tail or time.time() - path.stat().st_mtime > 120
    except OSError:
        return False


def main():
    # The console can't show every character; never crash over one.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    os.system("title ScrimStats Recorder")
    config = load_config()
    webhook = config.get("webhook", "")
    name = config.get("name") or os.environ.get("USERNAME", "a teammate")
    print(f"ScrimStats Recorder v{VERSION}")
    print("=" * 60)
    print("Leave this window open during scrims. Every game is recorded")
    print("on its own. Close the window when you're done.")
    print("=" * 60, flush=True)
    sender = None
    if discord_link.valid_webhook(webhook):
        sender = Sender(webhook, name, config.get("roster") or [])
        say(f"Connected to the team's Discord channel. Games are sent as \"{name}\".")
        say("Only custom games with 3 or more of the roster are sent; everything else stays on this PC.")
        threading.Thread(target=sender.send_waiting, daemon=True).start()
    else:
        say("Not connected to Discord (no recorder.json). Games are saved in the")
        say(f"\"Game recordings\" folder next to this program: send those files yourself.")

    def log(text):
        say(text)
        if sender and ("Game ended" in text or "Previous game closed" in text or "Recording stopped" in text):
            threading.Thread(target=sender.send_waiting, daemon=True).start()

    stop = threading.Event()
    worker = threading.Thread(target=Poller(FOLDER, log=log).run, args=(stop,), daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.5)
    except KeyboardInterrupt:
        say("Stopping...")
        stop.set()
        worker.join(5)
        if sender:
            sender.send_waiting()


if __name__ == "__main__":
    main()
