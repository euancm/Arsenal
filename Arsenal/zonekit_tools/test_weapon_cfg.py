"""Regression tests for weapon CFG helpers.

Run with Blender:
blender --background --factory-startup --python-exit-code 1 --python test_weapon_cfg.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from stalker2_arsenal.weapon_cfg import detect_magazines


class Mesh:
    def __init__(self, name):
        self.name = name


class DetectMagazinesTests(unittest.TestCase):
    def detect_single_magazine(self, name):
        return detect_magazines([(Mesh(name), ())])[0]

    def test_detects_qualifier_before_mag(self):
        magazine = self.detect_single_magazine('e9_increasedmag_full')
        self.assertEqual(magazine['name'], 'Increased')

    def test_detects_qualifier_after_mag(self):
        magazine = self.detect_single_magazine('e9_mag_increased_full')
        self.assertEqual(magazine['name'], 'Increased')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
