import os
import json
import tiktoken  # OpenAI's tokenizer library

def count_tokens_llm(text, model="gpt-3.5-turbo"):
    """Count tokens using the LLM's tokenizer."""
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))

def generate_ascii_histogram(data, title="Histogram"):
    """Generate an ASCII histogram for a list of numbers, scaled to a maximum bar length of 80."""
    max_value = max(data)
    min_value = min(data)
    bin_count = 10
    bins = [0] * bin_count
    bin_size = (max_value - min_value) / bin_count

    for value in data:
        bin_index = int((value - min_value) / bin_size)
        if bin_index == bin_count:  # Handle edge case for max value
            bin_index -= 1
        bins[bin_index] += 1

    max_bin_count = max(bins)
    scale_factor = 80 / max_bin_count if max_bin_count > 0 else 1

    histogram = f"{title}\n"
    for i, count in enumerate(bins):
        bin_range = f"[{min_value + i * bin_size:.2f}, {min_value + (i + 1) * bin_size:.2f})"
        scaled_count = int(count * scale_factor)
        histogram += f"{bin_range}: {'#' * scaled_count}\n"

    return histogram

def summarize_json_files(folder_path):
    """Summarize the content of JSON files in a folder."""
    json_files = [f for f in os.listdir(folder_path) if f.endswith(".json")]

    for json_file in json_files:
        json_file_path = os.path.join(folder_path, json_file)

        try:
            with open(json_file_path, "r", encoding="utf-8") as f:
                pages = json.load(f)

            word_counts = []
            token_counts = []

            for page in pages:
                text = page.get("text", "")
                word_counts.append(len(text.split()))
                token_counts.append(count_tokens_llm(text))

            summary = {
                "file_name": json_file,
                "min_word_count": min(word_counts),
                "max_word_count": max(word_counts),
                "average_word_count": sum(word_counts) / len(word_counts),
                "min_token_count": min(token_counts),
                "max_token_count": max(token_counts),
                "average_token_count": sum(token_counts) / len(token_counts),
            }

            print(f"Summary for {json_file}:\n{summary}\n")

            histogram = generate_ascii_histogram(token_counts, title=f"Token Count Histogram for {json_file}")
            print(histogram)

        except Exception as e:
            print(f"Error processing {json_file}: {e}")

if __name__ == "__main__":
    folder_path = "."  # Adjust this path to the directory containing your JSON files
    summarize_json_files(folder_path)
