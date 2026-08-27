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
RUN micromamba create -y -n svscanner \
    python=3.11 \
    pip \
    bcftools \
    htslib \
    parallel \
    repeatmasker \
    rmblast \
    trf \
    -c conda-forge \
    -c bioconda

ENV MAMBA_DOCKERFILE_ACTIVATE=1
SHELL ["/usr/local/bin/_dockerfile_shell.sh"]

# Clone repository
RUN git clone https://github.com/GenTechGp/SVscanner.git /opt/SVscanner

WORKDIR /opt/SVscanner

# Install Python dependencies
RUN micromamba run -n svscanner pip install --upgrade pip && \
    micromamba run -n svscanner pip install -r requirements.txt

RUN micromamba run -n svscanner which RepeatMasker

# Configure RepeatMasker to use RMBlast
#RUN micromamba run -n svscanner REPEATMASKER_DIR=$(dirname $(which RepeatMasker)) && \
#   perl ${REPEATMASKER_DIR}/../share/RepeatMasker/util/configure \
#      -default_search_engine rmblast

# Activate environment automatically
RUN echo "source activate svscanner" >> /etc/profile

ENV PATH=/opt/conda/envs/svscanner/bin:$PATH

WORKDIR /data

ENTRYPOINT ["micromamba", "run", "-n", "svscanner", "bash", "/opt/SVscanner/scripts/run_workflow.sh"]
