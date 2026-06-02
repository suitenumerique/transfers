import { useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "@gouvfr-lasuite/ui-kit";

// TLD must be ≥2 chars to match Django's EmailValidator on the backend —
// otherwise `sd@asdl.c` passes here and gets rejected at finalize time.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

interface RecipientInputProps {
  recipients: string[];
  onChange: (recipients: string[]) => void;
  onPendingChange?: (hasValidPending: boolean) => void;
  disabled?: boolean;
}

export function RecipientInput({
  recipients,
  onChange,
  onPendingChange,
  disabled,
}: RecipientInputProps) {
  const { t } = useTranslation();
  const [inputValue, setInputValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const addRecipient = (raw: string) => {
    const email = raw.trim().toLowerCase();
    if (!email) return;
    if (!EMAIL_RE.test(email)) {
      setError(t("Invalid email address."));
      return;
    }
    if (recipients.includes(email)) {
      setError(t("This recipient has already been added."));
      return;
    }
    if (recipients.length >= 50) {
      setError(t("Maximum 50 recipients."));
      return;
    }
    setError(null);
    onChange([...recipients, email]);
    setInputValue("");
    onPendingChange?.(false);
  };

  const removeRecipient = (email: string) => {
    onChange(recipients.filter((r) => r !== email));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === "," || e.key === "Tab") {
      if (inputValue.trim()) {
        e.preventDefault();
        addRecipient(inputValue);
      }
    }
    if (e.key === "Backspace" && inputValue === "" && recipients.length > 0) {
      removeRecipient(recipients[recipients.length - 1]);
    }
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    const pasted = e.clipboardData.getData("text");
    if (pasted.includes(",") || pasted.includes(";") || pasted.includes(" ")) {
      e.preventDefault();
      const emails = pasted.split(/[,;\s]+/).filter(Boolean);
      const newRecipients = [...recipients];
      for (const raw of emails) {
        const email = raw.trim().toLowerCase();
        if (EMAIL_RE.test(email) && !newRecipients.includes(email)) {
          newRecipients.push(email);
        }
      }
      onChange(newRecipients.slice(0, 50));
      setInputValue("");
    }
  };

  return (
    <div className="recipient-input">
      <div
        className="recipient-input__box"
        onClick={() => inputRef.current?.focus()}
      >
        {recipients.map((email) => (
          <span key={email} className="recipient-input__chip">
            <span className="recipient-input__chip-text">{email}</span>
            <button
              type="button"
              className="recipient-input__chip-remove"
              onClick={(e) => {
                e.stopPropagation();
                removeRecipient(email);
              }}
              disabled={disabled}
              aria-label={t("Remove {{email}}", { email })}
            >
              <Icon name="close" />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          type="email"
          className="recipient-input__input"
          value={inputValue}
          onChange={(e) => {
            const val = e.target.value;
            setInputValue(val);
            setError(null);
            onPendingChange?.(EMAIL_RE.test(val.trim()));
          }}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          onBlur={() => {
            if (inputValue.trim()) addRecipient(inputValue);
          }}
          placeholder={
            recipients.length === 0 ? t("Enter email addresses...") : ""
          }
          disabled={disabled}
          aria-label={t("Recipient email")}
        />
      </div>
      {error && <p className="recipient-input__error">{error}</p>}
    </div>
  );
}
