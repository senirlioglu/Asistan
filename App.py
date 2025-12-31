import streamlit as st
import re
import urllib.parse
import pandas as pd
import io
import requests
from datetime import datetime

# Sayfa yapılandırması
st.set_page_config(
    page_title="A101 Kampanya Mesaj Oluşturucu",
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

# Performans verisi URL'leri
PERFORMANS_URL_2025 = "https://github.com/senirlioglu/performans/raw/main/veri_2025.parquet"
PERFORMANS_URL_2024 = "https://github.com/senirlioglu/performans/raw/main/veri_2024.parquet"

# =============================================================================
# ÜRÜN EMOJİLERİ
# =============================================================================
URUN_EMOJILERI = {
    "TV": "📺", "SÜPÜRGE": "🧹", "BUZDOLABI": "❄️", "KLİMA": "❄️",
    "KAHVE": "☕", "ÇAY": "🍵", "TOST": "🥪", "WAFFLE": "🧇",
    "MİKSER": "🥣", "BLENDER": "🥤", "FRİTÖZ": "🍟", "AIRFRYER": "🍟",
    "SAÇ": "💇", "ÜTÜ": "👔", "ISITICI": "🔥", "VANTİLATÖR": "🌀",
    "KAMP": "⛺", "BAHÇE": "🌳", "MANGAL": "🔥", "BİSİKLET": "🚲",
    "ARABA": "🚗", "AKÜLÜ": "🚗", "OYUNCAK": "🧸", "BEBEK": "👶",
    "GÖMLEK": "👔", "SWEATSHIRT": "🧥", "EŞOFMAN": "🏃",
    "ÇARŞAF": "🛏️", "BATTANİYE": "🛏️", "NEVRESİM": "🛏️",
    "PERDE": "🪟", "HALI": "🏠", "DOLAP": "🗄️", "MASA": "🪑",
    "BARDAK": "🥛", "FİNCAN": "☕", "TABAK": "🍽️", "KAVANOZ": "🫙",
    "TERMOS": "🧊", "TESTERE": "🪚", "SAATİ": "⌚", "KAMERA": "📷",
    "POWERBANK": "🔋", "DONDURUC": "🧊", "ESPRESSO": "☕",
    "ÇAPA": "🚜", "MULTIMEDIA": "🎵", "MUG": "☕", "SEPETİ": "🧺",
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
@st.cache_data(ttl=3600)  # 1 saat cache
def load_performans_data():
    """GitHub'dan performans verilerini yükle"""
    try:
        # 2025 verisini yükle
        response = requests.get(PERFORMANS_URL_2025, timeout=30)
        if response.status_code == 200:
            df = pd.read_parquet(io.BytesIO(response.content))
            return df
    except Exception as e:
        st.warning(f"⚠️ Performans verisi yüklenemedi: {str(e)}")
    return None

def get_magaza_performans(df, magaza_kodu):
    """Mağaza bazlı performans özeti"""
    if df is None:
        return None, None

    try:
        # Mağaza kodunu tam eşleştir (contains yerine ==)
        magaza_filter = df['Magaza_Kod'].astype(str).str.strip() == magaza_kodu.strip()
        magaza_df = df[magaza_filter]

        if magaza_df.empty:
            return None, None

        # Mal grubu bazlı satış performansı
        mal_grubu_perf = magaza_df.groupby('Mal_Grubu').agg({
            'Adet': 'sum',
            'Ciro': 'sum'
        }).reset_index()
        mal_grubu_perf = mal_grubu_perf.sort_values('Adet', ascending=False)

        # Ürün bazlı satış performansı
        urun_perf = magaza_df.groupby(['Urun_Kod', 'Urun_Ad', 'Mal_Grubu']).agg({
            'Adet': 'sum',
            'Ciro': 'sum'
        }).reset_index()
        urun_perf = urun_perf.sort_values('Adet', ascending=False)

        return mal_grubu_perf, urun_perf

    except Exception as e:
        return None, None

def calculate_product_scores(urun, mal_grubu_perf, urun_perf):
    """
    İki farklı puanlama:
    1. Mağaza Skoru - Mağaza satış performansına göre (her mağazada farklı)
    2. Genel Skor - İndirim bazlı (tüm mağazalarda aynı)

    Düzeltmeler:
    - Mal grubu: max'a göre normalize (en çok satan = 100)
    - Fiyat farkı: kaldırıldı (indirim zaten var, pahalı ürünleri şişiriyordu)
    - Ürün geçmişi: mağaza bazlı 90. percentile'a göre normalize
    """

    raw_scores = {}

    # 1. İndirim Puanı (0-100)
    indirim = urun.get('indirim_num', 0)
    raw_scores['indirim'] = min(indirim / 50 * 100, 100)  # %50+ = max

    # 2. Ürün Satış Geçmişi + Mal Grubu (ürün kodu ile eşleştir)
    raw_scores['urun_gecmis'] = 0
    raw_scores['mal_grubu'] = 0
    urun_mal_grubu = None

    if urun_perf is not None and not urun_perf.empty:
        urun_kodu = urun.get('kod', '')
        urun_match = urun_perf[urun_perf['Urun_Kod'].astype(str) == urun_kodu]

        if not urun_match.empty:
            # Bu ürün daha önce satılmış - gerçek mal grubunu al
            adet = urun_match['Adet'].values[0]
            urun_mal_grubu = urun_match['Mal_Grubu'].values[0]

            # Mağaza bazlı normalize: 90. percentile eşiği
            p90 = urun_perf['Adet'].quantile(0.90)
            if p90 > 0:
                raw_scores['urun_gecmis'] = min((adet / p90) * 100, 100)
            else:
                raw_scores['urun_gecmis'] = 100 if adet > 0 else 0

    # Mal grubu performansı - MAX'a göre normalize (en çok satan = 100)
    if urun_mal_grubu and mal_grubu_perf is not None and not mal_grubu_perf.empty:
        mal_match = mal_grubu_perf[mal_grubu_perf['Mal_Grubu'] == urun_mal_grubu]
        if not mal_match.empty:
            max_adet = mal_grubu_perf['Adet'].max()
            if max_adet > 0:
                raw_scores['mal_grubu'] = (mal_match['Adet'].values[0] / max_adet) * 100

    # === MAĞAZA SKORU (mağaza bazlı - her mağazada farklı) ===
    # Ağırlık: Mal Grubu %40 + Ürün Geçmişi %40 + İndirim %20
    # (Fiyat farkı kaldırıldı - indirim zaten var)
    magaza_skor = (
        raw_scores['mal_grubu'] * 0.40 +
        raw_scores['urun_gecmis'] * 0.40 +
        raw_scores['indirim'] * 0.20
    )

    # === GENEL SKOR (indirim bazlı - tüm mağazalarda aynı) ===
    # Ağırlık: İndirim %60 + Mal Grubu %25 + Ürün %15
    genel_skor = (
        raw_scores['indirim'] * 0.60 +
        raw_scores['mal_grubu'] * 0.25 +
        raw_scores['urun_gecmis'] * 0.15
    )

    # Detaylar
    details = {
        'indirim': round(raw_scores['indirim'], 1),
        'mal_grubu': round(raw_scores['mal_grubu'], 1),
        'urun_gecmis': round(raw_scores['urun_gecmis'], 1),
        'mal_grubu_adi': urun_mal_grubu or "Yeni Ürün"
    }

    return round(magaza_skor, 1), round(genel_skor, 1), details

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
    """Workflow kampanya mailini parse et"""

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
        if 'Başlangıç' in line and i + 1 < len(lines):
            tarih_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', lines[i + 1])
            if tarih_match:
                result['baslangic'] = tarih_match.group(1)

        if 'Bitiş' in line and i + 1 < len(lines):
            tarih_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', lines[i + 1])
            if tarih_match:
                result['bitis'] = tarih_match.group(1)

        if 'Onaylayan' in line and i + 1 < len(lines):
            result['onaylayan'] = lines[i + 1]

    # Ürünleri parse et
    i = 0
    while i < len(lines):
        line = lines[i]

        # 8 haneli ürün kodu bul
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

                if next_line.startswith('₺') and not urun['eski_fiyat']:
                    urun['eski_fiyat'] = next_line.replace('₺', '').strip()
                elif next_line.startswith('₺') and urun['eski_fiyat']:
                    urun['yeni_fiyat'] = next_line.replace('₺', '').strip()
                elif next_line.startswith('%'):
                    indirim_str = next_line.replace('%', '').replace(',', '.').strip()
                    urun['indirim'] = next_line.replace('%', '').strip()
                    try:
                        urun['indirim_num'] = float(indirim_str)
                    except ValueError:
                        urun['indirim_num'] = 0
                elif not urun['ad'] and not next_line.startswith('₺') and not next_line.startswith('%'):
                    urun['ad'] = next_line

                j += 1

            if urun['ad'] and urun['yeni_fiyat']:
                try:
                    eski = float(urun['eski_fiyat'].replace('.', '').replace(',', '.'))
                    yeni = float(urun['yeni_fiyat'].replace('.', '').replace(',', '.'))
                    if yeni > eski:
                        result['uyarilar'].append(f"⚠️ {urun['ad'][:30]}: Yeni fiyat eskisinden yüksek!")
                except ValueError:
                    pass

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
def format_whatsapp_mesaji(magaza_adi, secili_urunler, bitis_tarihi):
    """WhatsApp mesajı oluştur"""

    mesaj = f"🛒 A101 {magaza_adi}\n\n"
    mesaj += "🔥 BUGÜNE ÖZEL!\n\n"

    for urun in secili_urunler:
        emoji = get_emoji(urun['ad'])
        ad_kisa = urun['ad'][:35] + "..." if len(urun['ad']) > 35 else urun['ad']
        mesaj += f"{emoji} {ad_kisa}\n"
        mesaj += f"   {urun['yeni_fiyat']}₺"
        if urun.get('eski_fiyat'):
            mesaj += f" ~~{urun['eski_fiyat']}₺~~"
        if urun.get('indirim'):
            mesaj += f" (%{urun['indirim']} indirim)"
        mesaj += "\n\n"

    mesaj += f"📅 Son gün: {bitis_tarihi}\n"
    mesaj += "📍 Stoklarla sınırlıdır\n\n"
    mesaj += "_Listeden çıkmak için ÇIKIŞ yazın_"

    return mesaj

# =============================================================================
# ANA UYGULAMA
# =============================================================================

st.markdown('<p class="main-header">📢 A101 Kampanya Mesaj Oluşturucu</p>', unsafe_allow_html=True)

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
        mal_grubu_perf, urun_perf = get_magaza_performans(performans_df, magaza_kodu)

    if mal_grubu_perf is not None:
        st.success("✅ Mağaza satış performansı yüklendi - Akıllı puanlama aktif!")
    else:
        st.warning("⚠️ Performans verisi bulunamadı - Sadece indirim bazlı sıralama yapılacak")

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

        # Ürünleri puanla (iki skor: mağaza + genel)
        for urun in kampanya['urunler']:
            magaza_skor, genel_skor, detay = calculate_product_scores(urun, mal_grubu_perf, urun_perf)
            urun['magaza_skor'] = magaza_skor
            urun['genel_skor'] = genel_skor
            urun['puan_detay'] = detay

        # Başarı mesajı
        st.markdown(f'''
            <div class="basari-kutusu">
                <strong>✅ {len(kampanya['urunler'])} ürün okundu ve puanlandı</strong>
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

        # İki tab ile iki farklı sıralama
        tab_magaza, tab_genel = st.tabs([
            f"🏪 {magaza_adi} İçin Önerilen",
            "📊 Genel Öneri (İndirim Bazlı)"
        ])

        secili_urunler = []

        with tab_magaza:
            st.markdown("""
            <div class="secim-rehberi">
                <strong>🏪 Mağaza Bazlı Puanlama:</strong><br>
                Bu sıralama <strong>mağazanızın satış geçmişine</strong> göre yapılmıştır.<br>
                • Mal Grubu Performansı (40%) - Bu kategori mağazanızda ne kadar satıyor?<br>
                • Ürün Satış Geçmişi (40%) - Bu ürünü daha önce sattınız mı?<br>
                • İndirim Oranı (20%)<br><br>
                🟢 60+ Çok İyi | 🟡 35-60 Orta | 🔴 35- Düşük
            </div>
            """, unsafe_allow_html=True)

            # Mağaza skoruna göre sırala
            urunler_magaza = sorted(kampanya['urunler'], key=lambda x: x.get('magaza_skor', 0), reverse=True)

            for urun in urunler_magaza:
                col1, col2, col3 = st.columns([1, 17, 4])

                with col1:
                    secili = st.checkbox("", key=f"m_{urun['kod']}", label_visibility="collapsed")
                    if secili and urun not in secili_urunler:
                        secili_urunler.append(urun)

                with col2:
                    emoji = get_emoji(urun['ad'])
                    puan = urun.get('magaza_skor', 0)
                    puan_badge = get_puan_badge(puan)
                    st.markdown(
                        f"{emoji} **{urun['ad'][:40]}** → {urun['yeni_fiyat']}₺ ~~{urun['eski_fiyat']}₺~~ {puan_badge}",
                        unsafe_allow_html=True
                    )

                with col3:
                    detay = urun.get('puan_detay', {})
                    with st.popover("📊 Detay"):
                        st.write(f"**Mal Grubu:** {detay.get('mal_grubu_adi', '-')}")
                        st.write(f"Kategori Perf: {detay.get('mal_grubu', 0)}/100")
                        st.write(f"Ürün Geçmişi: {detay.get('urun_gecmis', 0)}/100")
                        st.write(f"İndirim: %{urun.get('indirim', 0)}")

        with tab_genel:
            st.markdown("""
            <div class="secim-rehberi">
                <strong>📊 Genel Puanlama (Tüm Mağazalar İçin Aynı):</strong><br>
                Bu sıralama <strong>indirim oranına</strong> göre yapılmıştır.<br>
                • İndirim Oranı (60%)<br>
                • Mal Grubu Performansı (25%)<br>
                • Ürün Satış Geçmişi (15%)<br><br>
                🟢 60+ Çok İyi | 🟡 35-60 Orta | 🔴 35- Düşük
            </div>
            """, unsafe_allow_html=True)

            # Genel skora göre sırala
            urunler_genel = sorted(kampanya['urunler'], key=lambda x: x.get('genel_skor', 0), reverse=True)

            for urun in urunler_genel:
                col1, col2, col3 = st.columns([1, 17, 4])

                with col1:
                    secili = st.checkbox("", key=f"g_{urun['kod']}", label_visibility="collapsed")
                    if secili and urun not in secili_urunler:
                        secili_urunler.append(urun)

                with col2:
                    emoji = get_emoji(urun['ad'])
                    puan = urun.get('genel_skor', 0)
                    puan_badge = get_puan_badge(puan)
                    st.markdown(
                        f"{emoji} **{urun['ad'][:40]}** → {urun['yeni_fiyat']}₺ ~~{urun['eski_fiyat']}₺~~ | %{urun['indirim']} {puan_badge}",
                        unsafe_allow_html=True
                    )

                with col3:
                    detay = urun.get('puan_detay', {})
                    with st.popover("📊 Detay"):
                        st.write(f"İndirim: {detay.get('indirim', 0)}/100")
                        st.write(f"Kategori: {detay.get('mal_grubu', 0)}/100")
                        st.write(f"Ürün Geçmişi: {detay.get('urun_gecmis', 0)}/100")

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
            mesaj = format_whatsapp_mesaji(magaza_adi, secili_urunler, bitis)

            st.markdown("**Mesaj önizleme:**")
            st.markdown(f'<div class="mesaj-onizleme">{mesaj}</div>', unsafe_allow_html=True)

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

# Footer
st.markdown("---")
st.markdown("""
<p style="text-align:center; color:#888; font-size:12px;">
    A101 Kampanya Mesaj Oluşturucu v3.2 - Düzeltilmiş Puanlama<br>
    Yeni Mağazacılık A.Ş. © 2025
</p>
""", unsafe_allow_html=True)
