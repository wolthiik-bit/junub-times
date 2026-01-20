"""
Junub Times - AI News Scraper for South Sudan
"""
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import feedparser
import httpx
from datetime import datetime
from typing import List, Dict
import os

# ============== APP SETUP ==============
app = FastAPI(title="Junub Times", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== IN-MEMORY STORAGE ==============
# Simple storage (resets when app restarts - fine for MVP)
articles_db: List[Dict] = []
posts_db: List[Dict] = []

# ============== NEWS SOURCES ==============
RSS_SOURCES = [
    # ===== SOUTH SUDAN SPECIFIC =====
    ("Google News - South Sudan", "https://news.google.com/rss/search?q=%22South+Sudan%22&hl=en&gl=US&ceid=US:en"),
    ("Google News - Juba", "https://news.google.com/rss/search?q=Juba+South+Sudan&hl=en&gl=US&ceid=US:en"),
    ("Google News - Salva Kiir", "https://news.google.com/rss/search?q=%22Salva+Kiir%22&hl=en&gl=US&ceid=US:en"),
    ("Google News - Riek Machar", "https://news.google.com/rss/search?q=%22Riek+Machar%22&hl=en&gl=US&ceid=US:en"),
    ("Google News - UNMISS", "https://news.google.com/rss/search?q=UNMISS+South+Sudan&hl=en&gl=US&ceid=US:en"),
    ("Google News - South Sudan Oil", "https://news.google.com/rss/search?q=South+Sudan+oil&hl=en&gl=US&ceid=US:en"),
    ("Google News - South Sudan Peace", "https://news.google.com/rss/search?q=South+Sudan+peace&hl=en&gl=US&ceid=US:en"),
    ("Google News - South Sudan Refugees", "https://news.google.com/rss/search?q=South+Sudan+refugees&hl=en&gl=US&ceid=US:en"),
    
    # ===== SUDAN & NEIGHBORS =====
    ("Google News - Sudan", "https://news.google.com/rss/search?q=Sudan+NOT+%22South+Sudan%22&hl=en&gl=US&ceid=US:en"),
    ("Google News - Khartoum", "https://news.google.com/rss/search?q=Khartoum&hl=en&gl=US&ceid=US:en"),
    ("Google News - Sudan War", "https://news.google.com/rss/search?q=Sudan+war+conflict&hl=en&gl=US&ceid=US:en"),
    ("Google News - Abyei", "https://news.google.com/rss/search?q=Abyei&hl=en&gl=US&ceid=US:en"),
    
    # ===== EAST AFRICA REGIONAL =====
    ("Google News - East Africa", "https://news.google.com/rss/search?q=%22East+Africa%22&hl=en&gl=US&ceid=US:en"),
    ("Google News - IGAD", "https://news.google.com/rss/search?q=IGAD&hl=en&gl=US&ceid=US:en"),
    ("Google News - EAC", "https://news.google.com/rss/search?q=%22East+African+Community%22&hl=en&gl=US&ceid=US:en"),
    ("Google News - Kenya", "https://news.google.com/rss/search?q=Kenya&hl=en&gl=US&ceid=US:en"),
    ("Google News - Uganda", "https://news.google.com/rss/search?q=Uganda&hl=en&gl=US&ceid=US:en"),
    ("Google News - Ethiopia", "https://news.google.com/rss/search?q=Ethiopia&hl=en&gl=US&ceid=US:en"),
    ("Google News - Addis Ababa", "https://news.google.com/rss/search?q=%22Addis+Ababa%22&hl=en&gl=US&ceid=US:en"),
    ("Google News - Somalia", "https://news.google.com/rss/search?q=Somalia&hl=en&gl=US&ceid=US:en"),
    ("Google News - DR Congo", "https://news.google.com/rss/search?q=%22DR+Congo%22+OR+%22DRC%22&hl=en&gl=US&ceid=US:en"),
    ("Google News - Rwanda", "https://news.google.com/rss/search?q=Rwanda&hl=en&gl=US&ceid=US:en"),
    ("Google News - Burundi", "https://news.google.com/rss/search?q=Burundi&hl=en&gl=US&ceid=US:en"),
    ("Google News - Tanzania", "https://news.google.com/rss/search?q=Tanzania&hl=en&gl=US&ceid=US:en"),
    
    # ===== AFRICAN UNION & CONTINENTAL =====
    ("Google News - African Union", "https://news.google.com/rss/search?q=%22African+Union%22&hl=en&gl=US&ceid=US:en"),
    ("Google News - AU Peace Security", "https://news.google.com/rss/search?q=%22African+Union%22+peace+security&hl=en&gl=US&ceid=US:en"),
    
    # ===== UN & HUMANITARIAN =====
    ("UN News - Africa", "https://news.un.org/feed/subscribe/en/news/region/africa/feed/rss.xml"),
    ("UN News - Peace", "https://news.un.org/feed/subscribe/en/news/topic/peace-and-security/feed/rss.xml"),
    ("UN News - Humanitarian", "https://news.un.org/feed/subscribe/en/news/topic/humanitarian-aid/feed/rss.xml"),
    ("ReliefWeb - South Sudan", "https://reliefweb.int/updates/rss.xml?country=219"),
    ("ReliefWeb - Sudan", "https://reliefweb.int/updates/rss.xml?country=214"),
    ("ReliefWeb - East Africa", "https://reliefweb.int/updates/rss.xml?country=503"),
    ("UNHCR News", "https://www.unhcr.org/rss/news.xml"),
    ("WFP News", "https://www.wfp.org/rss.xml"),
    
    # ===== MAJOR AFRICA NEWS OUTLETS =====
    ("AllAfrica - South Sudan", "https://allafrica.com/tools/headlines/rdf/southsudan/headlines.rdf"),
    ("AllAfrica - Sudan", "https://allafrica.com/tools/headlines/rdf/sudan/headlines.rdf"),
    ("AllAfrica - East Africa", "https://allafrica.com/tools/headlines/rdf/eastafrica/headlines.rdf"),
    ("AllAfrica - Kenya", "https://allafrica.com/tools/headlines/rdf/kenya/headlines.rdf"),
    ("AllAfrica - Uganda", "https://allafrica.com/tools/headlines/rdf/uganda/headlines.rdf"),
    ("AllAfrica - Ethiopia", "https://allafrica.com/tools/headlines/rdf/ethiopia/headlines.rdf"),
    
    # ===== INTERNATIONAL COVERAGE =====
    ("Google News - Africa BBC", "https://news.google.com/rss/search?q=Africa+site:bbc.com&hl=en&gl=US&ceid=US:en"),
    ("Google News - Africa Reuters", "https://news.google.com/rss/search?q=Africa+site:reuters.com&hl=en&gl=US&ceid=US:en"),
    ("Google News - Africa Aljazeera", "https://news.google.com/rss/search?q=Africa+site:aljazeera.com&hl=en&gl=US&ceid=US:en"),
    ("Google News - Africa France24", "https://news.google.com/rss/search?q=Africa+site:france24.com&hl=en&gl=US&ceid=US:en"),
    ("Google News - Africa VOA", "https://news.google.com/rss/search?q=Africa+site:voanews.com&hl=en&gl=US&ceid=US:en"),
    
    # ===== ECONOMY & DEVELOPMENT =====
    ("Google News - Africa Economy", "https://news.google.com/rss/search?q=Africa+economy+development&hl=en&gl=US&ceid=US:en"),
    ("Google News - Nile River", "https://news.google.com/rss/search?q=%22Nile+River%22+OR+%22Blue+Nile%22+OR+%22White+Nile%22&hl=en&gl=US&ceid=US:en"),
    ("Google News - GERD Dam", "https://news.google.com/rss/search?q=GERD+Ethiopia+dam&hl=en&gl=US&ceid=US:en"),
    
    # ===== SPORTS =====
    ("Google News - Africa Football", "https://news.google.com/rss/search?q=Africa+football+soccer&hl=en&gl=US&ceid=US:en"),
    ("Google News - AFCON", "https://news.google.com/rss/search?q=AFCON+%22Africa+Cup%22&hl=en&gl=US&ceid=US:en"),
]

# ============== RELEVANCE KEYWORDS ==============
KEYWORDS = [
    # South Sudan - Highest Priority
    "south sudan", "juba", "junub", "splm", "spla", 
    "salva kiir", "riek machar", "taban deng", "rebecca nyandeng",
    "unmiss", "r-arcss", "revitalized agreement",
    
    # South Sudan Regions & Cities
    "upper nile", "unity state", "jonglei", "warrap", "lakes state",
    "western equatoria", "eastern equatoria", "central equatoria",
    "western bahr el ghazal", "northern bahr el ghazal",
    "wau", "malakal", "bentiu", "bor", "yei", "nimule", "torit",
    "renk", "aweil", "kuajok", "rumbek", "yambio", "kapoeta",
    
    # Sudan & Border
    "sudan", "khartoum", "abyei", "heglig", "rsf", "rapid support forces",
    "abdel fattah al-burhan", "hemeti", "darfur", "blue nile state",
    
    # East Africa Countries
    "kenya", "nairobi", "uganda", "kampala", "ethiopia", "addis ababa",
    "somalia", "mogadishu", "eritrea", "asmara", "djibouti",
    "tanzania", "dar es salaam", "rwanda", "kigali", 
    "burundi", "bujumbura", "dr congo", "drc", "kinshasa",
    
    # Regional Organizations
    "igad", "east african community", "eac", "african union", "au",
    "comesa", "continental free trade",
    
    # Key Topics
    "refugee", "humanitarian", "famine", "hunger", "food crisis",
    "peace agreement", "ceasefire", "conflict", "civil war",
    "oil production", "petroleum", "pipeline",
    "nile", "white nile", "blue nile", "gerd", "dam",
    "election", "constitution", "government",
    "flood", "drought", "climate", "agriculture",
    "cholera", "malaria", "health crisis",
]

# ============== HELPER FUNCTIONS ==============
def calculate_relevance(title: str, summary: str) -> float:
    text = f"{title} {summary}".lower()
    score = sum(1 for kw in KEYWORDS if kw in text)
    return min(score / 5, 1.0)

async def fetch_rss(url: str, source_name: str) -> List[Dict]:
    articles = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            feed = feedparser.parse(response.text)
            
            for entry in feed.entries[:15]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", "")[:500]
                
                if title and link:
                    relevance = calculate_relevance(title, summary)
                    if relevance >= 0.1:  # Only keep somewhat relevant articles
                        articles.append({
                            "id": len(articles_db) + len(articles) + 1,
                            "title": title,
                            "url": link,
                            "summary": summary,
                            "source": source_name,
                            "relevance": round(relevance, 2),
                            "status": "fetched",
                            "fetched_at": datetime.utcnow().isoformat()
                        })
    except Exception as e:
        print(f"Error fetching {source_name}: {e}")
    
    return articles

def generate_posts(article: Dict) -> List[Dict]:
    """Generate social media posts for an article"""
    hashtags = "#SouthSudan #Juba #JunubTimes #EastAfrica"
    posts = []
    
    # X (Twitter) post
    title_short = article["title"][:200]
    posts.append({
        "id": len(posts_db) + 1,
        "article_id": article["id"],
        "platform": "x",
        "content": f"{title_short}\n\n{article['url']}\n\n{hashtags}",
        "status": "pending"
    })
    
    # Facebook post
    posts.append({
        "id": len(posts_db) + 2,
        "article_id": article["id"],
        "platform": "facebook",
        "content": f"📰 {article['title']}\n\n{article['summary'][:300]}...\n\n🔗 Read more: {article['url']}\n\n{hashtags}",
        "status": "pending"
    })
    
    # Instagram post
    posts.append({
        "id": len(posts_db) + 3,
        "article_id": article["id"],
        "platform": "instagram",
        "content": f"🇸🇸 {article['title']}\n\n{article['summary'][:250]}...\n\n📱 Follow @junubtimes for more!\n\n{hashtags} #News #Africa",
        "status": "pending"
    })
    
    # TikTok post
    posts.append({
        "id": len(posts_db) + 4,
        "article_id": article["id"],
        "platform": "tiktok",
        "content": f"🚨 {article['title'][:100]}\n\nFollow for South Sudan news!\n\n{hashtags} #FYP #NewsUpdate",
        "status": "pending"
    })
    
    return posts

# ============== BACKGROUND TASKS ==============
async def fetch_all_news():
    """Fetch news from all sources"""
    print(f"📰 Fetching news at {datetime.utcnow()}")
    
    for source_name, url in RSS_SOURCES:
        new_articles = await fetch_rss(url, source_name)
        
        # Add only new articles (check by URL)
        existing_urls = {a["url"] for a in articles_db}
        for article in new_articles:
            if article["url"] not in existing_urls:
                articles_db.append(article)
    
    print(f"✅ Total articles: {len(articles_db)}")

# ============== DASHBOARD HTML ==============
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Junub Times Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
    <style>[v-cloak] { display: none; }</style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div id="app" v-cloak>
        <!-- Header -->
        <header class="bg-gradient-to-r from-blue-900 to-blue-700 text-white py-6 px-8 shadow-lg">
            <div class="max-w-6xl mx-auto flex flex-col md:flex-row justify-between items-center gap-4">
                <div>
                    <h1 class="text-3xl font-bold">🇸🇸 Junub Times</h1>
                    <p class="text-blue-200">AI News Automation for South Sudan</p>
                </div>
                <div class="flex gap-3">
                    <button @click="fetchNews" :disabled="loading" 
                            class="bg-blue-600 hover:bg-blue-500 px-6 py-2 rounded-lg font-medium disabled:opacity-50">
                        {{ loading ? '⏳ Loading...' : '🔄 Fetch News' }}
                    </button>
                </div>
            </div>
        </header>

        <main class="max-w-6xl mx-auto px-8 py-8">
            <!-- Stats -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                <div class="bg-white rounded-xl shadow p-6 text-center">
                    <p class="text-gray-500 text-sm">Total Articles</p>
                    <p class="text-3xl font-bold text-blue-600">{{ articles.length }}</p>
                </div>
                <div class="bg-white rounded-xl shadow p-6 text-center">
                    <p class="text-gray-500 text-sm">Approved</p>
                    <p class="text-3xl font-bold text-green-600">{{ articles.filter(a => a.status === 'approved').length }}</p>
                </div>
                <div class="bg-white rounded-xl shadow p-6 text-center">
                    <p class="text-gray-500 text-sm">Pending Posts</p>
                    <p class="text-3xl font-bold text-yellow-600">{{ posts.filter(p => p.status === 'pending').length }}</p>
                </div>
                <div class="bg-white rounded-xl shadow p-6 text-center">
                    <p class="text-gray-500 text-sm">Published</p>
                    <p class="text-3xl font-bold text-purple-600">{{ posts.filter(p => p.status === 'posted').length }}</p>
                </div>
            </div>

            <!-- Tabs -->
            <div class="flex gap-4 mb-6 border-b">
                <button @click="tab = 'articles'" 
                        :class="['pb-3 px-4 font-medium', tab === 'articles' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500']">
                    📰 Articles
                </button>
                <button @click="tab = 'posts'" 
                        :class="['pb-3 px-4 font-medium', tab === 'posts' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500']">
                    📝 Posts
                </button>
            </div>

            <!-- Articles Tab -->
            <div v-if="tab === 'articles'" class="space-y-4">
                <div class="flex gap-3 mb-4">
                    <button @click="approveTop" class="bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700">
                        ✅ Approve Top 5
                    </button>
                </div>
                
                <div v-if="articles.length === 0" class="bg-white rounded-xl p-12 text-center text-gray-500">
                    <p class="text-4xl mb-4">📭</p>
                    <p>No articles yet. Click "Fetch News" to get started!</p>
                </div>
                
                <div v-for="article in sortedArticles" :key="article.id" class="bg-white rounded-xl shadow p-6">
                    <div class="flex flex-col md:flex-row md:justify-between gap-4">
                        <div class="flex-1">
                            <div class="flex flex-wrap gap-2 mb-2">
                                <span :class="['px-3 py-1 rounded-full text-xs font-bold', 
                                    article.status === 'approved' ? 'bg-green-100 text-green-800' : 
                                    article.status === 'posted' ? 'bg-purple-100 text-purple-800' : 
                                    'bg-gray-100 text-gray-800']">
                                    {{ article.status.toUpperCase() }}
                                </span>
                                <span class="px-3 py-1 rounded-full text-xs bg-blue-100 text-blue-800">
                                    {{ (article.relevance * 100).toFixed(0) }}% relevant
                                </span>
                                <span class="text-sm text-gray-500">{{ article.source }}</span>
                            </div>
                            <h3 class="font-semibold text-lg mb-2">{{ article.title }}</h3>
                            <p class="text-gray-600 text-sm">{{ article.summary?.substring(0, 200) }}...</p>
                        </div>
                        <div class="flex md:flex-col gap-2">
                            <button v-if="article.status === 'fetched'" @click="approveArticle(article)"
                                    class="bg-green-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-green-700">
                                ✅ Approve
                            </button>
                            <button v-if="article.status === 'approved'" @click="generateArticlePosts(article)"
                                    class="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700">
                                📝 Generate
                            </button>
                            <a :href="article.url" target="_blank" 
                               class="bg-gray-200 px-4 py-2 rounded-lg text-sm text-center hover:bg-gray-300">
                                🔗 View
                            </a>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Posts Tab -->
            <div v-if="tab === 'posts'" class="space-y-4">
                <div v-if="posts.length === 0" class="bg-white rounded-xl p-12 text-center text-gray-500">
                    <p class="text-4xl mb-4">📝</p>
                    <p>No posts yet. Approve articles and click "Generate"!</p>
                </div>
                
                <div v-for="post in posts" :key="post.id" class="bg-white rounded-xl shadow p-6">
                    <div class="flex flex-col md:flex-row md:justify-between gap-4">
                        <div class="flex-1">
                            <div class="flex items-center gap-3 mb-3">
                                <span class="text-2xl">{{ platformIcon(post.platform) }}</span>
                                <span class="font-bold uppercase">{{ post.platform }}</span>
                                <span :class="['px-3 py-1 rounded-full text-xs font-bold',
                                    post.status === 'posted' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800']">
                                    {{ post.status.toUpperCase() }}
                                </span>
                            </div>
                            <pre class="bg-gray-50 p-4 rounded-lg text-sm whitespace-pre-wrap font-sans">{{ post.content }}</pre>
                        </div>
                        <div class="flex md:flex-col gap-2">
                            <button @click="copyPost(post)" 
                                    class="bg-gray-200 px-4 py-2 rounded-lg text-sm hover:bg-gray-300">
                                📋 Copy
                            </button>
                            <button v-if="post.status === 'pending'" @click="markPosted(post)"
                                    class="bg-purple-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-purple-700">
                                ✅ Mark Posted
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </main>

        <!-- Toast -->
        <div v-if="toast" class="fixed bottom-6 right-6 bg-gray-900 text-white px-6 py-4 rounded-xl shadow-2xl z-50">
            {{ toast }}
        </div>
    </div>

    <script>
    const { createApp } = Vue
    
    createApp({
        data() {
            return {
                tab: 'articles',
                loading: false,
                toast: null,
                articles: [],
                posts: []
            }
        },
        computed: {
            sortedArticles() {
                return [...this.articles].sort((a, b) => b.relevance - a.relevance)
            }
        },
        methods: {
            async api(url, method = 'GET') {
                const res = await fetch('/api' + url, { method })
                return res.json()
            },
            showToast(msg) {
                this.toast = msg
                setTimeout(() => this.toast = null, 3000)
            },
            platformIcon(p) {
                return { x: '𝕏', facebook: '📘', instagram: '📸', tiktok: '🎵' }[p] || '📱'
            },
            async fetchNews() {
                this.loading = true
                await this.api('/fetch', 'POST')
                this.showToast('🔄 Fetching news...')
                setTimeout(async () => {
                    this.articles = await this.api('/articles')
                    this.loading = false
                    this.showToast('✅ News fetched!')
                }, 3000)
            },
            async approveArticle(article) {
                await this.api('/articles/' + article.id + '/approve', 'POST')
                article.status = 'approved'
                this.showToast('✅ Approved!')
            },
            async approveTop() {
                const fetched = this.articles.filter(a => a.status === 'fetched')
                    .sort((a, b) => b.relevance - a.relevance)
                    .slice(0, 5)
                for (const article of fetched) {
                    await this.api('/articles/' + article.id + '/approve', 'POST')
                    article.status = 'approved'
                }
                this.showToast('✅ Top 5 approved!')
            },
            async generateArticlePosts(article) {
                const newPosts = await this.api('/articles/' + article.id + '/generate', 'POST')
                this.posts = await this.api('/posts')
                article.status = 'posted'
                this.showToast('📝 Posts generated!')
            },
            copyPost(post) {
                navigator.clipboard.writeText(post.content)
                this.showToast('📋 Copied!')
            },
            async markPosted(post) {
                await this.api('/posts/' + post.id + '/posted', 'POST')
                post.status = 'posted'
                this.showToast('✅ Marked as posted!')
            },
            async loadData() {
                this.articles = await this.api('/articles')
                this.posts = await this.api('/posts')
            }
        },
        async mounted() {
            await this.loadData()
        }
    }).mount('#app')
    </script>
