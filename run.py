# run.py
#
# Main orchestrator script for SciTranslator.
# Reads settings from config.yaml or CLI arguments.

import os
import sys
import shutil
import argparse
import yaml

# Import the pipeline scripts
import extractor
import ocr
import translator
import compiler
import stitcher

# --- Default Paths ---
TEMP_DIR = "temp"
IMAGE_DIR = os.path.join(TEMP_DIR, "images")

def check_dependencies():
    """
    Checks if required system binaries (pandoc, tectonic) are available.
    """
    dependencies = ["pandoc", "tectonic"]
    missing = []
    for dep in dependencies:
        if shutil.which(dep) is None:
            missing.append(dep)
    
    if missing:
        print(f"Error: Missing required system dependencies: {', '.join(missing)}")
        print("Please ensure they are installed and available in your PATH.")
        sys.exit(1)
    print("--- System dependencies verified ---")

def clean_temp_dirs():
    """
    Clears the temporary directories to ensure a fresh run.
    """
    print("--- Cleaning temporary directories ---")
    if os.path.exists(TEMP_DIR):
        # We also need to clear 'assets' and 'pandoc_tmp' which we added recently
        dirs_to_clean = ['images', 'markdown', 'translated', 'compiled', 'logs', 'assets', 'pandoc_tmp', 'tectonic_cache']
        for d in dirs_to_clean:
            dir_path = os.path.join(TEMP_DIR, d)
            if os.path.exists(dir_path):
                try:
                    shutil.rmtree(dir_path)
                    print(f"  > Cleared {dir_path}")
                except Exception as e:
                    print(f"  > Error cleaning {dir_path}: {e}")
            os.makedirs(os.path.join(TEMP_DIR, d), exist_ok=True)
    else:
        os.makedirs(TEMP_DIR)
        for d in ['images', 'markdown', 'translated', 'compiled', 'logs', 'assets', 'pandoc_tmp', 'tectonic_cache']:
            os.makedirs(os.path.join(TEMP_DIR, d))
    print("--- Done cleaning ---\n")

def load_config(config_path):
    """
    Loads configuration from a YAML file.
    """
    if not os.path.exists(config_path):
        print(f"Warning: Configuration file '{config_path}' not found. Using defaults.")
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def run_pipeline(config):
    """
    Executes the entire document translation pipeline based on the config.
    """
    check_dependencies()
    # 0. Extraction of Parameters
    p = config.get('pipeline', {})
    input_pdf = p.get('input_pdf', 'sample.pdf')
    target_language = p.get('target_language', 'English')
    output_pdf = p.get('output_pdf', 'output/translated.pdf')
    
    # Advanced / Formatting Parameters
    f = config.get('formatting', {})
    dpi = f.get('dpi', 300)
    
    # Model parameters
    m = config.get('model', {})
    vlm_model = m.get('vlm_name', 'gemini-3.1-flash-lite-preview')
    trans_model = m.get('translation_name', 'gemini-3.1-flash-lite-preview')

    # Ensure output directory exists
    output_dir = os.path.dirname(output_pdf)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    if not os.path.exists(input_pdf):
        print(f"Error: Input file not found at '{input_pdf}'", file=sys.stderr)
        sys.exit(1)
        
    clean_temp_dirs()
    
    # --- 1. Extraction ---
    print(f"--- Step 1: Extracting pages from {input_pdf} ---")
    extractor.extract_pages_as_images(pdf_path=input_pdf, output_dir=IMAGE_DIR, dpi=dpi)
    print("--- Extraction complete ---\n")
    
    # --- 2. OCR ---
    print(f"--- Step 2: Performing OCR (VLM Model: {vlm_model}) ---")
    ocr.run_ocr(pdf_path=input_pdf, model_name=vlm_model)
    print("--- OCR complete ---\n")
    
    # --- 3. Translation ---
    print(f"--- Step 3: Translating to {target_language} (Model: {trans_model}) ---")
    translator.run_translation(target_language=target_language, model_name=trans_model)
    print("--- Translation complete ---\n")
    
    # --- 4. Compilation ---
    print("--- Step 4: Compiling to PDF with Pandoc ---")
    papersize = f.get('papersize', 'a4')
    margin = f.get('margin', '2cm')
    fontsize = f.get('fontsize', '12pt')
    compiler.run_compilation(papersize=papersize, margin=margin, fontsize=fontsize, model_name=trans_model)
    print("--- Compilation complete ---\n")
    
    # --- 5. Stitching ---
    print(f"--- Step 5: Stitching final document to {output_pdf} ---")
    output_dir = os.path.dirname(output_pdf) or "."
    output_filename = os.path.basename(output_pdf)
    stitcher.stitch_pdfs(output_dir=output_dir, output_filename=output_filename)
    print("--- Stitching complete ---\n")
    
    print("--- Pipeline finished successfully! ---")
    print(f"Final output: {output_pdf}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SciTranslator: Translate scientific PDFs.")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--input", type=str, help="Override input_pdf")
    parser.add_argument("--lang", type=str, help="Override target_language")
    parser.add_argument("--output", type=str, help="Override output_pdf")
    args = parser.parse_args()
    
    # Load base config
    config = load_config(args.config)
    
    # CLI Overrides
    if 'pipeline' not in config: config['pipeline'] = {}
    if args.input: config['pipeline']['input_pdf'] = args.input
    if args.lang: config['pipeline']['target_language'] = args.lang
    if args.output: config['pipeline']['output_pdf'] = args.output
    
    # Start the engine
    run_pipeline(config)
