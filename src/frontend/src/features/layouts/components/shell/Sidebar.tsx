import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import {
  Icon,
  IconType,
  TreeProvider,
  TreeView,
  TreeViewItem,
  TreeViewNodeTypeEnum,
  type TreeViewDataType,
  type TreeViewNodeProps,
} from "@gouvfr-lasuite/ui-kit";
import { useTransfers } from "@/features/transfers/api/useTransfers";
import type { TransferListItem } from "@/features/api/types";

type TransferNode = TransferListItem;

export function Sidebar() {
  const { t } = useTranslation();
  const router = useRouter();
  const activeId =
    typeof router.query.id === "string" ? router.query.id : undefined;
  const { data } = useTransfers(1);

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
            height={28}
          />
        </Link>
      </div>

      <div className="shell-sidebar__top">
        <Link href="/" className="shell-sidebar__nav-row">
          <Icon name="add" />
          <span>{t("New transfer")}</span>
        </Link>

        <div className="shell-sidebar__nav-row shell-sidebar__nav-row--input">
          <Icon name="search" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("Search")}
            aria-label={t("Search transfers")}
          />
        </div>
      </div>

      <TransferTree actives={actives} archives={archives} activeId={activeId} />

      <div className="shell-sidebar__flex" />

      <div className="shell-sidebar__footer">
        <Button
          color="neutral"
          size="small"
          icon={<Icon name="help" type={IconType.OUTLINED} />}
          aria-label={t("Help")}
          title={t("Help")}
        />
        <Button
          color="neutral"
          size="small"
          icon={<Icon name="settings" type={IconType.OUTLINED} />}
          aria-label={t("Settings")}
          title={t("Settings")}
        />
      </div>
    </aside>
  );
}

// Two TITLE sections + NODE leaves is the pattern we draw from the Figma
// handoff (each transfer is a Tree Part, each section header a Title Section).
function TransferTree({
  actives,
  archives,
  activeId,
}: {
  actives: TransferListItem[];
  archives: TransferListItem[];
  activeId?: string;
}) {
  const { t } = useTranslation();
  const router = useRouter();

  const toNode = (item: TransferListItem): TreeViewDataType<TransferNode> => ({
    ...item,
  });

  // Key changes when the dataset shifts so TreeProvider re-seeds (it only
  // reads initialTreeData on mount).
  const dataKey = useMemo(
    () =>
      [...actives, ...archives]
        .map((i) => `${i.id}:${i.status}`)
        .join("|"),
    [actives, archives],
  );

  const initialTreeData: TreeViewDataType<TransferNode>[] = [
    {
      id: "__section-actives",
      nodeType: TreeViewNodeTypeEnum.TITLE,
      headerTitle: t("Active transfers"),
      children: actives.map(toNode),
    },
    {
      id: "__section-archives",
      nodeType: TreeViewNodeTypeEnum.TITLE,
      headerTitle: t("Archives"),
      children: archives.map(toNode),
    },
  ];

  return (
    <TreeProvider<TransferNode>
      key={dataKey}
      initialTreeData={initialTreeData}
    >
      <TreeView<TransferNode>
        rootNodeId="__root"
        selectedNodeId={activeId}
        initialOpenState={{
          "__section-actives": true,
          "__section-archives": true,
        }}
        renderNode={(props) => (
          <TransferTreeItem
            {...props}
            onNavigate={(id) => router.push(`/transfers/${id}`)}
          />
        )}
      />
    </TreeProvider>
  );
}

function TransferTreeItem(
  props: TreeViewNodeProps<TransferNode> & {
    onNavigate: (id: string) => void;
  },
) {
  const { t } = useTranslation();
  const { node, onNavigate, ...itemProps } = props;
  const data = node.data;

  // ui-kit dispatches TITLE / SEPARATOR / VIEW_MORE nodes internally —
  // renderNode is only called for NODE / SIMPLE_NODE leaves in our shape.
  return (
    <TreeViewItem
      {...itemProps}
      node={node}
      onClick={() => onNavigate(data.value.id)}
    >
      <Icon
        name="folder"
        type={IconType.OUTLINED}
        className={
          "status" in data.value && data.value.status !== "active"
            ? "shell-sidebar__tree-row-icon shell-sidebar__tree-row-icon--muted"
            : "shell-sidebar__tree-row-icon"
        }
      />
      <span className="shell-sidebar__tree-row-label">
        {("title" in data.value && data.value.title) || t("Untitled")}
      </span>
      <button
        type="button"
        className="shell-sidebar__tree-row-menu"
        aria-label={t("More actions")}
        title={t("More actions")}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        <Icon name="more_horiz" />
      </button>
    </TreeViewItem>
  );
}
