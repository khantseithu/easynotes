# Contributing

Thanks for helping with EasyNotes. Bug reports, fixes and small improvements are welcome. Open an issue first if you want to make a large change.

## Set up

Follow the Requirements section of the [README](README.md), then start the server:

```bash
python3 ytnotes.py
```

The server and the tests use only the Python standard library, so there is nothing to install for them.

## Before you open a pull request

Run the tests:

```bash
python3 -m unittest discover -s tests
```

- Keep each pull request to one change, and add a test when you fix a bug.
- Do not commit anything from `notes/` or `playlists/`. These folders hold your personal library.
- Do not commit API keys, cookies or other credentials.
- If you change the interface, check the light theme, the dark theme and a phone-width window.
