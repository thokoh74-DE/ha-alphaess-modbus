# Changelog

### v1.15.5

#### Bug fix: dispatch reset now also sent on HA startup

**EN**

v1.15.3 added a reset on *shutdown* and *unload*, but missed the root cause: the inverter retains the last dispatch command in its own non-volatile memory across power cycles and HA restarts. If HA crashed (no clean shutdown), or if the startup reset was skipped for any reason, the inverter kept running the previous Force Export / Import / Charging command — visible as unexpected grid feed-in (e.g. 2 kW at night with no PV).

v1.15.5 adds an **unconditional dispatch reset immediately after the first successful Modbus connection on startup**, before any switch state is restored. This is a safe no-op when no dispatch was active on the inverter. The reset is sent regardless of whether `active_dispatch_key` was persisted, because the inverter's own memory is the authoritative source — not HA's storage.

**DE**

v1.15.3 hat den Reset beim *Herunterfahren* und *Entladen* ergänzt, aber die eigentliche Ursache nicht behoben: Der Wechselrichter speichert den letzten Dispatch-Befehl in seinem eigenen nichtflüchtigen Speicher über Neustarts hinweg. Bei einem HA-Absturz (kein sauberer Shutdown) lief der Wechselrichter daher weiter im letzten Dispatch-Modus — sichtbar als unerwartete Netzeinspeisung (z.B. 2 kW nachts ohne PV).

v1.15.5 sendet **unmittelbar nach dem ersten erfolgreichen Modbus-Verbindungsaufbau beim Start** einen unbedingten Dispatch-Reset, bevor Switch-Zustände wiederhergestellt werden. Das ist ein sicheres No-Op wenn kein Dispatch aktiv war. Der Reset wird unabhängig vom persistierten `active_dispatch_key` gesendet, da der Wechselrichter-Speicher die maßgebliche Quelle ist — nicht der HA-Storage.

#### Upgrading from v1.15.4

No entities are renamed, removed, or added. The only behaviour change is the unconditional dispatch reset on startup. After updating, restart Home Assistant.

---

### v1.15.3

#### What's new

- **Automatic dispatch reset on HA shutdown and integration unload.** When Home Assistant shuts down gracefully or the integration is reloaded (HACS update, config change, manual reload), any active Force Export / Force Import / Force Charging / Dispatch session is now automatically stopped and the inverter returns to self-consumption mode. Previously the inverter kept running the last dispatch command indefinitely until its own internal timer expired or a manual *Dispatch Reset* was triggered.

Two complementary hooks are registered in `__init__.py`:

| Hook | Fires when | Effect |
|------|-----------|--------|
| `EVENT_HOMEASSISTANT_STOP` listener | Graceful HA shutdown | Sends dispatch reset before the event loop closes |
| Reset in `async_unload_entry` | Integration reload / HACS update / config change | Sends dispatch reset before the Modbus connection is closed |

Both hooks are guarded by `coordinator.active_dispatch_key is not None` and are a no-op when no dispatch is active — no impact on normal polling cycles. The persisted dispatch key is also cleared so a subsequent restart does not attempt a *Sync Dispatch State* for a dispatch that was already stopped cleanly.

**DE:** Beim geordneten HA-Shutdown oder Integrations-Reload (HACS-Update, Konfigurationsänderung, manueller Reload) wird nun automatisch ein Dispatch-Reset gesendet, damit der Wechselrichter in den Normalbetrieb zurückkehrt. Beide Hooks prüfen `active_dispatch_key is not None` und sind bei inaktivem Dispatch ein No-Op ohne Einfluss auf normale Poll-Zyklen.

#### Upgrading from v1.15.2

No entities are renamed, removed, or added. The only behaviour change is the automatic dispatch reset on shutdown/reload. After updating, restart Home Assistant — a config entry reload is sufficient.

---

### v1.15.2

#### Bug fixes

- German (and any future) entity translations now actually take effect. Home Assistant's rule is: if an entity sets an explicit `_attr_name`, that string is used outright and `_attr_translation_key` is never consulted — translations only apply when no explicit name is set. Every entity class in this integration (sensors, switches, numbers, selects, buttons, binary sensors, time entities) was setting both, so `translations/de.json` had no effect on any of them, including the entities that already had a working-looking `translation_key` before this fork touched anything. The explicit `_attr_name` is now removed everywhere a `translation_key` is set; English remains available as the automatic fallback via `strings.json`/`translations/en.json`, so nothing changes for English-language profiles.

