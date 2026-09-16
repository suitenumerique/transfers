import { PropsWithChildren, createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";

export interface DriveConfig {
  base_url: string;
  sdk_url: string;
  api_url: string;
  app_name: string;
}

export interface LaGaufreConfig {
  widget_url: string;
  api_url: string;
}

export interface AppConfig {
  ENVIRONMENT: string;
  LANGUAGES: string[];
  LANGUAGE_CODE: string;
  TRANSFER_MAX_FILE_SIZE: number;
  TRANSFER_MAX_TOTAL_SIZE: number;
  TRANSFER_MAX_FILES_PER_TRANSFER: number;
  // Multipart part size in bytes. Doubles as the encryption crypto chunk size:
  // one S3 part = one AES-GCM chunk of [IV | CT | tag]. Recipient SW peels
  // ``TRANSFER_CHUNK_SIZE + 28`` bytes per chunk, so the frontend must
  // slice and declare against this value (server is the source of truth).
  TRANSFER_CHUNK_SIZE: number;
  // Files larger than this are flagged "too large" and skip the antivirus
  // scan entirely (never submitted). 2 GB in prod (= clamav cap), smaller in
  // dev. Surfaced so the UI can name the limit in the "not scanned" tooltip.
  SCAN_MAX_FILE_SIZE: number;
  // How long a scan may run before the form calls it "taking too long":
  // BASE + PER_GIB × bytes under scan. Same formula as the backend's
  // rescan endpoint and reaper, so a retry never duplicates a running scan.
  SCAN_WAIT_BASE_SECONDS: number;
  SCAN_WAIT_SECONDS_PER_GIB: number;
  TRANSFER_EXPIRY_CHOICES: number[];
  TRANSFER_DEFAULT_EXPIRY_DAYS: number;
  // False when the operator disabled confidential transfers: the form hides
  // the toggle and the backend rejects a confidential finalize. Transfers
  // already created in that mode stay downloadable.
  TRANSFER_CONFIDENTIAL_ENABLED: boolean;
  // External help URL — sidebar's "?" footer button opens it in a new tab.
  // Empty string when the operator hasn't configured one (button hidden).
  HELP_URL: string;
  // Absent when the operator hasn't wired Drive up (DRIVE_BASE_URL empty).
  DRIVE?: DriveConfig;
  // Absent unless the operator set both LAGAUFRE_WIDGET_URL and
  // LAGAUFRE_API_URL — the app switcher is opt-in, since it loads a
  // third-party script and lists another operator's services.
  LAGAUFRE?: LaGaufreConfig;
}

interface ConfigContextValue {
  config: AppConfig | null;
  isReady: boolean;
  // The /config/ fetch failed (API unreachable, 5xx). ``retry`` refetches.
  isError: boolean;
  retry: () => void;
}

const ConfigContext = createContext<ConfigContextValue>({
  config: null,
  isReady: false,
  isError: false,
  retry: () => {},
});

// Renders children unconditionally so the Auth provider mounts and fires its
// own /users/me/ query in parallel — two sequential spinners on first paint
// was painful and both endpoints are independent.
export const ConfigProvider = ({ children }: PropsWithChildren) => {
  const query = useQuery<AppConfig>({
    queryKey: ["config"],
    queryFn: () => apiFetch<AppConfig>("/config/"),
    retry: false,
    staleTime: Infinity,
  });

  return (
    <ConfigContext.Provider
      value={{
        config: query.data ?? null,
        // ``status`` goes back to "pending" when a retry starts after an
        // error (no data yet), unlike ``isFetched``, which stays true; the
        // gate must keep showing the spinner through that window.
        isReady: query.status !== "pending",
        isError: query.isError,
        retry: () => void query.refetch(),
      }}
    >
      {children}
    </ConfigContext.Provider>
  );
};

export const useConfig = (): AppConfig => {
  const { config } = useContext(ConfigContext);
  if (!config) {
    throw new Error("`useConfig` must be used within a `ConfigProvider`.");
  }
  return config;
};

export const useConfigReady = (): boolean =>
  useContext(ConfigContext).isReady;

export const useConfigState = (): Pick<
  ConfigContextValue,
  "isReady" | "isError" | "retry"
> => {
  const { isReady, isError, retry } = useContext(ConfigContext);
  return { isReady, isError, retry };
};
