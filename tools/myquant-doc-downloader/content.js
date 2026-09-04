const ROOT = /^https:\/\/(www\.)?myquant\.cn\/docs2\//;
let running = false;

function normalize(url) {
  const parsed = new URL(url, location.href);
  parsed.hash = '';
  parsed.search = '';
  if (!ROOT.test(parsed.href)) return null;
  if (!/\/$|\.html?$/.test(parsed.pathname)) return null;
  return parsed.href;
}

function markdownFromDocument(doc, url) {
  const title = (doc.querySelector('h1, title')?.textContent || url).trim();
  const root = doc.querySelector('article, main, .markdown-body, .content, #content') || doc.body;
  const clone = root.cloneNode(true);
  clone.querySelectorAll('script,style,nav,header,footer,button,svg').forEach(el => el.remove());
  clone.querySelectorAll('pre').forEach(pre => {
    const code = pre.textContent.replace(/\n+$/, '');
    pre.replaceWith('\n\n```\n' + code + '\n```\n');
  });
  clone.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(h => {
    const level = Number(h.tagName.substring(1));
    h.replaceWith(`\n\n${'#'.repeat(level)} ${h.textContent.trim()}\n\n`);
  });
  clone.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
  clone.querySelectorAll('li').forEach(li => li.replaceWith(`\n- ${li.textContent.trim()}\n`));
  clone.querySelectorAll('p,div,tr').forEach(el => el.insertAdjacentText('beforebegin', '\n'));
  const body = clone.textContent.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  return `# ${title}\n\n来源：${url}\n\n${body}\n`;
}

async function sha256(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

function filePath(url, title) {
  const parsed = new URL(url);
  let path = decodeURIComponent(parsed.pathname).replace(/^\/docs2\//, '').replace(/\/$/, '/index');
  path = path.replace(/\.html?$/, '');
  const cleanTitle = title.replace(/[\\/:*?"<>|]/g, '_').replace(/\s+/g, ' ').trim();
  return `${path || 'index'}-${cleanTitle || 'document'}.md`;
}

async function fetchPage(url) {
  const response = await fetch(url, {credentials: 'include', redirect: 'follow'});
  const html = await response.text();
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const doc = new DOMParser().parseFromString(html, 'text/html');
  if (doc.querySelector('title')?.textContent?.includes('403 Forbidden')) throw new Error('页面返回 403');
  const links = [...doc.querySelectorAll('a[href]')].map(a => normalize(a.href)).filter(Boolean);
  return {markdown: markdownFromDocument(doc, url), links};
}

async function sync() {
  if (running) return {message: '已有同步任务正在运行。'};
  running = true;
  try {
    const manifest = (await chrome.storage.local.get('myquantManifest')).myquantManifest || {};
    const queue = [...new Set([...document.querySelectorAll('a[href]')].map(a => normalize(a.href)).filter(Boolean))];
    const seen = new Set(queue), failed = [], changed = [], unchanged = [];
    let processed = 0;
    while (queue.length) {
      const url = queue.shift();
      try {
        const page = await fetchPage(url);
        for (const link of page.links) if (!seen.has(link)) { seen.add(link); queue.push(link); }
        const hash = await sha256(page.markdown);
        const path = filePath(url, page.markdown.split('\n')[0].replace(/^# /, ''));
        if (manifest[url]?.hash === hash && manifest[url]?.path === path) unchanged.push(url);
        else {
          const saved = await chrome.runtime.sendMessage({type: 'SAVE_DOCUMENT', path, content: page.markdown});
          if (!saved?.ok) throw new Error(saved?.error || '保存失败');
          manifest[url] = {hash, path, syncedAt: new Date().toISOString()};
          changed.push(url);
        }
      } catch (error) { failed.push(`${url}：${error.message}`); }
      processed++;
    }
    await chrome.storage.local.set({myquantManifest: manifest});
    const summary = `完成：扫描 ${processed} 页，新增/更新 ${changed.length} 页，未变化 ${unchanged.length} 页，失败 ${failed.length} 页。`;
    return {message: failed.length ? `${summary}\n\n失败列表：\n${failed.join('\n')}` : summary};
  } finally { running = false; }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'START_SYNC') { sync().then(sendResponse).catch(e => sendResponse({message: `失败：${e.message}`})); return true; }
});
