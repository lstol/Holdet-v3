# ChatGPT Dashboard

Static expert-audit dashboard for the ChatGPT-side Holdet v3 optimizer.

Open `chatgpt/dashboard/index.html` in a browser. It is intentionally dependency-free
for fast iteration before the project commits to a frontend stack.

The pasted React source is also preserved at:

- `chatgpt/dashboard/react/HoldetV3ExpertDashboard.jsx`

That component expects a React app with shadcn-style `@/components/ui/*`,
`lucide-react`, `recharts`, and Tailwind available. The repository does not yet
define that frontend stack, so the static HTML remains the runnable dashboard for
now.

Current status:

- Pre-snapshot scaffold using sample data.
- Mirrors the audit, riders, teams, captain, forward-pressure, and output-contract
  surface from the proposed React component.
- Keeps all dashboard work under `chatgpt/`.
