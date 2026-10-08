#!/usr/bin/env python3
"""
Blog Bot — Reads Telegram messages and creates HTML blog posts
Runs on GitHub Actions every 10 minutes
"""

import os
import json
import re
import requests
import base64
from datetime import datetime
from pathlib import Path

# ========================================
# CONFIGURATION
# ========================================
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
GITHUB_REPO = 'arif0850/ai'
GITHUB_API = 'https://api.github.com'
TELEGRAM_API = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'

STATE_FILE = 'scripts/blog-state.json'
POSTS_DIR = 'posts'
IMAGES_DIR = 'posts/images'
SITEMAP_FILE = 'sitemap.xml'

# ========================================
# LOGGER
# ========================================
def log(msg):
    print(f"[BLOG-BOT] {msg}")

# ========================================
# STATE MANAGEMENT
# ========================================
def load_state():
    """Load last processed update_id"""
    if Path(STATE_FILE).exists():
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            log(f"State load error: {e}")
    return {'last_update_id': 0}

def save_state(state):
    """Save last processed update_id"""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# ========================================
# TELEGRAM
# ========================================
def get_updates(last_update_id):
    """Fetch new Telegram updates"""
    try:
        url = f'{TELEGRAM_API}/getUpdates'
        params = {
            'offset': last_update_id + 1,
            'timeout': 5,
            'allowed_updates': ['message']
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get('result', [])
    except Exception as e:
        log(f"getUpdates error: {e}")
        return []

def send_message(text):
    """Send confirmation message to Telegram"""
    try:
        url = f'{TELEGRAM_API}/sendMessage'
        data = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': text,
            'parse_mode': 'HTML'
        }
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        log(f"sendMessage error: {e}")

