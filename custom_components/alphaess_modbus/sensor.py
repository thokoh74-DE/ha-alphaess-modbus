from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DAILY_ENERGY_SENSORS, DOMAIN, SENSOR_REGISTERS, ModbusSensorDef
from .coordinator import AlphaESSCoordinator


@dataclass
class CalculatedSensorDef:
    key: str
    name: str
    unit: str | None
    device_class: str | None
    state_class: str | None = "measurement"


CALCULATED_SENSORS: list[CalculatedSensorDef] = [
    CalculatedSensorDef("current_pv_production", "Current PV Production", "W", "power"),
    CalculatedSensorDef("current_house_load", "Current House Load", "W", "power"),
    CalculatedSensorDef("battery_remaining_time", "Battery Remaining Time", "min", "duration"),
    CalculatedSensorDef("excess_power", "Excess Power", "W", "power"),
    CalculatedSensorDef("battery_full", "Battery Full", None, None, state_class=None),
    CalculatedSensorDef("total_house_load", "Total House Load", "kWh", "energy", state_class="total"),
]


def _calc_total_house_load_kwh(d: dict) -> float | None:
    """Lifetime house-load energy (kWh), mirroring Hillview's AlphaESS_Total_House_Load:

        grid_import - grid_export - battery_charge + battery_discharge + lifetime_pv

    NOTE: this inverter family has no lifetime register for AC-coupled PV-meter energy
    (only a live power reading), so unlike Today's House Load -- which Riemann-integrates
    that live power and is therefore exact -- this lifetime figure omits the AC-meter PV
    contribution and will run slightly low for AC-coupled PV systems. It's the best
    available lifetime approximation with the registers this inverter exposes.
    """
    keys = [
        "total_energy_consumption_from_grid_meter",
        "total_energy_feed_to_grid_meter",
        "total_energy_charge_battery",
        "total_energy_discharge_battery",
        "total_energy_from_pv",
    ]
    if any(d.get(k) is None for k in keys):
        return None
    return (
        float(d["total_energy_consumption_from_grid_meter"])
        - float(d["total_energy_feed_to_grid_meter"])
        - float(d["total_energy_charge_battery"])
        + float(d["total_energy_discharge_battery"])
        + float(d["total_energy_from_pv"])
    )

_DEVICE_CLASS_MAP = {
    "battery": SensorDeviceClass.BATTERY,
    "current": SensorDeviceClass.CURRENT,
    "duration": getattr(SensorDeviceClass, "DURATION", None),
    "energy": SensorDeviceClass.ENERGY,
    "energy_storage": getattr(SensorDeviceClass, "ENERGY_STORAGE", None),
    "frequency": SensorDeviceClass.FREQUENCY,
    "power": SensorDeviceClass.POWER,
    "temperature": SensorDeviceClass.TEMPERATURE,
    "voltage": SensorDeviceClass.VOLTAGE,
}

_SENSOR_ENUM_LOOKUPS: dict[str, dict[int, str]] = {
    "dispatch_energy_flow_direction": {
        0: "Aging End",
        1: "PV to Grid",
        2: "PV to Battery",
        3: "Battery to Grid",
        4: "Grid to Battery",
        5: "Battery to Grid 2",
    },
    "ip_method": {0: "DHCP", 1: "Static"},
}

_STATE_CLASS_MAP = {
    "measurement": SensorStateClass.MEASUREMENT,
    "total": SensorStateClass.TOTAL,
    "total_increasing": SensorStateClass.TOTAL_INCREASING,
}


def _fmt_version(v: Any) -> str:
    try:
        n = int(v)
        return f"V{n // 100}.{n % 100:02d}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_ip(v: Any) -> str:
    try:
        n = int(v)
        return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"
    except (TypeError, ValueError):
        return str(v)


_BATTERY_STATUS_MAP: dict[int, str] = {
    0: "Idle",
    1: "Discharging",
    256: "Charging",
    257: "Charging + Discharging",
    512: "Charging (mode 2)",
    513: "Charging (mode 2) + Discharging",
}


