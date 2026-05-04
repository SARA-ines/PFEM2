"""
Import tickets from an Excel file into PostgreSQL and ticket_metadata.json.

Common usage:
    python import_excel.py --file "C:\\path\\tickets.xlsx" --dry-run
    python import_excel.py --file "C:\\path\\tickets.xlsx"
    python import_excel.py --file "C:\\path\\tickets.xlsx" --replace-existing
"""

import argparse
from datetime import datetime
import json
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent))

from database import SessionLocal, Ticket


LOGICIEL_MAP = {
    "bigfinance": 1,
    "big finance": 1,
    "bigpaie": 2,
    "big paie": 2,
    "biggestion": 3,
    "big gestion": 3,
    "winstock": 3,
    "biggrh": 4,
    "big grh": 4,
    "biggt": 5,
}


EXCEL_COLUMNS = {
    "ticket_id": ["ticket_id", "id", "Ticket ID", "ticket"],
    "etat": ["etat", "etat_ticket", "statut", "status"],
    "objet": ["objet", "titre", "title", "subject"],
    "severity": ["severity", "priorite", "priority"],
    "user_id": ["user_id", "client_id", "client"],
    "createDateTime": ["createDateTime", "created_at", "date_creation", "date_creation_ticket"],
    "attachment_path": ["uve.attachment_path", "attachment_path", "attachment", "pj"],
    "closed_by": ["closed_by"],
    "closedDateTime": ["closedDateTime", "closed_at"],
    "assigned_to": ["assigned_to"],
    "assignedDateTime": ["assignedDateTime", "assigned_at"],
    "logiciel_id": ["logiciel_id", "software_id"],
    "logiciel": ["logiciel", "logiciel_nom", "software", "application"],
    "version_id": ["version_id", "version", "Version"],
    "details": ["details", "description", "probleme"],
    "module": ["module", "fonctionnalite"],
    "reformulation": ["Reformulation Ticket", "reformulation", "probleme_reformule"],
    "solution": ["Solution", "solution", "resolution"],
    "user_1": ["user_1", "user1", "consultant1"],
    "response_1": ["response_1", "reponse_1", "rep1"],
    "user_2": ["user_2", "user2"],
    "response_2": ["response_2", "reponse_2", "rep2"],
    "user_3": ["user_3", "user3"],
    "response_3": ["response_3", "reponse_3", "rep3"],
}


