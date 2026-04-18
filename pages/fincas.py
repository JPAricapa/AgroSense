import flet as ft
from services.db_service import get_all_fincas, create_finca, delete_finca


def build(page: ft.Page, state: dict, navigate, is_dark: bool, disconnect_ble):
    bg = "#0D1B2A" if is_dark else "#F0F2F5"
    card_bg = "#1B263B" if is_dark else "#FFFFFF"
    text_color = "#E0E1DD" if is_dark else "#1B263B"
    sub_color = "#778DA9" if is_dark else "#6B7280"
    accent = "#4CAF50"
    border_col = "#415A77" if is_dark else "#D1D5DB"
    selected_bg = "#1F6F43" if is_dark else "#DFF3E4"

    page.controls.clear()

    header = ft.Container(
        content=ft.Row(
            [
                ft.Text(
                    "Seleccionar finca",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=text_color,
                ),
                ft.Container(expand=True),
                ft.IconButton(
                    icon=ft.Icons.SETTINGS,
                    icon_color=sub_color,
                    icon_size=22,
                    tooltip="Configuración",
                    on_click=lambda _: navigate("/configuracion"),
                ),
                ft.IconButton(
                    icon=ft.Icons.BLUETOOTH_DISABLED,
                    icon_color="#F44336",
                    icon_size=18,
                    tooltip="Desconectar Bluetooth",
                    on_click=disconnect_ble,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=card_bg,
        padding=ft.Padding.symmetric(horizontal=16, vertical=12),
        border_radius=10,
    )

    new_name_field = ft.TextField(
        label="Nombre de la finca",
        hint_text="Ej: Mi Campo",
        border_color=border_col,
        focused_border_color=accent,
        cursor_color=accent,
        color=text_color,
        label_style=ft.TextStyle(color=sub_color),
        hint_style=ft.TextStyle(color=sub_color),
        height=52,
    )

    dialog_msg = ft.Text("", size=12, visible=False)

    crear_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(
            "Nueva Finca",
            size=16,
            weight=ft.FontWeight.BOLD,
            color=text_color,
        ),
        content=ft.Column(
            [
                new_name_field,
                ft.Container(height=4),
                dialog_msg,
            ],
            tight=True,
        ),
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def cerrar_dialogo(e=None):
        crear_dialog.open = False
        page.update()

    def abrir_dialogo(e=None):
        new_name_field.value = ""
        new_name_field.border_color = border_col
        dialog_msg.value = ""
        dialog_msg.visible = False
        if crear_dialog not in page.overlay:
            page.overlay.append(crear_dialog)
        crear_dialog.open = True
        page.update()

    def guardar_finca(e=None):
        nombre = (new_name_field.value or "").strip()
        if not nombre:
            new_name_field.border_color = "#F44336"
            dialog_msg.value = "Escribe un nombre"
            dialog_msg.color = "#F44336"
            dialog_msg.visible = True
            page.update()
            return

        ok = create_finca(nombre)
        if ok:
            crear_dialog.open = False
            page.update()
            do_load()
        else:
            new_name_field.border_color = "#F44336"
            dialog_msg.value = "Esa finca ya existe"
            dialog_msg.color = "#F44336"
            dialog_msg.visible = True
            page.update()

    crear_dialog.actions = [
        ft.TextButton("Cancelar", on_click=cerrar_dialogo),
        ft.Button(
            "Crear",
            icon=ft.Icons.ADD,
            on_click=guardar_finca,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                bgcolor=accent,
                color="#FFFFFF",
                padding=12,
            ),
        ),
    ]

    fincas_col = ft.Column([], spacing=8)

    def seleccionar_finca(fid, fname):
        state["finca_id"] = fid
        state["finca_nombre"] = fname
        navigate("/dashboard")

    def confirm_delete_finca(fid, fname):
        def do_delete(_):
            page.pop_dialog()
            delete_finca(fid)
            do_load()

        def cancel(_):
            page.pop_dialog()

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Eliminar finca", size=16, weight=ft.FontWeight.BOLD, color=text_color),
                content=ft.Text(
                    f'¿Deseas eliminar la finca "{fname}"?\nSe borrarán también todas sus mediciones.',
                    size=13,
                    color=sub_color,
                ),
                actions=[
                    ft.TextButton("Cancelar", on_click=cancel),
                    ft.Button(
                        "Eliminar",
                        icon=ft.Icons.DELETE,
                        on_click=do_delete,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=8),
                            bgcolor="#F44336",
                            color="#FFFFFF",
                            padding=10,
                        ),
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def hacer_tarjeta(fid, fname, is_created):
        selected = state.get("finca_id") == fid
        current_bg = selected_bg if selected else card_bg
        current_border = accent if selected else border_col
        icon_color = accent if selected else sub_color

        delete_btn = ft.Container(width=24)
        if is_created:
            delete_btn = ft.IconButton(
                icon=ft.Icons.DELETE,
                icon_color="#F44336",
                icon_size=16,
                tooltip="Eliminar finca",
                on_click=lambda e, f=fid, n=fname: confirm_delete_finca(f, n),
            )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.AGRICULTURE, color=icon_color, size=28),
                            ft.Container(expand=True),
                            delete_btn,
                        ],
                        spacing=2,
                    ),
                    ft.Text(
                        fname,
                        size=15,
                        weight=ft.FontWeight.W_600,
                        color=text_color,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=2),
                    ft.Text(
                        "Seleccionada" if selected else "Toca para elegir",
                        size=10,
                        color=sub_color,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            bgcolor=current_bg,
            border_radius=16,
            padding=ft.Padding.symmetric(horizontal=12, vertical=12),
            border=ft.Border.all(2, current_border),
            height=110,
            ink=True,
            on_click=lambda e, f=fid, n=fname: seleccionar_finca(f, n),
            expand=True,
        )

    def hacer_agregar():
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.ADD, color=sub_color, size=28),
                            ft.Container(expand=True),
                            ft.Container(width=24),
                        ],
                        spacing=2,
                    ),
                    ft.Text(
                        "Agregar",
                        size=15,
                        weight=ft.FontWeight.W_500,
                        color=sub_color,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=2),
                    ft.Text(
                        "Toca para crear",
                        size=10,
                        color=sub_color,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            bgcolor=card_bg,
            border_radius=16,
            padding=ft.Padding.symmetric(horizontal=12, vertical=12),
            border=ft.Border.all(2, border_col),
            height=110,
            ink=True,
            on_click=abrir_dialogo,
            expand=True,
        )

    def do_load():
        fincas = get_all_fincas()
        fincas_col.controls.clear()

        all_controls = (
            [hacer_tarjeta(f, n, True) for f, n in fincas]
            + [hacer_agregar()]
        )

        total = len(all_controls)

        for r in range((total + 1) // 2):
            i1 = r * 2
            i2 = r * 2 + 1

            row = ft.Row(
                [
                    all_controls[i1] if i1 < total else ft.Container(expand=True),
                    all_controls[i2] if i2 < total else ft.Container(expand=True),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
            )
            fincas_col.controls.append(row)
            fincas_col.controls.append(ft.Container(height=8))

        page.update()

    content = ft.Container(
        content=ft.Column(
            [
                header,
                ft.Container(height=10),
                fincas_col,
            ],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
        bgcolor=bg,
        expand=True,
        padding=12,
    )

    try:
        page.add(ft.SafeArea(content=content, expand=True))
    except Exception:
        page.add(
            ft.Container(
                content=content,
                padding=ft.Padding.only(top=18),
                expand=True,
            )
        )

    page.update()
    do_load()
