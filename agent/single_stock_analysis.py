"""
single_stock_analysis.py
~~~~~~~~~~~~~~~~~~~~~~~~~
单只股票完整分析工具：从数据采集到 AI 评分

功能：
    1. 检查 data/raw 是否有该股票的数据
    2. 若无或过期，从 Tushare 拉取数据并更新
    3. 运行 B1 策略判断是否通过
    4. 导出 K 线图
    5. 调用 LLM（GLM-4V-Flash/通义千问/Gemini）进行分析
    6. 输出最终评分报告

数据存储：
    - data/raw/{code}.csv              # 原始数据（复用现有目录）
    - data/kline/single/{code}_day.jpg # K 线图
    - data/review/single/{code}.json   # 分析报告

用法：
    python agent/single_stock_analysis.py 600519                    # 使用默认模型（GLM）
    python agent/single_stock_analysis.py 600519 --model qwen       # 指定模型
    python agent/single_stock_analysis.py 600519 --model gemini
    python agent/single_stock_analysis.py 600519 --force-refresh     # 强制刷新数据
"""
import argparse
import base64
import json
import os
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import tushare as ts
import yaml
from openai import OpenAI

warnings.filterwarnings("ignore")

# ────────────────────────────────────────────────
# 路径配置
# ────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent


def _resolve_path(*parts) -> Path:
    """解析路径，相对于项目根目录。"""
    p = _ROOT / Path(*parts)
    return p if p.is_absolute() else p


def _load_b1_config(config_path: Optional[Path] = None) -> dict:
    """加载统一的 B1 配置，默认读取 rules_preselect.yaml。"""
    path = config_path or _resolve_path("config", "rules_preselect.yaml")
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


# ────────────────────────────────────────────────
# 步骤 1: 数据采集
# ────────────────────────────────────────────────

def _to_ts_code(code: str) -> str:
    """把6位code映射到标准 ts_code 后缀。"""
    code = str(code).zfill(6)
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    elif code.startswith(("4", "8")):
        return f"{code}.BJ"
    else:
        return f"{code}.SZ"


def fetch_stock_data(code: str, days: int = 500) -> Optional[pd.DataFrame]:
    """从 Tushare 拉取单只股票的历史数据。

    Args:
        code: 股票代码（6位）
        days: 拉取天数（默认500天，约2年数据）

    Returns:
        DataFrame with columns: date, open, close, high, low, volume
    """
    ts_token = os.environ.get("TUSHARE_TOKEN")
    if not ts_token:
        print("[ERROR] 未设置环境变量 TUSHARE_TOKEN")
        return None

    ts.set_token(ts_token)

    # 计算日期范围
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    pro = ts.pro_api()
    ts_code = _to_ts_code(code)

    print(f"[步骤1] 正在拉取 {code} 数据（{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}）...")

    try:
        df = ts.pro_bar(
            ts_code=ts_code,
            adj="qfq",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            freq="D",
        )
    except Exception as e:
        print(f"[ERROR] 拉取数据失败: {e}")
        return None

    if df is None or df.empty:
        print(f"[WARN] {code} 无数据")
        return None

    # 标准化列名
    df = df.rename(columns={"trade_date": "date", "vol": "volume"})[
        ["date", "open", "close", "high", "low", "volume"]
    ].copy()
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "close", "high", "low", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.sort_values("date").reset_index(drop=True)
    print(f"[INFO] 拉取成功，共 {len(df)} 条记录")
    return df


