import os
import json
import requests
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
OR_HEADERS = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
OR_MODEL = "openai/gpt-4o-mini"
AI_JOB_LIMIT = 50

# ==============================
# API SOURCES
# ==============================

def fetch_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=15)
        data = r.json()
        for item in data[1:]:
            jobs.append({
                "title": item.get("position", ""),
                "company": item.get("company", ""),
                "description": (item.get("description") or "")[:800],
                "link": item.get("url", ""),
                "source": "RemoteOK",
            })
    except Exception as e:
        print(f"   ⚠ RemoteOK: {e}")
    print(f"   ✅ RemoteOK: {len(jobs)} jobs")
    return jobs

def fetch_remotive():
    jobs = []
    try:
        r = requests.get("https://remotive.com/api/remote-jobs?category=software-dev&limit=30", headers=HEADERS, timeout=15)
        data = r.json()
        for j in data.get("jobs", []):
            jobs.append({
                "title": j.get("title", ""),
                "company": j.get("company_name", ""),
                "description": (j.get("description") or "")[:800],
                "link": j.get("url", ""),
                "source": "Remotive",
            })
    except Exception as e:
        print(f"   ⚠ Remotive: {e}")
    print(f"   ✅ Remotive: {len(jobs)} jobs")
    return jobs

def fetch_jobicy():
    jobs = []
    try:
        r = requests.get("https://jobicy.com/api/v2/remote-jobs?count=20", headers=HEADERS, timeout=15)
        data = r.json()
        for j in data.get("jobs", []):
            jobs.append({
                "title": j.get("jobTitle", ""),
                "company": j.get("companyName", ""),
                "description": "",
                "link": j.get("url", ""),
                "source": "Jobicy",
            })
    except Exception as e:
        print(f"   ⚠ Jobicy: {e}")
    print(f"   ✅ Jobicy: {len(jobs)} jobs")
    return jobs

def fetch_himalayas():
    jobs = []
    try:
        r = requests.get("https://himalayas.app/jobs/api?limit=20", headers=HEADERS, timeout=15)
        data = r.json()
        for j in data.get("jobs", []):
            jobs.append({
                "title": j.get("title", ""),
                "company": j.get("company", {}).get("name", ""),
                "description": (j.get("excerpt") or "")[:800],
                "link": j.get("url", ""),
                "source": "Himalayas",
            })
    except Exception as e:
        print(f"   ⚠ Himalayas: {e}")
    print(f"   ✅ Himalayas: {len(jobs)} jobs")
    return jobs

# ==============================
# FETCH ALL
# ==============================

def fetch_jobs():
    print("\n🌐 Fetching remote jobs from APIs...\n")

    all_jobs = []
    sources = [fetch_remoteok, fetch_remotive, fetch_jobicy, fetch_himalayas]

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(s): s.__name__ for s in sources}
        for f in as_completed(futures):
            all_jobs.extend(f.result())

    print(f"\n📥 Total jobs collected: {len(all_jobs)}")
    return all_jobs

# ==============================
# AI RANKING
# ==============================

def ai_rank_jobs(jobs):
    # Send compact job info (no descriptions) to save tokens
    compact = [{"id": j["id"], "title": j["title"], "company": j["company"], "source": j["source"]} for j in jobs[:AI_JOB_LIMIT]]

    prompt = """You are a junior developer job recommender.

Rules:
- Prefer React, Node, Backend, Full Stack, MERN stack jobs
- Prefer fresher / <=2 years experience
- Penalize senior, director, VP, chief, lead roles
- Score strictly between 1-10

Return JSON: {"top_jobs": [{"id": int, "score": int, "reason": "why it fits"}]}
Pick the top 5 most suitable jobs only.
"""

    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=OR_HEADERS,
        json={
            "model": OR_MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Jobs:\n{json.dumps(compact, indent=2)}"},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 500,
        },
        timeout=60,
    )
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])

# ==============================
# MAP RESULTS
# ==============================

def map_results(ai_result, jobs):
    job_map = {j["id"]: j for j in jobs}
    items = ai_result.get("top_jobs") or ai_result.get("jobs") or []
    final = []
    for item in items:
        j = job_map.get(item["id"])
        if j:
            final.append({
                "title": j["title"],
                "company": j["company"],
                "link": j["link"],
                "source": j["source"],
                "score": item["score"],
                "reason": item["reason"],
            })
    return final

# ==============================
# TELEGRAM
# ==============================

def send_telegram(jobs):
    if not TELEGRAM_BOT_TOKEN:
        print("❌ Telegram not configured")
        return

    if not jobs:
        msg = "😴 No matching remote jobs found today."
    else:
        msg = "🔥 <b>AI Remote Jobs</b>\n\n"
        for j in jobs:
            src_emoji = {"RemoteOK": "🌐", "Remotive": "💼", "Jobicy": "📡", "Himalayas": "🏔️"}.get(j["source"], "📌")
            msg += f"{src_emoji} <b>{j['title'][:60]}</b>\n"
            msg += f"   🏢 {j['company'][:30]}\n"
            msg += f"   ⭐ {j['score']}/10 — {j['reason'][:80]}\n"
            if j["link"]:
                msg += f"   🔗 <a href='{j['link']}'>Apply</a>\n"
            msg += "\n"

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
    )
    print("📬 Telegram sent")

# ==============================
# MAIN
# ==============================

if __name__ == "__main__":
    print("🤖 AI Job Agent — Multi-API\n")

    all_jobs = fetch_jobs()

    if not all_jobs:
        print("❌ No jobs found")
        send_telegram([])
        exit()

    enriched = []
    for i, j in enumerate(all_jobs):
        j["id"] = i
        enriched.append(j)

    print("\n🤖 AI Ranking...\n")
    ai_result = ai_rank_jobs(enriched)
    final_jobs = map_results(ai_result, enriched)

    send_telegram(final_jobs)
    print(f"\n✅ Done — {len(final_jobs)} AI-ranked jobs sent")
