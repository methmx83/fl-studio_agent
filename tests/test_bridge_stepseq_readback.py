import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = ROOT / "fl_bridge" / "device_fl_studio_agent.py"


def load_bridge_module():
    fake_channels = types.ModuleType("channels")
    grid = {
        (0, 0): True,
        (0, 4): True,
        (4, 0): True,
        (4, 8): True,
    }
    params = {
        (0, 0, 0): 60,
        (0, 0, 1): 123,
        (0, 4, 0): 60,
        (0, 4, 1): 110,
        (4, 0, 0): 38,
        (4, 0, 1): 100,
        (4, 8, 0): 45,
        (4, 8, 1): 96,
    }

    def get_grid_bit(index, position, useGlobalIndex=False):  # noqa: N803
        return grid.get((index, position), False)

    def get_current_step_param(index, step, param, useGlobalIndex=False):  # noqa: N803
        return params[(index, step, param)]

    fake_channels.getGridBit = get_grid_bit
    fake_channels.getCurrentStepParam = get_current_step_param

    fake_device = types.ModuleType("device")
    fake_device.midiOutSysex = lambda payload: None
    fake_device.getPortNumber = lambda: 0

    fake_mixer = types.ModuleType("mixer")
    fake_mixer.getCurrentTempo = lambda: 128000

    fake_patterns = types.ModuleType("patterns")
    fake_patterns.patternNumber = lambda: 2
    fake_patterns.getPatternLength = lambda pattern: 4

    saved = {}
    for name, module in {
        "channels": fake_channels,
        "device": fake_device,
        "mixer": fake_mixer,
        "patterns": fake_patterns,
    }.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module

    try:
        spec = importlib.util.spec_from_file_location("test_fl_bridge_device", BRIDGE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved.items():
            if previous is None:
                del sys.modules[name]
            else:
                sys.modules[name] = previous


class BridgeStepseqReadbackTests(unittest.TestCase):
    def test_get_stepseq_returns_grid_bits_and_step_params(self) -> None:
        bridge = load_bridge_module()
        result = bridge._parse_and_dispatch(
            {
                "op": "get_stepseq",
                "args": {
                    "tracks": [{"name": "kick", "channel": 0}, {"name": "bass", "channel": 4}],
                    "total_steps": 16,
                },
            }
        )

        self.assertTrue(result["ok"])
        payload = result["result"]
        self.assertEqual(payload["pat_num"], 2)
        self.assertEqual(payload["total_steps"], 16)
        self.assertEqual(payload["pattern_len_beats"], 4)
        self.assertEqual(payload["tracks"][0]["on_steps"], [0, 4])
        self.assertEqual(payload["tracks"][0]["velocities"], {"0": 123, "4": 110})
        self.assertEqual(payload["tracks"][1]["pitches"], {"0": 38, "8": 45})

    def test_get_stepseq_switches_to_requested_pattern_and_restores_previous(self) -> None:
        jumps: list[int] = []

        fake_channels = types.ModuleType("channels")
        fake_channels.getGridBit = lambda index, position, useGlobalIndex=False: False  # noqa: ARG005,N803
        fake_channels.getCurrentStepParam = lambda index, step, param, useGlobalIndex=False: 0  # noqa: ARG005,N803

        fake_device = types.ModuleType("device")
        fake_device.midiOutSysex = lambda payload: None
        fake_device.getPortNumber = lambda: 0

        fake_mixer = types.ModuleType("mixer")
        fake_mixer.getCurrentTempo = lambda: 128000

        state = {"current": 2}
        fake_patterns = types.ModuleType("patterns")
        fake_patterns.patternNumber = lambda: state["current"]
        fake_patterns.getPatternLength = lambda pattern: 4

        def jump_to_pattern(index):
            jumps.append(index)
            state["current"] = int(index)

        fake_patterns.jumpToPattern = jump_to_pattern

        saved = {}
        for name, module in {
            "channels": fake_channels,
            "device": fake_device,
            "mixer": fake_mixer,
            "patterns": fake_patterns,
        }.items():
            saved[name] = sys.modules.get(name)
            sys.modules[name] = module

        try:
            spec = importlib.util.spec_from_file_location("test_fl_bridge_pattern_switch", BRIDGE_PATH)
            assert spec is not None and spec.loader is not None
            bridge = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bridge)
            result = bridge._parse_and_dispatch(
                {"op": "get_stepseq", "args": {"tracks": [{"channel": 0}], "pattern_index": 7, "total_steps": 16}}
            )
        finally:
            for name, previous in saved.items():
                if previous is None:
                    del sys.modules[name]
                else:
                    sys.modules[name] = previous

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["pat_num"], 7)
        self.assertEqual(jumps, [7, 2])


if __name__ == "__main__":
    unittest.main()
