"""
Handwriting Sync Cloud Function

Scans Logseq journal files in a GitHub repository for linked images of handwritten
journal pages. Uses Gemini Vision to perform handwriting recognition (OCR) and
saves transcripts to GCS.

Triggered by: Cloud Scheduler (daily) or HTTP request
Output: Handwriting transcripts saved to GCS in handwritten/ folder
"""

import base64
import json
import os
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import functions_framework
import requests
from google.cloud import storage
from flask import Request

# Vertex AI / Gemini imports
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig

# Local timezone (configurable via LOCAL_TIMEZONE env var)
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "Pacific/Auckland"))


def log_structured(severity: str, message: str, **kwargs):
    """Output structured JSON log for Cloud Logging."""
    log_entry = {
        "severity": severity,
        "message": message,
        "component": "handwriting-sync",
        **kwargs
    }
    print(json.dumps(log_entry))


def get_processed_state(bucket_name: str) -> dict:
    """Load the processed state from GCS.

    The state file tracks which images have been processed,
    avoiding duplicate OCR on subsequent runs.

    Returns:
        Dict mapping image_path -> transcript_path
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(".handwriting_sync_state.json")

    if blob.exists():
        try:
            content = blob.download_as_text()
            return json.loads(content)
        except Exception as e:
            log_structured("WARNING", f"Failed to load handwriting sync state: {e}",
                          event="state_load_error", error=str(e))

    return {}


def save_processed_state(bucket_name: str, state: dict) -> None:
    """Save the processed state to GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(".handwriting_sync_state.json")

    blob.upload_from_string(
        json.dumps(state, indent=2, ensure_ascii=False),
        content_type="application/json"
    )


def is_already_processed(image_path: str, state: dict) -> tuple[bool, Optional[str]]:
    """Check if an image has already been processed.

    Args:
        image_path: Path to the image in the repository
        state: The handwriting sync state dict

    Returns:
        Tuple of (is_processed, transcript_path)
    """
    if image_path in state:
        return True, state[image_path]
    return False, None


def get_github_file(
    repo: str,
    path: str,
    token: str,
    branch: str = "main"
) -> tuple[Optional[str], Optional[str]]:
    """Get file content and SHA from GitHub.

    Returns:
        Tuple of (content, sha) or (None, None) if file doesn't exist
    """
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
        log_structured("WARNING", f"Failed to get GitHub file: {e}",
                      event="github_get_error", path=path, error=str(e))
        return None, None


def get_github_binary_file(
    repo: str,
    path: str,
    token: str,
    branch: str = "main"
) -> Optional[bytes]:
    """Get binary file content from GitHub (for images).

    Returns:
        File bytes or None if not found
    """
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
        log_structured("WARNING", f"Failed to get GitHub binary file: {e}",
                      event="github_binary_error", path=path, error=str(e))
        return None


def list_github_directory(
    repo: str,
    path: str,
    token: str,
    branch: str = "main"
) -> list[dict]:
    """List files in a GitHub directory.

    Returns:
        List of file info dicts with 'name', 'path', 'type'
    """
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
        log_structured("WARNING", f"Failed to list GitHub directory: {e}",
                      event="github_list_error", path=path, error=str(e))
        return []


def extract_image_links(markdown_content: str) -> list[str]:
    """Extract image links from markdown content.

    Looks for:
    - ![alt](path/to/image.jpg)
    - ![[image.jpg]] (Logseq/Obsidian style)
    - [[assets/image.jpg]]

    Returns:
        List of image paths
    """
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
        # Remove any URL parameters
        img = img.split('?')[0]
        ext = os.path.splitext(img.lower())[1]
        if ext in image_extensions:
            filtered.append(img)

    return filtered


def is_handwriting_image(image_path: str) -> bool:
    """Check if an image path suggests it's a handwritten journal page.

    Looks for keywords like: handwritten, journal, notes, scan, page, handwriting
    """
    keywords = ['handwrit', 'journal', 'notes', 'scan', 'page', 'written', 'diary', 'notebook']
    path_lower = image_path.lower()
    return any(kw in path_lower for kw in keywords)


