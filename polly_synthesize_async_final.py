import boto3
import os
import time
import re  # Required for splitting text by chapter
import shutil # Required for deleting/creating directories
from botocore.exceptions import ClientError
from urllib.parse import urlparse # To parse the S3 URI

# --- Configuration ---
# Filesystem Paths
TEXT_FILE = "Input text file name.txt"  # CHANGE TO YOUR INPUT TEXT FILENAME (UTF-8 encoded)

# --- AWS / Polly Configuration ---
AWS_REGION = 'ca-central-1'                         # CHANGE TO YOUR AWS REGION
S3_BUCKET_NAME = 'my-polly-output-bucket'     # CHANGE TO YOUR S3 BUCKET NAME
S3_OUTPUT_PREFIX = 'polly-output/book-chapters/'    # Optional: Subfolder for chapters. Must end with '/'

# Polly Voice and Engine Settings
VOICE_ID = 'Maxim'                                  # Russian Male Voice
OUTPUT_FORMAT = 'mp3'                               # Output audio format
TTS_ENGINE = 'standard'                             # 'neural' or 'standard'

# --- Task Polling Configuration ---
POLL_INTERVAL_SECONDS = 10                          # Check status more frequently for multiple tasks
MAX_WAIT_MINUTES = 30                               # Increased max wait for potentially many chapters
# --- End Configuration ---

# --- Script Logic ---

# --- 1. Input Validation and Setup ---
if not os.path.exists(TEXT_FILE):
    print(f"Error: Input text file not found at '{TEXT_FILE}'")
    exit(1)
if not S3_BUCKET_NAME or S3_BUCKET_NAME == 'YOUR-BUCKET-NAME-HERE':
     print(f"Error: Please update the 'S3_BUCKET_NAME' variable.")
     exit(1)
if not S3_OUTPUT_PREFIX.endswith('/'):
    print(f"Warning: S3_OUTPUT_PREFIX ('{S3_OUTPUT_PREFIX}') does not end with '/'. Appending '/'.")
    S3_OUTPUT_PREFIX += '/'

# Derive output directory name from the text file name
OUTPUT_DIR_NAME = os.path.splitext(TEXT_FILE)[0] # Remove extension

# --- 2. Prepare Local Output Directory ---
print(f"Preparing local output directory: '{OUTPUT_DIR_NAME}'")
try:
    if os.path.exists(OUTPUT_DIR_NAME):
        print(f"  Directory '{OUTPUT_DIR_NAME}' already exists. Deleting it.")
        shutil.rmtree(OUTPUT_DIR_NAME)
    os.makedirs(OUTPUT_DIR_NAME)
    print(f"  Successfully created directory '{OUTPUT_DIR_NAME}'.")
except Exception as e:
    print(f"Error setting up output directory '{OUTPUT_DIR_NAME}': {e}")
    exit(1)

# --- 3. Initialize Boto3 Clients ---
print(f"\nInitializing Boto3 clients for region {AWS_REGION}...")
try:
    session = boto3.Session(region_name=AWS_REGION)
    polly_client = session.client('polly')
    s3_client = session.client('s3')
    print("Boto3 clients initialized successfully.")
except Exception as e:
    print(f"Error initializing Boto3 clients: {e}")
    exit(1)

# --- 4. Read and Split Text File into Chapters ---
print(f"\nReading text from '{TEXT_FILE}'...")
chapters = {} # Dictionary to store {chapter_title: chapter_text_with_ssml}
try:
    with open(TEXT_FILE, 'r', encoding='utf-8') as f:
        full_text_content = f.read()

    if not full_text_content.strip():
        print("Error: Input text file is empty.")
        exit(1)

    print("Splitting text into chapters...")
    # Regex to split by "Глава <number>", capturing the delimiter
    # It looks for "Глава", followed by one or more spaces, then one or more digits.
    split_pattern = r"(Глава\s+\d+)"
    parts = re.split(split_pattern, full_text_content)

    # The result of split with capturing group is [before_first, delim1, after1_before2, delim2, after2...]
    # We iterate through it, taking delimiter and the text that follows it.
    current_chapter_title = None
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue

        # Check if this part is a chapter title based on the pattern
        if re.match(split_pattern, part):
            current_chapter_title = part
            # Initialize chapter text, the actual content comes next
            if current_chapter_title not in chapters:
                 chapters[current_chapter_title] = ""
            print(f"  Found chapter: {current_chapter_title}")
        elif current_chapter_title:
            # This part is the text belonging to the last found chapter title
            # Add SSML wrapping and break tag
            ssml_text = f'<speak>{current_chapter_title}<break strength="strong"/>{part}</speak>'
            chapters[current_chapter_title] = ssml_text
            current_chapter_title = None # Reset until next title is found

    if not chapters:
        print("Error: No chapters found matching the pattern 'Глава <number>'.")
        exit(1)

    print(f"Successfully processed {len(chapters)} chapters.")

except Exception as e:
    print(f"Error reading or splitting text file: {e}")
    exit(1)


