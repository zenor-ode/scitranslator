import os
import fitz  # PyMuPDF
import time
import subprocess
import sys
import shutil

def run_pipeline_on_chunk(chunk_path, output_dir, max_quota_retries=5):
    """
    Runs the full translation pipeline on a single PDF chunk.
    """
    base_name = os.path.splitext(os.path.basename(chunk_path))[0]
    output_filename = f"{base_name}_translated.pdf"
    source_output_path = os.path.join("output", output_filename)
    final_chunk_output_path = os.path.join(output_dir, output_filename)

    for attempt in range(1, max_quota_retries + 1):
        try:
            print(f"Running pipeline on {chunk_path} (attempt {attempt})...")
            result = subprocess.run(
                [sys.executable, "run.py", "--input", chunk_path, "--output", source_output_path],
                capture_output=True,
                text=True,
                check=True
            )
            print(result.stdout)
            break
        except subprocess.CalledProcessError as e:
            print(f"Error running pipeline on {chunk_path}:")
            print(e.stderr)
            stderr = e.stderr or ""
            if ("RESOURCE_EXHAUSTED" in stderr or "429" in stderr) and attempt < max_quota_retries:
                print(f"Quota exhausted. Waiting 60 seconds before retrying ({attempt}/{max_quota_retries})...")
                time.sleep(60)
            else:
                raise

    if not os.path.exists(source_output_path):
        raise RuntimeError(f"Pipeline succeeded but output file not found at {source_output_path}")

    print(f"Moving translated chunk to {final_chunk_output_path}")
    shutil.move(source_output_path, final_chunk_output_path)
    return final_chunk_output_path


def stitch_pdfs(pdf_paths, output_path):
    """
    Merges multiple PDF files into one.
    """
    print(f"Stitching {len(pdf_paths)} PDFs into {output_path}...")
    final_pdf = fitz.open()
    for pdf_path in pdf_paths:
        if os.path.exists(pdf_path):
            chunk_pdf = fitz.open(pdf_path)
            final_pdf.insert_pdf(chunk_pdf)
            chunk_pdf.close()
        else:
            print(f"Warning: Translated chunk not found at {pdf_path}")
    final_pdf.save(output_path)
    final_pdf.close()
    print("Stitching complete.")


def main(pdf_path, chunk_size=10):
    """
    Splits a PDF into chunks, translates each chunk, and stitches them back.
    """
    if not os.path.exists(pdf_path):
        print(f"Error: PDF not found at {pdf_path}")
        return

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"PDF '{pdf_path}' has {total_pages} pages.")

    temp_chunk_dir = "temp/chunks"
    translated_chunks_dir = "temp/translated_chunks"
    os.makedirs(temp_chunk_dir, exist_ok=True)
    os.makedirs(translated_chunks_dir, exist_ok=True)

    chunk_paths = []
    translated_pdf_paths = []

    for i in range(0, total_pages, chunk_size):
        start_page = i
        end_page = min(i + chunk_size, total_pages)
        print(f"Processing pages {start_page + 1} to {end_page}...")

        chunk_doc = fitz.open()
        chunk_doc.insert_pdf(doc, from_page=start_page, to_page=end_page - 1)

        chunk_filename = f"chunk_{start_page + 1}-{end_page}.pdf"
        chunk_filepath = os.path.join(temp_chunk_dir, chunk_filename)
        chunk_doc.save(chunk_filepath)
        chunk_doc.close()
        chunk_paths.append(chunk_filepath)

        try:
            translated_chunk_path = run_pipeline_on_chunk(chunk_filepath, translated_chunks_dir)
            translated_pdf_paths.append(translated_chunk_path)
        except Exception as e:
            print(f"A critical error occurred while processing {chunk_filepath}: {e}")
            print("Stopping the process. You can resume later by running on the remaining pages.")
            break

    doc.close()

    if translated_pdf_paths:
        base_output_name = os.path.splitext(os.path.basename(pdf_path))[0]
        final_output_path = os.path.join("output", f"{base_output_name}_full_translated.pdf")
        os.makedirs("output", exist_ok=True)
        stitch_pdfs(translated_pdf_paths, final_output_path)
    else:
        print("No chunks were translated.")

    # Optional: Clean up temporary chunk files
    # for path in chunk_paths:
    #     os.remove(path)
    # for path in translated_pdf_paths:
    #      if os.path.exists(path):
    #          os.remove(path)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py <path_to_pdf> [chunk_size]")
    else:
        pdf_file = sys.argv[1]
        c_size = 10
        if len(sys.argv) > 2:
            try:
                c_size = int(sys.argv[2])
            except ValueError:
                print("Chunk size must be an integer.")
                sys.exit(1)
        main(pdf_file, chunk_size=c_size)
