import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import faiss
import numpy as np
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from embedding_config import get_embedder
from preprocessing import prepare_ticket_text, normalize_text as preprocess_normalize
from database import SessionLocal

MODULE_ALIASES = {
    "achat": "achats",
    "achats": "achats",
    "big finance": "comptabilite",
    "bigfinance": "comptabilite",
    "comptabilité": "comptabilite",
    "comptabilite": "comptabilite",
    "grh": "rh",
    "biggrh": "rh",
    "gestion ressources humaines": "rh",
    "bigpaie": "paie",
    "big gestion": "stock",
    "biggestion": "stock",
    "winstock": "stock",
    "gestion du temps": "gestion_temps",
    "gdt": "gestion_temps",
    "biggt": "gestion_temps",
    "service apres vente": "sav",
    "service après vente": "sav",
    "gestion des marches": "gestion_marches",
    "gestion des marchés": "gestion_marches",
    "gestion immobiliere": "gestion_immobiliere",
    "gestion immobilière": "gestion_immobiliere",
    "suivi realisation": "suivi_realisation",
    "suivi réalisation": "suivi_realisation",
    "dynamic big reports": "dynamic_reports",
    "gestion des tickets de support": "tickets_support",
    "general": "non_classe",
    "général": "non_classe",
    "": "",
}