# --- 5. Start Polly Synthesis Tasks for All Chapters ---
print(f"\nStarting asynchronous speech synthesis tasks for {len(chapters)} chapters...")
print(f"  Voice ID:        {VOICE_ID}")
print(f"  Engine:          {TTS_ENGINE}")
print(f"  Output S3 Prefix: s3://{S3_BUCKET_NAME}/{S3_OUTPUT_PREFIX}")

# Dictionary to track tasks: {task_id: chapter_title}
active_tasks = {}
failed_starts = []

for chapter_title, ssml_content in chapters.items():
    print(f"  Starting task for: {chapter_title}")
    try:
        response = polly_client.start_speech_synthesis_task(
            Text=ssml_content,
            OutputFormat=OUTPUT_FORMAT,
            OutputS3BucketName=S3_BUCKET_NAME,
            OutputS3KeyPrefix=S3_OUTPUT_PREFIX, # Polly appends TaskID.format
            VoiceId=VOICE_ID,
            Engine=TTS_ENGINE,
            LanguageCode='ru-RU', # Helps Polly, though often inferred
            TextType='ssml' # IMPORTANT: Specify text is SSML
        )

        task_id = response.get('SynthesisTask', {}).get('TaskId')
        if not task_id:
            print(f"    Error: Could not retrieve TaskId for {chapter_title}. Response: {response}")
            failed_starts.append(chapter_title)
            continue

        active_tasks[task_id] = chapter_title
        print(f"    Successfully started task. TaskId: {task_id}")

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        error_message = e.response.get("Error", {}).get("Message")
        print(f"    Error starting task for {chapter_title}: {error_code} - {error_message}")
        failed_starts.append(chapter_title)
    except Exception as e:
        print(f"    An unexpected error occurred starting task for {chapter_title}: {e}")
        failed_starts.append(chapter_title)

if not active_tasks:
    print("\nError: No synthesis tasks were successfully started.")
    exit(1)

print(f"\nSuccessfully initiated {len(active_tasks)} tasks.")
if failed_starts:
    print(f"Warning: Failed to start tasks for chapters: {', '.join(failed_starts)}")


# --- 6. Poll for Task Completion ---
print(f"\nWaiting for {len(active_tasks)} tasks to complete (checking status every {POLL_INTERVAL_SECONDS} seconds)...")
start_time = time.time()
completed_tasks = {} # {task_id: {'title': chapter_title, 'uri': output_uri}}
failed_tasks = {}    # {task_id: {'title': chapter_title, 'reason': reason}}
tasks_to_poll = list(active_tasks.keys()) # List of task IDs still needing status checks

while tasks_to_poll and time.time() < start_time + (MAX_WAIT_MINUTES * 60):
    print(f"  [{time.strftime('%H:%M:%S')}] Checking status for {len(tasks_to_poll)} remaining tasks...")
    # Check tasks in reverse so we can safely remove completed/failed ones
    for i in range(len(tasks_to_poll) - 1, -1, -1):
        task_id = tasks_to_poll[i]
        chapter_title = active_tasks[task_id]
        try:
            task_status_response = polly_client.get_speech_synthesis_task(TaskId=task_id)
            task_info = task_status_response.get('SynthesisTask', {})
            task_status = task_info.get('TaskStatus')

            if task_status == 'completed':
                print(f"    Task for '{chapter_title}' completed!")
                task_output_uri = task_info.get('OutputUri')
                if task_output_uri:
                    completed_tasks[task_id] = {'title': chapter_title, 'uri': task_output_uri}
                else:
                    print(f"    Error: Task for '{chapter_title}' completed but OutputUri missing!")
                    failed_tasks[task_id] = {'title': chapter_title, 'reason': 'Completed but OutputUri missing'}
                tasks_to_poll.pop(i) # Remove from polling list

            elif task_status == 'failed':
                failure_reason = task_info.get('TaskStatusReason', 'Unknown reason')
                print(f"    Error: Task for '{chapter_title}' failed: {failure_reason}")
                failed_tasks[task_id] = {'title': chapter_title, 'reason': failure_reason}
                tasks_to_poll.pop(i) # Remove from polling list

            elif task_status in ['scheduled', 'inProgress']:
                # Still working, keep polling
                pass
            else:
                print(f"    Warning: Unknown task status for '{chapter_title}': {task_status}")
                # Optionally treat unknown as failure or keep polling
                # failed_tasks[task_id] = {'title': chapter_title, 'reason': f'Unknown status: {task_status}'}
                # tasks_to_poll.pop(i)

        except ClientError as e:
            print(f"    Warning: Error checking task status for '{chapter_title}' (ID: {task_id}): {e}. Retrying...")
            # Keep polling, but maybe add a counter to give up after too many errors per task
        except Exception as e:
            print(f"    An unexpected error occurred checking status for '{chapter_title}' (ID: {task_id}): {e}")
            failed_tasks[task_id] = {'title': chapter_title, 'reason': f'Unexpected error during status check: {e}'}
            tasks_to_poll.pop(i) # Remove from polling list

    if tasks_to_poll: # Only sleep if there are tasks left to poll
        time.sleep(POLL_INTERVAL_SECONDS)

