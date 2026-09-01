"""
Competitor coverage scanner — DAILY.

For each competitor game (SullyGnome), find channels that streamed it in the last
day with peak concurrent viewers >= THRESHOLD and followers >= MIN_FOLL, skipping
Russian-language channels (EXCLUDE_LANGS), enrich each with contact email + social
links (Twitch GraphQL panels/socials), DEDUP against the whole MasterCRM AND the outreach book
(every tab — skip anyone already a contact anywhere), and append the new ones to the
"Competitor Coverage" tab. Channels WITHOUT a profile email are never added.

Fully autonomous: service-account auth (env GCP_SA_KEY in CI, or local key file).
"""
from __future__ import annotations

import glob
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

from urllib.parse import quote

import requests
import gspread
from google.oauth2.service_account import Credentials

# ---- config ----------------------------------------------------------------
SHEET_ID = "11x1FDXRGDZIKuyakmEjt2C5LrXC1-42K9eDdXkyTKuQ"      # MasterCRM
# Outreach book. Dedup MUST cover it too: contacts live there that never reach
# MasterCRM (DS invitees, journalists, UA lists...). Without it the scanner keeps
# re-adding them to Competitor Coverage as "new" every run.
EA_SHEET_ID = "1Vc3neddP-H0ANxKk96cDNm8HoIPz03fA6hilX3CXuxY"
TAB = "Competitor Coverage"
THRESHOLD = int(os.environ.get("LP_COMP_MIN", "100"))
MIN_FOLL = int(os.environ.get("LP_MIN_FOLLOWERS", "1000"))  # drop fake/botted low-follower channels
# languages we no longer source into the CRM (SullyGnome `language` field, lowercased).
# NOTE: "russian" only — Ukrainian is a separate language and is NOT excluded.
EXCLUDE_LANGS = {"russian"}
# languages we flag visually in the sheet (SullyGnome `language`, lowercased) ->
# row gets a tinted background so they stand out at a glance. Ukrainian = blue.
HIGHLIGHT_LANGS = {"ukrainian": "CFE2F3"}
# SullyGnome day window: 1 = last day (normal daily run). Override LP_SCAN_WINDOW=7
# for a one-off weekly backfill (e.g. when seeding newly-added competitor games).
SCAN_WINDOW = int(os.environ.get("LP_SCAN_WINDOW", "1"))
# optional: restrict a run to specific SullyGnome game ids (comma/space separated).
# empty = scan all GAMES. Used for targeted backfills of just the new competitors.
ONLY_GAMES = {int(x) for x in re.split(r"[,\s]+", os.environ.get("LP_ONLY_GAMES", ""))
              if x.strip().isdigit()}
STATUSES = ["Not contacted", "Contacted", "Keys Given (PT)", "Keys Given (Playtest)"]
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Kyiv")
except Exception:  # noqa: BLE001  (no tzdata locally — Kyiv is UTC+3 in summer)
    TZ = timezone(timedelta(hours=3))
# competitor games: SullyGnome numeric id -> display name (name is used url-encoded)
GAMES = {
    164411: "Content Warning", 196063: "PEAK", 203585: "Gamble With Your Friends",
    115691: "Escape the Backrooms", 211429: "Burglin' Gnomes", 151427: "Lethal Company",
    218831: "Funnel Runners", 210742: "Pratfall", 214291: "Forest Escape: Last Train",
    221410: "Meowgic", 201544: "YAPYAP", 186876: "R.E.P.O.",
    221608: "Grain Rot", 211693: "Dig Dig Die",
    206127: "RV There Yet?", 184245: "Schedule I",
    197572: "Shift at Midnight", 58977: "Phasmophobia", 224047: "Bombanana!",
    212609: "Project: Doors", 223542: "Meccha Chameleon",
    227154: "Machine Party", 214411: "Super Battle Golf",
    126390: "Backrooms: Escape Together", 228970: "How to Fish",
    192898: "MIMESIS", 224185: "Cat Mail Co.", 205721: "Far Far West",
    105461: "Palworld", 220677: "Librarian: Tidy Up the Arcane Library!",
    218839: "Friendly Steps", 184398: "A Game About Digging A Hole",
    222879: "A Game About Chopping Trees",
}
HEADER = ["Capture date", "Competitor game", "Streamer", "Peak viewers",
          "Followers", "Email", "Socials", "Status"]

