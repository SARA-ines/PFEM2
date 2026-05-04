from datetime import datetime
import os

from sqlalchemy import Column, Date, DateTime, Float, Integer, JSON, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:123456789@localhost/postgres",
)

if DATABASE_URL.startswith("postgresql://") and "+pg8000" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+pg8000://", 1)

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


class ConversationSession(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, nullable=True)
    state = Column(JSON, nullable=True)


class Message(Base):
    __tablename__ = "messages_chat"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role = Column("expediteur", String, nullable=False)
    content = Column("message", Text, nullable=False)
    timestamp = Column("date_creation", DateTime, default=datetime.utcnow)
    confidence = Column(Float, nullable=True)
    user_id = Column(Integer, nullable=True)
    session_id = Column(String, nullable=True)
    email = Column(String, nullable=True)
    state_code = Column("etat", Integer, nullable=True)
    phone = Column(String, nullable=True)


class Ticket(Base):
    __tablename__ = "tickets"

    ticket_id = Column(Integer, primary_key=True)
    etat = Column(String, nullable=True)
    objet = Column(String, nullable=True)
    severity = Column(String, nullable=True)
    user_id = Column(Integer, nullable=True)
    createDateTime = Column("createDateTime", DateTime, nullable=True)
    attachment_path = Column(String, nullable=True)
    assigned_to = Column(String, nullable=True)
    closed_by = Column(String, nullable=True)
    closedDateTime = Column("closedDateTime", DateTime, nullable=True)
    assignedDateTime = Column("assignedDateTime", DateTime, nullable=True)
    logiciel_id = Column(String, nullable=True)
    version_id = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    module = Column(String, nullable=True)
    assistant_session_id = Column(String, nullable=True)


class TicketKnowledge(Base):
    __tablename__ = "ticket_knowledge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, unique=True, nullable=True)
    objet = Column(Text, nullable=True)
    problem_text = Column(Text, nullable=True)
    conversation_text = Column(Text, nullable=True)
    final_solution = Column(Text, nullable=True)
    logiciel_id = Column(String, nullable=True)
    version_id = Column(String, nullable=True)
    module = Column(String, nullable=True)
    full_text = Column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    email = Column(String, nullable=True)
    etat = Column(Integer, nullable=True)
    phone = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    password = Column(String, nullable=True)
    username = Column(String, nullable=True)
    dateExpiration = Column("dateExpiration", Date, nullable=True)
    currentAccessDate = Column("currentAccessDate", DateTime, nullable=True)
    lastAccessDate = Column("lastAccessDate", DateTime, nullable=True)
    structure_id = Column(Integer, nullable=True)
    raison_social = Column(String, nullable=True)


class Logiciel(Base):
    __tablename__ = "logiciel"

    logiciel_id = Column(Integer, primary_key=True)
    nom_logiciel = Column(String, nullable=True)


class LogicielVersion(Base):
    __tablename__ = "logiciel_version"

    logiciel_version_id = Column(Integer, primary_key=True)
    logiciel_id = Column(Integer, nullable=True)
    version_id = Column(Integer, nullable=True)


class ClientLogiciel(Base):
    """Associe un client aux logiciels qu'il utilise avec leur version."""
    __tablename__ = "client_logiciel"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    logiciel_id = Column(Integer, nullable=False)
    version = Column(String, nullable=True)
    date_installation = Column(Date, nullable=True)
    actif = Column(Integer, default=1)


Base.metadata.create_all(engine)

with engine.begin() as conn:
    conn.exec_driver_sql(
        "ALTER TABLE messages_chat ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION"
    )
    conn.exec_driver_sql(
        "ALTER TABLE messages_chat ADD COLUMN IF NOT EXISTS session_id VARCHAR(100)"
    )
    conn.exec_driver_sql(
        "ALTER TABLE messages_chat ADD COLUMN IF NOT EXISTS user_id INTEGER"
    )
    conn.exec_driver_sql(
        "ALTER TABLE messages_chat ADD COLUMN IF NOT EXISTS email VARCHAR(255)"
    )
    conn.exec_driver_sql(
        "ALTER TABLE messages_chat ADD COLUMN IF NOT EXISTS etat INTEGER"
    )
    conn.exec_driver_sql(
        "ALTER TABLE messages_chat ADD COLUMN IF NOT EXISTS phone VARCHAR(50)"
    )
    conn.exec_driver_sql(
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS assistant_session_id VARCHAR(100)"
    )
    conn.exec_driver_sql(
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP"
    )
    conn.exec_driver_sql(
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id INTEGER"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_messages_chat_user_session ON messages_chat (user_id, session_id)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_messages_chat_session ON messages_chat (session_id)"
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
