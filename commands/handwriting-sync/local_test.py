#!/usr/bin/env python3
"""
Local test script for handwriting-sync.

This script performs a dry run of the handwriting sync process, scanning
a GitHub repository for Logseq journal files with linked images and
optionally processing them with Gemini Vision OCR.

Results are saved to a local subfolder instead of GCS for testing.

Usage:
    # Set environment variables first (or use .env file)
    export GITHUB_REPO=owner/repo
    export GITHUB_TOKEN=ghp_xxx
    export GCP_PROJECT=your-project-id

    # List all journals and their images (dry run)
    python local_test.py --dry-run

    # Process a specific date
    python local_test.py --date 2024-01-15

    # Process recent journals (last 7 days)
    python local_test.py --after 2024-01-08 --limit 10

    # Actually run OCR and save results locally
    python local_test.py --process --limit 5
"""

import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests

# Try to load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "Pacific/Auckland"))
OUTPUT_DIR = Path("local_output")


def get_github_file(
    repo: str,
    path: str,
    token: str,
    branch: str = "main"
) -> tuple[Optional[str], Optional[str]]:
    """Get file content from GitHub."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    params = {"ref": branch}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code == 404:
            return None, None
        response.raise_for_status()

        data = response.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]

    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] Failed to get file {path}: {e}")
        return None, None


def get_github_binary_file(
    repo: str,
    path: str,
    token: str,
    branch: str = "main"
) -> Optional[bytes]:
    """Get binary file content from GitHub (for images)."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    params = {"ref": branch}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if response.status_code == 404:
            return None
        response.raise_for_status()

        data = response.json()
        return base64.b64decode(data["content"])

    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] Failed to get binary file {path}: {e}")
        return None


def list_github_directory(
    repo: str,
    path: str,
    token: str,
    branch: str = "main"
) -> list[dict]:
    """List files in a GitHub directory."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    params = {"ref": branch}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] Failed to list directory {path}: {e}")
        return []


def extract_image_links(markdown_content: str) -> list[str]:
    """Extract image links from markdown content."""
    images = []

    # Standard markdown: ![alt](path)
    md_pattern = r'!\[.*?\]\(([^)]+)\)'
    images.extend(re.findall(md_pattern, markdown_content))

    # Logseq/Obsidian wiki-style: ![[image.jpg]] or [[image.jpg]]
    wiki_pattern = r'!?\[\[([^\]]+\.(?:jpg|jpeg|png|gif|webp|heic))\]\]'
    images.extend(re.findall(wiki_pattern, markdown_content, re.IGNORECASE))

    # Filter to only image files
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic'}
    filtered = []
    for img in images:
        img = img.split('?')[0]
        ext = os.path.splitext(img.lower())[1]
        if ext in image_extensions:
            filtered.append(img)

    return filtered


def parse_journal_date(filename: str) -> Optional[str]:
    """Parse the date from a Logseq journal filename (YYYY_MM_DD.md)."""
    match = re.match(r'(\d{4})_(\d{2})_(\d{2})\.md$', filename)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def transcribe_with_gemini(
    image_bytes: bytes,
    image_path: str,
    journal_date: str,
    project_id: str,
    location: str = "us-central1"
) -> dict:
    """Use Gemini Vision to transcribe handwritten text."""
    import vertexai
    from vertexai.generative_models import GenerativeModel, Part, GenerationConfig

    vertexai.init(project=project_id, location=location)
    model = GenerativeModel("gemini-2.5-flash")

    ext = os.path.splitext(image_path.lower())[1]
    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.heic': 'image/heic'
    }
    mime_type = mime_types.get(ext, 'image/jpeg')

    image_part = Part.from_data(image_bytes, mime_type=mime_type)

    prompt = f"""You are transcribing a handwritten journal page dated {journal_date}.

Please carefully read and transcribe ALL the handwritten text in this image.

Guidelines:
1. Preserve the original structure and formatting as much as possible
2. Use paragraph breaks where they appear in the handwriting
3. If there are lists or bullet points, format them appropriately
4. Include any dates, times, or headings that appear
5. If a word is unclear, make your best guess and mark it with [?]
6. If a section is completely illegible, mark it as [illegible]
7. Preserve any emphasis (underlines, etc.) using markdown formatting

