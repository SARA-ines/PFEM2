from collections import Counter
import base64
from datetime import datetime, timedelta
import email.mime.multipart
import email.mime.text
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import smtplib
import ssl
import sys
import traceback
import time
import unicodedata
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError

load_dotenv(Path(__file__).with_name(".env"))

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from business_logic import rewrite_rag_solution
from database import ClientLogiciel, ConversationSession, Logiciel, LogicielVersion, Message, Notification, PasswordResetToken, SessionLocal, Ticket, User
from nlp_engine import analyze
from preprocessing import prepare_ticket_text
from rag_engine import rag

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions = {}
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30


class ChatRequest(BaseModel):
    session_id: str = ""
    question: str
    exclude_ticket_ids: list[str] = []
    use_llm: bool = True
    ticket_context: dict = {}


class TicketAssignmentRequest(BaseModel):
    ticket_id: int


class ClientTicketCreate(BaseModel):
    title: str
    module: str
    software_name: str = ""
    software_version: str = ""
    description: str
    fonctionnalites: str = ""
    priority: str
    phone: str
    requester_name: str = "Marc Dupont"
    client_name: str = "BIG Logistique Algerie"
    client_id: str = "client-big-logistics"
    site: str = "Alger"


class ClientRegistrationCreate(BaseModel):
    full_name: str
    email: str
    phone: str
    company: str
    password: str


class TechnicianRegistrationCreate(BaseModel):
    full_name: str
    email: str
    phone: str
    technician_id: str
    specialty: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str
    role: str


def has_real_anthropic_key(api_key: str) -> bool:
    key = api_key.strip()
    if not key.startswith("sk-ant-"):
        return False
    if "xxxx" in key.lower():
        return False
    return len(key) > 20


def auth_secret() -> str:
    return os.getenv("AUTH_SECRET_KEY", "dev-auth-secret-change-me")


def hash_password(password: str, salt: str | None = None) -> str:
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_value.encode("utf-8"), 200000)
    return f"pbkdf2_sha256${salt_value}${digest.hex()}"


def verify_password(password: str, stored_password: str | None) -> bool:
    saved = (stored_password or "").strip()
    if not saved:
        return False
    if saved.startswith("pbkdf2_sha256$"):
        try:
            _, salt_value, saved_hash = saved.split("$", 2)
            candidate = hash_password(password, salt_value).split("$", 2)[2]
            return hmac.compare_digest(candidate, saved_hash)
        except ValueError:
            return False
    return hmac.compare_digest(saved, password)


def is_password_hashed(stored_password: str | None) -> bool:
    return (stored_password or "").startswith("pbkdf2_sha256$")


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("utf-8"))


