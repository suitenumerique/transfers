"""Deployment configuration, resolved per request from the environment.

One image, N operators. An instance declares a base configuration and, if it
serves several domains, what differs on each one. Nothing here is compiled in,
so re-theming a deployment is a restart, not a rebuild.

The resolved object is **sectioned**: ``{"theme_customization": {...}}``
today, and whatever
comes next — per-domain authentication, say — lands beside it rather than
inside it. Only the sections listed in ``SECTIONS`` are served to the browser;
a section this build doesn't know is private, so a shared configuration file
that carries secrets for another product can never leak through ``/config/``.

The ``theme_customization`` section is deliberately shaped like the theme
customization JSON
of ``docs`` and ``drive``, a superset of it: a file written for ``docs``
drops in unchanged. Like theirs, it is **not validated key by key** — an unknown key
travels through untouched. That is what lets the seven products converge on a
single file without this one having to know every key in it.
"""

import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.utils.text import slugify

logger = logging.getLogger(__name__)

# Section name -> the key /config/ serves it under, or ``None`` for a section
# that stays server-side. A section absent from this mapping is private: not
# knowing what it holds is reason enough never to hand it to a browser.
SECTIONS = {
    # Named after the key it is served under, which is the name ``docs``,
    # ``drive`` and ``calendars`` already give the file: one vocabulary from
    # the environment variable to the browser.
    "theme_customization": "theme_customization",
}

# Resolution is per request and cheap, but ``/config/`` is not the only caller
# anymore once a private section exists; memoize on the request object.
_REQUEST_ATTR = "_runtime_config"

# How long a file that could not be read is remembered as unreadable. Kept
# short -- putting the file back should take effect without a restart -- and
# never longer than a successful read is kept.
_FAILURE_CACHE_TIMEOUT = 60

# Characters that cannot appear in a bare hostname. An override key carrying
# one of them would never match, which is the failure the boot check exists to
# catch: a theme that silently never shows.
_NOT_IN_A_HOSTNAME = "/:@ "

# Top-level keys of a theme file, as ``docs`` writes one. An operator who
# pastes a theme straight into ``DEFAULT_CONFIG``, without wrapping it in a
# section, gets a configuration that holds nothing a browser will ever see --
# and a message about "sections" teaches them nothing. This is a heuristic on
# key *names*, never a schema, and it must stay one: wrapping a flat object
# automatically would turn a loud mistake into a surprising behaviour, and one
# day a theme key will be named like a section.
_THEME_LOOKING_KEYS = frozenset(
    {
        "colors",
        "favicon",
        "fontFaces",
        "fontFamily",
        "footer",
        "header",
        "help",
        "home",
        "onboarding",
        "waffle",
    }
)


def deep_merge(base, override):
    """Merge ``override`` onto ``base``, recursing into dicts only.

    Lists replace rather than concatenate: a half-merged ``legalLinks`` would
    be meaningless, and an operator must be able to *remove* a link, which
    concatenation would make impossible. An explicit ``null`` replaces too,
    which is how an override hides something the base declared.
    """
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override

    merged = dict(base)
    for key, value in override.items():
        merged[key] = deep_merge(merged[key], value) if key in merged else value
    return merged


def _load_inline(raw, name):
    """Parse one of the JSON environment variables.

    Malformed JSON here is a deployment mistake that fails the boot, like the
    other ``post_setup`` checks: an instance silently serving nobody's theme
    because of a stray comma is worse than one that refuses to start.
    """
    if not raw:
        return {}

    if isinstance(raw, dict):
        return raw

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ImproperlyConfigured(f"{name} is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ImproperlyConfigured(
            f"{name} must be a JSON object, got {type(parsed).__name__}."
        )

    return parsed


def _load_file(path, label):
    """Read and cache one of the JSON files.

    Unlike the inline variables, a missing or malformed file degrades to ``{}``
    and logs — same behaviour as ``docs``, and for the same reason: the file
    usually comes from a mounted ConfigMap that can be replaced under a running
    process, and taking the instance down for it would be worse than serving
    the neutral theme. The failure is cached as well, briefly: a path that is
    simply missing would otherwise cost an ``open()`` and an ERROR line on
    every request, for as long as it stays missing.
    """
    if not path:
        return {}

    cache_key = f"runtime_config_{label}_{slugify(path)}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
    except OSError:
        failure = "Configuration file cannot be read: %s"
    except json.JSONDecodeError:
        failure = "Configuration file is not valid JSON: %s"
    else:
        failure = (
            None
            if isinstance(parsed, dict)
            else "Configuration file must hold a JSON object: %s"
        )

    if failure:
        logger.error(failure, path)
        cache.set(
            cache_key, {}, min(_FAILURE_CACHE_TIMEOUT, settings.CONFIG_CACHE_TIMEOUT)
        )
        return {}

    cache.set(cache_key, parsed, settings.CONFIG_CACHE_TIMEOUT)
    return parsed


def _base():
    """The configuration before any override applies.

    Three sources, merged in this order: the ``docs``-shaped theme file (which
    becomes the ``theme_customization`` section, so a file written for
    ``docs`` needs no translation), then a sectioned file, then the sectioned
    inline variable. Inline last so a deployment can tweak one key over a
    mounted file.
    """
    theme_file = _load_file(settings.THEME_CUSTOMIZATION_FILE_PATH, "theme")
    base = {"theme_customization": theme_file} if theme_file else {}
    base = deep_merge(base, _load_file(settings.DEFAULT_CONFIG_FILE_PATH, "default"))
    return deep_merge(base, _load_inline(settings.DEFAULT_CONFIG, "DEFAULT_CONFIG"))


