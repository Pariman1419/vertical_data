(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory;
  else root.V2Table = factory(root.TanStack);
})(globalThis, function (T) {
  'use strict';
  const ROW = 34, COL = 190, HEADER = 58;
  function cell(value) {
    const text = value === null ? 'null' : String(value ?? '');
    return { text: text.length > 200 ? text.slice(0, 199) + '…' : text, title: text, null: value === null };
  }
  function compareNumber(a, b) {
    // Decimal/Int64 strings retain their precision; no Number coercion for exact values.
    const parts = value => {
      const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(String(value));
      return match && { sign: match[1] ? -1 : 1, int: match[2].replace(/^0+(?=\d)/, ''), frac: (match[3] || '').replace(/0+$/, '') };
    };
    const x = parts(a), y = parts(b);
    if (!x || !y) return Number(a) - Number(b);
    if (x.int === '0' && !x.frac) x.sign = 1;
    if (y.int === '0' && !y.frac) y.sign = 1;
    if (x.sign !== y.sign) return x.sign - y.sign;
    const width = Math.max(x.frac.length, y.frac.length);
    const left = x.int + '.' + x.frac.padEnd(width, '0'), right = y.int + '.' + y.frac.padEnd(width, '0');
    return (x.int.length - y.int.length || (left < right ? -1 : left > right ? 1 : 0)) * x.sign;
  }
  function model(data, opts = {}) {
    let state = { sorting: [], columnVisibility: Object.fromEntries(data.columns.map((_, i) => ['c' + i, i < (opts.maxColumnsShown ?? 20)])) };
    const columns = data.columns.map((col, index) => ({ id: 'c' + index, accessorFn: row => row[index], header: col.name,
      sortingFn(a, b, id) {
        const x = a.getValue(id), y = b.getValue(id);
        if (x === null || y === null) return x === y ? 0 : x === null ? -1 : 1;
        if (/^(u?int|decimal|float|double)/i.test(col.type)) return compareNumber(x, y);
        return String(x).localeCompare(String(y));
      } }));
    const table = T.createTable({ data: data.rows, columns, state, getCoreRowModel: T.getCoreRowModel(),
      getSortedRowModel: T.getSortedRowModel(), onStateChange(update) {
        state = typeof update === 'function' ? update(state) : update;
        table.setOptions(old => ({ ...old, state }));
      }, renderFallbackValue: null });
    const virtual = (count, size, horizontal) => new T.Virtualizer({ count, horizontal, estimateSize: () => size,
      getScrollElement: () => null, scrollToFn: () => {}, observeElementRect: () => {}, observeElementOffset: () => {}, overscan: 3,
      initialRect: { width: 800, height: 600 } });
    const rows = virtual(data.rows.length, ROW, false), cols = virtual(table.getVisibleLeafColumns().length, COL, true);
    return {
      table, rowVirtualizer: rows, columnVirtualizer: cols,
      rows: () => table.getRowModel().rows,
      columns: () => table.getVisibleLeafColumns(),
      search: text => data.columns.filter(c => c.name.toLowerCase().includes(text.toLowerCase())),
      sort(name) { const column = table.getColumn('c' + data.columns.findIndex(c => c.name === name)); column?.toggleSorting(); },
      setVisibleColumns(names) {
        const visible = new Set(names);
        table.setColumnVisibility(Object.fromEntries(data.columns.map((c, i) => ['c' + i, visible.has(c.name)])));
        cols.setOptions({ ...cols.options, count: table.getVisibleLeafColumns().length });
      },
      window({ width = 800, height = 600, scrollTop = 0, scrollLeft = 0 } = {}) {
        rows.scrollRect = cols.scrollRect = { width, height };
        rows.scrollOffset = scrollTop; cols.scrollOffset = scrollLeft;
        const rowItems = rows.getVirtualItems(), colItems = cols.getVirtualItems();
        const cells = rowItems.flatMap(r => colItems.map(c => ({ row: r.index, column: c.index })));
        return { rows: rowItems, columns: colItems, cells };
      }
    };
  }
  function mount(el, data, opts = {}) {
    const m = model(data, opts), doc = el.ownerDocument;
    let frame = 0, destroyed = false;
    const make = (tag, className, text) => { const node = doc.createElement(tag); node.className = className; if (text !== undefined) node.textContent = text; return node; };
    const picker = make('details', 'v2-columns'), summary = make('summary', '', 'Columns');
    const search = make('input', ''); search.type = 'search'; search.placeholder = 'Search columns'; search.setAttribute('aria-label', 'Search columns');
    const choices = make('div', 'v2-column-choices'); picker.append(summary, search, choices);
    const scroll = make('div', 'v2-grid'); scroll.tabIndex = 0; scroll.setAttribute('role', 'grid');
    scroll.setAttribute('aria-label', 'Preview. Use arrow keys to scroll. Tab to headers to sort.');
    scroll.setAttribute('aria-rowcount', String(data.rows.length + 1));
    const canvas = make('div', 'v2-grid-canvas'); scroll.append(canvas);
    el.replaceChildren(picker, scroll);
    const schedule = () => { if (!frame && !destroyed) frame = requestAnimationFrame(() => { frame = 0; paint(); }); };
    function paint() {
      if (destroyed) return;
      const focused = doc.activeElement?.dataset.sortColumn;
      const columns = m.columns(), rowData = m.rows();
      const view = m.window({ width: scroll.clientWidth, height: Math.max(0, scroll.clientHeight - HEADER),
        scrollTop: scroll.scrollTop, scrollLeft: scroll.scrollLeft });
      const visible = view.columns.slice();
      if (columns.length && !visible.some(c => c.index === 0)) visible.unshift({ index: 0, start: 0 });
      canvas.style.width = Math.max(scroll.clientWidth, columns.length * COL) + 'px';
      canvas.style.height = HEADER + data.rows.length * ROW + 'px';
      scroll.setAttribute('aria-colcount', String(columns.length));
      const fragment = doc.createDocumentFragment();
      const headerRow = make('div', 'v2-grid-header'); headerRow.setAttribute('role', 'row');
      headerRow.style.top = scroll.scrollTop + 'px';
      for (const c of visible) {
        const column = columns[c.index], source = data.columns[Number(column.id.slice(1))];
        const header = make('div', 'v2-cell v2-header' + (c.index === 0 ? ' v2-frozen' : ''));
        header.setAttribute('role', 'columnheader'); header.setAttribute('aria-colindex', String(c.index + 1));
        header.setAttribute('aria-sort', column.getIsSorted() === 'asc' ? 'ascending' : column.getIsSorted() === 'desc' ? 'descending' : 'none');
        const button = make('button', '', source.name); button.type = 'button'; button.title = 'Sort by ' + source.name;
        button.dataset.sortColumn = column.id;
        button.addEventListener('click', () => { m.sort(source.name); paint(); });
        header.append(button, make('small', 'muted', source.type));
        header.style.left = (c.index === 0 ? scroll.scrollLeft : c.start) + 'px'; headerRow.append(header);
      }
      fragment.append(headerRow);
      for (const r of view.rows) {
        const row = make('div', 'v2-grid-row'); row.setAttribute('role', 'row'); row.setAttribute('aria-rowindex', String(r.index + 2));
        row.style.top = HEADER + r.start + 'px';
        for (const c of visible) {
          const value = cell(rowData[r.index].getValue(columns[c.index].id));
          const node = make('div', 'v2-cell' + (c.index === 0 ? ' v2-frozen' : '') + (value.null ? ' muted' : ''), value.text);
          node.title = value.title; node.setAttribute('role', 'gridcell'); node.setAttribute('aria-colindex', String(c.index + 1));
          node.style.left = (c.index === 0 ? scroll.scrollLeft : c.start) + 'px'; row.append(node);
        }
        fragment.append(row);
      }
      canvas.replaceChildren(fragment);
      if (focused) canvas.querySelector(`[data-sort-column="${focused}"]`)?.focus({ preventScroll: true });
    }
    function renderChoices() {
      const visible = new Set(m.columns().map(c => c.columnDef.header));
      choices.replaceChildren(...m.search(search.value).map(c => {
        const label = make('label', ''), input = make('input', ''); input.type = 'checkbox'; input.checked = visible.has(c.name);
        input.addEventListener('change', () => {
          input.checked ? visible.add(c.name) : visible.delete(c.name);
          m.setVisibleColumns([...visible]); scroll.scrollLeft = 0; schedule();
        });
        label.append(input, doc.createTextNode(c.name)); return label;
      }));
    }
    search.addEventListener('input', renderChoices);
    scroll.addEventListener('scroll', schedule, { passive: true });
    const keydown = event => {
      if (event.target !== scroll || !['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault(); scroll.scrollBy({ top: event.key === 'ArrowDown' ? ROW : event.key === 'ArrowUp' ? -ROW : 0,
        left: event.key === 'ArrowRight' ? COL : event.key === 'ArrowLeft' ? -COL : 0 });
    };
    scroll.addEventListener('keydown', keydown);
    const observer = new ResizeObserver(schedule); observer.observe(scroll);
    renderChoices(); paint();
    return {
      destroy() { destroyed = true; observer.disconnect(); cancelAnimationFrame(frame); scroll.removeEventListener('scroll', schedule); scroll.removeEventListener('keydown', keydown); m.rowVirtualizer.cleanup(); m.columnVirtualizer.cleanup(); el.replaceChildren(); },
      setVisibleColumns(names) { m.setVisibleColumns(names); renderChoices(); schedule(); }
    };
  }
  return { mount, cell, _model: model };
});
