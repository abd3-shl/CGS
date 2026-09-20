"""
Test del posizionamento personaggi (FASE 8): nessun frame a riposo con la
faccia tagliata, visible_ratio >= 0.97, soggetto dentro i margini.

Eseguiti con `pytest tests/test_character_layout.py` (senza rete/API: solo
asset locali in assets/characters/ + geometrie sintetiche di fallback).
"""

import math

import pytest

from config import CHARACTER_POSE_COUNT, CHARACTER_VALID_POSITIONS
from core.character_geometry import (
    CHARACTER_MIN_VISIBLE_RATIO,
    CHARACTER_SAFE_MARGIN_PX,
    SubjectGeometry,
    adjust_for_text_overlap,
    clamp_subject_to_frame,
    compute_subject_placement,
    constrained_scale_abs,
    get_subject_geometry,
    rect_visible_ratio,
    validate_pose_layout_pair,
)
from core.layout_presets import VALID_LAYOUT_PRESETS


# ------------------------------------------------------------ Fixture


@pytest.fixture(autouse=True)
def _default_tuning(monkeypatch):
    """Rende i test ermetici rispetto alle variabili d'ambiente locali."""
    import core.character_geometry as geo

    monkeypatch.setattr(geo, "CHARACTER_MAX_WIDTH_RATIO", 0.62)
    monkeypatch.setattr(geo, "CHARACTER_SAFE_MARGIN_PX", 40)
    monkeypatch.setattr(geo, "CHARACTER_MIN_VISIBLE_RATIO", 0.97)
    monkeypatch.setattr(geo, "CHARACTER_FACE_MIN_VISIBLE", 1.0)
    monkeypatch.setattr(geo, "CHARACTER_SCALE_MIN", 0.65)
    monkeypatch.setattr(geo, "CHARACTER_SCALE_MAX", 0.90)


def _real_poses():
    """Pose con asset reale su disco (fallback: geometrie sintetiche)."""
    from core.character_selector import resolve_character_path

    poses = []
    for p in range(1, int(CHARACTER_POSE_COUNT) + 1):
        try:
            if resolve_character_path(p) is not None:
                poses.append(p)
        except Exception:
            pass
    return poses


def _synthetic_geometry(pose, sw, sh, src=(768, 1376)):
    bx0 = (src[0] - sw) / 2.0
    by0 = 82.0
    bx1, by1 = bx0 + sw, by0 + sh
    vcx = bx0 + sw / 2.0
    fw = min(190.0, max(140.0, 0.5 * sw))
    fh = 0.22 * sh
    return SubjectGeometry(
        pose=pose, path=f"synthetic:{pose}", mtime=0.0,
        bbox=(bx0, by0, bx1, by1), w=float(sw), h=float(sh),
        aspect=float(sw) / float(sh), visual_center_x=float(vcx),
        face_box=(vcx - fw / 2.0, by0, vcx + fw / 2.0, by0 + fh),
        src_size=(int(src[0]), int(src[1])),
    )


@pytest.fixture(params=[1, 2, 3, 4, 5])
def pose_id(request, monkeypatch):
    """Ogni posa: asset reale se presente, altrimenti geometria sintetica."""
    import core.character_geometry as geo

    pose = int(request.param)
    if pose in _real_poses():
        return pose
    # Fallback sintetico (rettangoli): posa 2 larga come il caso reale.
    widths = {1: 333.0, 2: 676.0, 3: 372.0, 4: 358.0, 5: 349.0}
    synth = _synthetic_geometry(pose, widths[pose], 1216.0)
    monkeypatch.setattr(geo, "_geometry_cache", {pose: synth})
    return pose


ALL_LAYOUTS = list(VALID_LAYOUT_PRESETS) + list(CHARACTER_VALID_POSITIONS)


# ------------------------------------------------------------ Matrice posa x layout x scala x punch


