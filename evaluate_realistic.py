import json
import atexit
import re
import subprocess
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import requests

API = "http://127.0.0.1:8000"
EVAL_PASSWORD = "EvalPass#2026"
EVAL_EMAIL = "eval.client@pfem2.local"
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
VENV_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"

_started_server = None


def normalize(text):
    text = (text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def extract_probleme(full_text):
    match = re.search(r"Probl.me:\s*(.*?)(?:\nConversation:|$)", full_text, re.DOTALL)
    return match.group(1).strip()[:200] if match else ""


def extract_solution(full_text):
    match = re.search(r"Solution:\s*(.*?)$", full_text, re.DOTALL)
    return match.group(1).strip()[:300] if match else ""


def tokenize(text):
    cleaned = re.sub(r"[^a-z0-9\s]", " ", normalize(text))
    return [token for token in cleaned.split() if len(token) > 2]


def solution_similarity(expected, predicted):
    expected_norm = normalize(expected)
    predicted_norm = normalize(predicted)
    if not expected_norm or not predicted_norm:
        return 0.0

    expected_tokens = set(tokenize(expected_norm))
    predicted_tokens = set(tokenize(predicted_norm))
    if not expected_tokens or not predicted_tokens:
        token_score = 0.0
    else:
        intersection = len(expected_tokens & predicted_tokens)
        union = len(expected_tokens | predicted_tokens)
        token_score = intersection / union if union else 0.0

    sequence_score = SequenceMatcher(None, expected_norm, predicted_norm).ratio()
    containment_score = 0.0
    if expected_norm in predicted_norm or predicted_norm in expected_norm:
        containment_score = 1.0

    return round(max(token_score, sequence_score, containment_score), 3)


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


def get_auth_headers():
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


def main():
    with open("ticket_test.json", "r", encoding="utf-8") as f:
        test_tickets = json.load(f)
    excluded_ids = [str(ticket.get("ticket_id")) for ticket in test_tickets if ticket.get("ticket_id") is not None]

    print(f"\n{'=' * 65}")
    print(f"   EVALUATION REALISTE - {len(test_tickets)} TICKETS REELS")
    print(f"{'=' * 65}")

    try:
        ensure_server()
        auth_headers = get_auth_headers()
    except Exception as exc:
        print(f"Impossible de preparer l'evaluation: {exc}")
        print(f"{'=' * 65}\n")
        raise SystemExit(1)

    results = []
    for i, ticket in enumerate(test_tickets[:30], 1):
        probleme = extract_probleme(ticket.get("full_text", ""))
        if not probleme or len(probleme) < 15:
            continue

        try:
            response = requests.post(
                f"{API}/search",
                json={
                    "session_id": f"real_eval_{i}",
                    "question": probleme,
                    "exclude_ticket_ids": excluded_ids,
                    "use_llm": False,
                },
                headers=auth_headers,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            state = data.get("state", {})
            conf = state.get("confidence_score", 0)
            mod = state.get("module", "")
            expected_solution = extract_solution(ticket.get("full_text", ""))
            predicted_solution = state.get("solution_proposee", "").strip()

            has_solution = len(predicted_solution) > 30
            has_similar = len(state.get("tickets_similaires", [])) > 0
            real_solution = normalize(expected_solution)
            proposed_solution = normalize(predicted_solution)
            real_words = set(real_solution.split())
            proposed_words = set(proposed_solution.split())
            if real_words and proposed_words:
                overlap = len(real_words & proposed_words) / len(real_words | proposed_words)
            else:
                overlap = 0.0
            sol_sim = solution_similarity(expected_solution, predicted_solution)
            close_solution = sol_sim >= 0.45

            results.append(
                {
                    "confidence": conf,
                    "has_solution": has_solution,
                    "has_similar": has_similar,
                    "module": mod,
                    "solution_similarity": sol_sim,
                    "sol_overlap": overlap,
                    "close_solution": close_solution,
                }
            )

            status = "[OK]" if close_solution else "[--]"
            print(f"{status} [{i:02d}] Conf={conf:.0%} Sol={sol_sim:.0%} Module={mod:12} | {normalize(probleme)[:45]}")

        except Exception as exc:
            print(f"[ER] [{i:02d}] {str(exc)[:50]}")

    print(f"{'=' * 65}")
    n = len(results)
    if n:
        avg_c = sum(r["confidence"] for r in results) / n
        sol_r = sum(r["has_solution"] for r in results) / n
        sim_r = sum(r["has_similar"] for r in results) / n
        avg_sol_sim = sum(r["solution_similarity"] for r in results) / n
        avg_overlap = sum(r["sol_overlap"] for r in results) / n
        close_sol_r = sum(r["close_solution"] for r in results) / n

        print(f"\nRESULTATS SUR DONNEES REELLES")
        print(f"   Tickets testes         : {n}")
        print(f"   Confiance moyenne      : {avg_c:.0%}")
        print(f"   Taux solution proposee : {sol_r:.0%}")
        print(f"   Taux ticket similaire  : {sim_r:.0%}")
        print(f"   Similarite solution    : {avg_sol_sim:.0%}")
        print(f"   Similarite solution      : {avg_overlap:.0%}")
        print(f"   Taux solution proche   : {close_sol_r:.0%}")

        score = (
            sol_r * 0.30
            + sim_r * 0.25
            + avg_overlap * 0.25
            + min(avg_c / 0.75, 1.0) * 0.20
        ) * 100
        print(f"\nScore realiste : {score:.0f}/100")
        if score >= 80:
            print("   [OK] EXCELLENT pour 164 tickets !")
        elif score >= 65:
            print("   [OK] BON - niveau acceptable")
        else:
            print("   [--] A ameliorer")
    print(f"{'=' * 65}\n")


if __name__ == "__main__":
    main()