def get_stock_data(code: str, force_refresh: bool = False) -> Optional[pd.DataFrame]:
    """获取股票数据：检查本地文件，根据日期差距决定是否更新。

    更新策略：
        - 文件不存在 → 拉取
        - 文件存在，最后一行日期与当前日期差距 >= 1 天 → 更新
        - 文件存在，数据是最新的 → 直接使用

    Args:
        code: 股票代码
        force_refresh: 是否强制从网络刷新

    Returns:
        DataFrame
    """
    raw_dir = _resolve_path("data", "raw")
    csv_path = raw_dir / f"{code}.csv"

    # 检查本地数据
    if not force_refresh and csv_path.exists():
        # 读取最后一行，获取最新日期
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if len(lines) >= 2:  # 至少有表头和一行数据
                    last_line = lines[-1].strip()
                    # 解析 CSV 行，提取第一个字段（date）
                    import io
                    last_row = pd.read_csv(io.StringIO(last_line), names=["date", "open", "close", "high", "low", "volume"])
                    latest_date_str = last_row["date"].iloc[0]
                    latest_date = pd.to_datetime(latest_date_str)

                    # 计算日期差距
                    today = datetime.now().date()
                    latest = latest_date.date()
                    days_diff = (today - latest).days

                    print(f"[步骤1] 本地数据: {csv_path}")
                    print(f"[INFO] 最新日期: {latest} (差距 {days_diff} 天)")

                    if days_diff < 1:
                        print(f"[INFO] 数据是最新的，无需更新")
                        # 读取完整数据并返回
                        df = pd.read_csv(csv_path)
                        df["date"] = pd.to_datetime(df["date"])
                        return df
                    else:
                        print(f"[INFO] 数据已过期 {days_diff} 天，正在更新...")
        except Exception as e:
            print(f"[WARN] 读取本地文件失败: {e}，将重新拉取")

    # 文件不存在或数据过期，从 Tushare 拉取
    print(f"[步骤1] 正在从 Tushare 拉取 {code} 数据...")
    df = fetch_stock_data(code)
    if df is None:
        return None

    # 保存到 data/raw
    raw_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    print(f"[INFO] 数据已保存: {csv_path}")

    return df


# ────────────────────────────────────────────────
# 步骤 2: B1 策略检查（简化版）
# ────────────────────────────────────────────────

def check_b1_strategy(df: pd.DataFrame, config_path: Optional[Path] = None) -> dict:
    """运行统一版 B1 策略检查。

    Args:
        df: 股票日线数据
        config_path: B1配置文件路径（可选）

    Returns:
        dict: {
            "passed": bool,
            "reason": str,
            "j_value": float,
            "j_q_value": float,
            "ma_status": str
        }
    """
    cfg = _load_b1_config(config_path)
    cfg_b1 = cfg.get("b1", {})
    j_threshold = float(cfg_b1.get("j_threshold", 15.0))
    j_q_threshold = float(cfg_b1.get("j_q_threshold", 0.10))
    zx_m1 = int(cfg_b1.get("zx_m1", 14))
    zx_m2 = int(cfg_b1.get("zx_m2", 28))
    zx_m3 = int(cfg_b1.get("zx_m3", 57))
    zx_m4 = int(cfg_b1.get("zx_m4", 114))

    pipeline_dir = _resolve_path("pipeline")
    if str(pipeline_dir) not in sys.path:
        sys.path.insert(0, str(pipeline_dir))

    from Selector import B1Selector

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if len(df) < max(zx_m4, 30) + 10:
        return {
            "passed": False,
            "reason": f"数据不足（需要至少 {max(zx_m4, 30) + 10} 条，当前 {len(df)} 条）",
            "j_value": 0,
            "j_q_value": 0,
            "k_value": 0,
            "d_value": 0,
            "ma_status": "N/A",
        }

    selector = B1Selector(
        j_threshold=j_threshold,
        j_q_threshold=j_q_threshold,
        zx_m1=zx_m1,
        zx_m2=zx_m2,
        zx_m3=zx_m3,
        zx_m4=zx_m4,
    )
    prepared = selector.prepare_df(df.set_index("date", drop=False))
    latest = prepared.iloc[-1]

    j_value = float(latest["J"]) if pd.notna(latest.get("J")) else 0.0
    k_value = float(latest["K"]) if pd.notna(latest.get("K")) else 0.0
    d_value = float(latest["D"]) if pd.notna(latest.get("D")) else 0.0
    j_q_value = float(
        prepared["J"].expanding(min_periods=1).quantile(j_q_threshold).iloc[-1]
    ) if "J" in prepared.columns and not prepared["J"].dropna().empty else 0.0

    conditions = []
    ma_status = "多头排列" if bool(latest.get("wma_bull", False)) else "非多头排列"

    kdj_ok = bool(selector._kdj_filter(prepared))
    zx_ok = bool(selector._zx_filter(prepared))
    wma_ok = bool(selector._wma_filter(prepared))
    max_vol_ok = bool(selector._max_vol_filter(prepared))

    if kdj_ok:
        conditions.append(f"KDJ低位通过（J={j_value:.1f}, Q{int(j_q_threshold * 100)}={j_q_value:.1f}）")
    else:
        conditions.append(f"KDJ未通过（J={j_value:.1f}, 阈值={j_threshold:.1f}, Q{int(j_q_threshold * 100)}={j_q_value:.1f}）")

    if zx_ok:
        conditions.append("知行线通过")
    else:
        conditions.append("知行线未通过")

    if wma_ok:
        conditions.append("周线多头排列通过")
    else:
        conditions.append("周线多头排列未通过")

    if max_vol_ok:
        conditions.append("量能形态通过")
    else:
        conditions.append("量能形态未通过")

    passed = bool(latest.get("_vec_pick", False))

    return {
        "passed": passed,
        "reason": "; ".join(conditions),
        "j_value": j_value,
        "j_q_value": j_q_value,
        "k_value": k_value,
        "d_value": d_value,
        "ma_status": ma_status,
    }


