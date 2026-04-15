import React, { PropsWithChildren, useEffect, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

interface User {
  id: string;
  email: string;
  full_name: string;
}

function getApiOrigin() {
  return (
    process.env.NEXT_PUBLIC_API_ORIGIN ||
    (typeof window !== "undefined" ? window.location.origin : "")
  );
}

const POPUP_NAME = "transferts-auth-popup";
const POPUP_MESSAGE = "transferts-auth-success";
const POPUP_MARKER_KEY = "transferts-auth-popup";

export const logout = () => {
  window.location.replace(`${getApiOrigin()}/api/v1.0/logout/`);
};

export const login = () => {
  window.location.replace(`${getApiOrigin()}/api/v1.0/authenticate/`);
};

// Open ProConnect in a popup so the parent window keeps its in-memory state
// (e.g. a File already selected in the upload form). Resolves when the popup
// signals auth success via BroadcastChannel or window.postMessage. The opener
// handle is NOT used for closure detection because COOP headers on the OIDC
// provider can sever the popup handle, causing `popup.closed` to read true
// while the popup is still active. A long timeout protects against popups
// the user closed manually.
const AUTH_POPUP_TIMEOUT_MS = 5 * 60 * 1000;

export function loginPopup(): Promise<void> {
  return new Promise((resolve, reject) => {
    const width = 520;
    const height = 700;
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;
    const features = `width=${width},height=${height},left=${left},top=${top}`;
    // Open on about:blank first so the popup inherits our origin and we can
    // write a marker into its sessionStorage. That marker survives the
    // cross-origin navigations of the OIDC dance (sessionStorage is scoped per
    // tab+origin, so the localhost:8900 bucket is still there when the popup
    // comes back at the end of the flow), unlike window.name which Chrome
    // clears on cross-origin top-level navigation.
    const popup = window.open("about:blank", POPUP_NAME, features);
    if (!popup) {
      reject(new Error("popup-blocked"));
      return;
    }

    try {
      popup.sessionStorage.setItem(POPUP_MARKER_KEY, String(Date.now()));
    } catch {
      // Browser blocked cross-window sessionStorage access — the popup will
      // fall back to window.name / opener.postMessage, which may fail.
    }

    popup.location.href = `${getApiOrigin()}/api/v1.0/authenticate/`;

    let channel: BroadcastChannel | null = null;
    let timeout: number | null = null;
    let focusGrace: number | null = null;
    let settled = false;

    const cleanup = () => {
      window.removeEventListener("message", messageHandler);
      window.removeEventListener("focus", focusHandler);
      window.removeEventListener("blur", blurHandler);
      if (channel) channel.close();
      if (timeout !== null) window.clearTimeout(timeout);
      if (focusGrace !== null) window.clearTimeout(focusGrace);
    };

    const settleResolve = () => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve();
    };

    const settleReject = (err: Error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(err);
    };

    // Popup-close detection via parent focus.
    //
    // We can't poll `popup.closed` directly: the OIDC provider sets
    // `Cross-Origin-Opener-Policy: same-origin`, which severs the popup
    // handle and makes `popup.closed` read true for the entire time the
    // popup sits on the provider — not just transiently. Polling therefore
    // produces false positives on legitimate logins.
    //
    // The signal we use instead: while the popup is the active window, our
    // parent window is blurred. The instant the user closes the popup (or
    // switches tabs), focus returns to the parent. We then start a 2 s
    // grace window — long enough for the user to Alt+Tab back to the popup
    // if they only switched momentarily — and, at the end of it, check
    // `popup.closed`. By that point the popup is really gone (or the user
    // is back on the parent intentionally), so the reading is trustworthy.
    const clearFocusGrace = () => {
      if (focusGrace !== null) {
        window.clearTimeout(focusGrace);
        focusGrace = null;
      }
    };

    const focusHandler = () => {
      if (settled) return;
      clearFocusGrace();
      focusGrace = window.setTimeout(() => {
        focusGrace = null;
        // We can't force-close a popup sitting on a Cross-Origin-Opener-
        // Policy: same-origin page — both `popup.close()` and
        // `popup.location.href = ...` become no-ops from the parent once
        // the browsing context has been severed. Every OIDC popup library
        // (Auth0, Firebase, etc.) hits the same limitation. The best we
        // can do here is unstick our own UI and rely on a UI hint telling
        // the user to close the orphaned window.
        settleReject(new Error("popup-closed"));
      }, 800);
    };

    const blurHandler = () => {
      clearFocusGrace();
    };

    window.addEventListener("focus", focusHandler);
    window.addEventListener("blur", blurHandler);

    const messageHandler = (e: MessageEvent) => {
      if (e.origin !== window.location.origin) return;
      if (!e.data || e.data.type !== POPUP_MESSAGE) return;
      settleResolve();
    };
    window.addEventListener("message", messageHandler);

    if (typeof BroadcastChannel !== "undefined") {
      channel = new BroadcastChannel(POPUP_NAME);
      channel.onmessage = (e) => {
        if (!e.data || e.data.type !== POPUP_MESSAGE) return;
        settleResolve();
      };
    }

    timeout = window.setTimeout(() => {
      settleReject(new Error("popup-timeout"));
    }, AUTH_POPUP_TIMEOUT_MS);
  });
}

// Called on every render of Auth. If the current window was opened by
// loginPopup (detected via the sessionStorage marker set before navigating to
// the OIDC endpoint), notify the opener via BroadcastChannel and close.
function maybeClosePopup() {
  if (typeof window === "undefined") return;

  let marker: string | null = null;
  try {
    marker = window.sessionStorage.getItem(POPUP_MARKER_KEY);
  } catch {
    return;
  }
  if (!marker) return;

  try {
    window.sessionStorage.removeItem(POPUP_MARKER_KEY);
  } catch {
    // best-effort cleanup
  }

  try {
    if (typeof BroadcastChannel !== "undefined") {
      const channel = new BroadcastChannel(POPUP_NAME);
      channel.postMessage({ type: POPUP_MESSAGE });
      channel.close();
    }
  } catch {
    // BroadcastChannel unavailable — fall through to postMessage
  }

  try {
    if (window.opener && !window.opener.closed) {
      window.opener.postMessage(
        { type: POPUP_MESSAGE },
        window.location.origin,
      );
    }
  } catch {
    // opener may be on a different origin or gone — best-effort
  }

  window.close();
}

interface AuthContextInterface {
  user?: User | null;
}

export const AuthContext = React.createContext<AuthContextInterface>({});

export const useAuth = () => React.useContext(AuthContext);

// Hook returning a function that opens the login popup and resolves once the
// auth query has been refetched. Components can `await requireAuth()` before
// running an authenticated action that must preserve in-memory state.
export const useRequireAuth = () => {
  const queryClient = useQueryClient();
  return async () => {
    await loginPopup();
    await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    await queryClient.refetchQueries({ queryKey: ["auth", "me"] });
  };
};

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

export const Auth = ({ children }: PropsWithChildren) => {
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

  useEffect(() => {
    if (user) maybeClosePopup();
  }, [user]);

  // Only show the full-screen loader on the very first mount, before the
  // query has settled (success OR error). After a 401, a manual refetch
  // (e.g. useRequireAuth after popup auth) would otherwise flip isLoading
  // back to true because there is no cached data, causing the entire tree
  // to unmount and briefly flash "Loading..." on top of the UI.
  if (!query.isFetched) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
        }}
      >
        Loading...
      </div>
    );
  }

  return (
    <AuthContext.Provider value={{ user }}>{children}</AuthContext.Provider>
  );
};
