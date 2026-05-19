/*
  Firmware principal de AgroSense.

  Este programa corre en el ESP32-S3 y coordina cuatro tareas:
  1. Leer el sensor de suelo 7 en 1 por RS485/Modbus.
  2. Leer temperatura y humedad ambiente con el DHT22.
  3. Enviar datos a la app por Bluetooth Low Energy (BLE).
  4. Ahorrar energia entrando en deep sleep cuando el sensor de CE queda en cero.

  La app y el firmware deben mantener el mismo nombre BLE, UUID de servicio,
  UUID de caracteristica y formato JSON. Si se cambia alguno de esos datos aqui,
  tambien se debe cambiar en services/ble_service.py.
*/

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


// Pines del MAX485. DE y RE controlan si el modulo RS485 transmite o recibe.
#define MAX485_DE 48
#define MAX485_RE 48
#define RXD2 47
#define TXD2 35

// SW_BT activa o desactiva el modo Bluetooth desde el interruptor fisico.
// WAKEUP_PIN despierta al ESP32 desde deep sleep cuando recibe nivel alto.
#define SW_BT 2
#define WAKEUP_PIN 1

ModbusMaster node;

// Declaraciones adelantadas de funciones usadas antes de estar definidas.
void configureWakeupPinForRunMode();
bool prepareWakeupPinForDeepSleep();
bool waitWakePinLowStable(unsigned long stableMs, unsigned long timeoutMs);

// Sensor DHT22 usado para temperatura y humedad ambiente.
#define DHTPIN 36
#define DHTTYPE DHT22
DHT dht(DHTPIN, DHTTYPE);

// La lectura Modbus se reparte por etapas para no bloquear todo el ciclo loop().
uint8_t sensorStage = 0;
const unsigned long sensorInterval = 200;
unsigned long lastSensorMillis = 0;

// Configuracion que se puede modificar desde la app por BLE.
unsigned long lastBLEMillis = 0;
unsigned long intervaloBLE = 2000;
unsigned long hibernateMinutes = 10;

const int LED_PIN = 41;
bool ledState = false;
unsigned long previousMillis = 0;
const long blinkInterval = 1000;
bool bleEncendiendo = false;
bool bleActivo = false;
bool bleInitialized = false;
bool bleClientConnected = false;
bool bleRestartAdvertisingRequested = false;
bool enteringDeepSleep = false;
unsigned long bleRestartAdvertisingAt = 0;
const unsigned long BLE_RESTART_DELAY_MS = 250;

// LCD I2C de 20x4. Si no muestra texto, revisar si la direccion es 0x27 o 0x3f.
LiquidCrystal_PCF8574 lcd(0x27);

// Caracteres personalizados para dibujar los bordes redondeados de la bateria.
byte batteryLeftCap[8] = {
  B00111,
  B00100,
  B00100,
  B00100,
  B00100,
  B00100,
  B00100,
  B00111
};

byte batteryRightCap[8] = {
  B11100,
  B00100,
  B00100,
  B00100,
  B00100,
  B00100,
  B00100,
  B11100
};

// Se usa un segundo bus I2C para el INA219 y se deja el bus principal para LCD.
TwoWire I2C_BATT = TwoWire(1);

Adafruit_INA219 ina219(0x40);

// Preferences guarda configuraciones en memoria NVS, aunque se reinicie el ESP32.
Preferences preferences;

// Rango estimado del paquete de bateria. Ajustar si se cambia la bateria.
float voltaje_min = 10;
float voltaje_max = 12.6;
float batteryVoltage = 0.0;
float batteryPercent = 0.0;

float h;
float t;

// Caracteristica BLE usada para notificar mediciones y recibir configuracion.
BLECharacteristic *pCharacteristic;

uint8_t result;
uint16_t rawValue;

// Variables globales donde queda la ultima medicion valida de cada sensor.
float humedad, temperatura, ph;
uint16_t ce, N, P, K;

float dht_h = NAN, dht_t = NAN;

// Si CE queda en cero por el tiempo configurado, el equipo entra en deep sleep.
unsigned long ceCeroInicio = 0;
bool ceEnCero = false;
bool hibernateCountdownResetRequested = false;

