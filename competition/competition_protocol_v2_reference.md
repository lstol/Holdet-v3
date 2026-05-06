# Holdet v2 — Competition Protocol
# competition_protocol.md

---

## 1. Purpose

This protocol governs the operation of a controlled hybrid dual-system setup for Holdet v2 decision support.

Two independent systems — System A (ChatGPT + Codex) and System B (Claude AI + Claude Code) — operate in parallel to produce independent recommendations for each stage. The goal is not to merge outputs but to exploit disagreement as a signal: where systems agree, confidence is higher; where they disagree, the human operator must reason about the source of divergence before acting.

The hybrid setup exists to:
- reduce single-system blind spots
- surface assumption differences before they become decision errors
- provide a controlled comparison baseline across a race

This protocol does not replace the Holdet v2 architecture contracts. All constraints in 01_system_canonical.md through 06_governance.md remain binding on System B. System A must operate under equivalent constraints derived from the same shared foundation.

---

## 2. Shared Foundation

Both systems must operate from an identical shared foundation for every stage. No system may modify, reinterpret, or extend any element of this foundation independently.

### 2.1 Mandatory shared artifacts

| Artifact | Source | Constraint |
|----------|--------|------------|
| Scoring rules and payoff structure | 02_rules_payoff.md | Read-only. No reinterpretation. |
| Outcome Space | 03_outcome_space.md | Closed set. No additions. |
| Rider universe | Versioned snapshot at T0 | Identical across both systems. |
| Race-State data | Versioned snapshot at T0 | Identical across both systems. |
| Odds snapshot | Versioned snapshot at T0 (if used) | Benchmark only. Not a model input. |
| Historical outcome archive | Versioned dataset | Identical training data source. |
| Stage definition | Versioned stage profile | Identical course, TTT flag, weather. |

### 2.2 Shared foundation constraint

No system may:
- substitute its own version of any shared artifact
- extend or narrow the Outcome Space unilaterally
- reinterpret payoff rules
- use a different odds snapshot than the one declared at T0

Any deviation from the shared foundation constitutes a protocol violation and invalidates that system's output for the stage.

---

## 3. Data Freeze Protocol

### 3.1 Snapshot time definition

For each stage, a single snapshot time T0 is declared. T0 is set at least 2 hours before the stage start time, or at trading window close — whichever is earlier.

T0 must be:
- explicitly declared before either system begins processing
- identical for both systems
- immutable once declared

### 3.2 Frozen artifacts at T0

At T0, the following are frozen and versioned:

- Rider universe (active roster, prices, statuses)
- Race-State snapshot (stage profile, weather, GC standings, current jersey holders)
- Odds snapshot (if used as benchmark signal)
- Bank balance and current team composition

### 3.3 Freeze constraint

No artifact update may be incorporated after T0. Both systems must use the identical frozen snapshot. If new information becomes available after T0 (crash, DNS announcement, weather change), it may be noted in the human operator's judgment layer but must not enter either system's computation for that stage.

### 3.4 Execution validity check

Before entering the Independent Recommendation Phase, each system must confirm and declare:

- Execution protocol satisfied: states S0 → S1 → S2 → S3 → S4 completed in order with no cross-state mutation
- System Integrity Validator (SIV) passed: all dependency direction, outcome coverage, cross-layer leakage, and GBC completeness checks returned PASS
- Valid configuration snapshot loaded: all inputs and parameters reference the T0-frozen snapshot and match the declared GBC-equivalent version

This confirmation must be recorded as part of the system's output header before any recommendation content is produced.

**Failure constraint:** If any of the three conditions above is not satisfied, the system's output is invalid for that stage. An invalid output must not enter the comparison protocol. The human operator is notified and may proceed with the single valid system's output or defer the decision.

---

## 4. Independent Recommendation Phase

### 4.1 Independence constraint

Neither system may observe the other system's intermediate artifacts, reasoning, or outputs before both outputs are locked. This includes:
- probability estimates
- EV calculations
- team selection drafts
- scenario assumptions
- confidence assessments

Cross-system visibility before output lock constitutes a protocol violation.

### 4.2 Required outputs per system

Each system must produce the following for every stage, independently:

**Team selection**
- 8 riders with justification per selection
- Budget utilization
- Team constraint compliance (max 2 per real-world team)

**Transfer decisions**
- Riders in, riders out
- Transfer fee cost
- Net EV rationale per transfer

**Captain selection**
- Selected captain
- Rationale based on CaptainPositiveValueGrowth EV
- Alternative captain considered

**Top EV riders list**
- Ranked list of top 5 riders by stage EV
- EV breakdown per rider (stage finish, GC, jersey, sprint/KOM, team bonus, captain bonus)

**Scenario assumptions**
- Stage type prediction (sprint, climber, breakaway, TTT, mixed)
- Key race dynamic assumptions (protected riders, breakaway probability, weather impact)

