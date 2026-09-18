"""The user's hand-written betting notes as filters over nesine odds ("Notlar").

Each rule is a function over one parsed nesine match (see ``bulletin.parse_event``) returning None or a
hit ``{"evidence": {label: value}, "paths": {label: "o45.ust"}, "expect": "..."}`` — ``paths`` says which
odds each piece of evidence came from, so the page can mark the ones that have moved since we first saw them
(note 5 is explicit about it: "oran değişmişse oynama"). The rules are the user's own heuristics, transcribed
as faithfully as the notes allow; where a note is ambiguous the interpretation is stated in ``how``.
Nothing here is validated by the system — ``history.py`` tests the rules that can be tested on the
Football-Data database and the page shows those numbers next to the note.

Rules that are anecdotes about specific clubs (3, 8) or basketball (9) are listed but not applied.
"""

from __future__ import annotations

from typing import Any, Callable

EPS = 0.006  # odds are published with two decimals; "equal to 1.64" means within half a cent


def _eq(a: float | None, b: float, eps: float = EPS) -> bool:
    return a is not None and abs(a - b) < eps


def _fav(ms: dict[str, float]) -> tuple[str | None, float | None]:
    """Favourite side ('1' or '2') by the lower match-result odds; None when both are missing."""
    h, a = ms.get("1"), ms.get("2")
    if h is None and a is None:
        return None, None
    if a is None or (h is not None and h <= a):
        return "1", h
    return "2", a


# --------------------------------------------------------------------------- rules

def r1(m: dict) -> dict | None:
    s = m.get("iy_skor") or {}
    vals = {k: s.get(k) for k in ("2-1", "1-2", "2-2")}
    if any(v is None for v in vals.values()) or not all(v < 38.0 for v in vals.values()):
        return None
    return {"evidence": {f"İY skor {k}": v for k, v in vals.items()},
            "paths": {f"İY skor {k}": f"iy_skor.{k}" for k in vals},
            "expect": "İlk yarı 2-1 / 1-2 / 2-2; ilk yarı KG var; en az 4 gol; 2,5 üst (3,5 üst %30)."}


def r4(m: dict) -> dict | None:
    ms = m["ms"]
    h, a = ms.get("1"), ms.get("2")
    if h is None and a is None:
        return None
    if h is None or a is None:
        # one side has no price at all: nesine does that for a favourite too short to quote
        side, odd, other = ("1", None, a) if h is None else ("2", None, h)
    else:
        side, odd = ("1", h) if h <= a else ("2", a)
        other = a if side == "1" else h
        if odd > 1.20:
            return None
    ev: dict[str, Any] = {"Favori": "ev sahibi" if side == "1" else "deplasman",
                          "Favorinin MS oranı": odd if odd is not None else "açılmamış",
                          "Diğer taraf": other if other is not None else "–"}
    return {"evidence": ev, "paths": {"Favorinin MS oranı": f"ms.{side}", "Diğer taraf": f"ms.{'2' if side == '1' else '1'}"},
            "expect": "2,5 üst (%99,9), 3,5 üst (%80), 6+ gol (%70); İY 1,5 üst; favoriye İY 2-0 / 3-0 denenebilir."}


def r5(m: dict) -> dict | None:
    ev: dict[str, Any] = {}
    paths: dict[str, str] = {}
    for group, label in (("iy05", "İY 0,5 {}"), ("ilk_gol", "İlk golü atar: {}"), ("korner", "{}")):
        for k, v in (m.get(group) or {}).items():
            if _eq(v, 1.64):
                ev[label.format(k)] = v
                paths[label.format(k)] = f"{group}.{k}"
    if not ev:
        return None
    return {"evidence": ev, "paths": paths, "expect": "2/1 veya 1/2. Maça 3–5 dk kala oyna; oran değişmişse oynama."}


