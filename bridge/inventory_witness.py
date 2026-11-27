"""Validate native current-player inventory payloads and keyed shortcuts; no world attestation."""

from copy import deepcopy

from load_witness import LoadStateFile, _integer, _slot, _state, main


SCOPE = 'load_header_and_inventory_detail'
DETAIL_FIELDS = {'last_weapon_type', 'stock', 'inner', 'extra'}
PRIMITIVE_FIELDS = {'item_id', 'weapon_type', 'weapon_parts', 'bullet_id', 'number'}
EXTRA_INTEGERS = {'item_id', 'rogue_weapon_level', 'initial_count'}


def _absent(value):
    return isinstance(value, dict) and set(value) == {'present'} and value['present'] is False


def _payload(value, *, extra=False):
    if _absent(value):
        return
    fields = EXTRA_INTEGERS | {'uint_data', 'initial_set'} if extra else PRIMITIVE_FIELDS
    if (not isinstance(value, dict) or set(value) != fields | {'present'} or value['present'] is not True
            or any(not _integer(value[name], -(2**31), 2**32 - 1)
                   for name in (EXTRA_INTEGERS if extra else PRIMITIVE_FIELDS))
            or extra and (not _integer(value['uint_data'], 0, 2**32 - 1) or type(value['initial_set']) is not bool)):
        raise ValueError('invalid native item payload')


def _detail(slot):
    if _absent(slot):
        return
    if not isinstance(slot, dict) or not DETAIL_FIELDS <= slot.keys():
        raise ValueError('missing native inventory details')
    if not _integer(slot['last_weapon_type'], -(2**31), 2**32 - 1):
        raise ValueError('invalid native last weapon type')
    _payload(slot['inner'])
    _payload(slot['extra'], extra=True)
    stock = slot['stock']
    if _absent(stock):
        return
    if (not isinstance(stock, dict) or set(stock) != {
            'present', 'index', 'weapon_equipped', 'default_item', 'additional_item', 'extra'}
            or stock['present'] is not True or not _integer(stock['index'], -(2**31), 2**31 - 1)
            or type(stock['weapon_equipped']) is not bool):
        raise ValueError('invalid native stock payload')
    _payload(stock['default_item'])
    _payload(stock['additional_item'])
    _payload(stock['extra'], extra=True)


def _inventory_state(value):
    if not isinstance(value, dict) or set(value) != {'checkpoint', 'inventory'}:
        raise ValueError('invalid detailed inventory state')
    inventory = value['inventory']
    if not isinstance(inventory, dict) or 'shortcuts' not in inventory:
        raise ValueError('missing native shortcuts')
    # Reuse the unchanged core contract after removing only the explicitly added fields.
    core = deepcopy(value)
    del core['inventory']['shortcuts']
    slots, equipped = inventory.get('slots'), inventory.get('equipped')
    if slots is None and inventory.get('slot_count') == 0:
        inventory['slots'] = slots = []
        core['inventory']['slots'] = []
    if not isinstance(slots, list) or not isinstance(equipped, dict):
        raise ValueError('invalid native detailed slots')
    for slot in slots + list(equipped.values()):
        _detail(slot)
    for slot in core['inventory']['slots'] + list(core['inventory']['equipped'].values()):
        if not _absent(slot):
            for name in DETAIL_FIELDS:
                del slot[name]
    _state(core)
    shortcuts = inventory['shortcuts']
    if not isinstance(shortcuts, dict) or set(shortcuts) != {'main', 'sub'}:
        raise ValueError('invalid native shortcut groups')
    for group in shortcuts.values():
        if (not isinstance(group, dict) or set(group) != {'count', 'entries'}
                or not _integer(group['count'], 0, 4)):
            raise ValueError('invalid native shortcut count')
        if group['count'] == 0 and group['entries'] is None:
            group['entries'] = []
        entries = group['entries']
        if not isinstance(entries, list) or len(entries) != group['count']:
            raise ValueError('native shortcut count mismatch')
        previous = -1
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {'key', 'slot'}
                    or not _integer(entry['key'], previous + 1, 3)):
                raise ValueError('invalid or unordered native shortcut key')
            previous = entry['key']
            _detail(entry['slot'])
            # A present dictionary entry must contain a real slot, including blank slots.
            core_slot = {key: data for key, data in entry['slot'].items() if key not in DETAIL_FIELDS}
            _slot(core_slot)


class InventoryStateFile(LoadStateFile):
    """Fresh native inventory details and shortcuts, bound to the existing guarded load receipt."""

    filename = 're2_coop_inventory_state.json'
    scope = SCOPE
    validate_state = staticmethod(_inventory_state)


if __name__ == '__main__':
    raise SystemExit(main(InventoryStateFile))
