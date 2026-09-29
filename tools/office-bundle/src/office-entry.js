// MiniYuxi 办公操作面 —— Univer 入口（浏览器端 Facade 原语，暴露到 window.UniverOffice）
// 仅做"原语导出"，具体创建/填数逻辑放 web/office/office-host.js（我们的 vanilla JS）。
import { createUniver, LocaleType, mergeLocales } from '@univerjs/presets';
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core';
import UniverPresetSheetsCoreZhCN from '@univerjs/preset-sheets-core/locales/zh-CN';
import { UniverDocsCorePreset } from '@univerjs/preset-docs-core';
import UniverPresetDocsCoreZhCN from '@univerjs/preset-docs-core/locales/zh-CN';
import '@univerjs/preset-sheets-core/lib/index.css';
import '@univerjs/preset-docs-core/lib/index.css';

window.UniverOffice = {
  createUniver,
  LocaleType,
  mergeLocales,
  UniverSheetsCorePreset,
  UniverDocsCorePreset,
  sheetsLocale: UniverPresetSheetsCoreZhCN,
  docsLocale: UniverPresetDocsCoreZhCN,
};
