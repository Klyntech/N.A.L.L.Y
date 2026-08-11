window.NALLY = window.NALLY || {};

NALLY.showDiff = function(diffText, filePath) {
  if (window.innerWidth <= 640) return;

  NALLY.dom.diffFile.textContent = filePath || '';
  NALLY.dom.diffBody.innerHTML = '';

  var lines = diffText.split('\n');
  var adds = 0, dels = 0;

  lines.forEach(function(line) {
    var span = document.createElement('span');
    span.className = 'diff-line';
    if (line.startsWith('@@')) {
      span.classList.add('diff-line-hdr');
    } else if (line.startsWith('+')) {
      span.classList.add('diff-line-add');
      adds++;
    } else if (line.startsWith('-')) {
      span.classList.add('diff-line-del');
      dels++;
    } else if (line.startsWith('---') || line.startsWith('+++')) {
      span.classList.add('diff-line-hdr');
    } else {
      span.classList.add('diff-line-ctx');
    }
    span.textContent = line + '\n';
    NALLY.dom.diffBody.appendChild(span);
  });

  NALLY.dom.diffStats.innerHTML = '<span class="diff-stat-add">+' + adds + '</span><span class="diff-stat-del">-' + dels + '</span>';
  NALLY.dom.diffPanel.classList.add('open');
};

NALLY.closeDiff = function() {
  NALLY.dom.diffPanel.classList.remove('open');
};

NALLY.minimizeDiff = NALLY.closeDiff;
