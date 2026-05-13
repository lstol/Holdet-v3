"""Shared name-matching utility — extracted from server.py for cross-module
reuse (S17-1 Sub-A origin; extended in name-matcher-hardening 2026-05-14).

Two consumers post-extraction:
- server.py (TV2 standings ingestion, optimizer-output post-processing, etc.)
- optimizer.py build_probabilities (odds-JSON name canonicalisation + intel
  key_signals rider canonicalisation against canonical riders.json roster)

Public surface:
- _ascii_fold(s)       — NFKD-decompose, drop combining marks, lowercase
- _NICKNAME_ALIASES    — bidirectional folded aliases dict
- match_rider_name(query, roster) → rider-dict or None

Matcher resolution order (first single-match wins; multi-match returns None):
  1. Exact accent-/case-folded equality, alias-aware
  2. Initial+lastname  ('J. Milan' → 'Jonathan Milan')
  3. Rule X: first-word AND last-word match  (drops middle names)
             ('Einer Rubio' → 'Einer Augusto Rubio')
  4. Rule Y: every query word appears as a complete whitespace-delimited
             word in the rider name  (handles missing-first / extra-middle)
             ('Thomas Silva' → 'Guillermo Thomas Silva')
  5. Last-word-of-query == last-word-of-rider
             ('Milan' → 'Jonathan Milan')

All comparisons are ASCII-folded.
"""
import unicodedata


def _ascii_fold(s: str) -> str:
    """NFKD-decompose, drop combining marks, lowercase. So 'González' → 'gonzalez',
    'Tjøtta' → 'tjotta'. Used by match_rider_name so ASCII-only paste input
    (e.g. vision OCR dropping accents) still matches accented roster names."""
    nfkd = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in nfkd if not unicodedata.combining(c)).lower()


# Bidirectional nickname / formal-expansion aliases. Used when the matcher's
# structural rules can't bridge a source-vs-canonical gap (e.g. TV2 publishes
# Spanish riders' formal-name expansions; riders.json carries the nickname).
# Keys/values are ASCII-folded. The reverse direction is added at module load
# so a query in either form resolves the other.
# If this grows past ~10 entries, lift to a dedicated aliases.json file.
_NICKNAME_ALIASES_RAW = {
    "juanpe lopez": "juan pedro lopez",  # roster: "Juanpe Lopez", TV2: "Juan Pedro Lopez"
    # name-matcher-hardening 2026-05-14: Oddschecker's "Jonas Vingegaard Hansen"
    # carries the patronymic that riders.json drops. Rules X / Y / 5 all fail
    # because the trailing token "hansen" doesn't appear in the canonical name.
    "jonas vingegaard hansen": "jonas vingegaard",
    # name-matcher-hardening 2026-05-14: Oddschecker's "Afonso Eulário" is a
    # single-character source typo for canonical "Afonso Eulálio" (R vs L in
    # surname). Same shape as Oruis/Orluis (which Rule 5 caught because the
    # canonical surname was unique); here Rule 5 fails because the last-word
    # differs from canonical.
    "afonso eulario": "afonso eulalio",
}
_NICKNAME_ALIASES: dict = {}
for _a, _b in _NICKNAME_ALIASES_RAW.items():
    _NICKNAME_ALIASES[_a] = _b
    _NICKNAME_ALIASES[_b] = _a


def match_rider_name(query: str, roster: list):
    """Match a free-form rider name against a roster of {'name': ...} dicts.
    Returns the matched rider dict or None.

    See module docstring for resolution order.
    """
    q = query.strip()
    if not q:
        return None
    qf      = _ascii_fold(q)
    qparts  = qf.split()
    qf_alt  = _NICKNAME_ALIASES.get(qf)  # alternative form, or None

    # 1. Exact (alias-aware)
    def _matches(rf: str) -> bool:
        return rf == qf or (qf_alt is not None and rf == qf_alt)
    exact = next((r for r in roster if _matches(_ascii_fold(r['name']))), None)
    if exact:
        return exact

    # 2. Initial+lastname (e.g. "J. Milan")
    parts = q.split()
    if len(parts) >= 2 and len(parts[0]) <= 3 and parts[0].endswith('.'):
        initial  = _ascii_fold(parts[0][0])
        lastname = _ascii_fold(' '.join(parts[1:]))
        candidates = [
            r for r in roster
            if _ascii_fold(r['name']).endswith(lastname)
            and _ascii_fold(r['name'].split()[0][0]) == initial
        ]
        if len(candidates) == 1:
            return candidates[0]

    # 3. Rule X: first-word AND last-word match (handles middle-name drops)
    if len(qparts) >= 2:
        qf_first, qf_last = qparts[0], qparts[-1]
        candidates = [
            r for r in roster
            if _ascii_fold(r['name'].split()[0])  == qf_first
            and _ascii_fold(r['name'].split()[-1]) == qf_last
        ]
        if len(candidates) == 1:
            return candidates[0]

    # 4. Rule Y: every query word is a whole word in the rider name
    if len(qparts) >= 2:
        candidates = [
            r for r in roster
            if all(qw in _ascii_fold(r['name']).split() for qw in qparts)
        ]
        if len(candidates) == 1:
            return candidates[0]

    # 5. Last-word-of-query == last-word-of-rider
    # (Pre-fix bug: compared full folded query against rider's last word —
    # 'einer rubio' could never equal 'rubio'. Existing callers route through
    # rules 1–2 with single-word or initial-form queries, so the bug was
    # latent for them; multi-word "first last" queries from TV2 surfaced it.)
    qf_last_word = qparts[-1] if qparts else qf
    candidates = [r for r in roster if _ascii_fold(r['name']).split()[-1] == qf_last_word]
    if len(candidates) == 1:
        return candidates[0]
    return None
