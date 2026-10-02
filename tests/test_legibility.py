"""Test P0 WS-D: legibility pura + background_probe su immagini sintetiche."""

import unittest

from core.background_probe import FlatBackgroundProbe, compute_stats
from core.legibility import contrast_ratio, decide_text_effects, relative_luminance


def _synthetic(kind, size=(108, 192)):
    from PIL import Image, ImageDraw
    import random
    img = Image.new("RGB", size, (0, 0, 0))
    if kind == "flat":
        img = Image.new("RGB", size, (16, 20, 24))
    elif kind == "gradient":
        px = img.load()
        for y in range(size[1]):
            v = int(255 * y / max(1, size[1] - 1))
            for x in range(size[0]):
                px[x, y] = (v, v, v)
    elif kind == "noise":
        rnd = random.Random(42)
        px = img.load()
        for y in range(size[1]):
            for x in range(size[0]):
                v = rnd.randint(0, 255)
                px[x, y] = (v, v, v)
    elif kind == "checker":
        d = ImageDraw.Draw(img)
        s = 12
        for y in range(0, size[1], s):
            for x in range(0, size[0], s):
                if (x // s + y // s) % 2:
                    d.rectangle([x, y, x + s - 1, y + s - 1], fill=(255, 255, 255))
    return img


class TestContrast(unittest.TestCase):
    def test_wcag_noti(self):
        self.assertAlmostEqual(contrast_ratio((255, 255, 255), (0, 0, 0)), 21.0, places=1)
        self.assertAlmostEqual(contrast_ratio((0, 0, 0), (0, 0, 0)), 1.0, places=2)
        # Grigio medio su nero ≈ 5.25 (noto WCAG).
        c = contrast_ratio((127, 127, 127), (0, 0, 0))
        self.assertGreater(c, 4.5)
        self.assertLess(c, 6.0)

    def test_luminanza(self):
        self.assertAlmostEqual(relative_luminance((255, 255, 255)), 1.0, places=3)
        self.assertAlmostEqual(relative_luminance((0, 0, 0)), 0.0, places=3)


class TestLevels(unittest.TestCase):
    def test_livello0_piatto_contrasto_alto(self):
        st = {"mean_lum": 0.0, "std_lum": 0.0, "p10": 0.0, "p90": 0.0, "edge_density": 0.0}
        e = decide_text_effects(st, (255, 255, 255), 84, "base", (0, 0, 0))
        self.assertEqual(e["level"], 0)
        self.assertEqual(e["stroke_px"], 0)
        self.assertIsNone(e["shadow"])

    def test_livello3_contrasto_basso(self):
        st = {"mean_lum": 0.5, "std_lum": 0.0, "p10": 0.5, "p90": 0.5, "edge_density": 0.0}
        e = decide_text_effects(st, (120, 120, 120), 84, "base", (128, 128, 128))
        self.assertEqual(e["level"], 3)
        self.assertGreaterEqual(e["stroke_px"], 3)
        self.assertLessEqual(e["stroke_px"], 8)
        self.assertGreater(e["scrim_alpha"], 0.0)

    def test_stroke_ombra_proporzionali(self):
        st = {"mean_lum": 0.5, "std_lum": 0.2, "p10": 0.2, "p90": 0.8, "edge_density": 0.5}
        e1 = decide_text_effects(st, (255, 255, 255), 56, "base", (128, 128, 128))
        e2 = decide_text_effects(st, (255, 255, 255), 112, "base", (128, 128, 128))
        self.assertGreater(e2["stroke_px"], e1["stroke_px"])
        self.assertGreater(e2["shadow"]["dy"], e1["shadow"]["dy"])

    def test_tier_t2_minimo_livello1_su_non_piatto(self):
        st = {"mean_lum": 0.0, "std_lum": 0.05, "p10": 0.0, "p90": 0.0, "edge_density": 0.1}
        e = decide_text_effects(st, (255, 255, 255), 84, "impact", (0, 0, 0))
        self.assertGreaterEqual(e["level"], 1)

    def test_determinismo(self):
        st = {"mean_lum": 0.3, "std_lum": 0.12, "p10": 0.1, "p90": 0.5, "edge_density": 0.2}
        a = decide_text_effects(st, (255, 255, 255), 84, "base", (40, 40, 40))
        b = decide_text_effects(st, (255, 255, 255), 84, "base", (40, 40, 40))
        self.assertEqual(a, b)


class TestProbe(unittest.TestCase):
    def test_flat_livello0(self):
        stats = compute_stats(_synthetic("flat"))
        self.assertLess(stats["std_lum"], 0.04)
        e = decide_text_effects(stats, (255, 255, 255), 84, "base", (16, 20, 24))
        self.assertEqual(e["level"], 0)

    def test_gradient_rumore_checker_non_piatto(self):
        for kind in ("gradient", "noise", "checker"):
            stats = compute_stats(_synthetic(kind))
            self.assertGreater(stats["std_lum"], 0.04, kind)

    def test_flat_probe(self):
        p = FlatBackgroundProbe("#101418")
        st = p.stats_for()
        self.assertEqual(st["std_lum"], 0.0)


if __name__ == "__main__":
    unittest.main()
