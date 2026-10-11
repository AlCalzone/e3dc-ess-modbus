# e3dc-ess-modbus

Read and control E3/DC home power stations over Modbus TCP.

## Installation

```bash
pip install e3dc-ess-modbus "modbus-connection[tmodbus]"
```

It needs Python 3.12 or later and [modbus-connection](https://github.com/home-assistant-libs/modbus-connection) 4.12.4 or later. The examples use its tmodbus backend, which `modbus-connection[tmodbus]` installs.

## Device setup

- **Protocol:** turn Modbus on under **Smart Functions** > **Smart Home** > **Modbus**, and set **Protocol** to **E3DC**. SunSpec mode is not supported.
- **Connection:** Modbus TCP, port 502 by default. The port is set in the same menu.
- **Unit ID:** 1.
- **Firmware:** grid control needs release 2025_06 or later, battery control 2025_40, the inverter operating mode 2025_43, and battery limits, stored energy and the battery power percentage 2026_04.
- **Supported devices:** E3/DC home power stations such as the S10 E, S10 E PRO, S10 X and S20 X PRO, and systems on the Q10 and P10 firmware lines.
- **Network:** the power station answers only clients in its own subnet.

## Usage

The library builds on modbus-connection. You open the connection and pass the library a `ModbusUnit`. The library never opens or closes the connection itself.

```python
import asyncio

from modbus_connection import ModbusTcpParams
from modbus_connection.tmodbus import ModbusConnection
from e3dc_ess_modbus import E3dcPowerStation


async def main() -> None:
    connection = ModbusConnection(ModbusTcpParams(host="192.168.1.50"))
    try:
        station = await E3dcPowerStation.async_detect(connection.for_unit(1))
        await station.async_update()
        print("PV:", station.power.pv_power, "W")
        print("Battery:", station.power.battery_soc, "%")
        print("Grid:", station.power.grid_power, "W")
        if station.battery_control is not None:
            await station.battery_control.async_write_battery_power(3000)
    finally:
        await connection.close()


asyncio.run(main())
```

Every value is `None` until the first update. Each update returns an `UpdateReport`. `report.updated` names the components that refreshed. `report.failed` maps the others to their error, and those keep their previous values. A lost connection raises `ModbusConnectionError`.

## Gotchas

- **Request rate:** the device accepts at most 10 requests per second. The library spaces its requests by 100 ms to stay under that.
- **Optional components:** setup probes which components the firmware serves and logs the missing ones at `INFO`. Those it doesn't serve stay `None`.
- **Setpoints expire:** the feed-in limit and the battery power lapse 30 seconds after the last write. The active power limit and the reactive power setpoints hold for the failsafe timeouts, 30 seconds by default. A timeout of 0 keeps them until the next write.
- **Holding a setpoint:** the library writes a setpoint once and never repeats it. To hold one, write it again before its timeout runs out. The `*_setpoint` attributes keep the last value written that the device acknowledged, as encoded. They don't clear when the setpoint lapses, only when the connection drops.
- **Reading back a write:** a write doesn't refresh the cached values. Call `await async_update_settings()` to read back what took effect.
- **Two-register writes:** the feed-in limit and the battery power go out as one FC16 write. If the device refuses FC16, the library logs it once and sends two single-register writes from then on. Between those two writes, the register pair holds a value that is neither the old nor the new one. If the second write fails, the library ends remote battery control, or writes the old feed-in limit back, and raises `InconsistentWriteError`.
- **Feed-in limit:** `feed_in_limit` reads back the last value written. The limit in effect may differ.
- **Wallbox bits:** which bits a wallbox uses depends on its model. Unused bits stay unset.
- **Testing:** built against the vendor's Modbus TCP manual, version 2.80, and tested against modbus-connection's mock. It has not been tested on real hardware.

## API

### `E3dcPowerStation(unit, *, timeout=None)`

An E3/DC home power station. `timeout` asks the connection for a per-request timeout, in seconds.

- `await async_detect(unit, *, timeout=None)`: build the device, read its identity and find out which optional components the firmware serves.
- `await async_update()`: refresh every component.
- `await async_update_readings()`: refresh what the device measures and reports on its own: power, DC strings, wallboxes, meters, power output and inverter mode status, battery limits and inverters.
- `await async_update_settings()`: refresh the values that change only when written: the feed-in limit, the failsafe timeouts and the battery remote control flag.
- `await async_read_raw()`: every register read, undecoded.
- `serial_number`, `model`: from the identity block.
- `readings_components`, `settings_components`: the components this firmware serves, once setup has run.
- `power_meter_readings`: the eight meter slots as `PowerMeterReading`, keyed by slot 0 to 7.
- `identity`, `power`, `dc_strings`, `wallboxes`, `power_meters`, `wide_power_meters`, `grid_status`, `grid_control`, `battery_control`, `inverter_mode_control`, `battery_limits`, `inverters`: the components below.

Numbered parts are mappings keyed by the manual's numbering: DC strings 1 to 3, and wallboxes, power meters and inverters 0 to 7.

### `identity` (`Identity`)

- `manufacturer`: the manufacturer name.
- `model`: the model, such as `S10 X`.
- `serial_number`: the serial number.
- `firmware_release`: the firmware release, such as `S10_2026_04`.
- `modbus_version`: the Modbus interface version, such as `2.3`.

### `power` (`PowerFlows`)

- `pv_power`: solar power, in W.
- `battery_power`: positive while charging, negative while discharging, in W.
- `house_power`: house consumption, in W.
- `grid_power`: positive while importing, negative while feeding in, in W.
- `additional_power`: power from additional feeders, such as a second PV inverter, in W.
- `wallbox_power`: wallbox power, in W.
- `wallbox_solar_power`: the solar share of the wallbox power, in W.
- `battery_soc`: state of charge, in %.
- `autarky`: self-sufficiency, in %.
- `self_consumption`: self-consumption, in %.
- `emergency_power_status`: an `EmergencyPowerStatus`.
- `ems_status`: `EmsStatus` flags.

### `dc_strings` (`DcStrings`)

A mapping of string number 1 to 3 to `DcString`. The manual marks string 3 as not used.

- `voltage`: string voltage, in V.
- `current`: string current, in A.
- `power`: string power, in W.

### `wallboxes` (`Wallboxes`)

- `slots`: eight `Wallbox` objects, in the order the device's wallbox configuration sets.
- `configured`: the configured wallboxes, keyed by slot.

Each `Wallbox` has:

- `slot`: its slot, from 0 to 7.
- `available`: a wallbox is configured in this slot.
- `charging_allowed`: charging is allowed. It reads the same bit as `charging_aborted`, inverted.
- `charging_aborted`: charging is not allowed.
- `charging`: a vehicle is drawing power. The wallbox sets this bit itself.
- `solar_mode`: charging from solar only. Unset means hybrid mode.
- `one_phase`: charging on one phase. Unset means three.
- `type2_plugged`, `type2_locked`: the type 2 plug is plugged in, or locked.
- `schuko_on`, `schuko_plugged`, `schuko_locked`: the type F socket is on, plugged in, or locked.
- `relay_16a_1p`, `relay_16a_3p`, `relay_32a_3p`: which relay is closed.
- `await async_write_charging_allowed(allowed)`: allow or abort charging.
- `await async_write_solar_mode(enabled)`: charge from solar only, or in hybrid mode.
- `await async_write_one_phase(enabled)`: charge on one phase, or on three.
- `await async_write_schuko_on(on)`: switch the type F socket on or off.

### `power_meters` (`PowerMeters`)

- `meters`: eight `PowerMeter` slots with `meter_type` and `power_l1` to `power_l3`. Read them through `power_meter_readings`, which uses the 32-bit values when they refreshed in the last poll.

A `PowerMeterReading` has:

- `meter_type`: a `PowerMeterType`, or `None` for an empty slot.
- `is_installed`: a meter is configured in this slot.
- `power_l1`, `power_l2`, `power_l3`: power per phase, in W.

### `wide_power_meters` (`WidePowerMeters`)

Optional. Present when the firmware serves the 32-bit meter values.

- `sg_ready_status`: the SG Ready status code. The manual documents no values.

### `grid_status` (`GridStatus`)

Optional. Present on firmware 2025_06 or later.

- `power_output_ready`: the inverter, DC-DC converter and battery can deliver power.

### `grid_control` (`GridControl`)

Optional. Present on firmware 2025_06 or later.

- `feed_in_limit`: the last feed-in limit written, in W.
- `active_power_failsafe_timeout`: how long an active power setpoint holds, in s.
- `reactive_power_failsafe_timeout`: how long a reactive power setpoint holds, in s.
- `active_power_limit_setpoint`, `active_power_failsafe_setpoint`, `reactive_power_failsafe_setpoint`: the last values acknowledged, in %.
- `reactive_power_setpoint` (var), `cos_phi_setpoint`, `reactive_power_percent_setpoint` (%): the last reactive power acknowledged, in the form it was written. The other two forms are `None`.
- `await async_write_feed_in_limit(watts)`: cap the power fed into the grid.
- `await async_write_active_power_limit(percent)`: cap the inverter's output, in % of rated power.
- `await async_write_active_power_failsafe(percent)`: the active power limit after a setpoint expires.
- `await async_write_reactive_power(var)`: set the reactive power, in var.
- `await async_write_reactive_power_percent(percent)`: set the reactive power, in % of rated apparent power.
- `await async_write_cos_phi(value)`: set the reactive power as cos φ, from -600 to 600.
- `await async_write_reactive_power_failsafe(percent)`: the reactive power after a setpoint expires.
- `await async_write_active_power_failsafe_timeout(seconds)`: how long an active power setpoint holds. 0 turns the failsafe off.
- `await async_write_reactive_power_failsafe_timeout(seconds)`: how long a reactive power setpoint holds. 0 turns the failsafe off.

### `battery_control` (`BatteryControl`)

Optional. Present on firmware 2025_40 or later.

- `remote_control_disabled`: register 40199. Writing 1 ends remote battery control at once. The manual says 0 has no effect.
- `battery_power_setpoint`: the last battery power acknowledged, in W. `None` after a stop or a percentage write.
- `await async_write_battery_power(watts)`: charge (positive) or discharge (negative) at a fixed power.
- `await async_stop_remote_control()`: hand control back at once, by writing 1 to 40199.
- `await async_write_remote_control_disabled(disabled)`: write 40199. True does what `async_stop_remote_control()` does.

On firmware 2026_04 and later, `battery_limits` sets the battery power as a percentage too.

### `inverter_mode_control` (`InverterModeControl`)

Optional. Present on firmware 2025_43 or later.

- `inverter_mode_request`: the forced inverter mode, an `InverterModeRequest`.
- `inverter_mode`: the inverter mode in effect, an `InverterMode`.
- `await async_write_inverter_mode_request(mode)`: force an `InverterModeRequest`.

### `battery_limits` (`BatteryLimits`)

Optional. Present on firmware 2026_04 or later.

- `max_charge_power`: what the battery can take right now, in W.
- `max_discharge_power`: what the battery can give right now, negative, in W.
- `remaining_energy`: stored energy, in Wh.
- `full_charge_energy`: capacity when full, in Wh.
- `battery_power_percent_setpoint`: the last battery power percentage acknowledged. `None` after a stop or a watt write.
- `await async_write_battery_power_percent(percent)`: charge (positive) or discharge (negative) at a share of full power. The watt write is on `battery_control`.

### `inverters` (`Inverters`)

Optional. Present when any inverter slot answers.

A mapping of slot number to `Inverter`, with every slot that answers its registers. Inverter 0 is the device's own. Slots 1 to 7 are for additional solar inverters, and an empty slot may answer with zeros.

- `is_connected`: the inverter reports a grid voltage.
- `active_power_l1` to `active_power_l3`: active power per phase, in W.
- `apparent_power_l1` to `apparent_power_l3`: apparent power per phase, in VA.
- `reactive_power_l1` to `reactive_power_l3`: reactive power per phase, in var.
- `voltage_l1` to `voltage_l3`: AC voltage per phase, in V.
- `current_l1` to `current_l3`: AC current per phase, in A.
- `frequency`: grid frequency, in Hz.
- `dc_power_1` to `dc_power_3`: DC power per tracker, in W.
- `dc_voltage_1` to `dc_voltage_3`: DC voltage per tracker, in V.
- `dc_current_1` to `dc_current_3`: DC current per tracker, in A.

### Enums

- `EmergencyPowerStatus`: `NOT_SUPPORTED`, `ACTIVE`, `INACTIVE`, `NOT_AVAILABLE`, `MOTOR_SWITCH_OFF`.
- `EmsStatus` (flags): `CHARGING_LOCKED`, `DISCHARGING_LOCKED`, `EMERGENCY_POWER_READY`, `WEATHER_BASED_CHARGING`, `FEED_IN_LIMITED`, `CHARGE_LOCK_TIME`, `DISCHARGE_LOCK_TIME`.
- `PowerMeterType`: `ROOT`, `EXTERNAL_PRODUCTION`, `BIDIRECTIONAL`, `EXTERNAL_CONSUMPTION`, `FARM`, `NOT_USED`, `WALLBOX`, `EXTERNAL_FARM`, `DATA_DISPLAY`, `CONTROL_BYPASS`.
- `InverterModeRequest`: `DISABLE_OVERWRITE`, `FORCE_IDLE_OFF_GRID_POWER_SAVE`.
- `InverterMode`: `INIT`, `IDLE_OFF_GRID_POWER_SAVE`.

### Errors

All errors the library raises itself derive from `E3dcError`. Transport and device errors come from modbus-connection.

- `NotAnE3dcError`: the device refused the identity block, or didn't identify as an E3/DC power station in E3DC mode. Raised by `async_detect()` and the first update.
- `InvalidValueError`: a value to write is out of range or of the wrong type. It is also a `ValueError`. Nothing is written.
- `InconsistentWriteError`: on a device that refuses FC16, the first half of a two-register setpoint was written and the second failed. The library has tried to restore a safe state and forgotten the setpoint.
- `ModbusConnectionError`: the connection was lost.
- `ModbusTimeoutError`: the device didn't answer before any component had refreshed.
- `ModbusExceptionError`: the device refused a write, for example a setpoint on firmware that doesn't support it.

The register addresses are in the component modules under [`src/e3dc_ess_modbus`](src/e3dc_ess_modbus), and in the vendor's Modbus TCP manual on the [E3/DC customer portal](https://my.e3dc.com).

## Troubleshooting

`script/query.py` reads the device once and prints every value:

```bash
uv run script/query.py 192.168.1.50
```

Add `--raw` to include the undecoded registers. A bug report about a wrong value needs them.

The `e3dc_ess_modbus` logger reports at `DEBUG` the components setup settled on. It logs each refused block at `INFO`, and a refused FC16 write or a half-written setpoint at `WARNING`.
