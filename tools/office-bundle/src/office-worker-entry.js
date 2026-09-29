// MiniYuxi 办公操作面 —— Univer **公式引擎 Worker** 入口
//
// 为什么必须有这个文件：
//   @univerjs/preset-sheets-core 的 preset 工厂里有 `notExecuteFormula: !!workerURL`——
//   **主线程没传 workerURL 时，它会主动把公式执行关掉**（公式只注册、不求值），
//   表现为 HR 表格里 SUM/AVG 填了不出结果。传了 workerURL 才会自动打开公式执行。
//
// 本文件就是那个 workerURL 指向的脚本：在 Worker 线程里跑公式引擎 + RPC 从端。
// 注意：
//   · 只 import worker preset（公式引擎 + RPC），**不要 import 任何 UI/渲染 preset 或 CSS**
//     —— Worker 里没有 DOM。
//   · 产物必须是 **classic worker**（主线程用 `new Worker(url)` 无 type 选项），
//     所以 esbuild 用 IIFE 格式，不能是 ESM。
import { createUniver, LocaleType, mergeLocales } from '@univerjs/presets';
import { UniverSheetsCoreWorkerPreset } from '@univerjs/preset-sheets-core/worker';
import UniverPresetSheetsCoreZhCN from '@univerjs/preset-sheets-core/locales/zh-CN';

createUniver({
  // locale 影响公式错误信息（#VALUE! 等）的语言，与主线程保持一致
  locale: LocaleType.ZH_CN,
  locales: {
    [LocaleType.ZH_CN]: mergeLocales(UniverPresetSheetsCoreZhCN),
  },
  presets: [UniverSheetsCoreWorkerPreset()],
});
