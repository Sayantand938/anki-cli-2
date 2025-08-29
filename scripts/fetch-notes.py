import argparse
import json
import requests
from pathlib import Path
from rich.console import Console

# Configs
BASE_DIR = Path(__file__).parent.parent # points to project root
DATA_DIR = BASE_DIR / 'data' / 'input'  # save fetched JSON here
INPUT_JSON_FILENAME = 'input.json'
DECK_NAME = '_Custom Study Session'

# Rich console setup
console = Console()

# Logging helpers
def log_success(message):
  console.print(f"✅ {message}")

def log_warn(message):
  console.print(f"⚠️ {message}", style="bold yellow")

def handle_error(error):
  console.print(f"❌ {str(error)}")

# AnkiConnect helpers
def anki_request(action, params=None):
  try:
    response = requests.post('http://localhost:8765', json={
      'action': action,
      'version': 6,
      'params': params or {}
    })
    response.raise_for_status()
    result = response.json()
    if 'error' in result and result['error']:
      raise Exception(result['error'])
    return result['result']
  except Exception as e:
    handle_error(e)
    return []

# Fetch all note IDs from the deck
def fetch_note_ids(deck_name):
  return anki_request('findNotes', {'query': f'deck:"{deck_name}"'})

# Fetch detailed note info
def fetch_note_details(note_ids):
  return anki_request('notesInfo', {'notes': note_ids})

# Ensure output path exists
def get_output_file_path():
  DATA_DIR.mkdir(parents=True, exist_ok=True)
  return DATA_DIR / INPUT_JSON_FILENAME

# Transform raw Anki notes into structured notes
def process_notes(notes):
  processed = []
  for note in notes:
    fields = note.get('fields', {})
    answer_index = fields.get('Answer', {}).get('value')
    answer_key = f'OP{answer_index}'
    correct_answer = fields.get(answer_key, {}).get('value', f"Invalid Answer Index: '{answer_index}'")

    processed.append({
      'noteId': note.get('noteId'),
      'SL': fields.get('SL', {}).get('value', ''),
      'Question': fields.get('Question', {}).get('value', ''),
      'OP1': fields.get('OP1', {}).get('value', ''),
      'OP2': fields.get('OP2', {}).get('value', ''),
      'OP3': fields.get('OP3', {}).get('value', ''),
      'OP4': fields.get('OP4', {}).get('value', ''),
      'Answer': correct_answer,
      'Extra': fields.get('Extra', {}).get('value', ''),
      'Video': fields.get('Video', {}).get('value', ''),
      'Tags': note.get('tags', [])
    })
  return processed

# Main logic
def run_fetch_notes(deck):
  note_ids = fetch_note_ids(deck)
  if not note_ids:
    log_warn(f'No notes found in deck "{deck}".')
    return

  log_success(f'Found {len(note_ids)} note(s) in deck "{deck}".')

  notes_info = fetch_note_details(note_ids)
  processed_notes = process_notes(notes_info)
  log_success('Note details processed successfully.')

  output_path = get_output_file_path()
  with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(processed_notes, f, ensure_ascii=False, indent=2)

  log_success(f'Notes exported to → "{output_path}"')

# CLI setup
def main():
  parser = argparse.ArgumentParser(description=f'Fetches and processes notes from Anki, saving them to {INPUT_JSON_FILENAME}.')
  parser.add_argument('-d', '--deck', default=DECK_NAME, help='Name of the Anki deck to fetch notes from')
  args = parser.parse_args()

  try:
    run_fetch_notes(args.deck)
  except Exception as e:
    handle_error(e)

if __name__ == '__main__':
  main()