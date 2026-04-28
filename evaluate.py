import atexit
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import requests

API = "http://127.0.0.1:8000"
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
VENV_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
EVAL_PASSWORD = "EvalPass#2026"
EVAL_EMAIL = "eval.client@pfem2.local"
EVALUATE_USE_LLM = os.getenv("EVALUATE_USE_LLM", "").strip().lower() in {"1", "true", "yes", "oui", "llm"}
EVALUATE_TIMEOUT_SECONDS = int(os.getenv("EVALUATE_TIMEOUT_SECONDS", "180" if EVALUATE_USE_LLM else "30"))

TEST_CASES = [
    {"q": "Stock negatif sur plusieurs articles apres mouvements de cession interne", "m": "stock", "t": "calcul"},
    {"q": "CUMP egal a zero dans les bons de sortie transfert biggestion", "m": "stock", "t": "calcul"},
    {"q": "Difference entre balance cumulee mouvements et journal des sorties", "m": "stock", "t": "calcul"},
    {"q": "Erreur lors de creation bon entree a partir bon commande, message lot aucun", "m": "stock", "t": "configuration"},
    {"q": "Stock initial importe incorrect a l'ouverture exercice 2025 biggestion", "m": "stock", "t": "configuration"},
    {"q": "Probleme regeneration stocks sur unite entreprise biggestion", "m": "stock", "t": "performance"},
    {"q": "Prix unitaire article carburant incoherent entre bon sortie et fiche article", "m": "stock", "t": "calcul"},
    {"q": "Apres modification bon sortie le logiciel cesse de fonctionner", "m": "stock", "t": "performance"},
    {"q": "Montant total non affiche dans mouvements stock article bon carburant", "m": "stock", "t": "interface"},
    {"q": "Retour produit client ne decremente pas la quantite en stock biggestion", "m": "stock", "t": "calcul"},
    {"q": "Erreur DISCORDANCE liste valeurs inserer colonnes lors saisie rappel bigpaie", "m": "paie", "t": "base_de_donnees"},
    {"q": "Rubriques employes et apprentis se confondent dans bigpaie calcul", "m": "paie", "t": "calcul"},
    {"q": "Net a payer affiche zero sur fiche de paie historique bigpaie", "m": "paie", "t": "interface"},
    {"q": "Fichier TXT virement salaires banque AGB genere vide exportation", "m": "paie", "t": "interface"},
    {"q": "Colonne BaseCalcule_ImpoCotis manquante table conges calcul paie bloque", "m": "paie", "t": "base_de_donnees"},
    {"q": "Lenteur terrible bigpaie apres installation nouvelle version mise a jour", "m": "paie", "t": "performance"},
    {"q": "IRG taux incorrect sur recapitulatif general paie rubrique 912", "m": "paie", "t": "calcul"},
    {"q": "Service SQL ne demarre pas saturation impossible acceder bigpaie", "m": "paie", "t": "base_de_donnees"},
    {"q": "Fichier DAS CACOBATPH genere non conforme nouvelle version logiciel", "m": "paie", "t": "configuration"},
    {"q": "Colonne SoumisAbat manquante table PRH_SITE_GEO erreur calcul paie", "m": "paie", "t": "base_de_donnees"},
    {"q": "Connexion serveur WinGRH impossible message erreur acces biggrh", "m": "rh", "t": "base_de_donnees"},
    {"q": "Erreur Word.Application non installe generation contrat biggrh", "m": "rh", "t": "configuration"},
    {"q": "Absences non affichees rapport malgre presence tableau pointage biggt", "m": "rh", "t": "interface"},
    {"q": "Conges attribues mois mai apparaissent aussi mois avril biggrh", "m": "rh", "t": "calcul"},
    {"q": "Liste deroulante niveau academique fiche employe ne fonctionne plus", "m": "rh", "t": "interface"},
    {"q": "Mise en disponibilite provoque blocage employe dans bigpaie biggrh", "m": "rh", "t": "configuration"},
    {"q": "Erreur impression etats biggrh biggt bigpaie liste des editions", "m": "rh", "t": "interface"},
    {"q": "Chevauchement date contrat licenciement periode essai biggrh", "m": "rh", "t": "configuration"},
    {"q": "Erreur saisie journal banque structure base donnees bigfinance", "m": "comptabilite", "t": "base_de_donnees"},
    {"q": "Compte 12000 resultat exercice anterieur triple ligne reouverture 2023", "m": "comptabilite", "t": "configuration"},
    {"q": "Numerotation piece comptable ne respecte pas sequence apres suppression", "m": "comptabilite", "t": "calcul"},
    {"q": "Exportation balance excel fichier vide bouton interrogation comptabilite", "m": "comptabilite", "t": "interface"},
    {"q": "Colonne Fecriture manquante erreur ODBC saisie bigfinance", "m": "comptabilite", "t": "base_de_donnees"},
    {"q": "Blocage acces bigfinance connexions SQL actives arriere plan licences", "m": "comptabilite", "t": "performance"},
    {"q": "Facture fournisseur erreur compte fournisseur vide comptabilisation", "m": "facturation", "t": "base_de_donnees"},
    {"q": "Montant TTC different net a payer facture subventionnee biggestion", "m": "facturation", "t": "calcul"},
    {"q": "Suppression impossible facture deja comptabilisee biggestion", "m": "facturation", "t": "configuration"},
    {"q": "Transfert bon livraison vers facture detail non transfere biggestion", "m": "facturation", "t": "base_de_donnees"},
    {"q": "Blocage enregistrement facture apres transfert plusieurs bons livraison", "m": "facturation", "t": "base_de_donnees"},
    {"q": "Deux bons commande meme numero CF0024 commandes differentes biggestion", "m": "facturation", "t": "base_de_donnees"},
]

