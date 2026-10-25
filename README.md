# Kids Video Factory — automated publishing edition

A Python project that turns a creative brief into a short vertical kids' story video, then optionally uploads it to YouTube and publishes it as an Instagram Reel. Source files are at the repository root; GitHub Actions workflow files must remain in `.github/workflows/`.

## What this version does

- Runs on a GitHub Actions schedule (default: 08:00 India time) or by manual dispatch.
- Accepts a prompt from workflow input or `VIDEO_PROMPT`.
- Uses an OpenAI-compatible chat-completions endpoint for story/scene planning when configured; otherwise it uses a deterministic local template (not an LLM).
- Can call a reachable ComfyUI API workflow to create one image per scene. FFmpeg then animates those still images with pan/zoom and combines them with narration.
- Uploads to YouTube through the official YouTube Data API resumable-upload endpoint when OAuth credentials are configured.
- For Instagram, uploads each run's MP4 to Cloudinary and uses that unique public HTTPS URL to publish a Reel through Meta's Graph API.
- Defaults to `PUBLISH_ENABLED=false`. Never enable public publishing until you have tested the generated output and all credentials.

## Honest limitations

This is an automated **AI-assisted illustrated video** pipeline, not a universal text-to-video engine. The included ComfyUI adapter is for per-scene images, which are animated by FFmpeg. It does not make characters perform genuinely generated continuous motion. A true AI-video workflow requires a compatible video-generation model, sufficient GPU, and a model-specific ComfyUI workflow/output adapter.

GitHub-hosted runners are CPU runners in this workflow. They do not provide a guaranteed free GPU. A remote ComfyUI instance must be reachable by the runner. Free notebook GPU sessions (such as Kaggle/Colab) are temporary and should not be treated as guaranteed always-on servers. Do not expose an unauthenticated ComfyUI server to the public internet.

Google AI Pro consumer-app access is not automatically an API credential, and this project does not automate browser clicks or bypass consumer product limits. The LLM endpoint must be a separately supported API or a self-hosted OpenAI-compatible endpoint. Free API quotas, when available, vary by provider and can change.

## 1. Create the GitHub repository

1. Create a new GitHub repository, preferably private while configuring credentials.
2. Upload the project files and preserve the `.github/workflows/daily.yml` path.
3. Open **Actions** in the repository and enable workflows.
4. Open **Daily Kids Video** and click **Run workflow** for a manual test.
5. Download the `kids-video-<run number>` artifact and inspect `kids_story.mp4`, `story.json`, `metadata.json`, and `thumbnail.jpg`.

The workflow runs at `02:30 UTC`, which is `08:00 Asia/Kolkata`. GitHub may delay scheduled workflows. GitHub Free includes a monthly Actions-minutes allowance for private repositories; public-repository standard runners have different included usage. Check the current GitHub billing page before relying on daily runs.

## 2. Configure Actions variables and secrets

Open **Repository → Settings → Secrets and variables → Actions**. Put non-sensitive settings in **Variables** and tokens/keys in **Secrets**. Never commit `.env`, OAuth client JSON, refresh tokens, API secrets, or access tokens.

### Variables

| Variable | Example / meaning |
|---|---|
| `VIDEO_PROMPT` | `A gentle Tamil story about a tiny elephant helping a friend` |
| `VIDEO_LANGUAGE` | `en` or `ta`; Tamil voice depends on installed eSpeak voice availability |
| `VIDEO_DURATION_SECONDS` | `45` (the project clamps the target to 20–60 seconds) |
| `VIDEO_TITLE_PREFIX` | `Little Story` |
| `PUBLISH_ENABLED` | `false` first; change to `true` only after private/unlisted tests |
| `YOUTUBE_PRIVACY` | `private`, `unlisted`, or `public`; use `private` for tests |
| `YOUTUBE_MADE_FOR_KIDS` | `true` only when the video is actually directed to children; choose the correct audience setting |
| `YOUTUBE_CONTAINS_SYNTHETIC_MEDIA` | `true` when the video meets YouTube's altered/synthetic-content disclosure criteria |
| `LLM_BASE_URL` | API base URL; code appends `/chat/completions` |
| `LLM_MODEL` | Exact model identifier supported by your chosen provider |
| `COMFYUI_BASE_URL` | HTTPS base URL for a reachable ComfyUI instance |
| `COMFYUI_PROMPT_NODE_ID` | Node ID in your API-format workflow whose `inputs.text` accepts the scene prompt |
| `COMFYUI_SAVE_NODE_ID` | SaveImage node ID in the workflow |
| `INSTAGRAM_GRAPH_VERSION` | Graph API version enabled for your Meta app, e.g. the current version shown in Meta's dashboard/docs |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name |

