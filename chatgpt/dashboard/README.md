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
- Uses local image assets from `../../shared/data/stage_images/giro_2026/stage-N.jpg`.

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
