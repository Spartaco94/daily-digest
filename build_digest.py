import json, os, re, datetime, time, pathlib
from urllib.request import urlopen
from xml.etree import ElementTree as ET
from html import unescape

# ---- CONFIG ----
MAX_ITEMS_PER_FEED = 1           # 1 post per feed (cambia a 999 per “tutti i post del giorno”)
WINDOW_HOURS = 36                # quanto indietro pescare (Substack daily: 24–36h è ok)
TZ_OFFSET_MIN = 60               # Europe/Rome (CET/CEST) ~ +60 min da UTC in inverno

CTA_BLOCK_MD = """
---

**Enjoy my work?**  
🎧 Audiobooks (YouTube): https://www.youtube.com/channel/UC6wt-XQUkZcXM92ii8g7ggw  
🐦 X (Twitter): https://x.com/0_Simone_0  
📸 Instagram: https://www.instagram.com/spartaco_94_/

*Each blog publishes 1 new story per day. This digest packs the 7 best picks in ~7 minutes.*
"""

CTA_BLOCK_HTML = """
<hr/>
<p><strong>Enjoy my work?</strong><br/>
🎧 Audiobooks (YouTube): <a href="https://www.youtube.com/channel/UC6wt-XQUkZcXM92ii8g7ggw" target="_blank">link</a><br/>
🐦 X (Twitter): <a href="https://x.com/0_Simone_0" target="_blank">@0_Simone_0</a><br/>
📸 Instagram: <a href="https://www.instagram.com/spartaco_94_/" target="_blank">@spartaco_94_</a></p>
<p><em>Each blog publishes 1 new story per day. This digest packs the 7 best picks in ~7 minutes.</em></p>
"""

TITLE_PREFIX = "7-in-7 Daily Digest"
# ----------------

def now_utc():
    return datetime.datetime.utcnow()

def cutoff_time():
    return now_utc() - datetime.timedelta(hours=WINDOW_HOURS)

def strip_html(html):
    txt = re.sub(r'<[^>]+>', ' ', html or '')
    txt = unescape(txt)
    txt = re.sub(r'\s+', ' ', txt).strip()
    return txt

def fetch_rss(url):
    with urlopen(url, timeout=20) as resp:
        data = resp.read()
    return data

def parse_entries(data):
    # Handles Atom and RSS 2.0
    root = ET.fromstring(data)
    ns = {'atom': 'http://www.w3.org/2005/Atom', 'dc': 'http://purl.org/dc/elements/1.1/'}
    entries = []
    # Atom
    for e in root.findall('.//{http://www.w3.org/2005/Atom}entry'):
        title = (e.findtext('atom:title', default='', namespaces=ns) or '').strip()
        link = ''
        for l in e.findall('atom:link', ns):
            if l.get('rel') in (None, 'alternate'):
                link = l.get('href') or ''
                if link: break
        summary = e.findtext('atom:summary', default='', namespaces=ns) or e.findtext('atom:content', default='', namespaces=ns) or ''
        pub = e.findtext('atom:updated', default='', namespaces=ns) or e.findtext('atom:published', default='', namespaces=ns) or ''
        entries.append({'title': title, 'link': link, 'summary': summary, 'pub': pub})
    # RSS 2.0
    for i in root.findall('.//item'):
        title = (i.findtext('title') or '').strip()
        link = (i.findtext('link') or '').strip()
        desc = i.findtext('description') or i.findtext('content:encoded') or ''
        pub = i.findtext('pubDate') or ''
        entries.append({'title': title, 'link': link, 'summary': desc, 'pub': pub})
    return entries

def parse_time_guess(s):
    if not s: return None
    # try several formats
    fmts = [
        '%a, %d %b %Y %H:%M:%S %z',      # RSS pubDate
        '%Y-%m-%dT%H:%M:%S%z',           # Atom with offset
        '%Y-%m-%dT%H:%M:%SZ',            # Atom Z
    ]
    for f in fmts:
        try:
            return datetime.datetime.strptime(s, f)
        except Exception:
            continue
    # fallback
    try:
        return datetime.datetime.strptime(s[:19], '%Y-%m-%dT%H:%M:%S')
    except Exception:
        return None

