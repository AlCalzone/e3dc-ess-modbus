from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from modbus_connection import IllegalFunctionError, ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit, WriteEvent

from e3dc_ess_modbus import (
    E3dcPowerStation,
    HoldsClosedError,
    InconsistentWriteError,
    NoSetpointError,
    Setpoint,
    SetpointHolds,
)
from e3dc_ess_modbus.model import register

BATTERY = Setpoint.BATTERY_POWER
FEED_IN = Setpoint.FEED_IN_LIMIT
ACTIVE = Setpoint.ACTIVE_POWER_LIMIT


@pytest.fixture
async def holds(station: E3dcPowerStation) -> SetpointHolds:
    await station.async_ensure_setup()
    return SetpointHolds(station, interval=None)


@pytest.fixture
def writes(mock_modbus_unit: MockModbusUnit) -> list[WriteEvent]:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    return events


def _writes_to(writes: list[WriteEvent], index: int) -> list[list[int] | list[bool]]:
    return [w.values for w in writes if w.address == register(index)]


def _refuse_fc16(monkeypatch: pytest.MonkeyPatch, unit: MockModbusUnit) -> None:
    monkeypatch.setattr(
        unit, "write_registers", AsyncMock(side_effect=IllegalFunctionError())
    )


async def test_a_hold_is_rewritten_until_stopped(
    holds: SetpointHolds, writes: list[WriteEvent]
) -> None:
    await holds.async_start(BATTERY, 3000)
    await holds.async_rewrite()
    await holds.async_rewrite()
    await holds.async_stop(BATTERY)
    await holds.async_rewrite()

    assert _writes_to(writes, 40197) == [[3000, 0]] * 3
    assert _writes_to(writes, 40199) == [[1]]
    assert holds.get(BATTERY) is None
    assert holds.requested(BATTERY) == 3000

    await holds.async_resume(BATTERY)
    hold = holds.get(BATTERY)
    assert hold is not None
    assert hold.confirmed


async def test_resuming_needs_a_value(holds: SetpointHolds) -> None:
    with pytest.raises(NoSetpointError):
        await holds.async_resume(FEED_IN)

    holds.remember(FEED_IN, 4000)
    await holds.async_resume(FEED_IN)

    assert holds.get(FEED_IN) is not None


async def test_grid_limits_are_handed_back(
    holds: SetpointHolds, writes: list[WriteEvent]
) -> None:
    await holds.async_start(FEED_IN, 4000)
    await holds.async_start(ACTIVE, 70)
    await holds.async_stop(FEED_IN)
    await holds.async_stop(ACTIVE)

    assert _writes_to(writes, 40186) == [[4000, 0]]
    assert _writes_to(writes, 40192) == [[700], [1000]]


async def test_a_failed_start_keeps_the_current_hold(
    holds: SetpointHolds, mock_modbus_unit: MockModbusUnit, writes: list[WriteEvent]
) -> None:
    await holds.async_start(BATTERY, 1000)
    mock_modbus_unit.fail_write(register(40197), ModbusTimeoutError())

    with pytest.raises(ModbusTimeoutError):
        await holds.async_start(BATTERY, 2000)
    mock_modbus_unit.fail_write(register(40197), None)
    await holds.async_rewrite()

    assert holds.requested(BATTERY) == 1000
    assert _writes_to(writes, 40197)[-1] == [1000, 0]


