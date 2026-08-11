window.NALLY = window.NALLY || {};

NALLY.toolIcon = function(name) {
  var icons = {
    ReadFile: 'file-text', FileOps: 'folder-cog', RunCommand: 'terminal',
    RunCode: 'play', CodeAnalysis: 'scan', SystemHealth: 'activity',
    WriteFile: 'file-plus', SearchFiles: 'search', WebSearch: 'globe',
    MemorySearch: 'brain', MemoryStore: 'database',
  };
  return icons[name] || 'zap';
};

NALLY.autoSummary = function(name, args) {
  if (!args) return 'Running ' + name;
  if (name === 'RunCommand' && args.command) {
    var cmd = args.command.trim();
    if (cmd.startsWith('ls') || cmd.startsWith('dir')) return 'Listing directory contents';
    if (cmd.startsWith('cd ')) return 'Changing directory to ' + cmd.slice(3);
    if (cmd.startsWith('cat ') || cmd.startsWith('type ')) return 'Reading file ' + cmd.split(' ').pop();
    if (cmd.startsWith('mkdir')) return 'Creating directory ' + cmd.split(' ').pop();
    if (cmd.startsWith('rm ') || cmd.startsWith('del ')) return 'Deleting ' + cmd.split(' ').pop();
    if (cmd.startsWith('cp ') || cmd.startsWith('copy ')) return 'Copying files';
    if (cmd.startsWith('mv ') || cmd.startsWith('ren ') || cmd.startsWith('rename ')) return 'Renaming or moving files';
    if (cmd.startsWith('git ')) return 'Running git command';
    if (cmd.startsWith('npm ') || cmd.startsWith('yarn ') || cmd.startsWith('pip ')) return 'Running package manager';
    if (cmd.includes('curl') || cmd.includes('wget')) return 'Fetching remote content';
    if (cmd.includes('grep') || cmd.includes('find') || cmd.includes('search')) return 'Searching for files or text';
    if (cmd.includes('test') || cmd.includes('pytest') || cmd.includes('jest')) return 'Running tests';
    if (cmd.includes('build') || cmd.includes('compile')) return 'Building project';
    if (cmd.includes('install')) return 'Installing dependencies';
    if (cmd.includes('start') || cmd.includes('run') || cmd.includes('serve')) return 'Starting a service';
    if (cmd.includes('stop') || cmd.includes('kill')) return 'Stopping a process';
    if (cmd.includes('deploy')) return 'Deploying application';
    if (cmd.length > 60) cmd = cmd.substring(0, 57) + '...';
    return 'Running: ' + cmd;
  }
  if (name === 'ReadFile' && args.path) {
    var parts = args.path.replace(/\\/g, '/').split('/');
    return 'Reading ' + (parts[parts.length - 1] || args.path);
  }
  if (name === 'FileOps') {
    if (args.action === 'list') return 'Listing files in ' + (args.path || 'directory');
    if (args.action === 'write') return 'Writing to ' + (args.path || 'file');
    if (args.action === 'mkdir') return 'Creating folder ' + (args.path || 'directory');
    return 'Performing file operation';
  }
  if (name === 'SearchFiles' && args.pattern) return 'Searching for "' + args.pattern + '"';
  if (name === 'WebSearch' && args.query) return 'Searching the web for "' + args.query + '"';
  if (name === 'RunCode') return 'Executing code';
  if (name === 'CodeAnalysis') return 'Analyzing ' + (args.path || 'code');
  if (name === 'MemorySearch' && args.query) return 'Searching memory for "' + args.query + '"';
  if (name === 'MemoryStore') return 'Saving to memory';
  if (args.path) return 'Working with ' + args.path;
  if (args.query) return 'Processing "' + args.query + '"';
  if (args.command) return 'Running command';
  return 'Running ' + name;
};

