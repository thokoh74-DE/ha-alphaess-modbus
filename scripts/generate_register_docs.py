#!/usr/bin/env python3
"""Regenerate docs/register_map.md from const.py register definitions.

Run from the repository root:
    python scripts/generate_register_docs.py
"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
# Import const directly to avoid __init__.py pulling in homeassistant dependencies.
sys.path.insert(0, str(ROOT / "custom_components" / "alphaess_modbus"))
import const  # noqa: E402

SENSOR_REGISTERS = const.SENSOR_REGISTERS
NUMBER_REGISTERS = const.NUMBER_REGISTERS
SELECT_REGISTERS = const.SELECT_REGISTERS
TIME_REGISTERS = const.TIME_REGISTERS
SWITCH_DESCRIPTIONS = const.SWITCH_DESCRIPTIONS
BUTTON_DESCRIPTIONS = const.BUTTON_DESCRIPTIONS

OUTPUT = ROOT / "docs" / "register_map.md"


def fmt_addr(addr: int | None) -> str:
    return f"0x{addr:04X}" if addr is not None else "N/A"


def fmt_scale(scale: float, offset: float) -> str:
    parts = []
    if offset != 0.0:
        parts.append(f"offset {offset:+g}")
    if scale != 1.0:
        parts.append(f"x{scale}")
    return ", ".join(parts) if parts else "-"


lines: list[str] = []

lines += [
    "# AlphaESS Modbus Register Map",
    "",
    "This document is auto-generated from "
    "`custom_components/alphaess_modbus/const.py`. "
    "Run `python scripts/generate_register_docs.py` from the repo root to regenerate it "
    "after modifying any register definitions.",
    "",
    "Entity IDs follow the pattern `<platform>.alphaess_<device_name>_<key>` "
    "where `<device_name>` is derived from the name you gave the device during setup "
    "(e.g. `sensor.alphaess_inverter_soc_battery`).",
    "",
    "---",
    "",
    "## Contents",
    "",
    "- [Sensor Registers](#sensor-registers-read-only)",
    "- [Writable Number Entities](#writable-number-entities)",
    "- [Writable Select Entities](#writable-select-entities)",
    "- [Writable Time Entities](#writable-time-entities)",
    "- [Switch Entities](#switch-entities)",
    "- [Button Entities](#button-entities)",
    "- [Dispatch Register Block](#dispatch-register-block)",
    "",
    "---",
    "",
]

# ---------------------------------------------------------------------------
# Sensor registers grouped by the `group` field
# ---------------------------------------------------------------------------
lines += [
    "## Sensor Registers (read-only)",
    "",
    "Sensors are polled at the interval shown. "
    "Entries marked **off** in the Default column are disabled in HA until manually enabled.",
    "",
]

groups: dict[str, list] = defaultdict(list)
for reg in SENSOR_REGISTERS:
    groups[reg.group or "Other"].append(reg)

for group_name, regs in groups.items():
    lines.append(f"### {group_name}")
    lines.append("")
    lines.append("| Address | Key | Name | Description | Unit | Type | Scale/Offset | Poll | Default |")
    lines.append("|---------|-----|------|-------------|------|------|--------------|------|---------|")
    for r in regs:
        scale_str = fmt_scale(r.scale, r.offset)
        default = "on" if r.enabled_by_default else "off"
        desc = r.description or ""
        lines.append(
            f"| {fmt_addr(r.address)} | `{r.key}` | {r.name} | {desc} "
            f"| {r.unit or '-'} | {r.data_type} | {scale_str} | {r.scan_interval} s | {default} |"
        )
    lines.append("")

lines.append("---")
lines.append("")

# ---------------------------------------------------------------------------
# Number registers
# ---------------------------------------------------------------------------
lines += [
    "## Writable Number Entities",
    "",
    "Numbers with an address write directly to a Modbus register when changed. "
    "Numbers with address **N/A** are dispatch parameters -- they are held in memory "
    "and assembled into the 11-register dispatch sequence when a switch is turned on.",
    "",
    "| Address | Key | Name | Description | Unit | Range | Step |",
    "|---------|-----|------|-------------|------|-------|------|",
]
for r in NUMBER_REGISTERS:
    range_str = f"{r.min_value} - {r.max_value}"
    desc = r.description or ""
    lines.append(
        f"| {fmt_addr(r.address)} | `{r.key}` | {r.name} | {desc} "
        f"| {r.unit or '-'} | {range_str} | {r.step} |"
    )
lines += ["", "---", ""]

# ---------------------------------------------------------------------------
# Select registers
# ---------------------------------------------------------------------------
lines += [
    "## Writable Select Entities",
    "",
    "| Address | Key | Name | Description | Options |",
    "|---------|-----|------|-------------|---------|",
]
for r in SELECT_REGISTERS:
    opts = " / ".join(r.options)
    desc = r.description or ""
    lines.append(
        f"| {fmt_addr(r.address)} | `{r.key}` | {r.name} | {desc} | {opts} |"
    )
lines += ["", "---", ""]

# ---------------------------------------------------------------------------
# Time registers
# ---------------------------------------------------------------------------
lines += [
    "## Writable Time Entities",
    "",
    "Each time entity writes to two separate registers (hour and minute) when the time is set in HA.",
    "",
    "| Hour Addr | Minute Addr | Key | Name | Description |",
    "|-----------|-------------|-----|------|-------------|",
]
for r in TIME_REGISTERS:
    desc = r.description or ""
    lines.append(
        f"| {fmt_addr(r.hour_address)} | {fmt_addr(r.minute_address)} "
        f"| `{r.key}` | {r.name} | {desc} |"
    )
lines += ["", "---", ""]

# ---------------------------------------------------------------------------
# Switch entities
# ---------------------------------------------------------------------------
lines += [
    "## Switch Entities",
    "",
    "The six dispatch switches (Force Charging, Force Discharging, Force Export, "
    "Force Import, Dispatch, Excess Export) are mutually exclusive -- turning one on "
    "turns all others off. The four Hold switches are independent gating controls.",
    "",
    "| Key | Name | Description |",
    "|-----|------|-------------|",
]
for key, (name, desc) in SWITCH_DESCRIPTIONS.items():
    lines.append(f"| `{key}` | {name} | {desc} |")
lines += ["", "---", ""]

# ---------------------------------------------------------------------------
# Button entities
# ---------------------------------------------------------------------------
lines += [
    "## Button Entities",
    "",
    "| Key | Name | Description |",
    "|-----|------|-------------|",
]
for key, (name, desc) in BUTTON_DESCRIPTIONS.items():
    lines.append(f"| `{key}` | {name} | {desc} |")
lines += ["", "---", ""]

# ---------------------------------------------------------------------------
# Dispatch register block reference
# ---------------------------------------------------------------------------
lines += [
    "## Dispatch Register Block",
    "",
    "The dispatch switches write 11 consecutive registers starting at **0x0880**. "
    "The active-power field uses a 32000-bias encoding: "
    "values below 32000 are charge (battery draw from grid/PV), "
    "values above 32000 are discharge (battery output to loads/grid).",
    "",
    "| Offset | Address | Field | Encoding |",
    "|--------|---------|-------|----------|",
    "| 0 | 0x0880 | Start | 1 = start, 0 = stop |",
    "| 1 | 0x0881 | Active Power HI | Always 0 (32-bit big-endian split) |",
    "| 2 | 0x0882 | Active Power LO | 32000 - W = charge; 32000 + W = discharge |",
    "| 3 | 0x0883 | Reactive Power HI | Always 0 |",
    "| 4 | 0x0884 | Reactive Power LO | 32000 (neutral) |",
    "| 5 | 0x0885 | Mode | 2 = SoC Control, 3 = Load Following, etc. |",
    "| 6 | 0x0886 | SoC | soc_percent / 0.392 (integer) |",
    "| 7 | 0x0887 | Time HI | Always 0 |",
    "| 8 | 0x0888 | Time LO | Duration in seconds |",
    "| 9 | 0x0889 | Flow Direction | Always 255 |",
    "| 10 | 0x088A | PV Switch | 1 = PV on, 2 = PV off, 0 = leave unchanged |",
    "",
]

OUTPUT.write_text("\n".join(lines), encoding="utf-8")
print(f"Written {OUTPUT}")
