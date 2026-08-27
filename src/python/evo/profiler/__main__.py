"""``python -m evo.profiler`` -- time a handful of real windows on a real GPU.

    .venv/bin/python -m evo.profiler calls.vcf hg38.fasta

Prints, for each (variant, layer set): seconds per window, the stage breakdown
that says where they went, peak VRAM, and whether the variant's vectors match
the current code's. Then converts each into hours for the full 8,177-window
callset, which is the number the sharding decision is actually made on.

It runs on the same worker, from the same checkout and the same venv as
``python -m evo.embeddings``, so anything it measures is what a real run will
do -- and like that command it must be invoked as ``.venv/bin/python``, never
``uv run``, which resyncs to ``uv.lock`` and uninstalls flash-attn.

Six windows per variant is enough. The spread between windows is small (they are
within a kilobase of each other in length) and the model load, which dwarfs
everything, is paid once and excluded.
"""

from __future__ import annotations

import argparse
import sys
import time

from evo.embeddings.cli import build_windows, select
from evo.embeddings.extract import LAYER_SETS, Evo2Embedder
from evo.embeddings.loci import read_insertions
from evo.embeddings.windows import WindowSpec
from evo.profiler.throughput import FINITE_LAYERS, VARIANTS, profile_variant
from evo.utils.reference import FastaReference

FULL_CALLSET = 8177
"""Reference + alt windows for the whole of ``first_500_INS.vcf``, from a dry run.

Hard-coded only to turn s/window into hours in the summary; nothing depends on
it being exact.
"""

LAYER_SETS_HERE = {"finite": list(FINITE_LAYERS), "default": list(LAYER_SETS["default"])}


def _mib(n: float) -> float:
    return n / 1024**2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m evo.profiler",
        description="Measure where an Evo 2 extraction run spends its time.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("vcf", help="SV VCF, as given to `python -m evo.embeddings`")
    p.add_argument("reference", help="indexed reference FASTA")
    p.add_argument("--windows", type=int, default=6,
                   help="windows timed per variant, after the warm-up")
    p.add_argument("--warmup", type=int, default=1,
                   help="untimed windows first; the first pass through a shape "
                        "pays allocator growth and autotuning no later one does")
    p.add_argument("--offset", type=int, default=40,
                   help="skip the telomeric N block at the head of the test VCF")
    p.add_argument("--variants", default=",".join(VARIANTS),
                   help=f"comma-separated: {', '.join(VARIANTS)}")
    p.add_argument("--layer-sets", default="finite,default",
                   help="'finite' drops blocks.30/31; 'default' is all nine")
    p.add_argument("--model", default="evo2_7b_base")
    p.add_argument("--device", default="cuda:0")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    import torch

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    sets = [s.strip() for s in args.layer_sets.split(",") if s.strip()]
    for v in variants:
        if v not in VARIANTS:
            raise SystemExit(f"--variants: unknown {v!r}; have {list(VARIANTS)}")
    for s in sets:
        if s not in LAYER_SETS_HERE:
            raise SystemExit(f"--layer-sets: unknown {s!r}; have {list(LAYER_SETS_HERE)}")

    free, total = torch.cuda.mem_get_info()
    print(f"gpu    {torch.cuda.get_device_name(0)}")
    print(f"vram   {_mib(total):.0f} MiB total, {_mib(free):.0f} MiB free")

    # Timed because "raise num_workers" presumes the host is in the way. This is
    # the entire host-side cost, it is paid once for a whole shard, and it
    # happens before the model is even loaded -- there is nothing for a worker
    # to overlap with.
    t0 = time.perf_counter()
    reference = FastaReference(args.reference)
    n = args.warmup + args.windows
    calls = select(read_insertions(args.vcf), args.offset, n * 4)
    windows, _, _, _ = build_windows(calls, reference, WindowSpec())
    windows = [w for w in windows if w.n_fraction <= 0.1][:n]
    build_s = time.perf_counter() - t0
    if len(windows) < n:
        raise SystemExit(
            f"only {len(windows)} clean windows from --offset {args.offset}; "
            f"need {n}. Lower --windows or move --offset."
        )
    lens = [len(w.sequence) for w in windows]
    print(f"host   {len(windows)} windows built in {build_s:.2f} s "
          f"({1000 * build_s / len(windows):.1f} ms/window), "
          f"lengths {min(lens)}-{max(lens)}")

    print(f"load   {args.model} ...", flush=True)
    t0 = time.perf_counter()
    embedder = Evo2Embedder(args.model, args.device)
    print(f"load   {time.perf_counter() - t0:.1f} s")

    results = []
    baselines: dict[str, object] = {}
    for set_name in sets:
        layers = LAYER_SETS_HERE[set_name]
        for name in variants:
            label = f"{name}/{set_name}"
            print(f"\n=== {label} ===")
            print(f"    {VARIANTS[name][1]}; {len(layers)} layers", flush=True)
            try:
                result = profile_variant(
                    name, embedder, torch, windows, layers, args.device,
                    warmup=args.warmup, reference=baselines.get(set_name),
                )
            except (torch.cuda.OutOfMemoryError, RuntimeError) as exc:
                # Not every allocator failure arrives as OutOfMemoryError -- some
                # come out of a kernel as a plain RuntimeError -- and an OOM on
                # `batched`, the variant most likely to hit one, must not take
                # the other five measurements down with it.
                if "out of memory" not in str(exc).lower():
                    raise
                torch.cuda.empty_cache()
                print(f"    OUT OF MEMORY -- {str(exc).splitlines()[0]}")
                results.append((label, None))
                continue

            # The first variant to run on a layer set defines "correct" for it,
            # so a later variant is compared against numbers from the same
            # model load and the same window rather than against a constant.
            baselines.setdefault(set_name, result["output"])

            per = result["seconds"]
            print(f"    {per:.2f} s/window   peak {result['peak_mib']:.0f} MiB "
                  f"({100 * result['peak_mib'] / _mib(total):.0f}% of card)")
            for stage, seconds in result["stages"].items():
                print(f"      {stage:<16} {seconds:6.2f} s  {100 * seconds / per:4.0f}%")
            other = per - sum(result["stages"].values())
            print(f"      {'unattributed':<16} {other:6.2f} s  {100 * other / per:4.0f}%")
            if result["matches"] is not None:
                verdict = "matches baseline" if result["matches"] else "*** DIFFERS ***"
                print(f"      vectors: {verdict} (max |diff| {result['max_abs_diff']:.4g})")
            results.append((label, result))

    print(f"\n=== summary ({FULL_CALLSET} windows in the full callset) ===")
    base = next((r["seconds"] for label, r in results
                 if label == "host/default" and r), None)
    for label, result in results:
        if result is None:
            print(f"  {label:<18}  OUT OF MEMORY")
            continue
        per = result["seconds"]
        delta = ""
        if base and label != "host/default":
            delta = f"  {100 * (base - per) / base:+.0f}%"
        flag = "" if result["matches"] is not False else "  MISMATCH"
        print(f"  {label:<18} {per:5.2f} s/window  {per * FULL_CALLSET / 3600:5.1f} "
              f"L4-hours  peak {result['peak_mib']:5.0f} MiB{delta}{flag}")
    print("\n  Divide the hours by the number of parallel shards.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
