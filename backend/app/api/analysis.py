"""
Analysis API
~~~~~~~~~~~~
分析相关 API (明日之星、单股诊断)
"""
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Candidate, AnalysisResult, DailyB1Check, Stock, Task
from app.services.analysis_service import analysis_service
from app.services.task_service import TaskService
from app.services.tushare_service import TushareService
from app.schemas import (
    CandidatesResponse,
    CandidateItem,
    AnalysisResultResponse,
    AnalysisItem,
    DiagnosisHistoryResponse,
    B1CheckItem,
    DiagnosisRequest,
    DiagnosisResponse,
)

router = APIRouter()

ROOT = Path(__file__).parent.parent.parent.parent


def ensure_tushare_ready() -> None:
    service = TushareService()
    valid, message = service.verify_token()
    if not valid:
        raise HTTPException(status_code=503, detail=f"Tushare 未就绪: {message}")


@router.get("/tomorrow-star/dates")
async def get_tomorrow_star_dates() -> dict:
    """获取明日之星历史日期列表"""
    history = analysis_service.get_candidates_history(limit=100)
    return {
        "dates": [h["date"] for h in history],
        "history": history,
    }


@router.get("/tomorrow-star/freshness")
async def get_tomorrow_star_freshness(
    db: Session = Depends(get_db),
) -> dict:
    """获取明日之星数据新鲜度状态。"""
    from app.services.market_service import market_service, MarketService

    latest_trade_date = market_service.get_latest_trade_date() if market_service.token else None
    local_latest_date = market_service.get_local_latest_date()
    latest_candidate_date = analysis_service.get_latest_candidate_date()
    latest_result_date = analysis_service.get_latest_result_date()

    running_task = (
        db.query(Task)
        .filter(
            Task.task_type.in_(["tomorrow_star", "full_update"]),
            Task.status.in_(["pending", "running"]),
        )
        .order_by(Task.created_at.desc())
        .first()
    )

    # 获取增量更新状态
    incremental_state = MarketService.get_update_state()

    needs_update = bool(
        latest_trade_date and (
            local_latest_date != latest_trade_date
            or latest_candidate_date != latest_trade_date
            or latest_result_date != latest_trade_date
        )
    )

    freshness_version = "|".join([
        str(latest_trade_date or ""),
        str(local_latest_date or ""),
        str(latest_candidate_date or ""),
        str(latest_result_date or ""),
        str(running_task.id if running_task else ""),
        str(running_task.status if running_task else ""),
        str(incremental_state.get("running", False)),
        str(incremental_state.get("progress", 0)),
    ])

    return {
        "latest_trade_date": latest_trade_date,
        "local_latest_date": local_latest_date,
        "latest_candidate_date": latest_candidate_date,
        "latest_result_date": latest_result_date,
        "needs_update": needs_update,
        "freshness_version": freshness_version,
        "running_task_id": running_task.id if running_task else None,
        "running_task_status": running_task.status if running_task else None,
        "incremental_update": {
            "running": incremental_state.get("running", False),
            "progress": incremental_state.get("progress", 0),
            "total": incremental_state.get("total", 0),
            "current_code": incremental_state.get("current_code"),
            "updated_count": incremental_state.get("updated_count", 0),
            "skipped_count": incremental_state.get("skipped_count", 0),
            "failed_count": incremental_state.get("failed_count", 0),
            "started_at": incremental_state.get("started_at"),
            "message": incremental_state.get("message", ""),
        },
    }


