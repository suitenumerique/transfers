import React, { PropsWithChildren, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

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

  if (query.isLoading) {
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
