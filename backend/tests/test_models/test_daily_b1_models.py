from app.models import DailyB1Check, DailyB1CheckDetail
from app.schemas import B1CheckItem, DiagnosisHistoryDetailResponse


def test_daily_b1_check_constraints_and_indexes():
    table = DailyB1Check.__table__

    unique_names = {constraint.name for constraint in table.constraints if constraint.name}
    index_names = {index.name for index in table.indexes}

    assert "uq_daily_b1_checks_code_check_date" in unique_names
    assert "ix_daily_b1_checks_code_check_date" in index_names
    assert "ix_daily_b1_checks_check_date_code" in index_names


def test_daily_b1_check_detail_table_definition():
    table = DailyB1CheckDetail.__table__

    unique_names = {constraint.name for constraint in table.constraints if constraint.name}
    index_names = {index.name for index in table.indexes}
    column_names = set(table.columns.keys())

    assert "uq_daily_b1_check_details_code_check_date" in unique_names
    assert "ix_daily_b1_check_details_code_check_date" in index_names
    assert "ix_daily_b1_check_details_status_check_date" in index_names
    assert {
        "code",
        "check_date",
        "status",
        "detail_version",
        "strategy_version",
        "rule_version",
        "score_details_json",
        "rules_json",
        "details_json",
        "updated_at",
    }.issubset(column_names)


def test_b1_check_item_detail_fields():
    item = B1CheckItem(
        check_date="2026-04-30",
        detail_ready=True,
        detail_version="v1",
        detail_updated_at="2026-05-04T10:00:00Z",
    )

    assert item.detail_ready is True
    assert item.detail_version == "v1"
    assert item.detail_updated_at is not None


def test_diagnosis_history_detail_response_payload():
    response = DiagnosisHistoryDetailResponse(
        code="002222",
        check_date="2026-04-30",
        status="ready",
        detail_ready=True,
        detail_version="v2",
        strategy_version="quant-v2",
        rule_version="rules-202605",
        payload={
            "score_details": {"trend": 3.2},
            "rules": {"prefilter_passed": True},
            "details": {"comment": "ok"},
        },
    )

    assert response.detail_ready is True
    assert response.payload.score_details == {"trend": 3.2}
    assert response.payload.rules == {"prefilter_passed": True}
