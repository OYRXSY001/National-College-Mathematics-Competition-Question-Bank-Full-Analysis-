// 打印页按钮（CSP 下不允许内联 onclick）
document.addEventListener("DOMContentLoaded", function () {
  var btn = document.querySelector("[data-print]");
  if (btn) {
    btn.addEventListener("click", function () {
      window.print();
    });
  }
});
