import { useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";

interface PasswordFormProps {
  onSubmit: (password: string) => void;
  isPending: boolean;
  isError: boolean;
}

export function PasswordForm({ onSubmit, isPending, isError }: PasswordFormProps) {
  const { t } = useTranslation();
  const [password, setPassword] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (password) onSubmit(password);
  };

  return (
    <form onSubmit={handleSubmit} className="password-form">
      <p>{t("This transfer is password protected.")}</p>
      <div className="password-form__field">
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={t("Password")}
          autoFocus
        />
        <Button type="submit" disabled={isPending || !password}>
          {isPending ? t("Verifying...") : t("Submit")}
        </Button>
      </div>
      {isError && (
        <p className="password-form__error">{t("Incorrect password.")}</p>
      )}
    </form>
  );
}
