# A101 Kampanya Asistanı

Bu proje A101 kampanya asistanı uygulamasıdır. Streamlit kullanılarak geliştirilmiştir.

## Kurulum ve Çalıştırma

### Gereksinimler
- Python 3.11+
- `requirements.txt` dosyasındaki kütüphaneler

### Yerel Çalıştırma
```bash
pip install -r requirements.txt
streamlit run App.py
```

## Dağıtım (Deployment)

Bu uygulama **Streamlit Cloud** ve **Railway** üzerinde çalışacak şekilde yapılandırılmıştır.

### 1. Streamlit Cloud

1. Streamlit Cloud hesabınıza giriş yapın.
2. "New app" butonuna tıklayın.
3. GitHub repository'nizi seçin.
4. Ana dosya yolu olarak `App.py` seçin.
5. **Advanced settings** bölümünden `Secrets` alanına Google Drive dosya ID'nizi ekleyin:
   ```toml
   GDRIVE_FILE_ID = "dosya_id_buraya"
   ```
6. "Deploy" butonuna tıklayın.

### 2. Railway

1. Railway hesabınıza giriş yapın.
2. "New Project" -> "Deploy from GitHub repo" seçeneğini kullanın.
3. Bu repository'yi seçin.
4. Railway otomatik olarak Python projesi olduğunu algılayacaktır.
5. **Variables** sekmesine gidin ve aşağıdaki değişkeni ekleyin:
   - `GDRIVE_FILE_ID`: Google Drive dosya ID'niz
   - `PERFORMANS_URL_2025`: (Varsa) Performans verisi URL'si
6. Uygulama otomatik olarak build edilecek ve `Procfile` sayesinde `streamlit run` komutu ile başlatılacaktır.

## Ortam Değişkenleri

Uygulamanın düzgün çalışması için aşağıdaki ortam değişkenlerine (veya secrets) ihtiyacı vardır:

- `GDRIVE_FILE_ID`: Performans verisinin bulunduğu Google Drive dosyasının ID'si. Bu zorunludur.
- `PERFORMANS_URL_2025`: Opsiyonel performans URL'si.
