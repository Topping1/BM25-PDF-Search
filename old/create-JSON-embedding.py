import os
import json
import numpy as np
from fastembed import TextEmbedding

def embed_pages_in_json(json_file_path, embedding_model):
    """
    Reads a JSON file containing text chunks (pages),
    generates embeddings for each chunk individually,
    and returns a list of page-chunks with embeddings included.

    IMPORTANT: We remove the "text" key from each page
    before returning, so the .emb file won't contain the text.
    """
    with open(json_file_path, "r", encoding="utf-8") as json_file:
        pages = json.load(json_file)

    # Process each text chunk individually
    total_pages = len(pages)
    for i, page in enumerate(pages):
        print(f"Processing page {i + 1} of {total_pages}")
        if "text" in page:
            # Generate embedding for the current text chunk
            embedding = list(embedding_model.passage_embed([page["text"]]))[0]  # Convert generator to list
            page["embedding"] = embedding.tolist()  # Convert np.array -> list

            # Remove the "text" key from the page object
            del page["text"]

    return pages

def process_json_files_in_folder():
    """
    Processes all JSON files in the current folder,
    creating a .emb file for each JSON file if not already present.
    The .emb file is still JSON in structure but omits the 'text' field.
    """
    # Initialize the embedding model (change model as needed)
    embedding_model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1")

    # Get a list of all .json files in the current directory
    files = [f for f in os.listdir(".") if f.endswith(".json")]
    total_files = len(files)

    for idx, file_name in enumerate(files):
        # Build the .emb filename
        emb_file_name = f"{os.path.splitext(file_name)[0]}.emb"

        # Skip if .emb file already exists
        if os.path.exists(emb_file_name):
            print(f"Skipping {file_name}, already processed.")
            continue

        print(f"Processing file {idx + 1} of {total_files}: {file_name}")

        try:
            # Embed pages and remove text
            embedded_pages = embed_pages_in_json(file_name, embedding_model)

            # Write the embedded pages to .emb file (JSON in disguise)
            with open(emb_file_name, "w", encoding="utf-8") as emb_file:
                json.dump(embedded_pages, emb_file, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"Error processing {file_name}: {e}")

if __name__ == "__main__":
    process_json_files_in_folder()
    print("Processing complete.")
