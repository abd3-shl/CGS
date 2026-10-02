"""Test P0 WS-C: safe_zones pure (nessuna rete, nessun ffmpeg)."""

import unittest

from core.safe_zones import (
    apply_overrides,
    cover_safe_rect,
    get_profile,
    normalize_profile_name,
    rail_rects,
    rect_violations,
    safe_rect,
    text_allowed_rect,
)


class TestProfiles(unittest.TestCase):
    def test_universal_default(self):
        p = get_profile()
        self.assertEqual(p["name"], "universal")
        self.assertEqual((p["top"], p["bottom"], p["left"], p["right"]), (150, 420, 120, 120))

    def test_universal_intersezione_conservativa(self):
        u = get_profile("universal")
        for name in ("tiktok", "reels", "shorts"):
            o = get_profile(name)
            self.assertGreaterEqual(u["bottom"], o["bottom"])
            self.assertGreaterEqual(u["left"], o["left"])
            self.assertGreaterEqual(u["top"], o["top"])

    def test_bottom_420_e_rail_220(self):
        p = get_profile("universal")
        self.assertEqual(p["bottom"], 420)
        self.assertEqual(p["rail_extra"], 220)
        r = rail_rects(p)
        self.assertEqual(len(r), 1)
        # Rail a destra, fascia y 700-1600.
        self.assertEqual((r[0][1], r[0][3]), (700, 1600))
        self.assertEqual(r[0][2] - r[0][0], 220 - 120)

    def test_override_json(self):
        p = get_profile("universal")
        q = apply_overrides(p, {"bottom": 400, "top": "x"})
        self.assertEqual(q["bottom"], 400)
        self.assertEqual(q["top"], 150)  # invalido ignorato

    def test_nome_ignoto_fallback(self):
        self.assertEqual(normalize_profile_name("xyz"), "universal")


class TestRects(unittest.TestCase):
    def test_text_allowed_rect_intersezione(self):
        p = get_profile("universal")
        # Layout center (90,150,990,900) ∩ safe (144,174,936,1476).
        r = text_allowed_rect((90, 150, 990, 900), p)
        self.assertEqual(r, (144, 174, 936, 900))

    def test_violazioni(self):
        p = get_profile("universal")
        self.assertEqual(rect_violations((200, 500, 800, 900), p), [])
        v = rect_violations((900, 800, 1000, 1500), p)
        self.assertIn("testo-in-rail", v)
        v2 = rect_violations((200, 100, 800, 400), p)
        self.assertIn("testo-in-top-ui", v2)
        v3 = rect_violations((200, 1400, 800, 1600), p)
        self.assertIn("testo-in-bottom-ui", v3)

    def test_cover_safe(self):
        self.assertEqual(cover_safe_rect(), (0, 285, 1080, 1635))

    def test_safe_rect_con_padding(self):
        p = get_profile("universal")
        # padding default 24 → (144,174,936,1476)
        self.assertEqual(safe_rect(p), (144, 174, 936, 1476))


if __name__ == "__main__":
    unittest.main()
