import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .domain import RawRecord

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.getenv("COSMO_DB", ROOT / "data" / "analyses.db"))


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS raw (id TEXT PRIMARY KEY, source TEXT, url TEXT, payload BLOB, metadata TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, document TEXT)")
    con.commit()
    return con


def store_raw(source: str, url: str, payload: bytes, published_at=None, cache_state="fresh") -> RawRecord:
    digest = hashlib.sha256(payload).hexdigest()
    record = RawRecord(id=f"{source}:{digest}", source=source, url=url, content_sha256=digest,
                       retrieved_at=datetime.now(timezone.utc), published_at=published_at,
                       cache_state=cache_state)
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO raw VALUES (?,?,?,?,?)",
                    (record.id, source, url, payload, record.model_dump_json()))
    return record


def latest_raw(source: str):
    with connect() as con:
        row = con.execute("SELECT payload,metadata FROM raw WHERE source=? ORDER BY json_extract(metadata,'$.retrieved_at') DESC LIMIT 1", (source,)).fetchone()
    return (row[0], RawRecord.model_validate_json(row[1])) if row else None


def store_analysis(document):
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO analyses VALUES (?,?)", (document.id, document.model_dump_json()))


def load_analysis(identifier):
    with connect() as con:
        row = con.execute("SELECT document FROM analyses WHERE id=?", (identifier,)).fetchone()
    return json.loads(row[0]) if row else None
