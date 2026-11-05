import { readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
for(const file of readdirSync('tests/browser').filter(f=>f.endsWith('.cjs'))){
 const result=spawnSync(process.execPath,['tests/browser/'+file],{stdio:'inherit',env:process.env});
 if(result.status!==0)process.exit(result.status||1);
}
