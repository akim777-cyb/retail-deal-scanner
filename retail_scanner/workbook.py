"""The two-tab Excel: All Properties (every listing inside the buy box) and First Pass (the ones that pencil)."""
from __future__ import annotations
import datetime

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

MONEY = '"$"#,##0;[Red]-"$"#,##0'
MONEY_EST = '"$"#,##0" est."'
PSF = '"$"#,##0.00'
PCT = "0.00%"
PCT0 = "0%"
TIMES = '0.00"x"'
LINK = Font(color="0563C1", underline="single")

# header, width, key in the row, kind of cell
COLUMNS = [
    ("Listing", 34, "address", "link"), ("Change", 22, "change", "wrap"), ("Property", 34, "name", "wrap"),
    ("City", 16, "city", "text"), ("State", 7, "state", "text"), ("MSA", 30, "msa", "wrap"), ("Type", 18, "kind", "text"),
    ("Ask", 13, "price", "money"), ("Cap Rate", 9, "cap_rate", "pct"), ("NOI", 13, "noi", "noi"),
    ("Size (SF)", 10, "sf", "int"), ("Price / SF", 10, "price_psf", "psf"), ("Occupancy", 10, "occupancy", "pct0"),
    ("Tenants", 34, "tenants", "wrap"), ("UW NOI", 13, "uw_noi", "money"), ("UW Cap", 9, "uw_cap", "pct"),
    ("DSCR", 8, "dscr", "times"), ("Cash-on-Cash", 11, "coc", "pct"), ("Price at Target Cap", 14, "price_at_target", "money"),
    ("Lot (Acres)", 9, "lot_acres", "dec2"), ("Year Built", 9, "year_built", "int"), ("Lease Type", 12, "lease_type", "text"),
    ("WALT (Yrs)", 9, "walt_years", "dec1"), ("Broker", 26, "broker", "wrap"), ("Days on Market", 9, "days_on_market", "int"),
    ("First Seen", 11, "first_seen", "date"), ("Source", 22, "source", "wrap"),
]


def header_notes(profile: dict, market: dict) -> dict:
    uw, loan, rule = profile["underwriting"], profile["underwriting"]["loan"], profile["first_pass"]
    basis = (f"{loan['amort_years']:g}-year amortization at {loan['rate'] * 100:g}%, {loan['ltv'] * 100:g}% LTV, "
             f"closing costs {uw.get('closing_costs_pct', 0) * 100:g}% of the ask.")
    return {
        "Listing": "Click the address for the listing page. Rows whose listing page has not been opened link to a search "
                   "that finds the listing. Hover a cell with a red corner for that listing's flags.",
        "Change": "Why the listing is in this export: New, price cut, newly priced, back on market, or listing page read "
                  "since the last export. Listings already exported, or marked pass, pursue or reviewed, are left out "
                  "of 'new only' exports unless the price drops.",
        "MSA": "Metro area from the Census Bureau (OMB July 2023 delineations), found from the ZIP code.",
        "Type": "From the listing's own type tags and title: Multi-Tenant Center, Single-Tenant NNN, Retail Building, Retail / Mixed Use.",
        "Cap Rate": "The cap rate on the listing (the broker's figure, not checked).",
        "NOI": "The NOI on the listing. 'est.' = no NOI shown: the ask times the listed cap rate.",
        "Occupancy": "As shown on the listing. Blank = not shown.",
        "Tenants": "Names from the listing page. Blank = the listing page has not been read, or does not name tenants.",
        "UW NOI": f"NOI less {uw['vacancy_credit_loss'] * 100:g}% vacancy and credit loss"
                  + (f", {uw['management_pct'] * 100:g}% management" if uw.get("management_pct") else "")
                  + f" and ${uw['reserves_psf']:.2f}/SF a year of reserves. Assumptions in profiles/{profile['key']}.json.",
        "UW Cap": "UW NOI / ask.",
        "DSCR": f"UW NOI / annual debt service. Loan: {basis} First Pass needs at least {rule['min_dscr']:.2f}x.",
        "Cash-on-Cash": "(UW NOI - debt service) / (down payment + closing costs), year one.",
        "Price at Target Cap": f"UW NOI / {uw['target_cap'] * 100:g}% target cap. Internal: never share with a seller, broker or lender.",
        "WALT (Yrs)": "Weighted average lease term remaining, when the listing shows it.",
        "First Seen": "The first day the scanner saw this listing.",
    }


def _sheet(ws, rows, profile, market):
    notes = header_notes(profile, market)
    fill = PatternFill("solid", fgColor="E7ECF2")
    for j, (head, width, _key, _kind) in enumerate(COLUMNS, 1):
        c = ws.cell(row=1, column=j, value=head)
        c.font, c.fill = Font(bold=True), fill
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if head in notes:
            c.comment = Comment(notes[head], "Retail Deal Scanner", width=380, height=170)
        ws.column_dimensions[get_column_letter(j)].width = width
    top = Alignment(vertical="top")
    for i, row in enumerate(rows, 2):
        for j, (_head, _width, key, kind) in enumerate(COLUMNS, 1):
            v = row.get(key)
            c = ws.cell(row=i, column=j)
            c.alignment = top
            if kind == "link":
                c.value, c.hyperlink, c.font = v, row.get("url"), LINK
                if row.get("notes"):
                    c.comment = Comment("\n".join(f"- {n}" for n in row["notes"]), "Retail Deal Scanner", width=440, height=220)
            elif v is None or v == "":
                continue
            elif kind == "money":
                c.value, c.number_format = round(v), MONEY
            elif kind == "noi":
                c.value, c.number_format = round(v), (MONEY_EST if row.get("noi_est") else MONEY)
            elif kind == "psf":
                c.value, c.number_format = round(v, 2), PSF
            elif kind == "pct":
                c.value, c.number_format = round(v, 4), PCT
            elif kind == "pct0":
                c.value, c.number_format = round(v, 3), PCT0
            elif kind == "times":
                c.value, c.number_format = round(v, 2), TIMES
            elif kind == "int":
                c.value = int(v)
                if key == "sf":
                    c.number_format = "#,##0"
            elif kind == "dec1":
                c.value, c.number_format = round(float(v), 1), "0.0"
            elif kind == "dec2":
                c.value, c.number_format = round(float(v), 2), "0.00"
            elif kind == "date":
                c.value, c.number_format = datetime.date.fromisoformat(v), "m/d/yy"
            elif kind == "wrap":
                c.value, c.alignment = v, Alignment(wrap_text=True, vertical="top")
            else:
                c.value = v
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(len(rows), 1) + 1}"


def write(path: str, rows_all: list[dict], rows_first: list[dict], profile: dict, market: dict) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "All Properties"
    _sheet(ws, rows_all, profile, market)
    _sheet(wb.create_sheet("First Pass"), rows_first, profile, market)
    wb.save(path)
