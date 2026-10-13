import {
  closeSync, constants, fstatSync, lstatSync, mkdtempSync, openSync,
  realpathSync, writeSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";

export interface PrivateOutput {
  path: string;
  write(text: string): void;
  close(): void;
}

export function createPrivateOutput(options: { prefix: string; path?: string }): PrivateOutput {
  if (process.platform === "win32" || typeof process.getuid !== "function") {
    throw new Error("Private diagnostics require verified POSIX file permissions.");
  }
  if (!/^[a-zA-Z0-9-]{1,80}$/.test(options.prefix)) {
    throw new Error("Invalid diagnostic output prefix.");
  }
  const uid = process.getuid();
  // Resolve the OS temporary-root alias once (macOS /var -> /private/var).
  // Additional links inside an explicit destination remain forbidden.
  const temporaryRoot = resolve(tmpdir());
  const base = realpathSync(temporaryRoot);
  const info = lstatSync(base);
  if (!info.isDirectory() ||
      (info.uid !== uid && !(info.mode & 0o1000)) ||
      ((info.mode & 0o022) && !(info.mode & 0o1000))) {
    throw new Error("Untrusted diagnostic temporary directory.");
  }
  let path: string;
  if (options.path !== undefined) {
    path = resolve(options.path);
    if (path.startsWith(temporaryRoot + sep)) {
      path = base + path.slice(temporaryRoot.length);
    }
    const parent = dirname(path);
    // Explicit destinations may not hide linked parents through normalization.
    if (realpathSync(parent) !== parent) throw new Error("Linked diagnostic parent refused.");
  } else {
    path = join(mkdtempSync(join(base, `${options.prefix}-`)), "rows.jsonl");
  }
  const parent = lstatSync(dirname(path));
  if (!parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== uid || (parent.mode & 0o077)) {
    throw new Error("Diagnostic parent must be privately owned.");
  }
  const fd = openSync(path, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW, 0o600);
  let closed = false;
  try {
    const file = fstatSync(fd);
    if (!file.isFile() || file.nlink !== 1 || file.uid !== uid || (file.mode & 0o077)) {
      throw new Error("Diagnostic output must be an independent private file.");
    }
  } catch {
    closeSync(fd);
    throw new Error("Diagnostic output could not be opened privately.");
  }
  return {
    path,
    write(text: string): void {
      if (closed) throw new Error("Diagnostic output is closed.");
      const bytes = Buffer.from(text, "utf8");
      let offset = 0;
      while (offset < bytes.length) {
        const written = writeSync(fd, bytes, offset, bytes.length - offset);
        if (written <= 0) throw new Error("Diagnostic write did not complete.");
        offset += written;
      }
    },
    close(): void {
      if (!closed) { closed = true; closeSync(fd); }
    },
  };
}
