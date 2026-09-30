"""
Shared bits for the LoL Scrim Comms app: where every folder and file lives.

The app is one folder. When running as the .exe, that folder is wherever the
.exe is. When running from source (for development), it's the built app
folder next to this source folder, so both use the same data.
"""

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "LoL Scrim Comms"
VERSION = "2.0.1"


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
        # Settings files (plain text, edit with Notepad)
        self.roster = self.settings / "Roster.txt"
        self.callouts = self.settings / "Callout types.txt"
        self.league_words = self.settings / "League words.txt"
        self.nicknames = self.settings / "Champion nicknames.txt"
        self.corrections = self.settings / "Corrections.txt"
        # Outputs
        self.dashboard = self.root / "Dashboard.html"
        self.csv = self.root / "Comms stats.csv"

    def ensure(self):
        """Create the folders and put default settings in place (never
        overwriting ones you've edited)."""
        for folder in (self.craig, self.games, self.transcripts, self.settings, self.data):
            folder.mkdir(parents=True, exist_ok=True)
        for target in (self.callouts, self.league_words, self.nicknames, self.corrections):
            if not target.exists():
                source = bundled("defaults") / target.name
                if source.exists():
                    shutil.copyfile(source, target)
        return self