# --- 7. Check Final Status & Report Failures ---
if tasks_to_poll:
    print(f"\nError: Timed out after {MAX_WAIT_MINUTES} minutes. The following tasks did not complete:")
    for task_id in tasks_to_poll:
        print(f"  - {active_tasks[task_id]} (TaskId: {task_id})")

if failed_tasks:
    print("\nError: Some synthesis tasks failed:")
    for task_id, info in failed_tasks.items():
        print(f"  - {info['title']} (TaskId: {task_id}): {info['reason']}")

if not completed_tasks:
     print("\nError: No tasks completed successfully. Cannot download results.")
     exit(1)

# --- 8. Download Completed Results from S3 ---
print(f"\nDownloading {len(completed_tasks)} completed audio files to '{OUTPUT_DIR_NAME}'...")
download_errors = {} # {chapter_title: error_message}
deletion_errors = {} # {chapter_title: error_message} # Track deletion errors separately
successful_deletions = 0

for task_id, info in completed_tasks.items():
    chapter_title = info['title']
    task_output_uri = info['uri']
    local_filename = os.path.join(OUTPUT_DIR_NAME, f"{chapter_title}.{OUTPUT_FORMAT}")
    s3_key = None

    print(f"  Processing '{chapter_title}' from {task_output_uri}") # Changed wording slightly
    try:
        # --- Parsing S3 Key ---
        parsed_uri = urlparse(task_output_uri)
        if not parsed_uri.path:
            raise ValueError("Could not parse path from OutputUri")

        path_parts = parsed_uri.path.lstrip('/').split('/', 1)
        if len(path_parts) == 2 and path_parts[0] == S3_BUCKET_NAME:
            s3_key = path_parts[1]
        else:
             print(f"    Warning: Could not extract key matching bucket name from path '{parsed_uri.path}'. Using path after first slash.")
             s3_key = parsed_uri.path.lstrip('/')
             if not s3_key:
                 raise ValueError(f"Failed to determine S3 key from OutputUri: {task_output_uri}")
             print(f"    Using fallback key: {s3_key}")

        print(f"    S3 Key: {s3_key}")
        print(f"    Local Path: {local_filename}")

        # --- Download ---
        s3_client.download_file(S3_BUCKET_NAME, s3_key, local_filename)
        print(f"    Successfully downloaded.")

        # --- Delete from S3 (ONLY after successful download) ---
        print(f"    Attempting to delete S3 object: {s3_key}")
        try:
            s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
            print(f"    Successfully deleted S3 object.")
            successful_deletions += 1
        except ClientError as del_e:
            err_msg = f"S3 Delete Error ({del_e.response.get('Error',{}).get('Code')}): {del_e}"
            print(f"    Warning: {err_msg}")
            deletion_errors[chapter_title] = err_msg
        except Exception as del_e:
            err_msg = f"Unexpected delete error: {del_e}"
            print(f"    Warning: {err_msg}")
            deletion_errors[chapter_title] = err_msg

    # --- Error Handling for Download/Parsing ---
    except ClientError as e:
         error_code = e.response.get("Error", {}).get("Code")
         err_msg = f"S3 Download Error ({error_code})"
         print(f"    Error downloading: {err_msg} - {e}")
         download_errors[chapter_title] = err_msg
    except ValueError as e:
        err_msg = f"Error parsing S3 URI/Path: {e}"
        print(f"    Error: {err_msg}")
        download_errors[chapter_title] = err_msg
    except Exception as e:
         err_msg = f"Unexpected download/processing error: {e}"
         print(f"    Error: {err_msg}")
         download_errors[chapter_title] = err_msg
         # Note: If download fails, deletion is automatically skipped.

# --- 9. Final Report ---
print("\n--- Script Summary ---")
print(f"Processed text file: '{TEXT_FILE}'")
print(f"Output directory:    '{OUTPUT_DIR_NAME}'")
print(f"Chapters found:      {len(chapters)}")
print(f"Tasks started:       {len(active_tasks) + len(failed_starts)}")
print(f"Tasks completed:     {len(completed_tasks)}")
print(f"Tasks failed:        {len(failed_tasks) + len(failed_starts)}")
print(f"Downloads successful:{len(completed_tasks) - len(download_errors)}")
print(f"Download errors:     {len(download_errors)}")
print(f"S3 Deletions attempted:{successful_deletions + len(deletion_errors)}") # Based on successful downloads
print(f"S3 Deletions successful:{successful_deletions}")
print(f"S3 Deletion errors:   {len(deletion_errors)}")

if download_errors:
    print("\nChapters with download errors:")
    for title, err in download_errors.items():
        print(f"  - {title}: {err}")

if deletion_errors:
    print("\nChapters with S3 deletion errors (file remains in S3):")
    for title, err in deletion_errors.items():
        print(f"  - {title}: {err}")

print("\nScript finished.")