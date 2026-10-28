import { ReactNode, useEffect, useRef, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
// The active transfer id is read from the matched route params to highlight
// the corresponding row; navigation itself uses TanStack Router's Link so the
// URL bar updates via client-side navigation.
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { ChevronDown, Folder, More, Plus, QuestionMark, XMark, Zoom } from "@gouvfr-lasuite/ui-kit/icons";
import type { DepositSpace } from "@/features/api/types";
import { useDepositSpaces } from "@/features/deposits/api/useDepositSpaces";
import { useTransfers } from "@/features/transfers/api/useTransfers";
import { useDebouncedValue } from "@/features/utils/use-debounced-value";
import { useConfig } from "@/features/providers/config";

export function Sidebar({ onClose }: { onClose?: () => void } = {}) {
  const { t } = useTranslation();
  const config = useConfig();
  // `strict: false` reads params from whatever route is currently matched —
  // returns `{ id }` on /transfers/$id, an empty object elsewhere.
  const { id: activeId } = useParams({ strict: false }) as { id?: string };
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput, 300);

  return (
    <aside className="shell-sidebar">
      <div className="shell-sidebar__header">
        <Link
          to="/"
          className="shell-sidebar__logo"
          aria-label={t("Transferts")}
        >
          <img
            src="/images/transfers-logo.svg"
            alt="Transferts"
            height={36}
          />
        </Link>
        {onClose && (
          // Mobile-only close button — hidden via CSS on desktop where
          // the sidebar is always visible. The TopBar burger toggles the
          // same state, but having the affordance from inside the drawer
          // matches the user's mental model when the drawer is open.
          <button
            type="button"
            className="shell-sidebar__close"
            onClick={onClose}
            aria-label={t("Close sidebar")}
            title={t("Close sidebar")}
          >
            <XMark />
          </button>
        )}
      </div>

      <div className="shell-sidebar__top">
        <Link to="/" className="shell-sidebar__nav-row">
          <Plus />
          <span>{t("New transfer")}</span>
        </Link>

        <div className="shell-sidebar__nav-row shell-sidebar__nav-row--input">
          <Zoom />
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder={t("Search")}
            aria-label={t("Search transfers")}
          />
          {searchInput && (
            <button
              type="button"
              className="shell-sidebar__nav-row-clear"
              onClick={() => setSearchInput("")}
              aria-label={t("Clear search")}
              title={t("Clear search")}
            >
              <XMark />
            </button>
          )}
        </div>
      </div>

      <div className="shell-sidebar__tree">
        <TransferSection
          label={t("Active transfers")}
          deactivated={false}
          search={search}
          activeId={activeId}
        />
        <TransferSection
          label={t("Deactivated transfers")}
          deactivated={true}
          search={search}
          activeId={activeId}
          muted
        />
        {config.INBOX_ENABLED && (
          <TransferSection
            label={t("Inbox")}
            filters={INBOX_FILTERS}
            search={search}
            activeId={activeId}
            emptyLabel={t("Nothing received yet")}
          />
        )}
        <SpacesSection search={search} activeId={activeId} />
      </div>

      <div className="shell-sidebar__footer">
        {config.HELP_URL && (
          <Button
            color="neutral"
            variant="tertiary"
            size="small"
            icon={<QuestionMark />}
            aria-label={t("Help")}
            title={t("Help")}
            href={config.HELP_URL}
            target="_blank"
            rel="noopener noreferrer"
          />
        )}
      </div>
    </aside>
  );
}

// Files sent to the agent's own address by people without an account.
const INBOX_FILTERS = { direction: "inbound", inbox: "true" };

