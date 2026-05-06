# Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| Session 1 | v3 architecture: odds + expert intel only, no affinity priors | History not predictive in pro cycling — see framing doc Section 7 |
| Session 1 | Captain EV layer added as explicit optimization step | Right-tail shape, not mean EV, drives captain pick — see framing doc Section 4.3 |
| Session 2 | Single repo for both AI systems, separated at folder level | Shared data contract requires single repo; independence maintained by folder separation |
| Session 2 | Intelligence gathering is AI-specific, never shared | Each system gathers own odds and intel — divergence is the useful signal |
| Session 2 | expert_sources.yaml lives in claude/engine/ not shared/ | Source weighting is Claude-internal configuration |
| Session 2 | sessions/, notes/, decisions/ live under claude/ | These are Claude-specific — ChatGPT manages its own equivalents |
