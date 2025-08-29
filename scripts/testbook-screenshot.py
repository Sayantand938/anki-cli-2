import subprocess
import tempfile
import os
import sys
import time

# Path to your AutoHotkey v2 executable
AHK_PATH = r"C:\Program Files\AutoHotkey\v2\AutoHotkey.exe"

def take_screenshots(count: int):
    """
    Takes 'count' screenshots using AHK.
    Each cycle: PrintScreen → wait 2s → mouse click → wait 2s.
    """
    print(f"Starting in 5 seconds... get ready!")
    time.sleep(5)  # initial delay before AHK starts

    ahk_script = f"""
#Requires AutoHotkey v2.0
CoordMode "Mouse", "Screen"

Loop {count} {{
    Send "{{PrintScreen}}"
    Sleep 2000
    Click 2481, 1398, "Left"
    Sleep 2000
}}
"""

    # Write the AHK script to a temporary file
    with tempfile.NamedTemporaryFile(suffix=".ahk", delete=False, mode="w", encoding="utf-8") as f:
        f.write(ahk_script)
        ahk_file = f.name

    try:
        # Run the AHK script
        subprocess.run([AHK_PATH, ahk_file], check=True)
    finally:
        # Clean up the temporary file
        os.remove(ahk_file)

if __name__ == "__main__":
    # Allow usage like: python app.py 30
    if len(sys.argv) > 1:
        try:
            n = int(sys.argv[1])
        except ValueError:
            print("Usage: python app.py <number_of_screenshots>")
            sys.exit(1)
    else:
        n = 10  # default
    
    take_screenshots(n)
