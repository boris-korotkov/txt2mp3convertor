# AWS Polly Book Narrator: Turning Text into Audiobooks

## Introduction: Finding Time to "Read"

Life gets busy, right? I love diving into books, but finding dedicated time to sit down and read can be a challenge. However, I realized there's plenty of time I *could* be "reading" if only the books were in audio format – during my commute, while exercising at the gym, doing chores around the house, or just taking a walk. This sparked an idea: why not build a tool to convert text-based books into high-quality audio files I could listen to anywhere?

## The Challenge: Local Text-to-Speech Limitations

My first thought was to use a local Text-to-Speech (TTS) engine. I experimented with models like `tts_models/multilingual/multi-dataset/xtts_v2`. While powerful, I ran into limitations, especially with my target books in Russian. The local model struggled with:

1.  **Inaccurate Emphasis:** Capturing the right intonation and stress on words was inconsistent, making the narration sound unnatural.
2.  **Awkward Pauses:** The model often introduced tiny, unnecessary pauses at the end of almost every line break in the source text, disrupting the flow of listening.

It became clear that for the quality and naturalness I wanted, especially for long-form content like books, I needed a more robust solution.

## The Solution: Leveraging the Cloud with AWS Polly

This led me to explore cloud-based TTS services, and **AWS Polly** stood out. It offers high-quality, natural-sounding voices across many languages (including excellent Russian voices like 'Maxim') and provides features specifically designed for handling larger text inputs.

The core of the solution involves:

1.  **Splitting the Book:** Large text files can exceed Polly's limits for synchronous synthesis and are simply unwieldy. The script intelligently splits the input text file into chapters using a regular expression (`Глава \d+`), making each chapter a manageable chunk. A small amount of SSML (`<speak>`, `<break>`) is used to clearly announce the chapter title before its content begins.
2.  **Asynchronous Synthesis:** Instead of waiting for each chapter to be converted one by one (which could take a very long time), the script uses Polly's `start_speech_synthesis_task`. This submits all chapters for processing simultaneously. Polly works on them in the background and saves the output MP3 files directly to an S3 bucket.
3.  **Monitoring and Downloading:** The script polls AWS using `get_speech_synthesis_task` to check the status of each chapter's synthesis task. Once a task is complete, the script parses the S3 output URI, determines the correct S3 key, and downloads the resulting MP3 file from S3 to a local directory.
4.  **Cleanup:** After successfully downloading an audio file, the script automatically deletes the corresponding file from the S3 bucket to keep things tidy and manage costs.

## Process Overview

The process follows this flow:

1.  The Python script (`polly_synthesize_async_final.py`) reads the local text file (`.txt`) and splits it into chapters using regex.
2.  For each chapter, the script initiates an asynchronous Polly synthesis task (`start_speech_synthesis_task`), providing the chapter text (wrapped in minimal SSML) and specifying an S3 location for the output audio file.
3.  AWS Polly processes the text for each task in the background and saves the resulting MP3 audio file to the designated S3 bucket and prefix.
4.  The script periodically polls Polly (`get_speech_synthesis_task`) to check the status of each submitted task.
5.  Once a task is marked 'completed', Polly provides an `OutputUri`. The script parses this URI to find the S3 object key and downloads the corresponding MP3 file from S3 to a local output directory using `s3_client.download_file`.
6.  After a successful download, the script deletes the MP3 file from the S3 bucket using `s3_client.delete_object` to clean up.

## Getting Started: Create Your Own Audiobooks

Want to try it yourself? Here’s how:

1.  **Prerequisites:**
    *   An **AWS Account**.
    *   **AWS Credentials** configured for your local environment where you'll run the script. This typically involves installing the [AWS CLI](https://aws.amazon.com/cli/) and running `aws configure`. Ensure the IAM user/role associated with your credentials has permissions for:
        *   Polly: `polly:StartSpeechSynthesisTask`, `polly:GetSpeechSynthesisTask`
        *   S3: `s3:PutObject` (for Polly to write output), `s3:GetObject` (for download), `s3:DeleteObject` (for cleanup).
    *   **Python 3** installed.
    *   **Boto3** library installed: `pip install boto3`.
    *   An **S3 Bucket** created in the AWS region you intend to use. Note the exact bucket name.

