chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== 'SAVE_DOCUMENT') return;
  (async () => {
    const safePath = message.path.replace(/^\/+|\.\.+/g, '_');
    const dataUrl = `data:text/markdown;charset=utf-8,${encodeURIComponent(message.content)}`;
    await chrome.downloads.download({
      url: dataUrl,
      filename: `myquant-docs/${safePath}`,
      saveAs: false,
      conflictAction: 'overwrite'
    });
    sendResponse({ok: true});
  })().catch(error => sendResponse({ok: false, error: error.message}));
  return true;
});
