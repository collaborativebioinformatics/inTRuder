# Novel Tandem Repeats

Identifying novel human loci absent from the reference genome.

## Important Links

- [Slack](https://baylorncbisvc-1jk9469.slack.com/archives/C0BRNLZDTL3) `#2026_group2_group10_tandem_repeats`
- [Hackathon Document](https://nam04.safelinks.protection.outlook.com/?url=https%3A%2F%2Fdocs.google.com%2Fdocument%2Fd%2F1XlZMGJdudr1C0jS9j1bWgZh4_OWm9lE0Qm8pbTQVRd8%2Fedit%3Fusp%3Dsharing&data=05%7C02%7Cyzb2%40txstate.edu%7C6cd5a1653219475caf8708df02a62c2f%7Cb19c134a14c94d4caf65c420f94c8cbb%7C0%7C0%7C639232584875699222%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=iEWgDTcm1XTYKKFT%2FwmVRQZA38vrz86x0gUgEVGzGIE%3D&reserved=0)
- [Zoom](https://cuanschutz.zoom.us/j/94705840498)
- [Team roles and subgroups](https://docs.google.com/document/d/17ginimXqbUi-xEAUXwJttZUjnYb8Fi3xF4hUsY9ry7k/edit?tab=t.0)
- [Detailed project proposal, including background](https://docs.google.com/document/d/18JEbKyxauTkjYTZojyhRf58wiZ7YvwZixZ-JOBXl74c/edit?usp=sharing)
- [Shared Google Drive Directory](https://drive.google.com/drive/folders/1jXJAgrP3To92SYn5w0bqxMdEu0wF66nd?usp=sharing)

## Web interface (proof of concept)

An interactive browser for candidate loci, with an agent that queries the same
data the charts read and can move the view for you.

```bash
just setup     # installs everything, generates the synthetic demo dataset
just dev       # backend on :8000, frontend on :3000
```

Add a model credential to `backend/.env` to enable chat — the data views work
without one. Anthropic, Google, Ollama and OpenAI are all selectable via
`LLM_PROVIDER`.

| Directory | What it is |
|---|---|
| [`frontend/`](./frontend) | Next.js + Tailwind + assistant-ui |
| [`backend/`](./backend) | FastAPI + LangGraph + DuckDB (its own uv project) |
| [`data/web/`](./data/web) | Dataset manifests — add your own data here |

**Adding a dataset is one YAML file, no code changes.** Manifests point at paths
on your own machine; nothing is uploaded and nothing but the small synthetic demo
set is committed. See [`data/web/README.md`](./data/web/README.md).

> The bundled demo data is **synthetic**. Sample names and the motif-length mix
> mirror the real HPRC callset so the shapes look right, but every locus,
> coordinate and catalog membership is generated. It is not a result.

## Flowchart
Project overview

[![Click to view interactive Miro Board](./docs/images/flowchart_05_08_2026.png)](https://miro.com/app/board/uXjVHuDLcpE=/?share_link_id=710821883698)

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the quick workflow on submitting changes via a pull request.

