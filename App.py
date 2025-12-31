import streamlit as st
import re
import pandas as pd
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
}

def get_emoji(urun_adi):
    """Ürün adına göre emoji döndür"""
    urun_upper = urun_adi.upper()
    for keyword, emoji in URUN_EMOJILERI.items():
        if keyword in urun_upper:
            return emoji
    return "🏷️"

# =============================================================================
# MAİL PARSER
# =============================================================================
def parse_kampanya_maili(mail_text):
    """Kampanya mailini parse et"""
    
    result = {
        'baslangic': None,
        'bitis': None,
        'magaza_kodu': None,
        'magaza_adi': None,
        'urunler': [],
        'parse_guven': 100,
        'hatalar': [],
        'uyarilar': []
    }
    
    # Tarihleri bul
    tarih_pattern = r'(\d{2}\.\d{2}\.\d{4})'
    tarihler = re.findall(tarih_pattern, mail_text)
    if len(tarihler) >= 2:
        result['baslangic'] = tarihler[0]
        result['bitis'] = tarihler[1]
    else:
        result['hatalar'].append("⚠️ Kampanya tarihleri bulunamadı!")
        result['parse_guven'] -= 20
    
    # Ürünleri parse et - tablo formatı
    lines = mail_text.split('\n')
    current_urun = {}
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        # Ürün kodu ile başlayan satır (8 haneli sayı)
        if re.match(r'^\d{8}$', line):
            if current_urun:
                result['urunler'].append(current_urun)
            current_urun = {'kod': line, 'ad': '', 'eski_fiyat': '', 'yeni_fiyat': '', 'indirim': ''}
        
        # Fiyat satırı
        elif '₺' in line and current_urun:
            fiyat_match = re.search(r'₺([\d.,]+)', line)
            if fiyat_match:
                if not current_urun['eski_fiyat']:
                    current_urun['eski_fiyat'] = fiyat_match.group(1)
                elif not current_urun['yeni_fiyat']:
                    current_urun['yeni_fiyat'] = fiyat_match.group(1)
        
        # İndirim oranı
        elif '%' in line and current_urun:
            indirim_match = re.search(r'%(\d+[,.]?\d*)', line)
            if indirim_match:
                current_urun['indirim'] = indirim_match.group(1)
        
        # Ürün adı (kod sonrası, fiyat öncesi satır)
        elif current_urun and current_urun['kod'] and not current_urun['eski_fiyat'] and line and not line.startswith('%'):
            current_urun['ad'] = line
    
    # Son ürünü ekle
    if current_urun and current_urun.get('kod'):
        result['urunler'].append(current_urun)
    
    # Alternatif parse - tek satır format
    if not result['urunler']:
        urun_pattern = r'(\d{8})\s+(.+?)\s+₺([\d.,]+)\s+₺([\d.,]+)\s+%(\d+[,.]?\d*)'
        for match in re.finditer(urun_pattern, mail_text):
            result['urunler'].append({
                'kod': match.group(1),
                'ad': match.group(2).strip(),
                'eski_fiyat': match.group(3),
                'yeni_fiyat': match.group(4),
                'indirim': match.group(5)
            })
    
    # Anomali kontrolleri
    for urun in result['urunler']:
        # Boş fiyat kontrolü
        if not urun.get('yeni_fiyat') or not urun.get('eski_fiyat'):
            result['uyarilar'].append(f"⚠️ {urun.get('ad', 'Bilinmeyen')}: Fiyat bilgisi eksik")
            result['parse_guven'] -= 5
        
        # Ters indirim kontrolü
        try:
            eski = float(urun.get('eski_fiyat', '0').replace('.', '').replace(',', '.'))
            yeni = float(urun.get('yeni_fiyat', '0').replace('.', '').replace(',', '.'))
            if yeni > eski and eski > 0:
                result['hatalar'].append(f"🔴 {urun.get('ad', 'Bilinmeyen')}: Yeni fiyat eskisinden yüksek!")
                result['parse_guven'] -= 10
        except:
            pass
        
        # Sıfır/çok düşük fiyat kontrolü
        try:
            yeni = float(urun.get('yeni_fiyat', '0').replace('.', '').replace(',', '.'))
            if yeni < 10:
                result['uyarilar'].append(f"⚠️ {urun.get('ad', 'Bilinmeyen')}: Fiyat çok düşük ({yeni}₺)")
        except:
            pass
    
    if not result['urunler']:
        result['hatalar'].append("🔴 Hiç ürün bulunamadı! Mail formatını kontrol edin.")
        result['parse_guven'] = 0
    
    return result

