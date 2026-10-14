# Tutorial notes: future improvements

These are ideas for after the first version of tutorial notes. That version detects the kind of video, uses a tutorial structure, adds the chapters and the linked repos and docs, and puts a screenshot under each step. Each item says what the problem is and a possible fix. The items are roughly in order: cheap fixes first.

## What we know from the first test

On a 17-minute Higgsfield tutorial, 9 of 10 screenshots showed what the step describes, and 1 matched only partly. In the first version, which took a frame from the first seconds of each step, only 4 of 10 matched. The video had no repo link, so the linked-sources part is still untested.

## Things to watch for on long coding videos (for example, Andrej Karpathy's)

- **Download size.** The app downloads the whole video at 720p for screenshots. A 2-hour video can be 1 GB or more. Fix: download only a few seconds around each candidate moment with `yt-dlp --download-sections`, or let ffmpeg seek on the stream URL.
- **Talks and lectures.** A talk such as "Intro to Large Language Models" is detected as `talk`, so it gets the conversation structure, with no screenshots. Fix: a lecture structure with definitions, the intuition, worked examples and formulas, and screenshots of the slides.
- **Many steps.** A 2-hour build can have 30 or more steps. Screenshot picking compares every candidate with every other one, so the time grows quickly. Fix: compare each candidate with a sample of the others, or with a few talking-head frames.
- **Code on screen, not in the repo.** The repo holds the final code, but the video builds it step by step. The note can show the final version of a function at a step where the video has only half of it. Fix: tell the model to show only what the step adds, or match each step to a commit in the repo's history.
- **Notebooks and Colab.** Links to Google Colab and Jupyter notebooks are fetched as web pages, so they give little or no code. Fix: turn Colab and GitHub notebook links into the raw `.ipynb` file and keep only the code and markdown cells.
- **Long transcripts.** The transcript is cut at 400,000 characters. That is about 6 hours of speech, so it is fine for most videos, but the linked sources share the same budget.

## Screenshots

- **Late subjects.** In step 10 of the test, the chosen frame showed the previous scene, because the pack shot appears later in the step. Fix: prefer candidates from the middle and end of a step when the scores are close, or let a vision model choose.
- **Redo screenshots.** Tuning frame choice today needs a script. Add a `--reframe` flag, and a "Redo screenshots" action in the app, that keeps the note text and takes the screenshots again.
- **Read the screen with a vision model.** Send each step's chosen frame, or two or three candidates, to a model that can read images. It can choose the best frame and write down the code, the terminal output or the diagram on it. Mark that code "Reconstructed from video" and give it a copy button. Put this behind a "technical mode" switch, because it adds one model call for each step.
- **More than one frame per step.** Long steps change the screen several times. Add a second frame when the candidates of a step are very different from each other.
- **Frames for moments, not only steps.** Add a frame where the transcript says "as you can see", "this function" or "look at this", and in the Gotchas section.
- **Crop and zoom.** At phone width, code in a 1280-pixel frame is hard to read. Crop to the area that changed between candidates.
- **Delete frames with their note.** Frames stay in `notes/frames/` if the note is removed.

## Note structure

- **A picker in the app.** The app has no control to choose the structure. Add a small menu (Auto, Conversation, Talk, Tutorial) next to the input, and a way to remake a note with a different structure.
- **Follow-along mode.** Show the steps as checkboxes, like the action items, and save progress for each note.
- **Freshness.** Show the publish date and the versions that the tutorial uses, for example "Uses Next.js 13 (2023)", and warn when the video is old.
- **Formulas.** Render LaTeX in lectures with KaTeX.
- **Links from the video.** Add the official site of each tool that the video uses, but only when the model can check the URL. Today the Links section has only the description links.

## Audio

- Technical notes skip code blocks, screenshots and the Links section. The step list can still be long when it is read aloud. Consider an audio script that covers the goal, a summary of the steps, the gotchas and the result.

## Reliability

- **yt-dlp goes out of date.** Old versions of yt-dlp get 403 errors on video downloads, while captions still work. The note now says when this happens. Consider a check at start-up that warns when yt-dlp is more than about 2 months old.
- **Kind detection costs one model call.** Skip it when the title or the chapters make the kind obvious, for example "tutorial", "build", "from scratch" or "how to".
