#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <Wire.h>
#include <LiquidCrystal_PCF8574.h>
#include "DHT.h"
#include <ModbusMaster.h>
#include <Adafruit_INA219.h>
#include <Preferences.h>
#include "driver/rtc_io.h"
#include "esp_system.h"


#define MAX485_DE 48
#define MAX485_RE 48
#define RXD2 16 // RO
#define TXD2 15 // DI

#define WAKEUP_PIN 1
#define SW_BT 2

ModbusMaster node;

#define DHTPIN 36
#define DHTTYPE DHT22
DHT dht(DHTPIN, DHTTYPE);

uint8_t sensorStage = 0;        // controla qué sensor leer en cada ciclo
const unsigned long sensorInterval = 200; // tiempo entre lecturas de sensores
unsigned long lastSensorMillis = 0;

unsigned long lastBLEMillis = 0;
unsigned long intervaloBLE = 2000;
unsigned long hibernateMinutes = 0;  // en modo Bluetooth, 0 = sin hibernar
const unsigned long HIBERNATE_MINUTES_NORMAL_MODE = 10;

const int LED_PIN = 21;      // Pin del LED (GPIO34 es solo entrada)
bool ledState = false;       // Estado del LED
unsigned long previousMillis = 0;
const long blinkInterval = 1000; // tiempo de titileo inicial en ms
bool bleEncendiendo = false; // bandera mientras BLE inicia
bool bleActivo = false;      // BLE activo después de encender
bool bleInitialized = false;
bool bleClientConnected = false;
bool bleRestartAdvertisingRequested = false;
unsigned long bleRestartAdvertisingAt = 0;
const unsigned long BLE_RESTART_DELAY_MS = 250;
esp_sleep_wakeup_cause_t bootWakeupCause = ESP_SLEEP_WAKEUP_UNDEFINED;
RTC_DATA_ATTR bool deepSleepArmed = false;
int lastWakePinLevel = -1;

void configureWakeupPinForRunMode();
bool prepareWakeupPinForDeepSleep();

LiquidCrystal_PCF8574 lcd(0x27); //0x3f

TwoWire I2C_BATT = TwoWire(1);

Adafruit_INA219 ina219;

Preferences preferences;

float voltaje_min = 9.0;
float voltaje_max = 12.6;

// BLE
BLECharacteristic *pCharacteristic;

uint8_t result;
uint16_t rawValue;

float humedad, temperatura, ph;
uint16_t ce, N, P, K;

float dht_h = NAN, dht_t = NAN;

unsigned long ceCeroInicio = 0;
bool ceEnCero = false;
volatile bool hibernateCountdownResetRequested = false;

// En modo normal se fuerza 1 minuto. En modo Bluetooth lo define hibernateMinutes.

//String rxValue;

class MyServerCallbacks: public BLEServerCallbacks {
  void onConnect(BLEServer *pServer) override {
    bleClientConnected = true;
    bleRestartAdvertisingRequested = false;
    Serial.println("Cliente BLE conectado");
  }

  void onDisconnect(BLEServer *pServer) override {
    bleClientConnected = false;

    if (bleActivo) {
      bleRestartAdvertisingRequested = true;
      bleRestartAdvertisingAt = millis() + BLE_RESTART_DELAY_MS;
      Serial.println("Cliente BLE desconectado. Reiniciando advertising...");
    } else {
      Serial.println("Cliente BLE desconectado");
    }
  }
};

class MyCallbacks: public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *pCharacteristic) {

    String rxValue = pCharacteristic->getValue();

