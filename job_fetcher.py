import os
import json
import re
import requests
import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List

# ==============================
# LOAD ENV
# ==============================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = genai.Client(api_key=GEMINI_API_KEY)

RSS_URL = "https://remoteok.com/remote-dev-jobs.rss"

# ==============================
# SCHEMA
# ==============================

class RankedJob(BaseModel):
    id: int
    score: int = Field(..., ge=1, le=10)
    reason: str

class JobList(BaseModel):
    top_jobs: List[RankedJob]

# ==============================
# EXPERIENCE DETECTION
# ==============================

def extract_experience(text):
    match = re.search(r'(\d+)\s*\+?\s*years?', text.lower())
    return int(match.group(1)) if match else 0

# ==============================
# FINAL FILTER (STRICT + SMART)
# ==============================

def is_valid_job(title, description):
    text = (title + " " + description).lower()

    # ✅ MUST HAVE YOUR STACK
    if not any(k in text for k in [
        "react", "node", "express", "mongodb",
        "python", "full stack", "backend"
    ]):
        return False, "Not your stack"

    # ❌ REMOVE IRRELEVANT ROLES
    if any(x in text for x in [
        "wordpress", "salesforce", "security",
        "devops", "qa", "designer", "manager"
    ]):
        return False, "Irrelevant role"

    # ❌ HARD REJECT extreme roles
    if any(x in text for x in ["director", "vp", "chief"]):
        return False, "Too senior"

    # ⚠️ SOFT PENALTY (NOT REJECT)
    penalty = 0

    if "senior" in text:
        penalty += 2
    if "lead" in text:
        penalty += 2

    exp = extract_experience(text)
    if exp > 2:
        penalty += 2

    return True, f"Penalty={penalty}"

# ==============================
# SCRAPER
# ==============================

def scrape_description(url):
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        return soup.get_text(" ", strip=True)[:1000]
    except:
        return ""

# ==============================
# FETCH JOBS
# ==============================

def fetch_jobs():
    feed = feedparser.parse(RSS_URL)
    entries = feed.entries[:40]

    print(f"\n📥 Total jobs fetched: {len(entries)}\n")

    def process(i, entry):
        desc = scrape_description(entry.link)
        valid, reason = is_valid_job(entry.title, desc)

        print(f"🔍 {entry.title[:50]}...")
        print(f"   → {reason}")

        if valid:
            return {
                "id": i,
                "title": entry.title,
                "link": entry.link,
                "description": desc
            }
        return None

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(lambda x: process(*x), enumerate(entries)))

    jobs = [j for j in results if j]

    print(f"\n🎯 Jobs passed to AI: {len(jobs)}\n")

    return jobs[:10]  # small clean dataset

# ==============================
# AI RANKING
# ==============================

def ai_rank_jobs(jobs):
    prompt = """
You are a junior developer job recommender.

Rules:
- Prefer React, Node, Backend, Full Stack
- Prefer fresher / <=2 years
- Penalize senior roles
- Score strictly between 1–10
- Return top 5 job IDs only

JSON only.
"""

    config = types.GenerateContentConfig(
        system_instruction=prompt,
        response_mime_type="application/json",
        response_schema=JobList
    )

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=f"Jobs:\n{jobs}",
        config=config
    )

    return JobList(**json.loads(response.text))

# ==============================
# MAP RESULTS
# ==============================

def map_results(ai_result, jobs):
    job_map = {j["id"]: j for j in jobs}
    final = []

    for item in ai_result.top_jobs:
        j = job_map.get(item.id)
        if j:
            final.append({
                "title": j["title"],
                "link": j["link"],
                "score": item.score,
                "reason": item.reason
            })

    return final

# ==============================
# UI
# ==============================

def print_ui(jobs):
    print("\n" + "="*60)
    print("🔥 FILTERED JOBS (ONLY YOUR STACK)")
    print("="*60)

    if not jobs:
        print("\n😴 No matching jobs today")
        return

    for i, j in enumerate(jobs, 1):
        print(f"\n[{i}] 🧠 {j['title']}")
        print(f"   ⭐ {j['score']}/10")
        print(f"   🔗 {j['link']}")
        print(f"   💡 {j['reason']}")
        print("-"*60)

# ==============================
# TELEGRAM
# ==============================

def send_telegram(jobs):
    if not TELEGRAM_BOT_TOKEN:
        print("❌ Telegram not configured")
        return

    if not jobs:
        msg = "😴 No matching jobs today"
    else:
        msg = "🔥 Job Alerts 🚀\n\n"
        for j in jobs:
            msg += f"🧠 {j['title']}\n⭐ {j['score']}/10\n🔗 {j['link']}\n\n"

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    )

# ==============================
# MAIN
# ==============================

if __name__ == "__main__":
    print("🚀 Running Smart Job Finder...\n")

    jobs = fetch_jobs()

    if not jobs:
        print("❌ No matching stack jobs found")
        send_telegram([])
        exit()

    print("\n🤖 AI Ranking...\n")

    ai_result = ai_rank_jobs(jobs)

    final_jobs = map_results(ai_result, jobs)

    print_ui(final_jobs)

    send_telegram(final_jobs)