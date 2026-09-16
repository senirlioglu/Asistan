"""PATTERN LAB — run every engine on one match, then throw most of the answers away.

The reader picks a match. They do not pick "exact or ±2", "twin or pattern", "which window" — the
orchestration is this module's job, and the engines underneath are the ones that already exist.

The hard part is not running them. It is that running eight engines across nine outcomes produces
seventy-odd measurements per match, and with a 95 % interval roughly four of them clear zero by
chance in a match where nothing whatsoever is happening. A screen that shows the winners of that
search will show six findings for every match forever, and every one of them will be noise wearing
a confidence interval.

So the scan is a funnel, and the funnel is statistical rather than cosmetic:

    1. every engine runs and every measurement is counted           -> `scanned`
    2. measurements without a benchmark or with too small a sample are dropped
    3. Benjamini-Hochberg across the whole family of THIS match     -> q values
    4. what is left needs a real effect too, not only a small q     -> `findings`

In most matches step 4 leaves nothing, and "bu maçta araştırılabilir bir durum bulunamadı" is the
correct answer rather than a failure. The number scanned is reported next to the number kept, so a
reader can see the denominator that makes the survivors unremarkable.

Two engines produce context rather than claims and never enter the family: odds movement (a shape,
not a rate) and fixture sequences (a similarity, not a probability). They are shown, labelled as
context, and excluded from the correction — putting them in would let a description borrow the
authority of a test it never took.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..config import Settings
from ..logging_setup import get_logger
from . import engine, service, sequence

log = get_logger("patterns.lab")

# the markets a finding may be about, in the order a reader thinks about them
OUTCOMES = ("win", "draw", "loss", "over25", "btts", "over15", "over35", "ht_draw", "ht_win")
OUTCOME_TR = {"win": "Kazanır", "draw": "Berabere", "loss": "Kaybeder", "over25": "2,5 üst",
              "btts": "KG var", "over15": "1,5 üst", "over35": "3,5 üst",
              "ht_draw": "İY berabere", "ht_win": "İY önde"}

MIN_N = 200          # below this the interval is the answer, whatever the point estimate says
MIN_EDGE = 1.0       # percentage points; smaller than this is not worth a reader's attention
ALPHA = 0.05

EVIDENCE = {
    "thin": "YETERSİZ VERİ",
    "discovery": "KEŞİF",
    "confirmed": "DOĞRULANDI",
    "tested": "İLERİ TESTTE",
}


@dataclass
class Finding:
    """One measurement that survived the funnel, with everything needed to disbelieve it."""

    source: str
    source_tr: str
    outcome: str
    n: int
    actual: float
    market: float | None
    edge: float
    ci: list[float]
    p: float
    q: float = 1.0
    evidence: str = "discovery"
    detail: str = ""

    def as_dict(self) -> dict:
        return {"source": self.source, "source_tr": self.source_tr, "outcome": self.outcome,
                "outcome_tr": OUTCOME_TR.get(self.outcome, self.outcome), "n": self.n,
                "actual": self.actual, "market": self.market, "edge": round(self.edge, 2),
                "ci": [round(self.ci[0], 2), round(self.ci[1], 2)],
                "p": round(self.p, 4), "q": round(self.q, 4),
                "evidence": self.evidence, "evidence_tr": EVIDENCE.get(self.evidence, self.evidence),
                "detail": self.detail}


def _harvest(source: str, source_tr: str, res: dict, detail: str = "") -> list[Finding]:
    """Turn one engine's outcome block into candidate findings. No filtering here — that is step 3."""
    out = []
    for o, m in (res.get("outcomes") or {}).items():
        if not m or not m.get("n"):
            continue
        edge = m.get("edge") if m.get("edge") is not None else m.get("vs_ref")
        ci = m.get("edge_ci") or m.get("vs_ref_ci") or [None, None]
        if edge is None or ci[0] is None or m.get("p") is None:
            continue                       # no benchmark, no claim — the rule the package runs on
        out.append(Finding(source=source, source_tr=source_tr, outcome=o, n=int(m["n"]),
                           actual=m.get("actual"), market=m.get("market") if m.get("market") is not None else m.get("ref"),
                           edge=float(edge), ci=[float(ci[0]), float(ci[1])], p=float(m["p"]),
                           detail=detail or res.get("label", "")))
    return out


