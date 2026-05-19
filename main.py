"""
Punto de entrada de la app AgroSense.

Este archivo crea la ventana Flet, mantiene el estado compartido de la
aplicacion y decide que pantalla se muestra segun la ruta actual. Las pantallas
estan separadas en la carpeta pages/ y los servicios externos estan en
services/.
"""

import flet as ft
import subprocess
import os
import sys
from services.ble_service import BLEService
from services.db_service import init_db
from pages import connection, fincas, dashboard, save, history, configuration

init_db()

# Estado compartido entre pantallas. Cada pantalla lee o actualiza estas llaves
# para saber si hay finca seleccionada, datos medidos o conexion BLE activa.
_state = {
    "current_data": None,
    "measured": False,
    "ready_to_save": False,
    "finca_id": None,
    "finca_nombre": None,
    "sample_interval_seconds": None,
    "hibernate_minutes": None,
    "ble_mode": False,
    "_ble_status_handler": None,
    "_current_route": "/connection",
    "_disconnect_requested": False,
    "_ble_notice": None,
}
# Servicio BLE unico para toda la app. Se comparte para no abrir varias
# conexiones al mismo ESP32.
_ble = BLEService()
_is_dark = [True]


def _is_android_runtime():
    """Detecta si la app corre dentro de Android o en escritorio."""
    return (
        sys.platform == "android"
        or hasattr(sys, "getandroidapilevel")
        or os.environ.get("P4A_BOOTSTRAP") is not None
        or os.environ.get("ANDROID_ARGUMENT") is not None
        or (os.environ.get("ANDROID_ROOT") and os.environ.get("ANDROID_DATA"))
    )


def get_system_theme():
    """Devuelve True para modo oscuro y False para modo claro."""
    if _is_android_runtime() or sys.platform != "linux":
        return True

    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True, text=True, timeout=2,
        )
        if "dark" in result.stdout.lower():
            return True
        if "light" in result.stdout.lower():
            return False
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
            capture_output=True, text=True, timeout=2,
        )
        if any(k in result.stdout.lower() for k in ["dark", "noir", "black"]):
            return True
    except Exception:
        pass
    return True


def main(page: ft.Page):
    """Configura la pagina principal y conecta la navegacion de la app."""
    page.title = "AgroSense"
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.window_maximized = False
    page.window_width = 400
    page.window_height = 700
    page.padding = 0

    _is_dark[0] = get_system_theme()
    page.bgcolor = "#0D1B2A" if _is_dark[0] else "#F0F2F5"

    def _normalize_route(route: str | None) -> str:
        # Flet acepta rutas con o sin slash; se normalizan para comparar facil.
        if not route:
            return "/connection"
        return route if route.startswith("/") else "/" + route

    def toggle_theme():
        # Cambia tema y vuelve a dibujar la pantalla actual.
        _is_dark[0] = not _is_dark[0]
        page.theme_mode = ft.ThemeMode.DARK if _is_dark[0] else ft.ThemeMode.LIGHT
        page.bgcolor = "#0D1B2A" if _is_dark[0] else "#F0F2F5"
        render_route(page.route)

    def _reset_measurement_state(clear_finca: bool = False):
        # Limpia datos temporales de medicion sin borrar la base de datos.
        _state["ble_mode"] = False
        _state["current_data"] = None
        _state["measured"] = False
        _state["ready_to_save"] = False
        _state["sample_interval_seconds"] = None
        _state["hibernate_minutes"] = None
        if clear_finca:
            _state["finca_id"] = None
            _state["finca_nombre"] = None

    def _handle_ble_status(status: str):
        # Recibe eventos del servicio BLE y los traduce a navegacion o avisos.
        handler = _state.get("_ble_status_handler")
        if callable(handler):
            try:
                handler(status)
            except Exception:
                pass

        if status == "connected":
            # Al conectar, el flujo normal continua hacia seleccion de finca.
            _state["ble_mode"] = True
            if _state.get("_current_route") == "/connection":
                navigate("/fincas")
            return

        if status == "disconnected":
            # Una desconexion no solicitada se muestra como aviso al usuario.
            disconnect_requested = bool(_state.get("_disconnect_requested"))
            _state["_disconnect_requested"] = False
            _ble.on_data = None
            _reset_measurement_state(clear_finca=False)

            if not disconnect_requested:
                _state["_ble_notice"] = (
                    "Se perdió la conexión con el equipo. Activa de nuevo el modo BLE y vuelve a conectar."
                )

            if _state.get("_current_route") != "/connection":
                navigate("/connection")
            return

    def render_route(route: str):
        # Borra la pantalla actual y construye la vista correspondiente.
        r = _normalize_route(route)
        _state["_current_route"] = r
        _state["_ble_status_handler"] = None
        page.controls.clear()
        page.overlay.clear()
        if r == "/connection":
            connection.build(page, _ble, _state, navigate, _is_dark[0])
        elif r == "/fincas":
            fincas.build(page, _state, navigate, _is_dark[0], disconnect_and_go_connection)
        elif r == "/configuracion":
            configuration.build(
                page,
                _state,
                navigate,
                _is_dark[0],
                disconnect_and_go_connection,
                _ble,
            )
        elif r == "/dashboard":
            dashboard.build(page, _state, navigate, _is_dark[0], disconnect_and_go_connection, _ble)
        elif r == "/save":
            save.build(page, _state, navigate, _is_dark[0], disconnect_and_go_connection)
        elif r == "/history":
            history.build(page, _state, navigate, _is_dark[0], disconnect_and_go_connection)
        else:
            connection.build(page, _ble, _state, navigate, _is_dark[0])

    def navigate(route: str):
        # Enrutador simple usado por los botones de cada pantalla.
        r = _normalize_route(route)
        current_route = _normalize_route(page.route or _state.get("_current_route"))
        if r == current_route:
            render_route(r)
            return
        page.go(r)

    def disconnect_and_go_connection(_=None):
        # Cierre manual de BLE: vuelve a conexion y limpia finca/datos activos.
        _state["_disconnect_requested"] = True
        _state["_ble_notice"] = None
        try:
            _ble.disconnect()
        except Exception:
            pass
        _reset_measurement_state(clear_finca=True)
        navigate("/connection")

    _ble.on_status = _handle_ble_status
    page.on_route_change = lambda e: render_route(e.route)
    page.go("/connection")


if __name__ == "__main__":
    os.environ.setdefault("FLET_SECRET_KEY", "agroprecision_secret_key_2024")
    ft.app(main, upload_dir="uploads")
