window.NALLY = window.NALLY || {};

// Same origin so login/API work on localhost and production (e.g. Render)
NALLY.API = window.location.origin;
NALLY.STORAGE_KEY = 'nally-token';
NALLY.THEME_KEY = 'nally-theme';
NALLY.COMPACT_KEY = 'nally-compact';
NALLY.LOCK_KEY = 'nally-lock';
NALLY.SVC_KEY = 'nally-svc';