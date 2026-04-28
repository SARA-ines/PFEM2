import os


EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
)
