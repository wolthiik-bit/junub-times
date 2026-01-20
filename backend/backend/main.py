"""
Junub Times - AI News Scraper & Social Media Automation
Complete application for South Sudan news
"""
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey,
    select, func, desc
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta
from typing import List, Optional, Dict
import asyncio
import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup
import re
import os
import enum

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

load_dotenv()

# =====================================================
# CONFIGURATION
# =====================================================
class Settings:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./junub_times.db")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    
    # Social Media API Keys
    X_API_KEY = os.getenv("X_API_KEY", "")
    X_API_SECRET = os.getenv("X_API_SECRET", "")
    X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN", "")
    X_ACCESS_SECRET = os.getenv("X_ACCESS_SECRET", "")
    META_PAGE_ACCESS_TOKEN = os.getenv("META_PAGE_ACCESS_TOKEN", "")
    META_PAGE_ID = os.getenv("META_PAGE_ID", "")
    META_IG_BUSINESS_ID = os.getenv("META_IG_BUSINESS_ID", "")
    
    # App Settings
    AUTO_APPROVE = os.getenv("AUTO_APPROVE", "false").lower() == "true"
    AUTO_POST = os.getenv("AUTO_POST", "false").lower() == "true"
    FETCH_INTERVAL = int(os.getenv("FETCH_INTERVAL_MINUTES", "30"))
    
    # South Sudan & East Africa Keywords
    KEYWORDS = [
        "south sudan", "juba", "junub", "splm", "spla", "salva kiir", "riek machar",
        "unmiss", "abyei", "upper nile", "equatoria", "bahr el ghazal", "jonglei",
        "unity state", "warrap", "lakes state", "western equatoria", "eastern equatoria",
        "central equatoria", "wau", "malakal", "bentiu", "bor", "yei", "nimule", "torit",
        "renk", "aweil", "kuajok", "rumbek", "igad", "east africa", "eac", "african union",
        "sudan", "khartoum", "ethiopia", "addis ababa", "kenya", "nairobi", "uganda", 
        "kampala", "dr congo", "refugee", "humanitarian", "famine", "flood",
        "peace agreement", "ceasefire", "oil production", "nile", "white nile"
    ]
    
    # News Sources
    RSS_SOURCES = [
        ("Google News - South Sudan", "https://news.google.com/rss/search?q=South+Sudan&hl=en&gl=US&ceid=US:en"),
        ("Google News - Juba", "https://news.google.com/rss/search?q=Juba+South+Sudan&hl=en&gl=US&ceid=US:en"),
        ("Google News - Salva Kiir", "https://news.google.com/rss/search?q=Salva+Kiir&hl=en&gl=US&ceid=US:en"),
        ("UN News Africa", "https://news.un.org/feed/subscribe/en/news/region/africa/feed/rss.xml"),
        ("AllAfrica South Sudan", "https://allafrica.com/tools/headlines/rdf/southsudan/headlines.rdf"),
        ("ReliefWeb South Sudan", "https://reliefweb.int/updates/rss.xml?country=219"),
        ("Google News - East Africa", "https://news.google.com/rss/search?q=East+Africa&hl=en&gl=US&ceid=US:en"),
        ("Google News - IGAD", "https://news.google.com/rss/search?q=IGAD&hl=en&gl=US&ceid=US:en"),
    ]

settings = Settings()

# =====================================================
# DATABASE
# =====================================================
engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class ArticleStatus(str, enum.Enum):
    FETCHED = "fetched"
    PROCESSING = "processing"
    PROCESSED = "processed"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUEUED = "queued"
    POSTED = "posted"
    FAILED = "failed"

class PostStatus(str, enum.Enum):
    PENDING = "pending"
    POSTING = "posting"
    POSTED = "posted"
    FAILED = "failed"

