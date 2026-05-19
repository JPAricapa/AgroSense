#!/usr/bin/env bash
# Script de compilacion Android para AgroSense con soporte BLE.
#
# Flet por si solo genera una APK, pero BLE en Android necesita clases Java
# adicionales de bleak y pyjnius. Por eso este script:
# 1. Limpia artefactos viejos que pueden dejar una APK sin BLE.
# 2. Genera el proyecto Android base con Flet.
# 3. Copia las clases Java requeridas por BLE al proyecto Android.
# 4. Protege esas clases de ProGuard/R8 para que no se eliminen.
# 5. Compila la APK final y la deja en build/apk/agrosense.apk.

# set -e: si un comando falla, el script se detiene.
# set -u: si se usa una variable no definida, el script se detiene.
# set -o pipefail: si falla un comando dentro de un pipe, se reporta el fallo.
set -euo pipefail

# ROOT_DIR queda apuntando a la raiz del proyecto, sin importar desde donde se
# ejecute el script. BASH_SOURCE[0] es este archivo; dirname obtiene scripts/.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Todas las rutas siguientes se calculan desde la raiz del proyecto.
cd "$ROOT_DIR"

# Carpeta temporal dentro de build/. Se usa para evitar problemas con /tmp en
# algunas instalaciones de Gradle, Flutter o Android.
TMP_ROOT="$ROOT_DIR/build/tmp"
mkdir -p "$TMP_ROOT"

# Fuerza la regeneracion del paquete Python sin eliminar todo el proyecto Flutter
# base. Esto evita que Flet reutilice un app.zip viejo sin los ultimos cambios.
rm -rf "$ROOT_DIR/build/.hash" "$ROOT_DIR/build/apk"

# Borra APK y paquetes Python generados anteriormente. Si alguno no existe,
# rm -f no falla.
rm -f \
    "$ROOT_DIR/build/flutter/app/app.zip" \
    "$ROOT_DIR/build/flutter/build/app/intermediates/flutter/release/flutter_assets/app/app.zip" \
    "$ROOT_DIR/build/flutter/build/app/intermediates/assets/release/mergeReleaseAssets/flutter_assets/app/app.zip" \
    "$ROOT_DIR/build/flutter/build/app/outputs/flutter-apk/app-release.apk"

# Redirige temporales de herramientas Python/Java hacia build/tmp.
export TMPDIR="$TMP_ROOT"
export TMP="$TMP_ROOT"
export TEMP="$TMP_ROOT"

# Gradle y Java leen JAVA_TOOL_OPTIONS. Si ya trae un tmpdir, se respeta.
# Si no lo trae, se agrega -Djava.io.tmpdir para que Java use build/tmp.
if [[ "${JAVA_TOOL_OPTIONS:-}" != *"-Djava.io.tmpdir="* ]]; then
    if [[ -n "${JAVA_TOOL_OPTIONS:-}" ]]; then
        export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS} -Djava.io.tmpdir=$TMP_ROOT"
    else
        export JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=$TMP_ROOT"
    fi
fi

# Primer paso de Flet: genera el proyecto Android y empaqueta Python.
# --clear-cache evita dependencias empaquetadas viejas.
# --cleanup-app elimina residuos de compilaciones anteriores dentro del proyecto.
flet build apk --clear-cache --cleanup-app

# Busca la carpeta Java incluida dentro de bleak. Esa carpeta contiene las
# clases Android que permiten escanear, conectar y recibir callbacks BLE.
BLEAK_JAVA_DIR="$(
python - <<'PY'
from pathlib import Path
import bleak

java_dir = Path(bleak.__file__).parent / "backends" / "p4android" / "java"
if not java_dir.exists():
    raise SystemExit(f"No se encontro Java de bleak en {java_dir}")
print(java_dir)
PY
)"

# Pyjnius tambien necesita su NativeInvocationHandler.java dentro del APK para
# que los callbacks Java puedan llamar codigo Python.
JNIUS_JAVA_DIR="$ROOT_DIR/build/site-packages/arm64-v8a/jnius/src"
if [[ ! -f "$JNIUS_JAVA_DIR/org/jnius/NativeInvocationHandler.java" ]]; then
    echo "No se encontro NativeInvocationHandler.java en $JNIUS_JAVA_DIR" >&2
    exit 1
fi

# Rutas internas del proyecto Android que Flet acaba de generar.
ANDROID_APP_DIR="$ROOT_DIR/build/flutter/android/app"
ANDROID_JAVA_DIR="$ANDROID_APP_DIR/src/main/java"
PROGUARD_FILE="$ANDROID_APP_DIR/proguard-rules.pro"

# Crea la carpeta Java si todavia no existe.
mkdir -p "$ANDROID_JAVA_DIR"

# Copia clases Java de bleak y pyjnius al proyecto Android para que se compilen
# junto con la APK final.
cp -R "$BLEAK_JAVA_DIR/com" "$ANDROID_JAVA_DIR/"
cp -R "$JNIUS_JAVA_DIR/org" "$ANDROID_JAVA_DIR/"

# ProGuard/R8 puede borrar clases que no detecta como usadas desde Java puro.
# Estas reglas obligan a conservar las clases BLE de bleak.
if ! grep -q "com.github.hbldh.bleak" "$PROGUARD_FILE"; then
    printf '\n-keep class com.github.hbldh.bleak.** { *; }\n' >> "$PROGUARD_FILE"
fi

# Tambien se conservan las clases de pyjnius, necesarias para comunicar Java y
# Python dentro de Android.
if ! grep -q "org.jnius" "$PROGUARD_FILE"; then
    printf '\n-keep class org.jnius.** { *; }\n' >> "$PROGUARD_FILE"
fi

# Segunda compilacion: ahora Flutter compila el proyecto Android ya modificado.
# SERIOUS_PYTHON_SITE_PACKAGES apunta al site-packages que Flet genero antes.
(
    cd "$ROOT_DIR/build/flutter"
    SERIOUS_PYTHON_SITE_PACKAGES="$ROOT_DIR/build/site-packages" flutter build apk
)

# Carpeta final donde el equipo busca la APK lista para instalar.
mkdir -p "$ROOT_DIR/build/apk"

# Copia la APK release de Flutter a un nombre estable para AgroSense.
cp "$ROOT_DIR/build/flutter/build/app/outputs/flutter-apk/app-release.apk" \
   "$ROOT_DIR/build/apk/agrosense.apk"

# Genera un hash SHA1 para identificar rapidamente si la APK cambio.
sha1sum "$ROOT_DIR/build/apk/agrosense.apk" | awk '{print $1}' \
    > "$ROOT_DIR/build/apk/agrosense.apk.sha1"

# Mensaje final con la ruta exacta de la APK generada.
echo "APK BLE lista: $ROOT_DIR/build/apk/agrosense.apk"
