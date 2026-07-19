import React, { PropsWithChildren, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { useConfigReady } from "@/features/providers/config";

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

export const Auth = ({ children }: PropsWithChildren) => {
  const configReady = useConfigReady();
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

  return (
    <AuthContext.Provider value={{ user }}>{children}</AuthContext.Provider>
  );
};