# ────────────────────────────────────────────────
# 步骤 3: 导出 K 线图
# ────────────────────────────────────────────────

def export_chart(df: pd.DataFrame, code: str, output_path: Path) -> bool:
    """导出 K 线图为图片。

    Args:
        df: 股票日线数据
        code: 股票代码
        output_path: 输出文件路径

    Returns:
        是否成功
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        print("[ERROR] 需要安装 plotly: pip install plotly")
        return False

    print(f"[步骤3] 正在导出 K 线图...")

    # 取最近120天数据
    df_chart = df.tail(120).copy()

    candlestick = go.Candlestick(
        x=df_chart["date"],
        open=df_chart["open"],
        high=df_chart["high"],
        low=df_chart["low"],
        close=df_chart["close"],
        name="K线",
    )
    fig = go.Figure(data=[candlestick])

    # 添加均线
    for period, color, name in [(7, "blue", "MA7"), (25, "orange", "MA25"), (77, "purple", "MA77")]:
        if len(df_chart) >= period:
            ma = df_chart["close"].rolling(window=period).mean()
            fig.add_trace(go.Scatter(
                x=df_chart["date"],
                y=ma,
                mode="lines",
                name=name,
                line=dict(color=color, width=1),
            ))

    fig.update_layout(
        title=f"{code} 日线图",
        xaxis_title="日期",
        yaxis_title="价格",
        template="plotly_white",
        height=600,
        width=1400,
        xaxis_rangeslider_visible=False,
    )

    # 导出
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 尝试使用 kaleido
    try:
        fig.write_image(str(output_path), format="jpg", width=1400, height=600, scale=2)
        print(f"[INFO] K 线图已导出: {output_path}")
        return True
    except Exception as e:
        print(f"[WARN] kaleido 导出失败: {e}")
        return False


# ────────────────────────────────────────────────
# 步骤 4: LLM 图表分析
# ────────────────────────────────────────────────

def load_prompt(prompt_path: Optional[Path] = None) -> str:
    """加载分析 prompt。"""
    default_path = _ROOT / "agent" / "prompt.md"
    path = prompt_path or default_path

    if not path.exists():
        return """你是专业波段交易员，擅长分析股票K线图。
