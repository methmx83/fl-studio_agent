import unittest

from fl_agent_desktop.ui_state import mapping_label_text, resolved_loop_settings


class MappingLabelTextTests(unittest.TestCase):
    def test_zero_based_mapping_label_uses_internal_channel_value(self) -> None:
        self.assertEqual(mapping_label_text("kick", {"kick": 0}, False), "channel 0")

    def test_one_based_mapping_label_shows_configured_and_internal_values(self) -> None:
        self.assertEqual(mapping_label_text("snare", {"snare": 4}, True), "configured 4 → internal 3")

    def test_missing_mapping_label_reports_not_mapped(self) -> None:
        self.assertEqual(mapping_label_text("bass", {}, False), "not mapped")


class ResolvedLoopSettingsTests(unittest.TestCase):
    def test_plan_values_override_current_ui_values(self) -> None:
        current = (94.0, "rock", 1)
        self.assertEqual(resolved_loop_settings(current, 128.0, "house", 4), (128.0, "house", 4))

    def test_missing_plan_values_fall_back_to_current_ui_values(self) -> None:
        current = (92.0, "hiphop", 2)
        self.assertEqual(resolved_loop_settings(current, None, None, None), current)

    def test_partial_plan_only_overrides_provided_fields(self) -> None:
        current = (140.0, "trap", 1)
        self.assertEqual(resolved_loop_settings(current, None, "rock", 8), (140.0, "rock", 8))


if __name__ == "__main__":
    unittest.main()
