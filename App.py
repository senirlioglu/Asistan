import streamlit as st
import re
import urllib.parse
import pandas as pd
import io
import requests
from datetime import datetime

# Sayfa yapılandırması
st.set_page_config(
    page_title="A101 Kampanya Asistanı",
    page_icon="📢",
    layout="wide"
)

# =============================================================================
# CSS STİLLERİ
# =============================================================================
st.markdown("""
<style>
    .main-header {
        text-align: center;
        color: #E31E24;
        font-size: 32px;
        font-weight: bold;
        margin-bottom: 20px;
    }
    .magaza-bandi {
        background-color: #E31E24;
        color: white;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
        font-size: 24px;
        font-weight: bold;
        margin: 20px 0;
        box-shadow: 0 4px 15px rgba(227, 30, 36, 0.3);
    }
    .mesaj-onizleme {
        background-color: #DCF8C6;
        border-radius: 10px;
        padding: 20px;
        font-family: 'Segoe UI', sans-serif;
        font-size: 14px;
        white-space: pre-wrap;
        border-left: 4px solid #25D366;
        margin: 15px 0;
    }
    .uyari-kutusu {
        background-color: #fff3cd;
        border: 1px solid #ffc107;
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
    }
    .hata-kutusu {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
    }
    .basari-kutusu {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
    }
    .secim-rehberi {
        background-color: #e7f3ff;
        border-left: 4px solid #0066cc;
        padding: 15px;
        margin: 15px 0;
        border-radius: 0 8px 8px 0;
    }
    .kontrol-kutusu {
        background-color: #f8f9fa;
        border: 2px solid #dee2e6;
        border-radius: 10px;
        padding: 20px;
        margin: 20px 0;
    }
    .tarih-bilgi {
        background-color: #e8f5e9;
        border-left: 4px solid #4caf50;
        padding: 10px 15px;
        margin: 10px 0;
        border-radius: 0 8px 8px 0;
    }
    .puan-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 12px;
        margin-left: 5px;
    }
    .puan-yuksek {
        background-color: #28a745;
        color: white;
    }
    .puan-orta {
        background-color: #ffc107;
        color: black;
    }
    .puan-dusuk {
        background-color: #dc3545;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# MAĞAZA LİSTESİ
# =============================================================================
MAGAZALAR = {
    "H283": "Fabrikalar Kepez",
    "C820": "Kemerağzı Muratpaşa",
    "J506": "Yahya Kemal Kepez",
    "2454": "Bahçelievler Muratpaşa",
    "B548": "Hamidiye Muratpaşa",
    "0396": "Köroğlu Muratpaşa",
    "F296": "Cahit Sıtkı Muratpaşa",
    "I023": "Balbey Muratpaşa",
    "E180": "Aydınlıkevler Muratpaşa",
    "4282": "Kara Yusuf Kepez",
    "I824": "Yalı Muratpaşa",
    "H519": "Üçyol Kepez",
    "D706": "Suphi Türel Kepez",
    "D587": "Düden Park Muratpaşa",
    "G874": "Mustafa Koç Camii Kepez",
    "1715": "Çağlayan Muratpaşa",
    "C007": "15 Temmuz Kepez",
    "6667": "Hastane Cad Kepez",
    "J218": "15 Katlılar Kepez",
    "1125": "Portakalçiçeği Muratpaşa",
    "C241": "Rasih Kaplan Cd Kepez",
}

WHATSAPP_NUMBER = "905399311842"

# Performans verisi URL'leri (Asistan reposundan)
PERFORMANS_URL_2025 = "https://github.com/senirlioglu/Asistan/raw/main/veri_2025.parquet"

# =============================================================================
# ÜRÜN EMOJİLERİ
# =============================================================================
URUN_EMOJILERI = {
    # Spesifik olanlar önce (uzun kelimeler)
    "EL ARABASI": "🛒", "BUDAMA": "✂️", "AIRFRYER": "🍟", "POWERBANK": "🔋",
    "SWEATSHIRT": "🧥", "NEVRESİM": "🛏️", "BATTANİYE": "🛏️", "ESPRESSO": "☕",
    "BİSİKLET": "🚲", "VANTİLATÖR": "🌀", "BUZDOLABI": "❄️", "DONDURUC": "🧊",
    "MULTIMEDIA": "🎵", "TESTERE": "🪚", "ÇARŞAF": "🛏️",
    # Genel kategoriler
    "TV": "📺", "SÜPÜRGE": "🧹", "KLİMA": "❄️",
    "KAHVE": "☕", "ÇAY": "🍵", "TOST": "🥪", "WAFFLE": "🧇",
    "MİKSER": "🥣", "BLENDER": "🥤", "FRİTÖZ": "🍟",
    "SAÇ": "💇", "ÜTÜ": "👔", "ISITICI": "🔥",
    "KAMP": "⛺", "BAHÇE": "🌿", "MANGAL": "🔥", "ŞEMSİYE": "☂️",
    "ARABA": "🚗", "AKÜLÜ": "🔋", "OYUNCAK": "🧸", "BEBEK": "👶",
    "GÖMLEK": "👔", "EŞOFMAN": "🏃", "PANTOLON": "👖", "MONT": "🧥",
    "PERDE": "🪟", "HALI": "🏠", "DOLAP": "🗄️", "MASA": "🪑", "SANDALYE": "🪑",
    "BARDAK": "🥛", "FİNCAN": "☕", "TABAK": "🍽️", "KAVANOZ": "🫙", "TENCERE": "🍳",
    "TERMOS": "🧊", "SAAT": "⌚", "KAMERA": "📷", "TELEFON": "📱",
    "ÇAPA": "🚜", "MUG": "☕", "SEPETİ": "🧺", "VALIZ": "🧳",
    "KUTU": "📦", "RAF": "📚", "AYNA": "🪞", "LAMBa": "💡",
    "DETERJAN": "🧴", "ŞAMPUAN": "🧴", "HAVLU": "🛁", "YORGAN": "🛏️",
    "BOYA": "🎨", "FIRIN": "🔥", "OCAK": "🔥", "SET": "📦",
    "YASTIK": "🛏️", "PASPAS": "🧹", "POŞET": "🛍️", "ÇÖP": "🗑️",
}

def get_emoji(urun_adi):
    """Ürün adına göre emoji döndür"""
    urun_upper = str(urun_adi).upper()
    for keyword, emoji in URUN_EMOJILERI.items():
        if keyword in urun_upper:
            return emoji
    return "🏷️"

# =============================================================================
# PERFORMANS VERİSİ
# =============================================================================
import os

@st.cache_data(ttl=3600)  # 1 saat cache
def load_performans_data():
    """Performans verilerini yükle - önce yerel, sonra GitHub"""

    # Önce yerel dosyayı dene
    local_path = os.path.join(os.path.dirname(__file__), 'veri_2025.parquet')
    if os.path.exists(local_path):
        try:
            df = pd.read_parquet(local_path)
            return df
        except Exception as e:
            st.warning(f"⚠️ Yerel dosya okunamadı: {str(e)}")

    # Yerel yoksa GitHub'dan çek
    try:
        response = requests.get(PERFORMANS_URL_2025, timeout=30)
        if response.status_code == 200:
            df = pd.read_parquet(io.BytesIO(response.content))
            return df
    except Exception as e:
        st.warning(f"⚠️ Performans verisi yüklenemedi: {str(e)}")
    return None

@st.cache_data(ttl=3600)
def get_urun_mal_grubu_map(_df):
    """Tüm ürünlerin mal gruplarını döndür (ürün kodu -> mal grubu)"""
    if _df is None:
        return {}
    try:
        urun_mg = _df.groupby('Urun_Kod')['Mal_Grubu'].first().to_dict()
        return {str(k): v for k, v in urun_mg.items()}
    except:
        return {}

@st.cache_data(ttl=3600)
def get_nitelikler(_df):
    """Parquet'teki tüm Nitelik değerlerini döndür"""
    if _df is None:
        return []
    try:
        return sorted(_df['Nitelik'].unique().tolist())
    except:
        return []

import math

def calculate_lift_scores(kampanya_urunleri, magaza_kodu, nitelik, df, urun_mal_grubu_map, weights=None):
    """
    Lift bazlı puanlama algoritması
    - Benchmark: Tüm mağazalar (aynı nitelik)
    - Mağaza payı / Benchmark payı = Lift
    - Shrinkage ile düzeltme
    - weights: (fit, disc, save) ağırlıkları - varsayılan (0.65, 0.25, 0.10)
    """
    if df is None or df.empty:
        return kampanya_urunleri, 0

    # Ağırlıklar
    w_fit, w_disc, w_save = weights if weights else (0.65, 0.25, 0.10)

    eps = 1e-6
    # Bugfix 3: Case-insensitive spot tespiti
    k = 200 if "spot" in str(nitelik).lower() else 500

    # Bugfix 1: Urun_Kod'u string'e çevir (tip uyuşmazlığı önleme)
    df = df.copy()
    df['Urun_Kod'] = df['Urun_Kod'].astype(str).str.strip()

    # Mağaza ve Benchmark filtreleme (aynı nitelik)
    store_df = df[(df['Magaza_Kod'].astype(str).str.strip() == str(magaza_kodu).strip()) &
                  (df['Nitelik'] == nitelik)]
    bench_df = df[df['Nitelik'] == nitelik]  # Tüm mağazalar = benchmark

    if store_df.empty:
        # Bu nitelikte mağaza verisi yok, fallback
        return kampanya_urunleri, 0

    # Paydalar (toplam değerler)
    TOTAL_ADET_store = store_df['Adet'].sum()
    TOTAL_CIRO_store = store_df['Ciro'].sum()
    TOTAL_ADET_bench = bench_df['Adet'].sum()
    TOTAL_CIRO_bench = bench_df['Ciro'].sum()

    # Bölgedeki mağaza sayısı (ortalama için)
    n_magaza = bench_df['Magaza_Kod'].nunique()
    n_magaza = max(n_magaza, 1)  # Sıfıra bölme önleme

    # Shrinkage weight
    w = TOTAL_ADET_store / (TOTAL_ADET_store + k)

    # === MAL GRUBU LIFT TABLOSU ===
    mal_grubu_lifts = {}
    for g in df['Mal_Grubu'].unique():
        store_g = store_df[store_df['Mal_Grubu'] == g]
        bench_g = bench_df[bench_df['Mal_Grubu'] == g]

        share_qty_store = (store_g['Adet'].sum() / TOTAL_ADET_store) if TOTAL_ADET_store > 0 else 0
        share_qty_bench = (bench_g['Adet'].sum() / TOTAL_ADET_bench) if TOTAL_ADET_bench > 0 else 0
        share_ciro_store = (store_g['Ciro'].sum() / TOTAL_CIRO_store) if TOTAL_CIRO_store > 0 else 0
        share_ciro_bench = (bench_g['Ciro'].sum() / TOTAL_CIRO_bench) if TOTAL_CIRO_bench > 0 else 0

        lift_qty = (share_qty_store + eps) / (share_qty_bench + eps)
        lift_ciro = (share_ciro_store + eps) / (share_ciro_bench + eps)

        # Shrinkage
        lift_qty_shr = 1 + w * (lift_qty - 1)
        lift_ciro_shr = 1 + w * (lift_ciro - 1)

        mal_grubu_lifts[g] = {'lift_qty': lift_qty_shr, 'lift_ciro': lift_ciro_shr}

    # === SKU LIFT TABLOSU ===
    sku_lifts = {}
    # Key'leri string yap (kampanya ürün kodları string)
    store_sku = {str(k): v for k, v in store_df.groupby('Urun_Kod').agg({'Adet': 'sum', 'Ciro': 'sum'}).to_dict('index').items()}
    bench_sku = {str(k): v for k, v in bench_df.groupby('Urun_Kod').agg({'Adet': 'sum', 'Ciro': 'sum'}).to_dict('index').items()}

    for sku in store_sku.keys():
        share_qty_store = (store_sku[sku]['Adet'] / TOTAL_ADET_store) if TOTAL_ADET_store > 0 else 0
        share_ciro_store = (store_sku[sku]['Ciro'] / TOTAL_CIRO_store) if TOTAL_CIRO_store > 0 else 0

        bench_vals = bench_sku.get(sku, {'Adet': 0, 'Ciro': 0})
        share_qty_bench = (bench_vals['Adet'] / TOTAL_ADET_bench) if TOTAL_ADET_bench > 0 else 0
        share_ciro_bench = (bench_vals['Ciro'] / TOTAL_CIRO_bench) if TOTAL_CIRO_bench > 0 else 0

        lift_qty = (share_qty_store + eps) / (share_qty_bench + eps)
        lift_ciro = (share_ciro_store + eps) / (share_ciro_bench + eps)

        lift_qty_shr = 1 + w * (lift_qty - 1)
        lift_ciro_shr = 1 + w * (lift_ciro - 1)

        sku_lifts[str(sku)] = {'lift_qty': lift_qty_shr, 'lift_ciro': lift_ciro_shr}

    # === KAMPANYA ÜRÜNLERİNİ SKORLA ===
    eslesen_sku = 0

    # Güven eşikleri
    SKU_MIN_STORE = 3    # Mağazada min satış adedi
    SKU_MIN_BENCH = 30   # Bölgede min satış adedi
    GROUP_MIN_SHARE = 0.003  # Mal grubu min pay (%0.3)
    ALPHA_K = 5          # Hiyerarşik blend katsayısı

    for urun in kampanya_urunleri:
        urun_kodu = urun.get('kod', '')
        mal_grubu = urun_mal_grubu_map.get(urun_kodu)

        # İndirim skorları
        try:
            eski_fiyat = float(urun.get('eski_fiyat', '0').replace('.', '').replace(',', '.'))
            yeni_fiyat = float(urun.get('yeni_fiyat', '0').replace('.', '').replace(',', '.'))
            saving_tl = eski_fiyat - yeni_fiyat
        except:
            saving_tl = 0

        discount_pct = urun.get('indirim_num', 0) / 100
        disc_score = min(discount_pct / 0.35, 1)  # %35+ = 1
        save_score = math.log1p(saving_tl) / math.log1p(3000) if saving_tl > 0 else 0
        save_score = min(save_score, 1)  # 3000 TL üstü tasarrufta 1'i aşmasın

        # Değişkenler
        fit = 0
        lift_qty = 1
        lift_ciro = 1
        sku_match = False
        store_qty = 0
        store_ciro = 0
        bench_qty = 0
        bench_ciro = 0
        store_share_qty = 0
        store_share_ciro = 0
        bench_share_qty = 0
        bench_share_ciro = 0

        # Uyarı mesajları
        data_warning = None
        group_warning = None
        score_penalty = 0

        # === MAL GRUBU DEĞERLERİ (her zaman hesapla) ===
        store_group_qty = 0
        store_group_ciro = 0
        store_group_share = 0
        fit_group = 0
        lift_qty_group = 1
        lift_ciro_group = 1

        if mal_grubu and mal_grubu in mal_grubu_lifts:
            store_g = store_df[store_df['Mal_Grubu'] == mal_grubu]
            bench_g = bench_df[bench_df['Mal_Grubu'] == mal_grubu]
            store_group_qty = store_g['Adet'].sum()
            store_group_ciro = store_g['Ciro'].sum()
            store_group_share = (store_group_qty / TOTAL_ADET_store) if TOTAL_ADET_store > 0 else 0

            lift_qty_group = mal_grubu_lifts[mal_grubu]['lift_qty']
            lift_ciro_group = mal_grubu_lifts[mal_grubu]['lift_ciro']
            fit_group = 0.7 * math.log(max(lift_qty_group, 0.01)) + 0.3 * math.log(max(lift_ciro_group, 0.01))

        # === MAL GRUBU VARLIK KAPISI ===
        # Mağaza bu mal grubunu neredeyse hiç satmıyorsa → ceza veya öneri dışı
        if store_group_qty == 0:
            group_warning = "⛔ Mal grubu hiç satılmamış"
            score_penalty = 50  # Ağır ceza
        elif store_group_share < GROUP_MIN_SHARE:
            group_warning = f"⚠️ Mal grubu zayıf (%{store_group_share*100:.2f})"
            score_penalty = 25  # Orta ceza

        # === SKU KONTROLÜ ===
        sku_qty_raw = 0
        bench_qty_raw = 0

        if urun_kodu in sku_lifts:
            sku_qty_raw = store_sku.get(urun_kodu, {}).get('Adet', 0)
            bench_vals = bench_sku.get(urun_kodu, {'Adet': 0, 'Ciro': 0})
            bench_qty_raw = bench_vals['Adet']

            # SKU güven kontrolü
            sku_trusted = (sku_qty_raw >= SKU_MIN_STORE) and (bench_qty_raw >= SKU_MIN_BENCH)

            if sku_trusted:
                # SKU verisi güvenilir → doğrudan kullan
                lift_qty = sku_lifts[urun_kodu]['lift_qty']
                lift_ciro = sku_lifts[urun_kodu]['lift_ciro']
                fit_sku = 0.7 * math.log(max(lift_qty, 0.01)) + 0.3 * math.log(max(lift_ciro, 0.01))
                fit = fit_sku
                sku_match = True
                eslesen_sku += 1

                store_qty = sku_qty_raw
                store_ciro = store_sku.get(urun_kodu, {}).get('Ciro', 0)
                bench_qty = bench_qty_raw
                bench_ciro = bench_vals['Ciro']
            else:
                # SKU verisi yetersiz → Hiyerarşik birleştirme
                alpha = sku_qty_raw / (sku_qty_raw + ALPHA_K)

                lift_qty_sku = sku_lifts[urun_kodu]['lift_qty']
                lift_ciro_sku = sku_lifts[urun_kodu]['lift_ciro']
                fit_sku = 0.7 * math.log(max(lift_qty_sku, 0.01)) + 0.3 * math.log(max(lift_ciro_sku, 0.01))

                # Blend: alpha * SKU + (1-alpha) * Group
                fit = alpha * fit_sku + (1 - alpha) * fit_group
                lift_qty = alpha * lift_qty_sku + (1 - alpha) * lift_qty_group
                lift_ciro = alpha * lift_ciro_sku + (1 - alpha) * lift_ciro_group

                sku_match = True  # SKU var ama düşük güvenle
                eslesen_sku += 1
                data_warning = f"⚠️ Düşük veri ({sku_qty_raw} adet), grup profili ağırlıklı"

                # Gösterim için mal grubu değerlerini kullan
                store_qty = store_group_qty
                store_ciro = store_group_ciro
                bench_qty = bench_g['Adet'].sum() if mal_grubu else 0
                bench_ciro = bench_g['Ciro'].sum() if mal_grubu else 0

        elif mal_grubu and mal_grubu in mal_grubu_lifts:
            # SKU yok → Mal grubu kullan
            lift_qty = lift_qty_group
            lift_ciro = lift_ciro_group
            fit = fit_group

            store_qty = store_group_qty
            store_ciro = store_group_ciro
            bench_qty = bench_g['Adet'].sum()
            bench_ciro = bench_g['Ciro'].sum()

        # Pay yüzdeleri
        store_share_qty = (store_qty / TOTAL_ADET_store * 100) if TOTAL_ADET_store > 0 else 0
        store_share_ciro = (store_ciro / TOTAL_CIRO_store * 100) if TOTAL_CIRO_store > 0 else 0
        bench_share_qty = (bench_qty / TOTAL_ADET_bench * 100) if TOTAL_ADET_bench > 0 else 0
        bench_share_ciro = (bench_ciro / TOTAL_CIRO_bench * 100) if TOTAL_CIRO_bench > 0 else 0

        # Final skor: 0.65*fit + 0.25*disc + 0.10*save
        fit_normalized = (fit + 2) / 4  # -2,+2 -> 0,1
        fit_normalized = max(0, min(1, fit_normalized))

        score = w_fit * fit_normalized + w_disc * disc_score + w_save * save_score
        score_100 = round(score * 100, 1)

        # Mal grubu cezası uygula
        score_100 = max(0, score_100 - score_penalty)

        # Sonuçları ürüne ekle
        urun['magaza_skor'] = score_100
        urun['genel_skor'] = round((0.60 * disc_score + 0.25 * fit_normalized + 0.15 * save_score) * 100, 1)
        urun['puan_detay'] = {
            'mal_grubu_adi': mal_grubu or 'Yeni Ürün',
            'lift_qty': round(lift_qty, 2),
            'lift_ciro': round(lift_ciro, 2),
            'disc_score': round(disc_score * 100, 1),
            'save_score': round(save_score * 100, 1),
            'fit': round(fit, 3),
            'sku_match': sku_match,
            # Ham değerler
            'store_qty': round(store_qty),
            'store_ciro': round(store_ciro),
            'bench_qty': round(bench_qty),
            'bench_ciro': round(bench_ciro),
            # Pay yüzdeleri
            'store_share_qty': round(store_share_qty, 2),
            'store_share_ciro': round(store_share_ciro, 2),
            'bench_share_qty': round(bench_share_qty, 2),
            'bench_share_ciro': round(bench_share_ciro, 2),
            # Uyarılar
            'data_warning': data_warning,
            'group_warning': group_warning,
            'sku_qty_raw': sku_qty_raw if urun_kodu in sku_lifts else None
        }

    return kampanya_urunleri, eslesen_sku

def apply_diversity_filter(urunler, max_per_group=2, top_n=10):
    """İlk N öneride aynı mal grubundan max X ürün"""
    sorted_urunler = sorted(urunler, key=lambda x: x.get('magaza_skor', 0), reverse=True)

    result = []
    group_count = {}

    for urun in sorted_urunler:
        mal_grubu = urun.get('puan_detay', {}).get('mal_grubu_adi', 'Yeni Ürün')

        if len(result) < top_n:
            # İlk 10 için çeşitlilik kuralı uygula
            if group_count.get(mal_grubu, 0) < max_per_group:
                result.append(urun)
                group_count[mal_grubu] = group_count.get(mal_grubu, 0) + 1
        else:
            # Geri kalanı direkt ekle
            result.append(urun)

    # Çeşitlilik nedeniyle atlananları sona ekle
    for urun in sorted_urunler:
        if urun not in result:
            result.append(urun)

    return result

def get_puan_badge(puan):
    """Puana göre badge HTML döndür"""
    if puan >= 60:
        return f'<span class="puan-badge puan-yuksek">⭐ {puan}</span>'
    elif puan >= 35:
        return f'<span class="puan-badge puan-orta">📊 {puan}</span>'
    else:
        return f'<span class="puan-badge puan-dusuk">📉 {puan}</span>'

# =============================================================================
# MAİL PARSER - Workflow Formatı
# =============================================================================
def parse_kampanya_maili(mail_text):
    """Workflow kampanya mailini parse et - hem satır hem tablo formatı destekler"""

    result = {
        'baslangic': None,
        'bitis': None,
        'onaylayan': None,
        'urunler': [],
        'hatalar': [],
        'uyarilar': []
    }

    lines = mail_text.strip().split('\n')
    lines = [line.strip() for line in lines if line.strip()]

    # Tarihleri bul
    for i, line in enumerate(lines):
        # Aynı satırda tarih olabilir
        if 'Başlangıç' in line:
            tarih_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', line)
            if tarih_match:
                result['baslangic'] = tarih_match.group(1)
            elif i + 1 < len(lines):
                tarih_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', lines[i + 1])
                if tarih_match:
                    result['baslangic'] = tarih_match.group(1)

        if 'Bitiş' in line:
            tarih_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', line)
            if tarih_match:
                result['bitis'] = tarih_match.group(1)
            elif i + 1 < len(lines):
                tarih_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', lines[i + 1])
                if tarih_match:
                    result['bitis'] = tarih_match.group(1)

        if 'Onaylayan' in line:
            # Aynı satırda isim olabilir
            onay_match = re.search(r'Onaylayan.*?([A-ZÇĞİÖŞÜa-zçğıöşü\s]+)\(', line)
            if onay_match:
                result['onaylayan'] = onay_match.group(1).strip()
            elif i + 1 < len(lines):
                result['onaylayan'] = lines[i + 1]

    # Ürünleri parse et - TAB-SEPARATED TABLO FORMATI
    # Format: Ürün Kodu | Ürün Adı | Satış Fiyatı | Tanıtım Fiyatı | İndirim Oranı
    for line in lines:
        # Tab veya çoklu boşlukla ayrılmış satırlar
        parts = re.split(r'\t+|\s{2,}', line)

        # 8 haneli ürün kodu ile başlayan satır
        if parts and re.match(r'^\d{8}$', parts[0].strip()):
            urun = {
                'kod': parts[0].strip(),
                'ad': '',
                'eski_fiyat': '',
                'yeni_fiyat': '',
                'indirim': '',
                'indirim_num': 0
            }

            # Satırdaki parçaları işle
            for part in parts[1:]:
                part = part.strip()
                if not part:
                    continue

                # Fiyat kontrolü (₺149,00 veya 149,00₺ veya 149,00)
                fiyat_match = re.search(r'₺?\s*([\d.,]+)\s*₺?', part)

                if '%' in part:
                    # İndirim oranı
                    indirim_match = re.search(r'%?\s*([\d.,]+)\s*%?', part)
                    if indirim_match:
                        indirim_str = indirim_match.group(1).replace(',', '.')
                        urun['indirim'] = indirim_str
                        try:
                            urun['indirim_num'] = float(indirim_str)
                        except:
                            pass
                elif '₺' in part and fiyat_match:
                    # Fiyat
                    fiyat_str = fiyat_match.group(1)
                    if not urun['eski_fiyat']:
                        urun['eski_fiyat'] = fiyat_str
                    elif not urun['yeni_fiyat']:
                        urun['yeni_fiyat'] = fiyat_str
                elif not urun['ad'] and not re.match(r'^[\d.,₺%\s]+$', part):
                    # Ürün adı (sayı/fiyat/yüzde içermeyen)
                    urun['ad'] = part

            # Ürün geçerliyse ekle
            if urun['ad'] and (urun['yeni_fiyat'] or urun['eski_fiyat']):
                # Fiyat kontrolü
                if urun['eski_fiyat'] and urun['yeni_fiyat']:
                    try:
                        eski = float(urun['eski_fiyat'].replace('.', '').replace(',', '.'))
                        yeni = float(urun['yeni_fiyat'].replace('.', '').replace(',', '.'))
                        if yeni > eski:
                            result['uyarilar'].append(f"⚠️ {urun['ad'][:30]}: Yeni fiyat eskisinden yüksek!")
                    except:
                        pass
                result['urunler'].append(urun)
                continue

    # Eski format desteği (satır satır ayrılmış)
    if not result['urunler']:
        i = 0
        while i < len(lines):
            line = lines[i]

            # 8 haneli ürün kodu bul (tek başına satırda)
            if re.match(r'^\d{8}$', line):
                urun = {
                    'kod': line,
                    'ad': '',
                    'eski_fiyat': '',
                    'yeni_fiyat': '',
                    'indirim': '',
                    'indirim_num': 0
                }

                # Sonraki satırları oku
                j = i + 1
                while j < len(lines) and j < i + 5:
                    next_line = lines[j]

                    # Fiyat regex
                    fiyat_pattern = r'[₺]?\s*([\d.,]+)\s*(?:₺|TL)?'
                    fiyat_match = re.match(fiyat_pattern, next_line.replace(' ', ''))
                    is_indirim = '%' in next_line

                    if fiyat_match and ('₺' in next_line or 'TL' in next_line):
                        fiyat_str = fiyat_match.group(1)
                        if not urun['eski_fiyat']:
                            urun['eski_fiyat'] = fiyat_str
                        elif not urun['yeni_fiyat']:
                            urun['yeni_fiyat'] = fiyat_str
                    elif is_indirim:
                        indirim_match = re.search(r'([\d.,]+)', next_line)
                        if indirim_match:
                            indirim_str = indirim_match.group(1).replace(',', '.')
                            urun['indirim'] = indirim_str
                            try:
                                urun['indirim_num'] = float(indirim_str)
                            except:
                                pass
                    elif not urun['ad'] and not ('₺' in next_line or 'TL' in next_line or '%' in next_line):
                        urun['ad'] = next_line

                    j += 1

                if urun['ad'] and urun['yeni_fiyat']:
                    result['urunler'].append(urun)

                i = j
            else:
                i += 1

    if not result['baslangic'] or not result['bitis']:
        result['uyarilar'].append("⚠️ Kampanya tarihleri bulunamadı, manuel kontrol edin.")

    if not result['urunler']:
        result['hatalar'].append("🔴 Hiç ürün bulunamadı! Mail formatını kontrol edin.")

    return result

# =============================================================================
# MESAJ FORMATLAMA
# =============================================================================
def format_whatsapp_mesaji(magaza_adi, secili_urunler, bitis_tarihi, toplam_urun_sayisi=None):
    """WhatsApp mesajı oluştur"""

    secili_sayi = len(secili_urunler)

    mesaj = f"🛒 A101 {magaza_adi}\n\n"

    # Başlık
    if toplam_urun_sayisi:
        mesaj += f"🔥 BUGÜNE ÖZEL – {toplam_urun_sayisi} üründe indirim var!\n"
    else:
        mesaj += "🔥 BUGÜNE ÖZEL!\n"

    mesaj += f"⭐ Aşağıdakiler öne çıkan {secili_sayi} fırsat:\n\n"

    # Ürünler
    for urun in secili_urunler:
        emoji = get_emoji(urun['ad'])
        ad_kisa = urun['ad'][:40] if len(urun['ad']) <= 40 else urun['ad'][:37] + "..."

        mesaj += f"{emoji} {ad_kisa}\n"
        mesaj += f"✅ {urun['yeni_fiyat']}₺"
        if urun.get('eski_fiyat'):
            mesaj += f" | Eski: {urun['eski_fiyat']}₺"
        if urun.get('indirim'):
            mesaj += f" (%{urun['indirim']} İNDİRİM)"
        mesaj += "\n\n"

    # Alt bilgi
    mesaj += f"📅 Son gün: {bitis_tarihi} | 📍 Stoklarla sınırlıdır\n\n"
    mesaj += "Listeden çıkmak için ÇIKIŞ yazın."

    return mesaj

# =============================================================================
# ANA UYGULAMA
# =============================================================================

st.markdown('<p class="main-header">📢 A101 Kampanya Asistanı</p>', unsafe_allow_html=True)

# =============================================================================
# MOD SEÇİMİ
# =============================================================================
mod_secim = st.radio(
    "Ne yapmak istiyorsunuz?",
    options=["📨 Mesaj Oluşturucu", "📊 Kampanya Oluşturucu"],
    horizontal=True,
    key="mod_secim",
    help="Mesaj Oluşturucu: Mevcut kampanya için müşteri mesajı oluşturur. Kampanya Oluşturucu: Stok verilerine göre hangi ürünlere kampanya yapılmalı önerir."
)

st.markdown("---")

# =============================================================================
# MESAJ OLUŞTURUCU MODU
# =============================================================================
if mod_secim == "📨 Mesaj Oluşturucu":
    # =============================================================================
    # ADIM 1: MAĞAZA SEÇİMİ
    # =============================================================================
    st.markdown("### 1️⃣ Mağaza Seçimi")

    magaza_secim = st.selectbox(
        "Mağazanızı seçin:",
        options=[""] + [f"{kod} - {ad}" for kod, ad in MAGAZALAR.items()],
        key="magaza_select"
    )

    if magaza_secim:
        magaza_kodu = magaza_secim.split(" - ")[0]
        magaza_adi = MAGAZALAR[magaza_kodu]

        # Mağaza bandı
        st.markdown(f'''
            <div class="magaza-bandi">
                🏪 {magaza_kodu} - {magaza_adi.upper()}
            </div>
        ''', unsafe_allow_html=True)

        st.info(f"📱 WhatsApp liste adı: **{magaza_kodu}_MUSTERI**")

        # Performans verisini yükle
        with st.spinner("📊 Satış performansı yükleniyor..."):
            performans_df = load_performans_data()
            urun_mal_grubu_map = get_urun_mal_grubu_map(performans_df)
            nitelikler = get_nitelikler(performans_df)

        if performans_df is not None:
            st.success("✅ Performans verisi yüklendi - Akıllı puanlama aktif!")

            # Nitelik seçimi
            st.markdown("### 📊 Kampanya Niteliği")
            # Varsayılan olarak Spot seçili gelsin
            default_nitelik = "Spot" if "Spot" in nitelikler else (nitelikler[0] if nitelikler else None)
            default_index = nitelikler.index(default_nitelik) if default_nitelik in nitelikler else 0

            nitelik_secim = st.selectbox(
                "Kampanya niteliğini seçin:",
                options=nitelikler,
                index=default_index,
                key="nitelik_select",
                help="Kampanya türüne göre seçin. Genellikle 'Spot' kullanılır."
            )

            # Skor ağırlıkları (gelişmiş ayarlar)
            with st.expander("⚙️ Skor Ağırlıkları (Gelişmiş)"):
                st.caption("Varsayılan değerler önerilir. Değiştirmek isterseniz ayarlayın.")
                col_w1, col_w2, col_w3 = st.columns(3)
                with col_w1:
                    weight_fit = st.slider("Müşteri Uyumu", 0, 100, 65, 5, key="w_fit", help="Lift bazlı uyum skoru") / 100
                with col_w2:
                    weight_disc = st.slider("İndirim", 0, 100, 25, 5, key="w_disc", help="İndirim oranı skoru") / 100
                with col_w3:
                    weight_save = st.slider("Tasarruf", 0, 100, 10, 5, key="w_save", help="TL bazlı tasarruf") / 100

                # Normalize et (toplamı 1 yap)
                total_weight = weight_fit + weight_disc + weight_save
                if total_weight > 0:
                    weight_fit = weight_fit / total_weight
                    weight_disc = weight_disc / total_weight
                    weight_save = weight_save / total_weight
                st.caption(f"Normalize: Uyum {weight_fit:.0%} | İndirim {weight_disc:.0%} | Tasarruf {weight_save:.0%}")
        else:
            st.warning("⚠️ Performans verisi bulunamadı - Sadece indirim bazlı sıralama yapılacak")
            nitelik_secim = None

        st.markdown("---")

        # =============================================================================
        # ADIM 2: KAMPANYA MAİLİ YAPIŞTIR
        # =============================================================================
        st.markdown("### 2️⃣ Kampanya Mailini Yapıştırın")

        st.markdown("""
        <div class="secim-rehberi">
            <strong>📋 Nasıl yapılır:</strong><br>
            1. Workflow'dan gelen kampanya onay mailini açın<br>
            2. <strong>Ctrl+A</strong> (tümünü seç) → <strong>Ctrl+C</strong> (kopyala)<br>
            3. Aşağıdaki alana <strong>Ctrl+V</strong> (yapıştır)
        </div>
        """, unsafe_allow_html=True)

        mail_icerik = st.text_area(
            "Kampanya mailini buraya yapıştırın:",
            height=200,
            placeholder="Mağaza Bölgesel Tanıtım Sonucu\n\nTanıtım Başlangıç Tarihi\n20.12.2025\n..."
        )

        if mail_icerik:
            # Parse et
            kampanya = parse_kampanya_maili(mail_icerik)

            # Hataları göster
            if kampanya['hatalar']:
                for hata in kampanya['hatalar']:
                    st.error(hata)
                st.stop()

            # Ürünleri puanla (Lift bazlı algoritma)
            if nitelik_secim and performans_df is not None:
                # Ağırlıkları session_state'den al
                w_fit = st.session_state.get('w_fit', 65) / 100
                w_disc = st.session_state.get('w_disc', 25) / 100
                w_save = st.session_state.get('w_save', 10) / 100
                # Normalize et
                total_w = w_fit + w_disc + w_save
                if total_w > 0:
                    weights = (w_fit/total_w, w_disc/total_w, w_save/total_w)
                else:
                    weights = (0.65, 0.25, 0.10)

                kampanya['urunler'], eslesen_sku = calculate_lift_scores(
                    kampanya['urunler'],
                    magaza_kodu,
                    nitelik_secim,
                    performans_df,
                    urun_mal_grubu_map,
                    weights=weights
                )
            else:
                eslesen_sku = 0
                # Fallback: sadece indirim bazlı
                for urun in kampanya['urunler']:
                    disc = urun.get('indirim_num', 0) / 100
                    urun['magaza_skor'] = round(min(disc / 0.35, 1) * 100, 1)
                    urun['genel_skor'] = urun['magaza_skor']
                    urun['puan_detay'] = {'mal_grubu_adi': urun_mal_grubu_map.get(urun.get('kod', ''), 'Yeni Ürün')}

            # Eşleşme sayısını hesapla
            toplam_urun = len(kampanya['urunler'])
            eslesen_mg = sum(1 for u in kampanya['urunler']
                              if u.get('puan_detay', {}).get('mal_grubu_adi')
                              and u.get('puan_detay', {}).get('mal_grubu_adi') != 'Yeni Ürün')

            # Başarı mesajı
            st.markdown(f'''
                <div class="basari-kutusu">
                    <strong>✅ {toplam_urun} ürün okundu ve puanlandı</strong><br>
                    📊 SKU eşleşmesi: <strong>{eslesen_sku}/{toplam_urun}</strong> |
                    Mal grubu eşleşmesi: <strong>{eslesen_mg}/{toplam_urun}</strong>
                </div>
            ''', unsafe_allow_html=True)

            # Tarih bilgisi
            if kampanya['baslangic'] and kampanya['bitis']:
                st.markdown(f'''
                    <div class="tarih-bilgi">
                        📅 <strong>Kampanya:</strong> {kampanya['baslangic']} - {kampanya['bitis']}
                    </div>
                ''', unsafe_allow_html=True)

            # Uyarıları göster
            if kampanya['uyarilar']:
                with st.expander(f"⚠️ {len(kampanya['uyarilar'])} Uyarı", expanded=False):
                    for uyari in kampanya['uyarilar']:
                        st.warning(uyari)

            st.markdown("---")

            # =============================================================================
            # ADIM 3: ÜRÜN SEÇİMİ (İKİ SIRALAMA)
            # =============================================================================
            st.markdown("### 3️⃣ Ürün Seçimi")

            # En iyi 5 öneri butonu
            col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
            with col_btn1:
                if st.button("🎯 En İyi 5 Öneri", type="primary", use_container_width=True):
                    top5 = apply_diversity_filter(kampanya['urunler'], max_per_group=2, top_n=5)
                    st.session_state['auto_selected'] = [u['kod'] for u in top5]
                    st.rerun()
            with col_btn2:
                if st.button("🔄 Seçimleri Temizle", use_container_width=True):
                    st.session_state['auto_selected'] = []
                    st.rerun()

            # Otomatik seçim listesi
            auto_selected = st.session_state.get('auto_selected', [])

            # İki tab ile iki farklı sıralama
            tab_magaza, tab_genel = st.tabs([
                f"🏪 {magaza_adi} İçin Önerilen",
                "📊 Genel Öneri (İndirim Bazlı)"
            ])

            secili_urunler = []

            with tab_magaza:
                st.markdown(f"""
                <div class="secim-rehberi">
                    <strong>🏪 Mağaza Bazlı Puanlama (Lift Algoritması):</strong><br>
                    Nitelik: <strong>{nitelik_secim or '-'}</strong> | Benchmark: Tüm Mağazalar<br>
                    • Müşteri Uyumu (65%) - Lift: Mağaza payı / Bölge payı<br>
                    • İndirim Çekiciliği (25%) - %35+ = maksimum<br>
                    • Tasarruf (10%) - TL bazlı (log normalize)<br><br>
                    🟢 60+ Çok İyi | 🟡 35-60 Orta | 🔴 35- Düşük
                </div>
                """, unsafe_allow_html=True)

                # Mağaza skoruna göre sırala + çeşitlilik filtresi
                urunler_magaza = apply_diversity_filter(kampanya['urunler'], max_per_group=2, top_n=10)

                # Güvenilir ve düşük güvenli ürünleri ayır
                urunler_guvenilir = [u for u in urunler_magaza if not u.get('puan_detay', {}).get('group_warning')]
                urunler_dusuk_guven = [u for u in urunler_magaza if u.get('puan_detay', {}).get('group_warning')]

                # Önce güvenilir ürünler
                for urun in urunler_guvenilir:
                    col1, col2, col3 = st.columns([1, 17, 4])

                    with col1:
                        default_val = urun['kod'] in auto_selected
                        secili = st.checkbox("", key=f"m_{urun['kod']}", value=default_val, label_visibility="collapsed")
                        if secili and urun not in secili_urunler:
                            secili_urunler.append(urun)

                    with col2:
                        emoji = get_emoji(urun['ad'])
                        puan = urun.get('magaza_skor', 0)
                        puan_badge = get_puan_badge(puan)
                        detay = urun.get('puan_detay', {})
                        mal_grubu = detay.get('mal_grubu_adi', '-')
                        sku_icon = "🎯" if detay.get('sku_match') else ""
                        st.markdown(
                            f"{emoji} **{urun['ad'][:40]}** | _{mal_grubu}_ {sku_icon} → {urun['yeni_fiyat']}₺ ~~{urun['eski_fiyat']}₺~~ {puan_badge}",
                            unsafe_allow_html=True
                        )

                    with col3:
                        with st.popover("📊 Detay"):
                            st.write(f"**Mal Grubu:** {mal_grubu}")
                            # Uyarılar
                            if detay.get('group_warning'):
                                st.warning(detay.get('group_warning'))
                            if detay.get('data_warning'):
                                st.info(detay.get('data_warning'))
                            st.markdown("---")
                            st.write("**📦 ADET**")
                            sku_raw = detay.get('sku_qty_raw')
                            if sku_raw is not None:
                                st.write(f"SKU Satış: {sku_raw} adet")
                            st.write(f"Mağaza: {detay.get('store_qty', 0):,} | Pay: %{detay.get('store_share_qty', 0):.2f}")
                            st.write(f"Bölge: {detay.get('bench_qty', 0):,} | Pay: %{detay.get('bench_share_qty', 0):.2f}")
                            st.write(f"**Lift: {detay.get('lift_qty', 1):.2f}x**")
                            st.markdown("---")
                            st.write("**💰 CİRO**")
                            st.write(f"Mağaza: {detay.get('store_ciro', 0):,}₺ | Pay: %{detay.get('store_share_ciro', 0):.2f}")
                            st.write(f"Bölge: {detay.get('bench_ciro', 0):,}₺ | Pay: %{detay.get('bench_share_ciro', 0):.2f}")
                            st.write(f"**Lift: {detay.get('lift_ciro', 1):.2f}x**")
                            st.markdown("---")
                            st.write(f"🏷️ İndirim: {detay.get('disc_score', 0):.0f} | 💵 Tasarruf: {detay.get('save_score', 0):.0f}")
                            st.write(f"🔍 SKU Eşleşme: {'✅' if detay.get('sku_match') else '❌'}")
                            st.markdown("---")
                            st.caption("ℹ️ Lift = Mağaza payı / Bölge payı")
                            st.caption("SKU az satıldıysa grup profili ağırlıklı hesaplanır")

                # Düşük güvenli ürünler (varsa)
                if urunler_dusuk_guven:
                    with st.expander(f"⚠️ Düşük Güvenli Ürünler ({len(urunler_dusuk_guven)} adet)", expanded=False):
                        st.caption("Bu ürünler mağazada zayıf kategorilerden. Dikkatli değerlendirin.")
                        for urun in urunler_dusuk_guven:
                            col1, col2, col3 = st.columns([1, 17, 4])
                            with col1:
                                default_val = urun['kod'] in auto_selected
                                secili = st.checkbox("", key=f"ml_{urun['kod']}", value=default_val, label_visibility="collapsed")
                                if secili and urun not in secili_urunler:
                                    secili_urunler.append(urun)
                            with col2:
                                emoji = get_emoji(urun['ad'])
                                puan = urun.get('magaza_skor', 0)
                                puan_badge = get_puan_badge(puan)
                                detay = urun.get('puan_detay', {})
                                mal_grubu = detay.get('mal_grubu_adi', '-')
                                warning = detay.get('group_warning', '')
                                st.markdown(
                                    f"⚠️ {emoji} **{urun['ad'][:35]}** | _{mal_grubu}_ → {urun['yeni_fiyat']}₺ {puan_badge}",
                                    unsafe_allow_html=True
                                )
                                st.caption(warning)

            with tab_genel:
                st.markdown("""
                <div class="secim-rehberi">
                    <strong>📊 Genel Puanlama (İndirim Ağırlıklı):</strong><br>
                    Bu sıralama <strong>indirim oranına</strong> göre yapılmıştır.<br>
                    • İndirim Oranı (60%)<br>
                    • Müşteri Uyumu (25%)<br>
                    • Tasarruf (15%)<br><br>
                    🟢 60+ Çok İyi | 🟡 35-60 Orta | 🔴 35- Düşük
                </div>
                """, unsafe_allow_html=True)

                # Genel skora göre sırala
                urunler_genel = sorted(kampanya['urunler'], key=lambda x: x.get('genel_skor', 0), reverse=True)

                for urun in urunler_genel:
                    col1, col2, col3 = st.columns([1, 17, 4])

                    with col1:
                        default_val = urun['kod'] in auto_selected
                        secili = st.checkbox("", key=f"g_{urun['kod']}", value=default_val, label_visibility="collapsed")
                        if secili and urun not in secili_urunler:
                            secili_urunler.append(urun)

                    with col2:
                        emoji = get_emoji(urun['ad'])
                        puan = urun.get('genel_skor', 0)
                        puan_badge = get_puan_badge(puan)
                        detay = urun.get('puan_detay', {})
                        mal_grubu = detay.get('mal_grubu_adi', '-')
                        st.markdown(
                            f"{emoji} **{urun['ad'][:40]}** | _{mal_grubu}_ → {urun['yeni_fiyat']}₺ ~~{urun['eski_fiyat']}₺~~ | %{urun['indirim']} {puan_badge}",
                            unsafe_allow_html=True
                        )

                    with col3:
                        with st.popover("📊 Detay"):
                            st.write(f"**Mal Grubu:** {mal_grubu}")
                            # Uyarılar
                            if detay.get('group_warning'):
                                st.warning(detay.get('group_warning'))
                            if detay.get('data_warning'):
                                st.info(detay.get('data_warning'))
                            st.markdown("---")
                            st.write("**📦 ADET**")
                            sku_raw = detay.get('sku_qty_raw')
                            if sku_raw is not None:
                                st.write(f"SKU Satış: {sku_raw} adet")
                            st.write(f"Mağaza: {detay.get('store_qty', 0):,} | Pay: %{detay.get('store_share_qty', 0):.2f}")
                            st.write(f"Bölge: {detay.get('bench_qty', 0):,} | Pay: %{detay.get('bench_share_qty', 0):.2f}")
                            st.write(f"**Lift: {detay.get('lift_qty', 1):.2f}x**")
                            st.markdown("---")
                            st.write("**💰 CİRO**")
                            st.write(f"Mağaza: {detay.get('store_ciro', 0):,}₺ | Pay: %{detay.get('store_share_ciro', 0):.2f}")
                            st.write(f"Bölge: {detay.get('bench_ciro', 0):,}₺ | Pay: %{detay.get('bench_share_ciro', 0):.2f}")
                            st.write(f"**Lift: {detay.get('lift_ciro', 1):.2f}x**")
                            st.markdown("---")
                            st.write(f"🏷️ İndirim: {detay.get('disc_score', 0):.0f} | 💵 Tasarruf: {detay.get('save_score', 0):.0f}")
                            st.write(f"🔍 SKU Eşleşme: {'✅' if detay.get('sku_match') else '❌'}")
                            st.markdown("---")
                            st.caption("ℹ️ Lift = Mağaza payı / Bölge payı")
                            st.caption("SKU az satıldıysa grup profili ağırlıklı hesaplanır")

            # Seçim kontrolü
            secili_sayi = len(secili_urunler)

            if secili_sayi > 0:
                if secili_sayi < 3:
                    st.warning(f"⚠️ {secili_sayi} ürün seçildi. En az 3 ürün önerilir.")
                elif secili_sayi > 5:
                    st.warning(f"⚠️ {secili_sayi} ürün seçildi. En fazla 5 ürün önerilir.")
                else:
                    st.success(f"✅ {secili_sayi} ürün seçildi")

                st.markdown("---")

                # =============================================================================
                # ADIM 4: STOK KONTROLÜ
                # =============================================================================
                st.markdown("### 4️⃣ Stok Kontrolü")

                stok_onay = st.checkbox(
                    f"✅ Seçtiğim {secili_sayi} ürün **{magaza_adi}** mağazasında STOKTA VAR",
                    key="stok_onay"
                )

                st.markdown("---")

                # =============================================================================
                # ADIM 5: MESAJ ÖNİZLEME VE GÖNDERME
                # =============================================================================
                st.markdown("### 5️⃣ Mesaj Önizleme ve Gönderme")

                # Mesajı oluştur
                bitis = kampanya['bitis'] or "Stoklarla sınırlı"
                toplam_urun = len(kampanya['urunler'])
                mesaj = format_whatsapp_mesaji(magaza_adi, secili_urunler, bitis, toplam_urun)

                st.markdown("**Mesaj önizleme:**")
                st.markdown(f'<div class="mesaj-onizleme">{mesaj}</div>', unsafe_allow_html=True)

                # Kopyalanabilir metin
                with st.expander("📋 Kopyalamak için tıklayın"):
                    st.code(mesaj, language=None)
                    st.caption("👆 Sağ üst köşedeki kopyala ikonuna tıklayın")

                # Kontroller
                st.markdown("---")
                st.markdown('<div class="kontrol-kutusu">', unsafe_allow_html=True)
                st.markdown("### ⚠️ Gönderim Öncesi Kontrol")

                kontrol1 = st.checkbox(
                    f"✅ Bu mesaj **{magaza_kodu} - {magaza_adi}** için hazırlandı",
                    key="kontrol1"
                )

                kontrol2 = st.checkbox(
                    f"✅ Tarih ({bitis}) ve fiyatlar doğru",
                    key="kontrol2"
                )

                st.markdown('</div>', unsafe_allow_html=True)

                # WhatsApp butonu
                if stok_onay and kontrol1 and kontrol2:
                    encoded_mesaj = urllib.parse.quote(mesaj)
                    whatsapp_link = f"https://wa.me/{WHATSAPP_NUMBER}?text={encoded_mesaj}"

                    st.markdown(f'''
                        <a href="{whatsapp_link}" target="_blank" style="
                            display: block;
                            background-color: #25D366;
                            color: white;
                            padding: 20px 40px;
                            text-decoration: none;
                            border-radius: 10px;
                            font-size: 20px;
                            font-weight: bold;
                            text-align: center;
                            margin-top: 20px;
                            box-shadow: 0 4px 15px rgba(37, 211, 102, 0.4);
                        ">
                            💬 WhatsApp'ta Gönder
                        </a>
                    ''', unsafe_allow_html=True)

                    st.info(f"👆 Butona tıklayınca WhatsApp açılacak. **{magaza_kodu}_MUSTERI** listesini seçip gönderin.")
                else:
                    st.markdown('''
                        <div style="
                            display: block;
                            background-color: #ccc;
                            color: #666;
                            padding: 20px 40px;
                            border-radius: 10px;
                            font-size: 20px;
                            font-weight: bold;
                            text-align: center;
                            margin-top: 20px;
                        ">
                            💬 WhatsApp'ta Gönder
                        </div>
                    ''', unsafe_allow_html=True)
                    st.warning("☝️ Yukarıdaki tüm kontrolleri tamamlayın.")

    else:
        st.info("👆 Önce mağazanızı seçin.")

# =============================================================================
# KAMPANYA OLUŞTURUCU MODU
# =============================================================================
else:  # mod_secim == "📊 Kampanya Oluşturucu"
    st.markdown("""
    <div class="secim-rehberi">
        <strong>📊 Kampanya Oluşturucu Nasıl Çalışır?</strong><br>
        1. Stok Excel dosyasını yükleyin<br>
        2. SM/BS/Mağaza filtreleri ile hedef mağazaları seçin<br>
        3. Sistem, lift algoritmasıyla hangi ürünlere kampanya yapılmalı önerir<br>
        4. Önerilen ürünleri Excel olarak indirin ve fiyatları belirleyin
    </div>
    """, unsafe_allow_html=True)

    # =============================================================================
    # ADIM 1: EXCEL YÜKLEME
    # =============================================================================
    st.markdown("### 1️⃣ Stok Verisini Yükleyin")

    uploaded_file = st.file_uploader(
        "Stok Excel dosyasını yükleyin (.xlsx)",
        type=['xlsx'],
        key="stok_excel_upload",
        help="Kolonlar: SM, BS, Kod, Mağaza Adı, Ürün Kodu, Ürün Tanımı, Stok, Alış, Satış Fiyatı, Marj, KDV, yeni fiyat, yeni marj, Stok TL"
    )

    if uploaded_file is not None:
        try:
            # Excel'i oku
            stok_df = pd.read_excel(uploaded_file)

            # Kolon isimlerini normalize et (boşlukları temizle)
            stok_df.columns = stok_df.columns.str.strip()

            # Gerekli kolonları kontrol et
            gerekli_kolonlar = ['Kod', 'Mağaza Adı', 'Ürün Kodu', 'Ürün Tanımı', 'Stok', 'Satış Fiyatı']
            eksik_kolonlar = [k for k in gerekli_kolonlar if k not in stok_df.columns]

            if eksik_kolonlar:
                st.error(f"❌ Eksik kolonlar: {', '.join(eksik_kolonlar)}")
                st.info("Beklenen kolonlar: SM, BS, Kod, Mağaza Adı, Ürün Kodu, Ürün Tanımı, Stok, Alış, Satış Fiyatı, Marj, KDV...")
            else:
                st.success(f"✅ {len(stok_df):,} satır yüklendi")

                # Önizleme
                with st.expander("📋 Veri Önizleme (ilk 10 satır)"):
                    st.dataframe(stok_df.head(10))

                st.markdown("---")

                # =============================================================================
                # ADIM 2: FİLTRELEME (SM → BS → MAĞAZA)
                # =============================================================================
                st.markdown("### 2️⃣ Mağaza Filtresi")

                # SM listesi
                sm_listesi = ["Tümü"] + sorted(stok_df['SM'].dropna().unique().tolist()) if 'SM' in stok_df.columns else ["Tümü"]

                col_sm, col_bs = st.columns(2)

                with col_sm:
                    secili_sm = st.multiselect(
                        "SM Seçin (opsiyonel):",
                        options=sm_listesi[1:],  # "Tümü" hariç
                        key="sm_secim",
                        help="Boş bırakırsanız tüm SM'ler dahil edilir"
                    )

                # BS listesini SM'e göre filtrele
                if secili_sm and 'BS' in stok_df.columns:
                    bs_df = stok_df[stok_df['SM'].isin(secili_sm)]
                    bs_listesi = sorted(bs_df['BS'].dropna().unique().tolist())
                elif 'BS' in stok_df.columns:
                    bs_listesi = sorted(stok_df['BS'].dropna().unique().tolist())
                else:
                    bs_listesi = []

                with col_bs:
                    secili_bs = st.multiselect(
                        "BS Seçin (opsiyonel):",
                        options=bs_listesi,
                        key="bs_secim",
                        help="Boş bırakırsanız tüm BS'ler dahil edilir"
                    )

                # Mağaza listesini SM/BS'e göre filtrele
                magaza_df = stok_df.copy()
                if secili_sm:
                    magaza_df = magaza_df[magaza_df['SM'].isin(secili_sm)]
                if secili_bs:
                    magaza_df = magaza_df[magaza_df['BS'].isin(secili_bs)]

                # Mağaza listesi (Kod - Ad formatında)
                magazalar_unique = magaza_df[['Kod', 'Mağaza Adı']].drop_duplicates()
                magaza_options = [f"{row['Kod']} - {row['Mağaza Adı']}" for _, row in magazalar_unique.iterrows()]

                secili_magazalar = st.multiselect(
                    "Mağaza Seçin (zorunlu):",
                    options=sorted(magaza_options),
                    key="magaza_coklu_secim",
                    help="Kampanya yapılacak mağazaları seçin"
                )

                if secili_magazalar:
                    st.success(f"✅ {len(secili_magazalar)} mağaza seçildi")

                    # Seçili mağaza kodlarını al
                    secili_magaza_kodlari = [m.split(" - ")[0] for m in secili_magazalar]

                    # Veriyi filtrele
                    filtered_df = stok_df[stok_df['Kod'].astype(str).isin([str(k) for k in secili_magaza_kodlari])]

                    st.markdown("---")

                    # =============================================================================
                    # ADIM 3: ANALİZ VE ÖNERİ
                    # =============================================================================
                    st.markdown("### 3️⃣ Kampanya Önerisi")

                    if st.button("🚀 Analiz Et ve Öner", type="primary", use_container_width=True):
                        with st.spinner("🔄 Lift algoritması çalışıyor..."):
                            # Performans verisini yükle
                            performans_df = load_performans_data()
                            urun_mal_grubu_map = get_urun_mal_grubu_map(performans_df)

                            if performans_df is None:
                                st.error("❌ Performans verisi yüklenemedi!")
                            else:
                                # Her ürün-mağaza kombinasyonu için skor hesapla
                                sonuclar = []

                                for _, row in filtered_df.iterrows():
                                    magaza_kodu = str(row['Kod'])
                                    urun_kodu = str(row['Ürün Kodu'])
                                    urun_adi = row['Ürün Tanımı']
                                    stok = row.get('Stok', 0)
                                    satis_fiyati = row.get('Satış Fiyatı', 0)
                                    alis_fiyati = row.get('Alış', 0)
                                    marj = row.get('Marj', 0)

                                    # Fiyatı temizle
                                    if isinstance(satis_fiyati, str):
                                        satis_fiyati = float(satis_fiyati.replace('₺', '').replace('.', '').replace(',', '.').strip())

                                    # Kampanya ürünü formatında oluştur
                                    urun = {
                                        'kod': urun_kodu,
                                        'ad': urun_adi,
                                        'eski_fiyat': str(satis_fiyati),
                                        'yeni_fiyat': '',  # Henüz belirlenmedi
                                        'indirim': '',
                                        'indirim_num': 0
                                    }

                                    # Lift skoru hesapla (sadece fit için, indirim yok)
                                    nitelik = "Spot"  # Varsayılan

                                    # Mal grubunu bul
                                    mal_grubu_kodu = urun_mal_grubu_map.get(urun_kodu)

                                    # Basitleştirilmiş lift hesaplama
                                    try:
                                        # Mağaza verisi
                                        store_data = performans_df[
                                            (performans_df['MAGAZA_KODU'].astype(str) == magaza_kodu) &
                                            (performans_df['NITELIK'].str.lower().str.contains('spot', na=False))
                                        ]

                                        # Benchmark verisi (tüm mağazalar)
                                        bench_data = performans_df[
                                            performans_df['NITELIK'].str.lower().str.contains('spot', na=False)
                                        ]

                                        # Mağaza verisi var mı kontrol et
                                        if len(store_data) == 0:
                                            # Mağaza verisi yok - stok bazlı öneri yap
                                            lift = 1.0
                                            sku_trusted = False

                                            # Stok bazlı skor (stok miktarına göre)
                                            if stok >= 20:
                                                fit_score = 70
                                                neden = f"📦 Yüksek stok ({stok} adet) - Mağaza verisi yok, stok bazlı öneri"
                                            elif stok >= 10:
                                                fit_score = 55
                                                neden = f"📦 Orta stok ({stok} adet) - Mağaza verisi yok, stok bazlı öneri"
                                            elif stok >= 5:
                                                fit_score = 40
                                                neden = f"📦 Düşük stok ({stok} adet) - Mağaza verisi yok"
                                            else:
                                                fit_score = 30
                                                neden = f"➖ Az stok ({stok} adet) - Mağaza verisi yok"
                                        else:
                                            # SKU bazlı lift
                                            store_sku = store_data[store_data['URUN_KODU'].astype(str) == urun_kodu]
                                            bench_sku = bench_data[bench_data['URUN_KODU'].astype(str) == urun_kodu]

                                            sku_qty = store_sku['TOPLAM_ADET'].sum() if len(store_sku) > 0 else 0
                                            bench_qty = bench_sku['TOPLAM_ADET'].sum() if len(bench_sku) > 0 else 0

                                            store_total = store_data['TOPLAM_ADET'].sum()
                                            bench_total = bench_data['TOPLAM_ADET'].sum()

                                            eps = 0.0001
                                            store_share = (sku_qty / (store_total + eps)) * 100
                                            bench_share = (bench_qty / (bench_total + eps)) * 100

                                            lift = (store_share + eps) / (bench_share + eps)

                                            # Skor (0-100)
                                            fit_score = min(max((lift - 0.5) / 1.5, 0), 1) * 100

                                            # SKU güven kontrolü
                                            sku_trusted = sku_qty >= 3 and bench_qty >= 30

                                            # Grup bazlı hesaplama (fallback)
                                            if mal_grubu_kodu:
                                                store_grp = store_data[store_data['MAL_GRUBU_KODU'].astype(str) == str(mal_grubu_kodu)]
                                                bench_grp = bench_data[bench_data['MAL_GRUBU_KODU'].astype(str) == str(mal_grubu_kodu)]

                                                grp_qty = store_grp['TOPLAM_ADET'].sum()
                                                grp_bench = bench_grp['TOPLAM_ADET'].sum()

                                                grp_share = (grp_qty / (store_total + eps)) * 100
                                                grp_bench_share = (grp_bench / (bench_total + eps)) * 100

                                                lift_grp = (grp_share + eps) / (grp_bench_share + eps)
                                                fit_grp = min(max((lift_grp - 0.5) / 1.5, 0), 1) * 100

                                                # Hierarchical blend
                                                if not sku_trusted:
                                                    alpha = sku_qty / (sku_qty + 5)
                                                    fit_score = alpha * fit_score + (1 - alpha) * fit_grp

                                            # Neden öneriliyor?
                                            if lift > 1.5:
                                                neden = f"🔥 Yüksek lift ({lift:.1f}x) - Mağaza bu üründe güçlü"
                                            elif lift > 1.0:
                                                neden = f"✅ Pozitif lift ({lift:.1f}x) - Ortalamanın üstünde"
                                            elif stok > 10:
                                                neden = f"📦 Yüksek stok ({stok} adet) - Eritilmeli"
                                            else:
                                                neden = f"➖ Standart performans (lift: {lift:.1f}x)"

                                    except Exception as e:
                                        fit_score = 50  # Varsayılan
                                        lift = 1.0
                                        neden = f"⚠️ Hesaplama hatası - Stok bazlı öneri ({stok} adet)"
                                        sku_trusted = False

                                    # Stok değeri hesapla
                                    stok_tl = stok * (satis_fiyati if isinstance(satis_fiyati, (int, float)) else 0)

                                    sonuclar.append({
                                        'SM': row.get('SM', ''),
                                        'BS': row.get('BS', ''),
                                        'Kod': magaza_kodu,
                                        'Mağaza Adı': row.get('Mağaza Adı', ''),
                                        'Ürün Kodu': urun_kodu,
                                        'Ürün Tanımı': urun_adi,
                                        'Stok': stok,
                                        'Alış': alis_fiyati,
                                        'Satış Fiyatı': satis_fiyati,
                                        'Marj': marj,
                                        'KDV': row.get('KDV', row.get('kdv', '')),
                                        'yeni fiyat': '',  # Kullanıcı dolduracak
                                        'yeni marj': '',  # Kullanıcı dolduracak
                                        'Stok TL': stok_tl,
                                        'Lift Skoru': round(fit_score, 1),
                                        'Lift': round(lift, 2),
                                        'Öneri Nedeni': neden,
                                        'SKU Güvenilir': '✅' if sku_trusted else '⚠️'
                                    })

                                # DataFrame oluştur ve sırala
                                sonuc_df = pd.DataFrame(sonuclar)

                                # Mağaza bazında grupla ve her mağaza için en iyi ürünleri seç
                                sonuc_df = sonuc_df.sort_values(
                                    ['Kod', 'Lift Skoru', 'Stok TL'],
                                    ascending=[True, False, False]
                                )

                                # Session state'e kaydet
                                st.session_state['kampanya_sonuc'] = sonuc_df

                                st.success(f"✅ Analiz tamamlandı! {len(sonuc_df)} ürün-mağaza kombinasyonu değerlendirildi.")

                    # Sonuçları göster
                    if 'kampanya_sonuc' in st.session_state:
                        sonuc_df = st.session_state['kampanya_sonuc']

                        st.markdown("---")
                        st.markdown("### 📊 Sonuçlar")

                        # Özet istatistikler
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("Toplam Satır", f"{len(sonuc_df):,}")
                        with col2:
                            st.metric("Benzersiz Ürün", f"{sonuc_df['Ürün Kodu'].nunique():,}")
                        with col3:
                            st.metric("Toplam Stok", f"{sonuc_df['Stok'].sum():,}")
                        with col4:
                            st.metric("Toplam Stok TL", f"₺{sonuc_df['Stok TL'].sum():,.0f}")

                        # Filtreleme seçenekleri
                        st.markdown("#### 🎯 Sonuç Filtresi")
                        col_f1, col_f2 = st.columns(2)
                        with col_f1:
                            min_skor = st.slider("Minimum Lift Skoru", 0, 100, 30, 5, key="min_skor_filter")
                        with col_f2:
                            min_stok = st.number_input("Minimum Stok", 0, 1000, 1, key="min_stok_filter")

                        # Filtrele
                        filtered_sonuc = sonuc_df[
                            (sonuc_df['Lift Skoru'] >= min_skor) &
                            (sonuc_df['Stok'] >= min_stok)
                        ]

                        st.info(f"📋 Filtrelenmiş: {len(filtered_sonuc):,} satır (Skor ≥ {min_skor}, Stok ≥ {min_stok})")

                        # Tablo göster
                        st.dataframe(
                            filtered_sonuc,
                            use_container_width=True,
                            height=400
                        )

                        # Excel indirme
                        st.markdown("---")
                        st.markdown("### 📥 Excel İndir")

                        # Excel'e dönüştür
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            filtered_sonuc.to_excel(writer, index=False, sheet_name='Kampanya Önerisi')
                        output.seek(0)

                        st.download_button(
                            label="📥 Kampanya Önerisini İndir (Excel)",
                            data=output,
                            file_name=f"kampanya_onerisi_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary",
                            use_container_width=True
                        )

                        st.caption("💡 Excel'i indirin, 'yeni fiyat' kolonunu doldurun ve kampanyayı başlatın.")

                else:
                    st.warning("👆 En az bir mağaza seçin.")

        except Exception as e:
            st.error(f"❌ Excel okuma hatası: {str(e)}")
            st.info("Dosya formatını kontrol edin. Beklenen kolonlar: SM, BS, Kod, Mağaza Adı, Ürün Kodu, Ürün Tanımı, Stok, Alış, Satış Fiyatı...")

    else:
        st.info("👆 Excel dosyası yükleyin.")

# Footer
st.markdown("---")
st.markdown("""
<p style="text-align:center; color:#888; font-size:12px;">
    A101 Kampanya Asistanı v4.0 - Mesaj Oluşturucu + Kampanya Oluşturucu<br>
    Yeni Mağazacılık A.Ş. © 2025
</p>
""", unsafe_allow_html=True)
