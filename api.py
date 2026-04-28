from fastapi import FastAPI, HTTPException
import faiss
import json
import numpy as np
import psycopg
import requests
from sentence_transformers import SentenceTransformer

app = FastAPI()

DB_DSN = "host=localhost port=5432 dbname=postgres user=postgres password=123456789"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"

index = faiss.read_index("ticket_index.faiss")

with open("ticket_metadata.json", "r", encoding="utf-8") as f:
    data = json.load(f)

model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")


def get_db_connection():
    return psycopg.connect(DB_DSN)


def ensure_tables():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages_chat (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(100) NOT NULL,
                    expediteur VARCHAR(30) NOT NULL,
                    message TEXT NOT NULL,
                    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_state (
                    session_id VARCHAR(100) PRIMARY KEY,
                    probleme_resume TEXT,
                    module VARCHAR(100),
                    type_incident VARCHAR(100),
                    niveau_urgence VARCHAR(50),
                    bloquant BOOLEAN DEFAULT FALSE,
                    infos_manquantes TEXT,
                    statut VARCHAR(50) DEFAULT 'qualification',
                    solution_proposee TEXT,
                    escalade_necessaire BOOLEAN DEFAULT FALSE,
                    technicien_assigne VARCHAR(100),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        conn.commit()


def enregistrer_message(session_id, expediteur, message):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages_chat (session_id, expediteur, message)
                VALUES (%s, %s, %s)
                """,
                (session_id, expediteur, message)
            )
        conn.commit()


def recuperer_historique(session_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT expediteur, message
                FROM messages_chat
                WHERE session_id = %s
                ORDER BY date_creation ASC, id ASC
                """,
                (session_id,)
            )
            rows = cur.fetchall()

    return [{"expediteur": exp, "message": msg} for exp, msg in rows]


def recuperer_etat_conversation(session_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    session_id,
                    probleme_resume,
                    module,
                    type_incident,
                    niveau_urgence,
                    bloquant,
                    infos_manquantes,
                    statut,
                    solution_proposee,
                    escalade_necessaire,
                    technicien_assigne
                FROM conversation_state
                WHERE session_id = %s
                """,
                (session_id,)
            )
            row = cur.fetchone()

    if not row:
        return {
            "session_id": session_id,
            "probleme_resume": "",
            "module": "",
            "type_incident": "",
            "niveau_urgence": "moyen",
            "bloquant": False,
            "infos_manquantes": "",
            "statut": "qualification",
            "solution_proposee": "",
            "escalade_necessaire": False,
            "technicien_assigne": ""
        }

    return {
        "session_id": row[0],
        "probleme_resume": row[1] or "",
        "module": row[2] or "",
        "type_incident": row[3] or "",
        "niveau_urgence": row[4] or "moyen",
        "bloquant": bool(row[5]),
        "infos_manquantes": row[6] or "",
        "statut": row[7] or "qualification",
        "solution_proposee": row[8] or "",
        "escalade_necessaire": bool(row[9]),
        "technicien_assigne": row[10] or ""
    }


def sauvegarder_etat_conversation(state):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_state (
                    session_id,
                    probleme_resume,
                    module,
                    type_incident,
                    niveau_urgence,
                    bloquant,
                    infos_manquantes,
                    statut,
                    solution_proposee,
                    escalade_necessaire,
                    technicien_assigne,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (session_id) DO UPDATE SET
                    probleme_resume = EXCLUDED.probleme_resume,
                    module = EXCLUDED.module,
                    type_incident = EXCLUDED.type_incident,
                    niveau_urgence = EXCLUDED.niveau_urgence,
                    bloquant = EXCLUDED.bloquant,
                    infos_manquantes = EXCLUDED.infos_manquantes,
                    statut = EXCLUDED.statut,
                    solution_proposee = EXCLUDED.solution_proposee,
                    escalade_necessaire = EXCLUDED.escalade_necessaire,
                    technicien_assigne = EXCLUDED.technicien_assigne,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    state["session_id"],
                    state["probleme_resume"],
                    state["module"],
                    state["type_incident"],
                    state["niveau_urgence"],
                    state["bloquant"],
                    state["infos_manquantes"],
                    state["statut"],
                    state["solution_proposee"],
                    state["escalade_necessaire"],
                    state["technicien_assigne"],
                )
            )
        conn.commit()


def normalize_text(text: str) -> str:
    return (
        text.lower()
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("à", "a")
        .replace("ù", "u")
        .replace("ô", "o")
        .replace("î", "i")
        .replace("ï", "i")
        .replace("ç", "c")
    )


def question_trop_vague(question: str) -> bool:
    question = normalize_text(question).strip()

    mots_vagues = [
        "ca marche pas",
        "ne fonctionne pas",
        "probleme",
        "bug",
        "erreur",
    ]

    if len(question) < 25:
        return True

    for mot in mots_vagues:
        if mot in question and len(question) < 60:
            return True

    return False


def build_history(messages):
    history = ""
    for msg in messages:
        history += f"{msg['expediteur']}: {msg['message']}\n"
    return history


def derive_state(session_id, messages, previous_state):
    history = build_history(messages)
    lowered = normalize_text(history)

    state = previous_state.copy()
    state["session_id"] = session_id

    if "stock" in lowered:
        state["module"] = "stock"
    elif "facturation" in lowered:
        state["module"] = "facturation"
    elif "paie" in lowered or "employe" in lowered:
        state["module"] = "rh"
    elif "achat" in lowered:
        state["module"] = "achat"

    if "sql" in lowered or "base" in lowered or "requete" in lowered:
        state["type_incident"] = "base_de_donnees"
    elif "connexion" in lowered or "login" in lowered or "mot de passe" in lowered:
        state["type_incident"] = "acces"
    elif "lent" in lowered or "performance" in lowered:
        state["type_incident"] = "performance"
    elif "impression" in lowered or "printer" in lowered:
        state["type_incident"] = "peripherique"

    if "bloquant" in lowered or "urgent" in lowered or "impossible" in lowered:
        state["bloquant"] = True
        state["niveau_urgence"] = "haut"
    elif state["niveau_urgence"] == "":
        state["niveau_urgence"] = "moyen"

    has_sql = "sql" in lowered
    has_module = state["module"] != ""
    has_error = "erreur" in lowered or "message d'erreur" in lowered

    missing = []
    if not has_module:
        missing.append("module concerné")
    if not has_error and not has_sql:
        missing.append("message d'erreur exact")
    if "avant" not in lowered and "apres" not in lowered and "quand" not in lowered:
        missing.append("action effectuée avant le problème")

    state["infos_manquantes"] = ", ".join(missing)

    if state["module"] or state["type_incident"]:
        state["probleme_resume"] = (
            f"Incident {state['type_incident'] or 'technique'}"
            f"{' sur le module ' + state['module'] if state['module'] else ''}"
        ).strip()

    state["escalade_necessaire"] = bool(
        state["bloquant"] and (
            state["type_incident"] == "base_de_donnees"
            or "timeout" in lowered
            or "500" in lowered
        )
    )

    if state["escalade_necessaire"]:
        state["statut"] = "escalade_technique"
    elif state["infos_manquantes"]:
        state["statut"] = "qualification"
    else:
        state["statut"] = "solution_possible"

    return state


def build_rag_context(question):
    question_vector = model.encode([question])
    question_vector = np.array(question_vector).astype("float32")

    _, indices = index.search(question_vector, 3)

    context = ""
    for idx in indices[0]:
        result = data[idx]
        context += result["full_text"] + "\n\n"
    return context


def build_prompt(history, context, question, state):
    return f"""
Tu es un agent support ERP.

Voici la conversation complète avec le client :
{history}

État courant de l'incident :
- résumé : {state['probleme_resume'] or 'non qualifié'}
- module : {state['module'] or 'inconnu'}
- type : {state['type_incident'] or 'inconnu'}
- urgence : {state['niveau_urgence']}
- bloquant : {'oui' if state['bloquant'] else 'non'}
- infos manquantes : {state['infos_manquantes'] or 'aucune'}
- escalade nécessaire : {'oui' if state['escalade_necessaire'] else 'non'}

Tickets similaires utiles :
{context}

Dernier message du client :
{question}

Règles importantes :
- Utilise d'abord l'historique de conversation pour comprendre le contexte.
- Les tickets similaires sont des exemples d'aide, pas des faits certains sur le client.
- N'invente jamais un module, une erreur ou une action si ce n'est pas clairement présent dans la conversation.
- Si le contexte est suffisant, donne une solution concrète.
- Si le contexte est insuffisant, pose 1 ou 2 questions précises maximum.
- Si l'incident semble bloquant ou nécessite un technicien, indique clairement qu'une escalade est recommandée.
- Ne dis pas que tu vas analyser plus tard : réponds directement.

Réponse attendue :
- 4 lignes maximum
- utile, concrète, sans introduction inutile
"""


ensure_tables()


@app.get("/")
def home():
    return {"message": "API support ERP prete"}


@app.get("/search")
def search(session_id: str, question: str):
    try:
        enregistrer_message(session_id, "utilisateur", question)
        messages = recuperer_historique(session_id)
        previous_state = recuperer_etat_conversation(session_id)
    except Exception as e:
        print("ERREUR POSTGRES :", e)
        raise HTTPException(status_code=500, detail=f"Erreur PostgreSQL: {e}") from e

    history = build_history(messages)
    state = derive_state(session_id, messages, previous_state)

    print("=== HISTORIQUE ===")
    print(history)
    print("=== QUESTION ===")
    print(question)
    print("=== STATE ===")
    print(state)

    if question_trop_vague(question) and len(messages) <= 1:
        answer = (
            "Pouvez-vous préciser votre problème : message d'erreur exact, module concerné, "
            "action effectuée avant le problème, et si c'est bloquant ?"
        )
        state["statut"] = "qualification"
        try:
            enregistrer_message(session_id, "bot", answer)
            sauvegarder_etat_conversation(state)
        except Exception as e:
            print("ERREUR POSTGRES :", e)
        return {"answer": answer, "state": state}

    normalized_history = normalize_text(history)

    if "sql" in normalized_history and "stock" in normalized_history:
        answer = (
            "Cela ressemble à une erreur SQL dans le module stock. Vérifiez le message d'erreur exact, "
            "la requête SQL exécutée et les droits d'accès à la base."
        )
        state["solution_proposee"] = answer
        state["statut"] = "solution_proposee"
        try:
            enregistrer_message(session_id, "bot", answer)
            sauvegarder_etat_conversation(state)
        except Exception as e:
            print("ERREUR POSTGRES :", e)
        return {"answer": answer, "state": state}

    if state["escalade_necessaire"]:
        answer = (
            "Incident potentiellement bloquant. Merci de transmettre au technicien avec le message d'erreur exact, "
            "le module concerné et l'action qui déclenche le problème."
        )
        state["solution_proposee"] = answer
        try:
            enregistrer_message(session_id, "bot", answer)
            sauvegarder_etat_conversation(state)
        except Exception as e:
            print("ERREUR POSTGRES :", e)
        return {"answer": answer, "state": state}

    try:
        context = build_rag_context(question)
    except Exception as e:
        print("ERREUR RAG :", e)
        context = ""

    prompt = build_prompt(history, context, question, state)

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False
            },
            timeout=180
        )
        response.raise_for_status()
        answer = response.json()["response"].strip()
    except Exception as e:
        print("ERREUR OLLAMA :", e)
        answer = "Erreur lors de la génération de la réponse."

    state["solution_proposee"] = answer
    if state["statut"] == "solution_possible":
        state["statut"] = "solution_proposee"

    try:
        enregistrer_message(session_id, "bot", answer)
        sauvegarder_etat_conversation(state)
    except Exception as e:
        print("ERREUR POSTGRES :", e)

    return {"answer": answer, "state": state}
