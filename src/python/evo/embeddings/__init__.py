"""Turning loci into Evo 2 vectors: window construction, extraction, storage."""

from evo.embeddings.extract import (
    BLOCK_TYPES,
    DEFAULT_LAYER_SET,
    LAYER_SETS,
    OVERFLOWS_FLOAT16,
    Embedder,
    Evo2Embedder,
    KmerEmbedder,
    extract,
    extract_window,
    reverse_complement,
)
from evo.embeddings.loci import (
    InsertionCall,
    insertion_sequence,
    parse_co,
    read_insertions,
)
from evo.embeddings.store import Embeddings, load, save
from evo.embeddings.windows import (
    SEGMENTS,
    Span,
    Window,
    WindowSpec,
    build_window,
)

__all__ = [
    "BLOCK_TYPES",
    "DEFAULT_LAYER_SET",
    "LAYER_SETS",
    "OVERFLOWS_FLOAT16",
    "SEGMENTS",
    "Embedder",
    "Embeddings",
    "Evo2Embedder",
    "InsertionCall",
    "KmerEmbedder",
    "Span",
    "Window",
    "WindowSpec",
    "build_window",
    "extract",
    "extract_window",
    "insertion_sequence",
    "load",
    "parse_co",
    "read_insertions",
    "reverse_complement",
    "save",
]
