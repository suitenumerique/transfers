// Entry point of the Playwright container: relays localhost:79xx to the
// services of compose.e2e.yaml, then runs the command it was given (by
// default `npx playwright test`) and exits with its status.
//
// The app hands out localhost URLs (OIDC redirects, presigned S3 URLs, links
// in emails), so the browser has to find every service there, as it would
// on the host.
import { spawn } from "node:child_process";
import net from "node:net";

const FORWARDS = {
  7980: ["frontend", 3000],
  7981: ["backend", 8000],
  7902: ["keycloak", 8802],
  7984: ["mailcatcher", 1080],
  7986: ["objectstorage", 9000],
};

const listening = Object.entries(FORWARDS).map(
  ([port, [host, targetPort]]) =>
    new Promise((resolve, reject) => {
      const server = net.createServer((client) => {
        const upstream = net.connect(targetPort, host);
        client.pipe(upstream).pipe(client);
        client.on("error", () => upstream.destroy());
        upstream.on("error", () => client.destroy());
      });
      server.on("error", reject);
      server.listen(Number(port), "127.0.0.1", resolve);
    }),
);
await Promise.all(listening);

const [command, ...args] = process.argv.slice(2);
const child = spawn(command, args, { stdio: "inherit" });
child.on("exit", (code, signal) => process.exit(signal ? 1 : (code ?? 1)));
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
