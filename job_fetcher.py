import os
import json
import re
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = genai.Client(api_key=GEMINI_API_KEY)

# ==============================
# SCHEMA
# ==============================

class RankedJob(BaseModel):
    id: int
    score: int = Field(..., ge=1, le=10)
    reason: str

class JobList(BaseModel):
    top_jobs: List[RankedJob]

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

# ==============================
# SCRAPERS
# ==============================

def scrape_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/remote-dev-jobs", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for tr in soup.select("tr.job"):
            title_el = tr.select_one("td.company h2 a")
            company_el = tr.select_one("td.company span.companyLink a")
            desc_el = tr.select_one("td.company div.description")
            link_el = tr.select_one("td.company a.preventLink")
            if title_el:
                title = title_el.get_text(strip=True)
                link = "https://remoteok.com" + (link_el.get("href") or title_el.get("href", ""))
                company = company_el.get_text(strip=True) if company_el else ""
                desc = desc_el.get_text(" ", strip=True)[:800] if desc_el else ""
                jobs.append({"title": title, "company": company, "description": desc, "link": link, "source": "RemoteOK"})
    except Exception as e:
        print(f"   ⚠ RemoteOK: {e}")
    print(f"   ✅ RemoteOK: {len(jobs)} jobs")
    return jobs

def scrape_weworkremotely():
    jobs = []
    try:
        r = requests.get("https://weworkremotely.com/remote-jobs/software-dev", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for li in soup.select("ul.jobs li:not(.view-all)"):
            a = li.select_one("a")
            if a:
                title_el = a.select_one("span.title")
                company_el = a.select_one("span.company")
                if title_el:
                    title = title_el.get_text(strip=True)
                    company = company_el.get_text(strip=True) if company_el else ""
                    link = "https://weworkremotely.com" + a.get("href", "")
                    jobs.append({"title": title, "company": company, "description": "", "link": link, "source": "WeWorkRemotely"})
    except Exception as e:
        print(f"   ⚠ WeWorkRemotely: {e}")
    print(f"   ✅ WeWorkRemotely: {len(jobs)} jobs")
    return jobs

def scrape_remotive():
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

# ==============================
# FETCH ALL
# ==============================

def fetch_jobs():
    print("\n🌐 Scraping remote job boards...\n")

    all_jobs = []
    scrapers = [scrape_remoteok, scrape_weworkremotely, scrape_remotive]

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(s): s.__name__ for s in scrapers}
        for f in as_completed(futures):
            all_jobs.extend(f.result())

    print(f"\n📥 Total jobs collected: {len(all_jobs)}")
    return all_jobs

# ==============================
# AI RANKING
# ==============================

def ai_rank_jobs(jobs):
    prompt = """
You are a junior developer job recommender.

Rules:
- Prefer React, Node, Backend, Full Stack, MERN stack
- Prefer fresher / <=2 years experience
- Penalize senior, director, VP, chief, lead roles
- Score strictly between 1–10
- Return top 5 job IDs only
- Give short reason why each job fits

JSON only.
"""

    config = types.GenerateContentConfig(
        system_instruction=prompt,
        response_mime_type="application/json",
        response_schema=JobList
    )

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=f"Jobs:\n{json.dumps(jobs, indent=2)}",
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
                "company": j["company"],
                "link": j["link"],
                "source": j["source"],
                "score": item.score,
                "reason": item.reason,
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
            src_emoji = {"RemoteOK": "🌐", "WeWorkRemotely": "🏢", "Remotive": "💼"}.get(j["source"], "📌")
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
    print("🤖 AI Job Agent — Web Scraper\n")

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
