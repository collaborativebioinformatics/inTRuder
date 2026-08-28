
# Set up env

## Conda
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash ~/Miniconda3-latest-Linux-x86_64.sh -b -p ${HOME}/miniconda3
source $HOME/miniconda3/bin/activate
conda init
source ~/.bashrc
export CONDA_PLUGINS_AUTO_ACCEPT_TOS="yes"

## Sniffles + AWSCLI
conda create -n sniffles
conda activate sniffles
conda install -y bioconda::sniffles
conda install -y conda-forge::awscli


# Download dataset CRAM
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/hprc/crams/${cram}.crai .
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/hprc/crams/${cram} .

# Download reference
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/reference-genome/human_GRCh38_no_alt_analysis_set.fasta .
aws s3 cp --no-sign-request s3://1000g-ont/working_dir/tr_benchmarking/reference-genome/human_GRCh38_no_alt_analysis_set.fasta.fai .
# UCSC Table Browser simple repeats BED file => simpleRepeat.bed


# Run Sniffles on single-sample
prefix=`basename ${cram} .cram`
sniffles --input ${cram} --vcf ${prefix}.vcf --snf ${prefix}.snf --reference human_GRCh38_no_alt_analysis_set.fasta --tandem-repeats simpleRepeat.bed

# Run Sniffles on all samples to generate multisample dataset
paste <(ls -1 *snf) <(ls -1 *.snf | cut -d'.' -f1) > snfs.tsv  ## <snf filename>\t<sample name>
sniffles --input snfs.tsv --vcf hprc_multisample.vcf --reference human_GRCh38_no_alt_analysis_set.fasta --tandem-repeats simpleRepeat.bed > multisample_output.log 2>multisample_error

# Filter multisample VCF to keep SVTYPE=INS
sudo apt install bcftools
bcftools view -i 'SVTYPE="INS"' hprc_multisample.vcf -o hprc_multisample.INS.vcf

