"""Test P0 WS-B: costruzione voice_settings + downgrade (nessuna rete reale)."""

import unittest

from core.tts import build_voice_settings, downgrade_voice_settings, model_capabilities


class TestVoiceSettings(unittest.TestCase):
    def test_default_e_clamp(self):
        s = build_voice_settings(None, "eleven_multilingual_v2")
        self.assertEqual(set(s.keys()),
                         {"stability", "similarity_boost", "style", "speed", "use_speaker_boost"})
        self.assertGreaterEqual(s["speed"], 1.0)
        self.assertLessEqual(s["speed"], 1.15)
        self.assertLessEqual(s["style"], 0.45)

    def test_profili_nicchia(self):
        fit = build_voice_settings("fitness_sport", "eleven_multilingual_v2")
        edu = build_voice_settings("educational", "eleven_multilingual_v2")
        self.assertEqual((fit["stability"], fit["style"], fit["speed"]), (0.40, 0.40, 1.10))
        self.assertEqual((edu["stability"], edu["style"], edu["speed"]), (0.60, 0.15, 1.04))

    def test_capacita_modello(self):
        caps = model_capabilities("eleven_turbo_v2")
        self.assertNotIn("style", caps)
        s = build_voice_settings("fitness_sport", "eleven_turbo_v2")
        self.assertNotIn("style", s)
        self.assertIn("speed", s)
        s2 = build_voice_settings(None, "modello_ignoto_xyz")
        self.assertEqual(set(s2.keys()), {"stability", "similarity_boost"})

    def test_downgrade(self):
        full = {"stability": 0.5, "similarity_boost": 0.75, "style": 0.25,
                "speed": 1.08, "use_speaker_boost": True}
        l1 = downgrade_voice_settings(full)
        self.assertEqual(set(l1.keys()), {"stability", "similarity_boost", "speed"})
        l2 = downgrade_voice_settings(l1)
        self.assertEqual(set(l2.keys()), {"stability", "similarity_boost"})
        self.assertIsNone(downgrade_voice_settings(l2))


class TestTtsDowngradeHttp(unittest.TestCase):
    """Downgrade a 400 con risposta simulata (mock requests.post)."""

    def test_retry_con_downgrade(self):
        import core.tts as tts_mod
        calls = []

        class Resp:
            def __init__(self, status, text=""):
                self.status_code = status
                self.text = text
                self.content = b"FAKEAUDIO"

        def fake_post(url, json=None, params=None, headers=None, timeout=None):
            calls.append(dict(json.get("voice_settings", {})))
            if len(calls) == 1:
                return Resp(400, '{"detail": "voice_settings style not supported"}')
            return Resp(200)

        import config as cfg
        old_keys = list(cfg.ELEVENLABS_API_KEYS)
        cfg.ELEVENLABS_API_KEYS = ["k1"]
        old_post = tts_mod.requests.post
        tts_mod.requests.post = fake_post
        try:
            import tempfile
            cfg.TEMP_DIR = tempfile.mkdtemp(prefix="tts_")
            out = tts_mod.generate_audio("ciao mondo", "n.mp3", niche="tech_ai")
            self.assertTrue(out.endswith("n.mp3"))
            self.assertEqual(len(calls), 2)
            self.assertIn("style", calls[0])
            self.assertNotIn("style", calls[1])
            self.assertNotIn("use_speaker_boost", calls[1])
        finally:
            tts_mod.requests.post = old_post
            cfg.ELEVENLABS_API_KEYS = old_keys


if __name__ == "__main__":
    unittest.main()
