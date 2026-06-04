from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _streamlit_secret(name: str) -> str | None:
    try:
        import streamlit as st

        value = st.secrets.get(name)
        return str(value) if value else None
    except Exception:
        return None


def database_url() -> str:
    return (
        os.getenv("DATABASE_URL")
        or _streamlit_secret("DATABASE_URL")
        or f"sqlite:///{(PROJECT_ROOT / 'data' / 'cloud_streamlit.db').as_posix()}"
    )


def normalize_sqlalchemy_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


@dataclass(frozen=True)
class CloudSettings:
    database_url: str
    paper_capital: float = 1_000_000.0
    slippage_bps: float = 8.0
    transaction_cost_bps: float = 12.0
    max_daily_setups: int = 2


settings = CloudSettings(database_url=normalize_sqlalchemy_url(database_url()))

