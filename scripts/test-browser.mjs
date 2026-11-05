import { readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
const requested=process.argv.slice(2);
const files=readdirSync('tests/browser').filter(f=>/^browser_.*\.mjs$/.test(f) && (!requested.length || requested.includes(f)));
if(!files.length)throw new Error('No matching browser tests');
for(const file of files){
  const result=spawnSync(process.execPath,['tests/browser/'+file],{stdio:'inherit',env:{...process.env,WORKFLOW_STATIC:'1'}});
  if(result.status!==0)process.exit(result.status||1);
}
