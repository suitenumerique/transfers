// Module-scope cache for newly created transfer passwords.
// Used to display the cleartext password ONCE on the success page right
// after creation. Cleared as soon as it is read (consume()), and lost on
// any page reload — so the password only survives the in-app navigation
// from the form to the detail page.

const stash = new Map<string, string>();

export function stashPassword(transferId: string, password: string): void {
  stash.set(transferId, password);
}

export function consumePassword(transferId: string): string | undefined {
  const value = stash.get(transferId);
  if (value !== undefined) stash.delete(transferId);
  return value;
}
