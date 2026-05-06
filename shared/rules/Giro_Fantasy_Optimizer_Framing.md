# Giro Fantasy Optimizer – Project Framing & Roadmap

**Status:** Living document – actively updated during the design session.

---

## 1. Purpose and Problem Definition

This project builds a **decision engine** for a Giro d'Italia fantasy game with strongly **convex scoring**, where:

- Stage winners and podiums dominate total points
- Captaincy amplifies right‑tail outcomes
- Transfers are costly when buying riders (1% of rider value)
- Historical priors are explicitly excluded
- Expert intelligence and market odds are core inputs for probability shaping

The system is **not** a cycling performance predictor. It is a **fantasy optimization and decision‑support engine** for elite‑level play.

---

## 2. Economic Reality (Non‑Negotiable)

Fantasy scoring is highly non‑linear:

- A single stage win can outweigh multiple top‑15 results
- GC time losses are catastrophic for non‑GC riders
- Captain choices concentrate payoff further

Therefore:
- High variance is often rational
- "Keep rather than churn" is not a global rule
- Strategy must account for **future exposure**, not only immediate points

---

## 3. Canonical Risk Framing

> **Risk is not an optimizer input.**  
> **Risk is an output, observed through outcome distributions.**

Implications:
- No mechanical risk penalties
- No hard classification of strategies as conservative or all‑in
- Decision logics may converge on the same team

Risk preferences are expressed **after simulation**, via choice of distribution quantile.

---

## 4. Optimization Architecture (Three‑Layer Model)

### Layer 1 – High‑Fidelity Stage‑n Optimization

**AI responsibility**

For the upcoming stage (*stage n+1*):

- Run high‑fidelity simulation
- Use probability distributions shaped by odds + expert intelligence
- Produce a **CDF of fantasy points for stage n+1**
- Generate top ~10 teams by EV and relevant P‑levels

This layer prioritizes **accuracy for the next stage only**.

---

### Layer 2 – Forward Transfer Pressure Estimation (n+2 and n+3)

**AI responsibility (deterministic, fast)**

Forward logic explicitly **does not simulate future points**.

Instead, for each candidate team it estimates:

- Expected number of riders that become structurally wrong
- Expected transfer volume (typically 3–5 riders per stage)
- Expected transfer cost (buy cost only: 1%)
- Exposure to catastrophic GC scoring penalties

Purpose:
- Enable forward thinking
- Avoid faking knowledge of future outcomes

---

### Layer 3 – Captain Selection

**AI responsibility, user override**

The captain decision is separate from team selection and is optimized independently after Layer 1 completes.

The core trade‑off is between:

- **GC leader**: reliable 100,000‑point GC bonus every stage, low variance
- **Stage winner candidate**: concentrated right‑tail upside, higher variance

The AI evaluates each candidate captain by computing **E[max(ΔV, 0)]** from the simulated distribution — right‑tail shape, not mean EV, drives the recommendation.

The AI proposes a captain with explicit rationale. The user overrides freely.

---

## 5. Forward Stage Description (User‑Controlled, Low‑Fidelity)

**User responsibility**

Future stages (n+2 and n+3) are described using **stage‑type likelihood sliders**, not fixed labels.

Stage archetypes include:
- Sprint
- Reduced sprint / hilly
- Hard GC
- Mixed / unclear

Sliders express **belief under uncertainty** and are:
- Initially suggested by the AI
- Always overrideable by the user

---

## 6. Rider Universe and Tiering

### Tier A – Relevant contenders (~20–30 riders)

**AI suggests, user confirms**

Characteristics:
- Non‑trivial chance of winning or podium
- Meaningful top‑10/top‑15 probabilities
- Receive full probability modeling

Sources used by AI:
- Bookmaker odds (win, top‑3, top‑10 where available)
- Expert previews and narratives

The AI proposes an initial Tier‑A list **per stage scenario**.
The user can:
- Add riders
- Remove riders
- Force inclusion or exclusion

---

### Tier B – Long‑tail / filler riders

Characteristics:
- <1% win probability
- No meaningful podium chance
- Value derived from:
  - Price efficiency
  - Team bonuses
  - Lead‑out roles
  - GC time safety

Tier‑B riders are **not** modeled for wins.
They are handled structurally, not probabilistically.

---

## 7. Probability Construction – Clear Division of Labor

### Step 1 – Scenario Mix

- **User** sets or confirms stage‑type sliders
- **AI** uses sliders to weight scenarios

---

### Step 2 – Tier‑A Identification

- **AI** proposes Tier‑A riders per scenario using odds + expert scan
- **User** adjusts Tier‑A if desired

---

### Step 3 – Baseline Probability Shape

- **AI** extracts implied probabilities from odds
- Probabilities are normalized **within each scenario**
- Outcome buckets used:
  - Win
  - Podium
  - Top‑10
  - Top‑15
  - No points
  - Catastrophe (DNS, GC loss)

Odds provide **shape**, not truth. Bookmaker odds are a T0‑frozen, stage‑specific snapshot of current race state — not a historical performance record. The market has already integrated recent form, parcours fit, and team dynamics into a single stage‑specific number.

---

### Step 4 – Expert Shaping

- **AI** reshapes probabilities based on expert signals:
  - Rider will / won't sprint
  - Team protection
  - Reduced sprint vs bunch sprint
