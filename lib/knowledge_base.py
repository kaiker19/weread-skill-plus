#!/usr/bin/env python3
"""
knowledge_base.py — SQLite knowledge store for weread-skill-plus

Tables:
  books       — book metadata + reading state
  highlights  — personal highlights  (/book/bookmarklist)
  reviews     — personal annotations (/review/list/mine)
  concepts    — LLM-extracted concept tags (cross-book connections)
  summaries   — cached daily/book summaries
  sync_state  — incremental sync cursors

Default DB path: ~/.weread-skill-plus/knowledge.db
Override via env: WEREAD_KB_PATH
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional


# ── Path ───────────────────────────────────────────────────────────────────

_SKILL_ROOT = Path(__file__).parent.parent  # lib/ → project root
DEFAULT_DB_PATH = _SKILL_ROOT / "data" / "knowledge.db"


def data_dir() -> Path:
    """数据目录的单一来源：key / 配置 / db 全走这里。
    WEREAD_DATA_DIR 环境变量优先——打包后由 launcher 落到 ~/.weread-skill-plus/
    （Path.home() 跨 Mac/Win 通用）；未设则项目根 data/，普通用法行为不变。"""
    env = os.environ.get("WEREAD_DATA_DIR")
    d = Path(env).expanduser() if env else _SKILL_ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_db_path() -> Path:
    env = os.environ.get("WEREAD_KB_PATH")
    if env:
        return Path(env).expanduser()
    return data_dir() / "knowledge.db"


_SSL_CTX = None


def ssl_context():
    """所有 urllib HTTPS 请求共用的 SSL context（缓存一次）。
    优先用 certifi 的 CA bundle——修非系统 Python(Homebrew/python.org/pyenv)
    连 i.weread.qq.com 时 CERTIFICATE_VERIFY_FAILED（它们用 OpenSSL，不带根证书库；
    系统 /usr/bin/python3 走 LibreSSL+钥匙串才无此问题，curl 同样走系统证书）。
    没装 certifi 则回退系统默认 context（系统 python 本就能连）。"""
    global _SSL_CTX
    if _SSL_CTX is None:
        import ssl
        try:
            import certifi
            _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            _SSL_CTX = ssl.create_default_context()
    return _SSL_CTX


@contextmanager
def _conn(db_path: Path = None):
    if db_path is None:
        db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema ─────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    book_id         TEXT PRIMARY KEY,
    title           TEXT NOT NULL DEFAULT '',
    author          TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT '',
    cover           TEXT NOT NULL DEFAULT '',
    progress        INTEGER NOT NULL DEFAULT 0,
    finish_time     INTEGER,
    last_read_time  INTEGER,
    highlight_count INTEGER NOT NULL DEFAULT 0,
    review_count    INTEGER NOT NULL DEFAULT 0,
    updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS highlights (
    highlight_id  TEXT PRIMARY KEY,
    book_id       TEXT NOT NULL REFERENCES books(book_id),
    content       TEXT NOT NULL,
    chapter_uid   INTEGER,
    chapter_title TEXT NOT NULL DEFAULT '',
    range_val     TEXT NOT NULL DEFAULT '',
    create_time   INTEGER,
    synced_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_highlights_book    ON highlights(book_id);
CREATE INDEX IF NOT EXISTS idx_highlights_created ON highlights(create_time);

CREATE TABLE IF NOT EXISTS reviews (
    review_id     TEXT PRIMARY KEY,
    book_id       TEXT NOT NULL REFERENCES books(book_id),
    content       TEXT NOT NULL,
    abstract      TEXT NOT NULL DEFAULT '',
    chapter_uid   INTEGER,
    range_val     TEXT NOT NULL DEFAULT '',
    create_time   INTEGER,
    synced_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_book    ON reviews(book_id);
CREATE INDEX IF NOT EXISTS idx_reviews_created ON reviews(create_time);

CREATE TABLE IF NOT EXISTS concepts (
    concept_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    tag           TEXT NOT NULL,
    source_type   TEXT NOT NULL CHECK(source_type IN ('highlight', 'review')),
    source_id     TEXT NOT NULL,
    book_id       TEXT NOT NULL REFERENCES books(book_id),
    created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_concepts_tag  ON concepts(tag);
CREATE INDEX IF NOT EXISTS idx_concepts_book ON concepts(book_id);

CREATE TABLE IF NOT EXISTS summaries (
    summary_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_type  TEXT NOT NULL CHECK(summary_type IN ('daily', 'book_completion')),
    book_id       TEXT,
    date          TEXT,
    content       TEXT NOT NULL,
    created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    source_type TEXT NOT NULL,           -- 'highlight' | 'review'
    source_id   TEXT NOT NULL,
    book_id     TEXT NOT NULL,
    model       TEXT NOT NULL,           -- which model produced this vector
    dim         INTEGER NOT NULL,
    vec         BLOB NOT NULL,           -- numpy float32 bytes
    created_at  INTEGER NOT NULL,
    PRIMARY KEY (source_type, source_id, model)
);
CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model);
CREATE INDEX IF NOT EXISTS idx_embeddings_book  ON embeddings(book_id);
"""


