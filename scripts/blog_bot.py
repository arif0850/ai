#!/usr/bin/env python3
"""
Blog Bot with Channel Support
- Reads from Telegram Channel (bot as admin)
- Sends preview to user DM
- Auto-categorize + Auto SEO
"""

import os
import json
import re
import requests
import base64
from datetime import datetime
from pathlib import Path
from collections import Counter

# ============================================================
# CONFIG
# ============================================================
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')          # User DM
TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')    # Channel
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
GITHUB_REPO = 'arif0850/ai'
GITHUB_API = 'https://api.github.com'
TELEGRAM_API = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'

STATE_FILE = 'scripts/blog-state.json'
POSTS_INDEX_FILE = 'scripts/posts-index.json'
CATEGORIES_FILE = 'scripts/categories.json'
POSTS_DIR = 'posts'
IMAGES_DIR = 'posts/images'
SITEMAP_FILE = 'sitemap.xml'

SITE_URL = 'https://www.hiarif.com'
AUTHOR_NAME = 'Md. Ariful Islam'
DEFAULT_OG_IMAGE = f'{SITE_URL}/assets/images/og-image.png'

STOPWORDS = set("""
a an the and or but if then else when while for to of in on at by with from as is are was were be been being have has had do does did
this that these those it its i you he she we they them their our your my his her
will would can could should may might must shall
about into over under after before during through above below between
not no nor so than too very just also only
""".split())

# ============================================================
# LOGGER
# ============================================================
def log(msg):
    print(f"[BLOG-BOT] {msg}")

# ============================================================
# STATE
# ============================================================
def load_state():
    if Path(STATE_FILE).exists():
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                if 'pending' not in data:
                    data['pending'] = {}
                if 'last_photo_id' not in data:
                    data['last_photo_id'] = None
                return data
        except Exception as e:
            log(f"State load error: {e}")
    return {'last_update_id': 0, 'pending': {}, 'last_photo_id': None}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# ============================================================
# TELEGRAM
# ============================================================
def tg_send(chat_id, text, reply_markup=None, parse_mode='HTML'):
    try:
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode,
            'disable_web_page_preview': True,
        }
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup)
        r = requests.post(f'{TELEGRAM_API}/sendMessage', data=payload, timeout=10)
        return r.json()
    except Exception as e:
        log(f"tg_send error: {e}")
        return None

def tg_edit_text(message_id, text, reply_markup=None):
    try:
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'message_id': message_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup)
        r = requests.post(f'{TELEGRAM_API}/editMessageText', data=payload, timeout=10)
        return r.json()
    except Exception as e:
        log(f"tg_edit_text error: {e}")
        return None

def tg_answer_callback(callback_id, text=''):
    try:
        requests.post(f'{TELEGRAM_API}/answerCallbackQuery', data={
            'callback_query_id': callback_id,
            'text': text,
        }, timeout=10)
    except Exception as e:
        log(f"tg_answer_callback error: {e}")

def get_updates(last_update_id):
    try:
        r = requests.get(f'{TELEGRAM_API}/getUpdates', params={
            'offset': last_update_id + 1,
            'timeout': 5,
            'allowed_updates': json.dumps(['message', 'callback_query', 'channel_post']),
        }, timeout=15)
        r.raise_for_status()
        return r.json().get('result', [])
    except Exception as e:
        log(f"getUpdates error: {e}")
        return []