- Adjustments are **relative**, not absolute

---

### Step 5 – Residual Allocation

- **AI** assigns remaining probability mass to Tier‑B riders
- Used only for:
  - Minor top‑15 outcomes
  - Team bonus participation

This preserves distribution coherence without noise.

---

## 8. Consequence‑Based Mismatch Logic

Forward pressure is driven by **scoring consequences**, not abstract fit.

**Sell pressure — GC penalty asymmetry:**

- **GC / climber in sprint stage**  
  Keeps GC time → acceptable

- **Sprinter in hard GC stage**  
  Gruppetto → up to 30 min loss  
  ≈ **90,000 fantasy point penalty**

These one‑way penalties implicitly force selling in future stages.

**Buy pressure — stage depth bonus:**

The depth bonus for placing 0–8 riders in the stage top 15 is non‑linear and can dominate total bank deposit on flat sprint stages. Affordable sprint top‑15 candidates on the right stage type therefore create structural **buy** pressure — the positive complement to GC penalty sell pressure. The depth bonus table should be explicitly evaluated when assessing forward value of Tier‑B sprint candidates.

---

## 9. Candidate Team Generation and Structuring

**AI responsibility**

1. Generate **top ~10 teams** for stage n+1 based on EV / P‑level
2. From these, select **3–5 structurally distinct teams**, differing in:
   - Rider role mix
   - Versatility vs specialization
   - Budget concentration
   - Forward transfer pressure
3. Label teams descriptively (e.g. "Sprint‑maximal", "Versatile core")

Teams are presented as **alternatives**, not prescriptions.

---

## 10. Practical End‑to‑End Workflow

### Step 1 – Post‑Stage Data Refresh (User)
- Stage n finishes
- Holdet.dk unlocks (~2 hours later)
- User clicks **Update Data** button

---

### Step 2 – Intelligence Phase (AI + User)
- **AI** gathers odds, previews, news, weather
- **AI** proposes Tier‑A riders and stage‑type sliders
- **User** reviews and overrides

---

### Step 3 – Optimization Phase (AI)
- Run high‑fidelity simulation for stage n+1
- Produce CDFs
- Generate and structure candidate teams
- Estimate forward transfer pressure
- Propose captain with right‑tail rationale

---

### Step 4 – Refinement Phase (User)
- Adjust future stage beliefs
- Override assumptions
- Optionally discard teams

---

### Step 5 – Final Decision (User)
- Select 1–2 teams
- Set captain
- Execute on Holdet.dk

---

## 11. Canonical Instruction to Any AI Continuing This Project

> Optimize today precisely.
> Propose probabilities, but never hide assumptions.
> Expose future consequences honestly.
> Let the user override at every critical decision point.

---

## 12. Shared Snapshot Specification

The file `stage_N_snapshot.json` is the handoff from Claude to ChatGPT before each stage. Both systems must operate from a provably identical frozen snapshot. This is the foundation of dual‑system comparison validity.

**Fields included in the snapshot:**

- `holdet_ids` — full rider universe with Holdet.dk identifiers
- `current_prices` — rider prices at time of snapshot
- `is_out` — DNF / withdrawal status per rider
- `post_stage_results` — actual finish positions from stage n
- `jersey_holders` — maglia rosa, points, KOM, youth at time of snapshot
- `gc_standings` — full GC classification after stage n
- `team_composition` — current 8‑rider team
- `bank_balance` — current bank balance in kr
- `stage_metadata` — stage number, type, distance, sprint and KOM locations

**Fields explicitly excluded from the snapshot:**

- Bookmaker odds
- Expert intel and source weights
- Probability distributions
- Team recommendations

Each system gathers odds and expert intel independently. Disagreement between Claude and ChatGPT is always traceable to its actual source: divergent probability judgment, or divergent optimization logic given identical data.

---

## 13. System Architecture

### Repository structure

Both AI systems operate within a single shared repository. Each system owns its own engine and dashboard. Neither system touches the other's directories.

```
holdet-v3/
├── ROADMAP.md
├── CLAUDE_CODE.md
├── claude/          ← Claude's engine and dashboard (Claude only)
│   ├── engine/
│   └── dashboard/
├── chatgpt/         ← ChatGPT/Codex domain (ChatGPT scaffolds independently)
└── shared/          ← Holdet.dk data and snapshots only (both systems read)
    ├── data/
    │   ├── riders/
    │   ├── stages/
    │   └── snapshots/
    └── rules/
```

### Shared data contract

`shared/` contains only the fields specified in Section 12: rider universe, prices, isOut status, post-stage results, jersey holders, GC standings, team composition, bank balance, and stage metadata. Intelligence configuration — source weights, odds inputs, expert notes — is each system's own internal concern and is never placed in shared/.

Each system:
- Reads rider universe and prices from `shared/data/riders/`
- Reads stage metadata from `shared/data/stages/`
- Reads the frozen stage snapshot from `shared/data/snapshots/stage_N_holdet.json`
- Writes its own output to `shared/data/snapshots/stage_N_claude.json` or `stage_N_chatgpt.json`

The snapshot schema is defined in Section 12.

### Independence principle

Each system gathers its own odds and expert intel independently. Probability distributions, team recommendations, and captain picks are never shared between systems before both outputs are locked. This preserves the validity of the dual-system comparison.

---

**End of document – continue updating in‑session.**
