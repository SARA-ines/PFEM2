"""
Test full-stack du chatbot ERP.
Usage :
    python run_tests.py                   # tous les tests
    python run_tests.py --cat paie        # seulement la categorie paie
    python run_tests.py --id P01          # un seul test
    python run_tests.py --rag-only        # RAG uniquement, sans LLM
    python run_tests.py --verbose         # affiche les reponses completes
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from main import run_assistant
from rag_engine import rag
from nlp_engine import analyze

# ── couleurs terminal (Windows compatible) ──────────────────────────────────
try:
    import colorama
    colorama.init()
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"
except ImportError:
    GREEN = RED = YELLOW = CYAN = BOLD = RESET = ""

PASS  = f"{GREEN}PASS{RESET}"
FAIL  = f"{RED}FAIL{RESET}"
WARN  = f"{YELLOW}WARN{RESET}"
SEP   = "-" * 90


def load_cases(path: str = "test_cases.json") -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_one(case: dict, verbose: bool = False) -> dict:
    session_id = str(uuid.uuid4())
    tc = case.get("ticket_context") or {}
    question = case["query"]

    t0 = time.time()
    try:
        result = run_assistant(
            question=question,
            session_id=session_id,
            use_llm=False,
            ticket_context=tc if tc else None,
        )
        elapsed = round(time.time() - t0, 2)
        state = result.get("state", {})
        answer = result.get("answer", "")

        actual_module      = state.get("module", "")
        actual_statut      = state.get("statut", "")
        actual_escalade    = bool(state.get("escalade_necessaire", False))
        actual_confidence  = float(state.get("confidence_score", 0))
        actual_resp_types  = [
            t.get("response_type", "")
            for t in state.get("tickets_similaires", [])
        ]
        best_sim = (
            state.get("metrics", {}).get("rag_similarity", 0)
            or (state.get("tickets_similaires") or [{}])[0].get("similarity", 0)
        )
        n_similar = state.get("metrics", {}).get("n_similar", 0)

        return {
            "ok": True,
            "elapsed": elapsed,
            "actual_module": actual_module,
            "actual_statut": actual_statut,
            "actual_escalade": actual_escalade,
            "actual_confidence": actual_confidence,
            "actual_resp_types": actual_resp_types,
            "best_similarity": best_sim,
            "n_similar": n_similar,
            "answer": answer[:200] if not verbose else answer,
            "full_state": state,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "elapsed": round(time.time() - t0, 2)}


def evaluate(case: dict, run_result: dict) -> dict:
    """Calcule pass/fail + score partiel."""
    checks = {}

    if not run_result["ok"]:
        return {"passed": False, "score": 0, "checks": {"erreur": run_result.get("error")}}

    expected_module = case.get("expected_module", "")
    expected_types  = set(case.get("expected_response_types", []))
    expected_esc    = case.get("expected_escalade", None)
    expected_v_chk  = case.get("expected_version_check", False)
    expected_v_ask  = case.get("expected_version_ask", False)
    no_similar      = case.get("expected_no_similar_tickets", False)

    actual_module    = run_result["actual_module"]
    actual_statut    = run_result["actual_statut"]
    actual_escalade  = run_result["actual_escalade"]
    actual_conf      = run_result["actual_confidence"]
    actual_types     = set(run_result["actual_resp_types"])
    actual_labels    = set(actual_types)
    if actual_statut == "solution_proposee":
        actual_labels.add("solution")
    if actual_statut:
        actual_labels.add(actual_statut)
    best_sim         = float(run_result["best_similarity"])
    n_sim            = run_result["n_similar"]

    total_checks = 0
    passed_checks = 0

    # 1 - Module correct
    if expected_module:
        total_checks += 1
        ok = actual_module == expected_module
        checks["module"] = ("OK" if ok else "FAIL",
                            f"attendu={expected_module}, obtenu={actual_module}")
        if ok:
            passed_checks += 1

    # 2 - Type de reponse acceptable
    if expected_types:
        total_checks += 1
        overlap = expected_types & actual_labels
        ok = bool(overlap)
        checks["response_type"] = ("OK" if ok else "FAIL",
                                   f"attendu un de {expected_types}, statut={actual_statut}, types_rag={actual_types}")
        if ok:
            passed_checks += 1

    # 3 - Escalade si attendue
    if expected_esc is not None:
        total_checks += 1
        ok = actual_escalade == expected_esc
        checks["escalade"] = ("OK" if ok else "FAIL",
                              f"attendu={expected_esc}, obtenu={actual_escalade}")
        if ok:
            passed_checks += 1

    # 4 - Version check declenche si attendu
    if expected_v_chk or expected_v_ask:
        total_checks += 1
        ok = (actual_statut in ("version_check", "qualification") or
              "version_check" in actual_types)
        checks["version_check"] = ("OK" if ok else "FAIL",
                                   f"statut={actual_statut}")
        if ok:
            passed_checks += 1

    # 5 - Pas de ticket similaire pour hors-domaine
    if no_similar:
        total_checks += 1
        ok = n_sim == 0
        checks["hors_domaine"] = ("OK" if ok else "FAIL",
                                  f"n_similar={n_sim} (attendu 0)")
        if ok:
            passed_checks += 1

    # 6 - Confiance minimale (pas pour hors-domaine/vague)
    if case["categorie"] not in ("hors_domaine", "vague", "salutation"):
        total_checks += 1
        ok = actual_conf >= 0.40
        checks["confidence"] = ("OK" if ok else "WARN",
                                f"confiance={actual_conf:.2f} (seuil 0.40)")
        if ok:
            passed_checks += 1

    # 7 - Similarite minimale (pas pour hors-domaine/vague)
    if case["categorie"] not in ("hors_domaine", "vague", "salutation"):
        total_checks += 1
        ok = best_sim >= 0.18
        checks["similarity"] = ("OK" if ok else "WARN",
                                f"best_sim={best_sim:.3f} (seuil 0.18)")
        if ok:
            passed_checks += 1

    score = round(passed_checks / total_checks, 2) if total_checks else 1.0
    hard_fail_checks = {"module", "response_type", "escalade", "version_check", "hors_domaine"}
    has_hard_fail = any(
        name in hard_fail_checks and result[0] == "FAIL"
        for name, result in checks.items()
    )
    passed = score >= 0.70 and not has_hard_fail

    return {"passed": passed, "score": score, "checks": checks,
            "passed_checks": passed_checks, "total_checks": total_checks}


def print_result(case: dict, run_res: dict, eval_res: dict, verbose: bool):
    status = PASS if eval_res["passed"] else FAIL
    score_pct = int(eval_res["score"] * 100)
    conf = run_res.get("actual_confidence", 0)
    sim  = run_res.get("best_similarity", 0)
    t    = run_res.get("elapsed", 0)

    print(f"  [{case['id']:<6}] {status}  {score_pct:>3}%  "
          f"conf={conf:.2f}  sim={sim:.3f}  t={t}s  "
          f"| {case['description']}")

    for check_name, (ok_str, detail) in eval_res["checks"].items():
        color = GREEN if ok_str == "OK" else (YELLOW if ok_str == "WARN" else RED)
        print(f"           {color}{ok_str:4}{RESET}  {check_name:<18} {detail}")

    if verbose and run_res.get("answer"):
        print(f"           {CYAN}Reponse:{RESET} {run_res['answer'][:300]}")
    print()


def print_summary(results: list[dict]):
    total   = len(results)
    passed  = sum(1 for r in results if r["eval"]["passed"])
    failed  = total - passed
    avg_sim = sum(r["run"].get("best_similarity", 0) for r in results) / max(total, 1)
    avg_con = sum(r["run"].get("actual_confidence", 0) for r in results) / max(total, 1)
    avg_t   = sum(r["run"].get("elapsed", 0) for r in results) / max(total, 1)

    pct = int(passed / total * 100) if total else 0
    bar_len = 40
    filled = int(bar_len * passed / total) if total else 0
    bar = GREEN + "#" * filled + RESET + "-" * (bar_len - filled)

    print(SEP)
    print(f"\n  {BOLD}RESULTATS FINAUX{RESET}")
    print(f"  [{bar}]  {passed}/{total} ({pct}%)")
    print()
    print(f"  Passes  : {GREEN}{passed}{RESET}")
    print(f"  Echoues : {RED}{failed}{RESET}")
    print(f"  Sim moy : {avg_sim:.3f}   Confiance moy : {avg_con:.2f}   Temps moy : {avg_t:.2f}s")
    print()

    if pct >= 90:
        print(f"  {GREEN}{BOLD}Objectif 90%+ ATTEINT !{RESET}")
    elif pct >= 75:
        print(f"  {YELLOW}Bon niveau ({pct}%) - encore quelques ajustements.{RESET}")
    else:
        print(f"  {RED}Score insuffisant ({pct}%) - voir les FAIL ci-dessus.{RESET}")
    print()

    # Tableau par categorie
    cats = {}
    for r in results:
        cat = r["case"]["categorie"]
        cats.setdefault(cat, {"pass": 0, "total": 0})
        cats[cat]["total"] += 1
        if r["eval"]["passed"]:
            cats[cat]["pass"] += 1

    print(f"  {'Categorie':<22} {'Pass/Total':>10}  {'Score':>6}")
    print(f"  {'-'*40}")
    for cat, v in sorted(cats.items()):
        p = int(v["pass"] / v["total"] * 100)
        color = GREEN if p >= 80 else (YELLOW if p >= 60 else RED)
        print(f"  {cat:<22} {v['pass']}/{v['total']:>5}       {color}{p}%{RESET}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Test full-stack chatbot ERP")
    parser.add_argument("--cat",     help="Filtrer par categorie (ex: paie, stock)")
    parser.add_argument("--id",      help="Lancer un seul test (ex: P01)")
    parser.add_argument("--verbose", action="store_true", help="Afficher les reponses")
    parser.add_argument("--cases",   default="test_cases.json", help="Fichier de tests")
    args = parser.parse_args()

    cases = load_cases(args.cases)

    if args.id:
        cases = [c for c in cases if c["id"] == args.id]
    elif args.cat:
        cases = [c for c in cases if c["categorie"] == args.cat]

    if not cases:
        print("Aucun test trouve.")
        sys.exit(1)

    print(f"\n{BOLD}{'='*90}{RESET}")
    print(f"  CHATBOT ERP — TEST FULL STACK  ({len(cases)} tests)")
    print(f"{'='*90}{RESET}\n")

    all_results = []
    categories_done = set()

    for case in cases:
        cat = case["categorie"]
        if cat not in categories_done:
            print(f"\n{BOLD}{CYAN}  [ {cat.upper()} ]{RESET}")
            categories_done.add(cat)

        run_res  = run_one(case, verbose=args.verbose)
        eval_res = evaluate(case, run_res)
        print_result(case, run_res, eval_res, verbose=args.verbose)
        all_results.append({"case": case, "run": run_res, "eval": eval_res})

    print_summary(all_results)

    # Export JSON des resultats
    out_path = Path(__file__).parent / "test_results_last.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([
            {
                "id": r["case"]["id"],
                "categorie": r["case"]["categorie"],
                "passed": r["eval"]["passed"],
                "score": r["eval"]["score"],
                "confidence": r["run"].get("actual_confidence"),
                "similarity": r["run"].get("best_similarity"),
                "module": r["run"].get("actual_module"),
                "statut": r["run"].get("actual_statut"),
                "elapsed": r["run"].get("elapsed"),
            }
            for r in all_results
        ], f, ensure_ascii=False, indent=2)
    print(f"  Resultats exportes : {out_path}\n")

    failed = sum(1 for r in all_results if not r["eval"]["passed"])
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
