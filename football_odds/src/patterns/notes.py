"""The notebook notes, re-measured with the pattern engine.

`src/nesine/history.py` already checks two of the notes against the database, but it answers a
weaker question: it compares the note's hit rate with the overall rate. That cannot separate "this
note finds something" from "this note finds favourites". A note that fires on heavy favourites
will beat the base rate every time and still be worthless, because the price already said so.

Here each testable note becomes a `Pattern` and every claim it makes is measured against:

    piyasa        for the markets Football-Data prices (1X2, 2,5 goals) — the paired difference
                  between what happened and what the price implied, minus the pool-wide offset
    benzer fiyat  for the markets it does not price (half-time result, 2/1/1/2 reversal, 6+ goals) —
                  the rate among matches carrying a SIMILAR PRICE. Half the notes are conditions on
                  the price, so comparing them with the whole pool would only rediscover that
                  favourites lead at half time and score more. See `engine.matched_rates`.

Which notes can be measured at all
----------------------------------
The database holds results, half-time scores and 1X2 / over-2.5 prices. It has no half-time-result
odds, no correct-score odds and no corner market, so notes 1, 5, 6, 7, 12, 13 and 15 — all of which
are conditions ON those prices — cannot be tested here at all; they can only be watched forward
from the nesine archive. Notes 3, 8 and 9 are anecdotes about specific clubs or basketball.

That leaves 2, 4, 10, 11, 14 and 16, and one caveat runs through all of them: nesine quotes one
exact price, while Football-Data carries an average across bookmakers. "Tam 1,67" therefore becomes
"1,665–1,675 ortalama", which is a slightly different set of matches than the note is about.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import engine
from .engine import Pattern

EPS = 0.005          # "exactly 1.67" against an average price: a band of half a cent
PRICED = ("win", "draw", "loss", "over25")      # the outcomes the market puts a number on


@dataclass
class Claim:
    """One thing a note asserts, and the side it asserts it about."""

    outcome: str
    text: str


@dataclass
class NoteTest:
    id: str
    no: int
    title: str
    note: str                      # the owner's own words
    pattern: Pattern
    claims: list[Claim]
    how: str                       # how the note was turned into a filter, including what was lost
    extra_sides: bool = False      # measure the away side too (notes written about "a team", not a venue)


def _tests() -> list[NoteTest]:
    return [
        NoteTest(
            id="n2", no=2, title="Ters çevirenin 7. maçı",
            note="Bir takım 2/1 veya 1/2 yaptıysa, sonra oynayacağı 7. maçı yine 2/1 veya 1/2 yapar. Bazen 6+ gol çıkıyor.",
            pattern=Pattern(extra={"h_since_rev": (6, 6)}),
            claims=[Claim("reversal", "yine 2/1 veya 1/2"), Claim("goals6", "6+ gol")],
            how="Takımın son ters çevirmesinden bu yana oynadığı maç sayısı 6 ise (bugünkü maç 7.'si).",
            extra_sides=True),
        NoteTest(
            id="n4", no=4, title="Favoriye oran açılmıyor (≤ 1,20)",
            note="Favoriye hiç oran açılmazsa ya da en fazla 1,20 açılırsa o maç %99,9 2,5 üst, %80 3,5 üst, %70 6+ biter.",
            pattern=Pattern(extra={"fav_odds": (1.0, 1.20)}),
            claims=[Claim("over25", "2,5 üst"), Claim("over35", "3,5 üst"), Claim("goals6", "6+ gol")],
            how="Konsensüs oranların düşüğü 1,20 ve altındaysa. 'Hiç açılmamış' hali veritabanında yok."),
        NoteTest(
            id="n10", no=10, title="Maç sonucu tam 1,67",
            note="MS1 veya MS2'de 1,67 görürsen o yöne ilk yarı 1 ve ilk yarı 1-0 al. %85 çalışıyor.",
            pattern=Pattern(extra={"cons_h": (1.67 - EPS, 1.67 + EPS)}),
            claims=[Claim("ht_win", "ilk yarı önde"), Claim("ht_1_0", "ilk yarı 1-0"), Claim("win", "maçı kazanır")],
            how="Ev sahibinin konsensüs oranı 1,665–1,675 ise (deplasman için ayrı satır).",
            extra_sides=True),
        NoteTest(
            id="n11", no=11, title="MS1 ile MS2 eşit (±0,01)",
            note="MS1 ve MS2 aynıysa %100 2/1 veya 1/2 olur; 0,01 fark varsa düşük tarafın yönünde.",
            pattern=Pattern(extra={"odds_gap": (0.0, 0.01)}),
            claims=[Claim("reversal", "2/1 veya 1/2"), Claim("draw", "beraberlik"), Claim("over25", "2,5 üst")],
            how="İki tarafın konsensüs oranı arasındaki fark 0,01 ve altındaysa. Notun 23–25 İY/MS oran "
                "penceresi veritabanında yok (İY/MS fiyatı tutulmuyor), o kısım ölçülemedi."),
        NoteTest(
            id="n14", no=14, title="Son maçı ters çevirenin ilk yarısı berabere",
            note="En son maçını 1/2 ya da 2/1 yapan takımın bir sonraki maçının ilk yarısı %80–90 berabere olur.",
            pattern=Pattern(extra={"h_since_rev": (0, 0)}),
            claims=[Claim("ht_draw", "ilk yarı berabere"), Claim("draw", "maç berabere")],
            how="Takımın bir önceki maçı 2/1 ya da 1/2 bittiyse.",
            extra_sides=True),
        NoteTest(
            id="n16", no=16, title="Favori 1,65 / 1,67 / 1,75",
            note="Favoriye 1,65, 1,67, bazen 1,75 verilirse o yöne ilk yarı gönül rahatlığıyla oynarsın; "
                 "açılan takım ilk yarı mutlaka 1 gol atar.",
            pattern=Pattern(extra={"cons_h": (1.65 - EPS, 1.75 + EPS)}),
            claims=[Claim("ht_win", "ilk yarı önde"), Claim("win", "maçı kazanır"), Claim("ht_draw", "ilk yarı berabere")],
            how="Ev sahibi favorinin oranı 1,645–1,755 ise. Not üç ayrı oranı sayıyor; aradaki değerler de "
                "bu banda giriyor, yani not olduğundan biraz geniş ölçüldü.",
            extra_sides=True),
    ]


def _away_pattern(p: Pattern) -> Pattern:
    """The same note read for the away team: swap the h_ columns for a_ and the price columns."""
    from dataclasses import replace

    extra = {}
    for col, rng in p.extra.items():
        if col.startswith("h_"):
            extra["a_" + col[2:]] = rng
        elif col == "cons_h":
            extra["cons_a"] = rng
        else:
            extra[col] = rng
    return replace(p, side="away", extra=extra)


def measure_notes(frame: pd.DataFrame, as_of: pd.Timestamp | None = None) -> list[dict]:
    """Every testable note, both sides where it applies, with its claims measured."""
    outcomes = tuple(dict.fromkeys(c.outcome for t in _tests() for c in t.claims))
    all_outcomes = PRICED + tuple(o for o in outcomes if o not in PRICED)
    base = {side: engine.baseline(frame, side, PRICED) for side in ("home", "away")}
    rows = []
    for t in _tests():
        variants = [("ev sahibi", t.pattern)] + ([("deplasman", _away_pattern(t.pattern))] if t.extra_sides else [])
        for side_label, pat in variants:
            claimed = tuple(c.outcome for c in t.claims)
            sub = engine.select(frame, pat, as_of=as_of)
            refs = engine.matched_rates(frame, sub, pat.side, claimed)     # matches priced like these
            res = engine.run(frame, pat, outcomes=claimed, as_of=as_of, base=base[pat.side], refs=refs)
            rows.append({"id": t.id, "no": t.no, "title": t.title, "note": t.note, "how": t.how,
                         "side": side_label, "n": res["n"],
                         "claims": [{"outcome": c.outcome, "text": c.text, **res["outcomes"][c.outcome]} for c in t.claims]})
    # every claim in the batch goes through the same multiple-testing correction
    flat = [c for r in rows for c in r["claims"]]
    for c, q in zip(flat, engine.fdr([c.get("p") for c in flat])):
        c["q"] = q
    return rows


def verdict(claim: dict) -> str:
    """What the measurement says about one claim, in one word — AFTER the multiple-testing correction."""
    if not claim["n"]:
        return "ölçülemedi"
    q = claim.get("q")
    priced = claim.get("edge_ci") and claim["edge_ci"][0] is not None
    ref = claim.get("vs_ref_ci") and claim["vs_ref_ci"][0] is not None
    if q is None or q > 0.05:
        return "fark yok" if (priced or ref) else "kıyas yok"
    if priced:
        return "piyasadan iyi" if claim["edge"] > 0 else "piyasadan kötü"
    return "benzer fiyatlılardan yüksek" if claim["vs_ref"] > 0 else "benzer fiyatlılardan düşük"


def report(rows: list[dict]) -> str:
    """A plain-text table, the way the owner reads it."""
    out = []
    for r in rows:
        out.append(f"\n{r['no']}. {r['title']} · {r['side']} · N={r['n']}")
        for c in r["claims"]:
            if not c["n"]:
                out.append(f"   {c['text']:24} ölçülemedi (yarı skoru yok)")
                continue
            line = f"   {c['text']:24} %{c['actual']:5.1f} [{c['ci'][0]:.0f}–{c['ci'][1]:.0f}]  N={c['n']:6}"
            if c.get("edge") is not None:
                line += f"  piyasa %{c['market']:.1f} · fark {c['edge']:+.1f} [{c['edge_ci'][0]:+.1f}, {c['edge_ci'][1]:+.1f}]"
            elif c.get("vs_ref") is not None:
                line += f"  benzer fiyat %{c['ref']:.1f} · fark {c['vs_ref']:+.1f} [{c['vs_ref_ci'][0]:+.1f}, {c['vs_ref_ci'][1]:+.1f}]"
            out.append(line + (f"  q={c['q']:.3f}" if c.get("q") is not None else "") + f"  -> {verdict(c)}")
    return "\n".join(out)
