import os
import json
import re
import requests
import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from colorama import init, Fore, Style
from tabulate import tabulate
import logging
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from functools import lru_cache
import time

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Initialize colorama
init(autoreset=True)

# ==============================
# LOGGING SETUP
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format=f'{Fore.CYAN}%(asctime)s{Style.RESET_ALL} - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==============================
# LOAD ENV
# ==============================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Configuration
RSS_URL = "https://remoteok.com/remote-dev-jobs.rss"
MAX_JOBS_TO_FETCH = 50
MAX_JOBS_TO_PROCESS = 15
THREAD_POOL_SIZE = 8
REQUEST_TIMEOUT = 15
CACHE_DURATION = 3600  # 1 hour cache

# ==============================
# DATA CLASSES
# ==============================

@dataclass
class Job:
    """Represents a job posting"""
    id: int
    title: str
    link: str
    description: str
    company: Optional[str] = None
    location: Optional[str] = None
    posted_date: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "link": self.link,
            "description": self.description[:500],
            "company": self.company,
            "location": self.location
        }

@dataclass
class RankedJobResult:
    """Represents a ranked job result"""
    job: Job
    score: int
    reason: str
    
    def display(self, index: int) -> str:
        score_color = Fore.GREEN if self.score >= 7 else Fore.YELLOW if self.score >= 5 else Fore.RED
        return f"""
{Fore.CYAN}{'─' * 70}
{Fore.WHITE}[{index}] {Fore.YELLOW}🎯 {self.job.title}
{Fore.CYAN}   {'─' * 60}
{Fore.GREEN}   📊 Score: {score_color}{self.score}/10{Style.RESET_ALL}
{Fore.BLUE}   🔗 Link: {self.job.link}
{Fore.MAGENTA}   💡 Match: {self.reason}
{Fore.CYAN}   🏢 Company: {self.job.company or 'N/A'}
{Fore.CYAN}   📍 Location: {self.job.location or 'Remote'}
{Fore.CYAN}{'─' * 70}
"""

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
# CACHE MANAGER
# ==============================

class CacheManager:
    def __init__(self):
        self.cache = {}
        self.cache_timestamp = {}
    
    def get(self, key: str) -> Optional[any]:
        if key in self.cache and time.time() - self.cache_timestamp.get(key, 0) < CACHE_DURATION:
            return self.cache[key]
        return None
    
    def set(self, key: str, value: any):
        self.cache[key] = value
        self.cache_timestamp[key] = time.time()
    
    def clear(self):
        self.cache.clear()
        self.cache_timestamp.clear()

cache_manager = CacheManager()

# ==============================
# ENHANCED EXPERIENCE DETECTION
# ==============================