def transcribe_handwriting_with_gemini(
    image_bytes: bytes,
    image_path: str,
    journal_date: str,
    project_id: str,
    location: str = "us-central1"
) -> dict:
    """Use Gemini Vision to transcribe handwritten text from an image.

    Args:
        image_bytes: Raw image bytes
        image_path: Path to the image (for context)
        journal_date: Date of the journal entry
        project_id: GCP project ID
        location: Vertex AI location

    Returns:
        Dict with transcription results
    """
    vertexai.init(project=project_id, location=location)

    # Use Gemini 2.5 Flash for vision tasks
    # See: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models
    model = GenerativeModel("gemini-2.5-flash")

    # Determine MIME type from extension
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

    # Create image part
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

        # Handle potential markdown code blocks
        if result_text.startswith("```"):
            result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
            result_text = re.sub(r'\n?```$', '', result_text)

        result = json.loads(result_text)
        result["is_handwritten"] = result.get("is_handwritten", True)
        return result

    except json.JSONDecodeError as e:
        log_structured("WARNING", f"Failed to parse Gemini response as JSON: {e}",
                      event="gemini_parse_error", error=str(e))
        return {
            "transcription": None,
            "confidence": "low",
            "notes": f"JSON parse error: {str(e)}",
            "is_handwritten": False
        }

    except Exception as e:
        log_structured("ERROR", f"Gemini Vision API error: {e}",
                      event="gemini_api_error", error=str(e))
        return {
            "transcription": None,
            "confidence": "low",
            "notes": f"API error: {str(e)}",
            "is_handwritten": False
        }


