import { PropsWithChildren, createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";

export interface DriveConfig {
  base_url: string;
  sdk_url: string;
  api_url: string;
  app_name: string;
}

export interface AppConfig {
  ENVIRONMENT: string;
  LANGUAGES: string[];
  LANGUAGE_CODE: string;
  TRANSFER_MAX_FILE_SIZE: number;
  TRANSFER_MAX_TOTAL_SIZE: number;
  TRANSFER_MAX_FILES_PER_TRANSFER: number;
  // External help URL — sidebar's "?" footer button opens it in a new tab.
  // Empty string when the operator hasn't configured one (button hidden).
  HELP_URL: string;
  // Absent when the operator hasn't wired Drive up (DRIVE_BASE_URL empty).
  DRIVE?: DriveConfig;
}

interface ConfigContextValue {
  config: AppConfig | null;
  isReady: boolean;
}

const ConfigContext = createContext<ConfigContextValue>({
  config: null,
  isReady: false,
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
      value={{ config: query.data ?? null, isReady: query.isFetched }}
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
