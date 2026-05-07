# ChatGPT Dashboard

Static expert cockpit dashboard for the ChatGPT-side Holdet v3 optimizer.

Open `chatgpt/dashboard/index.html` in a browser. It is intentionally dependency-free:
single HTML file, no React, no build step, no npm dependencies, no backend.

Current runnable dashboard:

- Dark Bloomberg/terminal-style one-screen cockpit.
- Laptop/desktop-first layout optimized for 1440p+.
- Stage image carousel for stages 1-21.
- Audit/rules validation, candidate teams, payoff distribution, captain EV,
  selected-team table, forward pressure, decision notes, and lock readiness all
  visible at once.
- Loads local image assets from `../../shared/stage_images/giro_2026/stage-N.jpg`.
  `shared/stage_images/` is a compatibility symlink to the current repository
  image directory.

## Verification

Use Safari only. Do not use Chrome, Playwright, Puppeteer, Selenium, or browser
automation for this dashboard.

From repo root:

```bash
open -a Safari chatgpt/dashboard/index.html
```

If local relative paths fail, serve from repo root:

```bash
python3 -m http.server 8765
open -a Safari http://localhost:8765/chatgpt/dashboard/index.html
```

Direct image checks:

```text
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
