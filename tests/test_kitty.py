import unittest

from newscli.app import _kitty_image_escape


class TestKittyEscape(unittest.TestCase):
    def test_kitty_escape_has_protocol_wrappers(self) -> None:
        data = b"\x89PNG\r\n\x1a\n" + b"x" * 100
        esc = _kitty_image_escape(data, cols=40, rows=10)
        self.assertIn("\x1b_G", esc)
        self.assertTrue(esc.endswith("\x1b\\"))


if __name__ == "__main__":
    unittest.main()