def init_db(db_path: Path = None):
    """Create all tables and indexes if they don't exist."""
    with _conn(db_path) as c:
        c.executescript(_SCHEMA)
        # 迁移：老库 reviews 表补 abstract 列（批注对应的划线原文）。幂等。
        cols = [r[1] for r in c.execute("PRAGMA table_info(reviews)").fetchall()]
        if "abstract" not in cols:
            c.execute("ALTER TABLE reviews ADD COLUMN abstract TEXT NOT NULL DEFAULT ''")
            # 清空 review 增量游标：下次同步会重新拉取所有批注以回填 abstract
            c.execute("DELETE FROM sync_state WHERE key LIKE 'review_synckey_%'")


# ── Books ──────────────────────────────────────────────────────────────────

def upsert_book(book: dict, db_path: Path = None):
    """Insert or update a book record. finish_time is never overwritten with NULL."""
    with _conn(db_path) as c:
        c.execute("""
            INSERT INTO books
              (book_id, title, author, category, cover,
               progress, finish_time, last_read_time,
               highlight_count, review_count, updated_at)
            VALUES (:book_id, :title, :author, :category, :cover,
                    :progress, :finish_time, :last_read_time,
                    :highlight_count, :review_count, :updated_at)
            ON CONFLICT(book_id) DO UPDATE SET
                title           = excluded.title,
                author          = excluded.author,
                category        = excluded.category,
                cover           = excluded.cover,
                progress        = excluded.progress,
                finish_time     = COALESCE(excluded.finish_time, books.finish_time),
                last_read_time  = excluded.last_read_time,
                highlight_count = excluded.highlight_count,
                review_count    = excluded.review_count,
                updated_at      = excluded.updated_at
        """, {
            "book_id":         book["book_id"],
            "title":           book.get("title", ""),
            "author":          book.get("author", ""),
            "category":        book.get("category", ""),
            "cover":           book.get("cover", ""),
            "progress":        book.get("progress", 0),
            "finish_time":     book.get("finish_time"),
            "last_read_time":  book.get("last_read_time"),
            "highlight_count": book.get("highlight_count", 0),
            "review_count":    book.get("review_count", 0),
            "updated_at":      int(time.time()),
        })


def get_book(book_id: str, db_path: Path = None) -> Optional[dict]:
    with _conn(db_path) as c:
        row = c.execute("SELECT * FROM books WHERE book_id=?", (book_id,)).fetchone()
        return dict(row) if row else None


def get_all_books(db_path: Path = None) -> List[dict]:
    with _conn(db_path) as c:
        return [dict(r) for r in c.execute("SELECT * FROM books").fetchall()]


