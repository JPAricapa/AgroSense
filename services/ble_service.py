"""
BLE service for communicating with the ESP32_SENSOR device using bleak.

Scans for a device named "ESP32_SENSOR", connects, subscribes to
notifications on characteristic 5678, and maps the incoming JSON
to the app-internal sensor format.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime

try:
    from bleak import BleakClient, BleakScanner
    _BLEAK_AVAILABLE = True
except Exception:
    _BLEAK_AVAILABLE = False

logger = logging.getLogger(__name__)

SERVICE_UUID = "00001234-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUID = "00005678-0000-1000-8000-00805f9b34fb"
DEVICE_NAME = "ESP32_SENSOR"
SCAN_TIMEOUT_S = 10.0


class BLEService:
    _last_p4android_error: str | None = None

    def __init__(self):
        self.on_data = None
        self.on_status = None
        self._connected = False
        self._client: "BleakClient | None" = None
        self._connecting = False
        self._disconnecting = False
        self._loop: "asyncio.AbstractEventLoop | None" = None
        self._pending_cleanup_task: "asyncio.Task | None" = None
        # Buffer for assembling fragmented BLE notifications
        self._rx_buffer = ""

    @staticmethod
    def _short_error(exc: BaseException) -> str:
        msg = str(exc).strip()
        return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__

    @staticmethod
    def _patch_pyjnius_for_serious_python() -> None:
        """Patch jnius.autoclass aliases used by bleak p4android on Flet."""
        # Pyjnius uses ANDROID_ARGUMENT as an Android runtime marker for some
        # thread cleanup hooks. Serious Python does not always expose the same
        # environment as python-for-android, so set a harmless marker before the
        # first jnius import when running inside the APK.
        if (
            "ANDROID_ARGUMENT" not in os.environ
            and os.environ.get("ANDROID_ROOT")
            and os.environ.get("ANDROID_DATA")
        ):
            os.environ["ANDROID_ARGUMENT"] = os.getcwd()

        try:
            import jnius  # type: ignore
        except Exception:
            return

        if getattr(jnius, "_agroprecision_ble_patch", False):
            return

        original_autoclass = jnius.autoclass

        def install_activity_class_loader() -> None:
            """Make pyjnius proxies visible to Java classes packaged in the APK."""
            try:
                thread = original_autoclass("java.lang.Thread").currentThread()
                python_activity = original_autoclass(
                    "com.flet.serious_python_android.PythonActivity"
                )
                activity = python_activity.mActivity
                if activity is None:
                    return

                loader = activity.getClassLoader()
                if loader is None:
                    app_context = activity.getApplicationContext()
                    if app_context is not None:
                        loader = app_context.getClassLoader()

                if loader is not None:
                    thread.setContextClassLoader(loader)
            except Exception:
                logger.debug("Could not install Android Activity classloader", exc_info=True)

        aliases = {
            "org.kivy.android.PythonActivity": [
                "com.flet.serious_python_android.PythonActivity",
                "org.kivy.android.PythonActivity",
            ],
            "org.kivy.android.PythonService": [
                "com.flet.serious_python_android.PythonService",
                "org.kivy.android.PythonService",
            ],
        }

        def patched_autoclass(name):
            if name in aliases:
                last_exc = None
                for candidate in aliases[name]:
                    try:
                        return original_autoclass(candidate)
                    except Exception as ex:
                        last_exc = ex
                if last_exc is not None:
                    raise last_exc
            return original_autoclass(name)

        install_activity_class_loader()
        jnius.autoclass = patched_autoclass
        jnius._agroprecision_ble_patch = True

        # Load these classes after the classloader switch so pyjnius dynamic
        # proxies can implement Bleak's callback interfaces on Android/Flet.
        for class_name in (
            "org.jnius.NativeInvocationHandler",
            "com.github.hbldh.bleak.PythonScanCallback",
            "com.github.hbldh.bleak.PythonScanCallback$Interface",
            "com.github.hbldh.bleak.PythonBluetoothGattCallback",
            "com.github.hbldh.bleak.PythonBluetoothGattCallback$Interface",
        ):
            try:
                original_autoclass(class_name)
            except Exception:
                logger.debug("Could not preload Java class %s", class_name, exc_info=True)

    @staticmethod
    def _has_flet_android_activity() -> bool:
        """Return True when Serious Python exposes the current Android Activity."""
        try:
            import jnius  # type: ignore

            python_activity = jnius.autoclass(
                "com.flet.serious_python_android.PythonActivity"
            )
            return python_activity.mActivity is not None
        except Exception:
            return False

    @staticmethod
    def _is_android_runtime() -> bool:
        """Best-effort Android runtime detection."""
        if sys.platform == "android":
            return True
        if hasattr(sys, "getandroidapilevel"):
            return True
        if os.environ.get("P4A_BOOTSTRAP") is not None:
            return True
        if os.environ.get("ANDROID_ARGUMENT") is not None:
            return True
        if os.environ.get("ANDROID_ROOT") and os.environ.get("ANDROID_DATA"):
            return True
        return BLEService._has_flet_android_activity()

    @classmethod
    def _try_load_p4android_backend(cls) -> tuple[dict, dict]:
        """Try loading bleak Android backend classes."""
        scanner_kwargs: dict = {}
        client_kwargs: dict = {}
        cls._last_p4android_error = None

        try:
            cls._patch_pyjnius_for_serious_python()
            from bleak.backends.p4android.client import BleakClientP4Android
            from bleak.backends.p4android.scanner import BleakScannerP4Android

            scanner_kwargs["backend"] = BleakScannerP4Android
            client_kwargs["backend"] = BleakClientP4Android
        except Exception as exc:
            cls._last_p4android_error = cls._short_error(exc)
            logger.exception("Could not load bleak p4android backend")

        return scanner_kwargs, client_kwargs

    def _get_bleak_backend_kwargs(self) -> tuple[dict, dict]:
        """Return backend kwargs for scanner/client when running on Android."""
        if self._is_android_runtime():
            return self._try_load_p4android_backend()

        return {}, {}

    def _emit_status(self, status: str) -> None:
        """Emit BLE status updates on the app loop when possible."""
        callback = self.on_status
        if callback is None:
            return

        loop = self._loop
        if loop is not None and loop.is_running() and not loop.is_closed():
            loop.call_soon_threadsafe(callback, status)
            return

        callback(status)

    def _reset_connection_state(self, client: "BleakClient | None" = None) -> None:
        """Clear transient BLE state so a fresh scan can start cleanly."""
        self._connected = False
        self._rx_buffer = ""
        if client is None or self._client is client:
            self._client = None

    def _track_cleanup_task(self, task: "asyncio.Task") -> None:
        self._pending_cleanup_task = task

        def _clear_done(done_task: "asyncio.Task") -> None:
            if self._pending_cleanup_task is done_task:
                self._pending_cleanup_task = None

        task.add_done_callback(_clear_done)

    async def _await_pending_cleanup(self) -> None:
        task = self._pending_cleanup_task
        if task is None:
            return

        try:
            await asyncio.shield(task)
        except Exception:
            logger.debug("Pending BLE cleanup failed", exc_info=True)

    async def _cleanup_client(self, client: "BleakClient | None") -> None:
        """Close a stale BLE client so Android can reconnect without restarting."""
        if client is None:
            return

        try:
            if client.is_connected:
                try:
                    await client.stop_notify(CHARACTERISTIC_UUID)
                except Exception:
                    logger.debug("Failed to stop BLE notifications during cleanup", exc_info=True)
            await client.disconnect()
        except Exception:
            logger.debug("BLE client cleanup failed", exc_info=True)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------
    @property
    def is_connected(self):
        return self._connected and self._client is not None and self._client.is_connected

    # ------------------------------------------------------------------
    # connect – callable from sync context (button click)
    # ------------------------------------------------------------------
    def connect(self):
        """Start an async connection task.

        Works whether or not an asyncio loop is already running:
        * If a running loop exists (Flet), schedule a task on it.
        * Otherwise, fall back to ``asyncio.run()``.
        """
        if not _BLEAK_AVAILABLE:
            if self.on_status:
                self.on_status("error:bleak no instalado – pip install bleak")
            return

        if self._connecting:
            logger.warning("connect() called while already connecting, ignoring")
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        else:
            self._loop = loop

        if loop and loop.is_running():
            loop.create_task(self._connect_async())
        else:
            asyncio.run(self._connect_async())

    # ------------------------------------------------------------------
    # disconnect
    # ------------------------------------------------------------------
    def disconnect(self):
        """Disconnect from BLE device (sync-friendly)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(self._disconnect_async())
        else:
            if self._client and self._client.is_connected:
                asyncio.run(self._disconnect_async())
            else:
                self._reset_connection_state(self._client)
                self._emit_status("disconnected")

    # ------------------------------------------------------------------
    # send_config
    # ------------------------------------------------------------------
    def send_config(self, interval_ms: int, hibernate_minutes: int = 0):
        """Send configuration to the ESP32 from sync contexts."""
        if not self.is_connected:
            logger.warning("send_config called but not connected")
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(self.send_config_async(interval_ms, hibernate_minutes))
        else:
            asyncio.run(self.send_config_async(interval_ms, hibernate_minutes))

    async def send_config_async(self, interval_ms: int, hibernate_minutes: int = 0) -> bool:
        """Send configuration to the ESP32 and wait for the write to finish."""
        if not self.is_connected:
            logger.warning("send_config_async called but not connected")
            return False

        payload = f"{interval_ms},{hibernate_minutes}"
        return await self._send_config_async(payload)

    # ------------------------------------------------------------------
    # Internal async helpers
    # ------------------------------------------------------------------
    async def _connect_async(self):
        """Scan, connect, and subscribe to notifications."""
        self._loop = asyncio.get_running_loop()
        self._connecting = True
        try:
            await self._await_pending_cleanup()

            stale_client = self._client
            if stale_client is not None:
                self._reset_connection_state(stale_client)
                await self._cleanup_client(stale_client)
                if self._is_android_runtime():
                    # Give Android a brief moment to release the previous GATT.
                    await asyncio.sleep(0.35)

            is_android = self._is_android_runtime()
            scanner_kwargs, client_kwargs = self._get_bleak_backend_kwargs()
            if is_android and not scanner_kwargs:
                detail = self._last_p4android_error or "sin detalle disponible"
                raise RuntimeError(
                    "No se pudo inicializar el backend BLE de Android "
                    f"(p4android). Detalle: {detail}"
                )

            # --- scanning ---
            self._emit_status("searching")

            device = await BleakScanner.find_device_by_name(
                DEVICE_NAME, timeout=SCAN_TIMEOUT_S, **scanner_kwargs
            )

            if device is None:
                self._emit_status("error:not_found")
                return

            logger.info("Found device: %s [%s]", device.name, device.address)

            # --- connecting ---
            client = BleakClient(
                device,
                disconnected_callback=self._on_disconnect,
                **client_kwargs
            )
            await client.connect()
            self._client = client
            self._connected = True

            # --- subscribe to notifications ---
            await client.start_notify(
                CHARACTERISTIC_UUID, self._notification_handler,
            )

            logger.info("Connected and subscribed to notifications")
            self._emit_status("connected")

        except Exception as exc:
            logger.exception("BLE connect failed")
            failed_client = self._client
            self._reset_connection_state(failed_client)
            await self._cleanup_client(failed_client)

            self._emit_status("error:connect_failed")
        finally:
            self._connecting = False

    async def _disconnect_async(self):
        """Stop notifications and disconnect."""
        client = self._client
        self._disconnecting = True
        try:
            await self._cleanup_client(client)
        except Exception:
            logger.exception("Error during disconnect")
        finally:
            self._disconnecting = False
            self._reset_connection_state(client)
            self._emit_status("disconnected")

    async def _send_config_async(self, payload: str) -> bool:
        """Write *payload* bytes to the characteristic and report success."""
        try:
            if self._client and self._client.is_connected:
                await self._client.write_gatt_char(
                    CHARACTERISTIC_UUID,
                    payload.encode("utf-8"),
                    response=True,
                )
                logger.info("Sent config: %s", payload)
                return True
        except Exception:
            logger.exception("Failed to send config")

        return False

    # ------------------------------------------------------------------
    # BLE callbacks
    # ------------------------------------------------------------------
    def _on_disconnect(self, client: "BleakClient"):
        """Called by bleak when the peripheral disconnects unexpectedly."""
        logger.warning("Device disconnected")
        was_disconnect_requested = self._disconnecting
        self._reset_connection_state(client)

        if not was_disconnect_requested:
            loop = self._loop
            if loop is not None and loop.is_running() and not loop.is_closed():
                task = loop.create_task(self._cleanup_client(client))
                self._track_cleanup_task(task)
            self._emit_status("disconnected")

    def _notification_handler(self, sender, data: bytearray):
        """Handle incoming BLE notifications.

        The ESP32 may fragment a single JSON payload across multiple
        BLE notifications.  We accumulate bytes in ``_rx_buffer`` and
        attempt to parse whenever a complete JSON object is detected.
        """
        try:
            chunk = data.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("Non-UTF8 BLE data received, ignoring")
            return

        self._rx_buffer += chunk

        # Try to extract one or more complete JSON objects
        while self._rx_buffer:
            stripped = self._rx_buffer.lstrip()
            if not stripped.startswith("{"):
                # Discard garbage before the first '{'
                idx = stripped.find("{")
                if idx == -1:
                    self._rx_buffer = ""
                    return
                stripped = stripped[idx:]
            self._rx_buffer = stripped

            try:
                parsed, end_idx = json.JSONDecoder().raw_decode(self._rx_buffer)
                # Consume the parsed portion
                self._rx_buffer = self._rx_buffer[end_idx:]
                self._process_esp_data(parsed)
            except json.JSONDecodeError:
                # Incomplete JSON – wait for more data
                break

    # ------------------------------------------------------------------
    # Data mapping
    # ------------------------------------------------------------------
    @staticmethod
    def _map_esp_to_app(esp: dict) -> dict:
        """Map ESP32 JSON to the app-internal sensor data format.

        ESP32 sends:
        {
          "dht": {"t": 25.5, "h": 60.0},
          "sensor7en1": {
            "temperatura": 22.1, "humedad": 45.0,
            "Ph": 6.5, "Ce": 120, "N": 80, "P": 30, "K": 200
          }
        }

        App expects:
        {
          "timestamp": "ISO-8601",
          "sensors_7in1": { ... },
          "am2315c": { ... }
        }
        """
        s7 = esp.get("sensor7en1", {})
        dht = esp.get("dht", {})

        return {
            "timestamp": datetime.now().astimezone().isoformat(),
            "sensors_7in1": {
                "temperature_soil": float(s7.get("temperatura", 0)),
                "humidity_soil": float(s7.get("humedad", 0)),
                "ph": float(s7.get("Ph", 0)),
                "nitrogen": float(s7.get("N", 0)),
                "phosphorus": float(s7.get("P", 0)),
                "potassium": float(s7.get("K", 0)),
                "ec": float(s7.get("Ce", 0)),
            },
            "am2315c": {
                "temperature_air": float(dht.get("t", 0)),
                "humidity_air": float(dht.get("h", 0)),
            },
        }

    def _process_esp_data(self, esp_json: dict):
        """Map and deliver a parsed ESP32 payload to the app."""
        try:
            mapped = self._map_esp_to_app(esp_json)
            logger.debug("Mapped sensor data: %s", mapped)
            if self.on_data:
                self.on_data(mapped)
        except Exception:
            logger.exception("Failed to map ESP32 data")
