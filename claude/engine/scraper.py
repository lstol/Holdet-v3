"""
Intel scraper — fetches stage previews from TV2, Feltet, Inner Ring using Playwright.
No web_search API calls. Playwright handles login where required.
"""

import os, re, asyncio
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

TV2_EMAIL       = os.getenv('TV2_EMAIL')
TV2_PASSWORD    = os.getenv('TV2_PASSWORD')
FELTET_EMAIL    = os.getenv('FELTET_EMAIL')
FELTET_PASSWORD = os.getenv('FELTET_PASSWORD')


async def _dismiss_cookiebot(page, timeout=3000):
    """Click CookieBot 'Acceptér alle' if present."""
    try:
        await page.click('button:has-text("Acceptér alle")', timeout=timeout)
        await page.wait_for_timeout(1000)
    except Exception:
        pass


async def _dismiss_feltet_consent(page, timeout=3000):
    """Click Feltet 'Tillad alle' consent if present."""
    try:
        await page.click('button:has-text("Tillad alle")', timeout=timeout)
        await page.wait_for_timeout(1000)
    except Exception:
        pass


async def _feltet_login(page):
    """Log in to Feltet.dk via jppol.dk Auth0 provider.
    Flow: /login (load) → dismiss consent if present → click /api/auth/login link
          → jppol.dk Auth0: email screen → password screen → redirects back to feltet.dk.
    """
    await page.goto('https://www.feltet.dk/login', wait_until='load', timeout=45000)
    await _dismiss_feltet_consent(page)
    await page.wait_for_timeout(500)
    # Click the NextAuth login link (may be on homepage after consent redirect)
    await page.click('a[href*="/api/auth/login"]', timeout=8000)
    # Wait for redirect to jppol.dk Auth0
    await page.wait_for_url('**/my.login.jppol.dk/**', timeout=15000)
    # Email screen
    await page.wait_for_selector('input[type="email"], input[name="username"], input[name="email"]', timeout=10000)
    await page.fill('input[type="email"], input[name="username"], input[name="email"]', FELTET_EMAIL)
    await page.click('button[type="submit"]')
    await page.wait_for_timeout(1500)
    # Password screen
    await page.wait_for_selector('input[type="password"]', timeout=10000)
    await page.fill('input[type="password"]', FELTET_PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_timeout(3000)


async def fetch_tv2_stage_preview(stage: int) -> str:
    """
    Log in to TV2 Sport and fetch Axelgaard's stage preview.
    Login via mit.tv2.dk (TV2 Play / TV2 Sport Plus combined auth).
    Article URL pattern: sport.tv2.dk/cykling/YYYY-MM-DD-axelgaards-optakt-til-N-etape-af-giro-ditalia
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Flow: mit.tv2.dk/?login → dismiss CookieBot → click "Log ind" → auth.tv2.dk form
        await page.goto('https://mit.tv2.dk/?login', wait_until='networkidle')
        await _dismiss_cookiebot(page)
        await page.wait_for_timeout(500)
        await page.click('a:has-text("Log ind"), button:has-text("Log ind")', timeout=8000)
        await page.wait_for_selector('input[name="email"]', timeout=10000)
        await page.fill('input[name="email"]', TV2_EMAIL)
        await page.fill('input[name="password"]', TV2_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(3000)

        pattern = re.compile(rf'axelgaards-optakt-til-{stage}[.-]etape', re.IGNORECASE)
        article_url = None

        for search_url in [
            'https://sport.tv2.dk/profil/emil-axels',
            'https://sport.tv2.dk/cykling/giro-d-italia/etaper',
        ]:
            await page.goto(search_url, wait_until='networkidle')
            links = await page.query_selector_all('a[href]')
            for link in links:
                href = await link.get_attribute('href')
                if href and pattern.search(href):
                    article_url = href if href.startswith('http') else f'https://sport.tv2.dk{href}'
                    break
            if article_url:
                break

        if not article_url:
            await browser.close()
            return f'[TV2/Axelgaard: Stage {stage} preview not found]'

        await page.goto(article_url, wait_until='networkidle')
        content = ''
        for selector in ['article', '.article-body', '.article__body', 'main']:
            el = await page.query_selector(selector)
            if el:
                content = await el.inner_text()
                break

        await browser.close()
        return content.strip() or f'[TV2/Axelgaard: Could not extract content from {article_url}]'


async def fetch_feltet_stage_analysis(stage: int) -> str:
    """
    Log in to Feltet.dk and fetch stage analysis (feltets-fiduser).
    URL pattern: feltet.dk/[landevej|plus]/feltets-fiduser-N.-etape-af-giro-ditalia/[id]
    Searches homepage (shows all recent content) and /plus/ listing.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        await _feltet_login(page)

        pattern = re.compile(rf'feltets-fiduser-{stage}[.-].*etape', re.IGNORECASE)
        article_url = None

        search_pages = [
            'https://www.feltet.dk/plus/',
            'https://www.feltet.dk/landevej/',
            'https://www.feltet.dk/',
            f'https://www.feltet.dk/?s=feltets-fiduser+{stage}.+etape',
        ]
        for search_url in search_pages:
            await page.goto(search_url, wait_until='load', timeout=30000)
            links = await page.query_selector_all('a[href]')
            for link in links:
                href = await link.get_attribute('href')
                if href and pattern.search(href):
                    article_url = href if href.startswith('http') else f'https://www.feltet.dk{href}'
                    break
            if article_url:
                break

        if not article_url:
            await browser.close()
            return f'[Feltet: Stage {stage} analysis not found]'

        await page.goto(article_url, wait_until='load', timeout=30000)
        content = ''
        for selector in ['article', '.article-body', '.content', 'main']:
            el = await page.query_selector(selector)
            if el:
                content = await el.inner_text()
                break

        await browser.close()
        return content.strip() or f'[Feltet: Could not extract content from {article_url}]'


# 2026-05-10: Ingemann scraper deprecated — Feltet stopped publishing the
# girospillet column for Giro 2026 (S16-2 diagnosis: Stage 1 article exists,
# Stages 2+ never published; not a scraper bug, an upstream content gap).
# Replaced by /paste-expert-team in server.py (source-agnostic image input).
# Keep dead code one commit cycle in case Feltet resumes; full deletion in
# S17 backlog if not.
# async def fetch_feltet_ingemann_team(stage: int) -> str:
#     """
#     Log in to Feltet.dk and fetch Ingemann's Holdet team recommendation.
#     URL pattern: feltet.dk/plus/girospillet-se-ekspertens-hold-til-N.-etape/[id]
#     """
#     async with async_playwright() as p:
#         browser = await p.chromium.launch(headless=True)
#         context = await browser.new_context()
#         page = await context.new_page()
#
#         await _feltet_login(page)
#
#         pattern = re.compile(rf'girospillet.*hold.*{stage}[.-].*etape', re.IGNORECASE)
#         article_url = None
#
#         search_pages = [
#             'https://www.feltet.dk/plus/',
#             'https://www.feltet.dk/landevej/',
#             'https://www.feltet.dk/',
#             f'https://www.feltet.dk/?s=girospillet+hold+{stage}.+etape',
#         ]
#         for search_url in search_pages:
#             await page.goto(search_url, wait_until='load', timeout=30000)
#             links = await page.query_selector_all('a[href]')
#             for link in links:
#                 href = await link.get_attribute('href')
#                 if href and pattern.search(href):
#                     article_url = href if href.startswith('http') else f'https://www.feltet.dk{href}'
#                     break
#             if article_url:
#                 break
#
#         if not article_url:
#             await browser.close()
#             return f'[Feltet Ingemann: Stage {stage} team not found]'
#
#         await page.goto(article_url, wait_until='load', timeout=30000)
#
#         # Log full body text so we can see page structure in server log
#         body_text = await page.inner_text('body')
#         print(f"[fetch_feltet_ingemann_team] article_url={article_url}")
#         print(f"[fetch_feltet_ingemann_team] BODY TEXT ({len(body_text)} chars):\n{body_text[:3000]}")
#
#         content = ''
#         for selector in ['article', '.article-body', '.entry-content', '.post-content',
#                          '.article-content', '.content-body', '.content', 'main', 'body']:
#             el = await page.query_selector(selector)
#             if el:
#                 text = await el.inner_text()
#                 if text and len(text.strip()) > 50:
#                     content = text
#                     print(f"[fetch_feltet_ingemann_team] matched selector: {selector!r} ({len(text)} chars)")
#                     break
#
#         await browser.close()
#         return content.strip() or f'[Feltet Ingemann: Could not extract content from {article_url}]'


async def fetch_inner_ring_preview(stage: int) -> str:
    """
    Fetch Inner Ring stage preview — no login required.
    URL pattern: inrng.com/YYYY/MM/giro-stage-N-preview-[finish-city]/
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto('https://inrng.com', wait_until='networkidle')

        pattern = re.compile(rf'giro.*stage.*{stage}.*preview|giro.*{stage}.*preview', re.IGNORECASE)
        links = await page.query_selector_all('a[href]')
        article_url = None
        for link in links:
            href = await link.get_attribute('href')
            if href and pattern.search(href):
                article_url = href
                break

        if not article_url:
            await page.goto(f'https://inrng.com/?s=giro+stage+{stage}+preview', wait_until='networkidle')
            links = await page.query_selector_all('a[href]')
            for link in links:
                href = await link.get_attribute('href')
                if href and pattern.search(href):
                    article_url = href
                    break

        if not article_url:
            await browser.close()
            return f'[Inner Ring: Stage {stage} preview not found]'

        await page.goto(article_url, wait_until='networkidle')
        content = ''
        for selector in ['article', '.entry-content', '.post-content', 'main']:
            el = await page.query_selector(selector)
            if el:
                content = await el.inner_text()
                break

        await browser.close()
        return content.strip() or f'[Inner Ring: Could not extract content from {article_url}]'


async def fetch_tv2_standings(stage: int) -> dict:
    """
    Log in to TV2 Sport once, then fetch all four classifications for `stage`:
    GC (samlet), Points (sprint), KOM (bjerg), Young rider (ungdom).

    Returns: {
      'gc':                    [{'rank':int, 'name_raw':str, 'team_raw':str, 'time_gap_seconds':int}, ...],
      'points_classification': [{'rank':int, 'name_raw':str, 'team_raw':str, 'points':int}, ...],
      'kom_classification':    [{'rank':int, 'name_raw':str, 'team_raw':str, 'points':int}, ...],
      'young_rider':           [{'rank':int, 'name_raw':str, 'team_raw':str, 'time_gap_seconds':int}, ...],
      'errors':                [str, ...],   # per-classification errors (empty list = clean run)
    }
    Name canonicalisation against riders.json happens upstream in the server endpoint
    so this function stays standalone-callable without server.py imports.
    """
    classifications = [
        ('gc',                    'samlet', 'time'),
        ('points_classification', 'sprint', 'points'),
        ('kom_classification',    'bjerg',  'points'),
        ('young_rider',           'ungdom', 'time'),
    ]
    out = {key: [] for key, _, _ in classifications}
    out['errors'] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Same login flow as fetch_tv2_stage_preview
        await page.goto('https://mit.tv2.dk/?login', wait_until='networkidle')
        await _dismiss_cookiebot(page)
        await page.wait_for_timeout(500)
        await page.click('a:has-text("Log ind"), button:has-text("Log ind")', timeout=8000)
        await page.wait_for_selector('input[name="email"]', timeout=10000)
        await page.fill('input[name="email"]', TV2_EMAIL)
        await page.fill('input[name="password"]', TV2_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(3000)

        for key, slug, value_kind in classifications:
            url = f'https://sport.tv2.dk/cykling/giro-d-italia/etape{stage}/klassement/{slug}'
            try:
                # 'load' is more reliable than 'networkidle' for the standings pages
                # (some have long-poll requests that never settle)
                await page.goto(url, wait_until='load', timeout=30000)
                await _dismiss_cookiebot(page)
                await page.wait_for_timeout(1500)
                # Try expanding the table — the page renders top ~12 by default
                try:
                    await page.click('button:has-text("Vis alt"), a:has-text("Vis alt")', timeout=2000)
                    await page.wait_for_timeout(800)
                except Exception:
                    pass
                rows = _parse_tv2_standings_table(await page.inner_text('body'), value_kind)
                out[key] = rows
            except Exception as e:
                out['errors'].append(f'{key}: {e}')

        await browser.close()
    return out


def _parse_tv2_standings_table(body_text: str, value_kind: str) -> list:
    """Parse TV2 klassement page body text into a list of rows.

    The page renders each ranking row as four separate lines:
      <rank>\\n<name>\\n<team>\\n<value>
    after a header line that starts with '#' and contains 'Rytter'.

    value_kind: 'time'   → emit {'time_gap_seconds': int}; rank-1's cumulative
                            time is treated as 0 gap.
                'points' → emit {'points': int}.
    """
    lines = [ln.strip() for ln in body_text.split('\n') if ln.strip()]
    rows = []
    in_table = False
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not in_table:
            if line.startswith('#') and 'Rytter' in line:
                in_table = True
            i += 1
            continue
        if not line.isdigit() or i + 3 >= n:
            break
        rank = int(line)
        name = lines[i + 1]
        team = lines[i + 2]
        val  = lines[i + 3]
        if value_kind == 'time':
            rows.append({'rank': rank, 'name_raw': name, 'team_raw': team,
                         'time_gap_seconds': _parse_tv2_time_gap(val)})
        else:
            rows.append({'rank': rank, 'name_raw': name, 'team_raw': team,
                         'points':  _parse_tv2_points(val)})
        i += 4
    return rows


def _parse_tv2_time_gap(s: str) -> int:
    """+m:ss → seconds. +h:mm:ss → seconds. Leader's cumulative time (e.g. '9:0:23')
    or anything not starting with '+' → 0 (leader has no gap)."""
    s = s.strip()
    if not s.startswith('+'):
        return 0
    parts = s[1:].split(':')
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


def _parse_tv2_points(s: str) -> int:
    s = s.strip()
    try:
        return int(s)
    except ValueError:
        return 0


def scrape_tv2_standings(stage: int) -> dict:
    """Sync wrapper for fetch_tv2_standings — mirrors scrape_all_intel pattern."""
    return asyncio.run(fetch_tv2_standings(stage))


def scrape_all_intel(stage: int, include_forward: bool = False) -> dict:
    """Scrapes all three current-stage sources concurrently. Returns raw text per source.

    Note: as of S17-β, `include_forward=True` is retained for backward compatibility
    but forward stages are no longer fetched here — `/gather-intel` now orchestrates
    forward scrapes via `fetch_tv2_generic_preview` directly (HTTP, not Playwright).
    When include_forward=True, returned dict still gains `tv2_n1` / `tv2_n2` keys for
    legacy callers, populated with the not-found sentinel so downstream consumers
    treat them as absent.
    """
    async def _run():
        tasks = [
            fetch_tv2_stage_preview(stage),
            fetch_feltet_stage_analysis(stage),
            fetch_inner_ring_preview(stage),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        tv2, feltet, inner_ring = results[0], results[1], results[2]
        out = {
            'tv2':        str(tv2)        if not isinstance(tv2, Exception)        else f'[TV2 error: {tv2}]',
            'feltet':     str(feltet)     if not isinstance(feltet, Exception)     else f'[Feltet error: {feltet}]',
            'inner_ring': str(inner_ring) if not isinstance(inner_ring, Exception) else f'[Inner Ring error: {inner_ring}]',
        }
        if include_forward:
            out['tv2_n1'] = f'[TV2/Axelgaard: Stage {stage + 1} preview not found]'
            out['tv2_n2'] = f'[TV2/Axelgaard: Stage {stage + 2} preview not found]'
        return out
    return asyncio.run(_run())


# ── S17-β: TV2 generic preview (HTTP, no Playwright) + per-stage source strategy ──

_TV2_GENERIC_URL_TEMPLATE = 'https://sport.tv2.dk/cykling/2026-04-14-{stage}-etape-eller-giro-ditalia-2026'


def fetch_tv2_generic_preview(stage: int) -> dict:
    """Fetch TV2's generic stage preview at the stable creation-date URL.

    Returns {'prose': str, 'source': str, 'url': str}.

    source ∈ {'axelgaard', 'generic_preview', 'not_found'}:
      - 'axelgaard'        — generic URL 301-redirected to Axelgaard's detailed article
                             (his column has been published; we get the richer prose
                             via the redirect for free).
      - 'generic_preview'  — landed on the lighter generic preview page (Axelgaard
                             not yet published).
      - 'not_found'        — HTTP 4xx, empty body, or stage out of range (e.g. stage 22).

    No Playwright, no login. ~1–2s per call.
    """
    url = _TV2_GENERIC_URL_TEMPLATE.format(stage=stage)
    try:
        resp = requests.get(
            url,
            timeout=10,
            allow_redirects=True,
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Holdet/1.0'},
        )
        if resp.status_code != 200:
            return {'prose': '', 'source': 'not_found', 'url': url}
        # Per CLAUDE_SESSION UTF-8 rule (S17-25): force encoding for Danish content.
        resp.encoding = 'utf-8'
        final_url = resp.url
        soup = BeautifulSoup(resp.text, 'html.parser')
        article = soup.find('article')
        if not article:
            return {'prose': '', 'source': 'not_found', 'url': final_url}
        prose = article.get_text(' ', strip=True)
        if not prose or len(prose) < 200:
            return {'prose': '', 'source': 'not_found', 'url': final_url}
        # Inspect final URL to detect whether we followed a redirect into Axelgaard's
        # detailed article path. The author slug pattern is `axelgaards-optakt-til-N-etape`.
        source = 'axelgaard' if 'axelgaards-optakt-til' in final_url else 'generic_preview'
        return {'prose': prose, 'source': source, 'url': final_url}
    except Exception as e:
        return {'prose': '', 'source': 'not_found', 'url': url, 'error': str(e)}


def fetch_stage_intel(stage: int, role: str) -> dict:
    """Role-dependent TV2 intel scraper.

    role='current':  try Axelgaard Playwright scraper first (primary); fall back to
                     the generic URL (HTTP) when the Axelgaard scraper returns the
                     not-found sentinel. Both yield the same prose shape.
    role='forward':  use the generic URL only (n+1, n+2). No Playwright cost.

    Returns {'prose': str, 'source': str}.
      source ∈ {'axelgaard', 'generic_preview', 'both_failed'}.
    """
    if role == 'current':
        prose = scrape_tv2_intel(stage)  # sync wrapper around fetch_tv2_stage_preview
        if not (prose.startswith('[TV2/Axelgaard:') or prose.startswith('[TV2 ')):
            return {'prose': prose, 'source': 'axelgaard'}
        fallback = fetch_tv2_generic_preview(stage)
        if fallback['source'] != 'not_found':
            return {'prose': fallback['prose'], 'source': fallback['source']}
        return {'prose': '', 'source': 'both_failed'}
    elif role == 'forward':
        result = fetch_tv2_generic_preview(stage)
        if result['source'] != 'not_found':
            return {'prose': result['prose'], 'source': result['source']}
        return {'prose': '', 'source': 'both_failed'}
    else:
        raise ValueError(f"Unknown role: {role!r}; expected 'current' or 'forward'")


def scrape_tv2_intel(stage: int) -> str:
    """Sync wrapper for fetch_tv2_stage_preview (Axelgaard via Playwright)."""
    return asyncio.run(fetch_tv2_stage_preview(stage))


# 2026-05-10: deprecated alongside fetch_feltet_ingemann_team above.
# def scrape_ingemann_team(stage: int) -> str:
#     """Scrapes Ingemann's Holdet team recommendation from Feltet."""
#     async def _run():
#         return await fetch_feltet_ingemann_team(stage)
#     return asyncio.run(_run())
