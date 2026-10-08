"""
Comms transcriber.

Turns Craig recordings (one audio file per person) into a timeline of who
said what, with a real-world timestamp on every line, using the same clock
as the game recorder. Speech-to-text is Whisper, running entirely on this
PC; nothing is uploaded.

English and Mandarin Chinese are both understood. The model decides which
language each stretch of speech is in (choosing only between the languages
in LANGUAGES). Chinese lines are kept in Chinese and also translated to
English by the same model, on this PC.

Output, in Transcripts\\ (per Craig recording):
  comms_<date>_<time>_<id>.txt     easy to read (Chinese lines show the
                                   original and the English translation)
  comms_<date>_<time>_<id>.jsonl   meta line + one "utterance" per line of
                                   speech: speaker, wall_clock, t (Unix
                                   seconds), language ("en"/"zh"), text
                                   (League spellings fixed), text_en (English
                                   translation for Chinese lines), text_raw
                                   (as heard), per-word timings
"""

import json
import mmap
import os
import re
import struct
import time
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import av
import numpy as np
import requests

from common import VERSION

# "small" understands English AND Chinese ("small.en" was English-only).
# "medium" is better at Chinese but about 3x slower.
MODEL_NAME = "small"
LANGUAGES = ("en", "zh")    # the languages the model may choose between
CPU_THREADS = 6             # fastest setting measured on this PC
# Hints: Whisper's hard limit is 223 tokens. Chinese words cost more tokens,
# so English and Chinese hints each get their own share.
HINT_TOKEN_BUDGET = {"en": 135, "zh": 65}
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


CJK = re.compile(r"[㐀-鿿豈-﫿]")   # Chinese characters


FULLWIDTH_TO_ASCII = str.maketrans({"，": ",", "。": ".", "？": "?", "！": "!", "：": ":",
                                    "；": ";", "、": ",", "（": "(", "）": ")"})


def has_chinese(text):
    return bool(CJK.search(text or ""))


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

VOCAB_FORMAT = 2     # bump when the saved name list's layout changes

