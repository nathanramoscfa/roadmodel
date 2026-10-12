import { expect, test } from "@playwright/test";
import { realpathSync, chmodSync, existsSync, linkSync, lstatSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { tmpdir } from "node:os";
import { createPrivateOutput } from "../../scripts/private-diagnostic-output";

function ownedFixture() { const dir=realpathSync(mkdtempSync(join(tmpdir(), "roadmodel-output-test-"))); chmodSync(dir,0o700); return dir; }
const mode=(p:string)=>statSync(p).mode&0o777;

test("fresh output is private before first write under permissive umask",()=>{
  test.skip(process.platform==="win32","diagnostic helper explicitly refuses unsupported Windows privacy");
  const mask=process.umask(0);let output:ReturnType<typeof createPrivateOutput>|undefined;
  try {
    output=createPrivateOutput({prefix:"synthetic-output"});
    expect(mode(dirname(output.path))).toBe(0o700);expect(mode(output.path)).toBe(0o600);
    expect(lstatSync(output.path).isFile()).toBe(true);expect(lstatSync(output.path).nlink).toBe(1);
    expect(lstatSync(output.path).uid).toBe(process.getuid!());
    expect(readFileSync(output.path,"utf8")).toBe("");
    output.write('{"id":"synthetic-1"}\n');output.write('{"id":"synthetic-2"}\n');
    output.close();output.close();
    expect(readFileSync(output.path,"utf8").trim().split("\n").map((line)=>JSON.parse(line))).toEqual([{id:"synthetic-1"},{id:"synthetic-2"}]);
    expect(()=>output!.write("late")).toThrow();
  } finally { output?.close();process.umask(mask);if(output)rmSync(dirname(output.path),{recursive:true,force:true}); }
});

for(const kind of ["regular","symlink","hardlink"] as const)test(`existing ${kind} is refused without changing target`,()=>{
  test.skip(process.platform==="win32");const dir=ownedFixture();const target=join(dir,"sentinel"),file=join(dir,"result.jsonl");
  writeFileSync(target,"synthetic sentinel",{mode:0o600});
  if(kind==="symlink")symlinkSync(target,file);else if(kind==="hardlink")linkSync(target,file);else writeFileSync(file,"synthetic existing",{mode:0o600});
  try{expect(()=>createPrivateOutput({prefix:"synthetic",path:file})).toThrow();expect(readFileSync(target,"utf8")).toBe("synthetic sentinel");if(kind==="regular")expect(readFileSync(file,"utf8")).toBe("synthetic existing");}
  finally{rmSync(dir,{recursive:true,force:true});}
});

test("safe explicit output preserves caller's exact path",()=>{
  test.skip(process.platform==="win32");const dir=ownedFixture(),file=join(dir,"name with spaces.jsonl");let output:ReturnType<typeof createPrivateOutput>|undefined;
  try{output=createPrivateOutput({prefix:"synthetic",path:file});expect(output.path).toBe(file);output.write('{"synthetic":true}\n');expect(mode(file)).toBe(0o600);}
  finally{output?.close();rmSync(dir,{recursive:true,force:true});}
});

test("explicit output accepts the operating system temporary root alias",()=>{
  test.skip(process.platform==="win32");
  const dir=mkdtempSync(join(tmpdir(),"roadmodel-output-test-"));chmodSync(dir,0o700);
  let output:ReturnType<typeof createPrivateOutput>|undefined;
  try{output=createPrivateOutput({prefix:"synthetic",path:join(dir,"rows.jsonl")});output.write("synthetic\n");expect(readFileSync(join(dir,"rows.jsonl"),"utf8")).toBe("synthetic\n");expect(mode(output.path)).toBe(0o600);}
  finally{output?.close();rmSync(dir,{recursive:true,force:true});}
});

for(const permissions of [0o755,0o777])test(`unsafe override parent ${permissions.toString(8)} is refused, never repaired`,()=>{
  test.skip(process.platform==="win32");const dir=ownedFixture(),file=join(dir,"output.jsonl");chmodSync(dir,permissions);
  try{expect(()=>createPrivateOutput({prefix:"synthetic",path:file})).toThrow();expect(mode(dir)).toBe(permissions);expect(existsSync(file)).toBe(false);}
  finally{chmodSync(dir,0o700);rmSync(dir,{recursive:true,force:true});}
});

test("explicit parent symlink is refused without following it",()=>{
  test.skip(process.platform==="win32");const dir=ownedFixture(),parent=ownedFixture(),alias=join(dir,"alias");symlinkSync(parent,alias);
  try{expect(()=>createPrivateOutput({prefix:"synthetic",path:join(alias,"output.jsonl")})).toThrow();expect(existsSync(join(parent,"output.jsonl"))).toBe(false);}
  finally{rmSync(dir,{recursive:true,force:true});rmSync(parent,{recursive:true,force:true});}
});

test("Windows diagnostic output explicitly refuses without an ACL implementation",()=>{
  test.skip(process.platform!=="win32");expect(()=>createPrivateOutput({prefix:"synthetic"})).toThrow();
});
