from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from modbus_connection import IllegalFunctionError
from modbus_connection.mock import MockModbusUnit, WriteEvent

from e3dc_ess_modbus import E3dcPowerStation, InverterModeRequest
from e3dc_ess_modbus.model import register

# A writer takes the set-up station and the value to write.
Writer = Callable[[E3dcPowerStation, Any], Awaitable[None]]


def _grid(name: str) -> Writer:
    return lambda station, value: getattr(station.grid_control, name)(value)


def _battery(name: str) -> Writer:
    return lambda station, value: getattr(station.battery_control, name)(value)


def _limits(name: str) -> Writer:
    return lambda station, value: getattr(station.battery_limits, name)(value)


def _field(component: str, field: str) -> Writer:
    return lambda station, value: getattr(station, component).write(field, value)


@pytest.fixture
async def writes(
    station: E3dcPowerStation, mock_modbus_unit: MockModbusUnit
) -> list[WriteEvent]:
    await station.async_ensure_setup()
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    return events


ACCEPTED = [
    # (writer, value, register, words)
    pytest.param(
        _grid("async_write_feed_in_limit"), 4000, 40186, [4000, 0], id="feed_in"
    ),
    pytest.param(
        _grid("async_write_feed_in_limit"), 0, 40186, [0, 0], id="feed_in_zero"
    ),
    pytest.param(
        _grid("async_write_feed_in_limit"),
        0x7FFF_FFFF,
        40186,
        [0xFFFF, 0x7FFF],
        id="feed_in_max",
    ),
    pytest.param(_grid("async_write_reactive_power"), -3000, 40189, [0xF448], id="var"),
    pytest.param(
        _grid("async_write_reactive_power"), 32767, 40189, [0x7FFF], id="var_max"
    ),
    pytest.param(
        _grid("async_write_reactive_power"), -32768, 40189, [0x8000], id="var_min"
    ),
    pytest.param(_grid("async_write_cos_phi"), -600, 40190, [0xFDA8], id="cos_phi_min"),
    pytest.param(_grid("async_write_cos_phi"), 600, 40190, [600], id="cos_phi_max"),
    pytest.param(
        _grid("async_write_reactive_power_percent"), -12.5, 40191, [0xFF83], id="q_pct"
    ),
    pytest.param(
        _grid("async_write_reactive_power_percent"),
        -100,
        40191,
        [0xFC18],
        id="q_pct_min",
    ),
    pytest.param(
        _grid("async_write_active_power_limit"), 70, 40192, [700], id="p_limit"
    ),
    pytest.param(
        _grid("async_write_active_power_limit"), 0, 40192, [0], id="p_limit_0"
    ),
    pytest.param(
        _grid("async_write_active_power_failsafe"), 100, 40193, [1000], id="p_failsafe"
    ),
    pytest.param(
        _grid("async_write_reactive_power_failsafe"), 0.1, 40195, [1], id="q_failsafe"
    ),
    pytest.param(
        _field("grid_control", "active_power_failsafe_timeout"),
        65535,
        40194,
        [0xFFFF],
        id="p_timeout_max",
    ),
    pytest.param(
        _field("grid_control", "reactive_power_failsafe_timeout"),
        0,
        40196,
        [0],
        id="q_timeout_off",
    ),
    pytest.param(
        _grid("async_write_active_power_failsafe_timeout"),
        120,
        40194,
        [120],
        id="p_timeout_typed",
    ),
    pytest.param(
        _grid("async_write_reactive_power_failsafe_timeout"),
        0,
        40196,
        [0],
        id="q_timeout_typed",
    ),
    pytest.param(
        _battery("async_write_battery_power"), -3000, 40197, [0xF448, 0xFFFF], id="bat"
    ),
    pytest.param(
        _battery("async_write_battery_power"),
        -0x8000_0000,
        40197,
        [0, 0x8000],
        id="bat_min",
    ),
    pytest.param(
        _battery("async_write_remote_control_disabled"), False, 40199, [0], id="enable"
    ),
    pytest.param(
        lambda station, _: station.battery_control.async_stop_remote_control(),
        None,
        40199,
        [1],
        id="stop",
    ),
    pytest.param(
        lambda station, value: station.inverter_mode_control.async_write_inverter_mode(
            value
        ),
        InverterModeRequest.FORCE_IDLE_OFF_GRID_POWER_SAVE,
        40200,
        [10],
        id="inverter_mode",
    ),
    pytest.param(
        _limits("async_write_battery_power_percent"), -50, 40210, [0xFE0C], id="bat_pct"
    ),
    pytest.param(
        _limits("async_write_battery_power_percent"),
        100,
        40210,
        [1000],
        id="bat_pct_max",
    ),
]


