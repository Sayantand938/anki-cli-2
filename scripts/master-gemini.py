#!/usr/bin/env python3
"""
Master Gemini AI Tool
Combines multiple AI operations into a single script with mode-based execution.
Enhanced with retry logic and graceful error handling.
Auto-chunking enabled by default.
"""

import argparse
import json
import pathlib
import re
import time
import random # Added for jitter
from typing import List, Optional
from pydantic import BaseModel, ValidationError
from google import genai
from google.genai.errors import ServerError, ClientError

# ==== Global Path Configuration ====
DEFAULT_INPUT_PATH = pathlib.Path("data/input/input.json")
DEFAULT_OUTPUT_PATH = pathlib.Path("data/output/output.json")
DEFAULT_LOG_PATH = pathlib.Path("data/output/output_raw.log")

# ==== Default Instruction Files ====
DEFAULT_TAG_AUDITOR_INSTRUCTION = pathlib.Path("instructions/tag-auditor.md")
DEFAULT_GRAMMAR_EXPLAIN_INSTRUCTION = pathlib.Path("instructions/grammar-explain.md")
DEFAULT_EXTRA_GENERATOR_INSTRUCTION = pathlib.Path("instructions/extra-generator.md")
DEFAULT_QUESTION_TAGGING_INSTRUCTION = pathlib.Path("instructions/question-tagging.md")

# ==== Retry Configuration ====
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # Initial delay in seconds
DEFAULT_MAX_DELAY = 60.0  # Maximum delay in seconds
DEFAULT_BACKOFF_FACTOR = 2.0  # Exponential backoff multiplier

# ==== Global Prompt Template ====
PROMPT_TEMPLATE = """
<file_contents>
File: {input_path}
```json
{input_json}
```

File: {instruction_path}
```markdown
{md_instructions}
```
</file_contents>

<user_instructions>
Follow the Instructions as mentioned in the instruction markdown file
</user_instructions>
"""


# ==== Define Schemas ====
class TagAudit(BaseModel):
    noteId: int
    oldTag: str
    newTag: str


class ExtraUpdate(BaseModel):
    noteId: int
    Extra: str


class TagUpdate(BaseModel):
    noteId: int
    newTag: str


# ==== Exception Classes ====
class RetryableError(Exception):
    """Exception for errors that should be retried."""
    pass


class NonRetryableError(Exception):
    """Exception for errors that should not be retried."""
    pass


# ==== Chunking Configuration ====
DEFAULT_CHUNK_SIZE = 25 # Now the default for --chunk-size


