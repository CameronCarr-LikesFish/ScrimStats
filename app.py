"""
ScrimStats: the app.

One window (ui/index.html, shown with pywebview using the browser engine
built into Windows) with everything in it:
  Home         record games, transcribe comms, activity log
  Dashboard    the stats, inside the app
  Transcripts  read and search who said what
  Rosters      who's who per roster (Varsity, JV...), picked from the names
               found in your recordings
  Games        recorded games; set the spectator delay where needed, add a
               player's recordings of spectated games
  Settings     the word lists, edited in the app

The page talks to the Api class below. Heavy work runs in background
threads; their messages go into a log that the page reads every second.

"ScrimStats.exe --self-test" runs a check without the window.
"""

import json
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from common import APP_NAME, VERSION, Paths, bundled


class Log:
    """Messages for the Activity panel, from any thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.items = []          # (number, "HH:MM:SS", text)

    def __call__(self, text):
        with self.lock:
            for line in str(text).splitlines() or [""]:
                if line.strip():
                    self.items.append((len(self.items), datetime.now().strftime("%H:%M:%S"), line))

    def since(self, cursor):
        with self.lock:
            return [(t, text) for n, t, text in self.items[cursor:]], len(self.items)


class LogWriter:
    """print() output (and library progress bars) into the log. In the .exe
    there's no console, so without this, printing would crash."""

    def __init__(self, log):
        self.log, self.buffer = log, ""

    def write(self, text):
        self.buffer += str(text).replace("\r", "\n")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.log(line)

    def flush(self):
        pass


def single_instance():
    """Only one copy may run, or two recorders would record the same game."""
    if os.name != "nt":
        return True
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "LoLScrimComms_single_instance")
    return ctypes.windll.kernel32.GetLastError() != 183   # 183 = already exists


def graphics_card_ready():
    try:
        import _pywhispercpp  # noqa: F401
        return True
    except Exception:
        return False


SETTINGS_FILES = {
    "callouts": ("Callout types", "Which phrases count as shotcalling, enemy info, my status, item timers, "
                 "timers, resources, vision, positive, flame and accountability. "
                 "One type per line: Type: phrase, phrase."),
    "league_words": ("League words", "Words the speech model listens for, most important first. "
                     "One per line. Chinese words have their own space, separate from English."),
    "nicknames": ("Champion nicknames", "What people call champions. One per line: Official Name: nickname, nickname."),
    "corrections": ("Corrections", "Fixes for words it keeps mishearing or mistranslating. "
                    "One per line: what it wrote => what it should be."),
}