// Collapsible section: clickable header with rotating chevron, an optional
// action just before the chevron, and its content below. We dropped
// ui-kit's TreeView (it doesn't expose a collapse-by-title API) — a plain
// <button>/<ul> covers it with better a11y.
function Section({
  label,
  isEmpty,
  isLoading,
  action,
  children,
}: {
  label: string;
  isEmpty: boolean;
  isLoading: boolean;
  action?: ReactNode;
  children: ReactNode;
}) {
  // ``null`` = auto: open while loading or once items arrive, collapsed
  // when the loaded list is empty. Any user click flips this to a
  // concrete boolean and stops the auto-collapse from kicking back in
  // (e.g. when they wipe the section to inspect the empty state).
  const [open, setOpen] = useState<boolean | null>(null);
  const effectiveOpen = open ?? (isLoading ? true : !isEmpty);
  const sectionId = `shell-section-${label.replace(/\s+/g, "-").toLowerCase()}`;

  return (
    <section
      className={`shell-sidebar__section${
        effectiveOpen ? " shell-sidebar__section--open" : ""
      }`}
    >
      <div className="shell-sidebar__section-head">
        <button
          type="button"
          className="shell-sidebar__section-header"
          onClick={() => setOpen(!effectiveOpen)}
          aria-expanded={effectiveOpen}
          aria-controls={sectionId}
        >
          <span>{label}</span>
          <ChevronDown
            className={`shell-sidebar__section-chevron${
              effectiveOpen ? "" : " shell-sidebar__section-chevron--closed"
            }`}
          />
        </button>
        {action}
      </div>
      <div
        id={sectionId}
        className={`shell-sidebar__section-collapse${
          effectiveOpen ? " shell-sidebar__section-collapse--open" : ""
        }`}
      >
        {children}
      </div>
    </section>
  );
}

type TransferQuery = ReturnType<typeof useTransfers>;

// A section listing transfers: sent ones by status, or the inbox.
function TransferSection({
  label,
  deactivated,
  filters,
  search,
  activeId,
  emptyLabel,
  muted = false,
}: {
  label: string;
  deactivated?: boolean;
  filters?: Record<string, string>;
  search: string;
  activeId: string | undefined;
  emptyLabel?: string;
  muted?: boolean;
}) {
  const { t } = useTranslation();
  const query = useTransfers({ deactivated, filters, search });
  const items = query.data?.pages.flatMap((page) => page.results) ?? [];
  return (
    <Section label={label} isEmpty={items.length === 0} isLoading={query.isLoading}>
      <TransferList
        query={query}
        activeId={activeId}
        muted={muted}
        emptyLabel={
          search
            ? t("No matching transfers")
            : (emptyLabel ??
              (deactivated
                ? t("No deactivated transfers")
                : t("No active transfers")))
        }
      />
    </Section>
  );
}

// Transfer rows, fetching the next page as the list nears its bottom.
// Rows of a transfer that is no longer active are muted.
function TransferList({
  query,
  activeId,
  emptyLabel,
  muted = false,
  nested = false,
}: {
  query: TransferQuery;
  activeId: string | undefined;
  emptyLabel: string;
  muted?: boolean;
  nested?: boolean;
}) {
  const { t } = useTranslation();
  const { data, hasNextPage, isFetchingNextPage, fetchNextPage, isLoading } =
    query;
  const items = data?.pages.flatMap((page) => page.results) ?? [];

  const listRef = useRef<HTMLUListElement>(null);
  // Local pending flag: `isFetchingNextPage` takes a render cycle to flip,
  // so multiple scroll/resize ticks in the same tick would fire duplicate
  // fetches for the same page.
  const pendingRef = useRef(false);

  // Fetch the next page when the list is near-bottom OR hasn't filled
  // its container yet. Re-runs on every relevant state change so we
  // don't rely on a single observer firing at the exact right moment —
  // scroll, resize and data arrival all re-trigger it.
  useEffect(() => {
    const ul = listRef.current;
    if (!ul) return;

    const maybeFetch = () => {
      if (pendingRef.current || !hasNextPage || isFetchingNextPage) return;
      const { scrollTop, scrollHeight, clientHeight } = ul;
      // Collapsed section (display: none): the ResizeObserver fires again
      // when it opens.
      if (clientHeight === 0) return;
      // Keep at least ~2 viewports of un-scrolled rows ahead of the user
      // so a fast wheel/trackpad flick doesn't run into the blank bottom
      // before the next page arrives.
      const lookahead = Math.max(1200, clientHeight * 2);
      if (scrollHeight - scrollTop - clientHeight < lookahead) {
        pendingRef.current = true;
        void fetchNextPage().finally(() => {
          pendingRef.current = false;
        });
      }
    };

    ul.addEventListener("scroll", maybeFetch, { passive: true });
    const ro = new ResizeObserver(maybeFetch);
    ro.observe(ul);
    maybeFetch();

    return () => {
      ul.removeEventListener("scroll", maybeFetch);
      ro.disconnect();
    };
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, data]);

  return (
    <ul
      ref={listRef}
      className={`shell-sidebar__section-list${
        nested ? " shell-sidebar__section-list--nested" : ""
      }`}
    >
      {items.length === 0 && !isLoading ? (
        <li className="shell-sidebar__empty">{emptyLabel}</li>
      ) : (
        items.map((item) => (
          <li
            key={item.id}
            className={`shell-sidebar__tree-row${
              item.id === activeId ? " shell-sidebar__tree-row--active" : ""
            }`}
          >
            <Link
              to="/transfers/$id"
              params={{ id: item.id }}
              className="shell-sidebar__tree-row-link"
            >
              <Folder
                className={`shell-sidebar__tree-row-icon${
                  muted || item.status !== "active"
                    ? " shell-sidebar__tree-row-icon--muted"
                    : ""
                }`}
              />
              <span className="shell-sidebar__tree-row-label">
                {item.title || t("Untitled")}
              </span>
            </Link>
          </li>
        ))
      )}
    </ul>
  );
}

