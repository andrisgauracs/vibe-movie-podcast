import os, re, textwrap, subprocess, shlex, sys
from typing import List, Optional
import click
from dotenv import load_dotenv
from rich import print
from rich.console import Console

# TMDb + Cinemagoer
import tmdbsimple as tmdb
from imdb import Cinemagoer

# OpenAI
from openai import OpenAI

console = Console()


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
        raise click.ClickException("TMDb: no results for that title/year")
    m = results[0]
    tmdb_title = m.get("title") or title
    mid = m["id"]
    ex = tmdb.Movies(mid).external_ids()
    imdb_id = ex.get("imdb_id")
    if not imdb_id:
        raise click.ClickException("TMDb: could not find IMDb ID via external_ids")
    return imdb_id, tmdb_title


def fetch_trivia(imdb_id: str, limit: int = 12) -> List[str]:
    ia = Cinemagoer()
    # Cinemagoer wants numeric part
    movie_id = imdb_id.replace("tt", "")
    mv = ia.get_movie(movie_id, info=["trivia"])
    items = mv.get("trivia", []) or []
    out = []
    for item in items:
        t = item if isinstance(item, str) else str(item)
        t = re.sub(r"\s+", " ", t).strip()
        t = textwrap.shorten(t, width=320, placeholder="…")
        out.append(t)
        if len(out) >= limit:
            break
    return out


SYSTEM_PROMPT = """You are a scriptwriter for a short two-person movie trivia podcast.
Write a clean, friendly dialogue that alternates speakers on each line.
Follow these rules:
- Speakers must be exactly the two names provided.
- One to two sentence intro, then a sequence of trivia beats, then a one line outro.
- Each trivia beat is 1 to 2 sentences from the lead speaker, then a 1 sentence reaction from the other.
- Keep lines under 220 characters.
- Avoid profanity and complicated punctuation.
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
    cmd = (
        f"python demo/inference_from_file.py "
        f"--model_path {shlex.quote(model_name)} "
        f"--txt_path {shlex.quote(txt_path)} "
        f"--speaker_names {speakers_arg} "
        f"--out_path {shlex.quote(out_wav)}"
    )
    console.rule("[bold]VibeVoice generation")
    console.print(cmd)
    subprocess.run(cmd, shell=True, check=True, cwd=vibevoice_dir)


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

    console.rule("[bold]Fetching trivia via Cinemagoer")
    trivia = fetch_trivia(imdb_id, limit=max_trivia)
    if not trivia:
        raise click.ClickException("No trivia found for this title")
    for idx, t in enumerate(trivia, 1):
        console.print(f"[cyan]Trivia {idx}[/]: {t}")

    console.rule("[bold]Writing dialogue with OpenAI")
    script = write_dialogue(openai_model, resolved_title, spk, trivia)
    txt_path = "podcast.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(script)
    console.print(f"Saved script to {txt_path}")

    console.rule("[bold]Synthesizing with VibeVoice")
    run_vibevoice(vibevoice_dir, vibevoice_model, txt_path, spk, outfile)
    console.print(f"[green]Done.[/] Wrote {outfile}")


if __name__ == "__main__":
    cli()
