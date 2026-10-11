from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from modbus_connection import (
    IllegalDataValueError,
    IllegalFunctionError,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusUnit, WriteEvent

from e3dc_ess_modbus import (
    E3dcPowerStation,
    InconsistentWriteError,
    InvalidValueError,
    InverterMode,
    InverterModeRequest,
)
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
    pytest.param(
        _grid("async_write_active_power_failsafe_timeout"), True, id="timeout_bool"
    ),
    pytest.param(_battery("async_write_battery_power"), True, id="bat_bool"),
    pytest.param(_battery("async_write_battery_power"), 500.7, id="bat_float"),
    pytest.param(_grid("async_write_reactive_power"), 12.5, id="var_float"),
    pytest.param(_grid("async_write_active_power_limit"), False, id="p_limit_bool"),
    pytest.param(
        lambda station, value: station.inverter_mode_control.async_write_inverter_mode(
            value
        ),
        99,
        id="inverter_mode_raw",
    ),
    pytest.param(
        lambda station, value: station.inverter_mode_control.async_write_inverter_mode(
            value
        ),
        InverterMode.INIT,
        id="inverter_mode_other_enum",
    ),
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
    with pytest.raises(InvalidValueError):
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


async def test_battery_setpoint_is_one_state(
    station: E3dcPowerStation, writes: list[WriteEvent]
) -> None:
    battery, limits = station.battery_control, station.battery_limits
    assert battery is not None
    assert limits is not None
    assert battery.battery_power_setpoint is None

    await battery.async_write_battery_power(-2000)
    assert battery.battery_power_setpoint == -2000
    with pytest.raises(InvalidValueError):
        await battery.async_write_battery_power(0x8000_0000)
    assert battery.battery_power_setpoint == -2000

    await limits.async_write_battery_power_percent(25)
    assert limits.battery_power_percent_setpoint == 25
    assert battery.battery_power_setpoint is None

    await battery.async_write_battery_power(1000)
    assert limits.battery_power_percent_setpoint is None

    await battery.async_write_remote_control_disabled(True)
    assert battery.battery_power_setpoint is None
    assert limits.battery_power_percent_setpoint is None


async def test_grid_setpoints_are_remembered(
    station: E3dcPowerStation, writes: list[WriteEvent]
) -> None:
    grid = station.grid_control
    assert grid is not None

    await grid.async_write_reactive_power(-3000)
    await grid.async_write_active_power_limit(70)
    await grid.async_write_active_power_failsafe(10)
    await grid.async_write_reactive_power_failsafe(5)
    assert grid.reactive_power_setpoint == -3000
    assert grid.active_power_limit_setpoint == 70
    assert grid.active_power_failsafe_setpoint == 10
    assert grid.reactive_power_failsafe_setpoint == 5

    await grid.async_write_cos_phi(300)
    assert grid.reactive_power_setpoint is None
    assert grid.cos_phi_setpoint == 300

    await grid.async_write_reactive_power_percent(-12.5)
    assert grid.cos_phi_setpoint is None
    assert grid.reactive_power_percent_setpoint == -12.5


async def test_a_refused_write_leaves_the_setpoint(
    station: E3dcPowerStation, mock_modbus_unit: MockModbusUnit
) -> None:
    await station.async_ensure_setup()
    battery, grid = station.battery_control, station.grid_control
    assert battery is not None
    assert grid is not None
    await battery.async_write_battery_power(500)
    await grid.async_write_active_power_limit(70)
    mock_modbus_unit.fail_write(register(40197), IllegalDataValueError())
    mock_modbus_unit.fail_write(register(40192), IllegalDataValueError())

    with pytest.raises(IllegalDataValueError):
        await battery.async_write_battery_power(-500)
    with pytest.raises(IllegalDataValueError):
        await grid.async_write_active_power_limit(50)

    assert battery.battery_power_setpoint == 500
    assert grid.active_power_limit_setpoint == 70


@pytest.mark.parametrize(
    ("writer", "value", "function_code"),
    [
        pytest.param(_grid("async_write_feed_in_limit"), 4000, 0x10, id="feed_in"),
        pytest.param(_battery("async_write_battery_power"), 500, 0x10, id="bat"),
        pytest.param(_grid("async_write_reactive_power"), 100, 0x06, id="var"),
        pytest.param(_grid("async_write_cos_phi"), 100, 0x06, id="cos_phi"),
        pytest.param(_grid("async_write_active_power_limit"), 50, 0x06, id="p_limit"),
        pytest.param(
            _grid("async_write_active_power_failsafe_timeout"), 30, 0x06, id="timeout"
        ),
        pytest.param(
            _battery("async_write_remote_control_disabled"), True, 0x06, id="disable"
        ),
        pytest.param(
            _limits("async_write_battery_power_percent"), 10, 0x06, id="bat_pct"
        ),
    ],
)
async def test_writer_function_codes(
    station: E3dcPowerStation,
    writes: list[WriteEvent],
    writer: Writer,
    value: Any,
    function_code: int,
) -> None:
    await writer(station, value)

    assert [write.function_code for write in writes] == [function_code]


async def test_fc16_refusal_is_remembered(
    station: E3dcPowerStation,
    writes: list[WriteEvent],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempts = 0

    async def refuse(address: int, values: list[int]) -> None:
        nonlocal attempts
        attempts += 1
        raise IllegalFunctionError()

    monkeypatch.setattr(station.modbus_unit, "write_registers", refuse)
    assert station.battery_control is not None
    assert station.grid_control is not None
    await station.battery_control.async_write_battery_power(-3000)
    await station.grid_control.async_write_feed_in_limit(4000)

    assert attempts == 1
    assert caplog.text.count("refuses FC16") == 1
    assert [(w.address, w.values) for w in writes][2:] == [
        (register(40186), [4000]),
        (register(40187), [0]),
    ]


async def test_fc16_failing_otherwise_does_not_fall_back(
    station: E3dcPowerStation,
    writes: list[WriteEvent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def time_out(address: int, values: list[int]) -> None:
        raise ModbusTimeoutError()

    monkeypatch.setattr(station.modbus_unit, "write_registers", time_out)
    assert station.battery_control is not None
    with pytest.raises(ModbusTimeoutError):
        await station.battery_control.async_write_battery_power(-3000)

    assert writes == []


async def test_a_half_written_pair_raises_and_forgets_the_setpoint(
    station: E3dcPowerStation,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def refuse(address: int, values: list[int]) -> None:
        raise IllegalFunctionError()

    await station.async_ensure_setup()
    battery = station.battery_control
    assert battery is not None
    await battery.async_write_battery_power(-500)
    monkeypatch.setattr(station.modbus_unit, "write_registers", refuse)
    mock_modbus_unit.fail_write(register(40198), ModbusTimeoutError())

    with pytest.raises(InconsistentWriteError) as err:
        await battery.async_write_battery_power(500)

    assert isinstance(err.value.__cause__, ModbusTimeoutError)
    assert battery.battery_power_setpoint is None
    assert "Register 40197 took its new low word" in caplog.text


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
        wallbox.async_write_one_phase(True), wallbox.async_write_charging_allowed(False)
    )

    assert mock_modbus_unit.holding[register(40088)] == 0b1000000111111
