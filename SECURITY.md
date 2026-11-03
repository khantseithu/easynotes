# Security

EasyNotes is a personal app that runs on your own computer. It has no accounts and no password.

## What to know before you run it

- The server listens only on `127.0.0.1`. It refuses requests whose `Host` header is not a local address, and it refuses changes that come from other websites.
- Do not expose the server to other devices or the internet, for example with a tunnel or a reverse proxy. It has no sign-in, so anyone who reaches it could read and delete your notes and use your model account.
- Transcripts and article text go to the model command that you choose (`agy`, `pi` or `claude`). The privacy terms of that provider apply.

## Report a problem

Report a vulnerability through [GitHub private vulnerability reporting](https://github.com/khantseithu/easynotes/security/advisories/new). Do not open a public issue for it. Include the steps that show the problem and the version or commit that you tested.