def download_photo(file_id):
    """Download photo from Telegram and return bytes"""
    try:
        # Get file path
        r = requests.get(f'{TELEGRAM_API}/getFile', params={'file_id': file_id}, timeout=10)
        r.raise_for_status()
        file_path = r.json()['result']['file_path']
        
        # Download
        dl_url = f'https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}'
        r = requests.get(dl_url, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception as e:
        log(f"Photo download error: {e}")
        return None

# ========================================
# PARSER
# ========================================
def parse_post(text):
    """
    Parse Telegram message:
    
    /newpost
    Title: My Blog Title
    
    Content here...
    
    ---END---
    """
    if not text:
        return None
    
    # Must start with /newpost
    if not text.strip().lower().startswith('/newpost'):
        return None
    
    # Remove /newpost
    text = text.strip()[8:].strip()
    
    # Try to find Title: line
    title = None
    lines = text.split('\n')
    content_lines = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower().startswith('title:'):
            title = stripped[6:].strip()
        else:
            content_lines.append(line)
    
    content = '\n'.join(content_lines).strip()
    
    # Remove ---END--- if present
    content = re.sub(r'-{3,}\s*END\s*-{3,}', '', content, flags=re.IGNORECASE).strip()
    
    if not title:
        # Use first line as title
        if content:
            title = content.split('\n')[0][:80]
            content = '\n'.join(content.split('\n')[1:]).strip()
        else:
            return None
    
    if not content:
        return None
    
    return {'title': title, 'content': content}

def slugify(text):
    """Convert title to URL-friendly slug"""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return text[:60]

def markdown_to_html(text):
    """Simple markdown to HTML"""
    # Escape
    html = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    # Bold: **text**
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    
    # Italic: *text*
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    
    # Links: [text](url)
    html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" target="_blank">\1</a>', html)
    
    # Paragraphs
    paragraphs = html.split('\n\n')
    result = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if p.startswith('- '):
            items = [f'<li>{line[2:]}</li>' for line in p.split('\n') if line.strip().startswith('- ')]
            result.append(f'<ul>{"".join(items)}</ul>')
        else:
            result.append(f'<p>{p.replace(chr(10), "<br>")}</p>')
    
    return '\n'.join(result)

# ========================================
# HTML GENERATOR
# ========================================
def generate_html(post, image_path=None):
    """Generate complete blog post HTML"""
    date_obj = datetime.now()
    date_str = date_obj.strftime('%B %d, %Y')
    date_iso = date_obj.strftime('%Y-%m-%d')
    
    content_html = markdown_to_html(post['content'])
    
    image_html = ''
    if image_path:
        image_html = f'''
        <div class="post-image">
          <img src="{image_path}" alt="{post['title']}" loading="lazy">
        </div>'''
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{post['title']} | Md. Ariful Islam</title>
  <meta name="description" content="{post['content'][:150].replace(chr(10), ' ')}...">
  <meta name="author" content="Md. Ariful Islam">
  
  <meta property="og:type" content="article">
  <meta property="og:title" content="{post['title']}">
  <meta property="og:description" content="{post['content'][:150].replace(chr(10), ' ')}...">
  <meta property="og:url" content="https://www.hiarif.com/posts/{slugify(post['title'])}.html">
  <meta property="og:image" content="https://www.hiarif.com/assets/images/og-image.png">
  
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{post['title']}">
  
  <meta name="theme-color" content="#121212">
  
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
  
  <style>
    :root {{
      --bg-main: #121212;
      --bg-card: #1e1e1e;
      --bg-inner: #232323;
      --accent: #ffdb6e;
      --text-main: #ffffff;
      --text-soft: #e5e5e5;
      --text-muted: #a3a3a3;
      --border: #2f2f2f;
      --radius-md: 14px;
      --radius-lg: 20px;
    }}
    
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg-main);
      color: var(--text-main);
      line-height: 1.7;
      padding: 40px 20px 100px;
      min-height: 100vh;
      letter-spacing: -0.01em;
    }}
    
    .container {{
      max-width: 800px;
      margin: 0 auto;
    }}
    
    .back-link {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--accent);
      text-decoration: none;
      font-size: 0.9rem;
      font-weight: 600;
      margin-bottom: 30px;
      transition: all 0.3s ease;
    }}
    
    .back-link:hover {{
      transform: translateX(-4px);
    }}
    
    .post-header {{
      margin-bottom: 40px;
      padding-bottom: 30px;
      border-bottom: 1px solid var(--border);
    }}
    
    .post-date {{
      font-size: 0.75rem;
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-weight: 700;
      margin-bottom: 12px;
    }}
    
    .post-title {{
      font-size: 2.2rem;
      font-weight: 800;
      line-height: 1.2;
      letter-spacing: -0.03em;
      color: var(--text-main);
    }}
    
    .post-content {{
      font-size: 1.05rem;
      color: var(--text-soft);
    }}
    
    .post-content p {{
      margin-bottom: 20px;
      line-height: 1.8;
    }}
    
    .post-content h2 {{
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--text-main);
      margin: 32px 0 16px;
      letter-spacing: -0.02em;
    }}
    
    .post-content h3 {{
      font-size: 1.2rem;
      font-weight: 700;
      color: var(--text-main);
      margin: 24px 0 12px;
    }}
    
    .post-content ul {{
      margin: 16px 0 20px 24px;
    }}
    
    .post-content li {{
      margin-bottom: 8px;
      color: var(--text-soft);
    }}
    
    .post-content strong {{
      color: var(--text-main);
      font-weight: 700;
    }}
    
    .post-content a {{
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px solid transparent;
      transition: border-color 0.3s ease;
    }}
    
    .post-content a:hover {{
      border-bottom-color: var(--accent);
    }}
    
    .post-image {{
      margin: 24px 0;
      border-radius: var(--radius-md);
      overflow: hidden;
      border: 1px solid var(--border);
    }}
    
    .post-image img {{
      width: 100%;
      height: auto;
      display: block;
    }}
    
    .post-footer {{
      margin-top: 50px;
      padding-top: 30px;
      border-top: 1px solid var(--border);
      text-align: center;
    }}
    
    .post-footer a {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: var(--accent);
      color: #121212;
      padding: 12px 24px;
      border-radius: 999px;
      text-decoration: none;
      font-weight: 700;
      font-size: 0.9rem;
      transition: all 0.3s ease;
    }}
    
    .post-footer a:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(255, 219, 110, 0.3);
    }}
    
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
      </header>
      
      {image_html}
      
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
    
    return html

# ========================================
# GITHUB API
# ========================================
def github_headers():
    return {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }

def get_github_file(path):
    """Get file content from GitHub"""
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    r = requests.get(url, headers=github_headers(), timeout=15)
    if r.status_code == 200:
        data = r.json()
        return {
            'sha': data['sha'],
            'content': base64.b64decode(data['content']).decode('utf-8')
        }
    return None

def commit_file(path, content, message):
    """Commit a file to GitHub"""
    # Try to get existing file (for update)
    existing = get_github_file(path)
    
    payload = {
        'message': message,
        'content': base64.b64encode(content.encode('utf-8')).decode('ascii')
    }
    
    if existing:
        payload['sha'] = existing['sha']
    
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    r = requests.put(url, headers=github_headers(), json=payload, timeout=20)
    
    if r.status_code in [200, 201]:
        return True
    else:
        log(f"Commit error {path}: {r.status_code} — {r.text[:200]}")
        return False

