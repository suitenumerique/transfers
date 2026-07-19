function getApiOrigin() {
  return (
    import.meta.env.NEXT_PUBLIC_API_ORIGIN ||
    (typeof window !== "undefined" ? window.location.origin : "")
  );
}

const API_BASE = () => `${getApiOrigin()}/api/v1.0`;

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

function getCsrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : "";
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE()}${path}`, {
    credentials: "include",
    ...options,
    headers: {
      ...(options?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      "X-CSRFToken": getCsrfToken(),
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    // Session died mid-flight (cookie expired, server-side logout, etc.).
    // The page showed cached data with no way to reauth in place — force a
    // full reload of the landing, which re-runs useAuth against the now-
    // empty session and surfaces the "Sign in" flow. replace() keeps the
    // dead URL out of browser history.
    if (res.status === 401 && typeof window !== "undefined") {
      window.location.replace("/");
    }
    throw new ApiError(
      (body as Record<string, string>).detail || res.statusText,
      res.status,
      body,
    );
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

export function apiUrl(path: string): string {
  return `${API_BASE()}${path}`;
}
