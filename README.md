# LoL Scrim Comms

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
- **English and Mandarin Chinese:** it detects which language is being
  spoken, even in mixed sentences. Chinese lines are kept in Chinese with a
  rough English translation, and the stats read Chinese directly.
- **Review:** a dashboard of per-player stats over time:
  - **Information:** enemy info, my status, item timers, and timers, plus
    item timers before objectives.
  - **Shotcalling:** calls per player, shotcall share, and main shotcallers
    per game.
  - **Attitude:** positivity, frustration aimed at teammates, accountability,
    and blame after death.
  - **Talking:** talking over teammates, fight presence, and talk share.

## Download and use

1. Download the latest `LoL-Scrim-Comms-*.zip` from
   [Releases](../../releases), unzip it anywhere, and double-click
   **`LoL Scrim Comms.exe`**. No Python needed.

   Windows may say "Windows protected your PC", because the app isn't
   signed. Click **More info → Run anyway**.
2. Read **`How to use.txt`** next to the `.exe`. In short:
   - Click **Start recording** before a scrim block.
   - Afterwards, use **Add Craig download…** and then **Transcribe**.
   - Click **Open dashboard** to see the stats.
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

This builds the `.exe` and installs it into a `LoL Scrim Comms` folder next
to this source folder. Check a build with
`"LoL Scrim Comms.exe" --self-test`, then read `_data\self-test.log`.

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
| `build.py` | Packages the `.exe` |

## History

See [CHANGELOG.md](CHANGELOG.md). It covers every stage from the first
recorder to now, with test results and the reasoning behind each decision.