class Source(Base):
    __tablename__ = "sources"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    url = Column(String(1024), nullable=False, unique=True)
    source_type = Column(String(50), default="rss")
    enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=1)
    last_fetched = Column(DateTime, nullable=True)
    fetch_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class Article(Base):
    __tablename__ = "articles"
    id = Column(Integer, primary_key=True)
    url = Column(String(2048), nullable=False, unique=True)
    title = Column(String(1024), nullable=False)
    content = Column(Text, default="")
    summary = Column(Text, default="")
    author = Column(String(255), default="")
    source_name = Column(String(255), default="")
    image_url = Column(String(2048), default="")
    published_at = Column(DateTime, default=datetime.utcnow)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    relevance_score = Column(Float, default=0.0)
    categories = Column(String(512), default="")
    keywords = Column(String(512), default="")
    status = Column(String(50), default=ArticleStatus.FETCHED.value)
    word_count = Column(Integer, default=0)

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"))
    platform = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    hashtags = Column(String(512), default="")
    media_url = Column(String(2048), default="")
    status = Column(String(50), default=PostStatus.PENDING.value)
    scheduled_at = Column(DateTime, nullable=True)
    posted_at = Column(DateTime, nullable=True)
    platform_post_id = Column(String(255), default="")
    platform_url = Column(String(2048), default="")
    error_message = Column(Text, default="")
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), default="")
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with async_session_maker() as session:
        result = await session.execute(select(Source).limit(1))
        if not result.scalar():
            for name, url in settings.RSS_SOURCES:
                session.add(Source(name=name, url=url, enabled=True))
            await session.commit()
            print(f"✅ Seeded {len(settings.RSS_SOURCES)} news sources")

async def get_session():
    async with async_session_maker() as session:
        yield session

# =====================================================
# NEWS SCRAPER
# =====================================================
class NewsScraper:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "JunubTimes/1.0 (News Aggregator)"}
        )
    
    async def close(self):
        await self.client.aclose()
    
    def calculate_relevance(self, title: str, content: str) -> float:
        text = f"{title} {content}".lower()
        
        high_priority = ["south sudan", "juba", "junub", "splm", "spla", 
                        "salva kiir", "riek machar", "unmiss", "abyei"]
        medium_priority = ["igad", "east africa", "sudan", "khartoum",
                          "upper nile", "equatoria", "bahr el ghazal"]
        
        score = 0
        for kw in high_priority:
            if kw in text:
                score += 3
        for kw in medium_priority:
            if kw in text:
                score += 2
        for kw in settings.KEYWORDS:
            if kw not in high_priority and kw not in medium_priority:
                if kw in text:
                    score += 1
        
        return min(score / 15, 1.0)
    
    def extract_categories(self, text: str) -> List[str]:
        text = text.lower()
        categories = []
        
        category_mapping = {
            "Politics": ["government", "election", "parliament", "minister", "president", "opposition", "splm", "vote"],
            "Conflict": ["war", "fighting", "attack", "military", "soldier", "violence", "ceasefire", "peace", "weapon"],
            "Humanitarian": ["refugee", "displaced", "aid", "humanitarian", "famine", "hunger", "food", "crisis"],
            "Economy": ["oil", "economy", "trade", "business", "investment", "development", "infrastructure", "export"],
            "Health": ["health", "hospital", "disease", "covid", "medical", "outbreak", "doctor", "medicine"],
            "Environment": ["flood", "drought", "climate", "environment", "water", "agriculture", "farming"],
            "International": ["un", "united nations", "african union", "igad", "international", "diplomat"],
            "Sports": ["football", "sport", "athlete", "team", "match", "tournament", "player"],
        }
        
        for category, keywords in category_mapping.items():
            if any(kw in text for kw in keywords):
                categories.append(category)
        
        return categories[:4]
    
    async def fetch_rss_feed(self, source: Source) -> List[Dict]:
        articles = []
        try:
            response = await self.client.get(source.url)
            response.raise_for_status()
            feed = feedparser.parse(response.text)
            
            for entry in feed.entries[:25]:
                try:
                    image_url = ""
                    if hasattr(entry, "media_content") and entry.media_content:
                        for media in entry.media_content:
                            if "image" in media.get("type", "") or media.get("medium") == "image":
                                image_url = media.get("url", "")
                                break
                    
                    published_at = datetime.utcnow()
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        import time
                        try:
                            published_at = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        except:
                            pass
                    
                    article_data = {
                        "url": entry.get("link", "").strip(),
                        "title": entry.get("title", "").strip(),
                        "summary": entry.get("summary", entry.get("description", "")).strip()[:1000],
                        "author": entry.get("author", ""),
                        "source_name": source.name,
                        "image_url": image_url,
                        "published_at": published_at
                    }
                    
                    if article_data["url"] and article_data["title"]:
                        articles.append(article_data)
                        
                except Exception as e:
                    print(f"Error parsing entry: {e}")
                    continue
            
            return articles
            
        except Exception as e:
            print(f"Error fetching RSS {source.url}: {e}")
            return []
    
    async def extract_full_content(self, url: str) -> Dict:
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            html = response.text
            
            content = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                no_fallback=False
            )
            
            if content and len(content) > 100:
                return {
                    "content": content[:8000],
                    "word_count": len(content.split())
                }
            
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "ad"]):
                tag.decompose()
            
            main = soup.find("main") or soup.find("article") or soup.find("body")
            if main:
                text = main.get_text(separator="\n", strip=True)
                return {
                    "content": text[:8000],
                    "word_count": len(text.split())
                }
            
            return {"content": "", "word_count": 0}
            
        except Exception as e:
            print(f"Error extracting content from {url}: {e}")
            return {"content": "", "word_count": 0}
    
    async def fetch_all_sources(self, session: AsyncSession) -> Dict:
        result = await session.execute(
            select(Source).where(Source.enabled == True).order_by(Source.priority)
        )
        sources = result.scalars().all()
        
        stats = {
            "sources_processed": 0,
            "articles_found": 0,
            "articles_new": 0,
            "articles_relevant": 0,
            "errors": []
        }
        
        for source in sources:
            try:
                articles = await self.fetch_rss_feed(source)
                stats["sources_processed"] += 1
                stats["articles_found"] += len(articles)
                
                for article_data in articles:
                    existing = await session.execute(
                        select(Article).where(Article.url == article_data["url"])
                    )
                    if existing.scalar():
                        continue
                    
                    relevance = self.calculate_relevance(
                        article_data["title"],
                        article_data.get("summary", "")
                    )
                    
                    if relevance < 0.05:
                        continue
                    
                    categories = self.extract_categories(
                        f"{article_data['title']} {article_data.get('summary', '')}"
                    )
                    
                    article = Article(
                        url=article_data["url"],
                        title=article_data["title"],
                        content=article_data.get("summary", ""),
                        summary=article_data.get("summary", "")[:500],
                        author=article_data.get("author", ""),
                        source_name=article_data.get("source_name", ""),
                        image_url=article_data.get("image_url", ""),
                        published_at=article_data.get("published_at", datetime.utcnow()),
                        relevance_score=relevance,
                        categories=",".join(categories),
                        status=ArticleStatus.FETCHED.value
                    )
                    
                    session.add(article)
                    stats["articles_new"] += 1
                    
                    if relevance >= 0.15:
                        stats["articles_relevant"] += 1
                
                source.last_fetched = datetime.utcnow()
                source.fetch_count += 1
                
            except Exception as e:
                stats["errors"].append(f"{source.name}: {str(e)}")
                source.error_count += 1
        
        await session.commit()
        return stats
    
    async def process_article(self, article: Article, session: AsyncSession) -> bool:
        try:
            article.status = ArticleStatus.PROCESSING.value
            await session.commit()
            
            content_data = await self.extract_full_content(article.url)
            
            if content_data["content"]:
                article.content = content_data["content"]
                article.word_count = content_data.get("word_count", 0)
                
                article.relevance_score = self.calculate_relevance(
                    article.title,
                    article.content
                )
                
                categories = self.extract_categories(f"{article.title} {article.content}")
                article.categories = ",".join(categories)
            
            article.status = ArticleStatus.PROCESSED.value
            await session.commit()
            return True
            
        except Exception as e:
            print(f"Error processing article {article.id}: {e}")
            article.status = ArticleStatus.FAILED.value
            await session.commit()
            return False

