# stitcher.py
#
# Usage:
#   1. Ensure you have the 'pymupdf' library installed (pip install pymupdf).
#   2. Run the script:
#      python stitcher.py

import os
import fitz  # PyMuPDF
import re

# --- Configuration ---
COMPILED_DIR = "temp/compiled"
DEFAULT_OUTPUT_FILENAME = "translated_paper.pdf"

def add_page_numbers(doc, fontsize=10, bottom_margin=36):
    """
    Stamps sequential page numbers, centered at the bottom of each page.
    Each source page is compiled to its own standalone PDF (with its own
    page counter disabled via pagestyle:empty in compiler.py), so numbering
    must be applied once here, after the final merge.
    """
    for i, page in enumerate(doc, start=1):
        text = str(i)
        text_width = fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
        x = (page.rect.width - text_width) / 2
        y = page.rect.height - bottom_margin
        page.insert_text((x, y), text, fontsize=fontsize, fontname="helv")

def stitch_pdfs(output_dir, output_filename):
    """
    Main function to merge individual page PDFs into a final document.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Ensure the compiled directory exists
    if not os.path.exists(COMPILED_DIR):
        print(f"Error: Directory '{COMPILED_DIR}' not found. Run compiler.py first.")
        return

    # Get a sorted list of PDF files
    try:
        pdf_files = sorted(
            [f for f in os.listdir(COMPILED_DIR) if f.endswith(".pdf") and not f.endswith("_temp.pdf")],
            key=lambda x: int(re.search(r'(\d+)', x).group())
        )
        if not pdf_files:
            print(f"No compiled PDF files found in {COMPILED_DIR}.")
            return
    except (FileNotFoundError, AttributeError, ValueError):
        print(f"Error: Could not find or parse files in the '{COMPILED_DIR}' directory.")
        return

    print(f"Found {len(pdf_files)} pages to stitch.")

    # Create a new PDF document for the output
    output_doc = fitz.open()

    for filename in pdf_files:
        filepath = os.path.join(COMPILED_DIR, filename)
        print(f"  > Merging {filename}...")
        try:
            with fitz.open(filepath) as page_doc:
                output_doc.insert_pdf(page_doc)
        except Exception as e:
            print(f"    Error merging {filename}: {e}")

    # Save the final document
    if len(output_doc) > 0:
        add_page_numbers(output_doc)
        final_path = os.path.join(output_dir, output_filename)
        output_doc.save(final_path)
        output_doc.close()
        print(f"\nSuccessfully created: {final_path}")
        print(f"Total pages: {len(pdf_files)}")
    else:
        print("\nNo pages were merged. Final PDF not created.")

if __name__ == "__main__":
    stitch_pdfs("." , DEFAULT_OUTPUT_FILENAME)
