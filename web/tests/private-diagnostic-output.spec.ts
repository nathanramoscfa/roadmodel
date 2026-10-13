import { expect, test } from "@playwright/test";
import {
  chmodSync, closeSync, constants, existsSync, fstatSync, linkSync, mkdtempSync,
  openSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import { createPrivateOutput } from "../../scripts/private-diagnostic-output";

function ownedFixture(): string {
  const dir = realpathSync(mkdtempSync(join(tmpdir(), "roadmodel-output-test-")));
  chmodSync(dir, 0o700);
  return dir;
}
const mode = (p: string) => statSync(p).mode & 0o777;
type Snapshot = { dev: number; ino: number; content: string };

// Pin the exact file inspected and read; a path replacement cannot redirect the
// read after its checks. Expected identity also detects replacement between reads.
function privateSnapshot(filename: string, links = 1, expected?: Snapshot): Snapshot {
  const fd = openSync(filename, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = fstatSync(fd);
    expect(info.isFile()).toBe(true);
    expect(info.nlink).toBe(links);
    expect(info.uid).toBe(process.getuid!());
    expect(info.mode & 0o777).toBe(0o600);
    if (expected) {
      expect(info.dev).toBe(expected.dev);
      expect(info.ino).toBe(expected.ino);
    }
    return { dev: info.dev, ino: info.ino, content: readFileSync(fd, "utf8") };
  } finally {
    closeSync(fd);
  }
}

test("fresh output is private before first write under permissive umask", () => {
  test.skip(process.platform === "win32", "diagnostic helper explicitly refuses unsupported Windows privacy");
  const mask = process.umask(0);
  let output: ReturnType<typeof createPrivateOutput> | undefined;
  try {
    output = createPrivateOutput({ prefix: "synthetic-output" });
    expect(mode(dirname(output.path))).toBe(0o700);
    const before = privateSnapshot(output.path);
    expect(before.content).toBe("");
    output.write('{"id":"synthetic-1"}\n');
    output.write('{"id":"synthetic-2"}\n');
    output.close();
    output.close();
    const after = privateSnapshot(output.path, 1, before);
    expect(after.content.trim().split("\n").map((line) => JSON.parse(line))).toEqual([
      { id: "synthetic-1" }, { id: "synthetic-2" },
    ]);
    expect(() => output!.write("late")).toThrow();
  } finally {
    output?.close();
    process.umask(mask);
    if (output) rmSync(dirname(output.path), { recursive: true, force: true });
  }
});

for (const kind of ["regular", "symlink", "hardlink"] as const) {
  test(`existing ${kind} is refused without changing target`, () => {
    test.skip(process.platform === "win32");
    const dir = ownedFixture(), target = join(dir, "sentinel"), file = join(dir, "result.jsonl");
    writeFileSync(target, "synthetic sentinel", { mode: 0o600 });
    if (kind === "symlink") symlinkSync(target, file);
    else if (kind === "hardlink") linkSync(target, file);
    else writeFileSync(file, "synthetic existing", { mode: 0o600 });
    try {
      // This sentinel deliberately has two links in the hardlink refusal case.
      const links = kind === "hardlink" ? 2 : 1;
      const before = privateSnapshot(target, links);
      expect(() => createPrivateOutput({ prefix: "synthetic", path: file })).toThrow();
      expect(privateSnapshot(target, links, before).content).toBe("synthetic sentinel");
      if (kind === "regular") expect(privateSnapshot(file).content).toBe("synthetic existing");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
}

test("safe explicit output preserves caller's exact path", () => {
  test.skip(process.platform === "win32");
  const dir = ownedFixture(), file = join(dir, "name with spaces.jsonl");
  let output: ReturnType<typeof createPrivateOutput> | undefined;
  try {
    output = createPrivateOutput({ prefix: "synthetic", path: file });
    expect(output.path).toBe(file);
    const before = privateSnapshot(file);
    expect(before.content).toBe("");
    output.write('{"synthetic":true}\n');
    expect(privateSnapshot(file, 1, before).content).toBe('{"synthetic":true}\n');
  } finally {
    output?.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("explicit output accepts the operating system temporary root alias", () => {
  test.skip(process.platform === "win32");
  const dir = mkdtempSync(join(tmpdir(), "roadmodel-output-test-"));
  chmodSync(dir, 0o700);
  let output: ReturnType<typeof createPrivateOutput> | undefined;
  try {
    output = createPrivateOutput({ prefix: "synthetic", path: join(dir, "rows.jsonl") });
    const before = privateSnapshot(output.path);
    expect(before.content).toBe("");
    output.write("synthetic\n");
    expect(privateSnapshot(join(dir, "rows.jsonl"), 1, before).content).toBe("synthetic\n");
  } finally {
    output?.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

for (const permissions of [0o755, 0o777]) {
  test(`unsafe override parent ${permissions.toString(8)} is refused, never repaired`, () => {
    test.skip(process.platform === "win32");
    const dir = ownedFixture(), file = join(dir, "output.jsonl");
    chmodSync(dir, permissions);
    try {
      expect(() => createPrivateOutput({ prefix: "synthetic", path: file })).toThrow();
      expect(mode(dir)).toBe(permissions);
      expect(existsSync(file)).toBe(false);
    } finally {
      chmodSync(dir, 0o700);
      rmSync(dir, { recursive: true, force: true });
    }
  });
}

test("explicit parent symlink is refused without following it", () => {
  test.skip(process.platform === "win32");
  const dir = ownedFixture(), parent = ownedFixture(), alias = join(dir, "alias");
  symlinkSync(parent, alias);
  try {
    expect(() => createPrivateOutput({ prefix: "synthetic", path: join(alias, "output.jsonl") })).toThrow();
    expect(existsSync(join(parent, "output.jsonl"))).toBe(false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(parent, { recursive: true, force: true });
  }
});

test("Windows diagnostic output explicitly refuses without an ACL implementation", () => {
  test.skip(process.platform !== "win32");
  expect(() => createPrivateOutput({ prefix: "synthetic" })).toThrow();
});