@pytest.mark.parametrize("layout", ALL_LAYOUTS)
@pytest.mark.parametrize("punch", [False, True])
@pytest.mark.parametrize("scale_hint", [0.65, 0.90])
def test_stable_state_contained(pose_id, layout, scale_hint, punch):
    """Stato stabile: soggetto dentro i margini, faccia integra, vis >= 0.97."""
    margin = int(CHARACTER_SAFE_MARGIN_PX)
    min_vis = float(CHARACTER_MIN_VISIBLE_RATIO)
    res = compute_subject_placement(
        pose_id, layout, punch, 1080, 1920, scale_hint=scale_hint)
    for key in ("new_w", "new_h", "px", "py", "scale_abs", "visible_ratio",
                "punch_effective"):
        assert math.isfinite(float(res[key])), f"{key} non finito: {res[key]}"
    sx, sy, sw2, sh2 = res["subject_rect"]
    fx, fy, fw2, fh2 = res["face_rect"]
    for v in (sx, sy, sw2, sh2, fx, fy, fw2, fh2):
        assert math.isfinite(float(v))
    assert res["visible_ratio"] >= min_vis, (
        f"posa {pose_id}/{layout} punch={punch}: vis={res['visible_ratio']:.3f}")
    assert sx >= margin - 1.0 and sx + sw2 <= 1080 - margin + 1.0, (
        f"posa {pose_id}/{layout}: soggetto x fuori [{sx:.0f}, {sx + sw2:.0f}]")
    assert sy >= margin - 1.0 and sy + sh2 <= 1920 + 1.0, (
        f"posa {pose_id}/{layout}: soggetto y fuori [{sy:.0f}, {sy + sh2:.0f}]")
    assert fx >= margin - 1.0 and fy >= margin - 1.0, (
        f"posa {pose_id}/{layout}: faccia sopra/sotto margine")
    assert fx + fw2 <= 1080 - margin + 1.0 and fy + fh2 <= 1920 - margin + 1.0, (
        f"posa {pose_id}/{layout}: faccia tagliata "
        f"[{fx:.0f},{fy:.0f},{fx + fw2:.0f},{fy + fh2:.0f}]")


def test_geometry_cached():
    """La geometria e' calcolata una sola volta per asset (cache RAM)."""
    g1 = get_subject_geometry(1)
    g2 = get_subject_geometry(1)
    assert g1 is g2
    assert g1.w > 0 and g1.h > 0 and g1.aspect > 0
    x0, y0, x1, y1 = g1.bbox
    assert x1 > x0 and y1 > y0
    assert x0 <= g1.visual_center_x <= x1


# ------------------------------------------------------------ Unita': scala = min(h, w)


def test_constrained_scale_width_wins():
    """Il vincolo di larghezza vince sempre su quello di altezza."""
    # Center standard: la testa resta sotto la fascia testo (490 + gutter 24),
    # tetto aggiuntivo (1920-490-24)/h che qui vince su tutti.
    k, _eff, capped = constrained_scale_abs(200.0, 1216.0, 768.0,
                                            "layout_center_standard",
                                            False, 1080, 1920)
    assert k == pytest.approx((1920.0 - 490.0 - 24.0) / 1216.0)
    assert capped
    # Split (separazione orizzontale, nessun tetto testo): vince l'altezza.
    kh, _e, _c = constrained_scale_abs(200.0, 1216.0, 768.0,
                                       "layout_split_left",
                                       False, 1080, 1920)
    assert kh == pytest.approx(0.90 * 1920 / 1216.0)
    # Soggetto larghissimo: vince la larghezza (0.62 * 1080 / w).
    k2, _eff2, capped2 = constrained_scale_abs(1290.0, 1216.0, 768.0,
                                               "layout_center_standard",
                                               False, 1080, 1920)
    assert k2 == pytest.approx(0.62 * 1080 / 1290.0)
    assert capped2
    # Scala piccola non vincolata (legacy 0.65): nessun cappello.
    k0, _e0, capped0 = constrained_scale_abs(333.0, 1216.0, 768.0,
                                             "bottom_center",
                                             False, 1080, 1920,
                                             scale_hint=0.65)
    assert k0 == pytest.approx(0.65 * 1920 / 1216.0)
    assert not capped0
    # Il punch_in non supera mai i vincoli (fattore effettivo <= richiesto).
    k3, eff3, _c3 = constrained_scale_abs(333.0, 1216.0, 768.0,
                                          "layout_split_left",
                                          True, 1080, 1920)
    assert eff3 <= 1.15 + 1e-9
    assert k3 * 333.0 <= 0.62 * 1080 + 1e-6


# ------------------------------------------------------------ Unita': clamp


def test_clamp_shifts_inside():
    x, y, sf, fixed = clamp_subject_to_frame(900.0, 100.0, 400.0, 1500.0,
                                             40, "stable", None, 1080, 1920)
    assert fixed and sf == pytest.approx(1.0)
    assert x == pytest.approx(1080 - 40 - 400.0)
    assert rect_visible_ratio((x, y, 400.0, 1500.0), 1080, 1920) == pytest.approx(1.0)


def test_clamp_shrinks_oversize():
    x, y, sf, fixed = clamp_subject_to_frame(0.0, 0.0, 2000.0, 1500.0,
                                             40, "stable", None, 1080, 1920)
    assert fixed and sf < 1.0
    assert x >= 40 - 1e-9 and x + 2000.0 * sf <= 1080 - 40 + 1e-9


