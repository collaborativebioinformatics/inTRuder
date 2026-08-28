## Background

Based on the [SuperSTR](https://github.com/bahlolab/superSTR) paper from the Bahlo lab

Simply tests how compressible the insertion sequences are - the more they are compressible, the higher the reported ratio (uncompressed/compressed), the more likely they are to be repetitive

## Usage

The code is `src/python/intruder/pipeline/compression/annotate.py`, installed as the
`compression` console script. Everything it imports — python3, pysam, zlib, argparse,
pandas — is already in the project's runtime dependencies, so `uv sync` is the whole
setup:

```
uv sync
```

`tr_annotation_env.yml` in this directory is the author's original conda environment.
It is kept as a record of the *non-Python* toolchain used alongside the annotator —
`bcftools` and `htslib` for wrangling the VCFs — which uv does not manage. It is not
needed to run this step, and its pinned build strings are macOS-arm64 only.

```
$ uv run compression -h

usage: compression [-h] --input INPUT --output OUTPUT

Annotate VCF with INFO fields eg. uv run compression -i HG00320.merged.sniffles.vcf -o HG00320.merged.sniffles_annotated.vcf

options:
  -h, --help           show this help message and exit
  --input, -i INPUT    Input VCF file
  --output, -o OUTPUT  Output annotated VCF file
```

### Example usage:

Input is 106844 variants, 243Mb uncompressed
```
time uv run compression -i hprc_multisample.INS.vcf -o hprc_multisample.INS_comp.vcf

real    0m10.150s
user    0m7.397s
sys     0m1.366s
```

## Output

Adds "SV_COMP" field to the VCF, eg. the highly repetitive string below has a high compression ratio, so we can be confident it is repetitive

```
chr1    876001  Sniffles2.INS.65S0      C       CACTCCCCACGCTTCCACCCCCACACTCCCCAACACTCCCTCCCCCATACACCCCCACACTCCCTCATACTCCCCCATACTACCGCCAACCTCCCCCATACTCCCCCGATCTCCCCCACACTCCCCACACTCCCCATAACTTCCCCCAGTACTCCTCCACCACACTCCCCCATACCCTCCCCCTCACAACGCCCTCCACTACTCACACACAACTCCCCTCTTACTCTCCCCCACACTCCCCCCACACTCACCCCCACTCCCATACTCCCCCCAACCTCCCCCATACTCCCCCACATTCCCCCATACTCCCCCACATTCCCCACACTCCCCCATCTCCCCAAACTCCCCCATACTCCTCCCCCATACTCCCCCACACTCCCCCACACTCCCCCAAACTCCCCATATCTCCTCCCCCATACTCCCCCATACTCCCCACACTCTCCCCCATACTCCCCCACACTCCCCCATACTCACCCTAACCTCCACCATACTCGCCCACTATTCACCCATACTCCCCCATACTCCCCCCAAAACTCCCCCATACTCCTCCCCCATACTCCACCCACACTCCCTCCACACTCCCCCAAACTCCCCCATACTCTCCCCCTTACTCCCCCACACTCCCCCACACTCCCCATACTCCCCCACACTCCCCACACACACCCCATACTCCCCCCACACTCCCCCACACTCCCCATACTCACCCCAAACTCCCTCACATTCCCCATACTCCCCCATACTCCCCAAACTCCCCCGATACCCTCCCCACACTCCCCCATACTCCCCCATACTCGGCCAACCTCCCCCAAATCCCCCACACACCCCCATACTCCCCCACAGTCCCCCACACTCCCCACACTCCCCCAACCTCCTCCATACTCCCCCATAACTCGGCCCACACTCGCCCACACCCCCCCATACTCCCCCACACTCCCCATA  59      PASS    IMPRECISE;SVTYPE=INS;SVLEN=938;SUPPORT=55;COVERAGE=64,67,66,67,64;STRAND=+-;STDEV_LEN=21.502;STDEV_POS=16.326;SUPPORT_LONG=0;VAF=0.833;SVCOMP=4.9162303664921465       GT:GQ:DR:DV     1/1:43:11:55
```

## Thresholds

Histograms made with [notebooks/comp_histograms.ipynb](../../notebooks/comp_histograms.ipynb);
the method is worked through in
[notebooks/compression-method.ipynb](../../notebooks/compression-method.ipynb).

1. Histogram of compression ratios from the above hprc merged file:

   <img width="592" height="437" alt="image" src="https://github.com/user-attachments/assets/c7f2c5b3-7a72-4c86-918d-0ad59dc3477b" />
2. Zoom to x>20

   <img width="575" height="442" alt="image" src="https://github.com/user-attachments/assets/fff44aa8-1621-4fbe-88f7-53426c140d52" />
   
3. Get percentiles:
```
   # print percentiles
	percentiles = np.arange(0.0, 1.1, 0.1)
	row_indices = (percentiles * (len(sorted) - 1)).astype(int)
	percentile_rows = sorted.iloc[row_indices]


	chrom	pos	alt	comp
	0	chr16	66490464	AAAATAAAATAAAATAAAATGGAATGGAATGGAATGGAATGGAATG...	123.854167
	10684	chr2	117643459	ATAATATTTATATATATAAATATTATATATACTATTTATATATATA...	6.949153
	21368	chr19	2348700	TTCTCTCTCTCCACACACACTCACGCGCTCTCATTCGCTTGATTCC...	4.723404
	32052	chr1	123415590	TGCTAGACAGAAGAATTCTCAGTAACTTCCTTGTGTTGTGTGTTTT...	3.666667
	42737	chr17	23053453	CTCTGAGGATTTCGTTGGAAACGGGATAAAACGCATAGAACTAAAA...	3.120370
	53421	chr4	49286104	AGGCTGGGGTGGTTGACATGAGAGAGACCGGGGAGTAACTGAGTGA...	2.694444
	64105	chr1	185651639	ATTTTTTTTTTCTTTTTTTTTTTTTTTTTTTTTGAGACGGAGTCTC...	2.512000
	74790	chr7	59139927	CTTCGTTGGAAACGGGATTTTTCATATAATGCTAGACGGAAGAATT...	2.257426
	85474	chr5	1422450	ACCCACAGTGCTGCCCACGCTGCTGGGTGCCCACCGCTGCCCACGG...	1.951220
	96158	chrX	71708929	TCAGGAGTTCCAGACGAGCCTGGGCAAGACGGTGAAACCCTGTCTC...	1.589286
	106843	chr22	16380916	<INS>	0.384615
```

So anything above 5 may be nicely repetitive
