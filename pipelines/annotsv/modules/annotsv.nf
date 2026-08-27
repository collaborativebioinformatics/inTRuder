process ANNOTSV {
    tag "${meta.id}"
    publishDir "${params.outdir}/annotsv", mode: params.publish_dir_mode, overwrite: true

    input:
    tuple val(meta), path(sv_vcf)
    path(candidate_genes)
    path(annotations_dir)

    output:
    tuple val(meta), path("*.annotated.tsv"), emit: tsv
    path "*.annotsv.log", emit: log

    script:
    def cg_arg = candidate_genes.name != 'NO_FILE' ? "-candidateGenesFile ${candidate_genes}" : ""
    def out_prefix = "${meta.id}.annotated"
    
    // Explicit docker wrapping to bypass Nextaur staging bug
    def docker_cmd = params.use_docker ? "docker run -u root --rm -v \$(pwd):\$(pwd) -w \$(pwd) ${params.annotsv_image}" : ""
    
    // Resolve commands (with or without docker)
    def annotsv_cmd = params.use_docker ? "AnnotSV" : (params.annotsv_dir ? "${params.annotsv_dir}/bin/AnnotSV" : "AnnotSV")

    """
    echo "[annotsv] Running AnnotSV on ${sv_vcf} (${params.genome_build})" >&2
    
    ${docker_cmd} \\
    ${annotsv_cmd} \\
        -SVinputFile    "${sv_vcf}" \\
        -genomeBuild    "${params.genome_build}" \\
        -outputDir      . \\
        -outputFile     "${out_prefix}.tsv" \\
        -bedtools       "${params.bedtools_path}" \\
        -bcftools       "${params.bcftools_path}" \\
        -annotationsDir AnnotSV \\
        ${cg_arg} \\
        ${ext.args ?: ''} \\
        2>&1 | tee "${meta.id}.annotsv.log"
        
    # Check if the output was successfully created
    if [ ! -f "${out_prefix}.tsv" ]; then
        echo "[annotsv] ERROR: Output file ${out_prefix}.tsv was not created!" >&2
        exit 1
    fi
    """
}
