"""
Yıllık Veri Aggregasyon Scripti
================================
Aylık Excel dosyalarını okur, aggrege eder, tek parquet çıkartır.

Kullanım:
1. Excel dosyalarını bir klasöre koy (örn: /data/2025/)
2. Bu scripti çalıştır
3. Çıkan parquet dosyasını GitHub'a yükle
"""

import pandas as pd
import os
from pathlib import Path

# =============================================================================
# AYARLAR - BURAYA KENDİ YOLLARINI YAZ
# =============================================================================

# Excel dosyalarının bulunduğu klasör
EXCEL_KLASORU = "./data/2025/"  # Değiştir

# Çıktı dosyası
CIKTI_DOSYASI = "./veri_2025_yillik.parquet"

# Excel'deki kolon isimleri (senin dosyalarına göre ayarlandı)
KOLON_ESLEME = {
    'Magaza_Kod': 'Mağaza - Anahtar',
    'Urun_Kod': 'Malzeme Kodu',
    'Mal_Grubu': 'MAL GRUBU',
    'Nitelik': 'NİTELİK',
    'Adet': 'Satış Miktarı',
    'Ciro': 'Satış Hasılatı (VD)'
}

# =============================================================================
# ANA FONKSİYONLAR
# =============================================================================

def excel_dosyalarini_bul(klasor):
    """Klasördeki tüm Excel dosyalarını bul"""
    klasor_path = Path(klasor)
    excel_dosyalari = list(klasor_path.glob("*.xlsx")) + list(klasor_path.glob("*.xls"))
    print(f"📁 {len(excel_dosyalari)} Excel dosyası bulundu:")
    for f in excel_dosyalari:
        print(f"   - {f.name}")
    return excel_dosyalari

def excel_oku_ve_normalize(dosya_yolu, kolon_esleme):
    """Excel dosyasını oku ve kolon isimlerini normalize et"""
    print(f"\n📖 Okunuyor: {dosya_yolu.name}")

    try:
        df = pd.read_excel(dosya_yolu)
        print(f"   Satır sayısı: {len(df):,}")

        # Kolon isimlerini normalize et (boşlukları temizle)
        df.columns = df.columns.str.strip()

        # Gerekli kolonları kontrol et
        eksik = []
        for hedef, kaynak in kolon_esleme.items():
            if kaynak not in df.columns:
                eksik.append(f"{hedef} ({kaynak})")

        if eksik:
            print(f"   ⚠️ UYARI: Eksik kolonlar: {eksik}")
            print(f"   Mevcut kolonlar: {list(df.columns)}")
            return None

        # Sadece gerekli kolonları al ve yeniden adlandır
        rename_map = {v: k for k, v in kolon_esleme.items()}
        df = df[list(kolon_esleme.values())].rename(columns=rename_map)

        print(f"   ✅ Başarılı: {len(df):,} satır")
        return df

    except Exception as e:
        print(f"   ❌ HATA: {str(e)}")
        return None

def aggrege_et(df):
    """Veriyi aggrege et"""
    print("\n🔄 Aggregasyon yapılıyor...")

    # String kolonları temizle
    for col in ['Magaza_Kod', 'Urun_Kod', 'Mal_Grubu', 'Nitelik']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Sayısal kolonları düzelt
    for col in ['Adet', 'Ciro']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Aggrege et
    agg_df = df.groupby(['Magaza_Kod', 'Urun_Kod', 'Mal_Grubu', 'Nitelik'], as_index=False).agg({
        'Adet': 'sum',
        'Ciro': 'sum'
    })

    print(f"   Aggrege sonrası satır sayısı: {len(agg_df):,}")
    print(f"   Benzersiz mağaza: {agg_df['Magaza_Kod'].nunique():,}")
    print(f"   Benzersiz ürün: {agg_df['Urun_Kod'].nunique():,}")
    print(f"   Benzersiz nitelik: {agg_df['Nitelik'].nunique()}")

    return agg_df

def main():
    print("=" * 60)
    print("📊 YILLIK VERİ AGGREGASYON SCRİPTİ")
    print("=" * 60)

    # Excel dosyalarını bul
    excel_dosyalari = excel_dosyalarini_bul(EXCEL_KLASORU)

    if not excel_dosyalari:
        print(f"\n❌ {EXCEL_KLASORU} klasöründe Excel dosyası bulunamadı!")
        print("   EXCEL_KLASORU değişkenini kontrol edin.")
        return

    # Tüm dosyaları oku ve birleştir
    tum_veriler = []
    for dosya in excel_dosyalari:
        df = excel_oku_ve_normalize(dosya, KOLON_ESLEME)
        if df is not None:
            tum_veriler.append(df)

    if not tum_veriler:
        print("\n❌ Hiçbir dosya okunamadı!")
        return

    # Birleştir
    print(f"\n📎 {len(tum_veriler)} dosya birleştiriliyor...")
    combined_df = pd.concat(tum_veriler, ignore_index=True)
    print(f"   Toplam satır: {len(combined_df):,}")

    # Aggrege et
    agg_df = aggrege_et(combined_df)

    # Parquet olarak kaydet
    print(f"\n💾 Kaydediliyor: {CIKTI_DOSYASI}")
    agg_df.to_parquet(CIKTI_DOSYASI, index=False)

    # Dosya boyutunu göster
    dosya_boyutu = os.path.getsize(CIKTI_DOSYASI) / (1024 * 1024)
    print(f"   Dosya boyutu: {dosya_boyutu:.1f} MB")

    print("\n" + "=" * 60)
    print("✅ TAMAMLANDI!")
    print(f"   Çıktı: {CIKTI_DOSYASI}")
    print(f"   Bu dosyayı GitHub'a yükleyin ve App.py'deki URL'i güncelleyin.")
    print("=" * 60)

if __name__ == "__main__":
    main()
