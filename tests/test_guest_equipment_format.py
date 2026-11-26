import unittest

from guest_equipment_format import valid_equipment


EMPTY = 'E1,8,0,-1,-1,-1,0,0,0'
STOCK = '0,0,1,-1,0,0,12,0,0'


class GuestEquipmentFormatTests(unittest.TestCase):
    def test_empty_and_populated_inventory(self):
        self.assertTrue(valid_equipment(EMPTY))
        self.assertTrue(valid_equipment(f'E1,8,1,{STOCK},-1,-1,-1,0,0,0'))
        stock_with_extra = '2,1,1,-1,0,0,12,1,1,-1,0,0,3,1,4294967295,1,-2147483648,0,2147483647'
        self.assertTrue(valid_equipment(f'E1,20,1,{stock_with_extra},2,-1,-1,1,{STOCK},1,2,-1,0,1,-1,-1,0'))

    def test_excess_missing_and_noncanonical_tokens(self):
        for wire in (None, 12, EMPTY.encode(), 'E2' + EMPTY[2:], EMPTY + ',', EMPTY + ',0', EMPTY[:-2],
                     EMPTY.replace('8', '08'), EMPTY.replace('8', '+8'), EMPTY.replace('8', '٨'),
                     EMPTY.replace(',0,', ',-0,', 1), EMPTY.replace('8', '8.0'), EMPTY + '\n',
                     'E1,' + ','.join(['0'] * 8200)):
            with self.subTest(wire=str(wire)[:50]):
                self.assertFalse(valid_equipment(wire))

    def test_bounds_and_presence_flags(self):
        for wire in (EMPTY.replace('8', '7'), EMPTY.replace('8', '21'), EMPTY.replace(',0,', ',21,', 1),
                     'E1,8,0,20,-1,-1,0,0,0', 'E1,8,0,-1,-2,-1,0,0,0',
                     'E1,8,0,-1,-1,-1,2,0,0', 'E1,8,0,-1,-1,-1,0,5,0',
                     'E1,8,0,-1,-1,-1,0,1,0,-1,4,0',
                     *(f'E1,8,1,{stock},-1,-1,-1,0,0,0' for stock in (
                         '-1,0,1,-1,0,0,12,0,0', '0,2,1,-1,0,0,12,0,0',
                         '0,0,297,-1,0,0,12,0,0', '0,0,1,382,0,0,12,0,0',
                         '0,0,1,-1,8,0,12,0,0', '0,0,1,-1,0,297,12,0,0',
                         '0,0,1,-1,0,0,2147483648,0,0', '0,0,1,-1,0,0,12,0,1,4294967296,1,0,0,0'))):
            with self.subTest(wire=wire):
                self.assertFalse(valid_equipment(wire))

    def test_duplicate_stock_indices_and_shortcut_kinds(self):
        self.assertFalse(valid_equipment(f'E1,8,2,{STOCK},{STOCK},-1,-1,-1,0,0,0'))
        self.assertFalse(valid_equipment('E1,8,0,-1,-1,-1,0,2,0,-1,0,1,-1,0,0'))
        self.assertFalse(valid_equipment('E1,8,0,-1,-1,-1,0,0,2,0,-1,0,1,-1,0'))

    def test_shortcut_lists_have_the_same_stable_order_as_native_capture(self):
        self.assertTrue(valid_equipment('E1,8,0,-1,-1,-1,0,2,0,-1,0,1,-1,2,0'))
        self.assertFalse(valid_equipment('E1,8,0,-1,-1,-1,0,2,0,-1,2,1,-1,0,0'))
        self.assertFalse(valid_equipment('E1,8,0,-1,-1,-1,0,0,2,0,-1,2,1,-1,0'))
