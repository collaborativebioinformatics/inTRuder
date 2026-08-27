# Analysing Evo 2 embeddings

**Reduce, cluster and novelty-score the `.npz` files `evo-embed` writes — and
check, every time, that the structure you found is not the one you put in.**

| | |
|---|---|
| Install | `uv sync --extra analysis` (CPU only; no torch, no GPU) |
| Commands | `analysis-reduce`, `analysis-cluster` |
| Code | [`src/python/analysis/`](../src/python/analysis/) |
| Input | `.npz` from [`python -m evo.embeddings`](../src/python/evo/embeddings/__main__.py), or one allele at a time from [`evo-embed`](../src/python/evo/embeddings/cli.py) |
| Run record | [`data/evo/README.md`](../data/evo/README.md) |

## Quick start

```bash
uv sync --extra analysis

# What is in this run, and which layers survived float16?
uv run analysis-reduce data/evo/benchA.npz --list

# Which of the 45 (layer, segment) views is worth looking at?
uv run analysis-reduce data/evo/benchA.npz --grid grid.tsv

# Project one view and check what its axes track
uv run analysis-reduce data/evo/benchA.npz \
    --layer blocks.26 --segment junction_5p \
    --method umap --out coords.tsv --plot umap.png --colour-by locus

# Partition it, and score the partition against what we already knew
uv run analysis-cluster data/evo/benchA.npz \
    --layer blocks.26 --segment junction_5p --method hdbscan --out labels.tsv
```

Both commands take the same view-selection flags (`--layer`, `--segment`,
`--strand`, `--normalize`, `--background`, `--delta`), write TSVs that join on
`row`, and accept several `.npz` files at once — which is how you read back a
run sharded with `evo-embed --offset`.

## The unit of analysis

A run stores `(n_windows, n_layers, n_segments, 2 × d_model)`. Layers and
segments are **alternative views** of the same window, not features to
concatenate; every command works on exactly one `(layer, segment)` pair, and
each vector is `concat(forward, reverse_complement)` so `--strand` can take
either half.

Two things are checked rather than assumed:

- **Finiteness.** `blocks.30` and `blocks.31` are ~100% `±inf` in the benchmark
  run — their activations exceed float16's 65,504 range. `--list` marks them,
  the default `--layer` skips them, and asking for one explicitly raises instead
  of yielding an all-NaN projection.
- **Scale.** `--normalize l2` (the default) makes Euclidean distance a monotone
  function of cosine, which is why `--cluster-metric euclidean` is the right
  choice for HDBSCAN despite the data being angular.

## What the benchmark run actually shows

Measured on `data/evo/benchA.npz` — 100 windows, 31 breakpoints, 65 samples, all
on chr1 between 20,849 and 121,109. **The result is negative, and it is the most
useful thing here.**

### Every axis is the locus

PCA of `blocks.26` / `junction_5p`, five components, 60.5% of variance:

| Component | variance | ε² vs `locus` | ρ vs `log_length` |
|---|---:|---:|---:|
| 1 | 27.1% | 0.977 | −0.44 |
| 2 | 12.7% | 0.979 | −0.31 |
| 3 | | 0.993 | +0.39 |
| 4 | | 0.972 | −0.41 |
| 5 | | 0.773 | +0.05 |

UMAP is the same picture: component 2 scores ε² 0.998 against `locus`, component
1 scores 0.974. HDBSCAN finds 8 clusters at silhouette 0.706 — tidy, and
homogeneity 0.911 against `locus`. The islands are loci.

`sample` explains nothing anywhere: neighbour purity 0.009 against a 0.008
chance baseline, and ε² is **negative** on every component.

> **Trap.** Raw η² against `sample` reads 0.51–0.57, which looks like half the
> variance. It is not: any split into *k* groups explains ≈`(k−1)/(n−1)` of pure
> noise, and 65 samples over 100 windows makes that 0.65. The reports print
> bias-corrected ε² for exactly this reason, and rank on it.

### It is not only the flanks

The obvious explanation is that the 3,584 bp flanks are shared between samples
at a breakpoint. Measured at `chr1:90258` over its 39 called samples,
`blocks.26`, max deviation across samples:

| segment | forward | reverse |
|---|---:|---:|
| `left` | 0.011 | 0.024 |
| `junction_5p` | 6.015 | 1.715 |
| `junction_3p` | 1.255 | 6.456 |
| `right` | 0.035 | 0.009 |

The flanks are constant to within numerical noise — Evo 2 is autoregressive, so
forward-strand flank tokens cannot see the insertion at all. But the `repeat`
segment, which pools **only inserted bases and no reference at all**, still
scores ε² 0.997–0.999 against `locus` on its top three components. The samples
called at one breakpoint carry near-identical alleles, so the insertion sequence
is itself locus-specific.