NALLY.addToolCard = function(name, args, id) {
  var d = NALLY.dom;
  var s = NALLY.state;

  if (name === 'generate_image') {
    var skelEl = document.createElement('div');
    skelEl.className = 'img-skel';
    d.chatMessages.appendChild(skelEl);
    d.scrollToBottom();
    s.toolCards[id] = {
      card: null, statusEl: null, name: name,
      resultSection: null, resultCode: null,
      skelEl: skelEl
    };
    return s.toolCards[id];
  }

  var card = document.createElement('div');
  card.className = 'tool-card running';

  var header = document.createElement('div');
  header.className = 'tool-card-header';

  var label = document.createElement('div');
  label.className = 'tool-card-label';

  var summary = document.createElement('div');
  summary.className = 'tool-card-summary';
  summary.textContent = NALLY.autoSummary(name, args);

  var nameEl = document.createElement('div');
  nameEl.className = 'tool-card-name';
  nameEl.textContent = name;

  label.appendChild(summary);
  label.appendChild(nameEl);

  var statusEl = document.createElement('div');
  statusEl.className = 'tool-card-status';
  statusEl.innerHTML = '<span class="tool-card-spinner"></span>';

  var chevron = document.createElement('div');
  chevron.className = 'tool-card-chevron';
  chevron.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';

  header.appendChild(label);
  header.appendChild(statusEl);
  header.appendChild(chevron);

  header.addEventListener('click', function() {
    card.classList.toggle('expanded');
  });

  card.appendChild(header);

  var body = document.createElement('div');
  body.className = 'tool-card-body';
  var inner = document.createElement('div');
  inner.className = 'tool-card-body-inner';

  var detail = document.createElement('div');
  detail.className = 'tool-card-detail';

  var inputLabel = document.createElement('div');
  inputLabel.className = 'tool-card-zone-label';
  inputLabel.textContent = 'Input';
  var inputCode = document.createElement('div');
  inputCode.className = 'tool-card-code';
  inputCode.textContent = args ? JSON.stringify(args, null, 2) : 'No input';
  detail.appendChild(inputLabel);
  detail.appendChild(inputCode);

  var resultSection = document.createElement('div');
  resultSection.className = 'tool-card-result-section';
  resultSection.style.display = 'none';
  var resultLabel = document.createElement('div');
  resultLabel.className = 'tool-card-zone-label';
  resultLabel.textContent = 'Result';
  var resultCode = document.createElement('div');
  resultCode.className = 'tool-card-code';
  resultSection.appendChild(resultLabel);
  resultSection.appendChild(resultCode);
  detail.appendChild(resultSection);

  inner.appendChild(detail);
  body.appendChild(inner);
  card.appendChild(body);

  d.chatMessages.appendChild(card);
  d.scrollToBottom();
  lucide.createIcons();

  s.toolCards[id] = {
    card: card, statusEl: statusEl, name: name,
    resultSection: resultSection, resultCode: resultCode,
    skelEl: null
  };
  return s.toolCards[id];
};

NALLY.updateToolCard = function(id, resultText, isError) {
  var tc = NALLY.state.toolCards[id];
  if (!tc) return;
  var d = NALLY.dom;

  if (tc.name === 'generate_image' && tc.skelEl) {
    if (isError) {
      tc.skelEl.style.opacity = '0.3';
      delete NALLY.state.toolCards[id];
      return;
    }
    if (resultText) {
      var imgMatch = resultText.match(/IMAGE_FILE:(.+)/);
      if (imgMatch) {
        var imgPath = imgMatch[1].trim();
        var imgFilename = imgPath.split(/[/\\]/).pop();
        var imgUrl = '/generated/' + imgFilename;
        var img = document.createElement('img');
        img.src = imgUrl;
        img.style.cssText = 'cursor:pointer;';
        img.addEventListener('click', function() { window.open(imgUrl, '_blank'); });
        tc.skelEl.appendChild(img);
        img.onload = function() {
          tc.skelEl.classList.add('loaded');
          d.scrollToBottom();
        };
        img.onerror = function() {
          tc.skelEl.style.opacity = '0.3';
        };
      } else {
        tc.skelEl.style.opacity = '0.3';
      }
    }
    delete NALLY.state.toolCards[id];
    return;
  }

  tc.card.classList.remove('running');
  tc.card.classList.add(isError ? 'error' : 'success');

  tc.statusEl.innerHTML = isError
    ? '<span class="tool-card-check"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></span>'
    : '<span class="tool-card-check"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span>';

  if (resultText) {
    var truncated = resultText.substring(0, 5000);
    var imgMatch = truncated.match(/IMAGE_FILE:(.+)/);
    if (imgMatch) {
      var imgPath = imgMatch[1].trim();
      var imgFilename = imgPath.split(/[/\\]/).pop();
      var imgUrl = '/generated/' + imgFilename;
      var metaText = truncated.replace(/IMAGE_FILE:.+/, '').trim();

      tc.resultCode.innerHTML = '';
      if (metaText) {
        var metaEl = document.createElement('div');
        metaEl.className = 'tool-card-code';
        metaEl.textContent = metaText;
        tc.resultCode.appendChild(metaEl);
      }

      if (tc.skelEl) {
        var img = document.createElement('img');
        img.src = imgUrl;
        img.style.cssText = 'cursor:pointer;';
        img.addEventListener('click', function() { window.open(imgUrl, '_blank'); });
        tc.skelEl.appendChild(img);
        img.onload = function() {
          tc.skelEl.classList.add('loaded');
          d.scrollToBottom();
        };
        img.onerror = function() {
          tc.skelEl.classList.remove('loaded');
          var label = tc.skelEl.querySelector('.img-skel-label');
          if (label) label.textContent = 'Failed to load';
        };
      } else {
        var img = document.createElement('img');
        img.src = imgUrl;
        img.style.cssText = 'max-width:100%;border-radius:8px;margin-top:8px;cursor:pointer;';
        img.onload = function() { d.scrollToBottom(); };
        img.onerror = function() { img.alt = 'Image failed to load: ' + imgFilename; };
        img.addEventListener('click', function() { window.open(imgUrl, '_blank'); });
        tc.resultCode.appendChild(img);
      }
    } else {
      tc.resultCode.textContent = truncated;
    }

    tc.resultSection.style.display = 'block';
  }

  d.scrollToBottom();
  delete NALLY.state.toolCards[id];
};

