
1- Firstly we modified the survivor.vcf file to convert SVTYPE=INS by SVTYPE=DUP following this command
sed "s/INS/DUP/g" survivor.vcf > survivor_DUP.vcf 
DUP.vcf file is the input for AnnotSV
2- This AnnotSV has been executed like this
./AnnotSV-3.5.3/bin/AnnotSV -SVinputFile survivor_DUP.vcf -tx ENSEMBL -hpo HP:0001156,HP:0001363,HP:0011304 -SVinputInfo 1 -outputFile prova_nova.vcf

3- Analysis of the output. R script called take_info_annotsv.R
This script select 42 columns related with TR annotations and then generate many figures that describes the effect of TR.


demo_output_annot_sv.tsv --> Demo of AnnotSV can provide
column_description.xlsx --> Description of each AnnotSV column (42 columns)
