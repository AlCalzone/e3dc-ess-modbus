"""The component base the E3/DC register map builds on."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

from modbus_connection.model import Component, ComponentGroup, UpdateReport

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

__all__ = ["E3dcComponent", "NumberedComponents", "UpdateReport", "register"]


def register(index: int) -> int:
    """The protocol address of register ``index`` as the manual numbers it.

    The manual counts from 1, so its register 40001 is address 40000.
    """
    return index - 1


class E3dcComponent(Component):
    """A sub-system of the E3/DC Simple Mode register map."""


class NumberedComponents[C: Component](ComponentGroup, Mapping[int, C]):
    """Components read as one group, keyed by the manual's numbering."""

    # Compare and hash by identity, the way a component does
    __eq__ = object.__eq__
    __hash__ = object.__hash__

    def __init__(self, unit: ModbusUnit, members: dict[int, C]) -> None:
        """Set up the group over ``members``."""
        self._members = members
        super().__init__(unit, members.values())

    def __getitem__(self, number: int) -> C:
        """The component numbered ``number``."""
        return self._members[number]

    def __iter__(self) -> Iterator[int]:
        """The numbers, in order."""
        return iter(self._members)

    def __len__(self) -> int:
        """How many components the group has."""
        return len(self._members)
