from datetime import datetime
import json

from sqlalchemy.orm import Session

from database import ConversationSession, Message

DEFAULT_STATE = {
    "probleme_resume": "",
    "module": "",
    "type_incident": "",
    "niveau_urgence": "moyen",
    "bloquant": False,
    "infos_manquantes": "",
    "statut": "qualification",
    "solution_proposee": "",
    "escalade_necessaire": False,
    "technicien_assigne": "",
}


def _state_from_db(raw_state) -> dict:
    if isinstance(raw_state, dict):
        return dict(raw_state)
    if isinstance(raw_state, str) and raw_state.strip():
        try:
            loaded = json.loads(raw_state)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _state_to_db(state: dict) -> dict:
    return json.loads(json.dumps(state or {}, ensure_ascii=False, default=str))


def get_or_create_session(session_id: str, db: Session) -> ConversationSession:
    session = db.query(ConversationSession).filter_by(session_id=session_id).first()
    if not session:
        session = ConversationSession(session_id=session_id, state=_state_to_db(DEFAULT_STATE.copy()))
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def get_history(session_id: str, db: Session, limit: int = 10) -> list[dict]:
    messages = (
        db.query(Message)
        .filter_by(session_id=session_id)
        .order_by(Message.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [{"role": m.role, "content": m.content} for m in reversed(messages)]


def save_message(session_id: str, role: str, content: str, db: Session, confidence: float | None = None):
    msg = Message(
        session_id=session_id,
        role=role,
        content=content,
        confidence=confidence,
        timestamp=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()


def update_state(session_id: str, updates: dict, db: Session):
    session = get_or_create_session(session_id, db)
    state = _state_from_db(session.state)
    for key, value in updates.items():
        if value is not None and value != "":
            state[key] = value
    session.state = _state_to_db(state)
    db.commit()
    db.refresh(session)
    return state


def build_context(session_id: str, nlp_result: dict, db: Session) -> dict:
    session = get_or_create_session(session_id, db)
    state = _state_from_db(session.state)

    if nlp_result.get("module"):
        state["module"] = nlp_result["module"]
    if nlp_result.get("type_incident"):
        state["type_incident"] = nlp_result["type_incident"]
    if nlp_result.get("intention") == "escalade":
        state["bloquant"] = True
        state["niveau_urgence"] = "haut"

    if not state.get("probleme_resume") and nlp_result.get("type_incident"):
        module_part = f" sur {state['module']}" if state.get("module") else ""
        state["probleme_resume"] = f"Incident {nlp_result['type_incident']}{module_part}"

    return state
