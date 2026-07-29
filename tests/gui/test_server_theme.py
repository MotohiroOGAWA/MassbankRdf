from __future__ import annotations

import unittest

from massbank_rdf.gui.server import APP_LAYOUT_STYLES


class TestServerTheme(unittest.TestCase):
    def test_layout_forces_light_color_scheme(self) -> None:
        self.assertIn("color-scheme: light !important", APP_LAYOUT_STYLES)
        self.assertIn("background: #ffffff !important", APP_LAYOUT_STYLES)


if __name__ == "__main__":
    unittest.main()
