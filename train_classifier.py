import json
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from preprocessing import extract_problem_core, normalize_text


ROOT_DIR = Path(__file__).resolve().parent
TRAIN_PATH = ROOT_DIR / "ticket_train.json"
MODEL_DIR = ROOT_DIR / "backend" / "models"


MODULE_KEYWORDS = {
    "stock": ["stock", "mouvement", "inventaire", "article", "cump", "winstock", "biggestion"],
    "paie": ["paie", "bigpaie", "bulletin", "salaire", "irg", "rubrique", "rappel"],
    "rh": ["rh", "biggrh", "wingrh", "pointage", "contrat", "conge", "employe", "biggt"],
    "comptabilite": ["comptabilite", "bigfinance", "journal", "bilan", "balance", "ecriture", "compte"],
    "facturation": ["facture", "facturation", "fournisseur", "bon de livraison", "ttc", "comptabilisation"],
}

TYPE_KEYWORDS = {
    "base_de_donnees": ["sql", "odbc", "table", "colonne", "base", "discordance", "non transfere"],
    "interface": ["impression", "affichage", "ecran", "rapport", "etat", "liste deroulante", "excel"],
    "performance": ["lenteur", "blocage", "bloque", "saturation", "freeze"],
    "permission": ["licence", "acces", "droits", "activation"],
    "configuration": ["installation", "version", "parametre", "mise a jour", "reinstallation", "reouverture"],
    "calcul": ["calcul", "montant", "cump", "prix unitaire", "net a payer", "ttc", "quantite"],
}


def extract_problem(full_text: str) -> str:
    marker = "Proble"
    if marker not in full_text:
        return extract_problem_core(full_text)
    start = full_text.find(marker)
    segment = full_text[start:]
    conversation_index = segment.find("Conversation:")
    if conversation_index != -1:
        segment = segment[:conversation_index]
    return extract_problem_core(segment)


def detect_label(text: str, mapping: dict[str, list[str]], default: str) -> str:
    normalized = normalize_text(text)
    best_label = default
    best_score = 0
    for label, keywords in mapping.items():
        score = sum(1 for keyword in keywords if keyword in normalized)
        if score > best_score:
            best_label = label
            best_score = score
    return best_label


def build_dataset():
    tickets = json.loads(TRAIN_PATH.read_text(encoding="utf-8"))
    rows = []
    for ticket in tickets:
        full_text = ticket.get("full_text", "")
        objet = ticket.get("objet", "")
        problem = extract_problem(full_text)
        source = f"{objet}. {problem}".strip()
        if len(source) < 12:
            continue
        rows.append(
            {
                "text": source,
                "module": detect_label(source, MODULE_KEYWORDS, "stock"),
                "type": detect_label(source, TYPE_KEYWORDS, "autre"),
            }
        )
    return rows


def build_pipeline():
    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1)),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]
    )


def main():
    rows = build_dataset()
    if not rows:
        raise SystemExit("Aucune donnee exploitable dans ticket_train.json")

    texts = [row["text"] for row in rows]
    modules = [row["module"] for row in rows]
    types = [row["type"] for row in rows]

    module_model = build_pipeline()
    type_model = build_pipeline()

    module_model.fit(texts, modules)
    type_model.fit(texts, types)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(module_model, MODEL_DIR / "module_classifier.joblib")
    joblib.dump(type_model, MODEL_DIR / "type_classifier.joblib")
    (MODEL_DIR / "classifier_meta.json").write_text(
        json.dumps({"train_samples": len(rows), "labels_module": sorted(set(modules)), "labels_type": sorted(set(types))}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Classifieurs enregistres dans {MODEL_DIR}")


if __name__ == "__main__":
    main()
