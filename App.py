import streamlit as st
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
    urun_upper = str(urun_adi).upper()
    for keyword, emoji in URUN_EMOJILERI.items():
        if keyword in urun_upper:
            return emoji
    return "🏷️"

# =============================================================================
# EXCEL PARSER
# =============================================================================
def parse_excel(df):
    """Excel dosyasını parse et"""
    
    result = {
        'urunler': [],
        'hatalar': [],
        'uyarilar': []
    }
    
    # Sütun isimlerini normalize et
    df.columns = df.columns.str.strip().str.lower()
    
    # Olası sütun isimleri
    kod_cols = ['ürün kodu', 'urun kodu', 'kod', 'malzeme']
    ad_cols = ['ürün adı', 'urun adi', 'ürün', 'urun', 'ad', 'tanım']
    eski_fiyat_cols = ['satış fiyatı', 'satis fiyati', 'eski fiyat', 'liste fiyatı']
    yeni_fiyat_cols = ['tanıtım fiyatı', 'tanitim fiyati', 'yeni fiyat', 'kampanya fiyatı', 'indirimli fiyat']
    indirim_cols = ['indirim oranı', 'indirim orani', 'indirim', 'iskonto']
    
    # Sütunları bul
    kod_col = None
    ad_col = None
    eski_fiyat_col = None
    yeni_fiyat_col = None
    indirim_col = None
    
    for col in df.columns:
        if any(x in col for x in kod_cols):
            kod_col = col
        elif any(x in col for x in ad_cols):
            ad_col = col
        elif any(x in col for x in eski_fiyat_cols):
            eski_fiyat_col = col
        elif any(x in col for x in yeni_fiyat_cols):
            yeni_fiyat_col = col
        elif any(x in col for x in indirim_cols):
            indirim_col = col
    
    # Sütun kontrolü
    if not kod_col:
        result['hatalar'].append("🔴 'Ürün Kodu' sütunu bulunamadı!")
    if not ad_col:
        result['hatalar'].append("🔴 'Ürün Adı' sütunu bulunamadı!")
    if not yeni_fiyat_col:
        result['hatalar'].append("🔴 'Tanıtım Fiyatı' sütunu bulunamadı!")
    
    if result['hatalar']:
        return result
    
    # Verileri parse et
    for idx, row in df.iterrows():
        try:
            kod = str(row.get(kod_col, '')).strip()
            ad = str(row.get(ad_col, '')).strip()
            
            # Boş satırları atla
            if not kod or kod == 'nan' or not ad or ad == 'nan':
                continue
            
            # Fiyatları temizle
            eski_fiyat = str(row.get(eski_fiyat_col, '')).replace('₺', '').replace('.', '').replace(',', '.').strip()
            yeni_fiyat = str(row.get(yeni_fiyat_col, '')).replace('₺', '').replace('.', '').replace(',', '.').strip()
            indirim = str(row.get(indirim_col, '')).replace('%', '').replace(',', '.').strip() if indirim_col else ''
            
            # Fiyatları formatla
            try:
                eski_fiyat_num = float(eski_fiyat) if eski_fiyat and eski_fiyat != 'nan' else 0
                yeni_fiyat_num = float(yeni_fiyat) if yeni_fiyat and yeni_fiyat != 'nan' else 0
                
                eski_fiyat_str = f"{eski_fiyat_num:,.0f}".replace(',', '.')
                yeni_fiyat_str = f"{yeni_fiyat_num:,.0f}".replace(',', '.')
            except:
                eski_fiyat_str = eski_fiyat
                yeni_fiyat_str = yeni_fiyat
                eski_fiyat_num = 0
                yeni_fiyat_num = 0
            
            # İndirim hesapla (yoksa)
            if not indirim and eski_fiyat_num > 0 and yeni_fiyat_num > 0:
                indirim = f"{((eski_fiyat_num - yeni_fiyat_num) / eski_fiyat_num) * 100:.1f}"
            
            urun = {
                'kod': kod,
                'ad': ad,
                'eski_fiyat': eski_fiyat_str,
                'yeni_fiyat': yeni_fiyat_str,
                'indirim': indirim,
                'indirim_num': float(indirim) if indirim and indirim != 'nan' else 0
            }
            
            # Anomali kontrolleri
            if yeni_fiyat_num > eski_fiyat_num and eski_fiyat_num > 0:
                result['uyarilar'].append(f"⚠️ {ad[:30]}: Yeni fiyat eskisinden yüksek!")
            
            if yeni_fiyat_num < 10 and yeni_fiyat_num > 0:
                result['uyarilar'].append(f"⚠️ {ad[:30]}: Fiyat çok düşük ({yeni_fiyat_num}₺)")
            
            result['urunler'].append(urun)
            
        except Exception as e:
            result['uyarilar'].append(f"⚠️ Satır {idx+1} okunamadı: {str(e)}")
    
    if not result['urunler']:
        result['hatalar'].append("🔴 Hiç ürün bulunamadı!")
    
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
    # ADIM 2: KAMPANYA TARİHLERİ
    # =============================================================================
    st.markdown("### 2️⃣ Kampanya Tarihleri")
    
    col1, col2 = st.columns(2)
    with col1:
        baslangic_tarihi = st.date_input("Başlangıç Tarihi", value=datetime.now())
    with col2:
        bitis_tarihi = st.date_input("Bitiş Tarihi", value=datetime.now())
    
    bitis_str = bitis_tarihi.strftime("%d.%m.%Y")
    
    st.markdown("---")
    
    # =============================================================================
    # ADIM 3: EXCEL YÜKLE
    # =============================================================================
    st.markdown("### 3️⃣ Kampanya Excel'i Yükle")
    
    st.info("💡 Kampanya mailindeki ürün tablosunu Excel'e kopyalayıp buraya yükleyin.")
    
    uploaded_file = st.file_uploader(
        "Excel dosyasını seçin",
        type=['xlsx', 'xls'],
        help="Ürün Kodu, Ürün Adı, Satış Fiyatı, Tanıtım Fiyatı, İndirim Oranı sütunları olmalı"
    )
    
    if uploaded_file:
        try:
            df = pd.read_excel(uploaded_file)
            
            st.success(f"✅ Dosya yüklendi: {len(df)} satır")
            
            # Parse et
            kampanya = parse_excel(df)
            
            # Hataları göster
            if kampanya['hatalar']:
                for hata in kampanya['hatalar']:
                    st.error(hata)
                st.stop()
            
            # Uyarıları göster
            if kampanya['uyarilar']:
                with st.expander(f"⚠️ {len(kampanya['uyarilar'])} Uyarı", expanded=False):
                    for uyari in kampanya['uyarilar']:
                        st.warning(uyari)
            
            st.success(f"✅ {len(kampanya['urunler'])} ürün başarıyla okundu")
            
            st.markdown("---")
            
            # =============================================================================
            # ADIM 4: ÜRÜN SEÇİMİ
            # =============================================================================
            st.markdown("### 4️⃣ Ürün Seçimi (3-5 ürün)")
            
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
            
            # Ürünleri indirime göre sırala
            urunler_sirali = sorted(kampanya['urunler'], key=lambda x: x['indirim_num'], reverse=True)
            
            st.markdown("**En yüksek indirimli ürünler üstte:**")
            
            # Session state ile seçimleri tut
            if 'secili_kodlar' not in st.session_state:
                st.session_state.secili_kodlar = []
            
            secili_urunler = []
            
            for urun in urunler_sirali:
                col1, col2 = st.columns([1, 20])
                
                with col1:
                    secili = st.checkbox("", key=f"urun_{urun['kod']}")
                    if secili:
                        secili_urunler.append(urun)
                
                with col2:
                    emoji = get_emoji(urun['ad'])
                    indirim_badge = "🔥" if urun['indirim_num'] >= 30 else ""
                    st.write(f"{emoji} **{urun['ad'][:50]}** - {urun['yeni_fiyat']}₺ ~~{urun['eski_fiyat']}₺~~ | %{urun['indirim']} {indirim_badge}")
            
            # Seçim sayısı kontrolü
            secili_sayi = len(secili_urunler)
            
            if secili_sayi > 0:
                if secili_sayi < 3:
                    st.warning(f"⚠️ {secili_sayi} ürün seçildi. En az 3 ürün seçmeniz önerilir.")
                elif secili_sayi > 5:
                    st.warning(f"⚠️ {secili_sayi} ürün seçildi. En fazla 5 ürün seçmeniz önerilir.")
                else:
                    st.success(f"✅ {secili_sayi} ürün seçildi.")
                
                st.markdown("---")
                
                # =============================================================================
                # ADIM 5: STOK KONTROLÜ
                # =============================================================================
                st.markdown("### 5️⃣ Stok Kontrolü")
                
                stok_onay = st.checkbox(
                    f"✅ Seçtiğim {secili_sayi} ürün **{magaza_kodu} {magaza_adi}** mağazasında STOKTA MEVCUT",
                    key="stok_onay"
                )
                
                st.markdown("---")
                
                # =============================================================================
                # ADIM 6: MESAJ ÖNİZLEME VE GÖNDERME
                # =============================================================================
                st.markdown("### 6️⃣ Mesaj Önizleme ve Gönderme")
                
                # Mesajı oluştur
                mesaj = format_whatsapp_mesaji(magaza_kodu, magaza_adi, secili_urunler, bitis_str)
                
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
                    f"✅ Kampanya tarihi ({bitis_str}) ve fiyatlar DOĞRU",
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
        
        except Exception as e:
            st.error(f"🔴 Excel okuma hatası: {str(e)}")

else:
    st.info("👆 Önce mağazanızı seçin.")

# Footer
st.markdown("---")
st.markdown("""
<p style="text-align:center; color:#888; font-size:12px;">
    A101 Kampanya Mesaj Oluşturucu v1.1<br>
    Yeni Mağazacılık A.Ş. © 2025
</p>
""", unsafe_allow_html=True)
