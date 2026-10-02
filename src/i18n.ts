// Display language (English / Simplified Chinese), shared by the tiles' client scripts.
// The choice lives on <html data-lang>, set before first paint by the inline script in Base.astro.
// Static text is rendered in both languages by T.astro and CSS shows one; scripts that build
// text at runtime read lang() and re-render on onLang().

export type Lang = 'en' | 'zh';

const STORAGE_KEY = 'lang';
const EVENT = 'langchange';

export const lang = (): Lang => (document.documentElement.dataset.lang === 'zh' ? 'zh' : 'en');

// Locale for Intl date/time formatting.
export const locale = () => (lang() === 'zh' ? 'zh-CN' : 'en-CA');

export function setLang(l: Lang) {
	if (l === lang()) return;
	const html = document.documentElement;
	html.dataset.lang = l;
	html.lang = l === 'zh' ? 'zh-CN' : 'en';
	try {
		localStorage.setItem(STORAGE_KEY, l);
	} catch {}
	swapAttrs();
	document.dispatchEvent(new Event(EVENT));
}

export function onLang(render: () => void) {
	document.addEventListener(EVENT, render);
}

// For tiles that draw from fetched data: show(draw) runs draw now and again on every language change,
// so whatever was last on screen (fresh, cached or an error) is redrawn in the new language.
export function redrawable() {
	let last = () => {};
	onLang(() => last());
	return (draw: () => void) => {
		last = draw;
		draw();
	};
}

// Attributes that cannot hold two spans: put the Chinese in data-zh-<attr>; English stays in <attr>.
const ATTRS = ['title', 'aria-label', 'placeholder'];
function swapAttrs() {
	const l = lang();
	for (const a of ATTRS) {
		for (const el of document.querySelectorAll(`[data-zh-${a}]`)) {
			if (!el.hasAttribute(`data-en-${a}`)) el.setAttribute(`data-en-${a}`, el.getAttribute(a) ?? '');
			el.setAttribute(a, el.getAttribute(`data-${l}-${a}`)!);
		}
	}
}
swapAttrs();

// Wording shared by the tiles that fetch data.
const common = {
	en: {
		updated: (time: string) => `Updated ${time}`,
		stale: (time: string) => `Couldn't refresh · last updated ${time}`,
		unavailable: 'Unavailable',
	},
	zh: {
		updated: (time: string) => `更新于 ${time}`,
		stale: (time: string) => `刷新失败 · 上次更新 ${time}`,
		unavailable: '暂不可用',
	},
};
export const t = () => common[lang()];

// "3:15 p.m." / "15:15", Toronto time.
export const timeOf = (at: number) =>
	new Date(at).toLocaleTimeString(locale(), { timeZone: 'America/Toronto', hour: 'numeric', minute: '2-digit' });
