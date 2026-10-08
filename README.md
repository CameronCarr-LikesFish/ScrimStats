# ScrimStats

A Windows app for reviewing a League of Legends team's scrim voice comms.
It records what happens in each game, transcribes what everyone said, lines
the two up on one clock, and tracks each player's comms habits over months.

- **Record games:** reads League's local game feed once a second while you
  play and saves every event (kills, dragons, towers…) with both the
  real-world time and the in-game time.
- **Transcribe comms:** turns a [Craig](https://craig.chat) multi-track
  Discord recording into who said what, and when. Speech-to-text runs
  **entirely on your PC** (Whisper), so nobody's voice is uploaded. It knows
  League vocabulary: every champion, item, ability, summoner spell and rune,
  from Riot's official data, in English and Chinese.
- **Fast on a graphics card:** transcription runs on the GPU through
  whisper.cpp + Vulkan (AMD, NVIDIA or Intel), about 11× faster than on the
  processor. A 3-hour, 8-person scrim took 11 minutes. Without a usable
  graphics card it falls back to the processor.
- **English and Mandarin Chinese:** it detects which language is being
  spoken, even in mixed sentences. Chinese lines are kept in Chinese with a
  rough English translation, and the stats read Chinese directly.
- **Review:** a dashboard of per-player stats over time, per roster
  (Varsity, JV...), for whole games or just the early, mid or late game:
  - **Information:** enemy info, my status, item timers, timers, asking for
    resources, and item or gold talk before objectives.
  - **Vision:** ward talk (warding, asking for vision, sweeping) and
    League's vision score.
  - **Shotcalling:** calls per player, shotcall share, and main shotcallers
    per game.
  - **Attitude:** positivity, flame at teammates (every flame line quoted word
    for word), accountability per play, and blame after death.
  - **Talking:** talking over teammates, fight presence, and talk share.
  - **Champions:** win rate on every champion you've played or played
    against, with icons.
  - **Between games:** what was said in lobby and draft, kept apart from
    the in-game stats.

## Download and use

1. Download the latest `ScrimStats-*.zip` from
   [Releases](../../releases), unzip it anywhere, and double-click
   **`ScrimStats.exe`**. No Python needed.

   Windows may say "Windows protected your PC", because the app isn't
   signed. Click **More info → Run anyway**.
2. Read **`How to use.txt`** next to the `.exe`. In short:
   - Click **Start recording** before a scrim block. If you spectate, have
     one player record too: spectators aren't told about dragons or barons.
   - Afterwards, use **Add Craig download…** and then **Transcribe**.
   - Set up your rosters in the **Rosters** tab, then open **Dashboard**.
3. The first transcription downloads the speech model (about 0.5 GB), once.

It only works on the PC where League is running, because the game's data
feed exists only on that machine while a game is open. It can't run as a
website.

## Privacy

Everything stays on the PC running the app: game recordings, voice
transcripts, and the dashboard (a local HTML file). The only internet use is
downloading the speech model once and League's name list once per patch.
**Don't commit your app folder's data to git.** It contains your teammates'
voices and behavior.

## Build from source

Requires Windows and Python 3.12+.

```
pip install -r requirements.txt -r requirements-build.txt
python build.py
```

This builds the `.exe` and installs it into a `ScrimStats` folder next
to this source folder. Check a build with
`ScrimStats.exe --self-test`, then read `_data\self-test.log`.

To run from source without building: `python app.py`. Set `LSC_HOME` to use
a different data folder.

| File | What it is |
|---|---|
| `app.py` | The window |
| `poller.py` | Game recorder |
| `transcriber.py` | Craig recordings → timestamped transcripts |
| `analytics.py` | Transcripts + games → stats and `Dashboard.html` |
| `dashboard_template.html` | The dashboard page |
| `common.py` | Where every folder lives |
| `defaults/` | Starting settings: callout phrase lists, League words, nicknames, corrections |
| `gpu-engine/` | How to build the graphics-card engine (whisper.cpp + Vulkan), and the patch it needs |
| `build.py` | Packages the `.exe` |

The app's font is [Lato](https://www.latofonts.com/) by Łukasz Dziedzic, included under the
SIL Open Font License (`ui/fonts/OFL.txt`).

## History

See [CHANGELOG.md](CHANGELOG.md). It covers every stage from the first
recorder to now, with test results and the reasoning behind each decision.
