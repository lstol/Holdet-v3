"""
Claude optimizer — builds candidate teams from stage snapshot.

Inputs:
    shared/data/snapshots/stage_N_holdet.json  — rider universe, prices, team state
    odds (gathered independently)
    shared/data/intelligence/expert_sources.yaml — source weights

Output:
    candidate teams ranked by EV, with CDF per team and captain proposals

Not yet implemented.
"""
