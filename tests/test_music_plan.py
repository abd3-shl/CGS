"""Test logica pura music_plan (solo unittest, niente ffmpeg)."""

import unittest

from core.music_plan import build_gain_expr, build_music_plan, gain_at


def _words():
    return [
        {"start": 0.0, "end": 0.5, "text": "ciao"},
        {"start": 1.2, "end": 1.7, "text": "mondo", "is_hero": True},
        {"start": 3.0, "end": 3.4, "text": "fine"},
    ]


def _chunks(words):
    return [
        {"start": 0.0, "end": 1.7, "narrative_role": "hook", "words": words[:2]},
        {"start": 1.7, "end": 3.4, "narrative_role": "body", "words": words[2:]},
        {"start": 3.4, "end": 5.0, "narrative_role": "cta", "words": [], "cta_card": True},
    ]


class TestMusicPlan(unittest.TestCase):
    def test_keyframes_monotoni_e_bordi(self):
        w = _words()
        p = build_music_plan(_chunks(w), w, 20.0, {"duration": 200.0, "lufs": -12.0}, -16.0, None)
        kf = p["keyframes"]
        self.assertGreaterEqual(len(kf), 2)
        self.assertEqual(kf[0][0], 0.0)
        self.assertEqual(kf[-1][0], 20.0)
        for (t0, _), (t1, _) in zip(kf, kf[1:]):
            self.assertGreaterEqual(t1, t0)

    def test_hook_body_cta_offsets(self):
        # Parole contigue (nessuna pausa): verifica gli offset puri di sezione.
        w = [
            {"start": 0.0, "end": 1.0, "text": "a"},
            {"start": 1.0, "end": 2.0, "text": "b"},
            {"start": 2.0, "end": 3.0, "text": "c"},
        ]
        c = [
            {"start": 0.0, "end": 1.0, "narrative_role": "hook", "words": w[:1]},
            {"start": 1.0, "end": 2.0, "narrative_role": "body", "words": w[1:2]},
            {"start": 2.0, "end": 3.0, "narrative_role": "cta", "words": w[2:]},
        ]
        p = build_music_plan(c, w, 20.0, {"duration": 200.0, "lufs": -12.0}, -16.0, None)
        # norm = -16 - (-12) = -4; hook -17 -> -21, body -20 -> -24, cta -18 -> -22
        self.assertAlmostEqual(gain_at(p, 0.2), -21.0, places=1)
        self.assertAlmostEqual(gain_at(p, 1.5), -24.0, places=1)
        self.assertAlmostEqual(gain_at(p, 10.0), -22.0, places=1)

    def test_pause_sotto_soglia_ignorate(self):
        w = [
            {"start": 0.0, "end": 0.5, "text": "a"},
            {"start": 0.6, "end": 1.0, "text": "b"},  # gap 0.1 < 0.35
        ]
        c = [{"start": 0.0, "end": 1.0, "narrative_role": "body", "words": w}]
        p = build_music_plan(c, w, 20.0, {"duration": 200.0, "lufs": -12.0}, -16.0, None)
        self.assertEqual(p["pause_count"], 0)
        self.assertEqual([e for e in p["events"] if e["type"] == "pause"], [])

    def test_pause_boost_e_hero_dip(self):
        w = _words()
        p = build_music_plan(_chunks(w), w, 20.0, {"duration": 200.0, "lufs": -12.0}, -16.0, None)
        self.assertGreaterEqual(p["pause_count"], 1)
        self.assertEqual(p["hero_count"], 1)
        # Durante la pausa la musica sale (~+4 dB sopra il fondo body/hook).
        g_pause = gain_at(p, 0.8)
        self.assertGreater(g_pause, -19.0)
        # Sul dip hero scende sotto il fondo locale.
        g_hero = gain_at(p, 1.2)
        self.assertLess(g_hero, -22.0)

    def test_video_breve_fade_ridotti_e_no_hero(self):
        w = _words()
        p = build_music_plan(_chunks(w), w, 5.0, {"duration": 200.0, "lufs": -12.0}, -16.0, None)
        self.assertEqual(p["fade_in_s"], 0.4)
        self.assertEqual(p["fade_out_s"], 1.0)
        self.assertEqual(p["hero_count"], 0)

    def test_fade_out_mai_prima_della_voce(self):
        w = [{"start": 0.0, "end": 18.5, "text": "lungo"}]
        c = [{"start": 0.0, "end": 18.5, "narrative_role": "body", "words": w}]
        p = build_music_plan(c, w, 20.0, {"duration": 200.0, "lufs": -12.0}, -16.0, None)
        # fade default 2.0 partirebbe a 18.0, ma la voce finisce a 18.5 -> clamp a 17.5.
        self.assertGreaterEqual(p["fade_out_start_s"], 17.5)

    def test_clamp_gain(self):
        w = _words()
        cfg = {"MUSIC_MAX_GAIN_DB": -30.0, "MUSIC_MIN_GAIN_DB": -22.0,
               "MUSIC_OFFSET_HOOK_LU": -17.0}
        p = build_music_plan(_chunks(w), w, 20.0, {"duration": 200.0, "lufs": -12.0}, -16.0, cfg)
        for _, g in p["keyframes"]:
            self.assertGreaterEqual(g, -30.0)
            self.assertLessEqual(g, -22.0)

    def test_gain_expr_valida_e_limitata(self):
        w = _words()
        p = build_music_plan(_chunks(w), w, 60.0, {"duration": 200.0, "lufs": -12.0}, -16.0, None)
        e = build_gain_expr(p)
        self.assertEqual(e.count("("), e.count(")"))
        self.assertLessEqual(len(e), 3500)
        self.assertIn("t", e)

    def test_determinismo(self):
        w = _words()
        c = _chunks(w)
        p1 = build_music_plan(c, w, 20.0, {"duration": 200.0, "lufs": -12.0}, -16.0, None)
        p2 = build_music_plan(c, w, 20.0, {"duration": 200.0, "lufs": -12.0}, -16.0, None)
        self.assertEqual(p1, p2)

    def test_max_keyframes(self):
        w = [{"start": float(i), "end": float(i) + 0.5, "text": f"p{i}"} for i in range(60)]
        c = [{"start": 0.0, "end": 120.0, "narrative_role": "body", "words": w}]
        p = build_music_plan(c, w, 120.0, {"duration": 300.0, "lufs": -12.0}, -16.0, None)
        self.assertLessEqual(len(p["keyframes"]), 40)

    def test_mai_eccezioni_input_vuoti(self):
        p = build_music_plan(None, None, 10.0, None, None, None)
        self.assertTrue(p["keyframes"])


if __name__ == "__main__":
    unittest.main()
