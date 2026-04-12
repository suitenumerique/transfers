import { useState } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Checkbox,
  Input,
  Select,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { useCreateTransfer } from "../api/useCreateTransfer";
import { FileDropZone } from "./FileDropZone";

const EXPIRY_CHOICES = [7, 30, 90];

function stripExtension(filename: string): string {
  return filename.replace(/\.[^.]+$/, "");
}

export function TransferForm() {
  const { t } = useTranslation();
  const router = useRouter();
  const createTransfer = useCreateTransfer();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [expiresInDays, setExpiresInDays] = useState<number>(30);
  const [sensitive, setSensitive] = useState(false);

  const handleFilesChange = (files: File[]) => {
    const next = files.length > 0 ? files[0] : null;
    setFile(next);
    if (next && title.trim() === "") {
      setTitle(stripExtension(next.name));
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    createTransfer.mutate(
      { title, expires_in_days: expiresInDays, sensitive, file },
      {
        onSuccess: (data) => {
          router.push(`/transfers/${data.id}`);
        },
      },
    );
  };

  const expiryOptions = EXPIRY_CHOICES.map((days) => ({
    label: t("{{count}} days", { count: days }),
    value: String(days),
  }));

  return (
    <form onSubmit={handleSubmit} className="transfer-form">
      <Input
        label={t("Title")}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={t("My transfer")}
        fullWidth
      />

      <div className="transfer-form__field">
        <label className="transfer-form__field-label">{t("File")}</label>
        <FileDropZone
          files={file ? [file] : []}
          onChange={handleFilesChange}
          maxFiles={1}
        />
        {!file && (
          <span className="transfer-form__hint">
            {t("At least one file required")}
          </span>
        )}
      </div>

      <Select
        label={t("Expiration")}
        options={expiryOptions}
        value={String(expiresInDays)}
        onChange={(e) => setExpiresInDays(Number(e.target.value))}
        clearable={false}
        fullWidth
      />

      <Checkbox
        label={t("Sensitive document")}
        checked={sensitive}
        onChange={(e) => setSensitive(e.target.checked)}
      />

      <Button type="submit" disabled={createTransfer.isPending || !file}>
        {createTransfer.isPending ? t("Sending...") : t("Create link")}
      </Button>

      {createTransfer.isError && (
        <Alert type={VariantType.ERROR}>
          {t("Error creating transfer.")}
        </Alert>
      )}
    </form>
  );
}
