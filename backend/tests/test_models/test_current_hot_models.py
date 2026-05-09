from app.models import (
    CurrentHotAnalysisResult,
    CurrentHotCandidate,
    CurrentHotIntradaySnapshot,
    CurrentHotRun,
)


def test_current_hot_run_table_definition():
    table = CurrentHotRun.__table__

    unique_names = {constraint.name for constraint in table.constraints if constraint.name}
    index_names = {index.name for index in table.indexes}

    assert "uq_current_hot_runs_pick_date" in unique_names
    assert "ix_current_hot_runs_status_pick_date" in index_names
    assert "ix_current_hot_runs_finished_at" in index_names


def test_current_hot_candidate_table_definition():
    table = CurrentHotCandidate.__table__

    unique_names = {constraint.name for constraint in table.constraints if constraint.name}
    index_names = {index.name for index in table.indexes}

    assert "uq_current_hot_candidates_pick_date_code" in unique_names
    assert "ix_current_hot_candidates_pick_date_code" in index_names
    assert "ix_current_hot_candidates_pick_date_board" in index_names


def test_current_hot_analysis_result_table_definition():
    table = CurrentHotAnalysisResult.__table__

    unique_names = {constraint.name for constraint in table.constraints if constraint.name}
    index_names = {index.name for index in table.indexes}

    assert "uq_current_hot_analysis_results_pick_date_code_reviewer" in unique_names
    assert "ix_current_hot_analysis_results_pick_date_code" in index_names
    assert "ix_current_hot_analysis_results_pick_date_signal_type" in index_names


def test_current_hot_intraday_snapshot_table_definition():
    table = CurrentHotIntradaySnapshot.__table__

    unique_names = {constraint.name for constraint in table.constraints if constraint.name}
    index_names = {index.name for index in table.indexes}

    assert "uq_current_hot_intraday_snapshots_trade_date_code" in unique_names
    assert "ix_current_hot_intraday_snapshots_trade_date_code" in index_names
    assert "ix_current_hot_intraday_snapshots_board_group" in index_names