def save_transcript(
    bucket_name: str,
    journal_date: str,
    image_path: str,
    transcription_result: dict,
    image_bytes: bytes
) -> str:
    """Save handwriting transcript and image to GCS.

    Returns the blob path where transcript was saved.
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    now = datetime.now(LOCAL_TIMEZONE)

    # Create a safe filename from the image path
    image_filename = os.path.basename(image_path)
    safe_name = re.sub(r'[^\w\-.]', '_', image_filename)
    base_name = os.path.splitext(safe_name)[0]

    # Save the transcript JSON
    transcript_path = f"handwritten/{journal_date}_{base_name}_transcript.json"
    transcript_data = {
        "journal_date": journal_date,
        "source_image": image_path,
        "transcribed_at": now.isoformat(),
        **transcription_result
    }

    transcript_blob = bucket.blob(transcript_path)
    transcript_blob.upload_from_string(
        json.dumps(transcript_data, indent=2, ensure_ascii=False),
        content_type="application/json"
    )

    # Add metadata
    transcript_blob.metadata = {
        "journal_date": journal_date,
        "source_image": image_path,
        "confidence": transcription_result.get("confidence", "unknown"),
        "word_count": str(transcription_result.get("word_count", 0))
    }
    transcript_blob.patch()

    # Also save the original image
    image_ext = os.path.splitext(image_path)[1] or '.jpg'
    image_blob_path = f"handwritten/{journal_date}_{base_name}{image_ext}"
    image_blob = bucket.blob(image_blob_path)
    image_blob.upload_from_string(
        image_bytes,
        content_type=f"image/{image_ext.lstrip('.').replace('jpg', 'jpeg')}"
    )

    log_structured("INFO", f"Saved transcript and image",
                  event="transcript_saved",
                  transcript_path=transcript_path,
                  image_path=image_blob_path)

    return transcript_path


def parse_journal_date(filename: str) -> Optional[str]:
    """Parse the date from a Logseq journal filename.

    Expects format: YYYY_MM_DD.md

    Returns:
        Date string (YYYY-MM-DD) or None
    """
    match = re.match(r'(\d{4})_(\d{2})_(\d{2})\.md$', filename)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def process_journal_file(
    repo: str,
    journal_path: str,
    token: str,
    branch: str,
    bucket_name: str,
    project_id: str,
    state: dict
) -> list[dict]:
    """Process a single journal file for handwritten images.

    Returns list of processed image results.
    """
    results = []

    # Get the journal date from filename
    filename = os.path.basename(journal_path)
    journal_date = parse_journal_date(filename)
    if not journal_date:
        log_structured("WARNING", f"Could not parse date from filename: {filename}",
                      event="parse_date_error")
        return results

    # Get journal content
    content, _ = get_github_file(repo, journal_path, token, branch)
    if not content:
        return results

    # Extract image links
    image_links = extract_image_links(content)
    if not image_links:
        return results

    log_structured("INFO", f"Found {len(image_links)} images in {filename}",
                  event="images_found",
                  journal_date=journal_date,
                  image_count=len(image_links))

    # Process each image
    for image_link in image_links:
        # Resolve relative paths
        if image_link.startswith('./') or image_link.startswith('../'):
            # Relative to journal file
            journal_dir = os.path.dirname(journal_path)
            image_path = os.path.normpath(os.path.join(journal_dir, image_link))
        elif not image_link.startswith('/') and not image_link.startswith('http'):
            # Try common Logseq asset locations
            if image_link.startswith('assets/'):
                image_path = image_link
            else:
                image_path = f"assets/{image_link}"
        else:
            image_path = image_link.lstrip('/')

        # Skip external URLs
        if image_path.startswith('http'):
            continue

        # Normalize path separators
        image_path = image_path.replace('\\', '/')

        # Check if already processed
        already_processed, existing_transcript = is_already_processed(image_path, state)
        if already_processed:
            log_structured("INFO", f"Image already processed: {image_path}",
                          event="already_processed",
                          transcript_path=existing_transcript)
            results.append({
                "image_path": image_path,
                "status": "skipped",
                "reason": "already_processed",
                "transcript_path": existing_transcript
            })
            continue

        # Check if it looks like a handwriting image (optional filter)
        # For now, process all images and let Gemini determine if it's handwriting

        # Download image from GitHub
        log_structured("INFO", f"Downloading image: {image_path}",
                      event="image_download_started")

        image_bytes = get_github_binary_file(repo, image_path, token, branch)
        if not image_bytes:
            log_structured("WARNING", f"Could not download image: {image_path}",
                          event="image_download_failed")
            results.append({
                "image_path": image_path,
                "status": "failed",
                "reason": "download_failed"
            })
            continue

        # Transcribe with Gemini Vision
        log_structured("INFO", f"Transcribing image with Gemini Vision",
                      event="transcription_started",
                      image_path=image_path,
                      image_size=len(image_bytes))

        transcription = transcribe_handwriting_with_gemini(
            image_bytes,
            image_path,
            journal_date,
            project_id
        )

        # Check if it was actually handwriting
        if not transcription.get("is_handwritten", True) or not transcription.get("transcription"):
            log_structured("INFO", f"Image is not handwritten text: {image_path}",
                          event="not_handwritten",
                          notes=transcription.get("notes"))
            results.append({
                "image_path": image_path,
                "status": "skipped",
                "reason": "not_handwritten",
                "notes": transcription.get("notes")
            })
            # Still mark as processed to avoid re-checking
            state[image_path] = "not_handwritten"
            continue

        # Save transcript
        transcript_path = save_transcript(
            bucket_name,
            journal_date,
            image_path,
            transcription,
            image_bytes
        )

        # Update state
        state[image_path] = transcript_path

        results.append({
            "image_path": image_path,
            "status": "success",
            "transcript_path": transcript_path,
            "confidence": transcription.get("confidence"),
            "word_count": transcription.get("word_count", 0)
        })

        log_structured("INFO", f"Successfully transcribed: {image_path}",
                      event="transcription_completed",
                      word_count=transcription.get("word_count", 0),
                      confidence=transcription.get("confidence"))

    return results


@functions_framework.http
def process_handwriting(request: Request):
    """HTTP Cloud Function to process handwritten journal pages.

    Query parameters:
    - date: Process only journals from this date (YYYY-MM-DD)
    - after: Process journals after this date
    - before: Process journals before this date
    - limit: Maximum number of journals to process
    - dry_run: List images without processing
    """
    start_time = datetime.now(LOCAL_TIMEZONE)

    # Get configuration
    project_id = os.environ.get("GCP_PROJECT")
    bucket_name = os.environ.get("GCS_BUCKET")
    github_repo = os.environ.get("GITHUB_REPO")
    github_token = os.environ.get("GITHUB_TOKEN")
    github_branch = os.environ.get("GITHUB_BRANCH", "main")
    journal_path = os.environ.get("LOGSEQ_JOURNAL_PATH", "journals")

    if not all([project_id, bucket_name, github_repo, github_token]):
        return {
            "status": "error",
            "message": "Missing required configuration"
        }, 500

    # Parse query parameters
    date_filter = request.args.get("date")
    after_filter = request.args.get("after")
    before_filter = request.args.get("before")
    limit = int(request.args.get("limit", 50))
    dry_run = request.args.get("dry_run", "").lower() == "true"

    log_structured("INFO", "Starting handwriting sync",
                  event="sync_started",
                  date_filter=date_filter,
                  after_filter=after_filter,
                  before_filter=before_filter,
                  dry_run=dry_run)

    try:
        # Load state
        state = get_processed_state(bucket_name)
        log_structured("INFO", f"Loaded state with {len(state)} processed images",
                      event="state_loaded")

        # List journal files
        journals = list_github_directory(github_repo, journal_path, github_token, github_branch)
        journal_files = [j for j in journals if j.get("name", "").endswith(".md")]

        log_structured("INFO", f"Found {len(journal_files)} journal files",
                      event="journals_found")

        # Filter journals
        filtered_journals = []
        for journal in journal_files:
            filename = journal.get("name", "")
            journal_date = parse_journal_date(filename)
            if not journal_date:
                continue

            # Apply date filters
            if date_filter and journal_date != date_filter:
                continue
            if after_filter and journal_date < after_filter:
                continue
            if before_filter and journal_date > before_filter:
                continue

            filtered_journals.append({
                "path": journal.get("path"),
                "name": filename,
                "date": journal_date
            })

        # Sort by date (most recent first) and apply limit
        filtered_journals.sort(key=lambda x: x["date"], reverse=True)
        filtered_journals = filtered_journals[:limit]

        log_structured("INFO", f"Processing {len(filtered_journals)} journals after filtering",
                      event="journals_filtered")

        if dry_run:
            # Just list what would be processed
            dry_run_results = []
            for journal in filtered_journals:
                content, _ = get_github_file(github_repo, journal["path"], github_token, github_branch)
                if content:
                    images = extract_image_links(content)
                    dry_run_results.append({
                        "journal": journal["name"],
                        "date": journal["date"],
                        "images": images,
                        "image_count": len(images)
                    })

            duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)
            return {
                "status": "success",
                "dry_run": True,
                "journals_scanned": len(filtered_journals),
                "results": dry_run_results,
                "duration_ms": duration_ms
            }

        # Process each journal
        all_results = []
        processed_count = 0
        error_count = 0

        for journal in filtered_journals:
            try:
                results = process_journal_file(
                    github_repo,
                    journal["path"],
                    github_token,
                    github_branch,
                    bucket_name,
                    project_id,
                    state
                )
                all_results.extend(results)
                processed_count += sum(1 for r in results if r.get("status") == "success")

            except Exception as e:
                log_structured("ERROR", f"Error processing journal {journal['name']}: {e}",
                              event="journal_error",
                              journal=journal["name"],
                              error=str(e))
                error_count += 1

        # Save updated state
        save_processed_state(bucket_name, state)

        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)

        log_structured("INFO", "Handwriting sync complete",
                      event="sync_completed",
                      journals_processed=len(filtered_journals),
                      images_transcribed=processed_count,
                      errors=error_count,
                      duration_ms=duration_ms)

        return {
            "status": "success",
            "dry_run": False,
            "journals_processed": len(filtered_journals),
            "images_transcribed": processed_count,
            "errors": error_count,
            "results": all_results,
            "duration_ms": duration_ms
        }

    except Exception as e:
        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)
        log_structured("ERROR", f"Handwriting sync failed: {e}",
                      event="sync_failed",
                      error=str(e),
                      duration_ms=duration_ms)
        return {
            "status": "error",
            "message": str(e),
            "duration_ms": duration_ms
        }, 500


@functions_framework.http
def health_check(request):
    """Simple health check endpoint."""
    return {"status": "healthy"}, 200
