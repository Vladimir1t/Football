"""Matching entities (players, teams) between providers.

The same player appears as:
    provider A:  "Aleksey Smirnov"   (Latin, first name first, own transliteration)
    provider B:  "Смирнов Алексей"   (Cyrillic, surname first)
    GPS system:  "А. Смирнов"        (initial + surname)

Strategy: transliterate everything to Latin, lowercase, drop punctuation,
compare token sets (order-insensitive), understand initials. Then match with
the strongest key available: (team, jersey) confirmed by the name, falling back
to fuzzy name within the team. Anything below the threshold is left unmatched
for a human to review: a wrong automatic match is worse than no match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}

# Different romanizations of the same sound collapse to one form.
_LATIN_FOLD = [("yo", "e"), ("iy", "y"), ("yy", "y"), ("ks", "x"), ("ck", "k"), ("w", "v")]


def transliterate(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())


def normalize_tokens(name: str) -> list[str]:
    """'Смирнов Алексей' -> ['aleksey', 'smirnov'] (sorted, folded)."""
    text = transliterate(name)
    text = re.sub(r"[^a-z\s]", " ", text)
    tokens = []
    for tok in text.split():
        for a, b in _LATIN_FOLD:
            tok = tok.replace(a, b)
        tokens.append(tok)
    return sorted(tokens)


def name_similarity(a: str, b: str) -> float:
    """Similarity in [0, 1], order-insensitive, aware of initials ('А. Смирнов')."""
    ta, tb = normalize_tokens(a), normalize_tokens(b)
    if not ta or not tb:
        return 0.0
    initials_a = [t for t in ta if len(t) == 1]
    initials_b = [t for t in tb if len(t) == 1]
    if initials_a or initials_b:
        # Compare surnames (longest tokens) and check the initial matches a first-name letter.
        full, short = (tb, ta) if initials_a else (ta, tb)
        short_words = [t for t in short if len(t) > 1]
        if not short_words:
            return 0.0
        surname = max(short_words, key=len)
        best = max(SequenceMatcher(None, surname, t).ratio() for t in full)
        initial = next(t for t in short if len(t) == 1)
        initial_ok = any(t.startswith(initial) for t in full if t != surname)
        return best if initial_ok else best * 0.7
    return SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()


@dataclass(frozen=True)
class Candidate:
    """A player of the master source (provider A)."""

    player_id: int
    name: str
    team_id: int
    jersey: int | None


@dataclass(frozen=True)
class MatchResult:
    player_id: int | None
    method: str
    score: float


def match_player(
    name: str,
    team_id: int | None,
    jersey: int | None,
    candidates: list[Candidate],
    jersey_confirm: float = 0.6,
    fuzzy_threshold: float = 0.85,
) -> MatchResult:
    same_team = [c for c in candidates if c.team_id == team_id]
    if not same_team:
        return MatchResult(None, "unmatched", 0.0)

    # 1) Strongest key: same team and shirt number, confirmed by a similar name
    #    (numbers get reassigned between seasons; the name guards against that).
    if jersey is not None:
        for c in same_team:
            if c.jersey == jersey:
                score = name_similarity(name, c.name)
                if score >= jersey_confirm:
                    return MatchResult(c.player_id, "team+jersey", round(score, 3))

    # 2) Fuzzy name within the team.
    scored = sorted(((name_similarity(name, c.name), c) for c in same_team), key=lambda x: -x[0])
    best_score, best = scored[0]
    if best_score >= fuzzy_threshold:
        # Ambiguity guard: two players with almost the same score -> let a human decide.
        if len(scored) > 1 and best_score - scored[1][0] < 0.05:
            return MatchResult(None, "unmatched", round(best_score, 3))
        return MatchResult(best.player_id, "name_fuzzy", round(best_score, 3))
    return MatchResult(None, "unmatched", round(best_score, 3))


def match_team(source_name: str, teams: list[tuple[int, str, list[str]]], threshold: float = 0.8) -> tuple[int | None, str]:
    """teams: (team_id, canonical_name, aliases). Exact alias first, then transliterated fuzzy."""
    for team_id, name, aliases in teams:
        if source_name == name or source_name in aliases:
            return team_id, "alias"
    best_id, best_score = None, 0.0
    for team_id, name, aliases in teams:
        for variant in [name, *aliases]:
            score = name_similarity(source_name, variant)
            if score > best_score:
                best_id, best_score = team_id, score
    if best_score >= threshold:
        return best_id, "fuzzy"
    return None, "unmatched"
