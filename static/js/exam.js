// 模拟考试倒计时：以服务端下发的剩余秒数为基准推算绝对截止时刻，
// 刷新页面不会重置计时；到时自动交卷（服务端同样兜底限时）。
(function () {
  "use strict";

  var el = document.getElementById("exam-countdown");
  if (!el) return;

  var remaining = parseInt(el.getAttribute("data-seconds") || "0", 10);
  var deadline = Date.now() + remaining * 1000;
  var submitForm = document.querySelector('form[action*="submit"]');
  var submitted = false; // 手动/自动只允许真正提交一次

  function render(now) {
    var left = Math.max(0, Math.ceil((deadline - now) / 1000));
    var m = Math.floor(left / 60);
    var s = left % 60;
    var mm = m < 10 ? "0" + m : "" + m; // 120 分钟不能被截成两位
    el.textContent = mm + ":" + ("0" + s).slice(-2);
    if (left <= 60) el.classList.add("text-danger");
    return left;
  }

  function tick() {
    var left = render(Date.now());
    if (left <= 0) {
      clearInterval(timer);
      if (submitForm && !submitted) {
        submitted = true;
        submitForm.submit();
      }
    }
  }

  render(Date.now());
  var timer = setInterval(tick, 1000);

  // 手动交卷：先确认，再防与到时自动交卷/连点竞态
  // （自动交卷走原生 .submit()，不触发 submit 事件，无需确认）
  if (submitForm) {
    submitForm.addEventListener("submit", function (event) {
      if (submitted) {
        event.preventDefault();
        return;
      }
      if (!window.confirm("确定交卷吗？交卷后不能再更改自评。")) {
        event.preventDefault();
        return;
      }
      submitted = true;
      var btn = submitForm.querySelector('button[type="submit"]');
      if (btn) btn.disabled = true;
    });
  }
})();
