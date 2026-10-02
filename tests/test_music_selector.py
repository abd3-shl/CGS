"""Test selettore tracce (solo filesystem temporaneo, niente ffmpeg reale)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import music_selector as ms


def _make_lib(root: Path, cats: dict[str, list[str]]):
    for cat, names in cats.items():
        d = root / cat
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / n).write_bytes(b"x" * 100)


class TestMusicSelector(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cartella_mancante_none(self):
        self.assertIsNone(ms.choose_track("dark_motivational", "script", [], None,
                                          music_dir=str(self.root / "nope")))

    def test_cartella_vuota_none(self):
        (self.root / "dark_motivational").mkdir()
        self.assertIsNone(ms.choose_track("dark_motivational", "script", [],
                                          music_dir=str(self.root)))

    def test_ignora_underscore_e_non_audio(self):
        lib = ms.scan_library(str(self.root))
        self.assertEqual(lib, {})
        _make_lib(self.root, {"dark_motivational": ["_skip.mp3", "note.txt", "ok.mp3"]})
        lib = ms.scan_library(str(self.root))
        self.assertEqual([Path(p).name for p in lib["dark_motivational"]], ["ok.mp3"])

    def test_scelta_deterministica_e_storia(self):
        _make_lib(self.root, {"dark_motivational": ["a.mp3", "b.mp3", "c.mp3", "d.mp3"]})
        fake = {"duration": 200.0, "lufs": -14.0, "true_peak": -1.0, "lra": 8.0,
                "lead_silence": 0.0, "tail_silence": 0.0, "sample_rate": 44100,
                "channels": 2, "codec": "mp3", "valid": True}

        def _fake_analyze(path, music_dir=None):
            info = dict(fake)
            info["path"] = str(path)
            return info

        with mock.patch.object(ms, "analyze_track", side_effect=_fake_analyze):
            t1 = ms.choose_track("dark_motivational", "stesso script", [], music_dir=str(self.root))
            t2 = ms.choose_track("dark_motivational", "stesso script", [], music_dir=str(self.root))
            self.assertEqual(t1["path"], t2["path"])  # deterministica
            t3 = ms.choose_track("dark_motivational", "stesso script", [t1["path"]],
                                 music_dir=str(self.root), history_size=3)
            self.assertNotEqual(t3["path"], t1["path"])  # anti-ripetizione

    def test_fallback_categoria(self):
        _make_lib(self.root, {"dark_motivational": ["x.mp3"]})
        fake = {"duration": 200.0, "lufs": -14.0, "true_peak": -1.0, "lra": 8.0,
                "lead_silence": 0.0, "tail_silence": 0.0, "sample_rate": 44100,
                "channels": 2, "codec": "mp3", "valid": True}

        def _fake_analyze(path, music_dir=None):
            info = dict(fake)
            info["path"] = str(path)
            return info

        with mock.patch.object(ms, "analyze_track", side_effect=_fake_analyze):
            t = ms.choose_track("tech_ai", "script", [], music_dir=str(self.root))
            self.assertIsNotNone(t)
            self.assertEqual(t["category"], "dark_motivational")

    def test_scarta_tracce_corte(self):
        _make_lib(self.root, {"educational": ["short.mp3"]})

        def _fake_analyze(path, music_dir=None):
            return {"path": str(path), "duration": 5.0, "lufs": -14.0, "valid": True}

        with mock.patch.object(ms, "analyze_track", side_effect=_fake_analyze):
            t = ms.choose_track("educational", "script", [], music_dir=str(self.root))
            self.assertIsNone(t)

    def test_cache_usata_senza_ffmpeg(self):
        _make_lib(self.root, {"educational": ["t.mp3"]})
        p = str(self.root / "educational" / "t.mp3")
        key = ms._cache_key(Path(p), str(self.root))
        cached = {"duration": 120.0, "lufs": -13.0, "true_peak": -1.0, "lra": 7.0,
                  "lead_silence": 0.0, "tail_silence": 0.0, "sample_rate": 44100,
                  "channels": 2, "codec": "mp3", "valid": True}
        (self.root / "_analysis.json").write_text(json.dumps({key: cached}), encoding="utf-8")
        with mock.patch.object(ms, "subprocess", side_effect=AssertionError("no ffmpeg")):
            # analyze_track deve servire dalla cache senza toccare subprocess.
            with mock.patch("core.music_selector.subprocess.run",
                            side_effect=AssertionError("no ffmpeg")):
                info = ms.analyze_track(p, music_dir=str(self.root))
                self.assertIsNotNone(info)
                self.assertEqual(info["duration"], 120.0)


if __name__ == "__main__":
    unittest.main()