class MyServerCallbacks: public BLEServerCallbacks {
  void onConnect(BLEServer *pServer) override {
    // Cuando la app se conecta, ya no hace falta reiniciar advertising.
    bleClientConnected = true;
    bleRestartAdvertisingRequested = false;
    Serial.println("Cliente BLE conectado");
  }

  void onDisconnect(BLEServer *pServer) override {
    bleClientConnected = false;

    // Si la desconexion no es por hibernacion, vuelve a anunciar para reconectar.
    if (bleActivo && !enteringDeepSleep) {
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

      // Formato nuevo enviado por la app: "intervalo_ms,hibernacion_min".
      int commaIdx = rxValue.indexOf(',');
      unsigned long nuevo = 0;
      unsigned long nuevaHibernacion = hibernateMinutes;

      if (commaIdx > 0) {
        nuevo = rxValue.substring(0, commaIdx).toInt();
        nuevaHibernacion = rxValue.substring(commaIdx + 1).toInt();
      } else {
        // Formato anterior: solo intervalo.
        nuevo = rxValue.toInt();
      }

      // Validar (evita valores inválidos como 0)
      if (nuevo > 0) {

        intervaloBLE = nuevo;
        hibernateMinutes = nuevaHibernacion;
        hibernateCountdownResetRequested = true;

        // Guardar en memoria flash (NVS) para conservar datos tras reinicio.
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
        Serial.println("Valor invalido recibido");
      }
    }
  }
};

void entrarDeepSleep() {

  Serial.println("Entrando en modo ahorro extremo...");
  enteringDeepSleep = true;

  // Si el pin de despertar esta alto antes de dormir, el equipo despertaria solo.
  if (!prepareWakeupPinForDeepSleep()) {
    enteringDeepSleep = false;
    lcd.clear();
    lcd.setCursor(0, 1);
    lcd.print("Wake pin en HIGH");
    lcd.setCursor(0, 2);
    lcd.print("No duerme");
    return;
  }

  if (bleInitialized) {
    // Apagar advertising antes de dormir evita eventos BLE durante la hibernacion.
    bleActivo = false;
    bleClientConnected = false;
    bleRestartAdvertisingRequested = false;
    BLEDevice::stopAdvertising();
    delay(500);
  }

  Serial.print("Wake pin despues de apagar BLE: ");
  Serial.println(digitalRead(WAKEUP_PIN));

  // Se espera que el pin quede estable en bajo; asi se evita un wake inmediato.
  if (!waitWakePinLowStable(1000, 3000)) {
    enteringDeepSleep = false;
    lcd.clear();
    lcd.setCursor(0, 1);
    lcd.print("Wake pin inestable");
    lcd.setCursor(0, 2);
    lcd.print("No duerme");
    configureWakeupPinForRunMode();
    return;
  }

  if (!prepareWakeupPinForDeepSleep()) {
    enteringDeepSleep = false;
    lcd.clear();
    lcd.setCursor(0, 1);
    lcd.print("Wake pin en HIGH");
    lcd.setCursor(0, 2);
    lcd.print("No duerme");
    return;
  }

  // Se apaga la pantalla para reducir consumo antes de entrar a deep sleep.
  lcd.clear();
  lcd.setBacklight(0);

  // EXT0 despierta con nivel alto en WAKEUP_PIN, normalmente por boton a 3.3 V.
  esp_sleep_enable_ext0_wakeup((gpio_num_t)WAKEUP_PIN, 1);

  delay(50);

  esp_deep_sleep_start();
}


