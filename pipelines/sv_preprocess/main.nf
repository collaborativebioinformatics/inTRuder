nextflow.enable.dsl = 2

process NORMALIZE_SVTYPE {
    tag "${input_vcf.simpleName}"
    publishDir "${params.outdir}", mode: 'copy', overwrite: true
    input:
    path input_vcf
    output:
    path '*.preprocessed.vcf', emit: vcf
    path '*.preprocess.log', emit: log
    script:
    """
    python3 "${projectDir}/scripts/normalize_svtype.py" \\
      --input "${input_vcf}" \\
      --output "${input_vcf.simpleName}.preprocessed.vcf" \\
      2>&1 | tee "${input_vcf.simpleName}.preprocess.log"
    """
}

workflow {
    if (!params.input) { log.error 'ERROR: --input is required'; exit 1 }
    NORMALIZE_SVTYPE(Channel.fromPath(params.input, checkIfExists: true))
}
