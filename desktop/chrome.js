(() => {
    if (window !== window.top || location.protocol !== 'http:' || location.hostname !== '127.0.0.1') return;
    const style = document.createElement('style');
    style.textContent = `
html[data-hydra-desktop]{--frame-gap:.75rem;--content-inset:clamp(1rem,3vw,2rem);--windowbar-height:calc(40px + 1.5rem);height:100%;overflow:hidden;scrollbar-gutter:auto}
html[data-hydra-desktop] body{display:block;height:100dvh;margin:0;padding:var(--frame-gap);overflow-y:auto;scroll-padding-top:var(--windowbar-height)}
html[data-hydra-desktop] header.site,html[data-hydra-desktop] nav.rail{top:calc(var(--windowbar-height) - var(--frame-gap));margin:var(--frame-gap) 0;max-height:calc(100dvh - var(--windowbar-height) - var(--frame-gap))}
html[data-hydra-desktop] main{max-width:none;padding:0 var(--content-inset) 3rem}
html[data-hydra-desktop] footer{max-width:none;padding-inline:var(--content-inset)}
html[data-hydra-desktop] .right>header.top{width:auto;max-width:none;margin:0 var(--content-inset) .85rem}
html[data-hydra-desktop] .right>section.stage{max-width:none;padding:0 var(--content-inset) 3rem}
html[data-hydra-desktop] main>.hero.front{margin-top:0}
@media(min-width:64rem){html[data-hydra-desktop] body{display:grid;grid-template-columns:15rem minmax(0,1fr);grid-template-rows:40px minmax(0,1fr);gap:var(--frame-gap);align-items:start}html[data-hydra-desktop] header.site,html[data-hydra-desktop] nav.rail{margin:0;height:calc(100dvh - var(--windowbar-height) - var(--frame-gap))}}
#hydra-windowbar{position:sticky;top:0;grid-column:1/-1;height:40px;z-index:2147483600;display:flex;align-items:center;gap:12px;padding-left:14px;border:1px solid var(--line,#d6d4ce);border-radius:var(--radius,12px);overflow:hidden;background:var(--panel,#f6f5f1);color:var(--ink,#242421);font:12px/1 var(--sans,system-ui,sans-serif);user-select:none;app-region:drag;-webkit-app-region:drag;view-transition-name:hydra-windowbar}
#hydra-windowbar .window-brand{display:flex;align-items:center;gap:8px;flex:none;font-weight:650;letter-spacing:.025em}
#hydra-windowbar .window-mark{display:grid;place-items:center;width:22px;height:22px;border:1px solid color-mix(in srgb,var(--accent,#586c50) 30%,transparent);border-radius:6px;background:color-mix(in srgb,var(--accent,#586c50) 9%,var(--panel,#f6f5f1));color:var(--accent,#586c50);font:600 15px/1 var(--serif,Georgia,serif)}
#hydra-windowbar .window-divider{height:14px;width:1px;flex:none;background:var(--line,#d6d4ce)}
#hydra-windowbar .window-title{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted,#666760)}
#hydra-windowbar .window-controls{display:flex;align-self:stretch;flex:none;app-region:no-drag;-webkit-app-region:no-drag}
#hydra-windowbar button{display:grid;place-items:center;width:46px;height:100%;margin:0;padding:0;border:0;border-radius:0;background:transparent;color:inherit;cursor:default;app-region:no-drag;-webkit-app-region:no-drag}
#hydra-windowbar button:hover{background:color-mix(in srgb,var(--ink,#242421) 9%,transparent)}
#hydra-windowbar button:active{background:color-mix(in srgb,var(--ink,#242421) 15%,transparent)}
#hydra-windowbar button:focus-visible{outline:2px solid var(--accent,#586c50);outline-offset:-4px}
#hydra-windowbar button[data-action=close]:hover{background:#c42b1c;color:white}
#hydra-windowbar button[data-action=close]:active{background:#a92216;color:white}
#hydra-windowbar svg{width:12px;height:12px;fill:none;stroke:currentColor;stroke-width:1;pointer-events:none}
#hydra-windowbar .restore{display:none}
html[data-window-maximized] #hydra-windowbar .maximize{display:none}
html[data-window-maximized] #hydra-windowbar .restore{display:block}
html[data-window-inactive] #hydra-windowbar .window-brand{opacity:.65}
#hydra-window-resize{position:fixed;inset:0 0 auto;height:4px;z-index:2147483601;cursor:ns-resize;app-region:no-drag;-webkit-app-region:no-drag}
html[data-window-maximized] #hydra-window-resize{display:none}
#hydra-scroll-fade{position:fixed;top:0;height:calc(var(--windowbar-height) + 1rem);z-index:30;pointer-events:none;opacity:0;background:linear-gradient(to bottom,var(--bg) calc(var(--windowbar-height) - var(--frame-gap)),transparent);transition:opacity .12s;view-transition-name:hydra-scroll-fade}
html[data-content-scrolled] #hydra-scroll-fade{opacity:1}
@media(prefers-reduced-motion:reduce){#hydra-scroll-fade{transition:none}}
::view-transition-group(hydra-windowbar),::view-transition-group(hydra-scroll-fade){animation:none}
::view-transition-old(hydra-windowbar),::view-transition-old(hydra-scroll-fade){display:none}
::view-transition-new(hydra-windowbar),::view-transition-new(hydra-scroll-fade){animation:none}
@media print{#hydra-windowbar,#hydra-window-resize,#hydra-scroll-fade{display:none!important}html[data-hydra-desktop]{height:auto;overflow:visible}html[data-hydra-desktop] body{height:auto;margin:0;overflow:visible}}
`;
    const prepare = () => {
        if (!document.documentElement) return false;
        document.documentElement.setAttribute('data-hydra-desktop', '');
        document.documentElement.append(style);
        return true;
    };
    if (!prepare()) {
        const observer = new MutationObserver(() => { if (prepare()) observer.disconnect(); });
        observer.observe(document, {childList:true});
    }
    const mount = () => {
        if (document.getElementById('hydra-windowbar')) return;
        const bar = document.createElement('div');
        bar.id = 'hydra-windowbar';
        bar.setAttribute('role', 'toolbar');
        bar.setAttribute('aria-label', 'Application window');
        bar.setAttribute('data-webview-drag', '');
        bar.setAttribute('data-webview-maximize', 'double');
        bar.innerHTML = `<span class="window-brand"><span class="window-mark" aria-hidden="true">H</span>Hydra</span><span class="window-divider" aria-hidden="true"></span><span class="window-title"></span><div class="window-controls" data-webview-ignore><button type="button" data-action="minimize" title="Minimize" aria-label="Minimize window"><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M1 6.5h10"/></svg></button><button type="button" data-action="maximize" title="Maximize" aria-label="Maximize window"><svg class="maximize" viewBox="0 0 12 12" aria-hidden="true"><rect x="1.5" y="1.5" width="9" height="9"/></svg><svg class="restore" viewBox="0 0 12 12" aria-hidden="true"><path d="M3.5 3.5v-2h7v7h-2"/><rect x="1.5" y="3.5" width="7" height="7"/></svg></button><button type="button" data-action="close" title="Close" aria-label="Close window"><svg viewBox="0 0 12 12" aria-hidden="true"><path d="m1.5 1.5 9 9m0-9-9 9"/></svg></button></div>`;
        const title = bar.querySelector('.window-title');
        const maximize = bar.querySelector('[data-action=maximize]');
        const root = document.documentElement;
        const setMaximized = value => {
            root.toggleAttribute('data-window-maximized', value);
            maximize.title = value ? 'Restore' : 'Maximize';
            maximize.setAttribute('aria-label', value ? 'Restore window' : 'Maximize window');
        };
        const updateTitle = () => { title.textContent = document.title || 'Archive'; title.title = title.textContent; };
        const updateFocus = () => root.toggleAttribute('data-window-inactive', !document.hasFocus());
        const syncColor = () => {
            const rgb = getComputedStyle(bar).backgroundColor.match(/[\d.]+/g);
            if (!rgb || rgb.length < 3) return;
            const hex = rgb.slice(0,3).map(n => Math.round(Number(n)).toString(16).padStart(2,'0')).join('');
            window.saucer.internal.message('hydra:chrome:' + hex);
        };
        bar.querySelector('.window-controls').addEventListener('click', async event => {
            const button = event.target.closest('button');
            if (!button) return;
            if (button.dataset.action === 'minimize') await window.saucer.minimize(true);
            if (button.dataset.action === 'close') await window.saucer.close();
            if (button.dataset.action === 'maximize') await window.saucer.maximize(!await window.saucer.maximized());
        });
        const resize = document.createElement('div');
        resize.id = 'hydra-window-resize';
        resize.setAttribute('aria-hidden','true');
        resize.addEventListener('mousedown', event => {
            if (event.button !== 0) return;
            event.preventDefault();
            event.stopPropagation();
            window.saucer.startResize(1 | (event.clientX < 8 ? 4 : event.clientX > innerWidth - 8 ? 8 : 0));
        });
        document.body.prepend(bar, resize);
        const page = document.querySelector('.page, .right') || document.querySelector('main');
        const fade = document.createElement('div');
        fade.id = 'hydra-scroll-fade';
        fade.setAttribute('aria-hidden', 'true');
        const updateScroll = () => root.toggleAttribute('data-content-scrolled', !!page && document.body.scrollTop > 0);
        const updateFade = () => {
            if (!page) return;
            const bounds = page.getBoundingClientRect();
            fade.style.left = bounds.left + 'px';
            fade.style.width = bounds.width + 'px';
        };
        if (page) {
            document.body.prepend(fade);
            new ResizeObserver(updateFade).observe(page);
            document.body.addEventListener('scroll', updateScroll, {passive:true});
            window.addEventListener('resize', updateFade);
        }
        new MutationObserver(updateTitle).observe(document.head, {subtree:true,childList:true,characterData:true});
        new MutationObserver(syncColor).observe(root, {attributes:true,attributeFilter:['data-mode']});
        window.addEventListener('hydra-window-maximized', event => setMaximized(event.detail));
        window.addEventListener('focus', updateFocus);
        window.addEventListener('blur', updateFocus);
        window.addEventListener('pageshow', () => {
            updateTitle();
            updateFocus();
            updateFade();
            updateScroll();
            syncColor();
            window.saucer.maximized().then(setMaximized);
        });
        matchMedia('(prefers-color-scheme: dark)').addEventListener('change', syncColor);
        document.addEventListener('load', event => { if (event.target.tagName === 'LINK') syncColor(); }, true);
        updateTitle();
        updateFocus();
        updateFade();
        updateScroll();
        syncColor();
        window.saucer.maximized().then(setMaximized);
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true});
    else mount();
})();
