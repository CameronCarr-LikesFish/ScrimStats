"""
Shared bits for the ScrimStats app: where every folder and file lives.

The app is one folder. When running as the .exe, that folder is wherever the
.exe is. When running from source (for development), it's the built app
folder next to this source folder, so both use the same data.
"""

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "ScrimStats"
VERSION = "2.7.0"


def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    override = os.environ.get("LSC_HOME")
    return Path(override) if override else Path(__file__).resolve().parent.parent / APP_NAME


def bundled(name):
    """A file shipped inside the app (templates, default settings)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


class Paths:
    def __init__(self, root=None):
        self.root = Path(root) if root else app_dir()
        # Folders people use
        self.craig = self.root / "Craig downloads"
        self.games = self.root / "Game recordings"
        self.transcripts = self.root / "Transcripts"
        self.settings = self.root / "Settings"
        # Behind-the-scenes storage
        self.data = self.root / "_data"
        self.models = self.data / "models"
        self.work = self.data / "in-progress"
        self.vocab = self.data / "lol_vocabulary.json"
        # Settings files (plain text, edited in the app's Settings and Roster tabs)
        self.roster = self.settings / "Roster.txt"
        self.callouts = self.settings / "Callout types.txt"
        self.league_words = self.settings / "League words.txt"
        self.nicknames = self.settings / "Champion nicknames.txt"
        self.corrections = self.settings / "Corrections.txt"
        # Outputs
        self.dashboard = self.root / "Dashboard.html"
        self.csv = self.root / "Comms stats.csv"

    def ensure(self):
        """Create the folders and put default settings in place. A settings
        file you've edited is never touched. One that still exactly matches
        the default from an older version (so nobody edited it) is upgraded
        to the new default, so improvements like new phrases reach you."""
        for folder in (self.craig, self.games, self.transcripts, self.settings, self.data):
            folder.mkdir(parents=True, exist_ok=True)
        for target in (self.callouts, self.league_words, self.nicknames, self.corrections):
            source = bundled("defaults") / target.name
            if not source.exists():
                continue
            if not target.exists() or (sha256(target) in OLD_DEFAULTS.get(target.name, ())
                                       and sha256(target) != sha256(source)):
                shutil.copyfile(source, target)
        return self


SAME_EVENT_S = 3.0   # a replayed event's time can differ by a few hundredths of a second


def event_identity(event):
    """What an event is, apart from when: its type and who/what was involved."""
    return (event.get("EventName"), event.get("KillerName"), event.get("VictimName"),
            event.get("DragonType"), event.get("TurretKilled"), event.get("InhibKilled"),
            event.get("Acer"), event.get("KillStreak"))   # a double kill, then a triple kill


class SeenEvents:
    """Remembers events, to spot a spectator rewind replaying one. A replayed
    event gets a new ID and its time can differ slightly (29.16 vs 29.18), so
    "the same" means the same type and people within a few seconds."""

    def __init__(self):
        self.times = {}

    def is_repeat(self, event):
        try:
            when = float(event.get("EventTime") or 0)
        except (TypeError, ValueError):
            when = 0.0
        times = self.times.setdefault(event_identity(event), [])
        if any(abs(when - t) <= SAME_EVENT_S for t in times):
            return True
        times.append(when)
        return False


def sha256(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Fingerprints of the settings files as shipped by earlier versions. A file
# matching one of these hasn't been edited, so it's safe to upgrade.
OLD_DEFAULTS = {
    "Callout types.txt": {"c0940b96d254db171983e07dc81c71fe0e6251e3fd55143295562926ef9a9f74",    # 2.0.x
                          "08aab5039cd313701ef87d1b64b2db987f9fefd795cc0bb1c1fe0d87d9d4700d",    # 2.1-2.2
                          "799689ee2d4c45b668d6aac468b4d88d2cac70a54a5195543c58c4edeb743904",    # 2.3
                          "7321dcaa7d730eae4a3abd08f67eb1d59ae7d558719b5b62389ab42cb64f0c18"},   # 2.4
    "League words.txt": {"a28537c694a2c5549e8a3ade89842fa7122f54740502a581adf68b378235d5e3",     # 2.0.x
                         "f994f3d59f51856fa8429da286cd9837b02470fed2b2c91cc96dc2f5f6055823"},    # 2.1-2.2
    "Champion nicknames.txt": {"e1da9b999b327571a0005319f16cdc353f3f1c920b45668c9b39d55fa9742f94"},
    "Corrections.txt": {"af3ca11fb1e1757fe49784ef73ba0344746f574252914b54826f4a01e590bcf7",      # 2.0.x
                        "c771240ccfabb456a50cb3e0f6fe8ea9fab72ce52da65803f733be383bd2e73e"},     # 2.1-2.2
}
