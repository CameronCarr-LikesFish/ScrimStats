"""
LoL Scrim Comms: the app window.

One window with three steps:
  1. Record games      runs the game recorder while you play
  2. Transcribe comms  turns Craig downloads into transcripts
  3. Review            builds and opens the dashboard; edit the roster

The heavy work runs in background threads; they send their messages to the
window through a queue, which the window checks ten times a second.
"""

import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from common import APP_NAME, VERSION, Paths, bundled

messages = queue.Queue()     # (kind, text) from any thread -> the window


def log(text):
    messages.put(("log", str(text)))


class QueueWriter:
    """Sends print() output (and library progress bars) to the activity log.
    In the .exe there's no console, so without this, printing would crash."""

    def __init__(self):
        self.buffer = ""

    def write(self, text):
        self.buffer += text.replace("\r", "\n")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                log(line)

    def flush(self):
        pass


def single_instance():
    """Only one copy of the app may run, or two recorders would record the
    same game twice. Returns False if another copy is already open."""
    if os.name != "nt":
        return True
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "LoLScrimComms_single_instance")
    return ctypes.windll.kernel32.GetLastError() != 183   # 183 = already exists


class App:
    def __init__(self, root):
        self.root = root
        self.paths = Paths().ensure()
        self.recorder_thread = None
        self.recorder_stop = threading.Event()
        self.transcribe_thread = None
        self.transcribe_stop = threading.Event()
        self.busy_dashboard = False
        self.closing = False

        root.title(APP_NAME)
        root.geometry("760x680")
        root.minsize(620, 560)
        icon = bundled("icon.ico")
        if icon.exists():
            try:
                root.iconbitmap(str(icon))
            except tk.TclError:
                pass
        self.build_ui()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.pump_messages)
        root.after(500, self.refresh_waiting)
        log(f"{APP_NAME} v{VERSION} ready. App folder: {self.paths.root}")

    # ------------------------------------------------------------------ UI

    def build_ui(self):
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        base = ("Segoe UI", 10)
        style.configure(".", font=base)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
        style.configure("Sub.TLabel", foreground="#52514e")
        style.configure("Step.TLabelframe.Label", font=("Segoe UI Semibold", 12))
        style.configure("Big.TButton", font=("Segoe UI Semibold", 11), padding=(16, 8))
        style.configure("Status.TLabel", font=("Segoe UI", 10))

        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Record your games, transcribe your comms, see how they change over time.",
                  style="Sub.TLabel").pack(anchor="w", pady=(0, 12))

        # Step 1: record games
        step1 = ttk.LabelFrame(outer, text=" 1   Record games ", style="Step.TLabelframe", padding=12)
        step1.pack(fill="x")
        row = ttk.Frame(step1)
        row.pack(fill="x")
        self.rec_button = ttk.Button(row, text="Start recording", style="Big.TButton",
                                     command=self.toggle_recorder, width=18)
        self.rec_button.pack(side="left")
        status = ttk.Frame(row)
        status.pack(side="left", fill="x", expand=True, padx=(14, 0))
        self.rec_dot = tk.Label(status, text="●", fg="#898781", font=("Segoe UI", 12))
        self.rec_dot.pack(side="left")
        self.rec_status = ttk.Label(status, text="Not recording", style="Status.TLabel")
        self.rec_status.pack(side="left", padx=(6, 0))
        ttk.Label(step1, text="Start this before your scrim block and leave the app open. "
                              "It records every game on its own.",
                  style="Sub.TLabel", wraplength=680).pack(anchor="w", pady=(8, 0))

        # Step 2: transcribe
        step2 = ttk.LabelFrame(outer, text=" 2   Transcribe comms ", style="Step.TLabelframe", padding=12)
        step2.pack(fill="x", pady=(12, 0))
        row = ttk.Frame(step2)
        row.pack(fill="x")
        self.tr_button = ttk.Button(row, text="Transcribe", style="Big.TButton",
                                    command=self.toggle_transcribe, width=18)
        self.tr_button.pack(side="left")
        ttk.Button(row, text="Add Craig download…", command=self.add_craig).pack(side="left", padx=(10, 0))
        self.tr_status = ttk.Label(row, text="", style="Status.TLabel")
        self.tr_status.pack(side="left", padx=(14, 0))
        ttk.Label(step2, text="After scrims: /stop Craig, download Multi-track → FLAC, then "
                              "\"Add Craig download…\" (or drop the .zip in the Craig downloads folder). "
                              "Takes roughly 30–60 minutes for a 3-hour block (longer with lots of Chinese).",
                  style="Sub.TLabel", wraplength=680).pack(anchor="w", pady=(8, 0))

        # Step 3: review
        step3 = ttk.LabelFrame(outer, text=" 3   Review ", style="Step.TLabelframe", padding=12)
        step3.pack(fill="x", pady=(12, 0))
        row = ttk.Frame(step3)
        row.pack(fill="x")
        self.dash_button = ttk.Button(row, text="Open dashboard", style="Big.TButton",
                                      command=self.open_dashboard, width=18)
        self.dash_button.pack(side="left")
        ttk.Button(row, text="Edit roster", command=self.edit_roster).pack(side="left", padx=(10, 0))
        ttk.Button(row, text="Settings", command=lambda: self.open_path(self.paths.settings)).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Transcripts", command=lambda: self.open_path(self.paths.transcripts)).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="App folder", command=lambda: self.open_path(self.paths.root)).pack(side="left", padx=(6, 0))

        # Activity log
        ttk.Label(outer, text="Activity", font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(14, 4))
        self.log_box = ScrolledText(outer, height=12, wrap="word", font=("Consolas", 9),
                                    relief="solid", borderwidth=1, state="disabled")
        self.log_box.pack(fill="both", expand=True)

    # ------------------------------------------------------- message pump

    def pump_messages(self):
        try:
            while True:
                kind, text = messages.get_nowait()
                if kind == "log":
                    self.append_log(text)
                elif kind == "rec_status":
                    self.rec_status.config(text=text)
                elif kind == "done":
                    getattr(self, text)()
        except queue.Empty:
            pass
        self.root.after(100, self.pump_messages)

    def append_log(self, text):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.config(state="normal")
        self.log_box.insert("end", f"{stamp}  {text}\n")
        lines = int(self.log_box.index("end-1c").split(".")[0])
        if lines > 3000:                                   # keep memory small
            self.log_box.delete("1.0", f"{lines - 3000}.0")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    # ---------------------------------------------------------- recorder

    def toggle_recorder(self):
        if self.recorder_thread and self.recorder_thread.is_alive():
            self.rec_button.config(state="disabled", text="Stopping…")
            self.recorder_stop.set()
            return
        from poller import Poller
        self.recorder_stop.clear()
        poller = Poller(self.paths.games, log=log,
                        status=lambda text: messages.put(("rec_status", text)))

        def work():
            try:
                poller.run(self.recorder_stop)
            finally:
                messages.put(("done", "recorder_finished"))

        self.recorder_thread = threading.Thread(target=work, daemon=True)
        self.recorder_thread.start()
        self.rec_button.config(text="Stop recording")
        self.rec_dot.config(fg="#0ca30c")
        self.rec_status.config(text="Starting…")
        log("Game recorder started.")

    def recorder_finished(self):
        self.rec_button.config(state="normal", text="Start recording")
        self.rec_dot.config(fg="#898781")
        self.rec_status.config(text="Not recording")
        log("Game recorder stopped.")
        self.maybe_finish_close()

    # -------------------------------------------------------- transcribe

    def toggle_transcribe(self):
        if self.transcribe_thread and self.transcribe_thread.is_alive():
            self.tr_button.config(state="disabled", text="Stopping…")
            self.transcribe_stop.set()
            log("Stopping after the current line…")
            return
        if self.recorder_thread and self.recorder_thread.is_alive():
            if not messagebox.askyesno(APP_NAME, "The game recorder is running. Transcribing uses "
                                                 "a lot of processor power and may lower your FPS "
                                                 "if you're in a game.\n\nTranscribe anyway?"):
                return
        self.transcribe_stop.clear()

        def work():
            try:
                import transcriber
                transcriber.transcribe_all(self.paths, log=log, stop_event=self.transcribe_stop)
            except Exception as error:
                log(f"Transcription problem: {type(error).__name__}: {error}")
            finally:
                messages.put(("done", "transcribe_finished"))

        self.transcribe_thread = threading.Thread(target=work, daemon=True)
        self.transcribe_thread.start()
        self.tr_button.config(text="Stop")
        log("Transcribing…")

    def transcribe_finished(self):
        self.tr_button.config(state="normal", text="Transcribe")
        self.refresh_waiting(repeat=False)
        self.maybe_finish_close()

    def add_craig(self):
        files = filedialog.askopenfilenames(
            title="Choose Craig download(s)", filetypes=[("Craig download", "*.zip"), ("All files", "*.*")],
            initialdir=str(Path.home() / "Downloads"))
        import shutil
        for name in files:
            source = Path(name)
            target = self.paths.craig / source.name
            if target.exists():
                log(f"{source.name} is already in Craig downloads.")
                continue
            shutil.copy2(source, target)
            log(f"Added {source.name}. Press Transcribe when you're ready.")
        self.refresh_waiting(repeat=False)

    def refresh_waiting(self, repeat=True):
        """How many Craig downloads are waiting to be transcribed. (Kept
        light: it runs every few seconds.)"""
        def transcribed(folder):
            try:
                text = (folder / "info.txt").read_text(encoding="utf-8", errors="replace")
            except OSError:
                return False
            match = re.search(r"^Recording\s+(\S+)", text, re.M)
            name = match.group(1) if match else folder.name
            return any(self.paths.transcripts.glob(f"comms_*_{name}.jsonl"))

        try:
            waiting = 0
            for item in self.paths.craig.iterdir():
                if item.suffix.lower() == ".zip":
                    if not (self.paths.craig / item.stem).exists():
                        waiting += 1
                elif item.is_dir():
                    folders = [item] if (item / "info.txt").exists() else \
                        [s for s in item.iterdir() if s.is_dir() and (s / "info.txt").exists()]
                    waiting += sum(1 for f in folders if not transcribed(f))
            busy = self.transcribe_thread and self.transcribe_thread.is_alive()
            if not busy:
                self.tr_status.config(text=f"{waiting} new recording{'s' if waiting != 1 else ''} waiting"
                                      if waiting else "Nothing new to transcribe")
        except OSError:
            pass
        if repeat:
            self.root.after(5000, self.refresh_waiting)

    # --------------------------------------------------------- dashboard

    def open_dashboard(self):
        if self.busy_dashboard:
            return
        self.busy_dashboard = True
        self.dash_button.config(state="disabled", text="Building…")

        def work():
            try:
                import analytics
                analytics.build(self.paths, log=log, open_browser=True)
            except Exception as error:
                log(f"Dashboard problem: {type(error).__name__}: {error}")
            finally:
                messages.put(("done", "dashboard_finished"))

        threading.Thread(target=work, daemon=True).start()

    def dashboard_finished(self):
        self.busy_dashboard = False
        self.dash_button.config(state="normal", text="Open dashboard")

    def edit_roster(self):
        if not self.paths.roster.exists():
            import analytics
            analytics.build(self.paths, log=log, open_browser=False, open_roster=True)
        else:
            self.open_path(self.paths.roster)

    def open_path(self, path):
        if not path.exists() and not path.suffix:
            path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    # ------------------------------------------------------------- close

    def on_close(self):
        recording = self.recorder_thread and self.recorder_thread.is_alive()
        transcribing = self.transcribe_thread and self.transcribe_thread.is_alive()
        if recording or transcribing:
            doing = " and ".join(x for x, on in (("recording games", recording),
                                                  ("transcribing", transcribing)) if on)
            if not messagebox.askyesno(APP_NAME, f"The app is {doing}. Stop and close?\n\n"
                                                 "Everything recorded so far is saved."):
                return
            self.closing = True
            self.recorder_stop.set()
            self.transcribe_stop.set()
            log("Closing: finishing up…")
            self.root.after(8000, self.root.destroy)      # never hang forever
            return
        self.root.destroy()

    def maybe_finish_close(self):
        if not self.closing:
            return
        still = any(t and t.is_alive() for t in (self.recorder_thread, self.transcribe_thread))
        if not still:
            self.root.destroy()


def self_test():
    """'LoL Scrim Comms.exe --self-test' checks the packaged app's parts
    without the window: the game recorder, transcription of anything in
    Craig downloads, and the dashboard. Results go to _data\\self-test.log."""
    paths = Paths().ensure()
    report = open(paths.data / "self-test.log", "w", encoding="utf-8")
    import faulthandler
    faulthandler.enable(report)          # if a library crashes hard, say where

    def write(text):
        report.write(f"{datetime.now():%H:%M:%S}  {text}\n")
        report.flush()

    sys.stdout = sys.stderr = QueueWriter()
    global log
    log = write
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
        write("Dashboard: OK")
        write("SELF-TEST PASSED")
    except Exception as error:
        import traceback
        write("SELF-TEST FAILED: " + "".join(traceback.format_exception(error)))
    finally:
        while not messages.empty():
            write(messages.get()[1])
        report.close()


def main():
    if "--self-test" in sys.argv:
        self_test()
        return
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)     # crisp text on high-DPI screens
        except Exception:
            pass
    if not single_instance():
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_NAME, f"{APP_NAME} is already open. Check your taskbar.")
        return
    sys.stdout = QueueWriter()
    sys.stderr = QueueWriter()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