def extract_experience(text: str) -> Tuple[int, str]:
    """Extract years of experience from text with pattern matching"""
    patterns = [
        r'(\d+)\s*\+?\s*years?',
        r'(\d+)\s*\+\s*yrs?',
        r'exp(?:erience)?:\s*(\d+)',
        r'(\d+)\s*year'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return int(match.group(1)), "matched"
    
    # Check for fresher indicators
    fresher_keywords = ['fresher', 'entry level', 'junior', 'graduate', '0-2 years']
    if any(keyword in text.lower() for keyword in fresher_keywords):
        return 0, "entry_level"
    
    return 0, "not_found"

# ==============================
# ENHANCED JOB VALIDATION
# ==============================

class JobValidator:
    """Advanced job validation with multiple criteria"""
    
    REQUIRED_TECH = {
        "frontend": ["react", "vue", "angular", "javascript", "typescript"],
        "backend": ["node", "python", "java", "go", "rust", "express", "django", "flask"],
        "database": ["mongodb", "postgresql", "mysql", "redis", "sql"],
        "fullstack": ["full stack", "fullstack", "mean", "mern"]
    }
    
    EXCLUDED_TITLES = {
        "senior": ["senior", "sr.", "sr"],
        "lead": ["lead", "team lead"],
        "management": ["director", "vp", "chief", "cto", "manager", "head of"],
        "other": ["wordpress", "salesforce", "security", "devops", "qa", "designer"]
    }
    
    @classmethod
    def validate(cls, title: str, description: str) -> Tuple[bool, str, Dict]:
        """Validate job and return detailed feedback"""
        title_lower = title.lower()
        desc_lower = description.lower()
        
        # Check for excluded titles
        for category, keywords in cls.EXCLUDED_TITLES.items():
            for keyword in keywords:
                if keyword in title_lower:
                    return False, f"Excluded role: {category}", {}
        
        # Check tech stack match
        matched_tech = []
        for category, techs in cls.REQUIRED_TECH.items():
            for tech in techs:
                if tech in title_lower or tech in desc_lower:
                    matched_tech.append(tech)
        
        if not matched_tech:
            return False, "No matching tech stack found", {}
        
        # Check experience level
        exp_years, exp_type = extract_experience(f"{title} {description}")
        if exp_years > 2:
            return False, f"Requires {exp_years}+ years experience", {}
        
        return True, "Valid", {"matched_tech": matched_tech, "exp_type": exp_type}

# ==============================
# ENHANCED SCRAPER
# ==============================

class JobScraper:
    """Advanced job scraper with retry logic"""
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    @staticmethod
    @lru_cache(maxsize=100)
    def scrape_description(url: str, retries: int = 3) -> str:
        """Scrape job description with retry logic"""
        for attempt in range(retries):
            try:
                response = requests.get(
                    url, 
                    headers=JobScraper.HEADERS, 
                    timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Remove script and style elements
                for element in soup(["script", "style", "nav", "footer", "header"]):
                    element.decompose()
                
                # Get text and clean it
                text = soup.get_text(" ", strip=True)
                text = re.sub(r'\s+', ' ', text)
                
                return text[:1500]  # Limit length
                
            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < retries - 1:
                    time.sleep(1)
                    
        return ""

# ==============================
# ENHANCED JOB FETCHER
# ==============================

class JobFetcher:
    """Enhanced job fetching with progress tracking"""
    
    def __init__(self):
        self.validator = JobValidator()
        self.scraper = JobScraper()
    
    def fetch_jobs(self) -> List[Job]:
        """Fetch and process jobs with progress tracking"""
        logger.info(f"{Fore.CYAN}📡 Fetching jobs from RSS feed...{Style.RESET_ALL}")
        
        feed = feedparser.parse(RSS_URL)
        entries = feed.entries[:MAX_JOBS_TO_FETCH]
        
        logger.info(f"📥 Found {len(entries)} total jobs")
        
        jobs = []
        matched_jobs = []
        
        # First pass: quick filtering without scraping
        for i, entry in enumerate(entries):
            # Quick check on title only
            valid, reason, _ = self.validator.validate(entry.title, "")
            if valid:
                matched_jobs.append((i, entry))
        
        logger.info(f"🎯 {len(matched_jobs)} jobs passed initial filter")
        
        if not matched_jobs:
            return []
        
        # Second pass: scrape and validate with progress bar
        with ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE) as executor:
            futures = {}
            
            for i, entry in matched_jobs[:MAX_JOBS_TO_PROCESS]:
                future = executor.submit(self._process_job, i, entry)
                futures[future] = (i, entry)
            
            completed = 0
            for future in as_completed(futures):
                completed += 1
                job = future.result()
                if job:
                    jobs.append(job)
                logger.info(f"Progress: {completed}/{len(futures)} jobs processed")
        
        logger.info(f"✅ Final valid jobs: {len(jobs)}")
        return jobs
    
    def _process_job(self, i: int, entry) -> Optional[Job]:
        """Process individual job"""
        try:
            description = self.scraper.scrape_description(entry.link)
            valid, reason, metadata = self.validator.validate(entry.title, description)
            
            # Extract company and location if available
            company = None
            location = None
            
            if hasattr(entry, 'author'):
                company = entry.author
            elif hasattr(entry, 'source'):
                company = entry.source.title
            
            # Try to extract location from description
            location_pattern = r'(?:location|remote|onsite|hybrid)[:\s]+([^\n]+)'
            location_match = re.search(location_pattern, description.lower())
            if location_match:
                location = location_match.group(1)
            
            if valid:
                return Job(
                    id=i,
                    title=entry.title,
                    link=entry.link,
                    description=description,
                    company=company,
                    location=location,
                    posted_date=getattr(entry, 'published', None)
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error processing job {i}: {e}")
            return None

# ==============================
# ENHANCED AI RANKING
# ==============================

class AIRanker:
    """AI-based job ranking with detailed analysis"""
    
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
    
    def rank_jobs(self, jobs: List[Job]) -> List[RankedJobResult]:
        """Rank jobs using AI with detailed analysis"""
        if not jobs:
            return []
        
        logger.info(f"{Fore.MAGENTA}🤖 AI analyzing {len(jobs)} jobs...{Style.RESET_ALL}")
        
        # Prepare job data for AI
        job_data = []
        for job in jobs:
            job_data.append({
                "id": job.id,
                "title": job.title,
                "description_preview": job.description[:500],
                "company": job.company,
                "location": job.location
            })
        
        prompt = f"""
You are a strict fresher job recommender with expert knowledge in tech hiring.

**RULES:**
- ONLY select jobs for freshers or candidates with ≤2 years experience
- REJECT any Senior, Lead, Director, VP, Chief roles
- PREFER Backend, React, Node, Full Stack, Python positions
- Score MUST be between 1-10 based on:
  * 8-10: Perfect match for fresher with your stack
  * 6-7: Good match but slight experience or tech mismatch
  * 4-5: Acceptable but not ideal
  * 1-3: Poor match

**Analyze each job for:**
1. Experience requirements (must be ≤2 years)
2. Tech stack alignment with your skills
3. Role seniority level
4. Company type and learning potential

Return ONLY the top 5 jobs ranked by best match, in JSON format.
"""

        config = types.GenerateContentConfig(
            system_instruction=prompt,
            response_mime_type="application/json",
            response_schema=JobList
        )
        
        try:
            response = self.client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=f"Jobs to analyze:\n{json.dumps(job_data, indent=2)}",
                config=config
            )
            
            ai_result = JobList(**json.loads(response.text))
            
            # Map results back to jobs
            job_map = {job.id: job for job in jobs}
            ranked_results = []
            
            for ranked_job in ai_result.top_jobs[:5]:
                job = job_map.get(ranked_job.id)
                if job:
                    ranked_results.append(RankedJobResult(
                        job=job,
                        score=ranked_job.score,
                        reason=ranked_job.reason
                    ))
            
            return ranked_results
            
        except Exception as e:
            logger.error(f"AI ranking failed: {e}")
            return []

# ==============================
# ENHANCED UI
# ==============================

class UI:
    """Beautiful terminal UI with animations"""
    
    @staticmethod
    def print_header():
        """Print animated header"""
        banner = f"""
{Fore.CYAN}{'═' * 70}
{Fore.YELLOW}🔥🔥🔥 {Fore.RED}SMART JOB FINDER {Fore.YELLOW}v3.0 {Fore.CYAN}🔥🔥🔥
{Fore.CYAN}{'═' * 70}
{Fore.GREEN}🎯 AI-Powered | 🚀 Real-time | 💡 Smart Matching
{Fore.CYAN}{'═' * 70}{Style.RESET_ALL}
"""
        print(banner)
    
    @staticmethod
    def print_stats(stats: Dict):
        """Print statistics in a beautiful table"""
        table_data = [
            ["📊 Total Jobs Scanned", stats.get('total_scanned', 0)],
            ["🎯 Initial Matches", stats.get('initial_matches', 0)],
            ["✅ Final Valid Jobs", stats.get('final_valid', 0)],
            ["🤖 AI Ranked Jobs", stats.get('ai_ranked', 0)],
            ["⏰ Scan Time", stats.get('scan_time', 'N/A')]
        ]
        
        print(f"\n{Fore.CYAN}{'─' * 70}")
        print(f"{Fore.WHITE}📈 SCAN STATISTICS")
        print(f"{Fore.CYAN}{'─' * 70}")
        print(tabulate(table_data, tablefmt="simple", colalign=("left", "right")))
        print(f"{Fore.CYAN}{'─' * 70}\n")
    
    @staticmethod
    def print_results(jobs: List[RankedJobResult]):
        """Print ranked jobs beautifully"""
        if not jobs:
            print(f"\n{Fore.YELLOW}😴 No fresher jobs found today{Style.RESET_ALL}")
            print(f"{Fore.CYAN}💡 Tip: Try again later or expand your search criteria{Style.RESET_ALL}")
            return
        
        print(f"\n{Fore.GREEN}{'🎉' * 35}")
        print(f"{Fore.WHITE}🏆 TOP {len(jobs)} FRESHER JOBS FOR YOU 🏆")
        print(f"{Fore.GREEN}{'🎉' * 35}{Style.RESET_ALL}")
        
        for i, job in enumerate(jobs, 1):
            print(job.display(i))
    
    @staticmethod
    def print_loading_animation(message: str, duration: float = 1.0):
        """Print loading animation"""
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        start_time = time.time()
        i = 0
        while time.time() - start_time < duration:
            print(f"\r{Fore.YELLOW}{chars[i % len(chars)]} {message}{Style.RESET_ALL}", end="")
            time.sleep(0.1)
            i += 1
        print("\r" + " " * 50 + "\r", end="")

# ==============================
# ENHANCED TELEGRAM
# ==============================

class TelegramNotifier:
    """Enhanced Telegram notifications with formatting"""
    
    @staticmethod
    def send(jobs: List[RankedJobResult]):
        """Send formatted job alerts to Telegram"""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.warning("Telegram not configured - skipping notification")
            return
        
        if not jobs:
            message = "😴 No fresher jobs found in this scan\n\n"
            message += f"🕐 Last checked: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        else:
            message = f"🔥 *FRESHER JOB ALERTS* 🔥\n\n"
            message += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"🎯 Top {len(jobs)} matches found\n\n"
            message += "─" * 30 + "\n\n"
            
            for i, job in enumerate(jobs, 1):
                message += f"*{i}. {job.job.title}*\n"
                message += f"⭐ Score: {job.score}/10\n"
                message += f"💡 {job.reason}\n"
                message += f"🔗 [Apply Here]({job.job.link})\n"
                if job.job.company:
                    message += f"🏢 {job.job.company}\n"
                message += "\n"
        
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True
                },
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("✅ Telegram notification sent")
            else:
                logger.error(f"Telegram send failed: {response.text}")
                
        except Exception as e:
            logger.error(f"Telegram error: {e}")

