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
        tickets_text = "\n".join(
            f"- [{t['id']}] {t['module'] or 'inconnu'}/{t['type'] or 'inconnu'} (similarite: {t['similarity']:.0%})\n"
            f"  Probleme: {t['description']}\n"
            f"  Solution: {t['solution']}"
            for t in similar_tickets[:2]
        )
    else:
        tickets_text = "Aucun ticket similaire trouve."

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

    return f"""Tu es un assistant expert en support ERP pour la societe BIG Informatique.
Tu dois qualifier les incidents, proposer des solutions et escalader si necessaire.
Tu connais le client qui te parle : utilise son profil pour personnaliser tes reponses.
{ticket_block}{client_block}
=== CONTEXTE ACTUEL DE LA SESSION ===
Module ERP identifie : {context.get('module') or 'Non identifie'}
Type d'incident      : {context.get('type_incident') or 'Non identifie'}
Niveau d'urgence     : {context.get('niveau_urgence', 'moyen')}
Bloquant             : {'Oui' if context.get('bloquant') else 'Non'}
Statut actuel        : {context.get('statut', 'qualification')}
Resume du probleme   : {context.get('probleme_resume') or 'En cours de qualification'}
Infos manquantes     : {context.get('infos_manquantes') or 'Aucune'}

=== ANALYSE NLP DU MESSAGE ===
Intention detectee   : {nlp_result.get('intention', 'inconnu')}
Score de confiance   : {nlp_result.get('confidence', 0):.0%}
Entites extraites    : {json.dumps(nlp_result.get('entities', {}), ensure_ascii=False)}

=== HISTORIQUE RECENT ===
{history_text}

=== TICKETS SIMILAIRES (base de connaissances) ===
{tickets_text}

=== MESSAGE ACTUEL DE L'UTILISATEUR ===
{user_message}

=== COMPORTEMENT ATTENDU ===
Tu es un assistant support ERP intelligent et conversationnel, comme ChatGPT mais specialise ERP.
Tu LIS ce que dit le client et tu REPONDS a ce qu'il dit vraiment.

--- DETECTION DE CONFUSION ---
Si le client dit : "j'ai pas compris", "c'est quoi", "je comprends pas", "tu veux dire quoi", "kesako", ou toute phrase exprimant qu'il ne comprend pas ta question precedente :
-> EXPLIQUE simplement le terme que tu as utilise
-> Exemple : si tu avais demande "le message d'erreur" et il dit "j'ai pas compris", reponds :
   "Le message d'erreur, c'est le texte qui apparait en rouge ou dans une petite fenetre quand le logiciel bloque. Par exemple : 'Erreur SQL', 'Acces refuse', 'Impossible d'ouvrir'. Est-ce que vous voyez quelque chose comme ca sur votre ecran ?"
-> NE PASSE PAS a la question suivante avant qu'il ait compris

--- DETECTION D'INFORMATION ---
Si le client donne une info (meme en langage courant, meme avec des fautes) :
-> Integre-la dans le diagnostic
-> Ne redemande pas une info deja donnee
-> Avance dans la resolution

--- PROPOSITION DE SOLUTION ---
Si des tickets similaires sont presents dans le contexte :
-> Propose DIRECTEMENT une solution basee sur ces cas
-> Formule-la en langage simple, pas en jargon
-> Exemples de formulations : "D'apres les cas similaires que j'ai vus, voici ce qui a marche : ..."

--- QUALIFICATION (si info insuffisante) ---
Si tu n'as vraiment pas assez d'infos pour diagnostiquer :
-> Pose UNE SEULE question, en expliquant POURQUOI tu as '';;.;..;]'.;'...;;.;.';.;.;.';/;';/';besoin de cette info
-> Exemple : "Pour vous aider, j'ai besoin de savoir ce qui s'affiche exactement a l'ecran quand ca bloque. C'est le message d'erreur, souvent en rouge ou dans une petite fenetre."
-> Si le client ne comprend toujours pas apres 2 essais -> propose quand meme une piste generale

REGLES ABSOLUES :
- Adresse-toi toujours au client par son prenom si tu le connais
- Parle en francais simple et humain, jamais en jargon
- Ne repete JAMAIS la meme question deux fois de suite
- Si le bloc TICKET SOUMIS est present, tu sais deja le logiciel/module/version — ne les redemande jamais
- Si c'est bloquant et urgent -> statut = "escalade_technique"

JSON attendu (UNIQUEMENT le JSON, rien d'autre) :

{{
  "reponse": "Message pour l'utilisateur en francais",
  "probleme_resume": "Resume court du probleme",
  "module": "module ERP ou vide",
  "type_incident": "type ou vide",
  "niveau_urgence": "bas|moyen|haut|critique",
  "bloquant": true,
  "statut": "qualification|en_cours|solution_proposee|escalade_technique|resolu",
  "solution_proposee": "Solution ou vide",
  "escalade_necessaire": false,
  "infos_manquantes": "Infos manquantes ou vide",
  "confidence_score": 0.0
}}

Ne reponds QUE avec le JSON, sans texte avant ni apres.
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
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
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
