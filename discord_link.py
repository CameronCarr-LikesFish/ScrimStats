"""
Getting a teammate's game recordings to the person running ScrimStats,
through a private Discord channel.

  Sending (the teammate's ScrimStats Recorder): when a game ends, its file
  is posted to the channel through a webhook (a link that lets a program
  post to one channel, and nothing else).

  Receiving (ScrimStats): a Discord bot that can read that channel looks
  for new game files and copies them into Game recordings, where they're
  joined with the spectated games automatically.

The webhook link and the bot token are kept in _data/discord.json on this
PC only. Neither is ever put in the code or the repository.
"""

import json
import re
import time

import requests

API = "https://discord.com/api/v10"
WEBHOOK = re.compile(r"^https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$")
CHANNEL_LINK = re.compile(r"discord(?:app)?\.com/channels/(\d+|@me)/(\d+)")
GAME_FILE = re.compile(r"^game_[\w-]+\.jsonl$")


def valid_webhook(url):
    return bool(WEBHOOK.match((url or "").strip()))


# ---------------------------------------------------------------------------
# Sending (used by the recorder)
# ---------------------------------------------------------------------------

def scrim_check(path, roster_ids=()):
    """Should this game be sent? Returns (yes/no, reason).
    1. It must be a custom game on Summoner's Rift. The recorder asks the
       League client (custom_game in the file). If the client couldn't be
       asked, any 10-player Summoner's Rift game passes this step.
    2. At least 3 of the roster's accounts must be in it: room for subs,
       but a duo's game isn't sent."""
    players, events = None, 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if players is None and '"type": "players"' in line:
                    players = json.loads(line)
                elif '"type": "event"' in line:
                    events += 1
    except (OSError, ValueError):
        return False, "couldn't read it"
    if not players or not events:
        return False, "no game in it"
    entries = players.get("players") or []
    mode = players.get("game_mode")
    if mode not in (None, "CLASSIC") or players.get("map") not in (None, 11) or len(entries) != 10:
        return False, "not a Summoner's Rift game"
    if players.get("custom_game") is False:
        return False, "not a custom game"
    wanted = {str(r).strip().lower() for r in roster_ids if str(r).strip()}
    if wanted:
        def ours(p):
            for key in (p.get("riotId") or "", p.get("summonerName") or ""):
                if key.lower() in wanted or key.split("#")[0].strip().lower() in wanted:
                    return True
            return False
        count = sum(1 for p in entries if ours(p))
        if count < 3:
            return False, f"only {count} of your roster in it (needs 3)"
    return True, "a scrim"


def post_game(webhook, path, sender):
    """Post one game file to the channel. Raises on failure."""
    events = sum(1 for line in open(path, encoding="utf-8") if '"type": "event"' in line)
    payload = {"username": "ScrimStats Recorder",
               "content": f"Game recording from **{sender}**: `{path.name}` ({events} events)",
               "allowed_mentions": {"parse": []}}
    with open(path, "rb") as f:
        r = requests.post(webhook.strip() + "?wait=true", timeout=30,
                          data={"payload_json": json.dumps(payload)},
                          files={"files[0]": (path.name, f, "application/json")})
    if r.status_code == 429:                       # slow down, then try once more
        time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
        return post_game(webhook, path, sender)
    r.raise_for_status()


# ---------------------------------------------------------------------------
# Receiving (used by ScrimStats)
# ---------------------------------------------------------------------------

def load_settings(paths):
    try:
        return json.loads((paths.data / "discord.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(paths, **changes):
    settings = load_settings(paths)
    settings.update({k: v for k, v in changes.items() if v is not None})
    (paths.data / "discord.json").write_text(json.dumps(settings, indent=1), encoding="utf-8")
    return settings


def channel_id(link_or_id):
    text = str(link_or_id or "").strip()
    m = CHANNEL_LINK.search(text)
    return m.group(2) if m else (text if text.isdigit() else None)


def pull_games(paths, log=print, max_messages=500):
    """Copy new game files posted in the channel into Game recordings.
    Returns how many were added. Does nothing if no bot is set up."""
    settings = load_settings(paths)
    token, channel = (settings.get("bot_token") or "").strip(), channel_id(settings.get("channel"))
    if not token or not channel:
        return 0
    headers = {"Authorization": f"Bot {token}", "User-Agent": "ScrimStats (github.com/CameronCarr-LikesFish/ScrimStats)"}
    seen_path = paths.data / "discord_seen.json"
    try:
        seen = set(json.loads(seen_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seen = set()
    added, before, read = 0, None, 0
    newest_first = []
    while read < max_messages:
        params = {"limit": 100, **({"before": before} if before else {})}
        r = requests.get(f"{API}/channels/{channel}/messages", headers=headers, params=params, timeout=20)
        if r.status_code == 401:
            raise RuntimeError("Discord didn't accept the bot token. Copy it again from the developer portal.")
        if r.status_code == 403:
            raise RuntimeError("The bot can't read that channel. Give it View Channel and Read Message History there.")
        if r.status_code == 404:
            raise RuntimeError("Discord can't find that channel. Copy the channel's link again.")
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        newest_first += batch
        read += len(batch)
        # Stop paging once a whole batch was already handled before.
        if all(a["id"] in seen for m in batch for a in m.get("attachments", [])) and any(
                m.get("attachments") for m in batch):
            break
        before = batch[-1]["id"]
        if len(batch) < 100:
            break
    # Without "Message Content Intent", Discord hides files (and text) from
    # the bot: webhook posts arrive empty.
    no_attachments = all(not m.get("attachments") for m in newest_first) and any(
        m.get("webhook_id") for m in newest_first)
    if no_attachments:
        raise RuntimeError("The bot can see the messages but not their files: turn on "
                           "\"Message Content Intent\" for the bot in Discord's developer portal.")
    paths.games.mkdir(parents=True, exist_ok=True)
    for message in reversed(newest_first):                       # oldest first
        for a in message.get("attachments", []):
            if a["id"] in seen or not GAME_FILE.match(a.get("filename", "")):
                continue
            data = requests.get(a["url"], timeout=30).content
            target = paths.games / a["filename"]
            if target.exists() and target.read_bytes() == data:
                seen.add(a["id"])
                continue
            who = re.sub(r"[^\w-]", "", (message.get("author") or {}).get("username", "player"))[:20] or "player"
            n = 1
            while target.exists():
                target = paths.games / f"{a['filename'][:-6]}_from_{who}{'' if n == 1 else n}.jsonl"
                n += 1
            target.write_bytes(data)
            seen.add(a["id"])
            added += 1
    seen_path.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    save_settings(paths, last_checked=time.strftime("%Y-%m-%d %H:%M"), last_added=added)
    if added:
        log(f"Discord: added {added} game recording(s) from your teammates.")
    return added
