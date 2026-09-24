"""
Libreria di curve di easing pure per le animazioni dei sottotitoli.

Riferimento standard: https://easings.net/ (formule di Robert Penner).
Nessuna dipendenza esterna, solo `math`.

Ogni funzione accetta `t` (float, progresso normalizzato 0.0-1.0) e
restituisce il valore "eased" (float, tipicamente 0.0-1.0). Alcune curve
come `ease_out_back` / `ease_out_elastic` possono superare leggermente 1.0
per l'effetto overshoot: e' normale e voluto (per le entrate "premium"
delle keyword). Prima di applicare un easing, normalizzare con `clamp01`.
"""

import math


def clamp01(t: float) -> float:
    """Clampa t nell'intervallo [0.0, 1.0], utile prima di applicare un easing."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return float(t)


def linear(t: float) -> float:
    """Progressione lineare, nessuna accelerazione (uso: fallback/debug)."""
    t = clamp01(t)
    return t


def ease_out_cubic(t: float) -> float:
    """Decelera in modo naturale verso la fine, per fade minimal.

    Uso visivo: entrata delle parole normali (solo opacita', nessuna scala).
    """
    t = clamp01(t)
    return 1.0 - pow(1.0 - t, 3)


def ease_in_cubic(t: float) -> float:
    """Accelera verso la scomparsa, per uscite.

    Uso visivo: fade-out di gruppo (tutte le parole insieme alla fine chunk).
    """
    t = clamp01(t)
    return t * t * t


def ease_out_back(t: float) -> float:
    """Leggero overshoot oltre 1.0, per entrata "premium" keyword.

    Uso visivo: entrata keyword (opacita' + scala 0.7 -> 1.0). L'overshoot
    (~1.1 a meta' curva) crea un effetto "pop" gradevole; clamparlo a 255
    quando usato per l'opacita'.
    """
    t = clamp01(t)
    if t == 0.0:
        return 0.0
    if t == 1.0:
        return 1.0
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * pow(t - 1.0, 3) + c1 * pow(t - 1.0, 2)


def ease_in_out_cubic(t: float) -> float:
    """Accelera poi decelera, per spostamenti fluidi del personaggio.

    Uso visivo: morph di posizione (vecchia -> nuova) e slide di continuita':
    partenza e arrivo morbidi, niente scatti ai bordi. Ritmo coerente.
    """
    t = clamp01(t)
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - pow(-2.0 * t + 2.0, 3) / 2.0


def ease_out_quad(t: float) -> float:
    """Decelerazione morbida piu' leggera del cubic, per fade delicati.

    Uso visivo: fade-in/fade-out del personaggio (opacita' 0->1, 1->0):
    ingresso/uscita fluidi senza scatti, ritmo normale non frenetico.
    """
    t = clamp01(t)
    return 1.0 - (1.0 - t) * (1.0 - t)


def ease_in_out_quad(t: float) -> float:
    """Fade+slide bilanciato, per transizioni di continuita'.

    Uso visivo: alternativa a in_out_cubic quando lo spostamento e' breve
    (stesso lato): movimento dolce senza overshoot.
    """
    t = clamp01(t)
    if t < 0.5:
        return 2.0 * t * t
    return 1.0 - pow(-2.0 * t + 2.0, 2) / 2.0


def ease_out_bounce(t: float) -> float:
    """Rimbalzo, alternativa piu' marcata per l'entrata keyword.

    Uso visivo: variante keyword piu' giocosa di `ease_out_back`.
    Ritorna 0.0 per t=0.0 e 1.0 per t=1.0, con rimbalzi intermedi.
    """
    t = clamp01(t)
    n1 = 7.5625
    d1 = 2.75
    if t < 1.0 / d1:
        return n1 * t * t
    elif t < 2.0 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    elif t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    else:
        t -= 2.625 / d1
        return n1 * t * t + 0.984375


def ease_out_elastic(t: float) -> float:
    """Elastico con overshoot/oscillazione, per effetti extra (non usato di default).

    Uso visivo: alternative sperimentali per entrate molto marcate.
    Puo' superare 1.0 e scendere sotto 0.0 nella fase iniziale.
    """
    t = clamp01(t)
    if t == 0.0:
        return 0.0
    if t == 1.0:
        return 1.0
    c4 = (2.0 * math.pi) / 3.0
    return pow(2.0, -10.0 * t) * math.sin((t * 10.0 - 0.75) * c4) + 1.0
