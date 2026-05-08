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


async def fetch_tv2_stage_preview(stage: int) -> str:
    """
    Log in to TV2 Sport and fetch Axelgaard's stage preview.
    URL pattern: sport.tv2.dk/cykling/YYYY-MM-DD-axelgaards-optakt-til-N-etape-af-giro-ditalia
    Date unknown — discover from the etaper listing page.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto('https://profil.tv2.dk/login', wait_until='networkidle')
        await page.fill('input[name="email"], input[type="email"]', TV2_EMAIL)
        await page.fill('input[name="password"], input[type="password"]', TV2_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(2000)

        await page.goto('https://sport.tv2.dk/cykling/giro-d-italia/etaper', wait_until='networkidle')

        pattern = re.compile(rf'axelgaards-optakt-til-{stage}[.-]etape', re.IGNORECASE)
        links = await page.query_selector_all('a[href]')
        article_url = None
        for link in links:
            href = await link.get_attribute('href')
            if href and pattern.search(href):
                article_url = href if href.startswith('http') else f'https://sport.tv2.dk{href}'
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
    URL pattern: feltet.dk/plus/feltets-fiduser-N.-etape-af-giro-ditalia-2026/[id]
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto('https://www.feltet.dk/login', wait_until='networkidle')
        await page.fill('input[name="email"], input[type="email"]', FELTET_EMAIL)
        await page.fill('input[name="password"], input[type="password"]', FELTET_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(2000)

        await page.goto('https://www.feltet.dk/plus/', wait_until='networkidle')

        pattern = re.compile(rf'feltets-fiduser-{stage}[.-].*etape.*giro', re.IGNORECASE)
        links = await page.query_selector_all('a[href]')
        article_url = None
        for link in links:
            href = await link.get_attribute('href')
            if href and pattern.search(href):
                article_url = href if href.startswith('http') else f'https://www.feltet.dk{href}'
                break

        if not article_url:
            await browser.close()
            return f'[Feltet: Stage {stage} analysis not found]'

        await page.goto(article_url, wait_until='networkidle')
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

        await page.goto('https://www.feltet.dk/login', wait_until='networkidle')
        await page.fill('input[name="email"], input[type="email"]', FELTET_EMAIL)
        await page.fill('input[name="password"], input[type="password"]', FELTET_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(2000)

        await page.goto('https://www.feltet.dk/plus/', wait_until='networkidle')

        pattern = re.compile(rf'girospillet.*hold.*{stage}[.-].*etape', re.IGNORECASE)
        links = await page.query_selector_all('a[href]')
        article_url = None
        for link in links:
            href = await link.get_attribute('href')
            if href and pattern.search(href):
                article_url = href if href.startswith('http') else f'https://www.feltet.dk{href}'
                break

        if not article_url:
            await browser.close()
            return f'[Feltet Ingemann: Stage {stage} team not found]'

        await page.goto(article_url, wait_until='networkidle')
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
