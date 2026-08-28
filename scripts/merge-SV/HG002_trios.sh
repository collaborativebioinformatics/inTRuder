# Download datasets
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/giab_epi2me/crams/HG004.30x.haplotagged.cram data/
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/giab_epi2me/crams/HG004.30x.haplotagged.cram.crai data/
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/giab_epi2me/crams/HG003.30x.haplotagged.cram.crai data/
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/giab_epi2me/crams/HG003.30x.haplotagged.cram. data/
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/giab_epi2me/crams/HG003.30x.haplotagged.cram data/
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/giab_epi2me/crams/HG003.30x.haplotagged.cram.crai data/
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/giab_epi2me/crams/HG002.30x.haplotagged.cram data/
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/giab_epi2me/crams/HG002.30x.haplotagged.cram.crai data/

# Download reference
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/reference-genome/human_GRCh38_no_alt_analysis_set.fasta .
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/reference-genome/human_GRCh38_no_alt_analysis_set.fasta.fai .

# Run Sniffles on single-sample
## simpleRepeat.txt downloaded from UCSC Table Browser and converted into simpleRepeat.bed
sniffles --input data/HG002.30x.haplotagged.cram --vcf data/HG002.30x.haplotagged.vcf --snf data/HG002.30x.haplotagged.snf --reference human_GRCh38_no_alt_analysis_set.fasta --tandem-repeats simpleRepeat.bed > HG002.output.log 2>HG002.error.log &
sniffles --input data/HG002.30x.haplotagged.cram --vcf data/HG002.30x.haplotagged.vcf --snf data/HG002.30x.haplotagged.snf --reference human_GRCh38_no_alt_analysis_set.fasta --tandem-repeats simpleRepeat.bed > HG002.output.log 2>HG002.error.log &
sniffles --input data/HG003.30x.haplotagged.cram --vcf data/HG003.30x.haplotagged.vcf --snf data/HG003.30x.haplotagged.snf --reference human_GRCh38_no_alt_analysis_set.fasta --tandem-repeats simpleRepeat.bed > HG003.output.log 2>HG003.error.log &
sniffles --input data/HG004.30x.haplotagged.cram --vcf data/HG004.30x.haplotagged.vcf --snf data/HG004.30x.haplotagged.snf --reference human_GRCh38_no_alt_analysis_set.fasta --tandem-repeats simpleRepeat.bed > HG004.output.log 2>HG004.error.log &

# Run sniffles on multiple samples to merge SVs
sniffles --input data/HG002.30x.haplotagged.snf data/HG003.30x.haplotagged.snf data/HG004.30x.haplotagged.snf --vcf data/HG002_03_04_multisample.vcf --reference human_GRCh38_no_alt_analysis_set.fasta --tandem-repeats simpleRepeat.bed > multisample_output.log 2>multisample_error.log &

# Mendelian report
/home/dnanexus/bcftools/bcftools +mendelian2 data/HG002_03_04_multisample.vcf -p HG002.30x.haplotagged,HG003.30x.haplotagged,HG004.30x.haplotagged -o trio_mendelian_report.txt

# Benchmark against GIAB truthset for HG002 SVs
## Use CMRG SV on HG38: https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/CMRG_v1.00/GRCh38/StructuralVariant/

## Extract HG002 from the merged SV VCF
bcftools view -s data/HG002_03_04_multisample.vcf | bgzip > data/HG002_extracted.vcf.gz; tabix data/HG002_extracted.vcf.gz
## Run truvari with the truthset and HG002 calls
truvari bench -b HG002_GRCh38_CMRG_SV_v1.00.vcf.gz -c data/HG002_extracted.vcf.gz -f human_GRCh38_no_alt_analysis_set.fa -o HG002-multisample-extracted-truvari --includebed HG002_GRCh38_CMRG_SV_v1.00.bed
truvari bench -b HG002_GRCh38_CMRG_SV_v1.00.vcf.gz -c data/HG002_extracted.vcf.gz -f human_GRCh38_no_alt_analysis_set.fa -o HG002-multisample-extracted-pass-truvari --includebed HG002_GRCh38_CMRG_SV_v1.00.bed --passonly

## Use the original HG002 SV VCF
## Run truvari with the truthset and HG002 calls
truvari bench -b HG002_GRCh38_CMRG_SV_v1.00.vcf.gz -c data/HG002.30x.haplotagged.vcf.gz -f human_GRCh38_no_alt_analysis_set.fa -o HG002-original-vcf-truvari --includebed HG002_GRCh38_CMRG_SV_v1.00.bed
truvari bench -b HG002_GRCh38_CMRG_SV_v1.00.vcf.gz -c data/HG002.30x.haplotagged.vcf.gz -f human_GRCh38_no_alt_analysis_set.fa -o HG002-original-vcf-pass-truvari --includebed HG002_GRCh38_CMRG_SV_v1.00.bed --passonly
