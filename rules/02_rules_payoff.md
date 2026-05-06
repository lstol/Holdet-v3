# Holdet v2 — Rules & Payoff Structure
# 02_rules_payoff.md
# Source: Official Danish Holdet rules (swush.com)
# Competition: Giro d'Italia 2026 / Tour de France 2026

---

## 1. Payoff Structure Contract

Payoff structure is a static, exogenous mapping from Outcome Space events to value. It is defined outside the system and is a direct input to Layer 4 (EV) only.

**Constraints:**
- Must not depend on Rider-Intrinsic, Race-State, Interaction, Probability, or EV outputs
- Must be versioned and fixed prior to execution boundary declaration
- Must remain invariant across all runs sharing the same Governance Binding Certificate version
- Must not be updated using EV outputs, derived signals, or any analysis derived from system outputs — including human judgment informed by system behavior, patterns observed in EV, or EV-correlated external signals (e.g. market odds)
- Changes require Governance Layer approval; the approving agent must not also control Outcome Space definition

---

## 2. Game Setup

| Parameter | Value |
|-----------|-------|
| Starting budget | 50,000,000 kr |
| Team size | Exactly 8 riders |
| Max from same real-world team | 2 |
| Captain | Exactly 1 of your 8 |
| Transfer fee (after Stage 1) | −1% of purchased rider's current value |
| Transfers before Stage 1 | Free, unlimited |
| Contract type | Gold = unlimited transfers |
| Bank interest | +0.5% per round on cash held (compounding) |
| Final score | Sum of all rider values + bank balance |

---

## 3. Per-Rider Scoring

### 3.1 Stage Finish Position (non-TTT only)

| Position | Value (kr) |
|----------|-----------|
| 1st | +200,000 |
| 2nd | +150,000 |
| 3rd | +130,000 |
| 4th | +120,000 |
| 5th | +110,000 |
| 6th | +100,000 |
| 7th | +95,000 |
| 8th | +90,000 |
| 9th | +85,000 |
| 10th | +80,000 |
| 11th | +70,000 |
| 12th | +55,000 |
| 13th | +40,000 |
| 14th | +30,000 |
| 15th | +15,000 |
| 16th+ | 0 |

### 3.2 GC Standing After Stage (every stage including TTT)

| GC Position | Value (kr) |
|-------------|-----------|
| 1st | +100,000 |
| 2nd | +90,000 |
| 3rd | +80,000 |
| 4th | +70,000 |
| 5th | +60,000 |
| 6th | +50,000 |
| 7th | +40,000 |
| 8th | +30,000 |
| 9th | +20,000 |
| 10th | +10,000 |
| 11th+ | 0 |

GC tie rule: same finish time → positions assigned by crossing order. Individual positions, no shared ranks, no averaged payouts.

### 3.3 Jersey Bonuses (per stage)

| Jersey | Value (kr) | Rule |
|--------|-----------|------|
| Yellow (GC leader) | +25,000 | Awarded to rider who WINS or DEFENDS at finish |
| Green (Points leader) | +25,000 | Same |
| Polka Dot (KOM leader) | +25,000 | Same |
| White (Best young rider) | +15,000 | Same |
| Most Aggressive (red number) | +50,000 | Awarded once per stage |

Jersey bonus goes to the rider holding the jersey at stage end — not to whoever wore it entering the stage.

### 3.4 Sprint & KOM Points

- Every sprint point = **+3,000 kr per point**
- Every KOM point (any category) = **+3,000 kr per point**
- Applies at every designated point on the route, not just the finish
- Sprint/KOM points are always ≥ 0
- Check stage roadbook — number and location of bonus points varies per stage

### 3.5 Late Arrival Penalty (non-TTT only)

- **−3,000 kr per full minute** behind stage winner
- **Truncated** (not rounded): 4 min 54 sec = 4 full minutes = −12,000 kr
- **Cap: −90,000 kr** (30 minutes maximum)
- Applies only to riders who finish the stage

