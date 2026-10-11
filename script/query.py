#!/usr/bin/env python3

"""Query an E3/DC home power station and print every value."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from modbus_connection import ModbusError
from modbus_connection.cli_helper import (
    CountingUnit,
    add_connection_args,
    connect_from_args,
    print_component,
)

from e3dc_ess_modbus import E3dcPowerStation, NotAnE3dcError

# E3/DC speaks Modbus TCP only, and answers on unit 1.
CONNECTIONS = (("tcp", None),)

EXAMPLES = """examples:
  uv run script/query.py 192.168.1.50
  uv run script/query.py 192.168.1.50 --port 5020 --raw
"""


def print_station(station: E3dcPowerStation) -> None:
    """Print each component the station serves, under its attribute name."""
    print_component(station.identity, title="identity")
    print()
    print_component(station.power, title="power")
    for number, string in enumerate(station.dc_string_list, start=1):
        print()
        print_component(string, title=f"dc_string_{number}")
    for number, wallbox in station.wallboxes.available:
        print()
        print_component(wallbox, title=f"wallbox_{number}")
    for number in range(len(station.power_meters.meters)):
        meter = station.power_meter(number)
        if not meter.is_installed:
            continue
        title = f"power_meter_{number}"
        meter_type = meter.meter_type.name.lower() if meter.meter_type else None
        print(f"\n{title}\n{'-' * len(title)}")
        print(f"  meter_type  {meter_type}")
        for phase in ("l1", "l2", "l3"):
            print(f"  power_{phase}    {getattr(meter, f'power_{phase}')} W")
    if station.wide_power_meters is not None:
        print(f"\nsg_ready_status  {station.wide_power_meters.sg_ready_status}")
    for number, inverter in station.inverter_slots.items():
        print()
        print_component(inverter, title=f"inverter_{number}")
    for name in ("battery_limits", "grid_control", "battery_control"):
        if (component := getattr(station, name)) is not None:
            print()
            print_component(component, title=name)


async def main() -> int:
    """Read one power station and print it."""
    # The backend logs a failed connect at ERROR with its traceback; the
    # messages below say it in one line.
    logging.getLogger().addHandler(logging.NullHandler())

    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_connection_args(parser, connections=CONNECTIONS)
    parser.add_argument("--unit", type=int, default=1, help="Modbus unit id")
    parser.add_argument(
        "--raw", action="store_true", help="also dump every register read, as JSON"
    )
    args = parser.parse_args()

    try:
        connection = await connect_from_args(args)
    except ModbusError as err:
        # A connect timeout arrives with no message of its own.
        detail = str(err) or type(err).__name__
        print(f"Could not connect to {args.target}: {detail}")
        return 1

    counting = CountingUnit(connection.for_unit(args.unit))
    try:
        station = await E3dcPowerStation.async_detect(counting)
        report = await station.async_update()  # the first update sets it up
        # A raw dump re-reads everything, so count the poll alone.
        poll_reads = counting.reads
        raw = await station.async_read_raw() if args.raw else None
    except NotAnE3dcError as err:
        print(f"Not an E3/DC device: {err}")
        return 1
    except ModbusError as err:
        print(f"Could not read the power station: {str(err) or type(err).__name__}")
        return 1
    finally:
        await connection.close()

    print_station(station)
    if report.failed:
        print("\nFailed to read:")
        for name, error in report.failed.items():
            print(f"  {name}: {str(error) or type(error).__name__}")
    if raw is not None:
        print("\nRaw registers")
        # The dump arrives address-ordered; sorting keys would undo that.
        print(json.dumps(raw, indent=2))
    print(f"\n{poll_reads} Modbus reads")
    return 0


raise SystemExit(asyncio.run(main()))