def test_clamp_keeps_face_visible():
    face = (900.0, 200.0, 1050.0, 450.0)  # esce a destra
    x, y, _sf, fixed = clamp_subject_to_frame(500.0, 100.0, 500.0, 1500.0,
                                              40, "stable", face, 1080, 1920)
    assert fixed
    # La faccia trasla rigidamente col soggetto: resta dentro i margini.
    dx = x - 500.0
    assert face[0] + dx >= 40 - 1e-9 and face[2] + dx <= 1080 - 40 + 1e-9


def test_clamp_transition_allows_offscreen():
    # A meta' animazione il fuori-campo e' ammesso (il keyframe finale e'
    # lo stato stabile: gli offset valgono 0 a progress 1).
    x, y, sf, fixed = clamp_subject_to_frame(-1404.0, 250.0, 1404.0, 2516.0,
                                             40, "transition", None, 1080, 1920)
    assert (x, y, sf, fixed) == (-1404.0, 250.0, 1.0, False)


# ------------------------------------------------------------ Unita': coppia posa/layout


def test_pair_wide_pose_forced_center():
    fixed, changed = validate_pose_layout_pair(2, "layout_split_right")
    assert changed and fixed == "layout_center_standard"


def test_pair_pointing_pose_forced_split():
    fixed, changed = validate_pose_layout_pair(4, "layout_center_standard")
    assert changed and "split" in fixed
    fixed5, changed5 = validate_pose_layout_pair(5, "layout_center_standard")
    assert changed5 and "split" in fixed5


def test_pair_compatible_untouched():
    fixed, changed = validate_pose_layout_pair(1, "layout_split_left")
    assert not changed and fixed == "layout_split_left"


def test_pair_legacy_vocabulary_preserved():
    fixed, changed = validate_pose_layout_pair(2, "bottom_right")
    assert changed and fixed == "bottom_center"


# ------------------------------------------------------------ Regressione: braccio teso ~1.2*W


def test_regression_wide_subject_contained(monkeypatch):
    """Soggetto ~1.2*W a scala massima: interamente visibile, margine >= 40."""
    import core.character_geometry as geo

    sw, sh = 1290.0, 1216.0  # ~1.19 * 1080 di larghezza nativa
    synth = _synthetic_geometry(9, sw, sh)
    monkeypatch.setattr(geo, "_geometry_cache", {9: synth})
    res = compute_subject_placement(9, "layout_split_right", True,
                                    1080, 1920, scale_hint=0.90)
    sx, sy, w2, h2 = res["subject_rect"]
    fx, fy, fw2, fh2 = res["face_rect"]
    assert res["visible_ratio"] >= 0.97
    assert sx >= 40 - 1.0 and sx + w2 <= 1080 - 40 + 1.0
    assert w2 <= 0.62 * 1080 + 1.0
    assert fx >= 40 - 1.0 and fx + fw2 <= 1080 - 40 + 1.0
    assert fy >= 40 - 1.0 and fy + fh2 <= 1920 - 40 + 1.0


# ------------------------------------------------------------ Testo prioritario


def test_text_overlap_rebalanced():
    """Overlap > 25% dell'area testo: layout opposto o scala ridotta."""
    geo = get_subject_geometry(1)
    bx0, by0, bx1, by1 = geo.bbox
    k = 1.0
    x_full, y_full = 100.0, 1920.0 - by1 * k
    # Fascia testo quasi interamente sotto il soggetto.
    text_rect = (x_full + bx0 * k, y_full + by0 * k,
                 geo.w * k, 300.0)
    out = adjust_for_text_overlap(
        1, "layout_split_left", False, k, x_full, y_full,
        geo.visual_center_x, bx0, by0, bx1, by1, geo.w, geo.h,
        geo.face_box, text_rect, 1080, 1920, 40, 0.4)
    assert out is not None  # overlap ~100% >> 25%: deve reagire
    _lay, _k2, _xf, _yf, _sj, _fc, notes = out
    assert notes


def test_no_overlap_no_change():
    """Senza overlap il placement resta invariato (None)."""
    geo = get_subject_geometry(1)
    bx0, by0, bx1, by1 = geo.bbox
    out = adjust_for_text_overlap(
        1, "layout_center_standard", False, 1.0, 200.0, 700.0,
        geo.visual_center_x, bx0, by0, bx1, by1, geo.w, geo.h,
        geo.face_box, (90.0, 140.0, 900.0, 350.0), 1080, 1920, 40, 0.4)
    assert out is None