# ==== Chunking Utility Functions ====
def chunk_json_data(data: list, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list:
    """Split data into chunks of specified size."""
    chunks = []
    for i in range(0, len(data), chunk_size):
        chunks.append(data[i:i + chunk_size])
    return chunks


def create_input_chunks(input_path: pathlib.Path, chunk_size: int) -> list[pathlib.Path]:
    """
    Create chunked input files from the main input file.
    Returns list of created chunk file paths.
    """
    try:
        # Read the main input file
        input_text = input_path.read_text(encoding="utf-8")
        data = json.loads(input_text)
        
        if not isinstance(data, list):
            raise ValueError("Input JSON must be an array/list")
            
        total_items = len(data)
        print(f"📊 Total items in input: {total_items}")
        
        if total_items == 0:
            print("⚠️  Input file is empty, no chunks to create")
            return []
            
        # Create chunks
        chunks = chunk_json_data(data, chunk_size)
        chunk_paths = []
        
        # Create chunk files
        input_dir = input_path.parent
        input_stem = input_path.stem  # filename without extension
        
        for i, chunk in enumerate(chunks, 1):
            chunk_filename = f"{input_stem}-{i}.json"
            chunk_path = input_dir / chunk_filename
            
            # Write chunk to file
            chunk_json = json.dumps(chunk, indent=2, ensure_ascii=False)
            chunk_path.write_text(chunk_json, encoding="utf-8")
            chunk_paths.append(chunk_path)
            
            start_item = (i - 1) * chunk_size + 1
            end_item = min(i * chunk_size, total_items)
            print(f"📝 Created {chunk_filename}: items {start_item}-{end_item} ({len(chunk)} items)")
            
        print(f"✅ Created {len(chunks)} chunk files")
        return chunk_paths
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON Decode Error in input file: {e}")
        raise NonRetryableError(f"Invalid JSON in input file: {e}")
    except Exception as e:
        print(f"❌ Error creating input chunks: {e}")
        raise NonRetryableError(f"Failed to create chunks: {e}")


def process_chunks(args, mode_name: str, default_instruction: pathlib.Path, 
                     schema_class: type, order_func, chunk_paths: list[pathlib.Path]) -> None:
    """Process multiple chunk files and generate corresponding outputs."""
    total_chunks = len(chunk_paths)
    successful_chunks = 0
    failed_chunks = []
    
    print(f"\n🔄 Processing {total_chunks} chunks for {mode_name}")
    print("=" * 60)
    
    for i, chunk_path in enumerate(chunk_paths, 1):
        print(f"\n📦 Processing chunk {i}/{total_chunks}: {chunk_path.name}")
        print("-" * 40)
        
        # Create chunk-specific output paths
        output_path = pathlib.Path(args.output) if args.output else DEFAULT_OUTPUT_PATH
        log_path = pathlib.Path(args.log) if args.log else DEFAULT_LOG_PATH
        
        # Modify paths to include chunk number
        output_stem = output_path.stem
        log_stem = log_path.stem
        
        chunk_output_path = output_path.parent / f"{output_stem}-{i}.json"
        chunk_log_path = log_path.parent / f"{log_stem}-{i}.log"
        
        # Ensure directories exist
        ensure_directories(chunk_output_path, chunk_log_path)
        
        # Create modified args for this chunk
        chunk_args = argparse.Namespace(**vars(args))
        chunk_args.input = str(chunk_path)
        chunk_args.output = str(chunk_output_path)
        chunk_args.log = str(chunk_log_path)
        
        try:
            # Process this chunk
            success = execute_single_chunk(
                chunk_args, mode_name, default_instruction, schema_class, order_func, i, total_chunks
            )
            
            if success:
                successful_chunks += 1
                print(f"✅ Chunk {i}/{total_chunks} completed successfully")
            else:
                failed_chunks.append(i)
                print(f"❌ Chunk {i}/{total_chunks} failed")
                
        except KeyboardInterrupt:
            print(f"\n⚠️  Processing interrupted by user at chunk {i}/{total_chunks}")
            break
        except Exception as e:
            failed_chunks.append(i)
            print(f"❌ Unexpected error processing chunk {i}: {e}")
            
    # Summary
    print("\n" + "=" * 60)
    print(f"📊 PROCESSING SUMMARY for {mode_name}")
    print(f"✅ Successful chunks: {successful_chunks}/{total_chunks}")
    
    if failed_chunks:
        print(f"❌ Failed chunks: {len(failed_chunks)} - {failed_chunks}")
        print("🔍 Check individual log files for details")
    else:
        print("🎉 All chunks processed successfully!")


def execute_single_chunk(args, mode_name: str, default_instruction: pathlib.Path, 
                         schema_class: type, order_func, chunk_num: int, total_chunks: int) -> bool:
    """Execute processing for a single chunk."""
    try:
        # Setup paths (already set in args)
        input_path = pathlib.Path(args.input)
        output_path = pathlib.Path(args.output)
        log_path = pathlib.Path(args.log)
        instruction_path = pathlib.Path(args.instruction) if args.instruction else default_instruction
        
        # Get model
        model_id = get_model_id(args.model)
        
        # Read files
        try:
            input_json, md_instructions = read_input_files(input_path, instruction_path)
        except NonRetryableError:
            return False  # Error already printed
        
        max_retries = getattr(args, 'max_retries', DEFAULT_MAX_RETRIES)
        last_error = None
        
        # Main retry loop for this chunk
        for overall_attempt in range(max_retries + 1):
            try:
                if overall_attempt > 0:
                    print(f"🔄 Chunk {chunk_num} retry attempt {overall_attempt + 1}/{max_retries + 1}")
                
                # Call API with retry logic
                raw_output = call_gemini_api_with_retry(
                    model_id, input_path, instruction_path, input_json, md_instructions,
                    max_retries=2  # Fewer API retries since we have overall retries
                )
                
                # Create unique log path for this attempt
                attempt_log_path = log_path.with_suffix(f".attempt{overall_attempt + 1}.log")
                
                # Validate and save
                success, is_retryable = save_and_validate_json(
                    raw_output, attempt_log_path, output_path, schema_class, order_func
                )
                
                if success:
                    return True
                
                elif not is_retryable:
                    print(f"❌ Chunk {chunk_num} failed with non-retryable JSON validation error.")
                    return False
                
                elif overall_attempt < max_retries:
                    delay = calculate_delay(overall_attempt, DEFAULT_BASE_DELAY, DEFAULT_MAX_DELAY, DEFAULT_BACKOFF_FACTOR)
                    print(f"⚠️  Chunk {chunk_num}: Retryable JSON validation error occurred.")
                    print(f"🕒 Waiting {delay:.2f} seconds before retry")
                    time.sleep(delay)
                    last_error = "JSON validation failed"
                else:
                    print(f"❌ Chunk {chunk_num}: All retry attempts exhausted due to JSON validation failures.")
                    last_error = "JSON validation failed"
                    
            except (RetryableError, NonRetryableError) as e:
                if isinstance(e, NonRetryableError):
                    print(f"❌ Chunk {chunk_num} API call failed with non-retryable error: {e}")
                    return False
                    
                last_error = e
                if overall_attempt < max_retries:
                    delay = calculate_delay(overall_attempt, DEFAULT_BASE_DELAY, DEFAULT_MAX_DELAY, DEFAULT_BACKOFF_FACTOR)
                    print(f"⚠️  Chunk {chunk_num}: Retryable API error: {e}")
                    print(f"🕒 Waiting {delay:.2f} seconds before retry")
                    time.sleep(delay)
                else:
                    print(f"❌ All retry attempts exhausted. Last error: {e}")
        
        return False
        
    except Exception as e:
        print(f"❌ Unexpected error in chunk {chunk_num}: {e}")
        return False
        
def clean_json_output(raw: str) -> str:
    """Remove possible markdown fences and surrounding whitespace."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned


def ensure_directories(output_path: pathlib.Path, log_path: pathlib.Path) -> None:
    """Ensure output directories exist."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)


def get_model_id(model_choice: str) -> str:
    """Map model choice to actual model ID."""
    model_map = {
        "flash": "gemini-2.5-flash",
        "pro": "gemini-2.5-pro"
    }
    return model_map[model_choice]


def read_input_files(input_path: pathlib.Path, instruction_path: pathlib.Path) -> tuple[str, str]:
    """Read input JSON and instruction files."""
    try:
        input_json = input_path.read_text(encoding="utf-8")
        md_instructions = instruction_path.read_text(encoding="utf-8")
        return input_json, md_instructions
    except FileNotFoundError as e:
        print(f"❌ Error: File not found - {e}")
        raise NonRetryableError(f"File not found: {e}")


def is_retryable_error(error: Exception) -> bool:
    """Determine if an error is retryable."""
    if isinstance(error, ServerError):
        # Server errors (5xx) are generally retryable
        return True
    elif isinstance(error, ClientError):
        # Most client errors (4xx) are not retryable, but some specific ones might be
        # For example, rate limiting (429) could be retryable
        error_message = str(error).lower()
        if "rate limit" in error_message or "429" in error_message:
            return True
        if "timeout" in error_message or "connection" in error_message:
            return True
        return False
    elif isinstance(error, (ConnectionError, TimeoutError)):
        # Network-related errors are retryable
        return True
    else:
        # Other exceptions are generally not retryable
        return False


def calculate_delay(attempt: int, base_delay: float, max_delay: float, backoff_factor: float) -> float:
    """Calculate delay for exponential backoff with jitter."""
    delay = min(base_delay * (backoff_factor ** attempt), max_delay)
    # Add some jitter to avoid thundering herd
    jitter = delay * 0.1 * random.random() # Use random imported from top
    return delay + jitter


def call_gemini_api_with_retry(model_id: str, input_path: pathlib.Path, instruction_path: pathlib.Path, 
                               input_json: str, md_instructions: str, max_retries: int = DEFAULT_MAX_RETRIES,
                               base_delay: float = DEFAULT_BASE_DELAY, max_delay: float = DEFAULT_MAX_DELAY,
                               backoff_factor: float = DEFAULT_BACKOFF_FACTOR) -> str:
    """Call Gemini API with retry logic and exponential backoff."""
    client = genai.Client()
    
    prompt = PROMPT_TEMPLATE.format(
        input_path=input_path,
        input_json=input_json,
        instruction_path=instruction_path,
        md_instructions=md_instructions
    )
    
    last_error = None
    
    for attempt in range(max_retries + 1):  # +1 because we start from 0
        try:
            print(f"🔄 API Call attempt {attempt + 1}/{max_retries + 1}")
            response = client.models.generate_content(model=model_id, contents=[prompt])
            result = (response.text or "").strip()
            
            if attempt > 0:
                print(f"✅ API call successful after {attempt + 1} attempts")
            
            return result
            
        except Exception as e:
            last_error = e
            
            if not is_retryable_error(e):
                print(f"❌ Non-retryable error: {e}")
                raise NonRetryableError(f"API call failed with non-retryable error: {e}")
            
            if attempt < max_retries:
                delay = calculate_delay(attempt, base_delay, max_delay, backoff_factor)
                print(f"⚠️  Retryable error occurred: {e}")
                print(f"🕒 Waiting {delay:.2f} seconds before retry {attempt + 2}/{max_retries + 1}")
                time.sleep(delay)
            else:
                print(f"❌ All retry attempts exhausted. Last error: {e}")
    
    # If we get here, all retries have been exhausted
    raise RetryableError(f"API call failed after {max_retries + 1} attempts. Last error: {last_error}")


class JSONValidationError(Exception):
    """Exception for JSON validation failures that might be retryable."""
    pass


def save_and_validate_json(raw_output: str, log_path: pathlib.Path, 
                           output_path: pathlib.Path, schema_class: type,
                           order_func) -> tuple[bool, bool]:
    """
    Save raw output and validate JSON according to schema.
    Returns (success, is_retryable) tuple.
    """
    # Save raw response for debugging
    try:
        log_path.write_text(raw_output, encoding="utf-8")
    except Exception as e:
        print(f"⚠️  Warning: Could not save raw output to log file: {e}")

    # Clean JSON fences if present
    cleaned_output = clean_json_output(raw_output)

    # Try JSON parsing
    try:
        parsed = json.loads(cleaned_output)
    except json.JSONDecodeError as e:
        print(f"❌ JSON Decode Error: {e}")
        print(f"🔍 Raw output saved at: {log_path}")
        print(f"📝 Problematic JSON content preview: {cleaned_output[:500]}...")
        
        # Check if this might be a retryable JSON issue
        error_msg = str(e).lower()
        is_retryable = any(keyword in error_msg for keyword in [
            "unexpected", "truncated", "incomplete", "malformed"
        ]) or len(cleaned_output.strip()) < 10  # Very short responses might indicate API issues
        
        return False, is_retryable

    # Validate with Pydantic
    try:
        if not isinstance(parsed, list):
            print(f"❌ Expected JSON array, got {type(parsed).__name__}")
            print(f"🔍 Raw output saved at: {log_path}")
            return False, True  # Unexpected format might be retryable
            
        if len(parsed) == 0:
            print(f"❌ Empty JSON array received")
            print(f"🔍 Raw output saved at: {log_path}")
            return False, True  # Empty responses might indicate API issues
            
        validated_items = [schema_class(**item) for item in parsed]
        
    except ValidationError as e:
        print(f"❌ Schema Validation Error:\n{e}")
        print(f"🔍 Raw output saved at: {log_path}")
        print(f"📝 Parsed JSON structure: {json.dumps(parsed[:2], indent=2) if len(parsed) > 0 else 'Empty list'}")
        
        # Check if validation error might be retryable
        error_msg = str(e).lower()
        is_retryable = any(keyword in error_msg for keyword in [
            "missing", "required field", "none is not an allowed value"
        ]) or len(parsed) < 3  # Very few items might indicate truncated response
        
        return False, is_retryable
        
    except Exception as e:
        print(f"❌ Unexpected validation error: {e}")
        print(f"🔍 Raw output saved at: {log_path}")
        return False, True  # Unexpected errors are potentially retryable

    # Save final JSON with stable ordering
    try:
        validated_json = json.dumps([order_func(item) for item in validated_items], 
                                    indent=2, ensure_ascii=False)
        output_path.write_text(validated_json, encoding="utf-8")
        
        print("\n✅ JSON successfully validated and saved.")
        print(f"📂 JSON saved to: {output_path}")
        print(f"📝 Raw response saved to: {log_path}")
        print(f"📊 Processed {len(validated_items)} items")
        return True, False
        
    except Exception as e:
        print(f"❌ Error saving validated JSON: {e}")
        return False, False  # File system errors are usually not retryable


def setup_paths(args, default_instruction: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    """Setup all required paths for a mode."""
    input_path = pathlib.Path(args.input) if args.input else DEFAULT_INPUT_PATH
    output_path = pathlib.Path(args.output) if args.output else DEFAULT_OUTPUT_PATH
    log_path = pathlib.Path(args.log) if args.log else DEFAULT_LOG_PATH
    instruction_path = pathlib.Path(args.instruction) if args.instruction else default_instruction
    
    ensure_directories(output_path, log_path)
    return input_path, output_path, log_path, instruction_path


def execute_mode_with_full_retry(args, mode_name: str, default_instruction: pathlib.Path, 
                                 schema_class: type, order_func) -> None:
    """Execute a mode with full retry logic including JSON validation retries."""
    print(f"🚀 Running {mode_name}")
    
    try:
        # Setup paths
        input_path, output_path, log_path, instruction_path = setup_paths(args, default_instruction)
        
        # Get model
        model_id = get_model_id(args.model)
        print(f"✅ Using model: {model_id}")
        
        # Read files
        try:
            input_json, md_instructions = read_input_files(input_path, instruction_path)
        except NonRetryableError:
            return  # Error already printed
        
        max_retries = getattr(args, 'max_retries', DEFAULT_MAX_RETRIES)
        last_error = None
        
        # Main retry loop for entire operation
        for overall_attempt in range(max_retries + 1):
            try:
                print(f"\n🔄 Overall attempt {overall_attempt + 1}/{max_retries + 1}")
                
                # Call API with retry logic
                raw_output = call_gemini_api_with_retry(
                    model_id, input_path, instruction_path, input_json, md_instructions,
                    max_retries=2  # Fewer API retries since we have overall retries
                )
                
                # Create unique log path for this attempt to preserve all attempts
                attempt_log_path = log_path.with_suffix(f".attempt{overall_attempt + 1}.log")
                
                # Validate and save
                success, is_retryable = save_and_validate_json(
                    raw_output, attempt_log_path, output_path, schema_class, order_func
                )
                
                if success:
                    if overall_attempt > 0:
                        print(f"✅ {mode_name} succeeded after {overall_attempt + 1} overall attempts!")
                    else:
                        print(f"🎉 {mode_name} completed successfully!")
                    return
                
                elif not is_retryable:
                    print(f"❌ {mode_name} failed with non-retryable JSON validation error.")
                    return
                
                elif overall_attempt < max_retries:
                    delay = calculate_delay(overall_attempt, DEFAULT_BASE_DELAY, DEFAULT_MAX_DELAY, DEFAULT_BACKOFF_FACTOR)
                    print(f"⚠️  Retryable JSON validation error occurred.")
                    print(f"🕒 Waiting {delay:.2f} seconds before overall retry {overall_attempt + 2}/{max_retries + 1}")
                    time.sleep(delay)
                    last_error = "JSON validation failed"
                else:
                    print(f"❌ All retry attempts exhausted due to JSON validation failures.")
                    last_error = "JSON validation failed"
                    
            except (RetryableError, NonRetryableError) as e:
                if isinstance(e, NonRetryableError):
                    print(f"❌ API call failed with non-retryable error: {e}")
                    return
                    
                last_error = e
                if overall_attempt < max_retries:
                    delay = calculate_delay(overall_attempt, DEFAULT_BASE_DELAY, DEFAULT_MAX_DELAY, DEFAULT_BACKOFF_FACTOR)
                    print(f"⚠️  Retryable API error: {e}")
                    print(f"🕒 Waiting {delay:.2f} seconds before overall retry {overall_attempt + 2}/{max_retries + 1}")
                    time.sleep(delay)
                else:
                    print(f"❌ All overall retry attempts exhausted. Last error: {e}")
        
        print(f"❌ {mode_name} failed after all retry attempts. Last error: {last_error}")
            
    except KeyboardInterrupt:
        print(f"\n⚠️  {mode_name} interrupted by user.")
    except Exception as e:
        print(f"❌ Unexpected error in {mode_name}: {e}")
        print(f"🔍 Please check your input files and try again.")


def execute_mode_with_chunking(args, mode_name: str, default_instruction: pathlib.Path, 
                                 schema_class: type, order_func) -> None:
    """Execute a mode with optional chunking support."""
    print(f"🚀 Running {mode_name}")
    
    # Check if chunking is requested or enabled by default
    chunk_size = args.chunk_size
    
    if chunk_size > 0:
        # Chunking mode
        print(f"📦 Chunking enabled: {chunk_size} items per chunk")
        
        # Setup input path
        input_path = pathlib.Path(args.input) if args.input else DEFAULT_INPUT_PATH
        
        try:
            # Create input chunks
            chunk_paths = create_input_chunks(input_path, chunk_size)
            
            if not chunk_paths:
                print("❌ No chunks created, exiting")
                return
            
            # Process all chunks
            process_chunks(args, mode_name, default_instruction, schema_class, order_func, chunk_paths)
            
        except NonRetryableError as e:
            print(f"❌ Failed to create chunks: {e}")
            return
        except KeyboardInterrupt:
            print(f"\n⚠️  {mode_name} interrupted by user during chunking.")
            return
    else:
        # Normal single-file mode (chunk_size is 0)
        print("📄 Processing: Single file mode (chunking disabled)")
        execute_mode_with_full_retry(args, mode_name, default_instruction, schema_class, order_func)


def execute_mode(args, mode_name: str, default_instruction: pathlib.Path, 
                schema_class: type, order_func) -> None:
    """Execute a mode with standardized workflow and error handling."""
    execute_mode_with_chunking(args, mode_name, default_instruction, schema_class, order_func)


# ==== Mode Implementations ====
def tag_auditor_mode(args) -> None:
    """Audit and correct tags using Gemini AI."""
    def order_audit(a: TagAudit):
        data = a.model_dump()
        return {"noteId": data["noteId"], "oldTag": data["oldTag"], "newTag": data["newTag"]}
    
    execute_mode(args, "Tag Auditor Mode 🏷️", DEFAULT_TAG_AUDITOR_INSTRUCTION, TagAudit, order_audit)


def grammar_explain_mode(args) -> None:
    """Generate grammar explanations using Gemini AI."""
    def order_extra(u: ExtraUpdate):
        data = u.model_dump()
        return {"noteId": data["noteId"], "Extra": data["Extra"]}
    
    execute_mode(args, "Grammar Explanation Mode 📝", DEFAULT_GRAMMAR_EXPLAIN_INSTRUCTION, ExtraUpdate, order_extra)


def extra_generator_mode(args) -> None:
    """Generate Extra field using Gemini AI."""
    def order_extra(u: ExtraUpdate):
        data = u.model_dump()
        return {"noteId": data["noteId"], "Extra": data["Extra"]}
    
    execute_mode(args, "Extra Generator Mode ➕", DEFAULT_EXTRA_GENERATOR_INSTRUCTION, ExtraUpdate, order_extra)


def question_tagging_mode(args) -> None:
    """Tag questions using Gemini AI."""
    def order_tag(u: TagUpdate):
        data = u.model_dump()
        return {"noteId": data["noteId"], "newTag": data["newTag"]}
    
    execute_mode(args, "Question Tagging Mode 🔖", DEFAULT_QUESTION_TAGGING_INSTRUCTION, TagUpdate, order_tag)


# ==== Main Function ====
def main():
    parser = argparse.ArgumentParser(
        description="Master Gemini AI Tool - Multiple AI operations in one script with retry logic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available Modes:
  tag-auditor      - Audit and correct tags
  grammar-explain  - Generate grammar explanations
  extra-generator  - Generate Extra field content
  question-tagging - Tag questions automatically

Examples:
  # Chunking enabled by default (25 items per chunk)
  python master_gemini.py --mode tag-auditor --input data.json --instruction inst.md
  
  # Custom chunk size
  python master_gemini.py --mode grammar-explain --input large_data.json --chunk-size 50 --model pro
  
  # Disable chunking (process as a single file)
  python master_gemini.py --mode extra-generator --input data.json --chunk-size 0
        """
    )
    
    # Required mode argument
    parser.add_argument(
        "--mode", 
        required=True,
        choices=["tag-auditor", "grammar-explain", "extra-generator", "question-tagging"],
        help="Select operation mode"
    )
    
    # Common arguments
    parser.add_argument("--input", help="Path to the input file")
    parser.add_argument("--output", help="Path to the output JSON file")
    parser.add_argument("--log", help="Path to the raw log file")
    parser.add_argument("--instruction", help="Path to the markdown instruction file")
    parser.add_argument("--model", choices=["flash", "pro"], default="flash", help="Choose model: flash or pro")
    
    # Retry configuration arguments
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES, 
                        help=f"Maximum number of retry attempts (default: {DEFAULT_MAX_RETRIES})")
    
    # Chunking configuration arguments (now default to DEFAULT_CHUNK_SIZE)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"Set chunk size (items per chunk). Use 0 to disable chunking. (default: {DEFAULT_CHUNK_SIZE})")
    
    args = parser.parse_args()
    
    print(f"🚀 Starting Master Gemini AI Tool")
    print(f"📋 Mode: {args.mode}")
    print(f"🤖 Model: {args.model}")
    print(f"🔄 Max retries: {args.max_retries}")
    if args.chunk_size > 0:
        print(f"📦 Chunking: {args.chunk_size} items per chunk (default auto-chunking active)")
    else:
        print(f"📄 Processing: Single file mode (chunking explicitly disabled)")
    print("-" * 50)

    # Route to appropriate mode
    mode_handlers = {
        "tag-auditor": tag_auditor_mode,
        "grammar-explain": grammar_explain_mode,
        "extra-generator": extra_generator_mode,
        "question-tagging": question_tagging_mode,
    }
    
    handler = mode_handlers.get(args.mode)
    if handler:
        handler(args)
    else:
        print(f"❌ Error: Unknown mode '{args.mode}'")


if __name__ == "__main__":
    main()