`--grid` says the same across all 35 finite views: locus neighbour purity lands
between 0.542 and 0.578 for every layer and every segment, against a 0.169
chance baseline, and `sample` excess never exceeds 0.037. No choice of layer or
segment escapes it.

**Conclusion: alt-allele embeddings alone cannot answer a novelty question.**
There is no view in which they carry something the coordinates do not already
give you.

## The two ways out

### 1. Subtract the reference allele

`evo-embed --background` embeds the reference allele at each breakpoint —
identical flanks, `insert=""` — and `--delta` subtracts it per breakpoint. What
survives is what the insertion did, with the locus cancelled:

```bash
# on the GPU worker: both alleles, one model load, into one directory
python -m evo.embeddings calls.vcf hg38.fa out/
# -> out/reference.npz (one window per breakpoint), out/alt.npz (one per call)

# locally
uv run analysis-reduce out/alt.npz --background out/reference.npz --delta \
    --layer blocks.26 --segment junction_5p --method umap --out delta.tsv
```

Prefer that to two `evo-embed` runs. It loads Evo 2 once instead of twice, and —
more to the point — it makes the control impossible to leave out, which is
exactly what went wrong on the first full attempt: an alt-only run is
indistinguishable from a complete one until the analysis comes back empty.

It emits one window per *distinct* breakpoint rather than per call, because the
reference allele does not depend on who was called there. On the full VCF that is
**2,124 breakpoints for 6,127 calls (2.88×)**: ≈5.7 h on one L4 at the measured
9.65 s/window, against 16.3 h for the alt run.

### 2. Score against the reference, without clustering at all

```bash
uv run analysis-cluster out/alt.npz --novelty --background out/reference.npz \
    --out scores.tsv
```

Each window's score is its distance to the *k*-th nearest reference-allele
window. This needs no cluster boundaries and no choice of *k*, and it is closer
to what the project is asking: a novel TR is not unusual *as sequence* — Evo 2
trained on plenty of tandem repeats — it is unusual in being *placed here*.
Without `--background` it falls back to LOF within the run, which is a weaker
claim because the comparison set is no longer the reference.

## Where this can go next

1. **Run the background extraction.** Everything above is blocked on it, and it
   is ~5.7 GPU-hours. Nothing else on this list is worth doing first.
2. **Fix the float16 overflow, then re-extract.** `store.save` casts to float16;
   bfloat16 is the same width with float32's exponent range. `blocks.31` is the
   deepest attention block — precisely where placement was expected to show up —
   and it is currently unreadable. `blocks.28.mlp.l3` is next in line: its
   per-dimension variance at `junction_5p` is 12,338 against `blocks.26`'s 0.122.
3. **Get the TR novelty labels joined on.** This is the gap that stops the
   embeddings meaning anything biologically. `first_500_INS.novelty.tsv` carries
   `novelty`, `ucsc_novelty`, `trexplorer_novelty`, `motif` and `purity` per
   call — but it is keyed on the merged record `POS` (via `sv_trfcaller.py`)
   while the embeddings are keyed on the per-sample `FORMAT/CO` breakpoint.
   Joining `benchA.npz` to it on `(SVID, sample)` matches **21 of 100** windows,
   and of those only 4 agree on position. The fix belongs upstream — see the
   warning in [`loci.py`](../src/python/evo/embeddings/loci.py) — not in a join
   key here, because the coordinates on that side are known to be wrong.
4. **Widen past chr1.** All 6,127 calls in this VCF are chr1, and 31 of the
   benchmark's breakpoints sit inside 100 kb, many within 100 bp of each other.
   At `--flank 3584` those windows overlap heavily, so `locus` is an over-fine
   label and the flank effect is worse than the 0.578 purity suggests.
5. **Then, and only then, ask the biological questions.** Do delta vectors
   cluster by motif class? Do the same TR expansions in different samples land
   together? Is distance-from-reference higher for `novel_locus` than for
   `known`? Each is a one-line `--colour-by` or a `--novelty` score once (1) and
   (3) are done.

## Reading the diagnostics

Both commands print these to stderr before writing anything, and both are
designed so a bad result is loud:

`neighbour purity`
: of each window's *k* nearest neighbours in the **input** space, how many share
  its `locus` / `sample`, against the chance baseline for that label's group
  sizes. Computed before reduction, because UMAP is under no obligation to
  preserve it.

`what the components track`
: per component, Spearman ρ against `log_length`, `insert_length`, `n_fraction`
  and `pos`, and bias-corrected ε² against `locus`, `sample`, `chrom` and
  `cropped`. Written in full by `--report`.

