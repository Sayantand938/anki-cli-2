import json
from pathlib import Path
from rich.console import Console
from rich.table import Table

def count_json_entries(json_file: Path) -> int:
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return len(data) if isinstance(data, list) else 0
    except Exception as e:
        print(f"❌ Error reading {json_file.name}: {e}")
        return 0

if __name__ == "__main__":
    data_dir = Path("./data/output")
    console = Console()

    if not data_dir.exists():
        console.print(f"[red]❌ Folder not found: {data_dir}[/red]")
    else:
        json_files = list(data_dir.glob("*.json"))

        if not json_files:
            console.print(f"[yellow]⚠️ No JSON files found in {data_dir}[/yellow]")
        else:
            # sort by creation time (old → new)
            json_files.sort(key=lambda f: f.stat().st_ctime)

            table = Table(title="JSON File Summary (Old → New)")
            table.add_column("File Name", style="cyan", no_wrap=True)
            table.add_column("Total Entries", style="green")

            for json_file in json_files:
                total_entries = count_json_entries(json_file)
                table.add_row(json_file.name, str(total_entries))

            console.print(table)
