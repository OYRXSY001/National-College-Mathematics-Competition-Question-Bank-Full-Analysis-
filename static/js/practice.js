// 练习页快捷键：1 答对 / 2 答错 / 3 跳过；已作答时 → 或回车 下一题
(function () {
  "use strict";

  function isTyping(el) {
    return el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
  }

  document.addEventListener("keydown", function (event) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (isTyping(event.target)) return;

    var verdictMap = { "1": "correct", "2": "wrong", "3": "skip" };
    var result = verdictMap[event.key];
    if (result) {
      var btn = document.querySelector('button[name="result"][value="' + result + '"]');
      if (btn) {
        event.preventDefault();
        btn.click();
        return;
      }
    }
    if (event.key === "Enter" || event.key === "ArrowRight") {
      // 只认有 id="next-question" 的“下一题”链接，避免误触“从头开始”
      var nextLink = document.getElementById("next-question");
      if (nextLink && document.querySelector('button[name="result"]') === null) {
        event.preventDefault();
        nextLink.click();
      }
    }
  });
})();