def issue_access_token(user: User, role: str) -> str:
    payload = {
        "sub": user.user_id,
        "role": role,
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
        "email": user.email or "",
    }
    payload_part = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(auth_secret().encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    return f"{payload_part}.{b64url_encode(signature)}"


def decode_access_token(token: str) -> dict:
    try:
        payload_part, signature_part = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Token invalide.") from exc

    expected_signature = hmac.new(auth_secret().encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    provided_signature = b64url_decode(signature_part)
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise HTTPException(status_code=401, detail="Token invalide.")

    try:
        payload = json.loads(b64url_decode(payload_part).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Token invalide.") from exc

    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Session expiree.")
    return payload


def format_module_label(module: str) -> str:
    labels = {
        "comptabilite": "Comptabilité",
        "immobilisations": "Immobilisations",
        "tresorerie": "Trésorerie",
        "fiscalite": "Fiscalité",
        "budget": "Budget",
        "analytique": "Analytique",
        "facturation": "Facturation",
        "paie": "Paie",
        "rh": "Gestion Ressources Humaines",
        "gestion_temps": "Gestion du Temps",
        "administration": "Administration",
        "achats": "Achats",
        "achat": "Achats",
        "stock": "Stock",
        "ventes": "Ventes",
        "cimenterie": "Cimenterie",
        "plateforme_java": "Plateforme java",
        "sav": "Service Après Vente",
        "crm": "CRM",
        "marches": "Marchés",
        "gpao": "GPAO",
        "qualite": "Qualité",
        "gestion_projets": "Gestion de projets",
        "gestion_taches": "Gestion des tâches",
        "gestion_flotte": "Gestion de flotte",
        "gestion_marches": "Gestion des Marchés",
        "gestion_immobiliere": "Gestion Immobilière",
        "suivi_realisation": "Suivi Réalisation",
        "gestion_location": "Gestion Location",
        "gestion_documents": "Gestion des Documents",
        "bigsmq": "BIGSMQ",
        "bigtrans": "BIGTrans",
        "bigpharm": "BIGPharm",
        "bigclinic": "BIGClinic",
        "bigmed": "BIGMed",
        "bighotel": "BIGHotel",
        "bigloc": "BIGLoc",
        "alsem": "ALSEM",
        "dynamic_reports": "Dynamic Big Reports",
        "tickets_support": "Gestion des Tickets de Support",
        "bigcom": "BIGCom",
        "mobile": "Mobile",
        "bigcrm_mobile": "BIGCRM Mobile",
        "bigdashboard_mobile": "BIGDashboard Mobile",
        "bigmarpi_mobile": "BIGMarpi Mobile",
        "bigimmo_mobile": "BIGImmo Mobile",
        "biginventaire_mobile": "BIGInventaire Mobile",
        "demandesrh_mobile": "DemandesRH Mobile",
        "biglivraison_mobile": "BIGLivraison Mobile",
        "bighelpdesk_mobile": "BIGHelpdesk Mobile",
        "bigclinique_mobile": "BIGClinique Mobile",
        "bigsmq_mobile": "BIGSMQ Mobile",
        "bigmed_mobile": "BIGMED Mobile",
        "interventions_annaba": "Interventions Annaba",
        "interventions_alger": "Interventions Alger",
        "interventions_oran": "Interventions Oran",
    }
    value = (module or "").strip().lower()
    return labels.get(value, module.capitalize() if module else "General")


def format_type_label(type_incident: str) -> str:
    labels = {
        "base_de_donnees": "Base de donnees",
        "interface": "Interface",
        "performance": "Performance",
        "permission": "Permission",
        "configuration": "Configuration",
        "calcul": "Calcul",
        "autre": "Autre",
    }
    value = (type_incident or "").strip().lower()
    return labels.get(value, type_incident.replace("_", " ").capitalize() if type_incident else "Autre")


def infer_category(module: str, type_incident: str) -> str:
    return f"{format_module_label(module)} / {format_type_label(type_incident)}"


def humanize_age(value: datetime | None) -> str:
    if not value:
        return "date inconnue"
    delta = datetime.utcnow() - value
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return "a l'instant"
    if seconds < 3600:
        return f"il y a {seconds // 60} min"
    if seconds < 86400:
        return f"il y a {seconds // 3600} h"
    days = seconds // 86400
    if days == 1:
        return "hier"
    return f"il y a {days} jours"


def normalize_priority(priority: str | None) -> str:
    value = (priority or "").strip().lower()
    if value in {"critique", "urgent", "urgente"}:
        return "critique"
    if value in {"haute", "haut"}:
        return "haute"
    if value in {"moyen", "moyenne"}:
        return "moyenne"
    return "normale"


CONV_PATTERN = re.compile(r'\n\n\[(Technicien|Client)\s+([^\]]+)\]\s*')


def parse_ticket_conversation(details: str) -> tuple[str, list[dict]]:
    """Split ticket details into (clean_description, messages).
    Conversation markers have the form: \\n\\n[Technicien X] text or [Client X] text."""
    if not details:
        return "", []
    match = CONV_PATTERN.search(details)
    if not match:
        return details.strip(), []
    description = details[:match.start()].strip()
    parts = CONV_PATTERN.split(details[match.start():])
    messages = []
    i = 1
    while i + 2 < len(parts):
        role_type = parts[i].strip()
        author = parts[i + 1].strip()
        text = parts[i + 2].strip()
        if text:
            messages.append({"author": author, "role": "technicien" if role_type == "Technicien" else "client", "text": text})
        i += 3
    return description, messages


def map_client_status(ticket: Ticket) -> str:
    etat = (ticket.etat or "").strip().lower()
    if etat in {"fermer", "ferme", "fermee", "closed", "cloture", "cloturee", "resolu", "resolue"}:
        return "resolu"
    if ticket.assigned_to:
        return "attribue"
    return "en_attente"


def map_technician_status(ticket: Ticket) -> str:
    etat = (ticket.etat or "").strip().lower()
    if etat in {"fermer", "ferme", "fermee", "closed", "cloture", "cloturee", "resolu", "resolue"}:
        return "resolu"
    if "attente" in etat:
        return "en_attente_client"
    if ticket.assigned_to:
        return "en_cours"
    return "nouveau"


def full_user_name(user: User | None) -> str:
    if not user:
        return "Utilisateur"
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(part for part in parts if part).strip()
    return name or (user.username or f"Utilisateur {user.user_id}")


# ─────────────────────────── SMTP EMAIL ───────────────────────────────────


def _build_reset_email_html(recipient_name: str, reset_link: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Réinitialisation du mot de passe</title></head>
<body style="margin:0;padding:0;background:#f4f7fb;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f7fb;padding:40px 20px;">
    <tr><td align="center">
      <table width="540" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
        <!-- Header -->
        <tr><td style="background:linear-gradient(135deg,#204779,#2f67a8);padding:32px 40px;text-align:center;">
          <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;">BIG Informatique</h1>
          <p style="margin:6px 0 0;color:rgba(255,255,255,0.75);font-size:13px;">Support Client</p>
        </td></tr>
        <!-- Body -->
        <tr><td style="padding:40px 40px 32px;">
          <h2 style="margin:0 0 16px;color:#0f2446;font-size:20px;">Réinitialisation du mot de passe</h2>
          <p style="margin:0 0 12px;color:#496583;font-size:15px;line-height:1.6;">
            Bonjour <strong>{recipient_name}</strong>,
          </p>
          <p style="margin:0 0 24px;color:#496583;font-size:15px;line-height:1.6;">
            Nous avons reçu une demande de réinitialisation du mot de passe associé à votre compte.
            Cliquez sur le bouton ci-dessous pour choisir un nouveau mot de passe.
          </p>
          <div style="text-align:center;margin:28px 0;">
            <a href="{reset_link}" style="display:inline-block;background:linear-gradient(135deg,#1c6cff,#124fd3);color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:10px;font-size:15px;font-weight:700;letter-spacing:0.02em;">
              Réinitialiser mon mot de passe
            </a>
          </div>
          <p style="margin:0 0 8px;color:#7a90ad;font-size:13px;line-height:1.6;">
            Ce lien est valable pendant <strong>1 heure</strong>. Après expiration, vous devrez refaire une demande.
          </p>
          <p style="margin:0;color:#7a90ad;font-size:13px;line-height:1.6;">
            Si vous n'avez pas demandé cette réinitialisation, ignorez cet email — votre mot de passe reste inchangé.
          </p>
        </td></tr>
        <!-- Link fallback -->
        <tr><td style="padding:0 40px 32px;">
          <p style="margin:0;color:#a0b0c8;font-size:12px;word-break:break-all;">
            Lien de secours : <a href="{reset_link}" style="color:#1c6cff;">{reset_link}</a>
          </p>
        </td></tr>
        <!-- Footer -->
        <tr><td style="background:#f8faff;padding:20px 40px;text-align:center;border-top:1px solid #e8eef6;">
          <p style="margin:0;color:#a0b0c8;font-size:12px;">
            © BIG Informatique — Support automatisé. Ne pas répondre à cet email.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_reset_email(to_email: str, recipient_name: str, token: str) -> None:
    """Envoie l'email de réinitialisation via Gmail SMTP (STARTTLS port 587).
    Lève une exception si l'envoi échoue — l'appelant doit la gérer."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

    print(f"[SMTP DEBUG] host={smtp_host} port={smtp_port} user={smtp_user!r} password_set={bool(smtp_password)}")

    if not smtp_user or not smtp_password:
        raise RuntimeError(
            "SMTP non configuré : renseignez SMTP_USER et SMTP_PASSWORD dans le fichier .env"
        )

    reset_link = f"{frontend_url}?reset_token={token}"
    html_body = _build_reset_email_html(recipient_name, reset_link)
    plain_body = (
        f"Bonjour {recipient_name},\n\n"
        f"Réinitialisez votre mot de passe via ce lien (valable 1 heure) :\n{reset_link}\n\n"
        "Si vous n'avez pas fait cette demande, ignorez cet email."
    )

    msg = email.mime.multipart.MIMEMultipart("alternative")
    msg["Subject"] = "Réinitialisation de votre mot de passe — BIG Informatique"
    msg["From"] = f"BIG Support <{smtp_user}>"
    msg["To"] = to_email
    msg.attach(email.mime.text.MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(email.mime.text.MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_email, msg.as_string())
            logger.info("Email de réinitialisation envoyé à %s", to_email)
    except smtplib.SMTPAuthenticationError as exc:
        print(traceback.format_exc())
        raise RuntimeError(
            "Échec de l'authentification SMTP. Vérifiez que vous utilisez un App Password Gmail "
            "(non le mot de passe principal) et que la validation en 2 étapes est activée."
        ) from exc
    except smtplib.SMTPException as exc:
        print(traceback.format_exc())
        raise RuntimeError(f"Erreur d'envoi email (SMTP) : {exc}") from exc
    except OSError as exc:
        print(traceback.format_exc())
        raise RuntimeError(
            f"Impossible de joindre le serveur SMTP ({smtp_host}:{smtp_port}). "
            "Vérifiez votre connexion et les paramètres SMTP."
        ) from exc



def pick_auto_technician(db) -> User | None:
    technicians = (
        db.query(User)
        .filter(User.etat != 2)
        .order_by(User.currentAccessDate.desc().nullslast(), User.user_id.asc())
        .all()
    )
    return technicians[0] if technicians else None


def infer_ticket_module(ticket: Ticket, logiciel_name: str = "") -> str:
    raw = (ticket.module or "").strip()
    if raw:
        return raw
    low_logiciel = logiciel_name.lower()
    if "paie" in low_logiciel:
        return "paie"
    if "finance" in low_logiciel or "compta" in low_logiciel:
        return "comptabilite"
    if "grh" in low_logiciel or "rh" in low_logiciel:
        return "rh"
    if "gestion" in low_logiciel or "stock" in low_logiciel:
        return "stock"
    return "general"


def infer_ticket_type(ticket: Ticket, module_name: str) -> str:
    text = f"{ticket.objet or ''} {ticket.details or ''}".lower()
    if "sql" in text or "base" in text or "bdd" in text:
        return "base_de_donnees"
    if "lenteur" in text or "bloqu" in text or "freeze" in text:
        return "performance"
    if "impression" in text or "affichage" in text or "etat" in text or "rapport" in text:
        return "interface"
    if "calcul" in text or "montant" in text or "irg" in text or "ecart" in text:
        return "calcul"
    if "activation" in text or "licence" in text or "acces" in text:
        return "permission"
    if "param" in text or "version" in text or "installation" in text:
        return "configuration"
    if module_name == "facturation" and ("facture" in text or "fournisseur" in text):
        return "calcul"
    return "autre"


def normalize_module_value(value: str) -> str:
    normalized = (value or "").strip().lower()
    aliases = {
        "grh": "rh",
        "biggrh": "rh",
        "gestion ressources humaines": "rh",
        "bigpaie": "paie",
        "big finance": "comptabilite",
        "bigfinance": "comptabilite",
        "comptabilite": "comptabilite",
        "big gestion": "stock",
        "biggestion": "stock",
        "winstock": "stock",
        "achat": "achats",
        "gestion du temps": "gestion_temps",
        "gdt": "gestion_temps",
        "biggt": "gestion_temps",
        "service apres vente": "sav",
        "service après vente": "sav",
        "gpao": "gpao",
        "gestion de projets": "gestion_projets",
        "gestion des taches": "gestion_taches",
        "gestion de flotte": "gestion_flotte",
        "gestion des marches": "gestion_marches",
        "gestion immobiliere": "gestion_immobiliere",
        "gestion immobilière": "gestion_immobiliere",
        "suivi realisation": "suivi_realisation",
        "gestion location": "gestion_location",
        "gestion des documents": "gestion_documents",
        "dynamic big reports": "dynamic_reports",
        "gestion des tickets de support": "tickets_support",
    }
    return aliases.get(normalized, normalized)


def extract_explicit_module(question: str) -> str:
    match = re.search(r"module\s*:\s*([^\n\r]+)", question or "", re.IGNORECASE)
    if not match:
        return ""
    raw_value = match.group(1).strip()
    if not raw_value:
        return ""
    return normalize_module_value(raw_value.split()[0])


def is_vague(question: str) -> bool:
    text = " ".join((question or "").lower().split())
    if len(text) < 40:
        return True

    vague_terms = {
        "bonjour",
        "probleme",
        "problème",
        "anomalie",
        "erreur",
        "bug",
        "fonctionne",
    }
    specific_words = [
        word
        for word in re.findall(r"\b[\w-]+\b", text)
        if word not in vague_terms and len(word) > 4
    ]
    return len(specific_words) < 3


def normalize_rule_text(*values: str) -> str:
    text = " ".join(str(value or "") for value in values)
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_consultant_escalation_request(question: str, ticket_context: dict | None = None) -> bool:
    tc = ticket_context or {}
    text = normalize_rule_text(
        question,
        tc.get("title", ""),
        tc.get("description", ""),
        tc.get("fonctionnalites", ""),
    )
    if not text:
        return False

    if "consultant" in text:
        return True

    if "migration" in text and any(
        term in text for term in ("donnees", "base", "serveur", "complete", "ancien", "nouveau")
    ):
        return True

    if any(term in text for term in ("reprise de donnees", "transfert de donnees", "import historique")):
        return True

    if "formation" in text and any(term in text for term in ("utilisateur", "users", "module", "assistance")):
        return True

    if any(term in text for term in ("configuration complete", "parametrage complet", "mise en place complete")):
        return True

    if "assistance" in text and any(term in text for term in ("configuration", "parametrage", "formation", "gpao")):
        return True

    return False


def is_direct_calculation_problem(question: str, nlp_result: dict | None = None) -> bool:
    text = normalize_rule_text(question)
    if (nlp_result or {}).get("type_incident") == "calcul":
        return True
    return any(
        term in text
        for term in (
            "calcul",
            "montant",
            "ttc",
            "tva",
            "total ht",
            "irg",
            "cump",
            "cotisation",
            "ecart",
            "stock negatif",
            "quantite",
            "prix",
        )
    )


def is_interface_output_problem(question: str) -> bool:
    text = normalize_rule_text(question)
    return any(
        term in text
        for term in (
            "impression",
            "etat",
            "affichage",
            "rapport",
            "crystal",
            "ecran",
            "vide",
        )
    )


def is_version_sensitive_problem(question: str, nlp_result: dict | None = None) -> bool:
    text = normalize_rule_text(question)
    strong_version_terms = (
        "cloture",
        "ecritures de report",
        "report a nouveau",
        "reouverture",
        "exercice",
        "installation",
        "reinstallation",
        "mise a jour",
        "version",
        "parametrage",
    )
    if is_interface_output_problem(question) and not any(term in text for term in strong_version_terms):
        return False
    if (nlp_result or {}).get("type_incident") == "configuration":
        return True
    return any(
        term in text
        for term in strong_version_terms
    )


def should_force_version_check(question: str, nlp_result: dict, ticket_context: dict | None = None) -> bool:
    tc = ticket_context or {}
    client_version = (
        tc.get("version")
        or nlp_result.get("software_version")
        or ""
    ).strip()
    if not client_version:
        return False
    if is_direct_calculation_problem(question, nlp_result) and not is_version_sensitive_problem(question, nlp_result):
        return False

    software_name = tc.get("software") or tc.get("software_name") or nlp_result.get("software") or ""
    latest_version = get_latest_version_for_software(software_name)
    if not latest_version or latest_version.strip() == client_version:
        return False
    return is_version_sensitive_problem(question, nlp_result)


def rag_vote_scores(similar: list[dict], key: str) -> dict[str, float]:
    votes = {}
    for ticket in similar:
        label = (ticket.get(key) or "").strip()
        if not label:
            continue
        votes[label] = votes.get(label, 0.0) + float(ticket.get("similarity", 0))
    total = sum(votes.values())
    if total <= 0:
        return {}
    return {label: round(score / total, 4) for label, score in votes.items()}


def fuse_incident_predictions(nlp_result: dict, similar: list[dict]) -> dict:
    module_scores = dict(nlp_result.get("module_scores", {}) or {})
    rag_module_scores = rag_vote_scores(similar, "module")
    all_modules = set(module_scores) | set(rag_module_scores)
    fused_module_scores = {
        mod: round(module_scores.get(mod, 0.0) * 0.7 + rag_module_scores.get(mod, 0.0) * 0.3, 4)
        for mod in all_modules
    }
    module = nlp_result.get("module", "")
    if fused_module_scores:
        best_module = max(fused_module_scores, key=fused_module_scores.get)
        if fused_module_scores[best_module] > 0:
            module = best_module

    type_scores = dict(nlp_result.get("type_scores", {}) or {})
    rag_type_scores = rag_vote_scores(similar, "type")

    all_types = set(type_scores) | set(rag_type_scores)
    fused_type_scores = {
        incident_type: round(type_scores.get(incident_type, 0.0) * 0.6 + rag_type_scores.get(incident_type, 0.0) * 0.4, 4)
        for incident_type in all_types
    }

    final_type = nlp_result.get("type_incident", "")
    if fused_type_scores:
        best_type = max(fused_type_scores, key=fused_type_scores.get)
        if fused_type_scores[best_type] > 0:
            final_type = best_type

    software = nlp_result.get("software", "")
    software_match = bool(software and similar and similar[0].get("software") == software)
    avg_similarity = sum(ticket.get("similarity", 0) for ticket in similar[:3]) / max(len(similar[:3]), 1) if similar else 0.0
    type_agreement = rag_type_scores.get(final_type, 0.0)
    best_nlp_score = max(type_scores.values()) if type_scores else nlp_result.get("confidence", 0.0)
    base_nlp_confidence = max(float(nlp_result.get("confidence", 0.4)), float(best_nlp_score))

    nlp_result["module"] = module
    nlp_result["module_scores"] = fused_module_scores or module_scores
    nlp_result["rag_module_scores"] = rag_module_scores
    nlp_result["type_incident"] = final_type
    nlp_result["type_scores"] = fused_type_scores or type_scores
    nlp_result["rag_type_scores"] = rag_type_scores
    nlp_result["rag_type_agreement"] = round(type_agreement, 4)
    nlp_result["avg_similarity_top3"] = round(avg_similarity, 4)
    nlp_result["software_match_bonus"] = 1.0 if software_match else 0.0

    # Formule corrigée : NLP a plus de poids pour ne plus bloquer à 49%
    # quand le RAG ne trouve pas de tickets proches
    nlp_result["confidence"] = round(
        min(
            0.20
            + 0.45 * base_nlp_confidence          # NLP pèse plus (était 0.30)
            + 0.20 * float(avg_similarity)         # RAG (était 0.25)
            + 0.10 * float(type_agreement)
            + 0.05 * (1.0 if software_match else 0.0)
            + 0.10 * (1.0 if similar else 0.0),   # bonus présence RAG
            0.95,
        ),
        2,
    )
    return nlp_result


def build_rag_only_response(question: str, nlp_result: dict, similar: list[dict], mode: str) -> dict:
    best_type_score = max((nlp_result.get("type_scores") or {"": 0}).values()) if nlp_result.get("type_scores") else 0.0
    nlp_conf = float(nlp_result.get("confidence", 0.3))

    if similar:
        best = similar[0]
        if best.get("response_type") == "clarification" and best.get("clarification_question"):
            solution_text = best["clarification_question"]
            reponse = solution_text
            statut = "qualification"
        else:
            solution_text = best["solution"]
            reponse = rewrite_rag_solution(
                best["objet"],
                solution_text,
                nlp_result.get("module", ""),
                nlp_result.get("type_incident", ""),
            )
            statut = "solution_proposee"
        if False and len(similar) > 1:
            reponse += f"\n\nAutre cas similaire : {similar[1]['objet']} — {similar[1]['solution'][:150]}"

        confidence = round(
            min(
                0.50
                + 0.20 * float(best.get("similarity", 0))
                + 0.15 * float(nlp_result.get("rag_type_agreement", 0))
                + 0.10 * float(best_type_score)
                + 0.10 * nlp_conf,
                0.95,
            ),
            2,
        )
    else:
        # Pas de ticket similaire : réponse de qualification basée sur NLP
        module = nlp_result.get("module", "")
        type_inc = nlp_result.get("type_incident", "")
        if module and type_inc:
            solution_text = (
                f"Incident de type '{type_inc}' detecte sur le module '{module}'. "
                "Merci de fournir le message d'erreur exact et les etapes pour reproduire le probleme."
            )
        elif module:
            solution_text = (
                f"Probleme detecte sur le module '{module}'. "
                "Pouvez-vous preciser le message d'erreur exact ?"
            )
        else:
            solution_text = (
                "Merci de preciser : le module concerne (stock, paie, RH, comptabilite, facturation), "
                "le message d'erreur exact, et si c'est bloquant."
            )
        reponse = solution_text
        confidence = round(min(0.40 + 0.20 * nlp_conf + 0.10 * best_type_score, 0.65), 2)
        statut = "qualification"

    return {
        "reponse": reponse,
        "probleme_resume": question[:100],
        "module": nlp_result.get("module", ""),
        "type_incident": nlp_result.get("type_incident", ""),
        "niveau_urgence": "moyen",
        "bloquant": False,
        "statut": statut,
        "solution_proposee": solution_text,
        "escalade_necessaire": confidence < 0.40,
        "confidence_score": round(confidence, 2),
        "tickets_similaires": [
            {
                "id": t["id"],
                "objet": t["objet"],
                "similarity": t["similarity"],
                "module": t.get("module", ""),
                "type": t.get("type", ""),
                "solution": t.get("solution", ""),
                "response_type": t.get("response_type", "solution"),
                "clarification_question": t.get("clarification_question", ""),
            }
            for t in similar
        ],
        "metrics": {
            "nlp_confidence": round(nlp_conf, 2),
            "rag_similarity": round(nlp_result.get("avg_similarity_top3", similar[0]["similarity"] if similar else 0), 2),
            "type_agreement": round(nlp_result.get("rag_type_agreement", 0), 2),
            "mode": mode,
        },
    }


def build_missing_info_request_v2(question: str, nlp_result: dict) -> tuple[str, list[str]]:
    normalized_question = (question or "").lower()
    checks = [
        ("module exact utilise", not nlp_result.get("module")),
        ("nom du logiciel", not nlp_result.get("software")),
        ("version du logiciel", not nlp_result.get("software_version")),
        (
            "message d'erreur exact ou code affiche",
            not any(term in normalized_question for term in ["erreur", "error", "exception", "code"]),
        ),
        (
            "etapes exactes pour reproduire le probleme",
            not any(term in normalized_question for term in ["apres", "lors", "etape", "reprodu", "quand"]),
        ),
        (
            "impact metier et si le probleme est bloquant",
            not any(term in normalized_question for term in ["bloquant", "urgent", "critique", "impossible"]),
        ),
        ("capture d'ecran si disponible", True),
    ]

    missing_items = []
    for label, needed in checks:
        if needed and label not in missing_items:
            missing_items.append(label)
        if len(missing_items) >= 4:
            break

    if not missing_items:
        missing_items = [
            "message d'erreur exact ou code affiche",
            "etapes exactes pour reproduire le probleme",
            "impact metier et si le probleme est bloquant",
        ]

    request_text = (
        "Merci de verifier que les informations deja affichees dans le resume sont correctes, "
        "puis de completer si besoin : "
        + "; ".join(missing_items)
        + ". Une fois confirme, votre ticket sera assigne a un technicien qui vous repondra le plus tot possible."
    )
    return request_text, missing_items


COLLECTION_FIELDS = [
    {
        "id": "module_exact",
        "label": "module exact utilise",
        "question": "Quel module exact utilisez-vous (stock, paie, RH, comptabilite, facturation) ?",
    },
    {
        "id": "software_name",
        "label": "nom du logiciel",
        "question": "Quel est le nom exact du logiciel concerne ?",
    },
    {
        "id": "software_version",
        "label": "version du logiciel",
        "question": "Quelle est la version exacte du logiciel ?",
    },
    {
        "id": "error_message",
        "label": "message d'erreur exact ou code affiche",
        "question": "Quel est le message d'erreur exact ou le code affiche a l'ecran ?",
    },
    {
        "id": "reproduction_steps",
        "label": "etapes exactes pour reproduire le probleme",
        "question": "Quelles sont les etapes exactes pour reproduire le probleme ?",
    },
    {
        "id": "business_impact",
        "label": "impact metier et caractere bloquant",
        "question": "Quel est l'impact metier, et est-ce que le probleme est bloquant ?",
    },
    {
        "id": "attachment_available",
        "label": "capture d'ecran si disponible",
        "question": "Avez-vous une capture d'ecran ou un document que vous pouvez joindre ?",
    },
]


def auto_collect_information(question: str, nlp_result: dict, session_state: dict) -> dict:
    text = (question or "").strip()
    normalized = text.lower()
    collected = dict(session_state.get("collected_info") or {})
    awaiting_field = session_state.get("awaiting_field", "")
    low_signal_answers = {"bonjour", "bonsoir", "merci", "ok", "oui", "non", "salut"}

    if awaiting_field and text and normalized not in low_signal_answers and len(text) >= 4:
        collected[awaiting_field] = text[:280]

    if nlp_result.get("module"):
        collected["module_exact"] = nlp_result["module"]
    if nlp_result.get("software"):
        collected["software_name"] = nlp_result["software"]
    if nlp_result.get("software_version"):
        collected["software_version"] = nlp_result["software_version"]

    software_match = re.search(r"logiciel\s*:\s*([^\n]+)", text, re.IGNORECASE)
    if software_match:
        collected["software_name"] = software_match.group(1).strip()[:120]

    version_match = re.search(r"version\s*:\s*([^\n]+)", text, re.IGNORECASE)
    if version_match:
        collected["software_version"] = version_match.group(1).strip()[:80]

    module_match = re.search(r"module\s*:\s*([^\n]+)", text, re.IGNORECASE)
    if module_match:
        collected["module_exact"] = module_match.group(1).strip()[:80]

    if any(term in normalized for term in ["erreur", "error", "exception", "code"]):
        collected.setdefault("error_message", text[:280])
    if any(term in normalized for term in ["apres", "lors", "etape", "reprodu", "quand", "puis"]):
        collected.setdefault("reproduction_steps", text[:280])
    if any(term in normalized for term in ["bloquant", "urgent", "critique", "impossible", "impact", "production"]):
        collected.setdefault("business_impact", text[:280])
    if any(term in normalized for term in ["capture", "piece jointe", "pj", "screenshot", "document"]):
        collected.setdefault("attachment_available", text[:280])

    return collected


def compute_collection_plan(question: str, nlp_result: dict, session_state: dict) -> tuple[dict, list[dict], dict | None]:
    collected = auto_collect_information(question, nlp_result, session_state)

    pending = []
    for field in COLLECTION_FIELDS:
        if not collected.get(field["id"]):
            pending.append(field)

    next_field = pending[0] if pending else None
    return collected, pending, next_field


def build_technician_summary_v2(
    question: str,
    nlp_result: dict,
    similar: list[dict],
    missing_items: list[str],
    collected_info: dict | None = None,
) -> str:
    parts = [f"Probleme client: {question[:220]}"]
    if nlp_result.get("module"):
        parts.append(f"Module probable: {nlp_result['module']}")
    if nlp_result.get("type_incident"):
        parts.append(f"Type probable: {nlp_result['type_incident']}")
    if nlp_result.get("software"):
        software_summary = nlp_result["software"]
        if nlp_result.get("software_version"):
            software_summary += f" {nlp_result['software_version']}"
        parts.append(f"Logiciel: {software_summary}")
    if similar:
        parts.append(f"RAG: meilleur cas similaire {similar[0].get('id', '?')} a {similar[0].get('similarity', 0):.0%}")
    if collected_info:
        compact = ", ".join(
            f"{key}={value[:80]}" for key, value in collected_info.items() if isinstance(value, str) and value.strip()
        )
        if compact:
            parts.append(f"Informations collectees: {compact}")
    if missing_items:
        parts.append("Informations a recuperer: " + ", ".join(missing_items))
    return " | ".join(parts)


GENERIC_SOLUTION_BY_TYPE = {
    "permission": (
        "Verifiez d'abord les droits de l'utilisateur sur le module concerne, puis reconnectez-vous avec un profil "
        "administrateur pour confirmer que le blocage ne vient pas d'un role ou d'une licence expiree. Si l'acces "
        "reste refuse, transmettez le message exact au support pour correction des droits."
    ),
    "calcul": (
        "Controlez les parametres de calcul du document, les taux appliques et les lignes source, puis regenerez le "
        "calcul apres sauvegarde. Si l'ecart persiste, joignez un exemple chiffre afin qu'un technicien compare les "
        "donnees en base avec le resultat affiche."
    ),
    "interface": (
        "Regenerer l'etat, verifier le modele d'impression et relancer l'application suffit souvent pour isoler le "
        "probleme. Si l'etat reste vide, il faut joindre le nom exact de l'etat et une capture du resultat."
    ),
    "performance": (
        "Verifiez d'abord la connexion au serveur, le nombre de sessions ouvertes et l'etat du service SQL. Si la "
        "lenteur persiste, un technicien devra controler les index, journaux et requetes lentes."
    ),
    "base_de_donnees": (
        "Avant toute manipulation, faites une sauvegarde de la base. Relevez ensuite le message SQL exact, le nom de "
        "la table ou de l'ecran concerne, puis transmettez ces elements pour correction technique."
    ),
    "configuration": (
        "Verifiez le parametrage du module, l'exercice ou la periode active, puis relancez l'operation apres "
        "validation des droits. Si le blocage continue, le ticket doit etre analyse par un technicien."
    ),
}


def build_generic_solution_text(module: str, incident_type: str) -> str:
    solution = GENERIC_SOLUTION_BY_TYPE.get(incident_type)
    if not solution:
        return ""
    if module:
        return f"Pour ce probleme sur le module {module}, voici la demarche conseillee : {solution}"
    return f"Voici la demarche conseillee : {solution}"


def build_rag_only_response_v2(question: str, nlp_result: dict, similar: list[dict], mode: str, session_state: dict | None = None) -> dict:
    best_type_score = max((nlp_result.get("type_scores") or {"": 0}).values()) if nlp_result.get("type_scores") else 0.0
    nlp_conf = float(nlp_result.get("confidence", 0.3))
    state = session_state or {}
    target_module = nlp_result.get("module", "")
    target_type = nlp_result.get("type_incident", "")
    if target_type == "configuration" and is_interface_output_problem(question):
        target_type = "interface"
    if is_direct_calculation_problem(question, nlp_result):
        similar = [ticket for ticket in similar if ticket.get("response_type") != "version_check"]
    filtered_similar = []
    for ticket in similar:
        similarity = float(ticket.get("similarity", 0))
        same_module = bool(target_module and ticket.get("module") == target_module)
        same_type = bool(target_type and ticket.get("type") == target_type)
        min_similarity = 0.28 if (same_module or same_type) else 0.32
        if similarity >= min_similarity:
            filtered_similar.append(ticket)
    best_similarity = float(filtered_similar[0].get("similarity", 0)) if filtered_similar else 0.0
    collected_info, pending_fields, next_field = compute_collection_plan(question, nlp_result, state)

    if filtered_similar:
        similar = filtered_similar
        best = similar[0]
        if best.get("response_type") == "clarification" and best.get("clarification_question"):
            solution_text = best["clarification_question"]
            reponse = solution_text
            statut = "qualification"
            infos_manquantes = "precision technique"
            missing_items = ["precision technique"]
            next_question = solution_text
            ready_for_assignment = False
        else:
            solution_text = best["solution"]
            reponse = rewrite_rag_solution(
                best["objet"],
                solution_text,
                nlp_result.get("module", ""),
                nlp_result.get("type_incident", ""),
            )
            statut = "solution_proposee"
            infos_manquantes = ""
            missing_items = []
            next_question = ""
            ready_for_assignment = False
        if False and len(similar) > 1:
            pass

        confidence = round(
            min(
                0.45
                + 0.20 * float(best.get("similarity", 0))
                + 0.15 * float(nlp_result.get("rag_type_agreement", 0))
                + 0.10 * float(best_type_score)
                + 0.10 * nlp_conf,
                0.95,
            ),
            2,
        )
    else:
        generic_solution = build_generic_solution_text(target_module, target_type)
        if generic_solution and nlp_conf >= 0.58:
            missing_items = []
            next_question = ""
            solution_text = generic_solution
            reponse = solution_text
            confidence = round(min(0.58 + 0.25 * nlp_conf + 0.10 * best_type_score, 0.82), 2)
            statut = "solution_proposee"
            infos_manquantes = ""
            similar = filtered_similar
            ready_for_assignment = False
        else:
            missing_items = [field["label"] for field in pending_fields]
            next_question = next_field["question"] if next_field else ""
            solution_text = next_question or build_missing_info_request_v2(question, nlp_result)[0]
            reponse = solution_text
            confidence = round(min(0.35 + 0.25 * nlp_conf + 0.10 * best_type_score, 0.69), 2)
            statut = "qualification" if confidence >= 0.40 else "escalade_technique"
            infos_manquantes = "; ".join(missing_items)
            similar = filtered_similar
            ready_for_assignment = next_field is None

    technician_summary = build_technician_summary_v2(question, nlp_result, similar, missing_items, collected_info)
    return {
        "reponse": reponse,
        "probleme_resume": question[:100],
        "module": nlp_result.get("module", ""),
        "type_incident": target_type,
        "niveau_urgence": "moyen",
        "bloquant": False,
        "statut": statut,
        "solution_proposee": solution_text,
        "escalade_necessaire": confidence < 0.40,
        "infos_manquantes": infos_manquantes,
        "next_question": next_question,
        "collected_info": collected_info,
        "resume_technicien": technician_summary,
        "hide_details_in_bubble": confidence < 0.70,
        "confidence_score": round(confidence, 2),
        "ready_for_assignment": ready_for_assignment if "ready_for_assignment" in locals() else False,
        "tickets_similaires": [
            {
                "id": t["id"],
                "objet": t["objet"],
                "similarity": t["similarity"],
                "module": t.get("module", ""),
                "type": t.get("type", ""),
                "solution": (t.get("solution", "") or "")[:150],
                "response_type": t.get("response_type", "solution"),
                "clarification_question": t.get("clarification_question", ""),
            }
            for t in similar
        ],
        "metrics": {
            "nlp_confidence": round(nlp_conf, 2),
            "rag_similarity": round(nlp_result.get("avg_similarity_top3", similar[0]["similarity"] if similar else 0), 2),
            "type_agreement": round(nlp_result.get("rag_type_agreement", 0), 2),
            "mode": mode,
            "n_similar": len(similar),
        },
    }


def get_latest_version_for_software(software_name: str, software_id: str = "") -> str:
    """Retourne la dernière version disponible d'un logiciel depuis logiciel_version.

    Accepte soit l'ID numérique (ex: "825") soit le nom (ex: "BigPaie", "bigpaie").
    Fait une correspondance partielle insensible à la casse sur nom_logiciel.
    """
    try:
        with SessionLocal() as db:
            lid = None

            # ID numérique direct (ex: "825", "827")
            sid = str(software_id or "").strip()
            if sid.isdigit():
                lid = int(sid)
            elif software_name:
                # Normalisation : minuscules, sans espaces ni tirets
                def _norm(s: str) -> str:
                    return s.lower().replace(" ", "").replace("-", "").replace("_", "")

                target = _norm(software_name)
                rows = db.execute(text("SELECT logiciel_id, nom_logiciel FROM logiciel")).fetchall()
                for row in rows:
                    if row[1] and (_norm(row[1]) == target or target in _norm(row[1]) or _norm(row[1]) in target):
                        lid = row[0]
                        break

            if lid is None:
                return ""

            row = db.execute(
                text("SELECT version_id FROM logiciel_version WHERE logiciel_id = :lid ORDER BY version_id DESC LIMIT 1"),
                {"lid": lid},
            ).scalar()
            return str(row) if row is not None else ""
    except Exception:
        return ""


def build_escalade_consultant_response(
    question: str,
    nlp_result: dict,
    similar: list[dict],
    session_state: dict,
    ticket_context: dict | None = None,
) -> dict:
    collected_info, pending_fields, next_field = compute_collection_plan(question, nlp_result, session_state)
    nlp_conf = float(nlp_result.get("confidence", 0.5))
    all_collected = next_field is None

    if all_collected:
        reponse = (
            "Merci pour toutes ces informations. Votre dossier est complet. "
            "Un consultant specialise va prendre en charge votre demande et vous contactera dans les meilleurs delais."
        )
        next_question = ""
        ready = True
    else:
        intro = (
            "Ce type de probleme necessite l'intervention d'un consultant specialise. "
            "Pour preparer votre dossier et vous mettre en relation rapidement, j'ai besoin de quelques informations. "
            if not session_state.get("response_mode") == "escalade_consultant"
            else "Merci. Pour completer votre dossier, "
        )
        reponse = f"{intro}{next_field['question']}"
        next_question = next_field["question"]
        ready = False

    technician_summary = build_technician_summary_v2(
        question, nlp_result, similar, [f["label"] for f in pending_fields], collected_info
    )
    confidence = round(min(0.60 + 0.15 * nlp_conf, 0.80), 2)
    return {
        "reponse": reponse,
        "probleme_resume": question[:100],
        "module": nlp_result.get("module", ""),
        "type_incident": nlp_result.get("type_incident", ""),
        "niveau_urgence": nlp_result.get("niveau_urgence", "moyen"),
        "bloquant": False,
        "statut": "escalade_consultant",
        "solution_proposee": "",
        "escalade_necessaire": True,
        "infos_manquantes": "; ".join(f["label"] for f in pending_fields),
        "next_question": next_question,
        "collected_info": collected_info,
        "resume_technicien": technician_summary,
        "hide_details_in_bubble": False,
        "confidence_score": confidence,
        "ready_for_assignment": ready,
        "tickets_similaires": [
            {
                "id": t["id"], "objet": t["objet"], "similarity": t["similarity"],
                "module": t.get("module", ""), "type": t.get("type", ""),
                "solution": "", "response_type": "escalade_consultant", "clarification_question": "",
            }
            for t in similar
        ],
        "metrics": {
            "nlp_confidence": round(nlp_conf, 2),
            "rag_similarity": round(similar[0]["similarity"] if similar else 0, 2),
            "type_agreement": round(nlp_result.get("rag_type_agreement", 0), 2),
            "mode": "ESCALADE_CONSULTANT",
            "n_similar": len(similar),
        },
    }


def build_version_check_response(
    question: str,
    nlp_result: dict,
    similar: list[dict],
    session_state: dict,
    ticket_context: dict | None = None,
) -> dict:
    tc = ticket_context or {}
    collected = session_state.get("collected_info") or {}

    client_version = (
        collected.get("software_version")
        or tc.get("version")
        or nlp_result.get("software_version")
        or session_state.get("version")
        or ""
    ).strip()

    # Récupère le nom du logiciel depuis le contexte ou le ticket similaire
    software_name = tc.get("software") or tc.get("software_name") or nlp_result.get("software") or ""

    # Récupère l'ID numérique du logiciel : priorité au ticket similaire (logiciel_id stocké comme "825")
    # puis au ticket_context si disponible
    sim_sw = similar[0].get("software", "") if similar else ""
    if sim_sw and str(sim_sw).strip().isdigit():
        software_id = sim_sw
    else:
        software_id = tc.get("logiciel_id") or ""
        if not software_id:
            software_name = software_name or sim_sw

    latest_version = get_latest_version_for_software(software_name, str(software_id))
    software_label = software_name or "votre logiciel"
    nlp_conf = float(nlp_result.get("confidence", 0.5))

    if not client_version:
        reponse = (
            f"Pour diagnostiquer ce probleme sur {software_label}, "
            "pourriez-vous m'indiquer la version exacte que vous utilisez actuellement ? "
            "(Accessible via le menu Aide > A propos)"
        )
        next_question = "Quelle est la version exacte du logiciel ?"
        statut = "qualification"
        escalade = False
        confidence = round(min(0.50 + 0.15 * nlp_conf, 0.70), 2)
        ready = False
        version_info = {"client_version": "", "latest_version": latest_version, "is_latest": False}
    elif latest_version and client_version.strip() != latest_version.strip():
        reponse = (
            f"Votre version actuelle ({client_version}) n'est pas la derniere version disponible de {software_label}. "
            f"La derniere version est la {latest_version}. "
            "La mise a jour resout generalement ce type de probleme. "
            "Souhaitez-vous que je vous guide pour la mise a jour, ou preferez-vous qu'un technicien vous assiste ?"
        )
        next_question = ""
        statut = "version_check"
        escalade = False
        confidence = round(min(0.72 + 0.10 * nlp_conf, 0.85), 2)
        ready = False
        version_info = {"client_version": client_version, "latest_version": latest_version, "is_latest": False}
    else:
        ctx = f"Vous utilisez deja la derniere version ({client_version})." if latest_version else f"Version utilisee : {client_version}."
        reponse = (
            f"{ctx} "
            "Le probleme persiste malgre la mise a jour. "
            "Je vais assigner votre ticket a un technicien specialise qui analysera le probleme en detail."
        )
        next_question = ""
        statut = "escalade_technique"
        escalade = True
        confidence = round(min(0.74 + 0.10 * nlp_conf, 0.88), 2)
        ready = True
        version_info = {"client_version": client_version, "latest_version": latest_version, "is_latest": True}

    technician_summary = (
        f"Probleme: {question[:120]} | Logiciel: {software_label} | "
        f"Version client: {client_version or 'non renseignee'} | "
        f"Derniere version DB: {latest_version or 'inconnue'}"
    )
    return {
        "reponse": reponse,
        "probleme_resume": question[:100],
        "module": nlp_result.get("module", ""),
        "type_incident": "configuration",
        "niveau_urgence": nlp_result.get("niveau_urgence", "moyen"),
        "bloquant": False,
        "statut": statut,
        "solution_proposee": reponse if statut != "qualification" else "",
        "escalade_necessaire": escalade,
        "infos_manquantes": "version du logiciel" if not client_version else "",
        "next_question": next_question,
        "collected_info": dict(collected),
        "resume_technicien": technician_summary,
        "hide_details_in_bubble": False,
        "confidence_score": confidence,
        "ready_for_assignment": ready,
        "version_info": version_info,
        "tickets_similaires": [
            {
                "id": t["id"], "objet": t["objet"], "similarity": t["similarity"],
                "module": t.get("module", ""), "type": t.get("type", ""),
                "solution": "", "response_type": "version_check", "clarification_question": "",
            }
            for t in similar
        ],
        "metrics": {
            "nlp_confidence": round(nlp_conf, 2),
            "rag_similarity": round(similar[0]["similarity"] if similar else 0, 2),
            "type_agreement": round(nlp_result.get("rag_type_agreement", 0), 2),
            "mode": "VERSION_CHECK",
            "n_similar": len(similar),
        },
    }


def load_client_profile(user: User) -> dict:
    """Charge le profil complet du client : logiciels, version, tickets récents."""
    profile = {
        "user_id": user.user_id,
        "full_name": full_user_name(user),
        "company": user.raison_social or "",
        "email": user.email or "",
        "phone": user.phone or "",
        "logiciels": [],
        "tickets_recents": [],
    }
    try:
        with SessionLocal() as db:
            # Logiciels du client
            rows = (
                db.query(ClientLogiciel, Logiciel)
                .join(Logiciel, Logiciel.logiciel_id == ClientLogiciel.logiciel_id)
                .filter(ClientLogiciel.user_id == user.user_id, ClientLogiciel.actif == 1)
                .all()
            )
            profile["logiciels"] = [
                {"nom": log.nom_logiciel, "version": cl.version or "inconnue"}
                for cl, log in rows
            ]
            # 5 derniers tickets du client
            tickets = (
                db.query(Ticket)
                .filter(Ticket.user_id == user.user_id)
                .order_by(Ticket.createDateTime.desc().nullslast())
                .limit(5)
                .all()
            )
            profile["tickets_recents"] = [
                {
                    "id": t.ticket_id,
                    "objet": t.objet or "",
                    "etat": t.etat or "",
                    "module": t.module or "",
                    "date": t.createDateTime.strftime("%Y-%m-%d") if t.createDateTime else "",
                }
                for t in tickets
            ]
            # Historique des messages de la session en cours si elle existe en DB
    except Exception:
        pass
    return profile


def load_user_history_from_db(user_id: int, limit: int = 20) -> list[dict]:
    """Charge les derniers messages d'un client depuis la base (persiste après déconnexion)."""
    if not user_id:
        return []
    with SessionLocal() as db:
        msgs = (
            db.query(Message)
            .filter(Message.user_id == user_id)
            .order_by(Message.timestamp.desc().nullslast(), Message.id.desc())
            .limit(limit)
            .all()
        )
        return [{"role": m.role, "content": m.content} for m in sort_messages_ascending(msgs)]


def save_message_to_db(user_id: int | None, role: str, content: str, confidence: float | None = None, session_id: str | None = None):
    """Persiste un message de chat en base."""
    if not user_id:
        return
    with SessionLocal() as db:
        msg = Message(
            role=role,
            content=content,
            confidence=confidence,
            user_id=user_id,
            session_id=session_id,
            timestamp=datetime.utcnow(),
        )
        db.add(msg)
        if session_id:
            existing_session = db.query(ConversationSession).filter(ConversationSession.session_id == session_id).first()
            existing_state = parse_session_state(existing_session.state if existing_session else None)
            upsert_conversation_session(db, session_id, existing_state, user_id)
        db.commit()


def fresh_session_state() -> dict:
    return {"collected_info": {}, "awaiting_field": ""}


def parse_session_state(raw_state) -> dict:
    if isinstance(raw_state, dict):
        parsed = dict(raw_state)
    elif isinstance(raw_state, str) and raw_state.strip():
        try:
            loaded = json.loads(raw_state)
            parsed = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            parsed = {}
    else:
        parsed = {}

    state = fresh_session_state()
    state.update(parsed)
    if not isinstance(state.get("collected_info"), dict):
        state["collected_info"] = {}
    state.setdefault("awaiting_field", "")
    return state


def encode_session_state(state: dict) -> dict:
    return json.loads(json.dumps(state or {}, ensure_ascii=False, default=str))


def message_to_history_item(message: Message) -> dict:
    return {
        "role": message.role,
        "content": message.content,
        "timestamp": message.timestamp.isoformat() if message.timestamp else None,
    }


def sort_messages_ascending(messages: list[Message]) -> list[Message]:
    return sorted(messages, key=lambda item: (item.timestamp or datetime.min, item.id or 0))


def load_persisted_session(session_id: str, user_id: int | None, limit: int = 120) -> dict:
    if not session_id:
        return {"history": [], "state": fresh_session_state()}

    with SessionLocal() as db:
        session = db.query(ConversationSession).filter(ConversationSession.session_id == session_id).first()
        if session and user_id and session.user_id and session.user_id != user_id:
            raise HTTPException(status_code=403, detail="Conversation non autorisee pour cet utilisateur.")

        query = db.query(Message).filter(Message.session_id == session_id)
        if user_id:
            query = query.filter(Message.user_id == user_id)
        messages = (
            query.order_by(Message.timestamp.desc().nullslast(), Message.id.desc())
            .limit(limit)
            .all()
        )
        history = [{"role": m.role, "content": m.content} for m in sort_messages_ascending(messages)]
        state = parse_session_state(session.state if session else None)
        return {"history": history, "state": state}


def upsert_conversation_session(db, session_id: str, state: dict, user_id: int | None = None):
    if not session_id:
        return

    session = db.query(ConversationSession).filter(ConversationSession.session_id == session_id).first()
    if session:
        if user_id and session.user_id and session.user_id != user_id:
            raise HTTPException(status_code=403, detail="Conversation non autorisee pour cet utilisateur.")
        if user_id and not session.user_id:
            session.user_id = user_id
    else:
        session = ConversationSession(session_id=session_id, user_id=user_id, created_at=datetime.utcnow())
        db.add(session)

    session.state = encode_session_state(state)
    session.updated_at = datetime.utcnow()


def persist_assistant_turn(
    user_id: int | None,
    session_id: str,
    user_message: str,
    assistant_message: str,
    state: dict,
    confidence: float | None = None,
):
    if not user_id or not session_id:
        return

    try:
        with SessionLocal() as db:
            now = datetime.utcnow()
            db.add(
                Message(
                    role="user",
                    content=user_message,
                    user_id=user_id,
                    session_id=session_id,
                    timestamp=now,
                )
            )
            db.add(
                Message(
                    role="assistant",
                    content=assistant_message,
                    confidence=confidence,
                    user_id=user_id,
                    session_id=session_id,
                    timestamp=datetime.utcnow(),
                )
            )
            upsert_conversation_session(db, session_id, state, user_id)
            db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Echec sauvegarde conversation: {exc}") from exc


def run_assistant(
    question: str,
    session_id: str = "",
    exclude_ticket_ids: list[str] | None = None,
    use_llm: bool = True,
    client_profile: dict | None = None,
    ticket_context: dict | None = None,
) -> dict:
    sid = session_id or str(uuid.uuid4())
    uid = (client_profile or {}).get("user_id")
    if sid not in sessions:
        persisted = load_persisted_session(sid, uid, limit=40) if session_id else {"history": [], "state": fresh_session_state()}
        sessions[sid] = {"history": persisted["history"], "state": persisted["state"], "user_id": uid}
    sess = sessions[sid]
    if uid and sess.get("user_id") and sess["user_id"] != uid:
        raise HTTPException(status_code=403, detail="Conversation non autorisee pour cet utilisateur.")
    if uid and not sess.get("user_id"):
        sess["user_id"] = uid
    sess["state"].setdefault("collected_info", {})
    sess["state"].setdefault("awaiting_field", "")

    # Mémoriser le profil client dans la session pour toute la conversation
    if client_profile and not sess.get("client_profile"):
        sess["client_profile"] = client_profile
    profile = sess.get("client_profile") or client_profile or {}

    # Pré-peupler la session avec les données du formulaire ticket dès le premier appel
    if ticket_context and not sess.get("ticket_context_loaded"):
        sess["ticket_context_loaded"] = True
        sess["ticket_context"] = ticket_context
        tc_module = normalize_module_value(ticket_context.get("module", ""))
        if tc_module:
            sess["state"]["module"] = tc_module
        if ticket_context.get("software"):
            sess["state"]["software"] = ticket_context["software"]
        if ticket_context.get("version"):
            sess["state"]["version"] = ticket_context["version"]
        if ticket_context.get("priority"):
            sess["state"]["niveau_urgence"] = normalize_priority(ticket_context["priority"])
        collected = sess["state"].setdefault("collected_info", {})
        if tc_module:
            collected["module"] = tc_module
        if ticket_context.get("software"):
            collected["logiciel"] = ticket_context["software"]
        if ticket_context.get("version"):
            collected["version"] = ticket_context["version"]
        if ticket_context.get("title"):
            collected["titre"] = ticket_context["title"]
        if ticket_context.get("fonctionnalites"):
            collected["fonctionnalites"] = ticket_context["fonctionnalites"]

    tc = sess.get("ticket_context") or ticket_context or {}

    PURE_GREETINGS = {"bonjour", "bonsoir", "salut", "hello", "bjr", "slt", "bsr", "hi", "coucou"}
    question_clean = question.strip().lower()
    is_greeting = question_clean in PURE_GREETINGS

    # Salutation en cours de conversation : répéter la dernière question du bot
    if is_greeting and sess["history"]:
        last_bot_msg = next(
            (m["content"] for m in reversed(sess["history"]) if m["role"] == "assistant"), ""
        )
        stored_module = sess["state"].get("module") or (normalize_module_value(tc.get("module", "")) if tc else "")
        stored_type = sess["state"].get("type_incident") or ""
        if last_bot_msg:
            greeting_reply = f"Bonjour ! {last_bot_msg}"
        elif stored_module:
            greeting_reply = (
                f"Bonjour ! Concernant votre probleme sur le module {stored_module}, "
                "pouvez-vous preciser le message d'erreur exact affiche a l'ecran ?"
            )
        else:
            greeting_reply = "Bonjour ! Pouvez-vous decrire votre probleme ?"
        sess["history"].append({"role": "user", "content": question})
        sess["history"].append({"role": "assistant", "content": greeting_reply})
        persist_assistant_turn(
            sess.get("user_id") or (client_profile or {}).get("user_id"),
            sid, question, greeting_reply, sess["state"],
        )
        return {
            "session_id": sid,
            "answer": greeting_reply,
            "state": {
                "module": stored_module,
                "type_incident": stored_type,
                "statut": sess["state"].get("statut", "qualification"),
                "solution_proposee": "",
                "escalade_necessaire": False,
                "infos_manquantes": "",
                "confidence_score": 0.4,
                "tickets_similaires": [],
                "ready_for_assignment": False,
            },
        }

    prepared = prepare_ticket_text(question)
    working_question = prepared["enriched"] or question

    # Pour les messages vagues (< 40 chars sans mots-clés), enrichir avec le contexte du formulaire
    if is_vague(question) and tc and (tc.get("description") or tc.get("title")):
        ctx_parts = [p for p in [
            f"Titre: {tc['title']}" if tc.get("title") else "",
            f"Description: {tc['description']}" if tc.get("description") else "",
            f"Fonctionnalites: {tc['fonctionnalites']}" if tc.get("fonctionnalites") else "",
        ] if p]
        if ctx_parts:
            ctx_text = "\n".join(ctx_parts)
            ctx_prepared = prepare_ticket_text(ctx_text)
            working_question = ctx_prepared["enriched"] or ctx_text

    nlp_result = analyze(working_question)

    # Injecter module/logiciel/version depuis le formulaire si NLP ne les détecte pas
    if tc.get("module") and not nlp_result.get("module"):
        nlp_result["module"] = normalize_module_value(tc["module"])
    if tc.get("software") and not nlp_result.get("software"):
        nlp_result["software"] = tc["software"]
    if tc.get("version") and not nlp_result.get("software_version"):
        nlp_result["software_version"] = tc["version"]

    explicit_module = extract_explicit_module(question) or (normalize_module_value(tc.get("module", "")) if tc else "")
    if explicit_module:
        nlp_result["module"] = explicit_module
        module_scores = dict(nlp_result.get("module_scores", {}) or {})
        module_scores[explicit_module] = max(float(module_scores.get(explicit_module, 0.0)), 1.0)
        nlp_result["module_scores"] = module_scores

    # Si NLP n'a pas détecté le logiciel et que le client n'a qu'un seul logiciel → l'inférer
    if not nlp_result.get("software") and profile.get("logiciels"):
        client_logiciels = profile["logiciels"]
        if len(client_logiciels) == 1:
            nlp_result["software"] = client_logiciels[0]["nom"]
            nlp_result["software_version"] = client_logiciels[0].get("version", "")

    client_software_list = ", ".join(l["nom"] for l in profile.get("logiciels", [])) if profile.get("logiciels") else "BigPaie, BigGestion, BigGRH"

    # Si le formulaire a fourni module+logiciel+description, on skip la qualification initiale
    has_ticket_context = bool(tc.get("module") and tc.get("software") and question.strip())

    if is_vague(question) and not explicit_module and not sess["state"].get("module") and not has_ticket_context:
        final = {
            "reponse": (
                f"Bonjour {profile.get('full_name', '')}{',' if profile.get('full_name') else 'Pour vous aider efficacement,'} merci de preciser :\n"
                f"1. Le logiciel concerne ({client_software_list})\n"
                "2. Le message d'erreur exact\n"
                "3. L'action effectuee avant le probleme"
            ),
            "probleme_resume": question[:100],
            "module": "",
            "type_incident": "",
            "niveau_urgence": "moyen",
            "bloquant": False,
            "statut": "qualification",
            "solution_proposee": "",
            "escalade_necessaire": False,
            "infos_manquantes": "logiciel, message d'erreur exact, action avant le probleme",
            "next_question": "Quel est le logiciel concerne, le message d'erreur exact et l'action effectuee avant le probleme ?",
            "collected_info": dict(sess["state"].get("collected_info") or {}),
            "resume_technicien": "",
            "hide_details_in_bubble": False,
            "confidence_score": 0.35,
            "ready_for_assignment": False,
            "tickets_similaires": [],
            "metrics": {
                "nlp_confidence": round(float(nlp_result.get("confidence", 0.35)), 2),
                "rag_similarity": 0.0,
                "type_agreement": 0.0,
                "mode": "QUALIFICATION_EARLY",
                "n_similar": 0,
            },
        }
        sess["state"].update(
            {
                "module": final["module"],
                "type_incident": final["type_incident"],
                "statut": final["statut"],
                "solution_proposee": final["solution_proposee"],
                "escalade_necessaire": final["escalade_necessaire"],
                "confidence_score": final["confidence_score"],
                "tickets_similaires": final["tickets_similaires"],
                "infos_manquantes": final["infos_manquantes"],
                "resume_technicien": final["resume_technicien"],
                "ready_for_assignment": final["ready_for_assignment"],
            }
        )
        sess["history"].append({"role": "user", "content": question})
        sess["history"].append({"role": "assistant", "content": final["reponse"]})
        persist_assistant_turn(
            sess.get("user_id") or (client_profile or {}).get("user_id"),
            sid,
            question,
            final["reponse"],
            sess["state"],
            final.get("confidence_score"),
        )
        return {"session_id": sid, "answer": final["reponse"], "state": final}

    similar = rag.search(
        nlp_result["embedding"],
        k=5,
        module_filter=nlp_result.get("module", ""),
        type_filter=nlp_result.get("type_incident", ""),
        software_filter=nlp_result.get("software", ""),
        version_filter=nlp_result.get("software_version", ""),
        query_text=working_question,
        exclude_ticket_ids=exclude_ticket_ids or [],
    )
    # Filtrer les tickets d'autres modules avant la fusion pour éviter la pollution du type
    confirmed_module = nlp_result.get("module") or (normalize_module_value(tc.get("module", "")) if tc else "")
    if confirmed_module and similar:
        same_mod = [t for t in similar if t.get("module") == confirmed_module]
        high_sim_other = [t for t in similar if t.get("module") != confirmed_module and float(t.get("similarity", 0)) >= 0.50]
        if same_mod:
            similar = same_mod + high_sim_other
    nlp_result = fuse_incident_predictions(nlp_result, similar)
    if explicit_module:
        nlp_result["module"] = explicit_module
        module_scores = dict(nlp_result.get("module_scores", {}) or {})
        module_scores[explicit_module] = max(float(module_scores.get(explicit_module, 0.0)), 1.0)
        nlp_result["module_scores"] = module_scores

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    ollama_url = os.getenv("OLLAMA_URL", "").strip()

    top_similar = similar[0] if similar else {}
    response_mode = sess["state"].get("response_mode", "")

    def _dominant_type(tickets: list[dict], rtype: str, top_n: int = 3) -> bool:
        """Retourne True si rtype domine parmi les top_n tickets similaires."""
        if not tickets:
            return False
        counts = {}
        for t in tickets[:top_n]:
            rt = t.get("response_type", "solution")
            counts[rt] = counts.get(rt, 0) + float(t.get("similarity", 0))
        return counts.get(rtype, 0) >= max(counts.values(), default=0) * 0.7

    client_version_str = (tc.get("version") or "").strip()
    consultant_escalation_requested = is_consultant_escalation_request(question, tc)
    force_version_check = should_force_version_check(question, nlp_result, tc)
    direct_calculation_problem = is_direct_calculation_problem(question, nlp_result)
    allow_version_from_rag = (not client_version_str) or is_version_sensitive_problem(question, nlp_result)
    response_similar = similar if allow_version_from_rag else [
        ticket for ticket in similar if ticket.get("response_type") != "version_check"
    ]
    top_similar = response_similar[0] if response_similar else {}

    if response_mode == "escalade_consultant":
        final = build_escalade_consultant_response(question, nlp_result, similar, sess["state"], tc)
    elif response_mode == "version_check":
        final = build_version_check_response(question, nlp_result, similar, sess["state"], tc)
    elif consultant_escalation_requested:
        final = build_escalade_consultant_response(question, nlp_result, similar, sess["state"], tc)
        sess["state"]["response_mode"] = "escalade_consultant"
    elif force_version_check:
        final = build_version_check_response(question, nlp_result, similar, sess["state"], tc)
    elif not client_version_str and similar and not response_mode:
        # Version inconnue mais tickets ERP trouves → demander la version en priorite
        final = build_version_check_response(question, nlp_result, similar, sess["state"], tc)
        sess["state"]["response_mode"] = "version_check"
    elif _dominant_type(similar, "escalade_consultant"):
        final = build_escalade_consultant_response(question, nlp_result, similar, sess["state"], tc)
        sess["state"]["response_mode"] = "escalade_consultant"
    elif _dominant_type(similar, "version_check") and allow_version_from_rag and not direct_calculation_problem:
        final = build_version_check_response(question, nlp_result, similar, sess["state"], tc)
        if not (tc.get("version") or nlp_result.get("software_version")):
            sess["state"]["response_mode"] = "version_check"
    elif top_similar.get("response_type") == "clarification":
        final = build_rag_only_response_v2(question, nlp_result, response_similar, mode="RAG_CLARIFICATION", session_state=sess["state"])
    elif use_llm and (has_real_anthropic_key(api_key) or ollama_url):
        from llm_engine import build_prompt, call_llm
        from business_logic import apply_business_logic

        try:
            prompt = build_prompt(
                question,
                sess["state"],
                sess["history"][-6:],
                response_similar,
                nlp_result,
                client_profile=profile,
                ticket_context=tc,
            )
            llm_result = call_llm(prompt)
            llm_result["_had_similar_tickets"] = len(response_similar) > 0
            llm_result["_best_similarity"] = response_similar[0]["similarity"] if response_similar else 0.0
            final = apply_business_logic(llm_result, nlp_result, sess["state"])
        except Exception as _llm_err:
            print(f"[LLM ERROR] {type(_llm_err).__name__}: {_llm_err}", flush=True)
            final = build_rag_only_response_v2(question, nlp_result, response_similar, mode="RAG_ONLY_FALLBACK", session_state=sess["state"])
    else:
        final = build_rag_only_response_v2(question, nlp_result, response_similar, mode="RAG_ONLY", session_state=sess["state"])

    sess["history"].append({"role": "user", "content": question})
    sess["history"].append({"role": "assistant", "content": final["reponse"]})
    sess["state"].update(
        {
            "module": final.get("module"),
            "type_incident": final.get("type_incident"),
            "statut": final.get("statut"),
            "collected_info": final.get("collected_info", sess["state"].get("collected_info", {})),
            "awaiting_field": "",
        }
    )
    next_question = final.get("next_question", "")
    if next_question:
        for field in COLLECTION_FIELDS:
            if field["question"] == next_question:
                sess["state"]["awaiting_field"] = field["id"]
                break

    if final.get("ready_for_assignment") or final.get("statut") in ("escalade_technique", "solution_proposee"):
        sess["state"].pop("response_mode", None)

    persist_assistant_turn(
        sess.get("user_id") or (client_profile or {}).get("user_id"),
        sid,
        question,
        final["reponse"],
        sess["state"],
        final.get("confidence_score"),
    )

    return {"session_id": sid, "answer": final["reponse"], "state": {k: v for k, v in final.items() if k != "reponse"}}


def load_reference_maps(db, tickets: list[Ticket]):
    user_ids = sorted({ticket.user_id for ticket in tickets if ticket.user_id is not None})
    logiciel_ids = []
    for ticket in tickets:
        raw = (ticket.logiciel_id or "").strip()
        if raw.isdigit():
            logiciel_ids.append(int(raw))

    users = db.query(User).filter(User.user_id.in_(user_ids)).all() if user_ids else []
    logiciels = db.query(Logiciel).filter(Logiciel.logiciel_id.in_(sorted(set(logiciel_ids)))).all() if logiciel_ids else []

    return (
        {user.user_id: user for user in users},
        {logiciel.logiciel_id: logiciel for logiciel in logiciels},
    )


def software_name_from_ticket(ticket: Ticket, logiciel_map: dict[int, Logiciel]) -> str:
    raw = (ticket.logiciel_id or "").strip()
    if raw.isdigit() and int(raw) in logiciel_map:
        return logiciel_map[int(raw)].nom_logiciel or f"Logiciel {raw}"
    return f"Logiciel {raw}" if raw else ""


def serialize_client_ticket(ticket: Ticket, user_map: dict[int, User], logiciel_map: dict[int, Logiciel]) -> dict:
    user = user_map.get(ticket.user_id)
    logiciel_name = software_name_from_ticket(ticket, logiciel_map)
    module_name = infer_ticket_module(ticket, logiciel_name)
    type_name = infer_ticket_type(ticket, module_name)
    attachment = Path(ticket.attachment_path).name if ticket.attachment_path else ""
    return {
        "id": ticket.ticket_id,
        "clientId": str(ticket.user_id) if ticket.user_id is not None else "client-inconnu",
        "requesterName": full_user_name(user),
        "category": infer_category(module_name, type_name),
        "title": ticket.objet or (ticket.details or "Ticket sans titre")[:80],
        "status": map_client_status(ticket),
        "priority": normalize_priority(ticket.severity),
        "createdAgo": humanize_age(ticket.createDateTime),
        "softwareName": logiciel_name,
        "softwareVersion": ticket.version_id or "",
        "phone": user.phone if user and user.phone else "",
        "description": ticket.details or "",
        "cleanDescription": parse_ticket_conversation(ticket.details or "")[0],
        "conversation": parse_ticket_conversation(ticket.details or "")[1],
        "fileName": attachment,
        "assignedTo": ticket.assigned_to or "",
    }


def serialize_technician_ticket(ticket: Ticket, user_map: dict[int, User], logiciel_map: dict[int, Logiciel]) -> dict:
    user = user_map.get(ticket.user_id)
    logiciel_name = software_name_from_ticket(ticket, logiciel_map)
    module_name = infer_ticket_module(ticket, logiciel_name)
    type_name = infer_ticket_type(ticket, module_name)
    confidence = 0.82 if map_technician_status(ticket) == "resolu" else 0.64
    diagnostics = [
        f"Module detecte : {format_module_label(module_name)}.",
        f"Priorite historique : {normalize_priority(ticket.severity)}.",
    ]
    if ticket.details:
        diagnostics.append(ticket.details[:220])
    checklist = [
        {"label": "Analyser le detail du ticket", "done": bool(ticket.details)},
        {"label": "Verifier l'affectation technicien", "done": bool(ticket.assigned_to)},
        {"label": "Verifier la cloture", "done": bool(ticket.closedDateTime)},
    ]
    notes = [
        {
            "time": (ticket.createDateTime or datetime.utcnow()).strftime("%H:%M"),
            "author": "Base tickets",
            "text": f"Ticket charge depuis public.tickets, etat = {ticket.etat or 'inconnu'}.",
        }
    ]
    return {
        "id": f"TK-{ticket.ticket_id}",
        "client": user.raison_social if user and user.raison_social else "Client non renseigne",
        "site": "Site non renseigne",
        "module": format_module_label(module_name),
        "type": format_type_label(type_name),
        "status": map_technician_status(ticket),
        "priority": normalize_priority(ticket.severity),
        "title": ticket.objet or (ticket.details or "Ticket sans titre")[:80],
        "openedAt": (ticket.createDateTime or datetime.utcnow()).strftime("%H:%M"),
        "requester": full_user_name(user),
        "summary": parse_ticket_conversation(ticket.details or "")[0][:180] or (ticket.details or "")[:180] or "Aucun resume disponible.",
        "conversation": parse_ticket_conversation(ticket.details or "")[1],
        "aiConfidence": confidence,
        "similarCount": 0,
        "lastAction": f"Affecte a {ticket.assigned_to}" if ticket.assigned_to else "Non affecte",
        "diagnostics": diagnostics,
        "checklist": checklist,
        "notes": notes,
    }


def format_delta(current: float, previous: float, suffix: str = "%") -> str:
    if previous == 0:
        if current == 0:
            return "stable vs periode precedente"
        return f"+100.0{suffix} vs periode precedente"
    delta = ((current - previous) / previous) * 100
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.1f}{suffix} vs periode precedente"


def format_hours(value: float) -> str:
    if value <= 0:
        return "0h"
    if value < 1:
        return f"{round(value * 60)}min"
    return f"{value:.1f}h"


def month_label(dt: datetime) -> str:
    labels = ["Jan", "Fev", "Mar", "Avr", "Mai", "Jun", "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]
    return labels[dt.month - 1]


def add_months(month_start: datetime, offset: int) -> datetime:
    month_index = (month_start.month - 1) + offset
    year = month_start.year + month_index // 12
    month = (month_index % 12) + 1
    return month_start.replace(year=year, month=month, day=1)


def build_reports_from_tickets(tickets: list[Ticket], logiciel_map: dict[int, Logiciel]) -> dict:
    now = datetime.utcnow()
    current_start = now - timedelta(days=30)
    previous_start = now - timedelta(days=60)

    def ticket_created(ticket: Ticket) -> datetime:
        return ticket.createDateTime or now

    current = [ticket for ticket in tickets if ticket_created(ticket) >= current_start]
    previous = [ticket for ticket in tickets if previous_start <= ticket_created(ticket) < current_start]

    def technician_status(ticket: Ticket) -> str:
        return map_technician_status(ticket)

    def waiting_count(items: list[Ticket]) -> int:
        return sum(1 for ticket in items if technician_status(ticket) in {"nouveau", "en_attente_client"})

    def resolved_count(items: list[Ticket]) -> int:
        return sum(1 for ticket in items if technician_status(ticket) == "resolu")

    def satisfaction_rate(items: list[Ticket]) -> float:
        if not items:
            return 0.0
        return (resolved_count(items) / len(items)) * 100

    def average_resolution_hours(items: list[Ticket]) -> float:
        resolved_items = [ticket for ticket in items if ticket.createDateTime and ticket.closedDateTime]
        if not resolved_items:
            return 0.0
        total_hours = sum((ticket.closedDateTime - ticket.createDateTime).total_seconds() / 3600 for ticket in resolved_items)
        return total_hours / len(resolved_items)

    resolved_current = resolved_count(current)
    resolved_previous = resolved_count(previous)
    waiting_current = waiting_count(current)
    waiting_previous = waiting_count(previous)
    avg_current = average_resolution_hours(current)
    avg_previous = average_resolution_hours(previous)
    satisfaction_current = satisfaction_rate(current)
    satisfaction_previous = satisfaction_rate(previous)

    monthly_trends = []
    anchor = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for offset in range(3, -1, -1):
        month_start = add_months(anchor, -offset)
        next_month_start = add_months(month_start, 1)
        items = [ticket for ticket in tickets if month_start <= ticket_created(ticket) < next_month_start]
        total = len(items)
        resolved = resolved_count(items)
        monthly_trends.append(
            {
                "month": month_label(month_start),
                "value": f"{resolved}/{total}",
                "percent": round((resolved / total), 2) if total else 0,
            }
        )

    category_counts = Counter()
    source_tickets = current or tickets
    for ticket in source_tickets:
        logiciel_name = software_name_from_ticket(ticket, logiciel_map)
        module_name = infer_ticket_module(ticket, logiciel_name)
        type_name = infer_ticket_type(ticket, module_name)
        category_counts[infer_category(module_name, type_name)] += 1

    total_categories = sum(category_counts.values()) or 1
    tones = ["blue", "green", "purple", "yellow"]
    categories = [
        {
            "label": label,
            "value": value,
            "percent": round(value / total_categories, 2),
            "tone": tones[index % len(tones)],
        }
        for index, (label, value) in enumerate(category_counts.most_common(4))
    ]

    return {
        "kpis": {
            "resolved": {"value": resolved_current, "delta": format_delta(resolved_current, resolved_previous)},
            "avg_resolution": {"value": format_hours(avg_current), "delta": format_delta(avg_current, avg_previous)},
            "satisfaction": {"value": f"{round(satisfaction_current)}%", "delta": format_delta(satisfaction_current, satisfaction_previous)},
            "waiting": {"value": waiting_current, "delta": format_delta(waiting_current, waiting_previous)},
        },
        "monthly_trends": monthly_trends,
        "categories": categories,
        "meta": {"tickets_current_period": len(current), "tickets_total": len(tickets)},
    }


def resolve_user_id(db, requester_name: str) -> int | None:
    clean = requester_name.strip()
    if not clean:
        return None
    parts = clean.split()
    if len(parts) >= 2:
        first_name = parts[0]
        last_name = " ".join(parts[1:])
        user = (
            db.query(User)
            .filter(func.lower(User.first_name) == first_name.lower(), func.lower(User.last_name) == last_name.lower())
            .first()
        )
        if user:
            return user.user_id
    user = db.query(User).filter(func.lower(User.username) == clean.lower()).first()
    return user.user_id if user else None


def next_user_id(db) -> int:
    return (db.query(func.max(User.user_id)).scalar() or 0) + 1


def resolve_logiciel_id(db, software_name: str) -> str | None:
    clean = software_name.strip()
    if not clean:
        return None
    logiciel = db.query(Logiciel).filter(func.lower(Logiciel.nom_logiciel) == clean.lower()).first()
    if logiciel:
        return str(logiciel.logiciel_id)
    logiciel = db.query(Logiciel).filter(func.lower(Logiciel.nom_logiciel).like(f"%{clean.lower()}%")).first()
    return str(logiciel.logiciel_id) if logiciel else None


def split_full_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def slugify_company(company: str) -> str:
    chars = []
    for char in company.lower().strip():
        if char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "-":
            chars.append("-")
    return "".join(chars).strip("-") or "client"


def extract_bearer_token(authorization: str | None) -> str:
    header = (authorization or "").strip()
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentification requise.")
    return header[7:].strip()


def get_authenticated_user(authorization: str | None, expected_role: str | None = None) -> User:
    token = extract_bearer_token(authorization)
    payload = decode_access_token(token)
    role = payload.get("role", "")
    if expected_role and role != expected_role:
        raise HTTPException(status_code=403, detail="Acces non autorise pour ce role.")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token invalide.")

    try:
        with SessionLocal() as db:
            user = db.query(User).filter(User.user_id == user_id).first()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Echec verification session: {exc}")

    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable.")
    return user


@app.get("/health")
def health():
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if has_real_anthropic_key(anthropic_key):
        llm_mode = "anthropic"
    elif os.getenv("OLLAMA_URL", "").strip():
        llm_mode = "ollama"
    else:
        llm_mode = "rag_only"

    return {
        "status": "ok",
        "rag_tickets": rag.stats().get("total", 0),
        "llm_mode": llm_mode,
    }


@app.post("/search")
def search(req: ChatRequest, authorization: str | None = Header(default=None)):
    auth_user = get_authenticated_user(authorization)
    profile = load_client_profile(auth_user) if auth_user else None
    tc = req.ticket_context if req.ticket_context else None
    return run_assistant(
        req.question,
        req.session_id,
        req.exclude_ticket_ids,
        req.use_llm,
        client_profile=profile,
        ticket_context=tc,
    )


@app.post("/auth/client/register")
def register_client(payload: ClientRegistrationCreate):
    full_name = payload.full_name.strip()
    email = payload.email.strip().lower()
    phone = payload.phone.strip()
    company = payload.company.strip()
    password = payload.password

    if not full_name or not email or not phone or not company or not password:
        raise HTTPException(status_code=400, detail="Tous les champs sont obligatoires.")
    if len(phone) < 8:
        raise HTTPException(status_code=400, detail="Numero de telephone invalide.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au moins 8 caracteres.")

    first_name, last_name = split_full_name(full_name)
    username = email.split("@")[0]

    try:
        with SessionLocal() as db:
            existing_email = db.query(User).filter(func.lower(User.email) == email).first()
            if existing_email:
                raise HTTPException(status_code=409, detail="Un compte existe deja avec cet email.")

            user = User(
                user_id=next_user_id(db),
                email=email,
                etat=2,
                phone=phone,
                first_name=first_name or full_name,
                last_name=last_name,
                password=hash_password(password),
                username=username,
                raison_social=company,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Creation impossible. Un compte client avec ces informations existe deja.",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Echec creation compte client. Veuillez reessayer.")

    return {
        "message": "Compte client cree avec succes.",
        "user": {
            "user_id": user.user_id,
            "full_name": full_user_name(user),
            "email": user.email,
            "phone": user.phone,
            "company": user.raison_social or "",
            "etat": user.etat,
            "client_id": f"client-{slugify_company(company)}-{user.user_id}",
        },
    }


@app.post("/auth/technician/register")
def register_technician(payload: TechnicianRegistrationCreate):
    full_name = payload.full_name.strip()
    email = payload.email.strip().lower()
    phone = payload.phone.strip()
    technician_id = payload.technician_id.strip().upper()
    specialty = payload.specialty.strip()
    password = payload.password

    if not full_name or not email or not phone or not technician_id or not specialty or not password:
        raise HTTPException(status_code=400, detail="Tous les champs sont obligatoires.")
    if len(phone) < 8:
        raise HTTPException(status_code=400, detail="Numero de telephone invalide.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au moins 8 caracteres.")

    parts = full_name.split()
    first_name = parts[0] if parts else full_name
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    try:
        with SessionLocal() as db:
            existing_email = db.query(User).filter(func.lower(User.email) == email).first()
            if existing_email:
                raise HTTPException(status_code=409, detail="Un compte existe deja pour cet email.")

            existing_username = db.query(User).filter(func.lower(User.username) == technician_id.lower()).first()
            if existing_username:
                raise HTTPException(status_code=409, detail="Cet identifiant technicien est deja utilise.")

            user = User(
                user_id=next_user_id(db),
                email=email,
                etat=1,
                phone=phone,
                first_name=first_name or full_name,
                last_name=last_name,
                password=hash_password(password),
                username=technician_id,
                raison_social=specialty,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Creation impossible. Un technicien avec cet email ou cet identifiant existe deja.",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Echec creation compte technicien. Veuillez reessayer.")

    return {
        "message": "Compte technicien cree avec succes.",
        "user": {
            "user_id": user.user_id,
            "full_name": full_user_name(user),
            "email": user.email,
            "phone": user.phone,
            "specialty": specialty,
            "etat": user.etat,
            "role": "technicien",
            "technician_id": technician_id,
        },
    }


@app.post("/auth/login")
def login(payload: LoginRequest):
    email = payload.email.strip().lower()
    password = payload.password
    role = payload.role.strip().lower()

    if role not in {"client", "technicien"}:
        raise HTTPException(status_code=400, detail="Role invalide.")

    try:
        with SessionLocal() as db:
            user = db.query(User).filter(func.lower(User.email) == email).first()
            if not user or not verify_password(password, user.password):
                raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect.")

            user_role = "client" if user.etat == 2 else "technicien"
            if user_role != role:
                raise HTTPException(status_code=403, detail="Ce compte ne correspond pas au role selectionne.")

            if not is_password_hashed(user.password):
                user.password = hash_password(password)
            user.currentAccessDate = datetime.utcnow()
            db.commit()
            db.refresh(user)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Echec connexion: {exc}")

    return {
        "message": "Connexion reussie.",
        "access_token": issue_access_token(user, user_role),
        "token_type": "bearer",
        "user": {
            "user_id": user.user_id,
            "full_name": full_user_name(user),
            "email": user.email or "",
            "phone": user.phone or "",
            "company": user.raison_social or "",
            "etat": user.etat,
            "role": user_role,
            "client_id": f"client-{slugify_company(user.raison_social or user.username or 'client')}-{user.user_id}",
            "username": user.username or "",
        },
    }


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@app.post("/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest):
    addr = (payload.email or "").strip().lower()
    if not addr:
        raise HTTPException(status_code=400, detail="L'adresse email est obligatoire.")

    try:
        with SessionLocal() as db:
            user = db.query(User).filter(func.lower(User.email) == addr).first()
            if not user:
                # Réponse générique — ne révèle pas si le compte existe
                return {"message": "Si un compte est associé à cette adresse, un lien de réinitialisation a été envoyé."}

            # Lire les données nécessaires pendant que la session est ouverte
            recipient_name = full_user_name(user)

            # Invalider les anciens tokens non utilisés pour cet utilisateur
            db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == user.user_id,
                PasswordResetToken.used == 0,
            ).update({"used": 1})

            # Générer un token sécurisé
            raw_token = secrets.token_urlsafe(40)
            expiry = datetime.utcnow() + timedelta(hours=1)
            reset_token = PasswordResetToken(
                user_id=user.user_id,
                token=raw_token,
                expires_at=expiry,
                used=0,
            )
            db.add(reset_token)
            db.commit()

        # Envoyer l'email après avoir fermé la session DB
        send_reset_email(addr, recipient_name, raw_token)

    except HTTPException:
        raise
    except RuntimeError as exc:
        print(traceback.format_exc())
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Erreur inattendue : {exc}")

    return {"message": "Un lien de réinitialisation a été envoyé à votre adresse email."}


@app.post("/auth/reset-password")
def reset_password(payload: ResetPasswordRequest):
    token_str = (payload.token or "").strip()
    new_pw = (payload.new_password or "").strip()

    if not token_str:
        raise HTTPException(status_code=400, detail="Token manquant.")
    if len(new_pw) < 8:
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au moins 8 caractères.")

    now = datetime.utcnow()
    try:
        with SessionLocal() as db:
            reset_tok = db.query(PasswordResetToken).filter(
                PasswordResetToken.token == token_str,
                PasswordResetToken.used == 0,
                PasswordResetToken.expires_at > now,
            ).first()

            if not reset_tok:
                raise HTTPException(status_code=400, detail="Lien invalide ou expiré. Veuillez refaire une demande.")

            user = db.query(User).filter(User.user_id == reset_tok.user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

            # Hacher le nouveau mot de passe avec le même algorithme que l'inscription
            user.password = hash_password(new_pw)
            reset_tok.used = 1
            db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Erreur inattendue : {exc}")

    return {"message": "Mot de passe réinitialisé avec succès. Vous pouvez maintenant vous connecter."}


@app.get("/client/profile")
def get_client_profile(authorization: str | None = Header(default=None)):
    """Retourne le profil complet du client connecté : infos, logiciels, tickets récents."""
    user = get_authenticated_user(authorization, expected_role="client")
    return load_client_profile(user)


class ClientLogicielCreate(BaseModel):
    logiciel_id: int
    version: str = ""


@app.post("/client/logiciels")
def add_client_logiciel(payload: ClientLogicielCreate, authorization: str | None = Header(default=None)):
    """Associe un logiciel à un client (admin ou client lui-même)."""
    user = get_authenticated_user(authorization, expected_role="client")
    try:
        with SessionLocal() as db:
            existing = (
                db.query(ClientLogiciel)
                .filter(ClientLogiciel.user_id == user.user_id, ClientLogiciel.logiciel_id == payload.logiciel_id)
                .first()
            )
            if existing:
                existing.version = payload.version
                existing.actif = 1
            else:
                db.add(ClientLogiciel(
                    user_id=user.user_id,
                    logiciel_id=payload.logiciel_id,
                    version=payload.version,
                    actif=1,
                ))
            db.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"message": "Logiciel associe avec succes."}


@app.get("/logiciels")
def list_logiciels(authorization: str | None = Header(default=None)):
    """Retourne la liste de tous les logiciels disponibles."""
    get_authenticated_user(authorization)
    try:
        with SessionLocal() as db:
            rows = db.query(Logiciel).order_by(Logiciel.nom_logiciel).all()
            return [{"logiciel_id": r.logiciel_id, "nom": r.nom_logiciel} for r in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/client/chat-history")
def get_client_chat_history(authorization: str | None = Header(default=None)):
    user = get_authenticated_user(authorization, expected_role="client")
    try:
        with SessionLocal() as db:
            msgs = (
                db.query(Message)
                .filter(Message.user_id == user.user_id)
                .order_by(Message.timestamp.desc().nullslast(), Message.id.desc())
                .limit(300)
                .all()
            )
            tickets = (
                db.query(Ticket)
                .filter(Ticket.user_id == user.user_id)
                .order_by(Ticket.createDateTime.asc())
                .all()
            )
            messages = [message_to_history_item(m) for m in sort_messages_ascending(msgs)]
            ticket_list = [
                {
                    "id": t.ticket_id,
                    "title": t.objet or "",
                    "module": t.module or "",
                    "details": (t.details or "")[:400],
                    "logiciel": t.logiciel_id or "",
                    "version": t.version_id or "",
                    "priority": t.severity or "normale",
                    "timestamp": t.createDateTime.isoformat() if t.createDateTime else None,
                    "etat": t.etat or "",
                }
                for t in tickets
            ]
        return {"messages": messages, "tickets": ticket_list}
    except Exception:
        return {"messages": [], "tickets": []}


@app.get("/client/tickets")
def get_client_tickets(authorization: str | None = Header(default=None)):
    user = get_authenticated_user(authorization, expected_role="client")
    try:
        with SessionLocal() as db:
            tickets = (
                db.query(Ticket)
                .filter(Ticket.user_id == user.user_id)
                .order_by(Ticket.createDateTime.desc().nullslast(), Ticket.ticket_id.desc())
                .all()
            )
            user_map, logiciel_map = load_reference_maps(db, tickets)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Connexion base impossible: {exc}")

    serialized = [serialize_client_ticket(ticket, user_map, logiciel_map) for ticket in tickets]
    stats = {
        "total": len(serialized),
        "enAttente": sum(1 for ticket in serialized if ticket["status"] == "en_attente"),
        "resolus": sum(1 for ticket in serialized if ticket["status"] == "resolu"),
        "ouverts": sum(1 for ticket in serialized if ticket["status"] == "ouvert"),
        "attribues": sum(1 for ticket in serialized if ticket["status"] == "attribue"),
    }
    return {"tickets": serialized, "stats": stats}


@app.post("/client/tickets")
def create_client_ticket(payload: ClientTicketCreate, authorization: str | None = Header(default=None)):
    auth_user = get_authenticated_user(authorization, expected_role="client")
    profile = load_client_profile(auth_user)
    # Le ticket_context contient tout ce que le client a saisi dans le formulaire
    ticket_context = {
        "title": payload.title,
        "module": payload.module,
        "software": payload.software_name,
        "version": payload.software_version,
        "priority": payload.priority,
        "description": payload.description,
        "fonctionnalites": payload.fonctionnalites,
    }
    # On envoie la description comme premier message — le chatbot connaît déjà module/logiciel/version
    fonc_suffix = f"\nFonctionnalites utilisees: {payload.fonctionnalites.strip()}" if payload.fonctionnalites.strip() else ""
    first_message = (payload.description or payload.title) + fonc_suffix
    assistant_result = run_assistant(
        first_message,
        client_profile=profile,
        ticket_context=ticket_context,
    )
    now = datetime.utcnow()

    try:
        with SessionLocal() as db:
            next_id = (db.query(func.max(Ticket.ticket_id)).scalar() or 0) + 1
            user_id = auth_user.user_id or resolve_user_id(db, payload.requester_name)
            logiciel_id = resolve_logiciel_id(db, payload.software_name)

            record = Ticket(
                ticket_id=next_id,
                etat="ouvert",
                objet=payload.title,
                severity=payload.priority.capitalize(),
                user_id=user_id,
                createDateTime=now,
                attachment_path=None,
                assigned_to=None,
                closed_by=None,
                closedDateTime=None,
                assignedDateTime=None,
                logiciel_id=logiciel_id,
                version_id=payload.software_version or None,
                details=payload.description + (f"\n\nFonctionnalites: {payload.fonctionnalites.strip()}" if payload.fonctionnalites.strip() else ""),
                module=payload.module,
                assistant_session_id=assistant_result.get("session_id") or None,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            user_map, logiciel_map = load_reference_maps(db, [record])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Echec insertion ticket: {exc}")

    return {
        "ticket": serialize_client_ticket(record, user_map, logiciel_map),
        "technician_ticket": serialize_technician_ticket(record, user_map, logiciel_map),
        "assistant": assistant_result,
    }


@app.delete("/client/tickets/{ticket_id}")
def delete_client_ticket(ticket_id: int, authorization: str | None = Header(default=None)):
    """Supprime un ticket appartenant au client connecté (uniquement si non affecté)."""
    auth_user = get_authenticated_user(authorization, expected_role="client")
    try:
        with SessionLocal() as db:
            ticket = (
                db.query(Ticket)
                .filter(Ticket.ticket_id == ticket_id, Ticket.user_id == auth_user.user_id)
                .first()
            )
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket introuvable.")
            if ticket.assigned_to:
                raise HTTPException(status_code=403, detail="Impossible de supprimer un ticket deja affecte a un technicien.")
            db.delete(ticket)
            db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"message": f"Ticket #{ticket_id} supprime avec succes."}


@app.post("/client/tickets/assign")
def assign_client_ticket(payload: TicketAssignmentRequest, authorization: str | None = Header(default=None)):
    auth_user = get_authenticated_user(authorization, expected_role="client")
    now = datetime.utcnow()

    try:
        with SessionLocal() as db:
            ticket = (
                db.query(Ticket)
                .filter(Ticket.ticket_id == payload.ticket_id, Ticket.user_id == auth_user.user_id)
                .first()
            )
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket introuvable.")
            if ticket.assigned_to:
                user_map, logiciel_map = load_reference_maps(db, [ticket])
                return {
                    "message": "Le ticket est deja assigne a un technicien.",
                    "ticket": serialize_client_ticket(ticket, user_map, logiciel_map),
                    "technician_ticket": serialize_technician_ticket(ticket, user_map, logiciel_map),
                }

            technician = pick_auto_technician(db)
            if not technician:
                raise HTTPException(status_code=404, detail="Aucun technicien disponible pour l'affectation.")

            ticket.assigned_to = full_user_name(technician)
            ticket.assignedDateTime = now
            ticket.etat = "attribue"
            db.commit()
            db.refresh(ticket)
            user_map, logiciel_map = load_reference_maps(db, [ticket])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Echec affectation ticket: {exc}")

    return {
        "message": f"Ticket #{ticket.ticket_id} assigne a {ticket.assigned_to}.",
        "ticket": serialize_client_ticket(ticket, user_map, logiciel_map),
        "technician_ticket": serialize_technician_ticket(ticket, user_map, logiciel_map),
    }


class TechnicianTakeOverRequest(BaseModel):
    ticket_id: int
    response: str = ""


class UpdatePriorityRequest(BaseModel):
    ticket_id: int
    priority: str


class ClientReplyRequest(BaseModel):
    message: str


class TechnicianMessageRequest(BaseModel):
    message: str


@app.patch("/technician/tickets/priority")
def update_ticket_priority(payload: UpdatePriorityRequest, authorization: str | None = Header(default=None)):
    get_authenticated_user(authorization, expected_role="technicien")
    valid = {"normale", "faible", "basse", "moyenne", "haute", "critique", "urgente"}
    if payload.priority.lower() not in valid:
        raise HTTPException(status_code=400, detail="Priorite invalide.")
    try:
        with SessionLocal() as db:
            ticket = db.query(Ticket).filter(Ticket.ticket_id == payload.ticket_id).first()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket introuvable.")
            ticket.severity = payload.priority.capitalize()
            db.commit()
            db.refresh(ticket)
            user_map, logiciel_map = load_reference_maps(db, [ticket])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "message": f"Priorite mise a jour.",
        "ticket": serialize_client_ticket(ticket, user_map, logiciel_map),
        "technician_ticket": serialize_technician_ticket(ticket, user_map, logiciel_map),
    }


@app.post("/technician/tickets/takeover")
def technician_takeover(payload: TechnicianTakeOverRequest, authorization: str | None = Header(default=None)):
    auth_user = get_authenticated_user(authorization, expected_role="technicien")
    now = datetime.utcnow()
    try:
        with SessionLocal() as db:
            ticket = db.query(Ticket).filter(Ticket.ticket_id == payload.ticket_id).first()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket introuvable.")
            ticket.assigned_to = full_user_name(auth_user)
            ticket.assignedDateTime = now
            ticket.etat = "attribue"
            response_text = payload.response.strip()
            if response_text:
                existing = ticket.details or ""
                ticket.details = existing + f"\n\n[Technicien {full_user_name(auth_user)}] {response_text}"
                if ticket.user_id:
                    notif = Notification(
                        user_id=ticket.user_id,
                        ticket_id=ticket.ticket_id,
                        ticket_title=ticket.objet,
                        sender_name=full_user_name(auth_user),
                        message_preview=response_text[:200],
                        is_read=0,
                        created_at=now,
                    )
                    db.add(notif)
            db.commit()
            db.refresh(ticket)
            user_map, logiciel_map = load_reference_maps(db, [ticket])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "message": f"Ticket #{ticket.ticket_id} pris en charge par {ticket.assigned_to}.",
        "technician_ticket": serialize_technician_ticket(ticket, user_map, logiciel_map),
    }


@app.post("/client/tickets/{ticket_id}/reply")
def client_ticket_reply(ticket_id: int, payload: ClientReplyRequest, authorization: str | None = Header(default=None)):
    auth_user = get_authenticated_user(authorization, expected_role="client")
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Le message ne peut pas etre vide.")
    try:
        with SessionLocal() as db:
            ticket = (
                db.query(Ticket)
                .filter(Ticket.ticket_id == ticket_id, Ticket.user_id == auth_user.user_id)
                .first()
            )
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket introuvable.")
            existing = ticket.details or ""
            ticket.details = existing + f"\n\n[Client {full_user_name(auth_user)}] {message}"
            db.commit()
            db.refresh(ticket)
            user_map, logiciel_map = load_reference_maps(db, [ticket])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "message": "Message envoye avec succes.",
        "ticket": serialize_client_ticket(ticket, user_map, logiciel_map),
    }


@app.get("/technician/tickets")
def get_technician_tickets(authorization: str | None = Header(default=None)):
    get_authenticated_user(authorization, expected_role="technicien")
    try:
        with SessionLocal() as db:
            tickets = db.query(Ticket).order_by(Ticket.createDateTime.desc().nullslast(), Ticket.ticket_id.desc()).all()
            user_map, logiciel_map = load_reference_maps(db, tickets)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Connexion base impossible: {exc}")

    serialized = [serialize_technician_ticket(ticket, user_map, logiciel_map) for ticket in tickets]
    stats = {
        "total": len(serialized),
        "critiques": sum(1 for ticket in serialized if ticket["priority"] == "critique"),
        "enCours": sum(1 for ticket in serialized if ticket["status"] == "en_cours"),
        "resolus": sum(1 for ticket in serialized if ticket["status"] == "resolu"),
    }
    return {"tickets": serialized, "stats": stats}


@app.get("/reports/summary")
def reports_summary(authorization: str | None = Header(default=None)):
    get_authenticated_user(authorization, expected_role="technicien")
    try:
        with SessionLocal() as db:
            tickets = db.query(Ticket).order_by(Ticket.createDateTime.desc().nullslast(), Ticket.ticket_id.desc()).all()
            _, logiciel_map = load_reference_maps(db, tickets)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Connexion base impossible: {exc}")
    return build_reports_from_tickets(tickets, logiciel_map)


@app.get("/client/conversations")
def get_client_conversations(authorization: str | None = Header(default=None)):
    """Retourne toutes les conversations du client, groupées par session, avec le ticket associé."""
    user = get_authenticated_user(authorization, expected_role="client")
    try:
        with SessionLocal() as db:
            msgs = (
                db.query(Message)
                .filter(Message.user_id == user.user_id)
                .order_by(Message.timestamp.desc().nullslast(), Message.id.desc())
                .limit(600)
                .all()
            )
            tickets = (
                db.query(Ticket)
                .filter(Ticket.user_id == user.user_id)
                .order_by(Ticket.createDateTime.asc())
                .all()
            )
            _, logiciel_map = load_reference_maps(db, tickets)
    except Exception:
        return {"conversations": []}

    msgs = sort_messages_ascending(msgs)
    ticket_by_session = {t.assistant_session_id: t for t in tickets if t.assistant_session_id}

    GAP_SECONDS = 30 * 60
    sessions_map: dict[str, list] = {}
    no_session_msgs = []
    for msg in msgs:
        if msg.session_id:
            sessions_map.setdefault(msg.session_id, []).append(msg)
        else:
            no_session_msgs.append(msg)

    if no_session_msgs:
        group_idx = 0
        current_key = f"time-group-{group_idx}"
        sessions_map[current_key] = [no_session_msgs[0]]
        for m in no_session_msgs[1:]:
            prev = sessions_map[current_key][-1]
            if (
                prev.timestamp
                and m.timestamp
                and (m.timestamp - prev.timestamp).total_seconds() > GAP_SECONDS
            ):
                group_idx += 1
                current_key = f"time-group-{group_idx}"
                sessions_map[current_key] = []
            sessions_map[current_key].append(m)

    conversations = []
    for sid, group in sessions_map.items():
        last_ts = group[-1].timestamp
        associated_ticket = ticket_by_session.get(sid)
        if not associated_ticket and group[0].timestamp:
            first_ts = group[0].timestamp
            best_diff = float("inf")
            for t in tickets:
                if t.createDateTime:
                    diff = abs((t.createDateTime - first_ts).total_seconds())
                    if diff < 3600 and diff < best_diff:
                        best_diff = diff
                        associated_ticket = t

        ticket_data = None
        if associated_ticket:
            logiciel_name = software_name_from_ticket(associated_ticket, logiciel_map)
            ticket_data = {
                "id": associated_ticket.ticket_id,
                "title": associated_ticket.objet or "",
                "module": associated_ticket.module or "",
                "description": parse_ticket_conversation(associated_ticket.details or "")[0][:300],
                "softwareName": logiciel_name,
                "softwareVersion": associated_ticket.version_id or "",
                "priority": normalize_priority(associated_ticket.severity),
                "status": map_client_status(associated_ticket),
                "createdAt": associated_ticket.createDateTime.isoformat() if associated_ticket.createDateTime else None,
            }

        messages_data = [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            }
            for m in group
        ]

        preview_msg = next((m for m in reversed(group) if m.role == "assistant"), None)
        preview = (preview_msg.content[:120] if preview_msg else "") or ""
        first_user = next((m for m in group if m.role in ("user", "utilisateur")), None)
        title = (
            (associated_ticket.objet if associated_ticket else None)
            or (first_user.content[:72] if first_user else None)
            or "Conversation"
        )

        conversations.append({
            "id": sid,
            "session_id": sid,
            "title": title,
            "preview": preview,
            "messages": messages_data,
            "ticket": ticket_data,
            "last_message_at": last_ts.isoformat() if last_ts else None,
            "updated_at": last_ts.isoformat() if last_ts else None,
        })

    conversations.sort(key=lambda c: c["last_message_at"] or "", reverse=True)
    return {"conversations": conversations}


# ─────────────────────────── NOTIFICATIONS ────────────────────────────────

@app.get("/notifications")
def get_notifications(authorization: str | None = Header(default=None)):
    auth_user = get_authenticated_user(authorization, expected_role="client")
    try:
        with SessionLocal() as db:
            notifs = (
                db.query(Notification)
                .filter(Notification.user_id == auth_user.user_id)
                .order_by(Notification.created_at.desc().nullslast())
                .limit(50)
                .all()
            )
        return {
            "notifications": [
                {
                    "id": n.id,
                    "ticketId": n.ticket_id,
                    "ticketTitle": n.ticket_title,
                    "senderName": n.sender_name,
                    "messagePreview": n.message_preview,
                    "isRead": bool(n.is_read),
                    "createdAt": n.created_at.isoformat() if n.created_at else None,
                }
                for n in notifs
            ],
            "unreadCount": sum(1 for n in notifs if not n.is_read),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.patch("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, authorization: str | None = Header(default=None)):
    auth_user = get_authenticated_user(authorization, expected_role="client")
    try:
        with SessionLocal() as db:
            notif = db.query(Notification).filter(
                Notification.id == notification_id,
                Notification.user_id == auth_user.user_id,
            ).first()
            if not notif:
                raise HTTPException(status_code=404, detail="Notification introuvable.")
            notif.is_read = 1
            db.commit()
        return {"message": "Notification marquée comme lue."}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/notifications/read-all")
def mark_all_notifications_read(authorization: str | None = Header(default=None)):
    auth_user = get_authenticated_user(authorization, expected_role="client")
    try:
        with SessionLocal() as db:
            db.query(Notification).filter(
                Notification.user_id == auth_user.user_id,
                Notification.is_read == 0,
            ).update({"is_read": 1})
            db.commit()
        return {"message": "Toutes les notifications marquées comme lues."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/technician/tickets/{ticket_id}/message")
def technician_send_message(
    ticket_id: int,
    payload: TechnicianMessageRequest,
    authorization: str | None = Header(default=None),
):
    auth_user = get_authenticated_user(authorization, expected_role="technicien")
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Le message ne peut pas être vide.")
    now = datetime.utcnow()
    try:
        with SessionLocal() as db:
            ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket introuvable.")
            existing = ticket.details or ""
            ticket.details = existing + f"\n\n[Technicien {full_user_name(auth_user)}] {message}"
            if ticket.user_id:
                notif = Notification(
                    user_id=ticket.user_id,
                    ticket_id=ticket.ticket_id,
                    ticket_title=ticket.objet,
                    sender_name=full_user_name(auth_user),
                    message_preview=message[:200],
                    is_read=0,
                    created_at=now,
                )
                db.add(notif)
            db.commit()
        return {"message": "Message envoyé avec succès."}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/rag_stats")
def rag_stats():
    return rag.stats()


@app.get("/session/{session_id}")
def get_session(session_id: str, authorization: str | None = Header(default=None)):
    user = get_authenticated_user(authorization, expected_role="client")
    persisted = load_persisted_session(session_id, user.user_id, limit=300)
    if persisted["history"]:
        return persisted

    memory_session = sessions.get(session_id)
    if memory_session and (not memory_session.get("user_id") or memory_session.get("user_id") == user.user_id):
        return {
            "history": memory_session.get("history", []),
            "state": memory_session.get("state", fresh_session_state()),
        }
    return persisted
