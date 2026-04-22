import { Html, Head, Main, NextScript } from "next/document";

export default function Document() {
  return (
    <Html lang="fr">
      <Head>
        <meta name="theme-color" content="#FFFFFF" />
        <link rel="icon" type="image/svg+xml" href="/images/transferts-favicon.svg" />
        <link rel="alternate icon" href="/images/transferts-favicon.svg" />
        <link rel="apple-touch-icon" href="/images/transferts-favicon.svg" />
        <link rel="manifest" href="/manifest.json" />
        <meta name="application-name" content="Transferts" />
        <meta name="description" content="Service de transfert de fichiers" />
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
