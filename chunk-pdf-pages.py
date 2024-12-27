import os
import json
import pymupdf4llm

def extract_page_chunks(file_path):
    """Extracts page-length chunks from a PDF file using PyMuPDF4LLM."""
    chunks = []
    with open(file_path, "rb") as f:
        data = pymupdf4llm.to_markdown(file_path, page_chunks=True)
        for page in data:
            chunks.append({
                "text": page["text"],
                "page_number": page.get("metadata", {}).get("page", None),
                "filename": os.path.basename(file_path)
            })
    return chunks

def process_files_in_folder():
    """Processes all PDF files in the folder into individual JSON files."""
    files = [f for f in os.listdir(".") if f.endswith(".pdf")]
    total_files = len(files)

    for idx, file_name in enumerate(files):
        json_file_name = f"{os.path.splitext(file_name)[0]}.json"

        if os.path.exists(json_file_name):
            print(f"Skipping {file_name}, already processed.")
            continue

        print(f"Processing file {idx + 1} of {total_files}: {file_name}")

        try:
            chunks = extract_page_chunks(file_name)
            with open(json_file_name, "w", encoding="utf-8") as json_file:
                json.dump(chunks, json_file, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error processing {file_name}: {e}")

if __name__ == "__main__":
    process_files_in_folder()
    print("Processing complete.")
