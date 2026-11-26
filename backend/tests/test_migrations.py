"""Alembic upgrade and downgrade smoke tests on an isolated temporary database."""

import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command


def test_initial_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "finassist_migration_test.db"
    ini_path = Path("alembic.ini")
    if not ini_path.exists():
        ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(ini_path.parent / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}"
    )

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        upgraded_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert {
        "users",
        "documents",
        "document_pages",
        "document_chunks",
        "chat_sessions",
        "chat_messages",
        "alembic_version",
    } <= upgraded_tables
    with sqlite3.connect(database_path) as connection:
        document_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(documents)")
        }
        message_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(chat_messages)")
        }
    assert {"indexed_chunk_count", "embedding_model", "indexed_at"} <= document_columns
    assert {
        "sources",
        "model_name",
        "retrieved_chunks_count",
        "retrieval_time_ms",
        "generation_time_ms",
        "retrieval",
        "evidence_status",
        "verification_status",
        "confidence_score",
        "verification_metadata",
        "confidence_metadata",
        "retrieval_attempts",
    } <= message_columns

    command.downgrade(config, "base")
    with sqlite3.connect(database_path) as connection:
        remaining_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert remaining_tables == {"alembic_version"}
