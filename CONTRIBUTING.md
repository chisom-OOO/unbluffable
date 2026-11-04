# Contributing

Thanks for your interest. Unbluffable was built for the Meta Global AI Developer Hackathon; issues and pull requests are welcome.

## Set up

See [Run it locally](README.md#run-it-locally). Replay mode works without an API key, so you can run everything offline.

## Before you open a pull request

1. Branch from `main` and keep commits small with clear messages.
2. Run the tests:
   ```
   python -m pytest -q
   for f in tests/*.cjs; do node "$f"; done
   ```
3. CI runs the same suites on every pull request; it must be green.

## Rules that keep the product honest

- **Maths is exact.** Numbers are checked with `fractions.Fraction`; a wrong number can never be marked correct.
- **`engine/` stays pure:** no network or model calls, runnable offline. Engine changes need tests first.
- **The spec wins.** Product decisions live in `spec/`. To change one, propose a row for `spec/DECISION_LOG.md` in your pull request rather than changing behaviour silently.
- **Keys stay on the server.** Never commit keys, `.env` files, or put keys in logs, the browser or URLs.
- **No personal data.** Don't commit recordings, transcripts or anyone's interview answers.

By contributing you agree that your work is licensed under the [MIT License](LICENSE) and that you'll follow the [code of conduct](CODE_OF_CONDUCT.md).
