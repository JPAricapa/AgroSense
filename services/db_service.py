"""
Servicio de base de datos local de AgroSense.

SQLite guarda las fincas y las mediciones dentro del dispositivo. En Android se
usa el directorio interno de la app; en escritorio se crea una carpeta local
services/.agroprecision/ para facilitar las pruebas.
"""

import sqlite3
from datetime import datetime
from pathlib import Path


def _get_app_dir() -> Path:
    """Calcula una ruta escribible tanto en Android como en escritorio."""
    module_path = Path(__file__).resolve()
    parts = module_path.parts
    if "files" in parts:
        files_index = parts.index("files")
        return Path(*parts[: files_index + 1]) / ".agroprecision"
    return module_path.parent / ".agroprecision"


APP_DIR = _get_app_dir()
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(APP_DIR / "measurements.db")


def init_db():
    """Crea las tablas si no existen antes de abrir cualquier pantalla."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fincas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            es_fija INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            finca_id INTEGER,
            timestamp TEXT,
            sensor_json TEXT NOT NULL,
            imagen TEXT,
            FOREIGN KEY (finca_id) REFERENCES fincas(id)
        )
    """)

    conn.execute("DELETE FROM fincas WHERE es_fija = 1")
    conn.commit()
    conn.close()


def get_all_fincas():
    """Lista todas las fincas creadas por el usuario."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, nombre FROM fincas ORDER BY id").fetchall()
    conn.close()
    return rows


def create_finca(nombre: str):
    """Crea una finca nueva; devuelve False si el nombre ya existe."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT INTO fincas (nombre, es_fija) VALUES (?, 0)", (nombre.strip(),))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def delete_finca(finca_id: int):
    """Elimina una finca y sus mediciones asociadas."""
    conn = sqlite3.connect(DB_PATH)
    es_fija = conn.execute("SELECT es_fija FROM fincas WHERE id = ?", (finca_id,)).fetchone()
    if es_fija and es_fija[0] == 1:
        conn.close()
        return False
    conn.execute("DELETE FROM measurements WHERE finca_id = ?", (finca_id,))
    conn.execute("DELETE FROM fincas WHERE id = ? AND es_fija = 0", (finca_id,))
    conn.commit()
    conn.close()
    return True


def save_measurement(finca_id, sensor_json, imagen=None):
    """Guarda una medicion con finca, fecha, datos JSON e imagen opcional."""
    try:
        finca_id = int(finca_id)
    except (TypeError, ValueError):
        finca_id = None

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "INSERT INTO measurements (finca_id, timestamp, sensor_json, imagen) VALUES (?, ?, ?, ?)",
        (finca_id, datetime.now().isoformat(), sensor_json, imagen),
    )
    conn.commit()
    conn.close()
    return cursor.lastrowid


def get_measurements_by_finca(finca_id):
    """Consulta mediciones de una finca especifica, de la mas reciente a la mas antigua."""
    try:
        finca_id = int(finca_id)
    except (TypeError, ValueError):
        return []

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT id, timestamp, sensor_json, imagen
        FROM measurements
        WHERE finca_id = ?
        ORDER BY id DESC
    """, (finca_id,)).fetchall()
    conn.close()
    return rows


def get_all_measurements():
    """Consulta todas las mediciones sin agrupar por finca."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT id, timestamp, sensor_json, imagen
        FROM measurements
        ORDER BY id DESC
    """).fetchall()
    conn.close()
    return rows


def get_all_measurements_with_finca():
    """Consulta todas las mediciones incluyendo el nombre de la finca."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT
            m.finca_id,
            COALESCE(f.nombre, 'Sin finca') AS finca_nombre,
            m.id,
            m.timestamp,
            m.sensor_json,
            m.imagen
        FROM measurements m
        LEFT JOIN fincas f ON f.id = m.finca_id
        ORDER BY finca_nombre COLLATE NOCASE ASC, m.id DESC
    """).fetchall()
    conn.close()
    return rows


def delete_measurement(mid: int):
    """Borra una medicion individual desde el historial."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM measurements WHERE id = ?", (mid,))
    conn.commit()
    conn.close()
