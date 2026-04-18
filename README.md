# AgroSense

Aplicación móvil desarrollada con Flet para la medición de suelo, la configuración del equipo por Bluetooth Low Energy y el registro local de lecturas agrícolas.

El proyecto integra dos partes:

- La app móvil y de escritorio escrita en Python con Flet.
- El firmware del ESP32, encargado de leer sensores, exponer la configuración por BLE y gestionar la hibernación.

## Qué hace la aplicación

AgroSense permite:

- Buscar y conectar el equipo por BLE.
- Configurar el intervalo de toma de datos.
- Configurar el tiempo de hibernación del equipo.
- Seleccionar una finca antes de guardar lecturas.
- Visualizar mediciones en tiempo real en el dashboard.
- Guardar mediciones con foto del cultivo.
- Consultar el historial de mediciones.
- Exportar el historial en formato CSV.

## Tecnologías usadas

- Python 3.10+
- Flet
- Bleak
- SQLite
- Flutter/Gradle para el empaquetado Android
- ESP32S3 con firmware en Arduino

## Estructura del proyecto

```text
.
├── main.py
├── pages/
│   ├── connection.py
│   ├── configuration.py
│   ├── fincas.py
│   ├── dashboard.py
│   ├── save.py
│   └── history.py
├── services/
│   ├── ble_service.py
│   └── db_service.py
├── android/
├── scripts/
│   └── build_ble_apk.sh
├── Configuraciones_hibernacion/
│   └── Configuraciones_hibernacion.ino
└── README.md
```

## Flujo principal de la app

1. El usuario abre la pantalla de conexión.
2. Se conecta al dispositivo AgroSense por BLE.
3. Configura el intervalo de toma de datos y el tiempo de hibernación.
4. Selecciona una finca.
5. Inicia la medición desde el dashboard.
6. Guarda la lectura y, si quiere, adjunta una foto.
7. Consulta el historial o exporta los datos a CSV.

## Entorno virtual

Para trabajar en desarrollo, conviene crear un entorno virtual dentro del proyecto.

En Linux o macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

En Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Cuando el entorno esté activo, instala las dependencias del proyecto.

## Instalación para desarrollo

Instala las dependencias del proyecto:

```bash
python -m pip install -e .
```

## Ejecución en escritorio

Para iniciar la app en entorno de desarrollo:

```bash
flet run main.py
```

Esto sirve para revisar la interfaz, validar rutas y probar parte de la lógica sin depender del APK.

## Compilación para Android

### APK estándar

```bash
flet build apk
```

### APK con soporte BLE para Android

Este proyecto usa un flujo adicional para incluir las clases Java necesarias para Bleak y pyjnius en Android:

```bash
bash scripts/build_ble_apk.sh
```

El APK generado queda en:

```text
build/apk/agrosense.apk
```

## Instalación manual por ADB

Si tienes un dispositivo Android conectado por USB o ADB inalámbrico:

```bash
adb install -r build/apk/agrosense.apk
```

## Validación rápida antes de compilar

Para verificar la sintaxis del proyecto:

```bash
python -m py_compile main.py pages/*.py services/*.py android/*.py
```

## Base de datos local

Las mediciones se guardan localmente con SQLite.

- En escritorio, la base de datos se crea en `services/.agroprecision/`.
- En Android, se guarda dentro del directorio interno de la aplicación.

La base de datos no debe subirse al repositorio.

## Firmware del ESP32

El firmware principal está en:

```text
Configuraciones_hibernacion/Configuraciones_hibernacion.ino
```

Ese sketch controla:

- La lectura de sensores.
- La publicación y recepción de datos por BLE.
- La configuración del tiempo de hibernación.
- La entrada a deep sleep y el despertar por botón.

Importante:

- Si cambias nombres BLE, UUID, formatos de datos o parámetros de configuración, debes actualizar la app y el firmware al mismo tiempo.

## Pantallas principales

- `connection.py`: conexión BLE y pantalla de bienvenida.
- `configuration.py`: ajuste del intervalo de lectura y de la hibernación.
- `fincas.py`: selección y creación de fincas.
- `dashboard.py`: visualización de valores en tiempo real.
- `save.py`: guardado de la medición y captura o carga de imagen.
- `history.py`: consulta del historial y exportación CSV.

## Notas de trabajo

- El proyecto usa navegación manual desde `main.py`.
- El estado compartido de la app se mantiene en el diccionario `_state`.
- La lógica BLE está centralizada en `services/ble_service.py`.
- La persistencia local está en `services/db_service.py`.

## Archivos generados

No conviene versionar estos artefactos:

- Bases de datos SQLite generadas localmente.
- APK generados en `build/`.
- Archivos `__pycache__/`.
- Datos capturados o exportados durante pruebas.

## Nombre del producto

El nombre visible actual de la aplicación es `AgroSense`.

La configuración principal del nombre del proyecto y del producto Android está definida en [pyproject.toml](/home/juan-pablo/SEMINARIO/seminario_flet/pyproject.toml):

- `project.name = "agrosense"`
- `tool.flet.product = "AgroSense"`
- `tool.flet.company = "AgroSense"`
- `tool.flet.org = "com.agrosense"`