`agreement`
: ARI, AMI, homogeneity and completeness of a clustering against the same known
  labels. **High is bad** — it means the partition was already predictable.

`--grid`
: all 45 views scored at once, so `--layer` and `--segment` are chosen on
  evidence rather than on the block-type argument in `extract.py`.

## Running the extraction on a GPU worker

`scripts/dx-worker-setup-evo2.sh` builds the environment. Pass it to any of the
`dx-*` scripts with `--setup`, in place of the generic
`scripts/dx-worker-setup.sh`, which does a plain `uv sync` and cannot install
Evo 2:

```bash
scripts/dx-batch-gpu.sh -t 6h -o data/dx/evo2 \
    --setup scripts/dx-worker-setup-evo2.sh \
    -f /Test_Inputs/first_500_INS.vcf \
    -f /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta \
    -f /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta.fai -- \
    python -m evo.embeddings /home/dnanexus/first_500_INS.vcf \
        /home/dnanexus/human_GRCh38_no_alt_analysis_set.fasta '$OUT'
```

To split a run across several machines, `scripts/dx-shard-gpu.sh` does the same
thing once per shard and stops every box afterwards — see
[docs/scripts/DNANexus.md](scripts/DNANexus.md#several-machines-at-once):

```bash
# ~15.6 L4-hours of work as 4 shards of ~4 h; --calls is the whole VCF's calls
scripts/dx-shard-gpu.sh --shards 4 --calls 6127 --time 6h \
    --setup scripts/dx-worker-setup-evo2.sh \
    -f /Test_Inputs/first_500_INS.vcf \
    -f /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta \
    -f /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta.fai -- \
    python -m evo.embeddings /home/dnanexus/first_500_INS.vcf \
        /home/dnanexus/human_GRCh38_no_alt_analysis_set.fasta '$OUT'
```

It is idempotent, but it is **not** `uv sync`, and each difference cost a
debugging round trip:

1. **Python 3.12, not the repo's pinned 3.13.** `evo2` caps itself below 3.13,
   so `uv.lock` gates it on `python_full_version < '3.13'`. A 3.13 sync succeeds
   and silently installs neither `evo2` nor `vortex`.
2. **flash-attn is required, not an optional fast path.** `vortex` imports
   `flash_attn_2_cuda` at module import time, so `import evo2` raises without it.
3. **It installs *after* the sync, from a prebuilt wheel.** The wheel is specific
   to (python tag, torch major.minor, CUDA, C++11 ABI), so torch must exist first
   to choose it — and these workers ship **no `nvcc`**, so the
   `--no-build-isolation` source build cannot run there at all.
4. **Afterwards, never `uv run`.** flash-attn is not in `uv.lock`, so `uv run`
   resyncs and *uninstalls* it. With no extras it removes torch and evo2 too.
   Call `.venv/bin/python` directly.

### What a run costs

Measured on one L4 with `python -m evo.profiler` (see
[`src/python/evo/profiler/`](../src/python/evo/profiler/)), which times real
windows and prints a stage breakdown, peak VRAM, and whether each variant's
vectors still match the baseline's:

| | s/window | forward | transfer | peak allocated |
|---|---:|---:|---:|---:|
| host pooling, 9 layers | 8.40 | 83% | 14% | 16,847 MiB |
| host pooling, 7 layers | 7.89 | 86% | 12% | 16,847 MiB |
| **device pooling, 7 layers** | **6.87** | 100% | 0% | 16,847 MiB |
| + batched fwd/revcomp | 6.45 | 100% | 0% | 19,066 MiB |

The full `first_500_INS.vcf` callset is 8,177 windows — 2,094 reference-allele
plus 6,083 alt — so ~15.6 L4-hours, or ~4 h across four parallel shards.

> **Batch size and `num_workers` are the wrong levers here, and this is
> measured rather than assumed.** One 8192-token pass through a 7B model is
> ~115 TFLOPs against an L4's ~121 TFLOPS peak, so a *single* sequence already
> saturates the card — the forward pass is 86–100% of every variant, and
> batching the two strands together recovers only launch overhead (6%, for
> +2.2 GB of peak). There is no dataloader to give workers to: window building
> is the entire host-side cost at 11.1 ms/window, done once before the model
> loads. And there is no larger GPU — both GPU instance types this project can
> launch are the same 1× L4 24 GB.
>
> What *did* pay was the transfer nobody was looking at: `extract_window` moved
> the whole `(8192, 4096)` token grid to the host as fp32, 134 MB per layer per
> pass, for `pool` to reduce it to five vectors. Pooling on the device sends
> ~80 KB instead.

Always profile before a long run: at ~7 s/window, 10% is two GPU-hours.
