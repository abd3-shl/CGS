"""Test P0 WS-B: pause_planner puro (nessuna rete, nessun ffmpeg)."""

import unittest

from core.pause_planner import (
    build_segments,
    classify_boundary,
    dramatic_gap_indices,
    map_time,
    plan_pauses,
    resolve_pace_profile,
)


def _words(gaps=(0.5, 0.2), start0=0.5, texts=("Ciao.", "come", "va?")):
    ws = []
    t = start0
    for i, tx in enumerate(texts):
        ws.append({"word": tx, "start": t, "end": t + 0.3})
        t += 0.3 + (gaps[i] if i < len(gaps) else 0.2)
    return ws


class TestClassify(unittest.TestCase):
    def test_sentence_clause_none(self):
        self.assertEqual(classify_boundary("Ciao."), "sentence_end")
        self.assertEqual(classify_boundary("va?"), "sentence_end")
        self.assertEqual(classify_boundary("oh,"), "clause")
        self.assertEqual(classify_boundary("bene;"), "clause")
        self.assertEqual(classify_boundary("come"), "none")
        self.assertEqual(classify_boundary(""), "none")


class TestPace(unittest.TestCase):
    def test_auto_per_nicchia(self):
        self.assertEqual(resolve_pace_profile("fitness_sport", None), "tight")
        self.assertEqual(resolve_pace_profile("dark_motivational", None), "tight")
        self.assertEqual(resolve_pace_profile("educational", None), "breathing")
        self.assertEqual(resolve_pace_profile("tech_ai", None), "balanced")
        self.assertEqual(resolve_pace_profile(None, None), "balanced")

    def test_override_esplicito(self):
        self.assertEqual(resolve_pace_profile("educational", {"pace": "tight"}), "tight")


class TestPlan(unittest.TestCase):
    BIG = {"max_change": 10.0}  # isola il comportamento dal budget di sicurezza

    def test_accorcia_gap_lungo(self):
        ws = _words(gaps=(1.5, 0.1))
        # Durata aderente al parlato (nessun tail-edit, niente floor 5s).
        plan = plan_pauses(ws, "Ciao. come va?", 3.35, "tech_ai", self.BIG)
        self.assertFalse(plan.get("no_change"))
        # Gap 1.5s dopo "Ciao." (sentence, balanced 0.32): tagliato a ~0.32.
        cuts = plan["cuts"]
        self.assertTrue(any(0.8 < a < 1.2 for a, _b in cuts), cuts)
        rw = plan  # gap retimato ≈ target
        from core.pause_planner import map_time as _m
        # w0.end=0.8 → w1.start=2.3: gap originale 1.5s → 0.32s dopo il taglio.
        self.assertAlmostEqual(_m(2.3, plan) - _m(0.8, plan), 0.32, delta=0.08)

    def test_allunga_drammatica(self):
        # Prima frase corta + gap piccolo dopo "Ciao.": drammatica → allunga.
        ws = _words(gaps=(0.06, 0.12))
        plan = plan_pauses(ws, "Ciao. come va?", 1.93, "tech_ai", self.BIG)
        ins = plan["insertions"]
        # Gap 0 dopo "Ciao." (fine prima frase) allungato verso 0.32+0.18=0.50.
        self.assertTrue(any(d > 0.2 for _a, d in ins), ins)

    def test_nessuna_pausa_interna_oltre_max(self):
        ws = _words(gaps=(0.5, 0.5))
        plan = plan_pauses(ws, "Ciao. come va?", 2.75, "fitness_sport", self.BIG)
        # Dopo il piano, i gap retimati devono essere <= 0.60 + tolleranza.
        from core.pause_editor import retime_words
        rw = retime_words(ws, plan)
        for a, b in zip(rw, rw[1:]):
            self.assertLessEqual(float(b["start"]) - float(a["end"]), 0.60 + 0.15)

    def test_head_tail(self):
        ws = _words(gaps=(0.2, 0.2), start0=0.8)
        plan = plan_pauses(ws, "Ciao come va", 6.0, None, None)
        st = plan["stats"]
        self.assertLess(st["head_delta_s"], 0.0)  # testa tagliata

    def test_limite_totale(self):
        ws = _words(gaps=(2.0, 2.0))
        plan = plan_pauses(ws, "Ciao. come va?", 8.0, "tech_ai", None)
        tot = plan["stats"]["shorten_s"] + plan["stats"]["lengthen_s"]
        self.assertLessEqual(tot, 0.12 * 8.0 + 1e-6)

    def test_piano_vuoto(self):
        ws = _words(gaps=(0.05, 0.05), start0=0.06)
        # last_end=1.06, durata 1.41 → head/tail già a target, gap < min_edit.
        plan = plan_pauses(ws, "Ciao come va", 1.41, None, None)
        self.assertTrue(plan.get("no_change"))

    def test_determinismo(self):
        ws = _words()
        p1 = plan_pauses(ws, "Ciao. come va?", 10.0, "tech_ai", None)
        p2 = plan_pauses(ws, "Ciao. come va?", 10.0, "tech_ai", None)
        self.assertEqual(p1, p2)


class TestMapTime(unittest.TestCase):
    def test_monotona_e_identita_fuori_tagli(self):
        ws = _words(gaps=(1.0, 0.1))
        plan = plan_pauses(ws, "Ciao. come va?", 10.0, "tech_ai", None)
        ts = [i * 0.05 for i in range(201)]
        m = [map_time(t, plan) for t in ts]
        for a, b in zip(m, m[1:]):
            self.assertGreaterEqual(b, a)

    def test_build_segments_coerente(self):
        segs, dst = build_segments([(1.0, 1.5)], [(2.0, 0.2)], 5.0)
        # keep [0,1) + insert 0.2 + keep [1.5,5)
        self.assertAlmostEqual(dst, 1.0 + 0.2 + 3.5, places=6)
        self.assertAlmostEqual(map_time(0.5, {"segments": segs}), 0.5, places=6)
        self.assertAlmostEqual(map_time(1.2, {"segments": segs}), 1.0, places=6)  # giunzione
        self.assertAlmostEqual(map_time(2.0, {"segments": segs}), 1.0 + 0.2 + 0.5, places=6)


class TestDramatic(unittest.TestCase):
    def test_prima_e_ultima_frase_e_domanda(self):
        # Parole distanziate (>=3s) così il diradamento non le fonde.
        ws = [{"word": "Smetti.", "start": 0.0, "end": 0.3},
              {"word": "davvero?", "start": 3.5, "end": 3.8},
              {"word": "pensa", "start": 7.0, "end": 7.2},
              {"word": "al", "start": 7.3, "end": 7.4},
              {"word": "50%", "start": 7.6, "end": 7.9}]
        d = dramatic_gap_indices(ws)
        self.assertIn(0, d)  # fine prima frase
        self.assertIn(1, d)  # dopo domanda / prima dell'ultima frase


if __name__ == "__main__":
    unittest.main()