### Secrets

| Secret | Required for |
|---|---|
| `LLM_API_KEY` | Optional LLM endpoint authentication; omit if your self-hosted endpoint needs no key |
| `COMFYUI_WORKFLOW_JSON` | Optional ComfyUI API-format workflow JSON; workflow node IDs must match the variables above |
| `YOUTUBE_CLIENT_ID` | YouTube OAuth |
| `YOUTUBE_CLIENT_SECRET` | YouTube OAuth |
| `YOUTUBE_REFRESH_TOKEN` | YouTube OAuth |
| `INSTAGRAM_ACCESS_TOKEN` | Meta/Instagram publishing token (for the Facebook Login flow, use a Page access token with the required permissions) |
| `INSTAGRAM_USER_ID` | Instagram professional account ID, not the Facebook Page ID |
| `CLOUDINARY_API_KEY` | Per-run public video hosting for Instagram |
| `CLOUDINARY_API_SECRET` | Per-run public video hosting for Instagram |

The app now uploads the current run's MP4 to Cloudinary automatically when Instagram credentials and Cloudinary settings are configured. It does not use a fixed, stale media URL. Cloudinary free-plan storage, bandwidth and file-size limits still apply.

## 3. Story-generation model (optional but recommended)

The LLM connector expects an OpenAI-compatible endpoint that supports `POST <LLM_BASE_URL>/chat/completions`. Set `LLM_BASE_URL`, `LLM_MODEL`, and optionally `LLM_API_KEY`. You can use a supported provider endpoint or a self-hosted compatible server. Check the provider's current pricing, free quota, endpoint format and terms first.

If you do not configure an LLM, the project uses a local prompt-aware template. That is a fallback, not AI story generation. The application catches LLM failures and falls back unless you change the error policy in code.

## 4. AI scene images (optional but recommended)

The ComfyUI adapter expects an API-format workflow JSON. The workflow should generate an image and save it with a `SaveImage` node. The app replaces the selected prompt node's `inputs.text`, queues the workflow, waits for its result, downloads the image, and repeats for five scenes.

1. Install ComfyUI on a machine with a compatible image model and enough GPU memory.
2. Load and test a workflow in ComfyUI, then export it in API format.
3. Identify the text-prompt node and `SaveImage` node IDs.
4. Make the service reachable from GitHub Actions through a secure, authenticated network path. The code does not implement ComfyUI authentication; do not expose an open endpoint to the internet.
5. Add the workflow JSON as the `COMFYUI_WORKFLOW_JSON` secret and configure the URL and node IDs.
6. Set `REQUIRE_AI_IMAGES=true` as a repository variable so the job fails rather than silently falling back to illustrated cards if image generation fails.

A free notebook is useful for manual experiments, but notebook shutdowns and changing quotas make it unreliable for scheduled unattended generation. If the only compute you have is a free notebook, generate media manually there and use GitHub Actions for the parts that do not require the GPU.

## 5. Set up YouTube OAuth

YouTube requires OAuth authorization; an API key alone cannot upload to your channel. The code uses a refresh token so scheduled jobs can request short-lived access tokens without opening a browser each day.