scraper = NewsScraper()

# =====================================================
# CONTENT GENERATOR
# =====================================================
class ContentGenerator:
    BASE_HASHTAGS = ["#SouthSudan", "#Juba", "#JunubTimes", "#EastAfrica", "#Africa"]
    
    CATEGORY_HASHTAGS = {
        "Politics": ["#SSPolitics", "#AfricaPolitics"],
        "Conflict": ["#Peace", "#Security"],
        "Humanitarian": ["#Humanitarian", "#Aid"],
        "Economy": ["#Economy", "#Development"],
        "Health": ["#Health", "#Healthcare"],
        "Environment": ["#Climate", "#Environment"],
        "International": ["#UN", "#IGAD", "#AfricanUnion"],
        "Sports": ["#Sports", "#AfricaSports"],
    }
    
    def _get_hashtags(self, article: Article, max_tags: int = 5) -> str:
        hashtags = self.BASE_HASHTAGS[:3]
        
        if article.categories:
            for cat in article.categories.split(","):
                cat = cat.strip()
                if cat in self.CATEGORY_HASHTAGS:
                    hashtags.extend(self.CATEGORY_HASHTAGS[cat][:1])
        
        return " ".join(list(dict.fromkeys(hashtags))[:max_tags])
    
    def generate_x_post(self, article: Article) -> str:
        hashtags = self._get_hashtags(article, 3)
        available = 280 - 25 - len(hashtags) - 4
        
        title = article.title[:available].strip()
        if len(article.title) > available:
            title = title[:available-3] + "..."
        
        return f"{title}\n\n{article.url}\n\n{hashtags}"
    
    def generate_facebook_post(self, article: Article) -> str:
        hashtags = self._get_hashtags(article, 5)
        
        summary = article.summary or article.content[:400]
        if len(summary) > 400:
            summary = summary[:397] + "..."
        
        return f"""📰 {article.title}

{summary}

🔗 Read more: {article.url}

{hashtags}"""
    
    def generate_instagram_post(self, article: Article) -> str:
        hashtags = self._get_hashtags(article, 5) + " #News #Breaking #Africa"
        
        summary = article.summary or article.content[:300]
        if len(summary) > 300:
            summary = summary[:297] + "..."
        
        return f"""🇸🇸 {article.title}

{summary}

📱 Follow @junubtimes for more updates from South Sudan and East Africa!

.
.
.
{hashtags}"""
    
    def generate_tiktok_post(self, article: Article) -> str:
        hashtags = self._get_hashtags(article, 4) + " #NewsUpdate #BreakingNews #FYP"
        
        title = article.title[:100]
        if len(article.title) > 100:
            title = title[:97] + "..."
        
        return f"""🚨 BREAKING: {title}

Follow for more South Sudan news!

{hashtags}"""
    
    def create_all_posts(self, article: Article) -> List[Post]:
        posts = []
        
        platforms = [
            ("x", self.generate_x_post),
            ("facebook", self.generate_facebook_post),
            ("instagram", self.generate_instagram_post),
            ("tiktok", self.generate_tiktok_post),
        ]
        
        for platform, generator in platforms:
            content = generator(article)
            posts.append(Post(
                article_id=article.id,
                platform=platform,
                content=content,
                hashtags=self._get_hashtags(article),
                media_url=article.image_url,
                status=PostStatus.PENDING.value
            ))
        
        return posts

