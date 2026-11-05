"""Tests for the per-request deployment configuration resolver."""

import json
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured

import pytest

from core import runtime_config
from core.runtime_config import (
    SECTIONS,
    check_configuration,
    deep_merge,
    resolve_for_domain,
)

FIXTURES = Path(__file__).parent / "fixtures"


def write_json(path, payload):
    """Write one of the configuration files a deployment would mount."""
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class TestDeepMerge:
    """The merge rule the whole mechanism rests on."""

    def test_adds_missing_keys(self):
        """An override adds what the base never had."""
        assert deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_recurses_into_dicts(self):
        """A nested key is merged, not replaced along with its siblings."""
        merged = deep_merge(
            {"help": {"documentation_url": "d", "support_url": "s"}},
            {"help": {"support_url": "s2"}},
        )
        assert merged == {"help": {"documentation_url": "d", "support_url": "s2"}}

    def test_lists_replace_rather_than_concatenate(self):
        """An override must be able to *remove* a link, not only add one."""
        merged = deep_merge({"links": [1, 2, 3]}, {"links": [4]})
        assert merged == {"links": [4]}

    def test_explicit_null_hides_a_base_value(self):
        """Absent means hidden front-side, so null is how an override hides."""
        assert deep_merge({"logo": {"src": "a.svg"}}, {"logo": None}) == {"logo": None}

    def test_scalar_over_dict_replaces(self):
        """Only two dicts recurse; anything else replaces wholesale."""
        assert deep_merge({"a": {"b": 1}}, {"a": "x"}) == {"a": "x"}

    def test_leaves_the_base_untouched(self):
        """A mutating merge would leak between requests through the cached
        file contents, which are shared."""
        base = {"help": {"documentation_url": "d"}}
        deep_merge(base, {"help": {"documentation_url": "other"}})
        assert base == {"help": {"documentation_url": "d"}}


class TestSections:
    """The public/private frontier."""

    def test_theme_is_the_only_public_section(self):
        """Pinned on purpose: adding a public section is a security decision,
        so it has to break this test and be made deliberately."""
        public = {name for name, key in SECTIONS.items() if key is not None}
        assert public == {"theme_customization"}

    def test_the_section_carries_the_name_it_is_served_under(self):
        """``docs`` and ``drive`` both call it ``theme_customization``; a
        third name would be one vocabulary too many. The section is named
        after it too, so the name holds from the environment variable
        through to the browser."""
        assert SECTIONS["theme_customization"] == "theme_customization"


class TestCheckConfiguration:
    """Boot-time validation of the plumbing — not of the keys."""

    def test_accepts_an_empty_environment(self):
        """A default install configures nothing, and must still boot."""
        check_configuration("", "")

    def test_rejects_malformed_json(self):
        """A stray comma fails the boot rather than serving nobody's theme."""
        with pytest.raises(ImproperlyConfigured, match="DEFAULT_CONFIG is not valid"):
            check_configuration('{"theme_customization": }', "")

    def test_rejects_a_non_object(self):
        """The envelope is an object; a list configures nothing."""
        with pytest.raises(ImproperlyConfigured, match="must be a JSON object"):
            check_configuration("[1, 2]", "")

    def test_rejects_a_non_object_override(self):
        """Named in the message: with several domains, which one is wrong is
        the only thing the operator needs to know."""
        with pytest.raises(
            ImproperlyConfigured, match=r"CONFIG_OVERRIDES\['opsn1.fr'\]"
        ):
            check_configuration("", json.dumps({"opsn1.fr": "not-an-object"}))

    @pytest.mark.parametrize(
        "domain",
        [
            "https://opsn1.fr",
            "opsn1.fr:9980",
            "opsn1.fr/app",
            "contact@opsn1.fr",
            "opsn1.fr ",
        ],
    )
    def test_rejects_a_key_that_is_not_a_bare_domain(self, domain):
        """A key is matched against the request's host minus its port, so an
        origin or a URL can never match — and the theme would silently never
        show, which is exactly what failing the boot is for."""
        with pytest.raises(ImproperlyConfigured, match="keyed on domains"):
            check_configuration("", json.dumps({domain: {"theme_customization": {}}}))

    def test_accepts_a_base_and_an_override(self):
        """The shape an instance with two domains actually ships."""
        check_configuration(
            json.dumps({"theme_customization": {"fontFamily": "Inter"}}),
            json.dumps({"opsn1.fr": {"theme_customization": {"colors": {}}}}),
        )

    def test_warns_on_an_unknown_section(self):
        """Asserted on the module logger: ``core`` does not propagate to
        caplog, as the authentication tests already note."""
        with mock.patch.object(runtime_config.logger, "warning") as warning:
            check_configuration(json.dumps({"auth": {"issuer": "x"}}), "")

        assert warning.called
        assert "section(s) this version does not know" in warning.call_args[0][0]
        assert "auth" in str(warning.call_args_list)

    def test_warns_on_an_unknown_section_inside_an_override(self):
        """A shared file may carry another product's sections; they must be
        reported, and kept server-side, wherever they appear."""
        with mock.patch.object(runtime_config.logger, "warning") as warning:
            check_configuration("", json.dumps({"opsn1.fr": {"auth": {"issuer": "x"}}}))

        assert warning.called
        assert "auth" in str(warning.call_args_list)