2.  **Prepare Your Text:**
    *   Convert your source material (e.g., a PDF book) into a **plain text (`.txt`) file**. Many tools can do this, but ensure the output is clean.
    *   **Crucially, save the text file with UTF-8 encoding.** This is vital, especially for books with non-ASCII characters (like Russian).
    *   Verify that chapters are marked consistently in a way the script's regex can detect. The default pattern is `r"(Глава\s+\d+)"` (matches "Глава" followed by spaces and digits). If your book uses a different format (e.g., "Chapter 1", "Part I"), you'll need to adjust the `split_pattern` variable in the script accordingly.

3.  **Clone the Repository:**
    ```bash
    git clone <your-repo-url> # Replace with your repository URL
    cd <your-repo-directory> # Navigate into the cloned directory
    ```

4.  **Configure the Script:**
    *   Open `polly_synthesize_async_final.py` in a text editor.
    *   Locate the **`--- Configuration ---`** section near the top.
    *   **Modify these essential variables:**
        *   `TEXT_FILE`: Set this to the exact filename of your UTF-8 encoded `.txt` book file (e.g., `"my_book.txt"`).
        *   `AWS_REGION`: Change `'ca-central-1'` to your AWS region (e.g., `'us-east-1'`, `'eu-west-2'`).
        *   `S3_BUCKET_NAME`: Replace `'my-polly-output-bucket'` with the exact name of *your* S3 bucket.
    *   **Review and optionally modify these:**
        *   `S3_OUTPUT_PREFIX`: A "folder" path within your bucket where Polly will place the output files. *It must end with a forward slash (`/`)!* (e.g., `'my-audiobooks/book1-chapters/'`).
        *   `VOICE_ID`: Choose a Polly voice ID suitable for your text's language (e.g., `'Maxim'` for Russian, `'Joanna'` for US English, `'Matthew'` for US English Male). Check the [AWS Polly documentation](https://docs.aws.amazon.com/polly/latest/dg/voicelist.html) for available voices.
        *   `OUTPUT_FORMAT`: `'mp3'` is common. Other options like `'ogg_vorbis'` are available.
        *   `TTS_ENGINE`: `'standard'` or `'neural'`. Neural voices sound more natural but are more expensive. Check pricing and availability for your chosen voice/region.
        *   `POLL_INTERVAL_SECONDS` and `MAX_WAIT_MINUTES`: Adjust if needed, but the defaults are generally reasonable.

5.  **Place Your Text File:**
    *   Make sure the `.txt` file specified in `TEXT_FILE` is in the same directory as the Python script, or provide the full path to it.

6.  **Run the Script:**
    *   Open your terminal or command prompt, navigate to the script's directory, and run:
        ```bash
        python polly_synthesize_async_final.py
        ```

7.  **Check Your Output:**
    *   The script will first create (or clear and recreate) a local directory named after your input text file (e.g., if `TEXT_FILE` is `"my_book.txt"`, it creates a directory named `"my_book"`).
    *   Monitor the script's output in your terminal. It will show:
        *   Initialization steps.
        *   Chapter detection.
        *   Confirmation as each Polly task is started (with its TaskId).
        *   Polling status updates.
        *   Notifications when tasks complete or fail.
        *   Download progress and S3 deletion confirmations (or errors).
        *   A final summary report.
    *   Once the script finishes successfully, you'll find the generated MP3 files (one per chapter, named like `Глава 1.mp3`, `Глава 2.mp3`, etc.) inside the created local output directory.

## Conclusion

This project successfully solved my personal need to consume more books by turning them into easily listenable audio files using the power and quality of AWS Polly. The asynchronous approach combined with S3 makes it efficient for handling even large texts, transforming potentially hours of waiting into a much faster process.

I hope this script and explanation are useful for others looking to convert their text libraries into personal audiobooks. Feel free to adapt it to your specific needs, perhaps by modifying the chapter splitting logic, integrating different cloud services, or experimenting further with SSML for even more nuanced narration. Happy listening!
