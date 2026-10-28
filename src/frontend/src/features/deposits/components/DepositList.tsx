import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { RelativeDate } from "@/features/ui/components/relative-date";
import { formatFileSize } from "@/features/utils/string-helper";
import { useInboundTransfers } from "../api/useInboundTransfers";

// Deposits received on a space, or (no ``spaceId``) the anonymous sends.
export function DepositList({ spaceId }: { spaceId?: string }) {
  const { t } = useTranslation();
  const {
    data,
    isLoading,
    isError,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useInboundTransfers(spaceId);
  const deposits = data?.pages.flatMap((page) => page.results) ?? [];

  if (isLoading) return <Spinner />;
  if (isError || !data) {
    return (
      <p className="deposits__empty">{t("Something went wrong. Try again.")}</p>
    );
  }
  if (deposits.length === 0) {
    return (
      <p className="deposits__empty">
        {spaceId
          ? t("No deposit on this space yet.")
          : t("You haven't received any files yet.")}
      </p>
    );
  }
  return (
    <>
      <ul className="deposits__list">
        {deposits.map((deposit) => (
          <li key={deposit.id} className="deposits__row">
            <Link
              to="/transfers/$id"
              params={{ id: deposit.id }}
              className="deposits__row-link"
            >
              <span className="deposits__row-title">
                {deposit.title || t("Untitled")}
              </span>
              <span className="deposits__row-meta">
                {deposit.depositor_name} · {deposit.depositor_email}
              </span>
              <span className="deposits__row-meta">
                {t("{{count}} file", { count: deposit.file_count })} ·{" "}
                {formatFileSize(deposit.total_size)} ·{" "}
                <RelativeDate iso={deposit.created_at} />
                {deposit.status !== "active" && ` · ${t("Expired")}`}
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {hasNextPage && (
        <Button
          color="neutral"
          variant="secondary"
          disabled={isFetchingNextPage}
          onClick={() => void fetchNextPage()}
        >
          {t("Load more")}
        </Button>
      )}
    </>
  );
}
