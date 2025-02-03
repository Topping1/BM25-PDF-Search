These scripts are a backup of the old scripts to create JSON and EMB files. The scripts are kept here because they can be more convenient to use for power users (use in Terminal window).

## Scripts Overview

### `chunk-pdf-pages.py`
- Extracts text from PDF files into JSON format, chunked by pages.
- Outputs one JSON file per PDF, named after the original PDF.
- The script checks for already processed PDFs, so if the user adds more PDFs to a folder, running the script again will only add the missing JSON files.

### `create-JSON-embedding.py`
- Generates embeddings for the text in JSON files using `fastembed`.
- Produces `.emb` files corresponding to the JSON files. These contain embeddings but exclude text for reduced size.
- The script checks for already processed JSON files, so if the user adds more PDFs and processes them into JSON files, running the script again will only add the missing EMB files.

## Workflow

### 1. Minimum Workflow (JSON files only)
- Run `chunk-pdf-pages.py` to extract text from PDFs into JSON files. This is usually a long process but it needs to be done only once.
- Use the `BM25-String-Embed-Rerank-PDF-Search.py` script to search the JSON files using BM25 or simple text search.

### 2. Recommended Workflow (JSON + EMB files)
- Run `chunk-pdf-pages.py` to create JSON files from PDFs. This is usually a long process but it needs to be done only once.
- Run `create-JSON-embedding.py` to generate EMB files containing text embeddings for each page. This is usually a long process but it needs to be done only once.
- Use `BM25-String-Embed-Rerank-PDF-Search.py` for full search functionality, including embedding-based search and reranking.