def _fmt_battery_status(v: Any) -> str:
    try:
        n = int(v)
        label = _BATTERY_STATUS_MAP.get(n, "Unknown")
        return f"{label} ({n})"
    except (TypeError, ValueError):
        return str(v)


def _fmt_duration_s(v: Any) -> str:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return str(v)
    if n <= 0:
        return "0m"
    hours, remainder = divmod(n, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


_SENSOR_FORMATTERS: dict[str, Callable[[Any], Any]] = {
    "bms_version": _fmt_version,
    "lmu_version": _fmt_version,
    "iso_version": _fmt_version,
    "local_ip": _fmt_ip,
    "subnet_mask": _fmt_ip,
    "gateway": _fmt_ip,
    "battery_status": _fmt_battery_status,
    "dispatch_time": _fmt_duration_s,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AlphaESSCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        AlphaESSSensor(coordinator, entry, reg) for reg in SENSOR_REGISTERS
    ]
    entities += [
        AlphaESSCalculatedSensor(coordinator, entry, defn) for defn in CALCULATED_SENSORS
    ]
    entities.append(AlphaESSEmsVersionSensor(coordinator, entry))
    entities.append(AlphaESSDispatchCountdownSensor(coordinator, entry))
    entities += [
        AlphaESSModeCountdownSensor(coordinator, entry, switch_key, name, icon)
        for switch_key, name, icon in [
            ("force_charging",    "Force Charging Countdown",    "mdi:battery-charging"),
            ("force_discharging", "Force Discharging Countdown", "mdi:battery-arrow-down"),
            ("force_export",      "Force Export Countdown",      "mdi:transmission-tower-export"),
            ("force_import",      "Force Import Countdown",      "mdi:transmission-tower-import"),
        ]
    ]
    entities += [
        AlphaESSDailySensor(coordinator, entry, key, source_key, ac_power_key)
        for key, source_key, ac_power_key in DAILY_ENERGY_SENSORS
    ]
    entities.append(
        AlphaESSDailySensor(
            coordinator, entry, "today_s_house_load",
            value_fn=_calc_total_house_load_kwh,
            ac_power_key="active_power_pv_meter",
        )
    )
    async_add_entities(entities)


class AlphaESSSensor(CoordinatorEntity[AlphaESSCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AlphaESSCoordinator,
        entry: ConfigEntry,
        reg: ModbusSensorDef,
    ) -> None:
        super().__init__(coordinator)
        self._reg = reg
        self._attr_unique_id = f"{entry.entry_id}_{reg.key}"
        self._attr_translation_key = reg.key
        self._attr_native_unit_of_measurement = reg.unit
        self._attr_device_class = _DEVICE_CLASS_MAP.get(reg.device_class or "")
        self._attr_state_class = _STATE_CLASS_MAP.get(reg.state_class or "")
        self._attr_entity_registry_enabled_default = reg.enabled_by_default
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get(self._reg.key)
        lookup = _SENSOR_ENUM_LOOKUPS.get(self._reg.key)
        if lookup is not None and raw is not None:
            return lookup.get(int(raw), str(raw))
        formatter = _SENSOR_FORMATTERS.get(self._reg.key)
        if formatter is not None and raw is not None:
            return formatter(raw)
        return raw


class AlphaESSCalculatedSensor(CoordinatorEntity[AlphaESSCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AlphaESSCoordinator,
        entry: ConfigEntry,
        defn: CalculatedSensorDef,
    ) -> None:
        super().__init__(coordinator)
        self._defn = defn
        self._attr_unique_id = f"{entry.entry_id}_{defn.key}"
        self._attr_translation_key = defn.key
        self._attr_native_unit_of_measurement = defn.unit
        self._attr_device_class = _DEVICE_CLASS_MAP.get(defn.device_class)
        self._attr_state_class = _STATE_CLASS_MAP.get(defn.state_class or "")
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    def _pv_production(self, d: dict) -> int | None:
        keys = ["pv1_power", "pv2_power", "pv3_power", "pv4_power", "active_power_pv_meter"]
        if any(d.get(k) is None for k in keys):
            return None
        return max(0, sum(int(d[k]) for k in keys))

    def _house_load(self, d: dict) -> int | None:
        grid = d.get("power_grid")
        if grid is None:
            return None
        if float(d.get("inverter_work_mode", 0)) == 2:
            return round(float(grid))
        pv = self._pv_production(d)
        battery = d.get("power_battery")
        if pv is None or battery is None:
            return None
        return max(0, int(pv) + int(battery) + int(grid))

    @property
    def native_value(self):
        d = self.coordinator.data
        if not d:
            return None

        if self._defn.key == "current_pv_production":
            return self._pv_production(d)

        if self._defn.key == "current_house_load":
            return self._house_load(d)

        if self._defn.key == "excess_power":
            pv = self._pv_production(d)
            house_load = self._house_load(d)
            if pv is None or house_load is None:
                return None
            return max(0, int(pv) - int(house_load))

        if self._defn.key == "battery_full":
            raw = d.get("battery_status")
            if raw is None:
                return None
            return int(raw) == 1

        if self._defn.key == "total_house_load":
            value = _calc_total_house_load_kwh(d)
            return round(value, 2) if value is not None else None

        if self._defn.key == "battery_remaining_time":
            raw = d.get("battery_remaining_time_raw")
            if raw is not None and int(raw) != 0:
                return int(raw)
            soc = d.get("soc_battery")
            capacity = d.get("battery_capacity_kwh")
            power_w = d.get("power_battery")
            if soc is None or capacity is None or power_w is None:
                return None
            soc = float(soc)
            capacity = float(capacity)
            power_w = float(power_w)
            if capacity <= 0 or abs(power_w) < 50:
                return None
            remaining_kwh = (soc / 100.0 * capacity) if power_w < 0 else ((100.0 - soc) / 100.0 * capacity)
            return max(0, int(remaining_kwh / abs(power_w) * 1000.0 * 60.0))

        return None


class AlphaESSCombinedSensor(CoordinatorEntity[AlphaESSCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AlphaESSCoordinator,
        entry: ConfigEntry,
        keys: list[str],
        name: str,
        unique_id_suffix: str,
        icon: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._keys = keys
        self._attr_translation_key = unique_id_suffix
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        parts = [self.coordinator.data.get(k) for k in self._keys]
        if any(p is None for p in parts):
            return None
        return self._format(*parts)

    def _format(self, *parts: Any) -> str:
        raise NotImplementedError


class AlphaESSEmsVersionSensor(AlphaESSCombinedSensor):
    def __init__(self, coordinator: AlphaESSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator, entry,
            keys=["ems_version_high", "ems_version_middle", "ems_version_low", "ems_version_low_suffix"],
            name="EMS Version",
            unique_id_suffix="ems_version",
            icon="mdi:chip",
        )

    def _format(self, high: Any, middle: Any, low: Any, suffix: Any) -> str:
        return f"V{int(high)}.{int(middle)}.{int(low)}{suffix or ''}"


class AlphaESSDispatchCountdownSensor(CoordinatorEntity[AlphaESSCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "dispatch_countdown"

    def __init__(self, coordinator: AlphaESSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_dispatch_countdown"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._unsub: Callable | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsub = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=1)
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def _tick(self, _now: datetime) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int | None:
        started = self.coordinator.dispatch_started_at
        dur = self.coordinator.dispatch_duration_s
        if started is None or dur <= 0:
            return None
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        remaining = max(0, int(dur - elapsed))
        return remaining


class AlphaESSModeCountdownSensor(CoordinatorEntity[AlphaESSCoordinator], SensorEntity):
    """Countdown sensor for a specific dispatch mode (force charging/discharging/export/import)."""
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: AlphaESSCoordinator,
        entry: ConfigEntry,
        switch_key: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._switch_key = switch_key
        self._attr_unique_id = f"{entry.entry_id}_{switch_key}_countdown"
        self._attr_translation_key = f"{switch_key}_countdown"
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._unsub: Callable | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsub = async_track_time_interval(self.hass, self._tick, timedelta(seconds=1))

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def _tick(self, _now: datetime) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int | None:
        if self.coordinator.active_dispatch_key != self._switch_key:
            return None
        started = self.coordinator.dispatch_started_at
        dur = self.coordinator.dispatch_duration_s
        if started is None or dur <= 0:
            return None
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        return max(0, int(dur - elapsed))


class AlphaESSDailySensor(CoordinatorEntity[AlphaESSCoordinator], RestoreSensor):
    """Daily energy sensor that resets at midnight using lifetime totals as a baseline.

    When ac_power_key is set, also integrates that live power register via Riemann
    sum and adds the result to the DC register delta. This handles AC-coupled PV
    inverters, which have no hardware energy counter in the AlphaESS register set.
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: AlphaESSCoordinator,
        entry: ConfigEntry,
        key: str,
        source_key: str | None = None,
        ac_power_key: str | None = None,
        value_fn: Callable[[dict], float | None] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._source_key = source_key
        self._value_fn = value_fn
        self._ac_power_key = ac_power_key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._day_start_value: float | None = None
        self._start_date: date | None = None
        self._unsub_midnight: Callable | None = None
        self._ac_accumulated_kwh: float = 0.0
        self._last_ac_time: float | None = None

    def _dc_value(self, d: dict) -> float | None:
        """Current value of this sensor's source: either a raw register (source_key)
        or a composite quantity supplied by value_fn (e.g. Today's House Load, which
        is derived from several registers rather than a single one)."""
        if self._value_fn is not None:
            return self._value_fn(d)
        if self._source_key is None:
            return None
        v = d.get(self._source_key)
        return float(v) if v is not None else None

    def _handle_coordinator_update(self) -> None:
        if self._ac_power_key:
            d = self.coordinator.data or {}
            power_w = d.get(self._ac_power_key)
            now = time.monotonic()
            if power_w is not None and self._last_ac_time is not None:
                elapsed_s = min(now - self._last_ac_time, 60.0)
                self._ac_accumulated_kwh += max(0.0, float(power_w)) * elapsed_s / 3_600_000.0
            self._last_ac_time = now
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        today = date.today()
        last_state = await self.async_get_last_state()
        restored = False
        if last_state and last_state.attributes:
            saved_date_str = last_state.attributes.get("start_date")
            saved_value = last_state.attributes.get("day_start_value")
            if saved_date_str and saved_value is not None:
                try:
                    saved_date = date.fromisoformat(str(saved_date_str))
                    if saved_date == today:
                        self._day_start_value = float(saved_value)
                        self._start_date = saved_date
                        restored = True
                except (ValueError, TypeError):
                    pass

        if not restored:
            current = self._dc_value(self.coordinator.data or {})
            if current is not None:
                self._day_start_value = float(current)
                self._start_date = today

        self._attr_last_reset = dt_util.start_of_local_day()

        if restored and self._ac_power_key and last_state and last_state.attributes:
            saved_ac = last_state.attributes.get("ac_accumulated_kwh")
            if saved_ac is not None:
                try:
                    self._ac_accumulated_kwh = float(saved_ac)
                except (ValueError, TypeError):
                    pass

        self._unsub_midnight = async_track_time_change(
            self.hass, self._reset_day, hour=0, minute=0, second=0
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_midnight:
            self._unsub_midnight()
            self._unsub_midnight = None

    async def _reset_day(self, _now: datetime) -> None:
        current = self._dc_value(self.coordinator.data or {})
        if current is not None:
            self._day_start_value = float(current)
            self._start_date = date.today()
        self._ac_accumulated_kwh = 0.0
        self._last_ac_time = None
        self._attr_last_reset = dt_util.start_of_local_day()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        if self._day_start_value is None:
            return None
        current = self._dc_value(self.coordinator.data or {})
        if current is None:
            return None
        dc_kwh = max(0.0, float(current) - self._day_start_value)
        return round(dc_kwh + self._ac_accumulated_kwh, 2)

    @property
    def extra_state_attributes(self) -> dict:
        if self._day_start_value is None:
            return {}
        attrs: dict = {
            "day_start_value": self._day_start_value,
            "start_date": self._start_date.isoformat() if self._start_date else None,
        }
        if self._ac_power_key:
            attrs["ac_accumulated_kwh"] = round(self._ac_accumulated_kwh, 4)
        return attrs
