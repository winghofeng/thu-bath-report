import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Optional

DEFAULT_INPUT = Path("用户交易记录20251230113346.xlsx")
DEFAULT_OUTPUT_DIR = Path("outputs")

TIME_KEYS = ["交易时间", "时间", "日期", "发生时间", "消费时间"]
AMOUNT_KEYS = ["交易金额", "金额", "消费金额", "支出", "收入"]
MERCHANT_KEYS = ["交易地点", "商户", "商家", "门店", "地点", "对方户名"]
EVENT_KEYS = ["交易事件", "交易类型", "事件", "类型"]

DEFAULT_MERCHANT_KEYWORDS = ["公寓", "宿舍"]
SMALL_AMOUNT_THRESHOLD = 0.1
SMALL_AMOUNT_GAP_MINUTES = 20
WATER_FEE_PER_TON = 23.0

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


def extract_merchants(input_path: Path) -> list:
    df = load_and_clean(input_path)
    merchants = sorted(df["merchant"].dropna().astype(str).unique().tolist())
    return merchants


def default_merchants(merchants: list) -> list:
    defaults = [m for m in merchants if any(k in m for k in DEFAULT_MERCHANT_KEYWORDS)]
    return defaults


def filter_bath_records(df: pd.DataFrame, merchant_filters: list) -> pd.DataFrame:
    bath_df = df[df["merchant"].isin(merchant_filters)].copy()
    if bath_df.empty:
        raise ValueError("未找到所选宿舍相关洗浴记录")
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

    if not cleaned_rows:
        return pd.DataFrame(
            columns=["start_time", "end_time", "amount", "merchant", "time", "duration_min"]
        )

    cleaned = pd.DataFrame(cleaned_rows)
    if "merchant" in df.columns:
        cleaned["merchant"] = df["merchant"].iloc[0]
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


def analyze_bath_report(input_path: Path, output_dir: Path, merchant_filters: Optional[List[str]] = None) -> dict:
    if not input_path.exists():
        raise FileNotFoundError(f"找不到文件: {input_path}")

    df = load_and_clean(input_path)
    all_merchants = sorted(df["merchant"].dropna().astype(str).unique().tolist())
    if merchant_filters is None:
        merchant_filters = default_merchants(all_merchants)
    else:
        merchant_filters = [m for m in merchant_filters if m in all_merchants]

    if not merchant_filters:
        raise ValueError("未找到可用宿舍名，请手动选择宿舍名称")

    df = filter_bath_records(df, merchant_filters)
    merged_frames = []
    for _, group in df.groupby("merchant"):
        merged_frames.append(merge_sessions(group, max_gap_minutes=10))
    df = pd.concat(merged_frames, ignore_index=True)
    if df.empty:
        raise ValueError("似乎没有洗澡记录，请检查选择的宿舍是否仅为打水记录。")

    df = df[df["time"].dt.hour >= 6]
    if df.empty:
        raise ValueError("似乎没有洗澡记录，请检查选择的宿舍是否仅为打水记录。")

    df = add_features(df)

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
        max_gap_idx = gaps.idxmax()
        max_gap_start = unique_dates.loc[max_gap_idx - 1].date()
        max_gap_end = unique_dates.loc[max_gap_idx].date()
    else:
        max_gap_days = None
        max_gap_start = None
        max_gap_end = None

    heatmap_matrix = heatmap_data.fillna(0).astype(int).values.tolist()
    heatmap_weekdays = heatmap_data.index.tolist()

    period_series = period_count.fillna(0).astype(int)
    period_labels = period_series.index.tolist()
    period_values = period_series.values.tolist()

    amount_min = df["amount"].min()
    amount_max = df["amount"].max()
    bin_start = np.floor(amount_min * 10) / 10
    bin_end = np.ceil(amount_max * 10) / 10
    if bin_end <= bin_start:
        bin_end = bin_start + 0.1
    bins = np.arange(bin_start, bin_end + 0.1, 0.1)
    hist_counts, hist_edges = np.histogram(df["amount"], bins=bins)
    hist_counts = hist_counts.tolist()
    hist_edges = hist_edges.tolist()

    report_lines = []
    report_lines.append("# 2025 年度洗刷刷自由报告")
    report_lines.append("")
    water_tons = total_amount / WATER_FEE_PER_TON if WATER_FEE_PER_TON else 0
    merchant_text = "、".join(merchant_filters)
    report_lines.append("## 统计信息")
    report_lines.append(
        f"- {total_sessions} 次洗澡记录，累计 {total_amount:.2f} 元，单次均价 {avg_amount:.2f} 元，中位数 {median_amount:.2f} 元。"
    )
    report_lines.append(f"- 折算用水约 **{water_tons:.2f} 吨**（水费 {WATER_FEE_PER_TON:.2f} 元/吨）。")
    report_lines.append("")
    report_lines.append("## 极值信息")
    report_lines.append(
        "- 最大洗澡开支：**{}** 于 **{}**（{:.2f} 元）。".format(
            max_amount_row["merchant"],
            max_amount_row["time"].strftime("%Y-%m-%d %H:%M:%S"),
            max_amount_row["amount"],
        )
    )
    report_lines.append(
        "- 最小洗澡开支：**{}** 于 **{}**（{:.2f} 元）。".format(
            min_amount_row["merchant"],
            min_amount_row["time"].strftime("%Y-%m-%d %H:%M:%S"),
            min_amount_row["amount"],
        )
    )
    if max_gap_days is not None:
        gap_line = f"- 间隔最长的洗澡天数：**{max_gap_days}** 天（{max_gap_start} -> {max_gap_end}）。"
        if max_gap_days > 2:
            gap_line += " 是不是出去玩啦？"
        report_lines.append(gap_line)
    else:
        report_lines.append("- 洗澡天数间隔：记录不足以计算。")
    report_lines.append("")
    report_lines.append("## 规则备注")
    report_lines.append(f"- 统计宿舍：{merchant_text}。")
    report_lines.append("- 0:00-6:00 无热水不计入。")
    report_lines.append("- 10 分钟以内多笔交易合并为 1 次洗澡；<=0.10 元小额与前后 20 分钟内洗澡合并，否则剔除。")
    report_md = "\n".join(report_lines)
    report_path = output_dir / "2025_bath_report.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")

    return {
        "report_path": report_path,
        "report_md": report_md,
        "min_hour": min_hour,
        "max_hour": max_hour,
        "heatmap": {
            "hours": heatmap_hours,
            "weekdays": heatmap_weekdays,
            "matrix": heatmap_matrix,
        },
        "period": {
            "labels": period_labels,
            "values": period_values,
        },
        "amount_distribution": {
            "counts": hist_counts,
            "edges": hist_edges,
        },
    }


def main():
    result = analyze_bath_report(DEFAULT_INPUT, DEFAULT_OUTPUT_DIR)
    print(f"已生成 {len(result['report_md'].splitlines())} 行报告文本 -> {result['report_path']}")
    print(f"输出目录: {DEFAULT_OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
