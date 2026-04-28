# -*- coding: utf-8 -*-
"""
Affiche des exemples de tickets exploitables et non-exploitables.
Lance : python afficher_tickets.py
"""
import json, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(Path(__file__).parent)

from rag_engine import extract_solution, extract_probleme, is_actionable_solution, normalize_text

path = Path(__file__).parent / "ticket_metadata.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

exploitables = []
non_exploitables = []
raisons = []

for t in data:
    full_text = t.get("full_text", "")
    objet = t.get("objet", "Sans titre")[:70]
    solution = extract_solution(full_text)
    probleme = extract_probleme(full_text)[:120] if extract_probleme(full_text) else full_text[:120]

    if not solution:
        non_exploitables.append({
            "id": t.get("ticket_id", "?"),
            "objet": objet,
            "probleme": probleme,
            "raison": "Aucune solution trouvee dans le texte",
            "solution_brute": ""
        })
    elif not is_actionable_solution(solution):
        non_exploitables.append({
            "id": t.get("ticket_id", "?"),
            "objet": objet,
            "probleme": probleme,
            "raison": "Solution non actionnable (trop vague ou juste 'merci')",
            "solution_brute": solution[:100]
        })
    else:
        exploitables.append({
            "id": t.get("ticket_id", "?"),
            "objet": objet,
            "probleme": probleme,
            "solution": solution[:150]
        })

print("=" * 70)
print(f"  TOTAL : {len(data)} tickets  |  {len(exploitables)} exploitables  |  {len(non_exploitables)} non-exploitables")
print("=" * 70)

print("\n")
print("=" * 70)
print("  20 TICKETS NON-EXPLOITABLES (ignores par le RAG)")
print("=" * 70)
for t in non_exploitables[:20]:
    print(f"\n  [#{t['id']}] {t['objet']}")
    print(f"  Probleme : {t['probleme']}")
    print(f"  Raison   : {t['raison']}")
    if t['solution_brute']:
        print(f"  Solution : {t['solution_brute']}")
    print("  " + "-" * 66)

print("\n")
print("=" * 70)
print("  20 TICKETS EXPLOITABLES (utilises par le RAG pour proposer des solutions)")
print("=" * 70)
for t in exploitables[:20]:
    print(f"\n  [#{t['id']}] {t['objet']}")
    print(f"  Probleme : {t['probleme']}")
    print(f"  Solution : {t['solution']}")
    print("  " + "-" * 66)

print()