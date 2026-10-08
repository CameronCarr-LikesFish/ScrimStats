# Changelog: ScrimStats

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

## [2.8.0]: 2026-10-08: op.gg links

Asked for: a link to each player's op.gg, and a multi-search with all their
names.

### Added

- **Player cards (Dashboard → Overview):** an **op.gg** link next to each
  name, one per account ("alt 2", "alt 3" for extra accounts).
- **op.gg multi-search** for the selected roster, above the cards.
- **Rosters tab:**
  - an op.gg link under each player's accounts
  - an **op.gg multi-search** button for the roster being edited
  - an **op.gg region** picker (NA by default), saved in
    `_data/settings.json`
- **Inside the app, links open in your normal web browser.** A dashboard
  opened on its own uses ordinary links.

### Decisions

- **Accounts typed without a #tag** ("Spark Salesman") get their tag from
  the recorded games, using the most common tag seen with that name. op.gg
  needs the tag. Picking an account from the list in the Rosters tab
  already stores it with the tag.
- **Link formats** (checked against op.gg):
  - profile: `op.gg/lol/summoners/<region>/<Name>-<TAG>`
  - multi-search: `op.gg/lol/multisearch/<region>?summoners=Name#TAG,...`

### Verified

- All 5 roster accounts got their tags from the recordings.
- In the app page (browser pane, stand-in backend):
  - a link for each player, on the cards and in the Rosters tab
  - the multi-search lists all 5
  - changing the region to EUW changed the links
  - clicks went to "open in browser"
- A real profile link returned 200 from op.gg.

---

## [2.7.1]: 2026-10-08: "Make recorder" and the file pickers work

Reported: "Make recorder seems to do nothing."

### Fixed

- **The file pickers never opened.** In pywebview 6 (the version the app
  is built with), `webview.OPEN_DIALOG` and `webview.SAVE_DIALOG` are
  leftover functions, not dialog types. Passing them opened nothing, so
  three buttons were silently broken:
  - **Make recorder for a teammate…** (save)
  - **Add Craig download…** (open)
  - **Add a player's recordings…** (open)
  They now use `webview.FileDialog.OPEN` / `.SAVE`.
- **"Make recorder" was greyed out without saying why.** It stayed off
  until a webhook link was saved, and none had been (pasted but not
  saved).
  - The button now always responds.
  - It saves the webhook link from step 1 first if one is pasted, and
    says exactly what's missing if not.
  - A pasted webhook link saves itself.
  - The teammate's name is a box next to the button (was a pop-up).
- **Every step shows its own message next to its button,** and any error
  now appears on screen instead of vanishing.

---

## [2.7.0]: 2026-10-08: ScrimStats Recorder for teammates, through Discord

Asked for: a small program a player can run during games, ideally with a
"more elegant, live" way to get the files back than sending them by hand.
Chosen: the recorder posts each game to a Discord channel, and ScrimStats
pulls them in by itself.

Why it matters: a spectator's recording has no dragons, barons or heralds,
and a spectator may see the game late. A player's recording has neither
problem, and it's joined with the spectated one automatically (2.4.0).

### Added

