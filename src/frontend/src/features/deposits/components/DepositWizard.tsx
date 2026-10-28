import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Input,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { CheckmarkShield } from "@gouvfr-lasuite/ui-kit/icons";
import { ApiError } from "@/features/api/client";
import { useAuth } from "@/features/auth";
import type { DepositReceipt } from "@/features/api/types";
import { formatFileSize } from "@/features/utils/string-helper";
import {
  startDepositChallenge,
  verifyDepositChallenge,
  type DepositTarget,
} from "../api/depositChallenge";
import { depositErrorMessage } from "./depositErrors";
import { DepositUpload } from "./DepositUpload";

type Step =
  | { name: "identity" }
  | { name: "code"; challengeId: string; email: string }
  | { name: "upload"; sessionToken: string }
  | { name: "sent"; receipt: DepositReceipt };

interface DepositWizardProps {
  // A space's link token, or ``null`` for an anonymous send: then the
  // depositor types the agent's address.
  spaceToken: string | null;
  // Who the files go to, as the page names it.
  recipientLabel?: string;
  maxDepositSize: number;
  maxFiles: number;
  // How long the agent can download the files, when the page knows it.
  retentionDays?: number;
  // False when the space takes any address without a code.
  verifyEmail?: boolean;
  // An end-to-end space's key, from the link's fragment.
  presetKey?: string;
}

