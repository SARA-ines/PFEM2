import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
import sys

import spacy

sys.path.append(str(Path(__file__).resolve().parents[1]))

from embedding_config import get_embedder
from preprocessing import prepare_ticket_text
from classifier_engine import load_classifier_bundle, predict_labels

try:
    nlp = spacy.load("fr_core_news_md")
except Exception:
    nlp = spacy.blank("fr")

CLASSIFIER_BUNDLE = load_classifier_bundle()

INTENTIONS = {
    "signaler_erreur": ["erreur", "bug", "probleme", "ne fonctionne pas", "crash", "bloque", "plante"],
    "demander_solution": ["comment", "aide", "resoudre", "corriger", "reparer"],
    "escalade": ["urgent", "critique", "bloquant", "impossible de travailler", "production"],
    "fournir_info": ["le module", "c est", "il s agit", "j ai", "voici"],
}

MODULE_KEYWORDS = {
    "stock": {
        "stock": 4,
        "mouvement": 2,
        "inventaire": 3,
        "magasin": 2,
        "article": 2,
        "biggestion": 5,
        "big gestion": 5,
        "entree": 2,
        "sortie": 2,
        "cump": 6,
        "winstock": 6,
        "reception": 2,
        "livraison": 2,
        "carburant": 3,
        "bon sortie": 3,
        "bon entree": 5,
        "lot": 3,
        "balance cumulee": 5,
        "quantite en stock": 6,
    },
    "paie": {
        "paie": 4,
        "bigpaie": 6,
        "bulletin": 3,
        "salaire": 3,
        "rubrique": 4,
        "irg": 6,
        "cotisation": 3,
        "rappel": 4,
        "recap": 3,
        "emoluments": 2,
        "net a payer": 5,
        "retenue": 3,
        "brut": 2,
        "cacobatph": 5,
        "das": 4,
        "virement salaires": 6,
        "fichier txt": 3,
    },
    "rh": {
        "rh": 3,
        "grh": 4,
        "biggrh": 6,
        "employe": 4,
        "conge": 4,
        "carriere": 2,
        "contrat": 4,
        "recrutement": 2,
        "formation": 2,
        "pointage": 3,
        "biggt": 5,
        "absence": 4,
    },
    "comptabilite": {
        "comptabilite": 4,
        "bigfinance": 6,
        "ecriture": 3,
        "journal": 4,
        "balance": 3,
        "bilan": 4,
        "compte": 3,
        "immobilisation": 2,
        "amortissement": 2,
        "banque": 4,
        "piece comptable": 6,
        "reouverture": 5,
        "resultat exercice": 4,
        "sequence": 3,
    },
    "facturation": {
        "facture": 5,
        "facturation": 5,
        "client": 2,
        "avoir": 2,
        "reglement": 2,
        "paiement": 2,
        "bon de livraison": 4,
        "bl": 2,
        "ttc": 4,
        "comptabilise": 5,
        "comptabilisation": 5,
        "fournisseur": 4,
        "compte fournisseur": 5,
        "bon commande": 3,
        "bon livraison vers facture": 7,
        "detail non transfere": 6,
        "facture subventionnee": 6,
        "numero cf": 5,
    },
    "immobilisations": {
        "immobilisation": 5,
        "amortissement": 5,
        "immobilisations": 5,
        "bien": 3,
        "inventaire physique": 4,
        "cession": 4,
        "dotation": 4,
    },
    "tresorerie": {
        "tresorerie": 5,
        "caisse": 4,
        "cheque": 4,
        "virement": 3,
        "bordereau": 3,
        "banque": 3,
        "rapprochement": 5,
        "decaissement": 4,
    },
    "fiscalite": {
        "fiscalite": 5,
        "tva": 5,
        "tax": 4,
        "declaration": 4,
        "impot": 4,
        "fiscal": 4,
    },
    "budget": {
        "budget": 5,
        "previsionnel": 4,
        "ecart budget": 5,
        "realisation": 3,
        "enveloppe": 3,
    },
    "analytique": {
        "analytique": 5,
        "centre de cout": 5,
        "axe": 4,
        "ventilation": 4,
        "imputation": 4,
    },
    "gestion_temps": {
        "pointage": 5,
        "gestion du temps": 6,
        "biggt": 6,
        "presence": 4,
        "retard": 3,
        "planning": 4,
        "horaire": 3,
        "conge": 3,
    },
    "achats": {
        "achat": 4,
        "commande achat": 5,
        "bon de commande": 4,
        "fournisseur": 3,
        "appel offre": 4,
        "reception": 3,
    },
    "ventes": {
        "vente": 4,
        "client": 2,
        "devis": 4,
        "commande client": 5,
        "bon livraison": 3,
        "tarif": 3,
    },
    "sav": {
        "sav": 5,
        "service apres vente": 6,
        "intervention": 4,
        "garantie": 4,
        "reparation": 4,
        "technicien terrain": 4,
    },
    "crm": {
        "crm": 5,
        "prospect": 4,
        "lead": 4,
        "opportunite": 4,
        "relation client": 5,
        "campagne": 3,
    },
    "marches": {
        "marche": 4,
        "appel d offre": 5,
        "soumission": 4,
        "contrat marche": 5,
        "avenant": 4,
    },
    "gpao": {
        "gpao": 5,
        "production": 4,
        "ordre de fabrication": 5,
        "gamme": 4,
        "nomenclature": 4,
        "atelier": 3,
    },
    "qualite": {
        "qualite": 5,
        "non conformite": 5,
        "audit": 4,
        "iso": 4,
        "controle qualite": 5,
    },
    "gestion_projets": {
        "projet": 4,
        "gestion de projets": 6,
        "planning projet": 5,
        "jalon": 4,
        "gantt": 5,
    },
    "gestion_taches": {
        "tache": 4,
        "gestion des taches": 6,
        "workflow": 4,
        "affectation tache": 5,
    },
    "gestion_flotte": {
        "flotte": 5,
        "vehicule": 4,
        "parc auto": 5,
        "carburant": 3,
        "entretien vehicule": 5,
    },
    "gestion_marches": {
        "marche immobilier": 5,
        "gestion des marches": 6,
        "bigmarpi": 6,
        "promotion immobiliere": 5,
    },
    "gestion_immobiliere": {
        "immobilier": 4,
        "gestion immobiliere": 6,
        "lot": 3,
        "programme": 3,
        "bien immobilier": 5,
    },
    "suivi_realisation": {
        "suivi realisation": 6,
        "avancement travaux": 5,
        "chantier": 4,
    },
    "gestion_location": {
        "location": 5,
        "loyer": 5,
        "locataire": 5,
        "bail": 4,
    },
    "gestion_documents": {
        "ged": 5,
        "gestion documentaire": 6,
        "document": 3,
        "archivage": 4,
        "numerisation": 4,
    },
}