    if (rxValue.length() > 0) {

      Serial.print("Recibido por BLE: ");
      Serial.println(rxValue);

      // Format: "interval_ms,hibernate_minutes" (e.g. "2000,10")
      int commaIdx = rxValue.indexOf(',');

      if (commaIdx > 0) {
        // New format with both values
        unsigned long newInterval = rxValue.substring(0, commaIdx).toInt();
        unsigned long newHibernate = rxValue.substring(commaIdx + 1).toInt();

        if (newInterval > 0) {
          intervaloBLE = newInterval;
          hibernateMinutes = newHibernate;  // 0 is valid (no timer wakeup)
          hibernateCountdownResetRequested = true;

          preferences.begin("config", false);
          preferences.putUInt("ble_int", intervaloBLE);
          preferences.putUInt("hib_min", hibernateMinutes);
          preferences.end();

          Serial.print("Nuevo intervalo guardado: ");
          Serial.println(intervaloBLE);
          Serial.print("Hibernacion guardada: ");
          Serial.print(hibernateMinutes);
          Serial.println(" min");
        } else {
          Serial.println("Valor de intervalo invalido");
        }
      } else {
        // Legacy format: single integer for interval only
        unsigned long nuevo = rxValue.toInt();

        if (nuevo > 0) {
          intervaloBLE = nuevo;

          preferences.begin("config", false);
          preferences.putUInt("ble_int", intervaloBLE);
          preferences.end();

          Serial.print("Nuevo intervalo guardado: ");
          Serial.println(intervaloBLE);
        } else {
          Serial.println("Valor invalido recibido");
        }
      }
    }
  }
};

void entrarDeepSleep() {

  Serial.println("Entrando en modo ahorro extremo...");
  deepSleepArmed = true;

  // Evita deinit del stack BLE aquí: en sesiones activas puede disparar panic por heap.
  if (bleInitialized) {
    bleActivo = false;
    bleClientConnected = false;
    bleRestartAdvertisingRequested = false;
    BLEDevice::stopAdvertising();
  }

  // Apagar pantalla si quieres
  lcd.clear();
  lcd.setBacklight(0);

  if (!prepareWakeupPinForDeepSleep()) {
    deepSleepArmed = false;
    return;
  }

  // Solo wakeup por botón físico
  esp_sleep_enable_ext0_wakeup((gpio_num_t)WAKEUP_PIN, 1);

  delay(50);
  delay(100); // pequeño margen

  esp_deep_sleep_start();
}


// ================= LED =================
void updateLED() {
  unsigned long currentMillis = millis();

  if (bleEncendiendo) {
    // Titilar mientras BLE se inicializa
    if (currentMillis - previousMillis >= blinkInterval) {
      previousMillis = currentMillis;
      ledState = !ledState;
      digitalWrite(LED_PIN, ledState ? HIGH : LOW);
    }
  } else if (bleActivo) {
    // Mantener encendido mientras BLE activo
    digitalWrite(LED_PIN, LOW);
  } else {
    // Apagar LED si BLE está apagado
    digitalWrite(LED_PIN, HIGH);
  }
}

void blinkLED(int pin, float duracionSegundos, unsigned long intervaloMs) {
  unsigned long start = millis();
  bool ledState = false;
  unsigned long previousMillis = 0;

  while (millis() - start < duracionSegundos * 1000) {
    unsigned long now = millis();
    if (now - previousMillis >= intervaloMs) {
      previousMillis = now;
      ledState = !ledState;
      digitalWrite(pin, ledState ? HIGH : LOW);
    }
  }
  digitalWrite(pin, LOW); // Apaga LED al terminar
}

// ================= LCD =================
void mostrarLCD(float porcentaje) {

  lcd.clear();

 // Línea 1
  lcd.setCursor(0,0);
  lcd.print("T:");
  lcd.print(dht_t,1);
  /*
 
  lcd.print(" H:");
  lcd.print(dht_h,1);
*/
  lcd.setCursor(6,0);
  lcd.print("[|||]");
  lcd.print(porcentaje,1);
  lcd.print("%");

  // Línea 2
  lcd.setCursor(0,1);
  lcd.print("pH:");
  lcd.print(ph,1);
  lcd.print(" N:");
  lcd.print(N);
  lcd.print(" P:");
  lcd.print(P);

}
/*void mostrarLCD() {

  lcd.clear();

  // Línea 1
  lcd.setCursor(0,0);
  lcd.print("T:");
  lcd.print(temperatura,1);
  lcd.print("C H:");
  lcd.print(humedad,0);

  // Línea 2
  lcd.setCursor(0,1);
  lcd.print("pH:");
  lcd.print(ph,2);
  lcd.print(" CE:");
  lcd.print(ce);

  // Línea 3
  lcd.setCursor(0,2);
  lcd.print("N:");
  lcd.print(N);
  lcd.print(" P:");
  lcd.print(P);

  // Línea 4
  lcd.setCursor(0,3);
  lcd.print("K:");
  lcd.print(K);
}*/


