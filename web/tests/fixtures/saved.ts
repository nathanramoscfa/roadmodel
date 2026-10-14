// web/tests/fixtures/saved.ts
//
// The saved-recommendations store as the browser holds it (lib/saved-store.ts):
// every row of every account, read straight from IndexedDB. A page that has
// not saved anything yet has no database; opening one here would create it
// empty and stop the page creating its store, so it is only listed.
import type { Page } from "@playwright/test";

export interface StoredRow {
  owner: string;
  id: string;
  kind: string;
  task: string;
}

export async function storedRows(page: Page): Promise<StoredRow[]> {
  return page.evaluate(async () => {
    const exists = (await indexedDB.databases()).some((db) => db.name === "roadmodel");
    if (!exists) return [];
    return new Promise<StoredRow[]>((resolve, reject) => {
      const open = indexedDB.open("roadmodel");
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const db = open.result;
        if (!db.objectStoreNames.contains("saved-recommendations")) {
          db.close();
          resolve([]);
          return;
        }
        const all = db.transaction("saved-recommendations").objectStore("saved-recommendations").getAll();
        all.onerror = () => reject(all.error);
        all.onsuccess = () => {
          db.close();
          resolve(all.result as StoredRow[]);
        };
      };
    });
  });
}
