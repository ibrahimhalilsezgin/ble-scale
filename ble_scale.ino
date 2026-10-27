#include <NimBLEDevice.h>
#include <strings.h>

static const char* TARGET_MAC = "78:66:a5:25:89:cb";
static std::vector<uint8_t> lastPayload;

static void printHex(const uint8_t* d, size_t len) {
  for (size_t i = 0; i < len; i++) {
    Serial.printf("%02X ", d[i]);
  }
}

static void parseScaleMfg(const uint8_t* b, size_t n, int rssi) {
  // 15 byte Manufacturer Data: C0 [SEQ] [W_H W_L] [IMP_H IMP_L] [PROTO] [UNIT] [STATUS/LOCK] [MAC x6]
  if (n < 15) return;

  uint8_t header     = b[0];
  uint8_t seq        = b[1];
  uint16_t wRaw      = (b[2] << 8) | b[3];
  uint16_t impRaw    = (b[4] << 8) | b[5];
  uint8_t protoFlag  = b[6];
  uint8_t unitFlag   = b[7];
  uint8_t statusFlag = b[8];

  float weightKg = wRaw / 100.0f;
  bool isLocked  = (statusFlag & 0x01) != 0;

  Serial.println("  +------------------------------------------------+");
  Serial.printf("  | AGIRLIK   : %.2f kg (%s)\n", weightKg, isLocked ? "SABITLENDI / KILITLI" : "OLCUYOR...");
  Serial.printf("  | EMPEDANS  : %u (BIA Vucut Direnci)\n", impRaw);
  Serial.printf("  | SAYAC/SEQ : #%u (0x%02X)\n", seq, seq);
  Serial.printf("  | BAYRAKLAR : Header=0x%02X Proto=0x%02X Unit=0x%02X Lock=0x%02X\n", header, protoFlag, unitFlag, statusFlag);
  Serial.printf("  | SINYAL    : %d dBm\n", rssi);
  Serial.println("  +------------------------------------------------+");
}

class ScaleScanCallbacks : public NimBLEScanCallbacks {
  void onResult(const NimBLEAdvertisedDevice* dev) override {
    std::string mac = dev->getAddress().toString();
    if (strcasecmp(mac.c_str(), TARGET_MAC) != 0) return;

    const std::vector<uint8_t>& raw = dev->getPayload();
    if (raw == lastPayload) return;

    bool isFirst = lastPayload.empty();
    std::vector<uint8_t> prev = lastPayload;
    lastPayload = raw;

    Serial.printf("\n[TARTI %s] RSSI:%d%s\n",
                  mac.c_str(),
                  dev->getRSSI(),
                  isFirst ? " [ILK TEMAS]" : " [YENI PAKET]");

    Serial.print("  [RAW]: ");
    printHex(raw.data(), raw.size());
    Serial.println();

    if (!isFirst && prev.size() == raw.size()) {
      Serial.print("  [DIFF]: ");
      for (size_t i = 0; i < raw.size(); i++) {
        if (prev[i] != raw[i]) {
          Serial.printf("b[%u]:%02X->%02X ", (unsigned)i, prev[i], raw[i]);
        }
      }
      Serial.println();
    }

    if (dev->haveManufacturerData()) {
      std::string md = dev->getManufacturerData();
      parseScaleMfg((const uint8_t*)md.data(), md.size(), dev->getRSSI());
    }
  }
} scanCallbacks;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.printf("\n=== ESP32-S3 TARTI COZUCU (%s) ===\n", TARGET_MAC);

  NimBLEDevice::init("");
  NimBLEScan* pScan = NimBLEDevice::getScan();
  pScan->setScanCallbacks(&scanCallbacks, true);
  pScan->setActiveScan(true);
  pScan->setInterval(45);
  pScan->setWindow(45);
  pScan->setDuplicateFilter(0);
  pScan->setMaxResults(0);
  pScan->start(0, false, true);
}

void loop() {
  delay(1000);
}