@pytest.mark.usefixtures("blank_config")
class TestFileSources:
    """Every variable has a ``*_FILE_PATH`` sibling.

    The file is the base and the inline value merges over it, so a deployment
    can mount an operator's configuration and still tweak one key from the
    environment. The precedence between the five sources is the whole contract.
    """

    def test_the_theme_file_becomes_the_theme_section(self, blank_config, tmp_path):
        """A theme file written for ``docs`` is flat; the resolver wraps it.

        That wrapping is what lets one drop in with no translation at all.
        """
        blank_config.THEME_CUSTOMIZATION_FILE_PATH = write_json(
            tmp_path / "theme.json", {"fontFamily": "Inter"}
        )

        assert resolve_for_domain("example.test") == {
            "theme_customization": {"fontFamily": "Inter"}
        }

    def test_the_inline_variable_wins_over_its_file(self, blank_config, tmp_path):
        """A mounted file, one key corrected from the environment."""
        blank_config.DEFAULT_CONFIG_FILE_PATH = write_json(
            tmp_path / "config.json",
            {"theme_customization": {"fontFamily": "Inter", "colors": {"--a": "#000"}}},
        )
        blank_config.DEFAULT_CONFIG = json.dumps(
            {"theme_customization": {"fontFamily": "Georgia"}}
        )

        theme = resolve_for_domain("example.test")["theme_customization"]

        assert theme["fontFamily"] == "Georgia"
        assert theme["colors"] == {"--a": "#000"}

    def test_the_two_override_sources_merge_across_spellings(
        self, blank_config, tmp_path
    ):
        """One domain, written two ways, is still one domain.

        The same contract as ``test_the_inline_variable_wins_over_its_file``,
        and it has to survive a file that spells the key ``CD33.test`` while
        the environment spells it ``cd33.test``. Both fold to the domain the
        request resolves on, so the inline source must merge onto the file's
        configuration rather than replace it.
        """
        blank_config.CONFIG_OVERRIDES_FILE_PATH = write_json(
            tmp_path / "overrides.json",
            {
                "CD33.test": {
                    "theme_customization": {
                        "fontFamily": "Inter",
                        "colors": {"--a": "#000"},
                    }
                }
            },
        )
        blank_config.CONFIG_OVERRIDES = json.dumps(
            {"cd33.test": {"theme_customization": {"fontFamily": "Georgia"}}}
        )

        theme = resolve_for_domain("cd33.test")["theme_customization"]

        assert theme["fontFamily"] == "Georgia"
        assert theme["colors"] == {"--a": "#000"}

    def test_the_five_sources_resolve_in_order(self, blank_config, tmp_path):
        """The precedence chain, end to end: theme file, then the sectioned
        file, then the sectioned variable, then the domain's file, then the
        domain's variable. Each source contributes a key of its own, and each
        one claims the same contested key."""
        blank_config.THEME_CUSTOMIZATION_FILE_PATH = write_json(
            tmp_path / "theme.json", {"one": True, "winner": "theme-file"}
        )
        blank_config.DEFAULT_CONFIG_FILE_PATH = write_json(
            tmp_path / "base.json",
            {"theme_customization": {"two": True, "winner": "base-file"}},
        )
        blank_config.DEFAULT_CONFIG = json.dumps(
            {"theme_customization": {"three": True, "winner": "base-inline"}}
        )
        blank_config.CONFIG_OVERRIDES_FILE_PATH = write_json(
            tmp_path / "overrides.json",
            {
                "opsn1.test": {
                    "theme_customization": {"four": True, "winner": "override-file"}
                }
            },
        )
        blank_config.CONFIG_OVERRIDES = json.dumps(
            {
                "opsn1.test": {
                    "theme_customization": {"five": True, "winner": "override-inline"}
                }
            }
        )

        assert resolve_for_domain("opsn1.test")["theme_customization"] == {
            "one": True,
            "two": True,
            "three": True,
            "four": True,
            "five": True,
            "winner": "override-inline",
        }

        # The same base, and nothing from either override source, on a domain
        # the overrides don't name.
        assert resolve_for_domain("example.test")["theme_customization"] == {
            "one": True,
            "two": True,
            "three": True,
            "winner": "base-inline",
        }

    def test_a_file_read_is_cached(self, blank_config, tmp_path):
        """``CONFIG_CACHE_TIMEOUT`` governs this — and it governs *every* file
        the resolver reads, which is why it no longer carries a ``THEME_`` name.
        A deployment that replaces a mounted file waits out the cache; it does
        not restart the process."""
        path = tmp_path / "theme.json"
        blank_config.THEME_CUSTOMIZATION_FILE_PATH = write_json(
            path, {"fontFamily": "Inter"}
        )

        first = resolve_for_domain("example.test")
        write_json(path, {"fontFamily": "Georgia"})

        assert resolve_for_domain("example.test") == first

        cache.clear()

        assert resolve_for_domain("example.test") == {
            "theme_customization": {"fontFamily": "Georgia"}
        }


