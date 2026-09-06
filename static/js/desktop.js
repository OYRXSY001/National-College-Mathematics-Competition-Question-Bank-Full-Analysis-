// 桌面版「我的」页按钮确认（CSP 下不允许内联 onsubmit）
document.addEventListener("DOMContentLoaded", function () {
  var quitForm = document.querySelector('form[action*="desktop-quit"]');
  if (quitForm) {
    quitForm.addEventListener("submit", function (event) {
      if (!window.confirm("确定退出桌面版吗？学习数据已保存在本机，下次打开可继续。")) {
        event.preventDefault();
      }
    });
  }
});