- **ScrimStats Recorder** (`recorder.py`, built as `ScrimStats Recorder.exe`,
  one file).
  - It is only the game recorder plus Discord: no speech model, window or
    dashboard.
  - The player double-clicks it before scrims and leaves its window open.
    Every game is recorded and kept in a "Game recordings" folder next to it.
  - **When a game ends, the file is posted to the team's channel** through a
    webhook ("Game recording from **Name**: game_….jsonl (193 events)").
  - Games that couldn't be sent (no internet, window closed mid-game) are
    sent the next time it starts. A list of sent files stops it posting
    anything twice.
  - **Only scrims are sent** (asked for midway: so a player's duo games
    aren't sent). Two checks:
    1. **It must be a custom game on Summoner's Rift.**
       - The recorder asks the League client on the player's PC
         (`isCustomGame`, from the client's local game-flow endpoint).
       - First tried: matchmade games give each player a lane and custom
         games don't. Rejected, because the team's tournament-draft scrims
         also show lanes (TOP, JUNGLE…). ARAM, Arena and the practice tool
         are also told apart by game mode, map and player count.
    2. **At least 3 of the roster's accounts must be in it**, which leaves
       room for subs. The zip's `recorder.json` carries the roster's Riot
       IDs for this.
    - If the client can't be asked, step 1 falls back to "Summoner's Rift
      with 10 players".
    - Games that don't qualify stay on the player's PC and are never posted.
    - The recorder now also saves the game mode, map, `custom_game` and
      queue ID in each file.
    - **Not yet seen live:** the client check needs a real game with the
      client open. Without the client, everything else was tested on real
      recordings. The 3 scrims qualify; a solo-queue game (0 roster
      accounts) and an Arena game don't; a copy of a scrim marked "not
      custom" is refused.
- **Games tab → "Spectating? Have a player record too"**, a three-step
  setup:
  1. **Webhook:** paste the private channel's webhook link.
  2. **Make recorder for a teammate…:** asks who it's for and saves
     `ScrimStats Recorder (Name).zip`. Inside are the program, a
     `recorder.json` already holding the webhook link and their name, and a
     plain-language "Read me".
  3. **Bot:** paste the bot token and the channel link. The steps to create
     the bot are written out on the page.
- **Pulling games from Discord** (`discord_link.py`).
  - Whenever the Dashboard or Games tab opens (or **Check Discord now** is
    clicked), the bot reads the channel and copies new `game_*.jsonl`
    attachments into Game recordings.
  - It remembers which attachments it already took.
  - A same-named file with different contents is kept as
    `…_from_<sender>.jsonl`, never overwritten.
  - Clear messages for: a wrong token, no permission to read the channel,
    an unknown channel, and "Message Content Intent" switched off. With that
    intent off, Discord hands the bot webhook posts with no files, so the
    app spots that case and says so.
- **Privacy:** the webhook link and bot token stay in `_data/discord.json`
  on the app's PC, never in the code or the repository.

### Fixed

- **Lines that are only "..." no longer count as talking.** That's what the
  speech model writes when it hears a sound but no words: a laugh, a sigh,
  breathing, background noise. The 2026-10-07 scrim had 22 of them (of 2,977
  lines). They didn't add words or callouts, but they did add to talking
  time and could count as talking over someone. They're still shown in the
  transcript.

### Verified

- **Fake Discord (no real requests):**
  - posting attaches the file, with the sender's name and event count
  - pulling imports a new game once, then nothing on the second pull
  - a different file with the same name was saved as `…_from_RecorderBot`
  - a bad token gives the token message; intent off gives the intent message
  - a non-Discord webhook link is refused
- **Recorder from source:** starts, says it isn't connected when there's no
  `recorder.json`, waits for a game.
- **Offline retry:** with the first send failing ("offline"), nothing was
  marked sent. The next attempt sent both waiting games. A restart sent
  nothing again.
- **Games tab (browser pane, stand-in backend):**
  - "Make recorder" stays off until a webhook is saved
  - a bad webhook shows the error
  - saving the bot clears the token box and shows "Bot token saved"
  - Check Discord reports the result
  - no console errors

---

## [2.6.1]: 2026-10-08: The dashboard in tabs

Asked for: the player cards shown first, and the rest split into tabs at the
top (champion stats, negativity / examples…).

### Changed

- **Filters at the top apply to every tab:** Roster, Part of game,
  Wins/Losses, Time.
- **Tabs:**
  - **Overview:** the player cards first, then the trend chart, wins vs
    losses, and sessions. The chart's own Stat and Group by pickers moved
    into the chart's box.
  - **Champions:** picks, played against, bans, and side and first-pick
    records.
  - **Flame & negativity:** every quoted line, with More context and the
    Flame / Negative / Neither buttons. The tab shows how many flame lines
    are in range.
  - **Between games.**
  - **How it works:** what every number means.
- **The tab you were on stays open when you click Refresh** (remembered by
  the app page, not saved anywhere).
- **"Heads up" notes are folded into one line** ("Heads up (3 notes, click to
  read)"), so they no longer push the cards off the first screen.

### Verified

- In the app page (browser pane, stand-in backend):
  - five tabs; Overview shows 6 player cards and the chart
  - Champions and Flame & negativity switch correctly
  - Refresh kept the open tab
  - switching back to Overview redraws the chart at the right width
  - no console errors

---

## [2.6.0]: 2026-10-08: Drafts from Drafter.lol: pick order, bans, sides

Asked for: stats like "our win rate when we first-pick Yunara". The team
drafts on drafter.lol, then locks in blind in League. League's own data has
no pick order or bans at all, so the draft site is the only source.

### How it reads Drafter.lol

- Drafter.lol's official API needs a paid key. However, a draft's public
  page carries its full data for the page itself to show: every game of the
  series, with:
  - both team names and sides, and who picked first
  - the 10 bans
  - the 10 picks in order
  - the patch, and whether it's fearless
- Paste the link once (**Games → Drafts from Drafter.lol**). The app reads
  the page once and keeps the result in `_data/drafts.json`. It never
  re-reads it on its own, so it's one page load per series. Drafter's terms
  don't forbid this.
- **Matching:** each draft game is matched to the recorded game that shares
  at least 8 of its 10 champions, so one late swap doesn't break it. Our
  side of the draft is the side with our champions.
- **Champion names:** Drafter uses Riot's internal keys ("MonkeyKing",
  "Chogath"). These are turned into the game's names ("Wukong", "Cho'Gath")
  using the champion list shipped with the icons.

### Added

- **Champions table:**
  - **Pick** filter:
    - first pick of the draft
    - the team's first pick
    - picks 1–3 (first phase)
    - picks 4–5 (second phase, usually counter picks)
  - For the team you played against too ("their first pick").
- **Bans view:** each champion banned by us and by them, and our W–L in
  games where we banned it.
- **Side and first pick:** blue-side and red-side W–L, W–L with and
  without first pick, and how many games have a draft linked. Sides come
  from the recording, so they work without drafts.
- **Games tab:** a Draft column shows which draft game each recording
  matched.

### Verified

- **The 2026-10-07 series (3 games, fearless, patch 16.20.1):**
  - All 3 drafts matched their recorded games.
  - The draft's side agreed with the recording's every time.
  - Wukong / Cho'Gath / Jarvan IV / Kai'Sa / K'Sante key names translated
    correctly.
- **Dashboard numbers:**
  - Blue side 1–0, red side 0–2.
  - With first pick 1–0.
  - First pick of the draft: Jinx, 1–0.
  - Team's first pick: Jinx 1–0, Ashe 0–1, Cho'Gath 0–1.
  - Bans: Bard banned by us in all 3 games.
- **Bad links:** a non-Drafter link and a draft ID with nothing on it both
  give a clear message instead of an error.

---

## [2.5.0]: 2026-10-08: Champions, correct win/loss, between games, sharp on every monitor

Asked for, while looking at 2.4.2:

- the window adjusting to each monitor
- a "greater context" button on flame lines
- stats only from inside games, with a separate between-games rundown
- per-champion win rates with champion icons, downloaded ahead of time
- a much higher bar for "negative": "we're so fucked", not "oh fuck"

### Fixed

- **Win/loss was wrong for spectated games.** The game reports "Win" or
  "Lose" from one side's point of view. For a spectator that turned out to
  be the blue side (ORDER), not your team. On 2026-10-07 your team was red
  (CHAOS) in games 1 and 3. Your nexus towers fell at 25:12 and 22:18 and
  the game still said "Win", so the dashboard showed **2–0** when the
  scrim was really **1–2**.
  - The winner now comes from **which side lost both nexus towers in the
    last 3 minutes**.
  - If that can't tell (a surrender), it uses the game's Win/Lose, read
    from the right side: blue for a spectator, or the player's own side.
    The recorder now saves the player's side (`active_team`) for this.
  - The result is then turned into **ours**: the side most of the roster's
    accounts were on.
  - All three recordings agree with the nexus towers.
- **Blurry on the second monitor.** That monitor is 1920×1080 at 150%
  scaling, with the main one at 100%. The window library declared one
  scale for the whole program, so on the 150% screen Windows stretched a
  100% picture by 1.5×.
  - The app now declares **per-monitor scaling** (`display.py`), so it's
    drawn at each monitor's real resolution.
  - Windows then doesn't resize the window when it moves between monitors,
    so a small watcher does: the window keeps the same size on screen,
    stays inside the screen it's on, and goes back to its full size on a
    bigger screen. Resizing by hand sets the new size.
  - Tested with a hidden window on both monitors:
    - main monitor: 96 DPI, page pixel ratio 1
    - second monitor: 144 DPI, ratio 1.5 (sharp), 1770×988 physical
    - back on the main monitor: 1180×820 again

### Added

- **Champions** (dashboard): every champion in your games, with **Riot's
  icon**, games, W–L and a win-rate bar.
  - Show **Our picks** (with who played them) or **Played against**.
  - Sort by most played, best or worst win rate.
  - It follows the roster and time range.
  - **Icons are downloaded when the app is built:** every champion,
    shipped inside the app, so they work offline from the start. A
    champion newer than the app is downloaded once into `_data/champions`.
    The icons are Riot's art, so they're never committed to the repository.
- **More context** on every flame or negative line: everything anyone said
  from 45 s before to 20 s after, with the line itself in bold.
- **Between games** (dashboard): what each person said outside the
  recorded games (lobby, draft, reviews between games): talking time,
  words, and positive, flame, negative, accountability and shotcall lines.
  - Nothing said between games counts toward any in-game stat. This was
    already true for the stats; the flame list mixed them, and now has a
    **When** filter (in games / between / both).
- **Negative talk per 10 min** (Attitude).

### Changed

- **"Negative" now has a high bar**, as asked.
  - New `Negative:` phrase list, defeatist or complaining only: "we're so
    fucked", "we're going to lose", "it's so over", "we threw", "ff", "this
    game sucks", "I give up", plus Chinese (输定了, 没救了, 投了…).
  - Plain swearing and exclamations ("oh fuck", "卧槽") are **Frustration**,
    which is no longer shown or scored anywhere. The old "other negative"
    showed 168 such lines from one scrim; now there's 1.
  - Phrases that looked defeatist but usually weren't were left out after
    testing on the real scrim: "I'm done" (as in finished), "it's over" ("if
    I get one kill on this guy, it's over"), "giving up" ("giving up
    positioning").
- **Three buttons per line: Flame / Negative / Neither** (were Flame / Not
  flame).
  - Lines already marked "Not flame" now count as **Neither**.
  - "Neither" lines can be listed again (Show: lines you marked
    "neither"), to undo.

### Verified

- **Real scrim copy:**
  - results Lose / Win / Lose, which match the nexus towers
  - 30 champion icons
  - 1 negative line
  - flame/negative lines carry 14–28 lines of context
  - between games: 89 minutes, per person
- **Dashboard in the app page (browser pane, stand-in backend):**
  - Champions with icons, Our picks / Played against
  - More context, with the quoted line highlighted
  - Negative saved with the right line ID
  - When = between games
  - no console errors

---

## [2.4.2]: 2026-10-08: Lato, sharper text, and Flame / Not flame buttons

Asked for: every font changed to Lato, things made less blurry, and a way to
mark a line as "not flame" or "yes, flame".

### Added

- **Flame / Not flame buttons** on every line in the dashboard's Flame and
  negative comments section (in the app; a dashboard opened in a browser
  only shows the decisions).
  - **Not flame:** the line stops counting as flame in every stat. It stays
    in the list under "Other negative", marked "✓ checked by you".
  - **Flame:** turns any negative line into flame, including ones the
    phrase lists missed.
  - **Click the pressed button again to undo** (back to the automatic call).
  - Decisions are saved in `_data/flame_reviews.json`, keyed by session,
    time and speaker, so they survive rebuilding the dashboard and changes
    to the phrase lists.
  - The list updates straight away. The numbers update on **Refresh**.

### Changed

- **Every font is now Lato**: the app window, the dashboard, the activity
  log and the settings editor.
  - Lato is shipped with the app (`ui/fonts`, regular and bold, Latin and
    Latin Extended), so it works offline.
  - The dashboard embeds it, so `Dashboard.html` looks the same opened
    anywhere.
  - Chinese text falls back to Microsoft YaHei, since Lato has no Chinese
    characters.
- **Sharper text and lines:**
  - **Text:** Windows only uses its sharper ClearType smoothing for text on a
    solid background. The app's scrolling areas (the main page, the
    transcript list, tables) had see-through backgrounds, so their text got
    the softer grayscale smoothing. They now all have solid backgrounds.
  - **Chart lines:** the chart's grid lines and day separators were drawn
    between pixels, which smears a 1-pixel line across 2. They now sit
    exactly on whole pixels.
  - **Size:** the base text size is 15 px (was 14).
  - **Checked first:** the display is at 100% scaling, so Windows wasn't
    stretching the window, and that wasn't the cause.

### Verified

- **App page in the browser pane, with a stand-in backend:**
  - Lato 400 and 700 load in the window and inside the dashboard.
  - Not flame → shown as Other negative ✓, with the saved note.
  - Clicking again → undone.
  - Flame on an "other negative" line → becomes Flame.
  - The 3 calls reached the backend with the right line IDs.
- **Stats:**
  - Marking one in-game flame line "not flame" took the flame count from 3
    to 2.
  - Undoing both decisions restored 3 and left the file empty.

---

## [2.4.1]: 2026-10-08: The trend chart goes game by game

Asked for: rather than one point per day, one point per game, with the day
shown on a second row under it.

### Changed

- **The trend chart now has one point per game**, by default (Group by:
  **Game**). Session, week and month are still there.
  - Games are evenly spaced, so a week off doesn't leave a gap and every game
    gets the same room.
  - Two rows of labels:
    - each game's number within its day (G1, G2, G3…)
    - the date underneath, centred under that day's games
  - A faint dashed line separates the days.
  - With many games (more than about 45 across the chart), the game numbers
    and day lines are left out, and only dates that fit are shown. That keeps
    a whole season readable.
  - The tooltip and the table view read "Oct 7, 2026, game 2".
- The Flame and negative comments table's columns line up with their headings.

### Verified

- **Real scrim, plus copies of it on two made-up later days (9 games):**
  - labels G1 G2 G3 · G1 G2 · G1 G2 G3 G4
  - dates Oct 7, Oct 9, Oct 14
  - dashed lines between the days
- **120 made-up games over 80 days:** no game numbers, 14 dates without
  overlap.

---

## [2.4.0]: 2026-10-08: Rosters, game phases, vision, resources, flame

Asked for after reviewing the first real scrim. The request was:

- Rename the repository to ScrimStats.
- Find out why an item call before a dragon in game 2 didn't count. The guess
  was that the player said "LDR", or said it two minutes early and then asked
  for gold.
- New stats: asking for resources, wards placed, ward talk, and flame at
  teammates.
- Accountability per play, not per 10 minutes.
- Every stat split into laning phase, mid game, and late game.
- A JV roster next to the varsity one, with a Rosters tab.

### Why the item call didn't count

The transcript has the call, about two minutes before the dragon. Over half
a minute, the player:

- said to play for the next drake and that they needed all the gold they
  could get
- asked for the gold
- said they needed "LTR". This is "LDR" (Lord Dominik's Regards), misheard.

Two things stopped it counting:

1. **The game recording has no dragons at all.** League's live data feed
   doesn't tell spectators about dragons, barons or heralds. Across the
   whole scrim (3 games, all spectated) there are 0 `DragonKill` events,
   0 `BaronKill` and 0 `HeraldKill`, and only 2 `HordeKill` (grubs). Games
   played on this PC have them (2–4 dragons per game). With no objectives in
   the data, "item timers before objectives" could only ever be 0 or blank
   for spectated games.
2. **The words didn't match.** "LTR" wasn't recognised as an item, and "I need
   … gold" with the "I" five words away fell outside the "about yourself"
   rule.

### Added

- **The GitHub repository is now `ScrimStats`** (was `lol-scrim-comms`; old
  links redirect).
- **A player's recording can be joined with a spectator's.** One of the five
  players runs ScrimStats and clicks Start recording. Afterwards their files
  go into the spectator's app with **Games → Add a player's recordings…**.
  They're joined automatically (same players and champions, as with rewind
  pieces).
  - The game then has the dragons and barons from the player's feed.
  - The player's feed is live, so that game needs no spectator delay. Its
    timeline comes only from the player's file.
  - The Games tab shows it as "Spectator + player", with an Objectives count
    ("not shown" for spectator-only games).
- **Rosters (Varsity, JV…).** The Roster tab is now **Rosters**, with one tab
  per roster: add, rename, delete.
  - Each player has a **Role** (Top, Jungle, Mid, Bot, Support).
  - A sub can be on two rosters under the same name. Their accounts and role
    stay in step on both.
  - `Roster.txt` now has `[Roster name]` lines and a 4th column, Role. Older
    files still load: their players form one roster.
  - Each game counts for the roster most of its players are on.
  - The dashboard has a **Roster** picker, and colors, cards, chart lines and
    tables follow the chosen roster.
- **Early / mid / late game.** Every stat can be seen for the whole game or
  one part of it (dashboard: **Part of game**; CSV: a `part_of_game` column
  with `all`, `early`, `mid`, `late` rows).
  - **Early (laning)** lasts, per player, until the first outer tower in
    their lane falls (either team's), and at most until 20:00. Junglers (role
    Jungle, or Smite in newer recordings): the first outer tower anywhere.
    No role: bot lane, as suggested.
  - **Mid** runs until 30:00, or until the first inhibitor falls if that's
    sooner.
  - **Late** is the rest.
  - Real scrim: the bot lane's first tower fell at 14.8, 16.4 and 17.9 min;
    top's at 19.8, 19.4 and 13.4.
- **Asking for resources** (new type `Resources`): "I need gold", "can I get
  the wave", "give me the camp", "every bit of gold", plus Chinese (我要钱,
  经济给我…). Real scrim: 3 lines, all of them the gold requests above.
