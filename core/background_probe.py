"""
Background Probe P0 (WS-D): statistiche dello sfondo dietro il testo (I/O).

- `FlatBackgroundProbe(color)` → stats costanti (tinta unita: livello 0).
- `FrameBackgroundProbe(source_path)` → 2-3 frame a bassa risoluzione
  (108x192) con ffmpeg nella finestra del chunk, stats DENTRO il text_box,
  con cache (path, t). Pronto per futuri sfondi reali (B-roll/immagini);
  oggi collegato tramite `background_source=None`.
- `compute_stats(image, box)` è puro (PIL) e riusabile nei test con immagini
  sintetiche (gradiente, rumore, scacchiera).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile


def _hex_to_rgb(color) -> tuple[int, int, int]:
    try:
        if isinstance(color, str) and color.strip().startswith("#") and len(color.strip()) == 7:
            s = color.strip()
            return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
        if isinstance(color, (tuple, list)) and len(color) >= 3:
            return (max(0, min(255, int(color[0]))), max(0, min(255, int(color[1]))),
                    max(0, min(255, int(color[2]))))
    except (TypeError, ValueError):
        pass
    return (0, 0, 0)


def _srgb_to_linear(v: float) -> float:
    v = max(0.0, min(1.0, v))
    if v <= 0.04045:
        return v / 12.92
    return ((v + 0.055) / 1.055) ** 2.4


def compute_stats(image, box: tuple | None = None) -> dict:
    """BackgroundStats da un'immagine PIL (puro).

    Ritorna {mean_lum, std_lum, p10, p90, edge_density} con luminanze 0..1.
    `box` = (x0,y0,x1,y1) in pixel dell'immagine (None = tutta).
    Mai eccezioni (fallback piatto scuro).
    """
    flat = {"mean_lum": 0.0, "std_lum": 0.0, "p10": 0.0, "p90": 0.0, "edge_density": 0.0}
    try:
        from PIL import Image as _Image
        img = image.convert("L") if image.mode != "L" else image
        w, h = img.size
        if box is not None:
            try:
                x0, y0, x1, y1 = (max(0, int(box[0])), max(0, int(box[1])),
                                  min(w, int(box[2])), min(h, int(box[3])))
                if x1 > x0 and y1 > y0:
                    img = img.crop((x0, y0, x1, y1))
            except (TypeError, ValueError, IndexError):
                pass
        # Downscale per velocità (max ~135x240): statistiche quasi identiche.
        try:
            if img.size[0] * img.size[1] > 135 * 240:
                img = img.resize((135, 240)) if img.size[0] < img.size[1] else img.resize((240, 135))
        except Exception:
            pass
        px = list(img.getdata())
        if not px:
            return flat
        n = len(px)
        lums = [_srgb_to_linear(v / 255.0) for v in px]
        mean = sum(lums) / n
        var = sum((v - mean) ** 2 for v in lums) / n
        std = var ** 0.5
        ordered = sorted(lums)
        p10 = ordered[max(0, int(n * 0.10) - 1)]
        p90 = ordered[min(n - 1, int(n * 0.90))]
        # Edge density: media delle differenze assolute orizzontali/verticali.
        W, H = img.size
        try:
            diff = 0.0
            cnt = 0
            for y in range(0, H, 2):
                base = y * W
                for x in range(0, W - 1, 2):
                    diff += abs(lums[base + x + 1] - lums[base + x])
                    cnt += 1
            for y in range(0, H - 1, 2):
                for x in range(0, W, 2):
                    diff += abs(lums[(y + 1) * W + x] - lums[y * W + x])
                    cnt += 1
            edge = (diff / cnt) if cnt else 0.0
        except Exception:
            edge = 0.0
        return {
            "mean_lum": round(mean, 4),
            "std_lum": round(std, 4),
            "p10": round(p10, 4),
            "p90": round(p90, 4),
            "edge_density": round(min(1.0, edge * 4.0), 4),
        }
    except Exception:
        return flat


class FlatBackgroundProbe:
    """Probe per tinta unita (oggi): stats costanti → livello 0. Puro."""

    def __init__(self, color=(0, 0, 0)):
        try:
            self.rgb = _hex_to_rgb(color)
        except Exception:
            self.rgb = (0, 0, 0)

    def stats_for(self, text_box=None, t: float = 0.0) -> dict:
        try:
            from core.legibility import relative_luminance
            lum = relative_luminance(self.rgb)
        except Exception:
            lum = 0.0
        return {"mean_lum": round(lum, 4), "std_lum": 0.0,
                "p10": round(lum, 4), "p90": round(lum, 4), "edge_density": 0.0}

    @property
    def bg_rgb(self) -> tuple[int, int, int]:
        return self.rgb


class FrameBackgroundProbe:
    """Probe su video/immagine reale (futuri B-roll): 2-3 frame 108x192.

    `source_path` = video o immagine. `stats_for(text_box_1080x1920, t)`:
    estrae un frame a bassa risoluzione con ffmpeg al tempo t (video) e
    calcola le stats dentro il text_box riscalato. Cache (path, round(t,1)).
    Best-effort: se l'estrazione fallisce → stats piatte scure.
    """

    def __init__(self, source_path: str):
        self.source = str(source_path or "")
        self._cache: dict = {}

    def _extract_frame(self, t: float):
        try:
            from PIL import Image as _Image
        except ImportError:
            return None
        try:
            ff = shutil.which("ffmpeg")
            if not ff or not self.source:
                return None
            import os as _os
            if not _os.path.isfile(self.source):
                return None
            tmp = tempfile.NamedTemporaryFile(prefix="bgprobe_", suffix=".png", delete=False)
            tmp_path = tmp.name
            tmp.close()
            is_video = self.source.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".avi"))
            if is_video:
                cmd = [ff, "-y", "-v", "error", "-ss", f"{max(0.0, float(t)):.2f}",
                       "-i", self.source, "-frames:v", "1",
                       "-vf", "scale=108:192", tmp_path]
            else:
                cmd = [ff, "-y", "-v", "error", "-i", self.source,
                       "-vf", "scale=108:192", "-frames:v", "1", tmp_path]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if res.returncode != 0:
                return None
            img = _Image.open(tmp_path).convert("RGB")
            try:
                import os as _os2
                _os2.remove(tmp_path)
            except OSError:
                pass
            return img
        except Exception:
            return None

    def stats_for(self, text_box=None, t: float = 0.0) -> dict:
        flat = {"mean_lum": 0.0, "std_lum": 0.0, "p10": 0.0, "p90": 0.0, "edge_density": 0.0}
        try:
            key = (self.source, round(float(t), 1))
        except (TypeError, ValueError):
            return flat
        if key in self._cache:
            img = self._cache[key]
        else:
            img = self._extract_frame(t)
            if img is None:
                return flat
            if len(self._cache) < 32:
                self._cache[key] = img
        try:
            # text_box in 1080x1920 → 108x192 (fattore 0.1).
            box = None
            if text_box is not None:
                box = (int(text_box[0] * 0.1), int(text_box[1] * 0.1),
                       int(text_box[2] * 0.1), int(text_box[3] * 0.1))
            return compute_stats(img, box)
        except Exception:
            return flat


def make_probe(background_source: str | None = None, background_color=(0, 0, 0)):
    """Factory: FrameBackgroundProbe se source reale, altrimenti Flat. Mai eccezioni."""
    try:
        if background_source:
            import os as _os
            if _os.path.isfile(str(background_source)):
                return FrameBackgroundProbe(str(background_source))
    except Exception:
        pass
    try:
        return FlatBackgroundProbe(background_color)
    except Exception:
        return FlatBackgroundProbe((0, 0, 0))
