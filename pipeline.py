#!/Users/niu/.workbuddy/binaries/python/versions/3.14.3/bin/python3
"""
AI Daily News — 主调度器

串联 4 层流水线，支持从任意层开始 / 单层重跑。

用法：
    python pipeline.py                    # 完整运行 4 层
    python pipeline.py --from layer2      # 从 Layer 2 开始（使用已有 raw.json）
    python pipeline.py --only layer1      # 只运行 Layer 1
    python pipeline.py --date 2026-04-12  # 指定日期（重跑历史）
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

# 项目根目录
ROOT_DIR = Path(__file__).parent
console = Console()


def load_config() -> dict:
    """加载全局配置文件 config.yaml"""
    config_path = ROOT_DIR / "config.yaml"
    if not config_path.exists():
        console.print("[red]❌ config.yaml 不存在，请先创建配置文件[/red]")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_data_dir(config: dict, date_str: str) -> Path:
    """确保当日数据目录存在"""
    data_dir = ROOT_DIR / config["global"]["data_dir"] / date_str
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def run_layer1(config: dict, data_dir: Path):
    """Layer 1: 收集"""
    from layers.collector import run_collector

    console.print(Panel("🔍 Layer 1: 收集", style="cyan bold"))
    result = run_collector(config, data_dir)
    console.print(
        f"  ✅ 采集完成: 共 {result['stats']['total']} 篇文章 → raw.json"
    )
    return result


def run_layer2(config: dict, data_dir: Path):
    """Layer 2: 筛选"""
    from layers.filter import run_filter

    console.print(Panel("🔬 Layer 2: 筛选", style="yellow bold"))
    date_str = data_dir.name
    result = run_filter(date=date_str, config=config)
    if "error" in result:
        raise RuntimeError(result["error"])
    console.print(
        f"  ✅ 筛选完成: {result.get('input', '?')} → {result.get('after_filter', '?')} 篇入选"
    )
    return result


def run_layer3(config: dict, data_dir: Path):
    """Layer 3: 编辑"""
    from layers.editor import run_editor

    console.print(Panel("✍️  Layer 3: 编辑", style="green bold"))
    date_str = data_dir.name
    result = run_editor(date=date_str, config=config)
    if "error" in result:
        raise RuntimeError(result["error"])
    console.print(f"  ✅ 编辑完成: 日报已生成")
    return result


def run_layer4(config: dict, data_dir: Path):
    """Layer 4: 归档"""
    console.print(Panel("📦 Layer 4: 归档", style="magenta bold"))
    # TODO: 实现 layers/archiver.py
    console.print("  ⏳ Layer 4 尚未实现")
    return None


# 层注册表
LAYERS = {
    "layer1": run_layer1,
    "layer2": run_layer2,
    "layer3": run_layer3,
    "layer4": run_layer4,
}

LAYER_ORDER = ["layer1", "layer2", "layer3", "layer4"]


def main():
    parser = argparse.ArgumentParser(
        description="AI Daily News — 四层流水线调度器"
    )
    parser.add_argument(
        "--only",
        choices=LAYER_ORDER,
        help="只运行指定层（如 --only layer1）",
    )
    parser.add_argument(
        "--from",
        dest="from_layer",
        choices=LAYER_ORDER,
        help="从指定层开始运行（如 --from layer2）",
    )
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="指定日期（默认今天，格式 YYYY-MM-DD）",
    )
    args = parser.parse_args()

    # 加载环境变量
    load_dotenv(ROOT_DIR / ".env")

    # 加载配置
    config = load_config()
    date_str = args.date
    data_dir = ensure_data_dir(config, date_str)

    console.print(
        Panel(
            f"📰 AI Daily News Pipeline\n"
            f"📅 日期: {date_str}\n"
            f"📁 数据目录: {data_dir}",
            title="启动",
            style="bold blue",
        )
    )

    # 确定要运行的层
    if args.only:
        layers_to_run = [args.only]
    elif args.from_layer:
        start_idx = LAYER_ORDER.index(args.from_layer)
        layers_to_run = LAYER_ORDER[start_idx:]
    else:
        layers_to_run = LAYER_ORDER

    console.print(f"  🏃 将运行: {' → '.join(layers_to_run)}\n")

    # 依次运行各层
    for layer_name in layers_to_run:
        try:
            LAYERS[layer_name](config, data_dir)
            console.print()
        except Exception as e:
            console.print(f"  [red]❌ {layer_name} 运行失败: {e}[/red]")
            console.print(
                f"  [dim]💡 修复后可从此层重跑: python pipeline.py --from {layer_name} --date {date_str}[/dim]"
            )
            sys.exit(1)

    console.print("[green bold]🎉 Pipeline 运行完成！[/green bold]")


if __name__ == "__main__":
    main()
