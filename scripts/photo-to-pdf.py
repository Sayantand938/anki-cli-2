import json
from pathlib import Path
from PIL import Image
from rich.console import Console
import shutil

console = Console()

# ---------- Config ----------
PHOTOS_DIR = Path("./photos")
OUTPUT_DIR = Path("./data/output")
INSTRUCTIONS_DIR = Path("./instructions")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff"}


def combine_images_to_pdf_in_folder(folder_path):
    """Process a single folder and create a PDF from its images."""
    image_files = sorted(
        [p for p in folder_path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS],
        key=lambda p: p.name
    )

    if not image_files:
        console.print(f"⚠️  No images found in {folder_path.name}", style="bold yellow")
        return False

    console.print(f"📸 Found {len(image_files)} images in {folder_path.name}. Converting to PDF...", style="bold cyan")

    try:
        # Ensure output folder exists
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Create output PDF path inside data/output/
        output_file = OUTPUT_DIR / f"{folder_path.name}.pdf"

        # Open all images and ensure they're in RGB mode
        images = [Image.open(img).convert("RGB") for img in image_files]

        # Save PDF
        images[0].save(output_file, save_all=True, append_images=images[1:])
        console.print(f"✅ Created PDF: {output_file}", style="bold green")

        # Create blank JSON if needed
        json_file = OUTPUT_DIR / f"{folder_path.name}.json"
        if not json_file.exists() or json_file.stat().st_size == 0:
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)
            console.print(f"📝 Created blank JSON: {json_file.name}", style="bold cyan")
        else:
            console.print(f"ℹ️ JSON already exists: {json_file.name}", style="bold yellow")

        # Delete original images
        for img_path in image_files:
            img_path.unlink()
            console.print(f"🗑️  Deleted {img_path.name}", style="bold magenta")

        # Delete empty folder
        try:
            folder_path.rmdir()
            console.print(f"🗂️  Deleted empty folder: {folder_path.name}", style="bold magenta")
        except OSError as e:
            console.print(f"⚠️  Could not delete folder {folder_path.name}: {e}", style="yellow")

        return True

    except Exception as e:
        console.print(f"❌ Failed to create PDF for {folder_path.name}: {e}", style="bold red")
        return False


def process_all_photo_folders():
    """Process all subfolders in the photos directory."""
    if not PHOTOS_DIR.exists():
        console.print(f"❌ Folder not found: {PHOTOS_DIR}", style="bold red")
        return

    def find_folders_with_images(path):
        """Recursively find folders that contain images."""
        folders_with_images = []
        for item in path.iterdir():
            if item.is_dir():
                has_images = any(f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS for f in item.iterdir())
                if has_images:
                    folders_with_images.append(item)
                else:
                    folders_with_images.extend(find_folders_with_images(item))
        return folders_with_images

    all_folders = find_folders_with_images(PHOTOS_DIR)
    if not all_folders:
        console.print("⚠️  No folders with images found to process.", style="bold yellow")
        return

    console.print(f"🎯 Found {len(all_folders)} folders to process:", style="bold blue")
    for folder in all_folders:
        console.print(f"   📁 {folder.relative_to(PHOTOS_DIR)}", style="cyan")
    console.print("")

    successful, failed = 0, 0
    for folder in all_folders:
        console.print(f"🔄 Processing: {folder.relative_to(PHOTOS_DIR)}", style="bold white")
        if combine_images_to_pdf_in_folder(folder):
            successful += 1
        else:
            failed += 1
        console.print("")

    # Copy QuizTranscriber.md after processing
    src_file = INSTRUCTIONS_DIR / "QuizTranscriber.md"
    dest_file = OUTPUT_DIR / "QuizTranscriber.md"
    try:
        shutil.copy2(src_file, dest_file)
        console.print(f"📄 Copied QuizTranscriber.md to {dest_file}", style="bold green")
    except Exception as e:
        console.print(f"⚠️ Failed to copy QuizTranscriber.md: {e}", style="bold red")

    console.print("=" * 50, style="bold")
    console.print("📊 Processing Summary:", style="bold white")
    console.print(f"   ✅ Successful: {successful}", style="bold green")
    console.print(f"   ❌ Failed: {failed}", style="bold red")
    console.print(f"   📁 Total folders: {len(all_folders)}", style="bold cyan")


if __name__ == "__main__":
    process_all_photo_folders()
