import { ProConnectButton } from "@gouvfr-lasuite/ui-kit";
import { login, useAuth } from "@/features/auth";

export default function HomePage() {
  const { user } = useAuth();

  if (user) {
    return (
      <div>
        <h1>Transferts</h1>
        <p>Bienvenue, {user.full_name || user.email}</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
      <h1>Transferts</h1>
      <p>Service de transfert de fichiers souverain</p>
      <ProConnectButton onClick={login} />
    </div>
  );
}
