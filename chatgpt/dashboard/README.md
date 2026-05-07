# ChatGPT Dashboard

Static expert cockpit dashboard for the ChatGPT-side Holdet v3 optimizer.

Open `chatgpt/dashboard/index.html` in Safari from a local server. It is
intentionally dependency-free: single HTML file, no React, no build step, no npm
dependencies, no backend.

Current runnable dashboard:

- Dark Bloomberg/terminal-style one-screen cockpit.
- Laptop/desktop-first layout optimized for 1440p+.
- Stage image carousel for stages 1-21.
- Audit/rules validation, candidate teams, payoff distribution, captain EV,
  selected-team table, forward pressure, decision notes, and lock readiness all
  visible at once.
- Stage image loading tries multiple local paths in order and shows the resolved
  path under the carousel. If every path fails, the dashboard shows a visible
  stage-specific error with all attempted paths.

Image path order:

1. `../../shared/stage_images/giro_2026/stage-N.jpg`
2. `../../shared/data/stage_images/giro_2026/stage-N.jpg`
3. `/shared/stage_images/giro_2026/stage-N.jpg`
4. `/shared/data/stage_images/giro_2026/stage-N.jpg`

## Verification

Use Safari only. Do not use Chrome, Playwright, Puppeteer, Selenium, or browser
automation for this dashboard.

Recommended from repo root:

```bash
python3 -m http.server 8765
open -a Safari http://localhost:8765/chatgpt/dashboard/index.html
```

Direct file mode can be tried, but local server mode is the supported path:

```bash
open -a Safari chatgpt/dashboard/index.html
```

Direct image checks:

```text
http://localhost:8765/shared/data/stage_images/giro_2026/stage-1.jpg
http://localhost:8765/shared/stage_images/giro_2026/stage-1.jpg
```

The pasted React source is also preserved at:

- `chatgpt/dashboard/react/HoldetV3ExpertDashboard.jsx`

That component expects a React app with shadcn-style `@/components/ui/*`,
`lucide-react`, `recharts`, and Tailwind available. The repository does not yet
define that frontend stack, so the static HTML remains the runnable dashboard for
now.

Current status:

- Pre-snapshot scaffold using sample data.
- Mirrors the approved expert cockpit design without requiring a frontend stack.
- Keeps all dashboard work under `chatgpt/`.
