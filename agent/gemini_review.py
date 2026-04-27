"""
gemini_review.py
~~~~~~~~~~~~~~~~
使用 Google Gemini 对候选股票进行图表分析评分。
继承自 BaseReviewer 基础架构。

用法：
    python agent/gemini_review.py                                    # 批量分析候选列表
    python agent/gemini_review.py --config config/gemini_review.yaml   # 指定配置文件
    python agent/gemini_review.py --code 600519                       # 单股分析（茅台）

配置：
    默认读取 config/gemini_review.yaml。

环境变量：
    GEMINI_API_KEY  —— Google Gemini API Key（必填）

输出：
    ./data/review/{pick_date}/{code}.json   每支股票的评分 JSON
    ./data/review/{pick_date}/suggestion.json  汇总推荐建议（批量模式）
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
import yaml

from base_reviewer import BaseReviewer

# ────────────────────────────────────────────────
# 配置加载
# ────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _ROOT / "config" / "gemini_review.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    # 路径参数（相对路径默认基于项目根目录）
    "candidates": "data/candidates/candidates_latest.json",
    "kline_dir": "data/kline",
    "output_dir": "data/review",
    "prompt_path": "agent/prompt.md",
    # Gemini 模型参数
    "model": "gemini-3.1-pro-preview",
    "request_delay": 5,
    "skip_existing": False,
    "suggest_min_score": 4.0,
}


def _resolve_cfg_path(path_like: str | Path, base_dir: Path = _ROOT) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else (base_dir / p)


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    cfg_path = config_path or _DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"找不到配置文件：{cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = {**DEFAULT_CONFIG, **raw}

    # BaseReviewer 依赖这些路径字段为 Path 对象
    cfg["candidates"] = _resolve_cfg_path(cfg["candidates"])
    cfg["kline_dir"] = _resolve_cfg_path(cfg["kline_dir"])
    cfg["output_dir"] = _resolve_cfg_path(cfg["output_dir"])
    cfg["prompt_path"] = _resolve_cfg_path(cfg["prompt_path"])

    return cfg


def _find_latest_pick_date(kline_dir: Path) -> str | None:
    """在 kline_dir 中查找最新的日期目录。"""
    if not kline_dir.exists():
        return None

    date_dirs = [d for d in kline_dir.iterdir() if d.is_dir() and d.name.isdigit()]
    if not date_dirs:
        return None

    # 按日期排序，返回最新的
    date_dirs.sort(key=lambda x: x.name, reverse=True)
    return date_dirs[0].name


def _find_chart_in_date(kline_dir: Path, pick_date: str, code: str) -> Path | None:
    """在指定日期目录中查找股票的 K 线图。"""
    date_dir = kline_dir / pick_date

    # 尝试不同的文件名格式
    for ext in [".jpg", ".jpeg", ".png"]:
        chart = date_dir / f"{code}_day{ext}"
        if chart.exists():
            return chart

    return None


class GeminiReviewer(BaseReviewer):
    def __init__(self, config):
        super().__init__(config)

        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("[ERROR] 未找到环境变量 GEMINI_API_KEY，请先设置后重试。", file=sys.stderr)
            sys.exit(1)

        self.client = genai.Client(api_key=api_key)

    @staticmethod
    def image_to_part(path: Path) -> types.Part:
        """将图片文件转为 Gemini Part 对象。"""
        suffix = path.suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
        mime_type = mime_map.get(suffix, "image/jpeg")
        data = path.read_bytes()
        return types.Part.from_bytes(data=data, mime_type=mime_type)

    def review_stock(self, code: str, day_chart: Path, prompt: str) -> dict:
        """
        调用 Gemini API，对单支股票进行图表分析，返回解析后的 JSON 结果。
        """
        user_text = (
            f"股票代码：{code}\n\n"
            "以下是该股票的 **日线图**，请按照系统提示中的框架进行分析，"
            "并严格按照要求输出 JSON。"
        )

        parts: list[types.Part] = [
            types.Part.from_text(text="【日线图】"),
            self.image_to_part(day_chart),
            types.Part.from_text(text=user_text),
        ]

        response = self.client.models.generate_content(
            model=self.config.get("model", "gemini-3.1-pro-preview"),
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                system_instruction=prompt,
                temperature=0.2,
            ),
        )

        response_text = response.text
        if response_text is None:
            raise RuntimeError(f"Gemini 返回空响应，无法解析 JSON（code={code}）")

        result = self.extract_json(response_text)
        result["code"] = code  # 附加股票代码便于追溯
        return result

    def review_single_stock(self, code: str, pick_date: str | None = None) -> dict:
        """分析单只股票。"""
        # 确定 pick_date
        if pick_date is None:
            pick_date = _find_latest_pick_date(self.kline_dir)
            if pick_date is None:
                print("[ERROR] 未找到任何 K 线数据目录")
                sys.exit(1)
            print(f"[INFO] 使用最新日期: {pick_date}")

        # 查找图表
        day_chart = _find_chart_in_date(self.kline_dir, pick_date, code)
        if day_chart is None:
            print(f"[ERROR] 未找到股票 {code} 在日期 {pick_date} 的 K 线图")
            print(f"       查找路径: {self.kline_dir / pick_date}")
            sys.exit(1)

        print(f"[INFO] 股票代码: {code}")
        print(f"[INFO] K 线图: {day_chart}")

        # 创建输出目录
        out_dir = self.output_dir / pick_date
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{code}.json"

        # 跳过已存在的文件
        if out_file.exists() and self.config.get("skip_existing", False):
            print(f"[INFO] {code}.json 已存在，跳过分析")
            with open(out_file, encoding="utf-8") as f:
                return json.load(f)

        # 执行分析
        print(f"[INFO] 正在分析 {code} ...", end=" ", flush=True)
        try:
            result = self.review_stock(code, day_chart, self.prompt)
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print("完成")
            return result
        except Exception as e:
            print(f"失败: {e}")
            raise


def _print_single_result(result: dict):
    """打印单股分析结果。"""
    print(f"\n{'='*60}")
    print(f"  {result.get('code', 'N/A')} 分析结果")
    print(f"{'='*60}")

    scores = result.get("scores", {})
    print(f"\n【评分明细】")
    print(f"  趋势结构:     {scores.get('trend_structure', 'N/A')}/5")
    print(f"  价格位置:     {scores.get('price_position', 'N/A')}/5")
    print(f"  量价行为:     {scores.get('volume_behavior', 'N/A')}/5")
    print(f"  前期异动:     {scores.get('previous_abnormal_move', 'N/A')}/5")
    print(f"  ─────────────────────────")
    print(f"  总分:         {result.get('total_score', 'N/A')}/5")

    print(f"\n【研判结果】")
    print(f"  信号类型:     {result.get('signal_type', 'N/A')}")
    print(f"  判定:         {result.get('verdict', 'N/A')}")

    comment = result.get("comment", "")
    if comment:
        print(f"\n【点评】")
        print(f"  {comment}")

    print(f"\n{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Gemini 图表复评",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python agent/gemini_review.py                    # 批量分析候选列表
  python agent/gemini_review.py --code 600519       # 单股分析
        """,
    )
    parser.add_argument(
        "--config",
        default=str(_DEFAULT_CONFIG_PATH),
        help="配置文件路径（默认 config/gemini_review.yaml）",
    )
    parser.add_argument(
        "--code",
        help="指定单只股票代码进行分析（如 600519）",
    )
    parser.add_argument(
        "--date",
        help="指定选股日期（格式: YYYY-MM-DD，默认使用最新日期）",
    )
    args = parser.parse_args()

    config = load_config(Path(args.config))
    reviewer = GeminiReviewer(config)

    # 单股分析模式
    if args.code:
        result = reviewer.review_single_stock(args.code, args.date)
        _print_single_result(result)
        return

    # 批量分析模式
    reviewer.run()


if __name__ == "__main__":
    main()
