import "../styles/main.scss";
import { type ReactElement, type ReactNode } from "react";
import type { NextPage } from "next";
import type { AppProps } from "next/app";
import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { CunninghamProvider } from "@gouvfr-lasuite/cunningham-react";
import "../features/i18n/initI18n";
import Head from "next/head";
import { useTranslation } from "react-i18next";
import { Auth } from "@/features/auth";
import { ConfigProvider } from "@/features/providers/config";

export type NextPageWithLayout<P = object, IP = P> = NextPage<P, IP> & {
  getLayout?: (page: ReactElement) => ReactNode;
};

type AppPropsWithLayout = AppProps & {
  Component: NextPageWithLayout;
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

// Cunningham's DeleteConfirmationModal ships a hard-coded "Supprimer" /
// "Delete" button label. Our revoke action is semantically a deactivation,
// not a deletion — override via `customLocales` so the modal's CTA reads
// "Désactiver" in every language we ship.
const CUSTOM_LOCALES = {
  "fr-FR": {
    components: {
      modals: {
        helpers: {
          delete_confirmation: { delete: "Désactiver" },
        },
      },
    },
  },
  "en-US": {
    components: {
      modals: {
        helpers: {
          delete_confirmation: { delete: "Deactivate" },
        },
      },
    },
  },
};

function AppContent({ Component, pageProps }: AppPropsWithLayout) {
  const { i18n } = useTranslation();
  const getLayout = Component.getLayout ?? ((page) => page);

  return (
    <CunninghamProvider
      currentLocale={i18n.language}
      customLocales={CUSTOM_LOCALES}
    >
      <ConfigProvider>
        <Auth>
          {getLayout(<Component {...pageProps} />)}
        </Auth>
      </ConfigProvider>
    </CunninghamProvider>
  );
}

export default function MyApp(props: AppPropsWithLayout) {
  return (
    <>
      <Head>
        <title>Transferts</title>
        <meta name="description" content="Service de transfert de fichiers" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <QueryClientProvider client={queryClient}>
        <AppContent {...props} />
      </QueryClientProvider>
    </>
  );
}
