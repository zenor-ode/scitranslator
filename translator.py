# translator.py
#
# This script uses the latest 'google-genai' library to translate Markdown files.

import os
import time
import re
from google import genai
from dotenv import load_dotenv

# --- Configuration ---
MARKDOWN_DIR = "temp/markdown"
TRANSLATED_DIR = "temp/translated"
MODEL_NAME = "gemini-3.1-flash-lite-preview"
DEFAULT_TARGET_LANGUAGE = "English"

def clean_markdown_response(response_text):
    """
    Cleans the LLM's response to extract only the raw Markdown code.
    Only strips a fence if the ENTIRE response is wrapped in one outer
    ```markdown ... ``` block. Content that includes its own fenced code
    listing must not have that inner fence mistaken for an outer wrapper,
    which would discard everything else in the translation.
    """
    text = response_text.strip()
    match = re.match(r'^```(?:markdown)?\n(.*)\n```$', text, re.DOTALL)
    return match.group(1).strip() if match else text

def translate_markdown(markdown_content, client, target_language, model_name=MODEL_NAME):
    """
    Sends Markdown content to Gemini for translation.
    """
    translation_prompt = f"""
You are an expert translator and Markdown specialist. Your task is to translate the following document content, which is in Markdown format, into {target_language}.

CRITICAL RULES:
1. Translate ONLY the prose/text content.
2. DO NOT translate or modify any Markdown syntax or LaTeX equations (`$...$` or `$$...$$`).
3. Maintain the exact same structure and formatting.
4. Your output must be ONLY the translated Markdown content, without any explanations.
"""
    if not client:
        print("  > Translation skipped due to uninitialized model.")
        return None

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[translation_prompt, markdown_content])
        translated_text = response.text
        return clean_markdown_response(translated_text)

    except Exception as e:
        print(f"  > Error during translation: {e}")
        return None

def run_translation(target_language=DEFAULT_TARGET_LANGUAGE, model_name=MODEL_NAME):
    """
    Main function to orchestrate the translation process.
    """
    load_dotenv()
    try:
        if "GEMINI_API_KEY" not in os.environ:
            raise ValueError("GEMINI_API_KEY not found.")
        client = genai.Client()
        print(f"Gemini client initialized for translation (Model: {model_name}).")
    except (ValueError, Exception) as e:
        print(f"Warning: Could not configure Gemini model. Translation will be skipped. Details: {e}")
        return

    os.makedirs(TRANSLATED_DIR, exist_ok=True)

    try:
        markdown_files = sorted(
            [f for f in os.listdir(MARKDOWN_DIR) if f.endswith((".md", ".markdown"))],
            key=lambda x: int(re.search(r'(\d+)', x).group(1))
        )
        if not markdown_files:
            print(f"No Markdown files found in '{MARKDOWN_DIR}'. Run ocr.py first.")
            return
    except (FileNotFoundError, AttributeError, TypeError):
        print(f"Error: Directory '{MARKDOWN_DIR}' not found. Please run ocr.py first.")
        return

    print(f"Found {len(markdown_files)} files to translate to {target_language}.")

    for filename in markdown_files:
        print(f"Translating {filename}...")
        filepath = os.path.join(MARKDOWN_DIR, filename)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                original_content = f.read()
        except Exception as e:
            print(f"  > Error reading file {filepath}: {e}. Skipping.")
            continue

        time.sleep(10)
        translated_content = translate_markdown(original_content, client, target_language, model_name=model_name)

        if translated_content:
            base_name = os.path.splitext(filename)[0]
            output_filename = f"{base_name}.md"
            output_filepath = os.path.join(TRANSLATED_DIR, output_filename)
            
            with open(output_filepath, "w", encoding="utf-8") as f:
                f.write(translated_content)
            print(f"  > Successfully saved translated Markdown to {output_filepath}")

if __name__ == "__main__":
    run_translation()
