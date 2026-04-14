import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Input, VariantType } from "@gouvfr-lasuite/cunningham-react";

interface PasswordPromptProps {
  // True when a previous attempt was rejected by the backend (wrong_password).
  wrongPassword?: boolean;
  // True when the parent is currently re-fetching with the candidate password.
  pending?: boolean;
  onSubmit: (password: string) => void;
}

export function PasswordPrompt({
  wrongPassword,
  pending,
  onSubmit,
}: PasswordPromptProps) {
  const { t } = useTranslation();
  const [password, setPassword] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) return;
    onSubmit(password);
  };

  return (
    <div className="password-prompt">
      <h1>{t("This transfer is protected")}</h1>
      <p>
        {t(
          "Enter the password you received separately to access this transfer.",
        )}
      </p>
      <form onSubmit={handleSubmit} className="password-prompt__form">
        <Input
          label={t("Password")}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
          fullWidth
        />
        <Button type="submit" disabled={pending || !password}>
          {pending ? t("Unlocking...") : t("Unlock")}
        </Button>
      </form>
      {wrongPassword && (
        <Alert type={VariantType.ERROR}>{t("Wrong password.")}</Alert>
      )}
    </div>
  );
}
