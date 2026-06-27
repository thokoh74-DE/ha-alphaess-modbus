from __future__ import annotations

import logging
import re

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import EVENT_HOMEASSISTANT_STOP, HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .config_flow import CONF_SLAVE_ID
from .const import DOMAIN, PLATFORMS
from .coordinator import AlphaESSCoordinator
from .modbus_client import AlphaESSModbusClient

_LOGGER = logging.getLogger(__name__)

SERVICE_WRITE_REGISTER = "write_register"
SERVICE_WRITE_REGISTER_SCHEMA = vol.Schema({
    vol.Required("address"): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
    vol.Required("value"): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
})

_MODEL_PREFIXES: dict[str, str] = {
    "SMILE-T10": "SMILE-T10",
    "SMILE-M5": "SMILE-M5",
    "SMILE-B3": "SMILE-B3",
    "SMILE-S5": "SMILE-S5",
    "SMILE5": "SMILE5",
    "STORION": "STORION",
    "ALD": "Alphastore",
}


def _detect_model(raw_sn: str) -> str:
    if not raw_sn:
        return "SMILE series"
    sn_upper = raw_sn.upper()
    for prefix in sorted(_MODEL_PREFIXES, key=len, reverse=True):
        if sn_upper.startswith(prefix):
            return _MODEL_PREFIXES[prefix]
    _match = re.match(r"^(.+?)(?:20\d{2}|19\d{2})", raw_sn)
    if _match:
        return _match.group(1).rstrip("-_ ").strip() or "SMILE series"
    return raw_sn[:20].strip() or "SMILE series"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.exceptions import ConfigEntryNotReady

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    client = AlphaESSModbusClient(
        host=host,
        port=port,
        slave_id=entry.data[CONF_SLAVE_ID],
    )
    try:
        await client.connect()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect to {host}:{port}: {err}") from err
    if not client.connected:
        raise ConfigEntryNotReady(f"Cannot connect to {host}:{port}")

    coordinator = AlphaESSCoordinator(hass, entry, client)
    await coordinator.async_load_restored_dispatch_key()
    await coordinator.async_config_entry_first_refresh()

    # ── Startup reset ────────────────────────────────────────────────────────
    # Always send a dispatch-reset immediately after the first successful
    # connection.  The inverter retains the last dispatch command in its own
    # memory across power cycles and HA restarts, so without this reset it
    # will keep running (e.g. Force Export at 2 kW) even though HA has no
    # active dispatch.  We send the reset unconditionally here — it is a
    # safe no-op when no dispatch was active — and then clear the persisted
    # dispatch key so switch states start clean.
    try:
        await coordinator.async_reset_dispatch()
        await coordinator.async_set_active_dispatch_key(None)
        _LOGGER.info(
            "AlphaESS Modbus: dispatch reset sent on startup (inverter returned to self-consumption)"
        )
    except Exception:
        _LOGGER.warning(
            "AlphaESS Modbus: could not send dispatch reset on startup",
            exc_info=True,
        )
    # ─────────────────────────────────────────────────────────────────────────

    raw_sn = (coordinator.data.get("inverter_sn") or "").strip().rstrip("\x00").strip()
    _model = _detect_model(raw_sn)
    _serial = raw_sn or None

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    async def _async_reset_on_stop(event: object) -> None:
        """Send a dispatch-reset to the inverter when HA shuts down.

        This ensures no active Force Export / Import / Charging dispatch is left
        running on the inverter after HA goes offline.  The handler is registered
        early so it fires even if the config entry is never unloaded (e.g. a
        hard shutdown where async_unload_entry is not awaited).
        """
        if coordinator.active_dispatch_key is not None:
            try:
                await coordinator.async_reset_dispatch()
                await coordinator.async_set_active_dispatch_key(None)
                _LOGGER.info(
                    "AlphaESS Modbus: dispatch reset sent on HA shutdown"
                )
            except Exception:
                _LOGGER.warning(
                    "AlphaESS Modbus: could not reset dispatch on HA shutdown",
                    exc_info=True,
                )

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_reset_on_stop)
    )

    if not hass.services.has_service(DOMAIN, SERVICE_WRITE_REGISTER):
        async def _handle_write_register(call: ServiceCall) -> None:
            address: int = call.data["address"]
            value: int = call.data["value"]
            # hass.data[DOMAIN] also holds non-coordinator entries (e.g. the
            # per-entry switches map), so only call coordinators.
            for obj in hass.data[DOMAIN].values():
                if isinstance(obj, AlphaESSCoordinator):
                    await obj.async_write_raw(address, value)

        hass.services.async_register(
            DOMAIN,
            SERVICE_WRITE_REGISTER,
            _handle_write_register,
            schema=SERVICE_WRITE_REGISTER_SCHEMA,
        )

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="AlphaESS Inverter",
        manufacturer="AlphaESS",
        model=_model,
        serial_number=_serial,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: AlphaESSCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_switches", None)
        # Reset any active dispatch before closing the Modbus connection so the
        # inverter does not keep running a force-export/import/charging command
        # after HA goes offline or the integration is reloaded.
        if coordinator.active_dispatch_key is not None:
            try:
                await coordinator.async_reset_dispatch()
                await coordinator.async_set_active_dispatch_key(None)
                _LOGGER.info(
                    "AlphaESS Modbus: dispatch reset sent on entry unload"
                )
            except Exception:
                _LOGGER.warning(
                    "AlphaESS Modbus: could not reset dispatch on unload",
                    exc_info=True,
                )
        await coordinator.client.close()
        if not any(isinstance(o, AlphaESSCoordinator) for o in hass.data[DOMAIN].values()):
            hass.services.async_remove(DOMAIN, SERVICE_WRITE_REGISTER)
    return unloaded
