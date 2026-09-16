# Motor sözlüğü

Bu dosya sistemin **tamamının** haritasıdır: hangi motor var, ne alır, ne verir, nerede kullanılır,
ve — en önemlisi — **ne yapmaz**. Bir motorun ne yapmadığını bilmemek, yaptığını bilmemekten daha
pahalıya mal olur; her bölümün sonunda o yüzden bir "yapmaz" satırı var.

Sistemin tek bir cümlelik iddiası şudur:

> "Piyasanın bu maça verdiği profile tarihsel olarak benzeyen maçlarda gerçekte ne olmuş —
> ve bu fark, belirsizliği hesaba katınca hâlâ bir fark mı?"

Bütün motorlar bu cümlenin bir parçasını taşır. Hiçbiri tek başına tahmin üretmez.

**Temel ilke:** *yüksek gerçekleşme oranı edge değildir.* %70 kazanmış bir desen, piyasa zaten %68
diyorsa hiçbir şey söylemiyordur. Bu yüzden her motorun çıktısında ham oranın yanında mutlaka
**karşılaştırma tabanı** (piyasa beklentisi / fiyat-eşlemeli referans / havuz taban oranı) vardır.

---

## 0. Bir bakışta

```
                    ┌─── VERİ ────────────────────────────────────────────┐
football-data.co.uk │ football_data → build → matches.parquet (179.878)   │
nesine.com bülten   │ bulletin      → watcher → archive (kalıcı geçmiş)   │
ESPN scoreboard     │ live          → canlı skor/dakika                   │
                    └──────────────────────┬──────────────────────────────┘
                                           │
        ┌──────────────────────────────────┼──────────────────────────────┐
        │                                  │                              │
   FİYAT MOTORU                     DURUM MOTORU                    NOT MOTORU
   features/odds.py                 patterns/state.py               nesine/rules.py
   marj at → p_home/p_draw/p_away    maç öncesi 136 kolon            16 el yazısı not
        │                                  │                              │
        ├─── models/similarity.py ─────────┤                              │
        │    (fiyat benzeri K komşu)       ├─ patterns/engine.py          │
        │                                  │  (desen → ölçüm)             │
        │                                  ├─ patterns/twins.py           │
        │                                  │  (7 kategorili ikiz)         │
        │                                  └─ patterns/discovery.py       │
        │                                     (tarama + eleme)            │
        ▼                                            ▼                    ▼
   models/stats.py ──► küçültme ──► models/signal.py │              nesine/history.py
        │                                            │                    │
        └──────────────► DOĞRULAMA KAPILARI ◄────────┴────────────────────┘
                     backtest/run.py   (walk-forward, backtest_ok)
                     patterns/evaluate.py (A–E model yarışı)
                                  │
                                  ▼
                            SUNUM (web/api.py + static)
                   Maçlar · Oyun · Sanal oyun · Karne · Notlar · Araştırma
```

---

## 1. Veri motorları

| motor | dosya | ne yapar |
|---|---|---|
| **İndirici** | `data/football_data.py` | `mmz4281/<sezon>/<lig>.csv` (22 bölüm) + `new/<ÜLKE>.csv` (16 ülke) indirir, önbelleğe alır. Biten sezon sonsuza kadar cache'te, güncel sezon `refresh_hours=12` saatte bir tazelenir. `fixtures.csv` (yaklaşan maçlar) ayrı çekilir |
| **Şema eşleyici** | `data/schema.py` | Football-Data yıllar içinde kolon adını değiştirdi (`BbAvH` → `AvgH` vs). Kanonik ada çevirir; `POST_MATCH_COLUMNS` maç sonrası bilgiyi işaretler ki özellik üretimine sızmasın |
| **Kurucu** | `data/build.py` | Ham CSV → kanonik kolon → konsensüs oran → marjsız olasılık → `data/processed/matches.parquet`. Hedef kolonlarını (`ftr`, `total_goals`, `btts`…) ekler |
| **Denetçi** | `data/audit.py` | Hangi market hangi sezonda hangi ligde var? (`results/audit/`). Sistem kurulurken "yarı skoru 2019 öncesi yok" gibi gerçekleri buradan öğrendik |
| **Kalite raporu** | `data/quality.py` | Her build'de eksik oran, bozuk overround, çift kayıt sayar → `results/data_quality_report.md` |
| **Sağlayıcı arayüzü** | `data/providers.py` | Motorlar veri kaynağına değil, iki soyutlamaya bağlı: `HistoricalDataProvider` ve `CurrentOddsProvider`. Böylece Football-Data yerine The-Odds-API takılabiliyor, model kodu değişmiyor |

**Yapmaz:** Avrupa kupaları, milli maçlar, kupa maçları veri setinde **yoktur**. Sadece lig maçları.
Alt lig yarı skoru ve O/U marketi bazı sezonlarda yok — bu yüzden bazı ölçümler daha küçük N ile çıkar.

---

## 2. Fiyat motoru — `features/odds.py`

Oranı olasılığa çeviren katman. Her şeyin girdisi burasıdır.

```
raw_i = 1 / oran_i
total = Σ raw_i            # = 1 + marj (overround)
p_i   = raw_i / total      # orantısal marj atma (referans yöntem)
```

- **Konsensüs zinciri:** `consensus_1x2` önce bahisçi ortalaması (`AvgH/D/A`), yoksa tek tek
  bahisçilerin ortalaması, o da yoksa kapanış ortalaması. Hangi halkanın kullanıldığı kayıtlıdır.
- **Alternatifler:** Shin (1993) içeriden-bilgi modeli ve power yöntemi araştırma için var; üretimde
  orantısal kullanılıyor.
- **Güvenlik:** oran ≤ 1.0 veya overround > 1.15 ise satır NaN olur — yarım kotalı bir marketten
  sahte olasılık üretilmez.

Çıktı kolonları: `p_home / p_draw / p_away`, `p_over25 / p_under25`, kapanış `pc_*`, hareket `delta_p_*`.

**Yapmaz:** nesine/İddaa marjını temizlemez (onlar ayrı kanal, `nesine/` altında). Bahisçiye özel
sapmayı modellemez — sadece piyasa ortalamasını alır.

### `features/vectors.py` — "Benzerlik %" tanımı