@pytest.mark.usefixtures("blank_config")
class TestDocsCompatibility:
    """The superset property, guarded.

    The theme section is shaped as a superset of the theme customization JSON
    of ``docs`` and ``drive``, which is what will let the Suite's products
    converge on a single file. If a test here fails, that convergence is off:
    a file written for ``docs`` no longer survives this resolver.
    """

    #: ``src/backend/impress/configuration/theme/default.json`` of ``docs``,
    #: copied verbatim at revision 4e6d28e2 (2026-07-27). Same licence, same
    #: copyright holder. Refresh it when ``docs`` changes its own.
    DOCS_THEME = FIXTURES / "docs_theme_default.json"

    @classmethod
    def docs_theme(cls):
        """``docs``' own default theme, parsed afresh for each comparison."""
        return json.loads(cls.DOCS_THEME.read_text(encoding="utf-8"))

    def test_the_docs_default_theme_travels_through_unchanged(self, blank_config):
        """The test that stands for all the others: ``docs``' own theme file,
        in and out of the resolver, identical. Nothing validated key by key,
        nothing rewritten, nothing dropped."""
        blank_config.THEME_CUSTOMIZATION_FILE_PATH = str(self.DOCS_THEME)

        resolved = resolve_for_domain("example.test")

        assert resolved == {"theme_customization": self.docs_theme()}

    def test_a_flat_file_composes_with_the_inline_variable(self, blank_config):
        """One key overridden, its neighbours in the same subtree intact — the
        property an operator relies on to adjust a mounted file."""
        blank_config.THEME_CUSTOMIZATION_FILE_PATH = str(self.DOCS_THEME)
        blank_config.DEFAULT_CONFIG = json.dumps(
            {
                "theme_customization": {
                    "help": {"documentation_url": "https://help.opsn1.test"}
                }
            }
        )

        theme = resolve_for_domain("example.test")["theme_customization"]
        docs_theme = self.docs_theme()

        assert theme["help"]["documentation_url"] == "https://help.opsn1.test"
        # Same subtree, untouched.
        assert theme["help"]["legal_links"] == docs_theme["help"]["legal_links"]
        assert theme["help"]["support_mailto"] == docs_theme["help"]["support_mailto"]
        # And the rest of the file.
        assert theme["footer"] == docs_theme["footer"]
        assert theme["header"] == docs_theme["header"]

    def test_a_malformed_file_degrades_without_stopping_the_process(
        self, blank_config, tmp_path
    ):
        """The migration test: adopting the mechanism must not give a product a
        *new* way to refuse to start.

        Unlike the inline variables, which are fixed at deploy time and fail
        the boot, a file comes from a mount that can be replaced under a
        running process. Serving the neutral theme beats taking the instance
        down.
        """
        path = tmp_path / "theme.json"
        path.write_text('{"help": }', encoding="utf-8")
        blank_config.THEME_CUSTOMIZATION_FILE_PATH = str(path)

        with mock.patch.object(runtime_config.logger, "error") as error:
            resolved = resolve_for_domain("example.test")

        assert resolved == {}
        assert error.called

    def test_a_missing_file_degrades_without_stopping_the_process(
        self, blank_config, tmp_path
    ):
        """A mount that isn't there yet, same reasoning."""
        blank_config.THEME_CUSTOMIZATION_FILE_PATH = str(tmp_path / "absent.json")

        with mock.patch.object(runtime_config.logger, "error") as error:
            resolved = resolve_for_domain("example.test")

        assert resolved == {}
        assert error.called

    def test_a_file_that_cannot_be_read_is_not_read_again_at_once(
        self, blank_config, tmp_path
    ):
        """The failure is cached too, or a missing mount costs an ``open()``
        and an ERROR line on every request for as long as it is missing --
        which on a public instance is a log flood, not a hint."""
        blank_config.THEME_CUSTOMIZATION_FILE_PATH = str(tmp_path / "absent.json")

        with mock.patch.object(runtime_config.logger, "error") as error:
            assert resolve_for_domain("example.test") == {}
            assert resolve_for_domain("example.test") == {}

        assert error.call_count == 1


