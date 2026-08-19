window.NALLY = window.NALLY || {};

NALLY.SERVICES = [
  { id:'github',    name:'GitHub',        auth:'oauth',  desc:'Repos, issues, PRs', mcp:true },
  { id:'notion',    name:'Notion',        auth:'oauth',  desc:'Notes & databases', lightIcon:true, mcp:true },
  { id:'gmail',     name:'Gmail',         auth:'oauth',  desc:'Email management', mcp:true },
  { id:'gdrive',    name:'Google Drive',  auth:'oauth',  desc:'File storage', mcp:true },
  { id:'gcal',      name:'Calendar',      auth:'oauth',  desc:'Scheduling', mcp:true, backendId:'gcalendar' },
  { id:'telegram',  name:'Telegram',      auth:'token',  desc:'Chat access', tokenLabel:'Bot Token', mcp:true },
  { id:'filesystem',name:'Filesystem',    auth:'none',   desc:'Local file access', mcp:false },
  { id:'fetch',     name:'Fetch',         auth:'none',   desc:'Web content fetching', mcp:true },
  { id:'higgsfield',name:'Higgsfield',    auth:'oauth',  desc:'AI video generation & editing', mcp:true },
  { id:'playwright',name:'Playwright',    auth:'none',   desc:'Browser automation & scraping', mcp:true },
  { id:'context7',  name:'Context7',      auth:'none',   desc:'Up-to-date library docs', mcp:true },
  { id:'meta',      name:'Meta Suite',    auth:'api_key',desc:'Facebook, Instagram, Threads, Ads', mcp:true },
  { id:'slack',     name:'Slack',         auth:'oauth',  desc:'Team messaging', mcp:false },
  { id:'discord',   name:'Discord',       auth:'token',  desc:'Community chat', mcp:false },
  { id:'jira',      name:'Jira',          auth:'oauth',  desc:'Project management', mcp:false },
  { id:'linear',    name:'Linear',        auth:'oauth',  desc:'Issue tracking', mcp:false },
  { id:'brave',     name:'Brave Search',  auth:'api_key',desc:'Web search', mcp:false },
  { id:'twitter',   name:'X / Twitter',   auth:'oauth',  desc:'Social posts', mcp:false },
  { id:'spotify',   name:'Spotify',       auth:'oauth',  desc:'Music & playlists', mcp:false },
  { id:'youtube',   name:'YouTube',       auth:'oauth',  desc:'Video & transcripts', mcp:false },
  { id:'dropbox',   name:'Dropbox',       auth:'oauth',  desc:'Cloud storage', mcp:false },
];

NALLY.SVC_COLORS = {
  github:'#6e5494', gmail:'#EA4335', slack:'#4A154B', telegram:'#26A5E4',
  gdrive:'#4285F4', gcal:'#4285F4', notion:'#000', linear:'#5E6AD2',
  discord:'#5865F2', jira:'#0052CC', brave:'#FB542B',
  higgsfield:'#FF6B35', twitter:'#000', spotify:'#1DB954', youtube:'#FF0000',
  dropbox:'#0061FF', filesystem:'#607D8B', fetch:'#FF6F00',
  playwright:'#2EAD33', context7:'#FF6B35', meta:'#0668E1',
};

NALLY.SVC_ICONS = {};

NALLY.getConnected = function() {
  try { return JSON.parse(localStorage.getItem(NALLY.SVC_KEY) || '{}'); }
  catch(e) { return {}; }
};
NALLY.saveConnected = function(obj) { localStorage.setItem(NALLY.SVC_KEY, JSON.stringify(obj)); };

NALLY.findSvc = function(id) { return NALLY.SERVICES.find(function(s){ return s.id === id; }); };
NALLY.backendId = function(id) { var s = NALLY.findSvc(id); return (s && s.backendId) ? s.backendId : id; };

NALLY.renderServices = function() {
  var connected = NALLY.getConnected();
  var grid = NALLY.dom.svcGrid;
  if (!grid) return;
  grid.innerHTML = NALLY.SERVICES.map(function(s) {
    var c = connected[s.id];
    var color = NALLY.SVC_COLORS[s.id] || '#888';
    var isLight = s.lightIcon;
    var bg = isLight ? 'rgba(255,255,255,0.9)' : color;
    var fg = isLight ? '#000' : '#fff';
    var svg = NALLY.SVC_ICONS[s.id] || '';
    var styledSvg = svg.replace('<svg', '<svg style="width:14px;height:14px;color:' + fg + '"');
    var badge = '';
    if (!s.mcp) {
      badge = '<span class="svc-badge coming-soon">Soon</span>';
    } else if (c) {
      badge = '<span class="svc-badge connected">Connected</span>';
    } else {
      badge = '<span class="svc-badge">Connect</span>';
    }
    var click = s.mcp ? 'NALLY.connectService(\'' + s.id + '\')' : '';
    var cls = 'svc-card' + (c ? ' connected' : '') + (!s.mcp ? ' coming-soon-card' : '');
    return '<div class="' + cls + '" data-svc="' + s.id + '" onclick="' + click + '">'
      + '<div class="svc-icon" style="background:' + bg + '">' + styledSvg + '</div>'
      + '<span class="svc-name">' + s.name + '</span>'
      + badge
      + (s.mcp ? '<button class="svc-disconnect" onclick="event.stopPropagation();NALLY.disconnectSvc(\'' + s.id + '\')">&times;</button>' : '')
      + '</div>';
  }).join('');
};

NALLY.connectService = function(id) {
  var svc = NALLY.findSvc(id);
  if (!svc || !svc.mcp) return;
  var connected = NALLY.getConnected();
  if (connected[id]) return;

  if (svc.auth === 'none') {
    connected[id] = { at: Date.now() };
    NALLY.saveConnected(connected);
    NALLY.renderServices();
    return;
  }
  if (svc.auth === 'oauth') {
    NALLY.showAuthModal(svc, 'oauth');
  } else {
    NALLY.showAuthModal(svc, 'token');
  }
};

NALLY.disconnectSvc = function(id) {
  var connected = NALLY.getConnected();
  delete connected[id];
  NALLY.saveConnected(connected);
  fetch(NALLY.API + '/api/mcp/disconnect/' + NALLY.backendId(id), {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + NALLY.state.token }
  }).catch(function(){});
  NALLY.renderServices();
};
