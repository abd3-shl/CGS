"""Test P0 WS-B: pause_editor su WAV sintetico (solo stdlib, nessun ffmpeg/rete)."""

import array
import math
import os
import tempfile
import unittest
import wave

from core.pause_editor import apply_pause_plan, retime_words
from core.pause_planner import map_time, plan_pauses

FR = 44100


def _burst(dur, freq=440.0, amp=10000):
    n = int(dur * FR)
    return array.array("h", (int(amp * math.sin(2 * math.pi * freq * i / FR)) for i in range(n)))


def _sil(dur):
    return array.array("h", [0] * int(dur * FR))


def _write(path, samples, nch=1):
    with wave.open(path, "wb") as w:
        w.setnchannels(nch)
        w.setsampwidth(2)
        w.setframerate(FR)
        w.writeframes(samples.tobytes())


def _read(path):
    with wave.open(path, "rb") as w:
        nch, _sw, fr, nf, _ct, _cn = w.getparams()
        raw = w.readframes(nf)
    a = array.array("h")
    a.frombytes(raw)
    return fr, nch, a


def _max_abs(a, lo, hi):
    lo = max(0, lo)
    hi = min(len(a), hi)
    m = 0
    for i in range(lo, hi):
        v = abs(int(a[i]))
        if v > m:
            m = v
    return m


class TestPauseEditor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pause_ed_")
        # 0.5 sil, 0.5 burst, 0.5 sil, 0.5 burst, 1.0 sil → 3.0s
        a = array.array("h")
        a.extend(_sil(0.5))
        a.extend(_burst(0.5))
        a.extend(_sil(0.5))
        a.extend(_burst(0.5))
        a.extend(_sil(1.0))
        self.src = os.path.join(self.tmp, "src.wav")
        _write(self.src, a)
        self.words = [{"word": "uno.", "start": 0.5, "end": 1.0},
                      {"word": "due", "start": 1.5, "end": 2.0}]
        self.dur = 3.0

    def test_durate_attese_e_nessun_taglio_nei_burst(self):
        plan = plan_pauses(self.words, "uno. due", self.dur, None, None)
        self.assertFalse(plan.get("no_change"))
        dst = os.path.join(self.tmp, "out.wav")
        eff = apply_pause_plan(self.src, dst, plan)
        self.assertIsNotNone(eff)
        fr, nch, out = _read(dst)
        # Durata attesa = dst_duration del piano effettivo (±2 campioni).
        exp_frames = int(round(float(eff["dst_duration"]) * FR))
        self.assertLessEqual(abs(len(out) // nch - exp_frames), 2)
        # Nessun taglio dentro i burst: l'energia resta (due burst presenti).
        # Stima: campioni con |v|>2000 ≈ 2×0.5s×87% (seno) ± margine.
        loud = sum(1 for v in out[::nch] if abs(int(v)) > 2000)
        self.assertGreater(loud, int(0.70 * FR))
        self.assertLess(loud, int(1.0 * FR))

    def test_nessuna_discontinuita_alle_giunzioni(self):
        plan = plan_pauses(self.words, "uno. due", self.dur, None, None)
        dst = os.path.join(self.tmp, "out.wav")
        eff = apply_pause_plan(self.src, dst, plan)
        self.assertIsNotNone(eff)
        _fr, nch, out = _read(dst)
        # Salti oltre 6000 unità tra campioni adiacenti = click (soglia generosa).
        jumps = 0
        step = max(1, nch)
        for i in range(0, len(out) - step, step):
            if abs(int(out[i + step]) - int(out[i])) > 6000:
                jumps += 1
        # I burst da 440Hz hanno salti naturali: confronta col budget del segnale
        # originale (stessa soglia) + margine per le giunzioni (<= 4 extra).
        _f0, _c0, src = _read(self.src)
        src_jumps = 0
        for i in range(0, len(src) - step, step):
            if abs(int(src[i + step]) - int(src[i])) > 6000:
                src_jumps += 1
        self.assertLessEqual(jumps, src_jumps + 4 * len(eff["cuts"]) + 4)

    def test_mappa_tempi_accurata(self):
        plan = plan_pauses(self.words, "uno. due", self.dur, None, None)
        dst = os.path.join(self.tmp, "out.wav")
        eff = apply_pause_plan(self.src, dst, plan)
        self.assertIsNotNone(eff)
        rw = retime_words(self.words, eff)
        # orig_* conservati, start/end mappati entro ±1 campione della map_time.
        for w0, w1 in zip(self.words, rw):
            self.assertAlmostEqual(w1["orig_start"], w0["start"])
            self.assertAlmostEqual(w1["orig_end"], w0["end"])
            self.assertAlmostEqual(w1["start"], map_time(w0["start"], eff), delta=1.0 / FR + 1e-9)
            self.assertAlmostEqual(w1["end"], map_time(w0["end"], eff), delta=1.0 / FR + 1e-9)
            self.assertLess(w1["start"], w1["end"])

    def test_salta_taglio_su_non_silenzio(self):
        # Piano fasullo che taglia DENTRO il burst: deve essere saltato.
        plan = {"segments": [(0.0, 0.6, 0.0), (0.9, 3.0, 0.6)],
                "cuts": [(0.6, 0.9)], "insertions": [],
                "src_duration": 3.0, "dst_duration": 2.7,
                "stats": {}, "profile": "balanced", "no_change": False}
        dst = os.path.join(self.tmp, "out2.wav")
        eff = apply_pause_plan(self.src, dst, plan)
        self.assertIsNone(eff)  # unico taglio saltato → nessun cambiamento


if __name__ == "__main__":
    unittest.main()
