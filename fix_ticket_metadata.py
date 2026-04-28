"""
Répare ticket_metadata.json :
- extrait la solution réelle depuis full_text
- détecte module, type et logiciel automatiquement
- reconstruit l'index FAISS
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ── 1. Charger les tickets ──────────────────────────────────────────────────
with open(ROOT / "ticket_metadata.json", encoding="utf-8") as f:
    tickets = json.load(f)

print(f"Tickets chargés : {len(tickets)}")

# ── 2. Règles de détection ──────────────────────────────────────────────────
MODULE_KEYWORDS = {
    "stock":        ["stock", "inventaire", "mouvement", "article", "sortie", "entree", "magasin", "réforme", "cession", "ajustement"],
    "paie":         ["paie", "salaire", "irg", "cotisation", "bulletin", "congé", "rémunération", "cnss", "cnas"],
    "rh":           ["rh", "grh", "recrutement", "personnel", "collaborateur", "formation", "contrat", "congé"],
    "comptabilite": ["compta", "bilan", "journal", "écriture", "balance", "fiscal", "tva", "grand livre", "finance", "bigfinance"],
    "facturation":  ["facture", "facturation", "devis", "commande", "vente", "client", "fournisseur", "avoir"],
    "achat":        ["achat", "appel d'offre", "bon de commande", "reception"],
}

TYPE_KEYWORDS = {
    "calcul":         ["calcul", "montant", "irg", "total", "ecart", "résultat", "incorrect", "erroné", "mauvais montant"],
    "interface":      ["affichage", "afficher", "rapport", "état", "impression", "liste", "colonne", "taille", "fenêtre"],
    "performance":    ["lenteur", "lent", "bloqué", "bloque", "freeze", "temps", "délai", "régénération"],
    "base_de_donnees":["sql", "base", "bdd", "cast", "requête", "erreur sql", "connexion base"],
    "configuration":  ["paramètre", "configuration", "installation", "mise à jour", "version", "activation", "licence"],
    "permission":     ["accès", "droits", "permission", "utilisateur", "profil", "autorisation"],
    "autre":          [],
}

SOFTWARE_KEYWORDS = {
    "BigGestion":    ["biggestion", "big gestion", "bigsoftweb", "bigsoft"],
    "BigPaie":       ["bigpaie", "big paie"],
    "BigGRH":        ["biggrh", "big grh", "grh"],
    "BigFinance":    ["bigfinance", "big finance"],
    "BigStock":      ["bigstock", "big stock"],
    "BigFacturation":["bigfacturation", "big facturation"],
}


def detect_module(text: str) -> str:
    text_low = text.lower()
    scores = {}
    for module, keywords in MODULE_KEYWORDS.items():
        scores[module] = sum(1 for kw in keywords if kw in text_low)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def detect_type(text: str) -> str:
    text_low = text.lower()
    for type_name, keywords in TYPE_KEYWORDS.items():
        if any(kw in text_low for kw in keywords):
            return type_name
    return "autre"


def detect_software(text: str) -> str:
    text_low = text.lower()
    for software, keywords in SOFTWARE_KEYWORDS.items():
        if any(kw in text_low for kw in keywords):
            return software
    return ""


def extract_solution(full_text: str) -> str:
    """Extrait la partie solution du full_text."""
    if not full_text:
        return ""

    # Chercher "Solution:" explicite
    match = re.search(r"Solution\s*:\s*(.+)", full_text, re.IGNORECASE | re.DOTALL)
    if match:
        sol = match.group(1).strip()
        # Nettoyer les doublons de conversation (souvent la solution = dernier msg conversation)
        # Garder max 400 caractères
        sol = sol[:400].strip()
        if len(sol) > 15:
            return sol

    # Sinon extraire la dernière ligne de la conversation
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]
    # Chercher la ligne après "Conversation:"
    for i, line in enumerate(lines):
        if line.lower().startswith("conversation"):
            remaining = lines[i+1:]
            if remaining:
                # Prendre le dernier message de la conversation
                last = remaining[-1][:400]
                if len(last) > 15:
                    return last

    # Extraire le problème comme fallback
    match = re.search(r"Probl[eè]me\s*:\s*(.+?)(?:Conversation|Solution|$)", full_text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()[:400]

    return ""


def extract_problem(full_text: str) -> str:
    """Extrait le problème du full_text."""
    match = re.search(r"Probl[eè]me\s*:\s*(.+?)(?:Conversation|Solution|$)", full_text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()[:300]
    return ""


# ── 3. Réparer chaque ticket ────────────────────────────────────────────────
fixed = 0
for ticket in tickets:
    full_text = ticket.get("full_text", "")
    objet = ticket.get("objet", "")
    combined = f"{objet} {full_text}"

    # Extraire la solution
    solution = extract_solution(full_text)
    ticket["solution"] = solution

    # Extraire le problème si absent
    if not ticket.get("probleme"):
        ticket["probleme"] = extract_problem(full_text)

    # Détecter module si absent ou "undefined"
    if not ticket.get("module") or ticket["module"] in (None, "undefined", ""):
        ticket["module"] = detect_module(combined)

    # Détecter type si absent
    if not ticket.get("type") or ticket["type"] in (None, "undefined", ""):
        ticket["type"] = detect_type(combined)

    # Détecter logiciel si absent
    if not ticket.get("software") or ticket["software"] in (None, "undefined", "N/A", ""):
        ticket["software"] = detect_software(combined)

    if solution:
        fixed += 1

print(f"Tickets avec solution extraite : {fixed}/{len(tickets)}")

# Statistiques modules
from collections import Counter
modules = Counter(t["module"] for t in tickets)
types   = Counter(t["type"]   for t in tickets)
print("\nRépartition modules :", dict(modules))
print("Répartition types   :", dict(types))

# ── 4. Sauvegarder ──────────────────────────────────────────────────────────
out_path = ROOT / "ticket_metadata.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(tickets, f, ensure_ascii=False, indent=2)

print(f"\n✅ ticket_metadata.json sauvegardé ({len(tickets)} tickets)")

# ── 5. Reconstruire l'index FAISS ──────────────────────────────────────────
print("\nReconstruction de l'index FAISS...")
sys.path.insert(0, str(ROOT / "backend"))

try:
    from embedding_config import get_embedding_model
    import numpy as np
    import faiss

    model = get_embedding_model()
    print("Modèle d'embedding chargé.")

    texts = []
    for t in tickets:
        # Combiner objet + problème + solution pour un meilleur embedding
        parts = [t.get("objet", ""), t.get("probleme", ""), t.get("solution", "")]
        texts.append(" ".join(p for p in parts if p).strip() or t.get("full_text", "")[:200])

    print(f"Génération des embeddings pour {len(texts)} tickets...")
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=32)
    embeddings = np.array(embeddings, dtype="float32")

    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)

    faiss.write_index(index, str(ROOT / "ticket_index.faiss"))
    print(f"✅ Index FAISS reconstruit : {index.ntotal} vecteurs de dimension {dim}")

except Exception as e:
    print(f"⚠️  Erreur reconstruction FAISS : {e}")
    print("Lance manuellement : cd backend && python -c \"from rag_engine import rag; print(rag.stats())\"")