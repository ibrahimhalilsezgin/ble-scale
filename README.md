# ESP32-S3 BLE Smart Scale Sniffer & BIA Telemetry Dashboard

ESP32-S3 (`NimBLE-Arduino`) kullanarak Bluetooth Low Energy (BLE) akıllı tartıların yayınladığı reklam paketlerini (`Manufacturer Specific Data`) gerçek zamanlı yakalayan, tersine mühendislik ile çözümlenen **15-byte `0xC0` tartı protokolünü** ayrıştıran ve **Biyoelektrik Empedans Analizi (BIA)** ile 10 farklı vücut kompozisyonu verisini canlı web arayüzünde sunan telemetri sistemi.

---

## Özellikler

- **Kesintisiz BLE Yakalama (ESP32-S3 & NimBLE 2.5.0):**
  - `DuplicateFilter(0)` ve `MaxResults(0)` ile RAM şişirmeden tartının yayınladığı her reklam paketini milisaniye bazında yakalar.
  - Yalnızca hedef MAC adresini filtreler ve ardışık paketler arasındaki byte farklarını (`[DIFF]`) anlık hesaplar.
- **Tersine Mühendislik ile Çözümlenmiş 15-Byte `0xC0` Protokolü:**
  - Canlı ağırlık (`0.01 kg` hassasiyet), paket sayacı (`SEQ`), BIA empedans direnci (`Ω`), açık-devre / çıplak ayak temas tespiti (`0x1770` / `6000`) ve sabitlenme (`Lock bit 0`) bayrağı çözümlemesi.
- **Gerçek Zamanlı Web Telemetri & BIA Kokpiti (`server.py` + `index.html`):**
  - **Canlı Dijital Tartı Kadranı:** Anlık `kg` / `lb`, ham `uint16` değer, `ÖLÇÜLÜYOR...` ve `SABİTLENDİ / KİLİTLİ` durum göstergeleri.
  - **BIA Vücut Kompozisyonu Motoru:** Boy, yaş ve cinsiyet profiliyle; **VKİ (BMI)**, **Vücut Yağ Oranı (%)**, **Kas Kütlesi (kg)**, **Yağsız Kütle (FFM)**, **Toplam Vücut Suyu (% & L)**, **Kemik Mineral Kütlesi (kg)**, **Protein Oranı (%)**, **Bazal Metabolizma (BMR kcal)**, **Metabolik Yaş** ve **İç Organ Yağlanma Skorunu** hesaplar.
  - **Canlı Paket Denetçisi (Live Packet Inspector):** Gelen her paketi `HEX`, `DEC`, `8-bit Binary` düzeyinde parçalar; akışı duraklatma, geçmiş paketlere tıklayarak bit inceleme ve `JSON` dışa aktarma sunar.

---

## 15-Byte BLE Manufacturer Data Protokol Yapısı

Tartı, BLE reklam paketinin `0xFF` (Manufacturer Specific Data) alanında **15 byte** uzunluğunda veri yayınlar:

```text
Örnek Paket (Ölçüm Anı) : C0 3D 05 9B 00 00 0A 01 24 78 66 A5 25 89 CB
Örnek Paket (Kilitli)   : C0 47 05 9B 17 70 0A 01 25 78 66 A5 25 89 CB
```

| Byte İndeksi | Alan Adı | Tip | Açıklama |
| :--- | :--- | :--- | :--- |
| `b[0]` | **Header** | `uint8` | Sabit protokol başlığı (`0xC0`) |
| `b[1]` | **Sequence (`SEQ`)** | `uint8` | Her yeni ölçüm paketinde `+1` artan paket sayacı |
| `b[2..3]` | **Weight (`W_H`, `W_L`)** | `uint16 BE` | `(b[2] << 8) \| b[3]` $\rightarrow$ `değer / 100.0 = kg` (Örn: `0x059B` = `1435` = **`14.35 kg`**) |
| `b[4..5]` | **BIA Impedance (`IMP_H`, `IMP_L`)** | `uint16 BE` | Ölçüm sürerken `0x0000` (`0`). Çıplak ayak teması yoksa `0x1770` (`6000` açık devre kodu). Çıplak ayakla ölçüm tamamlandığında gerçek vücut direnci (`Ω`). |
| `b[6]` | **Protocol Flag** | `uint8` | Protokol kontrol sabiti (`0x0A`) |
| `b[7]` | **Unit Flag** | `uint8` | Birim bayrağı (`0x01` = Kilogram `kg`) |
| `b[8]` | **Status / Lock Flag** | `uint8` | `0x24` (`00100100`) = Ölçülüyor, `0x25` (`00100101`) = **Sabitlendi / Kilitli** (`bit 0 == 1`) |
| `b[9..14]` | **MAC Address** | `uint8[6]` | Tartının 6 byte donanım MAC adresi (`78:66:A5:25:89:CB`) |

---

## Proje Yapısı

```text
ble_scale/
├── ble_scale.ino      # ESP32-S3 NimBLE-Arduino yakalayıcı ve seri port protokol çözücü
├── server.py          # COM port dinleyici, 15-byte hex parser ve yerel HTTP/JSON sunucusu
├── index.html         # Canlı tartı kadranı, BIA vücut analizi ve paket/bit denetçisi arayüzü
└── requirements.txt   # Python bağımlılıkları (pyserial)
```

---

## Kurulum & Çalıştırma

### 1. ESP32-S3 Firmware Yükleme
1. Arduino IDE üzerinden **ESP32** kart paketini ve **NimBLE-Arduino** (`v2.x`) kütüphanesini yükleyin.
2. `ble_scale.ino` içindeki `TARGET_MAC` sabitini kendi tartınızın MAC adresiyle eşleştirin.
3. Kart olarak `ESP32S3 Dev Module` seçip kodu yükleyin (`115200` baud).

### 2. Web Telemetri Arayüzünü Başlatma

```bash
pip install -r requirements.txt
python server.py
```

Varsayılan olarak `COM3` portunu dinler (farklı bir port için `SCALE_COM_PORT=COM5 python server.py` kullanabilirsiniz) ve arayüzü şu adreste başlatır:

```text
http://localhost:5050
```

---

## Lisans

MIT
