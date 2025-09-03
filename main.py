import os, re, textwrap, subprocess, shlex
from typing import List, Optional
import itertools
from pathlib import Path
import shutil
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
import socketserver

import click
from dotenv import load_dotenv
from rich import print
from rich.console import Console

# TMDb
import tmdbsimple as tmdb

# Wikipedia
import wikipediaapi

# OpenAI
from openai import OpenAI

console = Console()


# ---------------------- Wikipedia + TMDb ----------------------


def resolve_to_imdb_id(title: str, year: Optional[int]) -> tuple[str, str]:
    """Return (imdb_id, tmdb_title)"""
    search = tmdb.Search()
    data = search.movie(query=title) or {}
    results = data.get("results", [])
    if year:
        results = [
            r for r in results if str(r.get("release_date", "")).startswith(str(year))
        ]
    if not results:
        raise click.ClickException("TMDb: no results for that title or year")
    m = results[0]
    tmdb_title = m.get("title") or title
    mid = m["id"]
    ex = tmdb.Movies(mid).external_ids()
    imdb_id = ex.get("imdb_id")
    if not imdb_id:
        raise click.ClickException("TMDb: could not find IMDb ID via external_ids")
    return imdb_id, tmdb_title


def _wiki_client():
    ua = os.getenv("WIKI_USER_AGENT")
    if not ua:
        ua = "VibeMoviePodcast/0.1 (+https://example.com; contact@example.com)"
    return wikipediaapi.Wikipedia(language="en", user_agent=ua)


def _wiki_candidate_titles(title: str, year: Optional[int]) -> List[str]:
    cand = [title]
    if year:
        cand.append(f"{title} ({year} film)")
    cand.append(f"{title} (film)")
    # dedupe
    seen, out = set(), []
    for c in cand:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


def _collect_relevant_sections(page: wikipediaapi.WikipediaPage) -> List[str]:
    keep = {
        "Production",
        "Development",
        "Pre-production",
        "Casting",
        "Filming",
        "Post-production",
        "Visual effects",
        "Music",
        "Release",
        "Marketing",
        "Reception",
        "Box office",
        "Accolades",
        "Legacy",
    }
    texts: List[str] = []

    def walk(sec):
        if sec.title in keep:
            texts.append(f"{sec.title}\n{sec.text}")
        for child in sec.sections:
            walk(child)

    for s in page.sections:
        walk(s)
    return texts


def fetch_trivia_from_wikipedia(
    title: str, year: Optional[int], max_chars: int = 12000
) -> List[str]:
    wiki = _wiki_client()
    page = None
    for cand in _wiki_candidate_titles(title, year):
        p = wiki.page(cand)
        if p.exists():
            page = p
            break
    if not page:
        raise click.ClickException("Wikipedia page not found for this title")

    chunks = _collect_relevant_sections(page)
    if not chunks:
        chunks = [page.text]

    content = "\n\n".join(chunks)[:max_chars]

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = f"""From the notes below about the film "{title}", extract 12 short, punchy trivia facts.
Each fact must be one sentence under 220 characters. Avoid quotes and spoilers. Paraphrase rather than copying.
Return one bullet per line, no numbering.

Notes:
{content}"""

    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    raw = resp.choices[0].message.content.strip().splitlines()
    bullets = []
    for line in raw:
        t = re.sub(r"^[\-\*\d\.\)\s]+", "", line).strip()
        t = re.sub(r"\s+", " ", t)
        if t:
            bullets.append(textwrap.shorten(t, width=320, placeholder="…"))
    return bullets


# ---------------------- Script writing ----------------------

SYSTEM_PROMPT = """You are a scriptwriter for a short two-person movie trivia podcast.
Write a clean, friendly dialogue that alternates speakers on each line.
Follow these rules:
- Speakers must be exactly the two names provided.
- One to two sentence intro for the podcast introducing topics they will be discussing, then a sequence of trivia beats, then a one line outro.
- For intro use words like "Welcome to...", and for outro use words like "Thanks for listening..."
- Each trivia beat is 1 to 2 sentences from the lead speaker, then a 1 sentence reaction from the other.
- Keep lines under 220 characters.
- Avoid profanity and complicated punctuation.
- For one of the trivia beats, let one speaker ask the other speaker to sing about it.
- For one of the trivia beats, make sure the speakers get into an emotional heated argument.
Return only the dialogue lines, one per line in the format:
Speaker: text"""


