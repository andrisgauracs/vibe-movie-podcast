import os, re, textwrap, subprocess, shlex, sys
from typing import List, Optional
import click
from dotenv import load_dotenv
from rich import print
from rich.console import Console
import shutil
from pathlib import Path
import platform
import itertools

# TMDb
import tmdbsimple as tmdb

# Wikipedia
import wikipediaapi

# OpenAI
from openai import OpenAI


def _wiki_client():
    ua = os.getenv("WIKI_USER_AGENT")
    if not ua:
        # Provide a polite default. Include a URL or email you control.
        ua = f"VibeMoviePodcast/0.1 ({platform.system()};)"
    return wikipediaapi.Wikipedia(language="en", user_agent=ua)


console = Console()


def to_vibevoice_numbered_script(script_text: str, speakers: List[str]) -> str:
    """
    Convert lines like 'Alice: Hi' / 'Frank: Hey' or unlabeled lines
    into numbered turns: 'Speaker 1: ...' / 'Speaker 2: ...'
    The numbering order follows the --speakers list.
    """
    name_to_num = {speakers[0].lower(): "1", speakers[1].lower(): "2"}
    out_lines = []
    turn_cycle = itertools.cycle(["1", "2"])

    for raw in script_text.splitlines():
        line = raw.strip()
        if not line:
            continue

        # If already in expected format, keep it
        if line.lower().startswith("speaker 1:") or line.lower().startswith(
            "speaker 2:"
        ):
            out_lines.append(line)
            continue

        # If it looks like "Name: text"
        if ":" in line:
            left, right = line.split(":", 1)
            key = left.strip().lower()
            num = name_to_num.get(key)
            if num:
                out_lines.append(f"Speaker {num}: {right.strip()}")
                continue

        # Fallback: alternate speakers
        num = next(turn_cycle)
        out_lines.append(f"Speaker {num}: {line}")

    return "\n".join(out_lines)


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


def _wiki_candidate_titles(title: str, year: Optional[int]) -> List[str]:
    # Try common film page conventions
    cand = [title]
    if year:
        cand.append(f"{title} ({year} film)")
    cand.append(f"{title} (film)")
    # Deduplicate while preserving order
    seen = set()
    out = []
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
    """Fetch source notes from Wikipedia, then ask OpenAI to convert them into trivia bullets."""
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
        # fallback to the whole page text if no target sections
        chunks = [page.text]

    # Trim content to a reasonable size for the LLM
    content = "\n\n".join(chunks)
    content = content[:max_chars]

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = f"""From the notes below about the film "{title}", extract 12 short, punchy trivia facts.
Each fact must be self-contained, one sentence, and under 220 characters. Avoid quotes and spoilers. Paraphrase rather than copying.
Return one bullet per line, with no numbering.

Notes:
{content}"""

    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    raw = resp.choices[0].message.content.strip().splitlines()
    # Clean up bullets
    bullets = []
    for line in raw:
        t = re.sub(r"^[\-\*\d\.\)\s]+", "", line).strip()
        t = re.sub(r"\s+", " ", t)
        if t:
            bullets.append(textwrap.shorten(t, width=320, placeholder="…"))
    return bullets


SYSTEM_PROMPT = """You are a scriptwriter for a short two-person movie trivia podcast.
Write a clean, friendly dialogue that alternates speakers on each line.
Follow these rules:
- Speakers must be exactly the two names provided.
- One to two sentence intro for the podcast introducing topics they will be discussing, then a sequence of trivia beats, then a one line outro.
- Each trivia beat is 1 to 2 sentences from the lead speaker, then a 1 sentence reaction from the other.
- Keep lines under 220 characters.
- Avoid profanity and complicated punctuation.
- For one of the trivia beats, let one speaker ask the other speaker to sing about it.
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


def run_vibevoice(
    vibevoice_dir: str,
    model_name: str,
    txt_path: str,
    speakers: List[str],
    out_wav: str,
) -> None:
    speakers_arg = " ".join(speakers)
    outdir = "outputs"

    # Use an absolute path so the file is found even when cwd=vibevoice_dir
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

    # Grab newest WAV from the output dir and copy to requested name
    outdir_abs = Path(vibevoice_dir) / outdir
    candidates = sorted(outdir_abs.glob("*.wav"))
    if not candidates:
        raise click.ClickException(f"No WAV found in {outdir_abs}")
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    shutil.copy2(latest, out_wav)
    console.print(f"Copied {latest} -> {out_wav}")


@click.command()
@click.option("--title", required=True, help="Movie title to use")
@click.option("--year", type=int, default=None, help="Optional release year")
@click.option("--max-trivia", type=int, default=10)
@click.option(
    "--speakers",
    default="Alex,Bailey",
    help="Comma separated names. Example: Alex,Bailey",
)
@click.option("--outfile", default="podcast.wav")
def cli(title: str, year: Optional[int], max_trivia: int, speakers: str, outfile: str):
    load_dotenv()
    # Keys and paths
    tmdb_key = os.getenv("TMDB_API_KEY")
    if not tmdb_key:
        raise click.ClickException("Missing TMDB_API_KEY in env")
    tmdb.API_KEY = tmdb_key
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise click.ClickException("Missing OPENAI_API_KEY in env")

    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    vibevoice_dir = os.getenv("VIBEVOICE_DIR")
    vibevoice_model = os.getenv("VIBEVOICE_MODEL", "microsoft/VibeVoice-1.5B")
    if not vibevoice_dir or not os.path.isdir(vibevoice_dir):
        raise click.ClickException("Set VIBEVOICE_DIR to your VibeVoice checkout path")

    spk = [s.strip() for s in speakers.split(",") if s.strip()]
    if len(spk) != 2:
        raise click.ClickException("Provide exactly two speaker names")

    console.rule("[bold]Resolving title on TMDb")
    imdb_id, resolved_title = resolve_to_imdb_id(title, year)
    console.print(f"IMDb ID: [bold]{imdb_id}[/] for [bold]{resolved_title}[/]")

    console.rule("[bold]Fetching source notes from Wikipedia")
    bullets = fetch_trivia_from_wikipedia(resolved_title, year)
    if not bullets:
        raise click.ClickException("Could not extract trivia bullets from Wikipedia")
    # Respect --max-trivia
    trivia = bullets[:max_trivia]
    for idx, t in enumerate(trivia, 1):
        console.print(f"[cyan]Trivia {idx}[/]: {t}")

    console.rule("[bold]Writing dialogue with OpenAI")
    script = write_dialogue(openai_model, resolved_title, spk, trivia)
    script = to_vibevoice_numbered_script(script, spk)
    txt_path = "podcast.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(script)
    console.print(f"Saved script to {txt_path}")

    console.rule("[bold]Synthesizing with VibeVoice")
    run_vibevoice(vibevoice_dir, vibevoice_model, txt_path, spk, outfile)
    console.print(f"[green]Done.[/] Wrote {outfile}")


if __name__ == "__main__":
    cli()
