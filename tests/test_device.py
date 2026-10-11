from __future__ import annotations

import asyncio

import pytest
from modbus_connection import (
    IllegalDataAddressError,
    ModbusConnectionError,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusUnit

from e3dc_ess_modbus import (
    E3dcError,
    E3dcPowerStation,
    EmergencyPowerStatus,
    EmsStatus,
    InverterMode,
    Inverters,
    NotAnE3dcError,
    PowerMeterType,
)
from e3dc_ess_modbus.model import register

from .conftest import FIRMWARE, MODEL, SERIAL, seed


async def test_detect_reads_the_identity(mock_modbus_unit: MockModbusUnit) -> None:
    seed(mock_modbus_unit)
    station = await E3dcPowerStation.async_detect(mock_modbus_unit)

    assert station.serial_number == SERIAL
    assert station.model == MODEL
    assert station.identity.manufacturer == "HagerEnergy GmbH"
    assert station.identity.firmware_release == FIRMWARE
    assert station.identity.modbus_version == "2.3"
    assert station.identity.register_count == 210


async def test_detect_rejects_a_device_without_the_magic(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    seed(mock_modbus_unit, {40001: 0x5375})  # the first SunSpec word
    with pytest.raises(NotAnE3dcError, match="0x5375"):
        await E3dcPowerStation.async_detect(mock_modbus_unit)


async def test_setup_rejects_a_device_without_the_magic(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    station = E3dcPowerStation(mock_modbus_unit)
    with pytest.raises(NotAnE3dcError, match="nothing|0x0000"):
        await station.async_update()


async def test_asks_for_the_manuals_request_rate(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    E3dcPowerStation(mock_modbus_unit, timeout=5)

    assert mock_modbus_unit.message_spacing == 0.1
    assert mock_modbus_unit.required_timeout == 5


async def test_power_flows(station: E3dcPowerStation) -> None:
    report = await station.async_update_readings()

    assert report.complete
    power = station.power
    assert power.pv_power == 5321
    assert power.battery_power == -1200
    assert power.house_power == 870
    assert power.grid_power == -600
    assert power.wallbox_power == 11000
    assert power.wallbox_solar_power == 4200
    assert power.autarky == 26
    assert power.self_consumption == 82
    assert power.battery_soc == 87
    assert power.emergency_power_status is EmergencyPowerStatus.INACTIVE
    assert (
        power.ems_status == EmsStatus.EMERGENCY_POWER_READY | EmsStatus.FEED_IN_LIMITED
    )


async def test_dc_strings(station: E3dcPowerStation) -> None:
    await station.async_update_readings()

    first, second, third = station.dc_strings
    assert (first.voltage, first.current, first.power) == (612, 4.5, 2754)
    assert (second.voltage, second.current, second.power) == (598, 4.3, 2571)
    assert (third.voltage, third.current, third.power) == (0, 0, 0)


async def test_wallboxes(station: E3dcPowerStation) -> None:
    await station.async_update_readings()

    [(number, wallbox)] = station.wallboxes.configured
    assert number == 0
    assert wallbox.solar_mode is True
    assert wallbox.charging_aborted is False
    assert wallbox.charging is True
    assert wallbox.type2_locked is True
    assert wallbox.type2_plugged is True
    assert wallbox.one_phase is False
    assert station.wallboxes.slots[1].available is False


async def test_wallbox_writes_change_only_their_bit(
    station: E3dcPowerStation, mock_modbus_unit: MockModbusUnit
) -> None:
    await station.async_update_readings()
    wallbox = station.wallboxes.slots[0]

    await wallbox.async_write_charging(False)
    assert mock_modbus_unit.holding[register(40088)] == 0b0000000111111
    await wallbox.async_write_one_phase(True)
    assert mock_modbus_unit.holding[register(40088)] == 0b1000000111111
    await wallbox.async_write_solar_mode(False)
    assert mock_modbus_unit.holding[register(40088)] == 0b1000000111101


async def test_power_meters_prefer_the_32_bit_powers(
    station: E3dcPowerStation,
) -> None:
    await station.async_update_readings()

    root = station.power_meter(0)
    assert root.meter_type is PowerMeterType.ROOT
    assert root.is_installed
    assert (root.power_l1, root.power_l2, root.power_l3) == (-40000, 150, 100)
    assert not station.power_meter(1).is_installed
    assert station.power_meter(2).meter_type is None
    assert station.wide_power_meters is not None
    assert station.wide_power_meters.sg_ready_status == 1


async def test_power_meters_fall_back_to_16_bits(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    seed(mock_modbus_unit)
    mock_modbus_unit.fail_read(register(40137), IllegalDataAddressError())
    station = E3dcPowerStation(mock_modbus_unit)
    await station.async_update_readings()

    assert station.wide_power_meters is None
    assert "wide_power_meters" not in station.readings_components
    root = station.power_meter(0)
    assert (root.power_l1, root.power_l2, root.power_l3) == (-200, 150, 100)


def test_power_meter_numbers_are_checked(station: E3dcPowerStation) -> None:
    with pytest.raises(ValueError, match="no power meter 8"):
        station.power_meter(8)


async def test_every_answering_inverter_slot_is_kept(
    station: E3dcPowerStation,
) -> None:
    await station.async_update_readings()

    assert list(station.inverters or ()) == list(range(8))
    assert not _inverters(station)[1].is_connected
    inverter = _inverters(station)[0]
    assert inverter.is_connected
    assert inverter.apparent_power_l1 == 1800
    assert inverter.active_power_l1 == 1750
    assert inverter.voltage_l1 == 230.1
    assert inverter.current_l1 == 7.83
    assert inverter.frequency == 50.01
    assert inverter.dc_power_1 == 2754
    assert inverter.dc_voltage_1 == 612.0
    assert inverter.dc_current_1 == 4.5


async def test_an_inverter_offline_at_setup_connects_later(
    station: E3dcPowerStation, mock_modbus_unit: MockModbusUnit
) -> None:
    await station.async_update_readings()
    assert not _inverters(station)[1].is_connected

    seed(mock_modbus_unit, {41034 + 18: 2302})
    await station.async_update_readings()

    assert _inverters(station)[1].is_connected
    assert _inverters(station)[1].voltage_l1 == 230.2


async def test_a_refused_inverter_slot_is_dropped(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    seed(mock_modbus_unit)
    mock_modbus_unit.fail_read(register(41000 + 7 * 34), IllegalDataAddressError())
    station = E3dcPowerStation(mock_modbus_unit)
    await station.async_update_readings()

    assert list(station.inverters or ()) == list(range(7))


async def test_battery_limits(station: E3dcPowerStation) -> None:
    await station.async_update_readings()

    limits = station.battery_limits
    assert limits is not None
    assert limits.max_charge_power == 9000
    assert limits.max_discharge_power == -9000
    assert limits.remaining_energy == 7800
    assert limits.full_charge_energy == 10500


async def test_settings(station: E3dcPowerStation) -> None:
    report = await station.async_update_settings()

    assert report.updated == {
        "grid_control",
        "battery_control",
        "inverter_mode_control",
    }
    grid = station.grid_control
    battery = station.battery_control
    mode = station.inverter_mode_control
    assert grid is not None
    assert battery is not None
    assert mode is not None
    assert grid.feed_in_limit == 5000
    assert grid.power_output_ready is True
    assert grid.active_power_failsafe_timeout == 30
    assert grid.reactive_power_failsafe_timeout == 45
    assert battery.remote_control_disabled is False
    assert mode.inverter_mode is InverterMode.IDLE_OFF_GRID_POWER_SAVE


async def test_settings_never_read_write_only_registers(
    station: E3dcPowerStation, mock_modbus_unit: MockModbusUnit
) -> None:
    await station.async_ensure_setup()
    mock_modbus_unit.read_events.clear()
    await station.async_update_settings()

    write_only = {register(n) for n in (*range(40189, 40194), 40195, 40197, 40198)}
    for event in mock_modbus_unit.read_events:
        read = set(range(event.address, event.address + event.count))
        assert not read & write_only


async def test_old_firmware_has_no_control_blocks(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    seed(mock_modbus_unit)
    for index in (40186, 40199, 40200, 40202):
        mock_modbus_unit.fail_read(register(index), IllegalDataAddressError())
    station = E3dcPowerStation(mock_modbus_unit)
    report = await station.async_update()

    assert report.complete
    assert station.settings_components == ()
    assert "battery_limits" not in station.readings_components


@pytest.mark.parametrize(
    ("refused", "settings", "battery_limits"),
    [
        pytest.param(
            (40200,),
            ("grid_control", "battery_control"),
            True,
            id="battery_control_without_inverter_mode",
        ),
        pytest.param(
            (40199, 40200),
            ("grid_control",),
            True,
            id="battery_limits_without_battery_control",
        ),
        pytest.param(
            (40202,),
            ("grid_control", "battery_control", "inverter_mode_control"),
            False,
            id="battery_control_without_battery_limits",
        ),
    ],
)
async def test_partial_firmware(
    mock_modbus_unit: MockModbusUnit,
    refused: tuple[int, ...],
    settings: tuple[str, ...],
    battery_limits: bool,
) -> None:
    seed(mock_modbus_unit)
    for index in refused:
        mock_modbus_unit.fail_read(register(index), IllegalDataAddressError())
    station = E3dcPowerStation(mock_modbus_unit)
    report = await station.async_update()

    assert report.complete
    assert station.settings_components == settings
    assert ("battery_limits" in station.readings_components) is battery_limits


async def test_a_failed_component_keeps_the_rest(
    station: E3dcPowerStation, mock_modbus_unit: MockModbusUnit
) -> None:
    await station.async_update_readings()
    mock_modbus_unit.fail_read(register(40105), IllegalDataAddressError())
    report = await station.async_update_readings()

    assert set(report.failed) == {"power_meters"}
    assert "power" in report.updated


async def test_a_dead_link_raises(
    station: E3dcPowerStation, mock_modbus_unit: MockModbusUnit
) -> None:
    await station.async_update_readings()
    mock_modbus_unit.fail_requests(ModbusConnectionError())
    with pytest.raises(ModbusConnectionError):
        await station.async_update_readings()


async def test_a_silent_device_raises(
    station: E3dcPowerStation, mock_modbus_unit: MockModbusUnit
) -> None:
    await station.async_update_readings()
    mock_modbus_unit.fail_requests(ModbusTimeoutError())
    with pytest.raises(ModbusTimeoutError):
        await station.async_update_readings()


async def test_a_poll_costs_one_read_per_block(
    station: E3dcPowerStation, mock_modbus_unit: MockModbusUnit
) -> None:
    await station.async_ensure_setup()
    mock_modbus_unit.read_events.clear()
    await station.async_update_readings()

    # power, DC strings, wallboxes, meters, wide meters, battery limits, and
    # three reads for the eight inverter slots
    assert len(mock_modbus_unit.read_events) == 9


async def test_raw_dump_covers_every_component(
    station: E3dcPowerStation,
) -> None:
    raw = await station.async_read_raw()

    holding = raw["holding"]
    for index in (40001, 40068, 40088, 40096, 40105, 40137, 40186, 40199, 40202, 41000):
        assert register(index) in holding


def _with_magic() -> dict[int, int | list[int]]:
    return {40001: 0xE3DC}


def _inverters(station: E3dcPowerStation) -> Inverters:
    assert station.inverters is not None
    return station.inverters


async def test_stale_32_bit_meter_values_lose(
    station: E3dcPowerStation, mock_modbus_unit: MockModbusUnit
) -> None:
    await station.async_update_readings()
    assert station.power_meter(0).power_l1 == -40000

    mock_modbus_unit.fail_read(register(40137), IllegalDataAddressError())
    await station.async_update_readings()

    assert station.power_meter(0).power_l1 == -200


async def test_concurrent_polls_set_up_once(
    station: E3dcPowerStation, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    setup = station._async_setup

    async def counted() -> None:
        nonlocal calls
        calls += 1
        # Let the other poll run while this setup is in progress
        await asyncio.sleep(0)
        await setup()

    monkeypatch.setattr(station, "_async_setup", counted)
    await asyncio.gather(
        station.async_update_readings(), station.async_update_settings()
    )

    assert calls == 1


async def test_detect_maps_a_refused_identity_to_not_an_e3dc(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.fail_read(register(40001), IllegalDataAddressError())
    with pytest.raises(NotAnE3dcError) as err:
        await E3dcPowerStation.async_detect(mock_modbus_unit)

    assert err.value.magic is None
    assert isinstance(err.value, E3dcError)


async def test_leaves_the_timeout_alone_without_one(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    E3dcPowerStation(mock_modbus_unit)

    assert mock_modbus_unit.required_timeout is None