def _by_domain(mapping):
    """Fold override keys to lower case, before the two sources merge.

    DNS is case-insensitive and the request side folds case too — a ``CD33.fr``
    key is a cosmetic choice, not a different domain. Folding *after* the merge
    would leave two spellings of one domain looking like two keys, so
    ``deep_merge`` would never recurse into them and the inline source would
    replace the file's configuration for that domain instead of merging onto
    it, which is the opposite of what every other source pair does.
    """
    return {str(domain).lower(): value for domain, value in mapping.items()}


def _overrides():
    """``{domain: <partial sectioned config>}``, the file then the inline."""
    overrides = _by_domain(_load_file(settings.CONFIG_OVERRIDES_FILE_PATH, "overrides"))
    return deep_merge(
        overrides,
        _by_domain(_load_inline(settings.CONFIG_OVERRIDES, "CONFIG_OVERRIDES")),
    )


def _domain(request):
    """The domain this request came in on, port stripped.

    ``get_host()`` validates against ALLOWED_HOSTS, which is no constraint: a
    domain that isn't allowed never reaches us anyway, so an override key has
    to be in there regardless.
    """
    return request.get_host().split(":")[0].lower()


def resolve_for_domain(domain):
    """The whole sectioned configuration for one domain.

    One merge: the base, then what this domain overrides on it. An override
    states only what differs, so adding a domain never means restating a
    whole theme.

    This is the resolver proper, and it takes a domain rather than a request
    on purpose: a background task has no request, and the domain does not
    survive a ``.send()`` on its own. A task that needs configuration
    carries the request origin and resolves from its hostname.
    """
    override = _overrides().get((domain or "").lower())
    if override is not None and not isinstance(override, dict):
        # ``check_configuration`` refuses this in CONFIG_OVERRIDES at boot, but
        # the file form is read per request and can be replaced under a running
        # process. Merging a scalar onto the base would return that scalar, and
        # every caller treats the result as a mapping: the domain would answer
        # 500 until someone fixed the file. Serve the base instead.
        logger.error(
            "Configuration override for '%s' must be a JSON object, got %s; "
            "serving the base configuration instead.",
            domain,
            type(override).__name__,
        )
        override = None
    return deep_merge(_base(), override or {})


def resolve(request):
    """The HTTP adapter: resolve for the domain this request came in on.

    Memoized on the request object -- ``/config/`` is not the only caller
    once a private section exists.
    """
    cached = getattr(request, _REQUEST_ATTR, None)
    if cached is not None:
        return cached

    resolved = resolve_for_domain(_domain(request))

    setattr(request, _REQUEST_ATTR, resolved)
    return resolved


def public_payload(request):
    """The sections ``/config/`` may serve, under the keys the frontend reads."""
    resolved = resolve(request)
    return {
        response_key: resolved.get(section) or {}
        for section, response_key in SECTIONS.items()
        if response_key is not None
    }


def check_configuration(default_config, config_overrides):
    """Validate the environment side at boot. Called from ``post_setup``.

    Deliberately shallow. It checks the *plumbing* — parseable JSON, override
    keys that can actually match a request — and nothing about the
    configuration's own keys. Validating those would be the one thing that
    stops the seven products from sharing a single file.
    """
    base = _load_inline(default_config, "DEFAULT_CONFIG")
    overrides = _load_inline(config_overrides, "CONFIG_OVERRIDES")

    for domain, override in overrides.items():
        if not isinstance(override, dict):
            raise ImproperlyConfigured(
                f"CONFIG_OVERRIDES['{domain}'] must be a JSON object, "
                f"got {type(override).__name__}."
            )

        # The key is matched against ``get_host()`` minus its port, so an
        # origin or a URL can never match it, and the operator would be left
        # wondering why their theme never shows.
        if any(char in domain for char in _NOT_IN_A_HOSTNAME):
            raise ImproperlyConfigured(
                f"CONFIG_OVERRIDES is keyed on domains, and '{domain}' is not "
                "one: give a bare hostname, with no scheme, port or path."
            )

    sources = [("DEFAULT_CONFIG", base)] + [
        (f"CONFIG_OVERRIDES['{domain}']", override)
        for domain, override in overrides.items()
    ]

    unknown_sections = sorted(
        {section for _, source in sources for section in source} - set(SECTIONS)
    )
    if unknown_sections:
        logger.warning(
            "Configuration carries section(s) this version does not know: %s. "
            "They are kept server-side and never served to the frontend.",
            ", ".join(unknown_sections),
        )

    # The likeliest way to get an unknown section is to forget the envelope,
    # so say so rather than leave the operator reading about sections.
    for label, source in sources:
        flat = sorted(_THEME_LOOKING_KEYS.intersection(source))
        if flat:
            logger.warning(
                "%s carries theme keys at its top level (%s), so it reads as a "
                "flat theme file rather than a sectioned configuration, and "
                'configures nothing. Wrap it in {"theme_customization": {...}}, '
                "or point THEME_CUSTOMIZATION_FILE_PATH at the file.",
                label,
                ", ".join(flat),
            )
