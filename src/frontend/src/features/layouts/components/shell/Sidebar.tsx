import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
// router is read in the parent to highlight the active row; navigation
// itself uses Next.js Link so the URL bar updates via client-side push.
import { Button } from "@gouvfr-lasuite/cunningham-react";
import {
  ChevronDown,
  Folder,
  Plus,
  QuestionMark,
  XMark,
  Zoom,
} from "@gouvfr-lasuite/ui-kit";
import { useTransfers } from "@/features/transfers/api/useTransfers";
import { useDebouncedValue } from "@/features/utils/use-debounced-value";
import { useConfig } from "@/features/providers/config";

export function Sidebar({ onClose }: { onClose?: () => void } = {}) {
  const { t } = useTranslation();
  const router = useRouter();
  const config = useConfig();
  const activeId =
    typeof router.query.id === "string" ? router.query.id : undefined;

  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput, 300);

  return (
    <aside className="shell-sidebar">
      <div className="shell-sidebar__header">
        <Link
          href="/"
          className="shell-sidebar__logo"
          aria-label={t("Transferts")}
        >
          <img
            src="/images/transferts-logo.svg"
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
        <Link href="/" className="shell-sidebar__nav-row">
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

// Collapsible section: clickable header with rotating chevron + flat list
// of transfers below. We dropped ui-kit's TreeView (it doesn't expose a
// collapse-by-title API) — it was only being used as a styled list of
// leaves anyway, which a plain <button>/<ul> covers with better a11y.
function TransferSection({
  label,
  deactivated,
  search,
  activeId,
  muted = false,
}: {
  label: string;
  deactivated: boolean;
  search: string;
  activeId: string | undefined;
  muted?: boolean;
}) {
  const { t } = useTranslation();
  // ``null`` = auto: open while loading or once items arrive, collapsed
  // when the loaded list is empty. Any user click flips this to a
  // concrete boolean and stops the auto-collapse from kicking back in
  // (e.g. when they wipe the section to inspect the empty state).
  const [open, setOpen] = useState<boolean | null>(null);
  const {
    data,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    isLoading,
  } = useTransfers({ deactivated, search });

  const items = data?.pages.flatMap((page) => page.results) ?? [];
  const sectionId = `shell-section-${label.replace(/\s+/g, "-").toLowerCase()}`;
  // Resolve ``open`` from the user override (if any) or fall back to the
  // auto rule: open while loading, collapsed when the loaded list is
  // empty, open otherwise.
  const effectiveOpen = open ?? (isLoading ? true : items.length > 0);

  const listRef = useRef<HTMLUListElement>(null);
  // Local pending flag: `isFetchingNextPage` takes a render cycle to flip,
  // so multiple scroll/resize ticks in the same tick would fire duplicate
  // fetches for the same page.
  const pendingRef = useRef(false);

  // Fetch the next page when the list is near-bottom OR hasn't filled
  // its container yet. Re-runs on every relevant state change so we
  // don't rely on a single observer firing at the exact right moment —
  // scroll, resize, data arrival, and open-toggle all re-trigger it.
  useEffect(() => {
    const ul = listRef.current;
    if (!ul || !effectiveOpen) return;

    const maybeFetch = () => {
      if (pendingRef.current || !hasNextPage || isFetchingNextPage) return;
      const { scrollTop, scrollHeight, clientHeight } = ul;
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
  }, [effectiveOpen, hasNextPage, isFetchingNextPage, fetchNextPage, data]);

  return (
    <section
      className={`shell-sidebar__section shell-sidebar__section--${
        deactivated ? "deactivated" : "active"
      }${effectiveOpen ? " shell-sidebar__section--open" : ""}`}
    >
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
      <div
        className={`shell-sidebar__section-collapse${
          effectiveOpen ? " shell-sidebar__section-collapse--open" : ""
        }`}
      >
        <ul ref={listRef} id={sectionId} className="shell-sidebar__section-list">
          {items.length === 0 && !isLoading ? (
            <li className="shell-sidebar__empty">
              {search
                ? t("No matching transfers")
                : deactivated
                  ? t("No deactivated transfers")
                  : t("No active transfers")}
            </li>
          ) : (
            items.map((item) => (
              <li
                key={item.id}
                className={`shell-sidebar__tree-row${
                  item.id === activeId ? " shell-sidebar__tree-row--active" : ""
                }`}
              >
                <Link
                  href={`/transfers/${item.id}`}
                  className="shell-sidebar__tree-row-link"
                >
                  <Folder
                    className={`shell-sidebar__tree-row-icon${
                      muted ? " shell-sidebar__tree-row-icon--muted" : ""
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
      </div>
    </section>
  );
}