NALLY.buildApprovalCard = function(evt) {
  var d = NALLY.dom;
  NALLY.removeTyping();

  var approveCard = document.createElement('div');
  approveCard.className = 'tool-card pending expanded';

  var header = document.createElement('div');
  header.className = 'tool-card-header';
  header.style.cursor = 'default';

  var label = document.createElement('div');
  label.className = 'tool-card-label';

  var summary = document.createElement('div');
  summary.className = 'tool-card-summary';
  summary.textContent = NALLY.autoSummary(evt.name, evt.args);

  var nameEl = document.createElement('div');
  nameEl.className = 'tool-card-name';
  nameEl.textContent = evt.name || 'tool';

  label.appendChild(summary);
  label.appendChild(nameEl);

  var statusEl = document.createElement('div');
  statusEl.className = 'tool-card-status';
  statusEl.innerHTML = '<span style="color:#FBBF24"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/></svg></span>';

  header.appendChild(label);
  header.appendChild(statusEl);
  approveCard.appendChild(header);

  var body = document.createElement('div');
  body.className = 'tool-card-body';
  var inner = document.createElement('div');
  inner.className = 'tool-card-body-inner';

  var detail = document.createElement('div');
  detail.className = 'tool-card-detail';

  var inputLabel = document.createElement('div');
  inputLabel.className = 'tool-card-zone-label';
  inputLabel.textContent = 'Input';
  var inputCode = document.createElement('div');
  inputCode.className = 'tool-card-code';
  inputCode.textContent = evt.args ? JSON.stringify(evt.args, null, 2) : 'No input';
  detail.appendChild(inputLabel);
  detail.appendChild(inputCode);

  if (evt.diff && evt.file_path) NALLY.showDiff(evt.diff, evt.file_path);

  var btnWrap = document.createElement('div');
  btnWrap.className = 'tool-card-approve-btns';
  btnWrap.style.borderTop = '1px solid rgba(255,255,255,0.05)';

  var approveBtn = document.createElement('button');
  approveBtn.className = 'tool-approve-yes';
  approveBtn.textContent = 'Approve';

  var denyBtn = document.createElement('button');
  denyBtn.className = 'tool-approve-no';
  denyBtn.textContent = 'Deny';

  var tcId = evt.tool_call_id;
  approveBtn.addEventListener('click', function() { NALLY.approveTool(tcId, true); approveCard.remove(); });
  denyBtn.addEventListener('click', function() { NALLY.approveTool(tcId, false); approveCard.remove(); });

  btnWrap.appendChild(approveBtn);
  btnWrap.appendChild(denyBtn);
  detail.appendChild(btnWrap);

  inner.appendChild(detail);
  body.appendChild(inner);
  approveCard.appendChild(body);

  d.chatMessages.appendChild(approveCard);
  lucide.createIcons();
  d.scrollToBottom();
};

NALLY.approveTool = function(toolCallId, approved) {
  if (NALLY.state.useWebSocket && NALLY.state.ws && NALLY.state.ws.connected) {
    NALLY.state.ws.approve(toolCallId, approved);
    return;
  }
  fetch(NALLY.API + '/api/approve', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + NALLY.state.token,
    },
    body: JSON.stringify({ tool_call_id: toolCallId, approved: approved }),
  });
};