def normalize(text: str) -> str:
    if not text:
        return ""
    text = str(text).lower().strip()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def clean_cell(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    text = str(value).strip()
    if text.lower() in ("", "nan", "none", "nat"):
        return ""
    return text


def parse_int_cell(value) -> int | None:
    text = clean_cell(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_text_id(value) -> str | None:
    text = clean_cell(value)
    if not text:
        return None
    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass
    return text


def parse_datetime_cell(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    df_cols_normalized = {normalize(c): c for c in df.columns}
    for candidate in candidates:
        found = df_cols_normalized.get(normalize(candidate))
        if found:
            return found
    return None


def detect_column_map(df: pd.DataFrame) -> dict:
    col_map = {}
    for field, candidates in EXCEL_COLUMNS.items():
        found = find_column(df, candidates)
        if found:
            col_map[field] = found
    return col_map


def row_value(row, col_map: dict, field: str):
    column = col_map.get(field)
    if not column:
        return None
    return row.get(column, None)


def resolve_logiciel_id(logiciel_name: str) -> int | None:
    if not logiciel_name or logiciel_name.strip() in ("", "nan", "#NOM!", "#NOM?"):
        return None
    normalized = normalize(logiciel_name)
    for key, lid in LOGICIEL_MAP.items():
        if key in normalized:
            return lid
    return None


def resolve_logiciel_from_row(row, col_map: dict) -> str | None:
    logiciel_id = parse_text_id(row_value(row, col_map, "logiciel_id"))
    if logiciel_id:
        return logiciel_id
    logiciel_name = clean_cell(row_value(row, col_map, "logiciel"))
    resolved = resolve_logiciel_id(logiciel_name)
    return str(resolved) if resolved else None


def build_ticket_values(row, col_map: dict, ticket_id_override: int | None = None) -> tuple[int | None, dict]:
    ticket_id = ticket_id_override if ticket_id_override is not None else parse_int_cell(row_value(row, col_map, "ticket_id"))
    details = clean_cell(row_value(row, col_map, "details"))
    reformulation = clean_cell(row_value(row, col_map, "reformulation"))
    attachment = clean_cell(row_value(row, col_map, "attachment_path"))
    if attachment in ("##", "#"):
        attachment = ""

    values = {
        "etat": clean_cell(row_value(row, col_map, "etat")) or None,
        "objet": clean_cell(row_value(row, col_map, "objet")) or None,
        "severity": clean_cell(row_value(row, col_map, "severity")) or None,
        "user_id": parse_int_cell(row_value(row, col_map, "user_id")),
        "createDateTime": parse_datetime_cell(row_value(row, col_map, "createDateTime")),
        "attachment_path": attachment or None,
        "closed_by": clean_cell(row_value(row, col_map, "closed_by")) or None,
        "closedDateTime": parse_datetime_cell(row_value(row, col_map, "closedDateTime")),
        "assigned_to": clean_cell(row_value(row, col_map, "assigned_to")) or None,
        "assignedDateTime": parse_datetime_cell(row_value(row, col_map, "assignedDateTime")),
        "logiciel_id": resolve_logiciel_from_row(row, col_map),
        "version_id": parse_text_id(row_value(row, col_map, "version_id")),
        "details": reformulation or details or None,
        "module": clean_cell(row_value(row, col_map, "module")) or None,
    }
    return ticket_id, values


def apply_non_empty_values(ticket: Ticket, values: dict):
    for field, value in values.items():
        if value is not None:
            setattr(ticket, field, value)


def backup_file(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{path}.bak-{stamp}"
    shutil.copy2(path, backup_path)
    return backup_path


def read_metadata_ids(metadata_path: str) -> set[int]:
    if not os.path.exists(metadata_path):
        return set()
    with open(metadata_path, "r", encoding="utf-8") as f:
        items = json.load(f)
    return {item.get("ticket_id") for item in items if isinstance(item.get("ticket_id"), int)}


def read_metadata_items(metadata_path: str) -> list[dict]:
    if not os.path.exists(metadata_path):
        return []
    with open(metadata_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_existing_remapped_zero_id(row, col_map: dict, metadata_items: list[dict]) -> int | None:
    objet = clean_cell(row_value(row, col_map, "objet"))
    details = clean_cell(row_value(row, col_map, "details"))
    reformulation = clean_cell(row_value(row, col_map, "reformulation"))
    probleme = reformulation or details
    solution = clean_cell(row_value(row, col_map, "solution"))

    for item in metadata_items:
        item_id = item.get("ticket_id")
        if not isinstance(item_id, int) or item_id <= 0:
            continue
        if clean_cell(item.get("objet")) != objet:
            continue
        if solution and clean_cell(item.get("solution")) != solution:
            continue
        if probleme and clean_cell(item.get("probleme")) != probleme:
            continue
        return item_id

    try:
        with SessionLocal() as db:
            result = db.execute(
                text(
                    "SELECT ticket_id FROM tickets "
                    "WHERE objet = :objet AND details = :details "
                    "ORDER BY ticket_id DESC LIMIT 1"
                ),
                {"objet": objet, "details": probleme},
            )
            found = result.scalar()
            return int(found) if found else None
    except Exception:
        return None


def build_zero_ticket_id_remap(
    df: pd.DataFrame,
    col_map: dict,
    metadata_path: str,
    allow_ticket_zero: bool = False,
) -> dict[int, int]:
    if allow_ticket_zero:
        return {}

    metadata_items = read_metadata_items(metadata_path)
    used_ids = {item.get("ticket_id") for item in metadata_items if isinstance(item.get("ticket_id"), int)}
    for _, row in df.iterrows():
        ticket_id = parse_int_cell(row_value(row, col_map, "ticket_id"))
        if ticket_id and ticket_id > 0:
            used_ids.add(ticket_id)

    try:
        with SessionLocal() as db:
            result = db.execute(text("SELECT ticket_id FROM tickets WHERE ticket_id IS NOT NULL"))
            used_ids.update(row[0] for row in result if row[0] and row[0] > 0)
    except Exception:
        pass
    next_id = (max(used_ids) if used_ids else 0) + 1
    remap = {}
    for index, row in df.iterrows():
        ticket_id = parse_int_cell(row_value(row, col_map, "ticket_id"))
        if ticket_id == 0:
            existing_id = find_existing_remapped_zero_id(row, col_map, metadata_items)
            if existing_id:
                remap[index] = existing_id
                used_ids.add(existing_id)
                continue
            while next_id in used_ids:
                next_id += 1
            remap[index] = next_id
            used_ids.add(next_id)
            next_id += 1
    return remap


def build_full_text(row_data: dict) -> str:
    objet = row_data.get("objet", "")
    probleme = row_data.get("reformulation") or row_data.get("details", "")
    solution = row_data.get("solution", "")

    conversation_parts = []
    for i in range(1, 4):
        user = row_data.get(f"user_{i}", "")
        response = row_data.get(f"response_{i}", "")
        if user:
            conversation_parts.append(user)
        if response:
            conversation_parts.append(response)

    parts = []
    if objet:
        parts.append(f"Objet: {objet}")
    if probleme:
        parts.append(f"Probleme: {probleme}")
    if conversation_parts:
        parts.append("Conversation: " + " || ".join(conversation_parts))
    if solution:
        parts.append(f"Solution: {solution}")
    return "\n".join(parts)


def extract_problem_from_full_text(full_text: str) -> str:
    match = re.search(r"Probl(?:e|è|Ã¨)me:\s*(.*?)(?:\nConversation:|\nSolution:|$)", full_text or "", re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_conversation_from_full_text(full_text: str) -> str:
    match = re.search(r"Conversation:\s*(.*?)(?:\nSolution:|$)", full_text or "", re.DOTALL)
    return match.group(1).strip() if match else ""


def import_to_postgres(
    df: pd.DataFrame,
    col_map: dict,
    dry_run: bool = False,
    replace_existing: bool = False,
    allow_ticket_zero: bool = False,
    ticket_id_overrides: dict[int, int] | None = None,
) -> tuple[int, int, int, int]:
    db = SessionLocal()
    inserted = 0
    updated = 0
    skipped = 0
    errors = 0

    try:
        result = db.execute(text("SELECT ticket_id FROM tickets"))
        existing_ids = {row[0] for row in result}
    except Exception:
        existing_ids = set()

    ticket_id_overrides = ticket_id_overrides or {}

    for line_number, row in df.iterrows():
        try:
            ticket_id, values = build_ticket_values(row, col_map, ticket_id_overrides.get(line_number))
            if ticket_id is None:
                skipped += 1
                continue
            if ticket_id == 0 and not allow_ticket_zero:
                skipped += 1
                continue

            if ticket_id in existing_ids:
                if not replace_existing:
                    skipped += 1
                    continue
                if not dry_run:
                    ticket = db.get(Ticket, ticket_id)
                    if ticket is not None:
                        apply_non_empty_values(ticket, values)
                        db.commit()
                updated += 1
                continue

            if not dry_run:
                db.add(Ticket(ticket_id=ticket_id, **values))
                db.commit()
            inserted += 1
            existing_ids.add(ticket_id)

        except Exception as exc:
            db.rollback()
            errors += 1
            print(f"  [ERREUR] Ligne Excel {line_number + 2}: {exc}")

    db.close()
    return inserted, updated, skipped, errors


def build_metadata_entries(
    df: pd.DataFrame,
    col_map: dict,
    allow_ticket_zero: bool = False,
    ticket_id_overrides: dict[int, int] | None = None,
) -> list[dict]:
    entries = []
    ticket_id_overrides = ticket_id_overrides or {}

    for index, row in df.iterrows():
        solution = clean_cell(row_value(row, col_map, "solution"))
        if not solution:
            continue

        ticket_id = ticket_id_overrides.get(index) or parse_int_cell(row_value(row, col_map, "ticket_id"))
        if ticket_id is None:
            continue
        if ticket_id == 0 and not allow_ticket_zero:
            continue

        row_data = {
            "ticket_id": ticket_id,
            "objet": clean_cell(row_value(row, col_map, "objet")),
            "details": clean_cell(row_value(row, col_map, "details")),
            "reformulation": clean_cell(row_value(row, col_map, "reformulation")),
            "solution": solution,
            "module": clean_cell(row_value(row, col_map, "module")),
            "logiciel": clean_cell(row_value(row, col_map, "logiciel")),
            "version": parse_text_id(row_value(row, col_map, "version_id")) or "",
        }
        for i in range(1, 4):
            row_data[f"user_{i}"] = clean_cell(row_value(row, col_map, f"user_{i}"))
            row_data[f"response_{i}"] = clean_cell(row_value(row, col_map, f"response_{i}"))

        entries.append(
            {
                "ticket_id": ticket_id,
                "db_id": ticket_id,
                "objet": row_data["objet"],
                "probleme": row_data["reformulation"] or row_data["details"],
                "solution": solution,
                "module": row_data["module"],
                "logiciel_id": resolve_logiciel_from_row(row, col_map),
                "software": row_data["logiciel"],
                "version": row_data["version"],
                "full_text": build_full_text(row_data),
            }
        )
    return entries


def update_metadata_json(
    new_entries: list[dict],
    metadata_path: str,
    replace_existing: bool = False,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    existing = []
    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            existing = json.load(f)

    entries_by_id = {entry["ticket_id"]: entry for entry in new_entries}
    added = 0
    replaced = 0

    if replace_existing:
        used_ids = set()
        updated_existing = []
        for item in existing:
            ticket_id = item.get("ticket_id")
            if ticket_id in entries_by_id:
                updated_existing.append(entries_by_id[ticket_id])
                used_ids.add(ticket_id)
                replaced += 1
            else:
                updated_existing.append(item)
        existing = updated_existing

        for entry in new_entries:
            if entry["ticket_id"] not in used_ids:
                existing.append(entry)
                added += 1
    else:
        existing_ids = {item.get("ticket_id") for item in existing}
        for entry in new_entries:
            if entry["ticket_id"] not in existing_ids:
                existing.append(entry)
                existing_ids.add(entry["ticket_id"])
                added += 1

    if dry_run:
        return added, replaced, len(existing)

    backup = backup_file(metadata_path)
    if backup:
        print(f"  Backup metadata cree: {backup}")

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    return added, replaced, len(existing)


def upsert_ticket_knowledge(entries: list[dict], dry_run: bool = False) -> tuple[int, int]:
    if not entries:
        return 0, 0

    db = SessionLocal()
    existing_ids = {
        row[0]
        for row in db.execute(text("SELECT ticket_id FROM ticket_knowledge WHERE ticket_id IS NOT NULL"))
    }
    added = 0
    updated = 0

    statement = text(
        """
        INSERT INTO ticket_knowledge (
            ticket_id, objet, problem_text, conversation_text, final_solution,
            logiciel_id, version_id, module, full_text
        )
        VALUES (
            :ticket_id, :objet, :problem_text, :conversation_text, :final_solution,
            :logiciel_id, :version_id, :module, :full_text
        )
        ON CONFLICT (ticket_id) DO UPDATE SET
            objet = EXCLUDED.objet,
            problem_text = EXCLUDED.problem_text,
            conversation_text = EXCLUDED.conversation_text,
            final_solution = EXCLUDED.final_solution,
            logiciel_id = EXCLUDED.logiciel_id,
            version_id = EXCLUDED.version_id,
            module = EXCLUDED.module,
            full_text = EXCLUDED.full_text
        """
    )

    try:
        for entry in entries:
            ticket_id = entry.get("ticket_id")
            if ticket_id is None:
                continue
            full_text = entry.get("full_text", "") or ""
            params = {
                "ticket_id": ticket_id,
                "objet": entry.get("objet", "") or "",
                "problem_text": entry.get("probleme") or extract_problem_from_full_text(full_text),
                "conversation_text": entry.get("conversation") or extract_conversation_from_full_text(full_text),
                "final_solution": entry.get("solution", "") or "",
                "logiciel_id": entry.get("logiciel_id") or entry.get("software") or "",
                "version_id": entry.get("version") or "",
                "module": entry.get("module") or "",
                "full_text": full_text,
            }
            if ticket_id in existing_ids:
                updated += 1
            else:
                added += 1
                existing_ids.add(ticket_id)
            if not dry_run:
                db.execute(statement, params)
        if not dry_run:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return added, updated


def rebuild_rag_index():
    print("\nReconstruction de l'index FAISS...")
    try:
        import importlib
        import rag_engine

        importlib.reload(rag_engine)
        print("Index FAISS reconstruit avec succes.")
    except Exception as exc:
        print(f"Impossible de reconstruire l'index automatiquement: {exc}")
        print("Relance le serveur FastAPI pour recharger l'index.")


def main():
    parser = argparse.ArgumentParser(description="Import tickets Excel vers PostgreSQL + RAG")
    parser.add_argument("--file", required=True, help="Chemin vers le fichier Excel (.xlsx ou .xls)")
    parser.add_argument("--sheet", default=0, help="Nom ou index de la feuille Excel (defaut: 0)")
    parser.add_argument("--rebuild-rag", action="store_true", help="Reconstruire l'index FAISS apres l'import")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans ecriture")
    parser.add_argument("--metadata-only", action="store_true", help="Met a jour seulement ticket_metadata.json")
    parser.add_argument("--replace-existing", action="store_true", help="Remplace les ticket_id deja existants")
    parser.add_argument("--allow-ticket-zero", action="store_true", help="Autorise ticket_id=0")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"[ERREUR] Fichier introuvable: {args.file}")
        sys.exit(1)

    print(f"\n=== Import tickets depuis: {args.file} ===")
    if args.dry_run:
        print("[MODE SIMULATION - aucune ecriture]")
    if args.replace_existing:
        print("[MODE REMPLACEMENT - les anciens ticket_id seront mis a jour]")

    try:
        sheet = int(args.sheet) if str(args.sheet).isdigit() else args.sheet
        df = pd.read_excel(args.file, sheet_name=sheet)
        print(f"\nFichier lu: {len(df)} lignes, {len(df.columns)} colonnes")
        print(f"Colonnes detectees: {list(df.columns)}")
    except Exception as exc:
        print(f"[ERREUR] Impossible de lire le fichier Excel: {exc}")
        sys.exit(1)

    col_map = detect_column_map(df)
    print(f"\nMapping colonnes detecte: {col_map}")

    if "ticket_id" not in col_map:
        print("[ERREUR] Colonne ticket_id introuvable.")
        print(f"Colonnes disponibles: {list(df.columns)}")
        sys.exit(1)

    metadata_path = os.path.join(os.path.dirname(__file__), "ticket_metadata.json")
    if not os.path.exists(metadata_path):
        metadata_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ticket_metadata.json"))

    ticket_id_overrides = build_zero_ticket_id_remap(
        df,
        col_map,
        metadata_path,
        allow_ticket_zero=args.allow_ticket_zero,
    )
    if ticket_id_overrides:
        mappings = ", ".join(f"ligne Excel {index + 2}: 0 -> {new_id}" for index, new_id in ticket_id_overrides.items())
        print(f"\nRemapping ticket_id=0: {mappings}")

    if not args.metadata_only:
        print("\n--- Import vers PostgreSQL ---")
        inserted, updated, skipped, errors = import_to_postgres(
            df,
            col_map,
            dry_run=args.dry_run,
            replace_existing=args.replace_existing,
            allow_ticket_zero=args.allow_ticket_zero,
            ticket_id_overrides=ticket_id_overrides,
        )
        print(f"  Inseres: {inserted} | Mis a jour: {updated} | Ignores: {skipped} | Erreurs: {errors}")

    print("\n--- Mise a jour ticket_metadata.json ---")
    new_entries = build_metadata_entries(
        df,
        col_map,
        allow_ticket_zero=args.allow_ticket_zero,
        ticket_id_overrides=ticket_id_overrides,
    )
    print(f"  Tickets avec solution dans l'Excel: {len(new_entries)}")

    added, replaced, total = update_metadata_json(
        new_entries,
        metadata_path,
        replace_existing=args.replace_existing,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(f"  [SIMULATION] Ajoutes: {added} | Remplaces: {replaced} | Total apres import: {total}")
    else:
        print(f"  Ajoutes: {added} | Remplaces: {replaced} | Total dans metadata: {total}")

    print("\n--- Synchronisation PostgreSQL ticket_knowledge ---")
    knowledge_added, knowledge_updated = upsert_ticket_knowledge(new_entries, dry_run=args.dry_run)
    if args.dry_run:
        print(f"  [SIMULATION] Ajoutes: {knowledge_added} | Mis a jour: {knowledge_updated}")
    else:
        print(f"  Ajoutes: {knowledge_added} | Mis a jour: {knowledge_updated}")

    if args.rebuild_rag and not args.dry_run:
        rebuild_rag_index()

    print("\n=== Import termine ===")
    if not args.rebuild_rag:
        print("ATTENTION: Relance le serveur FastAPI pour que l'IA prenne en compte les changements.")


if __name__ == "__main__":
    main()