**Key risks**
- DNF/DNS candidates
- High-variance selections
- Assumption dependencies that could invalidate the recommendation

**Confidence assessment**
- Overall confidence level: HIGH / MEDIUM / LOW
- Primary source of uncertainty

---

## 5. Output Format

Both systems must adhere to the following standardized output structure. Outputs not conforming to this format are not eligible for comparison.

```
stage: [stage number and name]
snapshot_time: [T0 timestamp]
system: [A or B]

team:
  - rider: [name]
    price: [kr]
    role: [GC / sprinter / climber / allrounder / specialist]
    rationale: [one sentence]
  [× 8]

captain:
  rider: [name]
  rationale: [one sentence]
  alternative_considered: [name]

transfers:
  in:
    - rider: [name]
      price: [kr]
      fee: [kr]
      rationale: [one sentence]
  out:
    - rider: [name]
      rationale: [one sentence]
  net_fee_cost: [kr]

top_ev_riders:
  - rank: 1
    rider: [name]
    ev_total: [kr]
    ev_breakdown:
      stage_finish: [kr]
      gc: [kr]
      jersey: [kr]
      sprint_kom: [kr]
      team_bonus: [kr]
      captain_bonus: [kr, if captain]
  [× 5]

scenario_weights:
  stage_type: [sprint / climber / breakaway / TTT / mixed]
  breakaway_probability: [low / medium / high]
  gc_disruption_probability: [low / medium / high]
  weather_impact: [none / minor / significant]

key_assumptions:
  - [assumption 1]
  - [assumption 2]
  - [assumption 3, max]

key_risks:
  - rider: [name]
    risk: [DNF / DNS / form / team-order]
    severity: [low / medium / high]

confidence:
  level: [HIGH / MEDIUM / LOW]
  primary_uncertainty: [one sentence]
```

---

## 6. Comparison Protocol

### 6.1 Timing

Comparison begins only after both systems have submitted locked outputs. Neither system may modify its output once submitted.

### 6.2 Comparison dimensions

For each stage, outputs are compared across:

**Agreement analysis**
- Riders selected by both systems
- Captain agreement
- Transfer agreement
- Scenario type agreement
- Top EV rider overlap

**Disagreement analysis**
For every material disagreement, identify the driver:

| Disagreement type | Driver |
|-------------------|--------|
| Different rider selected | Probability difference, scenario difference, or assumption difference |
| Different captain | CaptainPositiveValueGrowth EV difference or scenario weight difference |
| Different transfer | EV threshold difference or risk assessment difference |
| Different scenario | Stage type prediction or race dynamic assumption |

**Confidence comparison**
- Where both systems are HIGH confidence and agree: strongest signal
- Where both systems are HIGH confidence and disagree: highest priority for human review — see Section 6.4
- Where one or both systems are LOW confidence: flag for caution

### 6.3 Comparison constraint

Comparison is observational only. No system adjusts its output in response to seeing the other system's output. The comparison artifact is produced by the human operator or a neutral aggregation process, not by either system.

### 6.4 Critical decision point

If both systems declare HIGH confidence AND materially disagree on any of the following — team selection, captain, transfers, or scenario type — the stage is classified as a CRITICAL DECISION POINT.

Material disagreement is defined as:
- Different captain selection
- ≥3 riders different in team selection
- Opposite scenario type predictions (e.g. sprint vs climber)
- Transfers that are mutually exclusive (System A buys rider X, System B sells rider X)

At a CRITICAL DECISION POINT, the human operator must produce an explicit decision record before any action is taken. The record must include:

```
critical_decision_point: true
stage: [stage number]
disagreement_summary: [one sentence describing the core conflict]
system_a_position: [brief summary]
system_b_position: [brief summary]
divergence_driver: [probability_difference / scenario_difference / assumption_difference / unknown]
human_reasoning: [explicit statement of why one position is preferred or neither is followed]
decision: [followed_A / followed_B / neither / hybrid]
```

Proceeding without this record when a CRITICAL DECISION POINT has been triggered constitutes a protocol violation. The decision record is appended to post-stage review and governance logs.

---

## 7. Final Decision Layer

The human operator makes all final decisions. Both systems act as advisors only.

### 7.1 Decision authority

- No output from either system is automatically executed
- No averaging or blending of system outputs is permitted
- The human operator selects from, modifies, or rejects system recommendations in full

### 7.2 Decision record

For each stage, the human operator records:
- which system's recommendation was followed (A, B, neither, or hybrid)
- rationale for deviation from either system's recommendation
- any manual overrides applied

### 7.3 Override record

Any manual override of a system recommendation must be logged with the following structure:

```
override:
  - override_type: [team / captain / transfer / assumption]
    original_recommendation: [what the system recommended]
    override_applied: [what the human did instead]
    reason: [explicit statement — required, not optional]
    source: [intuition / external_info / disagreement_analysis / other]
```

