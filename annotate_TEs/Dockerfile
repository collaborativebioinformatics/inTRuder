FROM mambaorg/micromamba:1.5.10

USER root

# System packages
RUN apt-get update && apt-get install -y \
    git \
    wget \
    curl \
    perl \
    make \
    gcc \
    g++ \
    tar \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Create bioinformatics environment
RUN micromamba create -y -n repeatmasker \
    python=3.11 \
    pip \
    bcftools \
    htslib \
    parallel \
    perl \
    trf \
    rmblast \
    h5py \
    -c conda-forge \
    -c bioconda

ENV MAMBA_DOCKERFILE_ACTIVATE=1
SHELL ["/usr/local/bin/_dockerfile_shell.sh"]

WORKDIR /data

# Install RepeatMasker and Dfam
RUN wget https://www.repeatmasker.org/RepeatMasker/RepeatMasker-4.2.4.tar.gz
RUN tar -xzf RepeatMasker-4.2.4.tar.gz

RUN wget https://github.com/Dfam-consortium/FamDB/archive/refs/tags/3.0.0.tar.gz
RUN tar -xzf 3.0.0.tar.gz

# Activate environment automatically
RUN echo "source activate repeatmasker" >> /etc/profile

ENV PATH=/opt/conda/envs/repeatmasker/bin:$PATH

WORKDIR /data/FamDB-3.0.0/Libraries/famdb/
RUN wget https://www.dfam.org/releases/current/families/FamDB/dfam40.0.h5.gz
RUN wget https://www.dfam.org/releases/current/families/FamDB/dfam40.curated.hmm.0.h5.gz
RUN wget https://www.dfam.org/releases/current/families/FamDB/dfam40.curated.consensus.0.h5.gz

RUN gunzip /data/FamDB-3.0.0/Libraries/famdb/*.gz

WORKDIR /data

ENV FAMDB_DIR="/data/FamDB-3.0.0"
ENV TRF_PRGM="/opt/conda/envs/repeatmasker/bin/trf"
ENV RMBLAST_DIR="/opt/conda/envs/repeatmasker/bin"
ENV REPEAT_MASKER="/data/RepeatMasker/RepeatMasker"

WORKDIR /data/RepeatMasker
RUN (printf "1\n5\n") | perl ./configure -famdb_dir /data/FamDB-3.0.0/ -default_search_engine rmblast

ENTRYPOINT ["micromamba", "run", "-n", "repeatmasker", "/data/RepeatMasker/RepeatMasker"]
