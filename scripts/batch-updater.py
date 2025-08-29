import json
import requests
from pathlib import Path
from typing import Optional, List, Literal, Union
from pydantic import BaseModel, ValidationError
from rich.console import Console

# ---------- Config ----------
DATA_DIR = Path("./data/output")
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
    # Use fetch_result=True to get the actual result data for notesInfo
    info = anki_request("notesInfo", {"notes": [note_id]}, fetch_result=True)
    
    if info is False or info is None: # anki_request returned False (error) or None (no result data found for some reason)
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
    
    # Check if the primary subject tag (e.g., 'ENG') already exists
    if any(tag.startswith(subject) for tag in current_tags):
        console.print(f"🔄 Replacing existing subject tag with '{entry.newTag}' for note {entry.noteId}", style="bold yellow")
        # Find the specific old subject tag to replace (e.g., 'ENG' or 'ENG::OldSub')
        old_subject_tag = next((tag for tag in current_tags if tag.startswith(subject)), None)
        if old_subject_tag:
             # Remove the old tag first to ensure a clean replacement
            remove_success = anki_request("removeTags", {
                "notes": [entry.noteId],
                "tags": old_subject_tag
            })
            if not remove_success:
                return False
            # Then add the new specific tag
            return anki_request("addTags", {
                "notes": [entry.noteId],
                "tags": entry.newTag
            })
        return False # Should not happen if any tag starts with subject
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
    # AnkiConnect's replaceTags correctly handles cases where oldTag might not exist,
    # and simply adds newTag if it wasn't there.
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
    # updateNoteFields returns null on success, so we rely on anki_request's boolean return
    return anki_request("updateNoteFields", params)

# ---------- File Processing ----------
def detect_mode(entries: list) -> Optional[str]:
    """
    Detects the processing mode based on the keys present in the entries.
    """
    if not entries:
        return None

    # Check the first entry to infer the mode
    first_entry = entries[0]
    
    # Question Tagging: has 'newTag' but not 'oldTag'
    if "newTag" in first_entry and "oldTag" not in first_entry and "Extra" not in first_entry:
        if all("noteId" in e and "newTag" in e and "oldTag" not in e and "Extra" not in e for e in entries):
            return "question-tagging"
    # Tag Auditor: has both 'newTag' and 'oldTag'
    elif "newTag" in first_entry and "oldTag" in first_entry and "Extra" not in first_entry:
        if all("noteId" in e and "newTag" in e and "oldTag" in e and "Extra" not in e for e in entries):
            return "tag-auditor"
    # Extra Generator / Grammar Explain: has 'Extra'
    elif "Extra" in first_entry and "newTag" not in first_entry and "oldTag" not in first_entry:
        if all("noteId" in e and "Extra" in e and "newTag" not in e and "oldTag" not in e for e in entries):
            return "extra-or-grammar"
    
    return None

def process_files():
    """
    Discovers and processes all output JSON files, updating Anki notes.
    """
    json_files = sorted(DATA_DIR.glob("output-*.json"))
    if not json_files:
        console.print("⚠️ No output-*.json files found in ./data/output", style="bold yellow")
        return

    for file in json_files:
        console.print(f"\n📂 Processing {file.name}", style="bold cyan")
        all_success = True # Reset success flag for each file

        try:
            entries = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(entries, list) or not entries:
                console.print(f"❌ Invalid file format or empty file: {file.name}", style="bold red")
                all_success = False # Mark as failure for this file
                continue

            mode = detect_mode(entries)
            if mode is None:
                console.print(f"⚠️ Could not detect a consistent mode for {file.name}. Skipping file.", style="bold yellow")
                all_success = False # Mark as failure for this file
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
                        obj = ExtraGenerator(**entry) # GrammarExplain has same structure
                        success = process_extra(obj, mode="extra-generator") # Using "extra-generator" as the literal
                    else:
                        console.print(f"⚠️ Unknown mode '{mode}' for entry {entry}. Skipping.", style="bold yellow")
                        success = False

                    if not success:
                        all_success = False # If any single entry fails, the whole file is marked for retry

                except ValidationError as e:
                    console.print(f"❌ Schema validation failed for entry {entry}: {e}", style="bold red")
                    all_success = False # Mark as failure for this file
                except Exception as e:
                    console.print(f"❌ Error processing entry {entry}: {e}", style="bold red")
                    all_success = False # Mark as failure for this file

            if all_success:
                file.unlink()
                console.print(f"🗑️ Deleted {file.name} after successful updates", style="bold magenta")
            else:
                console.print(f"⏸️ Kept {file.name} for retry due to previous errors", style="bold red")

        except json.JSONDecodeError:
            console.print(f"❌ Error decoding JSON from {file.name}. File might be corrupted.", style="bold red")
            # If JSON is invalid, it's a critical error for this file, so it's kept.
            console.print(f"⏸️ Kept {file.name} for manual inspection", style="bold red")
        except Exception as e:
            console.print(f"❌ Unexpected error while reading/processing {file.name}: {e}", style="bold red")
            console.print(f"⏸️ Kept {file.name} for manual inspection", style="bold red")

# ---------- Entry ----------
if __name__ == "__main__":
    process_files()