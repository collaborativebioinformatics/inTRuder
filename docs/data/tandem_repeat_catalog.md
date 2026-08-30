This dataset contains a bed file of tandem repeat catalog from this paper:

> Chiu, R., Rajan-Babu, IS., Friedman, J.M. et al. A comprehensive tandem repeat catalog of the human genome. Nat Commun 17, 1106 (2026). https://doi.org/10.1038/s41467-025-66153-5

The zonodo link is [here](https://zenodo.org/records/11522276) where the following files were downloaded:

* hg38.v1.bed.gz
* hg38.v1.bed.gz.tbi

In [Step 4 of the pipeline](https://docs.google.com/document/d/1Vs5xVBGYMwYAiHFNz-BmMlDSecp8ZhjsaDfrp4NURs0/edit?tab=t.0#heading=h.597ysu3a2szt), tandem repeat calls generated from SV calls (in TSV format) will be compared against this catalog to understand if our tandem repeats have been previously discovered.

This dataset will be used by the following scripts in the codebase:

* scripts/check_repeat_catalog/intersect.sh
* scripts/check_repeat_catalog/join-hits.py