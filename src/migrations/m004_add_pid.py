"""Миграция 004: добавление колонки pid в sessions (детекция зомби-сессий).

Зомби-сессия: процесс умер жёстко (SIGKILL/сбой питания) после start_session
и до end_session — finally не выполнился, и строка осталась «идущей»
(ended_at NULL) навсегда. Строка хранит pid процесса-создателя: строка с
ended_at NULL и мёртвым pid — зомби, её закрывает close_zombie_sessions().
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Добавляет колонку pid в sessions, если её нет."""
    cursor = conn.execute("PRAGMA table_info(sessions)")
    columns = [row[1] for row in cursor.fetchall()]
    if "pid" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN pid INTEGER")
