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

    def _eval_expr(self, expr: str, t: float) -> float:
        """Valutatore minimale della grammatica if(lt(a,b),x,y) con numeri e t."""
        import re as _re
        ex = _re.sub(r"\bt\b", f"({t})", expr)

        def _split_top(s: str) -> list[str]:
            parts, depth, cur = [], 0, ""
            for ch in s:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                if ch == "," and depth == 0:
                    parts.append(cur)
                    cur = ""
                else:
                    cur += ch
            parts.append(cur)
            return parts

        def _ev(s: str) -> float:
            s = s.strip()
            # Toglie parentesi ridondanti attorno a numeri/espressioni atomiche.
            while len(s) > 2 and s.startswith("(") and s.endswith(")"):
                depth = 0
                balanced = True
                for i, ch in enumerate(s):
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                    if depth == 0 and i < len(s) - 1:
                        balanced = False
                        break
                if balanced and depth == 0:
                    s = s[1:-1].strip()
                else:
                    break
            if s.startswith("if(") and s.endswith(")"):
                cond, x, y = _split_top(s[3:-1])
                c = cond.strip()
                if c.startswith("lt(") and c.endswith(")"):
                    a, b = _split_top(c[3:-1])
                    ok = _ev(a) < _ev(b)
                else:
                    ok = bool(_ev(c))
                return _ev(x) if ok else _ev(y)
            if s.startswith("lt(") and s.endswith(")"):
                a, b = _split_top(s[3:-1])
                return 1.0 if _ev(a) < _ev(b) else 0.0
            # Aritmetica di primo livello (+ e - binari, poi * e /).
            for ops in (("+", "-"), ("*", "/")):
                depth, idx, op = 0, -1, ""
                for i, ch in enumerate(s):
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                    elif depth == 0 and ch in ops:
                        if ch in ("+", "-") and i == 0:
                            continue
                        prev = s[i - 1] if i > 0 else ""
                        if ch == "-" and prev in ("e", "E"):
                            continue
                        idx, op = i, ch
                if idx > 0:
                    l, r = _ev(s[:idx]), _ev(s[idx + 1:])
                    if op == "+":
                        return l + r
                    if op == "-":
                        return l - r
                    if op == "*":
                        return l * r
                    return l / r if r else 0.0
            return float(s)

        return _ev(ex)

    def test_gain_expr_lineare_coerente(self):
        # volume con eval=frame vuole guadagni LINEARI >= 0, coerenti con gain_at.
        from core.music_plan import _db_to_lin
        w = _words()
        p = build_music_plan(_chunks(w), w, 20.0, {"duration": 200.0, "lufs": -12.0}, -16.0, None)
        e = build_gain_expr(p)
        import math as _math
        for t in (0.0, 0.2, 0.8, 1.2, 2.5, 4.5, 10.0, 19.9):
            got = self._eval_expr(e, t)
            want = _db_to_lin(gain_at(p, t))
            self.assertGreaterEqual(got, 0.0)
            # L'expr interpola in lineare, gain_at in dB: sulle rampe ripide
            # (dip hero 60 ms) divergono fino a ~1 dB, irrilevante all'ascolto.
            got_db = 20 * _math.log10(max(got, 1e-9))
            want_db = 20 * _math.log10(max(want, 1e-9))
            self.assertLessEqual(abs(got_db - want_db), 1.0)

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
