# e3dc-ess-modbus

Read and control E3/DC home power stations over Modbus TCP, as typed Python objects.

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
        print(station.model, station.serial_number)
        print("PV:", station.power.pv_power, "W")
        print("Battery:", station.power.battery_soc, "%")
        print("Grid:", station.power.grid_power, "W")
    finally:
        await connection.close()


asyncio.run(main())
```

## Installation

```bash
pip install e3dc-ess-modbus
```

Until the first release is on PyPI, install from git:

```bash
pip install "e3dc-ess-modbus @ git+https://github.com/AlCalzone/e3dc-ess-modbus"
```

The library builds on [modbus-connection](https://github.com/home-assistant-libs/modbus-connection). You open the connection and hand the library a unit. The library never opens or closes the link itself.

## Requirements and gotchas

- Turn Modbus on under **Smart Functions** > **Smart Home** > **Modbus**, and set **Protocol** to **E3DC**. SunSpec mode is not supported.
- The default port is 502. The unit ID is 1.
- The power station answers only clients in its own subnet.
- The manual allows at most 10 requests per second. The library spaces its requests to stay under that.
- Remote control needs firmware 2025_06 or later for the grid limits, and 2025_40 for battery control.
- Battery limits and stored energy need firmware 2026_04 or later.
- A remote control setpoint expires 30 seconds after it was last written. Write it again to hold it.
- `feed_in_limit` reads back the last value written. The limit in effect may differ.
- Wallbox bits differ by wallbox model. A bit a model doesn't use stays unset.

## API

### `E3dcPowerStation(unit, *, timeout=None)`

The device. Pass a `ModbusUnit`. `timeout` asks the connection for a per-request timeout, in seconds.

- `async_detect(unit, *, timeout=None)`: build the device and read its identity. Raises `NotAnE3dcError` when the device isn't an E3/DC power station in E3DC mode.
- `async_update()`: refresh everything.
- `async_update_readings()`: refresh the measurements: power, DC strings, wallboxes, meters, battery limits, inverters.
- `async_update_settings()`: refresh the remote control settings.
- `async_read_raw()`: every register read, undecoded, for bug reports.
- `power_meter(number)`: meter slot 0 to 7, as a `PowerMeterReading`.
- `serial_number`, `model`: from the identity block.
- `readings_components`, `settings_components`: the sub-systems this firmware serves, once the first update has run.

Each update method returns an `UpdateReport`. `report.updated` names the sub-systems that refreshed. `report.failed` maps the others to their error, and those keep their previous values. A dropped connection raises `ModbusConnectionError`.

### Sub-systems

Attributes on `E3dcPowerStation`. A value is `None` until the first update. A sub-system marked optional is `None` when the firmware doesn't serve it.

`identity` (`Identity`)
- `manufacturer`, `model`, `serial_number`, `firmware_release`: device strings.
- `modbus_version`: the Modbus interface version, such as `2.3`.

`power` (`PowerFlows`)
- `pv_power`: solar power, in W.
- `battery_power`: positive while charging, negative while discharging, in W.
- `house_power`: house consumption, in W.
- `grid_power`: positive while importing, negative while feeding in, in W.
- `additional_power`: power from additional feeders, such as a second PV inverter, in W.
- `wallbox_power`, `wallbox_solar_power`: wallbox power and its solar share, in W.
- `battery_soc`: state of charge, in %.
- `autarky`, `self_consumption`: self-sufficiency and self-consumption, in %.
- `emergency_power_status`: an `EmergencyPowerStatus`.
- `ems_status`: `EmsStatus` flags, such as charging locked or feed-in limited.

`dc_string_list` (list of `DcString`, strings 1 to 3)
- `voltage`, `current`, `power`.

`wallboxes` (`Wallboxes`)
- `slots`: eight `Wallbox` objects.
- `available`: `(slot number, Wallbox)` for each configured wallbox.

`Wallbox`
- `available`, `charging`, `solar_mode`, `charging_aborted`, `one_phase`: state.
- `type2_plugged`, `type2_locked`, `schuko_on`, `schuko_plugged`, `schuko_locked`: plugs and sockets.
- `relay_16a_1p`, `relay_16a_3p`, `relay_32a_3p`: which relay is closed.
- `async_write_charging(enabled)`: allow or abort charging.
- `async_write_solar_mode(enabled)`: solar-only or hybrid charging.
- `async_write_one_phase(enabled)`: one or three phases.

`PowerMeterReading`, from `power_meter(number)`
- `meter_type`: a `PowerMeterType`, such as `ROOT` for the grid connection point.
- `is_installed`: whether a meter is configured in this slot.
- `power_l1`, `power_l2`, `power_l3`: power per phase, in W.

`inverter_slots` (dict of slot number to `Inverter`)
- Inverter 0 is the device's own. Slots 1 to 7 hold the additional solar inverters that are connected.
- `active_power_l1` to `_l3`, `apparent_power_l1` to `_l3`, `reactive_power_l1` to `_l3`.
- `voltage_l1` to `_l3`, `current_l1` to `_l3`, `frequency`.
- `dc_power_1` to `_3`, `dc_voltage_1` to `_3`, `dc_current_1` to `_3`.

`battery_limits` (`BatteryLimits`, optional)
- `max_charge_power`, `max_discharge_power`: what the battery can take and give right now, in W.
- `remaining_energy`, `full_charge_energy`: stored energy and full capacity, in Wh.

`battery_control` (`BatteryControl`, optional)
- `async_write_battery_power(watts)`: charge (positive) or discharge (negative) at a fixed power.
- `async_write_battery_power_percent(percent)`: the same, as a share of full power.
- `async_stop_remote_control()`: hand control back at once.
- `async_write_inverter_mode(mode)`: force an `InverterModeRequest`.
- `remote_control_disabled`, `inverter_mode_request`, `inverter_mode`: current state.

`grid_control` (`GridControl`, optional)
- `async_write_feed_in_limit(watts)`: cap the power fed into the grid.
- `async_write_active_power_limit(percent)`: cap the inverter's output.
- `async_write_reactive_power(var)`, `async_write_reactive_power_percent(percent)`, `async_write_cos_phi(value)`: set reactive power.
- `async_write_active_power_failsafe(percent)`, `async_write_reactive_power_failsafe(percent)`: what applies after a setpoint expires.
- `feed_in_limit`, `power_output_ready`, `active_power_failsafe_timeout`, `reactive_power_failsafe_timeout`: current state.

`wide_power_meters` (`WidePowerMeters`, optional)
- `sg_ready_status`: the SG Ready status code.

The register layout lives in the source files under [`src/e3dc_ess_modbus`](src/e3dc_ess_modbus) and in the vendor's Modbus TCP manual on the [E3/DC customer portal](https://my.e3dc.com).

## Checking a real device

`script/query.py` reads one power station once and prints every value:

```bash
uv run script/query.py 192.168.1.50
```

Add `--raw` to include the undecoded registers, which a bug report about a wrong value needs.

## Debug logging

The `e3dc_ess_modbus` logger says at `DEBUG` which optional sub-systems setup found.