// ================= LED =================
void updateLED() {
  unsigned long currentMillis = millis();

  if (bleEncendiendo) {
    // Titilar mientras BLE se inicializa para indicar que esta arrancando.
    if (currentMillis - previousMillis >= blinkInterval) {
      previousMillis = currentMillis;
      ledState = !ledState;
      digitalWrite(LED_PIN, ledState ? HIGH : LOW);
    }
  } else if (bleActivo) {
    // LED fijo: el modo BLE esta disponible para la app.
    digitalWrite(LED_PIN, HIGH);
  } else {
    // LED apagado: el equipo mide localmente, pero no anuncia BLE.
    digitalWrite(LED_PIN, LOW);
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
  digitalWrite(pin, LOW);
}

void printBatteryIcon(float porcentaje) {
  int filledBlocks = 0;

  // El icono tiene tres bloques internos: bajo, medio y alto.
  if (porcentaje > 66) {
    filledBlocks = 3;
  } else if (porcentaje > 33) {
    filledBlocks = 2;
  } else if (porcentaje > 10) {
    filledBlocks = 1;
  }

  lcd.write((uint8_t)0);
  for (int i = 0; i < 3; i++) {
    if (i < filledBlocks) {
      // 255 usa todos los pixeles del caracter LCD para un bloque lleno.
      lcd.write((uint8_t)255);
    } else {
      lcd.print(" ");
    }
  }
  lcd.write((uint8_t)1);
}

void mostrarLCD(float porcentaje) {

  lcd.clear();

  if(porcentaje > 1){
  // Linea 1: conductividad electrica y estado de bateria.
  lcd.setCursor(0,0);
  lcd.print("CE:");
  lcd.print(ce,1);

  lcd.setCursor(11,0);
  printBatteryIcon(porcentaje);
  lcd.print(porcentaje,0);
  lcd.print("%");

  lcd.setCursor(0,1);
  lcd.print("Ta:");
  lcd.print(t,1);
  lcd.print(" Hr:");
  lcd.print(h,1);

  // Linea 3: variables principales del sensor de suelo.
  lcd.setCursor(0,2);
  lcd.print("Ts:");
  lcd.print(temperatura,0);
  lcd.print("  Hs:");
  lcd.print(humedad,0);
  lcd.print(" pH:");
  lcd.print(ph,1);

   // Linea 4: macronutrientes medidos por el sensor 7 en 1.
  lcd.setCursor(0,3);
  lcd.print("N:");
  lcd.print(N);
  lcd.print(" P:");
  lcd.print(P);
  lcd.print(" K:");
  lcd.print(K);}
  else {
  lcd.setCursor(4,1);
  lcd.print("BATERIA BAJA");
  lcd.setCursor(1,2);
  lcd.print("CONECTAR CARGADOR!");
  }
}


// ================= MODBUS =================
void preTransmission() {
  // Antes de consultar Modbus, el MAX485 pasa a modo transmision.
  digitalWrite(MAX485_DE, HIGH);
  digitalWrite(MAX485_RE, HIGH);
}

void postTransmission() {
  // Despues de enviar, el MAX485 vuelve a modo recepcion.
  digitalWrite(MAX485_DE, LOW);
  digitalWrite(MAX485_RE, LOW);
}

void configureWakeupPinForRunMode() {
  // En ejecucion normal se usa GPIO comun con pulldown interno.
  rtc_gpio_deinit((gpio_num_t)WAKEUP_PIN);
  pinMode(WAKEUP_PIN, INPUT_PULLDOWN);
}

bool prepareWakeupPinForDeepSleep() {
  // En deep sleep el pin debe configurarse con funciones RTC del ESP32.
  rtc_gpio_deinit((gpio_num_t)WAKEUP_PIN);
  rtc_gpio_init((gpio_num_t)WAKEUP_PIN);
  rtc_gpio_set_direction((gpio_num_t)WAKEUP_PIN, RTC_GPIO_MODE_INPUT_ONLY);
  rtc_gpio_pullup_dis((gpio_num_t)WAKEUP_PIN);
  rtc_gpio_pulldown_en((gpio_num_t)WAKEUP_PIN);

  delay(20);

  int wakeLevel = rtc_gpio_get_level((gpio_num_t)WAKEUP_PIN);
  Serial.print("Wake pin antes de dormir: ");
  Serial.println(wakeLevel);

  if (wakeLevel == 1) {
    Serial.println("Wake pin ya esta en HIGH. Se cancela deep sleep para evitar despertar inmediato.");
    configureWakeupPinForRunMode();
    return false;
  }

  return true;
}

bool waitWakePinLowStable(unsigned long stableMs, unsigned long timeoutMs) {
  unsigned long start = millis();
  unsigned long lowSince = 0;

  // La estabilidad se mide leyendo varias veces; un rebote reinicia el conteo.
  while (millis() - start < timeoutMs) {
    int level = digitalRead(WAKEUP_PIN);

    if (level == LOW) {
      if (lowSince == 0) {
        lowSince = millis();
      }

      if (millis() - lowSince >= stableMs) {
        Serial.println("Wake pin LOW estable");
        return true;
      }
    } else {
      lowSince = 0;
    }

    delay(20);
  }

  Serial.println("Wake pin no estuvo LOW estable");
  return false;
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  delay(300);

  // Imprime la causa de arranque para distinguir encendido normal y wakeup.
  esp_sleep_wakeup_cause_t wakeupCause = esp_sleep_get_wakeup_cause();
  Serial.print("Causa wakeup: ");
  Serial.println((int)wakeupCause);

  // Bus I2C principal para el LCD: SDA 38, SCL 37.
  Wire.begin(38, 37, 100000);
  lcd.begin(20, 4);
  lcd.createChar(0, batteryLeftCap);
  lcd.createChar(1, batteryRightCap);
  lcd.setBacklight(255);
  lcd.clear();
  lcd.setCursor(6,1);
  lcd.print("AgroSense");
  lcd.setCursor(1,2);
  lcd.print("INICIANDO SISTEMA");
  // Bus I2C secundario para el monitor de bateria INA219.
  I2C_BATT.begin(40, 39, 100000);

  if (!ina219.begin(&I2C_BATT)) {
    Serial.println("Error INA219");
  }

  dht.begin();

  Serial2.begin(9600, SERIAL_8N1, RXD2, TXD2);

  // RS485 inicia en recepcion para esperar respuesta del sensor.
  pinMode(MAX485_DE, OUTPUT);
  pinMode(MAX485_RE, OUTPUT);

  digitalWrite(MAX485_DE, LOW);
  digitalWrite(MAX485_RE, LOW);

  node.begin(1, Serial2);
  node.preTransmission(preTransmission);
  node.postTransmission(postTransmission);

  pinMode(SW_BT, INPUT_PULLUP);
  configureWakeupPinForRunMode();
  Serial.print("Wake pin inicial: ");
  Serial.println(digitalRead(WAKEUP_PIN));
  Serial.print("Switch Bluetooth inicial: ");
  Serial.println((digitalRead(SW_BT) == LOW) ? "ON" : "OFF");

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // Carga la ultima configuracion guardada por la app.
  preferences.begin("config", true);

  intervaloBLE = preferences.getUInt("ble_int", 2000);
  // Si no existe, usa 2000 ms como valor por defecto.
  hibernateMinutes = preferences.getUInt("hib_min", 10);

  preferences.end();

  Serial.print("Intervalo BLE cargado: ");
  Serial.println(intervaloBLE);
  Serial.print("Hibernacion cargada: ");
  Serial.print(hibernateMinutes);
  Serial.println(" min");

  setupBLE();

}

// ================= BLE SETUP =================
void setupBLE() {
  // Nombre que la app busca al escanear dispositivos BLE.
  BLEDevice::init("ESP32_SENSOR");
  bleInitialized = true;

  BLEServer *pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());
  // UUID corto 1234. En la app se usa su forma completa de 128 bits.
  BLEService *pService = pServer->createService("1234");

  // La caracteristica 5678 permite notificar mediciones y recibir configuracion.
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

  if (!bleClientConnected || pCharacteristic == nullptr) {
    return;
  }

  char msg[320];

  // JSON compacto que la app convierte a su estructura interna de sensores.
  snprintf(msg, sizeof(msg),
    "{\"dht\":{\"t\":%.2f,\"h\":%.2f},\"sensor7en1\":{\"temperatura\":%.2f,\"humedad\":%.2f,\"Ph\":%.2f,\"Ce\":%u,\"N\":%u,\"P\":%u,\"K\":%u},\"config\":{\"i_ms\":%lu,\"h_min\":%lu}}",
    dht_t, dht_h, temperatura, humedad, ph, ce, N, P, K,
    intervaloBLE, hibernateMinutes);

  pCharacteristic->setValue((uint8_t*)msg, strlen(msg));
  // notify envia la medicion a la app sin que la app tenga que pedirla.
  pCharacteristic->notify();

  Serial.println(msg);
}

