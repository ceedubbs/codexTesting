let transactions = [];
let index = 0;
const results = [];

fetch('transactions.json')
  .then(r => r.json())
  .then(data => {
    transactions = data;
    showNext();
  });

function showNext() {
  const card = document.getElementById('transaction-card');
  const btns = document.getElementById('buttons');
  if (index >= transactions.length) {
    card.classList.add('hidden');
    btns.classList.add('hidden');
    document.getElementById('result').textContent = JSON.stringify(results, null, 2);
    return;
  }
  const t = transactions[index];
  document.getElementById('t-date').textContent = t.date;
  document.getElementById('t-desc').textContent = t.description;
  document.getElementById('t-amount').textContent = '$' + t.amount;
  card.classList.remove('hidden');
  btns.classList.remove('hidden');
}

function choose(cat) {
  const t = transactions[index];
  results.push({...t, category: cat});
  index += 1;
  showNext();
}

document.querySelectorAll('#buttons button').forEach(btn => {
  btn.addEventListener('click', () => choose(btn.dataset.cat));
});

window.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft') choose('Food');
  if (e.key === 'ArrowRight') choose('Education');
  if (e.key === 'ArrowUp') choose('Entertainment');
  if (e.key === 'ArrowDown') choose('Other');
});