class Api:
    """Everything the window can ask for. pywebview calls these from the page.
    Everything else is kept "private" (names starting with _): pywebview looks
    through every public attribute to build the page's bridge, and handing it
    the window object made the app take ~20 seconds to start."""

    def __init__(self, paths, log):
        self._paths, self._log = paths, log
        self._window = None
        self._recorder_thread = self._transcribe_thread = None
        self._recorder_stop_flag = threading.Event()
        self._transcribe_stop_flag = threading.Event()
        self._rec_status = "Not recording"
        self._engine = ("Speech engine: graphics card" if graphics_card_ready()
                       else "Speech engine: processor")

    # ----- status -----

    def status(self, cursor=0):
        lines, cursor = self._log.since(int(cursor or 0))
        recording = bool(self._recorder_thread and self._recorder_thread.is_alive())
        transcribing = bool(self._transcribe_thread and self._transcribe_thread.is_alive())
        return {"version": VERSION, "folder": str(self._paths.root), "engine": self._engine,
                "recording": recording, "recorder_stopping": recording and self._recorder_stop_flag.is_set(),
                "rec_status": self._rec_status if recording else "Not recording",
                "transcribing": transcribing,
                "transcribe_stopping": transcribing and self._transcribe_stop_flag.is_set(),
                "waiting": 0 if transcribing else self._waiting(), "log": lines, "cursor": cursor}

    def _waiting(self):
        """How many Craig downloads haven't been transcribed yet (kept light)."""
        def done(folder):
            try:
                text = (folder / "info.txt").read_text(encoding="utf-8", errors="replace")
            except OSError:
                return False
            m = re.search(r"^Recording\s+(\S+)", text, re.M)
            return any(self._paths.transcripts.glob(f"comms_*_{m.group(1) if m else folder.name}.jsonl"))
        count = 0
        try:
            for item in self._paths.craig.iterdir():
                if item.suffix.lower() == ".zip":
                    count += not (self._paths.craig / item.stem).exists()
                elif item.is_dir():
                    folders = [item] if (item / "info.txt").exists() else \
                        [s for s in item.iterdir() if s.is_dir() and (s / "info.txt").exists()]
                    count += sum(1 for f in folders if not done(f))
        except OSError:
            pass
        return count

    # ----- recorder -----

    def recorder_start(self):
        if self._recorder_thread and self._recorder_thread.is_alive():
            return
        from poller import Poller
        self._recorder_stop_flag.clear()
        poller = Poller(self._paths.games, log=self._log,
                        status=lambda text: setattr(self, "_rec_status", text))

        def work():
            try:
                poller.run(self._recorder_stop_flag)
            finally:
                self._log("Game recorder stopped.")
        self._recorder_thread = threading.Thread(target=work, daemon=True)
        self._recorder_thread.start()
        self._rec_status = "Starting…"
        self._log("Game recorder started.")

    def recorder_stop(self):
        self._recorder_stop_flag.set()

    # ----- transcriber -----

    def transcribe_start(self):
        if self._transcribe_thread and self._transcribe_thread.is_alive():
            return
        self._transcribe_stop_flag.clear()

        def work():
            try:
                import transcriber
                transcriber.transcribe_all(self._paths, log=self._log, stop_event=self._transcribe_stop_flag)
                engine = getattr(next(iter(transcriber._engine_cache.values()), None), "name", None)
                if engine:
                    self._engine = "Speech engine: " + engine.split(" (")[0]
            except Exception as error:
                self._log(f"Transcription problem: {type(error).__name__}: {error}")
        self._transcribe_thread = threading.Thread(target=work, daemon=True)
        self._transcribe_thread.start()
        self._log("Transcribing…")

    def transcribe_stop(self):
        self._transcribe_stop_flag.set()
        self._log("Stopping after the current line…")

    def add_craig(self):
        import webview
        files = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True,
            directory=str(Path.home() / "Downloads"), file_types=("Craig download (*.zip)", "All files (*.*)"))
        for name in files or []:
            source = Path(name)
            target = self._paths.craig / source.name
            if target.exists():
                self._log(f"{source.name} is already in Craig downloads.")
            else:
                shutil.copy2(source, target)
                self._log(f"Added {source.name}. Press Transcribe when you're ready.")
        return len(files or [])

    # ----- dashboard -----

    def dashboard(self):
        import analytics
        lines = []
        analytics.build(self._paths, log=lines.append, open_browser=False, open_roster=False)
        html = self._paths.dashboard.read_text(encoding="utf-8")
        summary = next((l for l in lines if l.startswith("Dashboard updated")), "")
        return {"html": html, "summary": summary.replace("Dashboard updated: ", "")}

    # ----- transcripts -----

    def transcripts(self):
        out = []
        for path in sorted(self._paths.transcripts.glob("comms_*.jsonl"), reverse=True):
            try:
                with open(path, encoding="utf-8") as f:
                    meta = json.loads(f.readline())
            except (OSError, ValueError):
                continue
            out.append({"name": path.name, "start": meta.get("audio_start_t", 0),
                        "lines": sum(t.get("lines", 0) for t in meta.get("tracks", [])),
                        "speakers": [t["speaker"] for t in meta.get("tracks", []) if t.get("lines")]})
        return out

    def transcript(self, name):
        path = self._paths.transcripts / Path(name).name
        lines, speakers = [], []
        with open(path, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                try:
                    u = json.loads(line)
                except ValueError:
                    continue
                if u.get("type") != "utterance":
                    continue
                if u["speaker"] not in speakers:
                    speakers.append(u["speaker"])
                lines.append({"when": datetime.fromtimestamp(u["t"]).strftime("%H:%M:%S"),
                              "speaker": u["speaker"], "text": u["text"],
                              "language": u.get("language", "en"), "text_en": u.get("text_en", "")})
        return {"lines": lines, "speakers": speakers}

    # ----- roster -----

    def roster(self):
        import analytics
        data = (analytics.load_rosters(self._paths.roster) if self._paths.roster.exists()
                else {"rosters": [], "players": []})
        return {**data, "candidates": analytics.roster_candidates(self._paths)}

    def save_roster(self, rosters, players):
        import analytics
        analytics.save_roster(self._paths, rosters, players)
        self._log(f"Rosters saved ({', '.join(rosters)}).")
        return True

    # ----- games -----

    def games(self):
        import analytics
        return analytics.game_list(self._paths)

    def add_games(self):
        """A teammate's game recordings (they played; you spectated), copied
        into Game recordings. Same-named files get a new name, never replaced."""
        import webview
        files = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True, directory=str(Path.home() / "Downloads"),
            file_types=("Game recordings (*.jsonl)", "All files (*.*)"))
        added = 0
        for name in files or []:
            source = Path(name)
            if source.suffix.lower() != ".jsonl" or not source.name.startswith("game_"):
                self._log(f"Skipped {source.name}: not a ScrimStats game recording.")
                continue
            target = self._paths.games / source.name
            if target.exists() and target.read_bytes() == source.read_bytes():
                self._log(f"{source.name} is already in Game recordings.")
                continue
            n = 2
            while target.exists():
                target = self._paths.games / f"{source.stem}_from_player_{n}.jsonl"
                n += 1
            shutil.copy2(source, target)
            added += 1
        if added:
            self._log(f"Added {added} game recording(s). They're joined with the matching spectated games.")
        return added

    def set_delay(self, game_id, seconds):
        import analytics
        analytics.save_game_delay(self._paths, Path(game_id).name, float(seconds or 0))
        return True

    # ----- settings -----

    def settings_files(self):
        out = {}
        for key, (title, help_text) in SETTINGS_FILES.items():
            path = getattr(self._paths, key)
            out[key] = {"title": title, "help": help_text,
                        "text": path.read_text(encoding="utf-8") if path.exists() else ""}
        return out

    def save_setting(self, key, text):
        if key not in SETTINGS_FILES:
            return False
        getattr(self._paths, key).write_text(text.replace("\r\n", "\n"), encoding="utf-8")
        self._log(f"Saved {SETTINGS_FILES[key][0]}.")
        return True

    def open_folder(self, which):
        folder = {"root": self._paths.root, "craig": self._paths.craig, "games": self._paths.games,
                  "transcripts": self._paths.transcripts}.get(which, self._paths.root)
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    # ----- closing -----

    def _busy(self):
        return [what for what, t in (("recording games", self._recorder_thread),
                                     ("transcribing", self._transcribe_thread)) if t and t.is_alive()]

    def _shutdown(self):
        self._recorder_stop_flag.set()
        self._transcribe_stop_flag.set()
        for t in (self._recorder_thread, self._transcribe_thread):
            if t:
                t.join(timeout=8)


