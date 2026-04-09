import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useTransfers } from "../api/useTransfers";
import { TransferCard } from "./TransferCard";

export function TransferList() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useTransfers(page);

  if (isLoading) {
    return <div className="transfer-list__loading">{t("Loading...")}</div>;
  }

  if (isError) {
    return <div className="transfer-list__error">{t("Error loading transfers.")}</div>;
  }

  if (!data || data.results.length === 0) {
    return (
      <div className="transfer-list__empty">
        <p>{t("No transfers yet.")}</p>
      </div>
    );
  }

  return (
    <div className="transfer-list">
      <div className="transfer-list__items">
        {data.results.map((transfer) => (
          <TransferCard key={transfer.id} transfer={transfer} />
        ))}
      </div>
      {(data.previous || data.next) && (
        <div className="transfer-list__pagination">
          <Button
            size="small"
            color="neutral"
            disabled={!data.previous}
            onClick={() => setPage((p) => p - 1)}
          >
            {t("Previous")}
          </Button>
          <span>{t("Page {{page}}", { page })}</span>
          <Button
            size="small"
            color="neutral"
            disabled={!data.next}
            onClick={() => setPage((p) => p + 1)}
          >
            {t("Next")}
          </Button>
        </div>
      )}
    </div>
  );
}
