import re
import unicodedata


NOISE_PATTERNS = [
    r"\bbonjour\b",
    r"\bbonsoir\b",
    r"\bmerci\b",
    r"\bcordialement\b",
    r"\bnous vous informons\b",
    r"\bnous souhaitons vous informer\b",
    r"\bveuillez\b",
    r"\bfaire le necessaire\b",
    r"\bsuite a\b",
    r"\bfaisant suite\b",
    r"\bnous avons l honneur\b",
]

TECHNICAL_HINTS = {
    "erreur",
    "bloque",
    "blocage",
    "impression",
    "affichage",
    "sql",
    "odbc",
    "stock",
    "paie",
    "grh",
    "rh",
    "facture",
    "facturation",
    "compte",
    "journal",
    "bilan",
    "reouverture",
    "cump",
    "montant",
    "calcul",
    "licence",
    "acces",
    "transfert",
    "colonne",
    "table",
    "version",
    "installation",
}


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s:;,.!?/\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"[\r\n]+", ". ", text or "")
    parts = re.split(r"(?<=[.!?;:])\s+", normalized)
    return [part.strip(" .;:,\n\r\t") for part in parts if part and part.strip(" .;:,\n\r\t")]


def strip_noise_phrases(text: str) -> str:
    cleaned = normalize_text(text)
    for pattern in NOISE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _sentence_score(sentence: str) -> float:
    normalized = strip_noise_phrases(sentence)
    if not normalized:
        return 0.0

    score = 0.0
    tokens = set(normalized.split())
    score += sum(1.0 for hint in TECHNICAL_HINTS if hint in normalized or hint in tokens)
    if any(term in normalized for term in ["erreur", "bloque", "impossible", "anomalie"]):
        score += 2.0
    if len(tokens) >= 4:
        score += 0.5
    if len(tokens) > 25:
        score -= 0.5
    return score


def extract_problem_core(text: str, max_sentences: int = 3, max_chars: int = 320) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return normalize_text(text)[:max_chars]

    ranked = []
    for index, sentence in enumerate(sentences):
        score = _sentence_score(sentence)
        if score > 0:
            ranked.append((score, index, strip_noise_phrases(sentence)))

    if not ranked:
        cleaned = strip_noise_phrases(" ".join(sentences))
        return cleaned[:max_chars]

    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = sorted(ranked[:max_sentences], key=lambda item: item[1])
    summary = ". ".join(fragment for _, _, fragment in selected if fragment)
    return summary[:max_chars]


def prepare_ticket_text(text: str) -> dict:
    normalized = normalize_text(text)
    condensed = extract_problem_core(text)
    enriched = condensed if condensed else normalized
    return {
        "original": text or "",
        "normalized": normalized,
        "condensed": condensed,
        "enriched": enriched,
    }
