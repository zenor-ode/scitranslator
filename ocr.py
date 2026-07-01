# ocr.py
#
# This script uses the latest 'google-genai' library to perform OCR.

import os
import re
import time
import fitz  # PyMuPDF
from google import genai
from google.genai import types
from dotenv import load_dotenv
from extractor import is_blank_page, get_page_image_metadata # Import the helpers

# --- Configuration ---
IMAGE_DIR = "temp/images"
MARKDOWN_DIR = "temp/markdown"
MODEL_NAME = "gemini-3.1-flash-lite-preview"

def get_vlm_prompt(page_index, image_metadata=[]):
    """
    Returns the updated system instruction with image placeholder and Scaling logic.
    """
    metadata_hint = ""
    if image_metadata:
        metadata_hint = "### IMAGE METADATA HINTS:\n"
        for meta in image_metadata:
            metadata_hint += f"- Image Index {meta['index']}: original width takes up ~{meta['width_pct']}% of page width.\n"

    return f"""
You are an expert in document formatting and analysis. Your task is to perform OCR on this image of a document page and convert its entire content and layout into a single, clean **GitHub-flavored Markdown** file.

- Preserve the original structure, including columns, figures, and tables, using Markdown's capabilities.
- Convert all text accurately.
- **Do NOT transcribe the running page number** — only the isolated page count itself (e.g. a lone "791" or "3" printed at the very top or bottom edge of the page, outside the body text). The final document is paginated separately after translation, so a copied page number would become stale, duplicate, or out-of-order content.
  - If that same header/footer line also contains other text (e.g. a chapter or section title), keep that surrounding text — drop only the numeric page count itself, not the whole line.
  - This does NOT apply to equation or section reference numbers such as "(20a)", "(21)", or "(5)" — those are structural labels referenced elsewhere in the document and must always be kept exactly as printed, never omitted.
- Represent mathematical equations using LaTeX syntax within Markdown:
  - For inline equations, use `$ ... $`.
  - For block equations, use `$$ ... $$`.
- For tables, use Markdown table syntax.

{metadata_hint}

- **STRICT INSTRUCTION: If you see a diagram, photograph, chart, or graph, DO NOT attempt to recreate it in LaTeX or ASCII. Instead, insert a Markdown image placeholder exactly where it appears in the text using the naming format `![](temp/assets/page_{page_index}_img_N.png){{width=X%}}`. Leave the alt text empty — do not put a label like "Original Diagram" there, since Markdown-to-PDF converters turn non-empty alt text into an auto-generated figure caption, which would duplicate or clash with the document's own caption text nearby.**
- Use the **IMAGE METADATA HINTS** above to determine 'N' and 'X'. Infer the image index 'N' based on the order they appear on the page (0, 1, 2...). Set 'X' to the percentage provided in the hints for that image.

- Do not add any comments or explanations.
- Your output must be ONLY the raw Markdown content for this single page.
"""

def clean_markdown_response(response_text):
    """
    Cleans the VLM's response to extract only the raw Markdown code.
    Only strips a fence if the ENTIRE response is wrapped in one outer
    ```markdown ... ``` block. A page whose content includes its own fenced
    code listing (e.g. a Python snippet) must not have that inner fence
    mistaken for an outer wrapper, which would discard everything else on
    the page.
    """
    text = response_text.strip()
    match = re.match(r'^```(?:markdown)?\n(.*)\n```$', text, re.DOTALL)
    return match.group(1).strip() if match else text

def perform_ocr_for_page(image_path, client, page_index, image_metadata=[], model_name=MODEL_NAME):
    """
    Sends a single page image to Gemini for OCR and returns the Markdown content.
    """
    if not client:
        print(f"  > Skipping {os.path.basename(image_path)} due to uninitialized model.")
        return None

    print(f"Processing page {page_index} ({os.path.basename(image_path)})...")
    try:
        with open(image_path, 'rb') as f:
            image_bytes = f.read()
        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type='image/png'
                ),
                get_vlm_prompt(page_index, image_metadata)
            ])
        raw_markdown = response.text
        cleaned_markdown = clean_markdown_response(raw_markdown)
        return cleaned_markdown

    except Exception as e:
        print(f"  > Error processing page {page_index}: {e}")
        return None

def run_ocr(pdf_path=None, model_name=MODEL_NAME):
    """
    Main function to orchestrate the OCR process for all pages.
    """
    load_dotenv()
    try:
        if "GEMINI_API_KEY" not in os.environ:
            raise ValueError("GEMINI_API_KEY not found in environment variables or .env file.")
        
        client = genai.Client()
        print(f"Gemini client initialized (Model: {model_name}).")
        
        # Task 1: Open PDF to check for blank pages
        doc = fitz.open(pdf_path) if pdf_path else None
        if doc:
            print(f"Opened PDF '{pdf_path}' for stability and scaling checks.")

    except (ValueError, Exception) as e:
        print(f"Warning: Could not initialize Gemini model or PDF. Details: {e}")
        return

    os.makedirs(MARKDOWN_DIR, exist_ok=True)

    try:
        image_files = sorted(
            [f for f in os.listdir(IMAGE_DIR) if f.endswith(".png")],
            key=lambda x: int(re.search(r'(\d+)', x).group(1))
        )
        if not image_files:
            print(f"No PNG files found in '{IMAGE_DIR}'. Please run the extractor script first.")
            return
    except (FileNotFoundError, AttributeError, TypeError):
        print(f"Error: Could not find or parse files in the '{IMAGE_DIR}' directory.")
        return

    print(f"Found {len(image_files)} pages to process for OCR.")

    for image_filename in image_files:
        page_index = int(re.search(r'(\d+)', image_filename).group(1))
        image_path = os.path.join(IMAGE_DIR, image_filename)
        md_filename = f"page_{page_index}.md"
        md_filepath = os.path.join(MARKDOWN_DIR, md_filename)

        image_metadata = []
        # Task 1 & Scaling: Load page
        if doc:
            try:
                page = doc.load_page(page_index - 1)
                if is_blank_page(page):
                    print(f"Page {page_index}: Blank page detected. Bypassing API.")
                    with open(md_filepath, "w", encoding="utf-8") as f:
                        f.write("") # Return simple blank Markdown string
                    continue
                
                # Fetch Scaling Metadata
                image_metadata = get_page_image_metadata(page)
            except Exception as e:
                print(f"  > Warning: Could not analyze page {page_index}: {e}")

        time.sleep(5)  # Delay to respect API rate limits
        markdown_code = perform_ocr_for_page(image_path, client, page_index, image_metadata, model_name=model_name)

        if markdown_code:
            with open(md_filepath, "w", encoding="utf-8") as f:
                f.write(markdown_code)
            print(f"  > Successfully saved Markdown to {md_filepath}")

    if doc:
        doc.close()

if __name__ == "__main__":
    # For standalone testing
    PDF_TEST_PATH = "sample.pdf"
    run_ocr(PDF_TEST_PATH)
