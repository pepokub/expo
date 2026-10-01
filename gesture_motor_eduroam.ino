#include <WiFi.h>
#include <WiFiUdp.h>
#include <InEngMotor.h>

// ---------- ตั้งค่า WiFi ----------
// eduroam = WPA2-Enterprise (ใช้ username + password)
const char* EAP_SSID     = "KMUTT-Secure";
const char* EAP_IDENTITY = "phoobadee.suwan@kmutt.ac.th";  // ถ้าเชื่อมไม่ติด ลอง anonymous@YOUR_UNI.ac.th
const char* EAP_USERNAME = "69070503472";  // ใช้ username แบบเดียวกับที่กรอกบนคอม
const char* EAP_PASSWORD = "pepoInwza007.";
const bool USE_AP = false;                  // true = บอร์ดปล่อย WiFi "GestureCar" เอง

const unsigned int UDP_PORT = 4210;

// ---------- DEBUG ----------
const bool DEBUG = true;                    // ปิดได้ด้วยการเปลี่ยนเป็น false
const unsigned long NO_PACKET_WARN_MS = 2000;

// ---------- ตั้งค่ามอเตอร์ ----------
const int  SPEED = 200;
const unsigned long TIMEOUT_MS = 500;       // ไม่ได้รับคำสั่งเกินนี้ -> หยุดเอง

WiFiUDP udp;
char currentCmd = 'S';
unsigned long lastCmdTime = 0;
unsigned long lastRxTime = 0;
unsigned long lastWarnTime = 0;
unsigned long rxCount = 0;

void applyCommand(char c) {
  switch (c) {
    case 'F': inengmotor.forward(SPEED, SPEED);  break;
    case 'B': inengmotor.backward(SPEED, SPEED); break;
    case 'L': inengmotor.turnLeft(80, 180);      break;
    case 'R': inengmotor.turnRight(180, 80);     break;
    case 'K': inengmotor.brake();                break;
    case 'S':
    default:  inengmotor.stop();                 break;
  }
}

bool isValidCmd(char c) {
  return c == 'F' || c == 'B' || c == 'L' || c == 'R' || c == 'S' || c == 'K';
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=== Gesture Motor eduroam (DEBUG) ===");

  inengmotor.begin();
  inengmotor.stop();

  if (USE_AP) {
    WiFi.mode(WIFI_AP);
    WiFi.softAP("GestureCar", "12345678");
    Serial.print("AP started. IP: ");
    Serial.println(WiFi.softAPIP());
  } else {
    WiFi.mode(WIFI_STA);
    // ใช้กับ ESP32 Arduino core 3.x (ดูเวอร์ชันที่ Tools > Board > Boards Manager)
    WiFi.begin(EAP_SSID, WPA2_AUTH_PEAP, EAP_IDENTITY, EAP_USERNAME, EAP_PASSWORD);
    Serial.print("Connecting to WiFi");
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      Serial.print(".");
      if (millis() - start > 20000) {
        Serial.println("\nWiFi timeout, restarting...");
        ESP.restart();
      }
    }
    Serial.println();
    Serial.print("Connected. IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("MAC: ");
    Serial.println(WiFi.macAddress());
    Serial.print("Signal (RSSI): ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  }

  WiFi.setSleep(false);
  udp.begin(UDP_PORT);
  Serial.print("Listening UDP port ");
  Serial.println(UDP_PORT);
  Serial.println("Waiting for packets from Python...");

  lastCmdTime = millis();
  lastRxTime = millis();
  lastWarnTime = millis();
}

void loop() {
  int packetSize = udp.parsePacket();
  if (packetSize > 0) {
    char buf[16];
    int len = udp.read(buf, sizeof(buf) - 1);
    if (len < 0) len = 0;
    buf[len] = '\0';

    rxCount++;
    lastRxTime = millis();

    // ===== DEBUG: แสดงสิ่งที่ได้รับ "ก่อน" เข้า if/else ตรวจคำสั่ง =====
    if (DEBUG) {
      Serial.print("[RX #");
      Serial.print(rxCount);
      Serial.print("] from ");
      Serial.print(udp.remoteIP());
      Serial.print(":");
      Serial.print(udp.remotePort());
      Serial.print(" | packetSize=");
      Serial.print(packetSize);
      Serial.print(" len=");
      Serial.print(len);
      Serial.print(" | hex=");
      for (int i = 0; i < len; i++) {
        Serial.printf("%02X ", (uint8_t)buf[i]);
      }
      Serial.print("| text='");
      for (int i = 0; i < len; i++) {
        char ch = buf[i];
        if (ch >= 32 && ch <= 126) Serial.print(ch);
        else Serial.print('?');
      }
      Serial.print("'");
    }

    // ===== ตรวจคำสั่ง (ใช้ตัวอักษรที่ถูกต้องตัวสุดท้ายในแพ็กเก็ต) =====
    bool matched = false;
    for (int i = len - 1; i >= 0; i--) {
      if (isValidCmd(buf[i])) {
        matched = true;
        lastCmdTime = millis();
        if (buf[i] != currentCmd) {
          if (DEBUG) {
            Serial.print(" -> VALID '");
            Serial.print(buf[i]);
            Serial.print("' CHANGED ");
            Serial.print(currentCmd);
            Serial.print(" => ");
            Serial.print(buf[i]);
          }
          currentCmd = buf[i];
          applyCommand(currentCmd);
        } else if (DEBUG) {
          Serial.print(" -> VALID '");
          Serial.print(buf[i]);
          Serial.print("' (same, no change)");
        }
        break;
      }
    }
    if (DEBUG) {
      if (!matched) Serial.print(" -> INVALID (ไม่ตรงกับ F B L R S K) ignored");
      Serial.println();
    }
  }

  // ===== DEBUG: เตือนถ้าไม่มีแพ็กเก็ตเข้ามาเลย =====
  if (DEBUG && millis() - lastRxTime > NO_PACKET_WARN_MS &&
      millis() - lastWarnTime > NO_PACKET_WARN_MS) {
    lastWarnTime = millis();
    Serial.print("[WARN] ไม่มีแพ็กเก็ตมา ");
    Serial.print((millis() - lastRxTime) / 1000);
    Serial.print(" วินาที | WiFi status=");
    Serial.print(WiFi.status() == WL_CONNECTED ? "CONNECTED" : "NOT CONNECTED");
    if (!USE_AP) {
      Serial.print(" | IP=");
      Serial.print(WiFi.localIP());
      Serial.print(" | RSSI=");
      Serial.print(WiFi.RSSI());
    }
    Serial.println();
  }

  // Failsafe
  if (currentCmd != 'S' && millis() - lastCmdTime > TIMEOUT_MS) {
    if (DEBUG) Serial.println("[FAILSAFE] timeout -> STOP");
    currentCmd = 'S';
    applyCommand('S');
  }
}
