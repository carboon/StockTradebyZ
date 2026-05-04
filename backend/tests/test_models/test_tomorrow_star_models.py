from app.models import AnalysisResult, Candidate, TomorrowStarRun


def test_candidate_table_constraints_and_indexes():
    table = Candidate.__table__

    unique_names = {constraint.name for constraint in table.constraints if constraint.name}
    index_names = {index.name for index in table.indexes}

    assert "uq_candidates_pick_date_code" in unique_names
    assert "ix_candidates_pick_date_code" in index_names
    assert "ix_candidates_pick_date_id" in index_names


def test_analysis_result_table_constraints_and_indexes():
    table = AnalysisResult.__table__

    unique_names = {constraint.name for constraint in table.constraints if constraint.name}
    index_names = {index.name for index in table.indexes}

    assert "uq_analysis_results_pick_date_code_reviewer" in unique_names
    assert "ix_analysis_results_pick_date_code" in index_names
    assert "ix_analysis_results_pick_date_signal_type" in index_names
    assert "ix_analysis_results_pick_date_reviewer" in index_names


def test_tomorrow_star_run_table_definition():
    table = TomorrowStarRun.__table__

    unique_names = {constraint.name for constraint in table.constraints if constraint.name}
    index_names = {index.name for index in table.indexes}
    column_names = set(table.columns.keys())

    assert "uq_tomorrow_star_runs_pick_date" in unique_names
    assert "ix_tomorrow_star_runs_status_pick_date" in index_names
    assert "ix_tomorrow_star_runs_finished_at" in index_names
    assert {
        "pick_date",
        "status",
        "candidate_count",
        "analysis_count",
        "trend_start_count",
        "reviewer",
        "strategy_version",
        "window_size",
        "source",
        "started_at",
        "finished_at",
        "error_message",
    }.issubset(column_names)
