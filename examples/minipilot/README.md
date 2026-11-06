# MINIPILOT

A small synthetic study that `fleet run` builds end to end, from the CSV files
in `raw/` to SDTM (DM, AE, VS, EX) and ADaM (ADSL, ADVS, ADAE, ADEX):

```bash
uv run fleet run --config examples/minipilot/study_config.yaml --out out/minipilot
```

Why it exists, the clinical rules it shows and how to use it:
`docs/examples/minipilot.md`.
