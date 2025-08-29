import json
import shutil
from pathlib import Path
import os

def sanitize_text(value: str) -> str:
    """Clean and normalize text for TSV output."""
    if not value:
        return ""
    # collapse double <br> into single
    value = value.replace("<br><br>", "<br>")
    # replace <image content> with placeholder
    value = value.replace("<image content>", '<img src="400x200.png" alt="image">')
    # remove tabs and newlines
    return value.replace("\n", " ").replace("\t", " ")

def json_to_tsv(json_file, tsv_file):
    # Load JSON data
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    json_tag = json_file.stem  # use filename (without extension) as default tag

    with open(tsv_file, "w", encoding="utf-8") as f:
        # write the 3 header lines (Anki import format)
        f.write("#separator:tab\n")
        f.write("#html:true\n")
        f.write("#tags column:10\n")

        # write the data rows
        for item in data:
            if isinstance(item.get("Tags"), list) and item["Tags"]:
                tags = " ".join(t.strip() for t in item["Tags"])
            else:
                tags = json_tag  # fallback to JSON filename

            row = [
                str(item.get("SL", "")),  # SL from JSON
                sanitize_text(item.get("Question", "")),
                sanitize_text(item.get("OP1", "")),
                sanitize_text(item.get("OP2", "")),
                sanitize_text(item.get("OP3", "")),
                sanitize_text(item.get("OP4", "")),
                sanitize_text(item.get("Answer", "")),
                sanitize_text(item.get("Extra", "")),
                sanitize_text(item.get("Video", "")),
                tags
            ]
            f.write("\t".join(row) + "\n")

def merge_tsv_files(tsv_files, merged_file):
    # sort by creation time (old → new)
    tsv_files_sorted = sorted(tsv_files, key=lambda f: f.stat().st_ctime)

    with open(merged_file, "w", encoding="utf-8") as outfile:
        # write header once
        outfile.write("#separator:tab\n")
        outfile.write("#html:true\n")
        outfile.write("#tags column:10\n")

        for tsv in tsv_files_sorted:
            with open(tsv, "r", encoding="utf-8") as infile:
                lines = infile.readlines()
                # skip first 3 header lines
                data_lines = lines[3:] if len(lines) > 3 else []
                outfile.writelines(data_lines)

if __name__ == "__main__":
    data_dir = Path("./data/output")
    backup_dir = Path("./data/backup")

    if not data_dir.exists():
        print(f"❌ Folder not found: {data_dir}")
    else:
        json_files = list(data_dir.glob("*.json"))

        if not json_files:
            print(f"⚠️ No JSON files found in {data_dir}")
        else:
            # ensure backup dir exists and is clean
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True)

            tsv_files = []

            for json_file in json_files:
                tsv_file = json_file.with_suffix(".tsv")
                try:
                    # copy JSON to backup before processing
                    shutil.copy2(json_file, backup_dir / json_file.name)
                    print(f"📂 Backed up: {json_file.name}")

                    # convert JSON → TSV
                    json_to_tsv(json_file, tsv_file)
                    print(f"✅ Converted: {json_file.name} → {tsv_file.name}")

                    tsv_files.append(tsv_file)

                    # delete original JSON only after successful conversion
                    json_file.unlink()
                    print(f"🗑️ Deleted: {json_file.name}")

                except Exception as e:
                    print(f"❌ Failed to convert {json_file.name}: {e}")

            # merge all TSV files (by creation time)
            if tsv_files:
                merged_file = data_dir / "merged.tsv"
                merge_tsv_files(tsv_files, merged_file)
                print(f"📝 Merged {len(tsv_files)} TSV files → {merged_file.name}")
