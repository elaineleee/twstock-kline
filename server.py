"""Flask app: serves the daily brief JSON, pre-rendered Plotly chart HTML,
and the static front-end (PWA). Runs locally or behind cloudflared."""
from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, send_from_directory

ROOT = Path(__file__).parent
BRIEFS_DIR = ROOT / "data" / "briefs"
CHARTS_DIR = ROOT / "data" / "charts"

app = Flask(__name__, static_folder="static", template_folder="templates")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/manifest.json")
def manifest():
    return send_from_directory(app.static_folder, "manifest.json")


@app.route("/api/brief/<int:size>")
def api_brief(size: int):
    if size not in (50, 100, 200, 300):
        abort(404, description="universe size must be 50/100/200/300")
    p = BRIEFS_DIR / f"brief_{size}.json"
    if not p.exists():
        abort(503, description=f"brief_{size}.json not generated yet — run morning_brief.py")
    return app.response_class(p.read_text(), mimetype="application/json")


@app.route("/charts/<path:filename>")
def chart_file(filename: str):
    return send_from_directory(CHARTS_DIR, filename)


@app.errorhandler(404)
def _404(e):
    return jsonify({"error": str(e.description)}), 404


@app.errorhandler(503)
def _503(e):
    return jsonify({"error": str(e.description)}), 503


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)