def get_newly_finished_books(since_ts: int = None,
                              db_path: Path = None) -> List[dict]:
    """Return books where finish_time is set but no book_completion summary exists yet.

    since_ts: if given, only return books whose finish_time >= since_ts.
              Use this to avoid triggering summaries for books finished long ago
              on a cold start.
    """
    time_clause = "AND b.finish_time >= ?" if since_ts is not None else ""
    params = (since_ts,) if since_ts is not None else ()
    with _conn(db_path) as c:
        rows = c.execute(f"""
            SELECT b.* FROM books b
            WHERE b.finish_time IS NOT NULL
              {time_clause}
              AND NOT EXISTS (
                  SELECT 1 FROM summaries s
                  WHERE s.summary_type = 'book_completion'
                    AND s.book_id = b.book_id
              )
        """, params).fetchall()
        return [dict(r) for r in rows]


# ── Highlights ─────────────────────────────────────────────────────────────

def insert_highlight(h: dict, db_path: Path = None) -> bool:
    """Returns True if newly inserted, False if already existed."""
    with _conn(db_path) as c:
        cur = c.execute("""
            INSERT OR IGNORE INTO highlights
              (highlight_id, book_id, content, chapter_uid, chapter_title,
               range_val, create_time, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            h["highlight_id"],
            h["book_id"],
            h["content"],
            h.get("chapter_uid"),
            h.get("chapter_title", ""),
            h.get("range_val", ""),
            h.get("create_time"),
            int(time.time()),
        ))
        return cur.rowcount > 0


def get_highlights_since(since_ts: int, db_path: Path = None) -> List[dict]:
    """Get highlights created after since_ts, with book title/author joined."""
    with _conn(db_path) as c:
        rows = c.execute("""
            SELECT h.*, b.title AS book_title, b.author AS book_author
            FROM highlights h
            JOIN books b ON h.book_id = b.book_id
            WHERE h.create_time > ?
            ORDER BY h.create_time ASC
        """, (since_ts,)).fetchall()
        return [dict(r) for r in rows]


def get_highlights_for_book(book_id: str, db_path: Path = None) -> List[dict]:
    with _conn(db_path) as c:
        rows = c.execute("""
            SELECT * FROM highlights WHERE book_id=? ORDER BY create_time ASC
        """, (book_id,)).fetchall()
        return [dict(r) for r in rows]


# ── Reviews ────────────────────────────────────────────────────────────────

def insert_review(r: dict, db_path: Path = None) -> bool:
    """Returns True if newly inserted, False if already existed."""
    with _conn(db_path) as c:
        cur = c.execute("""
            INSERT OR IGNORE INTO reviews
              (review_id, book_id, content, abstract, chapter_uid, range_val,
               create_time, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["review_id"],
            r["book_id"],
            r["content"],
            r.get("abstract", ""),
            r.get("chapter_uid"),
            r.get("range_val", ""),
            r.get("create_time"),
            int(time.time()),
        ))
        return cur.rowcount > 0


def update_review_abstract(review_id: str, abstract: str, db_path: Path = None) -> None:
    """回填已存在批注的划线原文（仅当原值为空时写入），用于老数据补 abstract。"""
    if not abstract:
        return
    with _conn(db_path) as c:
        c.execute("UPDATE reviews SET abstract=? WHERE review_id=? AND abstract=''",
                  (abstract, review_id))


def get_reviews_since(since_ts: int, db_path: Path = None) -> List[dict]:
    """Get reviews created after since_ts, with book title/author joined."""
    with _conn(db_path) as c:
        rows = c.execute("""
            SELECT rv.*, b.title AS book_title, b.author AS book_author
            FROM reviews rv
            JOIN books b ON rv.book_id = b.book_id
            WHERE rv.create_time > ?
            ORDER BY rv.create_time ASC
        """, (since_ts,)).fetchall()
        return [dict(r) for r in rows]


def get_reviews_for_book(book_id: str, db_path: Path = None) -> List[dict]:
    with _conn(db_path) as c:
        rows = c.execute("""
            SELECT * FROM reviews WHERE book_id=? ORDER BY create_time ASC
        """, (book_id,)).fetchall()
        return [dict(r) for r in rows]