@pytest.mark.parametrize(("writer", "value", "index", "words"), ACCEPTED)
async def test_writer_sends_one_write(
    station: E3dcPowerStation,
    writes: list[WriteEvent],
    writer: Writer,
    value: Any,
    index: int,
    words: list[int],
) -> None:
    await writer(station, value)

    assert [(write.address, write.values) for write in writes] == [
        (register(index), words)
    ]


REJECTED = [
    pytest.param(_grid("async_write_feed_in_limit"), -1, id="feed_in_negative"),
    pytest.param(_grid("async_write_feed_in_limit"), 0x8000_0000, id="feed_in_wraps"),
    pytest.param(_grid("async_write_reactive_power"), 40000, id="var_wraps"),
    pytest.param(_grid("async_write_reactive_power"), -32769, id="var_too_low"),
    pytest.param(_grid("async_write_cos_phi"), 601, id="cos_phi"),
    pytest.param(_grid("async_write_reactive_power_percent"), -101, id="q_pct"),
    pytest.param(_grid("async_write_active_power_limit"), 101, id="p_limit"),
    pytest.param(_grid("async_write_active_power_failsafe"), -1, id="p_failsafe"),
    pytest.param(_grid("async_write_reactive_power_failsafe"), 100.5, id="q_failsafe"),
    pytest.param(
        _field("grid_control", "active_power_failsafe_timeout"), 65536, id="p_timeout"
    ),
    pytest.param(
        _field("grid_control", "reactive_power_failsafe_timeout"), -1, id="q_timeout"
    ),
    pytest.param(
        _grid("async_write_active_power_failsafe_timeout"), 65536, id="p_timeout_typed"
    ),
    pytest.param(
        _battery("async_write_remote_control_disabled"), 2, id="disable_not_bool"
    ),
    pytest.param(_battery("async_write_battery_power"), 0x8000_0000, id="bat_wraps"),
    pytest.param(_battery("async_write_battery_power"), -0x8000_0001, id="bat_too_low"),
    pytest.param(_limits("async_write_battery_power_percent"), 100.1, id="bat_pct"),
]


@pytest.mark.parametrize(("writer", "value"), REJECTED)
async def test_writer_rejects_without_sending(
    station: E3dcPowerStation, writes: list[WriteEvent], writer: Writer, value: Any
) -> None:
    with pytest.raises(ValueError):
        await writer(station, value)

    assert writes == []


async def test_int32_falls_back_to_two_single_writes(
    station: E3dcPowerStation,
    writes: list[WriteEvent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(address: int, values: list[int]) -> None:
        raise IllegalFunctionError()

    monkeypatch.setattr(station.modbus_unit, "write_registers", refuse)
    assert station.battery_control is not None
    await station.battery_control.async_write_battery_power(-3000)

    assert [(w.address, w.values, w.function_code) for w in writes] == [
        (register(40197), [0xF448], 0x06),
        (register(40198), [0xFFFF], 0x06),
    ]


async def test_wallbox_writes_set_the_bit_whatever_its_state(
    station: E3dcPowerStation, mock_modbus_unit: MockModbusUnit
) -> None:
    await station.async_update_readings()
    wallbox = station.wallboxes.slots[0]

    await wallbox.async_write_solar_mode(True)
    await wallbox.async_write_solar_mode(True)

    assert mock_modbus_unit.holding[register(40088)] == 0b0000000111011


async def test_setpoints_remember_the_last_value_written(
    station: E3dcPowerStation, writes: list[WriteEvent]
) -> None:
    grid, battery, limits = (
        station.grid_control,
        station.battery_control,
        station.battery_limits,
    )
    assert grid is not None
    assert battery is not None
    assert limits is not None
    assert battery.battery_power_setpoint is None

    await battery.async_write_battery_power(-2000)
    await grid.async_write_active_power_limit(70)
    await limits.async_write_battery_power_percent(25)
    with pytest.raises(ValueError):
        await battery.async_write_battery_power(0x8000_0000)

    assert battery.battery_power_setpoint == -2000
    assert grid.active_power_limit_setpoint == 70
    assert limits.battery_power_percent_setpoint == 25

    await battery.async_stop_remote_control()
    assert battery.battery_power_setpoint is None


async def test_concurrent_wallbox_writes_keep_both_bits(
    station: E3dcPowerStation,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await station.async_update_readings()
    wallbox = station.wallboxes.slots[0]
    read = mock_modbus_unit.read_holding_registers

    async def yielding_read(address: int, count: int) -> list[int]:
        words = await read(address, count)
        # Let the other write run between this read and its write
        await asyncio.sleep(0)
        return words

    monkeypatch.setattr(mock_modbus_unit, "read_holding_registers", yielding_read)

    await asyncio.gather(
        wallbox.async_write_one_phase(True), wallbox.async_write_charging(False)
    )

    assert mock_modbus_unit.holding[register(40088)] == 0b1000000111111