- **Vision**, a new dashboard group:
  - Three kinds of ward talk:
    - **Warding:** placing wards and where they are, ours or theirs.
    - **Asking for vision:** "no vision", "can someone ward", "buy pinks".
    - **Sweeping:** "sweep", "deward", "kill the ward".
  - **Vision talk** counts any of them, once per line. A line that's a
    request or a sweep isn't also counted as warding.
  - **Vision score per 10 min:** League's own scoreboard number. The live
    feed has no "wards placed" count, so this is the closest. The recorder
    now saves everyone's scores every 30 s (level, K/D/A, CS, vision score,
    item IDs) plus summoner spells, so the stats can see how much vision each
    player added in each part of the game. Only games recorded with 2.4 or
    newer have it.
- **Flame and negative comments**, a new dashboard section (asked for midway
  through this release: flame should always be quoted directly, for
  accountability).
  - Every line counted as flame, **word for word**, with the date and time,
    the game, the game clock and part of the game, and who said it.
  - **Other negative** adds swearing and frustration that wasn't aimed at
    anyone. It's shown, but it doesn't count against them.
  - It follows the roster, time range and wins/losses filters, and has its
    own player filter. Chinese lines show their translation.
  - Lines said between games are included, marked "between games".
  - The quotes stay in the local dashboard. Nothing is uploaded or committed.
  - Real scrim: 4 flame lines, 168 other negative lines.