// ================= LOOP =================
void loop() {

  delay(2000);
  unsigned long now = millis();

   bool estadoSwitch = digitalRead(SW_BT) == LOW;

   // Encender BLE cuando el interruptor fisico esta en modo Bluetooth.
    if (estadoSwitch && !bleActivo) {
    bleEncendiendo = true;   // comienza titileo
    Serial.println("Encendiendo BLE...");
    if (!bleInitialized) {
      setupBLE();             // inicializa BLE si todavia no existe
    }
    bleEncendiendo = false;  // termina titileo
    bleActivo = true;
    bleClientConnected = false;
    bleRestartAdvertisingRequested = false;
      Serial.println("BLE listo y anunciando");
      lcd.clear();
      lcd.setCursor(5,1);
      lcd.print("INICIANDO");
      lcd.setCursor(5,2);
      lcd.print("BLUETOOTH");
      BLEDevice::startAdvertising();      // BLE ya activo
      blinkLED(LED_PIN, 1, 200);
      updateLED();
    }

  // Apagar advertising cuando el interruptor sale del modo Bluetooth.
    if (!estadoSwitch && bleActivo) {
    lcd.clear();
    lcd.setCursor(6,1);
    lcd.print("APAGANDO");
    lcd.setCursor(6,2);
    lcd.print("BLUETOOTH");
    Serial.println("Apagando BLE...");
    bleActivo = false;
    bleClientConnected = false;
    bleRestartAdvertisingRequested = false;
    BLEDevice::stopAdvertising();
    blinkLED(LED_PIN, 1, 200);
    updateLED();
    }

  // Reinicia advertising despues de una desconexion normal de la app.
  if (bleRestartAdvertisingRequested && bleActivo && !bleClientConnected && ((long)(now - bleRestartAdvertisingAt) >= 0)) {
    BLEDevice::startAdvertising();
    bleRestartAdvertisingRequested = false;
    Serial.println("BLE advertising reiniciado tras desconexion");
  }


  if (now - lastSensorMillis >= sensorInterval) {
    lastSensorMillis = now;

    batteryVoltage = ina219.getBusVoltage_V();
    batteryPercent = (batteryVoltage - voltaje_min) / (voltaje_max - voltaje_min) * 100.0;
    batteryPercent = constrain(batteryPercent, 0, 100);

    // Lectura escalonada de Modbus: cada vuelta lee un registro diferente.
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
        case 2: temperatura = node.getResponseBuffer(0)/10.0; break;
        case 3: ce = node.getResponseBuffer(0); break;
        case 4: N = node.getResponseBuffer(0); break;
        case 5: P = node.getResponseBuffer(0); break;
        case 6: K = node.getResponseBuffer(0); break;
      }
    }

    // Avanza al siguiente registro para que el siguiente ciclo lea otra variable.
    sensorStage = (sensorStage + 1) % 7;

    // Actualiza LCD cuando ya se completo una vuelta por todos los registros.
    if (sensorStage == 0) mostrarLCD(batteryPercent);
  }

  // DHT se lee cada 2 segundos porque este sensor no requiere lecturas rapidas.
  static unsigned long lastDHTMillis = 0;
  if (now - lastDHTMillis >= 2000) {
    lastDHTMillis = now;
    h = dht.readHumidity();
    t = dht.readTemperature();
    if (!isnan(h) && !isnan(t)) {
      dht_h = h;
      dht_t = t;
    }
  }

  Serial.println("-------------");
  Serial.print("Voltaje: ");
  Serial.print(batteryVoltage);
  Serial.println(" V");

  Serial.print("Bateria: ");
  Serial.print(batteryPercent);
  Serial.println(" %");

   Serial.print("humedaddht ");
   Serial.print(h);
   Serial.print(" temperaturadht ");
   Serial.println(t);


  if (bleActivo && (now - lastBLEMillis >= intervaloBLE)) {
    lastBLEMillis = now;
    sendBLE();
  }


  // Refresca la pantalla con la ultima informacion disponible.
  mostrarLCD(batteryPercent);

  if (hibernateCountdownResetRequested) {
    ceEnCero = false;
    hibernateCountdownResetRequested = false;
  }

  if (ce == 0) {

  if (hibernateMinutes == 0) {
    ceEnCero = false;
  } else {
    if (!ceEnCero) {
      ceEnCero = true;
      ceCeroInicio = millis();
    }

    // Si CE sigue en cero por el tiempo configurado, se asume inactividad.
    unsigned long tiempoEsperaSleepConfigurado = hibernateMinutes * 60UL * 1000UL;
    if (millis() - ceCeroInicio >= tiempoEsperaSleepConfigurado) {
      Serial.println("CE en 0 mucho tiempo -> entrando en deep sleep");

      entrarDeepSleep();
    }
  }

  } else {
  ceEnCero = false;
  }
}
