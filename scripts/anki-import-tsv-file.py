import json
import requests
from pathlib import Path

def import_to_anki(tsv_path: Path):
    # Convert to absolute path & fix slashes (Anki requires forward slashes even on Windows)
    abs_path = tsv_path.resolve().as_posix()

    payload = {
        "action": "guiImportFile",
        "version": 6,
        "params": {
            "path": abs_path
        }
    }

    try:
        response = requests.post("http://localhost:8765", json=payload, timeout=5)
        response.raise_for_status()  # raises if HTTP error
        data = response.json()

        if data.get("error"):
            print(f"❌ AnkiConnect error: {data['error']}")
        else:
            print(f"✅ Import triggered for {abs_path}")

    except requests.exceptions.ConnectionError:
        print("⚠️ Could not connect to Anki. Please make sure Anki is running and AnkiConnect is installed.")
    except requests.exceptions.Timeout:
        print("⚠️ Connection to AnkiConnect timed out. Is Anki running?")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    tsv_file = Path("./data/output/merged.tsv")
    if not tsv_file.exists():
        print(f"❌ File not found: {tsv_file}")
    else:
        import_to_anki(tsv_file)
