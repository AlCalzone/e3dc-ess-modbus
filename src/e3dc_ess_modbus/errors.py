"""The errors the library raises itself.

Transport and device errors arrive as modbus-connection's ``ModbusError``.
"""

from __future__ import annotations


class E3dcError(Exception):
    """The base of the errors this library raises itself."""


class NotAnE3dcError(E3dcError):
    """The device answered, but not as an E3/DC power station in E3DC mode."""

    def __init__(self, magic: int | None) -> None:
        """Initialize the error."""
        shown = "nothing" if magic is None else f"0x{magic:04X}"
        super().__init__(
            f"register 40001 holds {shown}, not 0xE3DC: "
            "is Modbus set to the E3/DC protocol?"
        )
        self.magic = magic


class InvalidValueError(E3dcError, ValueError):
    """A value to write is out of range or of the wrong type. Nothing was sent."""


class InconsistentWriteError(E3dcError):
    """Half of a two-register setpoint was written, and the other half failed.

    The register pair holds the new low word next to the old high word until
    the setpoint lapses or is written again.
    """
