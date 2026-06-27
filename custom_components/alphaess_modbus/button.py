from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, RESET_MODE_ADDR
from .coordinator import AlphaESSCoordinator

_LOGGER = logging.getLogger(__name__)

BUTTON_DEFS = [
    {
        "key": "dispatch_reset",
        "name": "Dispatch Reset",
        "icon": "mdi:restart",
    },
    {
        "key": "synchronise_date_time",
        "name": "Synchronise Date & Time",
        "icon": "mdi:clock-check-outline",
    },
    {
        "key": "sync_dispatch_state",
        "name": "Sync Dispatch State",
        "icon": "mdi:sync",
    },
    {
        "key": "restart_pcs",
        "name": "Restart PCS",
        "icon": "mdi:restart",
    },
    {
        "key": "restart_ems",
        "name": "Restart EMS",
        "icon": "mdi:restart",
    },
    {
        "key": "reset_energy_totals",
        "name": "Reset Energy Totals",
        "icon": "mdi:counter",
    },
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AlphaESSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AlphaESSButton(coordinator, entry, d) for d in BUTTON_DEFS
    )


class AlphaESSButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AlphaESSCoordinator,
        entry: ConfigEntry,
        definition: dict,
    ) -> None:
        self._coordinator = coordinator
        self._entry_id = entry.entry_id
        self._key = definition["key"]
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_translation_key = self._key
        self._attr_icon = definition["icon"]
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_press(self, **kwargs: Any) -> None:
        if self._key == "dispatch_reset":
            await self._coordinator.async_reset_dispatch()
        elif self._key == "synchronise_date_time":
            await self._coordinator.async_sync_datetime()
        elif self._key == "sync_dispatch_state":
            await self._sync_dispatch_state()
        elif self._key == "restart_pcs":
            await self._coordinator.async_write_register(RESET_MODE_ADDR, 7)
        elif self._key == "restart_ems":
            await self._coordinator.async_write_register(RESET_MODE_ADDR, 8)
        elif self._key == "reset_energy_totals":
            await self._coordinator.async_write_register(RESET_MODE_ADDR, 1)

    async def _sync_dispatch_state(self) -> None:
        from .switch import _MUTEX_SWITCHES

        switches = self.hass.data[DOMAIN].get(f"{self._entry_id}_switches", {})
        dispatch_on = bool(
            self._coordinator.data
            and self._coordinator.data.get("dispatch_start") == 1
        )
        any_on = any(sw.is_on for key, sw in switches.items() if key in _MUTEX_SWITCHES)

        if dispatch_on and not any_on:
            power = (self._coordinator.data or {}).get("dispatch_active_power", 0)
            inferred_key = self._infer_active_dispatch_key(power)
            sw = switches.get(inferred_key)
            if sw:
                await sw.async_force_on()
                _LOGGER.info("sync_dispatch_state: dispatch active (power=%s W), marked %s on", power, inferred_key)
        elif not dispatch_on:
            # Inverter dispatch is off — clear any switches still showing on in HA
            cleared = []
            for key, sw in switches.items():
                if sw.is_on:
                    await sw.async_force_off()
                    cleared.append(key)
            if cleared:
                _LOGGER.info("sync_dispatch_state: cleared stale on-state for %s", cleared)

    def _infer_active_dispatch_key(self, power: float) -> str:
        """Best-effort guess at which switch is behind a live dispatch found after restart.

        Power sign alone used to be enough (Force Export always discharged: power > 0;
        Force Charging always charged: power < 0). That's no longer true: Force Export
        now also writes a negative/charging setpoint while PV surplus is recharging the
        battery, so a negative reading after a restart could be either switch.

        Preferred signal: the dispatch key persisted whenever a switch last turned on
        or off (coordinator.restored_dispatch_key), as long as it's still consistent
        with the live power sign — i.e. it wasn't superseded by some other write since
        the restart. Falling back to the old sign-only guess only when there's no
        persisted key (fresh install / cleared storage) or it contradicts the sign.
        """
        restored = self._coordinator.restored_dispatch_key
        # Switches whose dispatch word can legitimately be <= 32000 (charge/neutral).
        consistent_when_charging = {"force_charging", "force_export", "force_import", "excess_export"}
        # Switches whose dispatch word can legitimately be >= 32000 (discharge/neutral).
        consistent_when_discharging = {"force_discharging", "force_export"}
        if restored == "dispatch":
            return "dispatch"
        if restored in consistent_when_discharging and power > 0:
            return restored
        if restored in consistent_when_charging and power <= 0:
            return restored
        # No usable persisted key — fall back to the old two-way guess. This only
        # covers force_export/force_charging/dispatch, same as before; it cannot
        # tell force_discharging, force_import or excess_export apart from sign
        # alone, same limitation as before this fix.
        if power > 0:
            return "force_export"
        if power < 0:
            return "force_charging"
        return "dispatch"
