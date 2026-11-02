# 🚗 GM Buddy Araç Takip Sunucusu (Tracker Server)

GM Buddy GPS Araç Takip Cihazı için hafif (lightweight), harici kütüphane bağımlılığı olmayan ve mobil uyumlu canlı GPS takip sunucusu.

---

## 🌟 Özellikler
- **Saf Python 3 & SQLite:** Harici hiçbir paket (`pip`) gerektirmez.
- **Canlı Takip:** Saatten 4G/GPRS ile gelen enlem, boylam, hız, batarya seviyesi ve şarj durumunu anlık gösterir.
- **Gün Bazlı Geçmiş & Duraklama:** Tarih seçici ile gün gün rotayı ve aracın nerede kaç dakika durakladığını (zaman çizelgesi olarak) listeler.
- **Modern Harita:** Esri Dark Canvas, OpenStreetMap ve Esri Uydu Haritası desteği.
- **PWA Desteği:** Mobilde ve masaüstünde uygulama gibi kurulabilir.

---

## 🚀 Render.com Üzerinde 7/24 Ücretsiz Dağıtım (Deploy)

1. [Render.com](https://render.com) adresine gidin ve GitHub hesabınızla giriş yapın.
2. **New +** -> **Web Service** seçeneğine tıklayın.
3. Bu depoyu (`tracker_server`) seçin.
4. Ayarları şu şekilde yapın:
   - **Environment:** `Python 3`
   - **Build Command:** *(boş bırakın veya `pip install -r requirements.txt`)*
   - **Start Command:** `python server.py`
   - **Plan Type:** `Free`
5. **Create Web Service** butonuna basın. Birkaç saniye içinde `https://<uygulama-adiniz>.onrender.com` şeklinde ücretsiz 7/24 HTTPS sunucunuz hazır olacaktır!

---

## 📡 API Uç Noktaları

| Endpoint | Metot | Açıklama |
|---|---|---|
| `/` | `GET` | Web Kontrol Paneli (Dashboard) |
| `/api/report` | `POST` | Saatten telemetri verisi alma (`lat`, `lon`, `speed`, `battery`, ...) |
| `/api/live` | `GET` | En son canlı konum ve araç durumu |
| `/api/history?date=YYYY-MM-DD` | `GET` | Seçilen güne ait rota geçmişi |
| `/api/stops?date=YYYY-MM-DD` | `GET` | Seçilen güne ait duraklama analizleri |
| `/api/dates` | `GET` | Veritabanında kayıtlı günlerin listesi |
| `/api/clear` | `POST` | Veritabanını sıfırlama |
