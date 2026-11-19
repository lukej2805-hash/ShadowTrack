"""Local web UI for ShadowTrack.

Run:  python app.py   then open http://127.0.0.1:5000
Binds to localhost only, so it isn't reachable from other devices.
"""
import asyncio
import json

from flask import Flask, jsonify, request, send_from_directory

import lookup

app = Flask(__name__, static_folder="static")


def manual_links(username):
    if not username:
        return []
    with open(lookup.MANUAL_FILE, encoding="utf-8") as f:
        sites = json.load(f)
    return [{"site": s["name"], "url": s["url"].format(username)} for s in sites]


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.post("/api/search")
def api_search():
    body = request.get_json(silent=True) or {}
    query = str(body.get("query", "")).strip()
    region = str(body.get("region", "GB")).strip().upper() or "GB"
    if not query:
        return jsonify(error="Enter a username, email or phone number."), 400
    if len(query) > 200:
        return jsonify(error="That input is too long."), 400

    kind = lookup.detect_type(query)
    if kind == "username":
        data = asyncio.run(lookup.search_username(query))
        manual = manual_links(query)
    elif kind == "email":
        data = asyncio.run(lookup.search_email(query))
        manual = manual_links(data["username_guess"])
    else:
        data = lookup.search_phone(query, region)
        manual = []
    return jsonify(type=kind, data=data, manual=manual)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
