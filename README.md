<p align="center"><img src="assets/icon.svg" width="96" alt="YT Notes icon"></p>

# YT Notes

YT Notes turns a YouTube video into notes that you can read in a few minutes. You paste one or more links, a playlist, or a topic. The app writes the notes and can record an audio version on your Mac.

Each note has these parts:

- A TL;DR, which is a summary of two or three sentences.
- The key ideas, each with a link to its timestamp in the video.
- The frameworks that the speaker teaches, if the video has them.
- Two to four quotes from the speaker.
- Action items as checkboxes.
- A glossary that explains each abbreviation and jargon term.

Tutorials get a different structure, so that you can follow along without watching the whole video:

- The goal: what you build or learn.
- The prerequisites: tools, versions and accounts.
- Numbered steps, each with a link to its timestamp, a screenshot from the video, and the commands or code that it needs. Select a screenshot to watch that part of the video.
- Gotchas: the errors and fixes that the presenter mentions.
- The result, and what to try next.
- The links from the video description.
- A glossary.

The app decides the kind of video by itself. To choose the structure yourself, use `--kind tutorial` or `--kind conversation`.

The notes use plain English. The app gives the writing rules of the [simple-english](https://github.com/AminBlg/SimpleEnglish) skill to the model. Sentences are short, verbs are active, and the notes have no filler words.

## Requirements

YT Notes runs on macOS. The audio feature needs a Mac with Apple silicon. Install these tools before you start:

- Python 3.10 or later.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp), which gets the video data and the captions.
- [uv](https://docs.astral.sh/uv/), which runs the transcript fallback and the audio engine in separate environments.
- [ffmpeg](https://ffmpeg.org/), which compresses the audio.
- The [pi](https://github.com/earendil-works/pi) CLI (`pi`), which writes the notes. Sign in to the `openai-codex` provider once. Claude Code (`claude`) also works, as the Choose a model section shows.

To install the first four tools with Homebrew, run this command:

```bash
brew install python yt-dlp uv ffmpeg
```

For audio, download the Kokoro model once. Kokoro is a small text-to-speech model that runs on your Mac. The app uses the copy on your disk and does not connect to Hugging Face again.

```bash
uvx --from huggingface_hub hf download mlx-community/Kokoro-82M-bf16
```

## Start the app

Go to the project folder and start the server:

```bash
cd ytnotes
python3 ytnotes.py
```

The app opens at `http://127.0.0.1:8765` in your browser. Paste a YouTube link into the box and press Enter. Notes for a one-hour video take about one minute.

To read several videos, paste one link on each line. Press Shift+Enter to start a new line. The app writes up to three notes at the same time.

If you paste a playlist link, the app reads the first 50 videos of the playlist. A playlist link contains `/playlist?list=`. A video link that also contains `list=` gives only that video.

If you type a topic instead of a link, the app finds the best videos about the topic. Select how much video it covers, from 30 minutes to 4 hours. The app then writes one note for each video.

Each playlist and each topic becomes a collection in the library. A collection page shows each video with its TL;DR, in playlist order. Each note in a collection has links to the previous and the next video.

To listen to a note, select Listen. The first recording of a note takes about one minute. After that, the audio starts immediately. The player continues while you read other notes, and it remembers your position in each note.

To delete a note, select the trash button next to Listen, and then select Delete. The app removes the note and its audio. You can't undo this. The Chrome extension has the same button.

Glossary terms have a dotted underline in the text. Select a term to see what it means. The full glossary is at the end of each note.

## Today: a daily watch list

Today is a short list of new videos that are worth your time. It uses only the channels that you choose, so YouTube's recommendations do not decide what you see.

1. Select Today at the top of the library.
2. Add the channels that you trust. Paste a channel link, an @handle, or a link to one of its videos. Or select Add the channels in my notes.
3. The app reads the new uploads of each channel from its RSS feed. It leaves out Shorts, live streams, videos from more than 3 days ago, videos that you already have notes for, and videos that were on an earlier list.
4. The model reads the titles and descriptions, compares them with the notes in your library, and keeps up to 8 videos. Each pick has one line that says what you get from it.

Select Make notes to read a pick instead of watching it. While the server runs, it makes a new list once a day. Select Check again to make it now. The Chrome extension shows the same list above the library.

To make the list from the command line, run `python3 ytnotes.py --daily`. The first time, it adds the channels of your notes.

## Use the app on your phone

Your phone and your Mac must be on the same Wi-Fi network. Start the server with the `--lan` flag:

```bash
python3 ytnotes.py --lan
```

The server shows a second address, for example `http://192.168.1.117:8765`. Open that address on your phone. On an iPhone, select Share and then Add to Home Screen to get an app icon.

Use `--lan` only on a network that you trust. The app has no password, so each device on the network can open it.

## Use the Chrome extension

The Chrome extension shows your notes next to the video on YouTube. Select a timestamp to jump to that part of the video, or select Make notes for a video that has no notes yet. The server must be running.

To install it, go to `chrome://extensions`, turn on Developer mode, select Load unpacked, and select the `extension` folder. See [extension/README.md](extension/README.md) for more.

## Command line

You can also use YT Notes without the browser. Each command saves its result in the `notes/` folder:

| Command | Result |
|---|---|
| `python3 ytnotes.py "https://youtu.be/VIDEO_ID"` | Writes notes for one video. |
| `python3 ytnotes.py "https://youtu.be/ID_1" "https://youtu.be/ID_2"` | Writes notes for each video. |
| `python3 ytnotes.py "https://www.youtube.com/playlist?list=PLAYLIST_ID"` | Writes notes for the first 50 videos of a playlist and saves the playlist as a collection. |
| `python3 ytnotes.py "saas distribution" -t 60` | Writes notes for the best videos on a topic, about 60 minutes of video in total. |
| `python3 ytnotes.py "https://youtu.be/VIDEO_ID" --audio --voice bm_george` | Writes notes and records the audio in the voice that you select. |
| `python3 ytnotes.py "https://youtu.be/VIDEO_ID" --kind tutorial` | Writes notes with the tutorial structure. The choices are `auto` (the default), `conversation`, `talk`, and `tutorial`. |
| `python3 ytnotes.py --daily` | Makes today's watch list from your channels and prints it. |
| `python3 ytnotes.py --add-glossary` | Adds a glossary to old notes that do not have one. |
| `python3 ytnotes.py --model openai-codex/gpt-6-luna` | Uses a different model. See the Choose a model section. |
| `python3 ytnotes.py --port 8766` | Starts the server on a different port. |
| `python3 ytlearn.py "saas distribution" -t 60` | Makes a playlist link with short takeaways in the `playlists/` folder. |

The voices are `af_heart` (the default), `af_bella`, `am_michael`, `am_fenrir`, `bf_emma`, and `bm_george`. The letters `a` and `b` mean American and British. The letters `f` and `m` mean female and male.

## Choose a model

The default model is `openai-codex/gpt-6-luna`, which runs through pi. Use `--model` to select a different model. The same model writes the notes, the glossaries, and the topic picks.

| Value of `--model` | CLI that runs |
|---|---|
| `provider/model`, for example `openai-codex/gpt-6-luna` or `opencode-go/gpt-6-luna` | pi |
| A Claude model, for example `claude-haiku-5-5` or `sonnet` | Claude Code |
| `pi:` or `claude:` followed by a model name | The CLI that the prefix names |

To see the models that pi can use, run `pi --list-models`. The model setting is part of the server command, for example `python3 ytnotes.py --model claude-haiku-5-5`.

pi runs with its tools, sessions, extensions, and project files turned off. It gets only the prompt and the transcript.

## How it works

The app makes a note in these steps:

1. yt-dlp gets the title, the channel, the length, the chapters, the description, and the English captions of the video.
2. If YouTube blocks the caption download, youtube-transcript-api gets the captions in a different way.
3. The model reads the title, the description, and the start of the transcript, and decides if the video is a conversation, a talk, or a tutorial.
4. For a tutorial, `context.py` reads the GitHub repos, gists, and docs pages that the description links to. From a repo, it reads the README, the file list, and a few key files. The model then uses the real code instead of guessing it from speech.
5. pi or Claude Code writes the notes from the chapters, the linked sources, and the transcript. The prompt contains the note structure and the simple-english rules from `skills/simple-english/SKILL.md`.
6. For a tutorial, yt-dlp downloads the video at 720p or lower, and ffmpeg takes one frame for each step. The frames are in `notes/frames/`.
7. For audio, `tts.py` changes the notes into a spoken script and Kokoro records it. ffmpeg then compresses the recording to an `.m4a` file.

## Files

The project has these files and folders:

| Path | Contents |
|---|---|
| `ytnotes.py` | The server and the command line tool. |
| `ytnotes.html` | The app that opens in the browser. |
| `tts.py` | The script that records audio with Kokoro. |
| `ytlearn.py` | The video search and the playlist builder. |
| `daily.py` | The daily watch list: your channels, their RSS feeds, and the picks. |
| `ROADMAP.md` | Ideas for improving tutorial notes. |
| `context.py` | The code that gets chapters and reads the repos and docs that a video links to. |
| `llm.py` | The code that sends prompts to pi or Claude Code. |
| `skills/simple-english/` | A copy of the simple-english skill, with its license and source. |
| `assets/` | The app icon in SVG and PNG. |
| `extension/` | The Chrome extension. |
| `notes/` | Your notes, the audio files, `index.json`, and `collections.json`. Git ignores this folder. |
| `playlists/` | The playlists from `ytlearn.py`. Git ignores this folder. |

## Troubleshooting

These are the errors that you can see, and what to do:

- "No English transcript available": The video has no English captions, or YouTube blocks both caption methods. Try again later or use a different video.
- "Address already in use": Another copy of the server is running. Stop it with Ctrl+C, or start the server with `--port 8766`.
- "529 Overloaded" or a similar error from the model: The model provider is busy. Try again after a few minutes.
- "Notes failed" with a sign-in message: Sign in to pi or Claude Code again, then try again.
- The audio does not start: Make sure that you downloaded the Kokoro model. See the Requirements section.

## Credits

YT Notes uses work from these projects:

- [pi](https://github.com/earendil-works/pi) and [Claude Code](https://claude.com/claude-code), which run the models.
- [simple-english](https://github.com/AminBlg/SimpleEnglish) by AminBlg, MIT license. A copy is in `skills/simple-english/`.
- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), the [mlx-community](https://huggingface.co/mlx-community/Kokoro-82M-bf16) conversion, and [mlx-audio](https://github.com/Blaizzy/mlx-audio).
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api).