# =============================================================================
# MESAJ FORMATLAMA
# =============================================================================
def format_whatsapp_mesaji(magaza_kodu, magaza_adi, secili_urunler, bitis_tarihi):
    """WhatsApp mesajı oluştur"""
    
    mesaj = f"🛒 A101 {magaza_adi}\n\n"
    mesaj += "🔥 BUGÜN KAÇIRMA!\n\n"
    
    for urun in secili_urunler:
        emoji = get_emoji(urun['ad'])
        ad_kisa = urun['ad'][:35] + "..." if len(urun['ad']) > 35 else urun['ad']
        mesaj += f"{emoji} {ad_kisa} - {urun['yeni_fiyat']}₺"
        if urun.get('eski_fiyat'):
            mesaj += f" (Eski: {urun['eski_fiyat']}₺)"
        mesaj += "\n"
    
    mesaj += f"\n📅 Geçerlilik: {bitis_tarihi}\n"
    mesaj += "📍 Mağazamızda stoklarla sınırlı!\n\n"
    mesaj += "_Çıkmak için ÇIKIŞ yazın_"
    
    return mesaj

# =============================================================================
# ANA UYGULAMA
# =============================================================================

st.markdown('<p class="main-header">📢 A101 Kampanya Mesaj Oluşturucu</p>', unsafe_allow_html=True)

# Session state başlat
if 'adim' not in st.session_state:
    st.session_state.adim = 1
