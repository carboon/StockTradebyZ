from datetime import date

from app.models import Stock, StockDaily
from app.services.closing_analysis_service import ClosingAnalysisService


def _daily(code: str, trade_date: date, net_mf_amount: float | None) -> StockDaily:
    return StockDaily(
        code=code,
        trade_date=trade_date,
        open=10,
        close=10,
        high=10,
        low=10,
        volume=1000,
        net_mf_amount=net_mf_amount,
    )


def _fake_sector_flow_items(self, trade_date: date) -> list[dict]:
    return [
        {"sector_name": "工业金属", "net_mf_amount": 549522.87},
        {"sector_name": "软件服务", "net_mf_amount": -62520.45},
    ]


def test_sector_flow_uses_eastmoney_when_report_day_moneyflow_missing(db_session, monkeypatch) -> None:
    db_session.add_all(
        [
            Stock(code="600000", name="浦发银行", market="SH", industry="银行"),
            Stock(code="000858", name="五粮液", market="SZ", industry="白酒"),
            _daily("600000", date(2026, 5, 25), 1200),
            _daily("000858", date(2026, 5, 25), -800),
            _daily("600000", date(2026, 5, 26), None),
            _daily("000858", date(2026, 5, 26), None),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(ClosingAnalysisService, "_fetch_tushare_dc_sector_flow_items", _fake_sector_flow_items)

    flow = ClosingAnalysisService(db_session)._build_sector_flow(date(2026, 5, 26))

    assert flow["source"] == "tushare_dc"
    assert flow["source_trade_date"] == "2026-05-26"
    assert flow["is_fallback"] is True
    assert flow["inflow_top3"] == [{"sector_name": "工业金属", "net_mf_amount": 549522.87}]
    assert flow["outflow_top3"] == [{"sector_name": "软件服务", "net_mf_amount": -62520.45}]


def test_sector_flow_history_uses_eastmoney_for_report_day_when_moneyflow_missing(db_session, monkeypatch) -> None:
    db_session.add_all(
        [
            Stock(code="600000", name="浦发银行", market="SH", industry="银行"),
            _daily("600000", date(2026, 5, 25), 1200),
            _daily("600000", date(2026, 5, 26), None),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(ClosingAnalysisService, "_fetch_tushare_dc_sector_flow_items", _fake_sector_flow_items)

    history = ClosingAnalysisService(db_session)._build_sector_flow_history(date(2026, 5, 26), days=3)

    assert [item["trade_date"] for item in history] == ["2026-05-26", "2026-05-25"]
    assert history[0]["sectors"]["工业金属"] == 549522.87


def test_tomorrow_preselected_includes_trend_start_pass_outside_top30() -> None:
    scored = [
        {
            "code": f"{index:06d}",
            "local_score": float(100 - index),
            "signal_type": "rebound",
            "verdict": "WATCH",
            "b1_passed": True,
        }
        for index in range(35)
    ]
    scored.append(
        {
            "code": "603297",
            "local_score": 2.75,
            "signal_type": "trend_start",
            "verdict": "PASS",
            "b1_passed": True,
        }
    )

    preselected = ClosingAnalysisService._build_tomorrow_preselected(scored)

    assert "603297" in {item["code"] for item in preselected}
    assert len(preselected) == 31


def test_merge_ai_prediction_caps_at_top10_before_star_append() -> None:
    preselected = [
        {
            "code": f"{index:06d}",
            "local_score": float(100 - index),
            "tomorrow_star_pass": index == 10,
        }
        for index in range(12)
    ]
    ai_result = {
        "selected": [
            {"code": f"{index:06d}", "rank": index + 1, "ai_comment": "AI点评"}
            for index in range(10)
        ],
        "rejected": [{"code": "000010", "reason": "未进入AI前十"}],
    }

    selected = ClosingAnalysisService._merge_ai_prediction(preselected, ai_result)

    assert len(selected) == 11
    assert selected[-1]["code"] == "000010"
    assert selected[-1]["is_star_rejected"] is True


def test_ensure_tomorrow_star_visible_appends_only_one_extra() -> None:
    selected = [{"code": f"{index:06d}", "rank": index + 1} for index in range(10)]
    scored = [
        {
            "code": "600001",
            "name": "示例股份",
            "local_rank": 35,
            "local_score": 80.0,
            "tomorrow_star_pass": True,
            "b1_comment": "趋势启动，缩量回踩",
            "sector_net_mf_amount": 1000,
            "sector_3d_net_mf_amount": 3000,
            "matched_hot_topics": ["半导体"],
        },
        {
            "code": "600002",
            "local_rank": 36,
            "local_score": 70.0,
            "tomorrow_star_pass": True,
        },
    ]

    service = object.__new__(ClosingAnalysisService)
    result = service._ensure_tomorrow_star_visible(scored, selected)

    assert len(result) == 11
    assert result[-1]["code"] == "600001"
    assert "趋势启动，缩量回踩" in result[-1]["ai_comment"]
