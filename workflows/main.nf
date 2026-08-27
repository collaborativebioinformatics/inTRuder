#!/usr/bin/env nextflow

// ---------------------------------------------------------------------
// PARAMETERS
// ---------------------------------------------------------------------
// These are the "knobs" a user can set on the command line, e.g.:
//   nextflow run main.nf --input_vcf my_own_data.vcf --find_novel true

params.input_vcf   = null      // if null, we fall back to the GitHub default below
params.find_novel  = false     // decision point: stop after baseline, or continue?

// TODO: replace with the actual default data once I talk to Harriet about the files!
params.default_vcf_path = "${projectDir}/../data/HPRC_SV.survivor.ins.vcf"


// ---------------------------------------------------------------------
// PROCESS: baseline TR-finding step
// Wraps sv_trfcaller.py (the pytrf-based script) to identify tandem
// repeats within SV insertion ALT alleles.
// ---------------------------------------------------------------------
process FIND_TRS {

    // publishDir copies this process's output to a results folder,
    // so it's not just buried in Nextflow's internal work/ directory
    publishDir "results/baseline", mode: "copy"

    input:
    path vcf_file

    output:
    path "trf_output.tsv"

    script:
    // Calls the copy of sv_trfcaller.py baked into the Docker image at
    // build time (see Dockerfile's COPY instruction) - NOT the host
    // filesystem copy in src/python/. This only resolves correctly
    // when run with -profile docker.
    //
    // sv_trfcaller.py takes POSITIONAL args, not flags:
    //   python sv_trfcaller.py <input.vcf> <output.tsv>
    """
    python3 /opt/scripts/sv_trfcaller.py ${vcf_file} trf_output.tsv
    """
}

// ---------------------------------------------------------------------
// PROCESS: novelty screening
// Wraps the `novelty` CLI (installed via uv sync, from pyproject.toml)
// to screen TRF calls against UCSC simpleRepeat + TRExplorer, adding a
// verdict column (known / novel_motif / novel_locus / unscreened).
// ---------------------------------------------------------------------
process FIND_NOVEL {

    publishDir "results/novel", mode: "copy"

    input:
    path trf_tsv

    output:
    path "novelty_output.tsv"

     script:
    // --min-rep-units 3 matches the standard TR definition floor
    // discussed earlier (AJHG catalog: >=3 repeat units to count as a
    // real TR). Deliberately NOT setting --min-purity: interrupted /
    // imperfect repeats are real biology, not noise - a hard purity
    // gate would bias against exactly the messier, more-likely-novel
    // loci this pipeline is hunting for. Not using --drop-filtered
    // either, so nothing is silently discarded - every row is kept and
    // tagged, with filtering decisions left to a downstream step.
    """
    uv run novelty --platform ucsc,trexplorer annotate ${trf_tsv} novelty_output.tsv \
        --min-rep-units 3
    """
}

// ---------------------------------------------------------------------
// WORKFLOW: wires everything together, including the input-handling
// branch and the find_novel decision point
// ---------------------------------------------------------------------
workflow {

    // --- Input handling branch ---
    if (params.input_vcf) {
        // User supplied their own VCF - use it directly
        vcf_ch = Channel.fromPath(params.input_vcf)
    } else {
        // No input given -use default
        vcf_ch = Channel.fromPath(params.default_vcf_path)
    }

    // --- Baseline: find TRs in the insertions ---
    FIND_TRS(vcf_ch)

    // --- Decision point ---
    if (params.find_novel) {
    FIND_NOVEL(FIND_TRS.out)
    } else {
        println "find_novel=false: stopping after baseline TR-finding step."
    }
}