def r6(m: dict) -> dict | None:
    iyms = m.get("iyms") or {}
    ev = {f"İY/MS {k}": iyms[k] for k in ("1/2", "2/1") if iyms.get(k) is not None and iyms[k] < 18.0}
    if not ev:
        return None
    return {"evidence": ev, "paths": {k: f"iyms.{k.removeprefix('İY/MS ')}" for k in ev},
            "expect": "Bu maça mutlaka oynanır (1/2 ya da 2/1)."}


def r7(m: dict) -> dict | None:
    iy, ft = (m.get("iy_skor") or {}).get("diger"), (m.get("skor") or {}).get("diger")
    if iy is None or ft is None or not (iy < 5.0 and ft < 8.0):
        return None
    return {"evidence": {"İY skor diğer": iy, "Maç skoru diğer": ft},
            "paths": {"İY skor diğer": "iy_skor.diger", "Maç skoru diğer": "skor.diger"},
            "expect": "6+ gol; en az 3,5 üst; İY KG var / 2. yarı KG var."}


def r10(m: dict) -> dict | None:
    ms = m["ms"]
    hits = {k: ms[k] for k in ("1", "2") if _eq(ms.get(k), 1.67)}
    if not hits:
        return None
    side = next(iter(hits))
    return {"evidence": {f"MS {side}": hits[side]}, "paths": {f"MS {side}": f"ms.{side}"},
            "expect": f"İlk yarı {side} ve ilk yarı skoru {'1-0' if side == '1' else '0-1'} (not: %85 çalışır)."}


def r11(m: dict) -> dict | None:
    ms = m["ms"]
    h, a = ms.get("1"), ms.get("2")
    if h is None or a is None or abs(h - a) > 0.0101:
        return None
    iyms = m.get("iyms") or {}
    if _eq(h, a, 0.001):
        direction = "2/1 veya 1/2"
        combos = ["2/1", "1/2"]
    else:
        # the side with the lower odds is where the match "turns": home lower -> 2/1, away lower -> 1/2
        combos = ["2/1"] if h < a else ["1/2"]
        direction = combos[0]
    ev: dict[str, Any] = {"MS 1": h, "MS 2": a}
    paths = {"MS 1": "ms.1", "MS 2": "ms.2"}
    ok_window = []
    for c in combos:
        v = iyms.get(c)
        ev[f"İY/MS {c}"] = v if v is not None else "yok"
        paths[f"İY/MS {c}"] = f"iyms.{c}"
        ok_window.append(v is not None and 23.0 < v < 25.0)
    verdict = "OYNA: oran 23–25 aralığında." if any(ok_window) else "OYNAMA: İY/MS oranı 23–25 aralığının dışında."
    return {"evidence": ev, "paths": paths, "expect": f"{direction}. {verdict}"}


def r12(m: dict) -> dict | None:
    a, b = (m.get("o45") or {}).get("ust"), (m.get("iki_yari_15_ust") or {}).get("evet")
    if a is None or b is None or abs(a - b) > 0.20 + 1e-9:
        return None
    return {"evidence": {"4,5 üst": a, "Her iki yarı 1,5 üst": b},
            "paths": {"4,5 üst": "o45.ust", "Her iki yarı 1,5 üst": "iki_yari_15_ust.evet"},
            "expect": "6+ gol (4,5 üst); iki yarıda da 1,5 üst; 3,5 üst ve 2,5 üst rahat."}


def r13(m: dict) -> dict | None:
    v = (m.get("iy_y2_kg") or {}).get("evet/evet")
    if v is None or v >= 8.0:
        return None
    return {"evidence": {"1.Y / 2.Y KG var": v}, "paths": {"1.Y / 2.Y KG var": "iy_y2_kg.evet/evet"}, "expect": "En az 2,5 üst, hatta 3,5 üst; ilk yarıdan en az 2 gol; iki yarıda da 1,5 üst; İY 2-2 denenebilir."}


