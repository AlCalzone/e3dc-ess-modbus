# e3dc-ess-modbus

Read and control E3/DC home power stations over Modbus TCP, as typed Python
objects instead of register numbers.

The library maps the E3/DC "Simple Mode" register set onto
[modbus-connection](https://github.com/home-assistant-libs/modbus-connection)'s
device model. You hand it a `ModbusUnit`, call `async_update()`, and read the
sub-systems as attributes. It owns no connection and no I/O policy. The caller
does.

## Supported devices

E3/DC (HagerEnergy GmbH) home power stations and Quattroporte systems with the
Modbus interface turned on and its protocol set to `E3DC`: the S10 family
(S10 E, S10 E PRO, S10 X, S20 X PRO), and the systems running the Q10 and P10
firmware lines. The register
map follows the manufacturer's "Modbus TCP interface" manual, version 2.80.

The `SUN_SPEC` protocol setting serves a different map. This library does not
read it. A device in that mode fails detection with `NotAnE3dcError`.

What a device serves depends on its firmware. Blocks added in later releases
are probed once at setup, and a block the firmware refuses is never polled:

| Block | Registers | Probed | Firmware the manual names |
| :--- | :--- | :--- | :--- |
| Identity, power flows, wallboxes, DC strings, 16-bit power meters | 40001–40136 | no | – |
| SG Ready status, 32-bit power meter phases | 40137–40185 | yes | – |
| Inverter data | 41000–41271 | yes | – |
| Feed-in limit, active and reactive power control | 40186–40196 | yes | 2025_06 |
| Remote battery control | 40197–40199, 40210 | yes | 2025_40 |
| Inverter operating mode | 40200–40201 | yes | 2025_43 |
| Battery limits and stored energy | 40202–40209 | yes | 2026_04 |

## Usage

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

        print("Model:", station.model, station.serial_number)
        print("PV power:", station.power.pv_power, "W")
        print("Battery:", station.power.battery_soc, "%")
        print("Grid:", station.power.grid_power, "W")
        print("EMS:", station.power.ems_status)
    finally:
        await connection.close()


asyncio.run(main())
```

`async_detect()` reads the identification block and checks register 40001 for
the magic value `0xE3DC`. It raises `NotAnE3dcError` when the value is wrong,
which usually means Modbus is set to SunSpec. A caller that has already checked
the device constructs `E3dcPowerStation(unit)` directly. The first poll then
reads the identity and checks the magic value itself.

### Addresses

The manual numbers registers from 1, so its register 40001 is protocol address
40000. Every field in this library is declared with `register()`, which takes
the manual's number and returns the address:

```python
from e3dc_ess_modbus import register

register(40068)  # -> 40067, PV power
```

A field and the manual's table can then be read side by side. The same
convention applies to the inverter block, which the manual lists at 41000.

### Signs and word order

The device sends 32-bit values low word first, the "int32 swap" layout:

```python
station.power.grid_power     # -600: feeding 600 W into the grid
station.power.battery_power  # -1200: discharging at 1.2 kW
```

Grid power is positive while importing. Battery power is positive while
charging.

### Readings and settings refresh separately

`E3dcPowerStation` splits its poll by what it reads:

- `async_update_readings()` reads what the device measures: power flows, DC
  strings, wallboxes, power meters, battery limits and inverters.
- `async_update_settings()` reads the remote control registers, which change
  only when something writes them.
- `async_update()` reads both, in one merged report.

Each sub-system is read on its own, so one refused block does not take the rest
of the poll with it. Every update method returns an `UpdateReport`. A failed
component keeps its previous values and is listed by attribute name with its
error. A dead link (`ModbusConnectionError`) raises, and so does a timeout
before any component has answered:

```python
report = await station.async_update_readings()
for name, error in report.failed.items():
    print(f"{name} kept its previous values: {error}")
```

`readings_components` and `settings_components` name what this device polls,
once setup has settled it.

### Self-sufficiency and self-consumption

Register 40082 packs two percentages into one word. The library splits it:

```python
station.power.autarky           # 26, the high byte
station.power.self_consumption  # 82, the low byte
```

### Wallboxes

Up to eight wallboxes share registers 40088 to 40095. The slot order follows
the wallbox configuration on the device. Each slot is a `Wallbox` with one
attribute per bit of its control word:

```python
for number, wallbox in station.wallboxes.available:
    print(number, wallbox.charging, wallbox.type2_plugged, wallbox.solar_mode)

await wallbox.async_write_solar_mode(True)
await wallbox.async_write_charging(False)  # abort charging
await wallbox.async_write_one_phase(True)
```

A write re-reads the control word and changes only its own bit. Which bits a
wallbox serves depends on its model, and the manual has a table per model.

### Power meters

Eight meter slots report a type and the power on each phase. Newer firmware
adds a 32-bit copy of the phase powers, which does not overflow above 32 kW.
`power_meter()` returns the 32-bit values where the device has them:

```python
meter = station.power_meter(0)
if meter.is_installed:
    print(meter.meter_type, meter.power_l1, meter.power_l2, meter.power_l3)
```

### Inverters

The device's own inverter is inverter 0. Additional solar inverters take slots
1 to 7. Setup keeps inverter 0 and each additional inverter that reports a grid
voltage, so `inverter_list` holds only what is connected:

```python
for number, inverter in enumerate(station.inverter_list):
    print(number, inverter.active_power_l1, inverter.frequency)
```

### Remote control

Every setpoint holds for a timeout, 30 seconds by default. The device then
falls back to its own control. A caller that wants a setpoint to last rewrites
it before the timeout runs out:

```python
battery = station.battery_control
await battery.async_write_battery_power(3000)    # charge at 3 kW
await battery.async_write_battery_power(-2000)   # discharge at 2 kW
await battery.async_stop_remote_control()        # back to normal, at once

grid = station.grid_control
await grid.async_write_feed_in_limit(4000)       # watts
await grid.async_write_active_power_limit(70)    # percent of rated power
await grid.write("active_power_failsafe_timeout", 60)
```

Several of these registers are write-only. `GridControl` and `BatteryControl`
declare readable ranges that skip them, so a settings poll never reads one.
`feed_in_limit` reads back the last value written, not the limit in effect.

The manual lists only function codes 05 and 06 for writes. A two-register value
needs function code 16, so the int32 setpoints at 40186 and 40197 go out as one
FC16 write.

### Diagnostics

`async_read_raw()` dumps every register the device reads, undecoded, keyed by
address space and address. Quote it in an issue about a wrong value.
modbus-connection's mock replays it with `load_raw()`, so the dump can become a
test.

## Checking a real device

`script/query.py` reads one power station once and prints every value it
serves. It is the quickest way to check that the device is reachable and in the
right protocol mode:

```bash
uv run script/query.py 192.168.1.50
uv run script/query.py 192.168.1.50 --port 5020 --raw
```

`--raw` adds every register it read, undecoded. The script prints the read
count too, which includes the probes setup makes.

## Timing

The manual asks for at most 10 requests per second. The device object sets a
message spacing of 100 ms on its unit, so a poll stays under that limit on its
own. A caller who has measured their link passes `timeout=` to the constructor
or to `async_detect()`, which asks for it through `ModbusUnit.require_timeout()`.

Modbus is unencrypted, and the device answers only clients in its own subnet.

## Debug logging

The `e3dc_ess_modbus` logger says at `DEBUG` which optional blocks setup found,
which inverters refused their block, and the final poll list.

## Known gaps

The manual leaves a few things open. The library takes these readings of it:

- Register 40210 is listed with length 1 and type Int32. The library writes it
  as one signed 16-bit register.
- The inverter table gives addresses where the other tables give register
  numbers. The library reads both the same way, so inverter 0 starts at
  protocol address 40999.
- The power meter types do not include 0. An unused slot decodes to `None`.
- The manual documents no values for the SG Ready status.
