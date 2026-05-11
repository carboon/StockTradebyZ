#!/usr/bin/env python3
"""
Tushare API 验证 & Davis Double Click 模型数据源检测
绕过 set_token() 以适配沙盒环境
"""
import pandas as pd
import sys
sys.path.insert(0, "/Volumes/DATA/davis2click/venv/lib/python3.14/site-packages")

from tushare.pro.client import DataApi

TOKEN = "3b917b97a3b62f4a9357e2b608449ef63e483e5ca12a1ff879092957"
pro = DataApi(TOKEN)

print("=" * 60)
print("Tushare API 接口验证 — Davis 双击模型")
print("=" * 60)

results = {}

def test_interface(name, api_name, **kwargs):
    """测试单个接口并记录结果"""
    try:
        df = pro.query(api_name, **kwargs)
        if df is not None and not df.empty:
            cols = list(df.columns)
            results[name] = {"status": "OK", "columns": cols, "rows": len(df)}
            print(f"\n✅ {name} — {len(df)} rows, {len(cols)} cols")
            print(f"   Fields: {cols[:10]}{'...' if len(cols) > 10 else ''}")
            return df
        else:
            results[name] = {"status": "EMPTY", "columns": [], "rows": 0}
            print(f"\n⚠️  {name} — 返回空数据（可能权限不足或当日无数据）")
            return None
    except Exception as e:
        results[name] = {"status": "FAIL", "error": str(e)}
        print(f"\n❌ {name} — {str(e)[:150]}")
        return None

# ==========================================
# 1. 基础信息
# ==========================================
print("\n" + "-" * 40)
print("【基础信息】")
print("-" * 40)

test_interface("stock_basic", "stock_basic",
               exchange='', list_status='L',
               fields='ts_code,name,industry,list_date,market')

# ==========================================
# 2. 日线行情 & 估值
# ==========================================
print("\n" + "-" * 40)
print("【行情 & 估值】")
print("-" * 40)

test_interface("daily", "daily",
               ts_code='000001.SZ', start_date='20260101', end_date='20260511',
               fields='ts_code,trade_date,open,high,low,close,vol,amount')

test_interface("daily_basic", "daily_basic",
               ts_code='000001.SZ', start_date='20260101', end_date='20260511',
               fields='ts_code,trade_date,pe,pe_ttm,pb,ps,ps_ttm,total_mv,circ_mv,turnover_rate')

test_interface("daily_basic_batch", "daily_basic",
               ts_code='000001.SZ,600519.SH,300750.SZ', trade_date='20260509')

# ==========================================
# 3. 财务数据
# ==========================================
print("\n" + "-" * 40)
print("【财务数据】")
print("-" * 40)

test_interface("income", "income",
               ts_code='000001.SZ', period='20251231',
               fields='ts_code,report_type,revenue,operate_profit,total_profit,n_income,n_income_attr_p,basic_eps,diluted_eps')

test_interface("balancesheet", "balancesheet",
               ts_code='000001.SZ', period='20251231',
               fields='ts_code,report_type,total_assets,total_liab,total_hldr_eqy,goodwill,accounts_receiv')

test_interface("cashflow", "cashflow",
               ts_code='000001.SZ', period='20251231',
               fields='ts_code,report_type,n_cashflow_act,c_fr_sale_sg')

# ==========================================
# 4. 财务指标（衍生指标，含毛利率、ROE等）
# ==========================================
print("\n" + "-" * 40)
print("【财务指标 — fina_indicator】")
print("-" * 40)

test_interface("fina_indicator", "fina_indicator",
               ts_code='000001.SZ', period='20251231',
               fields='ts_code,grossprofit_margin,netprofit_margin,roe,roa,roe_dt,debt_to_assets,current_ratio,quick_ratio')

# 利润表TTM (获取最近4个季度数据)
print("\n" + "-" * 40)
print("【利润表 — 多季度（用于计算增速）】")
print("-" * 40)

test_interface("income_4q", "income",
               ts_code='000001.SZ', period='20241231,20240930,20240630,20240331,20231231,20230930,20230630,20230331',
               fields='ts_code,report_type,end_date,revenue,n_income,revenue_qq,n_income_qq')

test_interface("income_vip", "income_vip",
               ts_code='000001.SZ', period='20241231,20240930,20240630,20240331,20231231',
               fields='ts_code,report_type,end_date,revenue,n_income,basic_eps')

# ==========================================
# 5. 机构持仓
# ==========================================
print("\n" + "-" * 40)
print("【机构持仓】")
print("-" * 40)

test_interface("fund_hold", "fund_hold",
               ts_code='000001.SZ', end_date='20251231')

test_interface("fund_portfolio", "fund_portfolio",
               ts_code='000001.SZ', end_date='20251231')