def r15(m: dict) -> dict | None:
    d = m.get("iy_sonucu_kg") or {}
    ev = {("İY 1 & KG var" if k == "1&var" else "İY 2 & KG var"): d[k] for k in ("1&var", "2&var") if d.get(k) is not None and d[k] < 8.0}
    if not ev:
        return None
    return {"evidence": ev, "paths": {"İY 1 & KG var": "iy_sonucu_kg.1&var", "İY 2 & KG var": "iy_sonucu_kg.2&var"},
            "expect": "İki yarıda da 1,5 üst; 2-1 / 1-2; MS 4-2 veya 2-2 skorları."}


def r16(m: dict) -> dict | None:
    side, odd = _fav(m["ms"])
    if side is None or odd is None or not any(_eq(odd, x) for x in (1.65, 1.67, 1.75)):
        return None
    other = "2" if side == "1" else "1"
    return {"evidence": {f"MS {side} (favori)": odd, f"MS {other}": m["ms"].get(other)},
            "paths": {f"MS {side} (favori)": f"ms.{side}", f"MS {other}": f"ms.{other}"},
            "expect": f"İlk yarı {side} gönül rahatlığıyla; açılan takım ({'deplasman' if side == '1' else 'ev sahibi'}) ilk yarı mutlaka 1 gol atar (0,5 üst)."}


def r17(m: dict) -> dict | None:
    v = (m.get("o25_kg") or {}).get("ust&var")
    if v is None or v < 2.15:
        return None
    strong = v >= 2.25
    return {"evidence": {"2,5 Üst & KG Var": v}, "paths": {"2,5 Üst & KG Var": "o25_kg.ust&var"},
            "expect": "2,5 alt (%70–80)" + (" ve 3,5 alt gönül rahatlığıyla (oran 2,25+)" if strong else "; oran 2,25'i geçerse 3,5 alt da") + "."}


def r18(m: dict) -> dict | None:
    kg, ne = (m.get("iy_kg") or {}).get("var"), (m.get("iy_y2_kg") or {}).get("hayir/evet")
    if kg is None or ne is None or abs(kg - ne) > 0.10 + 1e-9:
        return None
    return {"evidence": {"İY KG var": kg, "1.Y/2.Y KG hayır/evet": ne},
            "paths": {"İY KG var": "iy_kg.var", "1.Y/2.Y KG hayır/evet": "iy_y2_kg.hayir/evet"},
            "expect": "İlk yarı KG var (%80–90); ilk yarı 0,5 üst gönül rahatlığıyla."}


def r20(m: dict) -> dict | None:
    v = (m.get("korner_aralik") or {}).get("12+")
    if v is None or v >= 3.0:
        return None
    return {"evidence": {"Toplam korner 12+": v}, "paths": {"Toplam korner 12+": "korner_aralik.12+"},
            "expect": "En az 9–10 korner" + (" (oran 2,50'nin altında: daha da iyi)" if v < 2.5 else "") + "."}