TYPE_KEYWORDS = {
    "base_de_donnees": {
        "sql": 7,
        "base de donnees": 6,
        "bdd": 5,
        "script": 4,
        "table": 5,
        "colonne": 6,
        "connexion serveur": 6,
        "odbc": 7,
        "service sql": 7,
        "discordance": 5,
        "manquante": 4,
        "vide": 3,
        "transfert": 3,
        "non transfere": 6,
        "enregistrement": 4,
        "numero": 3,
    },
    "interface": {
        "affichage": 5,
        "bouton": 3,
        "fenetre": 4,
        "etat": 3,
        "impression": 6,
        "crystal": 6,
        "masque": 4,
        "liste deroulante": 6,
        "filtre": 3,
        "affiche": 4,
        "ecran": 5,
        "rapport": 5,
        "exportation": 4,
        "fichier txt": 5,
        "excel": 5,
    },
    "performance": {
        "lenteur": 7,
        "lent": 5,
        "blocage": 5,
        "bloque": 5,
        "freeze": 6,
        "instable": 4,
        "saturation": 6,
        "cesse de fonctionner": 6,
        "temps de reponse": 5,
        "regeneration": 4,
    },
    "permission": {
        "acces": 4,
        "licence": 6,
        "code activation": 7,
        "cle": 4,
        "utilisateur": 2,
        "droits": 5,
        "debridage": 5,
    },
    "configuration": {
        "parametrage": 6,
        "installation": 5,
        "mise a jour": 6,
        "version": 5,
        "reinstallation": 6,
        "word application": 7,
        "ouverture exercice": 6,
        "stock initial": 6,
        "lot aucun": 5,
        "chevauchement": 6,
        "periode essai": 5,
        "mise en disponibilite": 6,
        "deja comptabilisee": 6,
        "reouverture": 5,
        "conforme": 4,
    },
    "calcul": {
        "calcul": 5,
        "montant": 4,
        "anomalie": 3,
        "incoherence": 5,
        "ecart": 5,
        "stock negatif": 8,
        "cump": 8,
        "quantite": 4,
        "prix unitaire": 7,
        "net a payer": 7,
        "irg": 8,
        "rubrique": 5,
        "ttc": 5,
        "difference": 5,
        "balance cumulee": 6,
        "sequence": 5,
        "numerotation": 5,
        "compte 12000": 5,
    },
}