def get_random_record(before_ts: int, db_path: Path = None) -> Optional[dict]:
    """Pick one random record from history (before before_ts).
    Prefers reviews (user's own thoughts); falls back to highlights longer than 40 chars.
    """
    with _conn(db_path) as c:
        # 1. Try a random review first
        row = c.execute("""
            SELECT r.content, b.title AS book_title, b.author,
                   r.create_time, 'review' AS source_type
            FROM reviews r JOIN books b ON r.book_id = b.book_id
            WHERE r.create_time < ? AND length(r.content) > 10
            ORDER BY RANDOM() LIMIT 1
        """, (before_ts,)).fetchone()
        if row:
            return dict(row)
        # 2. Fall back to highlights with a minimum length to avoid fragments
        row = c.execute("""
            SELECT h.content, b.title AS book_title, b.author,
                   h.create_time, 'highlight' AS source_type
            FROM highlights h JOIN books b ON h.book_id = b.book_id
            WHERE h.create_time < ? AND length(h.content) > 40
            ORDER BY RANDOM() LIMIT 1
        """, (before_ts,)).fetchone()
        return dict(row) if row else None


# ── Concepts ───────────────────────────────────────────────────────────────

def insert_concepts(source_type: str, source_id: str, book_id: str,
                    tags: List[str], db_path: Path = None):
    """Store LLM-extracted concept tags for a highlight or review."""
    now = int(time.time())
    with _conn(db_path) as c:
        c.executemany("""
            INSERT INTO concepts (tag, source_type, source_id, book_id, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, [(tag.strip(), source_type, source_id, book_id, now) for tag in tags if tag.strip()])


def get_concept_highlights(tag: str, db_path: Path = None) -> List[dict]:
    """某概念关联的划线（跨书），供图谱点击概念时的侧栏。"""
    with _conn(db_path) as c:
        rows = c.execute("""
            SELECT DISTINCT h.content, b.title AS book_title, e.book_id
            FROM concepts e
            JOIN highlights h ON e.source_type='highlight' AND h.highlight_id=e.source_id
            JOIN books b ON e.book_id = b.book_id
            WHERE e.tag = ?
            ORDER BY b.title
        """, (tag,)).fetchall()
        return [dict(r) for r in rows]


def get_distinct_concept_tags(db_path: Path = None) -> List[str]:
    with _conn(db_path) as c:
        return [r[0] for r in c.execute("SELECT DISTINCT tag FROM concepts").fetchall()]


def get_books_needing_concepts(db_path: Path = None, include_done: bool = False) -> List[dict]:
    """有划线的书。include_done=False 只返回还没抽过概念的；True 返回全部（换模型重抽用）。"""
    cond = "EXISTS (SELECT 1 FROM highlights h WHERE h.book_id = b.book_id)"
    if not include_done:
        cond += " AND NOT EXISTS (SELECT 1 FROM concepts cc WHERE cc.book_id = b.book_id)"
    with _conn(db_path) as c:
        rows = c.execute(f"SELECT b.* FROM books b WHERE {cond}").fetchall()
        return [dict(r) for r in rows]


def replace_book_concepts(book_id: str, concepts: List[dict], db_path: Path = None):
    """写入一本书的概念（先删旧、可重跑）。concepts: [{name, highlight_ids:[...]}]，
    每个概念按其支持划线落多行 concept↔highlight；无划线则落一条 book 级。"""
    now = int(time.time())
    with _conn(db_path) as c:
        c.execute("DELETE FROM concepts WHERE book_id=?", (book_id,))
        for con in concepts:
            name = (con.get("name") or "").strip()
            if not name:
                continue
            hids = con.get("highlight_ids") or []
            if hids:
                c.executemany("""
                    INSERT INTO concepts (tag, source_type, source_id, book_id, created_at)
                    VALUES (?, 'highlight', ?, ?, ?)
                """, [(name, h, book_id, now) for h in hids])
            else:
                c.execute("""
                    INSERT INTO concepts (tag, source_type, source_id, book_id, created_at)
                    VALUES (?, 'book', ?, ?, ?)
                """, (name, book_id, book_id, now))


def find_related_by_concepts(tags: List[str], exclude_book_id: str = None,
                              limit: int = 5, db_path: Path = None) -> List[dict]:
    """Find highlights/reviews from other books that share concept tags.

    Returns records sorted by number of matching tags (most overlap first).
    """
    if not tags:
        return []
    ph = ",".join("?" * len(tags))
    params = list(tags)
    exclude_clause = ""
    if exclude_book_id:
        exclude_clause = "AND c.book_id != ?"
        params.append(exclude_book_id)
    params.append(limit)
    with _conn(db_path) as c:
        rows = c.execute(f"""
            SELECT c.source_type, c.source_id, c.book_id,
                   b.title AS book_title,
                   GROUP_CONCAT(c.tag, ', ') AS matched_tags,
                   COUNT(*) AS match_count
            FROM concepts c
            JOIN books b ON c.book_id = b.book_id
            WHERE c.tag IN ({ph})
              {exclude_clause}
            GROUP BY c.source_id
            ORDER BY match_count DESC
            LIMIT ?
        """, params).fetchall()

        results = []
        for row in rows:
            r = dict(row)
            source = None
            with _conn(db_path) as c2:
                if r["source_type"] == "highlight":
                    source = c2.execute(
                        "SELECT content FROM highlights WHERE highlight_id=?",
                        (r["source_id"],)
                    ).fetchone()
                else:
                    source = c2.execute(
                        "SELECT content FROM reviews WHERE review_id=?",
                        (r["source_id"],)
                    ).fetchone()
            if source:
                r["content"] = source["content"]
            results.append(r)
        return results


# ── Keyword search (for cross-book echoes) ────────────────────────────────

def search_content(keyword: str, exclude_book_ids: List[str] = None,
                   before_ts: int = None, limit: int = 3,
                   db_path: Path = None) -> List[dict]:
    """LIKE search across highlights and reviews from other books.

    Returns list of dicts with: content, book_title, author, create_time,
    source_type ('highlight'|'review'), matched_kw.
    """
    pattern = f"%{keyword}%"
    exclude_clause = ""
    time_clause = ""
    base_params: List = [pattern]

    if exclude_book_ids:
        ph = ",".join("?" * len(exclude_book_ids))
        exclude_clause = f"AND h.book_id NOT IN ({ph})"
    if before_ts:
        time_clause = "AND h.create_time < ?"

    with _conn(db_path) as c:
        hl_params = list(base_params)
        if exclude_book_ids:
            hl_params.extend(exclude_book_ids)
        if before_ts:
            hl_params.append(before_ts)
        hl_params.append(limit)

        highlights = c.execute(f"""
            SELECT h.content, b.book_id, b.title AS book_title, b.author,
                   h.create_time, 'highlight' AS source_type
            FROM highlights h
            JOIN books b ON h.book_id = b.book_id
            WHERE h.content LIKE ?
              {exclude_clause.replace('h.book_id', 'h.book_id')}
              {time_clause}
            ORDER BY h.create_time DESC
            LIMIT ?
        """, hl_params).fetchall()

        rv_clause = exclude_clause.replace("h.book_id", "r.book_id")
        rv_time   = time_clause.replace("h.create_time", "r.create_time")
        rv_params = list(base_params)
        if exclude_book_ids:
            rv_params.extend(exclude_book_ids)
        if before_ts:
            rv_params.append(before_ts)
        rv_params.append(limit)

        reviews = c.execute(f"""
            SELECT r.content, b.book_id, b.title AS book_title, b.author,
                   r.create_time, 'review' AS source_type
            FROM reviews r
            JOIN books b ON r.book_id = b.book_id
            WHERE r.content LIKE ?
              {rv_clause}
              {rv_time}
            ORDER BY r.create_time DESC
            LIMIT ?
        """, rv_params).fetchall()

    results = []
    for row in list(highlights) + list(reviews):
        d = dict(row)
        d["matched_kw"] = keyword
        results.append(d)
    return results


# ── Summaries ──────────────────────────────────────────────────────────────

def save_summary(summary_type: str, content: str,
                 book_id: str = None, date: str = None,
                 db_path: Path = None):
    """Upsert: 一本书（或一天）只保留一条最新总结，避免重复堆积。"""
    with _conn(db_path) as c:
        if book_id is not None:
            c.execute("DELETE FROM summaries WHERE summary_type=? AND book_id=?",
                      (summary_type, book_id))
        elif date is not None:
            c.execute("DELETE FROM summaries WHERE summary_type=? AND date=?",
                      (summary_type, date))
        c.execute("""
            INSERT INTO summaries (summary_type, book_id, date, content, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (summary_type, book_id, date, content, int(time.time())))


def get_latest_summary(summary_type: str, book_id: str = None,
                        date: str = None, db_path: Path = None) -> Optional[dict]:
    """最新的真实总结。忽略 [pending 占位记录（视为无总结）。"""
    with _conn(db_path) as c:
        row = c.execute("""
            SELECT * FROM summaries
            WHERE summary_type = ?
              AND (book_id IS NULL OR book_id = ?)
              AND (date IS NULL OR date = ?)
              AND content NOT LIKE '[pending%'
            ORDER BY created_at DESC LIMIT 1
        """, (summary_type, book_id, date)).fetchone()
        return dict(row) if row else None


def get_books_needing_summary(db_path: Path = None, include_done: bool = False) -> List[dict]:
    """读完的书。include_done=False 只返回尚无真实总结的；True 返回全部（换模型重生成用）。
    「读后总结」顾名思义只对读完的书；在读的书（仅有划线）不计入。"""
    cond = "b.finish_time IS NOT NULL"
    if not include_done:
        cond += (" AND NOT EXISTS (SELECT 1 FROM summaries s WHERE s.summary_type='book_completion'"
                 " AND s.book_id=b.book_id AND s.content NOT LIKE '[pending%')")
    with _conn(db_path) as c:
        rows = c.execute(
            f"SELECT b.* FROM books b WHERE {cond} "
            "ORDER BY b.finish_time DESC NULLS LAST, b.last_read_time DESC").fetchall()
        return [dict(r) for r in rows]


def load_book_embeddings(book_id: str, model: str, source_type: str = "highlight",
                         db_path: Path = None) -> List[dict]:
    """某本书某类型的向量（提取式速览用）。返回 source_id / vec / content。"""
    with _conn(db_path) as c:
        rows = c.execute("""
            SELECT e.source_id, e.vec,
                   COALESCE(h.content, r.content) AS content
            FROM embeddings e
            LEFT JOIN highlights h ON e.source_type='highlight' AND h.highlight_id=e.source_id
            LEFT JOIN reviews   r ON e.source_type='review'    AND r.review_id=e.source_id
            WHERE e.book_id=? AND e.model=? AND e.source_type=?
        """, (book_id, model, source_type)).fetchall()
        return [dict(r) for r in rows]


# ── Sync State ─────────────────────────────────────────────────────────────

def get_sync_state(key: str, default: str = None, db_path: Path = None) -> Optional[str]:
    with _conn(db_path) as c:
        row = c.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_sync_state(key: str, value: str, db_path: Path = None):
    with _conn(db_path) as c:
        c.execute("""
            INSERT INTO sync_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, str(value)))


# ── Embeddings (optional semantic layer) ─────────────────────────────────────

def upsert_embedding(source_type: str, source_id: str, book_id: str,
                     model: str, dim: int, vec_blob: bytes, db_path: Path = None):
    """Store one vector (float32 bytes). Overwrites if same (source, model)."""
    with _conn(db_path) as c:
        c.execute("""
            INSERT OR REPLACE INTO embeddings
              (source_type, source_id, book_id, model, dim, vec, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (source_type, source_id, book_id, model, dim, vec_blob, int(time.time())))


def count_embeddings(model: str = None, db_path: Path = None) -> int:
    with _conn(db_path) as c:
        if model:
            return c.execute("SELECT COUNT(*) FROM embeddings WHERE model=?",
                             (model,)).fetchone()[0]
        return c.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]


def get_primary_model(db_path: Path = None) -> Optional[str]:
    """Model name with the most stored vectors. Lets read-only consumers
    (web insight endpoints) use embeddings without a runtime embedding source."""
    with _conn(db_path) as c:
        row = c.execute("""
            SELECT model FROM embeddings
            GROUP BY model ORDER BY COUNT(*) DESC LIMIT 1
        """).fetchone()
        return row["model"] if row else None


def count_sources(db_path: Path = None) -> int:
    """Total embeddable records (highlights + reviews)."""
    with _conn(db_path) as c:
        h = c.execute("SELECT COUNT(*) FROM highlights").fetchone()[0]
        r = c.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        return h + r


def get_sources_missing_embedding(model: str, limit: int = None,
                                  db_path: Path = None) -> List[dict]:
    """Highlights/reviews that have no embedding for the given model yet."""
    q = """
        SELECT 'highlight' AS source_type, h.highlight_id AS source_id,
               h.content AS content, h.book_id AS book_id
        FROM highlights h
        WHERE NOT EXISTS (
            SELECT 1 FROM embeddings e
            WHERE e.source_type='highlight' AND e.source_id=h.highlight_id AND e.model=?)
        UNION ALL
        SELECT 'review', r.review_id, r.content, r.book_id
        FROM reviews r
        WHERE NOT EXISTS (
            SELECT 1 FROM embeddings e
            WHERE e.source_type='review' AND e.source_id=r.review_id AND e.model=?)
    """
    params: List = [model, model]
    if limit:
        q += " LIMIT ?"
        params.append(limit)
    with _conn(db_path) as c:
        return [dict(r) for r in c.execute(q, params).fetchall()]


def load_search_embeddings(model: str, exclude_book_ids: List[str] = None,
                           before_ts: int = None, db_path: Path = None) -> List[dict]:
    """Load stored vectors (for a model) joined with their source content/book.

    Returns dicts: source_type, source_id, book_id, vec(bytes), book_title,
    author, content, create_time.
    """
    clauses = ["e.model = ?"]
    params: List = [model]
    if exclude_book_ids:
        ph = ",".join("?" * len(exclude_book_ids))
        clauses.append(f"e.book_id NOT IN ({ph})")
        params.extend(exclude_book_ids)
    time_clause = ""
    if before_ts:
        time_clause = "AND COALESCE(h.create_time, r.create_time) < ?"
    where = " AND ".join(clauses)
    q = f"""
        SELECT e.source_type, e.source_id, e.book_id, e.vec,
               b.title AS book_title, b.author AS author,
               COALESCE(h.content, r.content) AS content,
               COALESCE(h.create_time, r.create_time) AS create_time
        FROM embeddings e
        JOIN books b ON e.book_id = b.book_id
        LEFT JOIN highlights h ON e.source_type='highlight' AND h.highlight_id=e.source_id
        LEFT JOIN reviews   r ON e.source_type='review'    AND r.review_id=e.source_id
        WHERE {where} {time_clause}
    """
    if before_ts:
        params.append(before_ts)
    with _conn(db_path) as c:
        return [dict(r) for r in c.execute(q, params).fetchall()]


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db_path = get_db_path()
    init_db(db_path)
    print(f"OK: database initialized at {db_path}")

    # Quick stats
    with _conn(db_path) as c:
        stats = {
            "books":      c.execute("SELECT COUNT(*) FROM books").fetchone()[0],
            "highlights": c.execute("SELECT COUNT(*) FROM highlights").fetchone()[0],
            "reviews":    c.execute("SELECT COUNT(*) FROM reviews").fetchone()[0],
            "concepts":   c.execute("SELECT COUNT(*) FROM concepts").fetchone()[0],
            "summaries":  c.execute("SELECT COUNT(*) FROM summaries").fetchone()[0],
        }
    for k, v in stats.items():
        print(f"  {k}: {v}")
