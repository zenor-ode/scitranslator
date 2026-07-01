import fitz  # PyMuPDF
import os
import sys

def is_blank_page(page):
    """
    Checks if a page is effectively blank (Task 1).
    A page with fewer than 15 characters of text is only blank if it also
    has no images or vector drawings (otherwise it's a scanned/image-only page).
    """
    text = page.get_text().strip()
    if len(text) >= 15:
        return False
    return len(page.get_images()) == 0 and len(page.get_drawings()) == 0

def _cluster_rects(rects, padding=5):
    """
    Merges overlapping/nearby rects into connected clusters.
    Returns a list of [bbox, contributing_item_count].
    """
    clusters = []
    for rect in rects:
        padded = fitz.Rect(rect) + (-padding, -padding, padding, padding)
        merged = False
        for cluster in clusters:
            if padded.intersects(cluster[0]):
                cluster[0] |= rect
                cluster[1] += 1
                merged = True
                break
        if not merged:
            clusters.append([fitz.Rect(rect), 1])

    changed = True
    while changed:
        changed = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if clusters[i][0].intersects(clusters[j][0]):
                    clusters[i][0] |= clusters[j][0]
                    clusters[i][1] += clusters[j][1]
                    clusters.pop(j)
                    changed = True
                    break
            if changed:
                break
    return clusters

def find_vector_figure_regions(page, min_items=6, min_height=15, min_width=30, label_margin=40, final_padding=8):
    """
    Detects vector-drawn figures (e.g. TikZ/pgfplots charts) that have no
    embedded raster image and would otherwise be invisible to extraction.
    Filters out typographic furniture (fraction bars, table rules, frame
    borders), which are thin and/or isolated single-item shapes, by
    requiring a minimum size and a minimum number of clustered drawing
    items. Expands each cluster to include nearby text (axis ticks, legend
    labels), since those are drawn as glyphs rather than vector paths.
    Returns bounding rects ordered top-to-bottom.
    """
    drawings = page.get_drawings()
    candidates = [
        d["rect"] for d in drawings
        if d["rect"].height >= min_height and d["rect"].width >= min_width
    ]
    if not candidates:
        return []

    clusters = _cluster_rects(candidates)
    words = page.get_text("words")

    figures = []
    for bbox, count in clusters:
        if count < min_items:
            continue
        search_area = fitz.Rect(bbox) + (-label_margin, -label_margin, label_margin, label_margin)
        for w in words:
            word_rect = fitz.Rect(w[:4])
            if search_area.intersects(word_rect):
                bbox |= word_rect
        bbox = fitz.Rect(bbox) + (-final_padding, -final_padding, final_padding, final_padding)
        figures.append(bbox & page.rect)

    figures.sort(key=lambda r: (r.y0, r.x0))
    return figures

def get_page_image_metadata(page):
    """
    Analyzes the page to find image dimensions relative to page width (Task: Scaling).
    Returns a list of dictionaries with image index and width percentage.
    Covers both embedded raster images and detected vector-drawn figures,
    in the same order used to name their extracted files.
    """
    page_width = page.rect.width
    # get_image_info provides the bbox of where the image is actually PLACED on the page
    image_info = page.get_image_info(hashes=False)

    metadata = []
    for i, info in enumerate(image_info):
        bbox = info['bbox']  # (x0, y0, x1, y1)
        img_width = bbox[2] - bbox[0]
        width_pct = min(100, round((img_width / page_width) * 100))
        metadata.append({"index": i, "width_pct": width_pct})

    base_index = len(metadata)
    for offset, rect in enumerate(find_vector_figure_regions(page)):
        width_pct = min(100, round((rect.width / page_width) * 100))
        metadata.append({"index": base_index + offset, "width_pct": width_pct})

    return metadata

