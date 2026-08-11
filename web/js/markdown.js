window.NALLY = window.NALLY || {};

NALLY.renderMd = function(text) {
  if (!text || typeof text !== 'string') {
    console.warn('[renderMd] non-string input:', typeof text, text);
    return '';
  }
  var html = '';
  try {
    if (typeof marked !== 'undefined') {
      html = marked.parse(text);
    } else {
      html = text
        .replace(/```(\w*)\n([\s\S]*?)```/g, function(m, lang, code) {
          var cls = lang ? ' class="language-' + lang + '"' : '';
          return '<pre><code' + cls + '>' + code.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</code></pre>';
        })
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/~~(.+?)~~/g, '<del>$1</del>')
        .replace(/^\s*[-*]\s+\[[ x]\]\s+(.+)/gm, '<li><input type="checkbox" disabled> $1</li>')
        .replace(/^\s*[-*]\s+(.+)/gm, '<li>$1</li>')
        .replace(/^\s*\d+\.\s+(.+)/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>)/gs, function(m) { return '<ul>' + m + '</ul>'; })
        .replace(/^>\s+(.+)/gm, '<blockquote>$1</blockquote>')
        .replace(/^---$/gm, '<hr>')
        .replace(/\n/g, '<br>');
      html = html.replace(/^(\|.+\|)\n(\|[-| :]+\|)\n((?:\|.+\|\n?)+)/gm, function(m, hdr, sep, body) {
        var ths = hdr.split('|').filter(function(c) { return c.trim(); }).map(function(c) { return '<th>' + c.trim() + '</th>'; }).join('');
        var rows = body.trim().split('\n').map(function(row) {
          var tds = row.split('|').filter(function(c) { return c.trim(); }).map(function(c) { return '<td>' + c.trim() + '</td>'; }).join('');
          return '<tr>' + tds + '</tr>';
        }).join('');
        return '<div class="table-wrap"><table><thead><tr>' + ths + '</tr></thead><tbody>' + rows + '</tbody></table></div>';
      });
    }
  } catch(e) {
    console.error('[renderMd] parse error:', e);
    html = text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
  }
  if (typeof DOMPurify !== 'undefined') {
    return DOMPurify.sanitize(html, { ADD_TAGS: ['input'], ADD_ATTR: ['type', 'disabled', 'checked'] });
  }
  return html;
};

NALLY.initMarked = function() {
  if (typeof marked !== 'undefined') {
    var origTable = new marked.Renderer();
    origTable.table = function() {
      var h = arguments[0], b = arguments[1];
      if (h && typeof h === 'object') { b = h.body; h = h.header; }
      return '<div class="table-wrap"><table>' + (h || '') + (b || '') + '</table></div>';
    };
    marked.setOptions({
      breaks: true,
      gfm: true,
      renderer: origTable,
      highlight: function(code, lang) {
        if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
          try { return hljs.highlight(code, { language: lang }).value; } catch(e) {}
        }
        if (typeof hljs !== 'undefined') {
          try { return hljs.highlightAuto(code).value; } catch(e) {}
        }
        return code;
      }
    });
  }
};

NALLY.waitForMarked = function(cb, attempts) {
  attempts = attempts || 0;
  if (typeof marked !== 'undefined') {
    cb();
  } else if (attempts < 10) {
    setTimeout(function() { NALLY.waitForMarked(cb, attempts + 1); }, 50);
  } else {
    console.warn('[waitForMarked] marked.js failed to load, proceeding with fallback');
    cb();
  }
};
