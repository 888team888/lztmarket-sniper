# Contributing

Thanks for wanting to help. Here's how to do it properly.

## Reporting bugs

Open an issue using the Bug Report template. Include:
- Your OS and Python version (`python --version`)
- Your Chrome version (`chrome://version`)
- The full error from the terminal
- What you were doing when it broke

## Suggesting features

Open an issue using the Feature Request template. Describe what you want and why it's useful. Keep it practical — this tool is for LZT market monitoring, not a general purpose scraper.

## Pull requests

1. Fork the repo
2. Create a branch: `git checkout -b feature/your-feature-name`
3. Make your changes — keep it to one thing per PR
4. Test it actually works before submitting
5. Open a PR with a clear description of what changed and why

## Code style

- Keep it simple. This is a single-file Flask app by design.
- No new dependencies without a very good reason — the goal is minimal setup.
- If adding a new route, document it in the README under the API section.
- Don't break the mobile UI. Test on a narrow viewport.

## What won't be accepted

- Changes that require a database
- Adding a login/auth system (out of scope)
- Rewriting in a different framework
- Anything that makes setup harder for non-developers
