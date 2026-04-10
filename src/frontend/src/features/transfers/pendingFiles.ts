// In-memory handoff of files between the home dropzone and the new-transfer
// page. File objects can't go through URL or sessionStorage, so we stash them
// here during the router navigation.

let pendingFiles: File[] = [];

export function setPendingFiles(files: File[]) {
  pendingFiles = files;
}

export function consumePendingFiles(): File[] {
  const files = pendingFiles;
  pendingFiles = [];
  return files;
}
