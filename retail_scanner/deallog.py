"""The running Deal Log (reports/Deal Log.xlsx): every listing the scanner has ever analyzed, in every market, and every
scan it has run. It is rebuilt from the ledger after each export, so it never drifts from what the scanner knows.

  Deals  one row per listing: screen result, first-pass numbers, days on market, status, when its page was read,
         when it was exported, and any decision.
  Scans  one row per page-read batch (ingest) and per export.
"""
from __future__ import annotations
import datetime

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .screening import evaluate

MONEY = '"$"#,##0'
LINK = Font(color="0563C1", underline="single")

DEAL_COLUMNS = [
    ("Listing", 34), ("Property", 30), ("Markets", 14), ("City", 15), ("State", 6), ("MSA", 26), ("Type", 18),
    ("Ask", 12), ("Days on Market", 9), ("Cap Rate", 8), ("UW Cap", 8), ("DSCR", 7), ("Screen", 30), ("Status", 22),
    ("Page Read", 11), ("Exported", 22), ("Decision", 28), ("First Seen", 11), ("Last Seen", 11), ("Price History", 30),
]
SCAN_COLUMNS = [("Date", 11), ("Market", 14), ("Event", 9), ("Pages", 40), ("Listings Read", 9), ("New", 7),
                ("Price Changes", 8), ("Listing Pages Opened", 9), ("Exported", 9), ("First Pass", 8), ("File", 50)]

NOTES = {
    "Screen": "First Pass = inside the buy box and DSCR at least the profile minimum. In buy box = inside the buy box, "
              "First Pass not met or not run (no NOI or cap shown). Out = why it is outside the buy box.",
    "Status": "Gone = no longer on any page it was listed on, after a full re-read of those pages.",
    "Page Read": "The day its listing page was opened. Blank = only the results card was read. A page is not opened "
                 "again unless the price changes or 90 days pass.",
    "Exported": "Every export that carried it. A listing is never exported twice unless something changed.",
    "Days on Market": "From the listing page. 'N+' = page not opened: on the market at least N days since the scanner "
                      "first saw it.",
}


def _status(x: dict, gone) -> str:
    if gone(x):
        return "Gone (off every page it was on)"
    return x.get("status") or "Active"


def _decision(x: dict) -> str:
    r = x.get("review") or {}
    if not r:
        return ""
    return f"{r['status'].title()} {r['date']}" + (f": {r['note']}" if r.get("note") else "")


def deal_rows(ledger, profile: dict, geo, gone, as_of: str) -> list[dict]:
    rows = []
    for x in ledger.items.values():
        r = evaluate(x, profile, geo, as_of)
        if r["first_pass"]:
            screen, order = "First Pass", 0
        elif r["in_box"]:
            screen, order = "In buy box" + ("" if r["dscr"] is not None else ": no NOI or cap shown"), 1
        else:
            screen, order = "Out: " + "; ".join(r["reasons_out"]), 2
        exports = "; ".join(f"{e['date']}" + (f" ({e['market']})" if e.get("market") else "") for e in x.get("exports") or [])
        history = ", ".join(f"{d} ${p:,.0f}" for d, p in x.get("price_history") or [])
        rows.append({**r, "markets": ", ".join(x.get("markets") or []), "screen": screen, "order": order,
                     "status_text": _status(x, gone), "page_read": x.get("page_read_on") or "",
                     "exported": exports, "decision": _decision(x), "last_seen": x.get("last_seen"),
                     "history": history})
    rows.sort(key=lambda r: (r["markets"], r["order"], r["dscr"] is None, -(r["dscr"] or 0), r["price"] or 9e12))
    return rows


def write(path: str, ledger, profile: dict, geo, gone, scan_events: list[dict], as_of: str | None = None) -> int:
    as_of = as_of or datetime.date.today().isoformat()
    rows = deal_rows(ledger, profile, geo, gone, as_of)
    wb = Workbook()
    ws = wb.active
    ws.title = "Deals"
    fill, top = PatternFill("solid", fgColor="E7ECF2"), Alignment(vertical="top")
    for j, (head, width) in enumerate(DEAL_COLUMNS, 1):
        c = ws.cell(row=1, column=j, value=head)
        c.font, c.fill, c.alignment = Font(bold=True), fill, Alignment(wrap_text=True, vertical="top")
        if head in NOTES:
            c.comment = Comment(NOTES[head], "Retail Deal Scanner", width=360, height=140)
        ws.column_dimensions[get_column_letter(j)].width = width
    for i, r in enumerate(rows, 2):
        values = [r["address"], r["name"], r["markets"], r["city"], r["state"], r["msa"], r["kind"], r["price"],
                  r["days_on_market"], r["cap_rate"], r["uw_cap"], r["dscr"], r["screen"], r["status_text"],
                  r["page_read"], r["exported"], r["decision"], r["first_seen"], r["last_seen"], r["history"]]
        for j, v in enumerate(values, 1):
            c = ws.cell(row=i, column=j)
            c.alignment = top
            if v in (None, ""):
                continue
            head = DEAL_COLUMNS[j - 1][0]
            if head == "Listing":
                c.value, c.hyperlink, c.font = v, r["url"], LINK
            elif head == "Ask":
                c.value, c.number_format = round(v), MONEY
            elif head == "Days on Market":
                c.value, c.number_format = int(v), ('0"+"' if r["dom_floor"] else "0")
            elif head in ("Cap Rate", "UW Cap"):
                c.value, c.number_format = round(v, 4), "0.00%"
            elif head == "DSCR":
                c.value, c.number_format = round(v, 2), '0.00"x"'
            elif head in ("Page Read", "First Seen", "Last Seen"):
                c.value, c.number_format = datetime.date.fromisoformat(v), "m/d/yy"
            else:
                c.value = v
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(DEAL_COLUMNS))}{max(len(rows), 1) + 1}"

    ws = wb.create_sheet("Scans")
    for j, (head, width) in enumerate(SCAN_COLUMNS, 1):
        c = ws.cell(row=1, column=j, value=head)
        c.font, c.fill, c.alignment = Font(bold=True), fill, Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(j)].width = width
    for i, e in enumerate(sorted(scan_events, key=lambda e: e.get("date", "")), 2):      # same day: in the order run
        values = [e.get("date"), e.get("market"), e.get("event"), "; ".join(e.get("pages") or []), e.get("cards"),
                  e.get("new"), e.get("price_changes"), e.get("pages_opened"), e.get("rows"), e.get("first_pass"),
                  e.get("file")]
        for j, v in enumerate(values, 1):
            c = ws.cell(row=i, column=j)
            c.alignment = Alignment(vertical="top", wrap_text=(j == 4))
            if v in (None, ""):
                continue
            c.value = datetime.date.fromisoformat(v) if j == 1 else v
            if j == 1:
                c.number_format = "m/d/yy"
    ws.freeze_panes = "A2"
    wb.save(path)
    return len(rows)