- **Item nicknames:** about 80 more (lord doms, BT, RFC, mercs, tabis,
  steraks, youmuus…). Item nicknames moved up in League words, so they
  always fit in the speech model's hints.
- **Corrections:** `ltr => LDR`, and "Lord Dominic's" spellings.

### Changed

- **Flame replaces "frustration at teammates".** The old rule counted any
  swear word with "you" anywhere in the line. In the real scrim that was 29
  lines, almost none of them flame: an excited swear with "you" later in the
  sentence, a "how do you" question about Discord settings, and someone
  saying they're "not stupid" to a teammate.
  - **Flame** now needs a blaming or insulting phrase ("what are you doing",
    "why did you", "useless", "stop inting", "你在干嘛"…) with "you" or a
    teammate's name within 5 words (6 characters of 你 in Chinese).
  - Swearing on its own is **Frustration**, which isn't scored.
  - Real scrim: 3 lines, all mild "why are you…" questions.
  - Positivity and blame after death use flame.
  - An edited `Callout types.txt` without a `Flame:` line uses its
    Frustration phrases with the new 5-word rule.
- **Accountability is per 10 plays.** A play is any fight with a kill in it
  (kills less than 15 s apart are one fight) or an objective taken. It needs
  at least 5 plays.
- **Item or gold talk before objectives** (was "item timers before
  objectives"):
  - It counts item talk or a resource request.
  - The window is 2½ minutes before the objective (was 90 s), since the real
    call was about two minutes early.
- **Corrections now apply to the stats immediately**, including for older
  transcripts. The transcript text itself only changes when re-transcribed.
- **Game length is the real game.** A game now runs from game clock 0 to the
  furthest moment seen, in real time. Before, it ran from when recording
  started to when the last file closed. A spectator who keeps rewinding after
  the end had stretched the scrim's 3 games to 127 minutes; they're now 82.
- **Repeated events are found with a 3-second tolerance.** A rewind replays
  an event with a new ID, and its time can differ by hundredths of a second
  (a tower at 29.16 and again at 29.18), which got past the old exact-time
  check. A multikill's size is part of what makes it unique, so a double kill
  and the triple kill right after aren't merged. The recorder and the stats
  share this check, in `common.py`.
- **Missing roles:** the dashboard warns about players with an account but no
  role.

### Decisions

- **Tower lane numbers.** The game now names towers like
  `Turret_TOrder_L0_P3`. P3 is the outer tower, and the two nexus towers are
  L1 (mid). Which of L0 and L2 is top wasn't documented anywhere we could
  find. It was worked out from the scrim: Garen, Jayce and Aatrox took the L2
  towers and Ashe got first tower on L0, so L2 is top and L0 is bot. The
  older `Turret_T1_L/C/R_03` names are understood too.
- **Vision score, not wards placed.** The live feed has no ward count, and the
  post-game stats that do aren't available to a spectator.
- **The flame list is deliberately narrow.** A missed flame line costs less
  than calling a teammate toxic for "holy shit, you're alive".

### Verified

- **Real scrim (2026-10-07, copy of the data):**
  - 3 games found, 82 minutes in all, with 0 duplicate towers.
  - Laning phases: 52 min early, 27 min mid, 3 min late (short games).
  - The missed call now counts: the gold request and "I need LTR" count as
    item talk, and three lines count as resources. It still can't
    count toward objectives, because the dragons aren't in the spectator data.
- **Rosters tab, in the browser with a stand-in backend:**
  - add a roster
  - add a sub (accounts and role copied)
  - rename, then change the role (follows on both rosters)
  - save (correct `[Roster]` file), delete
- **Dashboard with Varsity and JV:**
  - roster and part-of-game pickers
  - accountability per play
  - main shotcallers per game across phase rows (1.3)
  - no console errors
- **Recorder dry run:** the `scores` line is written correctly. "#" players use
  their summoner name.
- **Settings:** unedited 2.3 settings files upgrade, via the new
  `OLD_DEFAULTS` hash.

### Known limitations

- **Spectator-only games** still have no dragons or barons, unless a player
  records too.
- **Vision score** starts with games recorded from now on.
- **Roles** have to be set by hand. Custom games report every player's
  position as "NONE"; only junglers are spotted, by Smite.
- **Late game** is short in most scrims, so its numbers will be noisy until
  there's more data.

---

## [2.3.1]: 2026-10-08: Renamed to ScrimStats

### Changed

- **The app is now called ScrimStats:**
  - **`ScrimStats.exe`** (was `LoL Scrim Comms.exe`)
  - the window title and sidebar
  - the app folder (`ScrimStats`, was `LoL Scrim Comms`), with all data moved
    over unchanged
  - the release download (`ScrimStats-<version>-windows.zip`)
- **The GitHub repository keeps its name** (`lol-scrim-comms`), so existing
  links keep working.

---

## [2.3.0]: 2026-10-08: Everything in one app window

Asked for after looking at the first real dashboard: everything should be one
app, with no Notepad or separate browser tab. The dashboard had also looked
broken, for two reasons: the roster had been typed with display names instead
of Discord usernames, and the trend chart grouped one evening of data into a
single "month" dot.

### Added

- **One window with a sidebar:** Home, Dashboard, Transcripts, Roster, Games,
  Settings. It's built with pywebview, which shows the app's pages using the
  WebView2 browser engine already in Windows.
  - **Home:** record games and transcribe comms (as before), with the Activity
    log.
  - **Dashboard:** the stats, right in the app, with a Refresh button.
  - **Transcripts:** pick a session, read who said what, search it, and filter
    to one speaker. Chinese lines show their translation.
  - **Roster:** players are built by **picking from lists of the names
    actually found in your recordings**: Discord names, with how much each
    person spoke, and Riot IDs, with games played and champions to help
    recognise them. Names that aren't found in any recording are outlined, so
    typos stand out.
  - **Games:** every recorded game, merged pieces included, with spectated
    games marked and a **per-game spectator delay** (None, 3 min, or a custom
    number of seconds).
  - **Settings:** the four word lists, edited in the app, plus buttons to open
    the app's folders.
- **A hidden-window self-check:** `LoL Scrim Comms.exe --ui-test` opens the
  real window **hidden**, checks the page talks to the app and that every tab
  loads, then closes. Results go to `_data\ui-test.log`.

### Changed

- **Per-game spectator delays.** The delay is set per game in the Games tab
  and saved in `_data\game_delays.json`. Game 1 of 7 Oct, which was spectated
  late, is set to the usual 3 minutes.
- **The dashboard groups by session** until there are at least 3 months of
  data. Grouping by month would otherwise show one dot.
- **Messages point at the app's tabs**, not at `Roster.txt` and Notepad.
  Unedited settings files from 2.1–2.2 upgrade automatically to the new
  wording.
- **`How to use.txt`** is rewritten for the one-window app.

### Fixed (during development)

- **The app took about 20 seconds to open.** pywebview looks through every
  public attribute of the object the page talks to, and that object held a
  reference to the whole window. Internal attributes are now private, and the
  app is ready in about 1 second.
- **The status updates could stop for good.** If the first request went out
  while the window was still starting, it went unanswered and the loop never
  asked again. Requests now time out after 4 seconds, and the next one always
  goes out.
- **Testing popped windows onto the screen** while the PC was in use (a
  fullscreen game was running). Visual checks moved to a browser preview with
  a copy of the data, and the packaged app is checked with the hidden-window
  test.

### Investigated: measuring the spectator delay from the comms

People react out loud within seconds of a kill, so a delayed game should show
reactions *before* the recorded kills. Scoring candidate delays from 0 to 300
seconds:
- **Games 2 and 3** (watched live) peaked at 0–6 seconds.
- **Game 1** (watched late) gave inconsistent peaks between 95 and 219
  seconds, because there were too few kills (32) to trust.

So the delay stays a manual, per-game setting.

### Verified

- **Packaged `.exe`:**
  - Self-test passed on the graphics card.
  - The hidden-window test passed on the real app folder: version shown, 8
    voices and 15 games listed, 1 transcript, 4 settings files, and the
    dashboard built.
- **Page content, on a copy of the real data:**
  - Roster pickers showed the existing choices.
  - Games showed the 3 spectated games merged from 7/31/24 pieces.
  - Transcript search worked.
  - The dashboard defaulted to grouping by session.

---

## [2.2.0]: 2026-10-08: Transcribing on the graphics card, and fixing spectated games

The first real scrim (8 speakers, 2.8 hours) went through the app. Two
problems surfaced:
- **Transcription on the processor took about 20 minutes per speaker,** so
  over 2½ hours for the scrim.
- **The recorder had split each spectated game into dozens of files,** with
  duplicate events.

Both are fixed. Transcription now runs on the graphics card, about **11×
faster**.

### Added

- **Graphics-card transcription:** whisper.cpp built with **Vulkan**, which
  works with AMD, NVIDIA and Intel cards, using the same Whisper "small"
  model.
  - The app uses the graphics card automatically, and falls back to the
    processor if the card or the engine isn't available.
  - On the test PC (AMD Radeon RX 7900 GRE), a 2.8-hour speaker track takes
    **about 2 minutes instead of 20**. An hour of real comms audio takes about
    53 seconds.
- **Each stretch of speech is transcribed on its own.** The speech detector
  finds where people talk, and stretches less than a second apart are kept
  together as one utterance (real audio, nothing spliced).
  - Every line's start comes from the detector, so a word can't drift onto a
    neighbouring line.
  - English or Chinese is still judged on larger chunks, since short clips
    are hard to judge, and it leans English unless Chinese is clearly more
    likely.
- **Uses the "no speech" probability for each segment,** which whisper.cpp
  computes but the bridge didn't pass on. The bridge is patched to expose it,
  so invented "Thank you." lines over background noise are dropped.
- **Non-speech labels are dropped:** "[BLANK_AUDIO]", "[inaudible]", "(M)",
  "（音乐）". The engine is also told to suppress them.
- **Repetition junk is dropped:** one character or word repeated many times
  ("Arcary,,,,,,,,,,,,,,", from the first real transcript) and broken
  characters ("�").
- **`gpu-engine/`** has the build steps (`BUILDING-GPU.md`) and the patch
  applied to the pywhispercpp bridge, so the engine can be rebuilt.
- **Spectated games are recognised.** The recorder notes when you're
  spectating (there's no "active player"). Older files are recognised by the
  game clock going backwards.

### Changed

- **The recorder only starts a new file when the players change.** It used to
  treat any backwards clock jump as a new game, but a spectator's clock jumps
  back on every rewind. Last night that split three games into 7, 31 and 24
  files.
- **The recorder skips replayed events.** A rewind makes the game replay
  events with new IDs, so events are now also matched by type, game time and
  who was involved.
- **The stats merge pieces of the same game:** files with the same 10
  players, less than 20 minutes apart. Repeated events are dropped. Last
  night's 76 files became 15 games, and game 2's 156 logged events became
  101 real ones.
- **Event times use the live edge.** A viewer can only be behind the live
  game, never ahead, so each moment of game time is placed at the earliest
  real time it was seen. That works through rewinds and replays (ignored) and
  game pauses (handled). It also uses the time stamps on the events
  themselves, not just the 10-second clock records.
- **English stretches get only the English hints.** With the Chinese hint
  words included, the graphics-card engine put Chinese punctuation into
  English ("I don﹑t know how good Janna，s with Ashe"). English lines with
  Chinese punctuation went from several to 0.
- **The dashboard warns about spectated games.** If custom-lobby spectators
  see the game late, every event in those games is late by that delay. The
  delay is still unconfirmed.

### Fixed (during development)

- **Garbled Chinese characters.** The bridge converted each token to text
  separately, so a Chinese character split across two tokens came out as
  "�". The bridge now hands back raw bytes, and characters are joined before
  decoding.
- **Joining speech with silences between pieces moved boundary words.** The
  first design glued speech pieces together with short silences, and words
  near the joins landed on the wrong side ("Oh," ended the previous line).
  Scored against the processor's line starts, it matched only 47–74% within a
  second, depending on the silence length. Transcribing each utterance on its
  own matched **95%**.
- **"Precise" (DTW) word timing was switched off without notice.** It
  conflicts with flash attention, so it was being disabled. Tested both ways,
  DTW was 20% slower and no more accurate, since line starts come from the
  speech detector, so flash attention stays.

### Verified

All on one speaker's 2.8-hour track from the real scrim, compared with the
processor result:

- **Speed:** a full track in 1 min 50 s on the graphics card, against about
  20 min on the processor (11×). An hour of audio took 53 s.
- **Timing:** 17–18 of 19 processor lines in the first hour had a
  graphics-card line starting within 1 second.
- **Completeness:** 405 lines against 137. The extra lines are mostly real
  short callouts the processor path dropped ("Oh, I have to lock in.", "I feel
  like if I leave lane, they're just going to kill you.").
- **Beam search vs. greedy:** greedy was 30% faster, but differed on about
  half of the noisy short lines, so the more accurate beam search stays.
- **Packaged `.exe`:** the self-test ran on the graphics card ("using Vulkan0
  backend") and transcribed the bilingual test recording, 9 of 11 lines in
  Chinese and all translated, in seconds.
- **Merging:** 76 game files became 15 games, and last night's three
  spectated games were each recognised as spectated.

### Known limitations

- **The spectator delay is unconfirmed.** For spectated games, if custom-lobby
  spectators get one, events will be late by that much. The clock test
  settles it.
- **Live-edge timing assumes you were watching live at some point** after
  each moment that matters. A stretch watched only on rewind gets the time of
  the next moment you were back at live.
- **The graphics-card engine needs a Vulkan-capable graphics driver.**
  Without one, the app uses the processor.
- **The engine is built from source** (see `gpu-engine/BUILDING-GPU.md`).
  Building the `.exe` without it gives a processor-only app.

---

## [2.1.0]: 2026-10-05: Chinese (Mandarin) comms

Some teammates sometimes talk in Chinese. Before this version, the
English-only speech model turned Chinese speech into made-up English or
dropped it. Now English and Mandarin are both understood, Chinese lines are
translated, and the stats read Chinese directly.

### Added

- **Bilingual transcription.** The model now decides, for each stretch of
  speech, whether it's English or Chinese, and writes it in that language.
  It handles mixed sentences too ("Kai'Sa 没有 flash 了").
  - It may only choose between English and Chinese. Left alone, it would
    consider all 99 languages it knows, and could mistake a short English
    callout for, say, Welsh.
  - Each line is labeled `language: "en"` or `"zh"` in the transcript file.
- **English translations of Chinese lines,** made on this PC by the same
  model, with nothing uploaded.
  - In the `.txt` transcript, Chinese lines are marked `(中文)` and followed
    by `→ translation`. The `.jsonl` has `text_en` on every line.
  - Translations are given a short League glossary (drake, baron, jungler,
    flash, my bad…) plus the night's champions.
- **Chinese in the stats.** Lines with Chinese are sorted with Chinese
  phrases matched against the **original wording**, so the stats don't depend
  on the translation being right. The English translation is checked too, and
  a type counts if either finds it (still at most once per line). Examples:
  - 我的锅 / 我的错 → accountability
  - 你在干嘛 → frustration at a teammate
  - 卧槽我好菜 → frustration at self (not scored)
  - 对面打野不见了 → enemy info
  - 我还差三百块出中娅 → item timer
  - 我们打大龙 → shotcall
- **"Who is it about" in Chinese:** 我 = yourself (but not 我们, "we"),
  你 / 你们 = a teammate, and 他 / 她 / 对面 / a champion name = the enemy.
  "My status" and "Item timers" need 我 within 6 characters.
- **Riot's official Chinese names** for all 173 champions and 276 items,
  downloaded alongside the English ones. Players say the short name
  (卡莎 for Kai'Sa), but some epithets are used as nicknames (盲僧 for Lee
  Sin), so both are kept.
- **Chinese hints for the speech model:** Chinese League terms (小龙, 大龙,
  打野, 闪现, 开团, 我的锅…) and the night's champions in Chinese. English and
  Chinese hints have **separate budgets** (135 and 65 tokens), so neither can
  crowd the other out.
- **New stat: Chinese share of talk** (Talking group). It shows how much of
  each player's talking is in Chinese, which matters if some teammates don't
  understand it.
- **Chinese phrase lists** in every callout type, Chinese League terms in
  `League words.txt`, and translation fixes in `Corrections.txt`.
- **Chinese fixes in `Corrections.txt`** ("打也 => 打野") are applied as
  plain find-and-replace, since Chinese has no spaces between words.
- **Filters for invented Chinese phrases:** subtitle credits and "like and
  subscribe" lines (字幕, 订阅, 点赞, 谢谢观看…) that the model sometimes
  "hears" in silence are dropped, like their English equivalents.
- **Settings files upgrade safely.** A settings file that still exactly
  matches an older version's default (nobody edited it) is replaced by the
  new default, so the Chinese phrases reach existing installs. **An edited
  file is never touched.** Your four settings files were unedited 2.0.1
  defaults and have been upgraded.

### Changed

- **The speech model is now `small`** (bilingual) instead of `small.en`
  (English-only). The 464 MB English-only model was removed from `_data` and
  the bilingual one put in its place, so there's still no download.
- **Speed:** nonstop English now runs at 0.14× real time (it was 0.10×,
  because of the language checking). Nonstop Chinese runs at 0.30× (see
  Fixed). The estimate for a 3-hour block is now **30–60 minutes**, longer
  with a lot of Chinese.
- **Words per minute counts Chinese fairly.** Words used to be counted by
  splitting on spaces, which made a whole Chinese sentence count as one word
  and would have made Chinese speakers look quiet. Chinese is now counted at
  the usual ~1.5 characters per word.
- **Callout phrase lists** also accept Chinese commas (，、) as separators.
- **English lines heard in a mostly-Chinese stretch** have their Chinese
  punctuation changed back to English punctuation ("…for this drake，" →
  "…for this drake,").
- **Saved name lists now have a format number**, so older saved copies are
  re-downloaded automatically when the layout changes.

### Fixed (during development)

- **Translation was the bottleneck: 1.5 seconds per line.** The model always
  works on 30-second chunks, so translating one short line at a time wasted
  most of each chunk. Several Chinese lines are now packed into one chunk with
  1.5-second silences between them and translated once. Each translated piece
  goes back to its line by timing. Chinese went from 0.60× to **0.30×** real
  time, and every test line still got its own translation.
- **Random garbage translations.** When unsure, the model retries with some
  randomness, which once turned 我的锅 ("my bad") into "My barradish
  barradish". Translation now uses fixed settings, so the same audio always
  gives the same result.
- **Echoed hints.** With fixed settings and the full 135-token hint list, the
  model sometimes "translated" by reading the hint list back ("Lee Sin, Lee,
  K'Sante, Kai'Sa, Ahri, top, jungle…"). Translation now gets a short
  glossary instead. Any piece that still looks like the hint list is thrown
  out, and that line is re-translated on its own without hints.
- **Riot's Chinese data swaps "name" and "title".** The first version stored
  Kai'Sa as 虚空之女 ("Daughter of the Void") instead of 卡莎. Both forms
  are now kept, with the short name first.
- **Mixed-language enemy info was missed.** "卡莎没有Flash了" wasn't counted:
  the Chinese list lacked "没有flash" and the English list lacked "doesn't
  have flash". Both were added, and Chinese matching now ignores capitals
  ("Flash" = "flash"). "去上路" ("went top") was added alongside "在上路"
  ("is top").

### Verified

- **Choosing the model.** 11 test clips of Mandarin callouts, mixed sentences
  and English, made with Microsoft's neural text-to-speech, plus the 6 earlier
  English clips:
  - **Language detection:** 17 of 17 correct, every time with 98%+
    confidence, with both models.
  - **small, no hints:** English unchanged. Chinese came out in Traditional
    characters with League-term errors (打野 → 打也, 无尽之刃 → 無盡職任),
    and translations were weak ("My pot, my pot", "Xiaolong" for drake).
  - **medium:** better Chinese and translations, but **3× slower**.
  - **small with hints:** Simplified characters, 打野 / 闪现 / 无尽之刃 right,
    and usable translations ("I don't have flash", "The enemy jungle is gone,
    watch out for the bot lane"). That's close to medium at a third of the
    time, so it was chosen.
- **End to end:** a fake two-person Craig recording mixing Mandarin, English
  and mixed sentences, run through transcription and the stats:
  - **Language:** all 11 lines labeled correctly.
  - **Timing:** Chinese lines within **0.16 s** of when they were said, and
    within 0.54 s for all lines.
  - **Stats:** all 11 sorted into the intended types, even the 2 lines where
    an item name was misheard ("能出" / "三百块" still marked them as item
    timers). Chinese share was computed (77% and 82%).
- **Repeatability:** two full runs gave identical translations, with no
  echoed hints.
- **Settings upgrade:** unedited old defaults were upgraded, and a file with
  an edit was left untouched.
- **Older data still works:** the fake year (45 sessions, 131 games) still
  builds correctly.
- **Packaged `.exe` self-test:** recorder, bilingual transcription (9 of 11
  lines in Chinese, all translated), Riot's Chinese names and the dashboard
  all ran inside the `.exe`, and it passed.

### Known limitations

- **Translations are rough,** especially for gaming slang. Use them to get
  the gist. When a term keeps coming out wrong, add a line to
  `Corrections.txt`, e.g. `my pot => my bad`.
- **Some item names in Chinese speech** can still be misheard (无尽之刃 →
  无尽职任 in testing). The surrounding words usually still mark the line as
  an item timer.
- **Language is decided per stretch of speech, up to 30 seconds,** not per
  sentence. Someone switching language mid-stretch may have part of it
  written in the other language. Mixed sentences are fine.
- **Cantonese isn't supported.** These models handle it poorly; it would
  need a much bigger, slower model.
- **Tested with synthetic voices only.** Real Mandarin comms (accents,
  crosstalk, slang) haven't been tried yet.

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
