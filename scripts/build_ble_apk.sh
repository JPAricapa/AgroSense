#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TMP_ROOT="$ROOT_DIR/build/tmp"
mkdir -p "$TMP_ROOT"

# Fuerza la regeneracion del paquete Python sin eliminar el proyecto Flutter base.
rm -rf "$ROOT_DIR/build/.hash" "$ROOT_DIR/build/apk"
rm -f \
    "$ROOT_DIR/build/flutter/app/app.zip" \
    "$ROOT_DIR/build/flutter/build/app/intermediates/flutter/release/flutter_assets/app/app.zip" \
    "$ROOT_DIR/build/flutter/build/app/intermediates/assets/release/mergeReleaseAssets/flutter_assets/app/app.zip" \
    "$ROOT_DIR/build/flutter/build/app/outputs/flutter-apk/app-release.apk"

export TMPDIR="$TMP_ROOT"
export TMP="$TMP_ROOT"
export TEMP="$TMP_ROOT"

if [[ "${JAVA_TOOL_OPTIONS:-}" != *"-Djava.io.tmpdir="* ]]; then
    if [[ -n "${JAVA_TOOL_OPTIONS:-}" ]]; then
        export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS} -Djava.io.tmpdir=$TMP_ROOT"
    else
        export JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=$TMP_ROOT"
    fi
fi

flet build apk --clear-cache --cleanup-app

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

JNIUS_JAVA_DIR="$ROOT_DIR/build/site-packages/arm64-v8a/jnius/src"
if [[ ! -f "$JNIUS_JAVA_DIR/org/jnius/NativeInvocationHandler.java" ]]; then
    echo "No se encontro NativeInvocationHandler.java en $JNIUS_JAVA_DIR" >&2
    exit 1
fi

ANDROID_APP_DIR="$ROOT_DIR/build/flutter/android/app"
ANDROID_JAVA_DIR="$ANDROID_APP_DIR/src/main/java"
PROGUARD_FILE="$ANDROID_APP_DIR/proguard-rules.pro"

mkdir -p "$ANDROID_JAVA_DIR"
cp -R "$BLEAK_JAVA_DIR/com" "$ANDROID_JAVA_DIR/"
cp -R "$JNIUS_JAVA_DIR/org" "$ANDROID_JAVA_DIR/"

if ! grep -q "com.github.hbldh.bleak" "$PROGUARD_FILE"; then
    printf '\n-keep class com.github.hbldh.bleak.** { *; }\n' >> "$PROGUARD_FILE"
fi
if ! grep -q "org.jnius" "$PROGUARD_FILE"; then
    printf '\n-keep class org.jnius.** { *; }\n' >> "$PROGUARD_FILE"
fi

(
    cd "$ROOT_DIR/build/flutter"
    SERIOUS_PYTHON_SITE_PACKAGES="$ROOT_DIR/build/site-packages" flutter build apk
)

mkdir -p "$ROOT_DIR/build/apk"
cp "$ROOT_DIR/build/flutter/build/app/outputs/flutter-apk/app-release.apk" \
   "$ROOT_DIR/build/apk/agrosense.apk"
sha1sum "$ROOT_DIR/build/apk/agrosense.apk" | awk '{print $1}' \
    > "$ROOT_DIR/build/apk/agrosense.apk.sha1"

echo "APK BLE lista: $ROOT_DIR/build/apk/agrosense.apk"