EMPTY_VOCAB = {"patch": None, "champions": [], "abilities": [], "items": [],
               "summoner_spells": [], "runes": [], "champions_zh": {}, "items_zh": []}


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
    # (A saved list in an older format, e.g. from before Chinese support, is refreshed.)
    if saved and (latest is None or (saved.get("patch") == latest
                                     and saved.get("format") == VOCAB_FORMAT)):
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
    def get(name, locale="en_US"):
        response = requests.get(f"{DDRAGON}/cdn/{patch}/data/{locale}/{name}", timeout=60)
        response.raise_for_status()
        return response.json()

    champions = list(get("championFull.json")["data"].values())
    items = set()
    for item in get("item.json")["data"].values():
        name = item.get("name", "").strip()
        if name and "<" not in name and item.get("maps", {}).get("11"):
            items.add(name)
    # Riot's official Chinese (zh_CN) names, matched to the English ones by ID.
    # In the Chinese data, "title" is the short name players say (卡莎 for
    # Kai'Sa) and "name" is the epithet (虚空之女), which is also used as a
    # nickname for some champions (盲僧 for Lee Sin). Keep both, short first.
    champions_zh = {}
    english_by_id = {c["id"]: c["name"] for c in champions}
    for champ_id, champ in get("champion.json", "zh_CN")["data"].items():
        if champ_id in english_by_id:
            names = [n for n in (champ.get("title"), champ.get("name")) if n]
            if names:
                champions_zh[english_by_id[champ_id]] = names
    items_zh = sorted({i.get("name", "").strip() for i in get("item.json", "zh_CN")["data"].values()
                       if i.get("name") and "<" not in i["name"] and i.get("maps", {}).get("11")})
    summoner_spells = {s["name"] for s in get("summoner.json")["data"].values()
                       if "CLASSIC" in s.get("modes", [])}
    runes = set()
    for tree in get("runesReforged.json"):
        runes.add(tree["name"])
        for slot in tree["slots"]:
            for rune in slot["runes"]:
                runes.add(rune["name"])
    return {
        "format": VOCAB_FORMAT,
        "patch": patch,
        "downloaded_at": iso_local(time.time()),
        "champions": sorted(c["name"] for c in champions),
        "abilities": sorted({s["name"] for c in champions for s in [c["passive"], *c["spells"]]}),
        "items": sorted(items),
        "summoner_spells": sorted(summoner_spells),
        "runes": sorted(runes),
        "champions_zh": champions_zh,
        "items_zh": items_zh,
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
        self.corrections = {spelling_key(w): r for w, r in corrections
                            if spelling_key(w) and not has_chinese(w)}
        # Chinese corrections ("打也 => 打野") are plain find-and-replace:
        # Chinese has no spaces between words, so whole-word matching doesn't apply.
        self.chinese_corrections = sorted(((w, r) for w, r in corrections if has_chinese(w)),
                                          key=lambda pair: len(pair[0]), reverse=True)
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
        for wrong, right in self.chinese_corrections:
            text = text.replace(wrong, right)
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


def build_hints(encode, champions, slang, nicknames, champions_zh=None):
    """Words the model listens for: this block's champions (+ nicknames, +
    their official Chinese names) first, then League words.txt top-down.
    English and Chinese terms fill separate budgets, so a long English list
    can't crowd out the Chinese words (or the other way round). Chinese
    hints also nudge the model to write Simplified rather than Traditional
    characters."""
    champions_zh = champions_zh or {}
    wanted = []
    for champion in champions:
        wanted.append(champion)
        wanted.extend(nicknames.get(champion, []))
        if champions_zh.get(champion):
            wanted.append(champions_zh[champion][0])     # the short name, e.g. 卡莎
    wanted.extend(slang)
    chosen = {"en": [], "zh": []}
    used = {"en": 0, "zh": 0}
    seen = set()
    for term in wanted:
        if term.lower() in seen:
            continue
        seen.add(term.lower())
        language = "zh" if has_chinese(term) else "en"
        cost = len(encode(" " + term + ","))
        if used[language] + cost > HINT_TOKEN_BUDGET[language]:
            continue
        chosen[language].append(term)
        used[language] += cost
    hints = ", ".join(chosen["en"])
    if chosen["zh"]:
        hints += "。" + "，".join(chosen["zh"])
    return hints, len(chosen["en"]) + len(chosen["zh"]), len(seen)


# A short English glossary for translating Chinese. Kept short on purpose: a
# long hint list makes the model sometimes "translate" by repeating the list.
TRANSLATE_GLOSSARY = ("League of Legends voice comms: drake, baron, herald, grubs, jungler, "
                      "top, mid, bot lane, support, flash, ult, engage, group, back, "
                      "my bad, item, gold")


def translation_hints(champions):
    """The glossary plus (up to 10 of) the champions played tonight."""
    return ", ".join([TRANSLATE_GLOSSARY] + list(champions)[:10])


def looks_like_echo(text, prompt):
    """True when a 'translation' is really the hint list repeated back."""
    pieces = [p.strip().lower() for p in re.split(r"[,:]", text) if p.strip()]
    terms = {t.strip().lower() for t in re.split(r"[,:]", prompt) if t.strip()}
    return len(pieces) >= 3 and sum(p in terms for p in pieces) >= 0.6 * len(pieces)


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


CHINESE_STOCK_PHRASES = ("字幕", "订阅", "訂閱", "点赞", "點贊", "谢谢观看", "謝謝觀看",
                         "明镜", "明鏡", "Amara", "独播剧场", "獨播劇場")


def looks_like_hallucination(segment, text):
    """Stock phrases Whisper sometimes 'hears' in silence (it learned from
    subtitled videos). The Chinese ones are subtitle credits and "like and
    subscribe" lines from Chinese video sites."""
    if any(phrase in text for phrase in CHINESE_STOCK_PHRASES):
        return True
    # Nothing but punctuation ("...", "-") isn't speech.
    if not re.search(r"[A-Za-z0-9㐀-鿿]", text):
        return True
    # Labels for non-speech instead of words: "[BLANK_AUDIO]", "[inaudible]", "(M)".
    if re.fullmatch(r"\s*[\[(（【][^\])）】]*[\])）】]\s*[.,，。]?\s*", text):
        return True
    # Noise often comes out as one character or word repeated over and over
    # ("Arcary,,,,,,,,,,,,,," in a real scrim), or as broken characters.
    if re.search(r"(.)\1{7,}", text) or "�" in text:
        return True
    words = text.lower().split()
    if len(words) >= 6 and len(set(words)) <= len(words) / 4:
        return True
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


class LanguageLimiter:
    """Wraps the speech engine so that when it guesses the language of each
    stretch of speech, it only chooses between LANGUAGES. Left alone it
    considers all 99 languages it knows, and could mistake a short English
    callout for Welsh or Japanese. Everything else passes straight through."""

    def __init__(self, engine, allowed):
        self._engine = engine
        self._allowed = set(allowed)

    def detect_language(self, *args, **kwargs):
        results = self._engine.detect_language(*args, **kwargs)
        limited = []
        for options in results:            # options: [("<|en|>", 0.97), ...], best first
            kept = [(token, p) for token, p in options if token[2:-2] in self._allowed]
            limited.append(kept or options)
        return limited

    def __getattr__(self, name):
        return getattr(self._engine, name)


TRANSLATE_WINDOW_S = 28    # pack Chinese lines into chunks this long…
TRANSLATE_GAP_S = 1.5      # …with this much silence between them


def translate_chinese_lines(engine, audio, lines, translate_hints, label, log, stop_event):
    """Add an English translation ("text_en") to every Chinese line, using the
    same model on the line's audio. English League words are given as hints
    so "小龙" comes out as "drake" rather than "Xiaolong" more often.

    The model always works on 30-second chunks, so translating one short
    line at a time wastes most of each chunk. Instead, several lines are
    packed into one chunk with a short silence between them, the chunk is
    translated once, and each translated piece goes back to the line whose
    slot it falls in (by timing). Any line that ends up with nothing is
    translated on its own."""
    chinese = [line for line in lines if line["language"] == "zh"]
    if not chinese:
        return
    log(f"    {label}: translating {len(chinese)} Chinese line(s) to English…")

    def clip_of(line):
        return audio[int(max(0.0, line["start"] - 0.2) * 16000):int((line["end"] + 0.3) * 16000)]

    def translate(window, timestamps, use_hints=True):
        return engine.translate(window, timestamps, translate_hints if use_hints else None)

    batch, length = [], 0.0
    batches = []
    for line in chinese:
        clip = clip_of(line)
        seconds = len(clip) / 16000 + TRANSLATE_GAP_S
        if batch and length + seconds > TRANSLATE_WINDOW_S:
            batches.append(batch)
            batch, length = [], 0.0
        batch.append((line, clip))
        length += seconds
    if batch:
        batches.append(batch)

    gap = np.zeros(int(TRANSLATE_GAP_S * 16000), dtype=np.float32)
    for batch in batches:
        if stop_event is not None and stop_event.is_set():
            raise Stopped()
        pieces, slots, position = [], [], 0.0
        for line, clip in batch:
            slots.append((position, position + len(clip) / 16000, line))
            pieces += [clip, gap]
            position += len(clip) / 16000 + TRANSLATE_GAP_S
        found = {id(line): [] for _, _, line in slots}
        for segment in translate(np.concatenate(pieces), timestamps=True):
            # The line whose slot overlaps this translated piece the most.
            overlap = [(min(segment.end, end) - max(segment.start, start), line)
                       for start, end, line in slots]
            best, line = max(overlap, key=lambda pair: pair[0])
            if best > 0 and not looks_like_echo(segment.text, translate_hints):
                found[id(line)].append(segment.text.strip())
        for _, _, line in slots:
            line["text_en"] = " ".join(found[id(line)]).strip()
            if not line["text_en"]:          # fallback: on its own, without hints
                line["text_en"] = " ".join(s.text.strip() for s in
                                           translate(clip_of(line), False, use_hints=False)).strip()


class Progress:
    """Prints "x / y (z%), about N left" every 30 seconds."""

    def __init__(self, label, duration, log):
        self.label, self.duration, self.log = label, duration, log
        self.started = self.last = time.monotonic()

    def update(self, position):
        now = time.monotonic()
        if now - self.last >= 30 and self.duration > 0:
            done = min(1.0, position / self.duration)
            left = (now - self.started) / done * (1 - done) if done > 0 else 0
            self.log(f"    {self.label}: {clock_text(position)} / {clock_text(self.duration)} "
                     f"({done:.0%}), about {clock_text(left)} left")
            self.last = now


# ---------------------------------------------------------------------------
# Speech engines. Two ways to run the same Whisper model:
#   CpuEngine  faster-whisper on the processor (works on any PC)
#   GpuEngine  whisper.cpp on the graphics card through Vulkan (AMD, NVIDIA
#              or Intel cards); several times faster where it's available
# Both turn audio into the same kind of lines, so everything after
# (pauses, Chinese, translation, stats) is identical.
# ---------------------------------------------------------------------------

class CpuEngine:
    name = "processor (faster-whisper)"

    def __init__(self, paths, model_name, log):
        from faster_whisper import WhisperModel
        log(f"Loading the speech model ({model_name}) on the processor. The first time, "
            "this downloads it (about 0.5 GB)…")
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8",
                                  cpu_threads=CPU_THREADS, download_root=str(paths.models))
        self.model.model = LanguageLimiter(self.model.model, LANGUAGES)
        self.key = f"cpu:{model_name}"

    def count_tokens(self, text):
        return len(self.model.hf_tokenizer.encode(text, add_special_tokens=False).ids)

    def transcribe_lines(self, audio, hints, label, log, stop_event):
        duration = len(audio) / 16000
        bilingual = self.model.model.is_multilingual
        segments, _ = self.model.transcribe(
            audio, language=None if bilingual else "en", multilingual=bilingual, beam_size=5,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
            word_timestamps=True, condition_on_previous_text=False,
            hotwords=hints or None, hallucination_silence_threshold=2.0)
        results, skipped = [], 0
        progress = Progress(label, duration, log)
        for segment in segments:
            if stop_event is not None and stop_event.is_set():
                raise Stopped()
            text = segment.text.strip()
            if not text or looks_like_hallucination(segment, text):
                skipped += 1
                continue
            results.extend(split_at_pauses(segment))
            progress.update(segment.end)
        return results, skipped

    def translate(self, window, timestamps, prompt):
        segments, _ = self.model.transcribe(
            window, language="zh", task="translate", beam_size=5, vad_filter=False,
            without_timestamps=not timestamps, condition_on_previous_text=False, hotwords=prompt,
            # No random retries: when unsure, the model normally retries with some
            # randomness, which turned 我的锅 into "My barradish" in testing.
            # Fixed settings give the same, sensible translation every time.
            temperature=0.0)
        return [SimpleNamespace(start=s.start, end=s.end, text=s.text) for s in segments]


