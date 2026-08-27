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
        // TODO: this is where Stage 3 (reliability filtering) and
        // Stage 4 (novelty determination) will plug in, once those
        // pieces are built. For now, just a placeholder so the branch
        // exists and is easy to find later.
        println "find_novel=true: novelty filtering pipeline would run here (not yet built)."
    } else {
        println "find_novel=false: stopping after baseline TR-finding step."
    }
}