async def test_a_half_written_start_ends_the_hold(
    holds: SetpointHolds,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await holds.async_start(BATTERY, 1000)
    _refuse_fc16(monkeypatch, mock_modbus_unit)
    mock_modbus_unit.fail_write(register(40198), ModbusTimeoutError())

    with pytest.raises(InconsistentWriteError):
        await holds.async_start(BATTERY, 3000)

    assert holds.get(BATTERY) is None
    assert holds.requested(BATTERY) == 1000


async def test_a_failing_rewrite_is_flagged_once_and_recovers(
    holds: SetpointHolds,
    mock_modbus_unit: MockModbusUnit,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    changes: list[None] = []
    holds._on_change = lambda: changes.append(None)
    await holds.async_start(BATTERY, 3000)
    mock_modbus_unit.fail_write(register(40197), ModbusTimeoutError())

    await holds.async_rewrite()
    await holds.async_rewrite()
    hold = holds.get(BATTERY)
    assert hold is not None
    assert hold.failing
    assert caplog.text.count("Could not rewrite battery_power") == 1

    mock_modbus_unit.fail_write(register(40197), None)
    await holds.async_rewrite()

    assert hold.confirmed
    assert "Rewriting battery_power works again" in caplog.text
    assert len(changes) == 3


async def test_the_first_transport_error_ends_the_pass(
    holds: SetpointHolds, mock_modbus_unit: MockModbusUnit, writes: list[WriteEvent]
) -> None:
    await holds.async_start(BATTERY, 3000)
    await holds.async_start(ACTIVE, 70)
    mock_modbus_unit.fail_write(register(40197), ModbusTimeoutError())
    writes.clear()

    await holds.async_rewrite()

    assert _writes_to(writes, 40192) == []


async def test_a_half_written_rewrite_ends_the_hold(
    holds: SetpointHolds,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await holds.async_start(BATTERY, 3000)
    _refuse_fc16(monkeypatch, mock_modbus_unit)
    mock_modbus_unit.fail_write(register(40198), ModbusTimeoutError())

    await holds.async_rewrite()

    assert holds.get(BATTERY) is None
    assert "Stopped holding battery_power after a half-written rewrite" in caplog.text


async def test_a_failed_release_is_retried(
    holds: SetpointHolds,
    mock_modbus_unit: MockModbusUnit,
    writes: list[WriteEvent],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    await holds.async_start(ACTIVE, 70)
    mock_modbus_unit.fail_write(register(40192), ModbusTimeoutError())

    with pytest.raises(ModbusTimeoutError):
        await holds.async_stop(ACTIVE)
    hold = holds.get(ACTIVE)
    assert hold is not None
    assert hold.releasing

    await holds.async_rewrite()
    assert holds.get(ACTIVE) is not None

    mock_modbus_unit.fail_write(register(40192), None)
    await holds.async_rewrite()

    assert holds.get(ACTIVE) is None
    assert _writes_to(writes, 40192)[-1] == [1000]
    assert "Released active_power_limit after an earlier failure" in caplog.text


async def test_a_failed_battery_release_is_dropped_after_the_watchdog(
    holds: SetpointHolds,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1000.0
    monkeypatch.setattr("e3dc_ess_modbus.holds.time.monotonic", lambda: now)
    await holds.async_start(BATTERY, 3000)
    mock_modbus_unit.fail_write(register(40199), ModbusTimeoutError())
    with pytest.raises(ModbusTimeoutError):
        await holds.async_stop(BATTERY)

    now += 29
    await holds.async_rewrite()
    assert holds.get(BATTERY) is not None

    now += 1
    await holds.async_rewrite()
    assert holds.get(BATTERY) is None


async def test_close_hands_back_and_refuses_new_holds(
    holds: SetpointHolds, writes: list[WriteEvent]
) -> None:
    await holds.async_start(BATTERY, 3000)

    await holds.async_close()
    with pytest.raises(HoldsClosedError):
        await holds.async_start(BATTERY, 3000)
    await holds.async_rewrite()

    assert _writes_to(writes, 40197) == [[3000, 0]]
    assert _writes_to(writes, 40199) == [[1]]


async def test_close_gives_up_on_a_dead_link(
    holds: SetpointHolds,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await holds.async_start(BATTERY, 3000)
    write_register = mock_modbus_unit.write_register

    async def hang(address: int, value: int) -> None:
        await asyncio.sleep(10)
        await write_register(address, value)

    monkeypatch.setattr(mock_modbus_unit, "write_register", hang)
    await holds.async_close(timeout=0.01)

    assert "Gave up handing setpoints back" in caplog.text


async def test_close_logs_a_failed_release(
    holds: SetpointHolds,
    mock_modbus_unit: MockModbusUnit,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await holds.async_start(BATTERY, 3000)
    mock_modbus_unit.fail_write(register(40199), ModbusTimeoutError())

    await holds.async_close()

    assert "Could not release battery_power" in caplog.text


async def test_a_stop_during_a_rewrite_is_not_undone(
    holds: SetpointHolds,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
    writes: list[WriteEvent],
) -> None:
    await holds.async_start(FEED_IN, 4000)
    await holds.async_start(BATTERY, 3000)
    write_registers = mock_modbus_unit.write_registers
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_feed_in(address: int, values: list[int]) -> None:
        if address == register(40186):
            started.set()
            await release.wait()
        await write_registers(address, values)

    monkeypatch.setattr(mock_modbus_unit, "write_registers", slow_feed_in)
    rewrite = asyncio.create_task(holds.async_rewrite())
    await started.wait()
    stop = asyncio.create_task(holds.async_stop(BATTERY))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(rewrite, stop)

    battery = [
        w.address for w in writes if w.address in (register(40197), register(40199))
    ]
    assert battery[-1] == register(40199)
    assert holds.get(BATTERY) is None


async def test_a_replacement_during_a_rewrite_wins(
    holds: SetpointHolds,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
    writes: list[WriteEvent],
) -> None:
    await holds.async_start(BATTERY, 3000)
    write_registers = mock_modbus_unit.write_registers
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def slow_first(address: int, values: list[int]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        await write_registers(address, values)

    monkeypatch.setattr(mock_modbus_unit, "write_registers", slow_first)
    rewrite = asyncio.create_task(holds.async_rewrite())
    await started.wait()
    replace = asyncio.create_task(holds.async_start(BATTERY, -2000))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(rewrite, replace)
    await holds.async_rewrite()

    assert _writes_to(writes, 40197)[-2:] == [[0xF830, 0xFFFF]] * 2


async def test_the_built_in_loop_rewrites_until_stopped(
    station: E3dcPowerStation, writes: list[WriteEvent]
) -> None:
    await station.async_ensure_setup()
    holds = SetpointHolds(station, interval=0.01)

    await holds.async_start(BATTERY, 3000)
    await asyncio.sleep(0.05)
    await holds.async_stop(BATTERY)
    rewrites = len(_writes_to(writes, 40197))
    await asyncio.sleep(0.05)

    assert rewrites >= 3
    assert len(_writes_to(writes, 40197)) == rewrites
    await holds.async_close()


async def test_closing_stops_the_built_in_loop(
    station: E3dcPowerStation, writes: list[WriteEvent]
) -> None:
    await station.async_ensure_setup()
    holds = SetpointHolds(station, interval=0.01)
    await holds.async_start(ACTIVE, 50)

    await holds.async_close()
    count = len(_writes_to(writes, 40192))
    await asyncio.sleep(0.05)

    assert len(_writes_to(writes, 40192)) == count