</body>
</html>
"""

# ============== API ROUTES ==============
@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the dashboard"""
    return HTMLResponse(content=DASHBOARD_HTML)

@app.get("/api/articles")
async def get_articles():
    """Get all articles"""
    return articles_db

@app.get("/api/posts")
async def get_posts():
    """Get all posts"""
    return posts_db

@app.post("/api/fetch")
async def trigger_fetch(background_tasks: BackgroundTasks):
    """Trigger news fetch"""
    background_tasks.add_task(fetch_all_news)
    return {"success": True, "message": "Fetching news..."}

@app.post("/api/articles/{article_id}/approve")
async def approve_article(article_id: int):
    """Approve an article"""
    for article in articles_db:
        if article["id"] == article_id:
            article["status"] = "approved"
            return {"success": True}
    return {"success": False, "error": "Not found"}

@app.post("/api/articles/{article_id}/generate")
async def generate_article_posts(article_id: int):
    """Generate posts for an article"""
    for article in articles_db:
        if article["id"] == article_id:
            new_posts = generate_posts(article)
            posts_db.extend(new_posts)
            article["status"] = "posted"
            return new_posts
    return {"success": False, "error": "Not found"}

@app.post("/api/posts/{post_id}/posted")
async def mark_post_posted(post_id: int):
    """Mark a post as posted"""
    for post in posts_db:
        if post["id"] == post_id:
            post["status"] = "posted"
            return {"success": True}
    return {"success": False, "error": "Not found"}

@app.get("/api/health")
async def health():
    """Health check"""
    return {"status": "healthy", "time": datetime.utcnow().isoformat()}

# ============== STARTUP ==============
@app.on_event("startup")
async def startup():
    print("=" * 50)
    print("🇸🇸 JUNUB TIMES - Starting up...")
    print("=" * 50)
    # Fetch news on startup
    asyncio.create_task(fetch_all_news())
