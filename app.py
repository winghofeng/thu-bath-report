from pathlib import Path
from typing import Optional
import uuid

from flask import Flask, jsonify, render_template, request

from generate_report import analyze_bath_report, default_merchants, extract_merchants

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/prepare", methods=["POST"])
def prepare():
    if "file" not in request.files:
        return jsonify({"error": "未找到上传文件"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "文件名为空"}), 400

    run_id = uuid.uuid4().hex[:8]
    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    upload_path = UPLOAD_DIR / f"{run_id}_{safe_name}"
    file.save(upload_path)

    try:
        merchants = extract_merchants(upload_path)
        defaults = default_merchants(merchants)
    except Exception as exc:  # pragma: no cover - passthrough for UI
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "run_id": run_id,
            "merchants": merchants,
            "defaults": defaults,
        }
    )


def find_upload_path(run_id: str) -> Optional[Path]:
    matches = list(UPLOAD_DIR.glob(f"{run_id}_*"))
    return matches[0] if matches else None


@app.route("/analyze", methods=["POST"])
def analyze():
    payload = request.get_json(silent=True) or {}
    run_id = payload.get("run_id")
    merchants = payload.get("merchants", [])
    if not run_id:
        return jsonify({"error": "缺少 run_id"}), 400

    upload_path = find_upload_path(run_id)
    if not upload_path or not upload_path.exists():
        return jsonify({"error": "未找到上传文件，请重新上传"}), 400

    run_output = OUTPUT_DIR / f"run_{run_id}"
    try:
        result = analyze_bath_report(upload_path, run_output, merchant_filters=merchants)
    except Exception as exc:  # pragma: no cover - passthrough for UI
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "run_id": run_id,
            "report_md": result["report_md"],
            "charts": {
                "heatmap": result["heatmap"],
                "period": result["period"],
                "amount_distribution": result["amount_distribution"],
            },
            "time_range": {
                "start_hour": result["min_hour"],
                "end_hour": result["max_hour"],
            },
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
