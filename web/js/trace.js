window.NALLY = window.NALLY || {};

NALLY.showTrace = function(runId) {
  var modal = document.createElement('div');
  modal.className = 'trace-modal';
  modal.innerHTML = '<div class="trace-modal-inner"><div class="trace-header"><h3>Execution Trace</h3><span class="trace-run-id">' + runId + '</span><button class="trace-close" id="traceCloseBtn">&times;</button></div><div class="trace-body" id="traceBody"><div class="trace-loading">Loading trace...</div></div></div>';
  document.body.appendChild(modal);
  modal.querySelector('#traceCloseBtn').onclick = function() { modal.remove(); };
  modal.addEventListener('click', function(e) { if (e.target === modal) modal.remove(); });

  fetch('/api/trace/' + encodeURIComponent(runId), { headers: { 'Authorization': 'Bearer ' + NALLY.state.token } })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var body = modal.querySelector('#traceBody');
      if (!data || !data.spans || data.spans.length === 0) {
        body.innerHTML = '<div class="trace-empty">No trace data recorded for this run.</div>';
        return;
      }
      body.innerHTML = '';
      var tree = NALLY.buildTraceTree(data.spans);
      tree.forEach(function(span) { body.appendChild(NALLY.renderTraceSpan(span)); });
    })
    .catch(function(err) {
      modal.querySelector('#traceBody').innerHTML = '<div class="trace-error">Failed to load trace: ' + err.message + '</div>';
    });
};

NALLY.buildTraceTree = function(spans) {
  var byParent = {};
  spans.forEach(function(s) {
    var pid = s.parent_span_id || '__root__';
    if (!byParent[pid]) byParent[pid] = [];
    byParent[pid].push(s);
  });
  function getChildren(parentId) {
    var children = byParent[parentId] || [];
    children.sort(function(a, b) { return (a.started_at || '').localeCompare(b.started_at || ''); });
    return children.map(function(c) {
      c._children = getChildren(c.span_id);
      return c;
    });
  }
  return getChildren('__root__');
};

NALLY.renderTraceSpan = function(span) {
  var wrap = document.createElement('div');
  wrap.className = 'trace-span';

  var header = document.createElement('div');
  header.className = 'trace-span-header';
  if (span._children && span._children.length) header.classList.add('has-children');

  var statusColor = { ok: '#34D399', error: '#EF4444', running: '#FBBF24' }[span.status] || '#6B7280';
  var chevron = span._children && span._children.length ? '<span class="trace-chevron">\u25B8</span>' : '';
  var duration = span.duration_ms != null ? span.duration_ms + 'ms' : '\u2026';

  header.innerHTML = chevron + '<span class="trace-dot" style="background:' + statusColor + '"></span>' +
    '<span class="trace-name">' + (span.name || 'unknown') + '</span>' +
    '<span class="trace-duration">' + duration + '</span>';

  if (span._children && span._children.length) {
    var collapsed = false;
    header.onclick = function(e) {
      collapsed = !collapsed;
      var chevEl = header.querySelector('.trace-chevron');
      if (chevEl) chevEl.textContent = collapsed ? '\u25BE' : '\u25B8';
      var childrenEl = wrap.querySelector('.trace-children');
      if (childrenEl) childrenEl.style.display = collapsed ? 'none' : '';
      e.stopPropagation();
    };
  }

  wrap.appendChild(header);

  if (span._children && span._children.length) {
    var childrenEl = document.createElement('div');
    childrenEl.className = 'trace-children';
    span._children.forEach(function(child) { childrenEl.appendChild(NALLY.renderTraceSpan(child)); });
    wrap.appendChild(childrenEl);
  }

  if (span.input_json || span.output_json || span.error) {
    var detail = document.createElement('div');
    detail.className = 'trace-detail';
    detail.style.display = 'none';
    var html = '';
    if (span.input_json) { try { html += '<div class="trace-section"><b>Input</b><pre>' + JSON.stringify(JSON.parse(span.input_json), null, 2) + '</pre></div>'; } catch(e) { html += '<div class="trace-section"><b>Input</b><pre>' + span.input_json + '</pre></div>'; } }
    if (span.output_json) { try { html += '<div class="trace-section"><b>Output</b><pre>' + JSON.stringify(JSON.parse(span.output_json), null, 2) + '</pre></div>'; } catch(e) { html += '<div class="trace-section"><b>Output</b><pre>' + span.output_json + '</pre></div>'; } }
    if (span.error) { html += '<div class="trace-section trace-error-section"><b>Error</b><pre>' + span.error + '</pre></div>'; }
    detail.innerHTML = html;
    wrap.appendChild(detail);

    header.style.cursor = 'pointer';
    header.onclick = function(e) {
      detail.style.display = detail.style.display === 'none' ? '' : 'none';
      e.stopPropagation();
    };
  }

  return wrap;
};
