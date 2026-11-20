const byId = (id) => document.getElementById(id);
let sequence = 0;
async function send(path, method = 'GET', body) {
  const start = performance.now();
  byId('request-label').textContent = `${method} ${path}`;
  byId('status').textContent = '요청 중…';
  try {
    const response = await fetch(path, {
      method, body, cache: 'no-store',
      headers: body === undefined ? {} : {'Content-Type': 'text/plain; charset=utf-8'},
    });
    const text = await response.text();
    const elapsed = `${(performance.now() - start).toFixed(1)} ms`;
    let data;
    try { data = JSON.parse(text); } catch { data = null; }
    byId('request-label').textContent = `${method} ${path}`;
    byId('status').textContent = String(response.status);
    byId('status').className = response.ok ? '' : 'error';
    byId('elapsed').textContent = elapsed;
    byId('type').textContent = response.headers.get('Content-Type') || '—';
    byId('length').textContent = response.headers.get('Content-Length') || '—';
    byId('body').textContent = data ? JSON.stringify(data, null, 2) : text || '(본문 없음)';
    byId('empty')?.remove();
    const row = document.createElement('tr');
    for (const value of [++sequence, `${method} ${path}`, response.status, elapsed, data?.backend || '로컬 / 해당 없음']) {
      const cell = document.createElement('td');
      cell.textContent = String(value);
      row.append(cell);
    }
    byId('history').prepend(row);
    while (byId('history').children.length > 20) byId('history').lastElementChild.remove();
  } catch (error) {
    byId('status').textContent = '연결 실패';
    byId('status').className = 'error';
    byId('body').textContent = error.message;
  }
}
document.querySelectorAll('[data-path]').forEach((button) => {
  button.addEventListener('click', () => send(button.dataset.path));
});
byId('echo-form').addEventListener('submit', (event) => {
  event.preventDefault();
  send('/api/echo', 'POST', byId('message').value);
});