#### Upgrading from v1.15.1

- No entities are renamed, removed, or added, and no unique IDs or entity IDs change, so existing automations, scripts, and dashboards keep working unchanged — only the displayed friendly name updates. After updating: restart Home Assistant (a config entry reload is not enough, since the translation file itself doesn't change, only the Python code that gates whether it's used), and if names still look stale in the browser, do a hard refresh (Ctrl+F5 / Cmd+Shift+R) — the frontend caches each integration's translation strings client-side and a normal reload doesn't always invalidate that cache.

---

### v1.15.1

Brings this build up to date with upstream senalse/ha-alphaess-modbus v1.15.0-beta.3, on top of the Force Export PV-charging fix, the Sync Dispatch State persistence fix, and the six new sensors added in this fork's own v1.14.1/v1.15.0.

#### What's new (from upstream v1.15.0-beta.1)

- Connection settings (IP address, port, Slave ID) can now be changed without removing and re-adding the integration. A "Reconfigure" option appears in the three-dot menu on the AlphaESS card in Settings > Devices & Services.

#### What's new (German translation)

- Full German translation (`translations/de.json`) for every entity name across all platforms (sensor, switch, number, select, button, binary_sensor, time) -- 226 entity names plus the setup/reconfigure/options flow text. Home Assistant switches to it automatically when the user's profile language is set to German; English remains the fallback otherwise.
- Two thirds of the entities (all ~159 register sensors, the 6 calculated sensors, and the EMS Version sensor) previously had no `translation_key` at all -- only a hardcoded English `_attr_name` -- so no translation file could ever have changed their displayed name. They now also set `translation_key`, same as the entities that already supported localization (switches, numbers, selects, buttons, the daily/countdown sensors). The English name remains as the fallback for any other language. The 8 time entities (charging/discharging period start/stop) had the same gap and got the same fix.

#### Bug fixes (from upstream v1.15.0-beta.2/beta.3, adapted)

- Force Export no longer auto-stops a few seconds after a low-SoC condition clears just because the battery is sitting near 0 W. Upstream's own fix for this (removing the separate battery-activity watchdog, since "battery near 0 W" is also the normal, legitimate state once PV covers the export target) is exactly the situation this fork's PV-charging fix made more common, so it was merged here too: the SoC-cutoff check in the Force Export servo loop is now the only auto-stop path, and it only ever fires while actually discharging (word > 32000), same as before.
- Upstream's beta.2 fix had a side effect: it dropped the Force Export Hold gate on that SoC-cutoff check, so Hold stopped preventing the auto-off it was designed to prevent. beta.3's fix for that -- checking the Hold switch directly inside the SoC-cutoff check -- is merged here as well, combined with the discharge-only gating from this fork's PV-charging fix.

#### Upgrading from v1.15.0

