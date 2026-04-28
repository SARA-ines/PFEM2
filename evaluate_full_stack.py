import atexit
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import warnings
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
VENV_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
API = os.getenv("EVAL_API_URL", "http://127.0.0.1:8000")
EVAL_PASSWORD = "EvalPass#2026"
EVAL_EMAIL = "eval.client@pfem2.local"
MAX_TICKETS = int(os.getenv("EVAL_MAX_TICKETS", "0"))
REQUEST_TIMEOUT = int(os.getenv("EVAL_TIMEOUT_SEC", "90"))

if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
warnings.filterwarnings(
    "ignore",
    message="`resume_download` is deprecated",
    category=FutureWarning,
)


_started_server = None
load_classifier_bundle = None
analyze = None
detect_module = None
detect_type = None
rag = None


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", normalize(text))
    return [token for token in cleaned.split() if len(token) > 2]


def solution_similarity(expected: str, predicted: str) -> float:
    expected_norm = normalize(expected)
    predicted_norm = normalize(predicted)
    if not expected_norm or not predicted_norm:
        return 0.0

    expected_tokens = set(tokenize(expected_norm))
    predicted_tokens = set(tokenize(predicted_norm))
    if expected_tokens and predicted_tokens:
        token_score = len(expected_tokens & predicted_tokens) / len(expected_tokens | predicted_tokens)
    else:
        token_score = 0.0

    sequence_score = SequenceMatcher(None, expected_norm, predicted_norm).ratio()
    containment_score = 1.0 if expected_norm in predicted_norm or predicted_norm in expected_norm else 0.0
    return round(max(token_score, sequence_score, containment_score), 3)


def extract_probleme(full_text: str) -> str:
    match = re.search(r"Probl.me:\s*(.*?)(?:\nConversation:|$)", full_text, re.DOTALL)
    return match.group(1).strip()[:400] if match else ""


def extract_solution(full_text: str) -> str:
    match = re.search(r"Solution:\s*(.*?)$", full_text, re.DOTALL)
    return match.group(1).strip()[:500] if match else ""


def ensure_local_components_loaded() -> None:
    global load_classifier_bundle, analyze, detect_module, detect_type, rag
    if analyze is not None and rag is not None and detect_module is not None and detect_type is not None:
        return

    from classifier_engine import load_classifier_bundle as _load_classifier_bundle
    from nlp_engine import analyze as _analyze
    from rag_engine import detect_module as _detect_module, detect_type as _detect_type, rag as _rag

    load_classifier_bundle = _load_classifier_bundle
    analyze = _analyze
    detect_module = _detect_module
    detect_type = _detect_type
    rag = _rag


def derive_expected_labels(ticket: dict) -> tuple[str, str]:
    text = f"{ticket.get('objet', '')}. {extract_probleme(ticket.get('full_text', ''))}".strip()
    return detect_module(text), detect_type(text)


def _healthcheck() -> bool:
    try:
        response = requests.get(f"{API}/health", timeout=3)
        return response.ok
    except requests.RequestException:
        return False


def _stop_server() -> None:
    global _started_server
    if _started_server is None:
        return
    if _started_server.poll() is None:
        _started_server.terminate()
        try:
            _started_server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _started_server.kill()
            _started_server.wait(timeout=5)
    _started_server = None


