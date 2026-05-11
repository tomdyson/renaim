from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Photo:
    id: int
    root_path: str
    original_path: str
    current_path: str
    original_name: str
    size: int
    mtime_ns: int
    status: str


@dataclass(frozen=True)
class Suggestion:
    id: int
    photo_id: int
    current_path: str
    model: str
    response: str
    slug: str
    proposed_path: str
    status: str


@dataclass(frozen=True)
class Rename:
    id: int
    batch_id: int
    photo_id: int
    suggestion_id: int | None
    old_path: str
    new_path: str
    old_atime_ns: int
    old_mtime_ns: int
    status: str


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.init()

    def close(self) -> None:
        self.conn.close()

    def init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY,
                root_path TEXT NOT NULL,
                original_path TEXT NOT NULL,
                current_path TEXT NOT NULL UNIQUE,
                original_name TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'indexed',
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY,
                photo_id INTEGER NOT NULL REFERENCES photos(id),
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                prompt TEXT NOT NULL,
                response TEXT NOT NULL,
                slug TEXT NOT NULL,
                proposed_name TEXT NOT NULL,
                proposed_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY,
                action TEXT NOT NULL,
                root_path TEXT NOT NULL,
                model TEXT,
                dry_run INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS renames (
                id INTEGER PRIMARY KEY,
                batch_id INTEGER NOT NULL REFERENCES batches(id),
                photo_id INTEGER NOT NULL REFERENCES photos(id),
                suggestion_id INTEGER REFERENCES suggestions(id),
                old_path TEXT NOT NULL,
                new_path TEXT NOT NULL,
                old_size INTEGER NOT NULL,
                old_atime_ns INTEGER NOT NULL,
                old_mtime_ns INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'applied',
                error TEXT,
                applied_at TEXT NOT NULL,
                undone_at TEXT,
                undo_batch_id INTEGER REFERENCES batches(id)
            );

            CREATE INDEX IF NOT EXISTS idx_photos_root ON photos(root_path);
            CREATE INDEX IF NOT EXISTS idx_suggestions_photo ON suggestions(photo_id);
            CREATE INDEX IF NOT EXISTS idx_renames_batch ON renames(batch_id);
            """
        )
        self.repair_undone_suggestions()
        self.conn.commit()

    def repair_undone_suggestions(self) -> int:
        """Reopen suggestions from older DBs where undo left them applied."""
        cursor = self.conn.execute(
            """
            UPDATE suggestions
               SET status = 'pending', updated_at = ?
             WHERE status = 'applied'
               AND id IN (
                   SELECT r.suggestion_id
                     FROM renames r
                     JOIN photos p ON p.id = r.photo_id
                    WHERE r.status = 'undone'
                      AND r.suggestion_id IS NOT NULL
                      AND p.status != 'renamed'
               )
            """,
            (now(),),
        )
        return cursor.rowcount

    def upsert_photo(self, root: Path, path: Path) -> Photo:
        stat = path.stat()
        current_path = str(path.resolve())
        timestamp = now()
        existing = self.conn.execute(
            "SELECT * FROM photos WHERE current_path = ?",
            (current_path,),
        ).fetchone()

        if existing:
            self.conn.execute(
                """
                UPDATE photos
                   SET root_path = ?, size = ?, mtime_ns = ?, status = CASE
                         WHEN status = 'missing' THEN 'indexed'
                         ELSE status
                       END,
                       updated_at = ?
                 WHERE id = ?
                """,
                (str(root.resolve()), stat.st_size, stat.st_mtime_ns, timestamp, existing["id"]),
            )
            self.conn.commit()
            return self.get_photo(existing["id"])

        cursor = self.conn.execute(
            """
            INSERT INTO photos (
                root_path, original_path, current_path, original_name,
                size, mtime_ns, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'indexed', ?, ?)
            """,
            (
                str(root.resolve()),
                current_path,
                current_path,
                path.name,
                stat.st_size,
                stat.st_mtime_ns,
                timestamp,
                timestamp,
            ),
        )
        self.conn.commit()
        return self.get_photo(cursor.lastrowid)

    def get_photo(self, photo_id: int) -> Photo:
        row = self.conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if not row:
            raise KeyError(photo_id)
        return Photo(**{key: row[key] for key in Photo.__dataclass_fields__})

    def photos_for_suggestions(self, root: Path, force: bool = False) -> list[Photo]:
        root_path = str(root.resolve())
        if force:
            rows = self.conn.execute(
                "SELECT * FROM photos WHERE root_path = ? AND status != 'renamed' ORDER BY current_path",
                (root_path,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT p.*
                  FROM photos p
                 WHERE p.root_path = ?
                   AND p.status != 'renamed'
                   AND NOT EXISTS (
                       SELECT 1 FROM suggestions s
                        WHERE s.photo_id = p.id
                          AND s.status IN ('pending', 'approved')
                   )
                 ORDER BY p.current_path
                """,
                (root_path,),
            ).fetchall()
        return [Photo(**{key: row[key] for key in Photo.__dataclass_fields__}) for row in rows]

    def add_suggestion(
        self,
        photo_id: int,
        model: str,
        prompt_version: str,
        prompt: str,
        response: str,
        slug: str,
        proposed_name: str,
        proposed_path: str,
    ) -> int:
        timestamp = now()
        cursor = self.conn.execute(
            """
            INSERT INTO suggestions (
                photo_id, model, prompt_version, prompt, response, slug,
                proposed_name, proposed_path, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                photo_id,
                model,
                prompt_version,
                prompt,
                response,
                slug,
                proposed_name,
                proposed_path,
                timestamp,
                timestamp,
            ),
        )
        self.conn.execute("UPDATE photos SET status = 'suggested', updated_at = ? WHERE id = ?", (timestamp, photo_id))
        self.conn.commit()
        return int(cursor.lastrowid)

    def set_photo_error(self, photo_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE photos SET status = 'error', last_error = ?, updated_at = ? WHERE id = ?",
            (error[:1000], now(), photo_id),
        )
        self.conn.commit()

    def latest_suggestions(self, root: Path, approved_only: bool = False) -> list[Suggestion]:
        statuses = ("approved",) if approved_only else ("pending", "approved")
        placeholders = ",".join("?" for _ in statuses)
        rows = self.conn.execute(
            f"""
            SELECT s.*, p.current_path
              FROM suggestions s
              JOIN photos p ON p.id = s.photo_id
             WHERE p.root_path = ?
               AND p.status != 'renamed'
               AND s.status IN ({placeholders})
               AND s.id = (
                   SELECT MAX(s2.id)
                     FROM suggestions s2
                    WHERE s2.photo_id = s.photo_id
                      AND s2.status IN ({placeholders})
               )
             ORDER BY p.current_path
            """,
            (str(root.resolve()), *statuses, *statuses),
        ).fetchall()
        return [
            Suggestion(
                id=row["id"],
                photo_id=row["photo_id"],
                current_path=row["current_path"],
                model=row["model"],
                response=row["response"],
                slug=row["slug"],
                proposed_path=row["proposed_path"],
                status=row["status"],
            )
            for row in rows
        ]

    def update_suggestion(self, suggestion_id: int, slug: str, proposed_name: str, proposed_path: str, status: str) -> None:
        self.conn.execute(
            """
            UPDATE suggestions
               SET slug = ?, proposed_name = ?, proposed_path = ?, status = ?, updated_at = ?
             WHERE id = ?
            """,
            (slug, proposed_name, proposed_path, status, now(), suggestion_id),
        )
        self.conn.commit()

    def create_batch(self, action: str, root: Path, model: str | None = None, dry_run: bool = False, notes: str | None = None) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO batches (action, root_path, model, dry_run, notes, started_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (action, str(root.resolve()), model, int(dry_run), notes, now()),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish_batch(self, batch_id: int) -> None:
        self.conn.execute("UPDATE batches SET finished_at = ? WHERE id = ?", (now(), batch_id))
        self.conn.commit()

    def record_rename(
        self,
        batch_id: int,
        photo_id: int,
        suggestion_id: int,
        old_path: Path,
        new_path: Path,
        old_size: int,
        old_atime_ns: int,
        old_mtime_ns: int,
    ) -> None:
        timestamp = now()
        self.conn.execute(
            """
            INSERT INTO renames (
                batch_id, photo_id, suggestion_id, old_path, new_path, old_size,
                old_atime_ns, old_mtime_ns, status, applied_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?)
            """,
            (
                batch_id,
                photo_id,
                suggestion_id,
                str(old_path),
                str(new_path),
                old_size,
                old_atime_ns,
                old_mtime_ns,
                timestamp,
            ),
        )
        self.conn.execute(
            "UPDATE photos SET current_path = ?, status = 'renamed', updated_at = ? WHERE id = ?",
            (str(new_path), timestamp, photo_id),
        )
        self.conn.execute(
            "UPDATE suggestions SET status = 'applied', updated_at = ? WHERE id = ?",
            (timestamp, suggestion_id),
        )
        self.conn.commit()

    def applied_renames(self, batch_id: int) -> list[Rename]:
        rows = self.conn.execute(
            """
            SELECT id, batch_id, photo_id, suggestion_id, old_path, new_path, old_atime_ns, old_mtime_ns, status
              FROM renames
             WHERE batch_id = ? AND status = 'applied'
             ORDER BY id DESC
            """,
            (batch_id,),
        ).fetchall()
        return [Rename(**{key: row[key] for key in Rename.__dataclass_fields__}) for row in rows]

    def mark_undone(
        self,
        rename_id: int,
        undo_batch_id: int,
        restored_path: Path,
        photo_id: int,
        suggestion_id: int | None = None,
    ) -> None:
        timestamp = now()
        self.conn.execute(
            "UPDATE renames SET status = 'undone', undone_at = ?, undo_batch_id = ? WHERE id = ?",
            (timestamp, undo_batch_id, rename_id),
        )
        self.conn.execute(
            "UPDATE photos SET current_path = ?, status = 'indexed', updated_at = ? WHERE id = ?",
            (str(restored_path), timestamp, photo_id),
        )
        if suggestion_id is not None:
            self.conn.execute(
                "UPDATE suggestions SET status = 'pending', updated_at = ? WHERE id = ? AND status = 'applied'",
                (timestamp, suggestion_id),
            )
        self.conn.commit()

    def latest_apply_batch_id(self) -> int | None:
        row = self.conn.execute(
            """
            SELECT b.id
              FROM batches b
             WHERE b.action = 'apply'
               AND b.dry_run = 0
               AND EXISTS (
                   SELECT 1
                     FROM renames r
                    WHERE r.batch_id = b.id
                      AND r.status = 'applied'
               )
             ORDER BY b.id DESC
             LIMIT 1
            """
        ).fetchone()
        return int(row["id"]) if row else None

    def batches(self, limit: int = 20) -> Iterable[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT b.*,
                   (SELECT COUNT(*) FROM renames r WHERE r.batch_id = b.id) AS rename_count,
                   (SELECT COUNT(*) FROM renames r WHERE r.batch_id = b.id AND r.status = 'applied') AS active_count
              FROM batches b
             ORDER BY b.id DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