RULES: list[dict[str, Any]] = [
    {"id": "n1", "no": 1, "title": "İlk yarı skorları 38'in altında", "fn": r1, "testable": False,
     "note": "İY skor < 38.00 ise o maç İY skor 2-1, 1-2, 2-2 mutlaka. En kötü ilk yarı KG var gelir, %99,9 çıkışır. Bu maçlarda en az 4 gol olur; İY–2. yarı KG var gelebilir. En garanti 2,5 üst, 3,5 üst %30 gelebilir.",
     "how": "İlk yarı skoru piyasasında 2-1, 1-2 ve 2-2'nin üçü de 38,00'ın altındaysa."},
    {"id": "n2", "no": 2, "title": "Ters çevirenin 7. maçı", "fn": None, "testable": True,
     "note": "Herhangi bir takım sırada bir maçı oynayıp 2/1 veya 1/2 yaptıysa sonra oynayacağı 7. sıradaki maçı yine 2/1 veya 1/2 yapar. Bazen de 6+ gol çıkıyor.",
     "how": ("Veritabanındaki ilk yarı/maç sonu geçmişinden: ters çevirdiği maç sayılmaz, ondan SONRA oynadığı maçlar sayılır ve "
             "bugünkü maç bunların 7.'siyse kural çalışır. Dikkat: sayım yalnızca bizim 38 ligimizin maçlarını görür; hazırlık "
             "maçları ve kupalar veritabanında olmadığı için sürpriz orada olduysa ya da arada kupa maçı oynandıysa sıra kayar.")},
    {"id": "n3", "no": 3, "title": "Başakşehir – Antalya – Alanya döngüsü", "fn": None, "testable": False, "applied": False,
     "note": "Bu takımların kendi aralarında oynadıkları maçlara bak: Başakşehir Alanya ile 2/1 yapıyor, sonra Antalya Alanya ile 1/2 yapıyor, sonra Başakşehir–Antalyaspor 3'lü döngüye giriyor ve sonuç yine 2/1.",
     "how": "Üç kulübe özel bir gözlem; genel bir filtre olarak uygulanmadı."},
    {"id": "n4", "no": 4, "title": "Favoriye oran açılmıyor (≤ 1,20)", "fn": r4, "testable": True,
     "note": "Bir maçta favori olan takıma hiç oran açılmazsa ya da en fazla 1,20'ye kadar açılırsa o maç %99,9 2,5 üst, %80 3,5 üst, %70 6+ biter. İlk yarı 1,5 üst ve favori takıma ilk yarı 2-0, 3-0 skorları da denenebilir.",
     "how": "Maç sonucu piyasasında favorinin oranı yoksa (1,00) ya da 1,20 ve altındaysa."},
    {"id": "n5", "no": 5, "title": "1,64 oranı (İY 0,5 · ilk gol · korner)", "fn": r5, "testable": False,
     "note": "Bir takımın ilk yarı 0,5 üst oranı 1,64 ise ya da alt oranı 1,64 ise o maça 2/1 veya 1/2 vuruyoruz. Değilse 'ilk golü kim atar' oranına bakıyoruz; 1,64 ise 2/1, 1/2 olasılığı doğuyor. O da değilse korner alanındaki 1,64 oranına bakıyoruz. Maç başlamasına 3–5 dk kala oynuyoruz; oran değişmesi olursa oynama.",
     "how": "İlk yarı 0,5 alt/üst, ilk golü kim atar ya da herhangi bir korner seçeneğinde tam 1,64 oranı varsa."},
    {"id": "n6", "no": 6, "title": "1/2 veya 2/1 oranı 18'in altında", "fn": r6, "testable": False,
     "note": "Bir maçın 1/2 veya 2/1 oranı < 18,00 ise o maça mutlaka oynanır.",
     "how": "İY/MS piyasasında 1/2 ya da 2/1 seçeneği 18,00'ın altındaysa."},
    {"id": "n7", "no": 7, "title": "'Diğer' skor oranları düşük", "fn": r7, "testable": False,
     "note": "İY skor 'diğer' < 5 ve aynı maçın maç skoru 'diğer' < 8 ise 6+ gol; en az 3,5 üst oynayabilirsin. Bu tarz maçlar çoğu şekilde İY KG var / 2. yarı KG var şeklinde sonuçlanır.",
     "how": "İlk yarı skoru 'Diğer' 5,00'ın, maç skoru 'Diğer' 8,00'ın altındaysa."},
    {"id": "n8", "no": 8, "title": "Barcelona – Valencia", "fn": None, "testable": False, "applied": False,
     "note": "Barcelona her sene Valencia ile maç yaptıktan sonra 2 maç sonra 1/2, 2/1 yapıyor.", "how": "Tek kulübe özel gözlem; uygulanmadı."},
    {"id": "n9", "no": 9, "title": "Basketbol 1,64", "fn": None, "testable": False, "applied": False,
     "note": "Basket maçlarında MS1 veya MS2 oranlarında 1,64 görürsen 1/0, 2/0 dene. Bu oran olunca gelir; en kötü yakın skorla çıkar.", "how": "Basketbol; bu sayfa futbol."},
    {"id": "n10", "no": 10, "title": "Maç sonucu tam 1,67", "fn": r10, "testable": True,
     "note": "Futbol maçlarında MS1 veya MS2'de 1,67 oranı görürsen o maça verdiği yöne doğru 2/0 ve 1/0 al. MS2 1,67 varsa o maç ilk yarı 2 ve 2/0; MS1 1,67 varsa o maç İY 1 ve 1/0. %85 çalışıyor.",
     "how": "MS 1 ya da MS 2 tam 1,67 ise. '1/0' ilk yarı 1-0 skoru olarak okundu."},
    {"id": "n11", "no": 11, "title": "MS1 ile MS2 eşit (ya da 0,01 fark)", "fn": r11, "testable": True,
     "note": "Bir maçta MS1 2,30, MS2 2,30 ise MS0 önemli değil; bu oranlar aynı ise %100 2/1 veya 1/2. Bazen MS1 2,30 iken MS2 2,31 olabiliyor: yani oranlar kimin tarafına 0,01 az ise maç o yönde 2/1 veya 1/2 çıkar. Bu oranları gördükten sonra o maçın 2/1 ve 1/2 oranlarına bakıyoruz: 23,00 < x < 25,00 olmalı. 2/1 → 25,10, 27,00 ya da 1/2 → 25,03, 28,00 ise OYNAMA.",
     "how": "MS 1 ve MS 2 farkı en fazla 0,01 ise; düşük oranlı taraf ev sahibiyse 2/1, deplasmansa 1/2 seçeneğinin oranı 23–25 aralığında mı diye bakılır."},
    {"id": "n12", "no": 12, "title": "6+ gol: iki yarının 1,5 üst oranları yakın", "fn": r12, "testable": False,
     "note": "6+ gol: 4,5 üst ve iki yarıda da 1,5 üst oranlarına bakıyoruz. Bu iki oran birbirinin aynı ise veya aralarında en fazla 0,20 varsa +6 gol oynayabilirsin. Bu bilgi maça yakın saatlerde kapanış oranıyla alınmalı. Aynı zamanda çok rahat 3,5 üst, iki yarıda 1,5 üst, 2,5 üst.",
     "how": "4,5 üst oranı ile 'Her iki yarıda da 1,5 üst' oranının farkı en fazla 0,20 ise (nesine ikinci yarı 1,5 piyasası vermiyor; iki yarı birlikte piyasası kullanıldı)."},
    {"id": "n13", "no": 13, "title": "İki yarıda da KG var oranı 8'in altında", "fn": r13, "testable": False,
     "note": "Bir maçın 1. yarı / 2. yarı KG var oranı < 8,00 ise o maç en az 2,5 üst ve hatta 3,5 üst olur. İlk yarıdan en az 2 gol gelir, iki yarıda da 1,5 üst; ilk yarı 2-2 skoru deneyebilirsin.",
     "how": "'1. Yarı / 2. Yarı Karşılıklı Gol' piyasasında Evet/Evet 8,00'ın altındaysa."},
    {"id": "n14", "no": 14, "title": "Son maçı ters çevirenin ilk yarısı berabere", "fn": None, "testable": True,
     "note": "En son maçlarını 1/2 ya da 2/1 yapan takımların bir sonraki maçının ilk yarısı %80–90 civarında 0 (berabere) olur.",
     "how": "Veritabanından: takımın bir önceki maçı 2/1 ya da 1/2 bittiyse."},
    {"id": "n15", "no": 15, "title": "İY sonucu + KG var oranı 8'in altında", "fn": r15, "testable": False,
     "note": "İY sonucu 1 ve KG var < 8,00 ise (ya da İY sonucu 2 ve KG var): bu tarz maçlarda 2 yarıda da 1,5 üst rahatlıkla oynayabilirsin. Aynı zamanda bu maçlar yine ilk yarı 2-1 ve 1-2, MS 4-2 veya 2-2 skorları da çıkabilir.",
     "how": "'1. Yarı Sonucu ve 1. Yarı KG' piyasasında 1 & Var ya da 2 & Var 8,00'ın altındaysa."},
    {"id": "n16", "no": 16, "title": "Favori 1,65 / 1,67 / 1,75", "fn": r16, "testable": True,
     "note": "MS1 veya MS2 verilen oranlarda favori takıma 1,65, 1,67 ve bazen 1,75 oranları verilirse bu tarz maçlara verilen yöne göre ilk yarı 1 veya ilk yarı 2 gönül rahatlığıyla oynayabilirsin. Ayrıca açılan takım ilk yarı mutlaka 1 gol atmaktadır; yine can'dan bu oran açılan takıma 0,5 üst gol de alabilirsin.",
     "how": "Favorinin maç sonucu oranı tam 1,65, 1,67 ya da 1,75 ise."},
    {"id": "n17", "no": 17, "title": "2,5 Üst & KG Var oranı 2,15 ve üstü → 2,5 alt", "fn": r17, "testable": False,
     "note": "Maçlarda açılan oranlarda ilk bakılacak yer 2,5 üst KG var oranıdır. O maça 2,15 ve üzerinde bir oran görürsen en az %70–80 2,5 alt oynayabilirsin. Oran ne kadar yüksekse (2,25, bazen 2,40–2,50) o maçlarda gönül rahatlığıyla 3,5 alt da oynanır; 3,5 alt oranı en az 1,40–1,50 arayanlar için hazinedir.",
     "how": "'2,5 Alt/Üst ve Karşılıklı Gol' piyasasında Üst & Var 2,15 ve üzerindeyse; 2,25 ve üzerinde 3,5 alt da eklenir. Veritabanında bu birleşik oran yok, ölçülemez."},
    {"id": "n18", "no": 18, "title": "İY KG var ile hayır/evet oranı aynı (≤ 0,10)", "fn": r18, "testable": False,
     "note": "Bir maçın ilk yarı KG var oranı ile 1. yarı / 2. yarı KG piyasasındaki hayır/evet oranı aynıysa ya da aralarında en fazla 0,10 fark varsa (3,30 – 3,40 olur, 3,30 – 3,41 geçersiz) o maçta ilk yarı KG var %80–90 gelir; ilk yarı 0,5 üst de gönül rahatlığıyla oynanır.",
     "how": "'İlk Yarı KG' Var oranı ile '1. Yarı / 2. Yarı KG' Hayır/Evet oranının farkı 0,10 ve altındaysa."},
    {"id": "n19", "no": 19, "title": "Son maçını 2-3 kaybeden (İspanya 2)", "fn": None, "testable": True,
     "note": "İspanya 2. liginde son maçını 2-3 (ya da 3-2) yenilen takımlar bir sonraki maçlarını 1/2 veya 2/1 yapıyorlar. Eğer bir sonraki maçta yapmazlarsa bazen kayabiliyor: 2-3 yenildikten sonraki 2. maçlarında da 1/2 veya 2/1 yapıyorlar.",
     "how": "Veritabanından: takımın bir önceki maçı 2-3 mağlubiyetse (kendi 2, rakip 3); o maç ters çevirmediyse bir sonraki maç için de bakılır. Not İspanya 2 için yazılmış; kural her ligde uyanır, evidence ligi söyler."},
    {"id": "n20", "no": 20, "title": "12+ korner oranı 3,00'ın altında", "fn": r20, "testable": False,
     "note": "12+ korner oranı 3,00'ın altında olursa (hatta 2,50'nin altında olursa daha iyi) bu tarz maçlarda en az 9–10 korner gelir.",
     "how": "'Toplam Korner Aralığı' piyasasında 12+ seçeneği 3,00'ın altındaysa. Korner sayısı veritabanında yok, ölçülemez."},
]


def evaluate(match: dict, history_hits: dict[str, dict] | None = None) -> list[dict]:
    """Rule hits for one match. `history_hits` = {rule_id: hit} computed from the database (rules 2, 14)."""
    hits = []
    for r in RULES:
        fn: Callable | None = r.get("fn")
        hit = fn(match) if fn else (history_hits or {}).get(r["id"])
        if hit:
            hits.append({"id": r["id"], "no": r["no"], "title": r["title"], **hit})
    return hits