def self_test():
    """Checks the packaged app's parts without the window. Results go to
    _data\\self-test.log."""
    paths = Paths().ensure()
    report = open(paths.data / "self-test.log", "w", encoding="utf-8")
    import faulthandler
    faulthandler.enable(report)

    def write(text):
        report.write(f"{datetime.now():%H:%M:%S}  {text}\n")
        report.flush()

    sys.stdout = sys.stderr = LogWriter(write)
    try:
        write(f"{APP_NAME} v{VERSION} self-test in {paths.root}")
        from poller import Poller
        stop = threading.Event()
        worker = threading.Thread(target=Poller(paths.games, log=write).run, args=(stop,))
        worker.start()
        time.sleep(3)
        stop.set()
        worker.join()
        write("Recorder: OK")
        import transcriber
        done = transcriber.transcribe_all(paths, log=write)
        write(f"Transcriber: OK ({len(done)} new transcript(s))")
        import analytics
        analytics.build(paths, log=write, open_browser=False, open_roster=False)
        analytics.roster_candidates(paths)
        analytics.game_list(paths)
        write("Dashboard: OK")
        write("Window page: " + ("OK" if bundled("ui/index.html").exists() else "MISSING"))
        write("SELF-TEST PASSED")
    except Exception as error:
        import traceback
        write("SELF-TEST FAILED: " + "".join(traceback.format_exception(error)))
    finally:
        report.close()


