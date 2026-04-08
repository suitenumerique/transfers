import { PropsWithChildren, createContext, useContext } from "react";

interface AppConfig {
    ENVIRONMENT: string;
    LANGUAGES: string[];
    LANGUAGE_CODE: string;
}

const DEFAULT_CONFIG: AppConfig = {
    ENVIRONMENT: "",
    LANGUAGES: [],
    LANGUAGE_CODE: "fr",
};

const ConfigContext = createContext<AppConfig>(DEFAULT_CONFIG);

export const ConfigProvider = ({ children }: PropsWithChildren) => {
    return (
        <ConfigContext.Provider value={DEFAULT_CONFIG}>
            {children}
        </ConfigContext.Provider>
    );
};

export const useConfig = () => {
    const config = useContext(ConfigContext);
    if (!config) {
        throw new Error("`useConfig` must be used within a `ConfigProvider`.");
    }
    return config;
};
