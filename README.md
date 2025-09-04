# Vibe Movie Podcast Generator

---

A Python-based tool that automatically generates engaging movie trivia podcasts using AI. It fetches movie data from TMDb, extracts trivia from Wikipedia, generates a conversational script with OpenAI, and synthesizes audio using Microsoft's VibeVoice.

## Features

- 🎬 **Movie Research**: Automatically resolves movie titles to IMDb IDs using TMDb
- 📚 **Trivia Extraction**: Scrapes and summarizes relevant trivia from Wikipedia
- 🤖 **AI Script Generation**: Creates natural, engaging dialogue between two podcast hosts
- 🎤 **Voice Synthesis**: Generates high-quality audio using VibeVoice TTS models
- 🎯 **Interactive CLI**: User-friendly command-line interface with prompts and choices
- 🌐 **Web Playback**: Built-in web server with HTML player for easy podcast playback
- 📁 **File Organization**: Automatically organizes generated files in a dedicated directory

## Prerequisites

- Python 3.8+
- API keys for:
- OpenAI (for script generation)
- TMDb (for movie data)
- Git (for cloning VibeVoice)
- FFmpeg (for audio processing)

## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/andrisgauracs/vibe-movie-podcast.git
   cd vibe-movie-podcast
   ```

2. Before running the installation script, create and activate a Python virtual environment:

   ```bash
   uv venv
   source .venv/bin/activate
   ```

3. **Run the installation script:**

   ```bash
   ./install.sh
   ```

   This will:

   - Install system dependencies (FFmpeg, build tools)
   - Set up Python environment with uv
   - Install required Python packages
   - Clone and install VibeVoice
   - Configure environment variables

4. **Set up environment variables:**

   ```bash
   cp .env.sample .env
   ```

   Edit `.env` with your API keys:

   ```bash
   OPENAI_API_KEY=your_openai_key_here
   TMDB_API_KEY=your_tmdb_key_here
   ```

## Usage

### Basic Usage

```bash
python main.py --title "The Matrix" --year 1999
```

### Advanced Usage

```bash
python main.py \
  --title "Inception" \
  --year 2010 \
  --speakers "Alex,Sam" \
  --outfile "inception-podcast" \
  --model "microsoft/VibeVoice-Large"
```

### Interactive Mode

Run without arguments for interactive prompts:

```bash
python main.py
```

You'll be prompted to:

- Enter movie title and year
- Choose VibeVoice model
- Select voice actors
- Specify output filename

## Command Line Options

- `--title`: Movie title (required if not interactive)
- `--year`: Release year (optional, helps with disambiguation)
- `--max-trivia`: Maximum number of trivia facts (default: 10)
- `--speakers`: Comma-separated speaker names (e.g., "Alice,Frank")
- `--outfile`: Output filename without extension
- `--model`: VibeVoice model to use
- `--no-server`: Skip starting the web server after generation
- `--serve-only`: Skip podcast generation and just serve existing files

## Configuration

### Environment Variables

- `OPENAI_API_KEY`: Your OpenAI API key
- `OPENAI_MODEL`: OpenAI model (default: gpt-4o-mini)
- `TMDB_API_KEY`: Your TMDb API key
- `VIBEVOICE_DIR`: Path to VibeVoice repository
- `VIBEVOICE_MODEL`: Primary VibeVoice model
- `VIBEVOICE_FALLBACK_MODEL`: Fallback model if primary fails

### Getting API Keys

1. **OpenAI**: Visit [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. **TMDb**: Visit [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) and create a free account

## Output

The tool generates:

- `podcast_files/podcast.txt`: The generated script
- `podcast_files/{outfile}.wav`: The synthesized audio podcast
- `podcast_files/index.html`: Web player for easy playback

After generation, a web server automatically starts at `http://localhost:3001` (or your configured port) with a beautiful HTML player.

### File Organization

All generated files are automatically organized in the `podcast_files/` directory:

```
podcast_files/
├── index.html      # Web player
├── podcast.txt     # Script
└── podcast.wav     # Audio file
```

### Web Server

The built-in web server provides:

- 🎵 HTML5 audio player with controls
- 📄 Script viewer
- ⬇️ Direct download links
- 📱 Mobile-friendly interface
- 🎨 Modern, responsive design

To disable the web server, use the `--no-server` flag.

## Serving Existing Podcasts

If you already have generated podcast files, you can start the web server without regenerating:

```bash
python main.py --serve-only
```

This will:

- Check for existing `podcast_files/` directory
- Start the web server on port 3001
- Serve your previously generated podcast

## Examples

### Generate a podcast about "The Shawshank Redemption"

```bash
python main.py --title "The Shawshank Redemption" --year 1994 --speakers "Bob,Alice"
```

### Use a specific VibeVoice model

```bash
python main.py --title "Pulp Fiction" --model "microsoft/VibeVoice-1.5B"
```

## Troubleshooting

### Common Issues

1. **"Missing API keys"**: Ensure `.env` file exists with correct keys
2. **"VibeVoice directory not found"**: Run `./install.sh` to clone VibeVoice
3. **"Model download failed"**: Check internet connection and HuggingFace access
4. **"Wikipedia page not found"**: Try different movie title or omit year

### Model Selection

- **VibeVoice-Large**: Higher quality, larger download (~7GB)
- **VibeVoice-1.5B**: Faster inference, smaller download (~3GB)

## Dependencies

- `openai`: For AI script generation
- `tmdbsimple`: TMDb API client
- `wikipedia-api`: Wikipedia data extraction
- `click`: Command-line interface
- `rich`: Beautiful terminal output
- `torch`: Machine learning framework
- `python-dotenv`: Environment variable management

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Podcast Samples

Enjoy sample podcasts generated by Vibe Movie Podcast Generator:

**Forrest Gump**
<div align="center">

https://github.com/user-attachments/assets/fd227b0a-3f3f-4d3d-a5ee-0f5c50388f2e

</div>


**Home Alone**
<div align="center">

https://github.com/user-attachments/assets/fb45aa82-5872-4ba9-86f1-632386759596

</div>

**The Dark Knight**
<div align="center">


https://github.com/user-attachments/assets/607a3604-c576-4e2e-8b41-f38fd9f0f38a


</div>

**The Godfather**
<div align="center">


https://github.com/user-attachments/assets/c4587802-5ef6-43e5-b3c7-2f44bb43140b


</div>

**The Matrix**
<div align="center">


https://github.com/user-attachments/assets/cd4515e7-d037-4eab-a58a-afbd5110e019


</div>

**There Will Be Blood**
<div align="center">


https://github.com/user-attachments/assets/1130d756-4e48-4a5b-ab39-b4276e88756b


</div>

**Titanic**
<div align="center">


https://github.com/user-attachments/assets/e3f2967f-dfc5-4b8d-b018-5b2cb667c7f2


</div>
