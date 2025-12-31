import streamlit as st
import re
import urllib.parse
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
    # Format: Kod (8 hane) → Ad → Satış Fiyatı (₺) → Tanıtım Fiyatı (₺) → İndirim (%)
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
                    # Satış fiyatı
                    urun['eski_fiyat'] = next_line.replace('₺', '').strip()
                elif next_line.startswith('₺') and urun['eski_fiyat']:
                    # Tanıtım fiyatı
                    urun['yeni_fiyat'] = next_line.replace('₺', '').strip()
                elif next_line.startswith('%'):
                    # İndirim oranı
                    indirim_str = next_line.replace('%', '').replace(',', '.').strip()
                    urun['indirim'] = next_line.replace('%', '').strip()
                    try:
                        urun['indirim_num'] = float(indirim_str)
                    except ValueError:
                        urun['indirim_num'] = 0
                elif not urun['ad'] and not next_line.startswith('₺') and not next_line.startswith('%'):
                    # Ürün adı
                    urun['ad'] = next_line

                j += 1

            # Validasyon
            if urun['ad'] and urun['yeni_fiyat']:
                # Fiyat kontrolü
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

    # Sonuç kontrolü
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

        # Başarı mesajı
        st.markdown(f'''
            <div class="basari-kutusu">
                <strong>✅ {len(kampanya['urunler'])} ürün okundu</strong>
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
        # ADIM 3: ÜRÜN SEÇİMİ
        # =============================================================================
        st.markdown("### 3️⃣ Ürün Seçimi (3-5 ürün önerilir)")

        st.markdown("""
        <div class="secim-rehberi">
            <strong>📋 Seçim İpuçları:</strong><br>
            • 🔥 Yüksek indirimli çekici ürün<br>
            • 🏠 Geniş kitlenin ilgisini çekecek ürün<br>
            • 💰 Uygun fiyatlı sepet tamamlayıcı<br>
            • ✅ <strong>Stokta olduğundan emin olun!</strong>
        </div>
        """, unsafe_allow_html=True)

        # Ürünleri indirime göre sırala
        urunler_sirali = sorted(kampanya['urunler'], key=lambda x: x['indirim_num'], reverse=True)

        st.markdown("**En yüksek indirimli ürünler üstte:**")

        secili_urunler = []

        for urun in urunler_sirali:
            col1, col2 = st.columns([1, 20])

            with col1:
                secili = st.checkbox("", key=f"urun_{urun['kod']}", label_visibility="collapsed")
                if secili:
                    secili_urunler.append(urun)

            with col2:
                emoji = get_emoji(urun['ad'])
                indirim_badge = "🔥" if urun['indirim_num'] >= 25 else ""
                st.write(f"{emoji} **{urun['ad'][:50]}** → {urun['yeni_fiyat']}₺ ~~{urun['eski_fiyat']}₺~~ | %{urun['indirim']} {indirim_badge}")

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
    A101 Kampanya Mesaj Oluşturucu v2.0<br>
    Yeni Mağazacılık A.Ş. © 2025
</p>
""", unsafe_allow_html=True)