MODULE_TYPE_HINTS = {
    "stock": {
        "calcul": {"stock negatif": 6, "cump": 7, "prix unitaire": 5, "quantite": 4, "balance cumulee": 4},
        "configuration": {"stock initial": 6, "ouverture exercice": 5, "lot aucun": 5, "bon entree": 4},
        "performance": {"regeneration": 6, "cesse de fonctionner": 6},
        "interface": {"montant total": 5, "non affiche": 5},
    },
    "paie": {
        "base_de_donnees": {"discordance": 7, "colonne": 7, "service sql": 7, "table": 5},
        "calcul": {"rubrique": 5, "irg": 7, "net a payer": 6},
        "interface": {"fichier txt": 6, "genere vide": 6, "fiche de paie": 4},
        "configuration": {"das": 6, "nouvelle version": 4},
    },
    "rh": {
        "base_de_donnees": {"connexion serveur": 7, "message erreur acces": 5},
        "configuration": {"word application": 7, "mise en disponibilite": 6, "chevauchement": 6, "contrat": 4},
        "interface": {"absences non affichees": 7, "liste deroulante": 7, "impression": 5},
        "calcul": {"conges attribues": 6},
    },
    "comptabilite": {
        "base_de_donnees": {"journal banque": 6, "odbc": 7, "colonne fecriture": 8},
        "configuration": {"reouverture": 6, "resultat exercice": 5},
        "calcul": {"numerotation": 6, "sequence": 6},
        "interface": {"exportation balance excel": 7, "fichier vide": 5},
        "performance": {"blocage acces": 6, "connexions sql": 5, "licences": 3},
    },
    "facturation": {
        "base_de_donnees": {"compte fournisseur vide": 8, "transfert": 6, "non transfere": 7, "enregistrement": 5, "numero": 4},
        "calcul": {"montant ttc": 7, "net a payer": 6},
        "configuration": {"deja comptabilisee": 7, "suppression impossible": 5},
    },
}

SOFTWARE_KEYWORDS = {
    "biggrh": ["biggrh", "wingrh", "grh"],
    "bigfinance": ["bigfinance", "big finance"],
    "biggestion": ["biggestion", "big gestion", "winstock"],
    "bigpaie": ["bigpaie", "paie"],
    "biggt": ["biggt"],
}

VERSION_PATTERNS = [
    r"\bv\d+(?:\.\d+){0,3}[a-z]?\b",
    r"\bversion\s+\d+(?:\.\d+){0,3}[a-z]?\b",
    r"\b\d+(?:\.\d+){2,4}[a-z]?\b",
]


