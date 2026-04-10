import { useTranslation } from "react-i18next";
import Link from "next/link";
import {
  Alert,
  Loader,
  Pagination,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { useState } from "react";
import { useTransfers } from "../api/useTransfers";
import { TransferCard } from "./TransferCard";

const PAGE_SIZE = 20;

function NewTransferCta() {
  const { t } = useTranslation();
  return (
    <Link href="/transfers/new" className="transfer-list__new-cta">
      <span className="transfer-list__new-cta-icon" aria-hidden="true">
        +
      </span>
      <span>{t("New transfer")}</span>
    </Link>
  );
}

export function TransferList() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useTransfers(page);

  if (isLoading) {
    return (
      <div className="transfer-list__loading">
        <Loader aria-label={t("Loading...")} />
      </div>
    );
  }

  if (isError) {
    return (
      <Alert type={VariantType.ERROR}>{t("Error loading transfers.")}</Alert>
    );
  }

  if (!data || data.results.length === 0) {
    return (
      <div className="transfer-list">
        <div className="transfer-list__empty">
          <p>{t("No transfers yet.")}</p>
        </div>
        <div className="transfer-list__items">
          <NewTransferCta />
        </div>
      </div>
    );
  }

  const pagesCount = Math.max(1, Math.ceil(data.count / PAGE_SIZE));

  return (
    <div className="transfer-list">
      <div className="transfer-list__items">
        {data.results.map((transfer) => (
          <TransferCard key={transfer.id} transfer={transfer} />
        ))}
        <NewTransferCta />
      </div>
      {pagesCount > 1 && (
        <div className="transfer-list__pagination">
          <Pagination
            page={page}
            pagesCount={pagesCount}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        </div>
      )}
    </div>
  );
}