def extract_images_from_page(page, page_num, assets_dir, dpi=300):
    """
    Extracts embedded images from a page and saves them as PNGs (Task 2).
    Excludes images smaller than 50x50 pixels.
    Also rasterizes detected vector-drawn figures (e.g. TikZ/pgfplots charts),
    which have no embedded raster image and would otherwise be skipped,
    leaving the OCR's image placeholder pointing at a file that never exists.
    """
    os.makedirs(assets_dir, exist_ok=True)
    images = page.get_images(full=True)

    for img_index, img in enumerate(images):
        xref = img[0]
        try:
            # Extract the image using PyMuPDF's Pixmap
            pix = fitz.Pixmap(page.parent, xref)

            # Skip tiny images (Task 2: e.g., width or height < 50 pixels)
            if pix.width < 50 or pix.height < 50:
                pix = None
                continue

            # Convert to RGB if necessary (to ensure PNG compatibility)
            if pix.n - pix.alpha > 3:
                old_pix = pix
                pix = fitz.Pixmap(fitz.csRGB, old_pix)
                old_pix = None

            # Strict naming convention: page_{page_number}_img_{image_index}.png
            image_filename = f"page_{page_num}_img_{img_index}.png"
            image_path = os.path.join(assets_dir, image_filename)
            pix.save(image_path)
            pix = None  # Free memory
        except Exception as e:
            print(f"    > Warning: Failed to extract image {img_index} on page {page_num}: {e}")

    next_index = len(images)
    zoom_factor = dpi / 72.0
    matrix = fitz.Matrix(zoom_factor, zoom_factor)
    for offset, rect in enumerate(find_vector_figure_regions(page)):
        vector_index = next_index + offset
        try:
            pix = page.get_pixmap(matrix=matrix, clip=rect)
            image_filename = f"page_{page_num}_img_{vector_index}.png"
            image_path = os.path.join(assets_dir, image_filename)
            pix.save(image_path)
            pix = None
        except Exception as e:
            print(f"    > Warning: Failed to rasterize vector figure {vector_index} on page {page_num}: {e}")

def extract_pages_as_images(pdf_path, output_dir, dpi=300):
    """
    Extracts pages from a PDF as high-resolution images and extracts embedded assets.

    Args:
        pdf_path (str): The path to the input PDF file.
        output_dir (str): The directory to save the output images (temp/images).
        dpi (int): The desired resolution in dots per inch.
    """
    # Create the output directory if it doesn't exist
    images_dir = output_dir
    
    # Task 2: Ensure there is an assets/ directory (e.g., temp/assets/)
    temp_root = os.path.dirname(images_dir)
    assets_dir = os.path.join(temp_root, "assets")
    
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(assets_dir, exist_ok=True)

    # Open the PDF file
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening PDF '{pdf_path}': {e}", file=sys.stderr)
        sys.exit(1)

    num_pages = doc.page_count
    zoom_factor = dpi / 72.0
    matrix = fitz.Matrix(zoom_factor, zoom_factor)

    print(f"Extracting {num_pages} page(s) and assets from '{pdf_path}' at {dpi} DPI...")

    # Iterate through the pages
    for page_num in range(num_pages):
        page_index = page_num + 1
        try:
            page = doc.load_page(page_num)
            
            # 1. Extract Full Page Image
            output_image_path = os.path.join(images_dir, f"page_{page_index}.png")
            pix = page.get_pixmap(matrix=matrix)
            pix.save(output_image_path)
            
            # 2. Extract Embedded Assets (Task 2)
            extract_images_from_page(page, page_index, assets_dir, dpi=dpi)
            
            print(f"  > Processed page {page_index}")
        except Exception as e:
            print(f"Error processing page {page_index}: {e}", file=sys.stderr)

    doc.close()
    print("Extraction complete.")

if __name__ == "__main__":
    # --- Configuration ---
    PDF_INPUT_PATH = "sample.pdf"
    TEMP_OUTPUT_DIR = "temp/images"
    # --- End Configuration ---

    if not os.path.exists(PDF_INPUT_PATH):
        print(f"Error: Input PDF '{PDF_INPUT_PATH}' not found.", file=sys.stderr)
        sys.exit(1)

    extract_pages_as_images(
        pdf_path=PDF_INPUT_PATH,
        output_dir=TEMP_OUTPUT_DIR
    )
