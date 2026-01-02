import pandas as pd
import numpy as np
from pathlib import Path
import seaborn as sns
import matplotlib.pyplot as plt

FILE = Path("用户交易记录20251230113346.xlsx")
OUT_DIR = Path("outputs")
OUT_DIR.mkdir(exist_ok=True)

TIME_KEYS = ["交易时间", "时间", "日期", "发生时间", "消费时间"]
AMOUNT_KEYS = ["交易金额", "金额", "消费金额", "支出", "收入"]
MERCHANT_KEYS = ["交易地点", "商户", "商家", "门店", "地点", "对方户名"]
EVENT_KEYS = ["交易事件", "交易类型", "事件", "类型"]

TARGET_MERCHANT_NAME = "紫荆公寓16号楼"
TARGET_MERCHANT_PATTERN = r"紫荆公寓\s*16\s*号楼"
SMALL_AMOUNT_THRESHOLD = 0.1
SMALL_AMOUNT_GAP_MINUTES = 20

WEEKDAY_ORDER = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
PERIOD_ORDER = ["上午", "下午", "晚上", "深夜"]


def find_header_row(raw: pd.DataFrame) -> int:
    for i, row in raw.iterrows():
        cells = [str(x) for x in row.tolist()]

        def find(keys):
            for cell in cells:
                for k in keys:
                    if k in cell:
                        return True
            return False

        if find(TIME_KEYS) and find(AMOUNT_KEYS) and find(MERCHANT_KEYS):
            return i
    raise ValueError("未找到包含时间/金额/商户列的表头")


def match_col(columns, keys):
    for c in columns:
        for k in keys:
            if k in c:
                return c
    return None


def load_and_clean(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None)
    header_idx = find_header_row(raw)
    header = raw.iloc[header_idx].astype(str).str.strip()
    df = raw.iloc[header_idx + 1 :].copy()
    df.columns = header
    df = df.dropna(how="all")

    time_col = match_col(df.columns, TIME_KEYS)
    amount_col = match_col(df.columns, AMOUNT_KEYS)
    merchant_col = match_col(df.columns, MERCHANT_KEYS)
    event_col = match_col(df.columns, EVENT_KEYS)

    if not time_col or not amount_col or not merchant_col:
        raise ValueError("无法识别时间/金额/商户列")

    df = df.rename(columns={time_col: "time", amount_col: "amount", merchant_col: "merchant"})
    if event_col:
        df = df.rename(columns={event_col: "event"})

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["merchant"] = df["merchant"].astype(str)

    df = df.dropna(subset=["time", "amount", "merchant"])
    df = df[df["amount"] > 0]

    if "event" in df.columns:
        df = df[df["event"].astype(str).str.contains("消费", na=False)]

    return df


def filter_bath_records(df: pd.DataFrame) -> pd.DataFrame:
    bath_df = df[df["merchant"].str.contains(TARGET_MERCHANT_PATTERN, na=False)].copy()
    if bath_df.empty:
        raise ValueError("未找到紫荆公寓16号楼相关洗浴记录")
    bath_df["merchant"] = TARGET_MERCHANT_NAME
    return bath_df