# distinct pastel per competitor game (hex) — quick visual grouping in column B
GAME_COLORS = {
    "Content Warning": "FADAD5", "PEAK": "FFF2CC", "Gamble With Your Friends": "D9EAD3",
    "Escape the Backrooms": "D0E0E3", "Burglin' Gnomes": "EAD1DC", "Lethal Company": "FCE5CD",
    "Funnel Runners": "CFE2F3", "Pratfall": "D9D2E9", "Forest Escape: Last Train": "B6D7A8",
    "Meowgic": "FCE1F0", "YAPYAP": "E6F0C8", "R.E.P.O.": "F4CCCC",
    "Grain Rot": "F9CB9C", "Dig Dig Die": "B4A7D6",
    "RV There Yet?": "A4C2F4", "Schedule I": "FFE599",
    "Shift at Midnight": "D7A9E3", "Phasmophobia": "C9DAF8", "Bombanana!": "FCD5CE",
    "Project: Doors": "B7E1CD", "Meccha Chameleon": "E1D5E7",
    "Machine Party": "FFD966", "Super Battle Golf": "A2C4C9",
    "Backrooms: Escape Together": "DD9EBD", "How to Fish": "A6E3E9",
    "MIMESIS": "D5A6BD", "Cat Mail Co.": "FFE0B2", "Far Far West": "E8C1A0",
    "Palworld": "C5E1A5", "Librarian: Tidy Up the Arcane Library!": "B3E5FC",
    "Friendly Steps": "F8BBD0", "A Game About Digging A Hole": "D7CCC8",
    "A Game About Chopping Trees": "DCEDC8",
}

SULLY_H = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"),
           "Referer": "https://sullygnome.com/", "X-Requested-With": "XMLHttpRequest",
           "Accept": "application/json, text/javascript, */*; q=0.01"}
GQL_H = {"Client-ID": "kimne78kx3ncx6brgo4mv6wki5h1ko", "Content-Type": "application/json"}
GQL_Q = ("query($l:String!){user(login:$l){description channel{socialMedias{name url}} "
         "panels{__typename ... on DefaultPanel{description linkURL}}}}")
# non-contact "emails" scraped from panels we must never use: Google Calendar feed
# ids (…@group.calendar.google.com), image files, hash-like local parts.
JUNK_EMAIL = re.compile(r"@(group\.)?calendar\.google\.com$|\.(png|jpe?g|gif|webp)$"
                        r"|^[0-9a-f]{20,}@", re.I)
DELAY = float(os.environ.get("LP_DELAY", "1.0"))


def creds():
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    raw = os.environ.get("GCP_SA_KEY")
    if raw:
        return Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
    key = glob.glob(os.path.join(os.path.dirname(__file__), "*ai-labs-rsg*.json"))
    return Credentials.from_service_account_file(key[0], scopes=scopes)


def channels_last_day(gid, name):
    """Channels that streamed the game in the last SCAN_WINDOW day(s), with peak (maxviewers)."""
    ne = quote(name, safe="")
    out, start = [], 0
    while True:
        u = (f"https://sullygnome.com/api/tables/gametables/getgamechannels/{SCAN_WINDOW}/{gid}/{ne}"
             f"/0/1/3/desc/{start}/100")
        try:
            j = requests.get(u, headers=SULLY_H, timeout=25).json()
        except Exception as e:  # noqa: BLE001
            print(f"    sully error {gid}: {e}"); break
        batch = j.get("data", [])
        out.extend(batch)
        tot = j.get("recordsTotal", 0)
        start += 100
        if not batch or start >= tot:
            break
        time.sleep(DELAY)
    return out


