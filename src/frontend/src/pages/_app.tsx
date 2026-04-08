import "../styles/main.scss";
import { type ReactElement, type ReactNode } from "react";
import type { NextPage } from "next";
import type { AppProps } from "next/app";
import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import "../features/i18n/initI18n";
import Head from "next/head";
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

export default function MyApp({ Component, pageProps }: AppPropsWithLayout) {
  const getLayout = Component.getLayout ?? ((page) => page);

  return (
    <>
      <Head>
        <title>Transferts</title>
        <meta name="description" content="Service de transfert de fichiers" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <QueryClientProvider client={queryClient}>
        <ConfigProvider>
          <Auth>
            {getLayout(<Component {...pageProps} />)}
          </Auth>
        </ConfigProvider>
      </QueryClientProvider>
    </>
  );
}