1. Open [Google Cloud Console](https://console.cloud.google.com/), create/select a project, and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen and add your Google account as a test user if the app is in Testing mode.
3. Create an OAuth client of type **Desktop app** and download its JSON file.
4. On your own computer, place the downloaded file beside `get_youtube_token.py`, renamed exactly `client_secret.json`. Do not upload this JSON to GitHub.
5. Install dependencies and run the helper locally:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python get_youtube_token.py
   ```

   On Windows, activate with `.venv\\Scripts\\activate` instead.
6. Sign in to the channel that should receive the videos and consent. Copy the printed refresh token into GitHub secret `YOUTUBE_REFRESH_TOKEN`. Add the printed/client ID to `YOUTUBE_CLIENT_ID` and the client secret from the downloaded JSON to `YOUTUBE_CLIENT_SECRET`.
7. Run one workflow with `PUBLISH_ENABLED=false` first, then enable publishing with `YOUTUBE_PRIVACY=private` and check the channel.

OAuth refresh tokens issued while an app is in Testing mode can expire (commonly after seven days for these scopes). For long-running automation, review Google's current OAuth publishing/verification requirements and consent-screen publishing status. An unverified API project may face restrictions on public uploads. If the token expires, rerun the helper and replace the GitHub secret.

Official docs: [YouTube video upload](https://developers.google.com/youtube/v3/guides/uploading_a_video), [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert), [OAuth credentials](https://developers.google.com/youtube/registering_an_application).

## 6. Set up Instagram Reels publishing

Instagram API publishing requires an eligible Instagram **Professional** account (Business or Creator) and a Meta app. For the Facebook Login flow implemented here, connect the Instagram professional account to a Facebook Page and obtain a Page access token with the appropriate Instagram publishing permissions. Personal/consumer accounts are not eligible for this publishing API flow.

1. In Meta for Developers, create an app and add the Instagram/Facebook Login products needed for the chosen API flow.
2. Connect the Instagram Professional account to a Facebook Page.
3. Grant the required permissions for account access and content publishing (for the Facebook Login path, typically `instagram_basic`, `instagram_content_publish`, and `pages_read_engagement`; Meta may require additional permissions or review depending on how the app is used).
4. Obtain the Instagram professional account ID and a Page access token; store them as `INSTAGRAM_USER_ID` and `INSTAGRAM_ACCESS_TOKEN` secrets.
5. Set `INSTAGRAM_GRAPH_VERSION` to a supported version for your app.
6. Create a Cloudinary account and copy the cloud name, API key, and API secret into the named variable/secrets above.
7. Test with `PUBLISH_ENABLED=true` while YouTube privacy is `private`; inspect the Instagram Reel and logs before relying on daily publishing.

The code uploads each rendered MP4 to Cloudinary, creates a Reel media container using that unique HTTPS URL, waits for processing, and then calls `media_publish`. Meta fetches the media from the public URL, so the file must remain reachable during processing. Check the current official docs for permissions, professional-account requirements, rate limits and supported video format: [Instagram Content Publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/).

## 7. Exact first deployment sequence

1. Upload the project to GitHub, keeping `.github/workflows/daily.yml` in place.
2. Run a manual workflow with all publishing disabled. Confirm the MP4 renders.
3. Configure an LLM endpoint; run again and check `story.json` for coherent prompt-specific scenes.
4. Configure ComfyUI; set `REQUIRE_AI_IMAGES=true`; run again and verify that scene images are AI-generated.
5. Configure YouTube OAuth secrets. Keep `PUBLISH_ENABLED=false` while validating configuration; then test with publishing enabled and `YOUTUBE_PRIVACY=private`.
6. Configure Instagram/Meta and Cloudinary credentials. Run once and confirm both platform IDs appear in logs.
7. Only after verifying the results, choose the appropriate YouTube privacy/audience settings and let the daily schedule run.

## Local setup and tests

Requires Python 3.11+, FFmpeg, and optionally `espeak-ng`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # edit .env for local configuration; never commit it
python -m unittest -v
python main.py --check
python main.py --prompt "A friendly little cloud learns to share rain with a garden" --dry-run
```

Outputs are written to `output/<run-id>/`. `runs.sqlite3` is a local run ledger. GitHub-hosted runners are ephemeral, so the SQLite ledger does not persist across scheduled runs; the workflow artifact preserves output files for seven days. If you need durable run history or retry protection across runs, add an external database or storage-backed ledger.

## Safety, copyright and reliability

- Start with publishing disabled and YouTube privacy set to private.
- Review every output before public publishing until you trust the pipeline.
- Mark YouTube audience settings accurately; do not assume every video is child-directed just because the project is for kids.
- Use original characters, properly licensed models, fonts, voices and music. This project does not add background music.
- Automated AI generation can produce confusing or unsuitable scenes. Add moderation/review before unattended public posting if the channel is intended for children.
- Never commit tokens or expose model servers without authentication.
- The current workflow runs daily, not continuously. A GitHub schedule is best-effort and free-tier minutes/storage limits apply.