GPU_MODEL_FILE = "ggml-small.bin"      # the same "small" model, in whisper.cpp's format
GPU_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/" + GPU_MODEL_FILE
GPU_WINDOW_S = 28                       # speech is grouped into chunks up to this long
GPU_GAP_S = 0.6                         # silence put between pieces of speech in a chunk
PAUSE_S = 1.0                           # a pause this long starts a new line
GPU_BEAM_SIZE = 5                       # 5 = beam search (more accurate); see GpuEngine


class GpuEngine:
    name = "graphics card (whisper.cpp + Vulkan)"

    def __init__(self, paths, log):
        from pywhispercpp.model import Model
        import _pywhispercpp as pw
        self.pw = pw
        model_path = paths.models / GPU_MODEL_FILE
        if not model_path.exists():
            log(f"Downloading the graphics-card speech model (about 0.5 GB, once)…")
            download(GPU_MODEL_URL, model_path)
        log("Loading the speech model on the graphics card…")
        # Each line's start comes from the speech detector (see transcribe_lines),
        # so whisper.cpp's slower "DTW" word timing isn't needed: in testing it
        # was 20% slower and no more accurate than flash attention, the default.
        self.model = Model(str(model_path), redirect_whispercpp_logs_to=None,
                           params_sampling_strategy=1 if GPU_BEAM_SIZE > 1 else 0)   # beam / greedy
        self.key = f"gpu:{GPU_MODEL_FILE}"

    @staticmethod
    def count_tokens(text):
        # Close enough for the hint budget: ~3.5 letters per token in English,
        # ~1.5 tokens per Chinese character.
        chinese = len(CJK.findall(text))
        return int(len(CJK.sub("", text)) / 3.5 + chinese * 1.5) + 1

    def _run(self, audio, **params):
        """One whisper.cpp pass. Every setting is passed every time, because
        the bridge remembers settings between calls."""
        base = dict(language="en", translate=False, initial_prompt="", token_timestamps=False,
                    no_context=True, single_segment=False, print_progress=False,
                    print_realtime=False, print_timestamps=False, suppress_blank=True,
                    suppress_nst=True,          # no "[BLANK_AUDIO]"-style labels
                    temperature=0.0, temperature_inc=0.2,
                    beam_search={"beam_size": GPU_BEAM_SIZE, "patience": -1.0},
                    greedy={"best_of": 1})
        base.update(params)
        return self.model.transcribe(audio, **base)

    def pick_language(self, audio):
        """English or Chinese for this chunk (never any other language). Leans
        English: on short or noisy chunks the guess is shaky, and mistaking
        English for Chinese garbles it, so Chinese has to be clearly ahead."""
        _, probabilities = self.model.auto_detect_language(audio)
        english = float(probabilities.get("en", 0.0))
        chinese = float(probabilities.get("zh", 0.0))
        return "zh" if chinese > 2 * english else "en"

    def _words(self):
        """The words of the last pass, with timings, from the token level.
        Token texts arrive as raw bytes and are joined before decoding, so a
        Chinese character split across two tokens comes out whole."""
        pw, ctx = self.pw, self.model._ctx
        end_of_text = pw.whisper_token_eot(ctx)
        segments = []
        for i in range(pw.whisper_full_n_segments(ctx)):
            words, current = [], None
            for j in range(pw.whisper_full_n_tokens(ctx, i)):
                data = pw.whisper_full_get_token_data(ctx, i, j)
                if data.id >= end_of_text:                # timestamps and other markers
                    continue
                piece = pw.whisper_full_get_token_text(ctx, i, j)
                piece = piece if isinstance(piece, bytes) else piece.encode("utf-8")
                starts_word = piece.startswith(b" ") or (current is not None and
                                                         _ends_with_whole_chinese_char(current["bytes"]))
                when = data.t0
                if current is None or starts_word:
                    if current is not None:
                        words.append(current)
                    current = {"bytes": piece, "t0": when, "t1": when, "p": [data.p]}
                else:
                    current["bytes"] += piece
                    current["t1"] = max(current["t1"], when)
                    current["p"].append(data.p)
            if current is not None:
                words.append(current)
            no_speech = (pw.whisper_full_get_segment_no_speech_prob(ctx, i)
                         if hasattr(pw, "whisper_full_get_segment_no_speech_prob") else 0.0)
            segments.append((words, float(no_speech)))
        return segments

    def transcribe_lines(self, audio, hints, label, log, stop_event):
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        duration = len(audio) / 16000
        speech = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500))
        # Stretches of speech less than a second apart are one utterance (a
        # breath mid-sentence isn't a new callout): keep the real audio between
        # them and transcribe them together. Lines still split at 1 s pauses.
        merged = []
        for part in speech:
            if (merged and part["start"] - merged[-1]["end"] < int(PAUSE_S * 16000)
                    and part["end"] - merged[-1]["start"] <= (GPU_WINDOW_S - GPU_GAP_S) * 16000):
                merged[-1]["end"] = part["end"]
            else:
                merged.append(dict(part))
        speech = merged
        # Group the speech into chunks of up to GPU_WINDOW_S seconds, remembering
        # where each piece came from so timings can be put back.
        windows, current, length = [], [], 0
        limit = GPU_WINDOW_S * 16000
        gap = int(GPU_GAP_S * 16000)
        for part in speech:
            start, end = part["start"], part["end"]
            while end - start > 0:
                take = min(end - start, limit - gap)
                if current and length + take + gap > limit:
                    windows.append(current)
                    current, length = [], 0
                current.append((start, start + take))
                length += take + gap
                start += take
        if current:
            windows.append(current)

        results, skipped = [], 0
        progress = Progress(label, duration, log)
        for pieces in windows:
            if stop_event is not None and stop_event.is_set():
                raise Stopped()
            # Pieces of speech are joined with a short silence between them,
            # so the model can hear where one ends and the next begins.
            silence = np.zeros(int(GPU_GAP_S * 16000), dtype=np.float32)
            chunk = np.concatenate([part for s, e in pieces for part in (audio[s:e], silence)])
            mapping, position = [], 0.0
            for s, e in pieces:
                mapping.append((position, s / 16000, (e - s) / 16000))
                position += (e - s) / 16000 + GPU_GAP_S

            def original(t):
                """A time in the joined chunk -> the time in the real recording.
                A word that lands in one of the added silences belongs to the
                nearer side of it."""
                for n, (chunk_start, real_start, length_s) in enumerate(mapping):
                    if t <= chunk_start + length_s:
                        return real_start + max(0.0, t - chunk_start)
                    if n + 1 < len(mapping) and t < mapping[n + 1][0]:
                        if t - (chunk_start + length_s) < mapping[n + 1][0] - t:
                            return real_start + length_s           # end of this piece
                        return mapping[n + 1][1]                   # start of the next
                chunk_start, real_start, length_s = mapping[-1]
                return real_start + min(length_s, max(0.0, t - chunk_start))

            # The language is judged on the whole chunk (short clips are hard
            # to judge)...
            language = self.pick_language(chunk)
            # ...but each stretch of speech is transcribed on its own, so every
            # word's time comes from that stretch and can't drift onto a
            # neighbouring one. (Joined chunks let boundary words slip across;
            # the graphics card is fast enough to do it this way.)
            for s, e in pieces:
                start_s, length_s = s / 16000, (e - s) / 16000
                self._run(audio[s:e], language=language, token_timestamps=True,
                          # English stretches get only the English hints: the
                          # Chinese ones made the model put Chinese punctuation
                          # in English ("Janna，s").
                          initial_prompt=(hints if language == "zh" else hints.split("。")[0]) if hints else "")
                for words, no_speech in self._words():
                    made = []
                    for w in words:
                        text = w["bytes"].decode("utf-8", errors="ignore")
                        if not text.strip():
                            continue
                        t0 = start_s + min(length_s, w["t0"] / 100)
                        t1 = start_s + min(length_s, max(w["t1"], w["t0"]) / 100)
                        made.append(SimpleNamespace(word=text, start=t0, end=t1,
                                                    probability=float(np.mean(w["p"])) if w["p"] else 0.0))
                    if not made:
                        continue
                    text = "".join(w.word for w in made).strip()
                    logprob = float(np.mean([np.log(max(w.probability, 1e-6)) for w in made]))
                    segment = SimpleNamespace(text=text, start=made[0].start, end=made[-1].end,
                                              words=made, avg_logprob=logprob, no_speech_prob=no_speech)
                    if looks_like_hallucination(segment, text):
                        skipped += 1
                        continue
                    results.extend(split_at_pauses(segment))
            progress.update(pieces[-1][1] / 16000)
        return results, skipped

    def translate(self, window, timestamps, prompt):
        segments = self._run(window, language="zh", translate=True, initial_prompt=prompt or "",
                             temperature_inc=0.0)     # no random retries (see CpuEngine)
        return [SimpleNamespace(start=s.t0 / 100, end=s.t1 / 100, text=s.text) for s in segments]