def _normalize(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokens(text: str) -> list[str]:
    return [token for token in text.split() if token]


def _match_keyword_score(text: str, keyword: str, threshold: float = 0.86) -> float:
    if keyword in text:
        return 1.0

    text_tokens = _tokens(text)
    key_tokens = _tokens(keyword)
    if not text_tokens or not key_tokens:
        return 0.0

    window = len(key_tokens)
    best = 0.0
    if window == 1:
        for token in text_tokens:
            best = max(best, SequenceMatcher(None, token, key_tokens[0]).ratio())
    else:
        for start in range(max(len(text_tokens) - window + 1, 1)):
            candidate = " ".join(text_tokens[start : start + window])
            best = max(best, SequenceMatcher(None, candidate, keyword).ratio())

    return best if best >= threshold else 0.0


def _score_weighted_keywords(text: str, weighted_keywords: dict[str, float]) -> dict[str, float]:
    scores = {}
    for key, weight in weighted_keywords.items():
        match_score = _match_keyword_score(text, key)
        if match_score > 0:
            scores[key] = round(weight * (1.0 if match_score >= 0.99 else 0.7), 3)
    return scores


def _normalize_scores(raw_scores: dict[str, float]) -> dict[str, float]:
    positive = {key: value for key, value in raw_scores.items() if value > 0}
    total = sum(positive.values())
    if total <= 0:
        return {}
    return {key: round(value / total, 4) for key, value in positive.items()}


def _confidence_from_scores(raw_scores: dict[str, float], best_key: str, default: float = 0.3) -> float:
    if not raw_scores or not best_key:
        return default
    total = sum(raw_scores.values()) or 1.0
    best_raw = raw_scores.get(best_key, 0.0)
    ratio = best_raw / total
    confidence = 0.35 + min(best_raw / 12.0, 0.3) + ratio * 0.3
    return round(min(confidence, 0.95), 2)


def detect_intention(text: str) -> tuple[str, float]:
    text_low = _normalize(text)
    scores = {}
    for intent, keywords in INTENTIONS.items():
        score = sum(1 for kw in keywords if _match_keyword_score(text_low, _normalize(kw)) > 0)
        if score:
            scores[intent] = score
    if not scores:
        return "inconnu", 0.4
    best = max(scores, key=scores.get)
    confidence = min(0.55 + scores[best] * 0.1, 0.95)
    return best, round(confidence, 2)


def detect_software(text: str) -> str:
    text_low = _normalize(text)
    scores = {}
    for software, aliases in SOFTWARE_KEYWORDS.items():
        score = 0.0
        for alias in aliases:
            match_score = _match_keyword_score(text_low, _normalize(alias))
            if match_score:
                score += 2.0 if match_score >= 0.99 else 1.2
        if score > 0:
            scores[software] = score
    return max(scores, key=scores.get) if scores else ""


def detect_version(text: str) -> str:
    text_low = _normalize(text)
    for pattern in VERSION_PATTERNS:
        match = re.search(pattern, text_low, re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def detect_module(text: str, software: str = "") -> tuple[str, float, dict[str, float]]:
    text_low = _normalize(text)
    raw_scores = {module: 0.0 for module in MODULE_KEYWORDS}

    for module, weighted_keywords in MODULE_KEYWORDS.items():
        raw_scores[module] += sum(_score_weighted_keywords(text_low, weighted_keywords).values())

    software_to_module = {
        "biggrh": "rh",
        "bigfinance": "comptabilite",
        "biggestion": "stock",
        "bigpaie": "paie",
        "biggt": "rh",
    }
    if software and software in software_to_module:
        raw_scores[software_to_module[software]] += 6.0

    best_module = max(raw_scores, key=raw_scores.get)
    if raw_scores[best_module] <= 0:
        return "", 0.3, {}

    confidence = _confidence_from_scores(raw_scores, best_module)
    return best_module, confidence, _normalize_scores(raw_scores)


def detect_type_incident(text: str, module: str = "") -> tuple[str, float, dict[str, float]]:
    text_low = _normalize(text)
    raw_scores = {incident_type: 0.0 for incident_type in TYPE_KEYWORDS}

    for incident_type, weighted_keywords in TYPE_KEYWORDS.items():
        raw_scores[incident_type] += sum(_score_weighted_keywords(text_low, weighted_keywords).values())

    for incident_type, hints in MODULE_TYPE_HINTS.get(module, {}).items():
        raw_scores[incident_type] += sum(_score_weighted_keywords(text_low, hints).values())

    if raw_scores.get("base_de_donnees", 0) == 0 and ("erreur" in text_low or "error" in text_low):
        raw_scores["base_de_donnees"] += 1.5

    best_type = max(raw_scores, key=raw_scores.get)
    if raw_scores[best_type] <= 0:
        return "", 0.3, {}

    confidence = _confidence_from_scores(raw_scores, best_type)
    return best_type, confidence, _normalize_scores(raw_scores)


def extract_entities(text: str) -> dict:
    doc = nlp(text)
    entities = {}
    for ent in getattr(doc, "ents", []):
        entities[ent.label_] = ent.text

    codes = re.findall(r"\b(?:erreur|error|code)\s*[:#]?\s*(\w+)", text, re.IGNORECASE)
    if codes:
        entities["code_erreur"] = codes[0]
    return entities


def analyze(text: str) -> dict:
    prepared = prepare_ticket_text(text)
    original_text = text or ""
    working_text = prepared["enriched"] or original_text
    normalized_text = prepared["normalized"]
    software = detect_software(working_text)
    version = detect_version(working_text)
    intention, conf_intention = detect_intention(working_text)
    module, module_conf, module_scores = detect_module(working_text, software)
    type_incident, type_confidence, type_scores = detect_type_incident(working_text, module)

    classifier_prediction = {}
    if CLASSIFIER_BUNDLE is not None:
        classifier_prediction = predict_labels(CLASSIFIER_BUNDLE, working_text)
        predicted_module = classifier_prediction.get("module", "")
        predicted_type = classifier_prediction.get("type_incident", "")
        predicted_module_scores = classifier_prediction.get("module_scores", {})
        predicted_type_scores = classifier_prediction.get("type_scores", {})

        if predicted_module:
            module_scores = {
                label: round(module_scores.get(label, 0.0) * 0.65 + predicted_module_scores.get(label, 0.0) * 0.35, 4)
                for label in set(module_scores) | set(predicted_module_scores)
            }
            module = max(module_scores, key=module_scores.get) if module_scores else module
            module_conf = max(module_conf, predicted_module_scores.get(module, 0.0))

        if predicted_type:
            type_scores = {
                label: round(type_scores.get(label, 0.0) * 0.65 + predicted_type_scores.get(label, 0.0) * 0.35, 4)
                for label in set(type_scores) | set(predicted_type_scores)
            }
            type_incident = max(type_scores, key=type_scores.get) if type_scores else type_incident
            type_confidence = max(type_confidence, predicted_type_scores.get(type_incident, 0.0))

    entities = extract_entities(text)
    embedding = get_embedder().encode(working_text).tolist()

    best_type_score = max(type_scores.values()) if type_scores else 0.0
    confidence = round(
        min((module_conf * 0.35) + (type_confidence * 0.4) + (conf_intention * 0.15) + (best_type_score * 0.1), 0.95),
        2,
    )

    return {
        "intention": intention,
        "module": module,
        "type_incident": type_incident,
        "entities": entities,
        "confidence": confidence,
        "embedding": embedding,
        "normalized_text": normalized_text,
        "condensed_text": prepared["condensed"],
        "software": software,
        "software_version": version,
        "module_scores": module_scores,
        "type_scores": type_scores,
        "classifier_prediction": classifier_prediction,
    }