请根据图表分析趋势、位置、量价行为，给出评分（1-5分）和投资建议（PASS/WATCH/FAIL）。
请严格按照JSON格式输出。"""

    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _image_to_base64(path: Path) -> str:
    """将图片转为 base64。"""
    data = path.read_bytes()
    return base64.b64encode(data).decode("utf-8")


def analyze_with_llm(
    code: str,
    chart_path: Path,
    model_type: str = "glm",
    prompt: Optional[str] = None,
) -> Optional[dict]:
    """调用 LLM 进行图表分析。

    Args:
        code: 股票代码
        chart_path: K 线图路径
        model_type: 模型类型 (glm/qwen/gemini)
        prompt: 自定义 prompt（可选）

    Returns:
        分析结果 dict
    """
    if prompt is None:
        prompt = load_prompt()

    # 模型配置
    model_configs = {
        "glm": {
            "env_key": "ZHIPUAI_API_KEY",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4v-flash",
        },
        "qwen": {
            "env_key": "DASHSCOPE_API_KEY",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen3-vl-plus",
        },
        "gemini": {
            "env_key": "GEMINI_API_KEY",
            # Gemini 使用不同的 SDK
            "use_gemini_sdk": True,
            "model": "gemini-3.1-pro-preview",
        },
    }

    if model_type not in model_configs:
        print(f"[ERROR] 不支持的模型类型: {model_type}")
        return None

    cfg = model_configs[model_type]
    api_key = os.environ.get(cfg["env_key"])

    if not api_key:
        print(f"[ERROR] 未设置环境变量: {cfg['env_key']}")
        return None

    print(f"[步骤4] 正在使用 {model_type.upper()} 分析 {code}...")

    user_text = (
        f"股票代码：{code}\n\n"
        "以下是该股票的 **日线图**，请按照系统提示中的框架进行分析，"
        "并严格按照要求输出 JSON。"
    )

    # Gemini 使用原生 SDK
    if model_type == "gemini":
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            # 读取图片
            suffix = chart_path.suffix.lower()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
            mime_type = mime_map.get(suffix, "image/jpeg")
            data = chart_path.read_bytes()

            response = client.models.generate_content(
                model=cfg["model"],
                contents=[
                    types.Content(role="user", parts=[
                        types.Part.from_text(text="【日线图】"),
                        types.Part.from_bytes(data=data, mime_type=mime_type),
                        types.Part.from_text(text=user_text),
                    ])
                ],
                config=types.GenerateContentConfig(
                    system_instruction=prompt,
                    temperature=0.2,
                ),
            )

            response_text = response.text
        except ImportError:
            print("[ERROR] 需要安装 google-genai: pip install google-genai")
            return None
        except Exception as e:
            print(f"[ERROR] Gemini 调用失败: {e}")
            return None

    else:  # GLM 和 Qwen 使用 OpenAI 兼容接口
        client = OpenAI(api_key=api_key, base_url=cfg["base_url"])

        # 准备图片
        if model_type == "qwen":
            # 通义千问需要 data URI
            suffix = chart_path.suffix.lower()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
            mime_type = mime_map.get(suffix, "image/jpeg")
            image_base64 = _image_to_base64(chart_path)
            image_url = f"data:{mime_type};base64,{image_base64}"
        else:  # glm
            # GLM 直接用 base64
            image_base64 = _image_to_base64(chart_path)
            image_url = image_base64

        try:
            response = client.chat.completions.create(
                model=cfg["model"],
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_url}},
                            {"type": "text", "text": user_text},
                        ],
                    },
                ],
                temperature=0.2,
            )
            response_text = response.choices[0].message.content
        except Exception as e:
            print(f"[ERROR] {model_type.upper()} 调用失败: {e}")
            return None

    if not response_text:
        print(f"[ERROR] {model_type.upper()} 返回空响应")
        return None

    # 解析 JSON
    import re
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
    if code_block:
        response_text = code_block.group(1)

    start = response_text.find("{")
    end = response_text.rfind("}") + 1
    if start == -1 or end == 0:
        print(f"[WARN] 未能解析 JSON，原始响应: {response_text[:200]}")
        return None

    try:
        result = json.loads(response_text[start:end])
        result["code"] = code
        print(f"[INFO] {model_type.upper()} 分析完成")
        return result
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON 解析失败: {e}")
        return None


# ────────────────────────────────────────────────
# 步骤 5: 生成报告
# ────────────────────────────────────────────────

def generate_report(
    code: str,
    b1_result: dict,
    llm_result: Optional[dict],
    output_path: Path,
) -> None:
    """生成最终分析报告。"""
    report = {
        "code": code,
        "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "b1_check": b1_result,
        "llm_analysis": llm_result,
    }

    # 保存 JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"[INFO] 报告已保存: {output_path}")


def print_report(code: str, b1_result: dict, llm_result: Optional[dict]) -> None:
    """打印分析报告到终端。"""
    print(f"\n{'='*60}")
    print(f"  {code} 股票分析报告")
    print(f"{'='*60}")

    # B1 检查结果
    print(f"\n【一、量化初选（B1策略）】")
    status = "✓ 通过" if b1_result["passed"] else "✗ 未通过"
    print(f"  状态: {status}")
    print(f"  原因: {b1_result['reason']}")
    print(f"  J值: {b1_result['j_value']:.2f}")
    print(f"  K值: {b1_result['k_value']:.2f}")
    print(f"  D值: {b1_result['d_value']:.2f}")
    print(f"  均线: {b1_result['ma_status']}")

    # LLM 分析结果
    if llm_result:
        print(f"\n【二、AI 图表分析】")

        scores = llm_result.get("scores", {})
        if scores:
            print(f"  趋势结构: {scores.get('trend_structure', 'N/A')}/5")
            print(f"  价格位置: {scores.get('price_position', 'N/A')}/5")
            print(f"  量价行为: {scores.get('volume_behavior', 'N/A')}/5")
            print(f"  前期异动: {scores.get('previous_abnormal_move', 'N/A')}/5")
            print(f"  ────────────────────────")
            print(f"  总分: {llm_result.get('total_score', 'N/A')}/5")

        print(f"  信号类型: {llm_result.get('signal_type', 'N/A')}")
        print(f"  判定: {llm_result.get('verdict', 'N/A')}")

        comment = llm_result.get("comment", "")
        if comment:
            print(f"\n  点评: {comment}")

    # 综合建议
    print(f"\n【三、综合建议】")
    if b1_result["passed"] and llm_result:
        verdict = llm_result.get("verdict", "UNKNOWN")
        if verdict == "PASS":
            print(f"  ✓ 量化通过 + AI 推荐 → **建议关注**")
        elif verdict == "WATCH":
            print(f"  ~ 量化通过 + AI 观察 → **谨慎关注**")
        else:
            print(f"  ✗ 量化通过 + AI 不推荐 → **暂不关注**")
    elif b1_result["passed"]:
        print(f"  ✓ 量化通过，AI分析未完成 → **可关注**")
    else:
        print(f"  ✗ 量化未通过 → **暂不关注**")

    print(f"{'='*60}\n")


# ────────────────────────────────────────────────
# 主函数
# ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="单只股票完整分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python agent/single_stock_analysis.py 600519                    # 使用 GLM-4V-Flash（免费）
  python agent/single_stock_analysis.py 600519 --model qwen       # 使用通义千问
  python agent/single_stock_analysis.py 600519 --model gemini     # 使用 Gemini
  python agent/single_stock_analysis.py 600519 --force-refresh   # 强制刷新数据
        """,
    )
    parser.add_argument("code", help="股票代码（6位，如 600519）")
    parser.add_argument(
        "--model",
        choices=["glm", "qwen", "gemini"],
        default="glm",
        help="选择 AI 模型（默认: glm，完全免费）",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="强制从网络刷新数据，不使用本地缓存",
    )
    parser.add_argument(
        "--config",
        help="B1 策略配置文件路径（可选）",
    )
    parser.add_argument(
        "--prompt",
        help="自定义 prompt 文件路径（可选）",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="跳过 LLM 分析，只做量化检查",
    )
    args = parser.parse_args()

    code = args.code.zfill(6)
    config_path = Path(args.config) if args.config else None
    prompt = load_prompt(Path(args.prompt)) if args.prompt else None

    print(f"\n{'='*60}")
    print(f"  单股分析: {code}")
    print(f"  AI 模型: {args.model.upper()}")
    print(f"{'='*60}\n")

    # ── 步骤 1: 获取数据（保存到 data/raw） ────────────────────────
    df = get_stock_data(code, args.force_refresh)
    if df is None or df.empty:
        print(f"[ERROR] 无法获取 {code} 的数据")
        sys.exit(1)

    # ── 步骤 2: B1 策略检查 ────────────────────────────────────────
    print(f"\n[步骤2] 正在运行 B1 策略检查...")
    b1_result = check_b1_strategy(df, config_path)
    print(f"[INFO] B1 检查: {b1_result['reason']}")

    # ── 步骤 3: 导出 K 线图 ────────────────────────────────────────
    chart_dir = _resolve_path("data", "kline", "single")
    chart_path = chart_dir / f"{code}_day.jpg"

    export_success = export_chart(df, code, chart_path)

    # ── 步骤 4: LLM 分析 ───────────────────────────────────────────
    llm_result = None
    if not args.skip_llm and export_success:
        llm_result = analyze_with_llm(code, chart_path, args.model, prompt)

    # ── 步骤 5: 生成报告 ───────────────────────────────────────────
    report_dir = _resolve_path("data", "review", "single")
    report_path = report_dir / f"{code}.json"

    generate_report(code, b1_result, llm_result, report_path)
    print_report(code, b1_result, llm_result)

    print(f"\n[OK] 分析完成！")
    print(f"   数据文件: {_resolve_path('data', 'raw', f'{code}.csv')}")
    print(f"   图表文件: {chart_path}")
    print(f"   报告文件: {report_path}")


if __name__ == "__main__":
    main()
