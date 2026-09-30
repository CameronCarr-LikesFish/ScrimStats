# Changelog: LoL Scrim Comms

This changelog covers the whole history of the project. It records what was
built, what broke, why it broke, how it was fixed, and how each piece was
verified.

**What this project is:** a toolkit for reviewing a collegiate League of
Legends team's scrim voice comms. It records what happens in each game,
transcribes what everyone said, lines the two up on one clock, and tracks
each player's comms habits over months.

**Format.** Newest release first. Every release has a summary, followed by
some of these sections: **Added**, **Changed**, **Fixed**, **Removed**,
**Verified** (what was tested, with real numbers), **Decisions** (why it
works the way it does) and **Known limitations**.

**Versions.** Releases 1.0.0 to 1.3.0 were separate tools, each run by its
own `.bat` file. 2.0.0 combines them into one app. The version numbers
before 2.0.0 were assigned after the fact, to give the history a clear order.

**Test machine:** Windows 11 Home (10.0.26200), Python 3.14.4, AMD Ryzen 5
7600X, AMD Radeon RX 7900 GRE, 31 GB RAM. The League game patch during
development was 16.19.

---

## [2.0.1]: 2026-09-30: Ready for GitHub

The project moves onto GitHub: the code lives in a repository, and the
ready-to-run app is offered as a download.

### Added

- **`README.md`**, the repository's front page: what the app does, how to
  download and use it, the privacy notes, and how to build it from source.
- **`.gitignore`** keeps build output and **all app data** out of git:
  recordings, transcripts, settings, the speech model and the dashboard.
  That data contains teammates' voices and behavior.
- **`requirements.txt`** (what the app needs) and **`requirements-build.txt`**
  (what building the `.exe` needs).

### Changed

- **Personal details removed from the code.** The example line in the
  roster template used a real Discord name and Riot ID; it now uses a
  made-up one (`Alex | alex | MidDiff#NA1`). Rosters that were already
  created are unaffected.

### Removed

- **The three 1.x tool folders** (`lol-scrim-poller`,
  `lol-scrim-transcriber`, `lol-scrim-analytics`) were deleted from this
  PC, after checking that everything worth keeping was in the app. The four
  game recordings were confirmed byte-identical, and the speech model had
  been copied.

### Known limitations

- **Can't run as a website.** GitHub stores and distributes the app, but it
  can't run it: the recorder needs League running on the same PC, and
  transcription runs locally on purpose.

---

## [2.0.0]: 2026-09-30: One app, and stats built around information vs. shotcalling

Two changes, both requested after reviewing the 1.3.0 dashboard:

1. **The stats were rebuilt around what the team cares about most:**
   information versus shotcalling. Frustration now only counts against
   someone when it's aimed at a teammate.
2. **The three tools became one app.** There's one folder and one
   `LoL Scrim Comms.exe` with a window, instead of three folders with three
   `.bat` files and a console window each.

### Added: Comms stats

