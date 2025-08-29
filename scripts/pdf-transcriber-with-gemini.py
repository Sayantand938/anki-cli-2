import argparse
import json
import pathlib
import re
from typing import List
from pydantic import BaseModel, ValidationError
from google import genai
from google.genai import types

# ==== Define Schema ====
class Question(BaseModel):
    SL: int
    Question: str
    OP1: str
    OP2: str
    OP3: str
    OP4: str
    Answer: str
    Tags: List[str]


def main():
    parser = argparse.ArgumentParser(description="Transcribe PDF quiz into JSON using Gemini")
    parser.add_argument("--input", required=True, help="Path to the input PDF file")
    parser.add_argument("--instruction", required=True, help="Path to the markdown instruction file")
    parser.add_argument("--model", choices=["flash", "pro"], default="flash", help="Choose model: flash or pro")
    args = parser.parse_args()

    pdf_path = pathlib.Path(args.input)
    md_path = pathlib.Path(args.instruction)

    # Map choice → actual model ID
    model_map = {
        "flash": "gemini-2.5-flash",
        "pro": "gemini-2.5-pro"
    }
    model_id = model_map[args.model]

    print(f"✅ Using model: {model_id}")

    # Read markdown instructions
    md_instructions = md_path.read_text(encoding="utf-8")

    # Init Gemini client
    client = genai.Client()

    # Always use inline PDF bytes (your case: small <10MB)
    pdf_part = types.Part.from_bytes(
        data=pdf_path.read_bytes(),
        mime_type="application/pdf"
    )
    print(f"📄 Using inline PDF (size={pdf_path.stat().st_size/1024/1024:.2f} MB)")

    # ==== Call Gemini ====
    prompt = f"""
You are given a PDF and markdown instructions.  
Apply the instructions to the JSON and return the modified JSON.  

⚠️ Rules:  
- Respond with JSON only  
- Do not include explanations, comments, or text outside JSON  
Instructions:
{md_instructions}
"""

    response = client.models.generate_content(
        model=model_id,
        contents=[pdf_part, prompt]
    )

    raw_output = (response.text or "").strip()

    # Save raw response for debugging
    out_dir = pdf_path.parent
    raw_log_path = out_dir / f"{pdf_path.stem}_raw.log"
    raw_log_path.write_text(raw_output, encoding="utf-8")

    # ==== Clean JSON fences if present ====
    cleaned_output = re.sub(r"^```(?:json)?\s*", "", raw_output)
    cleaned_output = re.sub(r"\s*```$", "", cleaned_output)

    # ==== Try JSON parsing ====
    try:
        parsed = json.loads(cleaned_output)
    except json.JSONDecodeError as e:
        print(f"❌ JSON Decode Error: {e}")
        print(f"🔎 Raw output saved at: {raw_log_path}")
        return

    # ==== Validate with Pydantic ====
    try:
        questions = [Question(**item) for item in parsed]
    except ValidationError as e:
        print(f"❌ Schema Validation Error:\n{e}")
        print(f"🔎 Raw output saved at: {raw_log_path}")
        return

    # Stable key ordering
    def ordered(q: Question):
        data = q.model_dump()
        return {
            "SL": data["SL"],
            "Question": data["Question"],
            "OP1": data["OP1"],
            "OP2": data["OP2"],
            "OP3": data["OP3"],
            "OP4": data["OP4"],
            "Answer": data["Answer"],
            "Tags": data["Tags"],
        }

    validated_json = json.dumps([ordered(q) for q in questions], indent=2, ensure_ascii=False)

    # Save final JSON
    out_path = out_dir / f"{pdf_path.stem}.json"
    out_path.write_text(validated_json, encoding="utf-8")

    print("\n✅ JSON successfully validated and saved.")
    print(f"📂 JSON saved to: {out_path}")
    print(f"📝 Raw response saved to: {raw_log_path}")


if __name__ == "__main__":
    main()
