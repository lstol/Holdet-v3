"""S17-ε-redo: Playwright runtime verification of the dashboard's force-in
click → JS state → /run-optimizer payload chain.

Originated 2026-05-13 to verify (and falsify) S17-ε's classification (f)
"wiring fully intact end-to-end." S17-ε's empirical evidence was a direct
`curl /run-optimizer` test which verified engine acceptance only; the
dashboard click path was not exercised.

Findings produced by this script (recorded in ROADMAP S17-ε-redo close):
  - State mutation works; payload assembly works; engine respects constraint.
  - Rider-table visual feedback for force-in fails due to type mismatch:
    toggleForce stores string '47397' (from onclick attribute), renderTable
    looks up via S.forceIn.has(rid) where rid is the number 47397 (from
    r.holdet_id). Set.has uses SameValueZero — string != number.
  - User clicks IN → no visual feedback → may click again → second click
    deletes the entry → run-optimizer fires with force_in: [].
  - Fix scope (S17-ε-fix): coerce String(rid) at both toggleForce and
    renderTable comparison sites; add localStorage persistence.

Re-run pattern: works against any localhost:5050 dashboard. Reads holdet_id
from S.riders; target rider can be changed by editing TARGET_RIDER.
"""
import asyncio, json, time
from playwright.async_api import async_playwright

DASHBOARD_URL = 'http://localhost:5050/'
TARGET_RIDER  = 'Paul Magnier'
TARGET_STAGE  = 5


async def main():
    captured = {'request': None, 'response': None, 'console': []}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await (await browser.new_context()).new_page()

        page.on('console', lambda msg: captured['console'].append(f'[{msg.type}] {msg.text}'))

        async def on_request(request):
            if '/run-optimizer' in request.url and request.method == 'POST':
                captured['request'] = json.loads(request.post_data) if request.post_data else None
        async def on_response(response):
            if '/run-optimizer' in response.url and response.request.method == 'POST':
                try: captured['response'] = await response.json()
                except Exception as e: captured['response'] = {'parse_error': str(e)}
        page.on('request', on_request)
        page.on('response', on_response)

        await page.goto(DASHBOARD_URL, wait_until='networkidle', timeout=30000)
        await page.evaluate(f"localStorage.setItem('holdet_target_stage', '{TARGET_STAGE}')")
        await page.reload(wait_until='networkidle', timeout=30000)

        magnier_row = page.locator(f'#rider-tbody tr:has-text("{TARGET_RIDER}")').first
        await magnier_row.wait_for(timeout=15000)

        # Probe what's actually accessible from page-eval scope
        accessibility = await page.evaluate("""
            (() => {
                const r = {};
                r.toggleForce_typeof = typeof toggleForce;
                r.renderTable_typeof = typeof renderTable;
                r.S_typeof_local = (typeof S);
                r.windowS = typeof window.S;
                r.S_via_globalThis = (typeof globalThis.S);
                return r;
            })()
        """)
        print(f'[scope probe] {accessibility}')

        # Try invoking toggleForce directly
        invoke = await page.evaluate("""
            (() => {
                if (typeof toggleForce !== 'function') return 'toggleForce not in scope';
                try {
                    toggleForce('47397', 'in');
                    return 'toggleForce returned without error';
                } catch (e) {
                    return 'toggleForce threw: ' + e.message;
                }
            })()
        """)
        print(f'[direct invoke] {invoke}')

        # Inspect Magnier row after direct invoke
        await page.wait_for_timeout(500)
        row_cls = await magnier_row.get_attribute('class')
        in_btn = magnier_row.locator('button.force-btn').first
        btn_cls = await in_btn.get_attribute('class')
        print(f'[after direct invoke] row.class={row_cls!r}  btn.class={btn_cls!r}')

        # Try to introspect S from inside the IIFE's scope.
        # Trick: evaluate an expression that uses S directly (not window.S)
        # If S is in the lexical scope of the dashboard script, page.evaluate
        # cannot reach it (separate function scope). But onclick="toggleForce(...)"
        # works because attributes are evaluated in the function-context of the
        # element, which has access to globals declared by inline scripts.
        s_probe = await page.evaluate("""
            (() => {
                // Try to read S directly. Should fail if S is module-scoped via const.
                try { return { ok: true, len: S.riders.length, forceIn: [...S.forceIn] }; }
                catch (e) { return { ok: false, err: e.message }; }
            })()
        """)
        print(f'[S probe via evaluate] {s_probe}')

        # Probe via the onclick attribute path — does the button's inline handler
        # reach the same S? Try to trigger handler programmatically and observe DOM.
        # If the handler runs but uses a DIFFERENT S than what the optimizer-fire
        # path reads, that'd be the bug.

        # Check whether the .click() actually fires onclick handler
        click_probe = await page.evaluate("""
            (() => {
                const tbody = document.getElementById('rider-tbody');
                let magnierRow = null;
                for (const tr of tbody.querySelectorAll('tr')) {
                    if (tr.textContent.includes('Paul Magnier')) { magnierRow = tr; break; }
                }
                if (!magnierRow) return 'no row';
                const btn = magnierRow.querySelector('button.force-btn');
                if (!btn) return 'no btn';
                // Install a click listener to detect if click events propagate
                let clickFired = false;
                btn.addEventListener('click', () => { clickFired = true; }, {once: true});
                btn.click();
                return {
                    clickFired,
                    onclickAttr: btn.getAttribute('onclick'),
                    btnClassAfter: btn.className,
                    rowClassAfter: magnierRow.className,
                };
            })()
        """)
        print(f'[click probe] {click_probe}')

        # Now click via Playwright to compare
        await in_btn.click()
        await page.wait_for_timeout(500)
        row_cls = await magnier_row.get_attribute('class')
        btn_cls = await in_btn.get_attribute('class')
        print(f'[playwright click +500ms] row.class={row_cls!r}  btn.class={btn_cls!r}')

        # Now click Run optimizer and see what payload gets sent
        await page.locator('#run-optimizer-btn').click()
        t0 = time.time()
        while captured['request'] is None and time.time() - t0 < 30:
            await page.wait_for_timeout(200)
        if captured['request']:
            print(f'\n[REQUEST payload]')
            print(f'  force_in = {captured["request"].get("force_in")!r}')

        # Console log dump
        print(f'\n[console lines: {len(captured["console"])}]')
        for line in captured['console'][:30]:
            print(f'  {line}')

        await browser.close()

asyncio.run(main())
