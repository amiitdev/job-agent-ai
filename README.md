# 🚀 AI Job Agent — Smart Remote Job Finder 🤖

> ⚡ Fully automated AI-powered job hunting system
> 📡 Fetch → 🧠 Filter → 🤖 Rank → 📩 Notify (Telegram)
> ☁️ Runs 24/7 using GitHub Actions (no laptop needed)

---

# 🎯 What This Project Does

This project automatically:

* 🌐 Fetches latest remote jobs from RSS feeds
* 🧹 Filters only relevant roles (React / Node / Backend)
* 🚫 Removes senior & irrelevant jobs
* 🤖 Uses AI (Gemini) to rank best jobs
* 📩 Sends top jobs directly to Telegram
* ⏰ Runs automatically every hour/day (cloud cron)

---

# 🧠 System Architecture

```
        GitHub Actions (Cron) ⏰
                  ↓
          Python Script 🐍
                  ↓
        Job Scraper (RSS + HTML) 🌐
                  ↓
        Smart Filter Logic 🎯
                  ↓
        Gemini AI Ranking 🤖
                  ↓
        Telegram Bot Alert 📩
```

---

# 🔥 Features

* ✅ Fully automated (no manual run)
* ✅ AI-based job ranking
* ✅ No duplicate/spam alerts (with history)
* ✅ Works 24/7 (even if laptop OFF)
* ✅ Clean CLI + Telegram output
* ✅ Fast (parallel scraping)

---

# 🛠 Tech Stack

* 🐍 Python
* 🌐 feedparser + requests + BeautifulSoup
* 🤖 Google Gemini AI (`google-genai`)
* 📦 Pydantic (schema validation)
* ☁️ GitHub Actions (scheduler)
* 📩 Telegram Bot API

---

# ⚙️ Setup Guide

## 1️⃣ Clone Repo

```
git clone https://github.com/YOUR_USERNAME/job-agent-ai.git
cd job-agent-ai
```

---

## 2️⃣ Install Dependencies

```
pip install requests feedparser beautifulsoup4 python-dotenv google-genai pydantic
```

---

## 3️⃣ Create `.env`

```
GEMINI_API_KEY=your_api_key
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## 4️⃣ Run Locally

```
python job_fetcher.py
```

---

# 🤖 GitHub Actions (Automation)

Create file:

```
.github/workflows/job.yml
```

Paste:

```yaml
name: Job Fetcher

on:
  schedule:
    - cron: "0 * * * *"   # every hour
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - run: |
          pip install requests feedparser beautifulsoup4 python-dotenv google-genai pydantic

      - run: python job_fetcher.py
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

---

# 🔐 Add GitHub Secrets

Go to:

```
Settings → Secrets and variables → Actions
```

Add:

* `GEMINI_API_KEY`
* `TELEGRAM_BOT_TOKEN`
* `TELEGRAM_CHAT_ID`

---

# 📩 Telegram Setup

1. Message `@BotFather`
2. Create bot → get token
3. Send message to your bot
4. Get chat ID:

```
https://api.telegram.org/bot<TOKEN>/getUpdates
```

---

# 🧪 Example Output

```
🔥 FINAL FRESHER JOBS

[1] Backend Developer
⭐ 9/10
🔗 https://...

[2] Intermediate Full Stack Engineer
⭐ 8/10
🔗 https://...
```

---

# ⚡ Cron Examples

| Frequency      | Cron          |
| -------------- | ------------- |
| Every hour     | `0 * * * *`   |
| Every 2 hours  | `0 */2 * * *` |
| Daily 9 AM IST | `30 3 * * *`  |

---

# 🚨 Common Issues

* ❌ No jobs found → Source may not have fresher roles
* ❌ Telegram not working → Check token/chat ID
* ❌ Workflow not running → Check `.github/workflows`
* ❌ Secrets missing → Add in GitHub settings

---

# 🚀 Future Improvements

* 📊 React Dashboard UI
* 🗄 Store jobs in database
* 🔍 Multi-source scraping (LinkedIn, Indeed)
* 🤖 Auto-apply to jobs
* 🧠 Resume matching AI

---

# 💡 Key Learning

```
This project teaches:
✔ Web scraping
✔ AI integration
✔ Backend system design
✔ Automation (cron)
✔ Cloud deployment
```

---

# 👨‍💻 Author

**Amit (Engineer)**

---

# ⭐ If you like this project

Give it a ⭐ on GitHub — it motivates future builds 🚀