# ==========================================
# 6. 股东质押
# ==========================================
print("\n" + "-" * 40)
print("【股东质押】")
print("-" * 40)

test_interface("pledge_stat", "pledge_stat",
               ts_code='000001.SZ')

test_interface("pledge_detail", "pledge_detail",
               ts_code='000001.SZ')

# ==========================================
# 7. 指数成分 & 北向资金
# ==========================================
print("\n" + "-" * 40)
print("【指数成分 & 资金流向】")
print("-" * 40)

test_interface("index_weight", "index_weight",
               index_code='000300.SH', trade_date='20260509')

test_interface("hk_hold", "hk_hold",
               ts_code='000001.SZ', start_date='20260101', end_date='20260511')

# 融资融券
test_interface("margin_detail", "margin_detail",
               ts_code='000001.SZ', start_date='20260501', end_date='20260511')

# 龙虎榜（情绪指标）
test_interface("top_list", "top_list",
               ts_code='000001.SZ', start_date='20260101', end_date='20260511')

# ==========================================
# 8. 广度扫描 — 全市场最新估值
# ==========================================
print("\n" + "-" * 40)
print("【广度扫描 — 全市场最新PE】")
print("-" * 40)

test_interface("full_market_daily_basic", "daily_basic",
               trade_date='20260509',
               fields='ts_code,trade_date,pe,pe_ttm,pb,total_mv,turnover_rate')

# 尝试获取多个财务指标（验证能否批量拉取）
print("\n" + "-" * 40)
print("【批量财务指标测试】")
print("-" * 40)

test_interface("fina_batch", "fina_indicator",
               ts_code='000001.SZ,600519.SH,300750.SZ', period='20251231',
               fields='ts_code,grossprofit_margin,netprofit_margin,roe,roe_dt,debt_to_assets')

# ==========================================
# 汇总
# ==========================================
print("\n" + "=" * 60)
print("接口汇总")
print("=" * 60)

ok = sum(1 for v in results.values() if v["status"] == "OK")
empty = sum(1 for v in results.values() if v["status"] == "EMPTY")
fail = sum(1 for v in results.values() if v["status"] == "FAIL")

print(f"\n  ✅ OK: {ok}   ⚠️ EMPTY: {empty}   ❌ FAIL: {fail}")
print(f"  总计: {len(results)} 个接口")

# 核心数据评估
print("\n" + "-" * 40)
print("【双击模型核心数据就绪度】")
print("-" * 40)

core_checks = {
    "估值数据 (PE/PB/PS)": "daily_basic" in results and results["daily_basic"]["status"] == "OK",
    "利润表 (计算增速)": "income" in results and results["income"]["status"] == "OK",
    "资产负债表 (商誉/应收)": "balancesheet" in results and results["balancesheet"]["status"] == "OK",
    "现金流 (经营质量)": "cashflow" in results and results["cashflow"]["status"] == "OK",
    "财务指标 (毛利率/ROE)": "fina_indicator" in results and results["fina_indicator"]["status"] == "OK",
    "机构持仓": "fund_hold" in results and results["fund_hold"]["status"] == "OK",
    "股东质押": "pledge_stat" in results and results["pledge_stat"]["status"] == "OK",
    "指数成分 (候选池)": "index_weight" in results and results["index_weight"]["status"] == "OK",
    "北向资金": "hk_hold" in results and results["hk_hold"]["status"] == "OK",
    "全市场扫描": "full_market_daily_basic" in results and results["full_market_daily_basic"]["status"] == "OK",
}

for name, ok_status in core_checks.items():
    icon = "✅" if ok_status else "❌"
    print(f"  {icon} {name}")

score = sum(1 for v in core_checks.values() if v)
print(f"\n  综合就绪度: {score}/{len(core_checks)}")

# 权限等级推断
print("\n" + "-" * 40)
print("【权限等级推断】")
print("-" * 40)

if results.get("income_vip", {}).get("status") == "OK":
    print("  🔓 推测为付费 VIP 权限（income_vip 可用）")
elif results.get("hk_hold", {}).get("status") == "OK":
    print("  🔓 推测为高级权限（港股通持仓可用）")
elif results.get("full_market_daily_basic", {}).get("rows", 0) > 100:
    print("  🔓 推测为基础权限（全市场数据可访问）")
else:
    print("  ⚠️  推测为免费/注册权限（部分数据受限）")

# 额外能力
if results.get("margin_detail", {}).get("status") == "OK":
    print("  + 融资融券数据可用")
if results.get("top_list", {}).get("status") == "OK":
    print("  + 龙虎榜数据可用")
if results.get("pledge_detail", {}).get("status") == "OK":
    print("  + 质押明细数据可用")

print("\n" + "=" * 60)
print("验证完成")
print("=" * 60)