def _ends_with_whole_chinese_char(data):
    """True when these bytes are complete text ending in a Chinese character
    (or Chinese punctuation), so the next token starts a new 'word'."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False                      # the character isn't finished yet
    return bool(text) and (has_chinese(text[-1]) or text[-1] in "，。？！、：；")


def download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".part")
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(temp, "wb") as f:
            for block in response.iter_content(1 << 20):
                f.write(block)
    temp.replace(target)


USE_GRAPHICS_CARD = True    # False = always use the processor


def make_engine(paths, model_name, log):
    """The graphics card when possible, otherwise the processor."""
    if USE_GRAPHICS_CARD:
        try:
            engine = GpuEngine(paths, log)
            log(f"Using the {engine.name}.")
            return engine
        except Exception as error:
            log(f"Graphics card not available for transcription ({type(error).__name__}: "
                f"{error}); using the processor instead.")
    engine = CpuEngine(paths, model_name, log)
    log(f"Using the {engine.name}.")
    return engine


def transcribe_track(engine, audio_path, hints, label, log, stop_event, translate_hints=""):
    log(f"  Reading {audio_path.name}…")
    audio = load_audio_16k(audio_path, log)
    duration = len(audio) / 16000
    log(f"  Transcribing {label} ({clock_text(duration)} of audio)…")
    started = time.monotonic()
    results, skipped = engine.transcribe_lines(audio, hints, label, log, stop_event)
    # Which language is each line? Chinese characters mean Chinese (mixed
    # lines like "Kai'Sa 没有 flash 了" count as Chinese).
    for line in results:
        line["language"] = "zh" if has_chinese(line["text"]) else "en"
        if line["language"] == "en":
            # An English line heard in a mostly-Chinese stretch can pick up
            # Chinese punctuation ("…for this drake，"); use English punctuation.
            line["text"] = line["text"].translate(FULLWIDTH_TO_ASCII).strip()
        line["text_en"] = line["text"] if line["language"] == "en" else ""
    translate_chinese_lines(engine, audio, results, translate_hints or TRANSLATE_GLOSSARY,
                            label, log, stop_event)
    chinese = sum(1 for line in results if line["language"] == "zh")
    log(f"    {label}: done, {len(results)} lines"
        + (f" ({chinese} in Chinese)" if chinese else "")
        + f" in {clock_text(time.monotonic() - started)}")
    return {"duration_s": round(duration, 3), "segments": results, "skipped": skipped}


def transcribe_recording(engine, folder, paths, vocab, slang, nicknames, fixer,
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
        lambda s: range(engine.count_tokens(s)),
        champions, slang, nicknames, vocab.get("champions_zh"))

    work = paths.work / info["id"]
    work.mkdir(parents=True, exist_ok=True)
    translate_hints = translation_hints(champions)
    settings = {"model": model_name, "engine": engine.key, "hints": hints,
                "translate_hints": translate_hints,
                "languages": list(LANGUAGES),
                "script_version": VERSION}
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
        result = transcribe_track(engine, track, hints, label, log, stop_event, translate_hints)
        result["settings"] = settings
        temp = saved_path.with_suffix(".tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temp.replace(saved_path)
        track_results[track] = result

    # (Tracks with no speech at all, e.g. someone who joined for a minute,
    # are ignored here: they can't be misaligned in any way that matters.)
    durations = [r["duration_s"] for r in track_results.values() if r["segments"]] or [0.0]
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
                "language": seg.get("language", "en"),
                "text": fixer.fix(seg["text"]), "text_raw": seg["text"],
                # English version: the line itself, or the translation of a Chinese line
                "text_en": fixer.fix(seg.get("text_en") or seg["text"]),
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
        "model": model_name, "languages": list(LANGUAGES),
        "vocabulary_patch": vocab.get("patch"), "hints": hints,
        "poller_games": [g["file"] for g in games],
        "tracks": [{"file": t.name, "speaker": speaker_name(t), "duration_s": r["duration_s"],
                    "lines": len(r["segments"]),
                    "chinese_lines": sum(1 for s in r["segments"] if s.get("language") == "zh")}
                   for t, r in track_results.items()],
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
        f.write("Times are real-world clock time. 'rec' is the position in Craig's audio files.\n")
        f.write("Chinese lines are marked (中文); the line under each is a rough machine translation.\n\n")
        for u in utterances:
            wall = datetime.fromtimestamp(u["t"]).strftime("%H:%M:%S")
            marker = " (中文)" if u["language"] == "zh" else ""
            f.write(f"[{wall} | rec {clock_text(u['audio_time'])}] {u['speaker']}{marker}: {u['text']}\n")
            if u["language"] == "zh":
                f.write(f"{' ' * 22}→ {u['text_en']}\n")
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


_engine_cache = {}


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

    if model_name not in _engine_cache:
        _engine_cache[model_name] = make_engine(paths, model_name, log)
    engine = _engine_cache[model_name]

    done = []
    for folder in to_do:
        try:
            result = transcribe_recording(engine, folder, paths, vocab, slang, nicknames, fixer,
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
