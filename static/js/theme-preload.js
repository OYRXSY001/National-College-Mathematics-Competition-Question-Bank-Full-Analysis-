// 主题预加载（防止页面闪烁）：必须在 <head> 中同步执行，不能加 defer
(function () {
  try {
    var t = localStorage.getItem('holo-theme') || 'auto';
    var e = t === 'auto'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : t;
    document.documentElement.setAttribute('data-theme', e);
  } catch (_) {}
})();
