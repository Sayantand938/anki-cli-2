import json
import requests
from pathlib import Path
from typing import Optional, Literal
from pydantic import BaseModel, ValidationError
from rich.console import Console
import shutil # Import shutil for moving files

# ---------- Config ----------
DATA_DIR = Path("./data")
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
ANKI_URL = "http://localhost:8765"
SUBJECTS = {"ENG", "BENG", "MATH", "GK", "GI"}

console = Console()

# ---------- Pydantic Schemas ----------
class QuestionTagging(BaseModel):
    noteId: int
    newTag: str

class TagAuditor(BaseModel):
    noteId: int
    oldTag: str
    newTag: str

class ExtraGenerator(BaseModel):
    noteId: int
    Extra: str

# Grammar Explain is same structure as Extra
GrammarExplain = ExtraGenerator

# ---------- AnkiConnect Helpers ----------
def anki_request(action, params=None, fetch_result=False):
    """
    Sends a request to the AnkiConnect API.
    If fetch_result is True, returns the 'result' field of the response on success,
    otherwise returns True on successful execution (no 'error' field in response).
    Returns False on any error.
    """
    try:
        res = requests.post(ANKI_URL, json={
            "action": action,
            "version": 6,
            "params": params or {}
        })
        res.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
        data = res.json()
        
        if data.get("error"):
            console.print(f"❌ AnkiConnect reported an error for action '{action}': {data['error']}", style="bold red")
            return False
        
        if fetch_result:
            return data.get("result") # Return the actual result data
        else:
            return True # No error, and no specific result data needed
    except requests.exceptions.ConnectionError:
        console.print(f"❌ AnkiConnect error: Could not connect to Anki. Is Anki running and AnkiConnect installed?", style="bold red")
        return False
    except requests.exceptions.RequestException as e:
        console.print(f"❌ AnkiConnect request failed for action '{action}': {e}", style="bold red")
        return False
    except Exception as e:
        console.print(f"❌ Unexpected error during AnkiConnect request for action '{action}': {e}", style="bold red")
        return False

def get_note_tags(note_id):
    """
    Fetches the tags for a given note ID.
    Returns a set of tags or an empty set if not found or on error.
    """
    info = anki_request("notesInfo", {"notes": [note_id]}, fetch_result=True)
    
    if info is False or info is None:
        return set()

    if isinstance(info, list) and info:
        return set(info[0].get("tags", []))
    return set()

def process_question_tagging(entry: QuestionTagging):
    """
    Processes a QuestionTagging entry to add or replace a subject tag.
    """
    subject = entry.newTag.split("::")[0]
    if subject not in SUBJECTS:
        console.print(f"⚠️ Invalid subject '{subject}' in newTag for note {entry.noteId}. Must be one of {SUBJECTS}", style="bold yellow")
        return False

    current_tags = get_note_tags(entry.noteId)
    
    if any(tag.startswith(subject) for tag in current_tags):
        console.print(f"🔄 Replacing existing subject tag with '{entry.newTag}' for note {entry.noteId}", style="bold yellow")
        old_subject_tag = next((tag for tag in current_tags if tag.startswith(subject)), None)
        if old_subject_tag:
            remove_success = anki_request("removeTags", {
                "notes": [entry.noteId],
                "tags": old_subject_tag
            })
            if not remove_success:
                return False
            return anki_request("addTags", {
                "notes": [entry.noteId],
                "tags": entry.newTag
            })
        return False
    else:
        console.print(f"➕ Adding tag '{entry.newTag}' to note {entry.noteId}", style="bold green")
        return anki_request("addTags", {
            "notes": [entry.noteId],
            "tags": entry.newTag
        })

def process_tag_auditor(entry: TagAuditor):
    """
    Processes a TagAuditor entry to replace one tag with another.
    """
    console.print(f"🔍 Replacing tag '{entry.oldTag}' with '{entry.newTag}' for note {entry.noteId}", style="bold cyan")
    return anki_request("replaceTags", {
        "notes": [entry.noteId],
        "tag_to_replace": entry.oldTag,
        "replace_with_tag": entry.newTag
    })

def process_extra(entry: ExtraGenerator, mode: Literal["grammar-explain", "extra-generator"]):
    """
    Processes an ExtraGenerator (or GrammarExplain) entry to update the 'Extra' field.
    """
    console.print(f"✏️ Updating Extra field for note {entry.noteId} ({mode})", style="bold green")
    params = {
        "note": {
            "id": entry.noteId,
            "fields": {"Extra": entry.Extra}
        }
    }
    return anki_request("updateNoteFields", params)