def within_window(pub_dt):
    if not pub_dt: return True  # in dubbio: includi
    # normalizza a UTC naive
    if pub_dt.tzinfo:
        pub_dt = pub_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return pub_dt >= cutoff_time()

def load_feeds():
    with open('feeds.json', 'r') as f:
        return json.load(f)['feeds']

def build_section_md(item, source_name=None):
    title = item['title'] or '(untitled)'
    link = item['link']
    summary = strip_html(item.get('summary', ''))
    if len(summary) > 300:
        summary = summary[:297] + '…'
    src = f" — _{source_name}_" if source_name else ""
    return f"### [{title}]({link}){src}\n{summary}\n"

def build_section_html(item, source_name=None):
    title = item['title'] or '(untitled)'
    link = item['link']
    summary = strip_html(item.get('summary', ''))
    if len(summary) > 300:
        summary = summary[:297] + '…'
    src = f" — <em>{source_name}</em>" if source_name else ""
    return f"<h3><a href=\"{link}\" target=\"_blank\">{title}</a>{src}</h3><p>{summary}</p>"

def source_name_from_url(url):
    # simple label from hostname path
    try:
        host = re.sub(r'^https?://', '', url).split('/')[0]
        return host.split('.')[0].capitalize()
    except Exception:
        return "Source"

def main():
    feeds = load_feeds()
    items = []
    for feed in feeds:
        try:
            data = fetch_rss(feed)
            entries = parse_entries(data)
            # order by published (best effort): newest first
            for e in entries:
                e['_dt'] = parse_time_guess(e.get('pub','')) or now_utc()
            entries.sort(key=lambda x: x['_dt'], reverse=True)
            picked = []
            for e in entries:
                if within_window(e['_dt']):
                    picked.append(e)
                if len(picked) >= MAX_ITEMS_PER_FEED:
                    break
            for e in picked:
                items.append( (source_name_from_url(feed), e) )
        except Exception as ex:
            print("ERR feed", feed, ex)

    # sort global newest first
    items.sort(key=lambda pair: pair[1].get('_dt', now_utc()), reverse=True)

    if not items:
        print("No items found within window; creating empty digest with CTA only.")

    today = (now_utc() + datetime.timedelta(minutes=TZ_OFFSET_MIN)).date().isoformat()
    out_dir = pathlib.Path('digest')/today
    out_dir.mkdir(parents=True, exist_ok=True)

    title = f"{TITLE_PREFIX} — {today}"
    intro = "A curated selection of today’s 7 posts across my blogs. Skim the summaries, click to read in full."

    # Markdown
    md_lines = [f"# {title}\n", intro, ""]
    for src, it in items:
        md_lines.append(build_section_md(it, src))
        md_lines.append("")
    md_lines.append(CTA_BLOCK_MD)
    (out_dir/'daily-digest.md').write_text("\n".join(md_lines), encoding='utf-8')

    # HTML
    html_parts = [f"<h1>{title}</h1>", f"<p>{intro}</p>"]
    for src, it in items:
        html_parts.append(build_section_html(it, src))
    html_parts.append(CTA_BLOCK_HTML)
    (out_dir/'daily-digest.html').write_text("\n".join(html_parts), encoding='utf-8')

    # summary file with quick links
    index_md = [
        f"# {title}",
        "",
        f"- Markdown: `digest/{today}/daily-digest.md`",
        f"- HTML: `digest/{today}/daily-digest.html`",
        "",
        "_Open the file → Copy → Paste into Substack → Publish_"
    ]
    (out_dir/'README.md').write_text("\n".join(index_md), encoding='utf-8')

if __name__ == "__main__":
    main()
