"""Test P0 WS-E1: export_profile puro (nessun ffmpeg, nessuna rete)."""

import os
import unittest

from core.export_profile import (
    build_video_encode_args,
    color_convert_filter,
    color_tag_args,
    get_export_profile,
    grain_filter,
    legacy_encode_args,
)


class TestExportProfile(unittest.TestCase):
    def test_profili(self):
        for q, preset, crf in (("draft", "ultrafast", 23), ("standard", "medium", 18),
                               ("final", "slow", 17)):
            p = get_export_profile(q)
            self.assertEqual(p["preset"], preset)
            self.assertEqual(p["crf"], crf)
            args = build_video_encode_args(p)
            self.assertIn("-profile:v", args)
            self.assertIn("high", args)
            self.assertIn("-level", args)
            self.assertIn("bt709", args)
            self.assertIn("aac", args)

    def test_default_final(self):
        p = get_export_profile(None)
        self.assertEqual(p["name"], "final")

    def test_qualita_ignota_fallback_final(self):
        p = get_export_profile("xyz")
        self.assertEqual(p["name"], "final")

    def test_override_ffmpeg_preset(self):
        old = os.environ.get("FFMPEG_PRESET")
        os.environ["FFMPEG_PRESET"] = "ultrafast"
        try:
            p = get_export_profile("final")
            self.assertEqual(p["preset"], "ultrafast")
        finally:
            if old is None:
                os.environ.pop("FFMPEG_PRESET", None)
            else:
                os.environ["FFMPEG_PRESET"] = old

    def test_args_identici_builder_composer(self):
        # Stessi argomenti per entrambi i path (unica fonte di verità).
        p = get_export_profile("final")
        a = build_video_encode_args(p)
        b = build_video_encode_args(dict(p))
        self.assertEqual(a, b)
        self.assertIn("60", a)  # GOP
        self.assertIn("+faststart", a)

    def test_legacy(self):
        args = legacy_encode_args()
        self.assertIn("20", args)
        self.assertNotIn("bt709", args)

    def test_color_e_grain(self):
        self.assertIn("out_color_matrix=bt709", color_convert_filter())
        self.assertIn("bt709", color_tag_args())
        self.assertIn("noise=alls=5", grain_filter())
        self.assertEqual(grain_filter(0), "")


if __name__ == "__main__":
    unittest.main()
