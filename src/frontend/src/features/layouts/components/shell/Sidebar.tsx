import { useMemo, useState } from "react";
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
  Zoom,
} from "@gouvfr-lasuite/ui-kit";
import { useTransfers } from "@/features/transfers/api/useTransfers";
import type { TransferListItem } from "@/features/api/types";
import { useConfig } from "@/features/providers/config";

export function Sidebar() {
  const { t } = useTranslation();
  const router = useRouter();
  const config = useConfig();
  const activeId =
    typeof router.query.id === "string" ? router.query.id : undefined;
  // Sidebar lists every transfer the user owns so the "Deactivated" section
  // isn't blind to older terminal ones. 200 matches the API's max_page_size;
  // past that we'd need infinite scroll, but that's a future-user problem.
  const { data } = useTransfers(1, 200);

  const [query, setQuery] = useState("");

  const { actives, archives } = useMemo(() => {
    const items = data?.results ?? [];
    const filter = (arr: TransferListItem[]) => {
      const q = query.trim().toLowerCase();
      if (!q) return arr;
      return arr.filter((it) =>
        (it.title || t("Untitled")).toLowerCase().includes(q),
      );
    };
    return {
      actives: filter(items.filter((it) => it.status === "active")),
      archives: filter(items.filter((it) => it.status !== "active")),
    };
  }, [data, query, t]);

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
      </div>

      <div className="shell-sidebar__top">
        <Link
          href="/"
          className="shell-sidebar__nav-row"
          onClick={() => {
            // If the user is already on `/` viewing a success panel from
            // a just-finalized transfer, Next.js Link treats this as a
            // no-op (same URL) and the form stays stuck on the confirm
            // screen. Broadcast a reset signal that TransferForm
            // listens to so the form bounces back to its empty state.
            if (router.pathname === "/") {
              window.dispatchEvent(new CustomEvent("transferts:new-transfer"));
            }
          }}
        >
          <Plus />
          <span>{t("New transfer")}</span>
        </Link>

        <div className="shell-sidebar__nav-row shell-sidebar__nav-row--input">
          <Zoom />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("Search")}
            aria-label={t("Search transfers")}
          />
        </div>
      </div>

      <div className="shell-sidebar__tree">
        <TransferSection
          label={t("Active transfers")}
          items={actives}
          activeId={activeId}
        />
        <TransferSection
          label={t("Deactivated transfers")}
          items={archives}
          activeId={activeId}
          muted
        />
      </div>

      <div className="shell-sidebar__flex" />

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
  items,
  activeId,
  muted = false,
}: {
  label: string;
  items: TransferListItem[];
  activeId: string | undefined;
  muted?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);
  const sectionId = `shell-section-${label.replace(/\s+/g, "-").toLowerCase()}`;

  return (
    <section className="shell-sidebar__section">
      <button
        type="button"
        className="shell-sidebar__section-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={sectionId}
      >
        <span>{label}</span>
        <ChevronDown
          className={`shell-sidebar__section-chevron${
            open ? "" : " shell-sidebar__section-chevron--closed"
          }`}
        />
      </button>
      <div
        className={`shell-sidebar__section-collapse${
          open ? " shell-sidebar__section-collapse--open" : ""
        }`}
      >
        <ul id={sectionId} className="shell-sidebar__section-list">
          {items.map((item) => (
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
          ))}
        </ul>
      </div>
    </section>
  );
}
