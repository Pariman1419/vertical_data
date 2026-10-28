import * as query_core from './query-core/index.js';
import * as table_core from './table-core/index.mjs';
import * as virtual_core from './virtual-core/index.js';
import * as form_core from './form-core/index.js';
import * as store from './store/index.js';
globalThis.TanStack = { ...query_core, ...table_core, ...virtual_core, ...form_core, ...store };
export const TanStack = globalThis.TanStack;
