# compiler.py
#
# This script uses the latest 'google-genai' library to perform self-healing
# compilation of Markdown files to PDF using Pandoc.

import os
import time
import subprocess
from google import genai
from dotenv import load_dotenv

# --- Configuration ---
TRANSLATED_DIR = "temp/translated"
COMPILED_DIR = "temp/compiled"
LOG_DIR = "temp/logs"
MAX_RETRIES = 3
MODEL_NAME = "gemini-3.1-flash-lite-preview"

# Prompt for fixing Markdown based on Pandoc errors
FIX_PROMPT_TEMPLATE = """
The following Markdown code failed to compile to PDF using Pandoc. Here is the error log from Pandoc.
Please analyze the error and the original code, then provide a corrected version of the Markdown.
The goal is to fix syntax or structural errors that Pandoc cannot handle. Preserve the original content and formatting as much as possible.
Output ONLY the corrected Markdown code, with no additional explanations or markdown formatting (like ```markdown).

ERROR LOG:
{error_log}

ORIGINAL MARKDOWN:
{markdown_code}
"""

def compile_pdf_with_pandoc(md_path, output_name, papersize="a4", margin="2cm", fontsize="12pt"):
    """
    Attempts to compile a .md file into a PDF using Pandoc.
    Redirects temp files to the project directory to avoid sandbox errors.
    """
    output_pdf_path = os.path.join(COMPILED_DIR, f"{output_name}.pdf")
    
    # Create local temp/cache directories within the workspace
    local_tmp = os.path.abspath(os.path.join("temp", "pandoc_tmp"))
    tectonic_cache = os.path.abspath(os.path.join("temp", "tectonic_cache"))
    
    os.makedirs(local_tmp, exist_ok=True)
    os.makedirs(tectonic_cache, exist_ok=True)
    
    # Prepare environment with redirected temp paths
    env = os.environ.copy()
    env["TMPDIR"] = local_tmp
    env["TECTONIC_CACHE_DIR"] = tectonic_cache

    try:
        # Pandoc command: input, output, engine, AND geometry flags!
        process = subprocess.run(
            [
                "pandoc", md_path, 
                "-o", output_pdf_path, 
                "--pdf-engine=tectonic",
                "-V", f"papersize:{papersize}",
                "-V", f"geometry:margin={margin}",
                "-V", f"fontsize:{fontsize}",
                "-V", "header-includes=\\usepackage{float}\\floatplacement{figure}{H}", # Forces images to stay in place
                "-V", "pagestyle:empty" # Each source page compiles to its own standalone PDF, so a
                                         # built-in page number here would restart at 1 every time;
                                         # stitcher.py numbers the final merged document instead.
                # "-V", "classoption:twocolumn",    # UNCOMMENT this if the original paper has two columns!
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            timeout=60,
            env=env # Pass the custom environment
        )
        if process.returncode == 0:
            return True, None
        else:
            return False, process.stderr or process.stdout
    except subprocess.TimeoutExpired as e:
        captured = (e.stdout or "") + (e.stderr or "")
        return False, f"Compilation timed out after {e.timeout}s.\n{captured}"
    except FileNotFoundError:
        return False, "Pandoc not found. Please ensure it is installed and in your system's PATH."
    except Exception as e:
        return False, str(e)

def fix_markdown_with_llm(client, markdown_code, error_log, model_name=MODEL_NAME):
    """
    Uses the LLM to fix Markdown syntax errors based on the Pandoc compiler log.
    """
    if not client:
        print("  > LLM model not initialized. Cannot attempt fix.")
        return None

    prompt = FIX_PROMPT_TEMPLATE.format(error_log=error_log, markdown_code=markdown_code)
    try:
        response = client.models.generate_content(model=model_name, contents=prompt)
        fixed_code = response.text.strip()
        if fixed_code.startswith("```markdown"):
            fixed_code = fixed_code[len("```markdown"):].strip()
        if fixed_code.endswith("```"):
            fixed_code = fixed_code[:-3].strip()
        return fixed_code
    except Exception as e:
        print(f"  > Error calling LLM for fix: {e}")
        return None

def run_compilation(papersize="a4", margin="2cm", fontsize="12pt", model_name=MODEL_NAME):
    """
    Main function to find translated markdown files and compile them to PDF.
    """
    load_dotenv()
    client = None
    try:
        if "GEMINI_API_KEY" in os.environ:
            client = genai.Client()
            print(f"Gemini client initialized for compilation self-healing (Model: {model_name}).")
        else:
            print("Warning: GEMINI_API_KEY not found. Self-healing loop will be disabled.")
    except Exception as e:
        print(f"Warning: Could not init Gemini model. Self-healing loop will be disabled. Error: {e}")

    os.makedirs(COMPILED_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    try:
        md_files = sorted([f for f in os.listdir(TRANSLATED_DIR) if f.endswith((".md", ".markdown"))])
    except FileNotFoundError:
        print(f"Error: The directory '{TRANSLATED_DIR}' was not found.")
        return

    if not md_files:
        print(f"No Markdown files found in {TRANSLATED_DIR}. Please run translator.py first.")
        return

    for filename in md_files:
        base_name = os.path.splitext(filename)[0]
        md_input_path = os.path.join(TRANSLATED_DIR, filename)

        try:
            with open(md_input_path, "r", encoding="utf-8") as f:
                markdown_content = f.read()
        except Exception as e:
            print(f"  > Error reading file {md_input_path}: {e}. Skipping.")
            continue

        success = False
        attempt = 0
        current_content_for_compile = markdown_content
        temp_md_path = os.path.join(COMPILED_DIR, f"{base_name}_temp.md")

        while not success and attempt < MAX_RETRIES:
            attempt += 1
            print(f"Compiling {filename} (Attempt {attempt})...")

            with open(temp_md_path, "w", encoding="utf-8") as f:
                f.write(current_content_for_compile)

            success, error_log = compile_pdf_with_pandoc(temp_md_path, base_name, papersize=papersize, margin=margin, fontsize=fontsize)

            if success:
                print(f"  > Success! Saved to {os.path.join(COMPILED_DIR, f'{base_name}.pdf')}")
                if os.path.exists(temp_md_path):
                    os.remove(temp_md_path)
            else:
                print("  > Compilation failed.")
                log_path = os.path.join(LOG_DIR, f"{base_name}_error_{attempt}.log")
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(error_log)
                print(f"  > Error log saved to {log_path}")

                if client and attempt < MAX_RETRIES:
                    print("  > Attempting LLM fix...")
                    time.sleep(10)
                    fixed_content = fix_markdown_with_llm(client, current_content_for_compile, error_log, model_name=model_name)

                    if fixed_content and fixed_content.strip() != current_content_for_compile.strip():
                        current_content_for_compile = fixed_content
                        print("  > LLM provided a fix. Retrying compilation.")
                    else:
                        print("  > LLM could not provide a new fix. Stopping.")
                        break
                else:
                    break

        if not success:
            print(f"  > Could not compile {filename} after {attempt} attempts.")

    print("\nCompilation process finished.")

if __name__ == "__main__":
    run_compilation()