def scan(settings: Settings, match_id: str, side: str = "home", alpha: float = ALPHA,
         min_n: int = MIN_N, min_edge: float = MIN_EDGE) -> dict | None:
    """Every engine on one match, corrected across the whole family, most of it thrown away."""
    df = service.frame(settings)
    if df is None:
        return None
    hit = df[df["match_id"] == match_id]
    if hit.empty:
        return None
    row = hit.iloc[0]

    candidates: list[Finding] = []
    context: list[dict] = []

    pat = service.patterns_for(settings, match_id, side=side)
    if pat:
        for level, tr in (("all", "Form deseni · tüm takımlar"), ("similar", "Form deseni · benzer güçtekiler"),
                          ("same_team", "Form deseni · bu takım")):
            res = (pat.get("levels") or {}).get(level)
            if res:
                candidates += _harvest(f"pattern_{level}", tr, res, detail=res.get("label", ""))

    tw = service.twins_for(settings, match_id, k=100, side=side)
    if tw:
        candidates += _harvest("twins", "Çok boyutlu ikizler", tw,
                               detail=f"en yakın {tw['diagnostics'].get('k')} maç, ortanca benzerlik "
                                      f"{tw['diagnostics'].get('median')}")

    comb = service.combined_for(settings, match_id, side=side)
    if comb:
        usable = [r for r in comb.get("rows", []) if r.get("n", 0) >= min_n]
        if usable:
            last = usable[-1]
            candidates += _harvest("combined", "İki takım birlikte", last, detail=last.get("step", ""))

    # ---- context, never claims -------------------------------------------------------------
    cyc = sequence.find_cycles(df, str(row["home_team"] if side == "home" else row["away_team"]),
                               centre_match_id=match_id, min_similarity=70.0)
    for c in (cyc.get("cycles") or [])[:3]:
        context.append({"source": "sequence", "source_tr": "Fikstür döngüsü",
                        "label": f"{c['kind_tr']} · ±{c['window']} · {c['past']['season']}",
                        "value": f"%{c['similarity']:g}",
                        "note": f"{c['n_compared']} pozisyonda karşılaştırıldı — benzerlik, olasılık değildir",
                        "data": c})

    nes = _movement_context(settings, match_id, row)
    if nes:
        context.append(nes)

    # ---- the funnel ------------------------------------------------------------------------
    scanned = len(candidates)
    sized = [f for f in candidates if f.n >= min_n]
    thin = scanned - len(sized)
    if sized:
        qs = engine.fdr([f.p for f in sized])
        for f, q in zip(sized, qs):
            f.q = float(q)
    findings = [f for f in sized if f.q <= alpha and abs(f.edge) >= min_edge]
    for f in findings:
        f.evidence = "confirmed" if f.q <= alpha else "discovery"
    _mark_tested(settings, findings, side)

    return {
        "match": {"id": match_id, "date": str(row["date"])[:10], "league": str(row["league"]),
                  "home": str(row["home_team"]), "away": str(row["away_team"]), "side": side},
        "scanned": scanned, "too_thin": thin, "after_correction": len(findings),
        "alpha": alpha, "min_n": min_n, "min_edge": min_edge,
        "findings": [f.as_dict() for f in sorted(findings, key=lambda x: (x.q, -abs(x.edge)))],
        "context": context,
        "near_misses": [f.as_dict() for f in sorted(sized, key=lambda x: x.q)[:5]
                        if f.q > alpha or abs(f.edge) < min_edge][:5],
    }


def _movement_context(settings: Settings, match_id: str, row: pd.Series) -> dict | None:
    """The odds movement shape, if this match is in the nesine bulletin and the archive saw it."""
    try:
        from ..web.api import _nesine_brief            # noqa: PLC0415 - optional, and it may not match
        brief = _nesine_brief(str(row["date"])[:10], str(row["home_team"]), str(row["away_team"]))
    except Exception:                                   # noqa: BLE001 - context is never load-bearing
        return None
    code = (brief or {}).get("code")
    if not code:
        return None
    from ..nesine import movement as mv

    out = mv.for_match(settings, int(code), cfg=mv.config_from_env())
    sel = (out.get("selections") or {}).get("ms.1") or {}
    v = sel.get("movement") or {}
    if not v.get("type"):
        return None
    return {"source": "movement", "source_tr": "Oran hareketi",
            "label": v["type"], "value": f"{v.get('total_pp')} puan" if v.get("total_pp") is not None else "–",
            "note": "hareket sınıfı bir şekildir, bir oran değil"
                    + ("" if v.get("confidence") != "low" else " · düşük güven"),
            "data": {"movement": v, "quality": sel.get("quality")}}


def _mark_tested(settings: Settings, findings: list[Finding], side: str) -> None:
    """Promote a finding to İLERİ TESTTE when the offline three-window scan also kept it.

    Being confirmed inside one match's family is a much weaker statement than surviving discovery,
    validation and an untouched test window, so the two are never shown as the same thing."""
    files = service.research_files(settings)
    claims = ((files.get("discovery") or {}).get("claims")) or []
    alive = {c.get("outcome") for c in claims
             if c.get("stage") == "survived" and c.get("side") == side}
    if not alive:
        return
    for f in findings:
        if (f.source.startswith("pattern") or f.source == "combined") and f.outcome in alive:
            f.evidence = "tested"