// The agent's deposit spaces, each unfolding into its deposits. A revoked
// space stays while it holds deposits, so they remain reachable. The "+"
// (and the placeholder before a first space) and each space's "…" lead to
// the pages that create and manage them.
function SpacesSection({
  search,
  activeId,
}: {
  search: string;
  activeId: string | undefined;
}) {
  const { t } = useTranslation();
  const { data, isLoading } = useDepositSpaces();
  const spaces = (data?.results ?? []).filter(
    (s) => !s.revoked_at || s.deposit_count > 0,
  );
  return (
    <Section
      label={t("Deposit spaces")}
      // Open even without a space: its placeholder invites to create one.
      isEmpty={false}
      isLoading={isLoading}
      action={
        <Link
          to="/spaces"
          className="shell-sidebar__section-action"
          aria-label={t("New deposit space")}
          title={t("New deposit space")}
        >
          <Plus />
        </Link>
      }
    >
      <ul className="shell-sidebar__section-list">
        {spaces.map((space) => (
          <SpaceNode
            key={space.id}
            space={space}
            search={search}
            activeId={activeId}
          />
        ))}
        {!isLoading && spaces.length === 0 && (
          <li className="shell-sidebar__tree-row">
            <Link
              to="/spaces"
              className="shell-sidebar__tree-row-link shell-sidebar__tree-row-link--muted"
            >
              <Plus className="shell-sidebar__tree-row-icon shell-sidebar__tree-row-icon--muted" />
              <span className="shell-sidebar__tree-row-label">
                {t("New deposit space")}
              </span>
            </Link>
          </li>
        )}
      </ul>
    </Section>
  );
}

function SpaceNode({
  space,
  search,
  activeId,
}: {
  space: DepositSpace;
  search: string;
  activeId: string | undefined;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const listId = `shell-space-${space.id}`;
  return (
    <li>
      <div
        className={`shell-sidebar__tree-row${
          space.id === activeId ? " shell-sidebar__tree-row--active" : ""
        }`}
      >
        <button
          type="button"
          className="shell-sidebar__tree-row-link shell-sidebar__tree-row-toggle"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls={listId}
        >
          <ChevronDown
            className={`shell-sidebar__section-chevron${
              open ? "" : " shell-sidebar__section-chevron--closed"
            }`}
          />
          <span
            className={`shell-sidebar__tree-row-label${
              space.revoked_at ? " shell-sidebar__tree-row-label--muted" : ""
            }`}
          >
            {space.revoked_at
              ? t("{{name}} (closed)", { name: space.name })
              : space.name}
          </span>
        </button>
        <Link
          to="/spaces/$id"
          params={{ id: space.id }}
          className="shell-sidebar__tree-row-menu"
          aria-label={t("Manage {{name}}", { name: space.name })}
          title={t("Manage {{name}}", { name: space.name })}
        >
          <More />
        </Link>
      </div>
      {open && (
        <div id={listId}>
          <SpaceDeposits spaceId={space.id} search={search} activeId={activeId} />
        </div>
      )}
    </li>
  );
}

// Mounted only once the space is unfolded, so closed spaces cost no request.
function SpaceDeposits({
  spaceId,
  search,
  activeId,
}: {
  spaceId: string;
  search: string;
  activeId: string | undefined;
}) {
  const { t } = useTranslation();
  const query = useTransfers({
    filters: { direction: "inbound", deposit_space: spaceId },
    search,
  });
  return (
    <TransferList
      query={query}
      activeId={activeId}
      nested
      emptyLabel={search ? t("No matching transfers") : t("No deposit yet")}
    />
  );
}
