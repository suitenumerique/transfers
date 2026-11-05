# Changelog

All notable changes to this project will be documented in this
file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Theme the interface at runtime, from a JSON object the backend
  resolves per request: one image serves every operator
  (`DEFAULT_CONFIG`)
- Serve a different theme per domain, as a patch over that base
  (`CONFIG_OVERRIDES`)
- Accept a theme file shaped like the one `docs` and `drive` take
  (`THEME_CUSTOMIZATION_FILE_PATH`)
- Let a deployment serve its own font files, declared in the theme
  (`fontFaces`) and turned into `@font-face` rules at runtime
- `USE_X_FORWARDED_HOST`, for an edge that rewrites `Host` and sets
  `X-Forwarded-Host`. The resolver reads the host to pick a theme, so
  an edge that rewrites it without this serves the neutral theme to
  every domain, silently

### Changed

- Read the Cunningham palette from /config instead of compiling it in
- Serve the theme as `theme_customization`, the key `docs` and `drive`
  already use, so a file written for them drops in unchanged
- Make the ProConnect sign-in button opt-in, and render the same
  sign-in affordance on the landing page and in the header
- Ship the neutral theme's own font instead of naming one nobody
  served: Hanken Grotesk, self-hosted, 54 kB of variable woff2 under
  the SIL Open Font License. The interface used to fall through to
  whatever sans-serif the visitor's system provided
- Read the logo, favicon, help and support links from the theme
  instead of hard-coding them
- Draw the product mark inline, from the Cunningham logo tokens, so a
  deployment recolours it without producing an asset of its own. The
  `anct-*` themes keep the blue and yellow it was drawn in; the neutral
  theme makes it monochrome

### Deprecated

- `HELP_URL`, `SUPPORT_URL` and the `LAGAUFRE` config key, superseded
  by `theme_customization.help.documentation_url`,
  `theme_customization.help.support_url` and
  `theme_customization.waffle`. Honoured as fallbacks for one version

### Removed

- The Scalingo buildpack files (`Procfile`, `bin/scalingo_*`). The
  container image and its Caddy front remain the only deployment path

### Fixed

- Email links now point at the domain the transfer was created on. They
  were built from a single instance-wide URL (`PUBLIC_BASE_URL`, which
  was declared nowhere, falling through to `LOGIN_REDIRECT_URL`), so on
  an instance serving several domains a recipient could receive a link
  to another operator's hostname. The origin of the request now travels
  with the task that sends the mail, and `PUBLIC_BASE_URL` is gone
- `OIDC_REDIRECT_ALLOWED_HOSTS` is documented and shipped as bare
  hosts. The values in `env.d` carried a scheme, which the host check
  compares against a netloc and can never match, so a `?next=` to one
  of them was silently dropped
- Signing in returns to the domain it was started from. The sign-in
  button sent no `?next=`, so the backend fell back to
  `LOGIN_REDIRECT_URL` -- a single host for the whole deployment. On
  any other domain the user landed on the wrong instance, carrying a
  session cookie set for a host they were no longer on, hence
  apparently logged out. Domains must be listed in
  `OIDC_REDIRECT_ALLOWED_HOSTS`; an unlisted one keeps the old
  behaviour
- The dev server now proxies the backend's prefixes, the ones Caddy
  forwards in production (`/api`, `/__heartbeat__`, `/static`), so dev
  is single-origin like prod and `NEXT_PUBLIC_API_ORIGIN` is empty by
  default. Dev used to split the app across two ports, which made the
  per-domain configuration impossible to exercise locally -- the
  backend read the API port's host, `localhost`, whatever domain the
  browser was on -- and left the session cookie on a host the page was
  not served from. A test pins the two routing tables together

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
