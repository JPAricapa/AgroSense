import flet as ft
import csv
import json
from datetime import datetime
from pathlib import Path
from services.db_service import APP_DIR, get_measurements_by_finca, delete_measurement


SENSOR_TABLE = [
    ("Temp. Suelo", "C"),
    ("Hum. Suelo", "%"),
    ("pH", ""),
    ("Nitrógeno", "mg/kg"),
    ("Fósforo", "mg/kg"),
    ("Potasio", "mg/kg"),
    ("EC", "dS/m"),
    ("Temp. Ambiente", "C"),
    ("Hum. Ambiente", "%"),
]


EXPORT_COLUMNS = [
    ("Temp. Ambiente (C)", 7),
    ("Hum. Ambiente (%)", 8),
    ("Temp. Suelo (C)", 0),
    ("Hum. Suelo (%)", 1),
    ("pH", 2),
    ("EC (dS/m)", 6),
    ("Nitrógeno (mg/kg)", 3),
    ("Fósforo (mg/kg)", 4),
    ("Potasio (mg/kg)", 5),
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


def build(page: ft.Page, state: dict, navigate, is_dark: bool, disconnect_ble):
    page.title = "AgroSense - Historial"

    bg         = "#0D1B2A" if is_dark else "#F0F2F5"
    card_bg    = "#1B263B" if is_dark else "#FFFFFF"
    text_color = "#E0E1DD" if is_dark else "#1B263B"
    sub_color  = "#778DA9" if is_dark else "#6B7280"
    accent = "#2E7D32"
    thumb_placeholder_bg = "#1F2D3D" if is_dark else "#E5E7EB"
    close_btn_bg = "#546E7A" if is_dark else "#607D8B"
    detail_table_bg = "#183A2A" if is_dark else "#E8F5E9"
    detail_table_border = "#2E7D32" if is_dark else "#A5D6A7"
    export_btn_bg = detail_table_bg
    export_btn_border = detail_table_border
    export_btn_text = "#E0E1DD" if is_dark else "#1B263B"

    page.controls.clear()

    finca_nombre = state.get("finca_nombre", "Sin finca")
    export_status = ft.Text("", size=11, visible=False)

    share = ft.Share()
    try:
        page.services[:] = [s for s in page.services if not isinstance(s, ft.Share)]
        page.services.append(share)
    except Exception:
        pass

    def show_export_status(text: str, color: str):
        export_status.value = text
        export_status.color = color
        export_status.visible = True
        page.update()

    def build_image_src(image_value):
        if not image_value:
            return None
        if isinstance(image_value, str) and image_value.startswith("data:image/"):
            return image_value
        return f"data:image/jpeg;base64,{image_value}"

    def close_button(label: str, on_click):
        return ft.Button(
            label,
            icon=ft.Icons.CLOSE,
            on_click=on_click,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                bgcolor=close_btn_bg,
                color="#FFFFFF",
                padding=8,
            ),
        )

    def show_image_dialog(src):
        def close_big(_=None):
            page.pop_dialog()

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                content=ft.Container(
                    width=360,
                    height=500,
                    content=ft.InteractiveViewer(
                        min_scale=0.8,
                        max_scale=4.0,
                        boundary_margin=20,
                        content=ft.Image(src=src, fit=ft.BoxFit.CONTAIN),
                    ),
                ),
                actions=[close_button("Cerrar", close_big)],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    # ── Diálogo de detalle ────────────────────────────────────────────────────
    def open_detail_dialog(mid, vals, imagen, fecha, hora):
        _short = {0: "Temperatura", 1: "Humedad", 7: "Temperatura", 8: "Humedad"}

        def sensor_cell(i):
            label, unit = SENSOR_TABLE[i]
            label = _short.get(i, label)
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Text(label, size=10, color=sub_color, text_align=ft.TextAlign.CENTER),
                        ft.Text(
                            f"{vals[i]:.2f} {unit}".strip(),
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=text_color,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=2,
                ),
                bgcolor=detail_table_bg,
                border_radius=8,
                border=ft.Border.all(1, detail_table_border),
                padding=ft.Padding.symmetric(horizontal=6, vertical=6),
                expand=True,
            )

        def section_header(label: str, icon):
            return ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(icon, size=14, color=sub_color),
                        ft.Text(label, size=11, weight=ft.FontWeight.BOLD, color=sub_color),
                    ],
                    spacing=4,
                    tight=True,
                ),
                padding=ft.Padding.only(top=6, bottom=2),
            )

        AMBIENT_ROWS = [(7, 8)]
        SOIL_ROWS = [(0, 1), (2, 6), (3, 4), (5, None)]

        sensor_rows = [section_header("Medidas de ambiente", ft.Icons.WB_CLOUDY_OUTLINED)]
        for left_idx, right_idx in AMBIENT_ROWS:
            sensor_rows.append(
                ft.Row(
                    [
                        sensor_cell(left_idx),
                        sensor_cell(right_idx) if right_idx is not None else ft.Container(expand=True),
                    ],
                    spacing=6,
                )
            )
        sensor_rows.append(section_header("Medidas de suelo", ft.Icons.COMPOST))
        for left_idx, right_idx in SOIL_ROWS:
            sensor_rows.append(
                ft.Row(
                    [
                        sensor_cell(left_idx),
                        sensor_cell(right_idx) if right_idx is not None else ft.Container(expand=True),
                    ],
                    spacing=6,
                )
            )

        detail_table = ft.Column(sensor_rows, spacing=6)

        img_widget = ft.Container()
        if imagen:
            image_src = build_image_src(imagen)

            def open_detail_image(_):
                show_image_dialog(image_src)

            img_widget = ft.Container(
                content=ft.Stack(
                    controls=[
                        ft.Image(
                            src=image_src,
                            width=340,
                            height=200,
                            fit=ft.BoxFit.CONTAIN,
                        ),
                        ft.Container(
                            content=ft.Icon(ft.Icons.ZOOM_IN, color="#FFFFFF", size=18),
                            alignment=ft.Alignment(1, 1),
                            width=340,
                            height=200,
                            padding=ft.Padding.only(right=6, bottom=6),
                        ),
                    ],
                    width=340,
                    height=200,
                ),
                height=200,
                width=340,
                border_radius=10,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                ink=True,
                on_click=open_detail_image,
            )

        def close(_=None):
            page.pop_dialog()

        def confirm_delete(_):
            def do_delete(__):
                page.pop_dialog()
                delete_measurement(mid)
                page.pop_dialog()
                do_load()

            def cancel_delete(__):
                page.pop_dialog()

            page.show_dialog(
                ft.AlertDialog(
                    modal=True,
                    title=ft.Text("Eliminar medición", size=16, weight=ft.FontWeight.BOLD, color=text_color),
                    content=ft.Text(
                        f"¿Deseas eliminar la medición del {fecha} {hora}?\nEsta acción no se puede deshacer.",
                        size=13,
                        color=sub_color,
                    ),
                    actions=[
                        ft.TextButton("Cancelar", on_click=cancel_delete),
                        ft.Button(
                            "Eliminar",
                            icon=ft.Icons.DELETE,
                            on_click=do_delete,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=8),
                                bgcolor="#F44336",
                                color="#FFFFFF",
                                padding=8,
                            ),
                        ),
                    ],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
            )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                f"{fecha}  {hora}",
                size=14,
                weight=ft.FontWeight.BOLD,
                color=text_color,
            ),
            content=ft.Container(
                width=360,
                height=460,
                content=ft.Column(
                    [
                        img_widget,
                        ft.Container(height=8),
                        detail_table,
                        ft.Container(height=4),
                        ft.Text(f"Fecha: {fecha}  {hora}", size=11, color=sub_color),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    spacing=0,
                ),
            ),
            actions=[
                ft.Button(
                    "Eliminar",
                    icon=ft.Icons.DELETE,
                    on_click=confirm_delete,
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=8),
                        bgcolor="#F44336",
                        color="#FFFFFF",
                        padding=8,
                    ),
                ),
                close_button("Cerrar", close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(dialog)

    # ── Card compacta ─────────────────────────────────────────────────────────
    def hacer_card(mid, fecha, hora, vals, imagen):
        image_src = build_image_src(imagen)

        if image_src:
            thumbnail = ft.Container(
                content=ft.Stack(
                    controls=[
                        ft.Image(
                            src=image_src,
                            width=80,
                            height=80,
                            fit=ft.BoxFit.COVER,
                            border_radius=8,
                        ),
                        ft.Container(
                            content=ft.Icon(ft.Icons.ZOOM_IN, color="#FFFFFF", size=18),
                            alignment=ft.Alignment(1, 1),
                            width=80,
                            height=80,
                            padding=ft.Padding.only(right=4, bottom=4),
                        ),
                    ],
                    width=80,
                    height=80,
                ),
                border_radius=8,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                width=80,
                height=80,
            )
        else:
            thumbnail = ft.Container(
                content=ft.Icon(ft.Icons.GRASS, size=32, color=sub_color),
                width=80,
                height=80,
                alignment=ft.Alignment(0, 0),
                bgcolor=thumb_placeholder_bg,
                border_radius=8,
            )

        return ft.Container(
            content=ft.Row(
                [
                    thumbnail,
                    ft.Container(width=10),
                    ft.Column(
                        [
                            ft.Text(
                                f"{fecha}  {hora}",
                                size=12,
                                color=text_color,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Text(
                                f"Temp. Ambiente: {vals[7]:.1f} C   Hum. Ambiente: {vals[8]:.0f} %",
                                size=11,
                                color=sub_color,
                            ),
                            ft.Text(
                                f"Temp. Suelo: {vals[0]:.1f} C   Hum. Suelo: {vals[1]:.0f} %",
                                size=11,
                                color=sub_color,
                            ),
                            ft.Text(
                                f"pH: {vals[2]:.1f}   EC: {vals[6]:.1f} dS/m",
                                size=11,
                                color=sub_color,
                            ),
                            ft.Text(
                                f"Nitrógeno: {vals[3]:.0f}   Fósforo: {vals[4]:.0f}",
                                size=11,
                                color=sub_color,
                            ),
                            ft.Text(
                                f"Potasio: {vals[5]:.0f}",
                                size=11,
                                color=sub_color,
                            ),
                        ],
                        spacing=3,
                        expand=True,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18, color=sub_color),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
            ),
            bgcolor=card_bg,
            border_radius=12,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            ink=True,
            on_click=lambda e, m=mid, v=vals, img=imagen, f=fecha, h=hora: open_detail_dialog(m, v, img, f, h),
        )

    async def export_csv():
        finca_id = state.get("finca_id")
        rows = get_measurements_by_finca(finca_id)

        if not rows:
            show_export_status("No hay datos para enviar en esta finca", "#FF9800")
            return

        safe_finca = "".join(
            c if c.isalnum() or c in ("_", "-") else "_"
            for c in (finca_nombre or "finca")
        )
        file_name = (
            f"agrosense_historial_{safe_finca}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )

        export_dir = APP_DIR / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        target_path = str(export_dir / file_name)

        def format_num(value, decimals=2):
            try:
                return f"{float(value):.{decimals}f}"
            except (TypeError, ValueError):
                return ""

        try:
            with open(target_path, "w", encoding="utf-8-sig", newline="") as csv_file:
                writer = csv.writer(csv_file, delimiter=";")
                writer.writerow([
                    "No. Medición",
                    "Fecha",
                    "Hora",
                    *[label for label, _ in EXPORT_COLUMNS],
                ])

                for numero, (_, timestamp, sensor_json, _) in enumerate(reversed(rows), start=1):
                    try:
                        data = json.loads(sensor_json)
                    except Exception:
                        data = {}
                    vals = get_values(data)

                    try:
                        dt = datetime.fromisoformat(timestamp)
                        fecha = dt.strftime("%d/%m/%Y")
                        hora = dt.strftime("%H:%M:%S")
                    except Exception:
                        fecha = timestamp[:10] if timestamp else ""
                        hora = timestamp[11:19] if timestamp and len(timestamp) >= 19 else ""

                    writer.writerow([
                        numero,
                        fecha,
                        hora,
                        *[format_num(vals[idx], 2) for _, idx in EXPORT_COLUMNS],
                    ])
        except Exception as ex:
            show_export_status(f"No se pudo generar el archivo: {ex}", "#F44336")
            return

        try:
            await share.share_files(
                [ft.ShareFile.from_path(target_path)],
                title="Compartir historial CSV de AgroSense",
                text=f"Historial de AgroSense: {Path(target_path).name}",
                subject=f"Historial AgroSense - {finca_nombre}",
            )
            show_export_status("Datos listos para compartir", "#4CAF50")
        except Exception as ex:
            show_export_status(f"No se pudo abrir compartir: {ex}", "#FF9800")

    # ── Header ────────────────────────────────────────────────────────────────
    header = ft.Container(
        content=ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.ARROW_BACK,
                    icon_color=text_color,
                    on_click=lambda _: navigate("/dashboard"),
                ),
                ft.Text("Historial", size=18, weight=ft.FontWeight.BOLD, color=text_color),
                ft.Container(expand=True),
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
                            ft.Icon(ft.Icons.AGRICULTURE, size=14, color="#4CAF50"),
                            ft.Text(
                                finca_nombre,
                                size=12,
                                color="#4CAF50",
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
        ),
        bgcolor=card_bg,
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
    )

    export_controls = ft.Container(
        content=ft.Column(
            [
                ft.Button(
                    "Enviar datos",
                    icon=ft.Icons.SHARE,
                    on_click=lambda _: page.run_task(export_csv),
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=10),
                        padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                        bgcolor=export_btn_bg,
                        color=export_btn_text,
                        side=ft.BorderSide(1, export_btn_border),
                    ),
                ),
                export_status,
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.START,
        ),
        padding=ft.Padding.only(left=2, top=2, bottom=2),
    )

    content_col = ft.Column([], spacing=8)

    def do_load():
        rows = get_measurements_by_finca(state.get("finca_id"))
        content_col.controls.clear()

        if not rows:
            content_col.controls.append(
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Icon(ft.Icons.FOLDER_OPEN, size=48, color=sub_color),
                                    ft.Text("No hay mediciones guardadas", size=14, color=sub_color),
                                    ft.Text("Mide desde el dashboard", size=12, color=sub_color),
                                ],
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            padding=40,
                        )
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    expand=True,
                )
            )
        else:
            cards = []
            for row in rows:
                mid, timestamp, sensor_json, imagen = row

                try:
                    data = json.loads(sensor_json)
                    vals = get_values(data)
                except Exception:
                    vals = [0.0] * 9

                try:
                    dt    = datetime.fromisoformat(timestamp)
                    fecha = dt.strftime("%d/%m/%Y")
                    hora  = dt.strftime("%H:%M")
                except Exception:
                    fecha = timestamp[:10] if timestamp else ""
                    hora  = timestamp[11:16] if len(timestamp) > 16 else ""

                cards.append(hacer_card(mid, fecha, hora, vals, imagen))

            for card in cards:
                content_col.controls.append(card)

        page.update()

    # ── Layout ────────────────────────────────────────────────────────────────
    scroll_col = ft.Column(
        [header, export_controls, ft.Container(height=8), content_col],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    root = ft.Container(
        content=scroll_col,
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
    do_load()
