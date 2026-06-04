from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from cloud_app.config import settings


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def json_loads(value: Any, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def engine():
    if settings.database_url.startswith("sqlite:///"):
        raw = settings.database_url.replace("sqlite:///", "", 1)
        Path(raw).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(settings.database_url, pool_pre_ping=True)


_ENGINE = engine()


@contextmanager
def db() -> Iterator[Connection]:
    with _ENGINE.begin() as conn:
        yield conn


def rows(result) -> list[dict]:
    output = []
    for row in result.mappings().all():
        item = dict(row)
        for key, value in list(item.items()):
            if key.endswith("_json"):
                item[key] = json_loads(value, value)
        output.append(item)
    return output


def row(result) -> dict | None:
    items = rows(result)
    return items[0] if items else None


def initialize_database() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS symbols (
      symbol TEXT PRIMARY KEY,
      company_name TEXT NOT NULL,
      sector TEXT NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS market_data_daily (
      symbol TEXT NOT NULL,
      trade_date TEXT NOT NULL,
      open REAL NOT NULL,
      high REAL NOT NULL,
      low REAL NOT NULL,
      close REAL NOT NULL,
      adjusted_close REAL NOT NULL,
      volume INTEGER NOT NULL,
      turnover REAL NOT NULL,
      source TEXT NOT NULL,
      source_metadata_json TEXT NOT NULL,
      created_at TEXT NOT NULL,
      PRIMARY KEY (symbol, trade_date)
    );

    CREATE TABLE IF NOT EXISTS strategy_validations (
      id TEXT PRIMARY KEY,
      run_id TEXT NOT NULL,
      strategy_key TEXT NOT NULL,
      strategy_name TEXT NOT NULL,
      family TEXT NOT NULL,
      metrics_json TEXT NOT NULL,
      passes_validation INTEGER NOT NULL,
      selection_score REAL NOT NULL,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS signals (
      id TEXT PRIMARY KEY,
      symbol TEXT NOT NULL,
      company_name TEXT NOT NULL,
      sector TEXT NOT NULL,
      strategy_key TEXT NOT NULL,
      strategy_name TEXT NOT NULL,
      signal_date TEXT NOT NULL,
      entry_low REAL NOT NULL,
      entry_high REAL NOT NULL,
      stop_loss REAL NOT NULL,
      target_price REAL NOT NULL,
      expected_holding_days INTEGER NOT NULL,
      risk_reward_ratio REAL NOT NULL,
      confidence_score REAL NOT NULL,
      reason_summary TEXT NOT NULL,
      factor_breakdown_json TEXT NOT NULL,
      backtest_summary_json TEXT NOT NULL,
      source_metadata_json TEXT NOT NULL,
      ranking_explanation TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS app_state (
      key TEXT PRIMARY KEY,
      value_json TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS workflow_runs (
      id TEXT PRIMARY KEY,
      run_type TEXT NOT NULL,
      status TEXT NOT NULL,
      started_at TEXT NOT NULL,
      completed_at TEXT,
      metadata_json TEXT NOT NULL
    );
    """
    with db() as conn:
        for statement in [part.strip() for part in ddl.split(";") if part.strip()]:
            conn.execute(text(statement))


def set_state(key: str, value: dict) -> None:
    timestamp = now_iso()
    with db() as conn:
        conn.execute(
            text(
                """
                INSERT INTO app_state (key, value_json, updated_at)
                VALUES (:key, :value_json, :updated_at)
                ON CONFLICT (key) DO UPDATE SET
                  value_json = excluded.value_json,
                  updated_at = excluded.updated_at
                """
            ),
            {"key": key, "value_json": json_dumps(value), "updated_at": timestamp},
        )


def get_state(key: str, default=None):
    with db() as conn:
        item = row(conn.execute(text("SELECT value_json FROM app_state WHERE key = :key"), {"key": key}))
    return json_loads(item["value_json"], default) if item else default

