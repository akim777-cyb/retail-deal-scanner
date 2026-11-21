"""All money math for the first pass. Nothing else in the scanner computes an NOI, a loan or a return.

    NOI basis    = listed NOI; else ask x listed cap rate (an estimate: the broker's cap applied to the ask)
    UW NOI       = NOI basis x (1 - vacancy & credit loss) - management % x NOI basis - reserves $/SF x building SF
    UW cap       = UW NOI / ask
    Loan         = ask x LTV;  debt service = loan x loan constant (monthly-pay, fully amortizing)
    DSCR         = UW NOI / debt service
    Equity       = ask x (1 - LTV) + ask x closing costs %
    Cash-on-cash = (UW NOI - debt service) / equity
    Price at target cap = UW NOI / target cap   (internal: never in anything for a seller, broker or lender)
"""
from __future__ import annotations


def loan_constant(rate: float, years: float) -> float:
    """Annual debt service per $1 of loan, paid monthly over `years`."""
    n = round(years * 12)
    if n <= 0:
        raise ValueError("amortization must be positive")
    r = rate / 12.0
    if r == 0:
        return 12.0 / n
    return 12.0 * r / (1.0 - (1.0 + r) ** -n)


def underwrite(price: float | None, uw: dict, noi: float | None = None, cap: float | None = None,
               sf: float | None = None) -> dict:
    """First-pass underwriting of one listing. Returns every figure plus the notes that explain gaps."""
    out = {"noi_basis": None, "noi_source": None, "uw_noi": None, "uw_cap": None, "loan": None, "debt_service": None,
           "dscr": None, "equity": None, "cash_flow": None, "coc": None, "price_at_target": None, "price_psf": None,
           "reserves": None, "vacancy": None, "management": None, "notes": []}
    if price and sf:
        out["price_psf"] = price / sf
    if noi:
        out["noi_basis"], out["noi_source"] = noi, "listed"
        if cap and price and abs(noi / price - cap) > 0.005:
            out["notes"].append(f"listed NOI implies a {noi / price * 100:.2f}% cap, not the listed {cap * 100:.2f}%")
    elif cap and price:
        out["noi_basis"], out["noi_source"] = price * cap, "implied"
    else:
        out["notes"].append("no NOI or cap rate shown: first pass not run")
        return out
    basis = out["noi_basis"]
    out["vacancy"] = basis * uw.get("vacancy_credit_loss", 0.0)
    out["management"] = basis * uw.get("management_pct", 0.0)
    if sf:
        out["reserves"] = uw.get("reserves_psf", 0.0) * sf
    else:
        out["reserves"] = 0.0
        if uw.get("reserves_psf"):
            out["notes"].append("building size not shown: no reserves taken")
    out["uw_noi"] = basis - out["vacancy"] - out["management"] - out["reserves"]
    if not price:
        return out
    loan = uw["loan"]
    out["uw_cap"] = out["uw_noi"] / price
    out["loan"] = price * loan["ltv"]
    out["debt_service"] = out["loan"] * loan_constant(loan["rate"], loan["amort_years"])
    out["dscr"] = out["uw_noi"] / out["debt_service"] if out["debt_service"] else None
    out["equity"] = price * (1 - loan["ltv"]) + price * uw.get("closing_costs_pct", 0.0)
    out["cash_flow"] = out["uw_noi"] - out["debt_service"]
    out["coc"] = out["cash_flow"] / out["equity"] if out["equity"] else None
    if uw.get("target_cap"):
        out["price_at_target"] = out["uw_noi"] / uw["target_cap"]
    return out


def passes(result: dict, occupancy: float | None, rule: dict) -> tuple[bool, list[str]]:
    """The First Pass test. Returns (passed, reasons it failed)."""
    why = []
    if result.get("dscr") is None:
        return False, ["no NOI or cap rate shown"] if result.get("noi_basis") is None else ["no price"]
    if rule.get("min_dscr") is not None and result["dscr"] < rule["min_dscr"]:
        why.append(f"DSCR {result['dscr']:.2f}x is under {rule['min_dscr']:.2f}x")
    if rule.get("min_uw_cap") is not None and (result["uw_cap"] or 0) < rule["min_uw_cap"]:
        why.append(f"UW cap {result['uw_cap'] * 100:.2f}% is under {rule['min_uw_cap'] * 100:.2f}%")
    if rule.get("min_occupancy") is not None and occupancy is not None and occupancy < rule["min_occupancy"]:
        why.append(f"occupancy {occupancy * 100:.0f}% is under {rule['min_occupancy'] * 100:.0f}%")
    return not why, why
