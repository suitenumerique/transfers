import { defineConfig, globalIgnores } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

const eslintConfig = defineConfig([
  globalIgnores([
    "dist/**",
    "src/routes.gen.ts",
    "scripts/**",
    // Leftover from the pre-Vite Next.js dev build; the directory predates
    // the migration to Vite + TanStack Router and is not regenerated.
    ".next/**",
  ]),
  ...tseslint.configs.recommended,
  reactHooks.configs.flat.recommended,
  {
    rules: {
      "no-console": ["error", { allow: ["error", "warn"] }],
      "@typescript-eslint/no-unused-vars": "error",
      "@typescript-eslint/no-empty-object-type": "off",
      "react-hooks/exhaustive-deps": "off",
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "warn",
      // Ref mutations in event handlers (e.g. isSubmittingRef) are a
      // legitimate escape hatch; the React Compiler rule over-flags them.
      // Kept as a warning, consistent with the other compiler rules above.
      "react-hooks/immutability": "warn",
    },
  },
]);

export default eslintConfig;
