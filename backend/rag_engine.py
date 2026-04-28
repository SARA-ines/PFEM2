import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

sys.path.append(str(Path(__file__).resolve().parents[1]))

from embedding_config import EMBEDDING_MODEL_NAME
from preprocessing import prepare_ticket_text, normalize_text as preprocess_normalize

embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)

MODULE_KEYWORDS = {
    "stock": ["stock", "mouvement", "inventaire", "magasin", "entree", "sortie", "article", "biggestion", "big gestion", "winstock", "cump", "reception", "bon de commande", "livraison"],
    "paie": ["paie", "bigpaie", "bulletin", "salaire", "rubrique", "irg", "cotisation", "rappel", "recap", "emoluments", "net a payer", "retenue", "brut", "cacobatph", "das"],
    "rh": ["rh", "grh", "biggrh", "employe", "conge", "carriere", "contrat", "recrutement", "depart", "fiche employe", "formation", "pointage", "biggt"],
    "comptabilite": ["comptabilite", "bigfinance", "big finance", "ecriture", "journal", "balance", "bilan", "compte", "tva", "immobilisation", "amortissement", "grand livre"],
    "facturation": ["facture", "facturation", "client", "avoir", "reglement", "paiement", "devis", "bon de livraison", "bl", "ttc", "comptabilise", "comptabilisation", "fournisseur", "compte fournisseur"],
    "achat": ["achat", "fournisseur", "bon de commande fournisseur", "approvisionnement"],
}

TYPE_KEYWORDS = {
    "base_de_donnees": ["sql", "base de donnees", "bdd", "script", "table", "colonne", "insert", "constraint", "connexion serveur", "odbc", "structure", "migration"],
    "interface": ["affichage", "bouton", "fenetre", "etat", "impression", "rapport", "crystal", "excel", "ecran", "masque", "liste deroulante", "filtre"],
    "performance": ["lenteur", "lent", "blocage", "bloque", "freeze", "timeout", "instable", "saturation"],
    "permission": ["acces", "licence", "code activation", "cle", "utilisateur", "droits", "permission", "debridage"],
    "configuration": ["parametrage", "parametre", "configuration", "reglage", "setup", "installation", "reinstallation", "mise a jour", "version", "maj"],
    "calcul": ["calcul", "erreur de calcul", "montant", "anomalie calcul", "incoherence", "discordance", "ecart", "cump", "quantite", "prix unitaire", "ttc"],
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

NON_ACTIONABLE_SOLUTION_PHRASES = [
    "en attente",
    "merci de nous",
    "merci d envoyer",
    "votre demande sera",
    "bien recu",
    "bien reçu",
    "veuillez nous communiquer",
    "veuillez nous preciser",
    "veuillez nous préciser",
    "merci de preciser",
    "merci de préciser",
    "merci de verifier",
    "merci de vérifier",
    "merci de recontacter",
    "nous n avons pas reussi a vous joindre",
    "nous n'avons pas reussi a vous joindre",
    "envoye par mail",
    "envoye par email",
    "proforma",
    "copier l integralite du message",
    "copier l'integralite du message",
    "cette problematique ne vous est pas destinee",
    "nous n avons toujours rien recu",
    "nous n'avons toujours rien recu",
]

SOLUTION_SIGNAL_TERMS = [
    "corrige",
    "corrigé",
    "resolu",
    "résolu",
    "regle",
    "réglé",
    "redemarrage",
    "redémarrage",
    "mise a jour",
    "mise à jour",
    "script",
    "parametre",
    "paramètre",
    "configuration",
    "modifier",
    "modification",
    "service sql",
    "verification",
    "vérification",
    "fonctionne correctement",
]


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def lexical_overlap(text_a: str, text_b: str) -> float:
    tokens_a = {token for token in preprocess_normalize(text_a).split() if len(token) > 2}
    tokens_b = {token for token in preprocess_normalize(text_b).split() if len(token) > 2}
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def detect_module(text: str) -> str:
    text_low = normalize_text(text)
    scores = {}
    for module, keywords in MODULE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_low)
        if score:
            scores[module] = score
    return max(scores, key=scores.get) if scores else "general"


def detect_type(text: str) -> str:
    text_low = normalize_text(text)
    scores = {}
    for incident_type, keywords in TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_low)
        if score:
            scores[incident_type] = score
    return max(scores, key=scores.get) if scores else "autre"


def detect_software(text: str) -> str:
    text_low = normalize_text(text)
    scores = {}
    for software, aliases in SOFTWARE_KEYWORDS.items():
        score = sum(1 for alias in aliases if alias in text_low)
        if score:
            scores[software] = score
    return max(scores, key=scores.get) if scores else ""


