## Background

1. Converts insertion sequences from the given (uncompressed) VCF to a fasta file with the headings based on chrom_pos_id (input VCF, output 1 fa per sample)
2. Runs RepeatMasker in the TEtools container (input fa per sample, output table per sample)
3. WIP - annotate RM table back to the VCF (input table, VCF per sample, output VCF per sample)

## Installation
Should only require docker/singularity and a couple of other things that should be on most nix systems

## Usage

1. VCF to fasta
```
for vcf in *.vcf
do
base=$(basename $file .vcf)
bash vcf_to_fasta.sh $vcf ${base}.fa
done
```

2. Run RM to annotate for TEs (it's a bit slow and cumbersome, perhaps only run it on the merged cohort VCF)

```
docker run --rm -v $(pwd):/data dfam/tetools:latest RepeatMasker -pa 4 -species human -dir out/ -no_is /data/first_500_INS_comp.vcf.fa
```
Outputs the following:
```
HG00290.merged.sniffles_comp.vcf.fa.cat
HG00290.merged.sniffles_comp.vcf.fa.masked
HG00290.merged.sniffles_comp.vcf.fa.out
HG00290.merged.sniffles_comp.vcf.fa.tbl
```
`*.out` is the file we want - for each fasta entry, the repeat and TE annotation is present
`*.tbl` is a summary for the whole run (number of LINEs, SINEs, simple repeats, etc)
`*.cat` and `*.masked` can be thrown in the bin

3. Annotate the `*.out` file back to it's VCF