def ui_test():
    """'ScrimStats.exe --ui-test': opens the real window HIDDEN (nothing
    appears on screen), checks the page loaded and can talk to the app,
    visits each tab, then closes. Results go to _data\\ui-test.log."""
    import webview
    paths = Paths().ensure()
    log = Log()
    sys.stdout = sys.stderr = LogWriter(log)
    api = Api(paths, log)
    window = webview.create_window(APP_NAME, url=str(bundled("ui") / "index.html"), js_api=api,
                                   width=1180, height=820, hidden=True)
    api._window = window
    results = []

    def check():
        try:
            time.sleep(6)
            results.append("version shown: " + str(window.evaluate_js('document.getElementById("version").textContent')))
            for page, probe in [("roster", '#voices tr'), ("games", '#games tr'),
                                ("transcripts", '#tr-list button'), ("settings", '#set-tabs button')]:
                window.evaluate_js(f'show("{page}")')
                time.sleep(2)
                count = window.evaluate_js(f'document.querySelectorAll("{probe}").length')
                results.append(f"{page}: {count} item(s)")
            window.evaluate_js('show("dashboard")')
            time.sleep(4)
            results.append("dashboard: " + str(window.evaluate_js('document.getElementById("dash-status").textContent')))
            results.append("UI TEST PASSED" if results[0] != "version shown: " else "UI TEST FAILED")
        except Exception as error:
            results.append(f"UI TEST FAILED: {type(error).__name__}: {error}")
        finally:
            (paths.data / "ui-test.log").write_text("\n".join(results) + "\n", encoding="utf-8")
            window.destroy()
    threading.Thread(target=check, daemon=True).start()
    webview.start()


def main():
    if "--self-test" in sys.argv:
        self_test()
        return
    if "--ui-test" in sys.argv:
        ui_test()
        return
    import webview
    if not single_instance():
        webview.create_window(APP_NAME, html=f"<p style='font:15px system-ui;padding:20px'>"
                              f"{APP_NAME} is already open. Check your taskbar.</p>", width=420, height=160)
        webview.start()
        return
    paths = Paths().ensure()
    log = Log()
    sys.stdout = sys.stderr = LogWriter(log)
    api = Api(paths, log)
    log(f"{APP_NAME} v{VERSION} ready.")
    window = webview.create_window(APP_NAME, url=str(bundled("ui") / "index.html"), js_api=api,
                                   width=1180, height=820, min_size=(860, 600))
    api._window = window

    def on_closing():
        doing = api._busy()
        if doing and not window.create_confirmation_dialog(
                APP_NAME, f"The app is {' and '.join(doing)}. Stop and close?\n\n"
                          "Everything recorded so far is saved."):
            return False                     # keep the window open
        api._shutdown()
        return True
    window.events.closing += on_closing
    webview.start(icon=str(bundled("icon.ico")) if bundled("icon.ico").exists() else None)


if __name__ == "__main__":
    main()
