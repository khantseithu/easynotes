# EasyNotes for Chrome

The extension shows your EasyNotes next to a YouTube video in Chrome. It opens in the Chrome side panel and follows the video in the current tab.

The extension uses the EasyNotes server on your Mac. It does not write notes itself, so the server must be running.

## What it does

- When a video has notes, the side panel shows them. Select a timestamp to jump to that part of the video in the same tab.
- While the video plays, a bar marks the key idea that the speaker talks about now.
- When a video has no notes, select Make notes. The notes appear in the panel when they are ready.
- Select Listen to record and play the audio version, as in the app.
- Glossary terms, action items and the voice setting work as they do in the app.
- Select the Library button to see all your notes, or to make notes from a link or a topic.
- Right-click a YouTube link, or a YouTube page, and select Make notes with EasyNotes.
- The toolbar icon shows a check mark on videos that already have notes.

## Install

1. Start the server: `python3 ytnotes.py --no-open`.
2. In Chrome, go to `chrome://extensions` and turn on Developer mode.
3. Select Load unpacked and select this `extension` folder.
4. Pin EasyNotes to the toolbar. Open a YouTube video and select the EasyNotes icon, or press Alt+Shift+N.

After you change a file in this folder, select the reload button for EasyNotes on `chrome://extensions`.

## Settings

The extension connects to `http://127.0.0.1:8765` by default. To use a different port or a server on another computer, open the extension's Settings from the gear button in the panel. For a server on another computer, start it with `--lan` and type the address that it shows. Chrome asks you to allow the extension to reach that address.

## Files

| Path | Contents |
|---|---|
| `manifest.json` | The Manifest V3 description of the extension. |
| `sidepanel.html`, `sidepanel.css`, `sidepanel.js` | The side panel: notes, library, audio player. |
| `background.js` | The service worker: the right-click menu and the check mark on the icon. |
| `content.js` | The script on YouTube pages that jumps the video to a timestamp. |
| `options.html`, `options.js` | The settings page. |
| `lib.js` | Code that the panel, the settings page and the service worker share. |
| `vendor/` | Copies of [marked](https://github.com/markedjs/marked) 12.0.2 (MIT) and [DOMPurify](https://github.com/cure53/DOMPurify) 3.1.6 (Apache 2.0 or MPL 2.0), with their licenses. Chrome extensions cannot load code from a CDN. |
| `icons/` | The app icon at 16, 32, 48 and 128 pixels. |

## Limits

- The audio stops when you close the side panel.
- Action items that you check in the extension are separate from the ones that you check in the app.
