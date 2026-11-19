# Contributing to Langdesk

Thanks for helping. Langdesk is used where a missed interpreter has real consequences, so we
favour small, well-tested changes and plain, readable code.

## Ground rules

- **No client details, anywhere.** Not in code, fixtures, tests, screenshots, issues or logs.
  Use fictional names and `555-01xx` phone numbers.
- Keep the request form fast. Anything that adds a field to it needs a strong reason.
- Every state change to a request goes through `langdesk/scheduling/services/dispatch.py` so it
  gets an audit event and the right messages.

## Getting set up

```bash
git clone https://github.com/lobojoel2003/Langdesk.git && cd Langdesk
```

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
```

```bash
make demo run
```

Sign in as `coordinator` / `langdesk-demo`. Background work runs inline without Redis.

## Before you open a pull request

```bash
make lint test
```

- Add or update tests. Coverage must stay above 90%.
- To test against Postgres like CI does, set
  `DATABASE_URL=postgres://user:pass@localhost:5432/langdesk` before running `pytest`.
- If you change models, include the migration (`python manage.py makemigrations`).
- If you change the UI, include before and after screenshots in the pull request.
- Add a line under **Unreleased** in `CHANGELOG.md`.

## Commit messages

Write the subject in the imperative, under 72 characters (`Skip reminders for cancelled
requests`), and explain the why in the body when it isn't obvious.

## Releases

Maintainers cut releases as described in [docs/releasing.md](docs/releasing.md).
