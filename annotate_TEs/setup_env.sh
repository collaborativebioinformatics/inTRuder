mamba env create -n repeatmasker -c bioconda -conda-forge -c anaconda h5py python perl trf rmblast

mamba activate repeatmasker

wget https://www.repeatmasker.org/RepeatMasker/RepeatMasker-4.2.4.tar.gz
tar -xzf RepeatMasker-4.2.4.tar.gz 
wget https://github.com/Dfam-consortium/FamDB/archive/refs/tags/3.0.0.tar.gz
tar -xzf 3.0.0.tar.gz 

cd FamDB-3.0.0/Libraries/famdb/
wget https://www.dfam.org/releases/current/families/FamDB/dfam40.0.h5.gz
wget https://www.dfam.org/releases/current/families/FamDB/dfam40.curated.hmm.0.h5.gz
wget https://www.dfam.org/releases/current/families/FamDB/dfam40.curated.consensus.0.h5.gz
gunzip *.gz

export FAMDB_DIR=$(realpath FamDB-3.0.0)
export TRF_PRGM=$CONDA_PREFIX/bin
export RMBLAST_DIR=$CONDA_PREFIX/bin