@pytest.mark.usefixtures("blank_config")
class TestResolveForDomain:
    """Resolution without a request.

    The resolver takes a domain, not a request, because a background task has
    no request: the domain does not survive a ``.send()`` on its own, and a
    task that needs configuration carries the request origin and resolves from
    its hostname. ``resolve(request)`` is the HTTP adapter over this.
    """

    @pytest.fixture(autouse=True)
    def _two_domains(self, blank_config):
        """A base and one override, the smallest multi-operator instance."""
        blank_config.DEFAULT_CONFIG = json.dumps(
            {"theme_customization": {"fontFamily": "Inter"}}
        )
        blank_config.CONFIG_OVERRIDES = json.dumps(
            {"opsn1.test": {"theme_customization": {"fontFamily": "Georgia"}}}
        )

    def test_a_non_object_override_serves_the_base(self, blank_config, tmp_path):
        """``check_configuration`` refuses this at boot, but only in the
        environment variable: the file is read per request and can be replaced
        under a running process. Merging a scalar would hand every caller a
        string where a mapping is expected, so the domain would answer 500
        until someone noticed. It gets the base instead, and a log line."""
        blank_config.CONFIG_OVERRIDES = ""
        blank_config.CONFIG_OVERRIDES_FILE_PATH = write_json(
            tmp_path / "overrides.json", {"opsn1.test": "not-an-object"}
        )

        with mock.patch.object(runtime_config.logger, "error") as error:
            resolved = resolve_for_domain("opsn1.test")

        assert resolved == {"theme_customization": {"fontFamily": "Inter"}}
        assert error.called

    @pytest.mark.parametrize("domain", ["opsn1.test", "OPSN1.test"])
    def test_resolves_an_override_with_no_request_in_sight(self, domain):
        """Case folded on the way in: DNS is case-insensitive, so a capital is
        a cosmetic choice, not another domain."""
        assert resolve_for_domain(domain) == {
            "theme_customization": {"fontFamily": "Georgia"}
        }

    @pytest.mark.parametrize("domain", ["example.test", "", None])
    def test_an_unmatched_or_missing_domain_gets_the_base(self, domain):
        """A task that never knew its origin still resolves — to the base,
        which is the neutral configuration, not an empty one."""
        assert resolve_for_domain(domain) == {
            "theme_customization": {"fontFamily": "Inter"}
        }
