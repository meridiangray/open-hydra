(() => {
    const root = document.getElementById('source-browser');
    if (!root) return;
    const data = JSON.parse(root.querySelector('#source-data').textContent);
    const entries = new Map(data.entries.map(entry => [entry.id, entry]));
    const state = {filter:'all', query:'', group:null, document:null, groupPage:0, documentPage:0};
    const size = 8;
    const documentSize = 6;
    const el = (tag, cls, text) => {
        const node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text !== undefined) node.textContent = text;
        return node;
    };
    const button = (text, action, cls) => {
        const node = el('button', cls, text);
        node.type = 'button';
        node.addEventListener('click', action);
        return node;
    };
    const link = (text, href) => {
        const node = el('a', '', text);
        node.href = href;
        return node;
    };
    const count = (n, word) => `${n.toLocaleString()} ${n === 1 ? word : word.endsWith('y') ? word.slice(0, -1) + 'ies' : word + 's'}`;
    const allowed = entry => state.filter !== 'wiki' || entry.coverage === 'wiki';
    for (const doc of data.documents) {
        doc.search = [doc.title, doc.group, doc.publisher, doc.url, ...doc.entries.map(id => entries.get(id).title)].join(' ').toLocaleLowerCase();
    }
    function pager(node, total, page, change, limit = size) {
        node.replaceChildren();
        if (total <= limit) return;
        const previous = button('Previous', () => change(page - 1));
        previous.disabled = page === 0;
        const next = button('Next', () => change(page + 1));
        next.disabled = (page + 1) * limit >= total;
        node.append(previous, el('span', 'meta', `${page * limit + 1}–${Math.min((page + 1) * limit, total)} of ${total}`), next);
    }
    function entryList(node, rows, missing = false) {
        let page = 0;
        const list = el('ul', 'source-entry-list');
        const pages = el('div', 'source-pagination');
        node.append(list, pages);
        const draw = () => {
            list.replaceChildren();
            for (const entry of rows.slice(page * size, (page + 1) * size)) {
                const item = el('li');
                item.append(link(entry.title, entry.href));
                if (missing) item.append(el('span', 'meta', `${count(entry.missing, 'record')} without a source`));
                list.append(item);
            }
            pager(pages, rows.length, page, value => { page = value; draw(); });
        };
        draw();
    }
    function groups() {
        if (state.filter === 'missing') {
            const rows = data.entries.filter(entry => entry.missing && entry.title.toLocaleLowerCase().includes(state.query));
            return rows.length ? [{id:'missing', documents:[], entries:rows, records:new Set()}] : [];
        }
        const found = new Map();
        for (const doc of data.documents) {
            const rows = doc.entries.map(id => entries.get(id)).filter(allowed);
            if (!rows.length || state.filter === 'saved' && doc.kind !== 'saved' || !doc.search.includes(state.query)) continue;
            if (!found.has(doc.group)) found.set(doc.group, {id:doc.group, documents:[], entries:new Set(), records:new Set()});
            const group = found.get(doc.group);
            group.documents.push(doc);
            rows.forEach(entry => group.entries.add(entry.id));
            doc.records.filter(record => record.entries.some(id => allowed(entries.get(id)))).forEach(record => group.records.add(record.id));
        }
        return [...found.values()].sort((a, b) => Number(a.id === 'Unresolved references') - Number(b.id === 'Unresolved references') || b.records.size - a.records.size || a.id.localeCompare(b.id));
    }
    function inspect(group) {
        const panel = root.querySelector('#source-inspector');
        panel.replaceChildren();
        if (!group) {
            panel.append(el('h2', '', 'No matching sources'), el('p', 'meta', 'Try a different search or filter. Missing sources lists entries with uncited records.'));
            return;
        }
        if (group.id === 'missing') {
            panel.append(el('h2', '', 'Missing sources'), el('p', 'meta', 'These entries have one or more records without a document or URL citation. Other records on the same entry may be sourced.'));
            entryList(panel, group.entries, true);
            return;
        }
        const selected = group.documents.find(doc => doc.id === state.document);
        if (selected) {
            const back = button('← Documents', () => { state.document = null; inspect(group); }, 'source-back');
            const heading = el('h3', 'source-title', selected.title);
            heading.tabIndex = -1;
            panel.append(back, heading);
            const kind = selected.kind === 'saved' ? 'Saved document record' : selected.kind === 'unresolved' ? 'Unresolved reference' : 'Link only';
            panel.append(el('p', 'source-kind', kind));
            const metadata = [selected.publisher, selected.published && `Published ${selected.published}`, selected.retrieved && `Retrieved ${selected.retrieved}`].filter(Boolean);
            if (metadata.length) panel.append(el('p', 'meta', metadata.join(' · ')));
            const actions = el('p', 'source-actions');
            if (selected.url) {
                const original = link('Original source', selected.url);
                original.rel = 'noreferrer';
                actions.append(original);
            }
            if (selected.href) actions.append(link('Open saved document record', selected.href));
            panel.append(actions);
            if (selected.url) panel.append(el('p', 'source-url', selected.url));
            if (selected.kind === 'saved') panel.append(el('p', 'meta', 'This is the saved document’s metadata. Full retained file text is not exposed by this wiki view.'));
            panel.append(el('h4', 'source-subheading', 'Used for'));
            const rows = selected.entries.map(id => entries.get(id)).filter(allowed).sort((a, b) => a.title.localeCompare(b.title));
            entryList(panel, rows);
            if (selected.notes.length) {
                const notes = el('details', 'source-notes');
                notes.append(el('summary', '', `Citation notes (${selected.notes.length})`), el('p', 'meta', 'Saved notes from citing records. A record may cite several sources; these notes are not necessarily verbatim quotations from this document.'));
                const body = el('div');
                const pages = el('div', 'source-pagination');
                let page = 0;
                const draw = () => {
                    body.replaceChildren(...selected.notes.slice(page * size, (page + 1) * size).map(note => el('pre', 'source-note', note)));
                    pager(pages, selected.notes.length, page, value => { page = value; draw(); });
                };
                draw();
                notes.append(body, pages);
                panel.append(notes);
            }
            return;
        }
        panel.append(el('h2', 'source-title', group.id));
        panel.append(el('p', 'meta', `${count(group.documents.length, 'source')} · ${count(group.entries.size, 'entry')} · ${count(group.records.size, 'citing record')}`));
        panel.append(el('p', 'meta', 'Choose a source to see its details and the entries it supports. Counts are usage, not a reliability rating.'));
        const docs = [...group.documents].sort((a, b) => b.records.length - a.records.length || a.title.localeCompare(b.title));
        const list = el('div', 'source-documents');
        for (const doc of docs.slice(state.documentPage * documentSize, (state.documentPage + 1) * documentSize)) {
            const item = button('', () => {
                state.document = doc.id;
                inspect(group);
                panel.querySelector('.source-title').focus({preventScroll:true});
            }, 'source-document');
            item.append(el('span', 'source-document-title', doc.title), el('span', 'meta', `${doc.kind === 'saved' ? 'Saved record' : doc.kind === 'unresolved' ? 'Unresolved reference' : 'Link only'} · ${count(doc.entries.map(id => entries.get(id)).filter(allowed).length, 'entry')}`));
            list.append(item);
        }
        const pages = el('div', 'source-pagination');
        pager(pages, docs.length, state.documentPage, value => { state.documentPage = value; inspect(group); }, documentSize);
        panel.append(list, pages);
    }
    function render() {
        const rows = groups();
        if (!rows.some(group => group.id === state.group)) {
            state.group = rows[0]?.id || null;
            state.document = null;
            state.documentPage = 0;
        }
        state.groupPage = Math.min(state.groupPage, Math.max(0, Math.ceil(rows.length / size) - 1));
        root.querySelector('#source-summary').textContent = state.filter === 'missing' ? `${count(rows[0]?.entries.length || 0, 'entry')} with uncited records` : count(rows.length, 'source group');
        const list = root.querySelector('#source-groups');
        list.replaceChildren();
        for (const group of rows.slice(state.groupPage * size, (state.groupPage + 1) * size)) {
            const item = button('', () => {
                state.group = group.id;
                state.document = null;
                state.documentPage = 0;
                render();
                root.querySelector('#source-inspector').focus({preventScroll:true});
            }, 'source-group');
            item.setAttribute('aria-pressed', String(group.id === state.group));
            item.setAttribute('aria-controls', 'source-inspector');
            const usage = group.id === 'missing' ? group.entries.length : group.records.size;
            item.setAttribute('aria-label', `${group.id}: ${count(usage, group.id === 'missing' ? 'entry' : 'citing record')}`);
            const total = el('span', 'meta', usage.toLocaleString());
            total.title = count(usage, group.id === 'missing' ? 'entry' : 'citing record');
            item.append(el('span', '', group.id === 'missing' ? 'Missing sources' : group.id), total);
            list.append(item);
        }
        pager(root.querySelector('#source-group-pages'), rows.length, state.groupPage, value => { state.groupPage = value; render(); });
        inspect(rows.find(group => group.id === state.group));
    }
    root.querySelector('#source-inspector').tabIndex = -1;
    root.querySelector('#source-search').addEventListener('input', event => {
        state.query = event.target.value.trim().toLocaleLowerCase();
        state.groupPage = 0;
        state.documentPage = 0;
        state.document = null;
        render();
    });
    root.querySelectorAll('[data-source-filter]').forEach(item => item.addEventListener('click', () => {
        state.filter = item.dataset.sourceFilter;
        state.groupPage = 0;
        state.documentPage = 0;
        state.document = null;
        root.querySelectorAll('[data-source-filter]').forEach(other => other.setAttribute('aria-pressed', String(other === item)));
        render();
    }));
    render();
})();
