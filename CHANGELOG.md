# Changelog

All notable changes to Langdesk are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Langdesk uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-19

The first release: everything a small clinic, school or legal aid office needs to request,
schedule and report on interpreters.

### Added

- **20-second request form**: language (most-requested first), date, start, one-tap duration,
  in person, video or phone, site, room and an optional appointment reference. Remembers each
  requester's usual site, department and service type.
- **Privacy guard rails**: requests hold an appointment reference, never client details.
  Reference fields accept ID-shaped values only; free-text fields reject dates of birth, Social
  Security numbers, phone numbers, email addresses and diagnosis keywords. Texts, emails and
  invites carry only language, time, place and reference.
- **Coordinator board** with open requests grouped by day, the top three interpreters ranked
  with readable reasons, one-click offer and assign, urgent flags, today's coverage and requests
  that still need an outcome. Refreshes itself every minute.
- **Ranking engine** with hard rules (language, credential, mode, sites, working hours, time off,
  double bookings with a travel buffer, daily limits, prior declines) and scoring for
  certification, staff over contract, same site, case continuity, reliability and workload.
- **Automatic dispatch** in waves: offers go to the best three, the next wave goes out when
  nobody replies in 20 minutes or everyone declines, and coordinators are alerted when the
  roster is exhausted.
- **Accept by text**: four-digit reply codes, `YES`/`NO`/`HELP`/`STOP`/`START`, first to accept
  wins and everyone else is told it's filled. A phone-friendly offer page does the same from the
  link in each text and email.
- **Pluggable SMS backends**: console (default), Twilio with signed inbound webhooks, and a
  generic JSON webhook relay for any other provider. An in-browser SMS simulator for trials.
- **Email** for offers, confirmations, updates, cancellations and requester notices, with
  iCalendar invites (`METHOD:REQUEST` and `METHOD:CANCEL`, sequence-numbered).
- **Subscribable calendar feed** per interpreter, with a one-click way to issue a new link.
- **Reminders** a day and two hours before (configurable), sent once and skipped when the
  assignment was made inside the window.
- **Video fallback** to Jitsi Meet: unfilled in-person requests switch to video an hour before
  start (configurable), the requester is told, and offers widen to remote interpreters. Video
  requests get a link straight away.
- **Outcomes** for every request (interpreted, client or interpreter no-show, client declined,
  outside line, unfilled, cancelled) with minutes interpreted.
- **Audit log** of every change on every request, with who did it and when.
- **Language-access report** by year or date range: fill rate, certified share, unfilled, hours,
  median notice and time to fill, video fallbacks, and breakdowns by language, month, outcome,
  mode, site, department, service type and interpreter type. Printable, with summary and full
  request-log CSV exports and a `language_access_report` management command.
- **Roster management** in the Django admin, with 52 preloaded languages including Mayan
  languages, Pacific languages and American Sign Language.
- **Roles**: requesters see and manage their own requests; the `Coordinators` group runs the
  board, roster and reports and is given admin permissions automatically.
- `seed_demo` command with a fictional organisation, roster, a year of history and a live board.
- `run_dispatcher` command to run the dispatcher from cron or systemd instead of Celery beat.
- `/healthz` endpoint reporting status, database, version, build number and commit.
- **Docker image** (non-root, multi-arch) and a one-command **Docker Compose** stack with
  Postgres, Redis, web, worker and beat. Secret key generated on first start.
- **CI/CD**: Ruff, tests on Python 3.12 and 3.13 against Postgres and SQLite with 90%+
  coverage, migration and deployment checks, package build, Docker Compose smoke test, edge
  images from `main`, tagged releases with multi-arch images, SBOM, build provenance,
  checksummed assets and notes from this changelog. CodeQL and Dependabot.

[Unreleased]: https://github.com/lobojoel2003/Langdesk/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/lobojoel2003/Langdesk/releases/tag/v1.0.0