// ================= MODBUS =================
void preTransmission() {
  digitalWrite(MAX485_DE, HIGH);
  digitalWrite(MAX485_RE, HIGH);
  delayMicroseconds(200);
}

void postTransmission() {
  delayMicroseconds(200);
  digitalWrite(MAX485_DE, LOW);
  digitalWrite(MAX485_RE, LOW);
}

const char* modbusErrorName(uint8_t code) {
  switch (code) {
    case 0x00: return "OK";
    case 0x01: return "funcion ilegal";
    case 0x02: return "registro ilegal";
    case 0x03: return "valor ilegal";
    case 0x04: return "fallo del sensor";
    case 0xE0: return "ID incorrecto";
    case 0xE1: return "funcion incorrecta";
    case 0xE2: return "timeout/sin respuesta";
    case 0xE3: return "CRC invalido";
    default: return "desconocido";
  }
}

const char* sensorStageName(uint8_t stage) {
  switch (stage) {
    case 0: return "pH";
    case 1: return "humedad";
    case 2: return "temperatura";
    case 3: return "CE";
    case 4: return "N";
    case 5: return "P";
    case 6: return "K";
    default: return "?";
  }
}

uint16_t sensorStageAddress(uint8_t stage) {
  switch (stage) {
    case 0: return 0x0006;
    case 1: return 0x0012;
    case 2: return 0x0013;
    case 3: return 0x0015;
    case 4: return 0x001E;
    case 5: return 0x001F;
    case 6: return 0x0020;
    default: return 0;
  }
}

void printModbusError(uint8_t stage, uint8_t code) {
  Serial.print("7en1 ERROR ");
  Serial.print(sensorStageName(stage));
  Serial.print(" reg 0x");
  uint16_t address = sensorStageAddress(stage);
  if (address < 0x1000) Serial.print("0");
  if (address < 0x0100) Serial.print("0");
  if (address < 0x0010) Serial.print("0");
  Serial.print(address, HEX);
  Serial.print(" -> 0x");
  if (code < 0x10) Serial.print("0");
  Serial.print(code, HEX);
  Serial.print(" (");
  Serial.print(modbusErrorName(code));
  Serial.println(")");
}

void configureWakeupPinForRunMode() {
  rtc_gpio_deinit((gpio_num_t)WAKEUP_PIN);
  pinMode(WAKEUP_PIN, INPUT_PULLDOWN);
}

bool prepareWakeupPinForDeepSleep() {
  rtc_gpio_deinit((gpio_num_t)WAKEUP_PIN);
  rtc_gpio_init((gpio_num_t)WAKEUP_PIN);
  rtc_gpio_set_direction((gpio_num_t)WAKEUP_PIN, RTC_GPIO_MODE_INPUT_ONLY);
  rtc_gpio_pullup_dis((gpio_num_t)WAKEUP_PIN);
  rtc_gpio_pulldown_en((gpio_num_t)WAKEUP_PIN);

  delay(10);

  int wakeLevel = rtc_gpio_get_level((gpio_num_t)WAKEUP_PIN);
  Serial.print("Wake pin level antes de dormir: ");
  Serial.println(wakeLevel);

  if (wakeLevel == 1) {
    Serial.println("Wake pin ya esta en HIGH. Se cancela deep sleep para evitar wakeup inmediato.");
    configureWakeupPinForRunMode();
    return false;
  }

  return true;
}

const char* resetReasonName(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_UNKNOWN: return "desconocido";
    case ESP_RST_POWERON: return "power on";
    case ESP_RST_EXT: return "reset externo";
    case ESP_RST_SW: return "reset por software";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT: return "watchdog interno";
    case ESP_RST_TASK_WDT: return "watchdog tarea";
    case ESP_RST_WDT: return "watchdog";
    case ESP_RST_DEEPSLEEP: return "salida de deep sleep";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_SDIO: return "SDIO";
    default: return "otro";
  }
}