def commit_image(path, image_bytes, message):
    """Commit an image to GitHub"""
    payload = {
        'message': message,
        'content': base64.b64encode(image_bytes).decode('ascii')
    }
    
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    r = requests.put(url, headers=github_headers(), json=payload, timeout=30)
    
    if r.status_code in [200, 201]:
        return True
    return False

def update_sitemap(new_url, lastmod):
    """Add new post URL to sitemap"""
    sitemap = get_github_file(SITEMAP_FILE)
    if not sitemap:
        log("Sitemap not found")
        return False
    
    content = sitemap['content']
    
    if new_url in content:
        log("URL already in sitemap")
        return True
    
    new_entry = f'''  <!-- Blog Post -->
  <url>
    <loc>{new_url}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>
  
</urlset>'''
    
    content = content.replace('</urlset>', new_entry)
    
    return commit_file(SITEMAP_FILE, content, f'Add {new_url} to sitemap')

def update_blog_listing(post_title, post_url, date_str, excerpt):
    """Add new post to blog.html"""
    blog = get_github_file('blog.html')
    if not blog:
        log("blog.html not found")
        return False
    
    content = blog['content']
    
    # Check if already added
    if post_url in content:
        log("URL already in blog.html")
        return True
    
    log("blog.html found but auto-update needs manual template")
    # We'll skip auto-update for blog.html to avoid breaking
    # User can manually add to blog.html or we can add later
    return True

# ========================================
# MAIN
# ========================================
def main():
    log("=" * 50)
    log(f"Blog Bot Run — {datetime.now().isoformat()}")
    log("=" * 50)
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("ERROR: Missing Telegram credentials")
        return
    
    state = load_state()
    last_id = state.get('last_update_id', 0)
    log(f"Last update ID: {last_id}")
    
    updates = get_updates(last_id)
    log(f"Found {len(updates)} new update(s)")
    
    if not updates:
        log("No new messages")
        return
    
    processed_count = 0
    new_last_id = last_id
    
    for update in updates:
        update_id = update.get('update_id', 0)
        new_last_id = max(new_last_id, update_id)
        
        message = update.get('message', {})
        chat_id = str(message.get('chat', {}).get('id', ''))
        
        # Only accept from our own chat
        if chat_id != str(TELEGRAM_CHAT_ID):
            log(f"Ignoring message from chat {chat_id}")
            continue
        
        # Get text (either direct text or caption for photos)
        text = message.get('text') or message.get('caption', '')
        
        if not text or not text.strip().lower().startswith('/newpost'):
            continue
        
        log(f"Processing /newpost...")
        
        parsed = parse_post(text)
        if not parsed:
            send_message("❌ <b>Error:</b> Could not parse post. Format:\n\n<code>/newpost\nTitle: My Title\n\nContent...</code>")
            continue
        
        slug = slugify(parsed['title'])
        post_url = f'https://www.hiarif.com/posts/{slug}.html'
        post_path = f'posts/{slug}.html'
        
        # Handle photo
        image_path = None
        if 'photo' in message:
            log("Downloading photo...")
            # Get largest photo
            photo = message['photo'][-1]
            img_bytes = download_photo(photo['file_id'])
            
            if img_bytes:
                # Determine extension (default jpg)
                ext = 'jpg'
                img_filename = f'{slug}.{ext}'
                img_path = f'{IMAGES_DIR}/{img_filename}'
                
                if commit_image(img_path, img_bytes, f'Add image for {slug}'):
                    image_path = f'../{img_path}'
                    log(f"Image saved: {img_path}")
        
        # Generate HTML
        html = generate_html(parsed, image_path)
        
        # Commit post
        if commit_file(post_path, html, f'Add blog post: {parsed["title"]}'):
            log(f"Post created: {post_path}")
            
            # Update sitemap
            date_iso = datetime.now().strftime('%Y-%m-%d')
            update_sitemap(post_url, date_iso)
            
            processed_count += 1
            
            send_message(f'''✅ <b>Post Published!</b>
            
📝 {parsed['title']}
🔗 {post_url}

সাইটে ২ মিনিটে live হবে।
<i>(GitHub Pages auto-deploy)</i>''')
        else:
            send_message(f"❌ <b>Failed:</b> Could not commit post.")
    
    # Save state
    state['last_update_id'] = new_last_id
    save_state(state)
    
    log(f"Processed {processed_count} new post(s)")
    log("Done!")

if __name__ == '__main__':
    main()
