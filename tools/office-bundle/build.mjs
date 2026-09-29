// esbuild 打包 Univer 为**离线**产物（IIFE），落到 web/vendor/univer/
//
// 产出两个文件：
//   univer.bundle.js   —— 主线程 Facade（表格 + 文档 preset、locale、CSS），暴露 window.UniverOffice
//   univer.worker.js   —— 公式引擎 Worker（公式引擎 + RPC 从端），主线程以 workerURL 引用
//
// ⚠️ 少了 univer.worker.js，主线程 preset 会把 notExecuteFormula 置 true → **SUM/AVG 不求值**。
// ⚠️ 两者都必须 IIFE（classic script / classic worker），不能是 ESM：
//    主线程用 `<script src>` 直接跑、Worker 用 `new Worker(url)`（无 type 选项）。
import { build } from 'esbuild';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = resolve(__dirname, '../../web/vendor/univer');
mkdirSync(OUT_DIR, { recursive: true });

// 两个入口共享的编译选项。生产产物必须 minify（未压缩 19MB，WebView 解析过慢）。
// Univer 内部有些依赖会读 process / global，IIFE 在浏览器里需要这些是 undefined 也不报错。
const COMMON = {
  bundle: true,
  format: 'iife',
  loader: { '.css': 'css' },
  define: { 'process.env.NODE_ENV': '"production"' },
  minify: true,
  target: ['es2020'],
  logLevel: 'info',
  legalComments: 'none',
};

// ---- 1) 主线程 ----
const mainOut = resolve(OUT_DIR, 'univer.bundle.js');
await build({
  ...COMMON,
  entryPoints: [resolve(__dirname, 'src/office-entry.js')],
  outfile: mainOut,
});
console.log('✓ 主线程 bundle -> ' + mainOut);

// ---- 2) 公式引擎 Worker ----
const workerOut = resolve(OUT_DIR, 'univer.worker.js');
await build({
  ...COMMON,
  entryPoints: [resolve(__dirname, 'src/office-worker-entry.js')],
  outfile: workerOut,
});
console.log('✓ 公式引擎 worker -> ' + workerOut);
