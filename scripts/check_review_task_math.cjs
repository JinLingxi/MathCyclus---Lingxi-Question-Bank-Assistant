// Syntax-check extracted formulas with an explicitly supplied local KaTeX build.
const fs = require("fs");
const path = require("path");
const [input, runtime, output] = process.argv.slice(2);
if (!input || !runtime || !output) throw Error("usage: node script input.json katex.min.js output.json");
if (fs.existsSync(output)) throw Error("output already exists");
const katex = require(path.resolve(runtime));
const rows = JSON.parse(fs.readFileSync(input,"utf8"));
const failures=[];
let formulas=0;
for (const row of rows) {
  for (const [field,text] of row.fields) {
    const pattern = /(?<!\\)\$\$([\s\S]*?)(?<!\\)\$\$|(?<!\\)\$([^$]*?)(?<!\\)\$|\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)/g;
    for (const match of text.matchAll(pattern)) {
      const formula=match[1] ?? match[2] ?? match[3] ?? match[4];
      formulas++;
      try {katex.renderToString(formula,{throwOnError:true,strict:"ignore",trust:false,
          displayMode:match[1]!==undefined || match[3]!==undefined});}
      catch(error) {failures.push({draft_id:row.draft_id,year:row.year,source:row.source,
        number:row.number,field,formula,error:String(error.message)});}
    }
  }
}
fs.writeFileSync(output,JSON.stringify({drafts:rows.length,formulas,failures,version:katex.version},null,2));
process.stdout.write(JSON.stringify({drafts:rows.length,formulas,failures:failures.length,version:katex.version}));
