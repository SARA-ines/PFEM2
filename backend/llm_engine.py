import json
import os
from pathlib import Path

from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).with_name(".env"))

try:
    import anthropic
except Exception:
    anthropic = None


def build_prompt(
    user_message: str,
    context: dict,
    history: list[dict],
    similar_tickets: list[dict],
    nlp_result: dict,
    client_profile: dict | None = None,
    ticket_context: dict | None = None,
) -> str:
    history_text = "\n".join(
        f"{'Utilisateur' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in history[-6:]
    ) or "Aucun historique."

    if similar_tickets:
        ticket_lines = []
        for t in similar_tickets[:2]:
            if t.get("response_type") == "clarification" and t.get("clarification_question"):
                response_line = f"  Question a poser au client: {t['clarification_question']}"
            else:
                response_line = f"  Solution: {t['solution']}"
            ticket_lines.append(
                f"- [{t['id']}] {t['module'] or 'inconnu'}/{t['type'] or 'inconnu'} (similarite: {t['similarity']:.0%})\n"
                f"  Probleme: {t['description']}\n"
                f"{response_line}"
            )
        tickets_text = "\n".join(ticket_lines)
    else:
        tickets_text = "Aucun contexte interne disponible."

    # Bloc ticket — infos du formulaire remplies par le client
    if ticket_context and any(ticket_context.get(k) for k in ("module", "software", "version", "title")):
        ticket_block = f"""
=== TICKET SOUMIS PAR LE CLIENT ===
Titre        : {ticket_context.get('title', '')}
Module       : {ticket_context.get('module', 'Non precise')}
Logiciel     : {ticket_context.get('software', 'Non precise')}
Version      : {ticket_context.get('version', 'Non precisee')}
Priorite     : {ticket_context.get('priority', 'Moyenne')}
Description  : {ticket_context.get('description', user_message)}

IMPORTANT : Ces informations ont ete saisies par le client dans le formulaire.
Tu connais deja le logiciel et le module — ne les redemande pas.
Analyse directement le probleme decrit et propose une solution ou demande des precisions techniques.
"""
    else:
        ticket_block = ""

    # Bloc client — vide si aucun profil
    if client_profile:
        logiciels_str = ", ".join(
            f"{l['nom']} v{l['version']}" for l in client_profile.get("logiciels", [])
        ) or "Non renseigne"
        tickets_recents_str = "\n".join(
            f"  - #{t['id']} [{t['date']}] {t['module'] or '?'} : {t['objet']} ({t['etat']})"
            for t in client_profile.get("tickets_recents", [])
        ) or "  Aucun ticket recent."
        client_block = f"""
=== PROFIL DU CLIENT ===
Nom          : {client_profile.get('full_name', 'Inconnu')}
Entreprise   : {client_profile.get('company', 'Non renseignee')}
Email        : {client_profile.get('email', '')}
Telephone    : {client_profile.get('phone', '')}
Logiciels    : {logiciels_str}
Tickets recents :
{tickets_recents_str}
"""
    else:
        client_block = ""

    module_val = context.get('module') or nlp_result.get('module') or ''
    type_val = context.get('type_incident') or nlp_result.get('type_incident') or ''

    return f"""Tu es l'assistant IA de BIG Informatique. Tu aides les clients a resoudre leurs problemes ERP.
Tu parles comme un vrai humain, en francais naturel et chaleureux. Pas de jargon, pas de listes techniques.
{ticket_block}{client_block}
Historique de la conversation :
{history_text}

Base de connaissances interne (NE PAS mentionner au client) :
{tickets_text}

Dernier message du client : {user_message}

REGLES :
1. Reponds directement a ce que dit le client, comme dans une vraie conversation.
2. Si tu as deja le module/logiciel/version (voir TICKET SOUMIS ci-dessus), ne les redemande JAMAIS.
3. Si la base de connaissances contient une solution pertinente, reformule-la naturellement ("Essayez de...", "Dans ce cas, il faut...").
4. Si tu poses une question, pose-en UNE SEULE, courte et claire.
5. Si le client dit "j'ai pas compris" ou similaire, explique le terme precedent avec des mots simples.
6. Utilise "vous" pour etre professionnel.
7. Si le probleme est bloquant en production, propose d'escalader vers un technicien.

Reponds UNIQUEMENT avec ce JSON, sans texte avant ni apres :
{{
  "reponse": "Ta reponse naturelle ici (peut etre une solution, une question, une explication)",
  "probleme_resume": "Resume du probleme en 1 phrase courte",
  "module": "{module_val}",
  "type_incident": "{type_val}",
  "niveau_urgence": "bas",
  "bloquant": false,
  "statut": "qualification",
  "solution_proposee": "",
  "escalade_necessaire": false,
  "infos_manquantes": "",
  "confidence_score": 0.75
}}
"""


def call_llm(prompt: str) -> dict:
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    ollama_timeout = int(os.getenv("OLLAMA_TIMEOUT_SEC", "45"))
    if anthropic_key and anthropic is not None:
        client = anthropic.Anthropic(api_key=anthropic_key)
        response = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        return parse_llm_json(raw)

    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    response = requests.post(
        ollama_url,
        json={
            "model": os.getenv("OLLAMA_MODEL", "llama3.2"),
            "prompt": prompt,
            "stream": False,
        },
        timeout=ollama_timeout,
    )
    response.raise_for_status()
    raw = response.json().get("response", "").strip()
    return parse_llm_json(raw)


def parse_llm_json(raw: str) -> dict:
    import re as _re
    cleaned = raw.strip()

    # Tenter l'extraction du bloc markdown ```json ... ```
    md_match = _re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if md_match:
        candidate = md_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Tenter l'extraction du premier objet JSON {...} dans le texte
    json_match = _re.search(r"\{[\s\S]*\}", cleaned)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Tenter le parse direct
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Dernier recours : retourner le texte brut comme réponse
    return {
        "reponse": cleaned or "Je n'ai pas pu produire une reponse structuree.",
        "probleme_resume": "",
        "module": "",
        "type_incident": "",
        "niveau_urgence": "moyen",
        "bloquant": False,
        "statut": "qualification",
        "solution_proposee": "",
        "escalade_necessaire": False,
        "infos_manquantes": "",
        "confidence_score": 0.5,
    }
