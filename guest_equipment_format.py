"""Validate the E1 inventory DTO exchanged with re2_coop/guest_equipment.lua."""

import re


MAX_BYTES = 16384
_INTEGER = re.compile(r'(?:0|-?[1-9][0-9]{0,9})')
_I32 = (-2**31, 2**31 - 1)
_WEAPON = (-1, 381)
_ITEM = (0, 296)
_INDEX = (-1, 19)


def valid_equipment(value):
    if (not isinstance(value, str) or len(value) > MAX_BYTES or not value.startswith('E1,')
            or not value.isascii()):
        return False
    fields = iter(value[3:].split(','))

    def number(low, high):
        token = next(fields)
        if not _INTEGER.fullmatch(token):
            raise ValueError
        result = int(token)
        if not low <= result <= high:
            raise ValueError
        return result

    def primitive():
        number(*_ITEM)
        number(*_WEAPON)
        number(0, 7)  # WeaponParts
        number(*_ITEM)  # BulletId
        number(*_I32)

    def stock():
        index = number(*_INDEX)
        number(0, 1)  # IsWeaponEquip
        primitive()
        if number(0, 1):  # AdditionalItem
            primitive()
        if number(0, 1):  # ExData
            number(0, 2**32 - 1)
            number(*_ITEM)
            number(*_I32)
            number(0, 1)
            number(*_I32)
        return index

    def shortcuts():
        previous = -1
        for _ in range(number(0, 4)):
            number(*_INDEX)
            number(*_WEAPON)
            kind = number(0, 3)
            if kind <= previous:
                raise ValueError
            previous = kind

    try:
        number(8, 20)  # CurrentSlotSize
        seen = set()
        for _ in range(number(0, 20)):
            index = stock()
            if index < 0 or index in seen:
                return False
            seen.add(index)
        number(*_INDEX)  # MainData
        number(*_WEAPON)
        number(*_WEAPON)  # SubData
        if number(0, 1):
            stock()
        shortcuts()
        shortcuts()
        return next(fields, None) is None
    except (StopIteration, ValueError):
        return False
