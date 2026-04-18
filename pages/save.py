import asyncio
import base64
import json

import flet as ft
import flet_camera as fc
import flet_permission_handler as ph
from services.db_service import save_measurement


SENSOR_TABLE = [
    ("Temp. Ambiente", "C", 7),
    ("Hum. Ambiente", "%", 8),
    ("Temp. Suelo", "C", 0),
    ("Hum. Suelo", "%", 1),
    ("pH", "", 2),
    ("EC", "dS/m", 6),
    ("Nitrógeno", "mg/kg", 3),
    ("Fósforo", "mg/kg", 4),
    ("Potasio", "mg/kg", 5),
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


def format_value(value):
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00" if value is None else str(value)


def _clear_file_pickers(page: ft.Page):
    try:
        page.services[:] = [s for s in page.services if not isinstance(s, ft.FilePicker)]
    except Exception:
        pass


def _clear_permission_handlers(page: ft.Page):
    try:
        page.services[:] = [
            s for s in page.services
            if not (hasattr(ph, "PermissionHandler") and isinstance(s, ph.PermissionHandler))
        ]
    except Exception:
        pass


class ManagedCamera(fc.Camera):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.is_mounted = False

    def did_mount(self):
        self.is_mounted = True
        super().did_mount()

    def will_unmount(self):
        self.is_mounted = False
        super().will_unmount()


def build(page: ft.Page, state: dict, navigate, is_dark: bool, disconnect_ble):
    page.title = "AgroSense - Medidas Tomadas"
    page.controls.clear()
    _clear_file_pickers(page)
    _clear_permission_handlers(page)

    bg = "#0D1B2A" if is_dark else "#F0F2F5"
    card_bg = "#1B263B" if is_dark else "#FFFFFF"
    text_color = "#E0E1DD" if is_dark else "#1B263B"
    sub_color = "#778DA9" if is_dark else "#6B7280"
    accent = "#4CAF50"
    border_col = "#415A77" if is_dark else "#D1D5DB"
    table_header_bg = "#374151" if is_dark else "#E5E7EB"
    table_bg = "#243447" if is_dark else "#F3F4F6"

    finca_nombre = state.get("finca_nombre", "Sin finca")
    image_data = [None]
    current_camera = [None]
    current_dialog = [None]

    picker = ft.FilePicker()
    try:
        page.services.append(picker)
    except Exception:
        pass

    _is_mobile = page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
    permission_handler = [None]

    def mount_permission_handler(force_recreate: bool = False):
        if not _is_mobile:
            return None

        current = permission_handler[0]
        if not force_recreate and current is not None and getattr(current, "page", None) is not None:
            return current

        try:
            _clear_permission_handlers(page)
            current = ph.PermissionHandler()
            page.services.append(current)
            permission_handler[0] = current
            page.update()
            return current
        except Exception:
            permission_handler[0] = None
            return None

    def safe_update():
        try:
            page.update()
        except Exception:
            pass

    # ── Header ────────────────────────────────────────────────────────────────
    header = ft.Container(
        content=ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.ARROW_BACK_IOS,
                    icon_color=text_color,
                    on_click=lambda _: navigate("/dashboard"),
                ),
                ft.Text(
                    "Medidas Tomadas",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=text_color,
                ),
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
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=card_bg,
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border_radius=10,
    )

    # ── Preview de imagen ─────────────────────────────────────────────────────
    foto_preview = ft.Container(
        content=ft.Image(
            src="",
            width=300,
            height=160,
            fit=ft.BoxFit.COVER,
            border_radius=10,
        ),
        bgcolor=card_bg,
        border_radius=10,
        border=ft.Border.all(1, border_col),
    )

    foto_status = ft.Text("Imagen: No", size=12, color="#F44336")
    msg = ft.Text("", size=13, visible=False)

    def open_preview_dialog(_=None):
        if not image_data[0]:
            return

        def close_preview(_=None):
            page.pop_dialog()

        dialog = ft.AlertDialog(
            modal=True,
            content=ft.Container(
                width=360,
                height=500,
                content=ft.InteractiveViewer(
                    min_scale=0.8,
                    max_scale=4.0,
                    boundary_margin=20,
                    content=ft.Image(
                        src=image_data[0],
                        fit=ft.BoxFit.CONTAIN,
                    ),
                ),
            ),
            actions=[ft.TextButton("Cerrar", on_click=close_preview)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(dialog)

    # Container tappable para ampliar la foto
    foto_tap = ft.Container(
        content=ft.Stack(
            controls=[
                ft.Image(
                    src="",
                    width=300,
                    height=160,
                    fit=ft.BoxFit.COVER,
                    border_radius=10,
                ),
                ft.Container(
                    content=ft.Icon(ft.Icons.ZOOM_IN, color="#FFFFFF", size=28),
                    alignment=ft.Alignment(1, 1),
                    width=300,
                    height=160,
                    padding=ft.Padding.only(right=8, bottom=8),
                ),
            ],
            width=300,
            height=160,
        ),
        border_radius=10,
        border=ft.Border.all(1, border_col),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        on_click=open_preview_dialog,
        ink=True,
        visible=False,
    )

    def process_image_bytes(img_bytes):
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        image_data[0] = f"data:image/jpeg;base64,{b64}"
        # Actualizar la imagen dentro del Stack
        foto_tap.content.controls[0].src = image_data[0]
        foto_tap.visible = True
        foto_status.value = "Imagen: Sí  (toca para ampliar)"
        foto_status.color = accent
        msg.value = "Foto agregada"
        msg.color = accent
        msg.visible = True
        safe_update()

    def show_error(text: str):
        foto_status.value = text
        foto_status.color = "#F44336"
        msg.value = text
        msg.color = "#F44336"
        msg.visible = True
        safe_update()

    def close_camera():
        current_camera[0] = None
        dialog = current_dialog[0]
        current_dialog[0] = None
        if dialog is not None:
            try:
                page.pop_dialog()
            except Exception:
                try:
                    dialog.open = False
                    safe_update()
                except Exception:
                    pass

    async def wait_for_camera_mount(camera: ManagedCamera):
        for _ in range(40):
            if camera.is_mounted:
                try:
                    _ = camera.page
                    return True
                except RuntimeError:
                    pass
            await asyncio.sleep(0.1)
        return False

    async def open_gallery():
        files = await picker.pick_files(
            allow_multiple=False,
            dialog_title="Seleccionar foto del cultivo",
            file_type=ft.FilePickerFileType.IMAGE,
            with_data=True,
        )

        if not files:
            foto_status.value = "Selección cancelada"
            foto_status.color = "#FF9800"
            msg.value = "No se seleccionó ninguna imagen"
            msg.color = "#FF9800"
            msg.visible = True
            safe_update()
            return

        file = files[0]
        if getattr(file, "bytes", None):
            process_image_bytes(file.bytes)
            return

        if getattr(file, "path", None):
            with open(file.path, "rb") as fp:
                process_image_bytes(fp.read())
            return

        show_error("No se pudo leer la imagen seleccionada")

    async def open_camera():
        if page.platform not in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS):
            raise RuntimeError("La cámara directa solo está soportada en Android o iOS")

        handler = mount_permission_handler()
        if handler is not None:
            try:
                status = await handler.request(ph.Permission.CAMERA)
            except RuntimeError as exc:
                if "Control must be added to the page first" not in str(exc):
                    raise
                handler = mount_permission_handler(force_recreate=True)
                if handler is None:
                    show_error("No se pudo validar el permiso de cámara")
                    return
                await asyncio.sleep(0)
                status = await handler.request(ph.Permission.CAMERA)
            if status != ph.PermissionStatus.GRANTED:
                show_error("Permiso de cámara denegado")
                return

        camera = ManagedCamera(
            preview_enabled=True,
            width=320,
            height=260,
        )
        current_camera[0] = camera

        capture_btn = ft.Button(
            "Capturar",
            icon=ft.Icons.PHOTO_CAMERA,
            disabled=True,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=12,
                bgcolor=accent,
                color="#FFFFFF",
            ),
            width=220,
        )

        async def capturar_foto(_):
            try:
                img_bytes = await camera.take_picture()
                process_image_bytes(img_bytes)
                close_camera()
            except Exception as ex:
                show_error(f"No se pudo tomar la foto: {ex}")

        capture_btn.on_click = capturar_foto

        dialog = ft.AlertDialog(
            modal=True,
            content=ft.Container(
                width=340,
                content=ft.Column(
                    [
                        ft.Text(
                            "Tomar foto",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color=text_color,
                        ),
                        ft.Container(height=12),
                        ft.Container(
                            content=camera,
                            border_radius=12,
                            border=ft.Border.all(1, border_col),
                            clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        ),
                        ft.Container(height=12),
                        capture_btn,
                    ],
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
            actions=[
                ft.TextButton("Cerrar", on_click=lambda _: close_camera()),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        current_dialog[0] = dialog

        foto_status.value = "Abriendo cámara..."
        foto_status.color = "#FF9800"
        msg.value = "Preparando cámara"
        msg.color = "#FF9800"
        msg.visible = True
        page.show_dialog(dialog)
        safe_update()

        mounted = await wait_for_camera_mount(camera)
        if not mounted:
            close_camera()
            raise RuntimeError("La cámara no terminó de montarse en la página")

        cameras = await camera.get_available_cameras()
        if not cameras:
            close_camera()
            raise RuntimeError("No se encontraron cámaras disponibles")

        selected = next(
            (c for c in cameras if c.lens_direction == fc.CameraLensDirection.BACK),
            cameras[0],
        )
        await camera.initialize(
            selected,
            fc.ResolutionPreset.HIGH,
            enable_audio=False,
        )

        capture_btn.disabled = False
        foto_status.value = "Cámara lista"
        foto_status.color = accent
        msg.value = "Toma la foto del cultivo"
        msg.color = accent
        msg.visible = True
        safe_update()

    async def tomar_foto(_):
        try:
            await open_camera()
        except Exception as ex:
            try:
                await open_gallery()
            except Exception:
                show_error(f"No se pudo abrir la cámara: {ex}")

    # ── Tabla de sensores ─────────────────────────────────────────────────────
    data = state.get("current_data")
    vals = get_values(data) if data else [0] * 9

    table_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(label, size=12, color=sub_color)),
                ft.DataCell(
                    ft.Text(
                        format_value(vals[idx]),
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=text_color,
                    )
                ),
                ft.DataCell(ft.Text(unit, size=12, color=sub_color)),
            ]
        )
        for label, unit, idx in SENSOR_TABLE
    ]

    table = ft.DataTable(
        heading_row_color=table_header_bg,
        border=ft.Border.all(1, border_col),
        border_radius=8,
        column_spacing=20,
        columns=[
            ft.DataColumn(
                ft.Text(
                    "Sensor",
                    size=12,
                    color=text_color if is_dark else "#374151",
                    weight=ft.FontWeight.BOLD,
                )
            ),
            ft.DataColumn(
                ft.Text(
                    "Valor",
                    size=12,
                    color=text_color if is_dark else "#374151",
                    weight=ft.FontWeight.BOLD,
                )
            ),
            ft.DataColumn(
                ft.Text(
                    "Uni.",
                    size=12,
                    color=text_color if is_dark else "#374151",
                    weight=ft.FontWeight.BOLD,
                )
            ),
        ],
        rows=table_rows,
    )

    table_container = ft.Row(
        [table],
        alignment=ft.MainAxisAlignment.CENTER,
    )

    def do_save(_):
        if not state.get("current_data"):
            msg.value = "No hay datos para guardar"
            msg.color = "#F44336"
            msg.visible = True
            safe_update()
            return

        if not state.get("finca_id"):
            msg.value = "No hay finca seleccionada"
            msg.color = "#F44336"
            msg.visible = True
            safe_update()
            return

        save_measurement(
            state.get("finca_id"),
            json.dumps(state["current_data"]),
            image_data[0],
        )

        state["current_data"] = None
        state["measured"] = False
        state["ready_to_save"] = False

        msg.value = "¡Medición guardada!"
        msg.color = accent
        msg.visible = True
        safe_update()
        navigate("/history")

    col = ft.Column(
        [
            header,
            ft.Container(height=8),
            ft.Container(
                content=ft.Text(
                    "Datos de la medición",
                    size=13,
                    weight=ft.FontWeight.W_500,
                    color=sub_color,
                ),
                padding=ft.Padding.only(left=4),
            ),
            ft.Container(height=4),
            table_container,
            ft.Container(height=12),
            ft.Button(
                "Tomar foto",
                icon=ft.Icons.CAMERA_ALT,
                on_click=tomar_foto,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=12),
                    padding=12,
                    bgcolor="#00796B",
                    color="#FFFFFF",
                ),
                width=300,
            ),
            ft.Container(height=8),
            ft.Button(
                "Elegir desde la galería",
                icon=ft.Icons.PHOTO_LIBRARY,
                on_click=lambda _: page.run_task(open_gallery),
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=12),
                    padding=12,
                    bgcolor="#1565C0",
                    color="#FFFFFF",
                ),
                width=300,
            ),
            ft.Container(height=4),
            foto_tap,
            ft.Container(height=4),
            foto_status,
            ft.Container(height=12),
            msg,
            ft.Container(height=12),
            ft.Button(
                "Guardar medición",
                icon=ft.Icons.SAVE,
                on_click=do_save,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=12),
                    padding=14,
                    bgcolor=accent,
                    color="#FFFFFF",
                ),
                width=300,
            ),
            ft.Container(height=8),
            ft.Button(
                "Volver a medir",
                icon=ft.Icons.REPLAY,
                on_click=lambda _: navigate("/dashboard"),
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=12),
                    padding=14,
                    bgcolor="#3949AB",
                    color="#FFFFFF",
                ),
                width=300,
            ),
        ],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )

    root = ft.Container(
        content=col,
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

    mount_permission_handler()
    safe_update()