MODULE_KEYWORDS = {
    "immobilisations": {
        "immobilisation": 8, "immobilisations": 8, "amortissement": 7, "cession": 5,
        "valeur de sortie": 5, "bien immobilier": 5, "inventaire immobilisation": 5,
        "consolidation des immobilisations": 8, "codification automatique": 4,
    },
    "tresorerie": {
        "tresorerie": 8, "trésorerie": 8, "virement": 5, "cheque": 5, "chèque": 5,
        "caisse": 4, "releve bancaire": 5, "relevé bancaire": 5, "rapprochement bancaire": 5,
        "ordre versement": 5, "ordre virement": 5, "credit exploitation": 4,
        "credit invest": 4, "mouvement tiers": 4, "creance": 4, "créance": 4, "dette": 4,
    },
    "fiscalite": {
        "fiscal": 7, "fiscalite": 8, "fiscalité": 8, "g50": 8, "liasse fiscale": 8,
        "declaration": 5, "déclaration": 5, "tva": 5, "bilan fiscal": 7,
        "resultat fiscal": 6, "résultat fiscal": 6,
    },
    "budget": {
        "budget": 8, "budgetaire": 7, "budgétaire": 7, "engagement": 5,
        "reservation": 4, "réservation": 4, "poste budgetaire": 6, "prevision budgetaire": 6,
        "prévision budgétaire": 6, "realisation budgetaire": 6, "réalisation budgétaire": 6,
    },
    "analytique": {
        "analytique": 8, "biganalytique": 9, "centre de responsabilite": 6,
        "centre de responsabilité": 6, "comptabilite analytique": 7,
        "comptabilité analytique": 7,
    },
    "facturation": {
        "facturation": 8, "facture client": 7, "facture d avoir": 7, "facture d'avoir": 7,
        "avoir client": 6, "bon de livraison": 6, "bl": 3, "commande client": 5,
        "proforma client": 5, "paiement client": 5, "encaissement": 5,
        "bon chargement": 4, "retenue de garantie": 4,
    },
    "ventes": {
        "vente": 8, "ventes": 8, "commande client": 5, "contrat client": 5,
        "demande offre client": 5, "livraison en preparation": 5, "livraison en préparation": 5,
        "retour livraison": 5, "remise": 3, "franchise": 3,
    },
    "achats": {
        "achat": 8, "achats": 8, "commande fournisseur": 7, "facture fournisseur": 7,
        "avoir fournisseur": 6, "fournisseur": 3, "demande d achat": 6,
        "demande d'achat": 6, "approvisionnement": 5, "service fait": 4,
        "dossier import": 4, "tco": 4,
    },
    "stock": {
        "stock": 8, "mouvement stock": 7, "inventaire": 5, "magasin": 4, "article": 4,
        "biggestion": 2, "big gestion": 2, "winstock": 7, "cump": 7, "sortie stock": 6,
        "entree stock": 6, "entrée stock": 6, "transfert magasin": 5, "fiche article": 5,
        "gestion des kits": 5, "kit": 4, "retour entree": 4, "retour sortie": 4,
        "stock negatif": 6, "stock négatif": 6,
    },
    "paie": {
        "paie": 8, "bigpaie": 8, "bulletin": 6, "salaire": 5, "rubrique": 5,
        "irg": 8, "cotisation": 5, "rappel": 5, "recap": 4, "récap": 4,
        "emoluments": 4, "émoluments": 4, "net a payer": 6, "net à payer": 6,
        "cacobatph": 6, "das": 5, "livre de paie": 6, "virement bancaire": 4,
    },
    "rh": {
        "rh": 5, "grh": 7, "biggrh": 8, "employe": 5, "employé": 5, "conge": 6,
        "congé": 6, "carriere": 4, "carrière": 4, "contrat": 4, "recrutement": 5,
        "formation": 5, "personnel": 5, "sanction": 4, "mutation": 4, "dossier retraite": 5,
        "audience": 4, "dotation": 4,
    },
    "gestion_temps": {
        "gestion temps": 8, "gestion du temps": 8, "biggt": 8, "pointage": 7,
        "heures sup": 6, "heuresup": 6, "absence": 5, "titre de conge": 5,
        "titre de congé": 5, "interface big gt": 7, "exportation biggt": 7,
    },
    "administration": {
        "administration": 8, "utilisateur": 6, "permission": 5, "droits": 5,
        "groupe d utilisateurs": 5, "groupe d'utilisateurs": 5, "parametres application": 5,
        "paramètres application": 5, "circuit de validation": 5, "responsabilite": 4,
        "responsabilité": 4, "jours feries": 4, "jours fériés": 4,
    },
    "comptabilite": {
        "comptabilite": 8, "comptabilité": 8, "ecriture comptable": 7, "écriture comptable": 7,
        "ecriture": 4, "écriture": 4, "journal": 5, "grand livre": 7, "balance": 5,
        "bilan": 5, "compte comptable": 6, "piece comptable": 6, "pièce comptable": 6,
        "reouverture": 5, "réouverture": 5, "cloture": 5, "clôture": 5,
        "bigfinance": 2, "big finance": 2,
    },
    "sav": {
        "sav": 8, "service apres vente": 8, "service après vente": 8, "diagnostic": 5,
        "devis": 4, "demande reparation": 6, "demande réparation": 6, "garantie": 5,
        "atelier": 4, "rapport": 3, "ordre d intervention": 5, "ordre d'intervention": 5,
    },
    "crm": {
        "crm": 8, "reclamation": 5, "réclamation": 5, "prospect": 4, "opportunite": 4,
        "opportunité": 4, "campagne": 4,
    },
    "cimenterie": {"cimenterie": 8, "ciment": 5},
    "plateforme_java": {"plateforme java": 8, "java": 4},
    "gestion_marches": {"gestion marches": 8, "gestion des marches": 8, "marches": 5, "marchés": 5},
    "gestion_immobiliere": {"gestion immobiliere": 8, "gestion immobilière": 8, "immobiliere": 5, "immobilière": 5},
    "suivi_realisation": {"suivi realisation": 8, "suivi réalisation": 8, "realisation": 4, "réalisation": 4},
    "gestion_location": {"gestion location": 8, "location": 5},
    "gestion_documents": {"gestion documents": 8, "gestion des documents": 8, "document": 4},
    "tickets_support": {"ticket support": 8, "tickets support": 8, "helpdesk": 6},
    "dynamic_reports": {"dynamic big reports": 8, "dynamic reports": 8, "reporting": 5},
    "mobile": {"mobile": 6, "android": 4, "ios": 4},
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

ESCALADE_CONSULTANT_PHRASES = [
    "se referer a un consultant",
    "referer a un consultant",
    "contacter un consultant",
    "besoin d un consultant",
    "assistance consultant",
    "consultant specialise",
    "intervention consultant",
    "faire appel a un consultant",
    "se rapprocher d un consultant",
    "un consultant",
]

VERSION_CHECK_PHRASES = [
    "installer la derniere version",
    "installer la version",
    "mettre a jour",
    "mise a jour",
    "derniere version disponible",
    "telecharger la derniere version",
    "passer a la derniere version",
    "version plus recente",
    "version recente",
    "derniere mise a jour",
]

CLARIFICATION_SIGNAL_PHRASES = [
    "veuillez nous preciser",
    "veuillez me preciser",
    "merci de preciser",
    "merci de nous preciser",
    "merci de m envoyer",
    "merci de nous envoyer",
    "merci d envoyer",
    "merci de nous communiquer",
    "veuillez nous communiquer",
    "merci de nous donner",
    "merci de nous expliquer",
    "merci de nous appeler",
    "merci de verifier",
    "merci de nous fournir",
    "pouvez vous",
    "quel est",
    "quelle est",
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


def normalize_module_name(module: str) -> str:
    normalized = normalize_text(module).replace(" ", "_")
    if normalized in MODULE_ALIASES:
        return MODULE_ALIASES[normalized]
    spaced = normalize_text(module)
    return MODULE_ALIASES.get(spaced, normalized)


def lexical_overlap(text_a: str, text_b: str) -> float:
    tokens_a = {token for token in preprocess_normalize(text_a).split() if len(token) > 2}
    tokens_b = {token for token in preprocess_normalize(text_b).split() if len(token) > 2}
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def detect_module(text: str, fallback_module: str = "") -> str:
    fallback = normalize_module_name(fallback_module)
    if fallback and fallback != "non_classe":
        return fallback

    text_low = normalize_text(text)
    scores = {}
    for module, keywords in MODULE_KEYWORDS.items():
        score = sum(weight for kw, weight in keywords.items() if normalize_text(kw) in text_low)
        if score:
            scores[module] = score
    return max(scores, key=scores.get) if scores else "non_classe"


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
    solution = extract_raw_solution(full_text)
    normalized_solution = normalize_text(solution)
    if len(solution) > 20 and not any(
        phrase in normalized_solution
        for phrase in NON_ACTIONABLE_SOLUTION_PHRASES
    ):
        return solution[:500]
    return ""


def extract_raw_solution(full_text: str) -> str:
    match = re.search(r"Solution:\s*(.*?)$", full_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def is_clarification_response(response: str) -> bool:
    normalized = normalize_text(response)
    if not normalized:
        return False
    if "?" in response:
        return True
    return any(phrase in normalized for phrase in CLARIFICATION_SIGNAL_PHRASES)


def build_clarification_question(response: str) -> str:
    text = re.sub(r"\s+", " ", response or "").strip()
    if not text:
        return ""

    candidates = re.split(r"\s*\|\|\s*|[\r\n]+|(?<=[.!?])\s+", text)
    selected = ""
    for candidate in candidates:
        normalized = normalize_text(candidate)
        if "?" in candidate or any(phrase in normalized for phrase in CLARIFICATION_SIGNAL_PHRASES):
            selected = candidate.strip()
            break
    if not selected:
        selected = text

    selected = re.sub(r"^(bonjour|salut|cordialement)\s*[,;:-]*\s*", "", selected, flags=re.IGNORECASE).strip()
    selected = selected.strip(" .;:")
    normalized = normalize_text(selected)

    replacements = [
        (r"^merci\s+de\s+nous\s+", "Pouvez-vous nous "),
        (r"^merci\s+de\s+m[' ]?", "Pouvez-vous m'"),
        (r"^merci\s+d[' ]?", "Pouvez-vous "),
        (r"^merci\s+de\s+", "Pouvez-vous "),
        (r"^veuillez\s+nous\s+", "Pouvez-vous nous "),
        (r"^veuillez\s+me\s+", "Pouvez-vous me "),
        (r"^veuillez\s+", "Pouvez-vous "),
    ]
    question = selected
    for pattern, replacement in replacements:
        if re.search(pattern, question, flags=re.IGNORECASE):
            question = re.sub(pattern, replacement, question, count=1, flags=re.IGNORECASE)
            break

    if not question.lower().startswith(("pouvez-vous", "est-ce que", "quel", "quelle", "quels", "quelles")):
        question = f"Pouvez-vous preciser : {question}"

    if len(question) > 260:
        question = question[:257].rstrip() + "..."
    if not question.endswith("?"):
        question += " ?"
    return question


def is_escalade_consultant(solution: str) -> bool:
    normalized = normalize_text(solution)
    return any(phrase in normalized for phrase in ESCALADE_CONSULTANT_PHRASES)


def is_version_check_needed(solution: str) -> bool:
    normalized = normalize_text(solution)
    return any(phrase in normalized for phrase in VERSION_CHECK_PHRASES)


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


def extract_probleme(full_text: str) -> str:
    match = re.search(r"Probl(?:e|è|Ã¨|ÃƒÂ¨)me:\s*(.*?)(?:\nConversation:|\nSolution:|$)", full_text, re.DOTALL)
    return match.group(1).strip()[:300] if match else ""


def build_full_text_from_knowledge(row: dict) -> str:
    parts = []
    if row.get("objet"):
        parts.append(f"Objet: {row['objet']}")
    if row.get("problem_text"):
        parts.append(f"Probleme: {row['problem_text']}")
    if row.get("conversation_text"):
        parts.append(f"Conversation: {row['conversation_text']}")
    if row.get("final_solution"):
        parts.append(f"Solution: {row['final_solution']}")
    return "\n".join(parts)


def load_ticket_knowledge_rows() -> list[dict]:
    query = text(
        """
        SELECT ticket_id, objet, problem_text, conversation_text, final_solution,
               logiciel_id, version_id, module, full_text
        FROM ticket_knowledge
        WHERE ticket_id IS NOT NULL
        ORDER BY ticket_id
        """
    )
    with SessionLocal() as db:
        rows = db.execute(query).mappings().all()

    data = []
    for row in rows:
        item = dict(row)
        full_text = item.get("full_text") or build_full_text_from_knowledge(item)
        data.append(
            {
                "ticket_id": item.get("ticket_id"),
                "db_id": item.get("ticket_id"),
                "objet": item.get("objet") or "",
                "probleme": item.get("problem_text") or "",
                "solution": item.get("final_solution") or "",
                "module": item.get("module") or "",
                "software": item.get("logiciel_id") or "",
                "version": item.get("version_id") or "",
                "full_text": full_text,
            }
        )
    return data


def load_ticket_metadata_rows() -> list[dict]:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "ticket_metadata.json")
    if not os.path.exists(path):
        path = os.path.abspath(os.path.join(base_dir, "..", "ticket_metadata.json"))
    if not os.path.exists(path):
        print(f"ticket_metadata.json introuvable (cherche dans {base_dir})")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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

        try:
            db_data = load_ticket_knowledge_rows()
            if db_data:
                data = db_data
                print(f"Source RAG: PostgreSQL ticket_knowledge ({len(data)} entrees brutes)")
            else:
                print("ticket_knowledge vide, source RAG fallback: ticket_metadata.json")
        except Exception as exc:
            print(f"Lecture ticket_knowledge impossible ({exc}), source RAG fallback: ticket_metadata.json")

        skipped = 0
        skipped_non_actionable = 0
        loaded_solutions = 0
        loaded_clarifications = 0
        loaded_escalades = 0
        loaded_version_checks = 0
        for ticket in data:
            full_text = ticket.get("full_text", "")
            probleme = extract_probleme(full_text)
            solution = extract_raw_solution(full_text) or (ticket.get("solution", "") or "").strip()
            objet = ticket.get("objet", "").strip()
            if not solution:
                skipped += 1
                continue

            response_type = "solution"
            clarification_question = ""
            if not is_actionable_solution(solution):
                if is_escalade_consultant(solution):
                    response_type = "escalade_consultant"
                    loaded_escalades += 1
                elif is_version_check_needed(solution):
                    response_type = "version_check"
                    loaded_version_checks += 1
                elif is_clarification_response(solution):
                    clarification_question = build_clarification_question(solution)
                    if clarification_question:
                        response_type = "clarification"
                        loaded_clarifications += 1
                    else:
                        skipped_non_actionable += 1
                        continue
                else:
                    skipped_non_actionable += 1
                    continue
            else:
                loaded_solutions += 1

            prepared = prepare_ticket_text(probleme or full_text)
            condensed_problem = prepared["enriched"] or probleme or full_text
            source_text = f"{objet} {condensed_problem} {ticket.get('solution', '')}"
            module = detect_module(source_text, ticket.get("module", ""))
            incident_type = detect_type(source_text)
            software = detect_software(source_text) or normalize_text(str(ticket.get("software", "")))
            version = detect_version(source_text) or str(ticket.get("version", "") or "")

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
                    "response_type": response_type,
                    "clarification_question": clarification_question,
                    "full_text": full_text[:400],
                }
            )

        print(
            f"{len(self.tickets)} tickets charges "
            f"({loaded_solutions} solutions, {loaded_clarifications} clarifications, "
            f"{loaded_escalades} escalades consultant, {loaded_version_checks} verif. version, "
            f"{skipped} sans solution ignores, {skipped_non_actionable} non actionnables ignorees)"
        )

    def _build_index(self):
        if not self.tickets:
            print("Aucun ticket a indexer")
            return

        texts = [
            f"{ticket['objet']} {ticket['module']} {ticket['type']} {ticket['software']} {ticket['version']} {ticket['description']}"
            for ticket in self.tickets
        ]
        self.embeddings = get_embedder().encode(texts, show_progress_bar=False, batch_size=16)
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
        usages = Counter(ticket.get("response_type", "solution") for ticket in self.tickets)
        return {
            "total": len(self.tickets),
            "par_usage": dict(usages.most_common()),
            "par_module": dict(modules.most_common()),
            "par_type": dict(types.most_common()),
        }


rag = RAGEngine()
