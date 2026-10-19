import { shell, countTo, cssTime } from './ui.js';
shell('home');
// The journey card's result counts down once its fourth step has arrived (home.css --at).
const step = document.querySelector('.journey-step:nth-child(4)');
const result = document.querySelector('.result-number');
countTo(result?.querySelector('em'), Number(result?.querySelector('em')?.textContent), {
  from: Number(result?.firstChild?.textContent), delay: step ? cssTime('--at', step) + 300 : 0,
});