# ==============================
# MAIN APPLICATION
# ==============================

class SmartJobFinder:
    """Main application orchestrator"""
    
    def __init__(self):
        self.ui = UI()
        self.fetcher = JobFetcher()
        self.ranker = AIRanker()
        self.notifier = TelegramNotifier()
    
    def run(self):
        """Run the job finder application"""
        start_time = time.time()
        
        # Print header
        self.ui.print_header()
        
        # Fetch jobs
        self.ui.print_loading_animation("Fetching and analyzing jobs...", 2)
        jobs = self.fetcher.fetch_jobs()
        
        if not jobs:
            self.ui.print_results([])
            self.notifier.send([])
            return
        
        # Rank jobs with AI
        self.ui.print_loading_animation("AI analyzing best matches...", 2)
        ranked_jobs = self.ranker.rank_jobs(jobs)
        
        # Calculate stats
        stats = {
            'total_scanned': MAX_JOBS_TO_FETCH,
            'initial_matches': len(jobs),
            'final_valid': len(jobs),
            'ai_ranked': len(ranked_jobs),
            'scan_time': f"{time.time() - start_time:.2f}s"
        }
        
        # Display results
        self.ui.print_stats(stats)
        self.ui.print_results(ranked_jobs)
        
        # Send notifications
        if ranked_jobs:
            self.notifier.send(ranked_jobs)
            print(f"\n{Fore.GREEN}✅ Results sent to Telegram!{Style.RESET_ALL}")
        
        # Footer
        print(f"\n{Fore.CYAN}{'═' * 70}")
        print(f"{Fore.WHITE}✨ Scan completed in {stats['scan_time']} ✨")
        print(f"{Fore.CYAN}{'═' * 70}{Style.RESET_ALL}\n")

# ==============================
# ENTRY POINT
# ==============================

if __name__ == "__main__":
    try:
        app = SmartJobFinder()
        app.run()
    except KeyboardInterrupt:
        print(f"\n\n{Fore.YELLOW}👋 Goodbye! Happy job hunting!{Style.RESET_ALL}\n")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"\n{Fore.RED}❌ Application error: {e}{Style.RESET_ALL}")