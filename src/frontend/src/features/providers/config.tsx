import {
  PropsWithChildren,
  createContext,
  useContext,
  useEffect,
  useState,
} from "react";
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
  // Absent when the operator hasn't wired Drive up (DRIVE_BASE_URL empty).
  DRIVE?: DriveConfig;
}

const ConfigContext = createContext<AppConfig | null>(null);

export const ConfigProvider = ({ children }: PropsWithChildren) => {
  const [config, setConfig] = useState<AppConfig | null>(null);

  useEffect(() => {
    apiFetch<AppConfig>("/config/")
      .then((data) => setConfig(data))
      .catch(() => {
        // TODO: handle error state
      });
  }, []);

  if (!config) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
        <p>Chargement…</p>
      </div>
    );
  }

  return (
    <ConfigContext.Provider value={config}>{children}</ConfigContext.Provider>
  );
};

export const useConfig = (): AppConfig => {
  const config = useContext(ConfigContext);
  if (!config) {
    throw new Error("`useConfig` must be used within a `ConfigProvider`.");
  }
  return config;
};