Komşu sıralaması hangi metrikle yapılırsa yapılsın, **raporlanan** benzerlik metrikten bağımsızdır:

```
TV = 0.5 · Σ |p_i − q_i|          (toplam değişim mesafesi)
Benzerlik % = 100 · (1 − TV)
```

%98 benzerlik = iki profil arasında 2 puanlık olasılık kütlesi farkı. Okunabilir ve sınırlı.

---

## 3. Benzerlik motoru (ana motor) — `models/similarity.py`

Sistemin ilk ve hâlâ ana motoru. Bir maçı **sadece fiyatıyla** tarif eder: 3 (veya 5) sayı.

- **Model A — tolerans:** her sonuçta ±tol içindeki tüm tarihsel maçlar.
- **Model B — K en yakın komşu (üretimde bu):** mesafeye göre ilk K. Metrik seçenekleri
  euclidean / manhattan / cosine / **mahalanobis**.
- **İleri-bakış koruması yapısaldır:** `candidates()` yalnızca sorgu tarihinden *kesinlikle önce*
  oynanmış maçları döndürür. Aynı sezonun önceki maçları serbest, sonraki maçları asla.

Üretim parametreleri (`results/backtest/selected_params.json`, backtest'in kendi seçtiği):
`feature_set=1x2_ou`, `metric=mahalanobis`, `k=100`, `half_life=null` (zaman ağırlığı yok),
`prior_strength=200`, `scope=global`.

**Yapmaz:** form, kadro, sakatlık, hava durumu, motivasyon — hiçbirini bilmez. Kasten. Bu motorun
iddiası "fiyatı aynı olan maçlar" idi; geri kalanı `patterns/` katmanının işi.

---

## 4. İstatistik ve küçültme motoru — `models/stats.py`

K komşu bulunduktan sonra "ne olmuş?" sorusunu cevaplar.

- **Ağırlıklı oranlar:** her komşunun zaman ağırlığı olabilir (`models/time_weights.py`,
  `w = exp(−λ·yıl)`, λ = ln2 / yarı_ömür).
- **Etkin örneklem:** Kish `n_eff = (Σw)² / Σw²`. Güven aralığı ve küçültme ham sayıyı değil bunu kullanır.
- **Wilson %95 aralığı** — küçük N'de normal yaklaşımın verdiği saçma aralıkları vermez.
- **Küçültme (empirical-Bayes), sistemin kalbi:**

  ```
  adj_i = (n_eff · hist_i + m · market_i) / (n_eff + m)
  ```

  `m = 200` ile 50 komşuluk bir set, piyasadan tarihsel orana giden yolun sadece %20'sini gider.
  18 maçlık bir "keşif" pratikte piyasayı hiç oynatmaz. Bu, aşırı öğrenmeye karşı ilk bariyerdir.

- Ayrıca: `fair_odds` (adil oran), `market_outside_ci` (piyasa aralığın dışında mı), iki-oran z testi.

**Yapmaz:** nedensellik iddia etmez. "Bu oran yüksek" demez — "bu oran, piyasanınkinden şu kadar
farklı ve farkın belirsizliği şu" der.

---

## 5. Sinyal motoru — `models/signal.py`

Skor değil, **kural seti**. Her kural `reasons` içinde raporlanır; neden o etiketi aldığı görülebilir.

| etiket | koşul |
|---|---|
| `LOW SAMPLE` | `n_eff < 100` |
| `STRONG` | \|edge\| ≥ 5 puan **VE** piyasa Wilson aralığı dışında **VE** ort. benzerlik ≥ %95 **VE `backtest_ok`** |
| `MODERATE` | \|edge\| ≥ 3 puan **VE** aralık dışı **VE** benzerlik ≥ %90 (veya `backtest_ok`'a takılan bir STRONG adayı) |
| `NEUTRAL` | geri kalan |

`backtest_ok` şu an **false**'tur (bkz. §7). Yani sistem tasarımı gereği **hiç STRONG sinyal
üretmiyor** — walk-forward testte piyasayı yenemediği için kendi kendini kısıtlıyor. Bu bir hata
değil, kapının çalıştığının kanıtı.

---

## 6. Analiz orkestratörü — `models/engine.py`

`analyze_match(market, as_of, …)` → market → komşular → istatistik → edge → sinyal.

Kritik nokta: **backtest de bu fonksiyonu çağırır** (`as_of` = tarihsel maç günü), günlük boru
hattı da (`as_of` = bugün). Yani "test edilen sistem" ile "canlı sistem" aynı kod yoludur. Ayrı iki
implementasyon olsaydı backtest hiçbir şey kanıtlamazdı.

`scopes`: `global` (tüm ligler) ve `same_league` ayrı ayrı hesaplanır, kullanıcı ikisini de görür.

---

## 7. Doğrulama kapıları

Burası sistemin "kendine inanmama" katmanı. İki bağımsız kapı var.

### 7a. Walk-forward backtest — `backtest/run.py`

| aşama | ne yapar |
|---|---|
| 1 | **Validation sezonları** (17/18–20/21) üzerinde parametre ızgarası; en düşük düzeltilmiş log loss kazanır |
| 2 | **Test sezonları** (21/22–25/26, hiç dokunulmamış): piyasa / tarihsel / düzeltilmiş skorlar, kalibrasyon, sezon ve lig bazında istikrar, ablasyonlar, ROI |
| 3 | Model gerektirmeyen piyasa analizleri: favori kovaları, lig kalibrasyonu, zaman istikrarı, lig kümeleri |
| 4 | Oran hareketi: açılış vs kapanış, steam vs drift |

Yardımcı motorlar: `walk_forward.py` (komşu matrisi + ızgara değerlendirmesi), `metrics.py`
(Brier, log loss, ECE, eşleşmiş anlamlılık testi), `roi.py` (düz bahis simülasyonu, max drawdown),
`buckets.py` (favori kovası, lig profili, lig kümeleme), `movement.py`, `calibration_model.py`
(izotonik / kova yeniden kalibrasyon — "favoriler 3-5 puan ucuz" deseninin sömürülebilir olup
olmadığı sorusu).

**Sonuç (38.732 test maçı):**

| | Brier | log loss |
|---|---|---|
| piyasa | **0,59715** | 0,99907 |
| tarihsel (ham) | 0,60268 | 1,00851 |
| düzeltilmiş | 0,59747 | 0,99946 |

p = 0,044 — ama **piyasa lehine**. `backtest_ok = false`. Kalibrasyon hatası (ECE) düzeltilmiş
modelde daha iyi (0,0079 vs 0,0112), yani model iyi kalibre ama daha keskin değil.

### 7b. Model yarışı — `patterns/evaluate.py`

Beş model, aynı maçlarda, walk-forward, her tahmin sadece o günden önceki bilgiyle:

| model | ne |
|---|---|
| **A piyasa** | marjsız piyasa olasılığı (taban) |
| **B benzerlik** | eski K-komşu + küçültme |
| **C pattern** | form kovası artıkları, `n/(n+300)` ile küçültülmüş |
| **D ikiz** | 7 kategorili ikiz motorunun oranları |
| **E hepsi** | C ve D'nin piyasadan sapmalarının toplamı |

Ölçütler: Brier, log loss, kalibrasyon hatası, ROI, **CLV** (kapanış çizgisine göre değer), N.

**Sonuç (5.000 maç):** A 0,59722 · B 0,59744 · C 0,59734 · D 0,59829 · E 0,59849.
Hiçbiri piyasayı yenmiyor. A'nın değeri tam backtest'teki 0,59715 ile örtüşüyor — yani örneklenmiş
karşılaştırma aynı şeyi ölçüyor, bu da testin kendisinin doğrulaması.

**Yapmaz:** bu kapılar "model kötü" demez, "model piyasadan daha iyi olduğunu **kanıtlayamadı**" der.
Fark önemli: ikincisi dürüst, birincisi abartı.

---

## 8. Pattern katmanı (yeni motorlar)

Benzerlik motoru maçı fiyatıyla tarif ediyordu. Bu katman maçı **durumuyla** tarif eder.

### 8a. Durum motoru — `patterns/state.py`

Her maç için, **maç başlamadan önce bilinebilir olan** her şeyi tek satıra yazar:
179.878 maç × 136 kolon, ~85 saniyede kuruluyor → `data/processed/match_state.parquet`.

İçerik:
- **Form:** son 3/5/10 maçın W/D/L dizisi (`h_form`, `a_form`), ayrıca **iç saha / deplasman ayrı**
  (`h_form_venue`, `a_form_venue`) — bir takımın evdeki formu başka, deplasmandaki başkadır.
- **Gol:** atılan/yenilen son 5, toplam gol eğilimi.
- **TSI (takım gücü):** **piyasadan türetilmiş Elo.** Güncelleme hedefi maçın sonucu değil,
  *piyasanın o maça verdiği olasılık* (`p_home + 0,5·p_draw`). Böylece sonuçtan sızma olmaz.
  `tsi_pct` = lig içi yüzdelik, ligler arası karşılaştırma için.
- **Rakip gücü ve göreli güç:** `strength_gap`.
- **Fikstür:** dinlenme günü (`h_rest_days`), sezon içi puan/averaj, tablo sırası (`h_pos`).
- **Tersine dönüş:** yarıda geride olup kazanma/kaybetme geçmişi (`h_since_rev`, `revs10`), HT/FT.
- **H2H:** karşılaşma sayısı (`h2h_n`).

`fixture_rows()` ile aynı şema yaklaşan maçlar için de üretilir — canlı maç da geçmiş maçla aynı
dilde konuşur.

**Yapmaz:** kadro, sakatlık, transfer, hakem, hava — veri setinde yok. Motivasyonu "objektif"
kolonlardan (sıra, puan farkı) türetmek planlandı, **henüz yapılmadı**.

### 8b. Pattern motoru — `patterns/engine.py`

"Bu daha önce olduğunda, sonra ne oldu?" sorusunun makinesi.

Bir `Pattern`: form dizisi (yaklaşık eşleşme opsiyonlu), saha, TSI yüzdeliği, rakip TSI, güç farkı,
fiyat bandı, dinlenme günü, tablo sırası, lig listesi, takım.

`measure()` bir ölçümde şunların **hepsini** birden verir:

| alan | ne |
|---|---|
| `actual` | gerçekleşme oranı |
| `ci` | Wilson %95 aralığı |
| `market` | aynı maçlarda piyasanın beklentisi |
| `diff`, `diff_ci` | fark ve farkın aralığı |
| `ref`, `vs_ref` | **fiyat-eşlemeli referans** — aynı fiyat bandındaki *tüm* maçlar ne yapmış |
| `p` | anlamlılık |

`matched_rates()` bu katmanın en önemli parçası: bir deseni ham taban oranıyla karşılaştırmak
tuzaktır, çünkü desen zaten belli fiyat aralığındaki maçları seçer. Referans, fiyat bandında
(0,025 adım) eşleştirilerek alınır. `fdr()` Benjamini-Hochberg ile çoklu test düzeltmesi yapar.

Ölçülen sonuçlar: win / draw / loss / over1.5 / over2.5 / over3.5 / 6+ gol / btts / ht_win /
ht_draw / reversal / ht_1_0.

Üç analiz seviyesi: **aynı takım** / **tüm takımlar** / **benzer güçteki takımlar**.

### 8c. İkiz motoru (Match DNA) — `patterns/twins.py`

Fiyatın ötesinde benzerlik. Yedi kategori, ağırlıklı:

| kategori | ağırlık | ne ölçer |
|---|---|---|
| market | 3,0 | fiyat profili |
| strength | 2,0 | iki takımın TSI yüzdeliği |
| opponent | 2,0 | rakip gücü |
| gap | 2,0 | güç farkı |
| form | 1,5 | form dizisi örtüşmesi |
| goals | 1,0 | gol profili |
| movement | 1,0 | oran hareketi |

- **`missing_penalty = 0,5`:** karşılaştırılamayan kategori yarım ağırlıkla ve 50 puanla girer —
  bilinmeyen bir şey "mükemmel uyum" sayılmaz.
- **`MIN_SLOTS`:** iki maçlık bir takım form kategorisinde 100 alamaz (bu bir hataydı, düzeltildi:
  nansum boş slotları atlıyordu).
- **Teşhis zorunlu:** `k` sabit 100 değil; her sorgu `best / worst / mean / median / n_above_90 /
  n_candidates` döndürür. 50 ikizin ortalaması 83 ise bunu bilmelisin — "50 benzer maç bulundu"
  demek yeterli değil.
- `k_sweep()` ile K'nın sonucu ne kadar değiştirdiği ölçülebilir.

**Ağırlıklar artık tahmin değil, ölçüm.** `patterns/tune.py` doğrulama penceresinde 79 yapılandırma
denedi ve kazananı dokunulmamış test penceresinde bir kez ölçtü:

| | market | güç | rakip | fark | form | gol | hareket |
|---|---|---|---|---|---|---|---|
| eski (elle) | 3,0 | 2,0 | 2,0 | 2,0 | 1,5 | 1,0 | 1,0 |
| **ayarlanmış** | **6,0** | 2,0 | 2,0 | 2,0 | 1,5 | **4,0** | 1,0 |

Log loss: doğrulama 1,01361 → 1,00572; **test 0,99403 → 0,98530** (piyasa 0,98398). Kazanç test
penceresinde doğrulamadakinden *büyük* çıktı — yani aşırı öğrenme değil, gerçek bir iyileşme.
Piyasayı yine geçmiyor, ama aradaki fark 0,010'dan 0,0013'e indi.

**Zaman ağırlığı: yapıldı, ölçüldü, reddedildi.** `half_life` parametresi var ve çalışıyor
(`decay_weights`, `models/time_weights` ile aynı formül). Seçilen ağırlıklarla yarı ömür taraması:

| yarı ömür | doğrulama | test |
|---|---|---|
| **kapalı** | **1,00572** | 0,98530 |
| 3 yıl | 1,00915 | 0,98821 |
| 5 yıl | 1,00711 | 0,98561 |
| 8 yıl | 1,00636 | 0,98487 |
| 12 yıl | 1,00606 | 0,98476 |

Yarı ömür kısaldıkça sonuç **tek yönlü kötüleşiyor**; 12 yıl (neredeyse "kapalı") en iyiye en yakın.
Yani 2012 maçı 2025 maçı kadar bilgilendirici — futbolda eskimeyen şey, fiyatın kendisi. Motor
kapalı çalışıyor; açmak isteyen `twin_weights.json`'daki `half_life` ile açabilir.

⚠️ `beats_default_on_test` yanlışsa ayarlanan mix **canlıya alınmaz** — üçüncü pencere dekor değil.

**Yapmaz:** `movement` kategorisi şu an her maçta boş: oran hareketi arşivi 15 Eylül 2026'da başladı.

### 8d. Keşif motoru — `patterns/discovery.py`

Binlerce koşulu tarayıp en iyilerini raporlamak **saçmalık üretmenin yoludur**. Bu motor tersini
yapar: iyi görüneni **elemeye çalışır**.

Zaman bazlı pencereler (asla rastgele değil):

```
train      2011-07 → 2018-07
validation 2018-07 → 2021-07
test       2021-07 → 2027-07   (hiç dokunulmaz)
```

Huni: **396 aday → 658 iddia → 65 → 4 → 1 hayatta kalan.**

Tek hayatta kalan: *ev sahibi WWW + fiyat bandı 0,60–0,80 → fiyattan daha az kaybediyor*
(−1,9 / −2,3 / −2,3 puan, üç pencerede de aynı yönde, q = 0,003, test penceresinde N = 1.170).

Elenen örnek, neden üçüncü pencerenin şart olduğunun kanıtı: *deplasman DDD → ilk yarı beraberlik*
adayı train ve validation'da −4,1 ve −5,7 iken **test penceresinde +1,4'e döndü** — işaret değiştirdi.

Eşikler: `MIN_N = 200`, `MIN_EDGE = 1,0` puan, ve "benchmark yoksa iddia yok" (karşılaştırma tabanı
hesaplanamayan iddia sessizce atılır, tahmin edilmez).

### 8e. Not ölçücü — `patterns/notes.py`

Defterdeki 16 el yazısı notu pattern motoruyla yeniden ölçer.

**Sonuç: 26 iddiadan 24'ü, fiyat eşlemesi + FDR sonrası piyasadan ayırt edilemez.**

- 14 numaralı notun "%80–90 ilk yarı beraberlik" iddiası gerçekte **%42,2** — aynı fiyattaki tüm
  maçlarda %41,8. Yani fark 0,4 puan.
- Ayakta kalan iki iddia, ikisi de 16 numaradan: deplasman favorisinin ilk yarı önde bitirmesi
  (+3,6 puan, q = 0,012) ve ev sahibi favorisinin kazanması (+1,0 puan, q = 0,012).
- 1, 5, 6, 7, 12, 13, 15 numaralı notlar bu veriyle **ölçülemez** (korner, ilk gol, İY skor gibi
  marketler Football-Data'da yok). Bunlar için nesine arşivi birikmeyi bekliyor.

### 8f. Ayar motoru — `patterns/tune.py`

`Weights`'teki sayılar birinin yazdığı makul sayılardı — ve sorun tam olarak buydu: **test
edilmemiş makul sayı, laboratuvar önlüğü giymiş varsayımdır.** Bu modül onları ölçerek seçer.

- Puanlama: ikizlerin kendi 1X2 oranlarının **log loss**'u (küçültülmüş hâli değil — 200'lük prior
  her yapılandırmayı piyasaya yapıştırır, arama yuvarlama gürültüsünü kıyaslamaya başlar).
- Arama: mevcut en iyinin etrafında birer birer değişim, **tek geçişte**. Kategori skorları ağırlıktan
  bağımsız olduğu için maç başına bir kez hesaplanıp 79 yapılandırma için yeniden ağırlıklandırılır —
  `W @ A` matris çarpımı. 79 yapılandırma, birinin maliyetine yakın.
- Pencereler: doğrulamada seç, **teste bir kez** bak.

**Yapmaz:** global arama değil, açgözlü. 6⁷ = 280.000 kombinasyonu denemez. Ve testte varsayılanı
geçemeyen bir mix'i **canlıya almaz** (`load_weights` reddeder).

### 8g. Birleşik desen — iki takım aynı anda (`engine.cascade`)

`Pattern` yalnız bir tarafı tarif edebiliyordu. `opp_form`, `opp_venue_form`, `venue_form` ve
`opp_approx` alanlarıyla artık maçı tarif ediyor — "WWW gelen takım" ile "WWW gelen takımın LLL
gelen takımı ağırlaması" farklı iddialardır ve yalnız ikincisi bir fikstür hakkındadır.

`cascade()` koşulları tek tek ekleyip her satırı piyasayla karşılaştırır. Son satır tablonun en
az ilginç yeri; **hangi koşulun sayıyı değiştirdiği** bulgudur. Adımlar iç içe olmak zorunda,
çünkü her adım bir öncekinin sonucu üzerinde çalışıyor — 180 bin satırda yedi adım 6,1 s yerine
0,6 s.

**Varsayılan ölçüldü, seçilmedi.** Koşul başına hayatta kalan ortanca örneklem:

| dizi | form | +saha | +rakip | +rakip saha |
|---|---|---|---|---|
| 5, birebir | 881 | 10 | **0** | 0 |
| 5, ±1 | 9368 | 767 | 46 | 5 |
| 4, birebir | 2465 | 49 | 1 | 0 |
| 3, birebir | 6578 | 527 | 27 | 3 |
| **3, ±1** | 46111 | 18124 | 4686 | **2066** |

Asıl düşüşü rakip değil, **genel form ile saha formunu birebir üst üste koymak** yapıyor
(881 → 10): saha formu zaten aynı geçmişten türeyen bir alt dizi, ikisi birlikte neredeyse tekil
anahtar. Sıkı ayarlar arayüzde duruyor çünkü N'in çöküşünü görmek de bulgudur.

### 8h. Servis katmanı — `patterns/service.py`

Web süreci 223 MB'lık tam tabloyu taşıyamaz. Bu modül sadece okunan 40 kolonu alır, sayıları
float32'ye, tekrar eden metinleri kategoriye çevirir: **38 MB, 0,3 s indeksleme, sorgu başına
~120 ms.** Önbellek parquet'in kendi değişim zamanına bağlı — günlük iş tabloyu altından
değiştirse bile sonraki istek yenisini alır.

---

## 8k. Pattern Lab — orkestrasyon katmanı (`patterns/target.py`, `patterns/lab.py`, `web/static`)

Araştırma sekmesinin en üstündeki araç. Yeni bir motor değil: mevcut motorları (desen, ikiz, iki
takımlı kaskad, fikstür döngüsü, oran hareketi) okuyucunun sorusuna göre kendisi seçip çalıştıran
katman. Okuyucu motor, pencere, "birebir mi ±2 mi" seçmez.

| mod | soru | ne çalışır | uç |
|---|---|---|---|
| 1 · Bu maçta ne olur? | bir maç | `lab.scan`: her motor × dokuz sonuç, tek ailede FDR; sağ kalanlar "araştırılabilir durum" (sinyal değil). Sonra bir **hedef** (1X2 / İY / İY/MS / gol) seçilince `target.analyse`: takımın geçmişi, rakibin geçmişi, tüm benzer durumlar, benzer takım × benzer rakip, historical twins, fikstür döngüsü — her katmanda N / gerçekleşen / beklenti / Δ / %95 / kanıt | `/api/tarama/{id}`, `/api/lab/hedef/{id}?target=` |
| 2 · Bu sonuca uyan maç bul | bir hedef | günün her maçında `target.analyse(light=True)`, arka planda (iş + poll); sıralama "araştırma önceliği" (\|Δ\|/SE × katman payı × keşif taramasında sağ kalan var mı) — bahis skoru değil | `POST/GET /api/lab/tara?date=&target=` |
| 3 · Kendi patternini test et | koşullar | `target.own_pattern`: takım (form, saha formu, güç), rakip, maç (güç farkı, lig), gol (son 5), piyasa (rol, oran aralığı, açılış→kapanış hareketi) — koşullar **tek tek eklenir**, her satır fiyata karşı (`engine.cascade`) | `/api/lab/kendi` (eski `/api/desen` duruyor) |
| 4 · Döngü ara | bir takım | `sequence.find_cycles` (±2/±3/±4, dört tür, bütün geçmiş sezonlar) + "geçmişte işe yaramış mı": `cycles.measure_for` | `/api/dongu`, `/api/lab/dongu-olc` |

Üç kural her yerde: piyasa referanstır (fiyatı olmayan markette kıyas "benzer fiyatlı maçlar"dır ve
öyle yazılır; fiyat yoksa "piyasa karşılaştırması mevcut değil"), **benzerlik olasılık değildir**
(ayrı kart, tooltip), havuzda bulunan hiçbir şey "doğrulandı" değildir (KEŞİF; DOĞRULANDI ve İLERİ
TESTTE yalnızca üç pencereli taramadan gelir).

Hedefler maç perspektifindedir (`engine.MATCH_OUTCOMES`: `ft_1/X/2`, `ht_1/X/2`, `htft_1/1 …
2/2`); İY ve İY/MS için bugünkü fiyat yalnızca nesine bülteninden (marjsız) gelir. "Pattern tahmini"
= bugünkü piyasa + kullanılabilir katmanların hassasiyet ağırlıklı ortalama farkı; katmanlar
örtüştüğü için aralık iyimserdir ve sayfa bunu söyler.

## 8l. Döngü ölçümü — `patterns/cycles.py`

`sequence.py` bir kulübün döngüsünü bulur; bu modül "böyle bir döngü geçmişte merkez maç hakkında
bir şey söylemiş mi" sorusunu **bütün veritabanında** ölçer. Her maç iki satır (iki kulübün
gözünden), ±4 rakip kodları vektörel; aynı (takım, merkez rakip) grubundaki farklı sezon çiftleri
toplu puanlanır (aynı sıra / ters sıra / kaymış / güç dizisi × ±2/±3/±4). ~180 bin maçta ~2 milyon
çift, ~40 s; günlük işte kurulur, `results/backtest/cycle_pairs.parquet` olarak durum tablosunun
mtime'ına bağlı önbelleklenir (ilk istek de kurabilir).

İki hipotez: **tekrar** (yeni merkez maç eskisi gibi bitti) ve **ayna** (1 ↔ 2 döndü, ters sıra için
varsayılan); yarı skoru olan maçlarda İY/MS aynası (1/2 ↔ 2/1, havuz oranına karşı). Her iddia yeni
merkez maçta o sonucun **piyasa fiyatının** yanında; üç katman (aynı takım / tüm takımlar / benzer
güç ±10); kanıt etiketi keşif/doğrulama/test pencerelerinden. Örnek tablosu (tarih, takım, sezon
A/B, tür, benzerlik, önceki/yeni merkez, piyasa, CLV) ölçümle birlikte gelir.

## 8i. Oran hareketi motoru — `nesine/movement.py`

Arşiv 15 Eylül 2026'dan beri her nesine fiyatını saklıyordu ama kimse geri okumuyordu: sayfada bir
ok vardı, o da fiyatın oynadığını söylüyor, nasıl/ne zaman/ne hızda oynadığı hakkında hiçbir şey
söylemiyordu.

| ne | nasıl |
|---|---|
| **Trajectory** | Arşiv satırları → seçim başına adım fonksiyonu, market bazında ileri doldurma |
| **Marjsız olasılık** | Mevcut `remove_margin` ile. Market **tamamen** izlenmiyorsa (29 skor sonucunun 4'ü) marj atılmaz, `novig: false` denir |
| **Açılış / şimdi / kapanış** | Maç başlamadıysa kapanış `None` — elimizdeki son fiyat kapanış fiyatı değildir |
| **Pencereler** | 24s/12s/6s/3s/1s/30dk/15dk × başlangıç, bitiş, delta, değişim sayısı, max, min, volatilite, hız |
| **Velocity** | Puan/saat, beş pencerede |
| **Acceleration** | Geç/erken hız oranı, etiket olarak |
| **Direction consistency** | \|net\| / yol uzunluğu — aynı yere varan düz yolu dolambaçlıdan ayırır |
| **Reversal** | Boolean değil: iki bacak + geri dönüş yüzdesi |
| **Sınıflandırma** | STEAM / DRIFT / LATE_* / REVERSAL / STABLE / NOISY + ACCELERATING / DECELERATING |

**Hiçbir eşik kodda gömülü değil** — hepsi `MovementConfig`'de, `FO_MOVE_<ALAN>` ile deploy'suz
değiştirilebilir.

**Hiçbir şey uydurulmuyor:** başlangıç fiyatını görmediğimiz pencere `insufficient` döner, iki
değişimden az olan seçim hiç sınıflandırılmaz, ve her karar snapshot sayısı, ilk/son kayıt ve
**izleyicinin son 24 saatin ne kadarında çalıştığı** ile birlikte gösterilir.

⚠️ **Üretimin ilk gününde bir hata yakalandı.** İlk 16 donmuş maç 8 REVERSAL / 0 STEAM geldi.
İçinde hiç steam olmayan dağılım bulgu değil, hatadır: REVERSAL kontrolü STEAM/DRIFT'ten önce
çalışıyor ve yalnız mutlak bacak büyüklüğüne bakıyordu, böylece 10 puanlık yükselişin sonundaki
1,6 puanlık geri tepme (%16) REVERSAL sayılıp steam kategorisini yutuyordu. `reversal_min_share`
artık geri bacağın gidenin en az yarısını geri almasını istiyor.

## 8j. İleri test — `nesine/forward.py`

Hareket sınıflandırması, maç başladıktan sonra tamamlanan bir yörüngeyi okur; yani geçmişe
uydurma imkânı verinin içine gömülüdür. Bu modül o imkânı kaldırır: karar kick-off'tan ~25 dakika
**önce** dondurulup sadece-ekleyen dosyaya yazılır, sonuç geldiğinde **ayrı satır** olarak eklenir,
donmuş satıra dokunulmaz.

Kaçırılan dondurma telafi edilemez — kick-off'u donmadan geçen maç, ne kadar veri birikirse
biriksin bir daha ileri test edilemez. Bu yüzden arşiv heartbeat'i gibi öncelikli yapıldı.

Örneklem eşikleri (`MovementConfig`): gösterim 30, araştırma 100, doğrulama 300 maç. Altında
**oran gösterilmez** — 14 maçta gelen %71, aynı yöne düşen 14 yazı turadır.

## 9. Nesine katmanı

Football-Data'nın `fixtures.csv`'i sadece bizim 38 ligimizin yaklaşan maçlarını ve sadece oran
geldiğinde listeler. Nesine bülteni ise her maçı ve **çok daha fazla marketi** taşır.

| motor | dosya | ne yapar |
|---|---|---|
| **Bülten** | `nesine/bulletin.py` | `cdnbulten.nesine.com/api/bulten/getprebultenfull` çeker, her futbol maçının taşıdığı oranları düzleştirir (`ms.1`, `iy05.ust`, `iyms.1-1`, `korner.*` …) |
| **İzleyici** | `nesine/watcher.py` | Oranlar kick-off'a yaklaştıkça oynar. Uyarlanabilir aralıkla (60 / 180 / 600 / 900 s) tazeler, hareketi kaydeder. `TRACKED` joker kullanır (`ms.*`, `iy.*`, `o25.*` …) — bir notun dayandığı market komple izlenir |
| **Arşiv** | `nesine/archive.py` | **Kalıcı, sadece-ekleyen geçmiş:** `results/odds_snapshots/<GG-AA-YYYY>.jsonl`. İzleyici çalışan bir görünüm tutar ve buduyor; arşiv hiçbir şeyi silmez. "Bu tarihçe kesinlikle kaybolmamalı" şartının karşılığı budur |
| **Notlar** | `nesine/rules.py` | 16 el yazısı notun filtre hâli. Her kural artık `paths` da döndürür (kanıt etiketi → oran yolu), böylece notun yanında **oranın ne yöne gittiği** ok olarak görünür |
| **Not geçmişi** | `nesine/history.py` | Notların veritabanında ne dediğini sayar: `team_hits` (takıma bağlı notlar 2 ve 14), `backtest` (oranla ifade edilebilen notların tüm veritabanındaki gerçekleşme oranı + taban oran) |
| **Nesine analizi** | `nesine/analyze.py` | Nesine'nin oranını piyasa kabul edip **kendi ikiz/benzerlik analizimizi** herhangi bir nesine maçında çalıştırır — ligimizde olmayan maçlar için de |

**Yapmaz:** nesine marjını temizlemez (oran olduğu gibi kullanılır). İddaa fiyatı veri setinde yok;
`paper.py`'nin ROI'si Football-Data konsensüsüne göredir, gerçek İddaa getirisi daha düşüktür.

---

## 10. Ürün motorları (kullanıcının gördüğü şeyler)

| motor | dosya | ne verir |
|---|---|---|
| **Günlük boru hattı** | `pipeline/today.py` | fikstür → her maç için `analyze_match` → `results/GG-AA-YYYY_predictions.csv/.xlsx` + `_details.json` + analog parquet'i. `merge=True` ile gün içi eklemeler eskisini silmez |
| **İş zamanlayıcı** | `pipeline/jobs.py` + `serve.py` | Günlük tam iş (06:30 UTC), karne işi (05:00 UTC = 08:00 TR), **saatlik fikstür tazeleme** (`FO_FIXTURES_EVERY_MIN`, ~14 s). Football-Data bir maçı ancak oranı gelince yayınlar — sabahki tur 4 maç görürken akşam 20 maç olabiliyor; saatlik tur bu yüzden var |
| **Karne** | `pipeline/scorecard.py` | Oynanmış maçlarda **kim daha yakındı** — piyasa mı tarih mi? Market bazında (1X2, 2.5/1.5 gol, ilk/ikinci yarı), genel ve lig bazında. "Haklı" = en yüksek olasılığı verdiği sonuç oldu; "daha yakın" = gerçekleşen sonuca daha yüksek olasılık verdi |
| **Sanal oyun** | `pipeline/paper.py` | Sabit kurala uyan bir bahisçi ne kazanırdı? 6 strateji (market_fav, hist_fav, deviation, contrarian, ou25_hist, ou25_market), düz bahis, tek maç. Hem konsensüs hem maksimum oranla (iyimser üst sınır) |
| **Kupon** | `pipeline/coupons.py` | Kullanıcı maç ve sonuç seçer; sistemin kendi seçimleri (tarih ve piyasa, **oluşturma anında dondurulmuş**) yanında yürür. Sonuçlar geldikçe üçü de puanlanır: sen, analoglar, piyasa |
| **Canlı skor** | `web/live.py` | ESPN'in açık scoreboard JSON'ı (anahtarsız, resmî değil — her çağrı sarmalanmış). Takım adı eşleştirme normalize + alias tablosu ile, lig ve gün bazında |
| **Web** | `web/api.py` + `static/` | FastAPI JSON API + elle yazılmış Türkçe, mobil öncelikli HTML/CSS/JS. Streamlit (`dashboard/app.py`) eski arayüz olarak duruyor |

### API uçları

```
/api/day/{date}            günün maçları + analiz
/api/match/{match_id}      tek maçın her şeyi (analiz + nesine özeti)
/api/twins/{match_id}      ikiz motoru (k, side parametreli) + maç künyesi (TSI, form, gol, dinlenme)
/api/patterns/{match_id}   desen motoru üç seviyede (bu takım / tüm takımlar / benzer güçtekiler),
                           `approx` ile birebir vs yaklaşık eşleşme
/api/research              notlar + modeller + keşif sonuçları + durum tablosu
/api/tarama/{match_id}     Pattern Lab mod 1: her motor, tek ailede FDR, araştırılabilir durumlar
/api/lab/hedefler          ölçülebilen hedefler (1X2 / İY / İY/MS / gol)
/api/lab/hedef/{id}        mod 1 hedef analizi: katmanlar, piyasa, pattern tahmini, neden
/api/lab/tara              mod 2: günün maçlarını bir hedef için tara (POST başlatır, GET izler)
/api/lab/kendi             mod 3: kendi koşulların, koşul koşul kaskad
/api/lab/maclar, /api/lab/takimlar   maç ve takım seçiciler
/api/dongu                 mod 4: bir takımın fikstür döngüleri (pencere/sezon/tür otomatik)
/api/lab/dongu-olc         "bu döngü geçmişte işe yaramış mı" — üç katman, piyasa yanında
/api/notlar                nesine notları + oran hareketi
/api/nesine-analiz         nesine maçında kendi analizimiz
/api/scorecard             karne
/api/paper                 sanal oyun
/api/coupons               kuponlar (GET/POST/DELETE)
/api/live/{date}           canlı skor
/api/analogues/…, /api/teams/…, /api/meta, /api/health
```

Site sekmeleri: **Maçlar** (oynanmış/devam eden/oynanacak filtresi) · **Oyun** (kupon + maç başına
açılır bilgi paneli) · **Sanal oyun** · **Karne** · **Notlar** · **Araştırma**.

Maç detayında sırasıyla: yorum · üç ihtimal (piyasa/geçmiş/düzeltilmiş + %95 aralık + adil oran) ·
İY-MS · gol dağılımı · skorlar · havuz karşılaştırması · **maç künyesi** (TSI, saha formu, gol
dengesi, dinlenme, güç farkı) · **çok boyutlu ikizler** (K seçilebilir: 25/50/100/250) · **desen
motoru** (üç seviye, birebir/±1/±2 eşleşme) · nesine oranları + defter notları · aynı takımlar ·
en benzer geçmiş maçlar.

---

## 11. Hangi soru hangi motora gider

| soru | motor |
|---|---|
| "Bu maçın adil oranı ne?" | `features/odds` → `models/similarity` → `models/stats` |
| "Fiyatı buna benzeyen maçlarda ne olmuş?" | `models/similarity` |
| "Durumu buna benzeyen maçlarda ne olmuş?" | `patterns/twins` |
| "Bu takımın gücü/formu/dinlenmesi ne?" | `patterns/state` → `/api/twins` künyesi |
| "Bu form dizisinden sonra ne oluyor?" | `patterns/engine` |
| "Bu desen gerçek mi, gürültü mü?" | `patterns/discovery` (üç pencere + FDR) |
| "Bu maçta araştırılabilir ne var?" | `patterns/lab` → Pattern Lab mod 1 |
| "Bu maç 2/1 olur mu?" | `patterns/target` (her katman + piyasa) |
| "Bugün 2/1 olabilecek maç hangisi?" | `patterns/target.start_day_scan` → mod 2 |
| "Bu takımın fikstürü tersine mi döndü, bir anlamı var mı?" | `patterns/sequence` + `patterns/cycles` → mod 4 |
| "Defterimdeki not doğru mu?" | `patterns/notes` |
| "Sistem piyasayı yeniyor mu?" | `backtest/run` + `patterns/evaluate` |
| "Dün kim haklıydı?" | `pipeline/scorecard` |
| "Bu kurala uysaydım ne kazanırdım?" | `pipeline/paper` |
| "Nesine oranı ne yöne gitti?" | `nesine/watcher` + `nesine/archive` |
| "Ligimizde olmayan bir maçı analiz et" | `nesine/analyze` |

---

## 12. Sistemin kendi hakkında söyledikleri

Bu bölüm motor listesi kadar önemlidir.

1. **Hiçbir motor piyasayı yenmedi.** Backtest ve model yarışı bağımsız olarak aynı sonucu verdi.
   `backtest_ok = false` ve sistem bu yüzden STRONG sinyal üretmiyor.
2. **396 desen adayından 1'i hayatta kaldı** ve o da "fiyattan ~2 puan daha az kaybediyor" diyor —
   kâr değil, daha az zarar.
3. **26 not iddiasından 24'ü fiyatla açıklanıyor.**
4. Bu bir başarısızlık değil, **ölçüm altyapısının çalıştığının kanıtı.** Aynı taramayı fiyat
   eşlemesi, üç zaman penceresi ve FDR olmadan yapsaydık 65 "keşif" ilan ederdik.

## 13. Bilinen eksikler (şartnameden yapılmayanlar)

Üç ayrı durumu karıştırmamak gerekiyor — "yok", "var ama görünmüyor" ve "yapıldı, ölçüldü,
reddedildi" aynı şey değil.

**Hâlâ yok:**

| # | eksik | neden |
|---|---|---|
| 1 | Oran hız pencereleri (15dk/30dk/1sa/3sa) + hareket sınıflandırması (STEAM / DRIFT / LATE STEAM / REVERSAL / ACCELERATING) | Arşiv 15 Eyl 2026'da başladı; yeterli geçmiş yok. ~2-3 hafta gerek. Not: `backtest/movement.py` açılış→kapanış steam/drift'i **araştırma olarak** ölçüyor; eksik olan maç başına canlı sınıflandırma |
| 2 | Lig segmentasyonu çalışması | Yapılmadı (`buckets.cluster_leagues` lig kümelerini çıkarıyor ama ikiz/desen motorlarına bağlanmadı) |
| 3 | H2H'in ağırlıklı/test edilmiş benzerlik özelliği olması | `h2h_n` durum tablosunda var, ikiz skoruna girmiyor |
| 4 | Motivasyon / bölge (küme düşme, şampiyonluk) özellikleri | Yapılmadı. Tablo sırası (`h_pos`) var, "ne uğruna oynuyor" yok |
| 5 | İki takımlı birleşik desen (Takım A + Takım B) | `Pattern.team` tek takım filtreliyor; ikili kombinasyon yok |
| 6 | Sadece nesine'de olan notların (1, 5, 6, 7, 12, 13, 15) ileriye dönük ölçümü | Arşiv birikmesini bekliyor |
| — | Avrupa / kupa fikstür bağlamı | **Yapılamaz** — o maçlar veri setinde hiç yok |

**Yapıldı, ölçüldü, veri "kullanma" dedi** (eksik değil, sonuç):

| konu | ölçüm | karar |
|---|---|---|
| İkiz zaman ağırlığı | yarı ömür taraması, §8c | kapalı — kısaldıkça tek yönlü kötüleşiyor |
| İkiz ağırlıkları | 79 yapılandırma, doğrulama + test | **ayarlandı**, market 3→6 / gol 1→4, testte doğrulandı |
| Piyasayı yenen model | A–E yarışı + walk-forward backtest | yok — sistem bu yüzden STRONG sinyal üretmiyor |
| 26 not iddiası | fiyat eşlemeli + FDR | 24'ü piyasadan ayırt edilemez |

---

## 14. Komut haritası

```bash
python -m src.cli download     # Football-Data CSV'lerini indir/tazele
python -m src.cli audit        # hangi market hangi sezonda var
python -m src.cli build        # matches.parquet kur + kalite raporu
python -m src.cli state        # match_state.parquet kur (~85 s)
python -m src.cli backtest     # walk-forward doğrulama → selected_params.json
python -m src.cli notes        # defter notlarını yeniden ölç → notes_measured.json
python -m src.cli models       # A–E model yarışı → backtest/models.json
python -m src.cli discover     # desen taraması + eleme → backtest/discovery.json
python -m src.cli tune-twins   # ikiz ağırlıkları + zaman ağırlığı → backtest/twin_weights.json
python -m src.cli today        # günün maçlarını analiz et
python -m src.cli web          # FastAPI + zamanlayıcı (canlı dağıtımın çalıştırdığı)
python -m pytest               # 60+ test
```

### Kalıcı dosyalar

| dosya | ne |
|---|---|
| `data/processed/matches.parquet` | tarihsel maç veritabanı (179.878) |
| `data/processed/match_state.parquet` | maç öncesi durum tablosu (136 kolon) |
| `results/odds_snapshots/*.jsonl` | **nesine oran geçmişi — asla silinmez** |
| `results/backtest/selected_params.json` | üretim parametreleri + `backtest_ok` |
| `results/backtest/models.json` | A–E karşılaştırması |
| `results/backtest/discovery.json` | keşif hunisi sonucu |
| `results/backtest/twin_weights.json` | ayarlanmış ikiz ağırlıkları + yarı ömür taraması |
| `results/backtest/cycle_pairs.parquet` (+ `.json`) | Pattern Lab döngü çiftleri (günlük işte kurulur, durum tablosuna bağlı) |
| `results/notes_measured.json` | not ölçümleri |
| `results/*_predictions.csv` + `_details.json` | günlük analiz çıktısı |
| `results/coupons.json` | kullanıcı kuponları |

Dağıtımda hepsi `FO_STATE_DIR` (Railway volume, 50 GB) altında yaşar; `serve.py:seed_state_dir`
boş volume'u repodaki kopyalarla bir kez tohumlar, araştırma çıktılarını ise imajdaki daha yeniyse
her açılışta günceller.
