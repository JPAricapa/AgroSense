import asyncio
import flet as ft
import flet_permission_handler as ph
from services.ble_service import BLEService

ACCENT = "#4CAF50"


def _clear_permission_handlers(page: ft.Page):
    try:
        page.services[:] = [
            s for s in page.services
            if not (hasattr(ph, "PermissionHandler") and isinstance(s, ph.PermissionHandler))
        ]
    except Exception:
        pass


def build(page: ft.Page, ble: BLEService, state, navigate, is_dark):
    page.title = "AgroSense"

    bg = "#0D1B2A" if is_dark else "#F0F4F8"
    card_bg = "#1B263B" if is_dark else "#FFFFFF"
    txt = "#E0E1DD" if is_dark else "#1B263B"
    sub = "#778DA9" if is_dark else "#6B7280"
    border = "#2D4A6A" if is_dark else "#D1D5DB"

    page.controls.clear()
    _clear_permission_handlers(page)

    pending_notice = state.pop("_ble_notice", None)
    status_label = ft.Text(
        pending_notice or "Esperando conexión...",
        size=13,
        color=sub if pending_notice is None else "#F44336",
        text_align=ft.TextAlign.CENTER,
    )
    status_icon = ft.Icon(
        icon=ft.Icons.BLUETOOTH if pending_notice is None else ft.Icons.BLUETOOTH_DISABLED,
        size=52,
        color=sub if pending_notice is None else "#F44336",
    )

    _is_mobile = page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
    permission_handler = [None]

    def is_permission_handler_ready(handler) -> bool:
        if handler is None:
            return False
        try:
            _ = handler.page
            return handler.parent is not None
        except Exception:
            return False

    def mount_permission_handler(force_recreate: bool = False):
        if not _is_mobile:
            return None

        current = permission_handler[0]
        if not force_recreate and is_permission_handler_ready(current):
            return current

        try:
            if force_recreate:
                _clear_permission_handlers(page)
                current = None

            if current is None:
                current = ph.PermissionHandler()
                page.services.append(current)
                permission_handler[0] = current
                page.update()

            return current
        except Exception:
            permission_handler[0] = None
            return None

    async def ensure_permission_handler_ready(force_recreate: bool = False):
        handler = mount_permission_handler(force_recreate=force_recreate)
        if handler is None:
            return None

        for _ in range(20):
            if is_permission_handler_ready(handler):
                return handler
            await asyncio.sleep(0.05)
            try:
                page.update()
            except Exception:
                pass

        return None

    def on_status(status: str):
        if status == "searching":
            status_label.value = "Buscando dispositivo BLE..."
            status_label.color = sub
            status_icon.icon = ft.Icons.BLUETOOTH_DISABLED
            status_icon.color = "#FFB300"
        elif status == "connected":
            status_label.value = "Conectado. Sigue con la configuración."
            status_label.color = sub
            status_icon.icon = ft.Icons.BLUETOOTH
            status_icon.color = ACCENT
        elif status.startswith("error"):
            code = status[6:]
            if code == "not_found":
                msg = "No se encontró el dispositivo. Verifica que esté encendido e intenta de nuevo."
            elif code == "connect_failed":
                msg = "No se pudo conectar al dispositivo. Intenta de nuevo."
            else:
                msg = "No se encontró el dispositivo. Verifica que esté encendido e intenta de nuevo."
            status_label.value = msg
            status_label.color = "#F44336"
            status_icon.icon = ft.Icons.BLUETOOTH_DISABLED
            status_icon.color = "#F44336"
        elif status == "disconnected":
            status_label.value = "Conexión BLE finalizada. Vuelve a activar el equipo para reconectar."
            status_label.color = "#F44336"
            status_icon.icon = ft.Icons.BLUETOOTH_DISABLED
            status_icon.color = "#F44336"

        page.update()

    state["_ble_status_handler"] = on_status

    async def connect_ble_with_permissions():
        try:
            handler = await ensure_permission_handler_ready()
            if handler is not None:
                permissions_to_request = []
                for name in ("BLUETOOTH_SCAN", "BLUETOOTH_CONNECT"):
                    perm = getattr(ph.Permission, name, None)
                    if perm is not None:
                        permissions_to_request.append(perm)

                if page.platform == ft.PagePlatform.ANDROID:
                    for name in ("LOCATION_WHEN_IN_USE", "LOCATION"):
                        perm = getattr(ph.Permission, name, None)
                        if perm is not None and perm not in permissions_to_request:
                            permissions_to_request.append(perm)

                for perm in permissions_to_request:
                    try:
                        status = await handler.request(perm)
                    except RuntimeError as exc:
                        if "Control must be added to the page first" not in str(exc):
                            raise
                        handler = await ensure_permission_handler_ready(force_recreate=True)
                        if handler is None:
                            status_label.value = "No se pudo inicializar permisos BLE. Intentando conectar..."
                            status_icon.icon = ft.Icons.INFO
                            status_icon.color = "#FFB300"
                            page.update()
                            await asyncio.sleep(0)
                            ble.connect()
                            return
                        status = await handler.request(perm)
                    if status != ph.PermissionStatus.GRANTED:
                        status_label.value = "Permisos BLE denegados"
                        status_icon.icon = ft.Icons.ERROR
                        status_icon.color = "#F44336"
                        page.update()
                        return

            ble.connect()
        except Exception:
            status_label.value = "No se pudo conectar al dispositivo. Intenta de nuevo."
            status_icon.icon = ft.Icons.BLUETOOTH_DISABLED
            status_icon.color = "#F44336"
            page.update()

    def on_connect_click(_):
        page.run_task(connect_ble_with_permissions)

    header = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.ECO, color=ACCENT, size=22),
                ft.Text(
                    "AgroSense",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=txt,
                ),
                ft.Container(expand=True),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=card_bg,
        padding=ft.Padding.symmetric(horizontal=14, vertical=12),
        border=ft.Border.only(bottom=ft.BorderSide(1, border)),
    )

    body = ft.Column(
        [
            ft.Container(height=18),
            ft.Icon(ft.Icons.ECO, size=64, color=ACCENT),
            ft.Container(height=10),
            ft.Text(
                "Sistema Móvil de Medición de Suelo",
                size=22,
                weight=ft.FontWeight.BOLD,
                color=txt,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Text(
                "AgroSense",
                size=12,
                color=sub,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Container(height=18),
            ft.Container(
                content=ft.Text(
                    (
                        "Bienvenido a AgroSense, tu sistema de agricultura de precisión, "
                        "una herramienta pensada para agricultores que necesitan lecturas "
                        "rápidas, configuración simple y seguimiento del cultivo desde el celular."
                    ),
                    size=14,
                    color=sub,
                    text_align=ft.TextAlign.JUSTIFY,
                ),
                width=310,
                padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                border_radius=12,
                border=ft.Border.all(1, border),
                bgcolor=card_bg,
            ),
            ft.Container(height=28),
            status_icon,
            ft.Container(height=8),
            status_label,
            ft.Container(height=28),
            ft.Button(
                "Buscar dispositivo BLE",
                icon=ft.Icons.BLUETOOTH,
                on_click=on_connect_click,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=12),
                    padding=ft.Padding.symmetric(vertical=14),
                    bgcolor="#2E7D32",
                    color="#FFFFFF",
                    side=ft.BorderSide(1, "#81C784"),
                ),
                width=290,
            ),
            ft.Container(height=18),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
    )

    root = ft.Container(
        content=ft.Column(
            [
                header,
                ft.Container(
                    content=body,
                    expand=True,
                    padding=ft.Padding.symmetric(horizontal=14),
                ),
            ],
            spacing=0,
            expand=True,
        ),
        bgcolor=bg,
        expand=True,
    )

    # Esto evita que el header quede debajo de la barra del sistema
    try:
        page.add(ft.SafeArea(content=root, expand=True))
    except Exception:
        # Fallback por si tu versión de Flet no trae SafeArea
        page.add(
            ft.Container(
                content=root,
                padding=ft.Padding.only(top=18),
                expand=True,
            )
        )

    mount_permission_handler()
    page.update()