def enrich(login):
    """Return (email, socials_string) from Twitch GraphQL socials + panels."""
    try:
        j = requests.post("https://gql.twitch.tv/gql", headers=GQL_H,
                          data=json.dumps({"query": GQL_Q, "variables": {"l": login}}),
                          timeout=20).json()
        u = (j.get("data") or {}).get("user") or {}
        sm = (u.get("channel") or {}).get("socialMedias") or []
        panels = u.get("panels") or []
        ptext = " ".join([(p.get("description") or "") + " " + (p.get("linkURL") or "")
                          for p in panels if p])
        socials = {}
        for s in sm:
            if s.get("url"):
                socials[(s.get("name") or "link").lower()] = s["url"]
        for lk in re.findall(r"https?://[^\s)\]]+", ptext):
            low = lk.lower()
            for k in ("linktr", "linktree", "beacons", "pixie", "discord", "instagram",
                      "twitter", "x.com", "youtube", "youtu.be", "tiktok"):
                if k in low and k not in socials:
                    socials[k] = lk
        emails = sorted(set(re.findall(r"[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}",
                                       (u.get("description") or "") + " " + ptext)))
        # drop non-contact junk: Google Calendar feed ids, image files, hash-like local parts
        emails = [e for e in emails if not JUNK_EMAIL.search(e)]
        return (emails[0] if emails else "",
                "\n".join(f"{k}: {v}" for k, v in socials.items()))
    except Exception:  # noqa: BLE001
        return "", ""


def _hyperlink_logins(sh, tabs=None):
    """Twitch logins from cells' derived hyperlink field (catches rich-text links
    like the Streamer/Name cells we insert). One metadata call for the whole book."""
    out = set()
    try:
        ranges = tabs if tabs is not None else [w.title for w in sh.worksheets()]
        md = sh.fetch_sheet_metadata(params={
            "ranges": ranges, "fields": "sheets/data/rowData/values/hyperlink"})
        for s in md.get("sheets", []):
            for d in s.get("data", []):
                for row in d.get("rowData", []):
                    for v in row.get("values", []):
                        mm = re.search(r"twitch\.tv/([a-z0-9_]{2,25})",
                                       (v.get("hyperlink") or "").lower())
                        if mm:
                            out.add(mm.group(1))
    except Exception:  # noqa: BLE001
        pass
    return out


def crm_seen(*books):
    """Every Twitch login + email already present in ANY tab of the given books.

    Read cells as FORMULA so twitch.tv URLs inside HYPERLINK() formulas are exposed,
    and harvest each book's derived hyperlink field as well so inserted rich-text
    links dedup too. Pass both MasterCRM and the outreach book — a contact that
    exists in either one must not be re-added.
    """
    logins, emails = set(), set()
    for sh in books:
        for w in sh.worksheets():
            try:
                vals = w.get_values(value_render_option="FORMULA")
            except Exception:  # noqa: BLE001
                vals = w.get_all_values()
            text = "\n".join("\t".join(str(c) for c in r) for r in vals).lower()
            logins |= set(re.findall(r"twitch\.tv/([a-z0-9_]{2,25})", text))
            emails |= set(re.findall(r"[\w.\-+]+@[\w.\-]+\.[a-z]{2,}", text))
        logins |= _hyperlink_logins(sh)
    return logins, emails


def link_streamer(sh, gid, start_row0, pairs):
    """Write column C rows as real clickable links (name -> channel URL),
    styled bold + underlined blue so they read as links."""
    accent = _rgb(11, 87, 208)
    rowdata = [{"values": [{
        "userEnteredValue": {"stringValue": name},
        "userEnteredFormat": {"textFormat": {
            "bold": True, "underline": True, "foregroundColor": accent,
            "fontSize": 10, "link": {"uri": url}}}}]} for name, url in pairs]
    sh.batch_update({"requests": [{"updateCells": {
        "range": {"sheetId": gid, "startRowIndex": start_row0,
                  "endRowIndex": start_row0 + len(pairs),
                  "startColumnIndex": 2, "endColumnIndex": 3},
        "rows": rowdata,
        "fields": "userEnteredValue,userEnteredFormat.textFormat"}}]})


def _rgb(r, g, b):
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


