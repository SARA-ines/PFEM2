# -*- coding: utf-8 -*-
"""
Evaluation realiste du systeme PFEM2.
Lance depuis le dossier backend :  python evaluate_realistic.py
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(Path(__file__).parent)

from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name(".env"))

from main import run_assistant, has_real_anthropic_key

# ─── Cas de test ─────────────────────────────────────────────────────────────
TEST_CASES = [
    {
        "id": 1,
        "label": "Erreur calcul paie IRG",
        "question": "Le calcul de l'IRG est incorrect dans BigPaie v3.2, le montant retenu est faux",
        "ticket_context": {"module": "paie", "software": "BigPaie", "version": "3.2", "priority": "haute"},
        "expect_module": "paie",
        "expect_type": "calcul",
        "expect_min_confidence": 0.55,
        "expect_solution": True,
    },
    {
        "id": 2,
        "label": "Lenteur module stock",
        "question": "BigGestion est tres lent lors de la saisie des bons de sortie stock, l'interface se fige",
        "ticket_context": {"module": "stock", "software": "BigGestion", "version": "2.1", "priority": "moyenne"},
        "expect_module": "stock",
        "expect_type": "performance",
        "expect_min_confidence": 0.50,
        "expect_solution": True,
    },
    {
        "id": 3,
        "label": "Impression etat comptabilite",
        "question": "Impossible d'imprimer le bilan comptable dans BigFinance, la fenetre d'impression ne s'ouvre pas",
        "ticket_context": {"module": "comptabilite", "software": "BigFinance", "version": "4.0", "priority": "normale"},
        "expect_module": "comptabilite",
        "expect_type": "interface",
        "expect_min_confidence": 0.50,
        "expect_solution": True,
    },
    {
        "id": 4,
        "label": "Erreur acces RH",
        "question": "Un utilisateur n'arrive plus a acceder au module RH de BigGRH apres mise a jour",
        "ticket_context": {"module": "rh", "software": "BigGRH", "version": "2.5", "priority": "haute"},
        "expect_module": "rh",
        "expect_type": "permission",
        "expect_min_confidence": 0.50,
        "expect_solution": True,
    },
    {
        "id": 5,
        "label": "Probleme vague sans contexte",
        "question": "ca marche pas",
        "ticket_context": {},
        "expect_module": "",
        "expect_type": "",
        "expect_min_confidence": 0.25,
        "expect_solution": False,
        "expect_qualification": True,
    },
    {
        "id": 6,
        "label": "Facture client erronee",
        "question": "La facture generee dans BigGestion ne contient pas les bonnes quantites, erreur de calcul total TTC",
        "ticket_context": {"module": "facturation", "software": "BigGestion", "version": "2.1", "priority": "critique"},
        "expect_module": "facturation",
        "expect_type": "calcul",
        "expect_min_confidence": 0.50,
        "expect_solution": True,
    },
    {
        "id": 7,
        "label": "Installation nouvelle version",
        "question": "Apres installation de BigPaie v4.0, le logiciel ne demarre plus, erreur au lancement",
        "ticket_context": {"module": "paie", "software": "BigPaie", "version": "4.0", "priority": "critique"},
        "expect_module": "paie",
        "expect_type": "configuration",
        "expect_min_confidence": 0.50,
        "expect_solution": True,
    },
    {
        "id": 8,
        "label": "Conge calcule incorrectement",
        "question": "Le solde de conge annuel dans BigGRH est faux, 15 jours affiches au lieu de 22",
        "ticket_context": {"module": "rh", "software": "BigGRH", "version": "2.5", "priority": "moyenne"},
        "expect_module": "rh",
        "expect_type": "calcul",
        "expect_min_confidence": 0.50,
        "expect_solution": True,
    },
]

# ─── Evaluation ───────────────────────────────────────────────────────────────

def evaluate():
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    llm_active = has_real_anthropic_key(anthropic_key)
    mode_label = "Claude (Anthropic)" if llm_active else "RAG uniquement (pas de cle Anthropic)"

    print("=" * 62)
    print("  EVALUATION PFEM2 - Systeme de support ERP")
    print(f"  Mode LLM : {mode_label}")
    print("=" * 62)

    total_score = 0
    max_score = 0
    results = []

    for tc in TEST_CASES:
        try:
            result = run_assistant(
                tc["question"],
                use_llm=llm_active,
                ticket_context=tc["ticket_context"] or None,
            )
        except Exception as exc:
            results.append({"id": tc["id"], "label": tc["label"], "error": str(exc), "score": 0, "max": 10})
            max_score += 10
            continue

        state = result.get("state", {})
        answer = result.get("answer", "")
        confidence = float(state.get("confidence_score", 0))
        module = (state.get("module") or "").strip().lower()
        type_inc = (state.get("type_incident") or "").strip().lower()
        statut = (state.get("statut") or "").strip()
        solution = (state.get("solution_proposee") or "").strip()

        score = 0
        details = []

        # 1. Module correct (+2)
        if tc["expect_module"]:
            if module == tc["expect_module"]:
                score += 2
                details.append("module OK")
            else:
                details.append(f"module KO (attendu={tc['expect_module']}, obtenu={module or 'vide'})")
        else:
            score += 2
            details.append("module n/a")

        # 2. Type incident correct (+2)
        if tc["expect_type"]:
            if type_inc == tc["expect_type"]:
                score += 2
                details.append("type OK")
            else:
                details.append(f"type KO (attendu={tc['expect_type']}, obtenu={type_inc or 'vide'})")
        else:
            score += 2
            details.append("type n/a")

        # 3. Confiance suffisante (+2)
        if confidence >= tc["expect_min_confidence"]:
            score += 2
            details.append(f"confiance OK ({confidence:.0%})")
        else:
            details.append(f"confiance KO ({confidence:.0%} < {tc['expect_min_confidence']:.0%})")

        # 4. Solution presente si attendue (+2)
        if tc.get("expect_solution"):
            if solution and len(solution) > 20:
                score += 2
                details.append("solution presente")
            else:
                details.append("solution absente ou trop courte")
        elif tc.get("expect_qualification"):
            if statut == "qualification" or (not solution):
                score += 2
                details.append("qualification correcte")
            else:
                details.append("devrait qualifier, pas resoudre")

        # 5. Reponse non vide et coherente (+2)
        if answer and len(answer) > 30:
            score += 2
            details.append("reponse coherente")
        else:
            details.append("reponse trop courte")

        case_max = 10
        total_score += score
        max_score += case_max
        results.append({
            "id": tc["id"],
            "label": tc["label"],
            "score": score,
            "max": case_max,
            "confidence": confidence,
            "module": module,
            "type": type_inc,
            "statut": statut,
            "details": details,
        })

    # ─── Affichage des resultats ──────────────────────────────────────────────
    print()
    for r in results:
        if "error" in r:
            print(f"  [CAS {r['id']:02d}] {r['label'][:40]:<40}  ERREUR: {r['error'][:60]}")
            continue
        bar = "#" * r["score"] + "-" * (r["max"] - r["score"])
        pct = r["score"] / r["max"] * 100
        print(f"  [CAS {r['id']:02d}] {r['label'][:40]:<40}  {r['score']}/{r['max']}  [{bar}] {pct:.0f}%")
        for d in r.get("details", []):
            print(f"           - {d}")

    print()
    print("=" * 62)
    global_pct = round(total_score / max_score * 100) if max_score else 0
    print(f"  SCORE GLOBAL : {total_score}/{max_score}  =>  {global_pct}/100")

    if global_pct >= 80:
        grade = "Excellent"
    elif global_pct >= 65:
        grade = "Bien"
    elif global_pct >= 50:
        grade = "Moyen"
    else:
        grade = "A ameliorer"

    print(f"  Appreciation : {grade}")
    print("=" * 62)
    print()

    if not llm_active:
        print("  Conseil : Ajoutez une cle Anthropic dans .env pour activer")
        print("  Claude et gagner +15 a +25 points sur ce score.")
        print()

    return global_pct


if __name__ == "__main__":
    evaluate()