def merge_sessions(df: pd.DataFrame, max_gap_minutes: int = 10) -> pd.DataFrame:
    df = df.sort_values("time").reset_index(drop=True)
    time_diff = df["time"].diff().dt.total_seconds().div(60)
    new_session = time_diff.isna() | (time_diff > max_gap_minutes)
    session_id = new_session.cumsum()

    merged = (
        df.groupby(session_id)
        .agg(start_time=("time", "min"), end_time=("time", "max"), amount=("amount", "sum"))
        .reset_index(drop=True)
    ).sort_values("start_time").reset_index(drop=True)

    cleaned_rows = []
    i = 0
    while i < len(merged):
        row = merged.loc[i].copy()
        if row["amount"] <= SMALL_AMOUNT_THRESHOLD:
            prev_idx = len(cleaned_rows) - 1
            next_idx = i + 1 if i + 1 < len(merged) else None
            gap_prev = None
            gap_next = None
            if prev_idx >= 0:
                gap_prev = (row["start_time"] - cleaned_rows[prev_idx]["end_time"]).total_seconds() / 60
            if next_idx is not None:
                next_row = merged.loc[next_idx]
                gap_next = (next_row["start_time"] - row["end_time"]).total_seconds() / 60

            target = None
            if gap_prev is not None and gap_prev <= SMALL_AMOUNT_GAP_MINUTES:
                target = "prev"
            if gap_next is not None and gap_next <= SMALL_AMOUNT_GAP_MINUTES:
                if target is None or gap_next < gap_prev:
                    target = "next"

            if target == "prev":
                cleaned_rows[prev_idx]["amount"] += row["amount"]
                cleaned_rows[prev_idx]["end_time"] = max(cleaned_rows[prev_idx]["end_time"], row["end_time"])
                i += 1
                continue
            if target == "next":
                merged.loc[next_idx, "amount"] += row["amount"]
                merged.loc[next_idx, "start_time"] = min(merged.loc[next_idx, "start_time"], row["start_time"])
                merged.loc[next_idx, "end_time"] = max(merged.loc[next_idx, "end_time"], row["end_time"])
                i += 1
                continue
            i += 1
            continue

        cleaned_rows.append(row.to_dict())
        i += 1

    cleaned = pd.DataFrame(cleaned_rows)
    cleaned["time"] = cleaned["start_time"]
    cleaned["duration_min"] = (
        (cleaned["end_time"] - cleaned["start_time"]).dt.total_seconds().div(60)
    )
    return cleaned


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = df["time"].dt.date
    df["weekday"] = df["time"].dt.weekday.map({
        0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"
    })
    df["hour"] = df["time"].dt.hour

    def bath_period(hour: int) -> str:
        if 6 <= hour < 12:
            return "上午"
        if 12 <= hour < 18:
            return "下午"
        if 18 <= hour < 22:
            return "晚上"
        return "深夜"

    df["bath_period"] = df["hour"].apply(bath_period)
    return df


def setup_style():
    sns.set_theme(style="whitegrid")
    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Arial Unicode MS", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def add_bar_labels(ax, fmt="{:.0f}", padding=3):
    for container in ax.containers:
        values = []
        for v in container.datavalues:
            if v is None or (isinstance(v, float) and not np.isfinite(v)):
                values.append("")
            else:
                values.append(fmt.format(v))
        ax.bar_label(container, labels=values, padding=padding, fontsize=9)


def save_fig(path: Path):
    plt.tight_layout()
    plt.savefig(path, dpi=200)
    plt.close()


