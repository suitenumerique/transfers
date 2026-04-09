import { useState } from "react";
import { useRouter } from "next/router";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useCreateTransfer } from "../api/useCreateTransfer";
import { FileDropZone } from "./FileDropZone";

const schema = z.object({
  title: z.string().max(255),
  message: z.string(),
  password: z.string(),
  expires_in_days: z.number().int().min(1).max(90),
});

type FormValues = z.infer<typeof schema>;

export function TransferForm() {
  const { t } = useTranslation();
  const router = useRouter();
  const createTransfer = useCreateTransfer();
  const [files, setFiles] = useState<File[]>([]);
  const [recipients, setRecipients] = useState<string[]>([]);
  const [recipientInput, setRecipientInput] = useState("");
  const [recipientError, setRecipientError] = useState("");

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { title: "", message: "", password: "", expires_in_days: 7 },
  });

  const addRecipient = () => {
    const email = recipientInput.trim();
    if (!email) return;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setRecipientError(t("Invalid email address"));
      return;
    }
    if (recipients.includes(email)) {
      setRecipientError(t("Recipient already added"));
      return;
    }
    setRecipients([...recipients, email]);
    setRecipientInput("");
    setRecipientError("");
  };

  const removeRecipient = (email: string) => {
    setRecipients(recipients.filter((r) => r !== email));
  };

  const onSubmit = (values: FormValues) => {
    if (files.length === 0) return;
    if (recipients.length === 0) return;

    createTransfer.mutate(
      {
        ...values,
        title: values.title || "",
        message: values.message || "",
        password: values.password || "",
        expires_in_days: values.expires_in_days,
        recipients,
        files,
      },
      {
        onSuccess: (data) => {
          router.push(`/transfers/${data.id}`);
        },
      },
    );
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="transfer-form">
      <div className="transfer-form__field">
        <label htmlFor="title">{t("Title")}</label>
        <input id="title" type="text" {...register("title")} placeholder={t("My transfer")} />
        {errors.title && <span className="transfer-form__error">{errors.title.message}</span>}
      </div>

      <div className="transfer-form__field">
        <label htmlFor="message">{t("Message")}</label>
        <textarea id="message" {...register("message")} rows={3} placeholder={t("Message for recipients...")} />
      </div>

      <div className="transfer-form__field">
        <label>{t("Recipients")}</label>
        <div className="transfer-form__recipients-input">
          <input
            type="email"
            value={recipientInput}
            onChange={(e) => {
              setRecipientInput(e.target.value);
              setRecipientError("");
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                addRecipient();
              }
            }}
            placeholder="email@exemple.fr"
          />
          <Button type="button" size="small" onClick={addRecipient}>
            {t("Add")}
          </Button>
        </div>
        {recipientError && <span className="transfer-form__error">{recipientError}</span>}
        {recipients.length > 0 && (
          <ul className="transfer-form__recipients">
            {recipients.map((email) => (
              <li key={email}>
                {email}
                <button type="button" onClick={() => removeRecipient(email)}>
                  &times;
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="transfer-form__field">
        <label>{t("Files")}</label>
        <FileDropZone files={files} onChange={setFiles} />
        {files.length === 0 && (
          <span className="transfer-form__hint">{t("At least one file required")}</span>
        )}
      </div>

      <div className="transfer-form__row">
        <div className="transfer-form__field">
          <label htmlFor="password">{t("Password (optional)")}</label>
          <input id="password" type="password" {...register("password")} />
        </div>
        <div className="transfer-form__field">
          <label htmlFor="expires_in_days">{t("Expiration (days)")}</label>
          <input
            id="expires_in_days"
            type="number"
            min={1}
            max={90}
            {...register("expires_in_days", { valueAsNumber: true })}
          />
          {errors.expires_in_days && (
            <span className="transfer-form__error">{errors.expires_in_days.message}</span>
          )}
        </div>
      </div>

      <Button
        type="submit"
        disabled={
          createTransfer.isPending ||
          files.length === 0 ||
          recipients.length === 0
        }
      >
        {createTransfer.isPending ? t("Sending...") : t("Send")}
      </Button>

      {createTransfer.isError && (
        <div className="transfer-form__error">
          {t("Error creating transfer.")}
        </div>
      )}
    </form>
  );
}
