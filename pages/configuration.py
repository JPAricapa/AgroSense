import asyncio

import flet as ft

from services.ble_service import BLEService


ACCENT = "#4CAF50"


def build(
    page: ft.Page,
    state: dict,
    navigate,
    is_dark: bool,
    disconnect_ble,
    ble: BLEService | None = None,
):
    page.title = "AgroSense - Configuración"

    bg = "#0D1B2A" if is_dark else "#F0F4F8"
    card_bg = "#1B263B" if is_dark else "#FFFFFF"
    txt = "#E0E1DD" if is_dark else "#1B263B"
    sub = "#778DA9" if is_dark else "#6B7280"
    border = "#2D4A6A" if is_dark else "#D1D5DB"

    page.controls.clear()

    def _state_optional_int(key: str) -> int | None:
        try:
            value = state.get(key)
            if value in (None, ""):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    if _state_optional_int("sample_interval_seconds") is None:
        state["sample_interval_seconds"] = 2
    else:
        state["sample_interval_seconds"] = _state_optional_int("sample_interval_seconds")

    if _state_optional_int("hibernate_minutes") is None:
        state["hibernate_minutes"] = 10
    else:
        state["hibernate_minutes"] = _state_optional_int("hibernate_minutes")

    finca_nombre = state.get("finca_nombre")

    resume_text = ft.Text(
        "",
        size=11,
        color=sub,
        text_align=ft.TextAlign.CENTER,
    )

    def update_resume():
        sample_interval = state["sample_interval_seconds"]
        hibernate_value = state["hibernate_minutes"]

        if sample_interval is None or hibernate_value is None:
            resume_text.value = "Selecciona ambas opciones."
            return

        hibernate_label = (
            "Sin hibernar" if hibernate_value == 0 else f"{hibernate_value} min"
        )
        resume_text.value = (
            f"Lectura cada {sample_interval} s  |  "
            f"Hibernación {hibernate_label}"
        )

    def on_interval_change(e):
        value = e.control.value
        try:
            state["sample_interval_seconds"] = (
                int(value) if value not in (None, "") else None
            )
        except (TypeError, ValueError):
            state["sample_interval_seconds"] = None
        update_resume()
        page.update()

    def on_hibernate_change(e):
        value = e.control.value
        try:
            state["hibernate_minutes"] = (
                int(value) if value not in (None, "") else None
            )
        except (TypeError, ValueError):
            state["hibernate_minutes"] = None
        update_resume()
        page.update()

    async def go_back(_):
        interval = state.get("sample_interval_seconds")
        hibernate = state.get("hibernate_minutes")

        if ble is not None and ble.is_connected and interval is not None and hibernate is not None:
            interval_ms = interval * 1000
            await ble.send_config_async(interval_ms, hibernate)
            await asyncio.sleep(0.15)

        navigate("/fincas")

    interval_dropdown = ft.Dropdown(
        label="Intervalo de toma de datos",
        value=str(state["sample_interval_seconds"]) if state["sample_interval_seconds"] is not None else "2",
        options=[
            ft.dropdown.Option("1", "1 segundo"),
            ft.dropdown.Option("2", "2 segundos"),
            ft.dropdown.Option("5", "5 segundos"),
            ft.dropdown.Option("10", "10 segundos"),
        ],
        width=290,
        border_color=border,
        focused_border_color=ACCENT,
        color=txt,
        label_style=ft.TextStyle(color=sub),
        on_select=on_interval_change,
    )

    hibernate_dropdown = ft.Dropdown(
        label="Tiempo de hibernación",
        value=str(state["hibernate_minutes"]) if state["hibernate_minutes"] is not None else "10",
        options=[
            ft.dropdown.Option("0", "Sin hibernar"),
            ft.dropdown.Option("1", "1 minuto"),
            ft.dropdown.Option("5", "5 minutos"),
            ft.dropdown.Option("10", "10 minutos"),
            ft.dropdown.Option("15", "15 minutos"),
            ft.dropdown.Option("30", "30 minutos"),
            ft.dropdown.Option("60", "60 minutos"),
        ],
        width=290,
        border_color=border,
        focused_border_color=ACCENT,
        color=txt,
        label_style=ft.TextStyle(color=sub),
        on_select=on_hibernate_change,
    )

    mode_badge = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.BLUETOOTH, size=14, color=ACCENT),
                ft.Text(
                    "Conexión BLE lista",
                    size=11,
                    color=ACCENT,
                    weight=ft.FontWeight.W_500,
                ),
            ],
            spacing=4,
            tight=True,
        ),
        bgcolor="#4CAF5026",
        border_radius=6,
        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
    )

    header = ft.Container(
        content=ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.ARROW_BACK,
                    icon_color=txt,
                    tooltip="Volver a fincas",
                    on_click=go_back,
                ),
                ft.Text(
                    "Configuración",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=txt,
                ),
                ft.Container(expand=True),
                mode_badge,
                ft.IconButton(
                    icon=ft.Icons.BLUETOOTH_DISABLED,
                    icon_color="#F44336",
                    icon_size=18,
                    tooltip="Desconectar Bluetooth",
                    on_click=disconnect_ble,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=card_bg,
        padding=ft.Padding.symmetric(horizontal=14, vertical=12),
        border_radius=10,
        border=ft.Border.only(bottom=ft.BorderSide(1, border)),
    )

    info_card = ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    "Configuración del sistema",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=txt,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(height=8),
                ft.Text(
                    (
                        "Configura el intervalo de toma de datos, que define cada cuánto "
                        "se actualizan los valores en pantalla. Ajusta también el tiempo de "
                        "hibernación para que el equipo entre en reposo cuando no esté "
                        "midiendo ninguna variable y así ahorrar batería."
                    ),
                    size=14,
                    color=sub,
                    text_align=ft.TextAlign.JUSTIFY,
                ),
                ft.Container(height=10),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.AGRICULTURE, size=16, color=ACCENT),
                            ft.Text(
                                (
                                    f"Finca: {finca_nombre}"
                                    if finca_nombre
                                    else "La finca se elige en el siguiente paso"
                                ),
                                size=12,
                                color=ACCENT,
                                weight=ft.FontWeight.W_500,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=6,
                    ),
                    bgcolor="#4CAF5026",
                    border_radius=8,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                ),
            ],
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        width=320,
        padding=ft.Padding.symmetric(horizontal=14, vertical=14),
        border_radius=14,
        border=ft.Border.all(1, border),
        bgcolor=card_bg,
    )

    config_card = ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    "Ajustes de medición",
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color=txt,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(height=10),
                interval_dropdown,
                ft.Container(height=10),
                hibernate_dropdown,
                ft.Container(height=10),
                resume_text,
            ],
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        width=320,
        padding=ft.Padding.symmetric(horizontal=14, vertical=14),
        border_radius=14,
        border=ft.Border.all(1, border),
        bgcolor=card_bg,
    )

    body = ft.Column(
        [
            ft.Container(height=18),
            info_card,
            ft.Container(height=16),
            config_card,
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

    update_resume()

    try:
        page.add(ft.SafeArea(content=root, expand=True))
    except Exception:
        page.add(
            ft.Container(
                content=root,
                padding=ft.Padding.only(top=18),
                expand=True,
            )
        )

    page.update()