const char* wakeupCauseName(esp_sleep_wakeup_cause_t cause) {
  switch (cause) {
    case ESP_SLEEP_WAKEUP_EXT0: return "EXT0 boton";
    case ESP_SLEEP_WAKEUP_EXT1: return "EXT1";
    case ESP_SLEEP_WAKEUP_TIMER: return "timer";
    case ESP_SLEEP_WAKEUP_TOUCHPAD: return "touch";
    case ESP_SLEEP_WAKEUP_ULP: return "ULP";
    case ESP_SLEEP_WAKEUP_UNDEFINED: return "arranque normal";
    default: return "otro";
  }
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  delay(400);
  Serial.println();
  Serial.println("=== AgroPrecision ESP32 ===");
  esp_reset_reason_t resetReason = esp_reset_reason();
  bootWakeupCause = esp_sleep_get_wakeup_cause();
  Serial.print("Reset reason: ");
  Serial.print((int)resetReason);
  Serial.print(" (");
  Serial.print(resetReasonName(resetReason));
  Serial.println(")");
  Serial.print("Wakeup cause: ");
  Serial.print((int)bootWakeupCause);
  Serial.print(" (");
  Serial.print(wakeupCauseName(bootWakeupCause));
  Serial.println(")");
  Serial.print("Deep sleep armado antes del arranque: ");
  Serial.println(deepSleepArmed ? "si" : "no");
  deepSleepArmed = false;
  Serial.print("RS485 RXD2 GPIO");
  Serial.print(RXD2);
  Serial.print(" | TXD2 GPIO");
  Serial.print(TXD2);
  Serial.print(" | DE/RE GPIO");
  Serial.println(MAX485_DE);
  Serial.println("Modbus 7en1: ID=1, 9600 baud, 8N1");

  Wire.begin(38, 39);  // SDA, SCL
  lcd.begin(16, 4);
  lcd.setBacklight(255);
  lcd.clear();
  lcd.setCursor(0,0);
  lcd.print("Iniciando ");
  lcd.setCursor(0,1);
  lcd.print("Sistema");

    I2C_BATT.begin(40, 41);

  if (!ina219.begin(&I2C_BATT)) {
    Serial.println("Error INA219");
  }

  dht.begin();

  Serial2.begin(9600, SERIAL_8N1, RXD2, TXD2);

  pinMode(MAX485_DE, OUTPUT);
  pinMode(MAX485_RE, OUTPUT);

  digitalWrite(MAX485_DE, LOW);
  digitalWrite(MAX485_RE, LOW);

  node.begin(1, Serial2);
  node.preTransmission(preTransmission);
  node.postTransmission(postTransmission);

  pinMode(SW_BT, INPUT_PULLUP);
  configureWakeupPinForRunMode();
  lastWakePinLevel = digitalRead(WAKEUP_PIN);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);

  preferences.begin("config", true);  // true = solo lectura

  intervaloBLE = preferences.getUInt("ble_int", 2000);
  // si no existe, usa 2000 como valor por defecto
  hibernateMinutes = preferences.getUInt("hib_min", 0);

  preferences.end();

  Serial.print("Intervalo BLE cargado: ");
  Serial.println(intervaloBLE);
  Serial.print("Hibernacion cargada: ");
  Serial.print(hibernateMinutes);
  Serial.println(" min");
  Serial.print("Modo inicial por switch: ");
  Serial.println((digitalRead(SW_BT) == LOW) ? "Bluetooth" : "Normal");
  Serial.print("Wake pin inicial en ejecucion: ");
  Serial.println(lastWakePinLevel);
  Serial.print("Resumen wakeup cause: ");
  Serial.print((int)bootWakeupCause);
  Serial.print(" (");
  Serial.print(wakeupCauseName(bootWakeupCause));
  Serial.println(")");

  setupBLE();
  
}

