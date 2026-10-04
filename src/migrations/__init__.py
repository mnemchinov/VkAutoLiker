"""Миграции SQLite через PRAGMA user_version.

Каждая миграция — отдельный файл mNNN_description.py с функцией upgrade(conn).
run_migrations проверяет текущую версию и применяет все необходимые миграции по порядку.

Версии:
  0 — пустая БД или старая БД до миграций.
  1 — созданы таблицы (m001_create_tables).
  2 — добавлена колонка is_auto (m002_add_is_auto).
  3 — добавлена колонка status (m003_add_status).
"""

import sqlite3

from migrations import m001_create_tables, m002_add_is_auto, m003_add_status

LATEST_VERSION = 3

_MIGRATIONS = [
    m001_create_tables.upgrade,
    m002_add_is_auto.upgrade,
    m003_add_status.upgrade,
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """Применяет все миграции до LATEST_VERSION через PRAGMA user_version.

    PRAGMA user_version хранит целое число — текущую версию схемы.
    Каждая миграция выполняется в порядке номеров, version инкрементируется.
    Все миграции в одной транзакции: commit после каждой.
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version in range(current, LATEST_VERSION):
        _MIGRATIONS[version](conn)
        conn.execute(f"PRAGMA user_version = {version + 1}")
        conn.commit()
