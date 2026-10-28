import React, { PropsWithChildren, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { useConfigState } from "@/features/providers/config";

interface User {
  id: string;
  email: string;
  full_name: string;
}

function getApiOrigin() {
  return (
    import.meta.env.NEXT_PUBLIC_API_ORIGIN ||
    (typeof window !== "undefined" ? window.location.origin : "")
  );
}

export const logout = () => {
  window.location.replace(`${getApiOrigin()}/api/v1.0/logout/`);
};

export const login = () => {
  window.location.replace(`${getApiOrigin()}/api/v1.0/authenticate/`);
};

// Sign-in always lands on the home page: remember where it started, so the
// home page sends the user back (a deposit page, a space shared by email).
const RETURN_PATH_KEY = "auth-return-path";
// Owned by features/deposits/api/claimInbound.ts.
const PENDING_CLAIM_KEY = "transfers.pendingInboundClaim";

// ``returnTo``: the page to come back to, when the current URL has lost
// part of it (a download page strips its key fragment once read).
export const loginAndReturn = (returnTo?: string) => {
  try {
    const { pathname, search, hash } = window.location;
    sessionStorage.setItem(
      RETURN_PATH_KEY,
      returnTo ?? `${pathname}${search}${hash}`,
    );
    // A claim left from an abandoned sign-in would take over this one.
    sessionStorage.removeItem(PENDING_CLAIM_KEY);
  } catch {
    // Storage blocked: the user reopens the page after signing in.
  }
  login();
};

export function takeReturnPath(): string | null {
  try {
    const path = sessionStorage.getItem(RETURN_PATH_KEY);
    sessionStorage.removeItem(RETURN_PATH_KEY);
    // Same-origin paths only.
    return path && path.startsWith("/") && !path.startsWith("//") ? path : null;
  } catch {
    return null;
  }
}

interface AuthContextInterface {
  user?: User | null;
}

export const AuthContext = React.createContext<AuthContextInterface>({});

export const useAuth = () => React.useContext(AuthContext);

const fetchMe = async (): Promise<User> => {
  const res = await fetch(`${getApiOrigin()}/api/v1.0/users/me/`, {
    credentials: "include",
  });
  if (!res.ok) {
    const error = new Error("Not authenticated") as Error & { code: number };
    error.code = res.status;
    throw error;
  }
  return res.json();
};

// Full-page state for an API that can't be reached at boot: nothing below
// can render without /config/, so say so and offer a retry rather than
// letting the first useConfig() throw into the error boundary.
const ServiceUnavailable = ({ onRetry }: { onRetry: () => void }) => {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "1rem",
        height: "100vh",
        padding: "2rem",
        textAlign: "center",
      }}
    >
      <p style={{ margin: 0, maxWidth: "32rem" }}>
        {t(
          "The service can't be reached right now. Check your connection, or try again in a moment.",
        )}
      </p>
      <Button color="brand" onClick={onRetry}>
        {t("Retry")}
      </Button>
    </div>
  );
};

export const Auth = ({ children }: PropsWithChildren) => {
  const {
    isReady: configReady,
    isError: configError,
    retry: retryConfig,
  } = useConfigState();
  const query = useQuery<User, Error & { code?: number }>({
    queryKey: ["auth", "me"],
    queryFn: fetchMe,
    retry: false,
  });

  const user = useMemo(() => {
    if (query.data) return query.data;
    if (query.isError && query.error?.code === 401) return null;
    return undefined;
  }, [query.isError, query.error?.code, query.data]);

  // Wait for BOTH the config fetch and the /users/me/ fetch. ConfigProvider
  // renders its children unconditionally (so Auth and its useQuery mount
  // immediately, in parallel with the config fetch) — without this gate,
  // a page could render briefly without config available. Single spinner
  // covers both fetches.
  if (!query.isFetched || !configReady) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
        }}
      >
        <Spinner size="xl" />
      </div>
    );
  }

  if (configError) {
    return <ServiceUnavailable onRetry={retryConfig} />;
  }

  return (
    <AuthContext.Provider value={{ user }}>{children}</AuthContext.Provider>
  );
};
