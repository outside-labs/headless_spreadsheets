"""Public package metadata."""

import unittest

import headless_spreadsheets


class PackageTests(unittest.TestCase):
    def test_public_version(self):
        self.assertEqual(headless_spreadsheets.__version__, "0.1.0")