def ensure_server() -> None:
    global _started_server
    if _healthcheck():
        return

    python_exe = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
    command = [
        str(python_exe),
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]

    _started_server = subprocess.Popen(
        command,
        cwd=str(BACKEND_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(_stop_server)

    deadline = time.time() + 120
    while time.time() < deadline:
        if _healthcheck():
            return
        if _started_server.poll() is not None:
            raise RuntimeError("Le serveur FastAPI a quitte immediatement.")
        time.sleep(2)

    raise TimeoutError("Le serveur FastAPI n'a pas repondu sur /health apres 120 secondes.")


def get_auth_headers() -> dict[str, str]:
    register_payload = {
        "full_name": "Client Evaluation",
        "email": EVAL_EMAIL,
        "phone": "0550000000",
        "company": "Evaluation PFEM2",
        "password": EVAL_PASSWORD,
    }
    try:
        requests.post(f"{API}/auth/client/register", json=register_payload, timeout=20)
    except requests.RequestException:
        pass

    login_response = requests.post(
        f"{API}/auth/login",
        json={"role": "client", "email": EVAL_EMAIL, "password": EVAL_PASSWORD},
        timeout=20,
    )
    login_response.raise_for_status()
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def fetch_health() -> dict:
    response = requests.get(f"{API}/health", timeout=15)
    response.raise_for_status()
    return response.json()


def call_search(question: str, session_id: str, auth_headers: dict[str, str], excluded_ids: list[str], use_llm: bool) -> dict:
    response = requests.post(
        f"{API}/search",
        json={
            "session_id": session_id,
            "question": question,
            "exclude_ticket_ids": excluded_ids,
            "use_llm": use_llm,
        },
        headers=auth_headers,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("state", {})


def local_rag_search(question: str, exclude_ticket_ids: list[str]) -> tuple[dict, list[dict]]:
    nlp_result = analyze(question)
    similar = rag.search(
        nlp_result["embedding"],
        k=5,
        module_filter=nlp_result.get("module", ""),
        type_filter=nlp_result.get("type_incident", ""),
        software_filter=nlp_result.get("software", ""),
        version_filter=nlp_result.get("software_version", ""),
        query_text=question,
        exclude_ticket_ids=exclude_ticket_ids,
    )
    return nlp_result, similar


def format_ratio(value: float) -> str:
    return f"{value:.0%}"


def print_section(title: str) -> None:
    print("\n" + "=" * 78)
    print(f"   {title}")
    print("=" * 78)


def main() -> None:
    print("Initialisation des composants NLP/RAG...")
    ensure_local_components_loaded()
    tickets = json.loads((ROOT_DIR / "ticket_test.json").read_text(encoding="utf-8"))
    if MAX_TICKETS > 0:
        tickets = tickets[:MAX_TICKETS]
    excluded_ids = [str(ticket.get("ticket_id")) for ticket in tickets if ticket.get("ticket_id") is not None]
    classifier_bundle = load_classifier_bundle()

    print_section(f"EVALUATION FULL STACK - {len(tickets)} TICKETS TEST")

    try:
        ensure_server()
        health = fetch_health()
        auth_headers = get_auth_headers()
    except Exception as exc:
        print(f"Impossible de preparer l'evaluation: {exc}")
        print("=" * 78 + "\n")
        raise SystemExit(1)

    llm_mode = health.get("llm_mode", "inconnu")
    llm_available = llm_mode in {"anthropic", "ollama"}
    print(f"Backend actif           : {API}")
    print(f"Mode LLM backend        : {llm_mode}")
    print(f"Tickets RAG charges     : {health.get('rag_tickets', '?')}")
    print(f"Classifieur disponible  : {'oui' if classifier_bundle else 'non'}")
    if not llm_available:
        print("Comparaison avec LLM    : indisponible (backend en mode rag_only)")

    rows = []
    module_hits_nlp = 0
    type_hits_nlp = 0
    module_hits_no_llm = 0
    type_hits_no_llm = 0
    module_hits_with_llm = 0
    type_hits_with_llm = 0
    rag_hits = 0
    classifier_hits_module = 0
    classifier_hits_type = 0

    for i, ticket in enumerate(tickets, 1):
        probleme = extract_probleme(ticket.get("full_text", ""))
        expected_solution = extract_solution(ticket.get("full_text", ""))
        if not probleme or len(probleme) < 15:
            continue

        expected_module, expected_type = derive_expected_labels(ticket)
        nlp_result, similar = local_rag_search(probleme, excluded_ids)
        classifier_prediction = nlp_result.get("classifier_prediction", {})
        rag_hits += 1 if similar else 0

        state_no_llm = call_search(
            question=probleme,
            session_id=f"fullstack_nollm_{i}",
            auth_headers=auth_headers,
            excluded_ids=excluded_ids,
            use_llm=False,
        )

        state_with_llm = None
        if llm_available:
            state_with_llm = call_search(
                question=probleme,
                session_id=f"fullstack_llm_{i}",
                auth_headers=auth_headers,
                excluded_ids=excluded_ids,
                use_llm=True,
            )

        nlp_module = nlp_result.get("module", "")
        nlp_type = nlp_result.get("type_incident", "")
        no_llm_module = state_no_llm.get("module", "")
        no_llm_type = state_no_llm.get("type_incident", "")
        with_llm_module = state_with_llm.get("module", "") if state_with_llm else ""
        with_llm_type = state_with_llm.get("type_incident", "") if state_with_llm else ""

        module_hits_nlp += 1 if nlp_module == expected_module else 0
        type_hits_nlp += 1 if nlp_type == expected_type else 0
        module_hits_no_llm += 1 if no_llm_module == expected_module else 0
        type_hits_no_llm += 1 if no_llm_type == expected_type else 0
        if state_with_llm:
            module_hits_with_llm += 1 if with_llm_module == expected_module else 0
            type_hits_with_llm += 1 if with_llm_type == expected_type else 0

        if classifier_prediction:
            classifier_hits_module += 1 if classifier_prediction.get("module", "") == expected_module else 0
            classifier_hits_type += 1 if classifier_prediction.get("type_incident", "") == expected_type else 0

        no_llm_solution = (state_no_llm.get("solution_proposee") or "").strip()
        no_llm_sol_sim = solution_similarity(expected_solution, no_llm_solution)
        no_llm_close = no_llm_sol_sim >= 0.45

        with_llm_solution = ""
        with_llm_sol_sim = 0.0
        with_llm_close = False
        if state_with_llm:
            with_llm_solution = (state_with_llm.get("solution_proposee") or "").strip()
            with_llm_sol_sim = solution_similarity(expected_solution, with_llm_solution)
            with_llm_close = with_llm_sol_sim >= 0.45

        rows.append(
            {
                "expected_module": expected_module,
                "expected_type": expected_type,
                "nlp_confidence": float(nlp_result.get("confidence", 0.0)),
                "classifier_module": classifier_prediction.get("module", ""),
                "classifier_type": classifier_prediction.get("type_incident", ""),
                "rag_found": bool(similar),
                "rag_best_similarity": float(similar[0].get("similarity", 0.0)) if similar else 0.0,
                "no_llm_confidence": float(state_no_llm.get("confidence_score", 0.0)),
                "no_llm_sim": no_llm_sol_sim,
                "no_llm_close": no_llm_close,
                "with_llm_confidence": float(state_with_llm.get("confidence_score", 0.0)) if state_with_llm else 0.0,
                "with_llm_sim": with_llm_sol_sim,
                "with_llm_close": with_llm_close,
            }
        )

        rag_marker = "RAG" if similar else "---"
        llm_display = f"{with_llm_sol_sim:.0%}" if state_with_llm else "n/a"
        print(
            f"[{i:02d}] Exp={expected_module[:4]:4}/{expected_type[:6]:6} "
            f"NLP={nlp_module[:4]:4}/{nlp_type[:6]:6} "
            f"{rag_marker}={float(similar[0].get('similarity', 0.0)) if similar else 0.0:.0%} "
            f"NoLLM={no_llm_sol_sim:.0%} "
            f"LLM={llm_display} | {normalize(probleme)[:42]}"
        )

    print_section("SYNTHESE")
    n = len(rows)
    if not n:
        print("Aucun ticket exploitable.")
        print("=" * 78 + "\n")
        return

    avg_nlp_conf = sum(row["nlp_confidence"] for row in rows) / n
    rag_rate = sum(row["rag_found"] for row in rows) / n
    avg_rag_best = sum(row["rag_best_similarity"] for row in rows) / n
    avg_no_llm_conf = sum(row["no_llm_confidence"] for row in rows) / n
    avg_no_llm_sim = sum(row["no_llm_sim"] for row in rows) / n
    no_llm_close_rate = sum(row["no_llm_close"] for row in rows) / n

    print("Classification")
    print(f"   Accuracy module NLP         : {format_ratio(module_hits_nlp / n)}")
    print(f"   Accuracy type NLP           : {format_ratio(type_hits_nlp / n)}")
    if classifier_bundle:
        print(f"   Accuracy module classifieur : {format_ratio(classifier_hits_module / n)}")
        print(f"   Accuracy type classifieur   : {format_ratio(classifier_hits_type / n)}")
    print(f"   Accuracy module pipeline    : {format_ratio(module_hits_no_llm / n)} (sans LLM)")
    print(f"   Accuracy type pipeline      : {format_ratio(type_hits_no_llm / n)} (sans LLM)")
    if llm_available:
        print(f"   Accuracy module pipeline    : {format_ratio(module_hits_with_llm / n)} (avec LLM)")
        print(f"   Accuracy type pipeline      : {format_ratio(type_hits_with_llm / n)} (avec LLM)")

    print("\nRAG")
    print(f"   Taux de recuperation RAG    : {format_ratio(rag_rate)}")
    print(f"   Similarite moyenne top-1    : {format_ratio(avg_rag_best)}")

    print("\nSolutions")
    print(f"   Confiance moyenne NLP       : {format_ratio(avg_nlp_conf)}")
    print(f"   Confiance moyenne sans LLM  : {format_ratio(avg_no_llm_conf)}")
    print(f"   Similarite sans LLM         : {format_ratio(avg_no_llm_sim)}")
    print(f"   Taux solution proche        : {format_ratio(no_llm_close_rate)} (sans LLM)")

    if llm_available:
        avg_with_llm_conf = sum(row["with_llm_confidence"] for row in rows) / n
        avg_with_llm_sim = sum(row["with_llm_sim"] for row in rows) / n
        with_llm_close_rate = sum(row["with_llm_close"] for row in rows) / n
        print(f"   Confiance moyenne avec LLM  : {format_ratio(avg_with_llm_conf)}")
        print(f"   Similarite avec LLM         : {format_ratio(avg_with_llm_sim)}")
        print(f"   Taux solution proche        : {format_ratio(with_llm_close_rate)} (avec LLM)")
        print(f"   Gain reel du LLM            : {avg_with_llm_sim - avg_no_llm_sim:+.1%} en similarite")
    else:
        print("   Similarite avec LLM         : non testee")
        print("   Gain reel du LLM            : non calcule")

    module_counter = Counter(row["expected_module"] for row in rows)
    print("\nDistribution du jeu de test")
    print(f"   Par module                  : {dict(module_counter)}")
    print(f"   Tickets testes              : {n}")
    print("\nNote")
    print("   Les labels attendus module/type sont derives automatiquement du corpus test.")
    print("   Ils servent a comparer les composants entre eux, pas a fournir une verite terrain humaine.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    