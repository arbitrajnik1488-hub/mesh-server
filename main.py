from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx, os
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

H = {"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36", "Accept": "application/json", "Content-Type": "application/json"}

@app.route("/")
def index():
    return jsonify({"status": "ok"})

@app.route("/auth", methods=["POST"])
def auth():
    b = request.json or {}
    login = b.get("login", "").strip()
    password = b.get("password", "").strip()
    if not login or not password:
        return jsonify({"error": "Введи логин и пароль"}), 400

    for attempt in [
        lambda: httpx.post("https://school.mos.ru/v3/auth/sudir/auth", json={"login": login, "password": password}, headers=H, timeout=12, follow_redirects=True),
        lambda: httpx.post("https://authedu.mosreg.ru/v3/auth/kauth/callback", json={"login": login, "password_plain": password, "auth_type": "password_plain"}, headers=H, timeout=12, follow_redirects=True),
    ]:
        try:
            r = attempt()
            if r.status_code == 200:
                data = r.json()
                token = data.get("token") or data.get("access_token")
                if token:
                    return jsonify({"token": token, **fetch_profile(token)})
        except Exception:
            pass

    try:
        r = httpx.post("https://login.mos.ru/sps/oauth/ae",
            data={"grant_type": "password", "client_id": "dnevnik.mos.ru", "username": login, "password": password, "scope": "openid profile"},
            headers={**H, "Content-Type": "application/x-www-form-urlencoded"}, timeout=12, follow_redirects=True)
        if r.status_code == 200:
            token = r.json().get("access_token")
            if token:
                return jsonify({"token": token, **fetch_profile(token)})
        return jsonify({"error": "Неверный логин или пароль. Используй данные от dnevnik.mos.ru"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def fetch_profile(token):
    h = {**H, "Authorization": f"Bearer {token}", "auth-token": token}
    try:
        r = httpx.get("https://school.mos.ru/api/family/mobile/v1/profile", headers=h, timeout=10)
        d = r.json()
        children = d.get("children") or []
        profile = d.get("profile") or d
        if children:
            c = children[0]
            return {"student_id": str(c.get("id") or ""), "name": f"{c.get('first_name','')} {c.get('last_name','')}".strip(), "class": c.get("class_name") or "", "school": (c.get("school") or {}).get("name") or ""}
        return {"student_id": str(profile.get("id") or ""), "name": f"{profile.get('first_name','')} {profile.get('last_name','')}".strip(), "class": "", "school": ""}
    except Exception:
        return {"student_id": "", "name": "Ученик", "class": "", "school": ""}

@app.route("/homeworks")
def homeworks():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    sid = request.args.get("student_id", "")
    if not token:
        return jsonify({"error": "Нет токена"}), 401
    h = {**H, "Authorization": f"Bearer {token}", "auth-token": token}
    today = datetime.now().strftime("%Y-%m-%d")
    week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        r = httpx.get("https://school.mos.ru/api/family/mobile/v1/homeworks", headers=h, params={"student_id": sid, "begin_prepared_date": today, "end_prepared_date": week}, timeout=12)
        d = r.json()
        items = d if isinstance(d, list) else (d.get("payload") or d.get("homeworks") or [])
        return jsonify({"homeworks": [x for x in map(parse_hw, items) if x]})
    except Exception as e:
        return jsonify({"error": str(e), "homeworks": []}), 500

def parse_hw(item):
    try:
        subj = item.get("subject_name") or (item.get("subject") or {}).get("name") or "Предмет"
        desc = item.get("description") or (item.get("homework") or {}).get("description") or ""
        raw = str(item).lower()
        typ = "cdz" if any(x in raw for x in ["цдз","challenge","cdz"]) else "test"
        return {"id": item.get("homework_entry_student_id") or item.get("id") or "", "subject": subj, "title": item.get("title") or desc[:60] or "Задание", "description": desc, "date": item.get("date") or "", "type": typ, "questions_count": len(item.get("materials") or [])}
    except Exception:
        return None

@app.route("/submit", methods=["POST"])
def submit():
    b = request.json or {}
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    hw_id = b.get("homework_id", "")
    ans = b.get("answer", "")
    if not token or not hw_id:
        return jsonify({"error": "Нет данных"}), 400
    h = {**H, "Authorization": f"Bearer {token}", "auth-token": token}
    for url, payload in [
        ("https://uchebnik.mos.ru/webtests/exam/rest/secure/challenge/task/answer", {"homework_entry_student_id": hw_id, "answer": ans, "@answer_type": "answer/free"}),
        (f"https://school.mos.ru/api/family/mobile/v1/homeworks/{hw_id}/answer", {"answer": ans}),
    ]:
        try:
            r = httpx.post(url, json=payload, headers=h, timeout=10)
            if r.status_code in (200, 201, 204):
                return jsonify({"ok": True})
        except Exception:
            pass
    return jsonify({"ok": False, "note": "Задание не поддерживает автоответ"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