def download_photo(file_id):
    try:
        r = requests.get(f'{TELEGRAM_API}/getFile', params={'file_id': file_id}, timeout=10)
        r.raise_for_status()
        file_path = r.json()['result']['file_path']
        dl_url = f'https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}'
        r = requests.get(dl_url, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception as e:
        log(f"Photo download error: {e}")
        return None

# ============================================================
# PARSER
# ============================================================
def parse_post(text):
    if not text:
        return None
    if not text.strip().lower().startswith('/newpost'):
        return None
    text = text.strip()[8:].strip()
    title = None
    content_lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.lower().startswith('title:'):
            title = stripped[6:].strip()
        else:
            content_lines.append(line)
    content = '\n'.join(content_lines).strip()
    content = re.sub(r'-{3,}\s*END\s*-{3,}', '', content, flags=re.IGNORECASE).strip()
    if not title:
        if content:
            title = content.split('\n')[0][:80].strip()
            content = '\n'.join(content.split('\n')[1:]).strip()
        else:
            return None
    if not content:
        return None
    return {'title': title, 'content': content}

# ============================================================
# SEO / UTILS
# ============================================================
def slugify(text):
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return text[:60]

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def make_description(content, limit=155):
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    text = re.sub(r'^-\s+', '', text, flags=re.MULTILINE)
    text = clean_text(text)
    if len(text) <= limit:
        return text
    return text[:limit - 3].rsplit(' ', 1)[0] + '...'

def extract_keywords(content, top_n=10):
    text = re.sub(r'[^\w\s]', ' ', content.lower())
    words = [w for w in text.split() if len(w) > 3 and w not in STOPWORDS and not w.isdigit()]
    counts = Counter(words)
    return [w for w, _ in counts.most_common(top_n)]

def word_count(content):
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    return len(re.findall(r'\w+', text))

def reading_time(wc):
    minutes = max(1, round(wc / 200))
    return f"{minutes} min read"

def seo_score(post, images):
    score = 0
    if post['title'] and len(post['title']) < 60:
        score += 2
    if len(post['content']) > 300:
        score += 2
    if images:
        score += 2
    if len(extract_keywords(post['content'])) >= 5:
        score += 2
    if word_count(post['content']) >= 100:
        score += 2
    return min(10, score)

def markdown_to_html(text):
    html = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" target="_blank" rel="noopener">\1</a>', html)
    paragraphs = html.split('\n\n')
    result = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if p.startswith('- '):
            items = [f'<li>{line[2:].strip()}</li>' for line in p.split('\n') if line.strip().startswith('- ')]
            result.append(f'<ul>{"".join(items)}</ul>')
        else:
            result.append(f'<p>{p.replace(chr(10), "<br>")}</p>')
    return '\n'.join(result)

# ============================================================
# CATEGORIES
# ============================================================
def load_categories():
    try:
        if Path(CATEGORIES_FILE).exists():
            with open(CATEGORIES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f).get('categories', [])
    except Exception as e:
        log(f"Categories load error: {e}")
    return []

def detect_category(title, content):
    cats = load_categories()
    if not cats:
        return 'notes'
    text = (title + ' ' + content).lower()
    text_words = set(re.findall(r'\b\w+\b', text))
    best_cat = 'notes'
    best_score = 0
    for cat in cats:
        if cat['id'] == 'notes':
            continue
        keywords = cat.get('keywords', [])
        if not keywords:
            continue
        score = 0
        for kw in keywords:
            kw_lower = kw.lower()
            if ' ' in kw_lower:
                if kw_lower in text:
                    score += 3
            elif kw_lower in text_words:
                score += 2
            elif kw_lower in text:
                score += 1
        if score > best_score:
            best_score = score
            best_cat = cat['id']
    log(f"Category detected: {best_cat} (score: {best_score})")
    return best_cat

def get_category_name(cat_id):
    cats = load_categories()
    for c in cats:
        if c['id'] == cat_id:
            return c['name']
    return 'Field Notes'

# ============================================================
# HTML GENERATOR
# ============================================================
def generate_html(post, slug, image_paths):
    now = datetime.now()
    date_str = now.strftime('%B %d, %Y')
    date_iso = now.strftime('%Y-%m-%d')
    url = f'{SITE_URL}/posts/{slug}.html'
    description = make_description(post['content'])
    keywords = extract_keywords(post['content'])
    wc = word_count(post['content'])
    rt = reading_time(wc)
    og_image = DEFAULT_OG_IMAGE
    if image_paths:
        first = image_paths[0]
        og_image = first if first.startswith('http') else f'{SITE_URL}/{first}'
    content_html = markdown_to_html(post['content'])
    images_html = ''
    if image_paths:
        for img in image_paths:
            src = img if img.startswith('http') else f'../{img}'
            images_html += f'\n<div class="post-image"><img src="{src}" alt="{post["title"]}" loading="lazy"></div>'
    keywords_meta = ', '.join(keywords)
    schema_json = json.dumps({
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post['title'],
        "description": description,
        "image": og_image,
        "author": {"@type": "Person", "name": AUTHOR_NAME, "url": SITE_URL},
        "publisher": {"@type": "Person", "name": AUTHOR_NAME},
        "datePublished": date_iso,
        "dateModified": date_iso,
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "wordCount": wc,
        "keywords": keywords_meta,
        "inLanguage": "en-US"
    }, indent=2)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{post['title']} | {AUTHOR_NAME}</title>
  <meta name="description" content="{description}">
  <meta name="author" content="{AUTHOR_NAME}">
  <meta name="keywords" content="{keywords_meta}">
  <link rel="canonical" href="{url}">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{post['title']}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{url}">
  <meta property="og:image" content="{og_image}">
  <meta property="og:site_name" content="{AUTHOR_NAME}">
  <meta property="article:published_time" content="{date_iso}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{post['title']}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{og_image}">
  <meta name="theme-color" content="#121212">
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
  <script type="application/ld+json">
{schema_json}
  </script>
  <style>
    :root {{ --bg-main: #121212; --bg-card: #1e1e1e; --bg-inner: #232323;
      --accent: #ffdb6e; --text-main: #ffffff; --text-soft: #e5e5e5;
      --text-muted: #a3a3a3; --border: #2f2f2f;
      --radius-md: 14px; --radius-lg: 20px; }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Inter', -apple-system, sans-serif;
      background: var(--bg-main); color: var(--text-main);
      line-height: 1.7; padding: 40px 20px 100px; min-height: 100vh;
      letter-spacing: -0.01em; }}
    .container {{ max-width: 800px; margin: 0 auto; }}
    .back-link {{ display: inline-flex; align-items: center; gap: 8px;
      color: var(--accent); text-decoration: none; font-size: 0.9rem;
      font-weight: 600; margin-bottom: 30px; transition: all 0.3s ease; }}
    .back-link:hover {{ transform: translateX(-4px); }}
    .post-header {{ margin-bottom: 30px; padding-bottom: 30px;
      border-bottom: 1px solid var(--border); }}
    .post-date {{ font-size: 0.75rem; color: var(--accent);
      text-transform: uppercase; letter-spacing: 0.12em;
      font-weight: 700; margin-bottom: 12px; }}
    .post-title {{ font-size: 2.2rem; font-weight: 800;
      line-height: 1.2; letter-spacing: -0.03em; color: var(--text-main); }}
    .post-meta {{ display: flex; gap: 18px; margin-top: 16px;
      font-size: 0.8rem; color: var(--text-muted); flex-wrap: wrap; }}
    .post-meta span {{ display: inline-flex; align-items: center; gap: 6px; }}
    .post-content {{ font-size: 1.05rem; color: var(--text-soft); }}
    .post-content p {{ margin-bottom: 20px; line-height: 1.8; }}
    .post-content h2 {{ font-size: 1.5rem; font-weight: 700;
      color: var(--text-main); margin: 32px 0 16px; letter-spacing: -0.02em; }}
    .post-content h3 {{ font-size: 1.2rem; font-weight: 700;
      color: var(--text-main); margin: 24px 0 12px; }}
    .post-content ul {{ margin: 16px 0 20px 24px; }}
    .post-content li {{ margin-bottom: 8px; color: var(--text-soft); }}
    .post-content strong {{ color: var(--text-main); font-weight: 700; }}
    .post-content em {{ color: var(--text-soft); font-style: italic; }}
    .post-content a {{ color: var(--accent); text-decoration: none;
      border-bottom: 1px solid transparent; transition: border-color 0.3s ease; }}
    .post-content a:hover {{ border-bottom-color: var(--accent); }}
    .post-image {{ margin: 24px 0; border-radius: var(--radius-md);
      overflow: hidden; border: 1px solid var(--border); }}
    .post-image img {{ width: 100%; height: auto; display: block; }}
    .post-footer {{ margin-top: 50px; padding-top: 30px;
      border-top: 1px solid var(--border); text-align: center; }}
    .post-footer a {{ display: inline-flex; align-items: center; gap: 8px;
      background: var(--accent); color: #121212; padding: 12px 24px;
      border-radius: 999px; text-decoration: none; font-weight: 700;
      font-size: 0.9rem; transition: all 0.3s ease; }}
    .post-footer a:hover {{ transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(255, 219, 110, 0.3); }}
    @media (max-width: 640px) {{
      body {{ padding: 24px 16px 80px; }}
      .post-title {{ font-size: 1.6rem; }}
      .post-content {{ font-size: 1rem; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <a href="../blog.html" class="back-link">
      <i class="fa-solid fa-arrow-left"></i> Back to Blog
    </a>
    <article>
      <header class="post-header">
        <div class="post-date">{date_str}</div>
        <h1 class="post-title">{post['title']}</h1>
        <div class="post-meta">
          <span><i class="fa-solid fa-user"></i> {AUTHOR_NAME}</span>
          <span><i class="fa-solid fa-clock"></i> {rt}</span>
          <span><i class="fa-solid fa-book"></i> {wc} words</span>
        </div>
      </header>
      {images_html}
      <div class="post-content">
        {content_html}
      </div>
    </article>
    <footer class="post-footer">
      <a href="../blog.html">
        <i class="fa-solid fa-book-open"></i> Read More Posts
      </a>
    </footer>
  </div>
</body>
</html>'''

# ============================================================
# GITHUB API
# ============================================================
def gh_headers():
    return {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }

def gh_get_file(path):
    try:
        r = requests.get(f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}',
                         headers=gh_headers(), timeout=15)
        if r.status_code == 200:
            d = r.json()
            return {'sha': d['sha'],
                    'content': base64.b64decode(d['content']).decode('utf-8')}
        return None
    except Exception as e:
        log(f"gh_get_file error {path}: {e}")
        return None

def gh_commit_file(path, content, message):
    existing = gh_get_file(path)
    payload = {
        'message': message,
        'content': base64.b64encode(content.encode('utf-8')).decode('ascii')
    }
    if existing:
        payload['sha'] = existing['sha']
    r = requests.put(f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}',
                     headers=gh_headers(), json=payload, timeout=20)
    if r.status_code in [200, 201]:
        return True
    log(f"Commit error {path}: {r.status_code}")
    return False

def gh_commit_image(path, image_bytes, message):
    payload = {
        'message': message,
        'content': base64.b64encode(image_bytes).decode('ascii')
    }
    r = requests.put(f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}',
                     headers=gh_headers(), json=payload, timeout=30)
    return r.status_code in [200, 201]

def gh_delete_file(path, message):
    existing = gh_get_file(path)
    if not existing:
        return True
    payload = {'message': message, 'sha': existing['sha']}
    r = requests.delete(f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}',
                        headers=gh_headers(), json=payload, timeout=20)
    return r.status_code in [200, 201]

# ============================================================
# SITEMAP
# ============================================================
def sitemap_add(slug, date_iso):
    url = f'{SITE_URL}/posts/{slug}.html'
    s = gh_get_file(SITEMAP_FILE)
    if not s:
        return False
    content = s['content']
    if url in content:
        return True
    entry = f'''  <!-- Blog Post -->
  <url>
    <loc>{url}</loc>
    <lastmod>{date_iso}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>
  
</urlset>'''
    content = content.replace('</urlset>', entry)
    return gh_commit_file(SITEMAP_FILE, content, f'Add {slug} to sitemap')

def sitemap_remove(slug):
    url = f'{SITE_URL}/posts/{slug}.html'
    s = gh_get_file(SITEMAP_FILE)
    if not s:
        return True
    content = s['content']
    if url not in content:
        return True
    pattern = re.compile(
        r'\s*<!-- Blog Post -->\s*<url>\s*<loc>' + re.escape(url) +
        r'</loc>.*?</url>', re.DOTALL)
    content = pattern.sub('', content)
    return gh_commit_file(SITEMAP_FILE, content, f'Remove {slug} from sitemap')

# ============================================================
# POSTS INDEX
# ============================================================
def load_posts_index():
    idx = gh_get_file(POSTS_INDEX_FILE)
    if idx:
        try:
            return json.loads(idx['content'])
        except Exception as e:
            log(f"posts-index parse error: {e}")
    return {'posts': []}

def save_posts_index(index, message):
    return gh_commit_file(
        POSTS_INDEX_FILE,
        json.dumps(index, indent=2, ensure_ascii=False),
        message
    )

def add_to_posts_index(slug, title, content, category, image_path):
    index = load_posts_index()
    index['posts'] = [p for p in index['posts'] if p.get('slug') != slug]
    excerpt = make_description(content, limit=150)
    keywords = extract_keywords(content, top_n=8)
    index['posts'].append({
        'slug': slug,
        'title': title,
        'excerpt': excerpt,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'category': category,
        'image': image_path or '',
        'keywords': keywords
    })
    index['posts'].sort(key=lambda p: p.get('date', ''), reverse=True)
    return save_posts_index(index, f'Add {slug} to posts index')

def remove_from_posts_index(slug):
    index = load_posts_index()
    original = len(index['posts'])
    index['posts'] = [p for p in index['posts'] if p.get('slug') != slug]
    if len(index['posts']) == original:
        return True
    return save_posts_index(index, f'Remove {slug} from posts index')

# ============================================================
# PENDING POST BUILDER
# ============================================================
def build_pending_and_preview(parsed, image_file_id, state):
    slug = slugify(parsed['title'])
    post_id = f"p{int(datetime.now().timestamp())}"
    category = detect_category(parsed['title'], parsed['content'])
    cat_name = get_category_name(category)

    state['pending'][post_id] = {
        'title': parsed['title'],
        'content': parsed['content'],
        'slug': slug,
        'category': category,
        'image_file_id': image_file_id,
        'created_at': datetime.now().isoformat(),
    }

    wc = word_count(parsed['content'])
    rt = reading_time(wc)
    keywords = extract_keywords(parsed['content'])
    desc = make_description(parsed['content'])
    score = seo_score(parsed, [image_file_id] if image_file_id else [])

    preview = (
        f"📝 <b>Preview Ready</b>\n\n"
        f"<b>Title:</b> {parsed['title']}\n"
        f"<b>Category:</b> {cat_name}\n"
        f"<b>Slug:</b> <code>{slug}</code>\n\n"
        f"<b>Words:</b> {wc}  •  <b>Reading:</b> {rt}\n"
        f"<b>Images:</b> {'✅ 1' if image_file_id else '❌ None'}\n"
        f"<b>SEO Score:</b> {score}/10\n\n"
        f"<b>Keywords:</b> {', '.join(keywords[:6])}\n\n"
        f"<b>Description:</b>\n<i>{desc}</i>"
    )

    keyboard = {
        'inline_keyboard': [[
            {'text': '✅ Approve', 'callback_data': f'approve:{post_id}'},
            {'text': '❌ Cancel', 'callback_data': f'cancel:{post_id}'},
        ]]
    }

    tg_send(TELEGRAM_CHAT_ID, preview, reply_markup=keyboard)


# ============================================================
# CHANNEL HANDLER (Main Flow)
# ============================================================
def handle_channel_post(post, state):
    chat_id = str(post.get('chat', {}).get('id', ''))

    if TELEGRAM_CHANNEL_ID and chat_id != str(TELEGRAM_CHANNEL_ID):
        log(f"Ignoring channel post from {chat_id}")
        return

    text = (post.get('text') or post.get('caption') or '').strip()
    has_photo = 'photo' in post

    # Case 1: Photo + /newpost caption (short post)
    if has_photo and text.lower().startswith('/newpost'):
        parsed = parse_post(text)
        if parsed:
            img_id = post['photo'][-1]['file_id']
            build_pending_and_preview(parsed, img_id, state)
            state['last_photo_id'] = None
        return

    # Case 2: /newpost text (long post)
    if text.lower().startswith('/newpost'):
        parsed = parse_post(text)
        if parsed:
            img_id = state.get('last_photo_id')
            build_pending_and_preview(parsed, img_id, state)
            state['last_photo_id'] = None
        return

    # Case 3: /skip
    if text.lower() in ['/skip', '/nophoto']:
        state['last_photo_id'] = None
        return

    # Case 4: Photo only
    if has_photo:
        state['last_photo_id'] = post['photo'][-1]['file_id']
        log(f"Photo stored for next post")
        return


# ============================================================
# USER DM HANDLER (Fallback)
# ============================================================
def handle_message(message, state):
    chat_id = str(message.get('chat', {}).get('id', ''))
    if chat_id != str(TELEGRAM_CHAT_ID):
        return

    text = message.get('text') or message.get('caption', '')
    if not text:
        return

    text_low = text.strip().lower()

    if text_low.startswith('/newpost'):
        parsed = parse_post(text)
        if parsed:
            img_id = None
            if 'photo' in message:
                img_id = message['photo'][-1]['file_id']
            else:
                img_id = state.get('last_photo_id')
                state['last_photo_id'] = None
            build_pending_and_preview(parsed, img_id, state)

    elif text_low.startswith('/delete'):
        parts = text.split()
        if len(parts) < 2:
            tg_send(TELEGRAM_CHAT_ID, "❌ <code>/delete slug-name</code> দিন।")
            return
        slug = parts[1].strip().lower()
        existing = gh_get_file(f'{POSTS_DIR}/{slug}.html')
        if not existing:
            tg_send(TELEGRAM_CHAT_ID, f"❌ <b>{slug}</b> খুঁজে পাওয়া যায়নি।")
            return
        keyboard = {'inline_keyboard': [[
            {'text': '✅ Yes, Delete', 'callback_data': f'delyes:{slug}'},
            {'text': '❌ Cancel', 'callback_data': f'delno:{slug}'},
        ]]}
        tg_send(TELEGRAM_CHAT_ID,
                f"🗑️ <b>Delete Post?</b>\n\nSlug: <code>{slug}</code>",
                reply_markup=keyboard)

    elif text_low.startswith('/list'):
        pending = state.get('pending', {})
        if not pending:
            tg_send(TELEGRAM_CHAT_ID, "📭 কোনো pending post নেই।")
            return
        lines = ["📋 <b>Pending Posts</b>\n"]
        for pid, p in pending.items():
            lines.append(f"• <code>{pid}</code> — {p['title']}")
        tg_send(TELEGRAM_CHAT_ID, '\n'.join(lines))

    elif text_low.startswith('/help') or text_low == '/start':
        tg_send(TELEGRAM_CHAT_ID,
            "🤖 <b>Blog Bot Commands</b>\n\n"
            "📢 <b>Channel-এ পোস্ট করুন:</b>\n"
            "• Photo আগে পাঠান → তারপর /newpost text\n"
            "• অথবা Photo + Caption (short post)\n\n"
            "📝 <code>/newpost</code> format:\n"
            "<code>/newpost\nTitle: Title\n\nContent\n---END---</code>\n\n"
            "🗑️ <code>/delete slug</code>\n"
            "📋 <code>/list</code>\n"
            "❓ <code>/help</code>"
        )


# ============================================================
# PUBLISH & DELETE
# ============================================================
def do_publish(state, post_id):
    p = state.get('pending', {}).get(post_id)
    if not p:
        return "❌ Post পাওয়া যায়নি (সম্ভবত expire)।"

    slug = p['slug']
    image_paths = []

    if p.get('image_file_id'):
        img_bytes = download_photo(p['image_file_id'])
        if img_bytes:
            img_path = f'{IMAGES_DIR}/{slug}.jpg'
            if gh_commit_image(img_path, img_bytes, f'Add image for {slug}'):
                image_paths.append(img_path)

    html = generate_html(p, slug, image_paths)
    if not gh_commit_file(f'{POSTS_DIR}/{slug}.html', html,
                          f'Add blog post: {p["title"]}'):
        return "❌ HTML commit করতে ব্যর্থ।"

    sitemap_add(slug, datetime.now().strftime('%Y-%m-%d'))

    image_for_index = image_paths[0] if image_paths else ''
    add_to_posts_index(
        slug=slug,
        title=p['title'],
        content=p['content'],
        category=p.get('category', 'notes'),
        image_path=image_for_index
    )

    del state['pending'][post_id]
    url = f'{SITE_URL}/posts/{slug}.html'

    return (
        f"✅ <b>Published!</b>\n\n"
        f"📝 {p['title']}\n"
        f"🏷️ {get_category_name(p.get('category', 'notes'))}\n"
        f"🔗 {url}\n\n"
        "২ মিনিটে live হবে।"
    )


def do_delete(slug):
    ok = True
    ok &= gh_delete_file(f'{POSTS_DIR}/{slug}.html', f'Delete post {slug}')
    gh_delete_file(f'{IMAGES_DIR}/{slug}.jpg', f'Delete image {slug}')
    sitemap_remove(slug)
    remove_from_posts_index(slug)
    if ok:
        return f"✅ <b>Deleted:</b> <code>{slug}</code>"
    return "⚠️ Partially deleted. Check GitHub."

# ============================================================
# CALLBACK HANDLER
# ============================================================
def handle_callback(cq, state):
    data = cq.get('data', '')
    cq_id = cq.get('id')
    msg = cq.get('message', {})
    msg_id = msg.get('message_id')

    if data.startswith('approve:'):
        post_id = data.split(':', 1)[1]
        tg_answer_callback(cq_id, 'Publishing...')
        result = do_publish(state, post_id)
        tg_edit_text(msg_id, result)

    elif data.startswith('cancel:'):
    post_id = data.split(':', 1)[1]
    # Answer callback first (removes loading state)
    tg_answer_callback(cq_id, 'Cancelled ✅')
    # Remove from pending if exists
    if post_id in state.get('pending', {}):
        del state['pending'][post_id]
        log(f"Cancelled pending post: {post_id}")
    else:
        log(f"Cancel clicked for {post_id} (not in pending)")
    # Update message regardless
    tg_edit_text(msg_id, "❌ <b>Post cancelled.</b>\n\n(Post removed from queue)")

    elif data.startswith('delyes:'):
        slug = data.split(':', 1)[1]
        tg_answer_callback(cq_id, 'Deleting...')
        result = do_delete(slug)
        tg_edit_text(msg_id, result)

    elif data.startswith('delno:'):
        tg_answer_callback(cq_id, 'Cancelled')
        tg_edit_text(msg_id, "✅ Delete cancelled.")

# ============================================================
# MAIN
# ============================================================
def main():
    log("=" * 50)
    log(f"Blog Bot Run — {datetime.now().isoformat()}")
    log("=" * 50)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("ERROR: Missing credentials")
        return

    state = load_state()
    last_id = state.get('last_update_id', 0)
    log(f"Last update ID: {last_id}")
    log(f"Pending posts: {len(state.get('pending', {}))}")
    log(f"Channel ID config: {TELEGRAM_CHANNEL_ID or 'NOT SET'}")

    updates = get_updates(last_id)
    log(f"Found {len(updates)} new update(s)")

    new_last = last_id
    for u in updates:
        new_last = max(new_last, u.get('update_id', 0))
        try:
            if 'message' in u:
                handle_message(u['message'], state)
            elif 'channel_post' in u:
                handle_channel_post(u['channel_post'], state)
            elif 'callback_query' in u:
                handle_callback(u['callback_query'], state)
        except Exception as e:
            log(f"Handler error: {e}")

    state['last_update_id'] = new_last
    save_state(state)
    log("Done!")


if __name__ == '__main__':
    main()