Return the transcription as a JSON object:
{{
    "transcription": "The full transcribed text",
    "confidence": "high/medium/low - your confidence in the accuracy",
    "notes": "Any notes about the handwriting quality or issues encountered",
    "word_count": 123,
    "has_lists": true/false,
    "has_drawings": true/false,
    "language": "detected language"
}}

If the image does not contain handwritten text (e.g., it's a photo, diagram, or printed text),
return:
{{
    "transcription": null,
    "confidence": "high",
    "notes": "Image does not contain handwritten text",
    "is_handwritten": false
}}
"""

    generation_config = GenerationConfig(
        temperature=0.1,
        max_output_tokens=4096,
        response_mime_type="application/json"
    )

    try:
        response = model.generate_content(
            [image_part, prompt],
            generation_config=generation_config
        )

        result_text = response.text.strip()
        if result_text.startswith("```"):
            result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
            result_text = re.sub(r'\n?```$', '', result_text)

        result = json.loads(result_text)
        result["is_handwritten"] = result.get("is_handwritten", True)
        return result

    except json.JSONDecodeError as e:
        return {
            "transcription": None,
            "confidence": "low",
            "notes": f"JSON parse error: {str(e)}",
            "is_handwritten": False
        }
    except Exception as e:
        return {
            "transcription": None,
            "confidence": "low",
            "notes": f"API error: {str(e)}",
            "is_handwritten": False
        }


def resolve_image_path(image_link: str, journal_path: str) -> str:
    """Resolve an image link to a full path in the repository."""
    if image_link.startswith('./') or image_link.startswith('../'):
        journal_dir = os.path.dirname(journal_path)
        image_path = os.path.normpath(os.path.join(journal_dir, image_link))
    elif not image_link.startswith('/') and not image_link.startswith('http'):
        if image_link.startswith('assets/'):
            image_path = image_link
        else:
            image_path = f"assets/{image_link}"
    else:
        image_path = image_link.lstrip('/')

    return image_path.replace('\\', '/')


def main():
    parser = argparse.ArgumentParser(description="Local test for handwriting-sync")
    parser.add_argument("--dry-run", action="store_true",
                        help="List images without processing")
    parser.add_argument("--process", action="store_true",
                        help="Actually run OCR and save results")
    parser.add_argument("--date", type=str,
                        help="Process only journals from this date (YYYY-MM-DD)")
    parser.add_argument("--after", type=str,
                        help="Process journals after this date")
    parser.add_argument("--before", type=str,
                        help="Process journals before this date")
    parser.add_argument("--limit", type=int, default=10,
                        help="Maximum number of journals to process")
    parser.add_argument("--journal-path", type=str, default="journals",
                        help="Path to journal files in repo")
    parser.add_argument("--branch", type=str, default="main",
                        help="Git branch to scan")

    args = parser.parse_args()

    # Get configuration
    github_repo = os.environ.get("GITHUB_REPO")
    github_token = os.environ.get("GITHUB_TOKEN")
    project_id = os.environ.get("GCP_PROJECT")

    if not github_repo:
        print("Error: GITHUB_REPO environment variable is required")
        print("Set it with: export GITHUB_REPO=owner/repo")
        sys.exit(1)

    if not github_token:
        print("Error: GITHUB_TOKEN environment variable is required")
        print("Set it with: export GITHUB_TOKEN=ghp_xxx")
        sys.exit(1)

    if args.process and not project_id:
        print("Error: GCP_PROJECT environment variable is required for processing")
        print("Set it with: export GCP_PROJECT=your-project-id")
        sys.exit(1)

    print(f"=== Handwriting Sync Local Test ===")
    print(f"Repository: {github_repo}")
    print(f"Branch: {args.branch}")
    print(f"Journal path: {args.journal_path}")
    print(f"Mode: {'Process with OCR' if args.process else 'Dry run (list only)'}")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Load local state (for tracking what we've processed)
    state_file = OUTPUT_DIR / "state.json"
    state = {}
    if state_file.exists():
        state = json.loads(state_file.read_text())

    # List journal files
    print(f"Scanning {args.journal_path}/ for journal files...")
    journals = list_github_directory(github_repo, args.journal_path, github_token, args.branch)
    journal_files = [j for j in journals if j.get("name", "").endswith(".md")]
    print(f"Found {len(journal_files)} journal files")
    print()

    # Filter journals
    filtered_journals = []
    for journal in journal_files:
        filename = journal.get("name", "")
        journal_date = parse_journal_date(filename)
        if not journal_date:
            continue

        if args.date and journal_date != args.date:
            continue
        if args.after and journal_date < args.after:
            continue
        if args.before and journal_date > args.before:
            continue

        filtered_journals.append({
            "path": journal.get("path"),
            "name": filename,
            "date": journal_date
        })

    # Sort by date (most recent first) and apply limit
    filtered_journals.sort(key=lambda x: x["date"], reverse=True)
    filtered_journals = filtered_journals[:args.limit]

    print(f"Processing {len(filtered_journals)} journals after filtering")
    print()

    total_images = 0
    processed_images = 0
    skipped_images = 0

    for journal in filtered_journals:
        print(f"=== {journal['date']} ({journal['name']}) ===")

        # Get journal content
        content, _ = get_github_file(github_repo, journal["path"], github_token, args.branch)
        if not content:
            print("  [SKIP] Could not read journal file")
            continue

        # Extract image links
        image_links = extract_image_links(content)
        if not image_links:
            print("  No images found in journal")
            continue

        print(f"  Found {len(image_links)} image(s)")

        for image_link in image_links:
            image_path = resolve_image_path(image_link, journal["path"])

            # Skip external URLs
            if image_path.startswith('http'):
                print(f"    [SKIP] External URL: {image_link}")
                continue

            total_images += 1

            # Check if already processed
            if image_path in state:
                print(f"    [SKIP] Already processed: {image_path}")
                skipped_images += 1
                continue

            print(f"    Image: {image_path}")

            if args.dry_run:
                continue

            if args.process:
                # Download image
                print(f"      Downloading...")
                image_bytes = get_github_binary_file(github_repo, image_path, github_token, args.branch)
                if not image_bytes:
                    print(f"      [ERROR] Could not download image")
                    continue

                # Save image locally
                image_output_dir = OUTPUT_DIR / "images" / journal["date"]
                image_output_dir.mkdir(parents=True, exist_ok=True)
                image_filename = os.path.basename(image_path)
                image_output_path = image_output_dir / image_filename
                image_output_path.write_bytes(image_bytes)
                print(f"      Saved image: {image_output_path}")

                # Run OCR
                print(f"      Running Gemini Vision OCR...")
                result = transcribe_with_gemini(
                    image_bytes, image_path, journal["date"], project_id
                )

                if not result.get("is_handwritten", True) or not result.get("transcription"):
                    print(f"      [INFO] Not handwritten text: {result.get('notes', 'unknown')}")
                    state[image_path] = "not_handwritten"
                else:
                    # Save transcript
                    transcript_dir = OUTPUT_DIR / "transcripts" / journal["date"]
                    transcript_dir.mkdir(parents=True, exist_ok=True)

                    base_name = os.path.splitext(image_filename)[0]
                    transcript_path = transcript_dir / f"{base_name}_transcript.json"

                    transcript_data = {
                        "journal_date": journal["date"],
                        "source_image": image_path,
                        "transcribed_at": datetime.now(LOCAL_TIMEZONE).isoformat(),
                        **result
                    }
                    transcript_path.write_text(json.dumps(transcript_data, indent=2, ensure_ascii=False))

                    print(f"      Saved transcript: {transcript_path}")
                    print(f"      Confidence: {result.get('confidence', 'unknown')}")
                    print(f"      Word count: {result.get('word_count', 0)}")

                    state[image_path] = str(transcript_path)
                    processed_images += 1

                # Save state after each image
                state_file.write_text(json.dumps(state, indent=2))

        print()

    # Summary
    print("=== Summary ===")
    print(f"Total images found: {total_images}")
    print(f"Already processed: {skipped_images}")
    if args.process:
        print(f"Newly processed: {processed_images}")
        print(f"Output directory: {OUTPUT_DIR.absolute()}")
    else:
        print(f"Pending: {total_images - skipped_images}")
        print()
        print("To process images, run:")
        print(f"  python local_test.py --process --limit {args.limit}")


if __name__ == "__main__":
    main()