_started_server = None


def _healthcheck() -> bool:
    try:
        response = requests.get(f"{API}/rag_stats", timeout=3)
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

    deadline = time.time() + 90
    while time.time() < deadline:
        if _healthcheck():
            return
        if _started_server.poll() is not None:
            raise RuntimeError("Le serveur FastAPI a quitte immediatement.")
        time.sleep(2)

    raise TimeoutError("Le serveur FastAPI n'a pas repondu sur http://127.0.0.1:8000 apres 90 secondes.")


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


def main() -> None:
    print("\n" + "=" * 70)
    print("   EVALUATION COMPLETE - 40 CAS COMPLEXES REELS")
    print(f"   Mode reponse : {'LLM/Ollama actif' if EVALUATE_USE_LLM else 'RAG rapide sans LLM'}")
    print("=" * 70)

    try:
        ensure_server()
        auth_headers = get_auth_headers()
    except Exception as exc:
        print(f"Impossible de preparer l'evaluation: {exc}")
        print("=" * 70 + "\n")
        return

    cases = TEST_CASES[:]
    random.shuffle(cases)
    results = []
    errors = 0

    for i, test in enumerate(cases, 1):
        try:
            response = requests.post(
                f"{API}/search",
                json={"session_id": f"eval_full_{i}", "question": test["q"], "use_llm": EVALUATE_USE_LLM},
                headers=auth_headers,
                timeout=EVALUATE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            state = data.get("state", {})

            ok_m = state.get("module") == test["m"]
            ok_t = state.get("type_incident") == test["t"]
            conf = state.get("confidence_score", 0)
            esc = state.get("escalade_necessaire", False)

            results.append(
                {
                    "case": test,
                    "module_ok": ok_m,
                    "type_ok": ok_t,
                    "confidence": conf,
                    "escalade": esc,
                }
            )

            status = "[OK]" if (ok_m and ok_t) else "[--]"
            m_icon = "OK" if ok_m else "NO"
            t_icon = "OK" if ok_t else "NO"
            print(f"{status} [{i:02d}] M={m_icon} T={t_icon} Conf={conf:.0%} | {test['q'][:50]}")
        except Exception as exc:
            errors += 1
            print(f"[ER] [{i:02d}] ERREUR SERVEUR: {str(exc)[:60]}")

    print("=" * 70)
    n = len(results)
    if n > 0:
        acc_m = sum(r["module_ok"] for r in results) / n
        acc_t = sum(r["type_ok"] for r in results) / n
        avg_c = sum(r["confidence"] for r in results) / n
        n_esc = sum(r["escalade"] for r in results)

        modules = ["stock", "paie", "rh", "comptabilite", "facturation"]
        print("\nPRECISION PAR MODULE :")
        for mod in modules:
            mod_tests = [r for r in results if r["case"]["m"] == mod]
            if mod_tests:
                ok = sum(1 for r in mod_tests if r["module_ok"] and r["type_ok"])
                marker = "[OK]" if ok == len(mod_tests) else "[--]"
                print(f"   {mod:15} : {ok}/{len(mod_tests)} {marker}")

        print(f"\nRESULTATS GLOBAUX ({n} tests / {errors} erreurs serveur)")
        print(f"   Precision module    : {acc_m:.0%}")
        print(f"   Precision type      : {acc_t:.0%}")
        print(f"   Confiance moyenne   : {avg_c:.0%}")
        print(f"   Escalades auto      : {n_esc}/{n}")

        score = (acc_m * 0.30 + acc_t * 0.30 + min(avg_c / 0.75, 1.0) * 0.40) * 100
        print(f"\nScore estime soutenance : {score:.0f}/100")
        if score >= 85:
            print("   EXCELLENT - Objectif 85%+ ATTEINT !")
        elif score >= 75:
            print("   TRES BON  - Niveau ingenieur confirme")
        elif score >= 65:
            print("   BON       - Quelques ajustements")
        else:
            print("   A ameliorer")

    print("\nBASE DE CONNAISSANCES (RAG)")
    try:
        rag_response = requests.get(f"{API}/rag_stats", timeout=10)
        rag_response.raise_for_status()
        stats = rag_response.json()
        print(f"   Total tickets : {stats['total']}")
        print(f"   Par module    : {stats['par_module']}")
        print(f"   Par type      : {stats['par_type']}")
    except Exception as exc:
        print(f"   Impossible de lire les stats RAG: {exc}")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
