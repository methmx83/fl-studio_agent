import unittest

from fl_agent_desktop.pattern_preview import pattern_preview_lines


class PatternPreviewTests(unittest.TestCase):
    def test_preview_starts_with_header(self) -> None:
        lines = pattern_preview_lines("rock", bars=1)
        self.assertEqual(lines[0], "Style: rock | Bars: 1 | Steps/Bar: 16")

    def test_preview_includes_core_tracks(self) -> None:
        lines = pattern_preview_lines("house", bars=1)
        self.assertTrue(any(line.startswith("Kick ") for line in lines))
        self.assertTrue(any(line.startswith("Snare") for line in lines))
        self.assertTrue(any(line.startswith("Hat  ") for line in lines))

    def test_preview_uses_bar_separators_for_multiple_bars(self) -> None:
        lines = pattern_preview_lines("hiphop", bars=2)
        kick_line = next(line for line in lines if line.startswith("Kick "))
        self.assertIn(" | ", kick_line)


if __name__ == "__main__":
    unittest.main()
