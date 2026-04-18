import flet as ft
from datetime import datetime


SENSOR_LABELS = [
    ("Temperatura", "C", "#EF5350"),
    ("Humedad", "%", "#26A69A"),
    ("pH", "", "#26C6DA"),
    ("Nitrógeno", "mg/kg", "#66BB6A"),
    ("Fósforo", "mg/kg", "#9CCC65"),
    ("Potasio", "mg/kg", "#CE93D8"),
    ("EC", "dS/m", "#4DB6AC"),
    ("Temperatura", "C", "#FFA726"),
    ("Humedad", "%", "#B39DDB"),
]



def get_values(data):
    s7 = data.get("sensors_7in1", {})
    am = data.get("am2315c", {})
    return [
        s7.get("temperature_soil", 0),
        s7.get("humidity_soil", 0),
        s7.get("ph", 0),
        s7.get("nitrogen", 0),
        s7.get("phosphorus", 0),
        s7.get("potassium", 0),
        s7.get("ec", 0),
        am.get("temperature_air", 0),
        am.get("humidity_air", 0),
    ]


def build(page: ft.Page, state: dict, navigate, is_dark: bool, disconnect_ble, ble=None):
    page.title = "AgroSense - Dashboard"
    bg = "#0D1B2A" if is_dark else "#F0F2F5"
    card_bg = "#1B263B" if is_dark else "#FFFFFF"
    text_color = "#E0E1DD" if is_dark else "#1B263B"
    sub_color = "#778DA9" if is_dark else "#6B7280"
    accent = "#4CAF50"

    page.controls.clear()

    finca_nombre = state.get("finca_nombre", "Sin finca")

    save_btn = None
    _ble_connected = bool(state.get("ble_mode", False) and ble is not None)

    def _update_save_button_visibility():
        if save_btn is None:
            return
        has_data = bool(state.get("ready_to_save") and state.get("current_data"))
        save_btn.disabled = not has_data
        save_btn.opacity = 1.0 if has_data else 0.45

    def _format_timestamp(ts: str) -> str:
        if not ts:
            return ""
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            return f"Lectura: {dt.strftime('%d/%m/%Y %H:%M:%S')}"
        except Exception:
            return ""

    def _update_cards(data):
        state["current_data"] = data
        state["measured"] = True
        state["ready_to_save"] = True

        vals = get_values(data)
        for i, v in enumerate(vals):
            card_values[i].value = f"{v:.2f}"

        timestamp_text.value = _format_timestamp(data.get("timestamp", ""))
        _update_save_button_visibility()

    # ── Datos BLE reales ──────────────────────────────────────────────────────
    def _on_ble_data(data_dict):
        _update_cards(data_dict)
        status_text.value = "Recibiendo datos BLE..."
        status_text.color = accent
        status_text.visible = True
        page.update()

    if _ble_connected and ble is not None:
        ble.on_data = _on_ble_data

    # ── Header ────────────────────────────────────────────────────────────────
    def go_to_configuration(_):
        if ble is not None:
            ble.on_data = None
        navigate("/fincas")

    header = ft.Container(
        content=ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.ARROW_BACK,
                    icon_color=text_color,
                    tooltip="Volver a fincas",
                    on_click=go_to_configuration,
                ),
                ft.Text(
                    "AgroSense",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=text_color,
                ),
                ft.Container(height=1, expand=True),
                ft.IconButton(
                    icon=ft.Icons.HISTORY,
                    icon_color=sub_color,
                    on_click=lambda _: navigate("/history"),
                ),
                ft.IconButton(
                    icon=ft.Icons.BLUETOOTH_DISABLED,
                    icon_color="#F44336",
                    icon_size=18,
                    tooltip="Desconectar Bluetooth",
                    on_click=disconnect_ble,
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.AGRICULTURE, size=14, color=accent),
                            ft.Text(
                                finca_nombre,
                                size=12,
                                color=accent,
                                weight=ft.FontWeight.W_500,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                max_lines=1,
                            ),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    bgcolor="#4CAF5026",
                    border_radius=6,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    max_width=130,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=card_bg,
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border_radius=10,
    )

    timestamp_text = ft.Text("", size=11, color=sub_color)
    _init_status = "Midiendo..." if _ble_connected else "Sin conexión BLE"
    _init_color = accent if _ble_connected else "#F44336"
    status_text = ft.Text(_init_status, size=12, color=_init_color, visible=True)

    # ── Cards de sensores ─────────────────────────────────────────────────────
    card_values = []
    card_containers = []
    card_border = "#5F6B7A" if is_dark else "#C7D0DA"
    card_tint = card_bg

    for label, unit, color in SENSOR_LABELS:
        val_text = ft.Text("-", size=20, weight=ft.FontWeight.BOLD, color=color)
        card = ft.Container(
            content=ft.Column(
                [
                    val_text,
                    ft.Text(label, size=11, color=sub_color, text_align=ft.TextAlign.CENTER),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=1,
            ),
            bgcolor=card_tint,
            border_radius=14,
            border=ft.border.all(1, card_border),
            padding=10,
            width=140,
        )
        card_containers.append(card)
        card_values.append(val_text)

    if state.get("measured") and state.get("current_data"):
        data = state["current_data"]
        vals = get_values(data)
        for i, v in enumerate(vals):
            card_values[i].value = f"{v:.2f}"
        timestamp_text.value = _format_timestamp(data.get("timestamp", ""))

    row1 = ft.Row(card_containers[0:2], alignment=ft.MainAxisAlignment.CENTER, spacing=8)
    row2 = ft.Row([card_containers[2], card_containers[6]], alignment=ft.MainAxisAlignment.CENTER, spacing=8)
    row3 = ft.Row([card_containers[3], card_containers[4]], alignment=ft.MainAxisAlignment.CENTER, spacing=8)
    row4 = ft.Row([card_containers[5]], alignment=ft.MainAxisAlignment.CENTER, spacing=8)
    row5 = ft.Row(card_containers[7:9], alignment=ft.MainAxisAlignment.CENTER, spacing=8)

    section_border = "#5F6B7A" if is_dark else "#C7D0DA"
    group_tint = card_bg
    shadow_color = "#00000033" if is_dark else "#00000012"

    def build_measure_group(title: str, icon, rows):
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(icon, size=16, color=sub_color),
                                ft.Text(
                                    title,
                                    size=13,
                                    weight=ft.FontWeight.BOLD,
                                    color=text_color,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=6,
                        ),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        border_radius=12,
                        bgcolor=group_tint,
                    ),
                    ft.Container(height=10),
                    *rows,
                ],
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=12,
            border=ft.border.all(1, section_border),
            border_radius=18,
            bgcolor=card_bg,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=14,
                color=shadow_color,
                offset=ft.Offset(0, 4),
            ),
        )

    soil_box = build_measure_group(
        "Medidas de suelo",
        ft.Icons.COMPOST,
        [
            row1,
            ft.Container(height=12),
            row2,
            ft.Container(height=12),
            row3,
            ft.Container(height=12),
            row4,
        ],
    )
    air_box = build_measure_group(
        "Medidas de ambiente",
        ft.Icons.WB_CLOUDY_OUTLINED,
        [
            row5,
        ],
    )

    def do_save(_):
        if state.get("current_data"):
            navigate("/save")
        else:
            status_text.value = "Primero realiza una medición"
            status_text.color = "#F44336"
            status_text.visible = True
            page.update()

    _has_data_initial = bool(state.get("ready_to_save") and state.get("current_data"))
    save_btn = ft.Button(
        "Guardar medición",
        icon=ft.Icons.SAVE_ALT,
        on_click=do_save,
        disabled=not _has_data_initial,
        opacity=1.0 if _has_data_initial else 0.45,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=12,
            bgcolor="#4CAF50",
            color="#FFFFFF",
        ),
        width=300,
    )

    cards_area = ft.Column(
        [
            timestamp_text,
            ft.Container(height=10),
            air_box,
            ft.Container(height=14),
            soil_box,
        ],
        spacing=0,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )

    btn_col = ft.Column(
        [
            ft.Container(height=18),
            save_btn,
            ft.Container(height=8),
            status_text,
            ft.Container(height=12),
        ],
        spacing=0,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )

    content = ft.Column(
        [
            header,
            ft.Container(height=10),
            cards_area,
            btn_col,
        ],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        expand=True,
    )

    root = ft.Container(
        content=content,
        bgcolor=bg,
        expand=True,
        padding=12,
    )

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
