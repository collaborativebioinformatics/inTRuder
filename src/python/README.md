# Python source (`src/python`)

Python code for the project. Environment is managed with [uv](https://docs.astral.sh/uv/).

## Setup

```bash
uv sync                       # create .venv and install locked dependencies
```

## Common tasks

```bash
uv add pandas                 # add a runtime dependency (updates pyproject.toml + uv.lock)
uv add --dev ruff             # add a dev-only dependency
uv run python src/python/your_script.py   # run a script inside the environment
uv run ruff check .           # lint
uv run pytest                 # run tests

# identify repeats using pyTRF from multisample SV file
uv run svpytrf -i multisample.vcf -o trf_output.tsv

# annotate TRF output with novelty verdicts
uv run novelty -i trf_output.tsv -o trf_novelty.tsv

# filter novelty output by motif purity and repeat coverage, etc.
uv run filter -i trf_novelty.tsv -o trf_novelty_filtered.tsv
```

The Python version is pinned in `../../.python-version`; dependencies are locked in
`../../uv.lock`. Commit both along with `pyproject.toml`.
