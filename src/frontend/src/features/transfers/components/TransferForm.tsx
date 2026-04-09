import { useState } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useCreateTransfer } from "../api/useCreateTransfer";
import { FileDropZone } from "./FileDropZone";

const EXPIRY_CHOICES = [7, 30, 90];

export function TransferForm() {
  const { t } = useTranslation();
  const router = useRouter();
  const createTransfer = useCreateTransfer();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [expiresInDays, setExpiresInDays] = useState(30);
  const [sensitive, setSensitive] = useState(false);

  const handleFilesChange = (files: File[]) => {
    setFile(files.length > 0 ? files[0] : null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    createTransfer.mutate(
      {
        title,
        expires_in_days: expiresInDays,
        sensitive,
        file,
      },
      {
        onSuccess: (data) => {
          router.push(`/transfers/${data.id}`);
        },
      },
    );
  };

  return (
    <form onSubmit={handleSubmit} className="transfer-form">
      <div className="transfer-form__field">
        <label htmlFor="title">{t("Title")}</label>
        <input
          id="title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t("My transfer")}
        />
      </div>

      <div className="transfer-form__field">
        <label>{t("File")}</label>
        <FileDropZone
          files={file ? [file] : []}
          onChange={handleFilesChange}
          maxFiles={1}
        />
        {!file && (
          <span className="transfer-form__hint">{t("At least one file required")}</span>
        )}
      </div>

      <div className="transfer-form__field">
        <label htmlFor="expires_in_days">{t("Expiration")}</label>
        <select
          id="expires_in_days"
          value={expiresInDays}
          onChange={(e) => setExpiresInDays(Number(e.target.value))}
        >
          {EXPIRY_CHOICES.map((days) => (
            <option key={days} value={days}>
              {t("{{count}} days", { count: days })}
            </option>
          ))}
        </select>
      </div>

      <div className="transfer-form__field transfer-form__checkbox">
        <label>
          <input
            type="checkbox"
            checked={sensitive}
            onChange={(e) => setSensitive(e.target.checked)}
          />
          {t("Sensitive document")}
        </label>
      </div>

      <Button
        type="submit"
        disabled={createTransfer.isPending || !file}
      >
        {createTransfer.isPending ? t("Sending...") : t("Create link")}
      </Button>

      {createTransfer.isError && (
        <div className="transfer-form__error">
          {t("Error creating transfer.")}
        </div>
      )}
    </form>
  );
}
