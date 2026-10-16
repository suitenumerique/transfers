# Changelog

All notable changes to this project will be documented in this
file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Read the Cunningham theme from /config instead of compiling it in
- Make the ProConnect sign-in button opt-in
  (`FRONTEND_PROCONNECT_BUTTON`)
- Make the landing page's "learn more" link configurable
  (`FRONTEND_LEARN_MORE_URL`)

## [0.3.0] - 2026-09-17

### Added

- Show each recipient's delivery state instead of waiting on the send
- Resume interrupted downloads, bound to a signed capability

### Fixed

- Big encrypted downloads now survive Firefox: the key is persisted,
  the transfer resumes and progress is shown
- Size the scan wait budget on the file, and never re-submit a scan
  that is still running
- Claim scan rows before re-submitting them, and scope the service
  worker's notices to the click that asked for them
- Send every download notice within the fetch event's lifetime
- Tell the page when a download fails after its headers
- Recover from a hard reload without a "preparing…" pause

## [0.2.0] - 2026-09-14

### Added

- Make the LaGaufre widget opt-in and deployment-configurable
- Publish a distroless backend image

### Changed

- Make confidential transfers calmer to read, gateable and reachable

### Fixed

- Never lose the key on a confidential email transfer, and say how to
  share it
- Stop encrypted downloads dying mid-stream when the service worker
  went idle
- Align the CSRF and sender env keys on the st-ansible template

## [0.1.0] - 2026-08-20

First public release.

[unreleased]: https://github.com/suitenumerique/transfers/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/suitenumerique/transfers/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/suitenumerique/transfers/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/suitenumerique/transfers/releases/tag/v0.1.0
