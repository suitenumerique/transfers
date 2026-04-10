import { type ReactElement } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/router";
import { useDropzone } from "react-dropzone";
import { login, useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { LandingPage } from "@/features/transfers/components/LandingPage";
import { TransferList } from "@/features/transfers/components/TransferList";
import { setPendingFiles } from "@/features/transfers/pendingFiles";
import type { NextPageWithLayout } from "./_app";

function AuthenticatedHome() {
  const { t } = useTranslation();
  const router = useRouter();

  const { getRootProps, isDragActive } = useDropzone({
    noClick: true,
    noKeyboard: true,
    onDrop: (files) => {
      if (files.length === 0) return;
      setPendingFiles(files);
      router.push("/transfers/new");
    },
  });

  return (
    <div
      {...getRootProps({ className: "home-dropzone" })}
      data-drag-active={isDragActive || undefined}
    >
      <div className="app-content">
        <h1>{t("My transfers")}</h1>
        <TransferList />
      </div>
      {isDragActive && (
        <div className="home-dropzone__overlay" aria-hidden="true">
          <div className="home-dropzone__overlay-content">
            <span className="home-dropzone__overlay-icon">⬆</span>
            <span>{t("Drop files to create a new transfer")}</span>
          </div>
        </div>
      )}
    </div>
  );
}

const HomePage: NextPageWithLayout = () => {
  const { user } = useAuth();

  if (!user) {
    return <LandingPage onLogin={login} />;
  }

  return <AuthenticatedHome />;
};

HomePage.getLayout = (page: ReactElement) => {
  return <MainLayout>{page}</MainLayout>;
};

export default HomePage;