// Deposit files without an account: say who you are, prove the email with
// the code it receives, upload, send. Already signed in, the account says
// who you are and no code is needed; a space can also take any address
// without one.
export function DepositWizard({
  spaceToken,
  recipientLabel,
  maxDepositSize,
  maxFiles,
  retentionDays,
  verifyEmail = true,
  presetKey,
}: DepositWizardProps) {
  const { t } = useTranslation();
  const { user } = useAuth();
  // Whether a receipt goes to the depositor: only to a proven address.
  const [emailVerified, setEmailVerified] = useState(true);
  const [step, setStep] = useState<Step>({ name: "identity" });
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [title, setTitle] = useState("");
  const [recipient, setRecipient] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const target: DepositTarget = spaceToken
    ? { space_token: spaceToken }
    : { recipient_email: recipient.trim() };

  // The address the challenge was asked for, whatever the form says since.
  const [submittedEmail, setSubmittedEmail] = useState("");

  const askCode = async () => {
    setError(null);
    setPending(true);
    const asked = user ? user.email : email.trim();
    try {
      const started = await startDepositChallenge(
        target,
        user
          ? {}
          : { depositor_name: name.trim(), depositor_email: email.trim() },
      );
      setSubmittedEmail(asked);
      if (started.deposit_token !== undefined) {
        setEmailVerified(started.email_verified);
        setStep({ name: "upload", sessionToken: started.deposit_token });
        return;
      }
      setCode("");
      setStep({ name: "code", challengeId: started.challenge_id, email: asked });
    } catch (err) {
      setError(depositErrorMessage(err));
    } finally {
      setPending(false);
    }
  };

  const checkCode = async (challengeId: string) => {
    setError(null);
    setPending(true);
    try {
      const session = await verifyDepositChallenge(challengeId, code.trim());
      setStep({ name: "upload", sessionToken: session.deposit_token });
    } catch (err) {
      const left =
        err instanceof ApiError
          ? (err.body as { attempts_left?: number } | undefined)?.attempts_left
          : undefined;
      setError(
        left !== undefined
          ? t("This code is not right. {{count}} attempt left.", {
              count: left,
            })
          : depositErrorMessage(err),
      );
    } finally {
      setPending(false);
    }
  };

  const identityReady =
    (user || (name.trim() && email.trim())) && (spaceToken || recipient.trim());
  const depositorEmail = submittedEmail;
  const needsCode = !user && verifyEmail;

  if (step.name === "sent") {
    return (
      <section className="deposit-wizard deposit-wizard--sent">
        <CheckmarkShield className="deposit-wizard__done-icon" />
        <h1 className="deposit-wizard__title">{t("Your files were sent")}</h1>
        <p className="deposit-wizard__text">
          {t("{{count}} file", { count: step.receipt.file_count })}
          {" · "}
          {formatFileSize(step.receipt.total_size)}
        </p>
        {emailVerified && (
          <p className="deposit-wizard__text">
            {t("A confirmation was sent to {{email}}.", {
              email: depositorEmail,
            })}
          </p>
        )}
      </section>
    );
  }

  return (
    <section className="deposit-wizard">
      <h1 className="deposit-wizard__title">
        {recipientLabel
          ? t("Send files to {{name}}", { name: recipientLabel })
          : t("Send files to an agent")}
      </h1>
      {retentionDays !== undefined && (
        <p className="deposit-wizard__text">
          {t("The agent can download your files for {{count}} days.", {
            count: retentionDays,
          })}
        </p>
      )}

      {step.name === "identity" && (
        <form
          className="deposit-wizard__form"
          onSubmit={(e) => {
            e.preventDefault();
            if (identityReady && !pending) void askCode();
          }}
        >
          {!spaceToken && (
            <Input
              label={t("Recipient's email address")}
              type="email"
              value={recipient}
              onChange={(e) => setRecipient(e.currentTarget.value)}
              text={t("The agent you are sending files to.")}
              fullWidth
              required
            />
          )}
          {/* Signed in: the account says who deposits, shown but locked. */}
          <Input
            label={t("Your name")}
            value={user ? user.full_name || user.email : name}
            onChange={(e) => setName(e.currentTarget.value)}
            disabled={Boolean(user)}
            maxLength={100}
            fullWidth
            required
          />
          <Input
            label={t("Your email address")}
            type="email"
            value={user ? user.email : email}
            onChange={(e) => setEmail(e.currentTarget.value)}
            disabled={Boolean(user)}
            text={
              user
                ? t("Signed in with ProConnect: no code needed.")
                : verifyEmail
                  ? t("We will send a code to this address to check it.")
                  : t("The agent will see that it was not checked.")
            }
            fullWidth
            required
          />
          <Input
            label={t("Subject of your deposit")}
            value={title}
            onChange={(e) => setTitle(e.currentTarget.value)}
            maxLength={80}
            fullWidth
          />
          {error && <Alert type={VariantType.ERROR}>{error}</Alert>}
          <Button
            type="submit"
            color="brand"
            fullWidth
            disabled={!identityReady || pending}
          >
            {needsCode ? t("Receive a code") : t("Continue")}
          </Button>
        </form>
      )}

      {step.name === "code" && (
        <form
          className="deposit-wizard__form"
          onSubmit={(e) => {
            e.preventDefault();
            if (code.trim().length === 6 && !pending)
              void checkCode(step.challengeId);
          }}
        >
          <p className="deposit-wizard__text">
            {t("We sent a 6-digit code to {{email}}.", { email: step.email })}
          </p>
          <Input
            label={t("Code")}
            value={code}
            onChange={(e) =>
              setCode(e.currentTarget.value.replace(/\D/g, "").slice(0, 6))
            }
            inputMode="numeric"
            maxLength={6}
            autoComplete="one-time-code"
            fullWidth
            required
          />
          {error && <Alert type={VariantType.ERROR}>{error}</Alert>}
          <Button
            type="submit"
            color="brand"
            fullWidth
            disabled={code.trim().length !== 6 || pending}
          >
            {t("Check the code")}
          </Button>
          <Button
            type="button"
            color="neutral"
            variant="tertiary"
            fullWidth
            // Not while a check runs: its answer would land on the wrong step.
            disabled={pending}
            onClick={() => {
              setError(null);
              setStep({ name: "identity" });
            }}
          >
            {t("Change my details or get a new code")}
          </Button>
        </form>
      )}

      {step.name === "upload" && (
        <DepositUpload
          sessionToken={step.sessionToken}
          title={title.trim()}
          maxDepositSize={maxDepositSize}
          maxFiles={maxFiles}
          presetKey={presetKey}
          onSent={(receipt) => setStep({ name: "sent", receipt })}
        />
      )}
    </section>
  );
}
