# Security

EasyNotes is a personal app that runs on your own computer. It has no accounts and no password.

## What to know before you run it

- By default the server listens only on `127.0.0.1`. It refuses requests whose `Host` header is not a local address, and it refuses changes that come from other websites.
- With `--lan`, each device on your network can read, change and delete your notes, and can start jobs that use your model account. It can also make the server fetch any web address when it reads an article. Use `--lan` only on a network that you trust, and never expose the server to the internet.
- Transcripts and article text go to the model command that you choose (`agy`, `pi` or `claude`). The privacy terms of that provider apply.

## Report a problem

Report a vulnerability through [GitHub private vulnerability reporting](https://github.com/khantseithu/ytnotes/security/advisories/new). Do not open a public issue for it. Include the steps that show the problem and the version or commit that you tested.
