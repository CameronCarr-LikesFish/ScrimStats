"""
Comms transcriber.

Turns Craig recordings (one audio file per person) into a timeline of who
said what, with a real-world timestamp on every line, using the same clock
as the game recorder. Speech-to-text is Whisper, running entirely on this
PC; nothing is uploaded.

Output, in Transcripts\\ (per Craig recording):
  comms_<date>_<time>_<id>.txt     easy to read
  comms_<date>_<time>_<id>.jsonl   meta line + one "utterance" per line of
                                   speech: speaker, wall_clock, t (Unix
                                   seconds), text (League spellings fixed),
                                   text_raw (as heard), per-word timings
"""

import json
import mmap
import os
import re
import struct
import time
import zipfile
from datetime import datetime, timezone

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import av
import numpy as np
import requests

from common import VERSION

MODEL_NAME = "small.en"     # "medium.en" = more accurate, about 3x slower
CPU_THREADS = 6             # fastest setting measured on this PC
HINT_TOKEN_BUDGET = 200     # Whisper's hard limit for hints is 223 tokens
AUDIO_EXTENSIONS = {".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".mp3"}
DDRAGON = "https://ddragon.leagueoflegends.com"
OPUS_SAMPLE_RATE = 48000


class Stopped(Exception):
    """Raised when the person presses Stop."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_iso(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def iso_local(unix_seconds):
    return (datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
            .astimezone().isoformat(timespec="milliseconds"))


def clock_text(seconds):
    seconds = int(max(0, seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def spelling_key(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def read_list_file(path):
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")]


# ---------------------------------------------------------------------------
# League vocabulary
# ---------------------------------------------------------------------------

EMPTY_VOCAB = {"patch": None, "champions": [], "abilities": [], "items": [],
               "summoner_spells": [], "runes": []}


def load_vocabulary(paths, log=print):
    """Official names from Riot's public game data, saved in _data and
    refreshed when a new patch comes out. Works offline from the saved copy."""
    saved = None
    if paths.vocab.exists():
        try:
            saved = json.loads(paths.vocab.read_text(encoding="utf-8"))
        except ValueError:
            saved = None
    try:
        latest = requests.get(f"{DDRAGON}/api/versions.json", timeout=10).json()[0]
    except Exception:
        latest = None
    if saved and (latest is None or saved.get("patch") == latest):
        return saved
    if latest is None:
        log("Couldn't reach Riot's servers for League names; continuing without them.")
        return saved or dict(EMPTY_VOCAB)
    log(f"Downloading League names for patch {latest}…")
    try:
        vocab = download_vocabulary(latest)
    except Exception as error:
        log(f"  Download failed ({error}); using the saved list instead.")
        return saved or dict(EMPTY_VOCAB)
    paths.vocab.parent.mkdir(parents=True, exist_ok=True)
    paths.vocab.write_text(json.dumps(vocab, indent=1, ensure_ascii=False), encoding="utf-8")
    return vocab


def download_vocabulary(patch):
    base = f"{DDRAGON}/cdn/{patch}/data/en_US/"

    def get(name):
        response = requests.get(base + name, timeout=60)
        response.raise_for_status()
        return response.json()

    champions = list(get("championFull.json")["data"].values())
    items = set()
    for item in get("item.json")["data"].values():
        name = item.get("name", "").strip()
        if name and "<" not in name and item.get("maps", {}).get("11"):
            items.add(name)
    summoner_spells = {s["name"] for s in get("summoner.json")["data"].values()
                       if "CLASSIC" in s.get("modes", [])}
    runes = set()
    for tree in get("runesReforged.json"):
        runes.add(tree["name"])
        for slot in tree["slots"]:
            for rune in slot["runes"]:
                runes.add(rune["name"])
    return {
        "patch": patch,
        "downloaded_at": iso_local(time.time()),
        "champions": sorted(c["name"] for c in champions),
        "abilities": sorted({s["name"] for c in champions for s in [c["passive"], *c["spells"]]}),
        "items": sorted(items),
        "summoner_spells": sorted(summoner_spells),
        "runes": sorted(runes),
    }


def read_nicknames(paths):
    nicknames = {}
    for line in read_list_file(paths.nicknames):
        if ":" in line:
            official, rest = line.split(":", 1)
            nicknames[official.strip()] = [n.strip() for n in rest.split(",") if n.strip()]
    return nicknames


def read_corrections(paths):
    corrections = []
    for line in read_list_file(paths.corrections):
        if "=>" in line:
            wrong, right = line.split("=>", 1)
            if wrong.strip() and right.strip():
                corrections.append((wrong.strip(), right.strip()))
    return corrections


class TermFixer:
    """Fixes League spellings ('kaisa' -> "Kai'Sa", 'kog maw' -> "Kog'Maw"),
    plus anything in Corrections.txt. Cautious: only changes words whose
    letters already match an official name, and never changes capitals alone."""

    def __init__(self, vocab, slang, nicknames, corrections):
        self.official = {}
        groups = [vocab.get("champions", []), vocab.get("items", []),
                  vocab.get("summoner_spells", []), vocab.get("runes", []),
                  vocab.get("abilities", []), slang,
                  [n for names in nicknames.values() for n in names]]
        for group in groups:
            for name in group:
                key = spelling_key(name)
                if len(key) >= 3 and re.search("[a-z]", key):
                    self.official.setdefault(key, name)
        self.corrections = {spelling_key(w): r for w, r in corrections if spelling_key(w)}
        longest = [len(n.split()) for n in list(self.official.values())
                   + [w for w, _ in corrections]]
        self.max_words = min(4, max(longest, default=1))

    @staticmethod
    def worth_fixing(spoken, official):
        if spoken.lower() == official.lower().rstrip("!.?"):
            return False
        if "'" in spoken and "'" not in official:
            return False
        return True

    def fix(self, text):
        words = text.split()
        out, i = [], 0
        while i < len(words):
            for n in range(min(self.max_words, len(words) - i), 0, -1):
                phrase = " ".join(words[i:i + n])
                lead, core, trail = re.match(r"^([\"'(\[]*)(.*?)([.,!?;:\"')\]]*)$", phrase).groups()
                key = spelling_key(core)
                replacement = None
                if key in self.corrections:
                    replacement = self.corrections[key]
                elif key in self.official and self.worth_fixing(core, self.official[key]):
                    replacement = self.official[key]
                if replacement:
                    out.append(lead + replacement + trail)
                    i += n
                    break
            else:
                out.append(words[i])
                i += 1
        return " ".join(out)


def build_hints(encode, champions, slang, nicknames):
    """Words the model listens for: this block's champions (+ nicknames)
    first, then League words.txt top-down, until the ~200-token limit."""
    wanted = []
    for champion in champions:
        wanted.append(champion)
        wanted.extend(nicknames.get(champion, []))
    wanted.extend(slang)
    chosen, seen, used = [], set(), 0
    for term in wanted:
        if term.lower() in seen:
            continue
        seen.add(term.lower())
        cost = len(encode(" " + term + ","))
        if used + cost > HINT_TOKEN_BUDGET:
            continue
        chosen.append(term)
        used += cost
    return ", ".join(chosen), len(chosen), len(seen)


# ---------------------------------------------------------------------------
# Craig recordings
# ---------------------------------------------------------------------------

def parse_craig_info(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    recording_id = re.search(r"^Recording\s+(\S+)", text, re.M)
    start = re.search(r"^Start time:\s*(\S+)", text, re.M)
    if not start:
        raise ValueError(f"{path} has no 'Start time:' line")
    return {"id": recording_id.group(1) if recording_id else path.parent.name,
            "start_time_text": start.group(1), "start_unix": parse_iso(start.group(1)),
            "raw_text": text}


def first_audio_offset(raw_path):
    """Seconds between Craig's 'Start time' and the start of its audio files.
    Craig's audio starts when someone first spoke (4 s later in our sync
    test). raw.dat stamps each audio page with its position since the start
    (in 1/48000 s); the earliest audio page is the audio files' 0:00."""
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        return None
    earliest, opus_streams = None, set()
    with open(raw_path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        pos = 0
        while True:
            pos = data.find(b"OggS", pos)
            if pos < 0 or pos + 27 > len(data):
                break
            granule, serial = struct.unpack_from("<qI", data, pos + 6)
            body_start = pos + 27 + data[pos + 26]
            body_length = sum(data[pos + 27:body_start])
            head = data[body_start:body_start + 8]
            if head.startswith(b"OpusHead"):
                opus_streams.add(serial)
            elif (body_length > 0 and serial in opus_streams and not head.startswith(b"OpusTags")
                  and 0 <= granule < OPUS_SAMPLE_RATE * 86400):
                earliest = granule if earliest is None else min(earliest, granule)
            pos = max(body_start + body_length, pos + 4)
    return None if earliest is None else earliest / OPUS_SAMPLE_RATE


def audio_length(audio_path):
    try:
        with av.open(str(audio_path)) as container:
            if container.duration:
                return container.duration / 1_000_000
    except Exception:
        pass
    return None


def speaker_name(audio_path):
    return re.sub(r"^\d+-", "", audio_path.stem)


def find_poller_games(paths, start_unix, end_unix):
    games = []
    if not paths.games.is_dir():
        return games
    for path in sorted(paths.games.glob("game_*.jsonl")):
        first = last = None
        champions = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    stamp = record.get("wall_clock") or record.get("started_at")
                    if stamp:
                        t = parse_iso(stamp)
                        first = t if first is None else min(first, t)
                        last = t if last is None else max(last, t)
                    if record.get("type") == "players":
                        champions = [p.get("championName") for p in record.get("players", [])
                                     if p.get("championName")]
        except OSError:
            continue
        if first is not None and first <= end_unix and last >= start_unix:
            games.append({"file": path.name, "champions": champions})
    return games


# ---------------------------------------------------------------------------
# Speech to text
# ---------------------------------------------------------------------------

def load_audio_16k(audio_path, log=print):
    """One channel, 16,000 samples/second, values -1..1. (faster-whisper's
    own reader breaks with the newest audio library, so we do it here.)"""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks = []
    with av.open(str(audio_path)) as container:
        try:
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    chunks.append(converted.to_ndarray().reshape(-1))
        except av.error.FFmpegError as error:
            log(f"    (stopped reading early: {error}; keeping what was read)")
        for converted in resampler.resample(None):
            chunks.append(converted.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def looks_like_hallucination(segment, text):
    """Stock phrases Whisper sometimes 'hears' in silence (it learned from
    subtitled videos)."""
    plain = re.sub(r"[^a-z ]", "", text.lower()).strip()
    if "for watching" in plain or "subscribe" in plain or "subtitles" in plain:
        return True
    if plain in {"you", "bye", "thank you", "thanks"} and (
            segment.no_speech_prob > 0.3 or segment.avg_logprob < -0.7):
        return True
    return segment.no_speech_prob > 0.8 and segment.avg_logprob < -1.0


def split_at_pauses(segment, pause_s=1.0):
    """Split a chunk wherever the speaker paused a second or more, so each
    callout gets the time it was actually said."""
    common = {"avg_logprob": round(segment.avg_logprob, 3),
              "no_speech_prob": round(segment.no_speech_prob, 3)}
    words = list(segment.words or [])
    if not words:
        return [{"start": round(segment.start, 3), "end": round(segment.end, 3),
                 "text": segment.text.strip(), "words": [], **common}]
    groups, current = [], [words[0]]
    for previous, word in zip(words, words[1:]):
        if word.start - previous.end >= pause_s:
            groups.append(current)
            current = []
        current.append(word)
    groups.append(current)
    return [{"start": round(g[0].start, 3), "end": round(g[-1].end, 3),
             "text": "".join(w.word for w in g).strip(),
             "words": [[w.word.strip(), round(w.start, 3), round(w.end, 3), round(w.probability, 3)]
                       for w in g], **common} for g in groups]


def transcribe_track(model, audio_path, hints, label, log, stop_event):
    log(f"  Reading {audio_path.name}…")
    audio = load_audio_16k(audio_path, log)
    duration = len(audio) / 16000
    log(f"  Transcribing {label} ({clock_text(duration)} of audio)…")
    segments, _ = model.transcribe(
        audio, language="en", beam_size=5,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
        word_timestamps=True, condition_on_previous_text=False,
        hotwords=hints or None, hallucination_silence_threshold=2.0)
    results, skipped = [], 0
    started = last_report = time.monotonic()
    for segment in segments:
        if stop_event is not None and stop_event.is_set():
            raise Stopped()
        text = segment.text.strip()
        if not text or looks_like_hallucination(segment, text):
            skipped += 1
            continue
        results.extend(split_at_pauses(segment))
        now = time.monotonic()
        if now - last_report >= 30 and duration > 0:
            done = min(1.0, segment.end / duration)
            left = (now - started) / done * (1 - done) if done > 0 else 0
            log(f"    {label}: {clock_text(segment.end)} / {clock_text(duration)} "
                f"({done:.0%}), about {clock_text(left)} left")
            last_report = now
    log(f"    {label}: done, {len(results)} lines in {clock_text(time.monotonic() - started)}")
    return {"duration_s": round(duration, 3), "segments": results, "skipped": skipped}


def transcribe_recording(model, folder, paths, vocab, slang, nicknames, fixer,
                         model_name, log, stop_event):
    info = parse_craig_info(folder / "info.txt")
    tracks = sorted((p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS),
                    key=lambda p: p.name)
    if not tracks:
        log(f"  No audio files in {folder.name}; skipping.")
        return None
    log(f"\nRecording {info['id']}: {len(tracks)} speaker(s): "
        + ", ".join(speaker_name(t) for t in tracks))

    offset = first_audio_offset(folder / "raw.dat")
    if offset is None:
        offset_source = "none: raw.dat missing, so times may be a few seconds early"
        log("  WARNING: raw.dat is missing, so timings may be a few seconds early.")
        offset = 0.0
    else:
        offset_source = "raw.dat first audio page"
    audio_start = info["start_unix"] + offset
    log(f"  Audio starts {offset:.2f} s after Craig's start time.")

    known = [n for n in (audio_length(t) for t in tracks) if n]
    games = find_poller_games(paths, audio_start, audio_start + (max(known) if known else 6 * 3600))
    champions = []
    for game in games:
        for champion in game["champions"]:
            if champion not in champions:
                champions.append(champion)
    if games:
        log(f"  Found {len(games)} recorded game(s); listening for: " + ", ".join(champions))
    else:
        log("  No recorded games for this time; using general League words.")
    hints, hint_count, hint_total = build_hints(
        lambda s: model.hf_tokenizer.encode(s, add_special_tokens=False).ids,
        champions, slang, nicknames)

    work = paths.work / info["id"]
    work.mkdir(parents=True, exist_ok=True)
    settings = {"model": model_name, "hints": hints, "script_version": VERSION}
    track_results = {}
    for number, track in enumerate(tracks, 1):
        label = f"{speaker_name(track)} ({number}/{len(tracks)})"
        saved_path = work / (track.name + ".json")
        if saved_path.exists():
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            if saved.get("settings") == settings:
                log(f"  {label}: already done earlier, reusing.")
                track_results[track] = saved
                continue
        result = transcribe_track(model, track, hints, label, log, stop_event)
        result["settings"] = settings
        temp = saved_path.with_suffix(".tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temp.replace(saved_path)
        track_results[track] = result

    durations = [r["duration_s"] for r in track_results.values()]
    tracks_aligned = max(durations) - min(durations) <= 2.0
    if not tracks_aligned:
        log("  WARNING: the speakers' audio files have different lengths; timings "
            "between speakers may not line up. Please report this.")

    utterances = []
    for track, result in track_results.items():
        speaker = speaker_name(track)
        for seg in result["segments"]:
            t0, t1 = audio_start + seg["start"], audio_start + seg["end"]
            utterances.append({
                "type": "utterance", "speaker": speaker,
                "wall_clock": iso_local(t0), "wall_clock_end": iso_local(t1),
                "t": round(t0, 3), "t_end": round(t1, 3), "audio_time": seg["start"],
                "text": fixer.fix(seg["text"]), "text_raw": seg["text"],
                "words": [[w, round(audio_start + ws, 3), round(audio_start + we, 3), p]
                          for w, ws, we, p in seg["words"]],
                "avg_logprob": seg["avg_logprob"], "no_speech_prob": seg["no_speech_prob"],
            })
    utterances.sort(key=lambda u: u["t"])

    local_start = datetime.fromtimestamp(audio_start).astimezone()
    stem = f"comms_{local_start.strftime('%Y-%m-%d_%H%M%S')}_{info['id']}"
    meta = {
        "type": "meta", "script_version": VERSION, "created_at": iso_local(time.time()),
        "craig_recording_id": info["id"], "craig_start_time": info["start_time_text"],
        "audio_start_offset_s": round(offset, 3), "audio_start_offset_source": offset_source,
        "audio_start_wall_clock": iso_local(audio_start), "audio_start_t": round(audio_start, 3),
        "timezone": local_start.tzname(), "tracks_aligned": tracks_aligned,
        "model": model_name, "vocabulary_patch": vocab.get("patch"), "hints": hints,
        "poller_games": [g["file"] for g in games],
        "tracks": [{"file": t.name, "speaker": speaker_name(t), "duration_s": r["duration_s"],
                    "lines": len(r["segments"])} for t, r in track_results.items()],
        "craig_info": info["raw_text"],
    }
    paths.transcripts.mkdir(parents=True, exist_ok=True)
    jsonl_path = paths.transcripts / f"{stem}.jsonl"
    temp = jsonl_path.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8", newline="\n") as f:
        for record in [meta] + utterances:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    temp.replace(jsonl_path)
    with open(paths.transcripts / f"{stem}.txt", "w", encoding="utf-8") as f:
        f.write(f"Comms transcript: Craig recording {info['id']}\n")
        f.write(f"Recorded {local_start.strftime('%Y-%m-%d %H:%M:%S')} ({local_start.tzname()})\n")
        f.write("Speakers: " + ", ".join(speaker_name(t) for t in tracks) + "\n")
        f.write("Times are real-world clock time. 'rec' is the position in Craig's audio files.\n\n")
        for u in utterances:
            wall = datetime.fromtimestamp(u["t"]).strftime("%H:%M:%S")
            f.write(f"[{wall} | rec {clock_text(u['audio_time'])}] {u['speaker']}: {u['text']}\n")
    log(f"  Saved {len(utterances)} lines → Transcripts\\{stem}.txt")
    return jsonl_path


# ---------------------------------------------------------------------------
# Finding what to transcribe
# ---------------------------------------------------------------------------

def collect_recordings(paths, log=print):
    """Craig folders in 'Craig downloads', unzipping any .zip files first."""
    paths.craig.mkdir(parents=True, exist_ok=True)
    for archive in sorted(paths.craig.glob("*.zip")):
        destination = paths.craig / archive.stem
        if not (destination / "info.txt").exists() and not any(destination.glob("*/info.txt")):
            log(f"Unzipping {archive.name}…")
            with zipfile.ZipFile(archive) as z:
                z.extractall(destination)
    folders = []
    for sub in sorted(p for p in paths.craig.iterdir() if p.is_dir()):
        if (sub / "info.txt").exists():
            folders.append(sub)
        else:
            folders.extend(s for s in sorted(sub.iterdir()) if s.is_dir() and (s / "info.txt").exists())
    return folders


def already_transcribed(paths, folder):
    try:
        recording_id = parse_craig_info(folder / "info.txt")["id"]
    except (OSError, ValueError):
        return False
    return any(paths.transcripts.glob(f"comms_*_{recording_id}.jsonl"))


def pending_recordings(paths, log=print):
    return [f for f in collect_recordings(paths, log) if not already_transcribed(paths, f)]


_model_cache = {}


def transcribe_all(paths, log=print, stop_event=None, model_name=MODEL_NAME):
    """Transcribe every new Craig recording. Returns the transcript paths."""
    to_do = pending_recordings(paths, log)
    if not to_do:
        log("No new Craig recordings to transcribe. Put Craig downloads (.zip) in "
            "the 'Craig downloads' folder.")
        return []
    log(f"{len(to_do)} recording(s) to transcribe.")
    vocab = load_vocabulary(paths, log)
    slang = read_list_file(paths.league_words)
    nicknames = read_nicknames(paths)
    fixer = TermFixer(vocab, slang, nicknames, read_corrections(paths))

    if model_name not in _model_cache:
        log(f"Loading the speech model ({model_name}). The first time, this downloads it "
            "(about 0.5 GB)…")
        from faster_whisper import WhisperModel
        _model_cache[model_name] = WhisperModel(
            model_name, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS,
            download_root=str(paths.models))
    model = _model_cache[model_name]

    done = []
    for folder in to_do:
        try:
            result = transcribe_recording(model, folder, paths, vocab, slang, nicknames, fixer,
                                          model_name, log, stop_event)
            if result:
                done.append(result)
        except Stopped:
            log("\nStopped. Speakers that were already finished are saved; "
                "transcribing again continues where it left off.")
            return done
        except (OSError, ValueError) as error:
            log(f"  Couldn't transcribe {folder.name}: {error}")
    log("\nTranscription finished.")
    return done


if __name__ == "__main__":
    from common import Paths
    transcribe_all(Paths().ensure())
