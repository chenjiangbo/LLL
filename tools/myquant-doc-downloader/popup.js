const status = document.getElementById('status');
const start = document.getElementById('start');
const clear = document.getElementById('clear');

function show(message) { status.textContent = message; }

async function activeTab() {
  const tabs = await chrome.tabs.query({active: true, currentWindow: true});
  return tabs[0];
}

start.addEventListener('click', async () => {
  start.disabled = true;
  try {
    const tab = await activeTab();
    if (!tab?.id || !/^https:\/\/(www\.)?myquant\.cn\/docs2\//.test(tab.url || '')) {
      throw new Error('当前页面不是 MyQuant docs2 文档页。');
    }
    show('正在扫描，请保持文档标签页打开…');
    const result = await chrome.tabs.sendMessage(tab.id, {type: 'START_SYNC'});
    show(result.message);
  } catch (error) {
    show(`失败：${error.message}\n如果刚安装扩展，请刷新 MyQuant 文档页后重试。`);
  } finally { start.disabled = false; }
});

clear.addEventListener('click', async () => {
  await chrome.storage.local.remove('myquantManifest');
  show('已清除增量记录；已下载文件不会被删除。');
});
