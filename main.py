"""Prompt-driven kids video generator; all project source files live at repository root."""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import hashlib
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
OUTPUT_ROOT = ROOT / "output"
DB_PATH = ROOT / "runs.sqlite3"
W, H = 720, 1280
PALETTES = [
    ((255, 232, 190), (255, 190, 190), (90, 55, 90)),
    ((201, 236, 255), (227, 215, 255), (45, 60, 105)),
    ((221, 248, 209), (255, 239, 190), (50, 80, 65)),
    ((255, 221, 239), (220, 232, 255), (95, 55, 90)),
    ((225, 230, 255), (255, 232, 190), (45, 55, 100)),
]

DEFAULT_PROMPT = "A gentle original story about a little animal learning kindness and helping a friend."
SAFE_RULES = (
    "Create an original, child-appropriate story. No violence, peril, frightening imagery, "
    "unsafe instructions, personal data, copyrighted characters, or unlicensed songs."
)

def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}

def retry_request(method, url, attempts=3, **kwargs):
    last = None
    for attempt in range(attempts):
        try:
            response = requests.request(method, url, timeout=kwargs.pop("timeout", 45), **kwargs)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"HTTP request failed after {attempts} attempts: {last}")

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY, prompt TEXT NOT NULL, status TEXT NOT NULL,
            video_path TEXT, created_at TEXT NOT NULL, error TEXT
        )""")

def record_run(run_id, prompt, status, video_path=None, error=None):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT OR REPLACE INTO runs(run_id,prompt,status,video_path,created_at,error) VALUES(?,?,?,?,?,?)",
            (run_id, prompt, status, str(video_path or ""), datetime.now(timezone.utc).isoformat(), str(error or "")),
        )

def validate_story(story):
    if not isinstance(story, dict):
        raise ValueError("Story response must be a JSON object.")
    for key in ("title", "description", "lesson", "scenes"):
        if key not in story:
            raise ValueError(f"Story missing required key: {key}")
    if not isinstance(story["scenes"], list) or len(story["scenes"]) != 5:
        raise ValueError("Story must contain exactly five scenes.")
    for i, scene in enumerate(story["scenes"]):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene {i+1} must be an object.")
        for key in ("heading", "text", "visual"):
            if not str(scene.get(key, "")).strip():
                raise ValueError(f"Scene {i+1} missing {key}.")
            scene[key] = str(scene[key])[:600]
    story["title"] = str(story["title"])[:90]
    story["description"] = str(story["description"])[:500]
    story["lesson"] = str(story["lesson"])[:300]
    return story

def local_plan(prompt):
    """Prompt-aware fallback; visual theme and story beats use the user's creative brief."""
    brief = re.sub(r"\s+", " ", prompt).strip()[:500]
    if not brief:
        brief = DEFAULT_PROMPT
    subject = brief.split(".")[0][:90]
    return validate_story({
        "title": subject[:75] or "A Little Kindness",
        "description": f"An original illustrated kids story inspired by this prompt: {brief}",
        "lesson": "Small acts of kindness can make a big difference.",
        "scenes": [
            {"heading": "A New Day", "text": f"Our story begins with this idea: {brief}", "visual": f"bright friendly children's illustration, {brief}, sunny opening scene"},
            {"heading": "A Little Challenge", "text": "Something small happens, and our little hero pauses to think of a kind solution.", "visual": f"friendly storybook scene inspired by {brief}, thoughtful character, gentle colors"},
            {"heading": "A Helpful Idea", "text": "The hero notices how a little help could make things better for everyone.", "visual": f"hopeful colorful illustration, {brief}, character discovers a helpful idea"},
            {"heading": "Working Together", "text": "With patience and teamwork, the friends take one small step at a time.", "visual": f"joyful teamwork scene, {brief}, warm storybook art"},
            {"heading": "A Happy Ending", "text": "Everyone smiles, and the hero learns that kindness is always worth sharing.", "visual": f"happy ending, {brief}, bright gentle children's picture book illustration"},
        ],
    })