def _hex(h):
    return _rgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def beautify(sh, cc):
    """Presentable, idempotent styling: frozen colored header, zebra rows,
    per-game color, peak gradient, wrapped socials, a Status dropdown with
    colored states, thousands separators, sensible widths. Re-applied safely
    every run (old bandings + conditional-format rules are cleared first)."""
    gid = cc.id
    n = len(cc.get_all_values()) or 1
    NC = len(HEADER)  # 8
    W = [105, 180, 160, 90, 100, 240, 430, 130]  # per-column pixel widths
    HEADER_BG = _hex("1B2A4A")       # deep indigo
    WHITE = _rgb(255, 255, 255)
    BAND_A = _rgb(255, 255, 255)
    BAND_B = _hex("EEF3FB")          # very light blue-gray

    meta = sh.fetch_sheet_metadata()
    old_bandings, n_cf = [], 0
    for s in meta.get("sheets", []):
        if s.get("properties", {}).get("sheetId") == gid:
            old_bandings = [b["bandedRangeId"] for b in s.get("bandedRanges", [])]
            n_cf = len(s.get("conditionalFormats", []))

    reqs = [{"updateSheetProperties": {
        "properties": {"sheetId": gid, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount"}}]
    reqs += [{"deleteBanding": {"bandedRangeId": b}} for b in old_bandings]
    reqs += [{"deleteConditionalFormatRule": {"sheetId": gid, "index": 0}}
             for _ in range(n_cf)]
    reqs.append({"addBanding": {"bandedRange": {
        "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": n,
                  "startColumnIndex": 0, "endColumnIndex": NC},
        "rowProperties": {"headerColor": HEADER_BG, "firstBandColor": BAND_A,
                          "secondBandColor": BAND_B}}}})
    # header row
    reqs.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": 0, "endColumnIndex": NC},
        "cell": {"userEnteredFormat": {
            "backgroundColor": HEADER_BG, "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
            "textFormat": {"foregroundColor": WHITE, "bold": True, "fontSize": 11}}},
        "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)"}})
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": gid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 40}, "fields": "pixelSize"}})
    for i, w in enumerate(W):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": w}, "fields": "pixelSize"}})

    def rng(c0, c1):
        return {"sheetId": gid, "startRowIndex": 1, "endRowIndex": n,
                "startColumnIndex": c0, "endColumnIndex": c1}

    if n > 1:
        # base data format: compact, top-aligned, clipped
        reqs.append({"repeatCell": {"range": rng(0, NC),
            "cell": {"userEnteredFormat": {"verticalAlignment": "TOP",
                     "wrapStrategy": "CLIP", "textFormat": {"fontSize": 10}}},
            "fields": "userEnteredFormat(verticalAlignment,wrapStrategy,textFormat.fontSize)"}})
        # peak + followers: thousands separator, centered
        reqs.append({"repeatCell": {"range": rng(3, 5),
            "cell": {"userEnteredFormat": {
                "numberFormat": {"type": "NUMBER", "pattern": "#,##0"},
                "horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}})
        # capture date centered
        reqs.append({"repeatCell": {"range": rng(0, 1),
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat.horizontalAlignment"}})
        # socials: wrap so each link sits on its own line
        reqs.append({"repeatCell": {"range": rng(6, 7),
            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
            "fields": "userEnteredFormat.wrapStrategy"}})
        # Status: centered + dropdown validation
        reqs.append({"repeatCell": {"range": rng(7, 8),
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat.horizontalAlignment"}})
        reqs.append({"repeatCell": {"range": rng(7, 8),
            "cell": {"dataValidation": {
                "condition": {"type": "ONE_OF_LIST",
                              "values": [{"userEnteredValue": s} for s in STATUSES]},
                "showCustomUi": True, "strict": False}},
            "fields": "dataValidation"}})
        # per-game color on the game column
        for gname, hexc in GAME_COLORS.items():
            reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [rng(1, 2)],
                "booleanRule": {"condition": {"type": "TEXT_EQ",
                                "values": [{"userEnteredValue": gname}]},
                                "format": {"backgroundColor": _hex(hexc)}}}}})
        # peak gradient (light -> strong): highlights the big streams at a glance
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [rng(3, 4)],
            "gradientRule": {"minpoint": {"color": _hex("FFFFFF"), "type": "MIN"},
                             "midpoint": {"color": _hex("C9DAF8"), "type": "PERCENTILE", "value": "60"},
                             "maxpoint": {"color": _hex("3C78D8"), "type": "MAX"}}}}})
        # Status colors
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [rng(7, 8)],
            "booleanRule": {"condition": {"type": "TEXT_EQ",
                            "values": [{"userEnteredValue": "Contacted"}]},
                            "format": {"backgroundColor": _hex("B6D7A8"),
                                       "textFormat": {"foregroundColor": _hex("274E13"), "bold": True}}}}}})
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [rng(7, 8)],
            "booleanRule": {"condition": {"type": "TEXT_EQ",
                            "values": [{"userEnteredValue": "Not contacted"}]},
                            "format": {"backgroundColor": _hex("F4CCCC"),
                                       "textFormat": {"foregroundColor": _hex("990000")}}}}}})
    sh.batch_update({"requests": reqs})


