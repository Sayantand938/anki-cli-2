import requests
from rich.console import Console

# ---------- Config ----------
ANKI_URL = "http://localhost:8765"
DECK_NAME = "_Custom Study Session"
SUBJECTS = {"ENG", "BENG", "MATH", "GI", "GK"}
console = Console()

# ---------- Helpers ----------
def anki_request(action, params=None):
    try:
        res = requests.post(ANKI_URL, json={
            "action": action,
            "version": 6,
            "params": params or {}
        })
        res.raise_for_status()
        data = res.json()
        if data.get("error"):
            raise Exception(data["error"])
        return data.get("result")
    except Exception as e:
        console.print(f"❌ AnkiConnect error: {e}", style="bold red")
        return None

# ---------- Main ----------
def replace_subject_tags(deck_name):
    for subject in SUBJECTS:
        tag_prefix = f"{subject}::"
        # Find notes in this deck with tags starting with "SUBJECT::"
        notes = anki_request("findNotes", {
            "query": f'deck:"{deck_name}" tag:"{tag_prefix}*"'
        })
        if not notes:
            continue

        # Get note details
        notes_info = anki_request("notesInfo", {"notes": notes})
        if not notes_info:
            continue

        for note in notes_info:
            note_id = note["noteId"]
            tags = set(note.get("tags", []))

            # Identify bad tags for this subject
            bad_tags = {t for t in tags if t.startswith(tag_prefix)}

            if not bad_tags:
                continue

            # Remove bad tags
            for bad_tag in bad_tags:
                anki_request("removeTags", {
                    "notes": [note_id],
                    "tags": bad_tag
                })
                console.print(f"🗑️ Removed '{bad_tag}' from note {note_id}", style="bold yellow")

            # Add subject tag if not already present
            if subject not in tags:
                anki_request("addTags", {
                    "notes": [note_id],
                    "tags": subject
                })
                console.print(f"➕ Added '{subject}' to note {note_id}", style="bold green")
            else:
                console.print(f"✅ '{subject}' already present in note {note_id}", style="dim")

    console.print("🏁 Strict subject tag cleanup with dedupe complete", style="bold magenta")

if __name__ == "__main__":
    replace_subject_tags(DECK_NAME)