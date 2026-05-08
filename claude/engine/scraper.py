"""
Intel scraper — fetches stage previews from TV2, Feltet, Inner Ring using Playwright.
No web_search API calls. Playwright handles login where required.
"""

import os, re, asyncio
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


async def fetch_feltet_ingemann_team(stage: int) -> str:
    """
    Log in to Feltet.dk and fetch Ingemann's Holdet team recommendation.
    URL pattern: feltet.dk/plus/girospillet-se-ekspertens-hold-til-N.-etape/[id]
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        await _feltet_login(page)

        pattern = re.compile(rf'girospillet.*hold.*{stage}[.-].*etape', re.IGNORECASE)
        article_url = None

        search_pages = [
            'https://www.feltet.dk/plus/',
            'https://www.feltet.dk/landevej/',
            'https://www.feltet.dk/',
            f'https://www.feltet.dk/?s=girospillet+hold+{stage}.+etape',
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
            return f'[Feltet Ingemann: Stage {stage} team not found]'

        await page.goto(article_url, wait_until='load', timeout=30000)
        content = ''
        for selector in ['article', '.article-body', '.content', 'main']:
            el = await page.query_selector(selector)
            if el:
                content = await el.inner_text()
                break

        await browser.close()
        return content.strip() or f'[Feltet Ingemann: Could not extract content from {article_url}]'


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


def scrape_all_intel(stage: int) -> dict:
    """Scrapes all three sources concurrently. Returns raw text per source."""
    async def _run():
        tv2, feltet, inner_ring = await asyncio.gather(
            fetch_tv2_stage_preview(stage),
            fetch_feltet_stage_analysis(stage),
            fetch_inner_ring_preview(stage),
            return_exceptions=True
        )
        return {
            'tv2':        str(tv2)        if not isinstance(tv2, Exception)        else f'[TV2 error: {tv2}]',
            'feltet':     str(feltet)     if not isinstance(feltet, Exception)     else f'[Feltet error: {feltet}]',
            'inner_ring': str(inner_ring) if not isinstance(inner_ring, Exception) else f'[Inner Ring error: {inner_ring}]',
        }
    return asyncio.run(_run())


def scrape_ingemann_team(stage: int) -> str:
    """Scrapes Ingemann's Holdet team recommendation from Feltet."""
    async def _run():
        return await fetch_feltet_ingemann_team(stage)
    return asyncio.run(_run())