# ---------- File Processing ----------
def chunk_and_delete_file(file_path: Path, output_dir: Path, chunk_size: int = 100):
    """
    Chunks a large JSON file into smaller files and deletes the original.
    """
    try:
        with file_path.open('r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        console.print(f"❌ Error reading {file_path}: {e}", style="bold red")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    chunks = [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]
    if not chunks:
        console.print(f"⚠️ No data to chunk in {file_path}", style="bold yellow")
        return
        
    for i, chunk in enumerate(chunks):
        chunk_file_path = output_dir / f"{file_path.stem}-chunk-{i+1}.json"
        try:
            with chunk_file_path.open('w', encoding='utf-8') as f:
                json.dump(chunk, f, indent=4)
            console.print(f"Created chunk: {chunk_file_path}", style="green")
        except Exception as e:
            console.print(f"❌ Error creating chunk {chunk_file_path}: {e}", style="bold red")
            return # Abort if a chunk fails to save

    # Delete the original file after all chunks are created
    try:
        if file_path.exists():
            file_path.unlink()
            console.print(f"🗑️ Original file deleted: {file_path}", style="bold magenta")
    except OSError as e:
        console.print(f"❌ Error deleting original file {file_path}: {e}", style="bold red")

def detect_mode(entries: list) -> Optional[str]:
    """
    Detects the processing mode based on the keys present in the entries.
    """
    if not entries:
        return None

    first_entry = entries[0]
    
    if "newTag" in first_entry and "oldTag" not in first_entry and "Extra" not in first_entry:
        if all("noteId" in e and "newTag" in e and "oldTag" not in e and "Extra" not in e for e in entries):
            return "question-tagging"
    elif "newTag" in first_entry and "oldTag" in first_entry and "Extra" not in first_entry:
        if all("noteId" in e and "newTag" in e and "oldTag" in e and "Extra" not in e for e in entries):
            return "tag-auditor"
    elif "Extra" in first_entry and "newTag" not in first_entry and "oldTag" not in first_entry:
        if all("noteId" in e and "Extra" in e and "newTag" not in e and "oldTag" not in e for e in entries):
            return "extra-or-grammar"
    
    return None

def process_files():
    """
    Discovers and processes all output JSON files, updating Anki notes.
    Deletes both the output and corresponding input files upon successful processing.
    """
    json_files = sorted(OUTPUT_DIR.glob("*.json"))
    if not json_files:
        console.print("⚠️ No JSON files found in ./data/output", style="bold yellow")
        return

    for file in json_files:
        console.print(f"\n📂 Processing {file.name}", style="bold cyan")
        all_success = True

        try:
            entries = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(entries, list) or not entries:
                console.print(f"❌ Invalid file format or empty file: {file.name}", style="bold red")
                all_success = False
                continue

            mode = detect_mode(entries)
            if mode is None:
                console.print(f"⚠️ Could not detect a consistent mode for {file.name}. Skipping file.", style="bold yellow")
                all_success = False
                continue

            for entry in entries:
                success = False
                try:
                    if mode == "question-tagging":
                        obj = QuestionTagging(**entry)
                        success = process_question_tagging(obj)
                    elif mode == "tag-auditor":
                        obj = TagAuditor(**entry)
                        success = process_tag_auditor(obj)
                    elif mode == "extra-or-grammar":
                        obj = ExtraGenerator(**entry)
                        success = process_extra(obj, mode="extra-generator")
                    else:
                        console.print(f"⚠️ Unknown mode '{mode}' for entry {entry}. Skipping.", style="bold yellow")
                        success = False

                    if not success:
                        all_success = False

                except ValidationError as e:
                    console.print(f"❌ Schema validation failed for entry {entry}: {e}", style="bold red")
                    all_success = False
                except Exception as e:
                    console.print(f"❌ Error processing entry {entry}: {e}", style="bold red")
                    all_success = False

            if all_success:
                # Assuming the input chunk file has the same name as the output chunk file
                input_file_path = INPUT_DIR / file.name

                try:
                    if input_file_path.exists():
                        input_file_path.unlink()
                        console.print(f"🗑️ Deleted corresponding input chunk file: {input_file_path.name}", style="bold magenta")
                except OSError as e:
                    console.print(f"❌ Error deleting input file {input_file_path.name}: {e}", style="bold red")

                # Delete the output chunk file
                try:
                    file.unlink()
                    console.print(f"🗑️ Deleted {file.name} after successful updates", style="bold magenta")
                except OSError as e:
                    console.print(f"❌ Error deleting output file {file.name}: {e}", style="bold red")
            else:
                console.print(f"⏸️ Kept {file.name} for retry due to previous errors", style="bold red")

        except json.JSONDecodeError:
            console.print(f"❌ Error decoding JSON from {file.name}. File might be corrupted.", style="bold red")
            console.print(f"⏸️ Kept {file.name} for manual inspection", style="bold red")
        except Exception as e:
            console.print(f"❌ Unexpected error while reading/processing {file.name}: {e}", style="bold red")
            console.print(f"⏸️ Kept {file.name} for manual inspection", style="bold red")

# ---------- Entry ----------
if __name__ == "__main__":
    # First, handle chunking any large input files
    large_input_files = INPUT_DIR.glob("*.json")
    for large_file in large_input_files:
        chunk_and_delete_file(large_file, OUTPUT_DIR)
        
    # Then, process the chunk files in the output directory
    process_files()