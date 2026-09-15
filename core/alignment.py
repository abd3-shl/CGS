"""
Allineamento della trascrizione Whisper allo script originale.

Whisper fornisce timestamp accurati ma può sbagliare singole parole
(omonimi, nomi propri, punteggiatura). Siccome l'audio è stato generato
proprio dallo script, le parole mostrate nei sottotitoli devono essere
quelle dello script: questa funzione riallinea le due sequenze con
difflib, tenendo i tempi di Whisper e le parole dello script.

Casi gestiti:
  - parola trascritta diversa  -> si usa la parola dello script (stessi tempi);
  - parola saltata da Whisper  -> si interpola il timing tra i vicini;
  - parola extra trascritta    -> si tiene invariata (preserva la continuità dei tempi).
"""

import difflib

from core.keywords import normalize_word


class AlignmentError(Exception):
    """Errore durante l'allineamento trascrizione/script."""
    pass


def _interp_missing(missing: list[str], prev_end: float, next_start: float | None) -> list[dict]:
    """Distribuisce le parole saltate da Whisper nell'intervallo tra i vicini."""
    n = len(missing)
    if next_start is None or next_start <= prev_end:
        next_start = prev_end + 0.3 * n
    span = (next_start - prev_end) / n
    return [
        {"word": w, "start": prev_end + span * i, "end": prev_end + span * (i + 1)}
        for i, w in enumerate(missing)
    ]


def _enforce_monotonic(words: list[dict]) -> None:
    """Garantisce timestamp non sovrapposti e crescenti (fix per interpolazioni)."""
    prev_end = 0.0
    for w in words:
        if w["start"] < prev_end:
            w["start"] = prev_end
        if w["end"] <= w["start"]:
            w["end"] = w["start"] + 0.05
        prev_end = w["end"]


def align_transcript(transcribed: list[dict], script_text: str) -> tuple[list[dict], dict]:
    """Riallinea le parole trascritte allo script originale.

    Args:
        transcribed: [{"word", "start", "end"}] da Whisper.
        script_text: testo originale usato per generare l'audio.

    Returns:
        (parole_allineate, stats) dove stats = {"match_ratio", "corrected",
        "interpolated", "extra"}.

    Raises:
        AlignmentError: se mancano parole trascritte o script.
    """
    if not transcribed:
        raise AlignmentError("Nessuna parola trascritta da allineare.")
    script_tokens = script_text.split()
    if not script_tokens:
        raise AlignmentError("Script vuoto: niente da allineare.")

    script_norm = [normalize_word(w) for w in script_tokens]
    tr_norm = [normalize_word(w["word"]) for w in transcribed]

    matcher = difflib.SequenceMatcher(a=script_norm, b=tr_norm, autojunk=False)
    aligned: list[dict] = []
    corrected = 0
    interpolated = 0
    extra = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                word = dict(transcribed[j1 + k])
                word["word"] = script_tokens[i1 + k]  # forma esatta dello script
                aligned.append(word)
        elif tag == "replace":
            # Accoppia nel limite del possibile: tempi di Whisper, parole dello script.
            for k in range(min(i2 - i1, j2 - j1)):
                word = dict(transcribed[j1 + k])
                word["word"] = script_tokens[i1 + k]
                aligned.append(word)
                corrected += 1
            if (i2 - i1) > (j2 - j1):
                # Parole dello script senza timing: interpola.
                prev_end = aligned[-1]["end"] if aligned else 0.0
                nxt = transcribed[j2]["start"] if j2 < len(transcribed) else None
                missing = script_tokens[i1 + (j2 - j1):i2]
                aligned.extend(_interp_missing(missing, prev_end, nxt))
                interpolated += len(missing)
            else:
                # Parole extra trascritte: si tengono per continuità dei tempi.
                aligned.extend(dict(w) for w in transcribed[j1 + (i2 - i1):j2])
                extra += (j2 - j1) - (i2 - i1)
        elif tag == "delete":
            # Parole dello script saltate da Whisper: interpola il timing.
            prev_end = aligned[-1]["end"] if aligned else 0.0
            nxt = transcribed[j1]["start"] if j1 < len(transcribed) else None
            missing = script_tokens[i1:i2]
            aligned.extend(_interp_missing(missing, prev_end, nxt))
            interpolated += len(missing)
        elif tag == "insert":
            aligned.extend(dict(w) for w in transcribed[j1:j2])
            extra += j2 - j1

    _enforce_monotonic(aligned)
    stats = {
        "match_ratio": round(matcher.ratio(), 3),
        "corrected": corrected,
        "interpolated": interpolated,
        "extra": extra,
    }
    return aligned, stats