def main():
    if not FILE.exists():
        raise FileNotFoundError(f"找不到文件: {FILE}")

    df = load_and_clean(FILE)
    df = filter_bath_records(df)
    df = merge_sessions(df, max_gap_minutes=10)

    df = df[df["time"].dt.hour >= 6]
    if df.empty:
        raise ValueError("过滤 0:00-6:00 时段后无有效洗浴记录")

    df = add_features(df)
    setup_style()

    total_sessions = len(df)
    total_amount = df["amount"].sum()
    avg_amount = df["amount"].mean()
    median_amount = df["amount"].median()

    period_count = df["bath_period"].value_counts().reindex(PERIOD_ORDER)
    min_hour = int(df["hour"].min())
    max_hour = int(df["hour"].max())
    heatmap_hours = list(range(min_hour, max_hour + 1))
    heatmap_data = (
        df.pivot_table(index="weekday", columns="hour", values="amount", aggfunc="count")
        .reindex(WEEKDAY_ORDER)
        .reindex(columns=heatmap_hours, fill_value=0)
    )

    max_amount_row = df.loc[df["amount"].idxmax()]
    min_amount_row = df.loc[df["amount"].idxmin()]

    unique_dates = pd.Series(sorted(pd.to_datetime(df["date"].unique())))
    if len(unique_dates) >= 2:
        gaps = unique_dates.diff().dt.days.dropna()
        max_gap_days = int(gaps.max())
        min_gap_days = int(gaps.min())
    else:
        max_gap_days = None
        min_gap_days = None

    # Figure 1: heatmap
    plt.figure(figsize=(12, 4.8))
    sns.heatmap(heatmap_data, cmap="YlGnBu", linewidths=0.3, linecolor="white")
    plt.title("星期-小时洗澡热力图（次数）")
    plt.xlabel("小时")
    plt.ylabel("星期")
    save_fig(OUT_DIR / "fig_01_weekday_hour_heatmap.png")

    # Figure 2: bath period count
    plt.figure(figsize=(8.6, 4.8))
    ax = sns.barplot(
        x=period_count.index,
        y=period_count.values,
        hue=period_count.index,
        palette="Blues_d",
        dodge=False,
    )
    if ax.legend_:
        ax.legend_.remove()
    add_bar_labels(ax, fmt="{:.0f}")
    plt.title("洗澡时段分布")
    plt.xlabel("时段")
    plt.ylabel("次数")
    save_fig(OUT_DIR / "fig_02_bath_period_count.png")

    # Figure 3: amount distribution
    plt.figure(figsize=(8.6, 4.8))
    sns.histplot(df["amount"], bins=25, kde=True, color="#C44E52")
    plt.title("洗澡开支分布")
    plt.xlabel("金额（元）")
    plt.ylabel("频次")
    save_fig(OUT_DIR / "fig_03_amount_distribution.png")

    report_lines = []
    report_lines.append("# 2025 年度洗刷刷自由报告")
    report_lines.append("")
    report_lines.append(
        "本报告自动识别时间、金额与商户列，并精准筛选商户包含“紫荆公寓16号楼”的洗浴记录。"
        "规则：0:00-6:00 无热水不计入；10 分钟以内多笔交易合并为 1 次洗澡；"
        "若出现 <=0.10 元小额，则与前后 20 分钟内的洗澡合并，否则剔除。"
        f"最终保留 {total_sessions} 次洗澡记录，累计 {total_amount:.2f} 元，"
        f"单次均价 {avg_amount:.2f} 元，中位数 {median_amount:.2f} 元。"
    )
    report_lines.append("")
    report_lines.append("## 极值分析")
    report_lines.append(
        "- 最大洗澡开支：**{}** 于 **{}**（{:.2f} 元）。".format(
            TARGET_MERCHANT_NAME,
            max_amount_row["time"].strftime("%Y-%m-%d %H:%M:%S"),
            max_amount_row["amount"],
        )
    )
    report_lines.append(
        "- 最小洗澡开支：**{}** 于 **{}**（{:.2f} 元）。".format(
            TARGET_MERCHANT_NAME,
            min_amount_row["time"].strftime("%Y-%m-%d %H:%M:%S"),
            min_amount_row["amount"],
        )
    )
    if max_gap_days is not None:
        report_lines.append(f"- 间隔最长的洗澡天数：**{max_gap_days}** 天。")
        report_lines.append(f"- 间隔最小的洗澡天数：**{min_gap_days}** 天。")
    else:
        report_lines.append("- 洗澡天数间隔：记录不足以计算。")
    report_lines.append("")
    report_lines.append("## 输出图表")
    report_lines.append("- fig_01_weekday_hour_heatmap.png")
    report_lines.append("- fig_02_bath_period_count.png")
    report_lines.append("- fig_03_amount_distribution.png")

    report_path = OUT_DIR / "2025_bath_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print(f"已生成 {len(report_lines)} 行报告文本 -> {report_path}")
    print(f"图表输出目录: {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
