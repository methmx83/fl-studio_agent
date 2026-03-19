import unittest

from fl_agent_desktop.parse import parse_command
from fl_studio_agent_mcp.patterns import normalize_key_scale, render_with_bassline


class ParseKeyScaleTests(unittest.TestCase):
    def test_parse_key_scale_from_in_phrase(self) -> None:
        cmd = parse_command("Create a 4/4 hiphop beat in D minor at 92 bpm")
        self.assertEqual(cmd.key, "D")
        self.assertEqual(cmd.scale, "minor")

    def test_parse_key_with_explicit_scale_keyword(self) -> None:
        cmd = parse_command("make a 4/4 trap loop key F# scale major")
        self.assertEqual(cmd.key, "F#")
        self.assertEqual(cmd.scale, "major")


class BasslinePlanTests(unittest.TestCase):
    def test_normalize_key_scale_handles_flats_and_aliases(self) -> None:
        self.assertEqual(normalize_key_scale("Bb", "maj"), ("A#", "major"))

    def test_render_with_bassline_attaches_note_events(self) -> None:
        pat = render_with_bassline("hiphop", total_steps=16, key="D", scale="minor")
        self.assertIsNotNone(pat.bass_notes)
        assert pat.bass_notes is not None
        self.assertGreaterEqual(len(pat.bass_notes), 1)
        self.assertEqual(pat.bass_notes[0].note, "D")


if __name__ == "__main__":
    unittest.main()