def detect_version(text: str) -> str:
    text_low = normalize_text(text)
    for pattern in VERSION_PATTERNS:
        match = re.search(pattern, text_low, re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def extract_solution(full_text: str) -> str:
    match = re.search(r"Solution:\s*(.*?)$", full_text, re.DOTALL)
    if match:
        solution = match.group(1).strip()
        normalized_solution = normalize_text(solution)
        if len(solution) > 20 and not any(
            phrase in normalized_solution
            for phrase in NON_ACTIONABLE_SOLUTION_PHRASES
        ):
            return solution[:500]
    return ""


def is_actionable_solution(solution: str) -> bool:
    normalized_solution = normalize_text(solution)
    if len(normalized_solution) < 24:
        return False
    if any(phrase in normalized_solution for phrase in NON_ACTIONABLE_SOLUTION_PHRASES):
        return False
    if "merci" in normalized_solution and not any(term in normalized_solution for term in SOLUTION_SIGNAL_TERMS):
        return False
    if any(term in normalized_solution for term in SOLUTION_SIGNAL_TERMS):
        return True
    if len(normalized_solution.split()) >= 8 and any(char.isdigit() for char in normalized_solution):
        return True
    return len(normalized_solution.split()) >= 10


def extract_query_error_tokens(text: str) -> set[str]:
    normalized = normalize_text(text)
    return {
        token
        for token in normalized.split()
        if len(token) > 3 and any(char.isdigit() for char in token)
    }


def extract_probleme(full_text: str) -> str:
    match = re.search(r"Probl(?:e|Ã¨)me:\s*(.*?)(?:\nConversation:|$)", full_text, re.DOTALL)
    return match.group(1).strip()[:300] if match else ""


class RAGEngine:
    def __init__(self):
        self.tickets = []
        self.index = None
        self.embeddings = None
        self._load_tickets()
        self._build_index()

    def _load_tickets(self):
        # Cherche d'abord dans le même dossier, puis un niveau au-dessus
        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, "ticket_metadata.json")
        if not os.path.exists(path):
            path = os.path.join(base_dir, "..", "ticket_metadata.json")
            path = os.path.abspath(path)
        if not os.path.exists(path):
            print(f"ticket_metadata.json introuvable (cherche dans {base_dir})")
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        skipped = 0
        skipped_non_actionable = 0
        for ticket in data:
            full_text = ticket.get("full_text", "")
            probleme = extract_probleme(full_text)
            solution = extract_solution(full_text)
            objet = ticket.get("objet", "").strip()
            if not solution:
                skipped += 1
                continue
            if not is_actionable_solution(solution):
                skipped_non_actionable += 1
                continue

            prepared = prepare_ticket_text(probleme or full_text)
            condensed_problem = prepared["enriched"] or probleme or full_text
            source_text = f"{objet} {condensed_problem}"
            module = detect_module(source_text)
            incident_type = detect_type(source_text)
            software = detect_software(source_text)
            version = detect_version(source_text)

            self.tickets.append(
                {
                    "id": str(ticket.get("ticket_id", ticket.get("db_id", "?"))),
                    "objet": objet,
                    "module": module,
                    "type": incident_type,
                    "software": software,
                    "version": version,
                    "description": f"{objet}. {condensed_problem}",
                    "normalized_description": preprocess_normalize(f"{objet}. {condensed_problem}"),
                    "solution": solution,
                    "normalized_solution": preprocess_normalize(solution),
                    "full_text": full_text[:400],
                }
            )

        print(
            f"{len(self.tickets)} tickets utiles charges "
            f"({skipped} sans solution ignores, {skipped_non_actionable} solutions non actionnables ignorees)"
        )

    def _build_index(self):
        if not self.tickets:
            print("Aucun ticket a indexer")
            return

        texts = [
            f"{ticket['objet']} {ticket['module']} {ticket['type']} {ticket['software']} {ticket['version']} {ticket['description']}"
            for ticket in self.tickets
        ]
        self.embeddings = embedder.encode(texts, show_progress_bar=False, batch_size=32)
        dim = self.embeddings.shape[1]
        self.index = faiss.IndexFlatL2(dim)
        self.index.add(self.embeddings.astype(np.float32))
        print(f"Index FAISS: {self.index.ntotal} vecteurs ({dim}D)")

    def search(
        self,
        query_embedding: list,
        k: int = 5,
        module_filter: str = "",
        type_filter: str = "",
        software_filter: str = "",
        version_filter: str = "",
        query_text: str = "",
        exclude_ticket_ids: list[str] | None = None,
    ) -> list[dict]:
        if not self.index or self.index.ntotal == 0:
            return []
        excluded_ids = {str(ticket_id) for ticket_id in (exclude_ticket_ids or [])}

        q = np.array([query_embedding], dtype=np.float32)
        n_search = min(k * 10, len(self.tickets))
        distances, indices = self.index.search(q, n_search)
        query_error_tokens = extract_query_error_tokens(query_text)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self.tickets):
                continue

            ticket = self.tickets[idx].copy()
            if excluded_ids and str(ticket.get("id", "")) in excluded_ids:
                continue
            base_similarity = float(1 / (1 + dist))
            lexical_score = lexical_overlap(query_text, ticket.get("description", "")) if query_text else 0.0
            solution_score = lexical_overlap(query_text, ticket.get("normalized_solution", "")) if query_text else 0.0
            similarity = base_similarity * 0.55 + lexical_score * 0.30 + solution_score * 0.15

            if module_filter and ticket.get("module") == module_filter:
                similarity *= 1.35
            elif module_filter:
                similarity *= 0.72
            if type_filter and ticket.get("type") == type_filter:
                similarity *= 1.20
            elif type_filter:
                similarity *= 0.82
            if software_filter and ticket.get("software") == software_filter:
                similarity *= 1.15
            if version_filter and ticket.get("version") == version_filter:
                similarity *= 1.08
            if query_error_tokens:
                ticket_text = f"{ticket.get('description', '')} {ticket.get('solution', '')}"
                if any(token in normalize_text(ticket_text) for token in query_error_tokens):
                    similarity *= 1.12

            ticket["similarity"] = round(min(similarity, 1.0), 3)
            ticket["base_similarity"] = round(base_similarity, 3)

            if ticket["similarity"] > 0.12:
                results.append(ticket)

        results.sort(key=lambda item: item["similarity"], reverse=True)
        return results[:k]

    def stats(self) -> dict:
        modules = Counter(ticket["module"] for ticket in self.tickets)
        types = Counter(ticket["type"] for ticket in self.tickets)
        return {"total": len(self.tickets), "par_module": dict(modules.most_common()), "par_type": dict(types.most_common())}


rag = RAGEngine()
