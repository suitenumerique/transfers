// Small 16px spinner used as a Button's ``icon`` while an async action is
// in flight. Inherits ``currentColor`` so it renders white on a filled
// brand button and neutral-tone on a tertiary one. Reused across the
// submit button (``TransferForm``) and the "Download all" button
// (``DownloadView``); keeping one implementation avoids the two drifting
// out of sync visually.
export function ButtonSpinner() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="file-item__ring file-item__ring--spin"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeOpacity="0.35"
        strokeWidth="2.5"
      />
      <path
        d="M12 3a9 9 0 0 1 9 9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