def highlight_langs(sh, cc, start_row0, rows):
    """Tint whole rows whose SullyGnome language is in HIGHLIGHT_LANGS.

    A direct cell background beats the zebra banding beautify() lays down, so the
    flag survives later runs. `rows` carry their language in the last column (it is
    stripped before the values are written to the sheet).
    """
    reqs = []
    for i, r in enumerate(rows):
        colour = HIGHLIGHT_LANGS.get(r[9] if len(r) > 9 else "")
        if not colour:
            continue
        reqs.append({"repeatCell": {
            "range": {"sheetId": cc.id, "startRowIndex": start_row0 + i,
                      "endRowIndex": start_row0 + i + 1,
                      "startColumnIndex": 0, "endColumnIndex": len(HEADER)},
            "cell": {"userEnteredFormat": {"backgroundColor": _hex(colour)}},
            "fields": "userEnteredFormat.backgroundColor"}})
    if not reqs:
        return
    for j in range(0, len(reqs), 400):
        sh.batch_update({"requests": reqs[j:j + 400]})
    print(f"  flagged {len(reqs)} rows by language "
          f"({', '.join(sorted(HIGHLIGHT_LANGS))})")


def main():
    gc = gspread.authorize(creds())
    sh = gc.open_by_key(SHEET_ID)
    try:
        ea = gc.open_by_key(EA_SHEET_ID)
    except Exception as e:  # noqa: BLE001 — never let a dedup source break the run
        print(f"WARN: outreach book unreachable ({e}); deduping against MasterCRM only")
        ea = None
    seen_logins, seen_emails = crm_seen(*(x for x in (sh, ea) if x))
    src = "MasterCRM + outreach book" if ea else "MasterCRM only"
    print(f"dedup index: {len(seen_logins)} twitch logins, "
          f"{len(seen_emails)} emails ({src})")

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    rows, added_logins = [], set()
    with requests.Session() as s:
        s.headers.update(SULLY_H)
        for gid, name in GAMES.items():
            if ONLY_GAMES and gid not in ONLY_GAMES:
                continue
            chans = [c for c in channels_last_day(gid, name)
                     if (c.get("maxviewers") or 0) >= THRESHOLD
                     and (c.get("followers") or 0) >= MIN_FOLL
                     and (c.get("language") or "").strip().lower() not in EXCLUDE_LANGS]
            print(f"  {name}: {len(chans)} channels (>= {THRESHOLD} peak & >= {MIN_FOLL} followers, "
                  f"excl. {'/'.join(sorted(EXCLUDE_LANGS))}, window={SCAN_WINDOW}d)")
            for c in chans:
                login = (c.get("twitchurl") or "").rstrip("/").rsplit("/", 1)[-1].lower()
                if not login or login in seen_logins or login in added_logins:
                    continue
                email, socials = enrich(login)
                if not email:
                    continue  # policy: never add a contact without a profile email
                if email.lower() in seen_emails:
                    continue  # same person already a contact by email
                added_logins.add(login)
                # trailing url is stripped before writing; used for the link
                rows.append([today, name, c.get("displayname") or login,
                             c.get("maxviewers"), c.get("followers"), email, socials,
                             "Not contacted", f"https://www.twitch.tv/{login}",
                             (c.get("language") or "").strip().lower()])
                time.sleep(0.3)
            time.sleep(DELAY)

    rows.sort(key=lambda r: -(r[3] or 0))
    cc = sh.worksheet(TAB)
    if not cc.get_all_values() or cc.row_values(1) != HEADER:
        cc.update(values=[HEADER], range_name="A1")
    start = len(cc.get_all_values())   # 0-based index of the first new row
    if rows:
        cc.append_rows([r[:8] for r in rows], value_input_option="USER_ENTERED")
    beautify(sh, cc)
    if rows:
        link_streamer(sh, cc.id, start, [(r[2], r[8]) for r in rows])
        highlight_langs(sh, cc, start, rows)
    print(f"\nAppended {len(rows)} NEW competitor streamers to '{TAB}'.")
    for r in rows[:10]:
        print(f"  {r[1]:24.24} {str(r[2])[:20]:20} peak={r[3]} foll={r[4]} email={'yes' if r[5] else '-'}")


if __name__ == "__main__":
    main()
