import unittest

from fl_agent_desktop.stepseq_readback import format_stepseq_snapshot


class StepseqReadbackFormattingTests(unittest.TestCase):
    def test_format_snapshot_renders_tracks_and_params(self) -> None:
        lines = format_stepseq_snapshot(
            "After write",
            {
                "ok": True,
                "result": {
                    "pat_num": 3,
                    "total_steps": 16,
                    "max_param_steps": 16,
                    "tracks": [
                        {
                            "name": "kick",
                            "channel": 0,
                            "on_steps": [0, 4, 8, 12],
                            "velocities": {"0": 123, "4": 119},
                        },
                        {
                            "name": "bass",
                            "channel": 4,
                            "on_steps": [0, 8],
                            "pitches": {"0": 38, "8": 45},
                        },
                    ],
                },
            },
        )
        self.assertEqual(lines[0], "After write: pattern 3 | steps 16 | param steps 16")
        self.assertTrue(any(line.startswith("kick ") for line in lines))
        self.assertIn("  vel   0:123, 4:119", lines)
        self.assertIn("  pitch 0:38, 8:45", lines)

    def test_format_snapshot_handles_error_payload(self) -> None:
        lines = format_stepseq_snapshot("Before write", {"ok": False, "error": "Unknown op: get_stepseq"})
        self.assertEqual(lines[0], "Before write: unavailable")
        self.assertIn("error: Unknown op: get_stepseq", lines)


if __name__ == "__main__":
    unittest.main()
