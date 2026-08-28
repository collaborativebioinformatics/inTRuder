#!/usr/bin/env nextflow

nextflow.enable.dsl = 2

params.input_tsv     = params.input_tsv     ?: null
params.work_dir      = params.work_dir      ?: launchDir
params.software_path = params.software_path ?: '/pl/active/dashnowlab/work/ealiyev/SVTR_Analysis/software'

if (!params.input_tsv) {
    error 'Missing required parameter: --input_tsv <file.tsv>'
}

def containerDir = "${params.software_path}/containers"

workflow {
    input_tsv = file(params.input_tsv, checkIfExists: true)
    project   = input_tsv.baseName

    ANNOTATE_SV(Channel.of(tuple(project, input_tsv)))
}

process ANNOTATE_SV {
    tag "${project}"

    container "${containerDir}/annotsv_3.5.8_biocontainers.sif"

    cpus 8
    memory 16.GB
    time 8.h

    publishDir params.work_dir, mode: 'copy'

    input:
    tuple val(project), path(input_tsv)

    output:
    path "${project}.bed",               emit: bed
    path "${project}.tsv",               emit: annotsv_tsv
    path "${project}.tsv.processed.tsv", emit: processed_tsv

    script:
    def sw = params.software_path
    """
    awk -F '\\t' 'BEGIN { OFS="\\t" }
        NR == 1 {
            sub(/\\r\$/, "")
            for (i = 1; i <= NF; i++) {
                if (\$i == "chrom")     chrom_col = i
                if (\$i == "ins_coord") coord_col = i
                if (\$i == "SVID")      id_col = i
            }
            if (!chrom_col || !coord_col || !id_col) {
                print "ERROR: input TSV must contain chrom, ins_coord, and SVID columns" > "/dev/stderr"
                exit 1
            }
            print "#CHROM", "START", "END", "SVTYPE", "SVID"
            next
        }
        {
            sub(/\\r\$/, "")
            id = \$id_col
            if (id != "" && !seen[id]++)
                print \$chrom_col, \$coord_col, \$coord_col + 1, "INS", id
        }
    ' "${input_tsv}" > "${project}.bed"

    AnnotSV \\
        -SVinputFile    "${project}.bed" \\
        -SVminSize      0 \\
        -svtBEDcol      4 \\
        -genomeBuild    GRCh38 \\
        -overwrite      1 \\
        -bedtools       \$(which bedtools) \\
        -SVinputInfo    1 \\
        -annotationsDir "${sw}/tools/AnnotSV/share/AnnotSV/" \\
        -outputFile     "${project}" \\
        -outputDir      .

    java -jar -Xmx64G \\
        "${sw}/tools/htsSidra-1.2-jar-with-dependencies.jar" \\
        processAnnotatedFileAnnotSV_3_8 \\
        "${project}.tsv"
    """
}
