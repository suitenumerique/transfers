import { LaGaufreV2 } from "@gouvfr-lasuite/ui-kit";
import { useConfig } from "@/features/providers/config";

// La Suite's app switcher. Opt-in: renders nothing until a deployment sets
// both LAGAUFRE_WIDGET_URL and LAGAUFRE_API_URL, so an instance outside a
// Suite deployment neither pulls the third-party script nor lists services
// belonging to another operator. The frontend's Caddy CSP must allow the
// same two origins (TRANSFERTS_FRONTEND_GAUFRE_SCRIPT_ORIGIN / _API_ORIGIN).
export function Gaufre() {
  const { LAGAUFRE } = useConfig();

  if (!LAGAUFRE) return null;

  return (
    <LaGaufreV2
      widgetPath={LAGAUFRE.widget_url}
      apiUrl={LAGAUFRE.api_url}
      showMoreLimit={100}
    />
  );
}
