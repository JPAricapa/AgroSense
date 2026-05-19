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
- Consultar el historial de mediciones sin necesidad de conectarse al equipo.
- Revisar el historial agrupado por finca.
- Exportar el historial en formato CSV, seleccionando las fincas que se quieren compartir.
- Mostrar icono y pantalla de inicio con la identidad de AgroSense.

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
├── scripts/
│   └── build_ble_apk.sh
├── AgroSense_Firmware/
│   └── AgroSense_Firmware.ino
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

El historial tambien se puede abrir desde la pantalla de conexion usando el icono superior de historial. En ese modo no hace falta estar conectado por BLE.

## Historial y exportacion CSV

El historial tiene dos comportamientos:

- Desde una finca seleccionada: muestra y exporta solo las mediciones de esa finca.
- Desde la pantalla de conexion: muestra las mediciones agrupadas por finca.

Cuando el historial se abre desde la pantalla de conexion, cada finca tiene una casilla de seleccion. El boton `Enviar datos` exporta unicamente las fincas seleccionadas. Si no hay ninguna finca marcada, la app muestra el aviso `Selecciona al menos una finca`.

El CSV se genera con separador `;`, encabezados sin tildes para evitar problemas de compatibilidad y codificacion `UTF-8` sin BOM. La primera columna es `No. Medicion`. Cuando se exporta mas de una finca, el archivo incluye la columna `Finca`.

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

Este es el flujo recomendado para instalar en el celular, porque conserva el soporte BLE de Android.

## Instalación manual por ADB

Si tienes un dispositivo Android conectado por USB o ADB inalámbrico:

```bash
adb install -r build/apk/agrosense.apk
```

Si hay mas de un dispositivo conectado:

```bash
adb devices
adb -s ID_DEL_DISPOSITIVO install -r build/apk/agrosense.apk
```

## Validación rápida antes de compilar

Para verificar la sintaxis del proyecto:

```bash
python -m py_compile main.py pages/*.py services/*.py
```

## Base de datos local

Las mediciones se guardan localmente con SQLite.

- En escritorio, la base de datos se crea en `services/.agroprecision/`.
- En Android, se guarda dentro del directorio interno de la aplicación.

La base de datos no debe subirse al repositorio.

## Firmware del ESP32

El firmware principal está en:

```text
AgroSense_Firmware/AgroSense_Firmware.ino
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
- `history.py`: consulta del historial, agrupación por finca y exportación CSV selectiva.

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

## Créditos

Este proyecto fue diseñado e implementado por Juan Pablo Aricapa Bedoya,
María José Colorado Morales, Juan Pablo Mahecha Ocampo e Ivan Diaz Zuluaga,
en el marco del Seminario de Grado Sistemas de agentes distribuidos para
Agricultura de precisión, con el acompañamiento de los profesores Jaime Alberto
Buitrago y Luis Miguel Capacho.
