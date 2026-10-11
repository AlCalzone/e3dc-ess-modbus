"""Fixtures: an E3/DC power station on modbus-connection's in-memory mock."""

from __future__ import annotations

import pytest
from modbus_connection.mock import MockModbusUnit

from e3dc_ess_modbus import E3dcPowerStation
from e3dc_ess_modbus.model import register


def ascii_words(text: str, length: int) -> list[int]:
    """Pack ASCII into ``length`` registers, two characters each (hi, lo)."""
    padded = text.ljust(length * 2, "\0")[: length * 2]
    return [(ord(padded[i]) << 8) | ord(padded[i + 1]) for i in range(0, length * 2, 2)]


def int32_words(value: int) -> list[int]:
    """An int32 as E3/DC sends it, low word first."""
    raw = value & 0xFFFFFFFF
    return [raw & 0xFFFF, raw >> 16]


SERIAL = "S10-12345678912"
MODEL = "S10 X"
FIRMWARE = "S10_2026_04"

# Keys are the manual's register numbers; ``seed`` shifts them to addresses.
HOLDING: dict[int, int | list[int]] = {
    # -- identity --
    40001: 0xE3DC,
    40002: 0x0203,  # Modbus interface 2.3
    40003: 210,
    40004: ascii_words("HagerEnergy GmbH", 16),
    40020: ascii_words(MODEL, 16),
    40036: ascii_words(SERIAL, 16),
    40052: ascii_words(FIRMWARE, 16),
    # -- power flows --
    40068: int32_words(5321),  # PV
    40070: int32_words(-1200),  # battery, discharging
    40072: int32_words(870),  # house
    40074: int32_words(-600),  # grid, feeding in (the manual's own example)
    40076: int32_words(0),
    40078: int32_words(11000),  # wallbox
    40080: int32_words(4200),  # wallbox solar share
    40082: 6738,  # autarky 26 %, self-consumption 82 % (the manual's example)
    40083: 87,  # SoC
    40084: 2,  # emergency power not active
    40085: 0b0010100,  # emergency power ready, feed-in limited
    # -- wallboxes: slot 0 an easy connect charging on three phases --
    40088: 0b0000000111011,  # available, solar, charging, locked, plugged
    # -- DC strings --
    40096: 612,
    40097: 598,
    40099: 450,  # 4.50 A
    40100: 430,
    40102: 2754,
    40103: 2571,
    # -- power meters: slot 0 the root meter, slot 1 unused --
    40105: 1,
    40106: 0xFF38,  # -200 W
    40107: 150,
    40108: 100,
    40109: 6,
    # -- 32-bit phase powers --
    40137: 1,  # SG Ready
    40138: int32_words(-40000),
    40140: int32_words(150),
    40142: int32_words(100),
    # -- remote control --
    40186: int32_words(5000),
    40188: 1,
    40194: 30,
    40196: 45,
    40199: 0,
    40200: 0,
    40201: 10,
    # -- battery limits --
    40202: int32_words(9000),
    40204: int32_words(-9000),
    40206: int32_words(7800),
    40208: int32_words(10500),
    # -- inverter 0 --
    41000: int32_words(1800),
    41006: int32_words(1750),
    41018: 2301,
    41019: 2299,
    41020: 2310,
    41021: 783,  # 7.83 A
    41024: 5001,  # 50.01 Hz
    41025: 2754,
    41028: 6120,  # 612.0 V
    41031: 450,
}


def seed(unit: MockModbusUnit, holding: dict[int, int | list[int]] = HOLDING) -> None:
    """Load register values, given by the manual's numbering, into the mock."""
    for index, value in holding.items():
        unit.holding[register(index)] = value


@pytest.fixture
def station(mock_modbus_unit: MockModbusUnit) -> E3dcPowerStation:
    """A current S10 X with every block of the 2026_04 firmware."""
    seed(mock_modbus_unit)
    return E3dcPowerStation(mock_modbus_unit)