def write_dialogue(
    openai_model: str, title: str, speakers: List[str], bullets: List[str]
) -> str:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    speakerA, speakerB = speakers
    bullets_block = "\n".join(f"- {b}" for b in bullets)
    user_content = (
        f"Movie title: {title}\n"
        f"Speakers: {speakerA}, {speakerB}\n"
        f"Trivia bullets:\n{bullets_block}\n"
        "Write the script now."
    )
    resp = client.chat.completions.create(
        model=openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


def to_vibevoice_numbered_script(script_text: str, speakers: List[str]) -> str:
    name_to_num = {speakers[0].lower(): "1", speakers[1].lower(): "2"}
    out_lines = []
    turn_cycle = itertools.cycle(["1", "2"])
    for raw in script_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("speaker 1:") or line.lower().startswith(
            "speaker 2:"
        ):
            out_lines.append(line)
            continue
        if ":" in line:
            left, right = line.split(":", 1)
            key = left.strip().lower()
            num = name_to_num.get(key)
            if num:
                out_lines.append(f"Speaker {num}: {right.strip()}")
                continue
        num = next(turn_cycle)
        out_lines.append(f"Speaker {num}: {line}")
    return "\n".join(out_lines)


# ---------------------- Voices and inference ----------------------


def list_available_voices(vibevoice_dir: str) -> List[str]:
    """Return voice basenames like en-Alice_woman, en-Frank_man, ..."""
    voices_dir = Path(vibevoice_dir) / "demo" / "voices"
    if not voices_dir.is_dir():
        return []
    return sorted([p.stem for p in voices_dir.glob("*.wav")])


def voice_to_speaker_label(voice_basename: str) -> str:
    """
    Map en-Alice_woman -> Alice
    zh-Xinran_woman -> Xinran
    in-Samuel_man -> Samuel
    """
    try:
        _, tail = voice_basename.split("-", 1)
        name = tail.split("_", 1)[0]
        return name
    except Exception:
        return voice_basename


def run_vibevoice_once(
    vibevoice_dir: str,
    model_name: str,
    txt_path: str,
    speakers: List[str],
    out_wav: str,
) -> None:
    speakers_arg = " ".join(speakers)
    outdir = "outputs"
    txt_abs = str(Path(txt_path).resolve())
    cmd = (
        f"python demo/inference_from_file.py "
        f"--model_path {shlex.quote(model_name)} "
        f"--txt_path {shlex.quote(txt_abs)} "
        f"--speaker_names {speakers_arg} "
        f"--output_dir {shlex.quote(outdir)}"
    )
    console.rule("[bold]VibeVoice generation")
    console.print(cmd)
    subprocess.run(cmd, shell=True, check=True, cwd=vibevoice_dir)

    outdir_abs = Path(vibevoice_dir) / outdir
    candidates = sorted(outdir_abs.glob("*.wav"))
    if not candidates:
        raise click.ClickException(f"No WAV found in {outdir_abs}")
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    shutil.copy2(latest, out_wav)
    console.print(f"Copied {latest} -> {out_wav}")


def run_vibevoice_with_fallback(
    vibevoice_dir: str,
    primary_model: str,
    fallback_model: str,
    txt_path: str,
    speakers: List[str],
    out_wav: str,
) -> None:
    try:
        run_vibevoice_once(vibevoice_dir, primary_model, txt_path, speakers, out_wav)
        return
    except subprocess.CalledProcessError as e:
        console.print("[yellow]Primary model failed. Trying fallback.[/]")
        run_vibevoice_once(vibevoice_dir, fallback_model, txt_path, speakers, out_wav)


# ------------------ Helpers ----------------------

SUPPORTED_MODELS = ["microsoft/VibeVoice-Large", "microsoft/VibeVoice-1.5B"]


def _hf_model_cached(model_id: str) -> bool:
    """Best-effort check for a cached HF model on disk."""
    cache_root = (
        Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    )
    try:
        org, name = model_id.split("/", 1)
    except ValueError:
        return False
    model_dir = cache_root / f"models--{org}--{name}"
    return model_dir.exists()


def _pick_model_interactively(default_model: str) -> str:
    """
    Always prompt for a model when --model is not provided.
    Annotate choices with [cached] if present locally, otherwise [download].
    """
    choices = SUPPORTED_MODELS

    def label(m: str) -> str:
        return f"{m} [cached]" if _hf_model_cached(m) else f"{m} [download]"

    click.echo("Choose VibeVoice model for this run:")
    for i, m in enumerate(choices, 1):
        click.echo(f"{i}. {label(m)}")

    default_idx = choices.index(default_model) + 1 if default_model in choices else 1
    idx = click.prompt(
        f"Pick a model [default: {label(choices[default_idx - 1])}]",
        type=int,
        default=default_idx,
    )
    if idx < 1 or idx > len(choices):
        raise click.ClickException("Invalid model choice")
    return choices[idx - 1]


def normalize_outfile_name(name: str) -> str:
    """
    Accepts a base name or a full name; returns '<basename>.wav'.
    Strips any audio extension the user typed by habit.
    """
    base = os.path.basename(name).strip()
    # remove common audio extensions if user typed one
    base = re.sub(r"\.(wav|mp3|flac|m4a|ogg)$", "", base, flags=re.IGNORECASE)
    # fallback if user left it empty
    if not base:
        base = "podcast"
    return f"{base}.wav"


# ---------------------- Web Server ----------------------


class PodcastHTTPRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With")
        super().end_headers()

    def log_message(self, format, *args):
        # Suppress default logging to keep output clean
        pass


def start_web_server(directory: str, port: int = 22034):
    """Start a simple web server to serve podcast files"""
    os.chdir(directory)

    class QuietHTTPRequestHandler(PodcastHTTPRequestHandler):
        pass

    try:
        with socketserver.TCPServer(("", port), QuietHTTPRequestHandler) as httpd:
            console.print(f"[green]Web server started at http://localhost:{port}[/]")
            console.print(f"[green]Serving files from: {directory}[/]")
            console.print(f"[green]Press Ctrl+C to stop the server[/]")
            console.print(f"[cyan]Note: On RunPod, access via http://YOUR_IP:{port}[/]")

            # Open browser if possible
            try:
                import webbrowser

                webbrowser.open(f"http://localhost:{port}")
            except:
                pass

            httpd.serve_forever()
    except KeyboardInterrupt:
        console.print("[yellow]Web server stopped[/]")
    except OSError as e:
        console.print(f"[red]Could not start web server: {e}[/]")
        console.print(
            "[yellow]You can still access files directly from the podcast_files directory[/]"
        )


@click.command()
@click.option("--title", default=None, help="Movie title")
@click.option("--year", type=int, default=None, help="Release year")
@click.option("--max-trivia", type=int, default=10)
@click.option(
    "--speakers", default=None, help="Comma separated names. Example: Alice,Frank"
)
@click.option(
    "--outfile",
    default=None,
    help="Output file name without extension. .wav is added automatically.",
)
@click.option(
    "--no-server",
    is_flag=True,
    default=False,
    help="Skip starting the web server after generation",
)
def cli(
    title: Optional[str],
    year: Optional[int],
    max_trivia: int,
    speakers: Optional[str],
    outfile: str,
    model: Optional[str],
    no_server: bool,
):
    load_dotenv()

    # Keys and paths
    tmdb_key = os.getenv("TMDB_API_KEY")
    if not tmdb_key:
        raise click.ClickException("Missing TMDB_API_KEY in env")
    tmdb.API_KEY = tmdb_key
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise click.ClickException("Missing OPENAI_API_KEY in env")

    # Pick model and fallback
    env_primary = os.getenv("VIBEVOICE_MODEL", "microsoft/VibeVoice-Large")
    env_fallback = os.getenv("VIBEVOICE_FALLBACK_MODEL", "microsoft/VibeVoice-1.5B")

    # If user passed --model, that wins. Otherwise prompt every time.
    primary_model = model or _pick_model_interactively(env_primary)

    # Fallback is the other model
    if primary_model == "microsoft/VibeVoice-Large":
        fallback_model = "microsoft/VibeVoice-1.5B"
    else:
        fallback_model = "microsoft/VibeVoice-Large"

    console.print(
        f"Primary model: [bold]{primary_model}[/], Fallback: [bold]{fallback_model}[/]"
    )

    vibevoice_dir = os.getenv("VIBEVOICE_DIR")
    if not vibevoice_dir or not os.path.isdir(vibevoice_dir):
        raise click.ClickException("Set VIBEVOICE_DIR to your VibeVoice checkout path")

    # Interactive prompts if not provided
    if not title:
        title = click.prompt("Movie title", type=str)
    if year is None:
        if click.confirm("Specify release year", default=True):
            year = click.prompt("Year", type=int)
        else:
            year = None

    # Resolve ID and fetch bullets
    console.rule("[bold]Resolving title on TMDb")
    imdb_id, resolved_title = resolve_to_imdb_id(title, year)
    console.print(f"IMDb ID: [bold]{imdb_id}[/] for [bold]{resolved_title}[/]")

    console.rule("[bold]Fetching source notes from Wikipedia")
    bullets = fetch_trivia_from_wikipedia(resolved_title, year)
    if not bullets:
        raise click.ClickException("Could not extract trivia bullets from Wikipedia")
    trivia = bullets[:max_trivia]
    for idx, t in enumerate(trivia, 1):
        console.print(f"[cyan]Trivia {idx}[/]: {t}")

    # Speakers selection
    if speakers:
        spk = [s.strip() for s in speakers.split(",") if s.strip()]
        if len(spk) != 2:
            raise click.ClickException("Provide exactly two speaker names")
    else:
        # List voices from repo
        available = list_available_voices(vibevoice_dir)
        if not available:
            console.print(
                "[yellow]No voice files found. Falling back to Alice, Frank.[/]"
            )
            spk = ["Alice", "Frank"]
        else:
            console.rule("[bold]Choose two voices")
            for i, v in enumerate(available, 1):
                print(f"{i:2d}. {v}")
            i1 = click.prompt("Pick voice 1 (number)", type=int)
            i2 = click.prompt("Pick voice 2 (number, different from 1)", type=int)
            if (
                i1 < 1
                or i1 > len(available)
                or i2 < 1
                or i2 > len(available)
                or i1 == i2
            ):
                raise click.ClickException("Invalid voice choices")
            v1, v2 = available[i1 - 1], available[i2 - 1]
            # Convert to speaker labels expected by demo script
            spk = [voice_to_speaker_label(v1), voice_to_speaker_label(v2)]
            console.print(f"Speaker mapping: {spk[0]} <- {v1}, {spk[1]} <- {v2}")

    if not outfile:
        base = click.prompt("Output file name (no extension)", default="podcast")
        outfile = normalize_outfile_name(base)
    else:
        outfile = normalize_outfile_name(outfile)

    console.print(f"Output will be written to [bold]{outfile}[/]")

    # Write script
    console.rule("[bold]Writing dialogue with OpenAI")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    script = write_dialogue(openai_model, resolved_title, spk, trivia)
    script = to_vibevoice_numbered_script(script, spk)
    txt_path = "podcast.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(script)
    console.print(f"Saved script to {txt_path}")

    # Synthesize with model fallback
    console.rule("[bold]Synthesizing with VibeVoice")
    run_vibevoice_with_fallback(
        vibevoice_dir, primary_model, fallback_model, txt_path, spk, outfile
    )
    console.print(f"[green]Done.[/] Wrote {outfile}")

    # Create podcast_files directory and move files
    console.rule("[bold]Organizing files")
    podcast_dir = Path("podcast_files")
    podcast_dir.mkdir(exist_ok=True)

    # Move generated files to podcast_files directory
    script_dest = podcast_dir / "podcast.txt"
    audio_dest = podcast_dir / outfile

    shutil.move(txt_path, script_dest)
    shutil.move(outfile, audio_dest)

    # Create a simple HTML player
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Movie Podcast: {resolved_title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
        }}
        .container {{
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 30px;
            backdrop-filter: blur(10px);
        }}
        h1 {{
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
        }}
        .player {{
            background: rgba(255, 255, 255, 0.2);
            border-radius: 10px;
            padding: 20px;
            margin: 20px 0;
        }}
        audio {{
            width: 100%;
            margin: 10px 0;
        }}
        .files {{
            margin-top: 30px;
            padding: 20px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
        }}
        a {{
            color: #ffd700;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .info {{
            background: rgba(255, 255, 255, 0.1);
            padding: 15px;
            border-radius: 5px;
            margin: 10px 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🎬 {resolved_title}</h1>

        <div class="info">
            <strong>Speakers:</strong> {', '.join(spk)}<br>
            <strong>Trivia Facts:</strong> {len(trivia)}<br>
            <strong>Generated:</strong> {time.strftime('%Y-%m-%d %H:%M:%S')}
        </div>

        <div class="player">
            <h2>🎧 Listen to the Podcast</h2>
            <audio controls preload="metadata">
                <source src="{outfile}" type="audio/wav">
                Your browser does not support the audio element.
            </audio>
        </div>

        <div class="files">
            <h3>📁 Files</h3>
            <p><a href="podcast.txt" target="_blank">📄 View Script (podcast.txt)</a></p>
            <p><a href="{outfile}" download>⬇️ Download Audio ({outfile})</a></p>
        </div>
    </div>
</body>
</html>"""

    html_file = podcast_dir / "index.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    console.print(f"[green]Files moved to {podcast_dir}/[/]")
    console.print(f"[green]Script: {script_dest}[/]")
    console.print(f"[green]Audio: {audio_dest}[/]")
    console.print(f"[green]Player: {html_file}[/]")

    # Start web server (unless disabled)
    if not no_server:
        console.rule("[bold]Starting web server")
        console.print("[cyan]Starting web server for podcast playback...[/]")

        # Start server in a separate thread so it doesn't block
        server_thread = threading.Thread(
            target=start_web_server, args=(str(podcast_dir), 22034), daemon=True
        )
        server_thread.start()

        # Give server time to start
        time.sleep(1)

        console.print(f"[green]🎧 Podcast ready! Visit: http://localhost:22034[/]")
        console.print(f"[green]📁 Files available at: {podcast_dir}/[/]")

        # Keep the main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("[yellow]Shutting down...[/]")
    else:
        console.print(
            f"[green]🎧 Podcast generated! Files available at: {podcast_dir}/[/]"
        )
        console.print(f"[green]📁 Script: {script_dest}[/]")
        console.print(f"[green]📁 Audio: {audio_dest}[/]")