- **Information is split into four kinds**, each tracked separately and as
  a total ("Info calls per 10 min"):
  - **Enemy info:** where enemies are and what they have ("Kai'Sa no
    flash", "jungler MIA", "he's back").
  - **My status:** telling the team about yourself ("I don't have flash",
    "I need to back", "I don't know where my laner is").
  - **Item timers:** telling the team about your items. "I'll have IE for
    drake" and "I won't have my item" both count, because either way the
    team gets the information. **Every item name** on Summoner's Rift from
    Riot's official data is recognized automatically. Short versions like
    "Zhonya's" and "Rabadon's" are generated from the full names, and common
    nicknames (IE, BotRK, bork, GA, QSS, LDR, NLR…) are in the editable
    list.
  - **Timers:** "drag in 40", "flash up in 20".
- **Item timers before objectives:** for each dragon, baron, herald, grubs
  or Atakhan taken, whether the player gave item info in the 90 seconds
  before. This measures exactly the "I will / won't have Infinity Edge for
  this drake" call.
- **Shotcalling is tracked separately from information:**
  - **Shotcalls per 10 min:** calling the team plan ("we're fighting drake",
    "reset", "group mid").
  - **Shotcall share:** each player's part of the team's calls.
  - **Main shotcallers per game:** a team stat counting how many people made
    at least 20% of the calls in each game, for games with at least 10
    calls. A rising number means too many people are calling.
- **Frustration at teammates per 10 min:** only frustration aimed at
  someone else ("what the fuck are you doing", "Rin why did you go in").
  Frustration at yourself ("fuck this, I'm so bad") is recorded but never
  scored.
- **Blame after death:** the share of a player's deaths followed within 20
  seconds by frustration aimed at a teammate.
- **Objective mentions per 10 min:** any mention of an objective, whatever
  kind of call it is.
- **Accountability** is now marked "more is better" on the dashboard.

### Added: The app

- **`LoL Scrim Comms.exe`** opens one window with three numbered steps:
  1. **Record games:** Start/Stop, with a live status line ("Recording
     game_… · game clock 14:32 · 23 events").
  2. **Transcribe comms:** Transcribe/Stop, "Add Craig download…" (a file
     picker that copies the `.zip` in), and a count of recordings waiting.
  3. **Review:** Open dashboard, Edit roster, and shortcuts to the
     Settings, Transcripts and app folders.

  An **Activity** panel shows everything the tools report, with
  timestamps.
- **One tidy folder:** `Craig downloads`, `Game recordings`,
  `Transcripts` and `Settings` are the folders people use. `_data` (speech
  model, League names, resume points) and `_internal` (the packaged
  program) can be ignored. The whole folder can be moved anywhere.
- **Settings are plain-text files you can edit in Notepad**:
  `Roster.txt`, `Callout types.txt`, `League words.txt`,
  `Champion nicknames.txt` and `Corrections.txt`. Defaults are created on
  first run and never overwrite your edits.
- **`How to use.txt`** is a one-page guide that sits next to the `.exe`.
- **Only one copy of the app can run at a time**, so two recorders can
  never record the same game twice. Opening a second copy shows "already
  open".
- **Safe closing:** closing the window while recording or transcribing asks
  first, then lets the recorder finish writing the current game's file
  before exiting.
- **Warning before transcribing while recording**, because transcription
  uses a lot of processor power and could lower your FPS mid-game.
- **Transcription can be stopped from the window.** It stops at the next
  line, keeps finished speakers, and resumes later.
- **A hidden self-test mode:** `LoL Scrim Comms.exe --self-test` runs the
  recorder, transcribes anything in `Craig downloads` and builds the
  dashboard with no window, then writes `_data\self-test.log`. If a
  library crashes hard, the log records exactly where.
- **An app icon:** sound-wave bars on a dark tile.
- **A demo dashboard** (`Demo dashboard (fake data).html`, in the source
  folder) shows a fake year with the 2.0 stats.

### Changed

- **Positivity** is now positive phrases ÷ (positive phrases + frustration
  aimed at teammates). Frustration at yourself no longer lowers it.
- **Comms are counted per line, not per phrase.** Each kind of call counts
  at most once per transcript line, and a line is roughly one callout
  (lines are split at 1-second pauses). Before, "I'm 300 gold off
  Zhonya's" counted as 3 item calls ("gold", "Zhonya's", and the item
  name). Now it counts as 1. 1.3.0 never ran on real data, so no existing
  numbers change.
- **"My status" and "Item timers" need the "I/my/me" close by**: within 4
  words of the status or item word. Before, "I think Ahri is missing, she
  has no flash" also counted as the speaker's own status because of "I
  think".
- **Enemy info is dropped when the sentence is about yourself**: "I have no
  flash" is your status. It still counts when an enemy is also named ("I'm
  going bot, Kai'Sa has no flash").
- **Blaming isn't counted as a shotcall**: "why did you go in" contains the
  shotcall phrase "go in", but it's blame.
- **The dashboard's stat menu is grouped:** Information, Shotcalling,
  Attitude, Talking. Player cards now show: info calls, item timers before
  objectives, shotcall share, positivity, accountability, and talking over
  teammates. The sessions table gains a "Main shotcallers" column, and the
  wins-vs-losses table now compares info calls, shotcalls, positivity,
  talking over, and fight presence.
- **Phrase matching is faster and more precise.** It now finds whole words
  and takes the longest match at each position. It handles about 46,000
  lines per second, so a year of scrims analyzes in about a second.
- **Settings file names** changed from `lol_slang.txt` / `corrections.txt`
  / `callout_categories.txt` to readable names in the `Settings` folder.
- **Speech recognition, the recorder and the transcript format are
  unchanged** from 1.0.0–1.2.0. They were moved into the app, not rewritten.
- **The spreadsheet file** is now `Comms stats.csv`, with columns for every
  new stat, including `item_timers_before_objectives_%`, `shotcall_share_%`
  and `blame_after_death_%`.

### Removed

- **"Frustrated phrases per 10 min":** frustration at yourself is fine in a
  League environment, so the stat was replaced by "Frustration at teammates
  per 10 min".
- **"Tilt after death":** replaced by "Blame after death" for the same
  reason.
- **The three separate `.bat` launchers.** The old folders
  (`lol-scrim-poller`, `lol-scrim-transcriber`, `lol-scrim-analytics`) are
  replaced by the app. Their data was copied into the app folder; see
  **Migration**.

### Fixed

- **The packaged app crashed when loading the speech model.** The first
  `.exe` build crashed with a Windows access violation inside the speech
  engine (CTranslate2) as the model loaded. The same code worked outside
  the package.
  - *Ruled out:* too little memory "stack" for the thread. The model loaded
    fine outside the package even with a 256 KB stack.
  - *Root cause:* PyInstaller had bundled a **2017 copy of Microsoft's C++
    runtime** (`msvcp140.dll` / `vcruntime140.dll`, version 14.16.27033),
    and the speech engine needs a current one (14.44.35211).
  - *Fix:* after packaging, the build script now replaces any bundled
    runtime file with the newest one on the build PC. Microsoft allows
    these files to ship alongside apps, so the `.exe` doesn't depend on
    what's installed on the PC running it.
- **Team-only chart listed every player.** "Main shotcallers per game"
  showed a legend chip for each player even though it has only a team
  line. Now the legend just says "Team".
- **Chart axis labels could be misleading:** a 0–5 scale was labeled "0, 1,
  3, 4, 5" (2.5 rounded up to 3). Labels now keep one decimal ("0, 1.3,
  2.5, 3.8, 5").
- **Two ambiguous Enemy info phrases were removed:** "ward" (usually a
  request, like "can someone ward") and a bare "dead".

### Verified

- **Sorting sentences into comms types:** 16 example sentences, all sorted
  correctly after the fixes above, including:
  - "Hey guys, I won't have Infinity Edge for this drake" → Item timers
  - "I think Ahri is missing, she has no flash" → Enemy info only
  - "dude fuck this, I'm so bad" → frustration at self (not scored)
  - "dude what the fuck are you doing" → frustration at teammates
  - "Rin why did you go in" → frustration at teammates, not a shotcall
- **Dashboard on a fake year** (45 sessions, 131 games):
  - Builds in 1.1 seconds, with no browser errors.
  - Checked in the browser: the grouped stat menu, the team-only chart and
    the new player cards.
- **App window, from source:** a scripted run opened the window, started
  the recorder ("Waiting for a game…"), built the dashboard and stopped the
  recorder. Screenshots and the activity log confirmed each step.
- **Packaged `.exe` self-test:**
  - The recorder started and stopped.
  - A real transcription of a two-speaker test recording ran inside the
    `.exe`, applying Craig's 3.5-second start-time correction.
  - The dashboard built, and the log ended "SELF-TEST PASSED".
- **Packaged `.exe` window:** launched normally with its icon in the title
  bar and all three steps showing. It closed cleanly (exit code 0) when
  sent a normal close.
- **Build:** PyInstaller 6.22.3, one folder, no console window. The build
  takes about 47 seconds, and the packaged program files (`_internal`) come
  to 254 MB. The speech model adds 464 MB in `_data`.

### Migration from 1.x

- **Game recordings:** all 4 recorded games were copied into
  `Game recordings` and checked byte-for-byte against the originals.
- **Speech model and League names:** the speech model (464 MB) and League
  name list were copied into `_data`, so there's no re-download.
- **Roster:** a fresh `Settings\Roster.txt` was created, listing the Riot
  IDs found so far. The old roster was an unfilled template, so nothing
  was lost.
- **Old folders:** nothing was deleted. The three old tool folders still
  exist and can be removed once you're happy with the app.

### Known limitations

- **Who a sentence is about** is judged from words like I / you / he and
  names, not real understanding. "You can't do anything against this
  champ" would count as frustration aimed at a teammate.
- **Item timers only measure whether an item call was made.** They can't
  tell whether the player was actually close to an item, because the
  recorder doesn't save item or gold data yet (see **Ideas for later**).
- **Everything is still untested on a real scrim.** No real multi-speaker
  Craig recording has been through the app yet.

---

## [1.3.0]: 2026-09-30: Comms analytics and dashboard

*(Released as `lol-scrim-analytics\analyze.py` v1.0.0.)*

The first version of the stats. It read every transcript and game recording
and built a dashboard showing how each player's comms change over time.

### Added

- **Automatic lining-up of speech and games.** Each scrim session is split
  into the games the recorder captured, and only speech during games counts
  (not champ select or breaks). Game events are placed on the real-world
  clock by counting back from when the recorder saw them. If the recorder
  started mid-game, the clock_sync pairs are used instead, counting back
  from the next sync so that an earlier pause can't shift the time.
- **A roster file** (`Name | Discord name(s) | Riot ID(s)`). Speech is
  matched to players by Discord name, and game events by Riot ID. Several
  accounts per person are supported, so history survives an account
  switch.
  - On first run it creates a template listing every Discord name and the
    most common Riot IDs found, then opens it in Notepad.
  - With no roster filled in, it falls back to showing Discord names.
- **Stats per player:**
  - words per minute and talk share
  - callouts per 10 min by type (info, timers, objectives, shotcalling),
    from an editable phrase list
  - positivity
  - frustrated phrases per 10 min
  - accountability
  - fight presence and words per teamfight
  - tilt after death
  - talking over teammates

  A **teamfight** is 3+ kills with no more than 15 seconds between them.
  **Talking over** means starting to speak while a teammate is mid-sentence;
  overlaps under 0.3 seconds are ignored.
- **`dashboard.html`**, a single page that opens in any browser and works
  offline:
  - **Player cards:** the last 30 days against the 30 before, marked ▲/▼
    with "(better)" or "(worse)".
  - **Trend chart:** group by session, week or month; filter to wins or
    losses; choose a time range; click names to hide lines; hover for
    exact values; arrow keys also work; a table view shows the same data.
  - **Wins vs losses** and **Sessions** tables, plus plain-language
    definitions of every stat.
  - **Light and dark mode.** Each player keeps one color everywhere
    (colorblind-tested palette, fixed by roster order).
  - **Works on a phone**, and too little data shows "–" instead of a
    misleading number.
- **`comms_stats.csv`:** one row per player per session, for Excel or
  Google Sheets.
- **Warnings** for Discord names missing from the roster, Riot IDs never
  seen in any game, and sessions with no recorded games.

### Fixed (during development)

- **Better/worse colors didn't show:** a more specific style rule overrode
  the green/red. Fixed the rule's specificity.
- **Normal wobble was labeled "worse":** a 1-point dip showed up as
  "(worse)". A change now has to be at least 3 points (percentages) or 10%
  (rates) to be called better or worse; anything smaller reads "about the
  same".
- **A misleading console message:** "opening in Notepad" was printed even
  when nothing was opened.

### Verified

A fake year of scrims was generated in the real file formats: 45 sessions,
131 games, 5 players plus an unlisted coach, with trends built in on
purpose. The dashboard found every trend, and players kept steady stayed
flat:

| Player | Stat | Oct–Dec | Jul–Sep | Built-in |
|---|---|---|---|---|
| Theo | Tilt after death | 71.5% | 26.9% | down ✅ |
| Theo | Positivity | 13.3% | 63.4% | up ✅ |
| Rin | Info calls / 10 min | 3.2 | 9.0 | up ✅ |
| Maya | Words / min | 3.0 | 7.1 | up ✅ |
| Maya | Fight presence | 66.1% | 94.6% | up ✅ |
| Jules | Talking over / 10 min | 17.0 | 9.6 | down ✅ |
| Cam | Shotcalling / 10 min | 12.0 | 12.1 | flat ✅ |
| Cam | Tilt after death | 15.5% | 14.5% | flat ✅ |

- **Other checks:**
  - Champ select frustration was correctly left out.
  - The coach was flagged as not in the roster.
  - A full year analyzed in about 3 seconds.
- **In the browser:** the hover readout, both color modes and phone width
  (no sideways scrolling) all worked, with no errors.

### Decisions

- **The dashboard is a local file, not a website.** It holds teammates'
  voices and behavior, so it never leaves the PC unless you choose to share
  it.
- **Stats count words and phrases.** That's transparent, free, and
  editable by the team. The trade-off is that tone and sarcasm are
  invisible, so the dashboard says clearly that it's for trends, not for
  judging single games.

---

## [1.2.0]: 2026-09-30: Comms transcriber

*(Released as `lol-scrim-transcriber\transcriber.py` v1.0.0.)*

Turns a Craig multi-track recording (one audio file per person) into who
said what, with a real-world timestamp on every line. It uses the same clock
as the game recorder.

### Added

- **Speech-to-text on this PC:** Whisper (`small.en`, via faster-whisper,
  8-bit on the processor). No audio is uploaded; the internet is only used
  to download the model once and League's name list once per patch.
- **The Craig start-time correction, applied automatically.** The
  real start of the audio is read from Craig's `raw.dat` (see 1.1.0).
  - If `raw.dat` is missing, it warns loudly and falls back to Craig's
    stated start time.
  - It warns if the speakers' audio files have different lengths, which
    would mean they may not line up with each other.
- **League vocabulary from Riot's official game data** (patch 16.19.1): 173
  champions, 865 abilities, 274 Summoner's Rift items, 9 summoner spells,
  and 67 runes and rune trees. It refreshes itself each patch and works
  offline from the saved copy.
- **Hints for the speech model.** It's told to listen for the champions
  actually picked in that block (read from the recorder's files), plus
  their nicknames, then a priority-ordered slang list, up to Whisper's
  limit. The limit is 223 "tokens" (word pieces); it uses up to 200.
- **Spelling fixes** ("kaisa" → "Kai'Sa", "chogath" → "Cho'Gath", "kog
  maw" → "Kog'Maw", "zhonyas" → "Zhonya's"), plus a corrections file for
  real mishearings ("zayen => Zaahen").
  - A word only changes when its letters already match an official name.
  - Capitals alone are never changed, and "we'll" is never turned into
    "Well".
  - The original wording is always kept as `text_raw`.
- **Filters for "hallucinated" phrases.** These are stock phrases Whisper
  sometimes invents in silence ("thanks for watching"), and it drops them.
  Silence is skipped before transcribing, which prevents most of them.
- **Resuming:** each finished speaker is saved as it completes, so
  stopping partway loses nothing, and runs that are already done are
  skipped.
- **Outputs:**
  - a readable `.txt` file: `[19:42:05 | rec 11:46] shotcaller: …`
  - a `.jsonl` file with speaker, real-world time, spelling-fixed text,
    raw text and per-word timings
- **Input handling:** it unzips Craig downloads by itself, and supports
  dragging a download onto `run_transcriber.bat`.

### Fixed (during development)

- **The speech library couldn't read audio.** faster-whisper 1.2.1's audio
  reader calls the audio library (`av`) with an option that `av` 19
  removed. The transcriber now reads audio itself. This also keeps
  whatever was read if one of Craig's streamed files ends abruptly.
- **Separate callouts were merged into one line.** Skipping silence made
  the model return callouts about 20 seconds apart as a single line with
  one timestamp. "Cho'Gath ult is down" was said 40 seconds after "Kai'Sa
  has no flash" but got the same time. Lines are now split wherever the
  speaker paused for 1 second or more, using each word's own timestamp.
- **A mishearing without champion hints:** "K'Sante" came out as "K
  Santa". Added `k santa => K'Sante` to the corrections list.

### Verified

Tested with fake two-person Craig recordings built from Windows'
text-to-speech voices, including a fake `raw.dat`:

- **Timing:** every line landed within **0.3 seconds** of when it was said
  (errors from −0.26 to +0.30 s), with the 3.5-second start correction
  applied.
- **Recognition:** with champion hints, every word was right, including
  Kai'Sa, K'Sante, Kog'Maw and Zhonya's. **Without** hints (no recorder
  file for that time), "Kai'Sa" came out as "Kyessay", which shows why
  running the recorder during scrims matters.
- **Speed:** 3 minutes of nonstop speech took 17.8 seconds with 6
  processor threads (0.10× real time), against 21.3 seconds with 12.
  6 threads became the default, which puts a 3-hour, 5-person block at
  roughly 20–45 minutes.
- **Stopping and resuming:** reused the finished speaker and redid only
  the other one. A second run skipped work already done.
- **Spelling fixes:** 9 test phrases were fixed correctly, and "we'll",
  "131" and "It's" were correctly left alone.

### Decisions

- **It runs on this PC, not in the cloud.** It's free, private and
  offline, and gives the same result every time. Your AMD graphics card
  can't use the standard speed-up (it needs NVIDIA), so it runs on the
  processor, and the speed tests showed that's fast enough.
- **The speech model is `small.en`,** which balances speed and accuracy.
  `medium.en` is available for about 3× the time.

---

## [1.1.0]: 2026-09-30: Field testing and voice-sync research

No new tool in this release. It covers real-game testing of the recorder,
choosing a voice recorder, and a sync test that found a timing problem
before any real scrim was affected.

### Verified: Recorder in real games

- **A 22-minute Arena game:**
  - All 145 events were recorded (116 champion kills, 22 multikills, 4
    aces, plus game start, first blood and minions spawning), numbered 0 to
    144 with no gaps or duplicates.
  - 133 clock syncs came 9.98–10.00 seconds apart.
  - Real time and game time stayed within **0.08 seconds** of each other
    for the whole game.
  - The file closed on its own with `"reason": "game_closed"` about 5
    seconds after the game window closed.
- **A second game stopped with Ctrl+C at 3 minutes:** 19 events and 22
  syncs, and the file ended cleanly with `"reason": "stopped_by_user"`.
  Ctrl+C also closes the `.bat` window, which is harmless because the file
  is already saved.
- **Arena quirk:** Arena doesn't report a `GameEnd` event, so there's no
  win/loss result. The file still closes correctly, because that's
  triggered by the game shutting down.

### Research: Choosing the voice recorder

- **Chose Craig** (a Discord bot). It records one track per speaker, which
  makes "who said what" free, and writes an exact start time.
  - Download format: **Multi-track → FLAC**, full quality at about half
    the size of WAV.
  - Limits: 6 hours per recording, and recordings are deleted after 7 days.

### Research: The sync test, and what it found

A Practice Tool game recorded by both the recorder and Craig. The tester
said "now" as a turret went down.

- **The problem:** Craig's `info.txt` "Start time" (15:23:55.119 UTC) is
  **not** when its audio files start. The downloaded FLAC cuts off the
  silence before the first person speaks.
- **Where the real timing is:** Craig's raw recording (`raw.dat`) stamps
  every audio page with its position since the start, in 1/48,000ths of a
  second. The first audio page was at **4.05 seconds**, so the FLAC's 0:00
  is really the start time plus 4.05 seconds.
- **Result:** transcription placed "All right, and **now**" at 51.9
  seconds into the audio, and the turret's death predicted 56.6 seconds.
  - Uncorrected, the voice was **4.7 seconds early**, and every callout
    would have been matched to the wrong moment.
  - Corrected, they agree within **0.65 seconds**, most of which is the
    tester saying "now" as the turret fell.
- **The PC's clock** was **0.1 seconds** off internet time. That's
  negligible.
- **Reading Craig's audio:** its FLAC files are written as a stream, which
  trips up simple audio readers at the very end. Later versions read
  them in a way that tolerates this.

### Decisions

- **Timing accuracy of about a second is enough.** Matching comms to fights
  needs seconds, not milliseconds.
- **This correction became a core feature of the transcriber (1.2.0).**

---

## [1.0.0]: 2026-09-29: Game event poller

*(Released as `lol-scrim-poller\event_poller.py` v1.0.0, with
`run_poller.bat` and a README.)*

The first piece: records everything that happens in each game, stamped with
both the real-world time and the in-game time, so it can later be matched
to a voice recording.

### Added

- **Checks the game once a second** through League's built-in local data
  feed (`https://127.0.0.1:2999`).
  - It accepts the game's self-signed certificate and hides the resulting
    warning.
  - "Connection refused" between games is treated as normal: it prints
    "Waiting for a game…" once and stays quiet.
- **Handles a whole scrim block on its own:**
  - It detects each game and ignores the loading screen.
  - One file per game: `recordings\game_YYYY-MM-DD_HHMMSS.jsonl`.
  - It goes back to waiting when a game closes.
  - If the game clock jumps backwards, it treats that as a new game and
    starts a new file.
- **What each file contains:**
  - a `meta` first line (version, start time, timezone)
  - every new event as the game sent it, plus `wall_clock` and
    `game_time`, logged once each (duplicates filtered by EventID)
  - a `clock_sync` pair every 10 seconds
  - a `players` line (who's on which champion)
  - an `end` line saying why the file closed
- **Accurate timestamps:** the real time is taken at the midpoint of each
  request, because the game read its clock somewhere during the request.
- **Crash-proof files:** every line is pushed straight to disk, so a crash
  or closed window never leaves a half-written file.
- **Safe stopping:** Ctrl+C sets a flag and the loop finishes its current
  step, instead of stopping mid-write.
- **Readable console output:** events print as they happen, for example
  `[14:32] CHAMPION_KILL — Ahri killed Zed (assist: Lee Sin)`, with
  champion names looked up from player names. A "still recording" line
  appears every minute, and it notes when it started mid-game and caught up.
- **Clicking in the console can't freeze it.** Windows' "Quick Edit" mode
  (click-to-select, which pauses the program) is turned off for this window
  only.
- **Resilient to surprises:** an unexpected error is shown once and the
  recorder keeps running, so one strange response can't lose a scrim block.
- **`run_poller.bat`** for double-clicking, and a README covering how to
  install Python, run the poller, tell it's working, and test it in
  Practice Tool.

### Fixed (during development)

- **Clock syncs came every 11 seconds, not 10.** Polls landing a few
  milliseconds early pushed each sync to the next second. Added half a
  second of tolerance, and syncs now land at 10.0 seconds.
- **"Game ended" took over 10 seconds, or never came.** On Windows, a
  refused local connection takes about 2 seconds, not an instant, so "5
  failed polls" lasted 10+ seconds. Two changes:
  - The connection timeout was shortened to 1 second, since a running game
    answers in milliseconds.
  - Game-over now means "no answer for 5 seconds" instead of counting
    failures.
- **The `.bat` file used Unix line endings**, which can confuse Windows
  batch files. It was converted to Windows line endings.

### Verified

- **Against a live game in progress:**
  - It started mid-game, caught up on 118 earlier events with no
    duplicates, and showed champion names correctly.
  - Clock syncs came every 10 seconds (after the fix above).
  - A stop signal closed the file cleanly.
- **Against a scripted fake League server** (plain HTTP on this PC; the
  real HTTPS connection was verified against the live game above):
  - It waited quietly with no game, and skipped the loading screen (the
    feed returns "not found" there).
  - It logged each event once with readable lines, and handled a `GameEnd`
    and a stolen dragon.
  - It detected the game closing about 5 seconds later, and picked up the
    next game.
  - It split into a new file when the clock jumped backwards, and a stop
    signal closed the file cleanly.
- **`run_poller.bat`** found Python and showed a friendly "install
  requests" message when that add-on was missing.

### Decisions

- **Every record carries both clocks.** The voice recording only knows
  real-world time and the game only knows game time. Recording periodic
  pairs of both lets them be joined accurately, even across scrim pauses,
  where the game clock stops but real time keeps going.
- **Events are logged exactly as the game sends them**, with no reshaping,
  so no information is ever lost.

---

## Ideas for later

Not built yet. These were noted during development.

- **Item and gold tracking in the recorder.** The game's data feed includes
  every player's items. Recording them would let "Item timers before
  objectives" check whether a player was actually close to an item that
  mattered.
- **Confirming five speakers line up.** The first real scrim recording will
  confirm that all five speakers' files line up with each other. The
  transcriber checks track lengths and warns if they don't.
- **Tuning for real voices.** Accuracy on real comms, with crosstalk,
  excitement and slang, will need tuning through `Corrections.txt` and
  `League words.txt` after the first real scrims.
- **Using the graphics card for speed.** Faster transcription on an AMD
  graphics card (for example via Vulkan) is possible if 20–45 minutes per
  block becomes a nuisance.
- **A shareable version of the dashboard** for teammates or coaches, if
  wanted.
- **More stats over time:** the team plans to add more things to track
  over time, once real data shows what's useful.

---

## For developers

- **Source:** `lol-scrim-comms\` holds `app.py` (window), `poller.py`,
  `transcriber.py`, `analytics.py`, `common.py` (folder layout),
  `dashboard_template.html`, `defaults\` (starting settings) and
  `build.py`.
- **Build:** with Python and the requirements (faster-whisper, requests,
  PyInstaller, Pillow) installed, run `python build.py`. It packages the
  app and installs the program files into `..\LoL Scrim Comms\`, never
  touching the data there. It also refreshes the bundled Microsoft C++
  runtime; see 2.0.0 → Fixed.
- **Run from source against the app's data:** `python app.py`. Set the
  `LSC_HOME` environment variable to point at a different app folder for
  testing.
- **Check a build:** run `LoL Scrim Comms.exe --self-test`, then read
  `_data\self-test.log`.
