from __future__ import annotations

from sqlalchemy import text

from cloud_app.backtester import run_walkforward_backtest
from cloud_app.db import db, initialize_database, json_dumps, new_id, now_iso, set_state
from cloud_app.market_data import sync_market_data
from cloud_app.scanner import run_daily_scan


def run_daily_workflow(mode: str = "fast", progress=None) -> dict:
    initialize_database()
    run_id = new_id()
    started_at = now_iso()
    with db() as conn:
        conn.execute(
            text(
                """
                INSERT INTO workflow_runs (id, run_type, status, started_at, metadata_json)
                VALUES (:id, 'daily', 'running', :started_at, :metadata_json)
                """
            ),
            {"id": run_id, "started_at": started_at, "metadata_json": json_dumps({"mode": mode})},
        )

    def update(label: str, pct: int) -> None:
        if progress:
            progress(label, pct)

    try:
        update("Updating NSE price data", 15)
        data_sync = sync_market_data()

        def backtest_progress(payload: dict) -> None:
            update(f"Strategy Lab: {payload.get('step', 'validating')}", 30 + int(payload.get("progress_pct", 0) * 0.45))

        validation = run_walkforward_backtest(mode=mode, progress_callback=backtest_progress)

        update("Scanning today setup candidates", 82)
        scan = run_daily_scan()

        result = {"run_id": run_id, "data_sync": data_sync, "strategy_validation": validation, "scan": scan}
        set_state("last_workflow", {"status": "completed", "completed_at": now_iso(), **result})
        with db() as conn:
            conn.execute(
                text(
                    """
                    UPDATE workflow_runs
                    SET status = 'completed', completed_at = :completed_at, metadata_json = :metadata_json
                    WHERE id = :id
                    """
                ),
                {"id": run_id, "completed_at": now_iso(), "metadata_json": json_dumps(result)},
            )
        update("Daily workflow complete", 100)
        return result
    except Exception as exc:
        set_state("last_workflow", {"status": "failed", "completed_at": now_iso(), "error": str(exc), "run_id": run_id})
        with db() as conn:
            conn.execute(
                text(
                    """
                    UPDATE workflow_runs
                    SET status = 'failed', completed_at = :completed_at, metadata_json = :metadata_json
                    WHERE id = :id
                    """
                ),
                {"id": run_id, "completed_at": now_iso(), "metadata_json": json_dumps({"error": str(exc)})},
            )
        raise
