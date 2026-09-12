// Keep the actual HTTP result visible when testing endpoints in Swagger.
const style = document.createElement('style');
style.textContent = `
  .swagger-ui textarea.body-param__text { min-height: 120px; height: 120px; }
  body:not(.show-curl) .swagger-ui .curl-command { display: none; }
  .docs-help { margin: 16px auto; padding: 12px 20px; max-width: 1420px;
    font: 14px/1.5 system-ui, sans-serif; background: #eef8f3; border: 1px solid #b7ddca; }
  .docs-help label { display: inline-block; margin-top: 8px; }
  .swagger-ui .live-responses-table { scroll-margin-top: 16px; }
`;
document.head.append(style);
const help = document.createElement('div');
help.className = 'docs-help';
help.innerHTML = `Sign in with <strong>POST /api/v1/auth/login</strong>, then test an endpoint.
  Execute sends the request; the <strong>Server response</strong> shows the actual status and JSON.
  <br><label><input type="checkbox"> Show cURL command previews</label>`;
document.body.prepend(help);
help.querySelector('input').addEventListener('change', event => {
  document.body.classList.toggle('show-curl', event.target.checked);
});

const renderedResponses = new WeakMap();
const observer = new MutationObserver(() => {
  for (const table of document.querySelectorAll('.live-responses-table')) {
    const text = table.textContent;
    if (!table.querySelector('.response-col_status') || renderedResponses.get(table) === text) continue;
    renderedResponses.set(table, text);
    table.scrollIntoView({ block: 'start', behavior: 'instant' });
  }
});
observer.observe(document.getElementById('swagger-ui'), { childList: true, subtree: true, characterData: true });