def generate_story(prompt):
    base = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("LLM_MODEL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not base or not model:
        return local_plan(prompt)
    instruction = (
        "Return ONLY valid JSON with keys title, description, lesson, scenes. "
        "scenes must contain exactly 5 objects with heading, text, visual. "
        "Write an original, coherent 30-60 second children's story based on this creative brief. "
        "Make every scene visibly distinct and the visual prompt concrete, describing character, setting, action, composition and lighting. "
        + SAFE_RULES + "\nCreative brief: " + prompt
    )
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = retry_request(
            "POST", base + "/chat/completions", headers=headers,
            json={"model": model, "messages": [{"role": "user", "content": instruction}], "temperature": 0.8},
            timeout=90,
        )
        content = response.json()["choices"][0]["message"]["content"]
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
        return validate_story(json.loads(content))
    except Exception as exc:
        print(f"WARNING: LLM planning failed; using local prompt-aware fallback: {exc}")
        return local_plan(prompt)

def get_font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def wrap_text(text, width=37):
    import textwrap
    return "\n".join(textwrap.wrap(str(text), width=width))

def gradient(size, top, bottom):
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(size[1]):
        ratio = y / max(1, size[1] - 1)
        color = tuple(int(top[i] * (1-ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, size[0], y), fill=color)
    return image

def draw_star(draw, cx, cy, radius, fill):
    import math
    points = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        r = radius if i % 2 == 0 else radius * 0.43
        points.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
    draw.polygon(points, fill=fill)

def render_card(story, scene, idx, output_path):
    top, bottom, ink = PALETTES[idx % len(PALETTES)]
    image = gradient((W, H), top, bottom)
    draw = ImageDraw.Draw(image, "RGBA")
    for x, y, radius in [(80,130,20),(620,160,24),(95,390,12),(620,470,14),(580,740,10)]:
        draw_star(draw, x, y, radius, (255,255,255,190))
    draw.ellipse((70, 470, 650, 1030), fill=(255,255,255,100))
    draw.rounded_rectangle((48, 48, 672, 120), radius=28, fill=(255,255,255,190))
    draw.text((W//2, 84), f"LITTLE STORY  •  {idx+1}/5", font=get_font(24, True), fill=ink, anchor="mm")
    visual = (scene.get("visual", "") + " " + scene.get("text", "")).lower()
    cx, cy = W//2, 640
    # Simple visuals are intentionally generic; prompt text remains prominent.
    if any(k in visual for k in ("star", "moon", "night", "sky", "space")):
        draw_star(draw, cx, cy, 150, (255,220,75,255))
        draw.ellipse((cx-48,cy-5,cx-25,cy+18), fill=ink)
        draw.ellipse((cx+25,cy-5,cx+48,cy+18), fill=ink)
        draw.arc((cx-40,cy+15,cx+40,cy+75), 0, 180, fill=ink, width=6)
    elif any(k in visual for k in ("flower", "seed", "sprout", "garden", "plant", "tree")):
        draw.rectangle((cx-12, cy+20, cx+12, cy+220), fill=(75,145,80,255))
        draw.ellipse((cx-115,cy-15,cx+5,cy+85), fill=(95,180,100,255))
        draw.ellipse((cx-5,cy-95,cx+115,cy+10), fill=(95,180,100,255))
        draw.ellipse((cx-60,cy-125,cx+60,cy-5), fill=(255,150,190,255))
        draw.ellipse((cx-28,cy-88,cx+28,cy-32), fill=(255,220,70,255))
        draw.rounded_rectangle((cx-150,cy+190,cx+150,cy+300), radius=24, fill=(180,115,80,255))
    else:
        # Generic friendly mascot face.
        draw.ellipse((cx-145, cy-145, cx-70, cy+5), fill=(255,255,255,230), outline=ink, width=5)
        draw.ellipse((cx+70, cy-145, cx+145, cy+5), fill=(255,255,255,230), outline=ink, width=5)
        draw.ellipse((cx-170, cy-70, cx+170, cy+270), fill=(255,255,255,245), outline=ink, width=6)
        draw.ellipse((cx-75,cy+35,cx-45,cy+65), fill=ink)
        draw.ellipse((cx+45,cy+35,cx+75,cy+65), fill=ink)
        draw.ellipse((cx-20,cy+65,cx+20,cy+90), fill=(235,120,150,255))
        draw.arc((cx-60,cy+75,cx+60,cy+155), 10, 170, fill=ink, width=5)
    draw.rounded_rectangle((38, 930, 682, 1195), radius=32, fill=(255,255,255,235))
    draw.text((W//2, 974), wrap_text(scene["heading"], 28), font=get_font(31, True), fill=ink, anchor="mm", align="center")
    draw.multiline_text((W//2, 1060), wrap_text(scene["text"], 39), font=get_font(25), fill=(40,45,60), anchor="mm", align="center", spacing=10)
    image.save(output_path)

def comfyui_image(scene_prompt, output_path):
    """Optional ComfyUI API workflow adapter; requires an API-format workflow and node IDs."""
    base = os.getenv("COMFYUI_BASE_URL", "").strip().rstrip("/")
    workflow_raw = os.getenv("COMFYUI_WORKFLOW_JSON", "").strip()
    prompt_node = os.getenv("COMFYUI_PROMPT_NODE_ID", "").strip()
    save_node = os.getenv("COMFYUI_SAVE_NODE_ID", "").strip()
    if not all([base, workflow_raw, prompt_node, save_node]):
        return False
    try:
        workflow = json.loads(workflow_raw)
        if prompt_node not in workflow or save_node not in workflow:
            raise ValueError("Configured ComfyUI node ID not found in workflow.")
        workflow[prompt_node].setdefault("inputs", {})["text"] = scene_prompt + ", child-friendly original storybook illustration, no text, no watermark"
        queued = retry_request("POST", base + "/prompt", json={"prompt": workflow}, timeout=60).json()
        prompt_id = queued.get("prompt_id")
        if not prompt_id:
            raise RuntimeError("ComfyUI did not return prompt_id.")
        deadline = time.time() + 240
        history = None
        while time.time() < deadline:
            time.sleep(3)
            h = retry_request("GET", f"{base}/history/{prompt_id}", timeout=30).json()
            history = h.get(prompt_id)
            if history and history.get("outputs"):
                break
        if not history:
            raise TimeoutError("ComfyUI generation timed out.")
        outputs = history.get("outputs", {})
        images = outputs.get(save_node, {}).get("images", [])
        if not images:
            # A SaveImage node may have a different ID in some workflows; search outputs.
            for output in outputs.values():
                if output.get("images"):
                    images = output["images"]
                    break
        if not images:
            raise RuntimeError("No images found in ComfyUI output history.")
        item = images[0]
        params = {"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")}
        data = retry_request("GET", base + "/view", params=params, timeout=60).content
        output_path.write_bytes(data)
        with Image.open(output_path) as im:
            im.verify()
        return True
    except Exception as exc:
        print(f"WARNING: ComfyUI image generation failed: {exc}")
        if env_bool("REQUIRE_AI_IMAGES", False):
            raise
        return False

def make_audio(text, out_wav, language):
    binary = shutil.which("espeak-ng") or shutil.which("espeak")
    if not binary:
        print("WARNING: espeak-ng not installed; video will have no narration.")
        return None
    voice = "ta" if language.lower().startswith("ta") else "en"
    try:
        subprocess.run([binary, "-v", voice, "-s", "145", "-w", str(out_wav), text], check=True, timeout=120)
        return out_wav
    except Exception as exc:
        print(f"WARNING: TTS failed ({exc}); rendering without narration.")
        return None

def run_ffmpeg(args, timeout=240):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg not found. Install FFmpeg and ensure it is on PATH.")
    subprocess.run(args, check=True, timeout=timeout, capture_output=True, text=True)

def render_video(story, out_dir, language="en", duration=45):
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    scenes = story["scenes"]
    per_scene = max(4, int(duration / len(scenes)))
    for idx, scene in enumerate(scenes):
        frame = frames_dir / f"scene_{idx:02d}.png"
        if not comfyui_image(scene["visual"], frame):
            render_card(story, scene, idx, frame)
    clips = []
    for idx in range(len(scenes)):
        clip = frames_dir / f"clip_{idx:02d}.mp4"
        run_ffmpeg([
            "ffmpeg", "-y", "-loop", "1", "-i", str(frames_dir / f"scene_{idx:02d}.png"),
            "-t", str(per_scene), "-vf",
            "scale=800:1422,zoompan=z='min(zoom+0.0008,1.04)':d=125:s=720x1280:fps=25,format=yuv420p",
            "-r", "25", "-an", "-c:v", "libx264", "-preset", "veryfast", str(clip)
        ])
        clips.append(clip)
    concat = frames_dir / "concat.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips), encoding="utf-8")
    silent = out_dir / "silent.mp4"
    run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(silent)])
    narration = " ".join(scene["text"] for scene in scenes) + " " + story["lesson"]
    audio = make_audio(narration, out_dir / "narration.wav", language)
    final = out_dir / "kids_story.mp4"
    if audio and audio.exists():
        run_ffmpeg(["ffmpeg", "-y", "-i", str(silent), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(final)])
    else:
        shutil.copy2(silent, final)
    with Image.open(frames_dir / "scene_00.png") as im:
        im.convert("RGB").save(out_dir / "thumbnail.jpg", quality=90)
    # Verify the final file with ffprobe when available.
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration,size", "-of", "json", str(final)], check=True, capture_output=True, text=True, timeout=30)
        probe = json.loads(result.stdout).get("format", {})
        if float(probe.get("duration", 0)) < 5 or int(probe.get("size", 0)) < 50000:
            raise RuntimeError("Final video failed duration/size validation.")
    elif final.stat().st_size < 50000:
        raise RuntimeError("Final video is unexpectedly small.")
    return final

def youtube_upload(video_path, title, description):
    required = [os.getenv(k, "").strip() for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")]
    if not all(required):
        print("YouTube skipped: OAuth credentials not configured.")
        return None
    client_id, client_secret, refresh_token = required
    token_response = retry_request("POST", "https://oauth2.googleapis.com/token", data={
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    }, timeout=45).json()
    access = token_response["access_token"]
    metadata = {
        "snippet": {"title": title[:100], "description": description[:5000], "categoryId": "22",
                    "tags": ["kids story", "children story", "learning"]},
        "status": {"privacyStatus": os.getenv("YOUTUBE_PRIVACY", "private"),
                   "selfDeclaredMadeForKids": env_bool("YOUTUBE_MADE_FOR_KIDS", True),
                   "containsSyntheticMedia": env_bool("YOUTUBE_CONTAINS_SYNTHETIC_MEDIA", False)},
    }
    init = retry_request("POST", "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json",
                 "X-Upload-Content-Type": "video/mp4"}, json=metadata, timeout=45)
    upload_url = init.headers.get("Location")
    if not upload_url:
        raise RuntimeError("YouTube did not return resumable upload URL.")
    with open(video_path, "rb") as stream:
        result = retry_request("PUT", upload_url, headers={"Authorization": f"Bearer {access}",
            "Content-Type": "video/mp4"}, data=stream, timeout=600)
    video_id = result.json().get("id")
    print(f"YouTube upload successful: {video_id}")
    return video_id

def cloudinary_upload_video(video_path, run_id):
    """Upload this run's MP4 to Cloudinary so Instagram can fetch a unique public HTTPS URL."""
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
    if not all([cloud_name, api_key, api_secret]):
        print("Instagram skipped: Cloudinary cloud name, API key, and API secret are required to host this run's MP4.")
        return None
    timestamp = str(int(time.time()))
    public_id = f"kids-video-factory/{run_id}"
    params = {"public_id": public_id, "timestamp": timestamp}
    to_sign = "&".join(f"{key}={params[key]}" for key in sorted(params)) + api_secret
    signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/video/upload"
    with open(video_path, "rb") as file_obj:
        response = requests.post(
            url,
            data={**params, "api_key": api_key, "signature": signature},
            files={"file": (Path(video_path).name, file_obj, "video/mp4")},
            timeout=(30, 600),
        )
    response.raise_for_status()
    result = response.json()
    secure_url = result.get("secure_url")
    if not secure_url or not secure_url.startswith("https://"):
        raise RuntimeError("Cloudinary upload did not return a public HTTPS URL.")
    print(f"Uploaded current-run video to Cloudinary: {secure_url}")
    return secure_url

def instagram_publish(caption, media_url):
    """Publish a Reel using Meta's Graph API (Facebook Login path)."""
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    user_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
    version = os.getenv("INSTAGRAM_GRAPH_VERSION", "").strip()
    if not all([token, user_id, version, media_url]):
        print("Instagram skipped: Meta token, Instagram professional account ID, API version, and hosted video URL are required.")
        return None
    parsed = urlparse(media_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Instagram media URL must be an HTTPS URL.")
    base = f"https://graph.facebook.com/{version}/{user_id}"
    create = retry_request("POST", base + "/media", data={
        "media_type": "REELS", "video_url": media_url, "caption": caption[:2200],
        "share_to_feed": "true", "access_token": token
    }, timeout=60).json()
    container_id = create.get("id")
    if not container_id:
        raise RuntimeError(f"Instagram did not return a media container ID: {create}")
    for _ in range(36):
        time.sleep(5)
        status = retry_request("GET", f"https://graph.facebook.com/{version}/{container_id}",
            params={"fields": "status_code,status", "access_token": token}, timeout=30).json()
        state = status.get("status_code")
        if state == "FINISHED":
            break
        if state in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram media processing failed: {status}")
    else:
        raise TimeoutError("Instagram media container processing timed out.")
    result = retry_request("POST", base + "/media_publish",
        data={"creation_id": container_id, "access_token": token}, timeout=60).json()
    media_id = result.get("id")
    if not media_id:
        raise RuntimeError(f"Instagram publishing failed: {result}")
    print(f"Instagram publishing successful: {media_id}")
    return media_id

def main():
    parser = argparse.ArgumentParser(description="Generate a prompt-driven illustrated kids story video.")
    parser.add_argument("--prompt", default=os.getenv("VIDEO_PROMPT", DEFAULT_PROMPT), help="Creative brief for the video.")
    parser.add_argument("--dry-run", action="store_true", help="Render only; never publish.")
    parser.add_argument("--check", action="store_true", help="Check runtime dependencies and config.")
    args = parser.parse_args()
    if args.check:
        missing = [name for name in ("ffmpeg",) if not shutil.which(name)]
        print(json.dumps({"python": sys.version.split()[0], "ffmpeg": shutil.which("ffmpeg"),
                          "espeak": shutil.which("espeak-ng") or shutil.which("espeak"),
                          "comfyui_configured": bool(os.getenv("COMFYUI_BASE_URL") and os.getenv("COMFYUI_WORKFLOW_JSON")),
                          "llm_configured": bool(os.getenv("LLM_BASE_URL") and os.getenv("LLM_MODEL")),
                          "youtube_configured": all(os.getenv(k, "").strip() for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")),
                          "instagram_configured": all(os.getenv(k, "").strip() for k in ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID", "INSTAGRAM_GRAPH_VERSION", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")),
                          "missing": missing}, indent=2))
        return 1 if missing else 0
    prompt = args.prompt.strip()
    if not prompt:
        raise SystemExit("Prompt is empty. Use --prompt or set VIDEO_PROMPT.")
    init_db()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    out_dir = OUTPUT_ROOT / run_id
    record_run(run_id, prompt, "RUNNING")
    try:
        story = generate_story(prompt)
        (out_dir := OUTPUT_ROOT / run_id).mkdir(parents=True, exist_ok=True)
        (out_dir / "story.json").write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
        duration = int(os.getenv("VIDEO_DURATION_SECONDS", "45"))
        duration = max(20, min(duration, 60))
        video = render_video(story, out_dir, os.getenv("VIDEO_LANGUAGE", "en"), duration)
        title = f"{os.getenv('VIDEO_TITLE_PREFIX', 'Little Story')}: {story['title']}"
        description = story["description"] + "\n\n" + story["lesson"] + "\n\nOriginal illustrated story."
        meta = {"run_id": run_id, "prompt": prompt, "title": title, "description": description,
                "video": str(video), "bytes": video.stat().st_size, "generated_at": datetime.now(timezone.utc).isoformat()}
        (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        record_run(run_id, prompt, "RENDERED", video)
        print(f"Rendered video: {video}")
        if env_bool("PUBLISH_ENABLED", False) and not args.dry_run:
            yt = youtube_upload(video, title, description)
            ig = None
            if all(os.getenv(k, "").strip() for k in (
                "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID", "INSTAGRAM_GRAPH_VERSION"
            )):
                media_url = cloudinary_upload_video(video, run_id)
                if media_url:
                    ig = instagram_publish(title + "\n\n" + description + "\n#KidsStories #Learning", media_url)
            record_run(run_id, prompt, "PUBLISHED" if yt or ig else "RENDERED", video)
            print(json.dumps({"youtube_video_id": yt, "instagram_media_id": ig}, indent=2))
        else:
            print("Publishing disabled or dry-run. Inspect video before enabling public uploads.")
        return 0
    except Exception as exc:
        record_run(run_id, prompt, "FAILED", error=exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

if __name__ == "__main__":
    raise SystemExit(main())
