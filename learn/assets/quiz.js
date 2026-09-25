/* ===========================================================================
   quiz.js: reusable multiple-choice drill with immediate feedback.
   Shared component. Link it, do not copy it.

       <script src="../assets/quiz.js" defer></script>

   Markup contract:

     <div class="quiz" data-quiz>
       <ol>
         <li class="q" data-answer="2">
           <p class="q-stem">Which context runs this expression?</p>
           <ul class="q-opts">
             <li><button class="opt">First option text</button></li>
             <li><button class="opt">Second option text</button></li>
           </ul>
           <p class="q-feedback" hidden>Shown once an option is chosen.</p>
         </li>
       </ol>
       <p class="quiz-score" data-score></p>
     </div>

   data-answer is the 1-based index of the correct option.
   Feedback is revealed on the first click and the question then locks, so the
   drill stays a retrieval test rather than a guess-until-green game.
   =========================================================================== */

(function () {
  "use strict";

  function initQuiz(quiz) {
    var questions = Array.prototype.slice.call(quiz.querySelectorAll(".q"));
    var scoreEl = quiz.querySelector("[data-score]");
    var answered = 0;
    var correct = 0;

    function render() {
      if (!scoreEl) return;
      if (answered === 0) {
        scoreEl.textContent =
          questions.length + " questions. Answer from memory, not by elimination.";
        return;
      }
      scoreEl.textContent = correct + " of " + answered + " correct.";
      if (answered === questions.length) {
        scoreEl.classList.add("is-done");
        scoreEl.textContent =
          "Done. " + correct + " of " + questions.length + " correct. " +
          (correct === questions.length
            ? "Tell your teacher, and ask for the next lesson."
            : "Ask your teacher about the ones you missed before moving on.");
      }
    }

    questions.forEach(function (q) {
      var answerIndex = parseInt(q.getAttribute("data-answer"), 10);
      var options = Array.prototype.slice.call(q.querySelectorAll(".opt"));
      var feedback = q.querySelector(".q-feedback");

      options.forEach(function (btn, i) {
        btn.setAttribute("type", "button");
        btn.addEventListener("click", function () {
          if (q.dataset.done === "true") return;
          q.dataset.done = "true";

          var isRight = i + 1 === answerIndex;
          answered += 1;
          if (isRight) correct += 1;

          options.forEach(function (other, j) {
            other.disabled = true;
            if (j + 1 === answerIndex) other.classList.add("is-right");
          });
          if (!isRight) btn.classList.add("is-wrong");

          if (feedback) feedback.hidden = false;
          render();
        });
      });
    });

    render();
  }

  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  ready(function () {
    Array.prototype.slice
      .call(document.querySelectorAll("[data-quiz]"))
      .forEach(initQuiz);
  });
})();
