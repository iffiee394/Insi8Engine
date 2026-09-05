# YouTube Insight Agent

Watches a fixed YouTube playlist and produces summaries + key points for each new video.

## Setup

1. **Install dependencies**

   ```powershell
   cd "D:\Cursor Projects\CursorP1"
   pip install -r requirements.txt
   ```

2. **Install ffmpeg** (for long-video audio chunking and yt-dlp)

   Download from https://ffmpeg.org/download.html and add to PATH.

3. **Configure `.env`**

   Copy `config.example.env` to `.env` and fill in:

   - `GROQ_API_KEY` — from your existing reel project
   - `YOUTUBE_API_KEY` — Google Cloud → YouTube Data API v3
   - `PLAYLIST_ID` — from your playlist URL (`list=PLxxxx`)

4. **Create your playlists**

   - **General playlist** — any video you want a full summary for (`PLAYLIST_ID`)
   - **Podcast playlist** — long videos where you set a custom agenda per video (`PODCASTS_PLAYLIST_ID`)

## Usage

**Poll manually (or on schedule):**

```powershell
python poll.py
```

**Open the dashboard:**

```powershell
python -m streamlit run app.py
```

### Two playlist modes

| Playlist | Behavior |
|----------|----------|
| **General** | Auto-processes → full summary + key points |
| **Podcast** | Waits for you to write an **agenda** in the dashboard → insights focused only on what you asked for |

Example agenda for a tech podcast:
```
• Focus mainly on the tech stack discussed
• How to get a remote job in this field
• Best sources and platforms for remote jobs
• What salary or pay range they mention
```

## Windows Task Scheduler (every 15 min)

1. Open Task Scheduler → Create Basic Task
2. Trigger: Daily, repeat every **15 minutes** for 1 day (or use advanced trigger)
3. Action: Start a program
   - Program: `python` (or full path to your Python exe)
   - Arguments: `"D:\Cursor Projects\CursorP1\poll.py"`
   - Start in: `D:\Cursor Projects\CursorP1`

## How it works

1. `poll.py` fetches all videos from your playlist via YouTube Data API
2. New videos (not in SQLite) are transcribed:
   - YouTube captions first (free)
   - Groq Whisper fallback (reused from your reel transcriber)
3. Groq LLM extracts summary + key points
4. Results saved to `data/insights.db` and shown in the Streamlit UI