- No entities are renamed, removed, or added beyond the six sensors already added in v1.15.0. The only behaviour changes are the new Reconfigure option, Force Export Hold working correctly again in the now-more-common "PV covers the export target, battery idle" case, and entity names displaying in German for users with German set as their Home Assistant profile language (no setting to enable -- it's automatic, and nothing changes for English-language profiles). Note that select dropdown option text (e.g. the Dispatch Mode choices) is not translated yet, only entity names; that would need a separate, more invasive change.

---

### v1.15.0

#### What's new

- Six new sensors, added for parity with the Hillview YAML package:
  - `pv_inverter_energy` (0x08D0) and `pv_system_total_energy` (0x08D2) — two previously unused lifetime PV energy registers. Their scale is assumed to be 0.1 by analogy with the integration's other uint32 energy totals; this isn't independently confirmed against AlphaESS documentation, so compare the readings to the AlphaESS app/portal's lifetime PV yield and adjust the `scale` in `const.py` if either is off by a factor of 10.
  - `total_house_load` — lifetime house-load energy, computed as grid import minus grid export minus battery charge plus battery discharge plus lifetime PV (mirrors Hillview's `AlphaESS_Total_House_Load`). Note this omits any AC-coupled PV-meter contribution, since this inverter family has no lifetime register for it; it's the best lifetime approximation the available registers allow.
  - `today_s_house_load` — the same formula as `total_house_load`, reset daily at midnight, with the AC-coupled PV meter's live power Riemann-integrated in on top (same mechanism already used for `today_pv_generation`), so unlike the lifetime figure this one is exact for AC-coupled PV too.
  - `excess_power` — PV output minus current house load, floored at 0 (mirrors `AlphaESS_Excess_Power`).
  - `battery_full` — boolean, true when the raw battery status register reads 1 (mirrors `AlphaESS_Battery_Full`).

#### Upgrading from v1.14.1

- No existing entities are renamed, removed, or changed. The six new sensors appear automatically after updating; no configuration is required. As with any new uint32 register, give Home Assistant a poll cycle (up to 60 s) before the two new PV energy sensors show a value.

---

### v1.14.1

#### Bug fixes

- Force Export no longer blocks PV from charging the battery. The battery setpoint was floored at 0 W, so whenever solar production exceeded house load plus the export target, the integration commanded "no power" instead of "charge with the surplus" — the battery stopped charging from PV entirely for as long as Force Export was active, even with headroom left. The setpoint can now go negative (charge) the same way Force Export's house-load/PV feed-forward and the grid-error servo already go positive (discharge). The discharge-stop SoC is also now only applied while actually discharging; while PV is recharging the battery during Force Export, a SoC at or below that threshold no longer turns Force Export off.
- Sync Dispatch State now correctly recognises Force Export after a Home Assistant restart even while it was charging the battery from PV surplus. It previously inferred the active switch purely from the sign of the live dispatch power (positive → Force Export, negative → Force Charging); since Force Export can now also write a negative/charging setpoint, that guess could misattribute a charging Force Export to Force Charging. The integration now also persists which switch was last active and prefers that record (when still consistent with the live power sign) over the sign-only guess.

#### Upgrading from v1.14.0

- No entities are renamed, removed, or added. Force Export behaves the same when discharging is needed; the only change is that PV surplus now reaches the battery instead of being held back while Force Export runs. The integration now also stores a small `.storage` file to remember which dispatch switch was last active across restarts, used only by Sync Dispatch State.

---

### v1.14.0

#### What's new

- Changing the power or cutoff SoC of a running force operation (Force Charging, Force Discharging, Force Export, Force Import) or the generic Dispatch now takes effect immediately without restarting the duration countdown. The original stop time is preserved; only changing the duration restarts the countdown. Previously any change to a running operation restarted the countdown, so it could run longer than intended unless you turned it off manually.

#### Bug fixes

- Force Export and Force Import now hold the grid at the target power steadily instead of oscillating. The power was being recalculated from a house-load figure that already included the battery's own output, which fed back on itself and could make the battery swing between roughly 1 kW and 4 kW every couple of seconds at a low export target. The control now adjusts the battery directly against the measured grid power, so export and import sit at the set target and recover smoothly after a sudden load change, with no grid import at low settings.

#### Upgrading from v1.13.1

- No entities are renamed, removed, or added, so dashboards and automations are unaffected. There are no new settings. Two behaviour changes: adjusting power or cutoff SoC while a force operation is running no longer extends the countdown (only changing the duration does), and Force Export and Force Import regulate more smoothly and accurately. If you have an automation that relied on the countdown restarting when the power changed, update the duration instead.

---

### v1.13.1

#### Bug fixes

- Home Assistant now recovers its Modbus connection to the inverter after a router restart. Previously a router reset could leave the connection stuck in a state that never recovered on its own, so sensors went unavailable and controls stopped working until Home Assistant or the integration was restarted. The integration now detects a dead or half-open connection, closes it, and reconnects cleanly on the next poll. This also makes recovery reliable when a force operation or automation is running at the time of the interruption.
- Force Export and Force Import now adjust the battery dispatch as soon as house load or solar changes, instead of waiting for a fixed 25-second cycle. At low export power settings a sudden load such as a kettle could previously pull power from the grid for up to 25 seconds before the next adjustment; it is now corrected within about a poll cycle (a couple of seconds), which matters for zero-import export tariffs.

#### Upgrading from v1.13.0

- No entities are renamed, removed, or added, so dashboards and automations are unaffected. There are no new settings. This release only improves connection recovery after a network interruption and how quickly Force Export and Force Import react to load and solar changes.

---

### v1.13.0

#### What's new

- Dispatch PV Enabled switch added. Controls the inverter's PV coupling during an active dispatch via register 0x088A, so PV can be enabled or disabled mid-dispatch (useful for shedding solar during negative-price periods). Defaults to on (PV enabled). Toggling it while a dispatch is running applies immediately; otherwise it takes effect on the next dispatch.
- All dispatch writes now include the flow-direction and PV-switch registers, extending the dispatch block from 9 to 11 registers (0x0880 to 0x088A). Confirmed on hardware: the PV switch only takes effect during an active dispatch, and the inverter restores PV to normal when the dispatch ends.

#### Bug fixes

- The Dispatch PV Enabled switch and the dispatch countdown now resolve correctly in the example dashboards; their entity IDs were wrong, which showed "Entity not found" on the Dispatch card.
- The write_register service no longer returns an error caused by internal data that is not a coordinator.
- The IP Method diagnostic sensor no longer errors when enabled. It reports a text value (DHCP or Static) but was classed as a numeric measurement, which Home Assistant rejects. It is disabled by default, so this only affected users who had enabled it.
- The Force Discharging Hold switch now has its own translation entry, matching the other Hold switches.
- Several integer diagnostic sensors (system time fields, Modbus baud rate, grid regulation) now display as whole numbers instead of decimals. All are disabled by default.

#### Upgrading from v1.12.0

- No entities are renamed or removed, so existing dashboards and automations are unaffected. The only new entity is the Dispatch PV Enabled switch, which defaults to on (PV stays enabled). Because the generic Dispatch now also sets the PV register, please report any unexpected PV behaviour during a dispatch.

---

### v1.12.0

#### What's new

- Six daily energy sensors added: Today's PV Generation, Today's Energy Feed to Grid, Today's Energy from Grid, Today's Battery Charged, Today's Battery Discharged, and Today's Battery Charged from Grid. Each resets at midnight using the inverter's lifetime cumulative totals as a baseline. State is preserved across HA restarts.

#### Bug fixes

- Today's PV Generation now includes energy from AC-coupled inverters. The hardware register only counts DC string PV; AC-coupled generation is now accumulated via a Riemann sum on the live AC PV meter reading and added to the daily total. The `ac_accumulated_kwh` attribute on the sensor shows the AC portion separately for verification.
- Daily energy sensor entity IDs corrected. The apostrophe in "Today's" caused HA to slugify names to `today_s_*` instead of `today_*`. Sensors now use translation keys so IDs are `today_energy_feed_to_grid`, `today_pv_generation`, etc. **Users upgrading from beta.1 should delete the old `today_s_*` entities from the entity registry after reloading the integration.**
- Force Charging, Discharging, Export, and Import countdown sensors now count down in real time. Previously they read a static hardware register that holds the initial duration and never decrements.
- Force Export and Force Import periodic power recalculation (every 25 s) no longer resets the countdown timer. The countdown now runs from the start of the session instead of restarting every 25 s.
- All countdown sensors now display in minutes by default instead of raw seconds. Existing entities may need the display unit changed in entity settings.

---

### v1.11.0

#### What's new

- Force Export Hold switch added. Enabling it before starting Force Export keeps the dynamic export running indefinitely after the duration expires.
- Force Discharging Hold switch added. Enabling it before starting Force Discharging keeps the session running for the full configured duration instead of stopping early when the SoC target is reached.
- Smart Export removed. It provided the same continuous dynamic export that Force Export Hold now covers. Users who relied on Smart Export should switch to Force Export with Force Export Hold enabled.
- Poll speed presets (Slow, Normal, Fast) added to integration options. Slow reduces the Modbus transaction rate for RS485-to-TCP adapter users prone to timeouts. Fast halves poll intervals and tightens the coordinator loop for faster SoC tracking and tighter dispatch control.
- Raw register write service (`alphaess_modbus.write_register`) added for advanced users. Writes any single register by address and integer value via Developer Tools or automations, with no scale or offset applied.
- B3 and B3PLUS model variant option added to integration options. Selecting B3/B3PLUS applies the correct scale factors for registers that differ from standard AlphaESS inverters.
- Per-mode dispatch countdown sensors added: Force Charging Countdown, Force Discharging Countdown, Force Export Countdown, and Force Import Countdown. Each shows remaining dispatch time only while its switch is active.

#### Bug fixes

- Force Export now dynamically calculates battery discharge power from live house load and PV production so the grid sees the configured feed-in rate. Previously it sent the target directly as battery discharge power, ignoring house load and PV entirely.
- Fast mode poll floor removed. The coordinator loop interval now tracks the Fast Mode Poll Interval directly, allowing sub-1 s polling for direct Modbus TCP connections. Previously the loop was hardcoded to 1 s in Fast mode.
- Excess Export power calculation corrected to charge the battery when PV production exceeds the Inverter AC Limit, instead of always writing zero power.
- Excess Export auto-pause now fires immediately on a work-mode fault instead of waiting up to 15 seconds.
- Excess Export now recalculates battery charge power on every coordinator update (every 2 s) and rewrites dispatch registers when power changes by 50 W or more, keeping pace with changing PV conditions.
- Excess Export dispatch registers could be re-written after the switch was turned off if a resume was in progress; an on-guard check now prevents this.
- All four Force modes (Charging, Discharging, Export, Import) now stop automatically when battery power stays within +/-50 W for 10 consecutive seconds, using the inverter's natural signal that it has reached its SoC target. Force Charging and Force Import previously had no early-stop watcher at all.
- Hold switches (Force Charging Hold, Force Export Hold, Force Import Hold, Force Discharging Hold) no longer keep the inverter in an indefinite hold loop after the duration expires. They now only gate the battery power watcher; the duration timer always stops the mode.
- Force Discharging and Force Export no longer schedule an orphan duration timer when SoC is already at or below the cutoff at startup. The orphan timer would call async_reset_dispatch hours later and could cancel an unrelated active dispatch.

### v1.10.0
- **feat:** Dispatch PV Switch sensor is now enabled by default.
- **feat:** Local IP, Subnet Mask, and Gateway sensors now display as dotted-decimal strings (e.g. `10.0.0.209`) instead of raw integers. IP Method shows `DHCP` or `Static`.
- **feat:** New Dispatch Time Remaining sensor (`sensor.alphaess_inverter_dispatch_countdown`) counts down from the configured dispatch duration in real time.
- **feat:** Battery Status sensor now shows a human-readable label alongside the raw value, e.g. "Charging + Discharging (257)" instead of just "257".
- **feat:** Dispatch Time sensor now shows a human-readable duration string (e.g. "3h 00m", "30m") instead of raw seconds with a thousands separator.
- **fix:** Local IP, Subnet Mask, and Gateway sensors were missing `state_class=None`, causing a `ValueError` on HA startup that prevented those entities from loading.
- **fix:** Battery Capacity scale corrected from 0.001 to 0.1 (reported values were 100x too small). Also fixes Battery Remaining Time which depends on the capacity value.
- **fix:** Battery Remaining Time always returned 0 on ALD-series inverters. Now calculated from live SoC, capacity, and battery power.
- **fix:** Excess Export Pause binary sensor was displaying "Pause" instead of "Excess Export Pause".
- **fix:** Force Import Pause binary sensor was displaying the full device-prefixed name instead of "Force Import Pause".

### v1.9.5
- **fix:** Battery Status sensor now displays as an integer instead of a float (e.g. `1` not `1.0`).
- **fix:** Force Import Hold switch now displays the correct icon (`mdi:battery-lock`); the previously assigned `mdi:transmission-tower-lock` does not exist in the MDI icon set bundled with Home Assistant.
- **fix:** BMS Version, LMU Version, and ISO Version sensors now have `state_class: None`, preventing a `ValueError` that crashed the coordinator update loop after every initial load in recent HA versions.
- **fix:** Register-backed number sliders (Charging/Discharging Cutoff SoC, Max Feed to Grid) now update immediately when written instead of reverting until the next poll cycle.
- **fix:** Force Discharging, Force Export, and Force Import duration sliders now correctly write the configured duration to the inverter (previously hardcoded to 60, 60, and 30 seconds respectively).
- **fix:** Dispatch Power slider now initialises to 0 kW on first install instead of the slider minimum (-20 kW).
- **fix:** Force Import Pause converted from a writable switch to a read-only binary sensor, consistent with Excess Export Pause.
- **fix:** Added `icons.json` so all entities correctly display their icons in Home Assistant 2024.6+.
- **fix:** Dispatch SoC and related dispatch-block sensors no longer show float artefacts (e.g. 99.96% instead of 100%).
- **fix:** SoC threshold sliders across all dispatch modes renamed from "Cutoff SoC" to "Stop at SoC" for consistency. Entity IDs are unchanged.
- **fix:** BMS Version, LMU Version, and ISO Version sensors now display in V1.65 format instead of the raw integer (165).
- **fix:** Four raw EMS version registers are now combined into a single EMS Version sensor (e.g. V1.0.23R1). The raw sub-registers are still polled but disabled by default.
- **fix:** Inverter model detection now uses a known-prefix lookup table (e.g. ALD -> Alphastore, SMILE-B3, SMILE-T10) before falling back to year-based regex parsing, giving more descriptive model names in the HA device card.

### v1.9.4
- **feat:** Excess Export now automatically pauses when the house load would cause grid import and resumes once PV production recovers. Excess Export Pause changed from a writable switch to a read-only binary sensor.

### v1.9.3
- **fix:** inverter model and serial number are now read from the device on startup and shown in the HA device card, replacing the hardcoded "SMILE-M5-S-INV / SMILE series" string.
- **fix:** integer sensor registers (dispatch mode, EMS version, fault/warning codes, period hours/minutes, etc.) no longer display with a spurious `.0` decimal suffix.
- **fix:** power sliders (force charge/discharge/export/import, dispatch power, max export power) now clamp to the configured Inverter AC Limit instead of always allowing up to 20 kW.

### v1.9.2
- **fix:** dev tools (`scan_registers.py`, `test_connection.py`) moved from the repo root to `tools/` so HACS does not surface them alongside the integration. `scan_registers.py` now builds its register label map from `SENSOR_REGISTERS` at runtime instead of a static dict, keeping it in sync automatically. `test_connection.py` now accepts `--host`, `--port`, and `--slave` arguments instead of hardcoded constants. A `tools/README.md` with usage examples is included.

### v1.9.1
- **fix:** removed unused `DEFAULT_SCAN_INTERVAL` and `MODBUS_HUB` constants from `const.py` (neither was imported anywhere).
- **fix:** `time.py` `async_set_value` now captures the current hour value before writing and rolls it back if the subsequent minute write raises an exception, so the inverter's schedule registers are never left in a half-updated state. A warning is logged when rollback fires.

### v1.9.0
- **feat:** reconnect storm protection - `modbus_client` now tracks consecutive connection failures and enforces a 10-second backoff after 3 in a row, so a TCP disconnect no longer fires dozens of blocking retry loops within one coordinator cycle. `connect()` is also guarded by a lock so concurrent callers coalesce into a single attempt.
- **feat:** coordinator aborts a cycle early (raising `UpdateFailed`) after more than 5 read errors, letting HA's built-in backoff handle the retry rather than grinding through all remaining registers on a dead connection.
- **feat:** number, select, and switch entities now expose an `available` property tied to `coordinator.last_update_success`, so all controls go unavailable during an outage instead of showing stale data (sensor entities already had this via `CoordinatorEntity`).

### v1.8.1
- **fix:** `coordinator.data` entries are now expired after 5x their `scan_interval` has elapsed without a successful read. Registers that start failing permanently (e.g. firmware change) will report `unknown` rather than keeping a stale value indefinitely.
- **fix:** removed `async_request_refresh()` from `async_write_dispatch`, `async_write_register`, and `async_write_registers`. These helpers were queuing a full coordinator poll after every write, causing extra round-trips and contention during active dispatch sequences. The 2-second poll loop delivers readback fast enough; `async_sync_datetime` retains its refresh so the UI updates immediately after a clock sync.
- **fix:** `async_sync_datetime` now writes all three time registers (0x0740-0x0742) in a single `write_registers` call instead of three sequential writes with 100 ms sleeps between them, eliminating the window where the inverter clock is only partially updated. BCD encoding (confirmed correct on this inverter) is unchanged.

### v1.8.0
- **feat:** batch contiguous Modbus register reads - adjacent registers (gap <= 4) are merged into a single `read_holding_registers` call per cycle, reducing typical transaction count from ~50 to ~10 per poll. Coordinator poll interval bumped from 1 s to 2 s; per-sensor `scan_interval` cadence is unchanged.
- **feat:** SOC watcher samples battery SoC every 2 s (down from 10 s) while a force-discharge, force-export, or SOC-watcher switch is active, tightening the cutoff margin for the zero-grid-draw invariant.
- **feat:** number and select sliders now source their displayed value from live coordinator data (the actual inverter register) rather than the last HA-saved state after a restart - so the UI immediately reflects changes made via the AlphaESS app or another client.
- **fix:** switch.py no longer looks up number/select values by hardcoded `hass.states.get("number.alphaess_inverter_*")` entity ID slugs. Values are now read from `coordinator.numbers` / `coordinator.selects`, which are seeded by the entities themselves on startup and kept current on every write. Dispatch mode and parameter sliders work correctly even if the device is renamed in HA.

### v1.7.4
- **fix:** 15 dispatch-parameter `ModbusNumberDef` entries (force-charging/discharging/export/import cutoff SoC, duration, and power; dispatch cutoff SoC, duration, and power) now have `address=None`. Previously they carried misleading register addresses that were never written directly, but could have caused silent state corruption if called via `async_write_register`.

### v1.7.3
- **fix:** track async tasks with `hass.async_create_task` so a reload mid-dispatch no longer leaks coroutines or logs "Task was destroyed but it is pending" errors
- **fix:** raise `ConfigEntryNotReady` on connection failure so HA retries automatically instead of marking the entry permanently failed
- **feat:** add hassfest and HACS validation CI (`.github/workflows/validate.yml`)

### v1.7.2
- **fix:** remove SOC calibration scheduling entities (SOC Calibration switch, SOC Calibration Enable switch, SOC Calibration Cycle Mode select, SOC Calibration Cycle Days number) - registers 0x1900-0x1903 return Illegal Data Address on current inverter firmware; the read-only Battery SOC Calibration status sensor at 0x012F remains. Use a Home Assistant automation to trigger a calibration cycle via the AlphaESS app or inverter web UI instead.

### v1.7.1
- **fix:** single-register writes (selects, numbers, buttons, time entities) were using Modbus FC16 (Write Multiple Registers) instead of FC6 (Write Single Register). Many AlphaESS inverters reject FC16 for individual registers with exception code 2 (Illegal Data Address). All single-register writes now correctly use FC6. Dispatch block writes (9 registers at 0x0880) remain on FC16.

### v1.7.0
- **feat:** 18 new entities - battery health (SoH, cell voltages, cell temps, relay status, module count, capacity), dispatch diagnostics (energy flow direction, freq dispatch flag and power/frequency setpoints), and SOC calibration scheduling (enable switch, trigger switch, cycle mode select, cycle days number)

### v1.6.5
- **feat:** Force Charging Hold and Force Import Hold switches - hold the inverter in force-charge or force-import mode indefinitely without a dispatch timeout

### v1.6.4
- **fix:** force discharge and force export now stop 1% above the SOC cutoff to guarantee zero grid draw on the GloBird ZeroHero plan (previously the inverter could briefly draw from grid as SoC hit the limit)

### v1.6.3
- **fix:** add SOC watcher to stop force discharging/export immediately when cutoff SoC is reached

### v1.6.2
- **fix:** use 60 s refresh loop for force discharging/export to guarantee dispatch reset on SOC cutoff

### v1.6.1
- **fix:** stop force discharge/charge/export immediately when SOC cutoff is reached

### v1.6.0
- **feat:** add Force Import switch, replace Smart Charge