### 3.6 DNF / DNS / Disqualification

| Status | Penalty | Detail |
|--------|---------|--------|
| DNF | −50,000 kr (once) | Stage of abandonment. Still earns sprint/KOM points earned before abandonment. Does NOT receive Team Bonus. |
| DNS | −100,000 kr per remaining stage | Rider deactivated. Bleeds every stage they don't start. |
| Disqualified | −50,000 kr (once) | Same as DNF. |

DNS cascade formula: DNF on Stage N of 21 = −50,000 + (−100,000 × (21 − N))

---

## 4. Team-Level Bonuses

### 4.1 Team Bonus (non-TTT only)

Triggered when any rider from a real-world team finishes 1st, 2nd, or 3rd. All your active riders from that same real-world team receive:

| Stage result | Bonus per your rider |
|-------------|---------------------|
| 1st place | +60,000 kr |
| 2nd place | +30,000 kr |
| 3rd place | +20,000 kr |

DNF riders on that stage do NOT receive the team bonus.

### 4.2 Captain Bonus

- Captain earns value changes identically to any other rider
- Whatever positive value growth captain achieves → same amount deposited directly to bank
- Negative days: NOT amplified
- Captain locked when stage starts; must be set during trading window

### 4.3 Stage Depth Bonus (non-TTT only)

Based on how many of your 8 riders finish in stage top 15. Paid directly to bank.

| Riders in Top 15 | Bank deposit (kr) |
|-----------------|------------------|
| 0 | 0 |
| 1 | 4,000 |
| 2 | 8,000 |
| 3 | 15,000 |
| 4 | 35,000 |
| 5 | 65,000 |
| 6 | 120,000 |
| 7 | 220,000 |
| 8 | 400,000 |

---

## 5. Team Time Trial (TTT) Stages

On TTT stages, the following are replaced:

| Replaced | By |
|----------|-----|
| Stage finish position | TTT team placement value |
| Team Bonus | TTT scoring |
| Late arrival penalty | Not applied |
| Stage depth bonus | Not applied |

TTT placement value (to all active riders from that real-world team):

| TTT Placement | Value per rider (kr) |
|--------------|---------------------|
| 1st | +200,000 |
| 2nd | +150,000 |
| 3rd | +100,000 |
| 4th | +50,000 |
| 5th | +25,000 |
| 6th+ | 0 |

Still applies normally on TTT stages: GC standing, jersey bonuses, sprint/KOM points.

---

## 6. Financial Mechanics

**Bank interest:** +0.5% per round on cash held, compounding.

**Transfer fee:** −1% of the purchased rider's current value, applied on buy. Free before Stage 1.

**Transfer fee formalization:** fee = 0.01 × TransferBuy.price. Strictly deterministic. No probabilistic interpretation permitted. No EV influence on fee structure.

**Total score:** Sum of all 8 rider values + bank balance (includes captain bonus deposits, stage depth deposits, and interest).

---

## 7. Trading Rules

- Window opens ~20:30 daily (2–3 hours after stage finish)
- Window closes when next stage starts
- Finish all trades 30 minutes before announced start — times change
- Captain change is free, any time window is open; locked at stage start

---

## 8. Confirmed Rule Clarifications

| Topic | Confirmed behaviour |
|-------|-------------------|
| Captain lock | Locked at stage start. Free to change in window. |
| Captain negative days | Only positive growth doubled. Losses NOT amplified. |
| Negative sprint/KOM | Always ≥ 0. Only late arrival + DNF/DNS give negative value. |
| GC ties | Same finish time → crossing order. Individual positions. |
| TTT bottom teams | 6th+ = 0. No late arrival penalty. |
| Final score | Rider values + bank (captain deposits + depth bonus + interest). |
| DNF sprint/KOM | DNF riders earn points accumulated before abandonment. |
| DNF team bonus | DNF riders do NOT receive team bonus on that stage. |
