import json
from pathlib import Path
from rich.console import Console

console = Console()

# ---------- Config ----------
BASE_DIR = Path("./data")
CHUNK_SIZE = 25  # Adjust as needed

def split_json_file(folder: Path, filename: str, prefix: str):
    """Split a large JSON file into chunked part files."""
    file_path = folder / filename
    if not file_path.exists():
        return False

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        console.print(f"❌ Failed to read {file_path}: {e}", style="bold red")
        return True  # Skip further action but don't merge

    if not isinstance(data, list) or not data:
        console.print(f"⚠️ {filename} is empty or not a list", style="bold yellow")
        return True

    chunks = [data[i:i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]
    for idx, chunk in enumerate(chunks, start=1):
        output_file = folder / f"{prefix}-{idx}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)
        console.print(f"✅ Created {output_file.name} with {len(chunk)} entries", style="bold green")

    file_path.unlink()
    console.print(f"🗑️ Deleted original {filename}", style="bold yellow")
    return True

def merge_json_files(folder: Path, prefix: str, filename: str):
    """Merge part files back into a single JSON file."""
    part_files = sorted(folder.glob(f"{prefix}-*.json"),
                        key=lambda p: int(p.stem.split("-")[-1]))
    if not part_files:
        return False

    merged_data = []
    for pf in part_files:
        try:
            with open(pf, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged_data.extend(data)
            console.print(f"✅ Merged {pf.name} ({len(data)} entries)", style="bold green")
        except Exception as e:
            console.print(f"❌ Failed to read {pf.name}: {e}", style="bold red")

    output_file = folder / filename
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(merged_data, f, ensure_ascii=False, indent=2)

    console.print(f"📦 Final merged file → {output_file} ({len(merged_data)} total entries)", style="bold cyan")
    return True

def process_folder(folder_name: str):
    folder = BASE_DIR / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    if folder_name == "input":
        filename = "input.json"
        prefix = "input"
    else:
        filename = "output.json"
        prefix = "output"

    file_exists = (folder / filename).exists()
    parts_exist = any(folder.glob(f"{prefix}-*.json"))

    if file_exists and not parts_exist:
        console.print(f"📂 Found {filename} in '{folder_name}' — splitting...", style="bold cyan")
        split_json_file(folder, filename, prefix)
    elif parts_exist and not file_exists:
        console.print(f"📂 Found {prefix}-*.json parts in '{folder_name}' — merging...", style="bold cyan")
        merge_json_files(folder, prefix, filename)
    else:
        console.print(f"ℹ️ No action needed for '{folder_name}'", style="bold blue")

def main():
    process_folder("input")
    process_folder("output")

if __name__ == "__main__":
    main()