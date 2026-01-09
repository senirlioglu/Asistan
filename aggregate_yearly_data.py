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

# Excel'deki kolon isimleri (senin dosyalarına göre ayarla)
KOLON_ESLEME = {
    'Magaza_Kod': 'Magaza_Kod',     # veya 'MAGAZA_KODU', 'Mağaza Kodu' vs.
    'Urun_Kod': 'Urun_Kod',         # veya 'URUN_KODU', 'Ürün Kodu' vs.
    'Mal_Grubu': 'Mal_Grubu',       # veya 'MAL_GRUBU', 'Mal Grubu' vs.
    'Nitelik': 'Nitelik',           # veya 'NITELIK', 'Kampanya Niteliği' vs.
    'Adet': 'Adet',                 # veya 'ADET', 'Satış Adedi' vs.
    'Ciro': 'Ciro'                  # veya 'CIRO', 'Satış Tutarı' vs.
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
        print(f"   Kolonlar: {list(df.columns)}")

        # Kolon isimlerini normalize et
        df.columns = df.columns.str.strip()

        # Gerekli kolonları seç ve yeniden adlandır
        kolonlar_mevcut = {}
        for hedef, kaynak in kolon_esleme.items():
            if kaynak in df.columns:
                kolonlar_mevcut[kaynak] = hedef
            else:
                # Alternatif isimler dene
                alternatifler = {
                    'Magaza_Kod': ['MAGAZA_KODU', 'Mağaza Kodu', 'MAGAZA_KOD', 'Magaza Kodu'],
                    'Urun_Kod': ['URUN_KODU', 'Ürün Kodu', 'URUN_KOD', 'Urun Kodu'],
                    'Mal_Grubu': ['MAL_GRUBU', 'Mal Grubu', 'MAL_GRUBU_ADI', 'Mal Grubu Adı'],
                    'Nitelik': ['NITELIK', 'Kampanya Niteliği', 'NİTELİK', 'Kampanya Niteligi'],
                    'Adet': ['ADET', 'Satış Adedi', 'SATIS_ADET', 'Toplam Adet'],
                    'Ciro': ['CIRO', 'Satış Tutarı', 'SATIS_TUTAR', 'Toplam Ciro']
                }

                for alt in alternatifler.get(hedef, []):
                    if alt in df.columns:
                        kolonlar_mevcut[alt] = hedef
                        break

        if len(kolonlar_mevcut) < 4:
            print(f"   ⚠️ UYARI: Bazı kolonlar bulunamadı!")
            print(f"   Bulunan: {list(kolonlar_mevcut.keys())}")
            return None

        # Sadece gerekli kolonları al ve yeniden adlandır
        df = df[list(kolonlar_mevcut.keys())].rename(columns=kolonlar_mevcut)

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
