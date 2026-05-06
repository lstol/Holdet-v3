# ChatGPT / Codex

This directory is owned by ChatGPT/Codex.
Structure is defined by ChatGPT independently.
Do not add files here from the Claude side.

## Current scaffold

This is a practical, explicit workspace for ChatGPT-side Holdet.dk Giro 2026
fantasy payoff optimization. It reads frozen shared snapshots, keeps local
odds/intel/probability work inside `chatgpt/`, and writes ChatGPT outputs under
`chatgpt/output/`.

Run tests:

```bash
PYTHONPATH=chatgpt python3 -m unittest discover -s chatgpt/tests
```

Run the stage scaffold once `shared/data/snapshots/stage_N_snapshot.json`
exists:

```bash
PYTHONPATH=chatgpt python3 -m src.run_stage --stage 1 --config chatgpt/configs/default_stage_config.json
```