if 'secili_urunler' not in st.session_state:
    st.session_state.secili_urunler = []

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
    
    # BÜYÜK MAĞAZA BANDI
    st.markdown(f'''
        <div class="magaza-bandi">
            🏪 AKTİF MAĞAZA: {magaza_kodu} - {magaza_adi.upper()}
        </div>
    ''', unsafe_allow_html=True)
    
    # WhatsApp liste adı hatırlatması
    st.info(f"📱 WhatsApp liste adı: **{magaza_kodu}_MUSTERI**")
    
    st.markdown("---")
    
    # =============================================================================
    # ADIM 2: KAMPANYA MAİLİ
    # =============================================================================
    st.markdown("### 2️⃣ Kampanya Mailini Yapıştırın")
    
    mail_icerik = st.text_area(
        "Kampanya onay mailinin içeriğini buraya yapıştırın:",
        height=200,
        placeholder="Workflow'dan gelen kampanya mailini kopyalayıp buraya yapıştırın..."
    )
    
    if mail_icerik:
        # Parse et
        kampanya = parse_kampanya_maili(mail_icerik)
        
        # Parse güven skoru
        if kampanya['parse_guven'] < 50:
            st.markdown(f'''
                <div class="hata-kutusu">
                    <strong>🔴 Parse Güven Skoru: %{kampanya['parse_guven']}</strong><br>
                    Mail formatında sorun var. Lütfen kontrol edin.
                </div>
            ''', unsafe_allow_html=True)
        elif kampanya['parse_guven'] < 80:
            st.markdown(f'''
                <div class="uyari-kutusu">
                    <strong>⚠️ Parse Güven Skoru: %{kampanya['parse_guven']}</strong><br>
                    Bazı veriler eksik olabilir.
                </div>
            ''', unsafe_allow_html=True)
        else:
            st.markdown(f'''
                <div class="basari-kutusu">
                    <strong>✅ Parse Güven Skoru: %{kampanya['parse_guven']}</strong><br>
                    {len(kampanya['urunler'])} ürün başarıyla okundu.
                </div>
            ''', unsafe_allow_html=True)
        
        # Hata ve uyarıları göster
        if kampanya['hatalar']:
            for hata in kampanya['hatalar']:
                st.error(hata)
        
        if kampanya['uyarilar']:
            with st.expander("⚠️ Uyarılar", expanded=False):
                for uyari in kampanya['uyarilar']:
                    st.warning(uyari)
        
        # Tarih bilgisi
        if kampanya['baslangic'] and kampanya['bitis']:
            st.success(f"📅 Kampanya: {kampanya['baslangic']} - {kampanya['bitis']}")
        
        st.markdown("---")
        
        # =============================================================================
        # ADIM 3: ÜRÜN SEÇİMİ
        # =============================================================================
        if kampanya['urunler']:
            st.markdown("### 3️⃣ Ürün Seçimi (3-5 ürün)")
            
            # Seçim rehberi
            st.markdown('''
                <div class="secim-rehberi">
                    <strong>📋 Seçim Rehberi:</strong><br>
                    • 1 <strong>çekici ürün</strong> (yüksek indirim, ilgi çekici)<br>
                    • 1 <strong>geniş kitle</strong> (mutfak, temizlik, temel ihtiyaç)<br>
                    • 1 <strong>sepet tamamlayıcı</strong> (küçük, uygun fiyatlı)<br>
                    • <strong>Stok kontrolü:</strong> Seçtiğiniz ürünler mağazanızda var mı?
                </div>
            ''', unsafe_allow_html=True)
            
            # Ürün tablosu
            secili_kodlar = []
            
            # DataFrame oluştur
            df_data = []
            for urun in kampanya['urunler']:
                indirim_val = 0
                try:
                    indirim_val = float(urun.get('indirim', '0').replace(',', '.'))
                except:
                    pass
                
                df_data.append({
                    'Kod': urun['kod'],
                    'Ürün': urun['ad'][:40] + ('...' if len(urun['ad']) > 40 else ''),
                    'Eski Fiyat': urun.get('eski_fiyat', '-'),
                    'Yeni Fiyat': urun.get('yeni_fiyat', '-'),
                    'İndirim %': urun.get('indirim', '-'),
                    'indirim_val': indirim_val
                })
            
            df = pd.DataFrame(df_data)
            df_sorted = df.sort_values('indirim_val', ascending=False)
            
            st.markdown("**En yüksek indirimli ürünler üstte:**")
            
            # Checkbox ile seçim
            for idx, row in df_sorted.iterrows():
                urun_data = kampanya['urunler'][idx]
                col1, col2 = st.columns([1, 20])
                
                with col1:
                    secili = st.checkbox("", key=f"urun_{row['Kod']}")
                    if secili:
                        secili_kodlar.append(urun_data)
                
                with col2:
                    emoji = get_emoji(row['Ürün'])
                    indirim_badge = ""
                    if row['indirim_val'] >= 30:
                        indirim_badge = "🔥"
                    st.write(f"{emoji} **{row['Ürün']}** - {row['Yeni Fiyat']}₺ ~~{row['Eski Fiyat']}₺~~ | %{row['İndirim %']} {indirim_badge}")
            
            # Seçim sayısı kontrolü
            secili_sayi = len(secili_kodlar)
            
            if secili_sayi > 0:
                if secili_sayi < 3:
                    st.warning(f"⚠️ {secili_sayi} ürün seçildi. En az 3 ürün seçmeniz önerilir.")
                elif secili_sayi > 5:
                    st.warning(f"⚠️ {secili_sayi} ürün seçildi. En fazla 5 ürün seçmeniz önerilir.")
                else:
                    st.success(f"✅ {secili_sayi} ürün seçildi.")
                
                st.markdown("---")
                
                # =============================================================================
                # ADIM 4: STOK KONTROLÜ
                # =============================================================================
                st.markdown("### 4️⃣ Stok Kontrolü")
                
                stok_onay = st.checkbox(
                    f"✅ Seçtiğim {secili_sayi} ürün **{magaza_kodu} {magaza_adi}** mağazasında STOKTA MEVCUT",
                    key="stok_onay"
                )
                
                st.markdown("---")
                
                # =============================================================================
                # ADIM 5: MESAJ ÖNİZLEME VE GÖNDERME
                # =============================================================================
                st.markdown("### 5️⃣ Mesaj Önizleme ve Gönderme")
                
                # Mesajı oluştur
                bitis = kampanya['bitis'] or "Stoklarla sınırlı"
                mesaj = format_whatsapp_mesaji(magaza_kodu, magaza_adi, secili_kodlar, bitis)
                
                st.markdown("**Mesaj önizleme:**")
                st.markdown(f'<div class="mesaj-onizleme">{mesaj}</div>', unsafe_allow_html=True)
                
                # =============================================================================
                # 2 AŞAMALI KONTROL
                # =============================================================================
                st.markdown("---")
                st.markdown('<div class="kontrol-kutusu">', unsafe_allow_html=True)
                st.markdown("### ⚠️ Gönderim Öncesi Kontrol")
                
                kontrol1 = st.checkbox(
                    f"✅ Bu mesaj **{magaza_kodu} - {magaza_adi}** mağazası için hazırlandı",
                    key="kontrol1"
                )
                
                kontrol2 = st.checkbox(
                    f"✅ Kampanya tarihi ({bitis}) ve fiyatlar DOĞRU",
                    key="kontrol2"
                )
                
                st.markdown('</div>', unsafe_allow_html=True)
                
                # WhatsApp gönder butonu
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
                            💬 WhatsApp'ta Gönder ({magaza_kodu}_MUSTERI listesine)
                        </a>
                    ''', unsafe_allow_html=True)
                    
                    st.markdown("")
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
                            cursor: not-allowed;
                        ">
                            💬 WhatsApp'ta Gönder
                        </div>
                    ''', unsafe_allow_html=True)
                    
                    st.warning("☝️ Gönderim için yukarıdaki tüm kontrolleri tamamlayın.")

else:
    st.info("👆 Önce mağazanızı seçin.")

# Footer
st.markdown("---")
st.markdown("""
<p style="text-align:center; color:#888; font-size:12px;">
     Kampanya Mesaj Oluşturucu v1.0<br>
    Yeni Mağazacılık A.Ş. © 2025
</p>
""", unsafe_allow_html=True)