// ================= BLE SETUP =================
void setupBLE() {
  BLEDevice::init("ESP32_SENSOR");
  bleInitialized = true;

  BLEServer *pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());
  BLEService *pService = pServer->createService("1234");

  pCharacteristic = pService->createCharacteristic(
                      "5678",
                      BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_WRITE
                    );
  
  pCharacteristic->setCallbacks(new MyCallbacks());

  pCharacteristic->addDescriptor(new BLE2902());

  pService->start();

  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID("1234");
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);
  pAdvertising->setMinPreferred(0x12);

  /*BLEDevice::startAdvertising();

  Serial.println("BLE listo y anunciando");
  lcd.clear();
  lcd.setCursor(0,0);
  lcd.print("Iniciando ");
  lcd.setCursor(0,1);
  lcd.print("Bluetooth");*/
}

// ================= ENVÍO BLE =================
void sendBLE() {

  if (!bleClientConnected) {
    return;
  }

  char msg[240];
  float safe_dht_t = isnan(dht_t) ? 0.0f : dht_t;
  float safe_dht_h = isnan(dht_h) ? 0.0f : dht_h;

  snprintf(msg, sizeof(msg),
    "{\"dht\":{\"t\":%.2f,\"h\":%.2f},\"sensor7en1\":{\"temperatura\":%.2f,\"humedad\":%.2f,\"Ph\":%.2f,\"Ce\":%u,\"N\":%u,\"P\":%u,\"K\":%u}}",
    safe_dht_t, safe_dht_h, temperatura, humedad, ph, ce, N, P, K);

  pCharacteristic->setValue((uint8_t*)msg, strlen(msg));
  pCharacteristic->notify();  // 🔥 CLAVE

  Serial.println(msg);
}