generator = ContentGenerator()

# =====================================================
# SOCIAL MEDIA POSTER
# =====================================================
class SocialPoster:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        await self.client.aclose()
    
    async def post_to_facebook(self, post: Post) -> Dict:
        if not settings.META_PAGE_ACCESS_TOKEN or not settings.META_PAGE_ID:
            return {"success": False, "error": "Facebook not configured"}
        
        try:
            url = f"https://graph.facebook.com/v19.0/{settings.META_PAGE_ID}/feed"
            data = {
                "message": post.content,
                "access_token": settings.META_PAGE_ACCESS_TOKEN
            }
            
            response = await self.client.post(url, data=data)
            response.raise_for_status()
            result = response.json()
            
            if "id" in result:
                return {
                    "success": True,
                    "platform_post_id": result["id"],
                    "platform_url": f"https://facebook.com/{result['id']}"
                }
            return {"success": False, "error": "No ID in response"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_platform_status(self) -> Dict:
        return {
            "x": {
                "configured": bool(settings.X_API_KEY and settings.X_ACCESS_TOKEN),
                "status": "ready" if settings.X_API_KEY else "not_configured"
            },
            "facebook": {
                "configured": bool(settings.META_PAGE_ACCESS_TOKEN and settings.META_PAGE_ID),
                "status": "ready" if settings.META_PAGE_ACCESS_TOKEN else "not_configured"
            },
            "instagram": {
                "configured": bool(settings.META_IG_BUSINESS_ID),
                "status": "ready" if settings.META_IG_BUSINESS_ID else "not_configured",
                "note": "Requires image for each post"
            },
            "tiktok": {
                "configured": False,
                "status": "manual",
                "note": "Copy content and post manually"
            }
        }

poster = SocialPoster()

# =====================================================
# SCHEDULER
# =====================================================
scheduler = AsyncIOScheduler()

async def job_fetch_news():
    print(f"📰 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fetching news...")
    async with async_session_maker() as session:
        try:
            stats = await scraper.fetch_all_sources(session)
            print(f"✅ Fetched {stats['articles_new']} new articles")
            
            session.add(ActivityLog(
                action="fetch_news",
                entity_type="system",
                details=f"New: {stats['articles_new']}, Relevant: {stats['articles_relevant']}"
            ))
            await session.commit()
            
        except Exception as e:
            print(f"❌ Fetch error: {e}")

async def job_process_articles():
    print(f"⚙️ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Processing...")
    async with async_session_maker() as session:
        try:
            result = await session.execute(
                select(Article)
                .where(Article.status == ArticleStatus.FETCHED.value)
                .order_by(desc(Article.relevance_score))
                .limit(10)
            )
            articles = result.scalars().all()
            
            processed = 0
            for article in articles:
                success = await scraper.process_article(article, session)
                if success:
                    processed += 1
                await asyncio.sleep(1)
            
            print(f"✅ Processed {processed} articles")
            
        except Exception as e:
            print(f"❌ Processing error: {e}")

def start_scheduler():
    scheduler.add_job(
        job_fetch_news,
        IntervalTrigger(minutes=settings.FETCH_INTERVAL),
        id="fetch_news",
        replace_existing=True
    )
    
    scheduler.add_job(
        job_process_articles,
        IntervalTrigger(minutes=10),
        id="process_articles",
        replace_existing=True
    )
    
    scheduler.start()
    print(f"🚀 Scheduler started (fetch every {settings.FETCH_INTERVAL} min)")

def stop_scheduler():
    scheduler.shutdown()

# =====================================================
# FASTAPI APP
# =====================================================
app = FastAPI(
    title="Junub Times",
    description="AI News Scraper for South Sudan",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await init_db()
    start_scheduler()
    asyncio.create_task(job_fetch_news())
    print("=" * 60)
    print("🇸🇸 JUNUB TIMES - AI News Automation Platform")
    print("=" * 60)

@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()
    await scraper.close()
    await poster.close()

# =====================================================
# DASHBOARD HTML
# =====================================================
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Junub Times Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🇸🇸</text></svg>">
    <style>
        [v-cloak] { display: none; }
        .gradient-header { background: linear-gradient(135deg, #1e3a5f 0%, #2d4a6f 50%, #1a365d 100%); }
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    <div id="app" v-cloak>
        <header class="gradient-header text-white shadow-xl">
            <div class="max-w-7xl mx-auto px-6 py-6">
                <div class="flex flex-col md:flex-row md:justify-between md:items-center gap-4">
                    <div>
                        <h1 class="text-3xl md:text-4xl font-bold">🇸🇸 Junub Times</h1>
                        <p class="text-blue-200 mt-1">AI News Automation for South Sudan</p>
                    </div>
                    <div class="flex flex-wrap gap-3">
                        <button @click="fetchNews" class="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg font-medium" :disabled="loading">
                            {{ loading ? '⏳ Fetching...' : '🔄 Fetch News' }}
                        </button>
                        <button @click="processArticles" class="bg-white/20 hover:bg-white/30 px-4 py-2 rounded-lg font-medium">
                            ⚙️ Process
                        </button>
                        <button @click="approveTop" class="bg-green-600 hover:bg-green-700 px-4 py-2 rounded-lg font-medium">
                            ✅ Approve Top 10
                        </button>
                    </div>
                </div>
            </div>
        </header>

        <main class="max-w-7xl mx-auto px-6 py-8">
            <!-- Stats -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6 mb-8">
                <div class="bg-white rounded-xl shadow-lg p-6">
                    <p class="text-gray-500 text-sm">Total Articles</p>
                    <p class="text-3xl font-bold text-blue-600">{{ stats.total_articles }}</p>
                </div>
                <div class="bg-white rounded-xl shadow-lg p-6">
                    <p class="text-gray-500 text-sm">New Today</p>
                    <p class="text-3xl font-bold text-green-600">{{ stats.articles_today }}</p>
                </div>
                <div class="bg-white rounded-xl shadow-lg p-6">
                    <p class="text-gray-500 text-sm">Pending Posts</p>
                    <p class="text-3xl font-bold text-yellow-600">{{ stats.pending_posts }}</p>
                </div>
                <div class="bg-white rounded-xl shadow-lg p-6">
                    <p class="text-gray-500 text-sm">Posted Today</p>
                    <p class="text-3xl font-bold text-purple-600">{{ stats.posted_today }}</p>
                </div>
            </div>

            <!-- Tabs -->
            <div class="border-b border-gray-200 mb-6">
                <nav class="flex gap-2">
                    <button v-for="tab in ['articles', 'posts', 'sources', 'platforms']" :key="tab"
                            @click="activeTab = tab"
                            :class="['px-6 py-3 font-medium border-b-2 capitalize', 
                                    activeTab === tab ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500']">
                        {{ tab }}
                    </button>
                </nav>
            </div>

            <!-- Articles -->
            <div v-if="activeTab === 'articles'">
                <div class="mb-4">
                    <select v-model="articleFilter" @change="loadArticles" class="border rounded-lg px-4 py-2">
                        <option value="">All Status</option>
                        <option value="fetched">Fetched</option>
                        <option value="processed">Processed</option>
                        <option value="approved">Approved</option>
                        <option value="rejected">Rejected</option>
                    </select>
                </div>

                <div class="space-y-4">
                    <div v-for="article in articles" :key="article.id" class="bg-white rounded-xl shadow-lg p-6">
                        <div class="flex flex-col lg:flex-row lg:justify-between gap-4">
                            <div class="flex-1">
                                <div class="flex flex-wrap items-center gap-2 mb-2">
                                    <span :class="['px-3 py-1 rounded-full text-xs font-semibold', getStatusClass(article.status)]">
                                        {{ article.status }}
                                    </span>
                                    <span class="text-sm text-gray-500">{{ article.source_name }}</span>
                                    <span class="text-sm text-blue-600">{{ (article.relevance_score * 100).toFixed(0) }}%</span>
                                </div>
                                <h3 class="font-semibold text-lg mb-2">{{ article.title }}</h3>
                                <p class="text-gray-600 text-sm">{{ article.summary }}</p>
                            </div>
                            <div class="flex flex-row lg:flex-col gap-2">
                                <button v-if="article.status !== 'approved'" @click="approveArticle(article.id)" 
                                        class="bg-green-600 text-white px-4 py-2 rounded-lg text-sm">✅ Approve</button>
                                <button v-if="article.status !== 'rejected'" @click="rejectArticle(article.id)" 
                                        class="bg-red-500 text-white px-4 py-2 rounded-lg text-sm">❌ Reject</button>
                                <button v-if="article.status === 'approved'" @click="generatePosts(article.id)" 
                                        class="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm">📝 Generate</button>
                                <a :href="article.url" target="_blank" class="bg-gray-200 px-4 py-2 rounded-lg text-sm text-center">🔗 View</a>
                            </div>
                        </div>
                    </div>
                    
                    <div v-if="articles.length === 0" class="bg-white rounded-xl p-12 text-center text-gray-500">
                        <p class="text-4xl mb-4">📭</p>
                        <p>No articles found. Click "Fetch News" to get started!</p>
                    </div>
                </div>
            </div>

            <!-- Posts -->
            <div v-if="activeTab === 'posts'">
                <div class="space-y-4">
                    <div v-for="post in posts" :key="post.id" class="bg-white rounded-xl shadow-lg p-6">
                        <div class="flex flex-col lg:flex-row lg:justify-between gap-4">
                            <div class="flex-1">
                                <div class="flex items-center gap-3 mb-3">
                                    <span class="text-xl">{{ getPlatformIcon(post.platform) }}</span>
                                    <span class="font-bold uppercase">{{ post.platform }}</span>
                                    <span :class="['px-3 py-1 rounded-full text-xs font-semibold', getStatusClass(post.status)]">
                                        {{ post.status }}
                                    </span>
                                </div>
                                <pre class="text-gray-700 text-sm whitespace-pre-wrap bg-gray-50 p-4 rounded-lg">{{ post.content }}</pre>
                            </div>
                            <div class="flex flex-row lg:flex-col gap-2">
                                <button v-if="post.status === 'pending'" @click="publishPost(post.id)" 
                                        class="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm">🚀 Publish</button>
                                <button @click="copyContent(post.content)" 
                                        class="bg-gray-200 px-4 py-2 rounded-lg text-sm">📋 Copy</button>
                            </div>
                        </div>
                    </div>
                    
                    <div v-if="posts.length === 0" class="bg-white rounded-xl p-12 text-center text-gray-500">
                        <p class="text-4xl mb-4">📝</p>
                        <p>No posts yet. Approve articles and generate posts!</p>
                    </div>
                </div>
            </div>

            <!-- Sources -->
            <div v-if="activeTab === 'sources'">
                <div class="space-y-4">
                    <div v-for="source in sources" :key="source.id" 
                         class="bg-white rounded-xl shadow-lg p-6 flex flex-col md:flex-row md:justify-between md:items-center gap-4">
                        <div>
                            <h3 class="font-semibold">{{ source.name }}</h3>
                            <p class="text-sm text-gray-500 truncate">{{ source.url }}</p>
                            <p class="text-xs text-gray-400">Fetches: {{ source.fetch_count }}</p>
                        </div>
                        <button @click="toggleSource(source.id)" 
                                :class="['px-4 py-2 rounded-lg text-sm', source.enabled ? 'bg-green-600 text-white' : 'bg-red-500 text-white']">
                            {{ source.enabled ? '✅ Enabled' : '❌ Disabled' }}
                        </button>
                    </div>
                </div>
            </div>

            <!-- Platforms -->
            <div v-if="activeTab === 'platforms'">
                <div class="grid md:grid-cols-2 gap-6">
                    <div v-for="(status, platform) in platformStatus" :key="platform" class="bg-white rounded-xl shadow-lg p-6">
                        <div class="flex items-center gap-3 mb-4">
                            <span class="text-3xl">{{ getPlatformIcon(platform) }}</span>
                            <h3 class="font-bold text-xl capitalize">{{ platform }}</h3>
                        </div>
                        <p :class="status.configured ? 'text-green-600' : 'text-red-500'">
                            {{ status.configured ? '✅ Configured' : '❌ Not Configured' }}
                        </p>
                        <p v-if="status.note" class="text-sm text-yellow-600 mt-2">⚠️ {{ status.note }}</p>
                    </div>
                </div>
            </div>
        </main>

        <!-- Toast -->
        <div v-if="toast" class="fixed bottom-6 right-6 bg-gray-900 text-white px-6 py-4 rounded-xl shadow-2xl">
            {{ toast }}
        </div>
    </div>

    <script>
    const { createApp } = Vue

    createApp({
        data() {
            return {
                activeTab: 'articles',
                loading: false,
                toast: null,
                stats: { total_articles: 0, articles_today: 0, pending_posts: 0, posted_today: 0 },
                articles: [],
                posts: [],
                sources: [],
                platformStatus: {},
                articleFilter: ''
            }
        },
        methods: {
            async api(endpoint, method = 'GET') {
                const res = await fetch('/api' + endpoint, { method })
                return await res.json()
            },
            showToast(msg) {
                this.toast = msg
                setTimeout(() => this.toast = null, 3000)
            },
            getStatusClass(status) {
                const classes = {
                    fetched: 'bg-gray-200 text-gray-700',
                    processed: 'bg-blue-200 text-blue-800',
                    approved: 'bg-green-200 text-green-800',
                    rejected: 'bg-red-200 text-red-800',
                    posted: 'bg-purple-200 text-purple-800',
                    pending: 'bg-yellow-200 text-yellow-800',
                    failed: 'bg-red-200 text-red-800'
                }
                return classes[status] || 'bg-gray-200'
            },
            getPlatformIcon(platform) {
                return { x: '𝕏', facebook: '📘', instagram: '📸', tiktok: '🎵' }[platform] || '📱'
            },
            async loadStats() { this.stats = await this.api('/stats') },
            async loadArticles() {
                let url = '/articles?limit=50'
                if (this.articleFilter) url += '&status=' + this.articleFilter
                this.articles = await this.api(url)
            },
            async loadPosts() { this.posts = await this.api('/posts?limit=50') },
            async loadSources() { this.sources = await this.api('/sources') },
            async loadPlatformStatus() { this.platformStatus = await this.api('/platform-status') },
            async fetchNews() {
                this.loading = true
                await this.api('/actions/fetch', 'POST')
                this.showToast('🔄 Fetching news...')
                setTimeout(async () => {
                    await this.loadStats()
                    await this.loadArticles()
                    this.loading = false
                    this.showToast('✅ Done!')
                }, 5000)
            },
            async processArticles() {
                await this.api('/actions/process', 'POST')
                this.showToast('⚙️ Processing...')
                setTimeout(() => this.loadArticles(), 3000)
            },
            async approveArticle(id) {
                await this.api('/articles/' + id + '/approve', 'POST')
                this.showToast('✅ Approved!')
                this.loadArticles()
            },
            async rejectArticle(id) {
                await this.api('/articles/' + id + '/reject', 'POST')
                this.showToast('❌ Rejected')
                this.loadArticles()
            },
            async approveTop() {
                await this.api('/articles/approve-top?min_score=0.15&limit=10', 'POST')
                this.showToast('✅ Top articles approved!')
                this.loadArticles()
            },
            async generatePosts(id) {
                await this.api('/posts/generate/' + id, 'POST')
                this.showToast('📝 Posts generated!')
                this.loadPosts()
            },
            async publishPost(id) {
                await this.api('/posts/' + id + '/publish', 'POST')
                this.showToast('🚀 Publishing...')
                this.loadPosts()
            },
            async toggleSource(id) {
                await this.api('/sources/' + id + '/toggle', 'POST')
                this.loadSources()
            },
            copyContent(content) {
                navigator.clipboard.writeText(content)
                this.showToast('📋 Copied!')
            }
        },
        async mounted() {
            await Promise.all([
                this.loadStats(),
                this.loadArticles(),
                this.loadPosts(),
                this.loadSources(),
                this.loadPlatformStatus()
            ])
        }
    }).mount('#app')
    </script>
</body>
</html>
"""

# =====================================================
# API ROUTES
# =====================================================
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)

@app.get("/api/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    
    total = (await session.execute(select(func.count(Article.id)))).scalar() or 0
    today_count = (await session.execute(
        select(func.count(Article.id)).where(Article.fetched_at >= today_start)
    )).scalar() or 0
    pending = (await session.execute(
        select(func.count(Post.id)).where(Post.status == PostStatus.PENDING.value)
    )).scalar() or 0
    posted = (await session.execute(
        select(func.count(Post.id)).where(Post.status == PostStatus.POSTED.value, Post.posted_at >= today_start)
    )).scalar() or 0
    
    return {"total_articles": total, "articles_today": today_count, "pending_posts": pending, "posted_today": posted}

@app.get("/api/articles")
async def get_articles(status: str = None, limit: int = 50, session: AsyncSession = Depends(get_session)):
    query = select(Article).order_by(desc(Article.relevance_score), desc(Article.published_at))
    if status:
        query = query.where(Article.status == status)
    result = await session.execute(query.limit(limit))
    return [
        {"id": a.id, "url": a.url, "title": a.title, "summary": (a.summary or "")[:300],
         "source_name": a.source_name, "relevance_score": a.relevance_score, 
         "categories": a.categories, "status": a.status}
        for a in result.scalars().all()
    ]

@app.post("/api/articles/{article_id}/approve")
async def approve_article(article_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Article).where(Article.id == article_id))
    article = result.scalar()
    if not article:
        raise HTTPException(404, "Not found")
    article.status = ArticleStatus.APPROVED.value
    await session.commit()
    return {"success": True}

@app.post("/api/articles/{article_id}/reject")
async def reject_article(article_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Article).where(Article.id == article_id))
    article = result.scalar()
    if not article:
        raise HTTPException(404, "Not found")
    article.status = ArticleStatus.REJECTED.value
    await session.commit()
    return {"success": True}

@app.post("/api/articles/approve-top")
async def approve_top(min_score: float = 0.15, limit: int = 10, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Article)
        .where(Article.status.in_([ArticleStatus.FETCHED.value, ArticleStatus.PROCESSED.value]), 
               Article.relevance_score >= min_score)
        .order_by(desc(Article.relevance_score))
        .limit(limit)
    )
    articles = result.scalars().all()
    for a in articles:
        a.status = ArticleStatus.APPROVED.value
    await session.commit()
    return {"success": True, "count": len(articles)}

@app.get("/api/posts")
async def get_posts(limit: int = 50, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Post).order_by(desc(Post.created_at)).limit(limit))
    return [
        {"id": p.id, "article_id": p.article_id, "platform": p.platform,
         "content": p.content, "status": p.status, "platform_url": p.platform_url}
        for p in result.scalars().all()
    ]

@app.post("/api/posts/generate/{article_id}")
async def generate_posts(article_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Article).where(Article.id == article_id))
    article = result.scalar()
    if not article:
        raise HTTPException(404, "Not found")
    
    posts = generator.create_all_posts(article)
    for p in posts:
        session.add(p)
    article.status = ArticleStatus.QUEUED.value
    await session.commit()
    return {"success": True, "count": len(posts)}

@app.post("/api/posts/{post_id}/publish")
async def publish_post(post_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Post).where(Post.id == post_id))
    post = result.scalar()
    if not post:
        raise HTTPException(404, "Not found")
    
    post.status = PostStatus.POSTED.value
    post.posted_at = datetime.utcnow()
    await session.commit()
    return {"success": True}

@app.get("/api/sources")
async def get_sources(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Source).order_by(Source.name))
    return [{"id": s.id, "name": s.name, "url": s.url, "enabled": s.enabled, "fetch_count": s.fetch_count}
            for s in result.scalars().all()]

@app.post("/api/sources/{source_id}/toggle")
async def toggle_source(source_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Source).where(Source.id == source_id))
    source = result.scalar()
    if not source:
        raise HTTPException(404, "Not found")
    source.enabled = not source.enabled
    await session.commit()
    return {"success": True}

@app.post("/api/actions/fetch")
async def trigger_fetch(background_tasks: BackgroundTasks):
    background_tasks.add_task(job_fetch_news)
    return {"success": True}

@app.post("/api/actions/process")
async def trigger_process(background_tasks: BackgroundTasks):
    background_tasks.add_task(job_process_articles)
    return {"success": True}

@app.get("/api/platform-status")
async def get_platform_status():
    return poster.get_platform_status()

@app.get("/api/health")
async def health():
    return {"status": "healthy"}
