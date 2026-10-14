// web/lib/saved-store.ts
//
// Where saved recommendations live: the visitor's own browser, in IndexedDB,
// one list per account ("anonymous" when signed out). roadmodel's servers
// never receive them. Another account signing in on the same browser does not
// see this account's list, and signing out keeps it for the next sign-in
// unless the visitor removes it (AppNav's sign-out panel).
//
// Every call is best effort: storage can be disabled, full or erased by the
// browser, and the page works the same without it. Tabs hear each other's
// changes on a BroadcastChannel.

import { LEGACY_CLEAR_SIGNAL, LEGACY_KEY, MAX_SAVED, legacyRuns, toSaved, type SavedRun } from "./saved-recommendations";

const DB_NAME = "roadmodel";
const DB_VERSION = 1;
const STORE = "saved-recommendations";
// [owner, at]: one account's entries, oldest first.
const BY_OWNER = "owner-at";
const CHANNEL = "roadmodel:saved-recommendations";
// This tab, so it skips its own messages.
const TAB = Math.random().toString(36).slice(2);

export type SavedMessage =
  | { type: "changed"; owner: string }
  | { type: "removed-all" }
  // A tab signed out: every tab drops what it shows and reloads as signed out.
  | { type: "signout" };

let opening: Promise<IDBDatabase> | null = null;

function database(): Promise<IDBDatabase> {
  if (opening) return opening;
  opening = new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const store = request.result.createObjectStore(STORE, { keyPath: ["owner", "id"] });
      store.createIndex(BY_OWNER, ["owner", "at"]);
    };
    request.onsuccess = () => {
      const db = request.result;
      // Another tab upgrading or deleting the database: let it, and reopen on
      // next use.
      db.onversionchange = () => { db.close(); opening = null; };
      resolve(db);
    };
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("blocked"));
  });
  opening.catch(() => { opening = null; });
  return opening;
}

function done<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function finished(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

function ownerRange(owner: string): IDBKeyRange {
  return IDBKeyRange.bound([owner, -Infinity], [owner, Infinity]);
}

// Writes entries for an owner and drops the oldest past MAX_SAVED. Returns how
// many were dropped.
async function write(owner: string, runs: SavedRun[]): Promise<number> {
  const tx = (await database()).transaction(STORE, "readwrite");
  const store = tx.objectStore(STORE);
  for (const run of runs) store.put({ ...run, owner });
  const keys = await done(store.index(BY_OWNER).getAllKeys(ownerRange(owner)));
  const excess = keys.slice(0, Math.max(0, keys.length - MAX_SAVED));
  for (const key of excess) store.delete(key);
  await finished(tx);
  return excess.length;
}

// This owner's entries, newest first. Malformed ones are skipped.
export async function listSaved(owner: string): Promise<SavedRun[]> {
  try {
    const tx = (await database()).transaction(STORE, "readonly");
    const rows = await done(tx.objectStore(STORE).index(BY_OWNER).getAll(ownerRange(owner)));
    return rows.reverse().flatMap((row) => toSaved(row) ?? []);
  } catch {
    return [];
  }
}

export async function addSaved(owner: string, run: SavedRun): Promise<void> {
  const valid = toSaved(run);
  if (!valid) return;
  try {
    await write(owner, [valid]);
    announce({ type: "changed", owner });
    void keepStorage();
  } catch { /* A storage failure must not prevent displaying a recommendation. */ }
}

// Entries from an export file. Returns how many were saved and how many old
// ones made room, or null when storage refused them.
export async function importSaved(owner: string, runs: SavedRun[]): Promise<{ saved: number; dropped: number } | null> {
  try {
    const dropped = await write(owner, runs);
    announce({ type: "changed", owner });
    void keepStorage();
    return { saved: runs.length, dropped };
  } catch {
    return null;
  }
}

export async function deleteSaved(owner: string, id: string): Promise<void> {
  try {
    const tx = (await database()).transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete([owner, id]);
    await finished(tx);
    announce({ type: "changed", owner });
  } catch { /* Storage unavailable: nothing was kept. */ }
}

// One account's entries.
export async function clearSaved(owner: string): Promise<void> {
  try {
    const tx = (await database()).transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    for (const key of await done(store.index(BY_OWNER).getAllKeys(ownerRange(owner)))) store.delete(key);
    await finished(tx);
    announce({ type: "changed", owner });
  } catch { /* Storage unavailable: nothing was kept. */ }
}

// Every account's entries in this browser: the sign-out panel's box, for a
// shared computer.
export async function removeAllSaved(): Promise<void> {
  try {
    const tx = (await database()).transaction(STORE, "readwrite");
    tx.objectStore(STORE).clear();
    await finished(tx);
  } catch { /* Storage unavailable: nothing was kept. */ }
  try {
    window.localStorage.removeItem(LEGACY_KEY);
    window.localStorage.removeItem(LEGACY_CLEAR_SIGNAL);
  } catch { /* Storage may be disabled. */ }
  announce({ type: "removed-all" });
}

// Carries the localStorage list over, once, then removes it. A list recorded
// for another account stays until that account signs in here.
export async function adoptLegacy(owner: string): Promise<void> {
  let raw: string | null;
  try { raw = window.localStorage.getItem(LEGACY_KEY); } catch { return; }
  const runs = legacyRuns(raw, owner);
  if (runs === null) return;
  try {
    if (runs.length > 0) await write(owner, runs);
    window.localStorage.removeItem(LEGACY_KEY);
    window.localStorage.removeItem(LEGACY_CLEAR_SIGNAL);
  } catch { /* Left in place; the next visit tries again. */ }
}

// Asks the browser not to evict the list when the disk runs low. Chrome
// decides by itself; Firefox may ask the visitor once; Safari grants it
// mostly to Home Screen web apps.
async function keepStorage(): Promise<void> {
  try {
    if (navigator.storage?.persist && !(await navigator.storage.persisted())) await navigator.storage.persist();
  } catch { /* Persistence is a request, never a requirement. */ }
}

export function announce(message: SavedMessage): void {
  try {
    const channel = new BroadcastChannel(CHANNEL);
    channel.postMessage({ ...message, from: TAB });
    channel.close();
  } catch { /* No other tab hears it; each reloads its list on its next visit. */ }
}

// Calls back on another tab's change. Returns the unsubscribe.
export function onSavedMessage(listener: (message: SavedMessage) => void): () => void {
  try {
    const channel = new BroadcastChannel(CHANNEL);
    channel.onmessage = (event: MessageEvent<SavedMessage & { from?: string }>) => {
      if (event.data.from !== TAB) listener(event.data);
    };
    return () => channel.close();
  } catch {
    return () => {};
  }
}