@router.get("/tomorrow-star/candidates", response_model=CandidatesResponse)
async def get_candidates(
    date: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> CandidatesResponse:
    """获取候选股票列表（带缓存，实时筛选最新交易日数据）"""
    from app.config import settings
    from app.services.market_service import market_service
    from datetime import date as date_class
    import pandas as pd
    import yaml
    import sys

    # 添加 pipeline 目录到 Python 路径
    pipeline_dir = ROOT / "pipeline"
    if str(pipeline_dir) not in sys.path:
        sys.path.insert(0, str(pipeline_dir))

    # 添加 agent 目录到 Python 路径
    agent_dir = ROOT / "agent"
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))

    from Selector import B1Selector

    requested_date = analysis_service._normalize_pick_date(date)
    latest_candidate_date = analysis_service.get_latest_candidate_date()

    # 1. 优先使用已有候选快照日期；缺失时再退回到交易日判断
    if market_service.token:
        should_update, latest_trade_date = market_service.should_update_data()
    else:
        should_update = False
        latest_trade_date = None
    pick_date_str = requested_date or latest_candidate_date or latest_trade_date or date_class.today().strftime("%Y-%m-%d")

    # 解析日期
    try:
        pick_date = pd.Timestamp(pick_date_str)
    except:
        pick_date = pd.Timestamp.now()

    try:
        def resolve_stock_name_map(codes: list[str]) -> dict[str, str | None]:
            normalized_codes = [str(code).zfill(6) for code in codes if str(code or "").strip()]
            if not normalized_codes:
                return {}

            name_map = {
                str(stock.code): stock.name
                for stock in db.query(Stock).filter(Stock.code.in_(normalized_codes)).all()
            }
            missing_name_codes = [code for code in normalized_codes if not name_map.get(code)]
            if missing_name_codes and os.environ.get("TUSHARE_TOKEN"):
                try:
                    TushareService().sync_stock_names_to_db(db, missing_name_codes)
                    name_map = {
                        str(stock.code): stock.name
                        for stock in db.query(Stock).filter(Stock.code.in_(normalized_codes)).all()
                    }
                except Exception as exc:
                    print(f"同步候选股票名称失败: {exc}")

            return name_map

        def build_b1_candidates(
            prepared: dict,
            pool_codes: list,
            target_pick_date,
            selector,
        ) -> list[dict]:
            computed_candidates = []

            for code in pool_codes:
                df = prepared.get(code)
                if df is None:
                    continue
                try:
                    if target_pick_date in df.index:
                        check_date = target_pick_date
                    else:
                        valid_dates = df.index[df.index <= target_pick_date]
                        if valid_dates.empty:
                            continue
                        check_date = valid_dates[-1]

                    # 使用当前代码重新计算，避免信任旧缓存中的 _vec_pick/candidates。
                    current_df = selector.prepare_df(df)
                    if check_date not in current_df.index:
                        continue

                    b1_passed = bool(current_df.loc[check_date, "_vec_pick"])
                    if not b1_passed:
                        continue

                    row = current_df.loc[check_date]
                    open_val = float(row["open"]) if pd.notna(row.get("open")) else None
                    close_val = float(row["close"])
                    change_pct = (close_val - open_val) / open_val * 100 if open_val and open_val > 0 else None
                    computed_candidates.append({
                        "code": code,
                        "date": check_date.strftime("%Y-%m-%d"),
                        "strategy": "b1",
                        "open": open_val,
                        "close": close_val,
                        "change_pct": change_pct,
                        "turnover_n": float(row.get("turnover_n", 0)),
                        "b1_passed": True,
                        "kdj_j": float(row.get("J", 0)) if pd.notna(row.get("J")) else None,
                    })
                except Exception as exc:
                    print(f"Error processing {code}: {exc}")
                    continue

            return computed_candidates

        def build_snapshot_candidates(
            snapshot_codes: list[str],
            target_pick_date,
            selector,
        ) -> list[dict]:
            raw_dir = ROOT / settings.raw_data_dir
            computed_candidates = []

            for code in snapshot_codes:
                csv_path = raw_dir / f"{code}.csv"
                if not csv_path.exists():
                    continue
                try:
                    df = pd.read_csv(csv_path)
                    df.columns = [c.lower() for c in df.columns]
                    if "date" not in df.columns:
                        continue
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date").reset_index(drop=True)
                    current_df = selector.prepare_df(df.set_index("date", drop=False))

                    if target_pick_date in current_df.index:
                        check_date = target_pick_date
                    else:
                        valid_dates = current_df.index[current_df.index <= target_pick_date]
                        if valid_dates.empty:
                            continue
                        check_date = valid_dates[-1]

                    row = current_df.loc[check_date]
                    open_val = float(row["open"]) if pd.notna(row.get("open")) else None
                    close_val = float(row["close"])
                    change_pct = (close_val - open_val) / open_val * 100 if open_val and open_val > 0 else None
                    computed_candidates.append({
                        "code": code,
                        "date": check_date.strftime("%Y-%m-%d"),
                        "strategy": "b1",
                        "open": open_val,
                        "close": close_val,
                        "change_pct": change_pct,
                        "turnover_n": float(row.get("turnover_n", 0)),
                        "b1_passed": True,
                        "kdj_j": float(row.get("J", 0)) if pd.notna(row.get("J")) else None,
                    })
                except Exception as exc:
                    print(f"Error processing snapshot candidate {code}: {exc}")
                    continue

            return computed_candidates

        # 加载配置
        config_file = ROOT / "config" / "rules_preselect.yaml"
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        global_cfg = cfg.get("global", {})
        b1_cfg = cfg.get("b1", {})

        if not b1_cfg.get("enabled", True):
            return CandidatesResponse(
                pick_date=pick_date.date(),
                candidates=[],
                total=0,
            )

        zx_m1 = b1_cfg.get("zx_m1", 14)
        zx_m2 = b1_cfg.get("zx_m2", 28)
        zx_m3 = b1_cfg.get("zx_m3", 57)
        zx_m4 = b1_cfg.get("zx_m4", 114)

        selector = B1Selector(
            j_threshold=float(b1_cfg.get("j_threshold", 15.0)),
            j_q_threshold=float(b1_cfg.get("j_q_threshold", 0.10)),
            zx_m1=zx_m1, zx_m2=zx_m2, zx_m3=zx_m3, zx_m4=zx_m4,
        )

        snapshot_pick_date, snapshot_codes = analysis_service.load_candidate_codes(requested_date)
        if snapshot_codes:
            if snapshot_pick_date:
                pick_date = pd.Timestamp(snapshot_pick_date)
            candidates = build_snapshot_candidates(snapshot_codes, pick_date, selector)
            stock_name_map = resolve_stock_name_map([c["code"] for c in candidates[:limit]])

            items = []
            for i, c in enumerate(candidates[:limit]):
                items.append(
                    CandidateItem(
                        id=i,
                        pick_date=pick_date.date(),
                        code=c["code"],
                        name=stock_name_map.get(c["code"]),
                        strategy="b1",
                        open_price=c.get("open"),
                        close_price=c["close"],
                        change_pct=c.get("change_pct"),
                        turnover=float(c["turnover_n"]),
                        b1_passed=True,
                        kdj_j=c["kdj_j"],
                    )
                )

            return CandidatesResponse(
                pick_date=pick_date.date(),
                candidates=items,
                total=len(candidates),
            )
        if requested_date:
            return CandidatesResponse(
                pick_date=pick_date.date(),
                candidates=[],
                total=0,
            )

        # 2. 尝试从缓存加载
        cached_data = market_service.load_prepared_data(pick_date_str)

        if cached_data is not None:
            # 使用缓存数据
            prepared = cached_data.get("prepared", {})
            pool_codes = cached_data.get("pool_codes", [])
            candidates = build_b1_candidates(prepared, pool_codes, pick_date, selector)

            print(f"使用缓存数据: {len(prepared)} 只股票, {len(pool_codes)} 只流动性池, {len(candidates)} 只候选")
        else:
            # 缓存不存在，需要重新计算
            print("缓存不存在，开始计算...")

            # 加载原始数据
            raw_dir = ROOT / settings.raw_data_dir
            if not raw_dir.exists():
                return CandidatesResponse(
                    pick_date=pick_date.date(),
                    candidates=[],
                    total=0,
                )

            # 加载并预处理数据
            from pipeline.pipeline_core import MarketDataPreparer, TopTurnoverPoolBuilder
            from pipeline.select_stock import load_raw_data
            raw_data = load_raw_data(str(raw_dir))

            # 预处理数据（计算 turnover_n 和 B1 指标）
            preparer = MarketDataPreparer(
                warmup_bars=global_cfg.get("min_bars_buffer", 10),
                n_turnover_days=global_cfg.get("n_turnover_days", 43),
                selector=B1Selector(
                    j_threshold=float(b1_cfg.get("j_threshold", 15.0)),
                    j_q_threshold=float(b1_cfg.get("j_q_threshold", 0.10)),
                ),
                n_jobs=4,  # 使用多进程加速
            )
            prepared = preparer.prepare(raw_data)

            # 构建流动性池
            top_m = global_cfg.get("top_m", 2000)
            pool_builder = TopTurnoverPoolBuilder(top_m=top_m)
            pool_by_date = pool_builder.build(prepared)
            pool_codes = pool_by_date.get(pick_date, [])

            if not pool_codes:
                # 如果 pick_date 没有数据，尝试使用最近一天的数据
                if pool_by_date:
                    nearest_date = max(d for d in pool_by_date.keys() if d <= pick_date)
                    pool_codes = pool_by_date.get(nearest_date, [])
                    pick_date = nearest_date

            # 运行 B1 策略筛选
            candidates = build_b1_candidates(prepared, pool_codes, pick_date, selector)

            # 保存到缓存
            cache_data = {
                "prepared": prepared,
                "pool_codes": pool_codes,
                "candidates": candidates,
                "pick_date": pick_date,
            }
            market_service.save_prepared_data(pick_date_str, cache_data)

            # 清理旧缓存
            market_service.clear_old_cache(keep_days=3)

        filtered_candidates = [c for c in candidates if c.get("b1_passed", True)]
        stock_name_map = resolve_stock_name_map([c["code"] for c in filtered_candidates[:limit]])

        # 转换为响应格式
        items = []

        for i, c in enumerate(filtered_candidates[:limit]):
            items.append(
                CandidateItem(
                    id=i,
                    pick_date=pick_date.date(),
                    code=c["code"],
                    name=stock_name_map.get(c["code"]),
                    strategy="b1",
                    open_price=c.get("open"),
                    close_price=c["close"],
                    change_pct=c.get("change_pct"),
                    turnover=float(c["turnover_n"]),
                    b1_passed=c["b1_passed"],
                    kdj_j=c["kdj_j"],
                )
            )

        # 更新交易日缓存
        if latest_trade_date:
            market_service.update_cache(latest_trade_date)

        return CandidatesResponse(
            pick_date=pick_date.date(),
            candidates=items,
            total=len(filtered_candidates),
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取候选数据失败: {str(e)}")


@router.get("/tomorrow-star/results", response_model=AnalysisResultResponse)
async def get_analysis_results(
    date: Optional[str] = None,
) -> AnalysisResultResponse:
    """获取指定日期的分析结果"""
    result = analysis_service.get_analysis_results(date)

    items = []
    for r in result.get("results", []):
        items.append(
            AnalysisItem(
                id=0,
                pick_date=datetime.strptime(result["pick_date"], "%Y-%m-%d").date() if result.get("pick_date") else None,
                code=r.get("code", ""),
                reviewer="quant",
                verdict=r.get("verdict"),
                total_score=r.get("total_score"),
                signal_type=r.get("signal_type"),
                comment=r.get("comment"),
            )
        )

    return AnalysisResultResponse(
        pick_date=datetime.strptime(result["pick_date"], "%Y-%m-%d").date() if result.get("pick_date") else None,
        results=items,
        total=len(items),
        min_score_threshold=result.get("min_score_threshold", 4.0),
    )


@router.get("/diagnosis/{code}/history", response_model=DiagnosisHistoryResponse)
async def get_diagnosis_history(
    code: str,
    days: int = 30,
    db: Session = Depends(get_db),
) -> DiagnosisHistoryResponse:
    """获取单股诊断历史"""
    code = code.zfill(6)
    history = analysis_service.get_stock_history_checks(code, days)
    stock = db.query(Stock).filter(Stock.code == code).first()
    if stock is None:
        try:
            stock = TushareService().sync_stock_to_db(db, code)
        except Exception:
            stock = None

    return DiagnosisHistoryResponse(
        code=code,
        name=stock.name if stock else None,
        history=[B1CheckItem.model_validate(h) for h in history],
        total=len(history),
    )


@router.post("/diagnosis/{code}/generate-history")
async def generate_diagnosis_history(
    code: str,
    background_tasks: BackgroundTasks,
    days: int = Query(default=30, description="生成最近N个交易日的历史数据"),
    clean: bool = Query(default=True, description="是否先清理旧数据"),
) -> dict:
    """重新刷新单股诊断历史数据（后台任务）"""
    ensure_tushare_ready()
    code = code.zfill(6)

    # 启动后台任务生成历史数据
    background_tasks.add_task(analysis_service.generate_stock_history_checks, code, days, clean)

    return {
        "status": "pending",
        "message": f"已启动刷新 {code} 最近{days}个交易日的诊断历史数据任务",
        "code": code,
        "days": days,
    }


@router.get("/diagnosis/{code}/history-status")
async def get_history_status(code: str) -> dict:
    """获取历史数据生成状态"""
    import json
    from pathlib import Path

    code = code.zfill(6)
    from app.config import settings
    history_dir = ROOT / settings.review_dir / "history"
    stock_history_file = history_dir / f"{code}.json"

    if not stock_history_file.exists():
        return {"exists": False, "generating": False, "count": 0}

    try:
        with open(stock_history_file, "r") as f:
            data = json.load(f)
        history = data.get("history", [])
        return {
            "exists": True,
            "generating": data.get("generating", False),
            "count": len(history),
            "total": data.get("total", 0),
            "generated_at": data.get("generated_at"),
        }
    except:
        return {"exists": False, "generating": False, "count": 0}


@router.post("/diagnosis/analyze")
async def analyze_stock(request: DiagnosisRequest, db: Session = Depends(get_db)) -> DiagnosisResponse:
    """启动单股分析"""
    ensure_tushare_ready()
    code = request.code.zfill(6)

    try:
        # 执行分析
        result = analysis_service.analyze_stock(code, "quant")
        stock = db.query(Stock).filter(Stock.code == code).first()
        if stock is None:
            try:
                stock = TushareService().sync_stock_to_db(db, code)
            except Exception:
                stock = None

        # 获取K线数据
        kline_data = None
        df = analysis_service.load_stock_data(code)
        if df is not None and not df.empty:
            # 确定成交量列名
            vol_col = "vol" if "vol" in df.columns else "volume" if "volume" in df.columns else None
            volume_data = df[vol_col].tolist()[-120:] if vol_col else []

            kline_data = {
                "dates": df["date"].dt.strftime("%Y-%m-%d").tolist()[-120:],
                "open": df["open"].tolist()[-120:],
                "high": df["high"].tolist()[-120:],
                "low": df["low"].tolist()[-120:],
                "close": df["close"].tolist()[-120:],
                "volume": volume_data,
            }

        return DiagnosisResponse(
            code=code,
            name=stock.name if stock else None,
            current_price=result.get("close_price"),
            b1_passed=result.get("b1_passed"),
            score=result.get("score"),
            verdict=result.get("verdict"),
            analysis={
                # B1 检查详情
                "kdj_j": result.get("kdj_j"),
                "zx_long_pos": result.get("zx_long_pos"),
                "weekly_ma_aligned": result.get("weekly_ma_aligned"),
                "volume_healthy": result.get("volume_healthy"),
                # 评分明细
                "scores": result.get("scores"),
                "trend_reasoning": result.get("trend_reasoning"),
                "position_reasoning": result.get("position_reasoning"),
                "volume_reasoning": result.get("volume_reasoning"),
                "abnormal_move_reasoning": result.get("abnormal_move_reasoning"),
                # 信号和结论
                "signal_type": result.get("signal_type"),
                "signal_reasoning": result.get("signal_reasoning"),
                "comment": result.get("comment"),
            },
            kline_data=kline_data,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@router.post("/tomorrow-star/generate")
async def generate_tomorrow_star(
    background_tasks: BackgroundTasks,
    reviewer: str = Query(default="quant", description="评审者类型"),
    db: Session = Depends(get_db),
) -> dict:
    """手动生成明日之星"""
    ensure_tushare_ready()
    task_service = TaskService(db)

    result = await task_service.create_task(
        "tomorrow_star",
        {"reviewer": reviewer}
    )

    return {
        "status": "pending",
        "message": "明日之星生成任务已创建",
        "task_id": result["task_id"],
        "ws_url": result["ws_url"],
    }