All three fields — `reason` and `source` — are mandatory. An override without explicit reason and declared source is an incomplete record and must be flagged before post-stage review.

Override records feed post-stage review and governance logs. They do not feed either system's model.

---

## 8. Post-Stage Review

After stage results are known, a structured review is performed.

### 8.1 Review dimensions

**Outcome accuracy**
- Predicted vs actual StageFinishPosition (top 5)
- Predicted vs actual GCPosition changes
- Predicted vs actual jersey changes
- DNF/DNS predictions vs actuals

**EV accuracy**
- Predicted EV vs realized value per rider
- Captain EV prediction accuracy
- Team bonus realization rate
- StageDepthCount prediction accuracy

**Assumption audit**
- Which scenario assumptions held?
- Which assumptions failed and why?
- Were failures due to model error, assumption error, or unforeseeable events?

### 8.2 System-level comparison

- Which system produced higher realized EV for the stage?
- Which system had more accurate probability-implied rankings?
- Which system's scenario assumptions were better calibrated?

### 8.3 Review constraint

Post-stage review findings feed the governance layer only. They do not trigger direct model updates. Single-stage findings are insufficient justification for any structural change under 06_governance.md Section 5.

---

## 9. Learning Constraint

### 9.1 Prohibited paths

- No single-run feedback into either system's model parameters
- No direct use of EV outputs, realized values, or stage results as training signals within the same run cycle
- No cross-system learning: System A findings must not update System B parameters and vice versa
- No automatic recalibration of probability models based on post-stage outcomes

### 9.2 Permitted paths

- Multi-run pattern analysis aggregated across ≥3 stages before any governance review
- Governance-controlled model updates following the change requirements in 06_governance.md Section 5
- Human operator judgment updates to the override layer (not to Layer 0 or Layer 3)

---

## 10. Drift Prevention

### 10.1 Monitored drift dimensions

Both systems must remain aligned on:
- interpretation of 02_rules_payoff.md scoring rules
- Outcome Space definitions in 03_outcome_space.md
- Execution protocol and snapshot discipline
- Output format compliance

### 10.2 Drift detection

Before each stage, a pre-run alignment check verifies:
- Both systems reference the same GBC-equivalent configuration
- Both systems use the identical T0 snapshot
- Both systems are operating on the same rider universe and outcome space version

### 10.3 Drift resolution constraint

Any detected drift must be identified, documented, and resolved before either system processes the stage. A stage processed under drift conditions produces invalid outputs for both systems.

---

## 11. Evaluation Metrics

System performance is tracked across the full race using the following metrics:

| Metric | Definition |
|--------|-----------|
| Total value (kr) | Sum of rider values + bank at race end, if system recommendation had been followed exactly |
| Captain performance | Realized CaptainPositiveValueGrowth vs predicted, per stage |
| Transfer efficiency | Net EV gain per transfer after fee cost |
| Calibration accuracy | Brier score or equivalent: predicted probabilities vs realized binary outcomes |
| Decision robustness | Percentage of recommendations that remained valid under actual race conditions |
| Scenario accuracy | Percentage of stage type predictions correct |
| DNF/DNS detection rate | Percentage of high-risk riders correctly flagged before abandonment |

Metrics are computed per stage and accumulated across the race. No metric triggers automatic system modification.

---

## 12. Known Limitations

This protocol explicitly acknowledges the following limitations:

**Human judgment remains part of the system.** The human operator's final decision layer introduces subjectivity that is not captured by either system's model. This is intentional and correct — the system is a decision support tool, not an autonomous agent.

**Cross-run interpretation cannot be fully eliminated.** The human operator observes both systems' outputs and post-stage reviews across multiple stages. This inevitably shapes intuition. The protocol mitigates but cannot eliminate this influence.

**This is a controlled hybrid, not a fully closed system.** The comparison process itself is not model-free. Observing divergence and reasoning about it is a form of learning that operates outside both systems' formal contracts.

**Shared foundation does not guarantee identical reasoning.** Two systems operating from the same data may produce different outputs due to architectural differences, probability model differences, or scenario assumption differences. Divergence is expected and informative — it is not a protocol failure.

**Odds as benchmark remain ambiguous.** While odds are constrained to divergence signaling only, the human operator's interpretation of divergence between model and market is itself a judgment call that cannot be fully formalized.

---

*This protocol is subordinate to the Holdet v2 architecture contracts (01–06). In any conflict between this protocol and the architecture contracts, the architecture contracts take precedence. This protocol governs the competitive comparison layer only — it does not modify, extend, or override any layer contract, governance rule, or execution constraint.*

*Changelog: v1.1 — Added Section 3.4 (execution validity check), Section 6.4 (critical decision point), Section 7.3 (override record structure).*
