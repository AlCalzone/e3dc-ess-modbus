"""Remote control of the grid connection and the battery, registers 40186 to 40210.

Several of these registers are write-only. The components read only the
readable ones and offer a method per write-only setpoint.

How long a setpoint holds depends on its register. The feed-in limit and the
battery power lapse 30 seconds after the last write. The reactive power
setpoints and the active power limit hold for the failsafe timeouts in 40194
and 40196, which default to 30 seconds. A timeout of 0 turns the failsafe off,
and the setpoint then holds until it is written again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from modbus_connection import IllegalFunctionError
from modbus_connection.encode import encode_int
from modbus_connection.model import boolean, enum, int32, integer

from .enums import InverterMode, InverterModeRequest
from .model import E3dcComponent, register

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

INT16_MIN, INT16_MAX = -0x8000, 0x7FFF
INT32_MIN, INT32_MAX = -0x8000_0000, 0x7FFF_FFFF


def _timeout(value: int) -> int:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"timeout {value} s is outside 0-65535")
    return value


def _feed_in_limit(watts: int) -> int:
    if not 0 <= watts <= INT32_MAX:
        raise ValueError(f"feed-in limit {watts} W is outside 0-{INT32_MAX}")
    return watts


def _int16(value: int) -> int:
    """A signed 16-bit value as the register word that carries it."""
    if not INT16_MIN <= value <= INT16_MAX:
        raise ValueError(f"{value} does not fit a signed 16-bit register")
    return encode_int(value, count=1)[0]


async def _write_tenths(
    unit: ModbusUnit, index: int, percent: float, low: float, high: float
) -> None:
    """Write a percentage to register ``index`` in the device's 0.1 % steps."""
    if not low <= percent <= high:
        raise ValueError(f"{percent} % is outside {low}-{high}")
    await unit.write_register(register(index), _int16(round(percent * 10)))


async def _write_int32(unit: ModbusUnit, index: int, value: int) -> None:
    """Write a signed 32-bit value to register ``index`` and the one after it.

    The manual lists no FC16 for this device, but one FC16 write is the only
    way to change both words at once. A device that refuses FC16 gets two FC06
    writes, low word first. Between the two writes, the register pair holds the
    new low word next to the old high word.
    """
    if not INT32_MIN <= value <= INT32_MAX:
        raise ValueError(f"{value} does not fit a signed 32-bit register pair")
    low, high = encode_int(value, count=2, word_order="little")
    try:
        await unit.write_registers(register(index), [low, high])
    except IllegalFunctionError:
        await unit.write_register(register(index), low)
        await unit.write_register(register(index + 1), high)


class GridControl(E3dcComponent):
    """Feed-in limitation and active and reactive power control.

    The device takes these only when it is certified for grid operator control.
    """

    register_ranges = (
        (register(40186), register(40188)),
        (register(40194), register(40194)),
        (register(40196), register(40196)),
    )

    feed_in_limit = int32(register(40186), word_order="little", unit="W")
    """The last limit written, not the limit in effect."""
    power_output_ready = boolean(register(40188))
    """PV inverter on the grid, DC-DC converter working, battery dischargeable."""
    active_power_failsafe_timeout = integer(
        register(40194), signed=False, unit="s", writable=_timeout
    )
    """How long an active power setpoint holds; 0 turns the failsafe off."""
    reactive_power_failsafe_timeout = integer(
        register(40196), signed=False, unit="s", writable=_timeout
    )
    """How long a reactive power setpoint holds; 0 turns the failsafe off."""

    async def async_write_feed_in_limit(self, watts: int) -> None:
        """Cap the power fed into the grid; rewrite within 30 seconds to keep it."""
        await _write_int32(self._unit, 40186, _feed_in_limit(watts))

    async def async_write_reactive_power(self, var: int) -> None:
        """Set the reactive power, in var.

        The manual allows ±50 % of the rated apparent power, which the device
        enforces. This checks only that the value fits the register.
        """
        await self._unit.write_register(register(40189), _int16(var))

    async def async_write_cos_phi(self, value: int) -> None:
        """Set the reactive power as cos φ, from -600 (0.4 capacitive) to 600."""
        if not -600 <= value <= 600:
            raise ValueError(f"cos φ setpoint {value} is outside -600-600")
        await self._unit.write_register(register(40190), _int16(value))

    async def async_write_reactive_power_percent(self, percent: float) -> None:
        """Set the reactive power as a percentage of the rated apparent power."""
        await _write_tenths(self._unit, 40191, percent, -100, 100)

    async def async_write_active_power_limit(self, percent: float) -> None:
        """Cap the inverter's active power, ignoring the house's consumption."""
        await _write_tenths(self._unit, 40192, percent, 0, 100)

    async def async_write_active_power_failsafe(self, percent: float) -> None:
        """Set the active power limit that applies once a setpoint times out."""
        await _write_tenths(self._unit, 40193, percent, 0, 100)

    async def async_write_reactive_power_failsafe(self, percent: float) -> None:
        """Set the reactive power that applies once a setpoint times out."""
        await _write_tenths(self._unit, 40195, percent, 0, 100)


class BatteryControl(E3dcComponent):
    """Remote control of the battery power, from release 2025_40."""

    register_ranges = ((register(40199), register(40199)),)

    remote_control_disabled = boolean(register(40199), writable=True)
    """1 disables remote battery control at once. The manual says 0 has no effect."""

    async def async_write_battery_power(self, watts: int) -> None:
        """Charge (positive) or discharge (negative) the battery at ``watts``.

        PV power charges first and the grid makes up the rest. The device
        returns to normal control unless this is rewritten within 30 seconds.
        """
        await _write_int32(self._unit, 40197, watts)

    async def async_stop_remote_control(self) -> None:
        """End remote battery control at once, without waiting for its timeout."""
        await self.write("remote_control_disabled", True)

    async def async_write_remote_control_disabled(self, disabled: bool) -> None:
        """Write register 40199 directly, for example to clear it again."""
        await self.write("remote_control_disabled", disabled)


class InverterModeControl(E3dcComponent):
    """The inverter operating mode, from release 2025_43."""

    register_ranges = ((register(40200), register(40201)),)

    inverter_mode_request = enum(
        register(40200), InverterModeRequest, signed=True, writable=True
    )
    inverter_mode = enum(register(40201), InverterMode, signed=True)

    async def async_write_inverter_mode(self, mode: InverterModeRequest) -> None:
        """Force an inverter operating mode, or hand control back."""
        await self.write("inverter_mode_request", mode)


class BatteryLimits(E3dcComponent):
    """What the battery can take and give right now, from release 2026_04."""

    max_charge_power = int32(register(40202), word_order="little", unit="W")
    max_discharge_power = int32(register(40204), word_order="little", unit="W")
    """Negative."""
    remaining_energy = int32(register(40206), word_order="little", unit="Wh")
    full_charge_energy = int32(register(40208), word_order="little", unit="Wh")

    async def async_write_battery_power_percent(self, percent: float) -> None:
        """Charge (positive) or discharge (negative) at a share of full power.

        The manual lists register 40210 with length 1 and type Int32. This
        writes one signed 16-bit register.
        """
        await _write_tenths(self._unit, 40210, percent, -100, 100)
