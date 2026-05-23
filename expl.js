const lines = [];

[...document.querySelectorAll('.pv2h-review-q')].forEach(q => {
  const correct = q.querySelector('.eq-option.answered.correct .eq-opt-text')
    ?.innerText?.trim();

  const wrong = q.querySelector('.eq-option.answered.incorrect .eq-opt-text')
    ?.innerText?.trim();

  const correctExplanation = q.querySelector('.pv2-correct-explanation')
    ?.innerText?.trim();

  const wrongExplanation = q.querySelector('.pv2-wrong-explanation')
    ?.innerText?.trim();

  if (correct) {
    const text = `${correct}\nCORRECT: ${correctExplanation}\n`;
    console.log(text);
    lines.push(text);
  }

  if (wrong) {
    const text = `${wrong}\nWRONG: ${wrongExplanation}\n`;
    console.log(text);
    lines.push(text);
  }
});

const blob = new Blob([lines.join('\n')], {
  type: 'text/plain'
});

const a = document.createElement('a');
a.href = URL.createObjectURL(blob);
a.download = 'review-results.md';

document.body.appendChild(a);
a.click();
a.remove();

URL.revokeObjectURL(a.href);