// ================= LOOP =================
void loop() {

  unsigned long now = millis();
  float voltaje = 0;
  float porcentaje = 0;
  bool resetHibernateCountdownNow = false;

   bool estadoSwitch = true;  // PRUEBA: BLE forzado activo — devolver a: (digitalRead(SW_BT) == LOW)
   unsigned long activeHibernateMinutes = estadoSwitch
    ? hibernateMinutes
    : HIBERNATE_MINUTES_NORMAL_MODE;
   int wakePinLevel = digitalRead(WAKEUP_PIN);

   if (wakePinLevel != lastWakePinLevel) {
    lastWakePinLevel = wakePinLevel;
    Serial.print("Wake pin cambio a: ");
    Serial.println(wakePinLevel);
   }

   if (hibernateCountdownResetRequested) {
    resetHibernateCountdownNow = true;
    hibernateCountdownResetRequested = false;
   }

   // 🔥 ENCENDER BLE
    if (estadoSwitch && !bleActivo) {
    bleEncendiendo = true;   // comienza titileo
    Serial.println("Encendiendo BLE...");
    if (!bleInitialized) {
      setupBLE();
    }
    bleEncendiendo = false;  // termina titileo
    bleActivo = true;
    bleClientConnected = false;
    bleRestartAdvertisingRequested = false;
      Serial.println("BLE listo y anunciando");
      lcd.clear();
      lcd.setCursor(0,0);
      lcd.print("Iniciando ");
      lcd.setCursor(0,1);
      lcd.print("Bluetooth");
      BLEDevice::startAdvertising();      // BLE ya activo
      blinkLED(LED_PIN, 1, 200);
      updateLED(); 
    }

  // 🔥 APAGAR BLE
    if (!estadoSwitch && bleActivo) {
    lcd.clear();
    lcd.setCursor(0,0);
    lcd.print("Apagando");
    lcd.setCursor(0,1);
    lcd.print("Bluetooth");
    Serial.println("Apagando BLE...");
    bleActivo = false;
    BLEDevice::stopAdvertising();
    bleClientConnected = false;
    bleRestartAdvertisingRequested = false;
    blinkLED(LED_PIN, 1, 200);
    updateLED();
    }


  if (bleRestartAdvertisingRequested && bleActivo && !bleClientConnected && ((long)(now - bleRestartAdvertisingAt) >= 0)) {
    BLEDevice::startAdvertising();
    bleRestartAdvertisingRequested = false;
    Serial.println("BLE advertising reiniciado tras desconexion");
  }

  if (now - lastSensorMillis >= sensorInterval) {
    lastSensorMillis = now;

    voltaje = ina219.getBusVoltage_V();
    porcentaje = (voltaje - voltaje_min) / (voltaje_max - voltaje_min) * 100.0;
    porcentaje = constrain(porcentaje, 0, 100);

    // Lectura escalonada de Modbus
    switch(sensorStage) {
      case 0: result = node.readHoldingRegisters(0x0006, 1); break; // pH
      case 1: result = node.readHoldingRegisters(0x0012, 1); break; // Humedad 7 en 1
      case 2: result = node.readHoldingRegisters(0x0013, 1); break; // Temp 7 en 1
      case 3: result = node.readHoldingRegisters(0x0015, 1); break; // CE
      case 4: result = node.readHoldingRegisters(0x001E, 1); break; // N
      case 5: result = node.readHoldingRegisters(0x001F, 1); break; // P
      case 6: result = node.readHoldingRegisters(0x0020, 1); break; // K
    }

    if (result == node.ku8MBSuccess) {
      switch(sensorStage) {
        case 0: ph = node.getResponseBuffer(0)/100.0; break;
        case 1: humedad = node.getResponseBuffer(0)/10.0; break;
        case 2: temperatura = (int16_t)node.getResponseBuffer(0)/10.0; break;
        case 3: ce = node.getResponseBuffer(0); break;
        case 4: N = node.getResponseBuffer(0); break;
        case 5: P = node.getResponseBuffer(0); break;
        case 6: K = node.getResponseBuffer(0); break;
      }
      Serial.print("7en1 OK ");
      Serial.print(sensorStageName(sensorStage));
      Serial.print(" raw=");
      Serial.println(node.getResponseBuffer(0));
    } else {
      printModbusError(sensorStage, result);
    }

    // Avanza al siguiente sensor
    sensorStage = (sensorStage + 1) % 7;

    // Actualiza LCD cada ciclo completo
    if (sensorStage == 0) mostrarLCD(porcentaje);
  }

  // 🌡 DHT (menos frecuente)
  static unsigned long lastDHTMillis = 0;
  if (now - lastDHTMillis >= 2000) {
    lastDHTMillis = now;
    float h = dht.readHumidity();
    float t = dht.readTemperature();
    if (!isnan(h) && !isnan(t)) {
      dht_h = h;
      dht_t = t;
    } else {
      Serial.println("Error leyendo DHT");
    }
  }

  /*
  Serial.println("-------------");
  Serial.print("Voltaje: ");
  Serial.print(voltaje);
  Serial.println(" V");

  Serial.print("Bateria: ");
  Serial.print(porcentaje);
  Serial.println(" %");
  */

  if (bleActivo && (now - lastBLEMillis >= intervaloBLE)) {
    lastBLEMillis = now;
    sendBLE();
  }
  

  mostrarLCD(porcentaje);  // 🔥 LCD
  delay(500);

  if (ce == 0) {
    if (estadoSwitch && resetHibernateCountdownNow) {
      ceEnCero = false;
      Serial.print("Configuracion BLE actualizada. Reiniciando contador de hibernacion a ");
      Serial.print(activeHibernateMinutes);
      Serial.println(" min desde ahora.");
    }

    if (activeHibernateMinutes == 0) {
      if (ceEnCero) {
        Serial.println("Hibernacion desactivada en modo Bluetooth. Se cancela el contador de deep sleep.");
      }
      ceEnCero = false;
    } else {
      if (!ceEnCero) {
        ceEnCero = true;
        ceCeroInicio = millis();  // empieza conteo
        Serial.print("CE en 0. Deep sleep en ");
        Serial.print(activeHibernateMinutes);
        Serial.print(" min si no cambia. Modo: ");
        Serial.println(estadoSwitch ? "Bluetooth" : "Normal");
      }

      unsigned long tiempoEspera = activeHibernateMinutes * 60UL * 1000UL;

      if (millis() - ceCeroInicio >= tiempoEspera) {
        Serial.print("CE en 0 mucho tiempo en modo ");
        Serial.print(estadoSwitch ? "Bluetooth" : "Normal");
        Serial.println(" -> entrando en deep sleep");
        entrarDeepSleep();
      }
    }

  } else {
    if (ceEnCero) {
      Serial.println("CE salio de 0. Se cancela el contador de deep sleep.");
    }
    ceEnCero = false;
  }
}
